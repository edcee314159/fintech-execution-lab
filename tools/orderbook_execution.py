"""Seeded synthetic queue/depth/latency research; not historical L2 reconstruction."""
from decimal import Decimal,ROUND_FLOOR
import math
import numpy as np
SCENARIOS=('balanced','thin','adverse')
POLICIES=('passive','aggressive','dynamic')


def options(payload):
    required={'scenario','quantity','seed','participation_rate','latency_ticks'}
    if not isinstance(payload,dict) or set(payload)!=required:raise ValueError('scenario, quantity, seed, participation_rate, latency_ticks required')
    if payload['scenario'] not in SCENARIOS:raise ValueError('unknown artificial market scenario')
    for key,lo,hi in [('quantity',1,100000),('seed',0,2**32-1),('latency_ticks',1,5)]:
        v=payload[key]
        if isinstance(v,bool) or not isinstance(v,int) or not lo<=v<=hi:raise ValueError(key+' outside supported range')
    r=payload['participation_rate']
    if isinstance(r,bool) or not isinstance(r,(int,float)) or not math.isfinite(r) or not .01<=r<=.25:raise ValueError('participation_rate must be .01..25')
    return dict(payload)


def generate_events(scenario='balanced',seed=7,count=240):
    if scenario not in SCENARIOS or isinstance(seed,bool) or not isinstance(seed,int) or not 0<=seed<=2**32-1 or count!=240:
        raise ValueError('supported scenario/seed and 240 ticks required')
    rng=np.random.default_rng(seed);events=[];center=10000;last_imbalance=0
    for t in range(count):
        move=int(rng.choice([-1,0,1],p=[.2,.6,.2]))
        if scenario=='adverse' and last_imbalance>40:move+=1
        center+=move;spread=int(rng.choice([1,2,3]));thin=scenario=='thin'
        buy=int(rng.poisson(35 if thin else 70));sell=int(rng.poisson(35 if thin else 70))
        if thin and 80<=t<120:buy=sell=0
        if scenario=='adverse' and t%30<5:buy+=100
        depth=rng.integers(5 if thin else 30,25 if thin else 120,size=3).tolist()
        events.append({'bid_cents':center,'ask_cents':center+spread,'bid_depths':depth,
            'ask_depth':int(rng.integers(100,300) if thin else rng.integers(20,120)),
            'buy_volume':buy,'sell_volume':sell,'cancel_front':int(rng.integers(0,5))})
        last_imbalance=buy-sell
    return events


def _validate(events,quantity,rate,policy,latency):
    if isinstance(quantity,bool) or not isinstance(quantity,int) or not 1<=quantity<=100000:raise ValueError('quantity1..100000 required')
    if policy not in POLICIES or isinstance(latency,bool) or not isinstance(latency,int) or not 1<=latency<=5:raise ValueError('unknown policy or latency1..5 required')
    if isinstance(rate,bool) or not isinstance(rate,(int,float)) or not math.isfinite(rate) or not 0<rate<=1:raise ValueError('participation rate in (0,1] required')
    if not isinstance(events,list) or not 2<=len(events)<=1000:raise ValueError('2..1000 market events required')
    for e in events:
        keys={'bid_cents','ask_cents','bid_depths','ask_depth','buy_volume','sell_volume','cancel_front'}
        if not isinstance(e,dict) or set(e)!=keys:raise ValueError('invalid event schema')
        if not isinstance(e['bid_depths'],list) or len(e['bid_depths'])!=3:raise ValueError('three bid depth levels required')
        nums=[e[k] for k in keys-{'bid_depths'}]+e['bid_depths']
        if any(isinstance(v,bool) or not isinstance(v,int) or not 0<=v<=10**9 for v in nums):raise ValueError('nonnegative integer market fields required')
        if not 3<=e['bid_cents']<e['ask_cents']:raise ValueError('positive uncrossed bid/ask required')


def choose_action(policy,state):
    if state['remaining']==0 or state['pending'] or state['ticks_left']<=state['latency']:return None,'wait_for_pending_or_deadline'
    active=state['active'];remaining=state['remaining'];steps=max(1,state['ticks_left']-state['latency'])
    opportunities=max(1,(state['ticks_left']-1)//state['latency'])
    child=min(remaining,max(1,math.ceil(remaining/opportunities)))
    action='limit' if policy=='passive' else 'market';reason='fixed_policy'
    if policy=='dynamic':
        capacity=state['mean_volume']*state['rate']*steps
        urgency=remaining/max(1.,capacity)
        wait=(state['ask_depth']+child)/max(1.,state['mean_buy'])
        behind=state['executed']<state['quantity']*(state['tick']+1)/state['count']-.05*state['quantity']
        action='market' if urgency>.7 or behind or state['trend_cents']<0 or wait>min(10,steps*.1) else 'limit'
        reason='deadline_or_queue_or_falling_price' if action=='market' else 'wait_for_spread'
        child=min(remaining,max(child,math.ceil(state['mean_volume']*state['rate']*.8)))
    if action=='limit':
        if active and (active['price']==state['ask'] or state['tick']-active['submitted']<4):return None,'preserve_queue_priority'
        return {'type':'limit','quantity':remaining,'price':state['ask']},reason
    return {'type':'market','quantity':child,'price':None},reason


def replay(events,quantity,rate,policy,*,latency=1):
    _validate(events,quantity,rate,policy,latency)
    remaining=quantity;active=None;pending=[];fills=[];orders=[];trace=[];flow_history=[];buy_history=[];mids=[];counter=0
    def log(tick,order_id,status,**extra):orders.append({'tick':tick,'order_id':order_id,'status':status,**extra})
    for t,e in enumerate(events):
        cap=int((Decimal(str(rate))*Decimal(e['buy_volume']+e['sell_volume'])).to_integral_value(rounding=ROUND_FLOOR))
        used=0;depth=e['bid_depths'].copy();before=remaining;mid=(e['bid_cents']+e['ask_cents'])/2;mids.append(mid)
        def fill(q,price,liquidity,order_id,cancel_pending=False):
            nonlocal remaining,used
            q=min(int(q),remaining,cap-used)
            if q<=0:return 0
            remaining-=q;used+=q
            fills.append({'tick':t,'order_id':order_id,'quantity':q,'price':price/100.,'liquidity':liquidity,
                          'cancel_pending':cancel_pending,'mid_cents':mid})
            log(t,order_id,'partial_fill' if remaining else 'parent_complete',quantity=q,price=price/100.,liquidity=liquidity)
            return q
        def market(q,order_id,cancel_pending=False,min_price=None):
            done=0
            for level in range(3):
                if min_price is not None and e['bid_cents']-level<min_price:break
                take=fill(min(q-done,depth[level]),e['bid_cents']-level,'taker',order_id,cancel_pending)
                depth[level]-=take;done+=take
                if done>=q or used>=cap or remaining==0:break
            return done
        # Old orders can fill before a delayed cancellation takes effect.
        if active and remaining:
            cancel_pending=bool(pending)
            if active['price']<=e['ask_cents']:
                active['ahead']=max(0,active['ahead']-e['cancel_front'])
                available=max(0,e['buy_volume']-active['ahead']);active['ahead']=max(0,active['ahead']-e['buy_volume'])
                done=fill(min(active['quantity'],available),active['price'],'maker',active['id'],cancel_pending)
            else:done=0
            active['quantity']-=done
            if active['quantity']==0:log(t,active['id'],'filled');active=None
        arrivals=[x for x in pending if x['arrival']<=t];pending=[x for x in pending if x['arrival']>t]
        for cmd in arrivals:
            if active:log(t,active['id'],'cancelled',remaining=active['quantity']);active=None
            q=min(cmd['quantity'],remaining);log(t,cmd['id'],'activated',quantity=q)
            if not q:log(t,cmd['id'],'no_op_parent_complete');continue
            if cmd['type']=='market':
                done=market(q,cmd['id']);log(t,cmd['id'],'filled' if done==q else 'ioc_remainder_expired',unfilled=q-done)
            else:
                active={'id':cmd['id'],'price':cmd['price'],'quantity':q,
                        'ahead':e['ask_depth'] if cmd['price']>=e['ask_cents'] else 0,'submitted':cmd['submitted']}
                if active['price']<=e['bid_cents']:
                    active['quantity']-=market(active['quantity'],active['id'],min_price=active['price'])
                    if active['quantity']==0:log(t,active['id'],'filled');active=None
        flow_history.append(e['buy_volume']+e['sell_volume']);buy_history.append(e['buy_volume'])
        state={'remaining':remaining,'pending':bool(pending),'ticks_left':len(events)-t,'latency':latency,
               'active':active,'tick':t,'count':len(events),'quantity':quantity,'executed':quantity-remaining,
               'mean_volume':float(np.mean(flow_history[-20:])),'mean_buy':float(np.mean(buy_history[-20:])),
               'ask_depth':e['ask_depth'],'ask':e['ask_cents'],'rate':rate,'trend_cents':mid-mids[max(0,t-5)]}
        command,reason=choose_action(policy,state)
        if command:
            counter+=1;command.update(id=counter,submitted=t,arrival=t+latency);pending.append(command)
            log(t,counter,'submitted',action=command['type'],arrival=command['arrival'],quantity=command['quantity'])
            if active:log(t,active['id'],'cancel_requested',effective_tick=t+latency)
        trace.append({'tick':t,'remaining':remaining,'filled':before-remaining,'cap':cap,'mid':mid/100.,
            'queue_ahead':active['ahead'] if active else None,'resting_quantity':active['quantity'] if active else 0,
            'pending':len(pending),'command':command['type'] if command else 'hold',
            'command_quantity':command['quantity'] if command else 0,'reason':reason})
    if active:log(len(events),active['id'],'deadline_expired',remaining=active['quantity'])
    for cmd in pending:log(len(events),cmd['id'],'deadline_expired_before_arrival',unfilled=cmd['quantity'])
    arrival=(events[0]['bid_cents']+events[0]['ask_cents'])/200.;last=mids[-1]/100
    fees=sum(f['quantity']*(.0005 if f['liquidity']=='taker' else -.0001) for f in fills)
    executed=sum((arrival-f['price'])*f['quantity'] for f in fills);residual_mark=remaining*(arrival-last)
    eligible=[f for f in fills if f['tick']+10<len(events)]
    markout=sum((mids[f['tick']+10]-f['mid_cents'])/100*f['quantity'] for f in eligible)
    notional=sum(f['mid_cents']/100*f['quantity'] for f in eligible)
    return {'policy':policy,'quantity':quantity,'residual':remaining,'complete':remaining==0,'fills':fills,'orders':orders,'trace':trace,
            'executed_shares':quantity-remaining,'fees':fees,'executed_shortfall':executed,'residual_mark_shortfall':residual_mark,
            'marked_total_bps':(executed+residual_mark+fees)/(quantity*arrival)*10000,
            'maker_shares':sum(f['quantity'] for f in fills if f['liquidity']=='maker'),
            'taker_shares':sum(f['quantity'] for f in fills if f['liquidity']=='taker'),
            'cancel_count':sum(o['status']=='cancelled' for o in orders),
            'markout_eligible_shares':sum(f['quantity'] for f in eligible),
            'seller_adverse_mid_move_bps_10ticks':markout/notional*10000 if notional else None}


def run_study(config):
    config=options(config);events=generate_events(config['scenario'],config['seed'])
    policies={p:replay(events,config['quantity'],config['participation_rate'],p,latency=config['latency_ticks']) for p in POLICIES}
    common=all(r['complete'] for r in policies.values());strategies=[]
    for p,r in policies.items():
        strategies.append({'planner':p,'cases':1,'completed':int(r['complete']),'mean_residual':r['residual'],
            'maker_shares':r['maker_shares'],'taker_shares':r['taker_shares'],'cancel_count':r['cancel_count'],
            'fees':r['fees'],'marked_total_bps':r['marked_total_bps'],'common_complete_count':int(common),
            'common_complete_mean_marked_bps':r['marked_total_bps'] if common else None,
            'seller_adverse_mid_move_bps_10ticks':r['seller_adverse_mid_move_bps_10ticks'],
            'markout_eligible_shares':r['markout_eligible_shares']})
    return {'orderbook_schema':'1.0','data_kind':'synthetic_order_book','design':config,'events':events,'policies':policies,
            'dashboard_summary':{'scenario':config['scenario'],'seed':config['seed'],'quantity':config['quantity'],
                'ticks':len(events),'tick_seconds':1,'strategies':strategies},
            'method':{'data_source':'Artificial seeded exogenous quotes/flows, not real order-book data',
                'matching':'Single ask queue plus three bid levels; front cancellations known only in synthetic model; arrivals after existing-order matching',
                'participation':'Retrospective per-tick external-flow quota; not a live continuous participation limiter',
                'fees_per_share':{'maker':-.0001,'taker':.0005},'markout_horizon_ticks':10,
                'limitations':'No endogenous market impact, exchange validation, hidden liquidity or empirical calibration; residual marking is not a fill'}}
