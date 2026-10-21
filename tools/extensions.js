"use strict";
const extensionLabels={capacity:'不用价格信号',always:'始终相信信号',trusted:'按历史验证降权',passive:'始终挂单',aggressive:'始终主动成交',dynamic:'动态切换'};
const orderStatusLabels={submitted:'提交命令',activated:'命令生效',partial_fill:'部分成交',parent_complete:'母单完成',filled:'子单完成',cancelled:'撤单生效',cancel_requested:'请求撤单',ioc_remainder_expired:'未成主动需求失效',no_op_parent_complete:'母单已完成，无需执行',deadline_expired:'截止仍未成交',deadline_expired_before_arrival:'截止前未能到达'};
let extensionData=null,extensionKind=null,extensionToken=0;
function resetExtensionResult(){
  extensionToken++;extensionData=null;extensionKind=null;
  for(const id of ['#extension-headers','#extension-rows','#extension-date','#extension-policy','#extension-events','#extension-chart'])document.querySelector(id).replaceChildren();
  document.querySelector('#extension-note').textContent='等待本次任务结果。';document.querySelector('#extension-detail').textContent='正在读取本次任务…';
  for(const id of ['#extension-date','#extension-policy','#extension-time'])document.querySelector(id).disabled=true;
}
async function loadExtensionResult(id,kind){
  resetExtensionResult();const token=extensionToken;
  try{
    const response=await fetch('/api/extensions/'+encodeURIComponent(id)),data=await response.json();if(!response.ok)throw new Error(data.error||'读取验证结果失败');
    if(token!==extensionToken||rollingJob?.id!==id||rollingJob?.kind!==kind)return;
    extensionData=data;extensionKind=kind;const signal=kind==='signal',s=data.dashboard_summary;
    const headers=signal?['方法','日期','完成','平均剩余','共同完成假设冲击成本','共同完成日期','共同完成缺口（基点）']:['方法','完成','剩余','被动成交','主动成交','撤单数','假设费用/返佣','共同完成缺口（基点）'];
    for(const text of headers){const th=document.createElement('th');th.textContent=text;document.querySelector('#extension-headers').append(th);}
    for(const r of s.strategies)workflowRow(document.querySelector('#extension-rows'),signal?[extensionLabels[r.planner],r.cases,r.completed,fmt(r.mean_residual),fmt(r.mean_assumed_impact),r.common_complete_count,fmt(r.common_complete_mean_marked_bps)]:[extensionLabels[r.planner],r.completed,r.mean_residual,r.maker_shares,r.taker_shares,r.cancel_count,fmt(r.fees),fmt(r.common_complete_mean_marked_bps)]);
    document.querySelector('#extension-note').textContent=signal?`过去逐日验证的平均信号权重 ${fmt(s.mean_reliability*100)}%。这是历史误差改善程度，不是成功概率。三种方案共享订单、时限和参与率；只有共同完成日期进入成本对照。`:'全部为人工盘口。成交顺序、队前撤单、延迟和费用均为假设；不是从上传行情重建的真实队列。若任一方案未完成，共同完成成本不显示。';
    const date=document.querySelector('#extension-date'),policy=document.querySelector('#extension-policy');
    const choices=signal?data.daily.map(d=>d.date):['人工场景：'+data.design.scenario+' · 种子 '+data.design.seed];
    for(const name of choices){const o=document.createElement('option');o.value=name;o.textContent=name;date.append(o);}date.value=choices.at(-1);
    for(const key of signal?['capacity','always','trusted']:['passive','aggressive','dynamic']){const o=document.createElement('option');o.value=key;o.textContent=extensionLabels[key];policy.append(o);}
    policy.value=signal?'trusted':'dynamic';document.querySelector('#extension-time').max=signal?77:data.events.length-1;document.querySelector('#extension-time').value=0;
    for(const id of ['#extension-date','#extension-policy','#extension-time'])document.querySelector(id).disabled=false;showExtensionDecision();
  }catch(e){if(token===extensionToken)document.querySelector('#extension-detail').textContent=e.message+'；可重新查询任务。';}
}
function showExtensionDecision(){
  if(!extensionData)return;const signal=extensionKind==='signal',t=Number(document.querySelector('#extension-time').value),policy=document.querySelector('#extension-policy').value;
  const series={},colors=['#b07d32','#176b60','#ba4d48'];let detail;
  document.querySelector('#extension-events').replaceChildren();
  if(signal){
    const day=extensionData.daily.find(d=>d.date===document.querySelector('#extension-date').value);if(!day)return;
    for(const [p,trace] of Object.entries(day.traces))series[p]=[day.quantity,...trace.slice(0,t+1).map(x=>x.remaining_after)];
    const r=day.traces[policy][t];detail=`${day.date}，开盘后 ${r.minute} 分钟开始前：预测下一时段收益 ${fmt(r.predicted_return*10000)} 基点，历史验证权重 ${fmt(r.weight*100)}%。容量基准尝试 ${fmt(r.baseline_request)} 股，保护下限 ${fmt(r.required_now)} 股，调整后尝试 ${fmt(r.request)} 股。该时段结束后回放成交 ${fmt(r.filled)} 股，剩余 ${fmt(r.remaining_after)} 股。`;
  }else{
    for(const [p,row] of Object.entries(extensionData.policies))series[p]=[row.quantity,...row.trace.slice(0,t+1).map(x=>x.remaining)];
    const row=extensionData.policies[policy],r=row.trace[t];
    detail=`人工事件第 ${t} 秒结束后：本步模拟成交 ${r.filled} 股，参与率配额 ${r.cap} 股，剩余 ${r.remaining} 股；队前数量 ${r.queue_ahead??'无挂单'}，在途命令 ${r.pending} 条。此时决定下一条命令：${r.command==='limit'?'挂单':r.command==='market'?'主动成交':'等待'}，数量 ${r.command_quantity} 股，延迟 ${extensionData.design.latency_ticks} 秒后才可能生效。`;
    for(const o of row.orders.filter(x=>x.tick<=t).slice(-12))workflowRow(document.querySelector('#extension-events'),[o.tick,o.order_id,orderStatusLabels[o.status]||o.status,o.quantity??o.remaining??o.unfilled??'—',o.action==='limit'?'挂单':o.action==='market'?'主动成交':'—']);
  }
  const maximum=Math.max(1,...Object.values(series).flat()),horizon=signal?78:extensionData.events.length,x=i=>65+i/horizon*675,y=v=>210-v/maximum*185;
  let svg='<svg viewBox="0 0 760 270" role="img" aria-label="截至滑块时点的三种执行方案剩余数量">';
  for(let i=0;i<5;i++){const v=maximum*i/4;svg+=`<line x1="65" x2="740" y1="${y(v)}" y2="${y(v)}" stroke="#dce5df"/><text x="58" y="${y(v)+4}" text-anchor="end" font-size="11">${fmt(v)}</text>`;}
  Object.entries(series).forEach(([p,values],i)=>{svg+=`<polyline points="${values.map((v,j)=>`${x(j)},${y(v)}`).join(' ')}" fill="none" stroke="${colors[i]}" stroke-width="2"/><text x="${65+i*220}" y="250" font-size="12" fill="${colors[i]}">${extensionLabels[p]}</text>`;});
  document.querySelector('#extension-chart').innerHTML=svg+'</svg>';document.querySelector('#extension-detail').textContent=detail;
}
for(const selector of ['#extension-date','#extension-policy'])document.querySelector(selector).addEventListener('change',showExtensionDecision);
document.querySelector('#extension-time').addEventListener('input',showExtensionDecision);
