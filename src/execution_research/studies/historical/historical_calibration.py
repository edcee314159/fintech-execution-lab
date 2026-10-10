"""Audited historical FX volatility calibration and a normalized execution-model adapter."""
from __future__ import annotations
import argparse,csv,hashlib,io,json,math,zipfile
from datetime import date
from pathlib import Path
import numpy as np
from execution_lab.config import ExecutionConfig
from execution_lab.schedule import make_ac
from execution_lab.metrics import predictions
from execution_lab.export import _provenance

def validate_design(d):
    if d.get("schema_version")!="1.0":raise ValueError("unsupported schema")
    dates={k:date.fromisoformat(d[k]) for k in ("data_start","data_end","training_start","training_end","evaluation_start","evaluation_end")}
    if not dates["data_start"]<dates["training_start"]<=dates["training_end"]<dates["evaluation_start"]<=dates["evaluation_end"]<=dates["data_end"]:
        raise ValueError("period overlap or invalid chronology")
    windows=d["rolling_windows"]
    if not windows or windows!=sorted(set(windows)) or any(isinstance(w,bool) or not isinstance(w,int) or not 2<=w<=500 for w in windows):
        raise ValueError("rolling windows must be distinct increasing integers")
    minimum=d["min_training_returns"]
    if isinstance(minimum,bool) or not isinstance(minimum,int) or not 3<=minimum<=3000:raise ValueError("training budget invalid")
    c=ExecutionConfig.from_dict(d["base"])
    if c.price!=d["calibration"]["benchmark_price"]:raise ValueError("benchmark price must agree with model")
    for value in (d["outlier_absolute_log_return_flag"],d["calibration"]["normal_95_multiplier"],d["calibration"]["annual_calendar_minutes"]):
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:raise ValueError("threshold/units must be positive finite")
    if not d["assets"] or len(d["assets"])>5:raise ValueError("asset budget invalid")
    required=d["source"]["required_columns"]
    if "Date" not in required or len(set(required))!=len(required):raise ValueError("required columns invalid")
    for asset,spec in d["assets"].items():
        if not asset.isalnum() or spec["numerator"] not in required or spec["denominator"] not in required or spec["numerator"]==spec["denominator"]:
            raise ValueError("cross-rate schema invalid")
    return c

def clean_rates(payload,d):
    try:stream=io.StringIO(payload.decode("utf-8-sig"))
    except UnicodeError as exc:raise ValueError("source must be UTF-8 CSV") from exc
    reader=csv.DictReader(stream);required=d["source"]["required_columns"]
    if reader.fieldnames is None or any(k not in reader.fieldnames for k in required):
        raise ValueError("source missing required columns")
    if any(reader.fieldnames.count(k)!=1 for k in required):raise ValueError("duplicate required column")
    audit={"input_rows":0,"outside_range_rows":0,"duplicate_rows":0,"dropped_rows":0,"kept_rows":0,
        "forward_filled":False,"extreme_returns_deleted":False,"dropped":[],"duplicates":[],
        "ignored_columns":[k for k in reader.fieldnames if k not in required]}
    seen={};rates=[]
    for line,row in enumerate(reader,start=2):
        if not row or all(not v for v in row.values()):continue
        audit["input_rows"]+=1
        try:day=date.fromisoformat(row["Date"].strip()).isoformat()
        except (ValueError,AttributeError,TypeError) as exc:raise ValueError(f"invalid source date at CSV line {line}") from exc
        if not d["data_start"]<=day<=d["data_end"]:
            audit["outside_range_rows"]+=1;continue
        selected=tuple((row.get(k) or "").strip() for k in required if k!="Date")
        if day in seen:
            if selected!=seen[day]:raise ValueError(f"conflicting duplicate date {day}")
            audit["duplicate_rows"]+=1;audit["duplicates"].append({"date":day,"line":line});continue
        seen[day]=selected;values={};reason=None
        for k in required:
            if k=="Date":continue
            value=(row.get(k) or "").strip()
            if value.lower() in ("","n/a","na","nan"):
                reason="missing_rate";break
            try:number=float(value)
            except ValueError:
                reason="invalid_rate";break
            if not math.isfinite(number) or number<=0:reason="invalid_rate";break
            values[k]=number
        if reason:
            audit["dropped_rows"]+=1
            audit["dropped"].append({"date":day,"line":line,"reason":reason,"selected_raw_rates":dict(zip([k for k in required if k!="Date"],selected))})
            continue
        record={"date":day,**values}
        for asset,spec in d["assets"].items():
            record[asset]=values[spec["numerator"]]/values[spec["denominator"]]
            if not math.isfinite(record[asset]) or record[asset]<=0:raise ValueError("invalid derived cross-rate")
        rates.append(record)
    rates.sort(key=lambda r:r["date"]);audit["kept_rows"]=len(rates)
    assert audit["input_rows"]==sum(audit[k] for k in ("outside_range_rows","duplicate_rows","dropped_rows","kept_rows"))
    if len(rates)<2:raise ValueError("insufficient clean prices")
    audit["first_date"]=rates[0]["date"];audit["last_date"]=rates[-1]["date"]
    audit["calendar_gap_days"]={str(k):sum((date.fromisoformat(b["date"])-date.fromisoformat(a["date"])).days==k for a,b in zip(rates[:-1],rates[1:])) for k in sorted({(date.fromisoformat(b["date"])-date.fromisoformat(a["date"])).days for a,b in zip(rates[:-1],rates[1:])})}
    return rates,audit

def make_returns(rates,asset,threshold):
    records=[]
    for previous,current in zip(rates[:-1],rates[1:]):
        minutes=(date.fromisoformat(current["date"])-date.fromisoformat(previous["date"])).days*1440
        if minutes<=0:raise ValueError("prices must have strictly increasing dates")
        value=math.log(current[asset]/previous[asset])
        records.append({"asset":asset,"start_date":previous["date"],"end_date":current["date"],
            "start_price":previous[asset],"end_price":current[asset],"elapsed_minutes":float(minutes),
            "log_return":value,"extreme_flag":bool(abs(value)>threshold)})
    return records

def fit_diffusion(returns,durations):
    r=np.asarray(returns,dtype=float);dt=np.asarray(durations,dtype=float)
    if r.ndim!=1 or dt.shape!=r.shape or len(r)<2 or not np.isfinite(r).all() or not np.isfinite(dt).all() or np.any(dt<=0):
        raise ValueError("fit needs at least two finite returns with positive durations")
    drift=float(r.sum()/dt.sum())
    variance=float(np.sum((r-drift*dt)**2/dt)/(len(r)-1))
    if not math.isfinite(variance):raise ValueError("non-finite diffusion fit")
    return {"drift_per_minute":drift,"variance_per_minute":variance,
        "sigma_per_sqrt_minute":float(math.sqrt(variance)),"sample_count":len(r),"elapsed_minutes":float(dt.sum()),
        "variance_degrees_of_freedom":len(r)-1}

def _fit_records(records,*,fixed_day=False):
    fit=fit_diffusion([x["log_return"] for x in records],[1440. if fixed_day else x["elapsed_minutes"] for x in records])
    return {**fit,"fit_first_date":records[0]["end_date"],"fit_last_date":records[-1]["end_date"],
        "time_mapping":"fixed_reference_1440_minutes" if fixed_day else "actual_calendar_minutes"}

def training_records(records,d):
    return [x for x in records if d["training_start"]<=x["end_date"]<=d["training_end"]]

def forecast_rows(records,d):
    train=training_records(records,d)
    if len(train)<d["min_training_returns"]:raise ValueError("insufficient training returns")
    static=_fit_records(train);rows=[];zcrit=d["calibration"]["normal_95_multiplier"]
    for index,target in enumerate(records):
        if not d["evaluation_start"]<=target["end_date"]<=d["evaluation_end"]:continue
        methods=[("static_training",static)]
        for window in d["rolling_windows"]:
            if index<window:raise ValueError("insufficient pre-forecast rolling history")
            history=records[index-window:index]
            methods.append((f"rolling_{window}",_fit_records(history)))
        for method,fit in methods:
            if fit["fit_last_date"]>target["start_date"]:raise AssertionError("future information in fit")
            mean=fit["drift_per_minute"]*target["elapsed_minutes"]
            variance=fit["variance_per_minute"]*target["elapsed_minutes"]
            error=target["log_return"]-mean
            if variance:
                squared_z=error**2/variance;z=error/math.sqrt(variance)
                covered=abs(z)<=zcrit;qlike=math.log(variance)+squared_z
            else:
                squared_z=None;z=None;covered=error==0;qlike=None
            rows.append({"asset":target.get("asset","test"),"method":method,"start_date":target["start_date"],"end_date":target["end_date"],
                "elapsed_minutes":target["elapsed_minutes"],"observed_log_return":target["log_return"],
                "forecast_mean":mean,"forecast_variance":variance,"forecast_error":error,"standardized_error":z,
                "squared_standardized_error":squared_z,"normal_95_covered":bool(covered),"qlike":qlike,
                "sigma_per_sqrt_minute":fit["sigma_per_sqrt_minute"],"drift_per_minute":fit["drift_per_minute"],
                "fit_first_date":fit["fit_first_date"],"fit_last_date":fit["fit_last_date"],"fit_sample_count":fit["sample_count"]})
    if not rows:raise ValueError("no holdout observations")
    return rows

def summarize_forecasts(rows):
    summary=[]
    for asset in sorted({r["asset"] for r in rows}):
        for method in sorted({r["method"] for r in rows if r["asset"]==asset}):
            chosen=[r for r in rows if r["asset"]==asset and r["method"]==method]
            for period in ["all"]+sorted({r["end_date"][:4] for r in chosen}):
                group=chosen if period=="all" else [r for r in chosen if r["end_date"].startswith(period)]
                errors=sum(r["forecast_error"]**2 for r in group);variances=sum(r["forecast_variance"] for r in group)
                q=[r["qlike"] for r in group if r["qlike"] is not None]
                summary.append({"asset":asset,"method":method,"period":period,"observations":len(group),
                    "msfe_over_forecast_variance":errors/variances if variances else None,
                    "empirical_normal_95_coverage":sum(r["normal_95_covered"] for r in group)/len(group),
                    "mean_qlike":sum(q)/len(q) if q else None,"zero_variance_forecasts":sum(r["forecast_variance"]==0 for r in group),
                    "interpretation":"Descriptive chronological holdout diagnostics; no independent-observation CI claimed."})
    return summary

def model_link(asset,calendar_fit,reference_fit,d):
    base=ExecutionConfig.from_dict(d["base"]);price=d["calibration"]["benchmark_price"]
    calendar_sigma=price*calendar_fit["sigma_per_sqrt_minute"]
    values={"original_assumption":base.volatility,"calibrated_calendar":calendar_sigma,
        "calibrated_reference_day":price*reference_fit["sigma_per_sqrt_minute"]}
    evaluation=ExecutionConfig.from_dict({**base.to_dict(),"volatility":calendar_sigma});rows=[];arrays={}
    for policy,sigma in values.items():
        config=ExecutionConfig.from_dict({**base.to_dict(),"volatility":sigma})
        schedule=make_ac(config,integer=False);key=asset+"_"+policy+"_inventory"
        arrays[key]=schedule.inventory
        rows.append({"asset":asset,"policy":policy,"array_key":key,"estimated_volatility":sigma,
            "planning_config":config.to_dict(),"evaluation_config":evaluation.to_dict(),
            "planning_prediction":predictions(config,schedule),"common_evaluation":predictions(evaluation,schedule),
            "first_quarter_quantity_fraction":float(schedule.quantities[:base.intervals//4].sum()/base.quantity),
            "instrument_scope":"synthetic_100_price_normalized_exposure","quantity_mode":"continuous_reference",
            "units_notice":"Historical relative FX volatility carried by a hypothetical 100 USD/unit instrument; not actual GBP/HKD quotes or real share execution."})
    best=next(r for r in rows if r["policy"]=="calibrated_calendar")["common_evaluation"]["objective"]
    for row in rows:row["relative_objective_excess_vs_calendar_plan"]=(row["common_evaluation"]["objective"]-best)/best
    return rows,arrays

def _lag1(values):
    a=np.asarray(values,dtype=float)
    if len(a)<3 or np.std(a[:-1])==0 or np.std(a[1:])==0:return None
    return float(np.corrcoef(a[:-1],a[1:])[0,1])

def run_study(d,csv_bytes,source_metadata):
    validate_design(d);rates,audit=clean_rates(csv_bytes,d)
    all_returns=[];forecasts=[];fits=[];model=[];arrays={}
    for asset,spec in d["assets"].items():
        records=make_returns(rates,asset,d["outlier_absolute_log_return_flag"]);all_returns.extend(records)
        train=training_records(records,d)
        if len(train)<d["min_training_returns"]:raise ValueError("insufficient training observations")
        calendar=_fit_records(train);fixed=_fit_records(train,fixed_day=True)
        origin=next(x for x in rates if x["date"]==calendar["fit_last_date"])
        for mapping,fit in (("calendar",calendar),("reference_day",fixed)):
            fits.append({"asset":asset,"mapping":mapping,**fit,"actual_price_at_training_end":origin[asset],
                "actual_quote_sigma_per_sqrt_minute":origin[asset]*fit["sigma_per_sqrt_minute"],
                "sigma_equivalent_at_price_100":d["calibration"]["benchmark_price"]*fit["sigma_per_sqrt_minute"],
                "daily_equivalent_log_volatility":fit["sigma_per_sqrt_minute"]*math.sqrt(1440),
                "annual_calendar_equivalent_log_volatility":fit["sigma_per_sqrt_minute"]*math.sqrt(d["calibration"]["annual_calendar_minutes"]),
                "training_return_lag1_correlation":_lag1([x["log_return"] for x in train]),
                "training_squared_return_lag1_correlation":_lag1([x["log_return"]**2 for x in train]),
                "extreme_flag_count":sum(x["extreme_flag"] for x in train),"units":spec["units"]})
        forecasts.extend(forecast_rows(records,d))
        rows,raw=model_link(asset,calendar,fixed,d);model.extend(rows);arrays.update(raw)
    provenance=_provenance()
    provenance.update(study_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        reporting_source_sha256=hashlib.sha256((Path(__file__).parent/"study_reporting.py").read_bytes()).hexdigest(),
        design_sha256=hashlib.sha256(json.dumps(d,sort_keys=True,separators=(",",":")).encode()).hexdigest(),
        source_member_sha256=hashlib.sha256(csv_bytes).hexdigest())
    return {"schema_version":"1.0","study_name":"Historical FX reference-data volatility calibration",
        "design":d,"provenance":provenance,"source_metadata":source_metadata,"cleaning_audit":audit,
        "rates":rates,"returns":all_returns,"calibration_fits":fits,"forecasts":forecasts,
        "forecast_summary":summarize_forecasts(forecasts),"model_link":model,
        "verification":{"passed":True,"audit_counts_reconcile":True,"no_price_imputation":True,
            "forecast_fit_dates_precede_targets":all(x["fit_last_date"]<=x["start_date"]<x["end_date"] for x in forecasts),
            "source_is_current_snapshot_not_vintage":True,"impact_and_risk_preference_remain_assumptions":True,
            "model_outputs_are_not_real_transaction_backtests":True}},arrays

def _json(path,value):
    path.write_text(json.dumps(value,indent=2,allow_nan=False,ensure_ascii=False)+"\n",encoding="utf-8",newline="\n")

def _csv(path,rows):
    if not rows:rows=[];fields=["no_records"]
    else:fields=list(rows[0])
    with path.open("w",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fields,lineterminator="\n");writer.writeheader();writer.writerows(rows)

def export_study(study,arrays,output,*,figures=True):
    output=Path(output)
    if output.exists() and any(output.iterdir()):raise FileExistsError("choose a new or empty output directory")
    output.mkdir(parents=True,exist_ok=True);_json(output/"results.json",study)
    for key,name in (("rates","clean-prices.csv"),("returns","returns.csv"),("forecasts","forecast-records.csv"),("forecast_summary","forecast-summary.csv")):
        _csv(output/name,study[key])
    _json(output/"cleaning-audit.json",study.get("cleaning_audit",{}))
    np.savez_compressed(output/"inventories.npz",**arrays)
    if figures:
        from .study_reporting import write_reports,render_figures
        write_reports(study,output);render_figures(study,arrays,output)
    _json(output/"manifest.json",{"sha256":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.iterdir()) if p.is_file()}})
    return output

def main():
    p=argparse.ArgumentParser();p.add_argument("--design",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    if args.output.exists() and any(args.output.iterdir()):p.error("choose a new or empty output directory")
    d=json.loads(args.design.read_text(encoding="utf-8"));folder=args.design.parent/"source"
    metadata=json.loads((folder/"source-metadata.json").read_text(encoding="utf-8"))
    archive=(folder/"eurofxref-hist.zip").read_bytes()
    if hashlib.sha256(archive).hexdigest()!=metadata["archive_sha256"]:raise ValueError("source archive hash mismatch")
    with zipfile.ZipFile(io.BytesIO(archive)) as z:csv_bytes=z.read(d["source"]["member"])
    if hashlib.sha256(csv_bytes).hexdigest()!=metadata["member_sha256"]:raise ValueError("source member hash mismatch")
    study,arrays=run_study(d,csv_bytes,metadata)
    export_study(study,arrays,args.output)
    print(json.dumps({"clean_prices":len(study["rates"]),"return_records":len(study["returns"]),
        "forecast_records":len(study["forecasts"]),"summary_records":len(study["forecast_summary"]),
        "model_plans":len(study["model_link"]),"verification":study["verification"]}))
if __name__=="__main__":main()
