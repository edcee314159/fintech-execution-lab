"""Portable Chinese reports for saved local experiments; no remote assets."""
import html
import json
import math
import importlib.util
from pathlib import Path
_adaptive_spec=importlib.util.spec_from_file_location("execution_adaptive_reports",Path(__file__).with_name("adaptive_reports.py"))
_adaptive_reports=importlib.util.module_from_spec(_adaptive_spec);_adaptive_spec.loader.exec_module(_adaptive_reports)
_extension_spec=importlib.util.spec_from_file_location("execution_extension_reports",Path(__file__).with_name("extension_reports.py"))
_extension_reports=importlib.util.module_from_spec(_extension_spec);_extension_spec.loader.exec_module(_extension_reports)


def safe_text(value):
    return html.escape(str(value), quote=True)


def number(value):
    if value is None:
        return '—'
    if isinstance(value, float):
        return f'{value:,.4g}'
    return str(value)


def table(headers, rows):
    return '<table><thead><tr>'+''.join('<th>'+safe_text(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+safe_text(number(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table>'


def lines_svg(series, labels):
    colors=['#bd792f','#176b60'];width,height=700,230
    maximum=max(1.,max(float(v) for values in series for v in values))
    if not math.isfinite(maximum):
        raise ValueError('图表数值不是有限值。')
    items=['<svg viewBox="0 0 700 260" role="img" aria-label="两种拆单计划的比较曲线">']
    for level in range(5):
        y=190-level*42
        items.append(f'<line x1="60" x2="680" y1="{y}" y2="{y}" stroke="#e3eae6"/><text x="54" y="{y+4}" text-anchor="end" font-size="11">{maximum*level/4:,.0f}</text>')
    for k,(values,label) in enumerate(zip(series,labels)):
        points=' '.join(f'{60+i/max(1,len(values)-1)*620:.2f},{190-float(v)/maximum*168:.2f}' for i,v in enumerate(values))
        items.append(f'<polyline points="{points}" stroke="{colors[k]}" stroke-width="2.5" fill="none"/><text x="{60+k*260}" y="225" fill="{colors[k]}">{safe_text(label)}</text>')
    items.append('</svg>')
    return ''.join(items)


def completion_svg(rows):
    height=50+len(rows)*35
    items=[f'<svg viewBox="0 0 800 {height}" role="img" aria-label="各方法完成率，包含未生成计划的情形">']
    for i,row in enumerate(rows):
        y=20+i*35;total=row['cases'];done=row['completed'];rate=done/total if total else 0
        label=row['predictor']+' / '+row['planner']
        items.append(f'<text x="0" y="{y+15}" font-size="12">{safe_text(label)}</text><rect x="340" y="{y}" width="340" height="21" fill="#e7eeea"/><rect x="340" y="{y}" width="{340*rate:.2f}" height="21" fill="#176b60"/><text x="690" y="{y+15}" font-size="12">{done}/{total}</text>')
    return ''.join(items)+'</svg>'


PREDICTORS={'uniform':'均匀成交量','historical_shape':'历史日内分布','previous_day':'前一交易日'}
PLANNERS={'twap_capped':'带上限均匀卖出','volume_capped':'按成交量分配','arrival_constrained':'成本风险权衡'}


def labelled(rows):
    return [{**r,'predictor':PREDICTORS.get(r['predictor'],r['predictor']),'planner':PLANNERS.get(r['planner'],r['planner'])} for r in rows]


_allocation_spec=importlib.util.spec_from_file_location("execution_allocation_reports",Path(__file__).with_name("allocation_reports.py"))
_allocation_reports=importlib.util.module_from_spec(_allocation_spec);_allocation_spec.loader.exec_module(_allocation_reports)

_safety_spec=importlib.util.spec_from_file_location("execution_safety_reports",Path(__file__).with_name("safety_reports.py"))
_safety_reports=importlib.util.module_from_spec(_safety_spec);_safety_spec.loader.exec_module(_safety_reports)

def render_report(kind, experiment, source_hash):
    if kind in ('recovery','marketguard'):return _safety_reports.render(kind,experiment,source_hash)
    if kind in ('budget','pairs'):return _allocation_reports.render(kind,experiment,source_hash)
    if kind=='adaptive':return _adaptive_reports.render(experiment,source_hash)
    if kind in ('signal','orderbook'):return _extension_reports.render(kind,experiment,source_hash)
    title='拆单实验室 · '+('基础模型实验报告' if kind=='core' else '滚动成交容量验证报告')
    text=[f'# {title}',f'\n实验记录 SHA-256：`{source_hash}`']
    sections=[]
    if kind=='core':
        config=experiment['config'];summary=experiment['summary'];names=('twap','ac_simplified')
        labels={'quantity':'卖出数量（股）','duration':'时长（分钟）','intervals':'时段数','price':'起始价格（货币/股）','volatility':'每平方根分钟的价格波动尺度','impact':'价格影响系数','risk_aversion':'风险权重','trials':'模拟次数','seed':'随机种子'}
        sections.append('<h2>实验设置</h2>'+table(['参数','值'],[(labels.get(k,k),v) for k,v in config.items()]))
        text+=['\n## 实验设置',*['- '+labels.get(k,k)+'：'+number(v) for k,v in config.items()]]
        schedule=[experiment['schedules'][n]['quantities'] for n in names]
        inventory=[experiment['schedules'][n]['inventory'] for n in names]
        sections.append('<h2>每时段计划卖出股数</h2><p>横向为时段顺序，纵向为股数。</p>'+lines_svg(schedule,['均匀卖出','模型拆单'])+'<h2>计划剩余股数</h2>'+lines_svg(inventory,['均匀卖出','模型拆单']))
        rows=[]
        for n,label in zip(names,['均匀卖出','模型拆单']):
            s=summary['strategies'][n];ci=s['empirical']['ci95_mean']
            rows.append([label,s['prediction']['mean'],s['prediction']['std'],s['prediction']['objective'],s['empirical']['mean'],' ～ '.join(number(v) for v in ci) if ci else '—'])
        sections.append('<h2>成本与风险（货币单位）</h2>'+table(['方法','理论均值','理论标准差','均值加权方差目标','模拟均值','模拟均值 95% 区间'],rows))
        text+=['\n## 成本与风险','| 方法 | 理论均值 | 标准差 | 风险权衡目标 | 模拟均值 | 95% 区间 |','|---|---:|---:|---:|---:|---|',*['| '+' | '.join(number(v) for v in r)+' |' for r in rows]]
        limits=f"{summary['valid_pairs']}/{summary['total_pairs']} 对路径在模型范围内；{summary['invalid_pairs']} 对出现非正价格。模拟统计仅使用有效路径，存在无效路径时属于条件样本。95% 区间衡量模拟均值误差，不是单次成本预测。基础模型假设计划全部成交，未验证市场容量、手续费、买卖价差或排队；整数方案不保证全局最优，不能证明实盘盈利。"
    else:
        summary=experiment['dashboard_summary'];context=experiment['input_provenance'];design=experiment['design'];dates=experiment['evaluation_calendar_dates']
        settings=[['数据标的',design['symbols'][0]],['输入来源',context['origin_note']],['输入原文件指纹',context['source_sha256']],['适配文件指纹',context['loader_sha256']],['完整交易日',summary['available_sessions']],['本次评估日期数',len(dates)],['评估起止',dates[0]+' 至 '+dates[-1]],['回看天数',design['lookback']],['订单占过去平均日量',design['fractions'][0]],['成交参与上限',design['participation_rate']],['价格冲击参数',design['impact']],['风险权重',design['risk_aversion']]]
        sections.append('<h2>数据和参数</h2>'+table(['项目','值'],settings))
        text+=['\n## 数据和参数',*['- '+a+'：'+safe_text(b) for a,b in settings]]
        rows=labelled(summary['strategies'])
        sections.append('<h2>计划与完成情况</h2><p>分母包含未生成计划的情形；同一日期的多种方案不是独立市场样本。</p>'+completion_svg(rows)+table(['预测','拆单方法','全部情形','已生成计划','完成','已计划但未完成','未生成计划','已生成计划平均剩余'],[[r['predictor'],r['planner'],r['cases'],r['planned'],r['completed'],r['planned']-r['completed'],r['cases']-r['planned'],r['mean_residual_planned']] for r in rows]))
        text+=['\n## 完成情况','| 预测 | 方法 | 全部情形 | 计划 | 完成 | 未生成计划 |','|---|---|---:|---:|---:|---:|',*['| '+' | '.join(map(str,[r['predictor'],r['planner'],r['cases'],r['planned'],r['completed'],r['cases']-r['planned']]))+' |' for r in rows]]
        grouped=summary['regimes'];sections.append('<h2>按市场状态分组（事后描述）</h2><p>目标日的量和波动与其过去窗口中位数比较：低于 0.8 倍为低，高于 1.2 倍为高，其余为常态。分组不用于当日预测或下单，不据此挑选表现好的日期。</p>'+table(['分组维度','状态','预测','方法','日期数','情形','完成'],[[r['dimension'],r['regime'],PREDICTORS[r['predictor']],PLANNERS[r['planner']],r['dates'],r['cases'],r['completed']] for r in grouped]))
        price_rows=[]
        for c in experiment['comparisons']:
            for planner,row in c['strategies'].items():
                price_rows.append([PREDICTORS[c['predictor']],PLANNERS[planner],c['common_complete_count'],row['common_complete_mean_marked_bps']])
        sections.append('<h2>价格诊断（假设价格与冲击，单位：基点）</h2><p>仅比较同一预测方法、同一订单大小下三种拆单方法共同完成的日期。不同预测方法的日期子集可能不同，不作跨预测方法成本排名。剩余股票按期末价格计价不等于卖出。</p>'+table(['预测','方法','共同完成日期数','平均标记缺口'],price_rows))
        limits='这是用户本地输入的容量回放，数据真实性、全市场覆盖和使用授权未独立核实。只使用每个目标日之前的完整上传交易日训练；不识别整日缺失、节假日或提前收盘。量和波动分组为事后分析。短样本或人工测试不能形成长期实盘结论；模拟完成不等于交易所成交，价格诊断不是已实现收益。未校准价格冲击与风险偏好，不模拟完整订单簿、费用、价差或排队，不进行年化或显著性优劣声明。'
        text+=['\n## 评估日期',', '.join(dates),'\n## 分组说明','分组仅为事后描述，不用于预测和下单；详细分组表、价格诊断和图表见同目录 HTML，完整记录见 evidence.json。']
    sections.append('<h2>局限与复现</h2><p>'+safe_text(limits)+'</p><p>代码与研究整理使用 AI 辅助。同行文件 evidence.json 保存本报告依据的实验记录及其指纹；图表均由这些记录生成。无外部图像、脚本或网络字体。</p>')
    text+=['\n## 局限与复现',limits,'\n代码与研究整理使用 AI 辅助。完整数值依据见 evidence.json，图表见 report.html。']
    css='body{font:14px/1.8 "Segoe UI","Microsoft YaHei",sans-serif;color:#183a34;max-width:1000px;margin:35px auto;padding:20px}h1{font-size:26px;border-bottom:3px solid #176b60}h2{font-size:19px;margin-top:28px}p{overflow-wrap:anywhere}table{border-collapse:collapse;width:100%;font-size:12px}th,td{border:1px solid #cbd9d1;padding:7px;text-align:left;overflow-wrap:anywhere}thead{background:#edf3ef;display:table-header-group}tr{break-inside:avoid}svg{display:block;width:100%;max-height:400px;margin:12px 0}code{overflow-wrap:anywhere}@page{size:A4;margin:14mm}@media print{body{margin:0;padding:0;max-width:none;font-size:11px}h2{break-after:avoid}svg{break-inside:avoid;max-height:80mm}}'
    page='<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+safe_text(title)+'</title><style>'+css+'</style></head><body><h1>'+safe_text(title)+'</h1><p>实验记录指纹：<code>'+safe_text(source_hash)+'</code></p>'+''.join(sections)+'</body></html>'
    return page,'\n'.join(text)+'\n'
