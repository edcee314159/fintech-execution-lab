"""Portable Chinese evidence for synthetic order recovery and market-state gates."""
import html
LABELS={'timeout_retry':'无保护的超时重发示例','reconciled':'持久化意图与对账恢复','unchecked':'无状态检查示例','guarded':'行情状态保护'}
STATES={'normal':'正常','recovering':'恢复观察/限速','closed':'常规时段外或闭市','status_unknown':'交易状态不明',
        'halted':'已确认停牌','quote_only':'只报价，尚未恢复交易','invalid_data':'无效报价','feed_gap':'序列缺口待快照',
        'stale_data':'报价过期','volume_unknown':'成交量数据不明'}
def esc(v):return html.escape(str(v),quote=True)
def table(headers,rows):
    return '<table><thead><tr>'+''.join('<th>'+esc(x)+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc('—' if x is None else x)+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table>'
def curves(series):
    maximum=max(1.,max(float(v) for a in series.values() for v in a));colors=['#b07d32','#176b60','#ba4d48']
    parts=['<svg viewBox="0 0 800 280" role="img" aria-label="数量和预留回放">']
    for i,(label,a) in enumerate(series.items()):
        points=' '.join(f'{55+k/max(1,len(a)-1)*720:.2f},{210-float(v)/maximum*180:.2f}' for k,v in enumerate(a))
        parts.append(f'<polyline points="{points}" fill="none" stroke="{colors[i]}" stroke-width="2"/><text x="{55+i*240}" y="250" font-size="11" fill="{colors[i]}">{esc(label)}</text>')
    return ''.join(parts)+'</svg>'
def render(kind,e,digest):
    recovery=kind=='recovery';title='拆单实验室 · '+('断线、重复回报与订单恢复' if recovery else '异常行情、停复牌与恢复保护')
    names={'quantity':'母单股数','scenario':'人工情形','seed':'随机种子','stale_after':'报价最大年龄（秒）',
           'recovery_ticks':'观察后恢复步数','max_child':'保护方案子单上限','participation_rate':'成交参与上限','session_date':'纽约本地交易日期'}
    scenes={'mixed':'混合故障','lost_ack':'确认丢失后断线','cancel_race':'撤单在途与断线','unresolved':'快照缺失未知订单',
            'stale':'行情中断与过期','halt':'停牌、只报价与交易恢复','zero':'有新报价但零成交量','gap':'序列缺口与快照','early_close':'提前收盘边界'}
    settings=[(names.get(k,k),scenes.get(v,v) if isinstance(v,str) else v) for k,v in e['design'].items()]
    parts=['<p>全部为人工故障实验，没有真实账户或券商连接。无保护对照是故意缺少检查的示例，不是另一套生产策略。</p>',table(['设置','值'],settings)]
    if recovery:
        headers=['方案','实际成交','已知成交','剩余','超卖','同意图重复下单','恰好完成母单']
        rows=[[LABELS[x['planner']],x['actual_filled'],x['known_filled'],x['residual'],x['oversold'],x['duplicate_order_submissions'],x['complete']] for x in e['dashboard_summary']['strategies']]
        parts+=['<h2>数量核对</h2>'+table(headers,rows),'<p>实际成交和实际持仓仅用于事后诊断，恢复器不会在断线时偷看模拟券商状态。只有完整订单、成交和持仓快照一致时才允许恢复；取消状态不会单独释放预留。</p>']
        t=e['policies']['reconciled']['trace']
        parts+=['<h2>保护方案的数量边界（股）</h2>'+curves({'本地已知成交':[x['known_filled'] for x in t],'仍可能成交的预留':[x['reserved'] for x in t],'实际成交（事后）':[x['actual_filled'] for x in t]}),
                table(['步','动作','本地已知成交','预留','可安全新增','状态已核实','实际成交（事后）','实际持仓（事后）','问题'],[[x[k] for k in ('step','action','known_filled','reserved','available','ready','actual_filled','actual_position','fault')] for x in t]),
                '<h2>持久化事件链</h2><p>每条先保存、刷新并请求fsync，再更新内存状态。序号与前序指纹连续；文件破损不自动截断。指纹用于完整性核对，不是防篡改签名。完整事件载荷在 evidence.json。</p>'+table(['序号','事件','事件指纹'],[[r['seq'],r['event']['kind'],r['sha256']] for r in e['journal']])]
    else:
        headers=['方案','成交','剩余','完成','保护规则外尝试','只报价时尝试','超过子单上限尝试','最大子单请求']
        rows=[[LABELS[x['planner']],x['filled'],x['residual'],x['complete'],x['unsafe_attempts'],x['quote_only_attempts'],x['oversized_attempts'],x['peak_child_request']] for x in e['dashboard_summary']['strategies']]
        parts+=['<h2>故障与完成情况</h2>'+table(headers,rows),'<p>保护规则外尝试指按本模块门控本应暂停时仍提交，不是交易所违规认定。无状态检查对照不限制追单请求；两方案共享母单、截止和事后成交参与上限。物理停牌、只报价及常规闭市期间两者都不能虚构成交。</p>']
        series={LABELS[p]:[e['design']['quantity']]+[x['remaining'] for x in row['trace']] for p,row in e['policies'].items()}
        parts+=['<h2>剩余量（股）</h2>'+curves(series)]
        t=e['policies']['guarded']['trace']
        parts+=['<h2>保护器逐秒状态</h2>'+table(['秒','纽约本地时间','状态','报价年龄','恢复比例','请求','成交','剩余','原因'],[[x['tick'],x['timestamp'],STATES[x['state']],x['quote_age'],round(x['ramp'],3),x['request'],x['filled'],x['remaining'],x['reason']] for x in t]),
                '<h2>日历范围</h2><p>仅2026年Nasdaq股票常规时段，纽约本地时间；非完整全球日历，不用于自动修复已有上传文件。来源：<a href="'+esc(e['calendar']['source'])+'">Nasdaq交易日历</a>，核对日期 '+esc(e['calendar']['checked_date'])+'。本日时段分钟范围（空值为闭市）：'+esc(e['calendar']['session_minutes'])+'。</p>']
    parts+=['<h2>方法与局限</h2><p>'+esc(e['limitations'])+'</p><p>代码与研究整理使用AI辅助。完整设置、轨迹和记录见 evidence.json。</p>']
    css='body{font:14px/1.8 "Microsoft YaHei",sans-serif;color:#183a34;max-width:1100px;margin:25px auto;padding:20px}table{border-collapse:collapse;width:100%;font-size:10px}th,td{border:1px solid #ccd9d1;padding:5px;overflow-wrap:anywhere}thead{background:#edf3ef}svg{width:100%}p{overflow-wrap:anywhere}@page{size:A4 landscape;margin:12mm}@media print{thead{display:table-header-group}tr,svg{break-inside:avoid}h2{break-after:avoid}}'
    page='<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>'+title+'</title><style>'+css+'</style></head><body><h1>'+title+'</h1><p>保存实验记录 SHA-256：'+esc(digest)+'</p>'+''.join(parts)+'</body></html>'
    md=['# '+title,'','实验记录 SHA-256：'+digest,'','全部为人工故障实验。','',*['- '+str(k)+'：'+str(v) for k,v in settings],'','| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(headers))+'|',*['| '+' | '.join(str(v) for v in row)+' |' for row in rows],'','## 局限',e['limitations'],'','完整图表和轨迹见 report.html；全部依据见 evidence.json。']
    return page,'\n'.join(md)+'\n'
