"""Prespecified, reproducible cost-risk sensitivity study using Execution Lab 0.1.0."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
from execution_lab.config import ExecutionConfig
from execution_lab.schedule import make_ac, make_twap
from execution_lab.simulation import run_paired
from execution_lab.metrics import predictions, summarize
from execution_lab.export import _provenance

MAX_STUDY_CELLS = 12_000_000

def enumerate_cases(design):
    if design.get("schema_version") != "1.0":
        raise ValueError("unsupported design schema")
    base = dict(design["base"])
    risks = design["risk_aversions"]
    scenarios = design["scenarios"]
    scaling = design.get("scaling_cases", [])
    if not risks or len(set(risks)) != len(risks) or risks != sorted(risks):
        raise ValueError("risk grid must be increasing and unique")
    count = len(risks)*len(scenarios)+len(scaling)
    if count*base["trials"]*(base["intervals"]+1) > MAX_STUDY_CELLS:
        raise ValueError("study budget exceeded")
    names = [s["name"] for s in scenarios]+[s["name"] for s in scaling]
    if len(set(names)) != len(names):
        raise ValueError("scenario names must be unique")
    ExecutionConfig.from_dict(base)
    entries = []
    for scenario in scenarios:
        changes = scenario["changes"]
        if len(changes)>1 or set(changes)-{"volatility","impact"}:
            raise ValueError("main scenarios must be one-factor volatility or impact changes")
        for index, risk in enumerate(risks):
            c = ExecutionConfig.from_dict({**base, **changes, "risk_aversion":risk})
            entries.append({"id":f"case_{len(entries):03d}", "role":"main",
                "scenario":scenario["name"], "config":c.to_dict()})
    scaling_refs = []
    for case in scaling:
        if set(case["changes"])-{"volatility","impact","risk_aversion"}:
            raise ValueError("scaling changes must hold the remaining configuration fixed")
        c = ExecutionConfig.from_dict({**base, **case["changes"]})
        found = next((e for e in entries if e["config"]==c.to_dict()), None)
        if found is None:
            found = {"id":f"case_{len(entries):03d}", "role":"scaling",
                "scenario":case["name"], "config":c.to_dict()}
            entries.append(found)
        scaling_refs.append({"name":case["name"],"id":found["id"]})
    return entries, scaling_refs

def _schedule(c, schedule):
    # Trades at interval starts; count times strictly before T/4.
    start = np.arange(c.intervals)*c.tau
    return {"quantities":schedule.quantities.tolist(),
        "inventory":schedule.inventory.tolist(),
        "prediction":predictions(c,schedule),
        "fraction_before_quarter":float(schedule.quantities[start<c.duration/4].sum()/c.quantity)}

def _coefficient(c):
    return c.risk_aversion*c.volatility**2*c.tau**2/c.impact

def run_study(design):
    entries, scaling_refs = enumerate_cases(design)
    cases, raw, markets = [], {}, {}
    for entry in entries:
        c = ExecutionConfig.from_dict(entry["config"])
        integer = {"twap":make_twap(c),"ac":make_ac(c)}
        continuous = {"twap":make_twap(c,integer=False),"ac":make_ac(c,integer=False)}
        e = run_paired(c,{"twap":integer["twap"],"ac_simplified":integer["ac"]})
        key = (c.volatility,c.price,c.trials,c.intervals,c.duration,c.seed)
        if key not in markets:
            markets[key] = f"market_{len(markets):02d}"
            raw[markets[key]+"_prices"] = e.prices
            raw[markets[key]+"_innovations"] = e.price_innovations
        market_key=markets[key]
        # Verify common paths before deduplicating raw market arrays.
        if not np.array_equal(raw[market_key+"_prices"],e.prices):
            raise AssertionError("market deduplication mismatch")
        for name,values in e.costs.items():
            raw[entry["id"]+"_"+name+"_costs"]=values
        raw[entry["id"]+"_valid"]=e.valid_pairs
        ci, ii = {k:_schedule(c,v) for k,v in continuous.items()}, {k:_schedule(c,v) for k,v in integer.items()}
        jc=ci["ac"]["prediction"]["objective"]
        jt=ci["twap"]["prediction"]["objective"]
        ji=ii["ac"]["prediction"]["objective"]
        checks={"continuous_optimal_vs_twap":bool(jc<=jt+1e-9*max(1,abs(jt))),
            "integer_objective_gap":ji-jc,
            "integer_objective_gap_relative":(ji-jc)/max(abs(jc),1e-30),
            "accounting_reconciled":all(v["reconciled_within_roundoff"] for v in e.accounting["strategies"].values())}
        if not checks["continuous_optimal_vs_twap"] or ji<jc-1e-9*max(1,abs(jc)):
            raise AssertionError("continuous objective verification failed")
        cases.append({**entry,"coefficient":_coefficient(c),"market_key":market_key,
            "continuous":ci,"integer":ii,"summary":summarize(e),
            "invalid_reasons":e.invalid_reasons,"accounting":e.accounting,"checks":checks})
    monotonic=True
    for scenario in design["scenarios"]:
        rows=[r for r in cases if r["role"]=="main" and r["scenario"]==scenario["name"]]
        means=np.array([r["continuous"]["ac"]["prediction"]["mean"] for r in rows])
        variances=np.array([r["continuous"]["ac"]["prediction"]["variance"] for r in rows])
        monotonic &= bool(np.all(np.diff(means)>=-1e-9*max(1,means.max())) and
            np.all(np.diff(variances)<=1e-9*max(1,variances.max())))
        for row in rows:
            p=row["integer"]["ac"]["prediction"]
            row["integer_grid_nondominated"] = not any(
                s["integer"]["ac"]["prediction"]["mean"]<=p["mean"] and
                s["integer"]["ac"]["prediction"]["variance"]<=p["variance"] and
                (s["integer"]["ac"]["prediction"]["mean"]<p["mean"] or
                 s["integer"]["ac"]["prediction"]["variance"]<p["variance"]) for s in rows)
    if not monotonic:
        raise AssertionError("continuous frontier monotonicity failed")
    by_id={r["id"]:r for r in cases}
    selected=[by_id[r["id"]] for r in scaling_refs]
    max_difference=0.0
    coefficients=[r["coefficient"] for r in selected]
    if selected:
        if not np.allclose(coefficients,coefficients[0],rtol=1e-12,atol=1e-15):
            raise ValueError("scaling cases must have equal dimensionless coefficients")
        baseline=np.array(selected[0]["continuous"]["ac"]["quantities"])/selected[0]["config"]["quantity"]
        max_difference=max(float(np.max(np.abs(
            np.array(r["continuous"]["ac"]["quantities"])/r["config"]["quantity"]-baseline))) for r in selected)
        if max_difference>1e-10:
            raise AssertionError("dimensionless scaling verification failed")
    provenance=_provenance()
    provenance["study_source_sha256"]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return {"schema_version":"1.0","study_name":"Prespecified cost-risk sensitivity study",
        "design":design,"provenance":provenance,"main_conditions":sum(r["role"]=="main" for r in cases),
        "total_evaluated_conditions":len(cases),"independent_base_paths":design["base"]["trials"],
        "sampling_note":"Independent paths within each condition; shared standardized innovations across all conditions. Conditions are correlated; do not sum trials across conditions.",
        "cases":cases,"scaling_check":{"references":scaling_refs,"coefficients":coefficients,
            "max_normalized_quantity_difference":max_difference,
            "integer_schedules_equal":all(r["integer"]["ac"]["quantities"]==selected[0]["integer"]["ac"]["quantities"] for r in selected) if selected else None},
        "verification":{"continuous_monotonicity":monotonic,
            "all_accounting_reconciled":all(r["checks"]["accounting_reconciled"] for r in cases),
            "invalid_pairs_across_conditions":sum(r["summary"]["invalid_pairs"] for r in cases),
            "max_relative_integer_objective_gap":max(r["checks"]["integer_objective_gap_relative"] for r in cases)}},raw

def _write_json(path,value):
    path.write_text(json.dumps(value,indent=2,allow_nan=False)+"\n",encoding="utf-8",newline="\n")

def export_study(study,raw,output,*,figures=True):
    output=Path(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("choose a new output directory; study results cannot be silently overwritten")
    output.mkdir(parents=True,exist_ok=True)
    _write_json(output/"results.json",study)
    _write_json(output/"design.json",study["design"])
    np.savez_compressed(output/"raw-paths.npz",**raw)
    with (output/"metrics.csv").open("w",encoding="utf-8",newline="") as stream:
        fields=["case_id","role","scenario","strategy","lambda","sigma","eta","coefficient",
            "quantity_mode","expected_cost","variance","std","objective","fraction_before_quarter",
            "status","valid_pairs","sample_mean","sample_variance","mean_ci95_low","mean_ci95_high"]
        writer=csv.DictWriter(stream,fields,lineterminator="\n");writer.writeheader()
        for r in study["cases"]:
            for mode in ("continuous","integer"):
                for strategy,core_name in [("twap","twap"),("ac","ac_simplified")]:
                    s=r[mode][strategy]; p=s["prediction"]; ci=[None,None]; emp={}
                    if mode=="integer":
                        emp=r["summary"]["strategies"][core_name]["empirical"]
                        ci=emp["ci95_mean"] or ci
                    writer.writerow(dict(zip(fields,[r["id"],r["role"],r["scenario"],strategy,
                        r["config"]["risk_aversion"],r["config"]["volatility"],r["config"]["impact"],
                        r["coefficient"],p["quantity_mode"],p["mean"],p["variance"],p["std"],
                        p["objective"],s["fraction_before_quarter"],r["summary"]["status"],
                        r["summary"]["valid_pairs"],emp.get("mean"),emp.get("variance"),*ci])))
    if figures:
        render_figures(study,output)
    (output/"research-note.md").write_text(research_note(study),encoding="utf-8",newline="\n")
    paths=sorted(p for p in output.iterdir() if p.is_file())
    _write_json(output/"manifest.json",{"sha256":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}})
    return output

def render_figures(study,output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size":10,"axes.spines.top":False,"axes.spines.right":False,"figure.dpi":140})
    rows=[r for r in study["cases"] if r["role"]=="main" and r["scenario"]=="baseline"]
    if not rows:
        return
    fig,axes=plt.subplots(1,2,figsize=(12,4.5),layout="constrained")
    selected=[r for r in rows if r["config"]["risk_aversion"] in (0,1e-6,1e-5,1e-4,1e-3)]
    for r in selected:
        c=r["config"];time=np.linspace(0,c["duration"],c["intervals"]+1);label=f"lambda={c['risk_aversion']:g}"
        axes[0].step(time,np.array(r["integer"]["ac"]["inventory"])/c["quantity"],where="pre",label=label)
        axes[1].plot(time[:-1],np.array(r["integer"]["ac"]["quantities"])/c["quantity"],label=label)
    axes[0].set(xlabel="Time (minutes)",ylabel="Remaining fraction",title="Integer inventory: trades at interval starts")
    axes[1].set(xlabel="Trade time (minutes)",ylabel="Fraction traded per interval",title="Execution allocation")
    axes[0].legend(fontsize=8);axes[1].legend(fontsize=8)
    fig.savefig(output/"01-execution-profiles.png");plt.close(fig)

    def curve(ax,rs,label):
        p=[r["continuous"]["ac"]["prediction"] for r in rs]
        line=ax.plot([s["std"] for s in p],[s["mean"] for s in p],"-",label=label)[0]
        q=[r["integer"]["ac"]["prediction"] for r in rs]
        ax.scatter([s["std"] for s in q],[s["mean"] for s in q],s=15,color=line.get_color(),zorder=3)
    fig,ax=plt.subplots(figsize=(8,5),layout="constrained")
    curve(ax,rows,"Continuous reference / integer points")
    p=rows[0]["integer"]["twap"]["prediction"]
    ax.scatter([p["std"]],[p["mean"]],marker="*",s=170,color="black",label="Integer TWAP",zorder=5)
    for r in rows:
        if r["config"]["risk_aversion"] not in (1e-5,1e-4,1e-3):
            continue
        p=r["continuous"]["ac"]["prediction"]
        ax.annotate(f"{r['config']['risk_aversion']:g}",(p["std"],p["mean"]),xytext=(5,5),textcoords="offset points",fontsize=8)
    ax.set(xlabel="Cost standard deviation (currency)",ylabel="Expected cost (currency)",
        title="Baseline cost-risk trade-off (labels: lambda)")
    ax.legend();fig.savefig(output/"02-cost-risk-frontier.png");plt.close(fig)

    fig,axes=plt.subplots(1,2,figsize=(12,4.6),layout="constrained")
    for ax,names,title in [(axes[0],["volatility_low","baseline","volatility_high"],"Volatility sensitivity (eta fixed)"),
                           (axes[1],["impact_low","baseline","impact_high"],"Impact sensitivity (sigma fixed)")]:
        for name in names:
            rs=[r for r in study["cases"] if r["role"]=="main" and r["scenario"]==name]
            if rs:curve(ax,rs,name.replace("_"," "))
        ax.set(xlabel="Cost standard deviation (currency)",ylabel="Expected cost (currency)",title=title)
        ax.legend(fontsize=8)
    fig.savefig(output/"03-parameter-frontiers.png");plt.close(fig)

    fig,axes=plt.subplots(1,2,figsize=(12,4.6),layout="constrained")
    main=[r for r in study["cases"] if r["role"]=="main"]
    valid=[r for r in main if r["summary"]["status"]=="valid"]
    for scenario in study["design"]["scenarios"]:
        rs=[r for r in main if r["scenario"]==scenario["name"]]
        axes[0].plot([r["config"]["risk_aversion"] for r in rs],[r["integer"]["ac"]["fraction_before_quarter"] for r in rs],marker=".",label=scenario["name"].replace("_"," "))
    axes[0].set_xscale("symlog",linthresh=1e-7)
    axes[0].set(xlabel="Risk aversion lambda",ylabel="Fraction executed before T/4",title="How parameters change execution urgency")
    axes[0].legend(fontsize=8)
    for i,r in enumerate(valid):
        p=r["integer"]["ac"]["prediction"];emp=r["summary"]["strategies"]["ac_simplified"]["empirical"]
        ci=emp["ci95_mean"]
        axes[1].errorbar(i,emp["mean"]-p["mean"],yerr=[[emp["mean"]-ci[0]],[ci[1]-emp["mean"]]],fmt=".",color="tab:blue",capsize=2)
    axes[1].axhline(0,color="black",lw=1)
    axes[1].set(xlabel="Main condition index (valid conditions only)",ylabel="Sample minus analytic mean (currency)",
        title=f"Monte Carlo checks: marginal 95% mean intervals\nInvalid main conditions: {len(main)-len(valid)}")
    fig.savefig(output/"04-urgency-and-monte-carlo.png");plt.close(fig)

    refs=study["scaling_check"]["references"]
    if refs:
        by_id={r["id"]:r for r in study["cases"]}
        base=by_id[refs[0]["id"]]; n=base["config"]["intervals"]
        time=np.arange(n)*base["config"]["duration"]/n
        fig,ax=plt.subplots(figsize=(9,4.5),layout="constrained")
        for index,ref in enumerate(refs):
            r=by_id[ref["id"]];c=r["config"]
            fraction=np.array(r["continuous"]["ac"]["quantities"])/c["quantity"]
            label=f"sigma={c['volatility']:g}, eta={c['impact']:g}, lambda={c['risk_aversion']:g}"
            if index==0:ax.plot(time,fraction,label=label,color="black")
            else:ax.scatter(time[index::4],fraction[index::4],marker=["o","s"][index%2],facecolors="none",edgecolors=["tab:blue","tab:orange"][index%2],label=label,s=35)
        ax.set(xlabel="Trade time (minutes)",ylabel="Normalized trade quantity",
            title=f"Equal c = lambda*sigma²*tau²/eta: coincident schedules\nMaximum normalized difference: {study['scaling_check']['max_normalized_quantity_difference']:.3g}")
        ax.legend(fontsize=8);fig.savefig(output/"05-dimensionless-scaling.png");plt.close(fig)

def research_note(study):
    rows=[r for r in study["cases"] if r["role"]=="main" and r["scenario"]=="baseline"]
    focus=next((r for r in rows if r["config"]["risk_aversion"]==study["design"]["base"]["risk_aversion"]),rows[0] if rows else None)
    lines=["# Cost-risk sensitivity in a simplified execution model","",
        "## Research question","",
        "How do risk aversion, volatility and temporary impact change a fixed sell-order schedule, and what additional expected cost buys reduced execution risk?","",
        "## Prespecified design","",
        f"Main conditions: {study['main_conditions']}; total distinct conditions including scaling checks: {study['total_evaluated_conditions']}. Each uses {study['independent_base_paths']:,} independent Gaussian paths. The same standardized draws are reused across conditions; these are not independent batches whose sample counts can be added.",
        "The design is fixed in design.json. Main comparisons vary lambda within five scenarios, changing only volatility or temporary impact relative to baseline. The two extra scaling conditions test a mathematical implication rather than search for a better result.","",
        "## Model and timing","",
        "Trade n_k at the start of interval k, then hold inventory x_k. tau=T/N; x_0=Q and x_N=0. Arithmetic Brownian reference prices have zero drift, innovations sigma*sqrt(tau)*Z. Linear temporary impact is eta*n_k/tau; orders fill in full.",
        "E[C]=(eta/tau)*sum(n_k^2); Var[C]=sigma^2*tau*sum(x_k^2), k=1,...,N. Minimize E[C]+lambda*Var[C]. Risk is cost variance; plotted standard deviation is its square root. Currency is an arbitrary consistent unit, not a calibrated GBP/HKD forecast.",
        "The continuous minimizer is unique for positive eta. A finite lambda grid samples the continuous cost-risk frontier; it does not draw every efficient point. Integer schedules use deterministic largest-remainder rounding and are feasible approximations, with no claim of globally optimal integer allocation. Connecting lines guide the eye. Grid nondominance is only relative to sampled integer schedules in the same scenario.",""]
    if focus:
        a=focus["integer"]["ac"]["prediction"];t=focus["integer"]["twap"]["prediction"]
        lines += ["## Baseline findings","",
            f"At lambda={focus['config']['risk_aversion']:g}, integer TWAP expected cost is {t['mean']:.2f}, versus {a['mean']:.2f} for the optimized-and-rounded schedule ({100*(a['mean']/t['mean']-1):.2f}% higher).",
            f"Cost variance falls by {100*(1-a['variance']/t['variance']):.2f}%; standard deviation falls by {100*(1-a['std']/t['std']):.2f}%. The weighted objective falls by {100*(1-a['objective']/t['objective']):.2f}%. These are analytic model comparisons, not estimated real-market gains.",
            f"The schedule executes {100*focus['integer']['ac']['fraction_before_quarter']:.2f}% of the order strictly before T/4.",
            "","| Scenario at the same lambda | Expected cost | Cost std | Executed before T/4 |","|---|---:|---:|---:|"]
        for r in study["cases"]:
            if r["role"]=="main" and r["config"]["risk_aversion"]==focus["config"]["risk_aversion"]:
                p=r["integer"]["ac"]["prediction"]
                lines.append(f"| {r['scenario']} | {p['mean']:.2f} | {p['std']:.2f} | {100*r['integer']['ac']['fraction_before_quarter']:.2f}% |")
        paired=focus["summary"]["paired"]
        lines += ["",f"Paired Monte Carlo AC-minus-TWAP mean: {paired['empirical']['mean']}; marginal 95% mean interval: {paired['empirical']['ci95_mean']}. Check its status and conditional/all-path labels in results.json before interpreting it."]
    lines += ["","## Mathematical scaling result","",
        "The continuous schedule depends on the dimensionless coefficient c=lambda*sigma^2*tau^2/eta. Holding c fixed while doubling sigma requires dividing lambda by four; doubling eta requires doubling lambda. Schedules coincide even though their cost and variance units change.",
        f"Checked coefficient values: {study['scaling_check']['coefficients']}. Maximum normalized trade difference: {study['scaling_check']['max_normalized_quantity_difference']:.3g}; identical integer schedules: {study['scaling_check']['integer_schedules_equal']}.",
        "","## Validation and interpretation","",
        f"Continuous cost increases and variance decreases along each lambda grid: {study['verification']['continuous_monotonicity']}. All direct accounting reconciliations passed: {study['verification']['all_accounting_reconciled']}. Maximum relative integer objective gap: {study['verification']['max_relative_integer_objective_gap']:.3g}.",
        f"Invalid pairs summed across correlated conditions: {study['verification']['invalid_pairs_across_conditions']}. This sum counts condition-path occurrences, not distinct independent paths.",
        "Mean intervals use the core's Student-t method on independent paths within one condition; they are marginal intervals, with no simultaneous-coverage or multiple-testing claim. A confidence interval missing the analytic mean is possible under repeated sampling. Monte Carlo uncertainty is separate from misspecification, volatility-estimation or impact-estimation uncertainty.",
        "No invalid path is clipped or resampled. Full masks and reasons are retained. Conditional summaries of surviving paths cannot support unconditional performance claims.",
        "Higher lambda or sigma increases urgency; higher eta makes immediate trading more expensive and pushes allocation toward a flatter schedule. Compare financial outcomes only within a consistent scenario and objective. A larger lambda means a different preference, not a universally better strategy.",
        "","## Limits and reproducibility","",
        "Synthetic constant parameters, guaranteed fills, no spread/fees/permanent impact, no liquidity constraints, no market data calibration or alpha. This is an execution-model research artifact, not an investment recommendation or proof of superior returns.",
        "results.json stores all configurations, continuous and integer schedules, analytic and empirical moments, invalid-path diagnostics and provenance. raw-paths.npz stores deduplicated reference prices, preserved innovations, integer costs and validity masks. Reconstruct execution prices as reference_price_before_trade - eta*n/tau, and costs as analytic_impact - innovations @ inventory[1:]. manifest.json hashes actual output bytes.",
        "Provenance records core source digest, package/runtime versions, and this driver digest. Core source stays unchanged. Run the study twice into separate empty directories; compare numeric results and raw arrays while allowing creation timestamps to differ.",
        "","## Reference","",
        "[Almgren and Chriss (2001), Optimal execution of portfolio transactions](https://doi.org/10.21314/JOR.2001.041). This study implements a simplified discrete temporary-impact reference and does not reproduce every assumption of that paper.",""]
    return "\n".join(lines)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--design",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    design=json.loads(args.design.read_text(encoding="utf-8"))
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("output directory must be empty")
    study,raw=run_study(design)
    export_study(study,raw,args.output)
    print(json.dumps({"output":str(args.output),"verification":study["verification"],
        "conditions":study["total_evaluated_conditions"]},allow_nan=False))

if __name__=="__main__":
    main()
