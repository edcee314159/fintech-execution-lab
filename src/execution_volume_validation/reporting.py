"""Static research figures and bilingual notes; no raw market-data exports."""
from pathlib import Path
from datetime import date
import json
import numpy as np
from .forecasting import PREDICTORS
from .study import PLANNERS

COLORS=("#137c80","#426ba2","#ce8142")
NAMES={"uniform":"Uniform","historical_shape":"Historical shape","previous_day":"Previous day",
       "twap_capped":"Capped uniform","volume_capped":"Capped volume","arrival_constrained":"Constrained arrival"}
FIGURES=("01-volume-curves.png","02-forecast-errors.png","03-completion.png","04-replay-example.png","05-paired-price-diagnostic.png")


def write_report(result,private,public,output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    output=Path(output);figs=output/"figures";figs.mkdir(parents=True,exist_ok=True)
    symbols=result["design"]["symbols"];dates=result["evaluation_calendar_dates"];fractions=result["design"]["fractions"]
    n_dates=len(dates);lookback=result["design"]["lookback"]
    acquired=result["design"].get("source_access_date")
    acquired_en=acquired or "not recorded";acquired_zh=acquired or "未记录"
    prepared=date.today().isoformat()
    (output/"report-provenance.json").write_text(json.dumps({"source_access_date":acquired,"report_prepared_date":prepared,"source_csv_sha256":{s:v["csv_sha256"] for s,v in result["sources"].items()}},indent=2)+"\n",encoding="utf-8")
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":10,"axes.spines.top":False,"axes.spines.right":False,"axes.titleweight":"bold","figure.facecolor":"white","axes.grid":True,"grid.alpha":.15})
    def finish(fig,name):
        fig.savefig(figs/name,dpi=170,bbox_inches="tight");plt.close(fig)
    fig,axes=plt.subplots(1,len(symbols),figsize=(5.6*len(symbols),3.8),squeeze=False,constrained_layout=True)
    for ax,s in zip(axes[0],symbols):
        observed=np.mean([private[f"{s}_{d}_actual_volume"]/private[f"{s}_{d}_actual_volume"].sum() for d in dates],axis=0)
        ax.plot(range(78),observed*100,color="#222f36",lw=2,label="Observed evaluation mean (after-event)")
        for i,p in enumerate(PREDICTORS):
            v=np.mean([private[f"{s}_{d}_{p}_forecast_volume"]/private[f"{s}_{d}_{p}_forecast_volume"].sum() for d in dates],axis=0)
            ax.plot(range(78),v*100,color=COLORS[i],label=NAMES[p],alpha=.85)
        ax.set(title=s,xlabel="Five-minute interval (09:30-16:00 ET)",ylabel="Share of daily volume (%)")
    axes[0,-1].legend(fontsize=8)
    fig.suptitle(f"Past-only forecasts and observed volume shape | {n_dates} evaluation dates",fontsize=13)
    finish(fig,FIGURES[0])
    fig,axes=plt.subplots(1,len(symbols),figsize=(5.3*len(symbols),3.8),squeeze=False,constrained_layout=True)
    means=[]
    for ax,s in zip(axes[0],symbols):
        for i,p in enumerate(PREDICTORS):
            rows=[f for f in result["forecasts"] if f["symbol"]==s and f["predictor"]==p]
            vals=np.array([f["scores"]["interval_wape"] for f in rows])*100
            ax.bar(i,vals.mean(),color=COLORS[i],alpha=.75)
            ax.scatter(i+np.linspace(-.15,.15,len(vals)),vals,color="#26333a",s=18,zorder=3)
            means.append((s,p,{k:float(np.mean([f["scores"][k] for f in rows])) for k in rows[0]["scores"]}))
        ax.set_xticks(range(3),[NAMES[p].replace(" ","\n") for p in PREDICTORS]);ax.set(title=s,ylabel="Interval WAPE (%)");ax.set_ylim(bottom=0)
    fig.suptitle(f"Volume forecast error | bars: means; dots: {n_dates} dates (descriptive)",fontsize=13)
    finish(fig,FIGURES[1])
    fig,axes=plt.subplots(len(symbols),len(fractions),figsize=(4.2*len(fractions),3.5*len(symbols)),squeeze=False,constrained_layout=True)
    for row,s in enumerate(symbols):
        for col,fraction in enumerate(fractions):
            ax=axes[row,col]
            for j,planner in enumerate(PLANNERS):
                summaries=[next(c for c in result["comparisons"] if c["symbol"]==s and c["predictor"]==p and c["order_fraction_adv"]==fraction) for p in PREDICTORS]
                values=[c["strategies"][planner]["completion_rate_all_cases"]*100 for c in summaries]
                ax.bar(np.arange(3)+(j-1)*.24,values,.23,color=COLORS[j],label=NAMES[planner])
            ax.set_xticks(range(3),[NAMES[p].replace(" ","\n") for p in PREDICTORS],fontsize=8)
            ax.set_ylim(0,108);ax.set_title(f"{s} | order = {fraction:.0%} of past ADV",fontsize=10)
            if col==0:ax.set_ylabel(f"Complete / all {n_dates} cases (%)")
    handles,labels=axes[-1,-1].get_legend_handles_labels()
    fig.legend(handles,labels,loc="outside lower center",ncol=3,fontsize=9)
    fig.suptitle("Capacity replay completion | no-plan cases stay in the denominator",fontsize=13)
    finish(fig,FIGURES[2])
    # Fixed in the design: last listed symbol, first evaluation date, largest order.
    s=symbols[-1];d=dates[0];fraction=max(fractions)
    rows=[r for r in result["records"] if r["symbol"]==s and r["date"]==d and r["predictor"]=="historical_shape" and r["order_fraction_adv"]==fraction]
    fig,axes=plt.subplots(2,1,figsize=(11,6),constrained_layout=True)
    first=next((r for r in rows if r["planning_feasible"]),None)
    if first is not None:
        cap=private[first["id"]+"_actual_caps"]
        axes[0].plot(range(78),cap,color="#26333a",lw=1.5,label="Observed interval quota (after-event)")
    for i,r in enumerate(rows):
        if not r["planning_feasible"]:continue
        key=r["id"];axes[0].plot(range(78),public[key+"_planned"],color=COLORS[i],alpha=.85,label=NAMES[r["planner"]]+" planned")
        axes[1].plot(range(79),public[key+"_remaining"],color=COLORS[i],label=NAMES[r["planner"]])
    if first is None:
        for ax in axes:ax.text(.5,.5,"No feasible plan for this fixed example",ha="center",transform=ax.transAxes)
    axes[0].set(ylabel="Shares / five-minute interval")
    axes[1].set(xlabel="Five-minute interval",ylabel="Remaining shares after replay")
    if first is not None:axes[0].legend(ncol=2,fontsize=8);axes[1].legend(fontsize=8)
    fig.suptitle(f"Fixed example: {s}, {d} | historical shape | {fraction:.0%} past ADV",fontsize=13)
    finish(fig,FIGURES[3])
    fig,axes=plt.subplots(1,len(symbols),figsize=(5.6*len(symbols),4.2),squeeze=False,constrained_layout=True)
    focus=.05 if .05 in fractions else min(fractions)
    for ax,s in zip(axes[0],symbols):
        c=next(c for c in result["comparisons"] if c["symbol"]==s and c["predictor"]=="historical_shape" and c["order_fraction_adv"]==focus)
        ys=[]
        for d in c["common_complete_dates"]:
            y=[next(r["price_diagnostic"]["marked_total_bps"] for r in result["records"] if r["symbol"]==s and r["date"]==d and r["predictor"]=="historical_shape" and r["order_fraction_adv"]==focus and r["planner"]==p) for p in PLANNERS]
            ax.plot(range(3),y,marker="o",alpha=.6,lw=1,label=d);ys.append(y)
        if ys:ax.plot(range(3),np.mean(ys,axis=0),color="#222f36",marker="D",lw=2.5,label="Common-date mean")
        else:ax.text(.5,.5,"No common completed dates; no cost comparison",ha="center",transform=ax.transAxes)
        ax.axhline(0,color="#999",lw=.8);ax.set_xticks(range(3),[NAMES[p].replace(" ","\n") for p in PLANNERS],fontsize=8)
        ax.set(title=f"{s} | common completed dates: {len(ys)}",ylabel="Assumed marked shortfall (bps)")
    if axes[0,-1].get_legend_handles_labels()[0]:axes[0,-1].legend(fontsize=7)
    fig.suptitle(f"Price diagnostic | historical shape, {focus:.0%} past ADV | assumed Close fills + impact",fontsize=12)
    finish(fig,FIGURES[4])
    forecast_lines=["| Instrument | Predictor | Mean daily APE | Mean interval WAPE | Mean cumulative share MAE |","|---|---|---:|---:|---:|"]
    forecast_lines += [f"| {s} | {NAMES[p]} | {m['daily_ape']:.2%} | {m['interval_wape']:.2%} | {m['cumulative_share_mae']:.2%} |" for s,p,m in means]
    forecast_table="\n".join(forecast_lines)
    completion_lines=[f"| Instrument | Predictor | Order / past ADV | TWAP complete / {n_dates} | Volume complete / {n_dates} | Arrival complete / {n_dates} | Common complete dates |","|---|---|---:|---:|---:|---:|---:|"]
    for c in result["comparisons"]:
        st=c["strategies"];completion_lines.append(f"| {c['symbol']} | {NAMES[c['predictor']]} | {c['order_fraction_adv']:.0%} | {st['twap_capped']['completed']} | {st['volume_capped']['completed']} | {st['arrival_constrained']['completed']} | {c['common_complete_count']} |")
    completion_table="\n".join(completion_lines)
    sensitivity_lines=["| Instrument | Planner | Common complete dates | eta=0 | eta=1e-5 | eta=5e-5 |","|---|---|---:|---:|---:|---:|"]
    for s in symbols:
        common=next(c["common_complete_dates"] for c in result["comparisons"] if c["symbol"]==s and c["predictor"]=="historical_shape" and c["order_fraction_adv"]==focus)
        for p in PLANNERS:
            rs=[r for r in result["records"] if r["symbol"]==s and r["predictor"]=="historical_shape" and r["order_fraction_adv"]==focus and r["planner"]==p and r["date"] in common]
            vals=[f"{np.mean([r['fixed_schedule_impact_sensitivity_bps'][str(eta)] for r in rs]):.3f}" if rs else "n/a" for eta in (0.,1e-5,5e-5)]
            sensitivity_lines.append(f"| {s} | {NAMES[p]} | {len(common)} | "+" | ".join(vals)+" |")
    sensitivity_table="\n".join(sensitivity_lines)
    figures="\n\n".join(f"![{name}](figures/{name})" for name in FIGURES)
    n=len(result["records"]);planned=result["planned_record_count"];complete=result["completed_record_count"]
    accepted=sum(len(a["accepted_sessions"]) for a in result["audit"].values())
    minutes=sum(a["accepted_minutes"] for a in result["audit"].values())
    source_links="[FirstRate Data](https://firstratedata.com/free-intraday-data), [format and permissions](https://firstratedata.com/about/FAQ), [license](https://firstratedata.com/about/license)"
    english=f"""# Real equity volume validation: chronological research pilot

Source: {source_links}. Instruments: {', '.join(symbols)}. Frozen input dates: {result['design']['expected_dates'][0]} to {result['design']['expected_dates'][-1]}. Raw data accessed {acquired_en}; report prepared {prepared}. {accepted} complete symbol-sessions, {minutes:,} retained regular-session minute bars, aggregated into 78 five-minute intervals per session. Changes are documented in the source design, not silently substituted.

## Question and method
Does a plan feasible under a past-only volume forecast remain feasible against subsequent observed volume? Exactly {lookback} preceding sessions predict each target date. There are {n_dates} evaluation date(s), {len(symbols)} selected instrument(s), and {result['evaluation_symbol_days']} symbol-days. The rolling window can include earlier completed evaluation dates, never the current date. Training dates are retained for every forecast and plan.

Predictors: uniform shape; equal-weight mean historical daily-normalized shape; previous-day absolute interval volumes. Uniform and historical shape share the past-window mean total; every predictor shares the same order size based on that past ADV. Orders are {', '.join(f'{f:.0%}' for f in fractions)} of past ADV; participation ceiling {result['design']['participation_rate']:.0%}. Three planners: capped uniform, capped forecast-volume and constrained arrival, using the unchanged reviewed kernel. Volatility uses only within-day price changes in training. Horizon 390 minutes; five-minute intervals; assumed eta={result['design']['impact']}, lambda={result['design']['risk_aversion']}. Impact and risk preferences are not empirically calibrated.

## Results and interpretation
{len(result['forecasts'])} forecasts; {n} planner-case records. {planned} generated plans and {complete} completed in replay. {planned-complete} generated plans retained terminal shares; {n-planned} cases correctly produced no plan. Repeated scenarios and planners on the same historical dates are not independent market observations. No-plan cases stay in the completion denominator.

{forecast_table}

WAPE is sum of absolute interval-volume errors divided by the observed day total. Daily APE compares total volume; cumulative share MAE compares cumulative normalized curves. Percentages are descriptive averages over target dates, not confidence intervals. A lower forecast error does not guarantee completion or cheaper execution. When forecast volume is uniform, the capped-uniform and capped-volume targets can coincide; they are not additional independent evidence.

{completion_table}

## What replay and price diagnostics mean
Each interval executes min(cumulative released plan - previous fills, floor(rho * observed interval volume)). Backlog carries forward; missed earlier capacity cannot be borrowed retroactively. Residual shares stay explicitly unfilled. Summed observed quotas give an after-event volume-only capacity upper bound, not an executable policy. Finished-interval volume becomes known after the event: this replay cannot establish live fill availability.

The sell-price diagnostic assumes each fill at five-minute Close plus constant temporary impact. Marked shortfall = Q*first Open - sum(fills*Close) - residual*final Close + eta/5*sum(fills^2). Residual marking is not execution. Price comparisons use only dates where all three planners of the SAME predictor/order size produced AND completed plans. Different predictors can have different common subsets; their means must not be used as an across-predictor performance ranking. A negative shortfall may reflect favorable price movement, not strategy alpha or a verified profit.

Fixed-schedule impact sensitivity below: historical shape, order {focus:.0%} of past ADV, mean marked shortfall in bps on the same common completed dates. Plans are held fixed, not re-optimised for each eta.

{sensitivity_table}

## Limits and reproduction
This is a short, selected-instrument pilot. No significance tests, annualisation or long-run superiority claims. Supplier reported intraday volume can differ from official daily totals; complete consolidated volume coverage has not been independently established. No order book, spread, fees, queue priority, auction-specific modelling or true trade-by-trade VWAP. Hypothetical own orders do not alter historical volume or prices. Prices use the vendor's historical adjustment conventions rather than point-in-time unadjusted quotes. Rounded constrained plans have continuous-relaxation bounds, not proofs of integer global optimality.

Raw OHLCV, raw volume/price arrays and vendor HTML remain local and are excluded from the public package. Independently fetch vendor data; frozen hashes reject rotated/changed samples. A changed data file requires a new named design and report. Public outputs contain derived metrics, strategy schedules/fills and static figures. [Reproduction guide](../../docs/real-volume.md).

AI-assisted implementation and research preparation. Prior studies remain separately labelled; this pilot does not replace their full-study evidence.

## Figures
{figures}
"""
    chinese=f"""# 真实股票与 ETF 成交量验证

数据来自 {source_links}。标的：{', '.join(symbols)}；冻结数据期 {result['design']['expected_dates'][0]}—{result['design']['expected_dates'][-1]}，数据取得日期：{acquired_zh}，报告整理日期：{prepared}。接收 {accepted} 个完整标的交易日、{minutes:,} 条常规时段分钟记录，每天合并为78个五分钟区间。

## 研究问题与方法
重点是展示从真实行情到可复现研究的流程：数据校验、交易时段处理、只用过去日期预测、生成整数约束计划，再用后续日期评估。

每个目标日只用此前 {lookback} 个已经结束的交易日。共有 {n_dates} 个评估日期、{len(symbols)} 个标的、{result['evaluation_symbol_days']} 个标的评估日。后续窗口可以纳入此前已结束的评估日，不读取当日价格或成交量来制订计划。训练日期逐条保留，便于检查未来信息泄漏。

三种预测是均匀曲线、等权历史日内占比均值、前一日成交量。前两种共享历史平均日量；所有预测方法共用按过去 ADV 确定的订单规模：{', '.join(f'{f:.0%}' for f in fractions)}，区间参与率上限 {result['design']['participation_rate']:.0%}。三种计划是约束下的均匀目标、预测成交量目标和到达价优化目标。波动率只从训练期日内价格变化估计；假设 eta={result['design']['impact']}、lambda={result['design']['risk_aversion']}，未校准真实交易冲击。

## 正式结果
{len(result['forecasts'])} 条预测、{n} 条策略条件记录。{planned} 条生成计划，{complete} 条在回放中完成；{planned-complete} 条留下未完成数量；另有 {n-planned} 条在预测容量检查时即明确无计划。相同日期上的不同条件、预测和策略不是独立市场样本，不能把 {n} 条记录当作 {n} 个独立观察。

{forecast_table}

区间 WAPE 是各段绝对预测误差之和除以实际全天成交量；日量 APE 衡量全天总量误差，累计占比 MAE 衡量日内形状误差。这些都是样本中的描述性平均值，不是统计置信区间。预测误差更小，不代表一定更便宜或能按时完成。均匀预测下，约束均匀目标和成交量目标可能相同，不构成额外独立证据。

{completion_table}

完成率分母保留所有评估日，无计划没有被删除。计划超出实际区间上限与回放违规是两回事：回放会截断每段成交量并保留剩余订单，不能用计划成功生成代替按期完成。

## 回放和成本口径
每段取“累计计划释放量减去此前已成交量”和“实际区间量乘参与率后向下取整”的较小值。未成交量延后，不能事后使用错过的早段容量，也没有重新优化剩余订单。实际容量总和只给出事后容量上界。完整区间量事后才知道，所以这是容量诊断，不能证明真实市场当时可以成交。

价格诊断假设每段在五分钟收盘价成交，再加固定冲击项。卖单短差分开保留已成交价格项、剩余订单期末盯市项和假设冲击项。盯市没有把剩余订单变成已完成成交。成本比较仅使用同一预测与规模下，三种计划均生成且均完成的共同日期，并显示日期数。不同预测的共同日期可能不同，不能直接按其均值排名。负短差可能只是价格变动有利，不能称为策略超额收益或已验证盈利。

下表是历史平均预测、{focus:.0%}过去 ADV 订单在共同完成日期上的固定计划冲击敏感性，单位bps。计划保持不变，没有声称重新优化或实证校准 eta。

{sensitivity_table}

## 研究局限与复现
样本短、标的经过选择，不做显著性检验、年化或长期有效性推断。供应商日内量可能与官方日度总量不同，完整综合行情覆盖未独立验证。OHLC不能还原真实逐笔VWAP、价差、盘口或排队；也没有区分开收盘竞价执行。假设自己的订单不会改变历史价格与成交量，价格按供应商历史调整口径使用。连续松弛的最优性界不是整数全局最优证明。

原始行情、原始价格/成交量数组和供应商页面留在本地，不进入公开成果包。公开包包含代码、衍生指标、策略计划与静态研究图。复现者从官网自行取得数据，锁定的来源哈希会拒绝轮换或修订的免费样本；不同输入应另立设计版本。[复现说明](../../docs/real-volume.md)。

代码和研究准备使用 AI 辅助。

## 五张研究图
{figures}
"""
    (output/"research-note.md").write_text(english,encoding="utf-8")
    (output/"中文研究解读.md").write_text(chinese,encoding="utf-8")
