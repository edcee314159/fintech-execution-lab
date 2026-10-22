"""Synthetic pretrade cost/time trade-offs with independent validation scenarios."""
import math
from decimal import Decimal, ROUND_FLOOR
import numpy as np

TRIALS = 256
LIMITS = ('全部价格、成交量与费用为人工假设，不是实盘报价或已校准成本。预算是相对起始中价的到达价缺口；'
          '包含价格变动、半价差、手续费和临时冲击，允许有利价格变动产生负缺口。预算不是硬止损。'
          '规划和验证使用独立随机流，仍来自同一人工分布，不是市场样本外证据。'
          '未完成计入联合失败；条件成本只含完成路径，共同完成成本只在所有候选都完成的同一批路径比较。'
          '未找到达标候选仅限本次8个候选，不能证明其他方法不可行。')

def options(payload):
    bounds = {'quantity':(1,1000000,True),'price':(1,10000,False),'deadline':(4,120,True),
              'volume_per_minute':(1,10000000,True),'volatility_bps':(0,100,False),
              'spread_bps':(0,100,False),'fee_bps':(0,100,False),'impact_bps':(0,500,False),
              'participation_rate':(.01,.25,False),'budget_bps':(0,1000,False),
              'required_success':(.5,.99,False),'seed':(0,2**32-1,True)}
    if not isinstance(payload,dict) or set(payload)!=set(bounds):
        raise ValueError('请完整提供成本预算参数，不接受额外字段。')
    for key,(lo,hi,integer) in bounds.items():
        v=payload[key]
        if (isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v)
                or not lo<=v<=hi or (integer and not isinstance(v,int))):
            raise ValueError(f'{key} 须在 {lo} 至 {hi} 之间'+('且为整数。' if integer else '。'))
    return dict(payload)

def expected_volume(c):
    t=(np.arange(c['deadline'])+.5)/c['deadline']
    shape=.7+1.2*(2*t-1)**2
    return c['volume_per_minute']*shape/shape.mean()

def generate_paths(c,seed,count=TRIALS):
    rng=np.random.default_rng(seed);n=c['deadline'];sigma=c['volatility_bps']/10000
    mids=c['price']*np.exp(np.cumsum(rng.normal(-.5*sigma*sigma,sigma,(count,n)),axis=1))
    # Positive lognormal volume around an explicit deterministic expected profile.
    volumes=np.floor(expected_volume(c)[None,:]*np.exp(rng.normal(-.5*.6**2,.6,(count,n)))
                     *np.exp(rng.normal(-.5*.35**2,.35,(count,1)))).astype(np.int64)
    return {'mids':mids,'volumes':volumes}

def _schedule(c,horizon,pace):
    weights=np.ones(horizon) if pace=='uniform' else np.linspace(2.,.5,horizon)
    # Fixed before any realized market data; no use of the simulated future.
    cumulative=np.floor(c['quantity']*np.cumsum(weights)/weights.sum()+1e-9).astype(np.int64)
    cumulative[-1]=c['quantity']
    return cumulative

def replay(c,horizon,pace,paths):
    q=c['quantity'];count=len(paths['mids']);remaining=np.full(count,q,dtype=np.int64)
    cost=np.zeros(count);direct=np.zeros(count);trace=[];done_at=np.full(count,horizon,dtype=int)
    cumulative=_schedule(c,horizon,pace)
    rate=Decimal(str(c['participation_rate']))
    for t in range(horizon):
        released=cumulative[t];executed=q-remaining
        request=np.maximum(0,released-executed)
        vol=paths['volumes'][:,t]
        capacity=np.array([int((Decimal(int(v))*rate).to_integral_value(rounding=ROUND_FLOOR)) for v in vol])
        filled=np.minimum(request,capacity)
        mid=paths['mids'][:,t]
        spread=filled*mid*c['spread_bps']/20000
        fee=filled*mid*c['fee_bps']/10000
        impact=filled*mid*c['impact_bps']/10000*filled/np.maximum(1,vol)
        timing=filled*(c['price']-mid)
        step=spread+fee+impact+timing
        cost+=step;direct+=spread+fee+impact
        was_open=remaining>0;remaining-=filled
        done_at[was_open & (remaining==0)]=t+1
        trace.append({'minute':t+1,'request':int(request[0]),'capacity':int(capacity[0]),
                      'filled':int(filled[0]),'remaining':int(remaining[0]),
                      'spread_cost':float(spread[0]),'fee_cost':float(fee[0]),
                      'impact_cost':float(impact[0]),'timing_cost':float(timing[0])})
    complete=remaining==0;bps=cost/(q*c['price'])*10000
    success=complete & (bps<=c['budget_bps'])
    marked=cost+remaining*(c['price']-paths['mids'][:,horizon-1])
    summary={'trials':count,'completed':int(complete.sum()),'unfinished':int((~complete).sum()),
             'successes':int(success.sum()),'budget_breaches':int((complete & ~success).sum()),
             'joint_success_rate':float(success.mean()),'completion_rate':float(complete.mean()),
             'mean_complete_bps':float(bps[complete].mean()) if complete.any() else None,
             'p95_complete_bps':float(np.quantile(bps[complete],.95)) if complete.any() else None,
             'mean_remaining':float(remaining.mean()),
             'mean_direct_cost':float(direct.mean()),
             'mean_marked_bps_all':float(marked.mean()/(q*c['price'])*10000),
             'mean_completion_minutes':float(done_at[complete].mean()) if complete.any() else None}
    return {'summary':summary,'cost_bps':bps,'complete':complete,'trace':trace,
            'first_shortfall':float(cost[0])}

def select_candidate(rows,required_success):
    eligible=[r for r in rows if r['planning']['joint_success_rate']>=required_success]
    return min(eligible,key=lambda r:(r['horizon'],r['planning']['p95_complete_bps'],
                                     r['planning']['mean_complete_bps'],r['id']))['id'] if eligible else None

def run_study(payload):
    c=options(payload)
    seeds=np.random.SeedSequence(c['seed']).generate_state(2).tolist()
    if seeds[0]==seeds[1]:seeds[1]=(seeds[1]+1)%2**32
    planning=generate_paths(c,seeds[0]);validation=generate_paths(c,seeds[1])
    horizons=sorted({math.ceil(c['deadline']*part/4) for part in (1,2,3,4)})
    rows=[];results=[]
    for horizon in horizons:
        for pace in ('uniform','frontloaded'):
            a=replay(c,horizon,pace,planning);b=replay(c,horizon,pace,validation)
            rows.append({'id':f'{horizon}_{pace}','horizon':horizon,'pace':pace,
                         'planning':a['summary'],'validation':b['summary'],
                         'validation_trace':b['trace'],'validation_first_shortfall':b['first_shortfall']})
            results.append(b)
    common=np.logical_and.reduce([r['complete'] for r in results])
    for row,r in zip(rows,results):
        row['validation']['common_complete_count']=int(common.sum())
        row['validation']['common_complete_mean_bps']=float(r['cost_bps'][common].mean()) if common.any() else None
        row['validation']['common_complete_p95_bps']=float(np.quantile(r['cost_bps'][common],.95)) if common.any() else None
        x=row['planning']
        # Complete-path cost alone is not used to rank paths with different success.
        row['on_planning_frontier']=not any(
            other['horizon']<=row['horizon'] and
            other['planning']['joint_success_rate']>=x['joint_success_rate'] and
            (other['horizon']<row['horizon'] or other['planning']['joint_success_rate']>x['joint_success_rate'])
            for other in rows)
    selected=select_candidate(rows,c['required_success'])
    s={'candidates':len(rows),'selected_id':selected,'planning_trials':TRIALS,'validation_trials':TRIALS,
       'common_complete_count':int(common.sum()),'status':'candidate_selected' if selected else 'no_candidate_meets_target'}
    return {'budget_schema':'budget-1.0','data_kind':'synthetic_budget_scenarios','design':c,
            'planning_seed':seeds[0],'validation_seed':seeds[1],'status':s['status'],
            'selected_id':selected,'candidates':rows,'dashboard_summary':s,'limitations':LIMITS}
