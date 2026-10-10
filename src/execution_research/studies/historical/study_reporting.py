"""Reader-facing scientific figures and measured English/Chinese notes."""
from pathlib import Path
from datetime import date
import math
import numpy as np

def write_reports(s,output):
    d=s["design"];audit=s["cleaning_audit"]
    fits={(r["asset"],r["mapping"]):r for r in s["calibration_fits"]}
    rows=["| Asset | Training returns | Calendar σ at price 100 | Reference-step σ at price 100 | Calendar annualized log-vol proxy |",
        "|---|---:|---:|---:|---:|"]
    chinese=["| 数据序列 | 训练收益数 | 日历法 σ（100价格） | 参考日法 σ（100价格） | 日历年化 log 波动代理 |","|---|---:|---:|---:|---:|"]
    for asset in d["assets"]:
        c=fits[asset,"calendar"];f=fits[asset,"reference_day"]
        values=f"| {asset} | {c['sample_count']} | {c['sigma_equivalent_at_price_100']:.6g} | {f['sigma_equivalent_at_price_100']:.6g} | {c['annual_calendar_equivalent_log_volatility']*100:.2f}% |"
        rows.append(values);chinese.append(values)
    summaries=[r for r in s["forecast_summary"] if r["period"]=="all"]
    table=["| Asset | Estimator | Holdout n | MSFE / forecast variance | Empirical normal 95% coverage | Mean QLIKE (lower is better, within asset) |","|---|---|---:|---:|---:|---:|"]
    for row in summaries:
        table.append(f"| {row['asset']} | {row['method']} | {row['observations']} | {row['msfe_over_forecast_variance']:.3f} | {row['empirical_normal_95_coverage']*100:.2f}% | {row['mean_qlike']:.3f} |")
    english=f"""# Historical FX reference-data volatility calibration

## Research question

Can an auditable historical-data pipeline estimate volatility, preserve information boundaries and supply dimensionally explicit inputs to the existing execution model? Compare assumptions about time conversion and diagnose chronological holdout forecasts; do not presume that any rolling estimator must outperform a frozen one.

## Data and transformations

Source: European Central Bank euro reference-rate historical CSV archive. [Official reference-rate description]({d['source']['methodology_url']}). Reference rates are informational and are not executable transaction quotes. The original download is retained unmodified, with retrieval time and SHA-256.

USD, GBP and HKD are quoted per euro. Derived USD/GBP = (USD/EUR)/(GBP/EUR); derived USD/HKD = (USD/EUR)/(HKD/EUR). The researcher sorts and filters the archive, derives cross-rates and log returns, and calculates statistics. [ECB reuse conditions]({d['source']['copyright_url']}); attribute the ECB and disclose these modifications. No ECB endorsement is implied.

Raw CSV rows: {audit['input_rows']}; outside fixed range: {audit['outside_range_rows']}; identical selected-rate duplicates: {audit['duplicate_rows']}; dropped missing/invalid rows: {audit['dropped_rows']}; retained prices: {audit['kept_rows']}. All counts reconcile. No forward filling; no extreme-return deletion. Structural date/schema errors and conflicting duplicates fail loudly. Missing, non-finite and non-positive rates are audited and omitted jointly from the cross-rate panel.

Data range: {audit['first_date']} to {audit['last_date']}. Training return END dates: {d['training_start']} to {d['training_end']}; holdout: {d['evaluation_start']} to {d['evaluation_end']}. Pre-training observations provide the prior price and rolling history. Current historical snapshots may contain later revisions; chronological boundaries are not a point-in-time vintage-data guarantee.

## Time units and estimation

For r_i=log(P_i/P_(i-1)) and dt_i equal to elapsed calendar minutes:
mu_hat = sum(r_i)/sum(dt_i);
sigma_hat² = sum((r_i-mu_hat*dt_i)²/dt_i)/(n-1).
This is the one-drift-parameter, degrees-of-freedom-adjusted constant-diffusion fit under independent Gaussian innovations. An independent verifier recomputes the fit with high-precision arithmetic.

The primary mapping uses actual calendar gaps. A sensitivity mapping fixes every reference-observation step to 1,440 minutes, including steps across weekends and holidays. Daily-equivalent sigma is sigma_min*sqrt(1440); calendar-annual equivalent is sigma_min*sqrt(525600). The annual proxy uses calendar time, not the equity convention of 252 trading days.

Daily reference observations do not identify true intraday volatility, liquidity, spreads, jumps or market impact. Published quote precision and cross-rate arithmetic may contribute noise, particularly for small currency moves. The calendar model assigns diffusion time across weekends/holidays even when activity differs; the fixed-step model compresses those gaps. Both are explicit modeling conventions. Estimating log-return diffusion also differs from the arithmetic Brownian price model in the core.

## Frozen training estimates

"""+ "\n".join(rows)+"""

## Chronological forecast diagnostics

The frozen estimator uses only training returns. Rolling windows of 20, 60 and 120 returns include only observations ending at or before the previous reference date. For each next observed reference interval, forecast mean=mu_hat*dt and variance=sigma_hat²*dt. Horizon length is the observed calendar interval; this is a retrospective interval-specific diagnostic, not a live service anticipating missing releases.

MSFE / forecast variance = sum((r-forecast_mean)²)/sum(forecast_variance). It measures squared forecast error, not pure variance alone: drift error and changing volatility both matter. Normal 95% coverage counts |error| <= 1.9599639845*sqrt(variance). QLIKE=log(variance)+error²/variance is also retained. Zero variance is recorded explicitly without inventing a positive floor.

"""+ "\n".join(table)+"""

These are descriptive holdout diagnostics. Correlated or heteroskedastic observations invalidate a simplistic independent-observation coverage confidence interval; none is claimed. Windows and dates were fixed before outcomes. Different periods can favor different estimators; no best window is selected or deployed after observing the holdout.

## Link to the execution model

The original core models a hypothetical price-100 instrument with quantities in shares. To preserve its units, carry the historical RELATIVE FX volatility into a synthetic price-normalized instrument: sigma_core=100*sigma_log_per_sqrt_minute. Also retain the actual quote-level sigma at the last training price, with units USD/GBP or USD/HKD per sqrt-minute.

Three continuous schedules per asset: the original assumed sigma=0.03, calendar-calibrated sigma, and reference-day-calibrated sigma. Compare all three under the same frozen calendar-calibrated model sigma, keeping eta=1e-5, lambda=1e-5, Q=100000, T=60 minutes and N=60. The calendar plan minimizes that continuous assumed objective by construction. Its objective advantage is a model consistency check, not evidence of superior historical trade execution.

This rescaling does not make GBP or HKD worth USD100, does not calibrate an actual equity, and does not infer eta from daily prices. Impact and risk preference remain assumptions. No historical transaction-price or real-market execution-profit backtest is performed.

## Reproducibility

Retain the raw official archive, metadata, fixed design, cleaned panel, returns, fits, every forecast and its fitting cutoff, period summaries, model inventory arrays and source/runtime hashes. Two runs using the same snapshot should agree numerically; a new download can change archive bytes as the provider adds observations or revises history.

Nine automated tests cover sorting and audit reconciliation, cross-rates, conflicts, missing data, calendar gaps, hand-worked fitting, invalid inputs, future-target perturbation, frozen training, normalized integration and strict exports. Source files of the original core are unchanged.
"""
    (output/"research-note.md").write_text(english,encoding="utf-8",newline="\n")
    chinese_note=f"""# 历史数据波动率校准

这一项把真实公开数据接入项目，补上数据获取、清洗、参数估计与模型单位映射的证据。数据来自欧洲央行，原始下载、来源时间与哈希都已保存。我们派生 GBP/USD 和 HKD/USD 价格序列，研究其相对价格波动，再在现有模型里演示参数的作用。

## 已完成什么

- 清洗得到 {audit['kept_rows']} 个日期的共同价格记录，共 {len(s['returns'])} 条资产收益记录。
- 固定 2022–2023 年作为训练期、2024–2025 年作为评估期；输出 {len(s['forecasts'])} 条预测记录，以及每条预测使用数据的起止日期。
- 比较固定训练估计与 20、60、120 个收益的滚动估计。所有拟合结束日期都不晚于预测起点，未来目标收益不会改变当前预测参数。
- 缺失、异常值和重复数据有处理账目；不前向填充，不自动删除极端涨跌。当前快照中删除 {audit['dropped_rows']} 行、去重 {audit['duplicate_rows']} 行；异常输入的处理另由测试验证。
- 9 项功能测试通过；两次研究运行与独立核验的结果见验证记录。

## 波动率校准的实际结果

"""+ "\n".join(chinese)+"""

原核心假设的 σ=0.03，单位是每单位价格每平方根分钟的价格波动。表中把历史相对波动放到一个**虚构的价格为100的工具**上，再转成同类单位。真实 GBP/USD、HKD/USD 报价另行保留，不能把表中100理解成一英镑或一港元的美元价格，也不能称为真实股票波动率校准。

![历史参考汇率与时间划分](01-historical-prices.png)

## 为什么要检查时间单位

主估计使用两个参考日期之间的实际日历分钟数，并拟合平均漂移；方差自由度使用 n−1。另一种转换把每个参考观测步都当作1440分钟，两者均完整记录。

周五至周一与普通相邻日期的时间不同，节假日或缺失数据也会产生更长间隔。按实际间隔归一化避免无声把这些间隔当成一样长；但它仍然假定周末、休市和其他时段遵循同一种扩散。因此，两种转换都是需要说明的模型约定，日度数据无法证实真实分钟波动率。图中的年化数使用365个日历日，不能和股票252交易日的年化数字直接混用。

![日历间隔与单位转换](05-time-units.png)

## 用持出数据检查估计是否稳定

"""+ "\n".join(table)+f"""

“MSFE / forecast variance”是预测误差平方总和除以预测方差总和。接近1表示这个二阶误差尺度较接近预测；大于1可能来自风险低估、均值预测错误或波动变化，并不等于交易亏损或某个策略的胜率。

本次英镑固定估计的二阶误差比例约为{next(x for x in summaries if x['asset']=='GBPUSD' and x['method']=='static_training')['msfe_over_forecast_variance']:.3f}，港元约为{next(x for x in summaries if x['asset']=='HKDUSD' and x['method']=='static_training')['msfe_over_forecast_variance']:.3f}，说明训练期的固定参数并未以同样方式描述两个序列的评估期。不能仅挑一个指标宣称滚动估计更好；QLIKE越低越好，且只在同一序列内比较。

95%覆盖是实际误差落在正态模型95%区间内的比例。数据可能时变或相关，因此这里只报告经验值，不给它套上不适用的独立样本置信区间。我们保留分年度结果、全部慢/快波动时期，不根据结果改换窗口或宣称某一种估计永远最好。

![滚动与固定波动代理](02-volatility-history.png)

![持出预测诊断](03-holdout-diagnostics.png)

## 如何进入原来的金融执行模型

每种相对波动映射为 σ_core=100×σ_log，再生成连续执行计划。冲击参数 η、风险偏好 λ、订单量与60分钟期限保持原假设，比较原σ=0.03、日历估计和参考日估计三种计划。

英镑映射计划在前15分钟卖出约{next(x for x in s['model_link'] if x['asset']=='GBPUSD' and x['policy']=='calibrated_calendar')['first_quarter_quantity_fraction']*100:.2f}%，港元约{next(x for x in s['model_link'] if x['asset']=='HKDUSD' and x['policy']=='calibrated_calendar')['first_quarter_quantity_fraction']*100:.2f}%，原假设计划约{next(x for x in s['model_link'] if x['policy']=='original_assumption')['first_quarter_quantity_fraction']*100:.2f}%；较低的波动输入在这个模型里减少了提前交易的动机。

三种计划都在同一个冻结的日历波动模型里评价。日历估计计划的目标函数更低是该模型最优化的结果，不是“在真实历史成交中获得更高收益”。本项没有订单簿、成交价格或交易冲击识别数据。

![波动率输入如何改变连续库存计划](04-model-integration.png)

## Reproducible research

See the English research note, results.json and fixed design for methods, assumptions and numerical evidence. Code and research preparation use AI assistance.

"""
    (output/"中文研究解读.md").write_text(chinese_note,encoding="utf-8",newline="\n")

def render_figures(s,arrays,output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size":10,"axes.spines.top":False,"axes.spines.right":False,"figure.dpi":140})
    assets=list(s["design"]["assets"]);colors=["tab:purple","tab:cyan"];d=s["design"]
    training_start=date.fromisoformat(d["training_start"]);training_end=date.fromisoformat(d["training_end"])
    holdout_start=date.fromisoformat(d["evaluation_start"]);holdout_end=date.fromisoformat(d["evaluation_end"])
    fig,axes=plt.subplots(1,2,figsize=(12,4.8),layout="constrained")
    dates=[date.fromisoformat(r["date"]) for r in s["rates"]]
    for ax,asset,color in zip(axes,assets,colors,strict=True):
        ax.plot(dates,[r[asset] for r in s["rates"]],color=color,lw=1.2)
        ax.axvspan(training_start,training_end,color="tab:gray",alpha=.14,label="Training: 2022-2023")
        ax.axvspan(holdout_start,holdout_end,color="tab:blue",alpha=.08,label="Holdout: 2024-2025")
        ax.ticklabel_format(axis="y",style="plain",useOffset=False)
        ax.set(title=asset,xlabel="Reference date",ylabel=s["design"]["assets"][asset]["units"])
        ax.legend(fontsize=8);ax.tick_params(axis="x",rotation=25)
    fig.suptitle("ECB-derived cross-rates; informational reference prices")
    fig.savefig(output/"01-historical-prices.png");plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(12,4.8),layout="constrained")
    for ax,asset in zip(axes,assets,strict=True):
        for method in ("static_training",)+tuple(f"rolling_{w}" for w in d["rolling_windows"]):
            rows=[r for r in s["forecasts"] if r["asset"]==asset and r["method"]==method]
            ax.plot([date.fromisoformat(r["end_date"]) for r in rows],
                [r["sigma_per_sqrt_minute"]*math.sqrt(d["calibration"]["annual_calendar_minutes"])*100 for r in rows],
                label=method.replace("_"," "),lw=1 if method!="static_training" else 1.8)
        ax.set(title=asset,xlabel="Holdout reference date",ylabel="Calendar-annualized log-vol proxy (%)")
        ax.legend(fontsize=8);ax.tick_params(axis="x",rotation=25)
    fig.suptitle("Past-only fitted parameters; calendar diffusion is a modeling assumption")
    fig.savefig(output/"02-volatility-history.png");plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(12,4.8),layout="constrained")
    methods=["static_training"]+[f"rolling_{w}" for w in d["rolling_windows"]]
    for offset,(asset,color) in enumerate(zip(assets,colors,strict=True)):
        rows=[next(r for r in s["forecast_summary"] if r["asset"]==asset and r["method"]==m and r["period"]=="all") for m in methods]
        x=np.arange(len(methods))+(offset-.5)*.35
        axes[0].bar(x,[r["msfe_over_forecast_variance"] for r in rows],width=.35,label=asset,color=color)
        axes[1].bar(x,[r["empirical_normal_95_coverage"]*100 for r in rows],width=.35,label=asset,color=color)
    for ax in axes:
        ax.set_xticks(range(len(methods)),["Static"]+[f"Rolling {w}" for w in d["rolling_windows"]])
    handles,labels=axes[0].get_legend_handles_labels()
    fig.legend(handles,labels,loc="outside lower center",ncols=2,fontsize=9)
    axes[0].axhline(1,color="black",ls="--",lw=1);axes[0].set(title="Squared error versus forecast variance",ylabel="MSFE / forecast variance")
    axes[1].axhline(95,color="black",ls="--",lw=1);axes[1].set(title="Empirical normal 95% interval coverage",ylabel="Coverage (%)",ylim=(0,105))
    fig.suptitle("Full chronological holdout; descriptive statistics, no coverage CI")
    fig.savefig(output/"03-holdout-diagnostics.png");plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(12,4.8),layout="constrained")
    for ax,asset in zip(axes,assets,strict=True):
        for row in s["model_link"]:
            if row["asset"]!=asset:continue
            x=arrays[row["array_key"]];ax.plot(np.linspace(0,d["base"]["duration"],len(x)),x/d["base"]["quantity"]*100,label=row["policy"].replace("_"," "))
        ax.set(title=asset+" relative-volatility proxy",xlabel="Execution minute",ylabel="Remaining synthetic inventory (%)")
        ax.legend(fontsize=8)
    fig.suptitle("Hypothetical price-100 instruments; impact remains assumed")
    fig.savefig(output/"04-model-integration.png");plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(12,4.8),layout="constrained")
    gaps=s["cleaning_audit"]["calendar_gap_days"]
    axes[0].bar([int(k) for k in gaps],list(gaps.values()),color="tab:gray")
    axes[0].set(xlabel="Calendar days between retained reference dates",ylabel="Observed intervals",title="No forward filling of weekends / missing observations")
    for offset,(asset,color) in enumerate(zip(assets,colors,strict=True)):
        fit={r["mapping"]:r for r in s["calibration_fits"] if r["asset"]==asset}
        values=[d["base"]["volatility"],fit["calendar"]["sigma_equivalent_at_price_100"],fit["reference_day"]["sigma_equivalent_at_price_100"]]
        axes[1].bar(np.arange(3)+(offset-.5)*.35,values,width=.35,label=asset,color=color)
    axes[1].set_yscale("log");axes[1].set_xticks(range(3),["Assumed","Calendar","Reference day"])
    axes[1].set(ylabel="Price-100 sigma per sqrt-minute",title="Time mapping and price normalization");axes[1].legend(fontsize=8)
    fig.suptitle("Minute-scale values are mapped from daily references, not measured intraday")
    fig.savefig(output/"05-time-units.png");plt.close(fig)
