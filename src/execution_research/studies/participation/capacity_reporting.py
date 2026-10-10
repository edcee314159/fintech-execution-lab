"""Bilingual methods, measured results, and five capacity research figures."""
from pathlib import Path
import numpy as np

LABELS={"twap_capped":"Capped uniform target","volume_capped":"Capped forecast-volume","arrival_constrained":"Constrained arrival"}
COLORS={"twap_capped":"tab:blue","volume_capped":"tab:orange","arrival_constrained":"tab:green"}
def selected(s):
    return [r for r in s["strategy_metrics"] if r["risk_aversion"]==s["design"]["base"]["risk_aversion"]]
def default_cases(s):
    return [c for c in s["cases"] if c["risk_aversion"]==s["design"]["base"]["risk_aversion"]]
def example_case(s):
    candidates=[c for c in default_cases(s) if c["feasible"]]
    return next((c for c in candidates if c["profile"]=="u_shape" and c["scenario"]=="moderate_capacity"),candidates[0] if candidates else None)
def write_reports(s,raw,output):
    d=s["design"];v=s["verification"];cases=default_cases(s);rows=selected(s);example=example_case(s)
    quota=["| Profile | Capacity scenario | Integer capacity (shares) | Feasible | Shortfall (shares) |",
        "|---|---|---:|---|---:|"]
    for c in cases:quota.append(f"| {c['profile']} | {c['scenario']} | {c['integer_capacity_total']:,} | {c['feasible']} | {c['shortfall_shares']:,} |")
    metrics=["| Profile | Scenario | Plan | Expected impact | Arrival SD | Mean + λ variance | Binding intervals |",
        "|---|---|---|---:|---:|---:|---:|"]
    for r in rows:
        p=r["prediction"];metrics.append(f"| {r['profile']} | {r['scenario']} | {LABELS[r['strategy']]} | {p['mean']:.2f} | {p['std']:.2f} | {p['objective']:.2f} | {r['binding_intervals']} |")
    measured_en="No capacity-feasible case exists in this design; no full-order strategy comparison is produced."
    measured_zh="此设计没有容量可行的条件，因此不生成完整订单策略排名。"
    if example:
        opt=next(r for r in rows if r["case_id"]==example["case_id"] and r["strategy"]=="arrival_constrained")
        measured_en=f"For {example['profile']} / {example['scenario']} at lambda={example['risk_aversion']:g}, integer capacity is {example['integer_capacity_total']:,} shares for a {d['base']['quantity']:,}-share order. The original unconstrained integer AC plan violates {example['unconstrained_reference']['violating_intervals']} interval caps. Its reference arrival objective is {example['unconstrained_reference']['arrival_prediction']['objective']:.2f}; the feasible integer constrained plan has objective {opt['prediction']['objective']:.2f} and binds {opt['binding_intervals']} intervals. This is the observed difference between two integer approximations. It combines capacity restrictions with rounding effects, and does not isolate the mathematical constraint premium or measure an actual market loss."
        measured_zh=f"以 {example['profile']} / {example['scenario']}、风险权重 {example['risk_aversion']:g} 为例：整数总容量为 {example['integer_capacity_total']:,} 股，订单为 {d['base']['quantity']:,} 股。原无约束整数AC计划在 {example['unconstrained_reference']['violating_intervals']} 个区间超限，其到达价目标为 {example['unconstrained_reference']['arrival_prediction']['objective']:.2f}；受限整数优化计划的目标为 {opt['prediction']['objective']:.2f}，有 {opt['binding_intervals']} 个区间触及整数上限。这个整数计划差异同时包含容量约束和舍入因素，不能直接视为纯粹的约束溢价；数值属于模型目标，不是实际市场损失。"
    english=f"""# Participation constraints and capacity feasibility

## Question and scope

Can a mathematically attractive execution plan actually satisfy a deterministic market-volume quota? This extension introduces nonnegative integer trades, interval participation limits and exact full-order conservation. It preserves the original constant temporary-impact arrival objective, isolating the effect of capacity from a change in the impact model.

The study uses {len(s['cases'])} conditions: {len(d['profiles'])} synthetic volume profiles, {len(d['risk_aversions'])} risk weights and {len(d['scenarios'])} capacity scenarios. {v['feasible_cases']} are capacity feasible and {v['infeasible_cases']} are infeasible. Every feasible condition compares three plans on the same {d['base']['trials']} seeded Gaussian price paths. Reusing these paths does not create additional independent market observations.

## Quota semantics and infeasibility

External interval volume V is an integer allocation of the scenario's total using the forecast profile. It excludes the seller's own trades. The participation denominator is that external volume: q/V, not q/(V+q), and not a broker's percentage of average daily volume. Each integer cap is floor(rho*V); decimal input semantics use Decimal(str(input)) before flooring.

Continuous capacity shortage means sum(rho*V)<Q. Integer-only shortage means the raw quota covers Q but sum(floor(rho*V))<Q. With unit shares, box constraints and a single sum constraint, sum(caps)>=Q is sufficient for integer feasibility. The maximal possible shares is min(Q,sum(caps)). Zero-volume intervals have cap zero.

Infeasible orders are explicitly diagnosed. No fictitious complete plan or financially incomparable partial-order cost is generated. Capacity feasibility does not establish positive prices, so price/fill validity is checked separately.

These volumes and quotas are known deterministic scenario inputs. Forecast capacity is not guaranteed actual available liquidity. There is no order book, fill probability, real-volume calibration, participation-triggered price feedback or live execution. A broker algorithm has additional controls and may fail to complete; this model does not replicate it. [IBKR VWAP controls](https://www.interactivebrokers.com/docs/general/order-types/algorithmic-orders/ib-algorithms/vwap).

## Three feasible plans

Capped uniform and capped volume plans project their original target onto the same bounded simplex:
min ||q-target||², subject to 0<=q<=cap and sum(q)=Q.
The water-filling solution is clip(target+theta,0,cap), with theta selected by bisection. Simple clipping loses the order total and is not used. The volume target uses only the predefined forecast curve.

The constrained arrival plan minimizes
J(q)=a*sum(q²)+lambda*sigma²*tau*sum(x_post²), a=eta/tau.
Writing x_post=Lq with L strictly upper triangular gives H=a*I+b*L.T@L and J=q.T@H@q. H is positive definite because a>0. Normalize q/Q for SciPy SLSQP, provide the analytic gradient, and polish free variables with an active-set KKT refinement that can release falsely active bounds. [SciPy SLSQP documentation](https://docs.scipy.org/doc/scipy/reference/optimize.minimize-slsqp.html).

All three continuous plans receive deterministic capacity-aware largest-remainder rounding. Extra shares go only to intervals with spare integer capacity. Every resulting Schedule passes the core conservation and inventory checks and an additional cap check. The original unconstrained AC plan is retained solely as a labelled feasibility diagnostic, not as an executable strategy in the paired comparisons.

## Numerical certificate, including integer limitations

For any feasible q and g=2Hq, convexity gives
J(z)>=J(q)+g.T@(z-q).
Minimize g.T@z over the same box-and-sum set by filling capacity in increasing gradient order. Let z_lin denote that solution. The first-order gap is g.T@(q-z_lin), with a conservative floating-point allowance added. Therefore J(q)-gap is a lower bound for the continuous optimum and also for the integer optimum.

The recorded gap measures continuous numerical optimality in model objective units. After rounding, J(q_integer)-lower_bound is an upper bound on the integer plan's suboptimality. Rounding is not a proof of global integer optimality or universal superiority over the integer benchmark plans. Max continuous certificate gap in this run: {v['max_continuous_certificate_gap']:.12g}.

## A measured result

{measured_en}

## Capacity diagnostics at the default risk weight

"""+ "\n".join(quota)+"""

## Strategy results at the default risk weight

Costs and standard deviations are in model currency; the risk weight has the corresponding units for mean plus variance.

"""+ "\n".join(metrics)+f"""

## Statistical checks and reproducibility

There are {len(s['strategy_metrics'])} strategy rows and {len(s['paired_metrics'])} paired rows. All paths, plans, integer quotas, absolute market volumes, continuous constrained quantities and original unconstrained diagnostics are retained. The same price innovations and a mask common to all three feasible plans are used. Nonpositive reference/fill paths are preserved; any invalid path suppresses inferential intervals. Invalid feasible-case paths here: {v['invalid_feasible_case_paths']}.

Direct initial notional minus proceeds is checked against impact minus inventory times preserved price innovations under a floating-point bound. Analytic variance is sigma²*tau*||x_post||². Paired variance uses inventory differences. Student-t intervals quantify Monte Carlo mean uncertainty, not risk-objective uncertainty, liquidity forecast uncertainty or actual-market performance; no family-wide significance claim is made.

Independent checks reconstruct Decimal quotas, order accounting, statistics, the convex lower bound and a separate active-set reference solution. Two runs must reproduce numerical JSON and raw arrays exactly. Source/runtime digests and file manifests are retained. The separate tests also cover a hand-worked two-interval case, zero capacities, the singleton feasible set and small integer enumeration.

## Limits and attribution

This is a deterministic full-order capacity model. The 10% quota is an illustrative design choice, not a recommended trading setting. Capacity inputs are not estimated from real volume. A smaller realized volume could breach a forecast-based participation constraint or prevent actual completion. The extension adds no partial-fill accounting or endpoint liquidation penalty; infeasibility is reported rather than assigning an arbitrary economic value to unfinished shares.

Code and research preparation use AI assistance. This is a simulation study, not broker-algorithm replication or live execution.
"""
    (output/"research-note.md").write_text(english,encoding="utf-8",newline="\n")
    chinese=f"""# 成交量与参与率约束

这项完善把“怎样安排交易”推进到“计划能否满足给定容量”。保留原固定冲击模型，加入每区间整数交易上限、完整订单守恒和容量不足诊断。

## 完成内容

- 共 {len(s['cases'])} 条件，其中 {v['feasible_cases']} 条件容量可行，{v['infeasible_cases']} 条件不可行。
- 可行条件比较受限TWAP、受限成交量计划、受限到达价优化；每个条件用相同的 {d['base']['trials']} 条价格路径。
- 输出 {len(s['strategy_metrics'])} 条策略记录、{len(s['paired_metrics'])} 条配对比较，并保留所有原始样本。
- 原无约束AC只作超限诊断，不混入可执行策略排名。

## 为什么要检查两种容量不足

每段交易量不能超过 floor(参与率×外部市场成交量)。这里参与率分母排除自己的交易；每段成交量是预设模拟输入，不是真实历史估计，也不是券商ADV参数。

总原始容量不足时必然无法完成；即使原始总容量刚好足够，各段分别向下取整也可能使可用整数股数不足。系统区分这两种情况，报告最多能交易多少股、还差多少股，不生成虚假的完整成交结果。

![容量可行性](01-capacity-feasibility.png)

## 怎样得到守约束的计划

受限TWAP与受限成交量计划先对原目标作有界投影，在超限区间减量后向其他区间重新分配，保证总量守恒。简单把超限部分截掉会漏掉订单，不能替代重新分配。

受限到达价优化把每段上限直接放入凸二次优化，再用可释放误判活动边界的KKT主动集方法作数值修正。三种计划均用容量感知的最大余数舍入，新增整数股只放到有剩余容量的区间。

![受限交易与库存](02-constrained-plans.png)

## 这次实际发现了什么

{measured_zh}

容量越接近完成订单所需的最低水平，留给优化器调整时机的空间越小；容量宽松时能还原原来的无约束连续解。是否更优必须对应同一个金融目标。平均成本的配对区间不能证明风险加权目标显著更优。

![约束下的到达价目标](03-arrival-objectives.png)

默认风险权重下的容量诊断：

"""+ "\n".join(quota)+"""

默认风险权重下的策略结果：

"""+ "\n".join(metrics)+f"""

## 如何核验优化结果

除了查看求解器是否报告成功，我们用凸目标的梯度构造全局一阶下界。在线性化目标下，把容量按梯度从低到高分配，得到连续最优值的下界。整数计划目标减去该下界，给出它距离整数全局最优的差距上界。本轮连续证书的最大差距为 {v['max_continuous_certificate_gap']:.12g}。

这个证书不会把舍入后的计划冒充整数全局最优。独立核验用另一种主动集方法检查连续解，另外用小规模完整整数枚举检查上下界。

![连续证书与整数差距上界](04-optimality-certificates.png)

## 统计比较与适用范围

以下图表是受限优化计划减受限TWAP的平均成本，正值表示平均冲击成本较高；它可以同时具有更低的风险加权目标。95%区间仅描述蒙特卡洛均值误差，不代表真实交易收益、参数误差或风险目标差的置信区间。

![配对平均成本比较](05-paired-costs.png)

本轮可行条件中，无效价格条件路径为 {v['invalid_feasible_case_paths']}。所有样本保留；若出现非正价格或成交价，则停止推断区间。所有计划使用共同价格路径和共同有效掩码，避免筛选对某计划有利的样本。

预设容量可行不保证真实市场成交。实际成交量低于预期时仍可能超参与率或无法完成；本项没有订单簿、部分成交、未完成库存罚金或真实成交量预测。[实际券商VWAP的执行控制与未完成风险](https://www.interactivebrokers.com/docs/general/order-types/algorithmic-orders/ib-algorithms/vwap)

## Reproducible research

See the English research note, results.json and fixed design for methods, assumptions and numerical evidence. Code and research preparation use AI assistance.

"""
    (output/"中文研究解读.md").write_text(chinese,encoding="utf-8",newline="\n")

def render_figures(s,raw,output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    plt.rcParams.update({"font.size":9,"axes.spines.top":False,"axes.spines.right":False,"figure.dpi":140})
    d=s["design"];profiles=d["profiles"];scenarios=[v["name"] for v in d["scenarios"]];cases=default_cases(s);rows=selected(s)
    grid=np.zeros((len(profiles),len(scenarios)))
    fig,ax=plt.subplots(figsize=(11,6.2),layout="constrained")
    for i,profile in enumerate(profiles):
        for j,scenario in enumerate(scenarios):
            c=next(c for c in cases if c["profile"]==profile and c["scenario"]==scenario)
            grid[i,j]=2 if c["feasible"] else (1 if c["reason"]=="integer_rounding_shortage" else 0)
    ax.imshow(grid,cmap=ListedColormap(["#f6b6ad","#ffe0a0","#bce1c1"]),vmin=0,vmax=2,aspect="auto")
    for i,profile in enumerate(profiles):
        for j,scenario in enumerate(scenarios):
            c=next(c for c in cases if c["profile"]==profile and c["scenario"]==scenario)
            label=f"{c['integer_capacity_total']:,}\n"+("feasible" if c["feasible"] else f"short {c['shortfall_shares']:,}")
            ax.text(j,i,label,ha="center",va="center",fontsize=8.5)
    ax.set_xticks(range(len(scenarios)),[v.replace("_","\n") for v in scenarios])
    ax.set_yticks(range(len(profiles)),[p.replace("_"," ") for p in profiles])
    ax.set_title(f"Integer quota capacity vs Q={d['base']['quantity']:,} shares\nRed: raw shortage; amber: rounding-only shortage; green: feasible")
    fig.savefig(output/"01-capacity-feasibility.png");plt.close(fig)
    example=example_case(s)
    if example is None:
        for name in ("02-constrained-plans.png","03-arrival-objectives.png","04-optimality-certificates.png","05-paired-costs.png"):
            fig,ax=plt.subplots(figsize=(9,4),layout="constrained");ax.text(.5,.5,"No capacity-feasible full-order plans in this design",ha="center",va="center");ax.set_axis_off()
            fig.savefig(output/name);plt.close(fig)
        return
    caseid=example["case_id"];n=d["base"]["intervals"];minutes=np.linspace(0,d["base"]["duration"],n+1)
    fig,axes=plt.subplots(1,2,figsize=(12,5),layout="constrained")
    axes[0].step(minutes[:-1],raw[caseid+"_caps"],where="post",color="black",label="Integer quota")
    for name in example["strategies"]:
        axes[0].step(minutes[:-1],raw[caseid+"_"+name+"_quantities"],where="post",label=LABELS[name],color=COLORS[name])
        axes[1].plot(minutes,raw[caseid+"_"+name+"_inventory"]/d["base"]["quantity"]*100,label=LABELS[name],color=COLORS[name])
    diagnostic="Original AC (exceeds caps)" if not example["unconstrained_reference"]["feasible"] else "Original AC (feasible reference)"
    axes[0].plot(minutes[:-1],raw[caseid+"_unconstrained_quantities"],"--",color="tab:red",label=diagnostic)
    axes[1].plot(minutes,raw[caseid+"_unconstrained_inventory"]/d["base"]["quantity"]*100,"--",color="tab:red",label=diagnostic)
    axes[0].set(xlabel="Minute",ylabel="Shares per interval",title="Planned quantities and caps")
    axes[1].set(xlabel="Minute",ylabel="Remaining inventory (%)",title="Inventory trajectories")
    handles,labels=axes[0].get_legend_handles_labels();fig.legend(handles,labels,loc="outside lower center",ncols=3,fontsize=8)
    fig.suptitle(example["profile"].replace("_"," ")+" / "+example["scenario"].replace("_"," ")+"; default risk weight")
    fig.savefig(output/"02-constrained-plans.png");plt.close(fig)
    feasible_scenarios=[v for v in scenarios if any(c["feasible"] and c["scenario"]==v for c in cases)]
    fig,axes=plt.subplots(1,len(feasible_scenarios),figsize=(5*len(feasible_scenarios),5),squeeze=False,layout="constrained")
    for ax,scenario in zip(axes.flat,feasible_scenarios):
        for offset,name in enumerate(LABELS):
            vals=[]
            for p in profiles:
                r=next((r for r in rows if r["profile"]==p and r["scenario"]==scenario and r["strategy"]==name),None)
                vals.append(r["prediction"]["objective"] if r else np.nan)
            ax.bar(np.arange(len(profiles))+(offset-1)*.25,vals,width=.25,label=LABELS[name],color=COLORS[name])
        ax.set_xticks(range(len(profiles)),[p.replace("_","\n") for p in profiles]);ax.set(title=scenario.replace("_"," "),ylabel="Expected cost + lambda * arrival variance")
    handles,labels=axes.flat[0].get_legend_handles_labels();fig.legend(handles,labels,loc="outside lower center",ncols=3,fontsize=8)
    fig.suptitle("Only complete capacity-feasible integer plans; default risk weight")
    fig.savefig(output/"03-arrival-objectives.png");plt.close(fig)
    feasible=[c for c in s["cases"] if c["feasible"]]
    fig,ax=plt.subplots(figsize=(11,4.8),layout="constrained")
    ax.semilogy(range(len(feasible)),[max(c["certificate"]["gap"],1e-12) for c in feasible],"o",ms=4,label="Continuous numerical certificate gap")
    ax.semilogy(range(len(feasible)),[max(c["certificate"]["integer_suboptimality_upper_bound"],1e-12) for c in feasible],"x",ms=5,label="Integer suboptimality upper bound")
    ax.set(xlabel="Feasible case index (all risk weights)",ylabel="Objective gap in model currency",title="Convex lower-bound certificates; values below 1e-12 shown at 1e-12")
    handles,labels=ax.get_legend_handles_labels();fig.legend(handles,labels,loc="outside lower center",ncols=2,fontsize=8)
    fig.savefig(output/"04-optimality-certificates.png");plt.close(fig)
    fig,axes=plt.subplots(1,len(feasible_scenarios),figsize=(5*len(feasible_scenarios),5),squeeze=False,layout="constrained")
    for ax,scenario in zip(axes.flat,feasible_scenarios):
        for i,p in enumerate(profiles):
            r=next((r for r in s["paired_metrics"] if r["profile"]==p and r["scenario"]==scenario and r["risk_aversion"]==d["base"]["risk_aversion"] and r["first"]=="arrival_constrained" and r["second"]=="twap_capped"),None)
            if r is None:continue
            mean=r["all_paths"]["mean"];ci=r["all_paths"]["ci95_mean"]
            if ci:ax.errorbar(i,mean,yerr=[[mean-ci[0]],[ci[1]-mean]],fmt="o",capsize=4,color="tab:blue")
            else:ax.plot(i,mean,"o",color="tab:blue")
            ax.scatter(i,r["prediction_mean"],marker="x",color="black")
        ax.axhline(0,color="gray",ls="--",lw=1);ax.set_xticks(range(len(profiles)),[p.replace("_","\n") for p in profiles])
        ax.set(title=scenario.replace("_"," "),ylabel="Constrained arrival minus capped uniform mean cost")
    fig.suptitle("Dots: paired mean and 95% Monte Carlo CI; crosses: analytic mean; default risk")
    fig.savefig(output/"05-paired-costs.png");plt.close(fig)
