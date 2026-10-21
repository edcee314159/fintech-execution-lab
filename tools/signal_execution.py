"""Chronological ridge signal with historical validation weight and execution controls."""
from pathlib import Path
import importlib.util,math
import numpy as np
from execution_volume_validation.forecasting import order_quantity
from execution_volume_validation.replay import price_diagnostic
_spec=importlib.util.spec_from_file_location('signal_capacity_engine',Path(__file__).with_name('adaptive_execution.py'))
capacity=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(capacity)
POLICIES=('capacity','always','trusted')
SCENARIOS=('learned','zero','inverted')


def _returns(day):
    prices=np.r_[day.open_price,np.asarray(day.close,dtype=float)]
    if len(prices)!=79 or not np.isfinite(prices).all() or np.any(prices<=0):raise ValueError('78 positive finite closes and opening price required')
    r=prices[1:]/prices[:-1]-1
    if not np.isfinite(r).all():raise ValueError('nonfinite returns')
    return r


def _samples(days):
    xs=[];ys=[]
    for day in days:
        r=_returns(day)
        for t in range(3,78):xs.append([r[t-1],float(r[t-3:t].mean())]);ys.append(r[t])
    return np.array(xs,dtype=float),np.array(ys,dtype=float)


def _fit(days):
    x,y=_samples(days);center=x.mean(axis=0);scale=x.std(axis=0);scale=np.where(scale>1e-12,scale,1.)
    z=np.column_stack([np.ones(len(x)),(x-center)/scale]);penalty=np.diag([0.,.001,.001])
    coef=np.linalg.solve(z.T@z+penalty,z.T@y)
    return {'center':center.tolist(),'scale':scale.tolist(),'coef':coef.tolist(),
            'bound':float(min(.05,max(1e-6,np.quantile(np.abs(y),.99))))}


def _predict(model,x):
    z=np.column_stack([np.ones(len(x)),(x-np.array(model['center']))/np.array(model['scale'])])
    return np.clip(z@np.array(model['coef']),-model['bound'],model['bound'])


def fit_model(history):
    if not 2<=len(history)<=20 or [d.day for d in history]!=sorted({d.day for d in history}) or len({d.symbol for d in history})!=1:
        raise ValueError('2..20 chronological complete sessions for one symbol required')
    error=zero=0.;folds=[]
    for i in range(1,len(history)):
        model=_fit(history[:i]);x,y=_samples(history[i:i+1]);p=_predict(model,x)
        error+=float(np.sum((y-p)**2));zero+=float(np.sum(y*y))
        folds.append({'train_end':history[i-1].day.isoformat(),'validation_date':history[i].day.isoformat(),'observations':len(y)})
    result=_fit(history);result.update(reliability=max(0.,min(1.,1-error/zero)) if zero>1e-20 else 0.,
        validation_sse=error,zero_signal_sse=zero,validation_folds=folds,train_dates=[d.day.isoformat() for d in history])
    return result


def predict_return(model,observed_closes,opening):
    closes=np.asarray(observed_closes,dtype=float)
    if len(closes)<3:return 0.
    p=np.r_[opening,closes];r=p[1:]/p[:-1]-1
    return float(_predict(model,np.array([[r[-1],r[-3:].mean()]]))[0])


def adjust_request(baseline,required,remaining,prediction,price,reliability,impact=1e-5):
    if not all(math.isfinite(v) for v in (prediction,price,reliability,impact)) or not 0<=reliability<=1 or price<=0 or impact<=0:
        raise ValueError('finite signal, positive price/impact and weight in [0,1] required')
    shift=-reliability*prediction*price/(2*impact/5)
    shift=float(np.clip(shift,-baseline,2*max(1,baseline)))
    return max(int(required),min(int(remaining),int(round(baseline+shift))))


def replay_day(history,target,quantity,rate,*,scenario='learned'):
    if scenario not in SCENARIOS:raise ValueError('unknown signal scenario')
    model=fit_model(history);_returns(target);volumes=np.array([d.volume for d in history]);actual=capacity._volumes(target.volume)
    if actual.shape!=(78,):raise ValueError('78 target volume bars required')
    if isinstance(quantity,(bool,np.bool_)) or not isinstance(quantity,(int,np.integer)) or not 1<=quantity<=10_000_000:raise ValueError('quantity must be1..10million integer')
    caps=capacity.capacities(actual,rate);remaining={p:int(quantity) for p in POLICIES};fills={p:[] for p in POLICIES};traces={p:[] for p in POLICIES}
    for t in range(78):
        prediction=predict_return(model,target.close[:t],target.open_price)
        if scenario=='zero':prediction=0.
        elif scenario=='inverted':prediction=-prediction
        price=float(target.close[t-1]) if t else float(target.open_price)
        for policy in POLICIES:
            d=capacity.decision(volumes,actual[:t],remaining[policy],rate)
            weight=0. if policy=='capacity' else (1. if policy=='always' else model['reliability'])
            request=adjust_request(d['request'],d['required_now'],remaining[policy],prediction,price,weight)
            fill=min(request,int(caps[t]));before=remaining[policy];remaining[policy]-=fill;fills[policy].append(fill)
            traces[policy].append({'interval':t,'minute':t*5,'request':request,'baseline_request':d['request'],
                'required_now':d['required_now'],'predicted_return':prediction,'weight':weight,'remaining_before':before,
                'filled':fill,'remaining_after':remaining[policy]})
    strategies={}
    for policy in POLICIES:
        diag=price_diagnostic(quantity,target.open_price,fills[policy],target.close,1e-5,5.)
        strategies[policy]={'fills':fills[policy],'residual':remaining[policy],'complete':remaining[policy]==0,
            'remaining':(quantity-np.r_[0,np.cumsum(fills[policy])]).tolist(),**diag}
    return {'model':model,'strategies':strategies,'traces':traces}


def run_study(days,config):
    n=config['lookback'];k=config['evaluation_days'];scenario=config.get('signal_scenario','learned')
    if isinstance(n,bool) or not isinstance(n,int) or not 2<=n<=20 or isinstance(k,bool) or not isinstance(k,int) or not 1<=k<=60:
        raise ValueError('lookback2..20 and evaluation_days1..60 required')
    if len(days)<=n or [d.day for d in days]!=sorted({d.day for d in days}) or len({d.symbol for d in days})!=1:
        raise ValueError('insufficient or nonchronological sessions')
    selected=days[-(n+k):];records=[];daily=[]
    for i in range(n,len(selected)):
        h=selected[i-n:i];target=selected[i];quantity=order_quantity(float(np.mean([d.volume.sum() for d in h])),config['fraction'])
        r=replay_day(h,target,quantity,config['participation_rate'],scenario=scenario);day=target.day.isoformat()
        daily.append({'date':day,'quantity':quantity,'model':r['model'],'traces':r['traces']})
        for policy,s in r['strategies'].items():records.append({'date':day,'planner':policy,'quantity':quantity,'train_dates':r['model']['train_dates'],**s})
    common=[d['date'] for d in daily if all(r['complete'] for r in records if r['date']==d['date'])];strategies=[]
    for policy in POLICIES:
        rows=[r for r in records if r['planner']==policy];paired=[r for r in rows if r['date'] in common]
        strategies.append({'planner':policy,'cases':len(rows),'completed':sum(r['complete'] for r in rows),
            'mean_residual':float(np.mean([r['residual'] for r in rows])),
            'all_case_partial_fill_mean_impact':float(np.mean([r['assumed_impact'] for r in rows])),
            'mean_assumed_impact':float(np.mean([r['assumed_impact'] for r in paired])) if paired else None,
            'common_complete_count':len(paired),'common_complete_mean_marked_bps':float(np.mean([r['marked_total_bps'] for r in paired])) if paired else None})
    summary={'evaluation_days':len(daily),'evaluation_start':daily[0]['date'],'evaluation_end':daily[-1]['date'],
             'cases':len(records),'strategies':strategies,'common_complete_dates':common,
             'mean_reliability':float(np.mean([d['model']['reliability'] for d in daily]))}
    return {'signal_schema':'1.0','symbol':days[0].symbol,'design':dict(config),'records':records,'daily':daily,
            'dashboard_summary':summary,'method':{'ridge_penalty':.001,'impact':1e-5,'shift_limit_baseline_multiple':2,
             'weight_interpretation':'Historical walk-forward squared-error improvement over zero forecast, not probability or guaranteed future effectiveness'}}
