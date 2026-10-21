"""Past-only scenario capacity warnings and bounded adaptive release replay.

A research policy, not an order-book fill model or calibrated probability model.
"""
from decimal import Decimal, ROUND_FLOOR
from numbers import Real, Integral
import math
import numpy as np
from execution_volume_validation.forecasting import order_quantity
from execution_volume_validation.replay import price_diagnostic

POLICIES=('fixed_twap','fixed_volume','adaptive')
CHECKPOINTS=(0,12,39,60,77)


def _rate(rate):
    if isinstance(rate,(bool,np.bool_)) or not isinstance(rate,Real) or not math.isfinite(rate) or not 0<rate<=1:
        raise ValueError('participation rate must be finite in (0,1]')


def _volumes(values):
    raw=np.asarray(values,dtype=object)
    if any(isinstance(v,(bool,np.bool_)) or not isinstance(v,Real) for v in raw.flat):
        raise ValueError('volumes must be numeric and not boolean')
    v=np.asarray(values,dtype=float)
    if not np.isfinite(v).all() or np.any(v<0) or np.any(v>1e12) or np.any(v!=np.floor(v)):
        raise ValueError('volumes must be finite nonnegative integers at most 1e12 per bar')
    return v


def capacities(volumes,rate):
    _rate(rate)
    return np.array([int((Decimal(str(rate))*Decimal(str(v))).to_integral_value(rounding=ROUND_FLOOR))
                     for v in volumes],dtype=np.int64)


def allocate(quantity,weights):
    weights=np.asarray(weights,dtype=float)
    if weights.ndim!=1 or not len(weights) or not np.isfinite(weights).all() or np.any(weights<0):
        raise ValueError('finite nonnegative allocation weights required')
    weights=weights if weights.sum()>0 else np.ones(len(weights))
    target=quantity*weights/weights.sum();out=np.floor(target).astype(np.int64)
    left=quantity-int(out.sum())
    out[np.argsort(-(target-out),kind='stable')[:left]]+=1
    if int(out.sum())!=quantity:raise ArithmeticError('allocation did not conserve quantity')
    return out


def forecast(history_volumes,observed_prefix,rate):
    _rate(rate);h=_volumes(history_volumes);prefix=_volumes(observed_prefix)
    if h.ndim!=2 or h.shape[1]!=78 or not 2<=len(h)<=20 or prefix.ndim!=1 or len(prefix)>=78:
        raise ValueError('2 to 20 historical 78-bar sessions and an observed prefix shorter than 78 required')
    if np.any(h.sum(axis=1)<=0):raise ValueError('historical daily volume must be positive')
    t=len(prefix);prior=float(h.sum(axis=1).mean()/78*3)
    scale=(float(prefix.sum())+prior)/(h[:,:t].sum(axis=1)+prior)
    scenarios=h[:,t:]*scale[:,None]
    # Forecast capacities are approximate; realized integer caps use Decimal below.
    caps=np.floor(scenarios*rate).astype(np.int64);total=caps.sum(axis=1)
    low,median,high=np.quantile(total,[.1,.5,.9])
    return {'scenario_caps':caps,'median_volume':np.median(scenarios,axis=0),
            'capacity_p10':float(low),'capacity_p50':float(median),'capacity_p90':float(high),
            'scenario_count':len(h)}


def _simulate(releases,caps):
    released=executed=0;fills=[]
    for request,cap in zip(releases,caps):
        released+=int(request);fill=min(released-executed,int(cap));executed+=fill;fills.append(fill)
    return np.array(fills,dtype=np.int64)


def decision(history_volumes,observed_prefix,remaining,rate):
    if isinstance(remaining,(bool,np.bool_)) or not isinstance(remaining,Integral) or not 0<=remaining<=10_000_000:
        raise ValueError('remaining quantity must be an integer from 0 to 10 million')
    f=forecast(history_volumes,observed_prefix,rate);caps=f.pop('scenario_caps');weights=f.pop('median_volume')
    nominal=int(allocate(remaining,weights)[0])
    reserve=float(np.quantile(caps[:,1:].sum(axis=1),.1))
    needed=max(0,math.ceil(remaining-reserve));request=min(remaining,max(nominal,needed))
    continuation=np.r_[request,allocate(remaining-request,weights[1:])] if len(weights)>1 else np.array([remaining])
    cover=float(np.mean(caps.sum(axis=1)>=remaining))
    complete=float(np.mean([int(_simulate(continuation,c).sum())>=remaining for c in caps]))
    return {**f,'remaining_before':int(remaining),'nominal':nominal,'required_now':int(min(remaining,needed)),'request':int(request),
            'capacity_cover_share':cover,'continuation_completion_share':complete,
            'risk':'shortfall' if cover==0 else ('warning' if cover<.9 else 'normal'),
            'accelerated':request>nominal,'continuation':continuation.tolist()}


def replay_day(history_volumes,target_volume,quantity,rate,*,prices=None,arrival_price=100.,impact=1e-5):
    if isinstance(quantity,(bool,np.bool_)) or not isinstance(quantity,Integral) or not 1<=quantity<=10_000_000:
        raise ValueError('order quantity must be an integer from 1 to 10 million')
    _rate(rate);history=_volumes(history_volumes);actual=_volumes(target_volume)
    if actual.shape!=(78,):raise ValueError('target day needs 78 bars')
    forecast(history,np.array([],dtype=int),rate)
    caps=capacities(actual,rate);prices=np.full(78,100.) if prices is None else np.asarray(prices,dtype=float)
    releases={'fixed_twap':allocate(quantity,np.ones(78)),
              'fixed_volume':allocate(quantity,history.mean(axis=0))}
    fills={name:_simulate(q,caps) for name,q in releases.items()}
    dynamic=[];trace=[];checks=[];brier=[];covered=[];remaining=int(quantity)
    for t in range(78):
        # Neither current-bar liquidity nor any future bar is passed to decision().
        d=decision(history,actual[:t],remaining,rate);d.pop('continuation')
        d['interval']=t;d['minute']=t*5
        fill=min(d['request'],int(caps[t]));dynamic.append(fill);remaining-=fill
        d.update(filled=fill,remaining_after=remaining);trace.append(d)
        truth=int(caps[t:].sum());hit=d['capacity_p10']<=truth<=d['capacity_p90'];covered.append(hit)
        if d['remaining_before']>0:brier.append((d['capacity_cover_share']-int(truth>=d['remaining_before']))**2)
        if t in CHECKPOINTS:checks.append({'interval':t,'covered':bool(hit),'actual_remaining_capacity':truth,
                                          'capacity_p10':d['capacity_p10'],'capacity_p90':d['capacity_p90']})
    fills['adaptive']=np.array(dynamic,dtype=np.int64);strategies={}
    for name,f in fills.items():
        residual=quantity-int(f.sum());diag=price_diagnostic(quantity,arrival_price,f,prices,impact,5.)
        strategies[name]={'fills':f.tolist(),'remaining':(quantity-np.r_[0,np.cumsum(f)]).tolist(),
                          'complete':residual==0,'residual':residual,'completion_fraction':float(f.sum()/quantity),
                          'first_capacity_warning':next((x['interval'] for x in trace if x['remaining_before']>0 and x['risk']!='normal'),None) if name=='adaptive' else None,
                          'accelerated_bars':sum(x['accelerated'] for x in trace) if name=='adaptive' else 0,**diag}
    return {'strategies':strategies,'trace':trace,'calibration':{'checkpoints':checks,
            'band_hits':sum(covered),'band_count':len(covered),'capacity_cover_brier_sum':float(sum(brier)),
            'capacity_cover_brier_count':len(brier)}}


def run_study(days,config):
    lookback=config['lookback'];evaluation=config['evaluation_days'];rate=config['participation_rate'];_rate(rate)
    if (isinstance(lookback,bool) or not isinstance(lookback,int) or not 2<=lookback<=20
        or isinstance(evaluation,bool) or not isinstance(evaluation,int) or not 1<=evaluation<=60):
        raise ValueError('lookback2..20 and evaluation_days1..60 required')
    if len(days)<=lookback:raise ValueError('not enough complete historical sessions')
    if len({d.symbol for d in days})!=1 or [d.day for d in days]!=sorted({d.day for d in days}):
        raise ValueError('strict chronological sessions for one symbol required')
    selected=days[-(lookback+evaluation):];records=[];daily=[]
    for i in range(lookback,len(selected)):
        target=selected[i];history=selected[i-lookback:i];volumes=np.array([d.volume for d in history])
        quantity=order_quantity(float(volumes.sum(axis=1).mean()),config['fraction'])
        r=replay_day(volumes,target.volume,quantity,rate,prices=target.close,arrival_price=target.open_price)
        train=[d.day.isoformat() for d in history];day=target.day.isoformat()
        daily.append({'date':day,'train_dates':train,'quantity':quantity,'trace':r['trace'],'calibration':r['calibration']})
        for planner,s in r['strategies'].items():records.append({'symbol':target.symbol,'date':day,'train_dates':train,
                                                                'quantity':quantity,'planner':planner,**s})
    common=[d['date'] for d in daily if all(r['complete'] for r in records if r['date']==d['date'])]
    strategies=[]
    for planner in POLICIES:
        rows=[r for r in records if r['planner']==planner];paired=[r for r in rows if r['date'] in common]
        strategies.append({'planner':planner,'dates':len(rows),'cases':len(rows),'completed':sum(r['complete'] for r in rows),
            'mean_residual':float(np.mean([r['residual'] for r in rows])),
            'mean_marked_bps':float(np.mean([r['marked_total_bps'] for r in rows])),
            'mean_assumed_impact':float(np.mean([r['assumed_impact'] for r in rows])),
            'common_complete_count':len(paired),
            'common_complete_mean_marked_bps':float(np.mean([r['marked_total_bps'] for r in paired])) if paired else None})
    checkpoints=[{'interval':t,'dates':len(daily),'covered_dates':sum(next(c['covered'] for c in d['calibration']['checkpoints'] if c['interval']==t) for d in daily)} for t in CHECKPOINTS]
    hits=sum(d['calibration']['band_hits'] for d in daily);count=sum(d['calibration']['band_count'] for d in daily)
    bc=sum(d['calibration']['capacity_cover_brier_count'] for d in daily)
    calibration={'band_hits':hits,'band_count':count,'band_coverage':hits/count,'checkpoints':checkpoints,
                 'capacity_cover_brier':sum(d['calibration']['capacity_cover_brier_sum'] for d in daily)/bc if bc else None,
                 'active_decisions':bc,'independent_date_count':len(daily)}
    summary={'available_sessions':len(days),'training_window':lookback,'evaluation_days':len(daily),
             'evaluation_start':daily[0]['date'],'evaluation_end':daily[-1]['date'],'cases':len(records),
             'completed':sum(r['complete'] for r in records),'strategies':strategies,'common_complete_dates':common,
             'calibration':calibration}
    return {'adaptive_schema':'1.0','title':'Adaptive completion-risk capacity replay','design':dict(config),
            'symbol':days[0].symbol,'records':records,'daily':daily,'dashboard_summary':summary,'calibration':calibration,
            'method':{'prior_bars':3,'tail_capacity_quantile':.1,'warning_threshold':.9,
                      'scenario_interpretation':'Historical scenario fractions, not calibrated completion probabilities',
                      'cost_interpretation':'Assumed interval-close marks and fixed impact; residual marking is not a fill',
                      'fill_interpretation':'Aggregate retrospective capacity; adaptive unfilled requests replanned next bar, no order book or cancel costs'}}
