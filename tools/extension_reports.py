"""Portable reports for signal execution and explicitly artificial queue replay."""
import html
LABELS={'capacity':'不用价格信号','always':'始终相信信号','trusted':'按历史验证降权','passive':'始终挂单','aggressive':'始终主动成交','dynamic':'动态切换'}
SIGNAL_LIMITS='信号只在过去完整日训练，权重来自过去逐日验证误差相对零预测的改善，不是概率或未来有效性的保证。无信号和反向信号为压力测试。速度调整为受容量保护的启发式单步价格与冲击权衡，不构成最优执行证明。五分钟成交仍按事后总量与收盘价假设，不含价差、费用、队列和撤单成本；冲击参数0.00001未校准。'
BOOK_LIMITS='全部盘口、成交流和取消事件均由固定种子人工生成，不是从分钟行情还原的真实订单簿。单档卖队列、三档买深度及外生价格是假设；取消队前量仅在人工模型中可知。先匹配旧挂单，再执行到达的撤改单，延迟以一秒步长计。参与率为事后每步外部成交量配额，不是实盘连续参与率控制。费用和返佣是假设；未模拟内生冲击、隐藏流动性和交易所规则。剩余期末计价不是成交，不证明盈利或真实市场优势。'


def esc(v):return html.escape(str(v),quote=True)
def num(v):return '—' if v is None else (f'{v:,.5g}' if isinstance(v,float) else str(v))
def table(headers,rows):return '<table><thead><tr>'+''.join('<th>'+esc(x)+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(num(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table>'


def curves(series):
    maximum=max(1,max(max(x) for x in series.values()));colors=['#b07d32','#176b60','#ba4d48'];parts=['<svg viewBox="0 0 760 260" role="img" aria-label="三种方案剩余数量对照">']
    for k,(label,values) in enumerate(series.items()):
        points=' '.join(f'{60+i/max(1,len(values)-1)*680:.2f},{210-v/maximum*185:.2f}' for i,v in enumerate(values))
        parts.append(f'<polyline points="{points}" fill="none" stroke="{colors[k]}" stroke-width="2"/><text x="{60+k*225}" y="245" fill="{colors[k]}" font-size="12">{esc(label)}</text>')
    return ''.join(parts)+'</svg>'


def render(kind,e,digest):
    signal=kind=='signal';title='拆单实验室 · '+('信号可信度与执行速度报告' if signal else '人工订单簿：挂单与主动成交报告');s=e['dashboard_summary'];labels={'lookback':'回看完整日','evaluation_days':'最多评估日','fraction':'订单/历史平均日量','participation_rate':'参与率上限','signal_scenario':'信号压力情形','scenario':'人工盘口情形','quantity':'卖出数量','seed':'随机种子','latency_ticks':'延迟秒数'};values={'learned':'历史模型信号','zero':'无信号','inverted':'反向信号','balanced':'相对均衡','thin':'流动性稀薄','adverse':'被动成交后不利变化'};settings=[(labels.get(k,k),values.get(v,v) if isinstance(v,str) else v) for k,v in e['design'].items() if k!='upload_id'];parts=[]
    limits=SIGNAL_LIMITS if signal else BOOK_LIMITS
    if signal:
        p=e['input_provenance'];settings=[('数据标的',e['symbol']),('来源',p['origin_note']),('原文件指纹',p['source_sha256']),('适配文件指纹',p['loader_sha256']),*settings]
        rows=[[LABELS[r['planner']],r['cases'],r['completed'],r['mean_residual'],r['mean_assumed_impact'],r['common_complete_count'],r['common_complete_mean_marked_bps']] for r in s['strategies']]
        headers=['方法','日期数','完成日期','平均剩余','共同完成假设冲击成本','共同完成日期','共同完成缺口（基点）']
        parts+=['<p>同一目标日使用相同订单、截止时间和参与率。成本只在三种方案共同完成的同一组日期比较，所有未完成日期保留。不同信号情形是不同压力测试，不应混作独立市场样本。</p>']
        parts+=['<h2>历史验证权重</h2>'+table(['目标日','训练开始','训练结束','历史验证权重','相对零预测验证误差'],[[d['date'],d['model']['train_dates'][0],d['model']['train_dates'][-1],d['model']['reliability'],d['model']['validation_sse']/d['model']['zero_signal_sse'] if d['model']['zero_signal_sse']>1e-20 else None] for d in e['daily']])]
        day=e['daily'][-1];series={LABELS[k]:[x['remaining_before'] for x in day['traces'][k]] for k in LABELS if k in day['traces']}
        details=table(['分钟','权重','下一步收益预测','容量基准尝试','保护下限','最终尝试','回放成交','剩余'],[[x['minute'],x['weight'],x['predicted_return'],x['baseline_request'],x['required_now'],x['request'],x['filled'],x['remaining_after']] for x in day['traces']['trusted']])
        caption=day['date']+'：每五分钟决策的完整轨迹，非实盘收益。'
    else:
        settings=[('数据性质','全部人工生成；不使用上传行情'),*settings]
        headers=['方法','完成','剩余','被动成交','主动成交','撤单数','费用/返佣','共同完成缺口（基点）']
        rows=[[LABELS[r['planner']],r['completed'],r['mean_residual'],r['maker_shares'],r['taker_shares'],r['cancel_count'],r['fees'],r['common_complete_mean_marked_bps']] for r in s['strategies']]
        parts+=['<p>三种方案共享同一条人工外生事件流，每步最多使用同样比例的外部成交量。若任一方案未完成，共同完成成本为空。每次运行只是一个人工场景，不是一个真实交易日。</p>']
        series={LABELS[k]:[e['design']['quantity']]+[x['remaining'] for x in p['trace']] for k,p in e['policies'].items()}
        details=table(['步','订单','状态','数量/剩余','动作'],[[x['tick'],x['order_id'],x['status'],x.get('quantity',x.get('remaining',x.get('unfilled','—'))),x.get('action','—')] for x in e['policies']['dynamic']['orders'][:80]])
        caption='动态方案的前80条生命周期事件；完整记录见 evidence.json。'
        parts+=['<h2>卖方成交后的中价变动诊断</h2><p>成交后10步中价上升记为卖方不利变动，按有足够后续事件的成交股数加权；不把缺少后续价格的末尾成交填零。</p>'+table(['方法','可评估股数','10步后不利中价变动（基点）'],[[LABELS[r['planner']],r['markout_eligible_shares'],r['seller_adverse_mid_move_bps_10ticks']] for r in s['strategies']])]
    parts=['<h2>参数与来源</h2>'+table(['项目','值'],settings),'<h2>执行对照</h2>'+table(headers,rows),*parts,'<h2>剩余数量轨迹</h2>'+curves(series),'<h2>'+esc(caption)+'</h2>'+details,'<h2>方法与局限</h2><p>'+esc(limits)+'</p><p>代码与研究整理使用AI辅助。完整设置与数值依据在 evidence.json；图表不依赖外部资源。</p>']
    css='body{font:14px/1.8 "Microsoft YaHei",sans-serif;color:#183a34;max-width:1050px;margin:30px auto;padding:20px}table{border-collapse:collapse;width:100%;font-size:11px}th,td{border:1px solid #ccd9d1;padding:6px;overflow-wrap:anywhere}thead{background:#edf3ef}svg{width:100%}p{overflow-wrap:anywhere}@page{size:A4;margin:12mm}@media print{thead{display:table-header-group}tr,svg{break-inside:avoid}h2{break-after:avoid}}'
    page='<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>'+title+'</title><style>'+css+'</style></head><body><h1>'+title+'</h1><p>实验记录 SHA-256：'+esc(digest)+'</p>'+''.join(parts)+'</body></html>'
    md=['# '+title,'','实验记录 SHA-256：`'+digest+'`','',*['- '+esc(a)+'：'+esc(num(b)) for a,b in settings],'','| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(headers))+'|',*['| '+' | '.join(num(v) for v in row)+' |' for row in rows],'','## 局限',limits,'','完整图表见 report.html，完整数值与生命周期事件见 evidence.json。']
    return page,'\n'.join(md)+'\n'
