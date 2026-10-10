"""Fixed-design capacity experiments with common innovations and explicit infeasibility."""
import argparse,csv,hashlib,json,math
from pathlib import Path
import numpy as np
from execution_lab.config import ExecutionConfig
from execution_lab.schedule import integerize,make_ac
from execution_lab.simulation import _market
from execution_lab.export import _provenance
from execution_research.studies.volume.volume_benchmark import profile_weights,analytic_prediction,simulate_common,_stats
from .participation import participation_limits,make_capped_twap,make_capped_volume,solve_constrained

STRATEGIES=("twap_capped","volume_capped","arrival_constrained")

def validate_design(d):
    if d.get("schema_version")!="1.0":raise ValueError("unsupported design")
    base=ExecutionConfig.from_dict(d["base"])
    if not 2<=base.intervals<=120:raise ValueError("dense constrained study requires 2 to 120 intervals")
    profiles=d["profiles"];risks=d["risk_aversions"];scenarios=d["scenarios"]
    if not profiles or len(set(profiles))!=len(profiles):raise ValueError("profiles must be unique")
    for p in profiles:profile_weights(p,base.intervals)
    if not risks or risks!=sorted(set(risks)) or base.risk_aversion not in risks:raise ValueError("unique increasing risk grid must include the report's default")
    for risk in risks:ExecutionConfig.from_dict(base.to_dict()|{"risk_aversion":risk})
    names=[s["name"] for s in scenarios]
    if not names or len(set(names))!=len(names) or any(not isinstance(v,str) or not v.replace("_","").isalnum() for v in names):
        raise ValueError("scenario names must be unique alphanumeric identifiers")
    for scenario in scenarios:
        volume=scenario["market_volume"]
        if isinstance(volume,bool) or not isinstance(volume,int) or not 1<=volume<=10**12:raise ValueError("market total must be a positive integer")
        participation_limits(base,np.full(base.intervals,volume/base.intervals),scenario["participation_rate"])
    count=len(profiles)*len(risks)*len(scenarios)
    if count>120 or count*base.trials>240000:raise ValueError("study budget exceeded")
    return base

def run_study(d):
    base=validate_design(d);prices,increments=_market(base)
    raw={"market_prices":prices,"market_increments":increments};cases=[];metrics=[];paired=[]
    for profile in d["profiles"]:
        forecast=profile_weights(profile,base.intervals);raw["profile_"+profile]=forecast
        for scenario in d["scenarios"]:
            volumes=integerize(scenario["market_volume"]*forecast,scenario["market_volume"])
            quota=participation_limits(base,volumes,scenario["participation_rate"]);caps=quota["caps"]
            for risk in d["risk_aversions"]:
                c=ExecutionConfig.from_dict(base.to_dict()|{"risk_aversion":risk});caseid=f"case_{len(cases):03d}"
                original=make_ac(c);a=np.full(c.intervals,c.impact/c.tau)
                violations=original.quantities>caps
                record={"case_id":caseid,"profile":profile,"scenario":scenario["name"],"risk_aversion":risk,
                    "config":c.to_dict(),"market_volume":scenario["market_volume"],"participation_rate":scenario["participation_rate"],
                    **{k:v for k,v in quota.items() if k!="caps"},
                    "max_possible_shares":min(c.quantity,quota["integer_capacity_total"]),
                    "unconstrained_reference":{"strategy":"ac_simplified","feasible":bool(not violations.any()),
                        "violating_intervals":int(violations.sum()),"excess_shares_sum":int(np.maximum(original.quantities-caps,0).sum()),
                        "arrival_prediction":analytic_prediction(c,original,a)},
                    "strategies":[],"status":"capacity_infeasible","valid_paths":None,"invalid_paths":None,
                    "accounting":None,"certificate":None}
                cases.append(record);raw[caseid+"_market_volumes"]=volumes;raw[caseid+"_caps"]=caps
                raw[caseid+"_unconstrained_quantities"]=original.quantities;raw[caseid+"_unconstrained_inventory"]=original.inventory
                if not quota["feasible"]:continue
                optimized,info=solve_constrained(c,caps)
                schedules={"twap_capped":make_capped_twap(c,caps),"volume_capped":make_capped_volume(c,forecast,caps),optimized.strategy:optimized}
                simulation=simulate_common(c,schedules,a,prices,increments);valid=simulation["valid_mask"]
                record.update(strategies=list(schedules),status=simulation["status"],valid_paths=int(valid.sum()),invalid_paths=int((~valid).sum()),
                    invalid_diagnostics=simulation["invalid_diagnostics"],accounting=simulation["accounting"],certificate=info["certificate"])
                raw[caseid+"_continuous_quantities"]=info["continuous_quantities"];raw[caseid+"_valid"]=valid
                predictions={}
                for name,s in schedules.items():
                    q=s.quantities
                    if np.any(q>caps):raise AssertionError("participation limit exceeded")
                    costs=simulation["arrival_costs"][name];prediction=analytic_prediction(c,s,a);predictions[name]=prediction
                    raw[caseid+"_"+name+"_quantities"]=q;raw[caseid+"_"+name+"_inventory"]=s.inventory;raw[caseid+"_"+name+"_costs"]=costs
                    rates=np.divide(q,volumes,out=np.zeros(c.intervals,dtype=float),where=volumes>0)
                    metrics.append({"case_id":caseid,"profile":profile,"scenario":scenario["name"],"risk_aversion":risk,"strategy":name,
                        "prediction":prediction,"all_paths":_stats(costs,inferential=simulation["status"]=="valid"),
                        "valid_subset":_stats(costs[valid],inferential=False),
                        "first_quarter_fraction":float(q[:max(1,c.intervals//4)].sum()/c.quantity),
                        "binding_intervals":int(((q==caps)&(caps>0)).sum()),"max_participation":float(rates.max()),
                        "integer_suboptimality_upper_bound":prediction["objective"]-info["certificate"]["lower_bound"]})
                for first,second in (("volume_capped","twap_capped"),("arrival_constrained","twap_capped"),("arrival_constrained","volume_capped")):
                    xa=schedules[first].inventory[1:];xb=schedules[second].inventory[1:]
                    delta=simulation["arrival_costs"][first]-simulation["arrival_costs"][second]
                    paired.append({"case_id":caseid,"profile":profile,"scenario":scenario["name"],"risk_aversion":risk,
                        "first":first,"second":second,"direction":first+"_minus_"+second,
                        "prediction_mean":predictions[first]["mean"]-predictions[second]["mean"],
                        "prediction_variance":float(c.volatility**2*c.tau*np.dot(xa-xb,xa-xb)),
                        "analytic_objective_difference":predictions[first]["objective"]-predictions[second]["objective"],
                        "all_paths":_stats(delta,inferential=simulation["status"]=="valid"),"valid_subset":_stats(delta[valid],inferential=False)})
    provenance=_provenance()
    source_files=list(sorted(Path(__file__).parent.glob("*.py")))+list(sorted((Path(__file__).parent.parent/"volume").glob("*.py")))
    provenance["extension_sources_sha256"]={p.relative_to(Path(__file__).parent.parent).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
    provenance["design_sha256"]=hashlib.sha256(json.dumps(d,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    feasible=[c for c in cases if c["feasible"]]
    verification={"feasible_cases":len(feasible),"infeasible_cases":len(cases)-len(feasible),
        "all_accounting_reconciled":all(v["reconciled"] for c in feasible for v in c["accounting"].values()),
        "all_plans_respect_caps":True,"all_cases_use_identical_market_innovations":True,
        "invalid_feasible_case_paths":sum(c["invalid_paths"] for c in feasible),
        "max_continuous_certificate_gap":max((c["certificate"]["gap"] for c in feasible),default=0),
        "all_raw_cost_paths_retained":True,"infeasible_cases_have_no_executed_strategies":True}
    return {"schema_version":"1.0","study_name":"Deterministic participation constraints and capacity feasibility",
        "design":d,"provenance":provenance,"cases":cases,"strategy_metrics":metrics,"paired_metrics":paired,"verification":verification},raw

def _json(path,value):
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+"\n",encoding="utf-8",newline="\n")

def _csv(path,records,paired=False):
    rows=[]
    for record in records:
        row={k:record[k] for k in ("case_id","profile","scenario","risk_aversion")}
        if paired:
            row.update({k:record[k] for k in ("first","second","direction","prediction_mean","prediction_variance","analytic_objective_difference")})
        else:
            row["strategy"]=record["strategy"];row.update({"prediction_"+k:v for k,v in record["prediction"].items()})
            row.update({k:record[k] for k in ("first_quarter_fraction","binding_intervals","max_participation","integer_suboptimality_upper_bound")})
        row.update({"empirical_"+k:v for k,v in record["all_paths"].items() if k!="ci95_mean"})
        ci=record["all_paths"]["ci95_mean"];row.update(ci95_lower=ci[0] if ci else None,ci95_upper=ci[1] if ci else None)
        rows.append(row)
    with path.open("w",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,list(rows[0]) if rows else ["no_records"],lineterminator="\n")
        writer.writeheader();writer.writerows(rows)

def export_study(study,raw,output,*,figures=True):
    output=Path(output)
    if output.exists() and any(output.iterdir()):raise FileExistsError("choose a new or empty output directory")
    output.mkdir(parents=True,exist_ok=True);_json(output/"results.json",study)
    np.savez_compressed(output/"paths-and-schedules.npz",**raw)
    _csv(output/"strategy-metrics.csv",study["strategy_metrics"]);_csv(output/"paired-metrics.csv",study["paired_metrics"],True)
    case_rows=[{k:c[k] for k in ("case_id","profile","scenario","risk_aversion","feasible","reason","raw_capacity_total","integer_capacity_total","shortfall_shares","max_possible_shares","status")} for c in study["cases"]]
    with (output/"capacity-diagnostics.csv").open("w",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,list(case_rows[0]),lineterminator="\n");writer.writeheader();writer.writerows(case_rows)
    if figures:
        from .capacity_reporting import write_reports,render_figures
        write_reports(study,raw,output);render_figures(study,raw,output)
    _json(output/"manifest.json",{"sha256":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.iterdir()) if p.is_file()}})
    return output

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--design",type=Path,required=True);parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):parser.error("choose a new or empty output directory")
    study,raw=run_study(json.loads(args.design.read_text(encoding="utf-8")));export_study(study,raw,args.output)
    print(json.dumps({"cases":len(study["cases"]),"strategy_rows":len(study["strategy_metrics"]),"paired_rows":len(study["paired_metrics"]),
        "raw_arrays":len(raw),"verification":study["verification"]}))
if __name__=="__main__":main()
