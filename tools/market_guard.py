"""Quote/market-state gate and synthetic IOC replay; offline Nasdaq equity calendar 2026."""
from datetime import date,datetime,timedelta
from decimal import Decimal,ROUND_FLOOR
import math,random

CALENDAR_SOURCE='https://www.nasdaqtrader.com/trader.aspx?id=Calendar'
HOLIDAYS={'2026-01-01','2026-01-19','2026-02-16','2026-04-03','2026-05-25','2026-06-19',
          '2026-07-03','2026-09-07','2026-11-26','2026-12-25'}
EARLY_CLOSE={'2026-11-27','2026-12-24'}
SCENARIOS=('mixed','stale','halt','zero','gap','early_close')
LIMITS=('全部行情、状态与IOC成交为人工故障实验，不是真实交易所数据。状态来自独立人工状态通道；'
        '零成交量不推断停牌，只恢复报价不代表恢复交易。序列缺口或无效报价需要显式快照，快照完整性在本模型中是假设。'
        '该门控只控制本实验的新IOC子单，不会撤销其他模块或真实账户的已有挂单；撤单在途风险由订单恢复实验单独检验。'
        '日历仅覆盖2026年Nasdaq股票常规时段，纽约本地时间，不覆盖临时闭市、其他交易所、盘前盘后或其他年份；未知年份停止。'
        '原有CSV上传与冻结研究仍沿用原来的390分钟规则，此功能没有悄悄修复或扩充历史数据。'
        '无状态检查对照故意缺少保护，不用于证明成本、收益或实盘安全优势。')

def integer(v,lo=0,hi=10**12):
    if isinstance(v,bool) or not isinstance(v,int) or not lo<=v<=hi:raise ValueError('无效整数参数。')
    return v
def session_bounds(text):
    try:d=date.fromisoformat(text)
    except (ValueError,TypeError):raise ValueError('交易日期须为 YYYY-MM-DD。') from None
    if d.isoformat()!=text or d.year!=2026:raise ValueError('当前离线日历仅支持2026年。')
    if d.weekday()>4 or text in HOLIDAYS:return None
    return 570,780 if text in EARLY_CLOSE else 960

def options(p):
    keys={'quantity','scenario','seed','stale_after','recovery_ticks','max_child','participation_rate','session_date'}
    if not isinstance(p,dict) or set(p)!=keys:raise ValueError('请完整提供异常行情实验参数。')
    for k,lo,hi in [('quantity',1,100000),('seed',0,2**32-1),('stale_after',1,10),('recovery_ticks',1,20),('max_child',1,1000)]:
        integer(p[k],lo,hi)
    if p['scenario'] not in SCENARIOS:raise ValueError('未知人工行情情形。')
    r=p['participation_rate']
    if isinstance(r,bool) or not isinstance(r,(int,float)) or not math.isfinite(r) or not .01<=r<=.25:raise ValueError('参与率须在1%至25%之间。')
    bounds=session_bounds(p['session_date'])
    if p['scenario']=='early_close' and (not bounds or bounds[1]!=780):raise ValueError('提前收盘情形请选择2026-11-27或2026-12-24。')
    return dict(p)

class MarketGuard:
    def __init__(self,stale_after=3,recovery_ticks=5):
        integer(stale_after,1,10);integer(recovery_ticks,1,20)
        self.stale_after=stale_after;self.recovery_ticks=recovery_ticks
        self.quote=None;self.status='unknown';self.status_seq=-1;self.tick=-1
        self.gap=False;self.invalid=False;self.healthy=0;self.rejected=0
    def update(self,e):
        t=integer(e['tick'])
        if t<=self.tick:raise ValueError('接收时钟必须严格增加。')
        self.tick=t;accepted=False;reason=''
        st=e['status']
        if st is not None:
            if (not isinstance(st,dict) or set(st)!={'seq','state'} or
                isinstance(st['seq'],bool) or not isinstance(st['seq'],int) or st['seq']<0 or
                st['state'] not in ('trading','halted','quote_only','unknown')):
                self.status='unknown';reason='无效交易状态消息'
            elif st['seq']>self.status_seq:self.status=st['state'];self.status_seq=st['seq']
            elif st['seq']==self.status_seq and st['state']!=self.status:
                self.status='unknown';reason='同一状态序号内容冲突'
        q=e['quote']
        if q is not None:
            valid=isinstance(q,dict) and set(q)=={'seq','source_tick','bid','ask','resync'}
            if valid:
                try:
                    for k in ('seq','source_tick','bid','ask'):integer(q[k])
                    valid=0<q['bid']<q['ask'] and q['source_tick']<=t and isinstance(q['resync'],bool)
                except ValueError:valid=False
            if not valid:self.invalid=True;self.rejected+=1;reason='报价无效、交叉或时间来自未来'
            elif self.quote is not None and q['seq']<=self.quote['seq']:
                self.rejected+=1
                if q['seq']==self.quote['seq'] and q!=self.quote:self.invalid=True;reason='同一报价序号内容冲突'
            elif self.quote is not None and q['source_tick']<self.quote['source_tick']:
                self.invalid=True;self.rejected+=1;reason='报价源时间逆序'
            else:
                if self.quote is not None and q['seq']!=self.quote['seq']+1:self.gap=True
                if q['resync']:self.gap=False;self.invalid=False
                self.quote=dict(q);accepted=True
        volume=e['observed_volume']
        volume_ok=not isinstance(volume,bool) and isinstance(volume,int) and 0<=volume<=10**12
        age=t-self.quote['source_tick'] if self.quote is not None else None
        if e['session_open'] is not True:state='closed'
        elif self.status=='unknown':state='status_unknown'
        elif self.status=='halted':state='halted'
        elif self.status=='quote_only':state='quote_only'
        elif self.invalid:state='invalid_data'
        elif self.gap:state='feed_gap'
        elif age is None or age>self.stale_after:state='stale_data'
        elif not volume_ok:state='volume_unknown'
        else:state='eligible'
        if state!='eligible':
            self.healthy=0;allow=False;ramp=0.
        else:
            if accepted:self.healthy+=1
            ramp=min(1.,max(0.,(self.healthy-2)/self.recovery_ticks))
            allow=ramp>0;state='normal' if ramp==1 else 'recovering'
        return {'state':state,'allow':allow,'ramp':ramp,'quote_age':age,'accepted_update':accepted,
                'healthy_updates':self.healthy,'reason':reason,'rejected_messages':self.rejected}

def generate_events(payload):
    c=options(payload);rng=random.Random(c['seed']);bounds=session_bounds(c['session_date'])
    start=(bounds[1]-1.5) if c['scenario']=='early_close' else 570
    # Early-close demonstration starts 90 seconds before the scheduled close.
    start=datetime.fromisoformat(c['session_date'])+timedelta(minutes=start)
    events=[];bid=10000;scenario=c['scenario']
    for t in range(240):
        bid=max(100,bid+rng.choice([-1,0,0,0,1]));volume=rng.randint(200,600)
        status=None;halt=False;quote_only=False
        if t==0:status={'seq':1,'state':'trading'}
        if scenario in ('mixed','halt'):
            halt=140<=t<165;quote_only=155<=t<165
            if t==140:status={'seq':2,'state':'halted'}
            if t==155:status={'seq':3,'state':'quote_only'}
            if t==165:status={'seq':4,'state':'trading'}
        zero=scenario=='zero' and 40<=t<80
        if zero:volume=0
        quote={'seq':t+1,'source_tick':t,'bid':bid,'ask':bid+2,'resync':False}
        observed=volume
        if scenario in ('mixed','stale') and 40<=t<70:quote=None
        if scenario in ('mixed','stale') and t==71:quote['resync']=True
        if scenario in ('mixed','gap') and 90<=t<100:
            if t==90:quote=None
            if t==99:quote['resync']=True
        if scenario=='mixed' and t==110:quote['bid']=bid+5
        if scenario=='mixed' and t==111:quote['resync']=True
        if scenario=='mixed' and 120<=t<125:observed=None
        stamp=start+timedelta(seconds=t);minute=stamp.hour*60+stamp.minute+stamp.second/60
        opened=bounds is not None and bounds[0]<=minute<bounds[1]
        events.append({'tick':t,'timestamp':stamp.isoformat(sep=' '),'quote':quote,'status':status,
                       'observed_volume':observed,'session_open':opened,'truth_volume':volume,
                       'truth_bid':bid,'actual_halted':halt,'actual_quote_only':quote_only})
    return events

def replay(payload,events,policy):
    c=options(payload)
    if policy not in ('unchecked','guarded') or not isinstance(events,list) or len(events)!=240:raise ValueError('未知保护方案或事件数量。')
    remaining=c['quantity'];g=MarketGuard(c['stale_after'],c['recovery_ticks']);trace=[];past_volume=400
    rate=Decimal(str(c['participation_rate']));unsafe=0;quote_only_attempts=0;large=0
    for t,e in enumerate(events):
        gate=g.update(e)
        released=math.ceil(c['quantity']*(t+1)/len(events))
        demand=max(0,released-(c['quantity']-remaining))
        if policy=='guarded':
            maximum=math.floor(c['max_child']*gate['ramp'])
            forecast=int((Decimal(past_volume)*rate).to_integral_value(rounding=ROUND_FLOOR))
            request=min(remaining,demand,maximum,forecast) if gate['allow'] else 0
        else:request=min(remaining,demand)
        cap=int((Decimal(integer(e['truth_volume']))*rate).to_integral_value(rounding=ROUND_FLOOR))
        physical=e['session_open'] and not e['actual_halted'] and not e['actual_quote_only']
        filled=min(request,cap) if physical else 0;remaining-=filled
        blocked=not gate['allow'];unsafe+=int(request>0 and blocked)
        quote_only_attempts+=int(request>0 and e['actual_quote_only']);large+=int(request>c['max_child'])
        trace.append({'tick':t,'timestamp':e['timestamp'],'state':gate['state'],'ramp':gate['ramp'],
            'request':request,'filled':filled,'capacity':cap if physical else 0,'remaining':remaining,
            'quote_age':gate['quote_age'],'guard_would_block':blocked,'reason':gate['reason'],
            'actual_halted':e['actual_halted'],'actual_quote_only':e['actual_quote_only'],
            'session_open':e['session_open'],'rejected_messages':gate['rejected_messages']})
        observed=e['observed_volume']
        if isinstance(observed,int) and not isinstance(observed,bool) and observed>=0:past_volume=observed
    return {'planner':policy,'residual':remaining,'complete':remaining==0,'filled':c['quantity']-remaining,
            'unsafe_attempts':unsafe,'quote_only_attempts':quote_only_attempts,'oversized_attempts':large,
            'peak_child_request':max(x['request'] for x in trace),'trace':trace}

def run_study(payload):
    c=options(payload);events=generate_events(c);policies={p:replay(c,events,p) for p in ('unchecked','guarded')}
    return {'marketguard_schema':'marketguard-1.0','data_kind':'synthetic_market_state_faults','design':c,
            'events':events,'policies':policies,'calendar':{'year':2026,'source':CALENDAR_SOURCE,
                'checked_date':'2026-10-23','timezone':'America/New_York (local wall-clock timestamps)',
                'session_minutes':session_bounds(c['session_date'])},
            'dashboard_summary':{'quantity':c['quantity'],'scenario':c['scenario'],'ticks':240,
                'strategies':[{k:v for k,v in r.items() if k!='trace'} for r in policies.values()]},
            'limitations':LIMITS}
