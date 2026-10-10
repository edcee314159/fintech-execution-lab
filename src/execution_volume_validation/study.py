"""A frozen historical design with explicit public/private output separation."""
from datetime import date
from pathlib import Path
import hashlib
import json
import math
import re
import numpy as np
from execution_lab.config import ExecutionConfig
from execution_research.studies.participation.participation import participation_limits,make_capped_twap,make_capped_volume,solve_constrained
from .data import load_sessions
from .forecasting import PREDICTORS,predict,order_quantity,forecast_scores
from .replay import replay_schedule,price_diagnostic

PLANNERS=("twap_capped","volume_capped","arrival_constrained")


def _validate(design):
    required={"symbols","expected_dates","lookback","fractions","participation_rate","impact","risk_aversion","sources"}
    if not isinstance(design,dict) or not required<=design.keys():raise ValueError("design is missing required fields")
    symbols=design["symbols"]
    if not symbols or len(set(symbols))!=len(symbols) or any(not isinstance(s,str) or not re.fullmatch(r"[A-Z0-9._-]{1,12}",s) for s in symbols):raise ValueError("unique safe symbols required")
    if design.get("source_access_date") is not None:
        date.fromisoformat(design["source_access_date"])
    dates=[date.fromisoformat(d) for d in design["expected_dates"]]
    if dates!=sorted(set(dates)):raise ValueError("unique chronological expected dates required")
    n=design["lookback"]
    if isinstance(n,bool) or not isinstance(n,int) or n<2 or len(dates)<=n:raise ValueError("lookback needs history and evaluation dates")
    if not design["fractions"] or len(set(design["fractions"]))!=len(design["fractions"]):raise ValueError("unique fractions required")
    for f in design["fractions"]:order_quantity(10000,f)
    return dates


def _comparisons(records,symbols,fractions):
    summaries=[]
    for symbol in symbols:
        for predictor in PREDICTORS:
            for fraction in fractions:
                rows=[r for r in records if r["symbol"]==symbol and r["predictor"]==predictor and r["order_fraction_adv"]==fraction]
                dates=sorted({r["date"] for r in rows});common=[]
                for d in dates:
                    today=[r for r in rows if r["date"]==d]
                    if len(today)==3 and all(r["planning_feasible"] and r["replay"]["complete"] for r in today):common.append(d)
                strategies={}
                for planner in PLANNERS:
                    r=[x for x in rows if x["planner"]==planner];planned=[x for x in r if x["planning_feasible"]];paired=[x for x in r if x["date"] in common]
                    strategies[planner]={"cases":len(r),"planned":len(planned),"completed":sum(x["replay"]["complete"] for x in planned),
                        "completion_rate_all_cases":sum(x["replay"]["complete"] for x in planned)/len(r),
                        "mean_completion_fraction_planned":float(np.mean([x["replay"]["completion_fraction"] for x in planned])) if planned else None,
                        "mean_residual_planned":float(np.mean([x["replay"]["residual"] for x in planned])) if planned else None,
                        "common_complete_mean_marked_bps":float(np.mean([x["price_diagnostic"]["marked_total_bps"] for x in paired])) if paired else None}
                summaries.append({"symbol":symbol,"predictor":predictor,"order_fraction_adv":fraction,"common_complete_dates":common,"common_complete_count":len(common),"strategies":strategies})
    return summaries


def run_study(input_dir: Path,design: dict):
    dates=_validate(design);symbols=design["symbols"];lookback=design["lookback"]
    records=[];forecasts=[];audits={};private={};public={};sources={}
    for symbol in symbols:
        source=design["sources"][symbol];name=source["csv_member"]
        if Path(name).name!=name or "/" in name or "\\" in name:raise ValueError("source CSV must be a local filename")
        path=Path(input_dir)/name;digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if digest!=source["csv_sha256"]:raise ValueError(f"input hash mismatch for {symbol}; frozen study cannot use changed sample")
        loaded,audit=load_sessions(path,symbol);audits[symbol]=audit;byday={d.day:d for d in loaded}
        omitted=[d.isoformat() for d in byday if dates[0]<=d<=dates[-1] and d not in dates]
        if omitted:raise ValueError(f"omitted eligible interior sessions for {symbol}: {omitted}; use consecutive eligible sessions")
        absent=[d.isoformat() for d in dates if d not in byday]
        if absent:raise ValueError(f"missing eligible sessions for {symbol}: {absent}")
        days=[byday[d] for d in dates];sources[symbol]={"csv_sha256":digest,"csv_member":name,"url":source.get("url"),"archive_sha256":source.get("archive_sha256")}
        for i in range(lookback,len(days)):
            current=days[i];history=days[i-lookback:i];base=f"{symbol}_{current.day.isoformat()}"
            private[base+"_actual_volume"]=current.volume;private[base+"_close_prices"]=current.close
            private[base+"_open_price"]=np.array([current.open_price])
            for predictor in PREDICTORS:
                forecast=predict(history,current.day,predictor,lookback);prefix=base+"_"+predictor
                private[prefix+"_forecast_volume"]=forecast.volume
                forecasts.append({"symbol":symbol,"date":current.day.isoformat(),"predictor":predictor,"train_dates":list(forecast.train_dates),"scores":forecast_scores(forecast.volume,current.volume)})
                for fraction in design["fractions"]:
                    quantity=order_quantity(forecast.adv,fraction)
                    c=ExecutionConfig(quantity=quantity,duration=390.,intervals=78,price=forecast.training_price,volatility=forecast.volatility,impact=design["impact"],risk_aversion=design["risk_aversion"],trials=2)
                    limits=participation_limits(c,forecast.volume,design["participation_rate"])
                    case=prefix+"_"+str(fraction).replace(".","p")
                    private[case+"_forecast_caps"]=limits["caps"]
                    plans={};certificate=None
                    if limits["feasible"]:
                        plans["twap_capped"]=make_capped_twap(c,limits["caps"])
                        plans["volume_capped"]=make_capped_volume(c,forecast.volume,limits["caps"])
                        plans["arrival_constrained"],info=solve_constrained(c,limits["caps"]);certificate=info["certificate"]
                    for planner in PLANNERS:
                        record={"id":case+"_"+planner,"symbol":symbol,"date":current.day.isoformat(),"predictor":predictor,"planner":planner,"order_fraction_adv":fraction,
                            "quantity":quantity,"train_dates":list(forecast.train_dates),"training_volatility_per_sqrt_minute":forecast.volatility,
                            "planning_feasible":limits["feasible"],"planning_reason":limits["reason"],"predicted_integer_capacity":limits["integer_capacity_total"],
                            "continuous_certificate":certificate if planner=="arrival_constrained" else None,"replay":None,"price_diagnostic":None}
                        if limits["feasible"]:
                            q=plans[planner].quantities;run=replay_schedule(q,current.volume,design["participation_rate"])
                            diagnostic=price_diagnostic(quantity,current.open_price,run["fills"],current.close,c.impact,c.tau)
                            record["replay"]={k:v for k,v in run.items() if k not in ("caps","fills","remaining")}
                            record["price_diagnostic"]=diagnostic
                            for eta in (0.,1e-5,5e-5):
                                d=price_diagnostic(quantity,current.open_price,run["fills"],current.close,eta,c.tau)
                                record.setdefault("fixed_schedule_impact_sensitivity_bps",{})[str(eta)]=d["marked_total_bps"]
                            for suffix,array in {"planned":q,"fills":run["fills"],"remaining":run["remaining"]}.items():public[record["id"]+"_"+suffix]=array
                            private[record["id"]+"_actual_caps"]=run["caps"]
                        records.append(record)
    private.update(public)
    result={"schema_version":"1.0","title":"Real equity volume: chronological forecast and retrospective capacity pilot",
        "source":"FirstRate Data free samples","design":design,"sources":sources,"audit":audits,"forecasts":forecasts,"records":records,
        "comparisons":_comparisons(records,symbols,design["fractions"]),"evaluation_calendar_dates":[d.isoformat() for d in dates[lookback:]],
        "evaluation_symbol_days":len(symbols)*(len(dates)-lookback),"forecast_count":len(forecasts),"planned_record_count":sum(r["planning_feasible"] for r in records),
        "completed_record_count":sum(bool(r["replay"] and r["replay"]["complete"]) for r in records),
        "interpretation":f"{len(dates)-lookback} evaluation dates, {len(symbols)} selected instruments. Retrospective capacity replay and assumed close-price diagnostics, not actual fills, true VWAP, calibrated impact, live trading or statistically established superiority.",
        "ai_assistance":"AI-assisted implementation and research preparation.",
        "raw_data_policy":"Raw OHLCV and raw-volume/price arrays are excluded from public package. Fetch independently from vendor; frozen hashes are mandatory."}
    return result,private,public


def save_study(result,private,public,output: Path):
    output=Path(output)
    if output.exists() and (not output.is_dir() or any(output.iterdir())):raise ValueError("output must be new or empty; existing research is preserved")
    output.mkdir(parents=True,exist_ok=True)
    (output/"private-diagnostics").mkdir(exist_ok=True)
    (output/"results.json").write_text(json.dumps(result,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    np.savez_compressed(output/"private-diagnostics"/"full-arrays.npz",**private)
    np.savez_compressed(output/"derived-schedules.npz",**public)
    receipt={"research_scope":"Frozen full pilot; not smoke", "design_sha256":hashlib.sha256(json.dumps(result["design"],sort_keys=True,separators=(",",":")).encode()).hexdigest(),
        "public_files":{name:hashlib.sha256((output/name).read_bytes()).hexdigest() for name in ("results.json","derived-schedules.npz")},
        "private_arrays_excluded_from_distribution":True}
    (output/"manifest.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
