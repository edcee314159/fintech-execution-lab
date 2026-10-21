"""Offline Chinese presentation of adaptive replay; evidence retains all dates."""
import html

LABELS={'fixed_twap':'固定均匀拆单','fixed_volume':'固定按历史成交量拆单','adaptive':'动态风险预警拆单'}
LIMITS='容量覆盖比例与固定后续计划完成比例只是历史场景占比，不是已校准的成交概率；历史 p10–p90 区间不保证未来有 80% 覆盖率。每次决策只用过去完整交易日和当天此前已结束时段，不读取当前或未来成交量。成交仍按事后五分钟总量限制及收盘价假设回放，不含订单簿、排队、费用、价差或撤单成本。动态未成数量下期重新优化，不自动放宽参与率、延长截止时间或更改订单量。剩余股票期末计价不等于成交；冲击参数固定为 0.00001，未作真实交易校准。'


def esc(v):return html.escape(str(v),quote=True)
def num(v):return '—' if v is None else (f'{v:,.4g}' if isinstance(v,float) else str(v))
def table(headers,rows):
    return '<table><thead><tr>'+''.join('<th>'+esc(x)+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(num(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table>'


def trace_svg(trace):
    keys=['capacity_p10','capacity_p50','capacity_p90','remaining_before'];colors=['#b07d32','#498379','#176b60','#ba4d48']
    labels=['容量 p10','容量中位数','容量 p90','尚待卖出']
    maximum=max(1,max(float(r[k]) for r in trace for k in keys));items=['<svg viewBox="0 0 760 280" role="img" aria-label="剩余容量历史场景区间与剩余订单">']
    for i in range(5):
        yy=210-i*46;items.append(f'<line x1="70" x2="740" y1="{yy}" y2="{yy}" stroke="#dce5df"/><text x="65" y="{yy+4}" text-anchor="end" font-size="11">{maximum*i/4:,.0f}</text>')
    for k,color,label in zip(keys,colors,labels):
        points=' '.join(f'{70+r["interval"]/77*670:.2f},{210-r[k]/maximum*184:.2f}' for r in trace)
        items.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2"/>')
    for i,(label,color) in enumerate(zip(labels,colors)):items.append(f'<text x="{70+i*165}" y="255" fill="{color}" font-size="12">{label}</text>')
    items.append('<text x="70" y="230" font-size="11">开盘前决策</text><text x="645" y="230" font-size="11">最后五分钟前</text></svg>')
    return ''.join(items)


def render(experiment,source_hash):
    e=experiment;s=e['dashboard_summary'];c=e['calibration'];p=e['input_provenance'];config=e['design']
    title='拆单实验室 · 成交容量风险预警与动态拆单报告'
    settings=[['标的',e['symbol']],['来源',p['origin_note']],['原文件 SHA-256',p['source_sha256']],['适配文件 SHA-256',p['loader_sha256']],['评估区间',s['evaluation_start']+' 至 '+s['evaluation_end']],['独立评估日期数',s['evaluation_days']],['训练窗口完整日',s['training_window']],['订单 / 历史平均日量',config['fraction']],['参与率上限',config['participation_rate']]]
    rows=[[LABELS[r['planner']],r['cases'],r['completed'],r['cases']-r['completed'],r['mean_residual'],r['mean_assumed_impact']] for r in s['strategies']]
    paired=[[LABELS[r['planner']],r['common_complete_count'],r['common_complete_mean_marked_bps']] for r in s['strategies']]
    parts=['<h2>数据与参数</h2>'+table(['项目','值'],settings),'<h2>同量、同时限、同参与率的对照</h2><p>均为卖单。固定计划未成需求累计等待；动态方案每五分钟重新分配未成需求。完成率分母保留所有日期。</p>'+table(['方法','日期','完成','未完成','平均剩余股数','平均假设冲击成本'],rows),'<h2>共同完成日期上的成本诊断</h2><p>只在三种方案都完成的同一组日期比较基点缺口；不以少成交来降低成本。期末剩余计价的全样本诊断仅保存在完整证据中。</p>'+table(['方法','共同完成日期数','平均假设缺口（基点）'],paired)]
    coverage=[[x['interval']*5,x['dates'],x['covered_dates'],x['covered_dates']/x['dates']] for x in c['checkpoints']]
    parts+=['<h2>预测区间的样本外检查</h2><p>以下在事先固定的检查时点统计 p10–p90 区间是否覆盖后来实际出现的剩余总容量。一个交易日的多个时点不视为独立日期。所有时点覆盖率：'+esc(num(c['band_coverage']))+'；容量覆盖场景占比的 Brier 诊断：'+esc(num(c['capacity_cover_brier']))+'（越小越好，仅统计仍有剩余订单的决策）。短样本不构成概率校准结论。</p>'+table(['开盘后分钟','日期数','覆盖日期数','实际覆盖比例'],coverage)]
    latest=e['daily'][-1];parts+=['<h2>'+esc(latest['date'])+' 的动态风险轨迹</h2><p>各点是当前五分钟开始前的预测。容量区间是历史场景分位数。完整日期与每五分钟的依据均在 evidence.json。</p>'+trace_svg(latest['trace'])]
    trace_rows=[[r['minute'],r['remaining_before'],r['capacity_p10'],r['capacity_p90'],r['capacity_cover_share'],r['continuation_completion_share'],r['request'],r['filled'],r['remaining_after']] for r in latest['trace'] if r['interval'] in (0,12,39,60,77) or r['accelerated']]
    parts+=[table(['分钟','待卖股数','容量 p10','容量 p90','容量覆盖场景比','固定后续计划完成场景比','本期尝试','回放成交','剩余'],trace_rows),'<h2>方法与局限</h2><p>根据过去成交量路径生成场景，并用当天已发生累计量校正；加入相当于三个五分钟历史均量的先验，避免开盘少量观测造成极端缩放。若后续容量 p10 不足，则提高本期尝试数量；最终成交仍受同一参与率上限限制。</p><p>'+esc(LIMITS)+'</p><p>代码与研究整理使用 AI 辅助。同行证据文件保存完整记录。图表没有外部资源。</p>']
    css='body{font:14px/1.8 "Microsoft YaHei",sans-serif;max-width:1050px;margin:30px auto;padding:20px;color:#183a34}table{border-collapse:collapse;width:100%;font-size:11px}th,td{border:1px solid #cbd9d1;padding:6px;overflow-wrap:anywhere}thead{background:#edf3ef}svg{width:100%;display:block}p{overflow-wrap:anywhere}h2{margin-top:25px}@page{size:A4;margin:12mm}@media print{body{margin:0;padding:0;font-size:11px}thead{display:table-header-group}tr,svg{break-inside:avoid}h2{break-after:avoid}}'
    page='<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>'+title+'</title><style>'+css+'</style></head><body><h1>'+title+'</h1><p>实验记录 SHA-256：'+esc(source_hash)+'</p>'+''.join(parts)+'</body></html>'
    md=['# '+title,'','实验记录 SHA-256：`'+source_hash+'`','',*['- '+a+'：'+esc(num(b)) for a,b in settings],'','## 同量对照','| 方法 | 日期 | 完成 | 未完成 | 平均剩余 | 假设冲击成本 |','|---|---:|---:|---:|---:|---:|',*['| '+' | '.join(num(v) for v in r)+' |' for r in rows],'','## 区间检验','固定时点的覆盖统计与逐时轨迹见 report.html。完整记录见 evidence.json。','独立评估日期数：'+str(s['evaluation_days']),'','## 局限',LIMITS]
    return page,'\n'.join(md)+'\n'
