"""Prespecified multi-stream Monte Carlo convergence and Gaussian interval calibration."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from numbers import Real
from pathlib import Path
import numpy as np
from scipy.stats import beta, chi2, norm, t
from execution_lab.config import ExecutionConfig
from execution_lab.schedule import make_ac, make_twap
from execution_lab.metrics import predictions
from execution_lab.simulation import run_paired
from execution_lab.export import _provenance

MAX_STUDY_CELLS=80_000_000
CHANNELS=("twap","ac","paired")

def validate_design(design):
    if design.get("schema_version")!="1.0":raise ValueError("unsupported design schema")
    base=ExecutionConfig.from_dict(design["base"])
    sizes=design["sample_sizes"];seeds=design["seeds"];confidence=design["confidence_level"]
    if not sizes or any(isinstance(n,bool) or not isinstance(n,int) or n<2 for n in sizes):
        raise ValueError("sample sizes must be integers with at least two paths")
    if sizes!=sorted(sizes) or len(set(sizes))!=len(sizes):
        raise ValueError("sample sizes must be increasing and unique")
    if sizes[-1]!=base.trials:raise ValueError("maximum sample size must match base trials")
    if len(seeds)<2 or any(isinstance(s,bool) or not isinstance(s,int) or not 0<=s<=2**32-1 for s in seeds):
        raise ValueError("at least two valid integer seeds required")
    if len(set(seeds))!=len(seeds):raise ValueError("seeds must be unique")
    if len(seeds)*base.trials*(base.intervals+1)>MAX_STUDY_CELLS:raise ValueError("study budget exceeded")
    if isinstance(confidence,bool) or not isinstance(confidence,Real) or not np.isfinite(confidence) or not 0<confidence<1:
        raise ValueError("confidence level must be between zero and one")
    return base

def exact_binomial_interval(successes,total,confidence):
    if not total:return None
    alpha=1-confidence
    return [0.0 if successes==0 else float(beta.ppf(alpha/2,successes,total-successes+1)),
        1.0 if successes==total else float(beta.ppf(1-alpha/2,successes+1,total-successes))]

def gaussian_stats(values,*,truth,confidence,inferential=True):
    values=np.asarray(values,dtype=float)
    if values.ndim!=1 or not np.isfinite(values).all():raise ValueError("values must be a finite vector")
    out={"count":int(values.size),"mean":None,"variance":None,"std":None,"standard_error":None,
        "ci_mean":None,"ci_variance":None,"mean_covered":None,"variance_covered":None,
        "standardized_mean_error":None}
    if values.size<2:return out
    n=values.size;mean=float(values.mean());variance=float(values.var(ddof=1))
    out.update(mean=mean,variance=variance,std=float(np.sqrt(variance)))
    if inferential:
        alpha=1-confidence;df=n-1
        se=float(np.sqrt(variance/n));radius=float(t.ppf(1-alpha/2,df))*se if variance else 0.
        mean_ci=[mean-radius,mean+radius]
        var_ci=[float(df*variance/chi2.ppf(1-alpha/2,df)),float(df*variance/chi2.ppf(alpha/2,df))] if variance else [0.,0.]
        true_se=float(np.sqrt(truth["variance"]/n))
        standardized=(mean-truth["mean"])/true_se if true_se else (0. if mean==truth["mean"] else None)
        out.update(standard_error=se,ci_mean=mean_ci,ci_variance=var_ci,
            mean_covered=bool(mean_ci[0]<=truth["mean"]<=mean_ci[1]),
            variance_covered=bool(var_ci[0]<=truth["variance"]<=var_ci[1]),
            standardized_mean_error=standardized)
    return out

def _array_hash(array):
    a=np.ascontiguousarray(array,dtype="<f8")
    return hashlib.sha256(a.tobytes()).hexdigest()

def _schedule(schedule):
    return {"quantity_mode":"integer_approximation","quantities":schedule.quantities.tolist(),"inventory":schedule.inventory.tolist()}

def aggregate_batches(batches,theory,sizes,confidence):
    aggregates=[]
    for n in sizes:
        rows=[r for r in batches if r["sample_size"]==n]
        eligible=all(r["eligible_for_nominal_coverage"] for r in rows)
        for channel in CHANNELS:
            metrics=[r["channels"][channel] for r in rows]
            mean=theory[channel]["mean"];variance=theory[channel]["variance"]
            errors=np.array([s["mean"]-mean for s in metrics])
            var_errors=np.array([s["variance"]-variance for s in metrics])
            item={"sample_size":n,"channel":channel,"replicates":len(rows),
                "eligible_replicates":sum(r["eligible_for_nominal_coverage"] for r in rows),
                "status":"unconditional_model_check" if eligible else "selection_affected",
                "mean_bias":float(errors.mean()),"mean_rmse":float(np.sqrt(np.mean(errors**2))),
                "theoretical_mean_rmse":float(np.sqrt(variance/n)),
                "relative_variance_rmse":float(np.sqrt(np.mean(var_errors**2))/variance) if variance else None,
                "theoretical_relative_variance_rmse":float(np.sqrt(2/(n-1))) if variance else None,
                "mean_coverage":None,"mean_coverage_interval":None,"variance_coverage":None,
                "variance_coverage_interval":None,"mean_interval_average_width":None,
                "variance_interval_average_width":None,"paired_ci_excludes_zero_fraction":None,
                "coverage_target":confidence if variance else 1.0,
                "coverage_interval_method":"Clopper-Pearson exact binomial",
                "all_path_moments_are_algebraic_diagnostics_if_selection_affected":not eligible}
            if eligible:
                mc=sum(s["mean_covered"] for s in metrics);vc=sum(s["variance_covered"] for s in metrics)
                item.update(mean_coverage=mc/len(rows),mean_coverage_successes=mc,
                    mean_coverage_interval=exact_binomial_interval(mc,len(rows),confidence),
                    variance_coverage=vc/len(rows),variance_coverage_successes=vc,
                    variance_coverage_interval=exact_binomial_interval(vc,len(rows),confidence),
                    mean_interval_average_width=float(np.mean([s["ci_mean"][1]-s["ci_mean"][0] for s in metrics])),
                    variance_interval_average_width=float(np.mean([s["ci_variance"][1]-s["ci_variance"][0] for s in metrics])))
                if channel=="paired":
                    item["paired_ci_excludes_zero_fraction"]=sum(s["ci_mean"][0]>0 or s["ci_mean"][1]<0 for s in metrics)/len(rows)
            aggregates.append(item)
    slopes={}
    for channel in CHANNELS:
        rows=[r for r in aggregates if r["channel"]==channel]
        usable=all(r["status"]=="unconditional_model_check" and r["mean_rmse"]>0 for r in rows)
        slopes[channel]=float(np.polyfit(np.log([r["sample_size"] for r in rows]),np.log([r["mean_rmse"] for r in rows]),1)[0]) if usable and len(rows)>1 else None
    return aggregates,slopes

def run_study(design):
    base=validate_design(design);sizes=design["sample_sizes"];confidence=design["confidence_level"]
    schedules={"twap":make_twap(base),"ac_simplified":make_ac(base)}
    twap=schedules["twap"];ac=schedules["ac_simplified"]
    theory={"twap":predictions(base,twap),"ac":predictions(base,ac)}
    coefficient=base.volatility**2*base.tau
    paired_variance=float(coefficient*np.sum((ac.inventory[1:]-twap.inventory[1:])**2))
    theory["paired"]={"mean":theory["ac"]["mean"]-theory["twap"]["mean"],
        "variance":paired_variance,"std":float(np.sqrt(paired_variance))}
    independent=theory["twap"]["variance"]+theory["ac"]["variance"]
    covariance=float(coefficient*np.dot(ac.inventory[1:],twap.inventory[1:]))
    if not np.isclose(paired_variance,independent-2*covariance,rtol=1e-12,atol=1e-8):raise AssertionError("paired variance identity failed")
    raw={"twap_costs":np.empty((len(design["seeds"]),base.trials)),
        "ac_costs":np.empty((len(design["seeds"]),base.trials)),
        "valid_pairs":np.empty((len(design["seeds"]),base.trials),dtype=bool)}
    batches=[];replicates=[]
    for index,seed in enumerate(design["seeds"]):
        c=ExecutionConfig.from_dict({**base.to_dict(),"seed":seed})
        e=run_paired(c,schedules)
        raw["twap_costs"][index]=e.costs["twap"];raw["ac_costs"][index]=e.costs["ac_simplified"];raw["valid_pairs"][index]=e.valid_pairs
        reconciled=all(r["reconciled_within_roundoff"] for r in e.accounting["strategies"].values())
        replicates.append({"replicate_index":index,"seed":seed,"paths":base.trials,
            "valid_paths":int(e.valid_pairs.sum()),"invalid_paths":int((~e.valid_pairs).sum()),
            "price_matrix_sha256":_array_hash(e.prices),"innovation_matrix_sha256":_array_hash(e.price_innovations),
            "matrix_hash_semantics":"SHA256 of C-contiguous little-endian float64 bytes; dimensions in base config",
            "accounting_reconciled":reconciled,"accounting":e.accounting,"invalid_reasons":e.invalid_reasons})
        delta=e.costs["ac_simplified"]-e.costs["twap"]
        for n in sizes:
            valid=bool(e.valid_pairs[:n].all())
            channels={}
            for name,values in [("twap",e.costs["twap"]),("ac",e.costs["ac_simplified"]),("paired",delta)]:
                channels[name]=gaussian_stats(values[:n],truth=theory[name],confidence=confidence,inferential=valid)
            batches.append({"replicate_index":index,"seed":seed,"sample_size":n,
                "valid_paths":int(e.valid_pairs[:n].sum()),"invalid_paths":int((~e.valid_pairs[:n]).sum()),
                "eligible_for_nominal_coverage":valid,
                "label":"all_model_paths" if valid else "outside_model_algebraic_diagnostics",
                "channels":channels})
    aggregates,slopes=aggregate_batches(batches,theory,sizes,confidence)
    provenance=_provenance()
    provenance["study_source_sha256"]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return {"schema_version":"1.0","study_name":"Multi-seed statistical validation and Monte Carlo convergence",
        "design":design,"provenance":provenance,"unique_market_paths":len(design["seeds"])*base.trials,
        "replicate_count":len(replicates),"nested_batch_count":len(batches),
        "schedules":{"twap":_schedule(twap),"ac":_schedule(ac)},"theory":theory,
        "pairing":{"paired_variance":paired_variance,"counterfactual_independent_variance":independent,
            "cross_strategy_cost_covariance":covariance,
            "independent_over_paired_variance":independent/paired_variance if paired_variance else None,
            "interpretation":"Independent comparison is an analytic counterfactual at equal per-strategy sample size, not another simulated dataset."},
        "financial_comparison":{"analytic_expected_cost_delta":theory["paired"]["mean"],
            "analytic_objective_delta":theory["ac"]["objective"]-theory["twap"]["objective"],
            "note":"Positive paired mean cost is not evidence of an inferior weighted objective; mean CIs do not quantify objective-difference uncertainty."},
        "replicates":replicates,"batches":batches,"aggregates":aggregates,
        "convergence":{"mean_rmse_loglog_slopes":slopes,"theoretical_slope":-.5,
            "fit_note":"Descriptive fit only. Nested sizes and cross-strategy metrics are correlated; no regression p-values or confidence claims."},
        "verification":{"retained_all_prespecified_seeds":[r["seed"] for r in replicates]==design["seeds"],
            "all_accounting_reconciled":all(r["accounting_reconciled"] for r in replicates),
            "invalid_path_occurrences":sum(r["invalid_paths"] for r in replicates),
            "all_batch_counts_match_design":len(batches)==len(sizes)*len(replicates),
            "no_coverage_or_monotonic_error_requirement_used_as_a_pass_fail_rule":True}},raw

def _write_json(path,value):
    path.write_text(json.dumps(value,indent=2,allow_nan=False)+"\n",encoding="utf-8",newline="\n")

def export_study(study,raw,output,*,figures=True):
    output=Path(output)
    if output.exists() and any(output.iterdir()):raise FileExistsError("choose a new or empty output directory")
    output.mkdir(parents=True,exist_ok=True)
    _write_json(output/"results.json",study);_write_json(output/"design.json",study["design"])
    np.savez_compressed(output/"raw-costs.npz",**raw)
    with (output/"batch-metrics.csv").open("w",encoding="utf-8",newline="") as stream:
        fields=["replicate_index","seed","sample_size","channel","label","valid_paths","mean","variance","standard_error","mean_ci_low","mean_ci_high","variance_ci_low","variance_ci_high","mean_covered","variance_covered"]
        writer=csv.DictWriter(stream,fields,lineterminator="\n");writer.writeheader()
        for row in study["batches"]:
            for name,m in row["channels"].items():
                ci=m["ci_mean"] or [None,None];vi=m["ci_variance"] or [None,None]
                writer.writerow(dict(zip(fields,[row["replicate_index"],row["seed"],row["sample_size"],name,row["label"],row["valid_paths"],
                    m["mean"],m["variance"],m["standard_error"],*ci,*vi,m["mean_covered"],m["variance_covered"]])))
    with (output/"aggregate-metrics.csv").open("w",encoding="utf-8",newline="") as stream:
        fields=["sample_size","channel","replicates","status","mean_bias","mean_rmse","theoretical_mean_rmse","relative_variance_rmse",
            "mean_coverage","variance_coverage","mean_interval_average_width","paired_ci_excludes_zero_fraction"]
        writer=csv.DictWriter(stream,fields,lineterminator="\n");writer.writeheader()
        for row in study["aggregates"]:writer.writerow({k:row[k] for k in fields})
    (output/"research-note.md").write_text(research_note(study),encoding="utf-8",newline="\n")
    if figures:render_figures(study,output)
    _write_json(output/"manifest.json",{"sha256":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.iterdir()) if p.is_file()}})
    return output

def render_figures(study,output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size":10,"axes.spines.top":False,"axes.spines.right":False,"figure.dpi":140})
    colors={"twap":"tab:blue","ac":"tab:orange","paired":"tab:green"}
    fig,axes=plt.subplots(1,2,figsize=(12,4.7),layout="constrained")
    for channel in CHANNELS:
        rows=[r for r in study["aggregates"] if r["channel"]==channel]
        n=[r["sample_size"] for r in rows]
        if all(r["mean_rmse"]>0 for r in rows):
            axes[0].loglog(n,[r["mean_rmse"] for r in rows],"o-",color=colors[channel],label=channel+" empirical")
            axes[0].loglog(n,[r["theoretical_mean_rmse"] for r in rows],"--",color=colors[channel],alpha=.7,label=channel+" theory")
        if all(r["relative_variance_rmse"] is not None and r["relative_variance_rmse"]>0 for r in rows):
            axes[1].loglog(n,[r["relative_variance_rmse"] for r in rows],"o-",color=colors[channel],label=channel)
    sizes=study["design"]["sample_sizes"]
    axes[1].loglog(sizes,np.sqrt(2/(np.array(sizes)-1)),"k--",label="Gaussian theory")
    axes[0].set(xlabel="Paths per independent replicate",ylabel="Mean RMSE (currency)",title="Empirical mean errors versus 1/sqrt(n)")
    axes[1].set(xlabel="Paths per independent replicate",ylabel="Relative variance RMSE",title="Variance estimates across prespecified seeds")
    axes[0].legend(fontsize=8);axes[1].legend(fontsize=8)
    fig.savefig(output/"01-monte-carlo-convergence.png");plt.close(fig)

    fig,axes=plt.subplots(1,2,figsize=(12,4.7),layout="constrained")
    for ax,key,ci_key,title in [(axes[0],"mean_coverage","mean_coverage_interval","Mean interval coverage"),
                                (axes[1],"variance_coverage","variance_coverage_interval","Variance interval coverage")]:
        for j,channel in enumerate(CHANNELS):
            rows=[r for r in study["aggregates"] if r["channel"]==channel and r[key] is not None]
            if not rows:continue
            x=np.array([r["sample_size"] for r in rows])*(1+(j-1)*.05)
            y=np.array([r[key] for r in rows]);cis=np.array([r[ci_key] for r in rows])
            ax.errorbar(x,y,yerr=np.vstack([y-cis[:,0],cis[:,1]-y]),fmt="o-",color=colors[channel],label=channel,capsize=3)
        ax.axhline(study["design"]["confidence_level"],color="black",ls="--",lw=1,label="Nominal coverage (nondegenerate)")
        ax.set_xscale("log");ax.set(xlabel="Paths per replicate (small offsets for clarity)",ylabel="Observed fraction",ylim=(.7,1.015),title=title)
        ax.legend(fontsize=8)
    fig.suptitle(f"Coverage over {study['replicate_count']} independent replicates; bars: exact binomial intervals")
    fig.savefig(output/"02-interval-coverage.png");plt.close(fig)

    fig,ax=plt.subplots(figsize=(9,5),layout="constrained")
    rows=[r for r in study["batches"] if r["sample_size"]==max(sizes)]
    for row in rows:
        m=row["channels"]["paired"]
        if m["ci_mean"] is None:continue
        ci=m["ci_mean"];color="tab:blue" if m["mean_covered"] else "tab:red"
        ax.vlines(row["replicate_index"],ci[0],ci[1],color=color,lw=1)
        ax.scatter([row["replicate_index"]],[m["mean"]],color=color,s=9)
    ax.axhline(study["theory"]["paired"]["mean"],color="black",ls="--",label="Analytic AC-minus-TWAP mean")
    ax.set(xlabel="Prespecified replicate index",ylabel="Paired mean cost difference (currency)",
        title=f"All seed outcomes retained: n={max(sizes):,}\nRed intervals miss the analytic mean; this is expected occasionally")
    ax.legend(fontsize=9);fig.savefig(output/"03-all-seed-paired-intervals.png");plt.close(fig)

    fig,axes=plt.subplots(1,2,figsize=(12,4.7),layout="constrained")
    rows=[r for r in study["aggregates"] if r["channel"]=="paired"]
    n=np.array([r["sample_size"] for r in rows])
    widths=[r["mean_interval_average_width"] for r in rows]
    if all(w is not None and w>0 for w in widths):
        axes[0].loglog(n,widths,"o-",label="Paired empirical average")
        z=norm.ppf((1+study["design"]["confidence_level"])/2)
        independent=2*z*np.sqrt(study["pairing"]["counterfactual_independent_variance"]/n)
        paired_theory=2*z*np.sqrt(study["pairing"]["paired_variance"]/n)
        axes[0].loglog(n,paired_theory,"--",label="Paired known-variance theory")
        axes[0].loglog(n,independent,"s--",label="Independent known-variance theory")
    axes[0].set(xlabel="Paths per strategy",ylabel="Mean interval width (currency)",title="Pairing precision at equal per-strategy n")
    axes[0].legend(fontsize=8)
    if all(r["paired_ci_excludes_zero_fraction"] is not None for r in rows):
        axes[1].plot(n,[r["paired_ci_excludes_zero_fraction"] for r in rows],"o-")
    axes[1].set_xscale("log")
    axes[1].set(xlabel="Paths per replicate",ylabel="Fraction of paired intervals excluding zero",ylim=(-.03,1.03),
        title="Precision for a mean-cost difference\nThis does not test the weighted-objective difference")
    fig.savefig(output/"04-pairing-and-precision.png");plt.close(fig)

def research_note(study):
    confidence=study["design"]["confidence_level"];r=study["replicate_count"];maxn=max(study["design"]["sample_sizes"])
    lines=["# Multi-seed statistical validation of an execution simulator","",
        "## Research question","",
        "Do simulated cost moments and confidence intervals behave as predicted when the random stream changes and the number of paths grows? How much does shared-path pairing improve the precision of a cost-difference estimate?","",
        "## Fixed design and dependence","",
        f"{r} prespecified distinct integer seeds; nested sample sizes {study['design']['sample_sizes']}. Simulate {maxn:,} paths once per seed, using prefixes for smaller sizes. There are {study['unique_market_paths']:,} maximum-size market paths, not the sum of nested sample counts. Each strategy shares prices with the other.",
        "The full seed list is stored before simulation; no seed, batch or interval is selected based on favorable results. Across replicates, separate pseudorandom streams are used. Independence is a simulation assumption; prefixes within a seed and statistics across strategies are correlated.",
        "Integer schedules, financial configuration and preference are fixed. This examines Monte Carlo error under the same model, not parameter-estimation error, model misspecification, real-market performance or a new execution algorithm.",
        "SeedSequence child states were deterministically mapped to distinct uint32 integer seeds because the core accepts integer seeds. This uses NumPy's seeding machinery but does not pass full child objects to the core. [NumPy random-stream documentation](https://numpy.org/doc/2.3/reference/random/parallel.html).","",
        "## Statistical methods","",
        "For n independent Gaussian cost draws, estimate mean and unbiased variance (ddof=1). The mean interval is sample mean +/- t_(1-alpha/2,n-1)*sample std/sqrt(n). The variance interval is [(n-1)*s^2/chi2_(1-alpha/2,n-1), (n-1)*s^2/chi2_(alpha/2,n-1)]. The Gaussian assumption follows from fixed inventories applied linearly to Gaussian price innovations in the algebraic model. [SciPy Student-t distribution](https://docs.scipy.org/doc/scipy-1.16.2/reference/generated/scipy.stats.t.html), [NIST variance interval derivation](https://www.itl.nist.gov/div898/handbook/eda/section3/eda358.htm).",
        "Aggregate bias and root mean squared error (RMSE) across all prespecified replicates separately for each sample size and channel. Mean RMSE theory is population std/sqrt(n); relative variance RMSE theory is sqrt(2/(n-1)). Finite-replicate measurements fluctuate; a single path-prefix mean error need not decrease monotonically.",
        "At each size/channel, coverage is the fraction of replicate intervals containing the known analytic moment. Exact Clopper-Pearson binomial intervals quantify uncertainty in that fraction. Do not pool correlated sizes/channels, require every interval to cover, or interpret multiple marginal intervals as simultaneous coverage. Degenerate zero-variance channels have point intervals and target coverage one. [SciPy exact binomial interval documentation](https://docs.scipy.org/doc/scipy-1.16.2/reference/generated/scipy.stats._result_classes.BinomTestResult.proportion_ci.html).",
        "If any batch at a sample size has invalid prices, nominal unconditional coverage at that size is suppressed for all channels. All-path moments remain algebraic diagnostics and no Gaussian interval is assigned to the truncated surviving samples. Invalid paths are kept without clipping or resampling.","",
        "## Paired precision and financial interpretation","",
        f"Analytic paired expected cost difference AC-minus-TWAP: {study['theory']['paired']['mean']:.6f}. Analytic weighted-objective difference: {study['financial_comparison']['analytic_objective_delta']:.6f}. These are different quantities.",
        f"Paired cost-difference variance: {study['pairing']['paired_variance']:.6f}; an independent-strategy comparison at equal per-strategy n would have variance {study['pairing']['counterfactual_independent_variance']:.6f}. Independent/paired variance ratio: {study['pairing']['independent_over_paired_variance']}. The independent comparison is calculated analytically; it is not an additional simulated experiment.",
        "The covariance of costs under common paths reduces the variance of their difference. Plot comparators use known-population-variance Gaussian interval widths; the empirical paired widths use Student-t intervals with estimated variance. These methods differ slightly at finite n. More precise mean-cost intervals do not establish real-market superiority or quantify a weighted-objective confidence interval. Synthetic currency units are not calibrated GBP/HKD forecasts.","",
        "## Results","",
        "| Paths per seed | Paired mean RMSE | Theory RMSE | Average paired mean interval width | Mean coverage (exact binomial interval) | Variance coverage (exact binomial interval) |",
        "|---:|---:|---:|---:|---:|---:|"]
    for a in study["aggregates"]:
        if a["channel"]=="paired":
            def fmt(v,d=3):return "not reported" if v is None else f"{v:.{d}f}"
            mc="not reported" if a["mean_coverage_interval"] is None else f"{a['mean_coverage']:.3f} [{a['mean_coverage_interval'][0]:.3f}, {a['mean_coverage_interval'][1]:.3f}]"
            vc="not reported" if a["variance_coverage_interval"] is None else f"{a['variance_coverage']:.3f} [{a['variance_coverage_interval'][0]:.3f}, {a['variance_coverage_interval'][1]:.3f}]"
            lines.append(f"| {a['sample_size']} | {fmt(a['mean_rmse'])} | {fmt(a['theoretical_mean_rmse'])} | {fmt(a['mean_interval_average_width'])} | {mc} | {vc} |")
    lines += ["",f"Descriptive log-log mean-RMSE slopes: {study['convergence']['mean_rmse_loglog_slopes']}; theoretical slope -0.5. The four nested sample sizes are correlated, so this fit carries no regression p-value or independent-point uncertainty claim.",
        "All individual results, coverage success counts and exact coverage uncertainty intervals appear in results.json and CSV. Coverage misses are retained, not treated as bugs merely for missing the theoretical moment.",
        "","## Verification and provenance","",
        f"All prespecified seeds retained: {study['verification']['retained_all_prespecified_seeds']}; all direct accounting reconciliations passed: {study['verification']['all_accounting_reconciled']}; invalid maximum-size path occurrences: {study['verification']['invalid_path_occurrences']}.",
        "raw-costs.npz retains both maximum-size cost arrays and validity masks for every seed. Prices and innovations are regenerated from the recorded configuration, integer seed and pinned runtime; their SHA256 hashes are recorded per replicate (C-contiguous little-endian float64 bytes). Thus full raw price matrices need not be duplicated in the archive.",
        "Source and input digests, core commit/digest, versions and output byte hashes accompany the data. An independent verification regenerates every seed, reconstructs costs and masks, and checks stored statistics. Repeating into a fresh directory must reproduce numeric records and raw arrays in the same environment; creation timestamps may differ.",
        "","## Limits","",
        "The fixed simple model assumes arithmetic Brownian reference prices, linear temporary impact, guaranteed fills, no spread/fees/permanent impact and no liquidity constraints. Normal-cost calibration is a model-specific check. Running more paths narrows simulation error; it does not fix an incorrect financial model. A nominal 95% mean interval is not a 95% prediction interval for a new realized cost or real-market execution.",
        "Finite seed counts produce coverage-estimation uncertainty. Nested sizes, pairing and selected plotted examples are explicitly accounted for; all seeds are shown rather than a best seed. This is statistical verification of a research prototype, not evidence of predictive trading returns.",""]
    return "\n".join(lines)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--design",type=Path,required=True);parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):parser.error("choose a new or empty output directory")
    source=args.design.read_bytes();design=json.loads(source)
    study,raw=run_study(design)
    study["provenance"]["prespecified_input_sha256"]=hashlib.sha256(source).hexdigest()
    export_study(study,raw,args.output)
    print(json.dumps({"replicates":study["replicate_count"],"nested_batches":study["nested_batch_count"],
        "unique_market_paths":study["unique_market_paths"],"verification":study["verification"]},allow_nan=False))

if __name__=="__main__":main()
