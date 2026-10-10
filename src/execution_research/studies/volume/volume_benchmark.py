"""Three-strategy execution comparisons with distinct arrival and market-VWAP benchmarks."""
from __future__ import annotations
import argparse,csv,hashlib,json,math
from pathlib import Path
import numpy as np
from scipy.stats import t
from execution_lab.config import ExecutionConfig
from execution_lab.types import Schedule
from execution_lab.schedule import make_twap,make_ac,integerize,validate_schedule
from execution_lab.reference_solver import solve_tridiagonal
from execution_lab.simulation import _market
from execution_lab.export import _provenance

PROFILES=("flat","u_shape","front_loaded","back_loaded","midday_peak")

def normalize_volume(weights,intervals):
    raw=np.asarray(weights,dtype=object)
    if raw.ndim!=1 or len(raw)!=intervals or any(isinstance(x,(bool,np.bool_)) for x in raw):raise ValueError("volume weights need one numeric entry per interval")
    try:a=np.asarray(weights,dtype=float)
    except (TypeError,ValueError) as exc:raise ValueError("volume weights must be numeric") from exc
    if not np.isfinite(a).all() or np.any(a<0) or a.max()<=0:raise ValueError("volume weights must be finite nonnegative with positive total")
    a=a/a.max();return a/a.sum()

def _schedule(c,name,quantities,integer):
    if not isinstance(integer,bool):raise ValueError("integer flag must be Boolean")
    q=integerize(quantities,c.quantity) if integer else np.array(quantities,dtype=float)
    x=np.concatenate((np.cumsum(q[::-1])[::-1],[0.]));x[0]=c.quantity
    result=Schedule(name,q,x,integer);validate_schedule(result,c);return result

def make_volume_weighted(c,forecast_weights,*,integer=True):
    c.validate();v=normalize_volume(forecast_weights,c.intervals)
    return _schedule(c,"volume_weighted",c.quantity*v,integer)

def profile_weights(name,intervals):
    if name not in PROFILES:raise ValueError("unknown synthetic profile")
    u=(np.arange(intervals)+.5)/intervals
    values={"flat":np.ones(intervals),"u_shape":.5+2*(2*u-1)**2,
        "front_loaded":.5+3*(1-u),"back_loaded":.5+3*u,
        "midday_peak":.5+3*np.exp(-.5*((u-.5)/.16)**2)}
    return normalize_volume(values[name],intervals)

def _coefficients(c,a):
    a=np.asarray(a,dtype=float)
    if a.shape!=(c.intervals,) or not np.isfinite(a).all() or np.any(a<=0):raise ValueError("positive finite impact coefficients required")
    return a

def impact_coefficients(c,forecast_weights,model):
    c.validate();v=normalize_volume(forecast_weights,c.intervals)
    if model=="constant":return np.full(c.intervals,c.impact/c.tau)
    if model!="inverse_expected_volume" or np.any(v<=0):raise ValueError("volume-linked impact needs strictly positive forecast weights")
    return _coefficients(c,c.impact/(c.tau*c.intervals*v))

def continuous_optimum(c,a):
    c.validate();a=_coefficients(c,a)
    if c.intervals==1:return np.array([c.quantity,0.])
    risk=c.risk_aversion*c.volatility**2*c.tau
    if risk==0:
        q=c.quantity*normalize_volume(a.min()/a,c.intervals)
        x=np.concatenate((np.cumsum(q[::-1])[::-1],[0.]));x[0]=c.quantity;return x
    diagonal=a[:-1]+a[1:]+risk;adjacent=-a[1:-1];rhs=np.zeros(c.intervals-1);rhs[0]=a[0]*c.quantity
    return np.concatenate(([c.quantity],solve_tridiagonal(adjacent,diagonal,adjacent,rhs),[0.]))

def make_optimized(c,a,*,integer=True):
    return _schedule(c,"ac_volume_aware",-np.diff(continuous_optimum(c,a)),integer)

def analytic_prediction(c,s,a,exposure=None):
    a=_coefficients(c,a);validate_schedule(s,c)
    if exposure is None:exposure=s.inventory[1:]
    mean=float(np.dot(a,s.quantities**2))
    variance=float(c.volatility**2*c.tau*np.dot(exposure,exposure))
    return {"mean":mean,"variance":variance,"std":math.sqrt(variance),"objective":mean+c.risk_aversion*variance}

def remaining_volume(weights,n):
    v=normalize_volume(weights,n)
    return np.concatenate((np.cumsum(v[::-1])[::-1],[0.]))[1:]

def benchmark_prediction(c,s,a,realized_weights):
    exposure=s.inventory[1:]-c.quantity*remaining_volume(realized_weights,c.intervals)
    return analytic_prediction(c,s,a,exposure)

def benchmark_costs(c,s,a,increments,realized_weights):
    prediction=benchmark_prediction(c,s,a,realized_weights)
    return prediction["mean"]-np.asarray(increments)@(s.inventory[1:]-c.quantity*remaining_volume(realized_weights,c.intervals))

def simulate_common(c,schedules,a,prices,increments):
    c.validate();a=_coefficients(c,a)
    if len(schedules)!=3:raise ValueError("provide three schedules")
    for name,s in schedules.items():
        if s.strategy!=name:raise ValueError("schedule key disagrees with strategy")
        validate_schedule(s,c)
    prices=np.asarray(prices);increments=np.asarray(increments)
    if prices.shape!=(c.trials,c.intervals+1) or increments.shape!=(c.trials,c.intervals) or not np.isfinite(prices).all() or not np.isfinite(increments).all():raise ValueError("invalid common price arrays")
    expected=np.column_stack((np.full(c.trials,c.price),c.price+np.cumsum(increments,axis=1)))
    if not np.allclose(prices,expected,rtol=0,atol=8*c.intervals*np.finfo(float).eps*max(1.,float(np.max(np.abs(prices))))):raise ValueError("prices do not agree with preserved innovations")
    valid=np.all(prices>0,axis=1);costs={};accounting={};execution_bad={}
    gamma=c.intervals*np.finfo(float).eps/(1-c.intervals*np.finfo(float).eps)
    for name,s in schedules.items():
        fills=prices[:,:-1]-a*s.quantities
        mean=float(np.dot(a,s.quantities**2));costs[name]=mean-increments@s.inventory[1:]
        direct=c.quantity*c.price-fills@s.quantities
        residual=np.abs(costs[name]-direct)
        bound=8*gamma*(abs(c.quantity*c.price)+np.abs(fills)@s.quantities)
        if not np.all(residual<=bound):raise AssertionError("proceeds accounting mismatch")
        accounting[name]={"reconciled":True,"max_residual_currency":float(residual.max()),"max_roundoff_bound_currency":float(bound.max())}
        execution_bad[name]=np.any(fills<=0,axis=1);valid &= ~execution_bad[name]
    invalid=[]
    for index in np.flatnonzero(~valid):
        invalid.append({"path":int(index),"nonpositive_reference_price":bool(np.any(prices[index]<=0)),
            "affected_strategies":[name for name in schedules if execution_bad[name][index]]})
    status="valid" if valid.all() else ("invalid_model" if not valid.any() else "partially_invalid")
    return {"arrival_costs":costs,"valid_mask":valid,"status":status,"accounting":accounting,"invalid_diagnostics":invalid}

def _stats(values,*,inferential):
    a=np.asarray(values);n=len(a)
    result={"count":n,"mean":None,"variance":None,"standard_error":None,"ci95_mean":None}
    if n<2:return result
    mean=float(a.mean());variance=float(a.var(ddof=1));result.update(mean=mean,variance=variance)
    if inferential:
        se=math.sqrt(variance/n);radius=float(t.ppf(.975,n-1))*se
        result.update(standard_error=se,ci95_mean=[mean-radius,mean+radius])
    return result

def validate_design(d):
    if d.get("schema_version")!="1.0":raise ValueError("unsupported schema")
    c=ExecutionConfig.from_dict(d["base"])
    if c.intervals<2:raise ValueError("study needs at least two intervals")
    names=d["profiles"]
    if not names or len(set(names))!=len(names) or any(n not in PROFILES for n in names):raise ValueError("invalid profiles")
    risks=d["risk_aversions"]
    if not risks or len(set(risks))!=len(risks) or risks!=sorted(risks):raise ValueError("risk weights must be increasing and unique")
    for risk in risks:ExecutionConfig.from_dict({**c.to_dict(),"risk_aversion":risk})
    if d["impact_models"]!=["constant","inverse_expected_volume"]:raise ValueError("both specified impact assumptions required")
    if d["benchmark_volume_cases"]!=["matched","shifted"]:raise ValueError("both realized volume cases required")
    f=d["shift_fraction"]
    if isinstance(f,bool) or not isinstance(f,(float,int)) or not math.isfinite(f) or not 0<f<1:raise ValueError("invalid shift fraction")
    count=len(names)*len(risks)*2
    if count>60 or count*c.trials>200000:raise ValueError("experiment budget exceeded")
    return c

def run_study(d):
    base=validate_design(d);prices,increments=_market(base)
    raw={"market_prices":prices,"market_increments":increments};cases=[];metrics=[];paired=[]
    shift=max(1,int(round(base.intervals*d["shift_fraction"])))%base.intervals
    for profile in d["profiles"]:
        forecast=profile_weights(profile,base.intervals);shifted=np.roll(forecast,shift)
        raw["profile_"+profile+"_forecast"]=forecast;raw["profile_"+profile+"_shifted"]=shifted
        for model in d["impact_models"]:
            for risk in d["risk_aversions"]:
                c=ExecutionConfig.from_dict({**base.to_dict(),"risk_aversion":risk})
                case_id=f"case_{len(cases):03d}";a=impact_coefficients(c,forecast,model)
                optimizer=make_ac(c) if model=="constant" else make_optimized(c,a)
                schedules={"twap":make_twap(c),"volume_weighted":make_volume_weighted(c,forecast),optimizer.strategy:optimizer}
                result=simulate_common(c,schedules,a,prices,increments);valid=result["valid_mask"]
                continuous=continuous_optimum(c,a)
                continuous_q=-np.diff(continuous)
                lower=float(np.dot(a,continuous_q**2)+c.risk_aversion*c.volatility**2*c.tau*np.dot(continuous[1:],continuous[1:]))
                excesses={name:analytic_prediction(c,s,a)["objective"]-lower for name,s in schedules.items()}
                if any(excess < -1e-9*max(1.,abs(lower)) for excess in excesses.values()):raise AssertionError("continuous lower bound violated")
                record={"case_id":case_id,"profile":profile,"impact_model":model,"risk_aversion":risk,"config":c.to_dict(),
                    "optimizer_strategy":optimizer.strategy,"status":result["status"],"valid_paths":int(valid.sum()),"invalid_paths":int((~valid).sum()),
                    "accounting":result["accounting"],"invalid_diagnostics":result["invalid_diagnostics"],
                    "continuous_arrival_objective_lower_bound":lower,"arrival_objective_excess_over_continuous_bound":excesses,
                    "realized_shift_bins":shift,"shifted_vs_forecast_L1":float(np.abs(shifted-forecast).sum())}
                cases.append(record);raw[case_id+"_coefficients"]=a;raw[case_id+"_continuous_inventory"]=continuous;raw[case_id+"_valid"]=valid
                for name,s in schedules.items():
                    raw[case_id+"_"+name+"_quantities"]=s.quantities;raw[case_id+"_"+name+"_inventory"]=s.inventory
                    raw[case_id+"_"+name+"_arrival_costs"]=result["arrival_costs"][name]
                targets=[("arrival","none",None),("market_vwap","matched",forecast),("market_vwap","shifted",shifted)]
                for benchmark,volume_case,weights in targets:
                    values={};predicted={}
                    for name,s in schedules.items():
                        if benchmark=="arrival":
                            costs=result["arrival_costs"][name];prediction=analytic_prediction(c,s,a)
                        else:
                            costs=benchmark_costs(c,s,a,increments,weights);prediction=benchmark_prediction(c,s,a,weights)
                            raw[case_id+"_"+name+"_"+volume_case+"_vwap_costs"]=costs
                            market_vwap=prices[:,:-1]@weights
                            fills=prices[:,:-1]-a*s.quantities
                            direct=c.quantity*market_vwap-fills@s.quantities
                            gamma=c.intervals*np.finfo(float).eps/(1-c.intervals*np.finfo(float).eps)
                            tolerance=8*gamma*(np.abs(c.quantity*market_vwap)+np.abs(fills)@s.quantities)
                            if not np.all(np.abs(direct-costs)<=tolerance):raise AssertionError("market-VWAP accounting mismatch")
                        values[name]=costs;predicted[name]=prediction
                        metrics.append({"case_id":case_id,"profile":profile,"impact_model":model,"risk_aversion":risk,
                            "strategy":name,"benchmark":benchmark,"volume_case":volume_case,
                            "prediction":prediction,"all_paths":_stats(costs,inferential=result["status"]=="valid"),
                            "valid_subset":_stats(costs[valid],inferential=False),
                            "first_quarter_fraction":float(s.quantities[:c.intervals//4].sum()/c.quantity),
                            "forecast_volume_L1":float(np.abs(s.quantities/c.quantity-forecast).sum()),
                            "arrival_objective_excess_over_continuous_bound":excesses[name]})
                    for first,second in (("volume_weighted","twap"),(optimizer.strategy,"twap"),("volume_weighted",optimizer.strategy)):
                        exposure=schedules[first].inventory[1:]-schedules[second].inventory[1:]
                        variance=float(c.volatility**2*c.tau*np.dot(exposure,exposure))
                        delta=values[first]-values[second]
                        paired.append({"case_id":case_id,"profile":profile,"impact_model":model,"risk_aversion":risk,
                            "benchmark":benchmark,"volume_case":volume_case,"first":first,"second":second,
                            "direction":first+"_minus_"+second,"prediction_mean":predicted[first]["mean"]-predicted[second]["mean"],
                            "prediction_variance":variance,
                            "analytic_objective_difference":predicted[first]["objective"]-predicted[second]["objective"],
                            "all_paths":_stats(delta,inferential=result["status"]=="valid"),
                            "valid_subset":_stats(delta[valid],inferential=False)})
    provenance=_provenance();provenance["study_source_sha256"]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    reporting=Path(__file__).parent/"study_reporting.py"
    provenance["reporting_source_sha256"]=hashlib.sha256(reporting.read_bytes()).hexdigest() if reporting.exists() else None
    provenance["design_sha256"]=hashlib.sha256(json.dumps(d,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return {"schema_version":"1.0","study_name":"Forecast-volume execution and market-VWAP benchmarking",
        "design":d,"provenance":provenance,"cases":cases,"strategy_metrics":metrics,"paired_metrics":paired,
        "verification":{"all_accounting_reconciled":all(v["reconciled"] for c in cases for v in c["accounting"].values()),
            "continuous_lower_bounds_respected":True,"raw_invalid_paths_retained":True,
            "all_cases_use_identical_market_prices":True,"planning_uses_forecast_volume_only":True,
            "total_invalid_case_paths":sum(c["invalid_paths"] for c in cases)}},raw

def _json(path,data):
    path.write_text(json.dumps(data,indent=2,ensure_ascii=False,allow_nan=False)+"\n",encoding="utf-8",newline="\n")

def _metrics_csv(path,rows,paired=False):
    flattened=[]
    for r in rows:
        keys=["case_id","profile","impact_model","risk_aversion","benchmark","volume_case"]
        keys+=["first","second","direction"] if paired else ["strategy"]
        row={k:r[k] for k in keys}
        pred={"prediction_mean":r["prediction_mean"],"prediction_variance":r["prediction_variance"],"analytic_objective_difference":r["analytic_objective_difference"]} if paired else {"prediction_"+k:v for k,v in r["prediction"].items()}
        row.update(pred)
        row.update({"empirical_"+k:v for k,v in r["all_paths"].items() if k!="ci95_mean"})
        ci=r["all_paths"]["ci95_mean"];row.update(ci95_lower=ci[0] if ci else None,ci95_upper=ci[1] if ci else None)
        flattened.append(row)
    with path.open("w",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,list(flattened[0]) if flattened else ["no_records"],lineterminator="\n")
        writer.writeheader();writer.writerows(flattened)

def export_study(study,raw,output,*,figures=True):
    output=Path(output)
    if output.exists() and any(output.iterdir()):raise FileExistsError("choose a new or empty output directory")
    output.mkdir(parents=True,exist_ok=True);_json(output/"results.json",study)
    np.savez_compressed(output/"paths-and-schedules.npz",**raw)
    _metrics_csv(output/"strategy-metrics.csv",study["strategy_metrics"]);_metrics_csv(output/"paired-metrics.csv",study["paired_metrics"],paired=True)
    if figures:
        from .study_reporting import write_reports,render_figures
        write_reports(study,raw,output);render_figures(study,raw,output)
    _json(output/"manifest.json",{"sha256":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.iterdir()) if p.is_file()}})
    return output

def main():
    p=argparse.ArgumentParser();p.add_argument("--design",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    if args.output.exists() and any(args.output.iterdir()):p.error("choose a new or empty output directory")
    study,raw=run_study(json.loads(args.design.read_text(encoding="utf-8")))
    export_study(study,raw,args.output)
    print(json.dumps({"cases":len(study["cases"]),"strategy_rows":len(study["strategy_metrics"]),"paired_rows":len(study["paired_metrics"]),"raw_arrays":len(raw),"verification":study["verification"]}))
if __name__=="__main__":main()
