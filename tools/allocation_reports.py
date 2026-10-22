"""Portable Chinese evidence reports for synthetic pretrade and paired execution."""
import html
LABELS={'uniform':'均匀分批','frontloaded':'前快后慢','independent':'两笔独立执行','coordinated':'双资产协同'}
def esc(v):return html.escape(str(v),quote=True)
def num(v):return '—' if v is None else f'{v:,.5g}' if isinstance(v,float) else str(v)
def table(headers,rows):
    return '<table><thead><tr>'+''.join('<th>'+esc(x)+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(num(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table>'
def chart(series):
    maximum=max(1.,max(float(v) for values in series.values() for v in values));colors=['#b07d32','#176b60','#ba4d48','#426f9a']
    parts=['<svg viewBox="0 0 800 280" role="img" aria-label="执行进度回放">']
    for i,(label,values) in enumerate(series.items()):
        points=' '.join(f'{55+k/max(1,len(values)-1)*725:.2f},{210-float(v)/maximum*185:.2f}' for k,v in enumerate(values))
        parts.append(f'<polyline points="{points}" stroke="{colors[i%4]}" fill="none" stroke-width="2"/><text x="{55+(i%2)*380}" y="{240+(i//2)*20}" font-size="11" fill="{colors[i%4]}">{esc(label)}</text>')
    return ''.join(parts)+'</svg>'
def render(kind,e,digest):
    budget=kind=='budget';title='拆单实验室 · '+('成本预算助手报告' if budget else '双资产协同执行报告')
    names={'quantity':'卖出股数','price':'起始中价','deadline':'截止分钟','volume_per_minute':'预期每分钟成交量',
           'volatility_bps':'每分钟收益波动（基点）','spread_bps':'完整价差（基点）','fee_bps':'单边费用（基点）',
           'impact_bps':'100%参与率冲击（基点）','participation_rate':'参与率上限','budget_bps':'成本预算（基点）',
           'required_success':'规划达标比例要求','seed':'随机种子','sell_quantity':'卖出A股数','buy_quantity':'买入B股数',
           'sell_price':'A起始中价','buy_price':'B起始中价','initial_cash':'初始现金','correlation':'人工相关系数',
           'risk_weight':'协同风险权重','max_progress_gap':'预测进度差目标','scenario':'人工情形'}
    scenes={'balanced':'相对均衡','buy_slow':'B买入侧前段较慢','sell_slow':'A卖出侧前段较慢','dry':'两边均无成交容量'}
    settings=[(names.get(k,k),scenes.get(v,v) if isinstance(v,str) else v) for k,v in e['design'].items()]
    parts=['<p>全部为人工场景实验，不使用上传行情，不接真实券商。</p>',table(['设置','值'],settings)]
    extra_md=[]
    if budget:
        selected=next((r for r in e['candidates'] if r['id']==e['selected_id']),None)
        note=(f"规划集选择 {selected['horizon']} 分钟 · {LABELS[selected['pace']]}；独立验证联合达标 {selected['validation']['successes']}/256。验证不达标时仍保留原推荐，避免重选偏差。") if selected else '本次候选没有达到规划要求；不能证明其他交易方法都不可行。'
        parts+=['<h2>规划结论与独立检验</h2><p>'+esc(note)+'</p><p>联合达标 = 按时全部完成且到达价缺口不超过预算。每组256条人工路径；规划与独立验证种子：'+str(e['planning_seed'])+' / '+str(e['validation_seed'])+'。</p>']
        headers=['分钟','节奏','规划时长/达标前沿','规划达标/256','验证完成/256','验证达标/256','验证超预算/256','验证未完成/256','完成路径P95（基点）','共同完成均值（基点）']
        rows=[]
        for r in e['candidates']:
            v=r['validation'];rows.append([r['horizon'],LABELS[r['pace']],'是' if r['on_planning_frontier'] else '否',r['planning']['successes'],v['completed'],v['successes'],v['budget_breaches'],v['unfinished'],v['p95_complete_bps'],v['common_complete_mean_bps']])
        parts+=['<h2>候选取舍</h2>'+table(headers,rows),'<p>条件P95只来自各自完成路径，不能直接跨候选排名；共同完成均值使用同一组 '+str(e['dashboard_summary']['common_complete_count'])+' 条路径。负缺口是相对起始中价有利，不是投资利润。未完成计失败。</p>']
        row=selected or e['candidates'][-2];trace=row['validation_trace']
        parts+=['<h2>独立验证第一条路径 · '+str(row['horizon'])+'分钟 '+LABELS[row['pace']]+'（股）</h2>'+chart({'剩余股数':[e['design']['quantity']]+[x['remaining'] for x in trace]}),
                table(['分钟','尝试','容量','成交','剩余','半价差成本','费用','冲击成本','时机成本'],[[x[k] for k in ('minute','request','capacity','filled','remaining','spread_cost','fee_cost','impact_cost','timing_cost')] for x in trace])]
        extra_md=[note,'规划/验证种子：'+str(e['planning_seed'])+' / '+str(e['validation_seed'])]
    else:
        parts+=['<h2>资金与比较口径</h2><p>'+esc(e['funding_note'])+' 卖出回款当步用于买入，不借款、不做空。成本分母为两边起始总名义金额之和。</p>']
        headers=['方法','完成/32','平均A剩余','平均B剩余','平均风险积分','平均峰值风险','平均最大进度差','现金受限场景','共同完成均值（基点）','共同完成P95（基点）']
        rows=[[LABELS[x['planner']],x['completed'],x['mean_sell_remaining'],x['mean_buy_remaining'],x['mean_integrated_target_variance'],x['mean_peak_target_risk_std'],x['mean_max_progress_gap'],x['cash_limited_scenarios'],x['common_complete_mean_bps'],x['common_complete_p95_bps']] for x in e['dashboard_summary']['strategies']]
        parts+=['<h2>32条配对人工场景</h2>'+table(headers,rows),'<p>共同完成 '+str(e['dashboard_summary']['common_complete_count'])+' 条；完成率分母始终为32。风险积分单位：货币²·分钟；峰值为一分钟风险标准差（货币）。进度差为两边完成比例之差的绝对值。</p>',
                '<h2>全部场景期末标记诊断</h2><p>未成交余量按期末中价标记机会成本，不视为成交，不能替代完成率或共同完成成本。</p>'+table(['方法','平均标记缺口（基点）','P95标记缺口（基点）'],[[LABELS[x['planner']],x['mean_marked_bps_all'],x['p95_marked_bps_all']] for x in e['dashboard_summary']['strategies']])]
        series={}
        for p,row in e['policies'].items():
            for leg,q in [('sell',e['design']['sell_quantity']),('buy',e['design']['buy_quantity'])]:
                series[LABELS[p]+(' · A剩余%' if leg=='sell' else ' · B剩余%')]=[100.]+[100*x[leg+'_remaining']/q for x in row['trace']]
        parts+=['<h2>输入种子的单场景回放（非平均结果）</h2>'+chart(series),
                '<h2>协同方案现金与进度</h2>'+table(['分钟','卖A','买B','A剩余','B剩余','现金','目标偏离风险','进度差','现金受限'],[[x['minute'],x['sell_filled'],x['buy_filled'],x['sell_remaining'],x['buy_remaining'],x['cash_cents']/100,x['risk_std'],x['progress_gap'],x['cash_limited']] for x in e['policies']['coordinated']['trace']])]
        extra_md=[e['funding_note'],'共同完成场景：'+str(e['dashboard_summary']['common_complete_count'])]
    parts+=['<h2>方法与局限</h2><p>'+esc(e['limitations'])+'</p><p>代码和研究整理使用AI辅助。完整数值依据见 evidence.json。</p>']
    css='body{font:14px/1.8 "Microsoft YaHei",sans-serif;color:#183a34;max-width:1100px;margin:30px auto;padding:20px}table{border-collapse:collapse;width:100%;font-size:11px}th,td{border:1px solid #ccd9d1;padding:6px;overflow-wrap:anywhere}thead{background:#edf3ef}svg{width:100%}p{overflow-wrap:anywhere}@page{size:A4 landscape;margin:12mm}@media print{thead{display:table-header-group}tr,svg{break-inside:avoid}h2{break-after:avoid}}'
    page='<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>'+title+'</title><style>'+css+'</style></head><body><h1>'+title+'</h1><p>实验记录 SHA-256：'+esc(digest)+'</p>'+''.join(parts)+'</body></html>'
    md=['# '+title,'','实验记录 SHA-256：'+digest,'','全部为人工场景实验。','',*['- '+str(k)+'：'+str(v) for k,v in settings],'',*extra_md,'','| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(headers))+'|',*['| '+' | '.join(num(v) for v in row)+' |' for row in rows],'','## 局限',e['limitations'],'','完整图表见 report.html；全部数值见 evidence.json。']
    return page,'\n'.join(md)+'\n'
