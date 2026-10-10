"""Measured interpretation and five scientific plots for the volume execution extension."""
from pathlib import Path
import math
import numpy as np

LABELS={"twap":"TWAP","volume_weighted":"Forecast-volume","ac_simplified":"AC (arrival)","ac_volume_aware":"AC (volume-aware arrival)"}
def selected(s,*,profile=None,model=None,strategy=None,benchmark="arrival",volume_case="none"):
    risk=s["design"]["base"]["risk_aversion"]
    return [r for r in s["strategy_metrics"] if r["risk_aversion"]==risk and r["benchmark"]==benchmark and r["volume_case"]==volume_case
        and (profile is None or r["profile"]==profile) and (model is None or r["impact_model"]==model) and (strategy is None or r["strategy"]==strategy)]

def write_reports(s,raw,output):
    d=s["design"];n=d["base"]["intervals"];trials=d["base"]["trials"];risk=d["base"]["risk_aversion"]
    table=["| Profile | Impact assumption | Plan | Expected arrival cost | Arrival SD | Mean + λ variance | First-quarter sold |","|---|---|---|---:|---:|---:|---:|"]
    for r in selected(s):
        p=r["prediction"]
        table.append(f"| {r['profile']} | {r['impact_model']} | {LABELS[r['strategy']]} | {p['mean']:.2f} | {p['std']:.2f} | {p['objective']:.2f} | {r['first_quarter_fraction']*100:.2f}% |")
    tracking=["| Profile | Impact assumption | Arrival SD | Matched-VWAP SD | Shifted-VWAP SD |","|---|---|---:|---:|---:|"]
    for model in d["impact_models"]:
        for profile in d["profiles"]:
            arrival=selected(s,profile=profile,model=model,strategy="volume_weighted")[0]
            matched=selected(s,profile=profile,model=model,strategy="volume_weighted",benchmark="market_vwap",volume_case="matched")[0]
            shifted=selected(s,profile=profile,model=model,strategy="volume_weighted",benchmark="market_vwap",volume_case="shifted")[0]
            tracking.append(f"| {profile} | {model} | {arrival['prediction']['std']:.2f} | {matched['prediction']['std']:.6f} | {shifted['prediction']['std']:.2f} |")
    constant=selected(s,profile="u_shape",model="constant",strategy="volume_weighted")[0]
    twap=selected(s,profile="u_shape",model="constant",strategy="twap")[0]
    inverse=selected(s,profile="u_shape",model="inverse_expected_volume",strategy="volume_weighted")[0]
    inverse_twap=selected(s,profile="u_shape",model="inverse_expected_volume",strategy="twap")[0]
    matched_u=selected(s,profile="u_shape",model="constant",strategy="volume_weighted",benchmark="market_vwap",volume_case="matched")[0]
    shifted_u=selected(s,profile="u_shape",model="constant",strategy="volume_weighted",benchmark="market_vwap",volume_case="shifted")[0]
    english=f"""# Forecast-volume execution and market-VWAP benchmarking

## Research question and implementation

Add a third schedule q_k = Q*vhat_k, where vhat is an expected, normalized market-volume curve fixed before execution. Compare it with TWAP and an arrival-objective optimizer under five synthetic volume profiles and two impact assumptions. These are static VWAP-style trajectories, not implementations of a broker's live algorithm.

VWAP is price weighted by traded volume; a trading trajectory and an ex-post price benchmark are separate objects. [IBKR VWAP definition](https://www.interactivebrokers.com/campus/glossary-terms/volume-weighted-average-price-vwap/). The industry algorithm has additional execution controls and fill uncertainty that this experiment omits. [IBKR algorithm documentation](https://www.interactivebrokers.com/docs/general/order-types/algorithmic-orders/ib-algorithms/vwap).

The original core source and its two-strategy run_paired interface remain unchanged. The extension consumes its immutable Schedule contract, validation, largest-remainder integerization, original AC/TWAP and tridiagonal solver. A separate three-schedule adapter uses the same preserved exogenous price innovations.

## Fixed design and model assumptions

{len(s['cases'])} conditions: {len(d['profiles'])} forecast profiles × {len(d['risk_aversions'])} risk preferences × 2 impact assumptions. Each uses the same {trials} IID Gaussian innovation paths, N={n} intervals over {d['base']['duration']} minutes. Price randomness is reused across all schedules and cases; import/setup does not alter the seeded generator. Every plan must sell Q={d['base']['quantity']} shares.

Profiles are flat, U-shaped, front-loaded, back-loaded and midday-peaked. They are deterministic synthetic inputs, not empirical stock-volume estimates. Relative weights do not specify total market volume or capacity.

Constant impact: a_k=eta/tau, exactly the existing financial model.
Secondary assumed liquidity relation: a_k=eta/(tau*N*vhat_k). Volume-heavy intervals have smaller temporary-impact coefficients. This relation is introduced as an assumption, not a calibrated fact. It equals the original coefficient for flat volume.

The optimizer is appropriate to each arrival-cost objective. Constant impact uses the original AC schedule. The secondary model uses a separate variable-coefficient arrival optimizer. It does not optimize VWAP-tracking variance. A generalized optimizer's continuous interior system has diagonal a_(k-1)+a_k+b, adjacent entries -a_k, b=lambda*sigma²*tau, and first RHS a_0*Q. Symmetric positive-definite structure permits the reused tridiagonal solve.

At lambda=0 the continuous cost optimum allocates inversely to a_k: uniform for constant impact, proportional to forecast volume for the assumed inverse-volume coefficient. At positive risk preference, front-loading balances impact cost against exposure. Integerized schedules are feasible approximations; retain the continuous objective as a lower bound, not a guarantee of global integer optimality.

## Two price benchmarks, three evaluation groups

Use interval-start external reference prices P_k, excluding the agent's own impacted executions. Market VWAP = sum(v_realized_k*P_k). It is a model proxy rather than transaction-by-transaction traded VWAP.

Arrival shortfall for a sell = Q*P_0 - proceeds.
Market-VWAP shortfall = Q*VWAP_market - proceeds.
Positive values mean less sale proceeds than the specified benchmark.

Let x_post be remaining inventory after each trade, and u_post remaining normalized realized volume after each interval. With preserved price increments eps:
arrival cost = sum(a*q²) - eps@x_post;
market-VWAP cost = sum(a*q²) - eps@(x_post-Q*u_post).
Expected shortfall equals deterministic impact under either benchmark. Variance is sigma²*tau times the squared norm of the corresponding exposure vector. Mean-plus-lambda-variance is evaluated separately for each benchmark; an arrival optimizer need not optimize the VWAP objective.

Evaluation groups: arrival price, matched forecast/realized market-VWAP weights, and realized weights circularly shifted by {int(round(n*d['shift_fraction']))} bins. Only the evaluation benchmark changes in the mismatch experiment. The planned quantities and the preset liquidity coefficients remain fixed. It is a tracking-error stress test, not an endogenous liquidity shock or complete stochastic volume-forecast model.

Exact matching continuous quantities cancel external VWAP price noise under the deterministic matched-volume assumption. Integer rounding leaves a small residual. This does not cancel arrival-price risk or guarantee equal realized market volumes.

## Actual analytic results at lambda={risk:g}

Costs and standard deviations are in model currency. All plans shown are integerized.

"""+ "\n".join(table)+f"""

## A measured example

For the U-shaped profile at the default risk weight, the volume plan's expected impact cost exceeds TWAP by {constant['prediction']['mean']-twap['prediction']['mean']:.2f} under constant impact. Under the separately assumed inverse-volume coefficients it is lower by {inverse_twap['prediction']['mean']-inverse['prediction']['mean']:.2f}. This change follows the explicit liquidity model, rather than a universal advantage of volume scheduling.

The same volume plan has arrival SD {constant['prediction']['std']:.2f}, matched-VWAP tracking SD {matched_u['prediction']['std']:.6f}, and shifted-VWAP tracking SD {shifted_u['prediction']['std']:.2f}. Near-zero matched tracking risk relies on the deterministic exact-volume assumption.

## Tracking versus arrival risk

"""+ "\n".join(tracking)+f"""

## Monte Carlo validation and paired inference

Export {len(s['strategy_metrics'])} strategy records and {len(s['paired_metrics'])} paired comparisons, with every cost sample and schedule retained in paths-and-schedules.npz. Compare cost to direct notional-minus-proceeds accounting under a conservative floating-point bound. Invalid case-path count: {s['verification']['total_invalid_case_paths']}; raw paths and common validity masks are preserved.

All three strategies use the same price innovations and a common mask requiring positive reference and execution prices. If any path is invalid, retain descriptive all-path and valid-subset statistics but suppress inferential intervals, avoiding conditional-selection superiority claims.

For valid experiments, Student-t 95% intervals quantify Monte Carlo uncertainty in mean shortfall and paired MEAN differences. They do not quantify uncertainty in calibrated parameters, actual execution performance, or the risk-weighted objective. No multiple-comparison family-wide significance claim is made.

For any pair, the common market-VWAP term cancels. Analytic paired variance is sigma²*tau*||x_A-x_B||² for all benchmark groups. Arrival and VWAP targets can change each strategy's individual risk while leaving the paired shortfall difference unchanged. This provides a useful accounting identity and illustrates why benchmark choice matters.

## Reproducibility and limits

Fixed design, shared market innovations, all trajectories, impact coefficients, continuous lower bounds, empirical moments, paired intervals and source/runtime digests are retained. Repeat the same design numerically; independently reconstruct proceeds, benchmark exposures, statistics and weighted linear-system solutions.

Eighteen automated cases include hand-worked weights/optima, safe normalization, invalid volume input, exact flat-profile TWAP identity, original-AC agreement, risk-neutral inverse-volume allocation, direct accounting, external-volume benchmark separation and common invalid masks.

There is no order book, partial filling, participation cap, fee/spread model, endogenous price-volume dependence, real volume-forecast learning or live execution. The extra impact relation is an explicit secondary model. Numerical evidence supports understanding of benchmarking and model assumptions, not a claim of real-market superiority.
"""
    (output/"research-note.md").write_text(english,encoding="utf-8",newline="\n")
    chinese=f"""# 预期成交量加权执行基准

现在每个实验都有三种计划：均匀分配的TWAP、现有到达价优化参照，以及按预期成交量分配的VWAP风格计划。我们研究交易目标、成交量形状与冲击假设如何共同影响结果，而不预设新策略应该胜出。

## 完成范围

- 五种预设成交量曲线、三种风险权重、两种冲击假设，共 {len(s['cases'])} 个条件。
- 每个条件用相同的 {trials} 条外生价格路径公平比较三种计划。
- 分别评价到达价、成交量匹配的市场VWAP、成交量错位的市场VWAP，输出 {len(s['strategy_metrics'])} 条策略记录、{len(s['paired_metrics'])} 条配对比较。
- 18 项自动测试通过；手算、原算法一致性、完整清仓、直接成交收入、基准价格和无效路径都有检查。
- 全部无效条件路径数为 {s['verification']['total_invalid_case_paths']}；原始数据与共同有效掩码保留。原项目核心源码未修改。

## 成交量加权计划怎样生成

计划先收到预期成交量曲线，把权重归一化为vhat，每个区间安排Q×vhat_k股，再用原项目的确定性最大余数法生成整数计划。平坦曲线会精确得到与TWAP相同的整数交易计划。权重可以按任意相同比例放大，计划不改变。

这些曲线是模拟输入。历史汇率价格数据不包含股票日内成交量，不能用它冒充本项的成交量校准。

![预期成交量曲线](01-volume-profiles.png)

![不同曲线下的三种库存计划](02-inventory-plans.png)

## 为什么同时比较两个价格基准

“按成交量交易的计划”与“市场VWAP价格”不同。市场VWAP用外部价格和市场成交量权重计算，排除自己的冲击成交价。[VWAP定义](https://www.interactivebrokers.com/campus/glossary-terms/volume-weighted-average-price-vwap/)

卖单的到达价成本是订单初始市值减成交收入；市场VWAP成本是Q×市场VWAP减成交收入。两者为同一批交易提供不同的风险评价。到达价优化参照解决前一个目标，不能直接称为VWAP跟踪的最优算法。

当未来成交量恰好等于预期、且连续交易数量精确按它分配时，计划的价格噪声与VWAP基准噪声会抵消。整数舍入留下很小误差；成交量错位会破坏抵消。即使VWAP跟踪风险接近零，到达价风险仍可能很大。

![到达价风险与VWAP跟踪风险](04-tracking-risk.png)

## 冲击假设会改变“什么计划合适”

主实验保持原来的固定冲击：每个区间的成本系数相同。此时均匀交易能降低纯冲击成本，按不均匀成交量分配并不自动更便宜。

第二组实验明确假设成交量较大的区间更有流动性，成本系数按预期成交量反比变化。为了公平，用相应的变系数三对角优化作为参照。在不考虑风险时，连续最优数量会与成交量成正比；这是该假设模型的数学结果，不是从真实市场估计出的规律。

我们保留连续最优目标值作为整数计划下界，不声称最大余数舍入得到全局整数最优。

![两种冲击假设下的到达价目标](03-arrival-objective.png)

在默认风险权重下，实际数值如下。成本、标准差与目标均为模型货币单位。

"""+ "\n".join(table)+f"""

## 一个实际结果：优势取决于假设

默认风险权重、U形曲线下，成交量计划的预期冲击成本在固定冲击模型中比TWAP高 {constant['prediction']['mean']-twap['prediction']['mean']:.2f}；在另设的反成交量冲击假设中比TWAP低 {inverse_twap['prediction']['mean']-inverse['prediction']['mean']:.2f}。同一种计划的成本优势会因流动性假设改变。

它的到达价标准差为 {constant['prediction']['std']:.2f}，成交量恰好匹配时的VWAP跟踪标准差为 {matched_u['prediction']['std']:.6f}，错位后为 {shifted_u['prediction']['std']:.2f}。跟踪得准与承担较低到达价风险是不同结论。

## 统计比较怎样理解

图中比较成交量计划减TWAP的平均成本，正值意味着同一基准下平均成本更高。区间是配对蒙特卡洛均值差的95%区间，不是实盘效果或风险加权目标差的置信区间。不要把很多比较里出现的单个区间当作整体显著性证明。

![配对均值差及蒙特卡洛区间](05-paired-comparisons.png)

同一市场VWAP项在两个策略的成本差里相消，所以配对的平均成本差和差的方差不因共同价格基准变化；但各策略自身的跟踪风险会变化。原始数据中同时保留两者，便于复核这个恒等关系。

成交量错位情形只改变评价用的市场权重，不改变已生成计划和预设冲击系数。这一项检查跟踪误差，没有模拟成交量突变后的真实流动性响应。成交量限制和参与率约束在 participation 模块中单独研究。

## Reproducible research

See the English research note, results.json and fixed design for methods, assumptions and numerical evidence. Code and research preparation use AI assistance.

"""
    (output/"中文研究解读.md").write_text(chinese,encoding="utf-8",newline="\n")

def render_figures(s,raw,output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size":10,"axes.spines.top":False,"axes.spines.right":False,"figure.dpi":140})
    d=s["design"];profiles=d["profiles"];minutes=np.linspace(0,d["base"]["duration"],d["base"]["intervals"]+1);colors={"twap":"tab:blue","volume_weighted":"tab:orange","ac_simplified":"tab:green","ac_volume_aware":"tab:green"}
    fig,ax=plt.subplots(figsize=(10,4.6),layout="constrained")
    for profile in profiles:ax.plot((minutes[1:]+minutes[:-1])/2,raw["profile_"+profile+"_forecast"]*100,label=profile.replace("_"," "))
    ax.set(xlabel="Execution minute",ylabel="Forecast volume share per interval (%)",title="Synthetic positive forecast curves; normalized totals equal one")
    ax.legend(fontsize=8);fig.savefig(output/"01-volume-profiles.png");plt.close(fig)
    fig,axes=plt.subplots(2,3,figsize=(12,7),layout="constrained")
    for ax,profile in zip(axes.flat,profiles):
        for row in selected(s,profile=profile,model="constant"):
            x=raw[row["case_id"]+"_"+row["strategy"]+"_inventory"]
            ax.plot(minutes,x/d["base"]["quantity"]*100,label=LABELS[row["strategy"]],color=colors[row["strategy"]])
        ax.set(title=profile.replace("_"," "),xlabel="Minute",ylabel="Remaining inventory (%)")
    for ax in list(axes.flat)[len(profiles):]:ax.set_visible(False)
    handles,labels=axes.flat[0].get_legend_handles_labels()
    fig.legend(handles,labels,loc="outside lower center",ncols=3,fontsize=9)
    fig.suptitle("Three integerized plans; original constant-impact model, default risk weight")
    fig.savefig(output/"02-inventory-plans.png");plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(12,4.8),layout="constrained")
    for ax,model in zip(axes,d["impact_models"],strict=True):
        opt="ac_simplified" if model=="constant" else "ac_volume_aware"
        for offset,name in enumerate(("twap","volume_weighted",opt)):
            rows=[selected(s,profile=p,model=model,strategy=name)[0] for p in profiles]
            ax.bar(np.arange(len(profiles))+(offset-1)*.25,[r["prediction"]["objective"] for r in rows],width=.25,label=LABELS[name],color=colors[name])
        ax.set_xticks(range(len(profiles)),[p.replace("_","\n") for p in profiles])
        ax.set(title=model.replace("_"," "),ylabel="Expected cost + lambda * arrival variance")
        ax.legend(fontsize=8)
    fig.suptitle("Arrival objective under separately labeled impact assumptions")
    fig.savefig(output/"03-arrival-objective.png");plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(12,4.8),layout="constrained")
    for ax,model in zip(axes,d["impact_models"],strict=True):
        for benchmark,case,label in (("arrival","none","Arrival risk"),("market_vwap","matched","Matched VWAP tracking"),("market_vwap","shifted","Shifted VWAP tracking")):
            rows=[selected(s,profile=p,model=model,strategy="volume_weighted",benchmark=benchmark,volume_case=case)[0] for p in profiles]
            ax.semilogy(range(len(profiles)),[max(r["prediction"]["std"],1e-8) for r in rows],"o-",label=label)
        ax.set_xticks(range(len(profiles)),[p.replace("_","\n") for p in profiles])
        ax.set(title=model.replace("_"," "),ylabel="Analytic shortfall standard deviation")
        ax.legend(fontsize=8)
    fig.suptitle("Forecast-volume plan: arrival and tracking risk differ; zero SD plotted at 1e-8 only")
    fig.savefig(output/"04-tracking-risk.png");plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(12,4.8),layout="constrained")
    for ax,model in zip(axes,d["impact_models"],strict=True):
        rows=[next(r for r in s["paired_metrics"] if r["profile"]==p and r["impact_model"]==model and r["risk_aversion"]==d["base"]["risk_aversion"] and r["benchmark"]=="arrival" and r["first"]=="volume_weighted" and r["second"]=="twap") for p in profiles]
        mean=np.array([r["all_paths"]["mean"] for r in rows]);ci=[r["all_paths"]["ci95_mean"] for r in rows]
        if any(c is None for c in ci):ax.plot(range(len(profiles)),mean,"o",label="Descriptive mean; invalid paths")
        else:ax.errorbar(range(len(profiles)),mean,yerr=np.array([[m-c[0] for m,c in zip(mean,ci)],[c[1]-m for m,c in zip(mean,ci)]]),fmt="o",capsize=4,label="Paired empirical mean and 95% CI")
        ax.scatter(range(len(profiles)),[r["prediction_mean"] for r in rows],marker="x",color="black",label="Analytic mean difference")
        ax.axhline(0,color="gray",ls="--",lw=1);ax.set_xticks(range(len(profiles)),[p.replace("_","\n") for p in profiles])
        ax.set(title=model.replace("_"," "),ylabel="Forecast-volume minus TWAP mean cost");ax.legend(fontsize=8)
    fig.suptitle("Monte Carlo mean uncertainty; common external price paths")
    fig.savefig(output/"05-paired-comparisons.png");plt.close(fig)
