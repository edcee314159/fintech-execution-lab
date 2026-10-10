"""Estimated-parameter policies evaluated under fixed true execution-model parameters."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from numbers import Real
from pathlib import Path
import numpy as np
from scipy.stats import t
from execution_lab.config import ExecutionConfig
from execution_lab.schedule import make_ac, make_twap
from execution_lab.metrics import predictions
from execution_lab.simulation import run_paired
from execution_lab.export import _provenance

MAX_STUDY_CELLS=40_000_000

def _grid(values,name,*,positive=True):
    if not values or any(isinstance(v,bool) or not isinstance(v,Real) or not np.isfinite(v) or (v<=0 if positive else v<0) for v in values):
        raise ValueError(name+" must be finite positive values" if positive else name+" must be finite nonnegative values")
    if len(set(values))!=len(values) or list(values)!=sorted(values):
        raise ValueError(name+" must be increasing and unique")

def enumerate_cases(design):
    if design.get("schema_version")!="1.0":
        raise ValueError("unsupported schema")
    base=ExecutionConfig.from_dict(design["base_true"])
    risks=design["risk_aversions"];sigmas=design["sigma_ratios"];impacts=design["impact_ratios"]
    _grid(risks,"risk grid",positive=False);_grid(sigmas,"sigma ratios");_grid(impacts,"impact ratios")
    scenarios=design["true_scenarios"];supplemental=design.get("supplemental_cases",[])
    if not scenarios or len({s["name"] for s in scenarios})!=len(scenarios):
        raise ValueError("true scenario names must be nonempty and unique")
    count=len(scenarios)*len(risks)*len(sigmas)*len(impacts)+len(supplemental)+len(scenarios)*len(risks)
    if count*base.trials*(base.intervals+1)>MAX_STUDY_CELLS:
        raise ValueError("study budget exceeded")
    settings={}
    for s in scenarios:
        changes=s["changes"]
        if len(changes)>1 or set(changes)-{"volatility","impact"}:
            raise ValueError("true scenarios must use one-factor volatility or impact changes")
        c=ExecutionConfig.from_dict({**base.to_dict(),**changes})
        if c.volatility<=0:
            raise ValueError("true volatility must be positive for ratio-based forecasting diagnostics")
        settings[s["name"]]=c.to_dict()
    cases=[]
    def add(name,scenario,risk,sigma_ratio,impact_ratio,role):
        _grid([sigma_ratio],"sigma ratio");_grid([impact_ratio],"impact ratio")
        if scenario not in settings:
            raise ValueError("unknown true scenario")
        true=ExecutionConfig.from_dict({**settings[scenario],"risk_aversion":risk})
        estimated=ExecutionConfig.from_dict({**true.to_dict(),"volatility":true.volatility*sigma_ratio,"impact":true.impact*impact_ratio})
        cases.append({"id":f"case_{len(cases):03d}","name":name,"role":role,"scenario":scenario,
            "risk_aversion":risk,"sigma_ratio":sigma_ratio,"impact_ratio":impact_ratio,
            "true_config":true.to_dict(),"estimated_config":estimated.to_dict(),
            "coefficient_ratio":sigma_ratio**2/impact_ratio})
    for s in scenarios:
        for risk in risks:
            for sr in sigmas:
                for ir in impacts:
                    add(f"{s['name']}_lambda{risk:g}_sigma{sr:g}_eta{ir:g}",s["name"],risk,sr,ir,"main")
    if len({s["name"] for s in supplemental})!=len(supplemental):
        raise ValueError("supplemental names must be unique")
    for s in supplemental:
        if s["risk_aversion"] not in risks:
            raise ValueError("supplemental risk preference must be in the prespecified grid")
        add(s["name"],s["scenario"],s["risk_aversion"],s["sigma_ratio"],s["impact_ratio"],"supplemental")
    return cases

def _stats(values,label,*,inferential=True):
    out={"label":label,"count":int(values.size),"mean":None,"variance":None,"std":None,"standard_error":None,"ci95_mean":None}
    if values.size<2:
        return out
    mean=float(np.mean(values));var=float(np.var(values,ddof=1))
    out.update(mean=mean,variance=var,std=float(np.sqrt(var)))
    if inferential:
        se=float(np.sqrt(var/values.size));radius=float(t.ppf(.975,values.size-1))*se if var else 0.
        out.update(standard_error=se,ci95_mean=[mean-radius,mean+radius])
    return out

def _plan(schedule,true,estimated=None):
    q=schedule.quantities;inventory=schedule.inventory
    out={"quantity_mode":"integer_approximation" if schedule.integer else "continuous_reference",
        "quantities":q.tolist(),"inventory":inventory.tolist(),"true_prediction":predictions(true,schedule),
        "fraction_before_quarter":float(q[np.arange(true.intervals)*true.tau<true.duration/4].sum()/true.quantity)}
    if estimated is not None:
        out["forecast"]=predictions(estimated,schedule)
    return out

def _paired(estimated,comparison,mask,true,estimated_schedule,comparison_schedule):
    delta=estimated-comparison
    all_valid=bool(mask.all())
    prediction={"mean":float(predictions(true,estimated_schedule)["mean"]-predictions(true,comparison_schedule)["mean"]),
        "variance":float(true.volatility**2*true.tau*np.sum((estimated_schedule.inventory[1:]-comparison_schedule.inventory[1:])**2))}
    return {"direction":"estimated_policy_minus_comparison","prediction":prediction,
        "empirical":_stats(delta[mask],"all_model_paths" if all_valid else "conditional_three_strategy_valid_paths"),
        "all_paths":_stats(delta,"all_model_paths" if all_valid else "outside_model_algebraic_diagnostics",inferential=all_valid)}

def run_study(design):
    specs=enumerate_cases(design)
    cases=[];anchors={};anchor_lookup={};anchor_objects={};markets={};raw={}
    losses=[];cancellation_diffs=[]
    for spec in specs:
        true=ExecutionConfig.from_dict(spec["true_config"])
        estimated=ExecutionConfig.from_dict(spec["estimated_config"])
        anchor_key=json.dumps(true.to_dict(),sort_keys=True)
        if anchor_key not in anchor_lookup:
            aid=f"anchor_{len(anchors):03d}"
            oracle=make_ac(true);twap=make_twap(true)
            oe=run_paired(true,{"twap":twap,"ac_simplified":oracle})
            mk=(true.volatility,true.price,true.trials,true.intervals,true.duration,true.seed)
            if mk not in markets:
                markets[mk]=f"market_{len(markets):02d}"
                raw[markets[mk]+"_prices"]=oe.prices
                raw[markets[mk]+"_innovations"]=oe.price_innovations
            market_key=markets[mk]
            np.testing.assert_array_equal(raw[market_key+"_prices"],oe.prices)
            raw[aid+"_oracle_costs"]=oe.costs["ac_simplified"]
            raw[aid+"_twap_costs"]=oe.costs["twap"]
            raw[aid+"_valid"]=oe.valid_pairs
            anchors[aid]={"id":aid,"scenario":spec["scenario"],"true_config":true.to_dict(),"market_key":market_key,
                "oracle_continuous":_plan(make_ac(true,integer=False),true),
                "oracle_integer":_plan(oracle,true),"twap_integer":_plan(twap,true),
                "twap_continuous":_plan(make_twap(true,integer=False),true),
                "accounting":oe.accounting,"invalid_reasons":oe.invalid_reasons}
            anchor_objects[aid]=(oe,oracle,twap)
            anchor_lookup[anchor_key]=aid
        aid=anchor_lookup[anchor_key];anchor=anchors[aid]
        oe,oracle,twap=anchor_objects[aid]
        schedule=make_ac(estimated);continuous=make_ac(estimated,integer=False)
        ee=run_paired(true,{"twap":twap,"ac_simplified":schedule})
        # Financial moments and simulation use true parameters, never the estimating configuration.
        np.testing.assert_array_equal(ee.prices,oe.prices)
        np.testing.assert_array_equal(ee.price_innovations,oe.price_innovations)
        np.testing.assert_array_equal(ee.costs["twap"],oe.costs["twap"])
        common=ee.valid_pairs & oe.valid_pairs
        raw[spec["id"]+"_costs"]=ee.costs["ac_simplified"]
        raw[spec["id"]+"_estimated_pair_valid"]=ee.valid_pairs
        raw[spec["id"]+"_valid"]=common
        nvalid=int(common.sum());status="valid" if nvalid==true.trials else ("invalid_model" if nvalid==0 else "partially_invalid")
        continuous_plan=_plan(continuous,true,estimated)
        integer_plan=_plan(schedule,true,estimated)
        jc=anchor["oracle_continuous"]["true_prediction"]["objective"]
        ji=anchor["oracle_integer"]["true_prediction"]["objective"]
        regret=continuous_plan["true_prediction"]["objective"]-jc
        iloss=integer_plan["true_prediction"]["objective"]-jc
        tolerance=1e-9*max(abs(jc),1)
        if regret < -tolerance or iloss < -tolerance:
            raise AssertionError("true continuous oracle lower bound failed")
        losses.append(regret)
        if spec["role"]=="supplemental" and np.isclose(spec["coefficient_ratio"],1,rtol=1e-12,atol=1e-15):
            delta=np.max(np.abs(np.array(continuous_plan["quantities"])-np.array(anchor["oracle_continuous"]["quantities"])))/true.quantity
            cancellation_diffs.append(float(delta))
            if delta>1e-10:
                raise AssertionError("parameter error cancellation failed")
        all_valid=bool(common.all())
        stats={}
        for name,costs in [("estimated_policy",ee.costs["ac_simplified"]),("oracle_rounded",oe.costs["ac_simplified"]),("twap",oe.costs["twap"])]:
            empirical=_stats(costs[common],"all_model_paths" if all_valid else "conditional_three_strategy_valid_paths")
            stats[name]={"empirical":empirical,"all_paths":_stats(costs,"all_model_paths" if all_valid else "outside_model_algebraic_diagnostics",inferential=all_valid),
                "empirical_objective":None if empirical["mean"] is None else empirical["mean"]+true.risk_aversion*empirical["variance"],
                "empirical_objective_ci":None}
        emap={r["pair_index"]:r for r in ee.invalid_reasons}
        omap={r["pair_index"]:r for r in oe.invalid_reasons}
        invalid=[{"pair_index":int(i),"estimated_policy_pair":emap.get(int(i)),"oracle_pair":omap.get(int(i))} for i in np.flatnonzero(~common)]
        forecast=integer_plan["forecast"];actual=integer_plan["true_prediction"]
        forecast_ratios={"mean":forecast["mean"]/actual["mean"],
            "variance":forecast["variance"]/actual["variance"] if actual["variance"] else None}
        if not np.isclose(forecast_ratios["mean"],spec["impact_ratio"],rtol=1e-12):
            raise AssertionError("forecast cost scaling failed")
        if forecast_ratios["variance"] is not None and not np.isclose(forecast_ratios["variance"],spec["sigma_ratio"]**2,rtol=1e-12):
            raise AssertionError("forecast variance scaling failed")
        cases.append({**spec,"anchor_id":aid,"continuous":continuous_plan,"integer":integer_plan,
            "continuous_regret":regret,"continuous_regret_pct":100*regret/jc,
            "integer_loss_vs_continuous_oracle":iloss,"integer_loss_vs_continuous_oracle_pct":100*iloss/jc,
            "integer_gap_vs_rounded_oracle":actual["objective"]-ji,
            "integer_gap_vs_rounded_oracle_pct":100*(actual["objective"]-ji)/ji,
            "forecast_ratios":forecast_ratios,
            "integer_objective_vs_twap_pct":100*(actual["objective"]/anchor["twap_integer"]["true_prediction"]["objective"]-1),
            "status":status,"total_paths":true.trials,"valid_paths":nvalid,"invalid_paths":true.trials-nvalid,
            "empirical":stats,"paired_vs_oracle":_paired(ee.costs["ac_simplified"],oe.costs["ac_simplified"],common,true,schedule,oracle),
            "paired_vs_twap":_paired(ee.costs["ac_simplified"],oe.costs["twap"],common,true,schedule,twap),
            "invalid_reasons":invalid,"accounting":ee.accounting})
    correct=[r for r in cases if r["sigma_ratio"]==r["impact_ratio"]==1]
    correct_match=all(r["integer"]["quantities"]==anchors[r["anchor_id"]]["oracle_integer"]["quantities"] and abs(r["continuous_regret"])<=1e-9 for r in correct)
    if not correct_match:
        raise AssertionError("correct estimates did not recover oracle")
    provenance=_provenance()
    provenance["study_source_sha256"]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return {"schema_version":"1.0","study_name":"Execution-policy robustness under parameter misspecification",
        "design":design,"provenance":provenance,"independent_base_paths":design["base_true"]["trials"],
        "main_conditions":sum(r["role"]=="main" for r in cases),"total_conditions":len(cases),"oracle_anchor_count":len(anchors),
        "cases":cases,"anchors":anchors,
        "sampling_note":"One bank of independent standardized Gaussian paths reused across correlated conditions; no addition of condition trial counts.",
        "objective_note":"All outcome objectives use the true parameters and the same specified lambda. Oracle continuous is a model lower bound. Rounded oracle is a feasible reference, not a globally optimal integer solver. Mean-cost CIs are not objective-loss CIs.",
        "verification":{"correct_estimates_recover_oracle":correct_match,
            "continuous_oracle_lower_bound_checked":True,
            "min_continuous_regret":min(losses),
            "max_cancellation_normalized_difference":max(cancellation_diffs,default=0),
            "cancellation_conditions_checked":len(cancellation_diffs),
            "invalid_case_path_occurrences":sum(r["invalid_paths"] for r in cases),
            "all_accounting_reconciled":all(v["reconciled_within_roundoff"] for r in cases for v in r["accounting"]["strategies"].values()) and all(v["reconciled_within_roundoff"] for a in anchors.values() for v in a["accounting"]["strategies"].values())}},raw

def _write_json(path,value):
    path.write_text(json.dumps(value,indent=2,allow_nan=False)+"\n",encoding="utf-8",newline="\n")

def export_study(study,raw,output,*,figures=True):
    output=Path(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("output must be empty; choose a new directory")
    output.mkdir(parents=True,exist_ok=True)
    _write_json(output/"results.json",study);_write_json(output/"design.json",study["design"])
    np.savez_compressed(output/"raw-paths.npz",**raw)
    fields=["case_id","role","scenario","lambda","sigma_est_over_true","eta_est_over_true","coefficient_ratio",
        "continuous_true_mean","continuous_true_variance","continuous_true_objective","continuous_oracle_objective",
        "continuous_regret_pct","integer_true_mean","integer_true_variance","integer_true_objective",
        "integer_gap_vs_rounded_oracle_pct","integer_loss_vs_continuous_oracle_pct","integer_objective_vs_twap_pct",
        "forecast_mean","forecast_variance","fraction_before_quarter","status","valid_paths",
        "empirical_mean","empirical_variance","empirical_objective","paired_mean_vs_oracle","paired_mean_ci95_low","paired_mean_ci95_high"]
    with (output/"metrics.csv").open("w",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fields,lineterminator="\n");writer.writeheader()
        for r in study["cases"]:
            cp=r["continuous"]["true_prediction"];ip=r["integer"]["true_prediction"];fp=r["integer"]["forecast"]
            oracle=study["anchors"][r["anchor_id"]]["oracle_continuous"]["true_prediction"]
            emp=r["empirical"]["estimated_policy"]["empirical"];paired=r["paired_vs_oracle"]["empirical"]
            ci=paired["ci95_mean"] or [None,None]
            writer.writerow(dict(zip(fields,[r["id"],r["role"],r["scenario"],r["risk_aversion"],r["sigma_ratio"],r["impact_ratio"],r["coefficient_ratio"],
                cp["mean"],cp["variance"],cp["objective"],oracle["objective"],r["continuous_regret_pct"],
                ip["mean"],ip["variance"],ip["objective"],r["integer_gap_vs_rounded_oracle_pct"],r["integer_loss_vs_continuous_oracle_pct"],r["integer_objective_vs_twap_pct"],
                fp["mean"],fp["variance"],r["integer"]["fraction_before_quarter"],r["status"],r["valid_paths"],
                emp["mean"],emp["variance"],r["empirical"]["estimated_policy"]["empirical_objective"],paired["mean"],*ci])))
    (output/"research-note.md").write_text(research_note(study),encoding="utf-8",newline="\n")
    if figures:render_figures(study,output)
    _write_json(output/"manifest.json",{"sha256":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.iterdir()) if p.is_file()}})
    return output

def _focus_rows(study,risk=None):
    risk=study["design"]["base_true"]["risk_aversion"] if risk is None else risk
    return [r for r in study["cases"] if r["role"]=="main" and r["scenario"]=="baseline" and r["risk_aversion"]==risk]

def render_figures(study,output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size":10,"axes.spines.top":False,"axes.spines.right":False,"figure.dpi":140})
    sr=study["design"]["sigma_ratios"];ir=study["design"]["impact_ratios"];risks=study["design"]["risk_aversions"]
    if not _focus_rows(study,risks[0]):return
    def matrix(rows,field):
        return np.array([[next(r[field] for r in rows if r["sigma_ratio"]==s and r["impact_ratio"]==e) for e in ir] for s in sr])
    values=[matrix(_focus_rows(study,risk),"continuous_regret_pct") for risk in risks]
    fig,axes=plt.subplots(1,len(risks),figsize=(4*len(risks)+1,4.7),layout="constrained",squeeze=False)
    upper=max(float(v.max()) for v in values)
    for ax,risk,m in zip(axes[0],risks,values):
        im=ax.imshow(m,origin="lower",vmin=0,vmax=max(upper,1e-12),cmap="YlOrRd")
        ax.set(xticks=np.arange(len(ir)),xticklabels=[f"{v:g}x" for v in ir],yticks=np.arange(len(sr)),yticklabels=[f"{v:g}x" for v in sr],
            xlabel="Estimated / true impact",ylabel="Estimated / true volatility",title=f"lambda = {risk:g}")
        for y in range(len(sr)):
            for x in range(len(ir)):
                ax.text(x,y,f"{m[y,x]:.2f}%",ha="center",va="center",color="white" if m[y,x]>.6*upper else "black",fontsize=9)
    fig.colorbar(im,ax=axes[0].tolist(),label="True continuous objective loss vs oracle (%)",shrink=.8)
    fig.suptitle("Parameter errors: baseline market; shared true objective within each panel")
    fig.savefig(output/"01-objective-loss-heatmaps.png");plt.close(fig)

    rows=_focus_rows(study);anchor=study["anchors"][rows[0]["anchor_id"]]
    fig,ax=plt.subplots(figsize=(9,5.5),layout="constrained")
    for r in rows:
        p=r["integer"]["true_prediction"]
        if r["sigma_ratio"]==r["impact_ratio"]==1:continue
        ax.scatter(p["std"],p["mean"],s=40,c=np.log2(r["coefficient_ratio"]),cmap="coolwarm",vmin=-3,vmax=3)
    # Label distinct coefficient ratios once; coincident policies are not separate shapes.
    seen=set()
    for r in sorted(rows,key=lambda r:r["coefficient_ratio"]):
        key=round(r["coefficient_ratio"],10)
        if key in seen or key==1:continue
        seen.add(key);p=r["integer"]["true_prediction"]
        offset={.125:(-90,64),.25:(-88,42),.5:(-75,22)}.get(key,(7,7))
        ax.annotate(f"c_hat/c={key:g}",(p["std"],p["mean"]),xytext=offset,textcoords="offset points",fontsize=9,
            arrowprops={"arrowstyle":"-","lw":.6,"color":"0.5"} if key<1 else None)
    for name,marker,label in [("oracle_integer","*","Oracle rounded (true parameters)"),("twap_integer","s","Integer TWAP")]:
        p=anchor[name]["true_prediction"]
        ax.scatter(p["std"],p["mean"],marker=marker,s=160,color="black",label=label,zorder=6)
    ax.set(xlabel="True cost standard deviation (currency)",ylabel="True expected cost (currency)",
        title=f"Estimated-parameter plans evaluated in the same true market\nlambda={rows[0]['risk_aversion']:g}; lower mean cost alone is not lower objective")
    ax.margins(x=.12,y=.12)
    ax.legend(fontsize=9);fig.savefig(output/"02-true-cost-risk.png");plt.close(fig)

    fig,axes=plt.subplots(1,2,figsize=(10,4.7),layout="constrained")
    for ax,key,title in [(axes[0],"mean","Forecast / true expected cost"),(axes[1],"variance","Forecast / true cost variance")]:
        m=np.array([[next(r["forecast_ratios"][key] for r in rows if r["sigma_ratio"]==s and r["impact_ratio"]==e) for e in ir] for s in sr])
        im=ax.imshow(m,origin="lower",cmap="coolwarm",norm=matplotlib.colors.LogNorm(vmin=.25,vmax=4))
        ax.set(xticks=np.arange(len(ir)),xticklabels=[f"{v:g}x" for v in ir],yticks=np.arange(len(sr)),yticklabels=[f"{v:g}x" for v in sr],
            xlabel="Estimated / true impact",ylabel="Estimated / true volatility",title=title)
        for y in range(len(sr)):
            for x in range(len(ir)):ax.text(x,y,f"{m[y,x]:g}x",ha="center",va="center")
        colorbar=fig.colorbar(im,ax=ax,shrink=.8,ticks=[.25,.5,1,2,4])
        colorbar.ax.set_yticklabels(["0.25x","0.5x","1x","2x","4x"])
    fig.suptitle("Same integer plan: forecasts use estimates; outcomes use true parameters")
    fig.savefig(output/"03-forecast-miscalibration.png");plt.close(fig)

    fig,ax=plt.subplots(figsize=(10,5),layout="constrained")
    scenarios=study["design"]["true_scenarios"];x=np.arange(len(scenarios));width=.8/len(risks)
    for index,risk in enumerate(risks):
        maxima=[max(r["continuous_regret_pct"] for r in study["cases"] if r["role"]=="main" and r["scenario"]==s["name"] and r["risk_aversion"]==risk) for s in scenarios]
        ax.bar(x-.4+width/2+index*width,maxima,width,label=f"lambda={risk:g}")
    ax.set(xticks=x,xticklabels=[s["name"].replace("_"," ") for s in scenarios],ylabel="Max continuous objective loss vs oracle (%)",
        title="Largest loss within the prespecified 3x3 estimation-error grid\nEach comparison holds the true scenario and lambda fixed")
    ax.legend(loc="upper left",bbox_to_anchor=(1.01,1),fontsize=9);fig.savefig(output/"04-grid-loss-by-market.png");plt.close(fig)

    extra=[r for r in study["cases"] if r["role"]=="supplemental"]
    cancellation=[r for r in extra if np.isclose(r["coefficient_ratio"],1)]
    if cancellation:
        correct=next(r for r in rows if r["sigma_ratio"]==r["impact_ratio"]==1)
        selected=[correct]+cancellation
        fig,axes=plt.subplots(1,2,figsize=(11,4.6),layout="constrained")
        for index,r in enumerate(selected):
            c=r["true_config"];times=np.arange(c["intervals"])*c["duration"]/c["intervals"]
            fraction=np.array(r["continuous"]["quantities"])/c["quantity"]
            label=f"sigma ratio={r['sigma_ratio']:g}, impact ratio={r['impact_ratio']:g}"
            if index==0:axes[0].plot(times,fraction,color="black",label=label)
            else:axes[0].scatter(times[index::4],fraction[index::4],marker=["o","s"][index%2],facecolors="none",edgecolors=["tab:blue","tab:orange"][index%2],s=30,label=label)
        xx=np.arange(len(selected))
        axes[1].bar(xx-.18,[r["forecast_ratios"]["mean"] for r in selected],.36,label="Expected cost")
        axes[1].bar(xx+.18,[r["forecast_ratios"]["variance"] for r in selected],.36,label="Cost variance")
        axes[1].axhline(1,color="black",ls="--",lw=1)
        axes[1].set(xticks=xx,xticklabels=["Correct"]+[r["name"].replace("_"," ") for r in cancellation],ylabel="Forecast / true moment",title="Same decisions can hide inaccurate forecasts")
        axes[0].set(xlabel="Trade time (minutes)",ylabel="Normalized continuous quantity",title="Errors cancel in the schedule coefficient")
        axes[0].legend(fontsize=8);axes[1].legend(fontsize=8)
        fig.savefig(output/"05-cancellation-not-calibration.png");plt.close(fig)

def research_note(study):
    rows=_focus_rows(study)
    focus=next((r for r in rows if r["sigma_ratio"]==r["impact_ratio"]==1),None)
    lines=["# Execution-policy robustness under parameter misspecification","",
        "## Research question","",
        "If a trader estimates volatility or temporary market impact incorrectly, how much does the resulting fixed execution schedule lose when evaluated under the true model, and how misleading are its forecasts?","",
        "## Prespecified design","",
        f"{study['main_conditions']} main conditions and {study['total_conditions']-study['main_conditions']} supplemental cancellation checks; {study['oracle_anchor_count']} cached true-parameter oracle/TWAP anchors. Each condition uses {study['independent_base_paths']:,} independent Gaussian paths. One bank of standardized draws is reused across correlated conditions, not added up as independent samples.",
        "Five true market scenarios change only true volatility or impact relative to baseline. Three fixed risk preferences and a 3x3 grid of volatility/impact estimate-to-truth ratios are specified before execution. Supplemental ratios are labelled off-grid. No parameters are estimated from historical observations: these are controlled misspecification experiments.",
        "Risk preference lambda is treated as known. Quantity, horizon, interval timing and price-path specification are held fixed. Estimate-to-truth ratios describe a hindsight error, not information a real trader necessarily knows.",
        "","## Policy construction and true evaluation","",
        "Construct a continuous optimizer from estimated sigma and eta, then derive a feasible integer approximation with the core's deterministic rounding. Evaluate both plans using true sigma and eta. The true-parameter continuous oracle is the model lower bound; its integerized plan is only a rounded reference, not a globally optimal integer solution.",
        "Trade at interval starts. With tau=T/N, E_true[C]=(eta_true/tau)*sum(n_k^2), Var_true[C]=sigma_true^2*tau*sum(x_k^2), k=1,...,N. J_true=E_true[C]+lambda*Var_true[C]. Every comparison to oracle/TWAP holds true parameters and lambda fixed.",
        "Continuous regret is J_true(estimated continuous plan)-J_true(continuous oracle); the relative loss divides by the positive continuous oracle objective. Integer loss against the continuous oracle includes rounding. The signed integer gap against the rounded oracle is reported separately and is not mathematically guaranteed nonnegative.",
        "Lower expected cost need not mean a lower weighted objective. Mean-cost paired intervals quantify only mean-cost differences; they are not confidence intervals for objective loss. Empirical mean-plus-lambda-times-sample-variance is recorded without an objective confidence interval.",
        "Currency is an arbitrary consistent model unit; no GBP/HKD or real-market calibration is implied.",""]
    if focus:
        oracle=study["anchors"][focus["anchor_id"]]["oracle_integer"]["true_prediction"]
        lines += [f"## Baseline results at lambda={focus['risk_aversion']:g}","",
            f"Rounded oracle true expected cost: {oracle['mean']:.2f}; cost variance: {oracle['variance']:.2f}; weighted objective: {oracle['objective']:.2f}.",
            "","| Sigma estimate / true | Impact estimate / true | True expected cost, integer | True cost std, integer | Continuous loss vs oracle | Forecast variance / true |",
            "|---:|---:|---:|---:|---:|---:|"]
        for r in rows:
            p=r["integer"]["true_prediction"]
            lines.append(f"| {r['sigma_ratio']:g} | {r['impact_ratio']:g} | {p['mean']:.2f} | {p['std']:.2f} | {r['continuous_regret_pct']:.2f}% | {r['forecast_ratios']['variance']:g} |")
        worst=max(rows,key=lambda r:r["continuous_regret_pct"])
        main=[r for r in study["cases"] if r["role"]=="main"]
        w=max(main,key=lambda r:r["continuous_regret_pct"])
        lines += ["",f"The largest continuous loss in the baseline 3x3 grid at lambda={focus['risk_aversion']:g} is {worst['continuous_regret_pct']:.2f}% at sigma ratio {worst['sigma_ratio']:g}, impact ratio {worst['impact_ratio']:g}.",
            f"Across the full prespecified main grid, the largest loss is {w['continuous_regret_pct']:.2f}% in {w['scenario']} at lambda={w['risk_aversion']:g}, sigma ratio={w['sigma_ratio']:g}, impact ratio={w['impact_ratio']:g}. This is a sampled-grid maximum, not an unrestricted worst-case bound.",
            "Higher volatility estimates or lower impact estimates produce more urgent plans. Underestimating volatility often lowers immediate impact cost while retaining more price exposure. The loss depends on true parameters and preference; comparisons cannot rank different true markets as universally superior.",""]
    lines += ["## Forecast errors and cancellation","",
        "For the same plan, E_hat[C]/E_true[C]=eta_hat/eta_true. Var_hat[C]/Var_true[C]=(sigma_hat/sigma_true)^2, when true variance is positive. A volatility estimate at half truth reports one quarter of true variance: a 75% understatement, not a 50% understatement.",
        "Schedule shape depends on c_hat=lambda*sigma_hat^2*tau^2/eta_hat. Joint errors cancel in decisions when (sigma_hat/sigma_true)^2/(eta_hat/eta_true)=1. Doubling estimated sigma while quadrupling estimated eta recovers the oracle schedule but overstates both expected cost and variance by four. Halving sigma and quartering eta likewise preserves the schedule but understates both moments by a factor of four. Correct decisions do not prove correct forecasts.",
        f"Supplemental cancellation cases checked: {study['verification']['cancellation_conditions_checked']}; maximum normalized continuous quantity difference: {study['verification']['max_cancellation_normalized_difference']:.3g}.","",
        "## Validation and uncertainty","",
        f"Correct estimates recover the oracle: {study['verification']['correct_estimates_recover_oracle']}. Continuous oracle lower bounds checked: {study['verification']['continuous_oracle_lower_bound_checked']}. All accounting reconciliations passed: {study['verification']['all_accounting_reconciled']}. Invalid case-path occurrences: {study['verification']['invalid_case_path_occurrences']}.",
        "All estimated-policy, rounded-oracle and TWAP costs use the same paths. The common validity mask is the intersection of both core paired experiments, so comparative empirical moments use the same three-strategy sample. Raw masks, invalid reasons and all-path costs remain in the output; no clipping or resampling.",
        "For invalid paths, all-path summaries are algebraic diagnostics without inferential intervals, and surviving-path summaries are conditional. Marginal Student-t 95% intervals concern mean-cost simulation error only, with no simultaneous coverage, true-market forecast guarantee or multiple-comparison superiority claim.",
        "","## Limits and interpretation","",
        "Constant true parameters, arithmetic Brownian reference prices with zero drift, linear temporary impact, guaranteed fills, and no liquidity, spread, fees, permanent impact, learning or market-data estimation. This is not yet a statistically estimated robust optimizer or a minimax policy.",
        "The findings can prioritize calibration checks within this model, especially the quadratic volatility-to-variance relation. They do not justify a universal claim that one parameter always matters more: error sizes, true coefficients and lambda all affect losses.",
        "","## Reproducibility","",
        "design.json preserves the fixed design; results.json stores complete true/estimated configurations, both quantity modes, all predictions, true-parameter anchors, empirical moments and invalid diagnostics. raw-paths.npz contains deduplicated market prices/innovations, benchmark costs and masks, estimated-policy costs and both pair/common masks.",
        "Reconstruct integer costs as true temporary-impact cost minus preserved innovations @ inventory[1:]. Reconstruct fills from reference prices before each trade minus true impact*n/tau. manifest.json hashes output bytes; provenance includes core/source digests and runtime versions. Repeating into a new empty directory should reproduce all numeric records and raw arrays in the same recorded environment; creation timestamps may differ.",
        "","## Reference","",
        "[Almgren and Chriss (2001), Optimal execution of portfolio transactions](https://doi.org/10.21314/JOR.2001.041). This is a simplified discrete temporary-impact model, not a reproduction of every component of the original framework.",""]
    return "\n".join(lines)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--design",type=Path,required=True);parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):parser.error("choose an empty output directory")
    source=args.design.read_bytes();design=json.loads(source)
    study,raw=run_study(design)
    study["provenance"]["prespecified_input_sha256"]=hashlib.sha256(source).hexdigest()
    export_study(study,raw,args.output)
    print(json.dumps({"conditions":study["total_conditions"],"anchors":study["oracle_anchor_count"],"verification":study["verification"]},allow_nan=False))

if __name__=="__main__":main()
