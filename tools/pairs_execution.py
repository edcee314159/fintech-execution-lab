"""Cash-constrained two-asset execution under explicitly synthetic correlated markets."""
import math
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import numpy as np

POLICIES=('independent','coordinated')
TRIALS=32
LIMITS=('全部双资产行情、相关性、冲击和费用为人工假设，未接入真实行情或券商。'
        '卖出资金在同一分钟立即可用，不代表实际资金结算规则；不允许借款、做空或超过目标数量。'
        '决策只见当前价格和上一分钟及以前的成交量；实际成交按事后分钟成交量上限假设，非真实成交保证。'
        '协同先减少预测进度差超过目标的部分，再权衡成本、风险和进度；进度差目标不是实际硬上限。协同为有限候选单步启发式，不保证最优、完成或优于独立方案。'
        '协方差风险衡量相对目标组合的偏离，不等于实际损失；期末余量标记不算成交。'
        '独立与协同方案使用相同任务和人工市场；只有共同完成场景比较已成交全量缺口，所有失败保留。')

def options(payload):
    bounds={'sell_quantity':(1,100000,True),'buy_quantity':(1,100000,True),
            'sell_price':(1,10000,False),'buy_price':(1,10000,False),
            'initial_cash':(0,1000000000,False),'deadline':(4,120,True),
            'participation_rate':(.01,.25,False),'volatility_bps':(0,100,False),
            'correlation':(-1,1,False),'spread_bps':(0,100,False),'fee_bps':(0,100,False),
            'impact_bps':(0,500,False),'risk_weight':(0,20,False),'max_progress_gap':(0,1,False),'seed':(0,2**32-1,True)}
    if not isinstance(payload,dict) or set(payload)!=set(bounds)|{'scenario'}:
        raise ValueError('请完整提供双资产执行参数，不接受额外字段。')
    if payload['scenario'] not in ('balanced','buy_slow','sell_slow','dry'):
        raise ValueError('未知人工双资产情形。')
    for key,(lo,hi,integer) in bounds.items():
        v=payload[key]
        if (isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v)
                or not lo<=v<=hi or (integer and not isinstance(v,int))):
            raise ValueError(f'{key} 须在 {lo} 至 {hi} 之间'+('且为整数。' if integer else '。'))
    # Cash and quote precision must be explicit instead of silently discarding fractions of cents.
    for key in ('sell_price','buy_price','initial_cash'):
        if Decimal(str(payload[key]))*100 != (Decimal(str(payload[key]))*100).to_integral_value():
            raise ValueError(key+' 只支持两位小数。')
    return dict(payload)

def target_variance(sell_deviation,buy_deviation,sigma,correlation):
    a,b=sell_deviation,buy_deviation
    return max(0.,sigma*sigma*(a*a+b*b+2*correlation*a*b))

def generate_events(c,seed):
    rng=np.random.default_rng(seed);n=c['deadline'];sigma=c['volatility_bps']/10000
    z=rng.normal(size=(n,2));rho=c['correlation']
    returns=np.column_stack((z[:,0],rho*z[:,0]+math.sqrt(max(0.,1-rho*rho))*z[:,1]))*sigma-.5*sigma*sigma
    prices=np.maximum(100,np.rint(np.array([c['sell_price'],c['buy_price']])*100*np.exp(np.cumsum(returns,axis=0)))).astype(np.int64)
    events=[]
    for t in range(n):
        # Same expected volume per leg; asymmetry/interruptions explicit in scenario.
        vols=np.maximum(0,np.rint(rng.lognormal(math.log(1200)-.5*.25**2,.25,2))).astype(int)
        if t<int(.6*n):
            if c['scenario']=='buy_slow':vols[1]//=8
            if c['scenario']=='sell_slow':vols[0]//=8
        if c['scenario']=='dry':vols[:]=0
        events.append({'sell_mid_cents':int(prices[t,0]),'buy_mid_cents':int(prices[t,1]),
                       'sell_volume':int(vols[0]),'buy_volume':int(vols[1])})
    return events

def _ceil_money(value):
    return int(value.to_integral_value(rounding=ROUND_CEILING))

def charges(c,q,mid,volume):
    if q==0:return 0
    d=Decimal;notional=d(q)*d(mid)
    spread=notional*d(str(c['spread_bps']))/d(20000)
    fee=notional*d(str(c['fee_bps']))/d(10000)
    impact=notional*d(str(c['impact_bps']))/d(10000)*d(q)/d(max(1,volume))
    return _ceil_money(spread+fee+impact)

def _transact(c,sell_request,buy_request,sell_cap,buy_cap,remaining_a,remaining_b,cash,pa,pb,va,vb):
    qa=min(remaining_a,sell_request,sell_cap)
    proceeds=qa*pa-charges(c,qa,pa,va)
    available=cash+proceeds
    high=min(remaining_b,buy_request,buy_cap);low=0
    while low<high:
        q=(low+high+1)//2
        if q*pb+charges(c,q,pb,vb)<=available:low=q
        else:high=q-1
    qb=low;spend=qb*pb+charges(c,qb,pb,vb)
    return qa,qb,proceeds,spend,high

def _request(c,t,ra,rb,cash,pa,pb,past_a,past_b,policy):
    qa,qb=c['sell_quantity'],c['buy_quantity'];n=c['deadline']
    base_a=min(ra,max(0,math.ceil(qa*(t+1)/n)-(qa-ra)))
    base_b=min(rb,max(0,math.ceil(qb*(t+1)/n)-(qb-rb)))
    if policy=='independent' or c['risk_weight']==0:return base_a,base_b
    # Predict capacity solely from prior volume; the first minute uses an explicit prior.
    va=max(1,round(sum(past_a[-5:])/len(past_a[-5:]))) if past_a else 1200
    vb=max(1,round(sum(past_b[-5:])/len(past_b[-5:]))) if past_b else 1200
    ca=int(Decimal(va)*Decimal(str(c['participation_rate'])))
    cb=int(Decimal(vb)*Decimal(str(c['participation_rate'])))
    choices_a=sorted({0,min(ra,base_a),min(ra,ca),min(ra,max(base_a,math.ceil(ra/(n-t))*2))})
    choices_b=sorted({0,min(rb,base_b),min(rb,cb),min(rb,max(base_b,math.ceil(rb/(n-t))*2))})
    gap=c['max_progress_gap']
    choices_a=sorted(set(choices_a)|{min(ra,max(0,math.floor(ra-qa*rb/qb+qa*min(rb,base_b,cb)/qb+qa*gap)))})
    choices_b=sorted(set(choices_b)|{min(rb,max(0,math.floor(rb-qb*ra/qa+qb*min(ra,base_a,ca)/qa+qb*gap)))})
    scale=(qa*c['sell_price']+qb*c['buy_price']);target=1-(t+1)/n
    def score(a,b):
        sa,bb,proceeds,spend,_=_transact(c,a,b,ca,cb,ra,rb,cash,pa,pb,va,vb)
        left_a,left_b=ra-sa,rb-bb
        variance=target_variance(left_a*pa/100,-left_b*pb/100,c['volatility_bps']/10000,c['correlation'])
        direct=(sa*pa-proceeds+spend-bb*pb)/100
        tracking=.025*scale*(max(0,left_a/qa-target)**2+max(0,left_b/qb-target)**2)
        violation=max(0.,abs(left_a/qa-left_b/qb)-gap)
        # Forecast soft target: actual current-minute liquidity is still unknown.
        return (round(violation,12),direct+c['risk_weight']*math.sqrt(variance)+tracking)
    return min(((a,b) for a in choices_a for b in choices_b),key=lambda pair:(score(*pair),-sum(pair)))

def replay(payload,events,policy):
    c=options(payload)
    if policy not in POLICIES or not isinstance(events,list) or len(events)!=c['deadline']:
        raise ValueError('双资产方法或事件数量不正确。')
    fields={'sell_mid_cents','buy_mid_cents','sell_volume','buy_volume'}
    for event in events:
        if (not isinstance(event,dict) or set(event)!=fields or
                any(isinstance(v,bool) or not isinstance(v,int) or not 0<=v<=10**12 for v in event.values()) or
                min(event['sell_mid_cents'],event['buy_mid_cents'])<100):
            raise ValueError('无效人工双资产事件。')
    ra,rb=c['sell_quantity'],c['buy_quantity'];cash=int(Decimal(str(c['initial_cash']))*100)
    past_a=[];past_b=[];trace=[];shortfall=0;cash_limited=0
    rate=Decimal(str(c['participation_rate']));sigma=c['volatility_bps']/10000
    pa0=int(Decimal(str(c['sell_price']))*100);pb0=int(Decimal(str(c['buy_price']))*100)
    for t,e in enumerate(events):
        pa,pb=e['sell_mid_cents'],e['buy_mid_cents'];va,vb=e['sell_volume'],e['buy_volume']
        request_a,request_b=_request(c,t,ra,rb,cash,pa,pb,past_a,past_b,policy)
        ca=int((Decimal(va)*rate).to_integral_value(rounding=ROUND_FLOOR))
        cb=int((Decimal(vb)*rate).to_integral_value(rounding=ROUND_FLOOR))
        affordable_demand=min(rb,request_b,cb)
        sa,bb,proceeds,spend,_=_transact(c,request_a,request_b,ca,cb,ra,rb,cash,pa,pb,va,vb)
        limited=bb<affordable_demand;cash_limited+=int(limited)
        cash+=proceeds-spend;ra-=sa;rb-=bb
        shortfall+=sa*pa0-proceeds+spend-bb*pb0
        risk=target_variance(ra*pa/100,-rb*pb/100,sigma,c['correlation'])
        trace.append({'minute':t+1,'sell_request':request_a,'buy_request':request_b,
                      'sell_filled':sa,'buy_filled':bb,'sell_capacity':ca,'buy_capacity':cb,
                      'sell_remaining':ra,'buy_remaining':rb,'sell_proceeds_cents':proceeds,
                      'buy_spend_cents':spend,'cash_cents':cash,'cash_limited':limited,
                      'risk_variance':risk,'risk_std':math.sqrt(risk),
                      'progress_gap':abs(ra/c['sell_quantity']-rb/c['buy_quantity']),
                      'net_target_deviation':(ra*pa-rb*pb)/100,
                      'sell_mid_cents':pa,'buy_mid_cents':pb})
        past_a.append(va);past_b.append(vb)
    denominator=c['sell_quantity']*pa0+c['buy_quantity']*pb0
    marked=shortfall+ra*(pa0-events[-1]['sell_mid_cents'])+rb*(events[-1]['buy_mid_cents']-pb0)
    return {'planner':policy,'complete':ra==0 and rb==0,'sell_remaining':ra,'buy_remaining':rb,
            'cash_cents':cash,'cash_limited_steps':cash_limited,'shortfall_cents':shortfall,
            'complete_shortfall_bps':shortfall/denominator*10000 if ra==rb==0 else None,
            'marked_shortfall_bps':marked/denominator*10000,
            'integrated_target_variance':sum(x['risk_variance'] for x in trace),
            'peak_target_risk_std':max(x['risk_std'] for x in trace),
            'max_progress_gap':max(x['progress_gap'] for x in trace),'trace':trace}

def run_study(payload):
    c=options(payload);records=[];policies=None;events=None
    # First scenario uses the entered seed for an easy-to-reproduce detailed replay.
    seeds=[c['seed']]+np.random.SeedSequence([c['seed'],117]).generate_state(TRIALS-1).tolist()
    for i,seed in enumerate(seeds):
        path=generate_events(c,seed)
        results={p:replay(c,path,p) for p in POLICIES}
        if i==0:policies=results;events=path
        records.append({'scenario_id':i,'seed':seed,'policies':{
            p:{k:v for k,v in row.items() if k!='trace'} for p,row in results.items()}})
    common=[r for r in records if all(p['complete'] for p in r['policies'].values())]
    strategies=[]
    for p in POLICIES:
        rows=[r['policies'][p] for r in records]
        mean=lambda key:float(np.mean([r[key] for r in rows]))
        strategies.append({'planner':p,'cases':TRIALS,'completed':sum(r['complete'] for r in rows),
            'mean_sell_remaining':mean('sell_remaining'),'mean_buy_remaining':mean('buy_remaining'),
            'mean_integrated_target_variance':mean('integrated_target_variance'),
            'mean_peak_target_risk_std':mean('peak_target_risk_std'),
            'mean_max_progress_gap':mean('max_progress_gap'),
            'mean_marked_bps_all':mean('marked_shortfall_bps'),
            'p95_marked_bps_all':float(np.quantile([r['marked_shortfall_bps'] for r in rows],.95)),
            'cash_limited_scenarios':sum(r['cash_limited_steps']>0 for r in rows),
            'common_complete_count':len(common),
            'common_complete_mean_bps':float(np.mean([r['policies'][p]['complete_shortfall_bps'] for r in common])) if common else None,
            'common_complete_p95_bps':float(np.quantile([r['policies'][p]['complete_shortfall_bps'] for r in common],.95)) if common else None})
    funding=c['initial_cash']+c['sell_quantity']*c['sell_price']<c['buy_quantity']*c['buy_price']
    return {'pairs_schema':'pairs-1.0','data_kind':'synthetic_two_asset_scenarios','design':c,
            'funding_warning':funding,'funding_note':'按起始中价的资金已不足。' if funding else '起始中价资金核对未发现不足；费用和价格变化仍可能造成不足。',
            'seeds':seeds,'events':events,'policies':policies,'records':records,
            'dashboard_summary':{'cases':TRIALS,'strategies':strategies,'common_complete_count':len(common)},
            'limitations':LIMITS}
