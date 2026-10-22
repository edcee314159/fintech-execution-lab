"use strict";
const safetyLabels={timeout_retry:'无保护的超时重发示例',reconciled:'持久化意图与对账恢复',unchecked:'无状态检查示例',guarded:'行情状态保护'};
const safetyStates={normal:'正常',recovering:'恢复观察/限速',closed:'常规时段外或闭市',status_unknown:'交易状态不明',halted:'已确认停牌',quote_only:'只报价，尚未恢复交易',invalid_data:'无效报价',feed_gap:'序列缺口待快照',stale_data:'报价过期',volume_unknown:'成交量数据不明'};
let safetyData=null,safetyKind=null,safetyToken=0;
function resetSafetyResult(){
  safetyToken++;safetyData=null;safetyKind=null;
  for(const id of ['#safety-headers','#safety-rows','#safety-policy','#safety-chart','#safety-events'])document.querySelector(id).replaceChildren();
  document.querySelector('#safety-note').textContent='等待本次人工故障实验。';document.querySelector('#safety-detail').textContent='';
  for(const id of ['#safety-policy','#safety-time'])document.querySelector(id).disabled=true;
}
async function loadSafetyResult(id,kind){
  resetSafetyResult();const token=safetyToken;
  try{
    const response=await fetch('/api/extensions/'+encodeURIComponent(id)),data=await response.json();
    if(!response.ok)throw new Error(data.error||'读取人工故障结果失败');
    if(token!==safetyToken||rollingJob?.id!==id||rollingJob?.kind!==kind)return;
    safetyData=data;safetyKind=kind;const recovery=kind==='recovery';
    const headers=recovery?['方案','实际成交','本地已知成交','剩余','超卖','同意图重复下单','恰好完成母单']:['方案','成交','剩余','完成','保护规则外尝试','只报价时尝试','超过子单上限尝试','最大子单请求'];
    for(const name of headers){const th=document.createElement('th');th.textContent=name;document.querySelector('#safety-headers').append(th);}
    for(const r of data.dashboard_summary.strategies)workflowRow(document.querySelector('#safety-rows'),recovery?[safetyLabels[r.planner],r.actual_filled,r.known_filled,r.residual,r.oversold,r.duplicate_order_submissions,r.complete?'是':'否']:[safetyLabels[r.planner],r.filled,r.residual,r.complete?'是':'否',r.unsafe_attempts,r.quote_only_attempts,r.oversized_attempts,r.peak_child_request]);
    const policy=document.querySelector('#safety-policy');
    for(const key of Object.keys(data.policies)){const o=document.createElement('option');o.value=key;o.textContent=safetyLabels[key];policy.append(o);}
    policy.value=recovery?'reconciled':'guarded';
    document.querySelector('#safety-note').textContent=recovery?'预留包括未知接收和撤单在途的可能成交数量。完整订单、成交、持仓快照不一致时暂停，不把“列表未找到”当作可以重发。实际成交与实际持仓仅用于事后诊断。无保护重发是故意缺少检查的示例，两条轨迹步骤不同，不做速度排名。':'零成交量不会被当成停牌；只报价仍暂停。序列缺口或无效报价需明确快照，恢复先观察两条合格更新，再逐步限速。这里仅控制本实验的新IOC子单，不会撤销其他模块的已有挂单。日历仅支持2026年Nasdaq常规时段。';
    for(const id of ['#safety-policy','#safety-time'])document.querySelector(id).disabled=false;
    document.querySelector('#safety-time').value=0;showSafetyDecision();
  }catch(e){if(token===safetyToken)document.querySelector('#safety-detail').textContent=e.message+'；可重新查询任务。';}
}
function showSafetyDecision(){
  if(!safetyData)return;
  const recovery=safetyKind==='recovery',key=document.querySelector('#safety-policy').value,row=safetyData.policies[key],slider=document.querySelector('#safety-time');
  slider.max=row.trace.length-1;if(Number(slider.value)>=row.trace.length)slider.value=row.trace.length-1;
  const t=Number(slider.value),r=row.trace[t],series={};
  document.querySelector('#safety-events').replaceChildren();
  if(recovery){
    const trace=row.trace.slice(0,t+1);
    series['本地已知成交']=trace.map(x=>x.known_filled);series['仍可能成交的预留']=trace.map(x=>x.reserved);series['实际成交（事后）']=trace.map(x=>x.actual_filled);
    document.querySelector('#safety-detail').textContent='第 '+r.step+' 步：'+r.action+'。本地已知成交 '+r.known_filled+' 股，仍预留 '+r.reserved+' 股，可安全新增 '+r.available+' 股，'+(r.ready?'状态已核实，仍受可新增数量约束':'暂停新单')+'。事后实际持仓 '+r.actual_position+' 股。'+(r.fault?'核实提示：'+r.fault:'');
    for(const x of trace.slice(-8))workflowRow(document.querySelector('#safety-events'),[x.step,x.action,x.known_filled,x.reserved,x.available]);
  }else{
    const trace=row.trace.slice(0,t+1);
    series['本方案剩余股数']=[safetyData.design.quantity,...trace.map(x=>x.remaining)];
    document.querySelector('#safety-detail').textContent=r.timestamp+'（纽约本地），'+safetyStates[r.state]+'，报价年龄 '+(r.quote_age==null?'未知':r.quote_age+'秒')+'。恢复比例 '+fmt(r.ramp*100)+'%，尝试 '+r.request+' 股，模拟成交 '+r.filled+' 股，剩余 '+r.remaining+' 股。'+(r.reason||'')+(key==='unchecked'?' 无检查示例显示保护器诊断，但没有遵守保护决定。':'');
    for(const x of trace.slice(-8))workflowRow(document.querySelector('#safety-events'),[x.tick,safetyStates[x.state],x.request,x.filled,x.remaining]);
  }
  const maximum=Math.max(1,...Object.values(series).flat()),colors=['#b07d32','#176b60','#ba4d48'];let svg='<svg viewBox="0 0 800 280" role="img" aria-label="截至滑块时点的数量与预留">';
  Object.entries(series).forEach(([label,values],i)=>{
    svg+='<polyline points="'+values.map((v,k)=>(55+k/row.trace.length*720)+','+(210-v/maximum*180)).join(' ')+'" stroke="'+colors[i]+'" fill="none" stroke-width="2"/><text x="'+(55+i*240)+'" y="250" font-size="11" fill="'+colors[i]+'">'+label+'</text>';
  });
  document.querySelector('#safety-chart').innerHTML=svg+'</svg>';
}
document.querySelector('#safety-policy').addEventListener('change',showSafetyDecision);
document.querySelector('#safety-time').addEventListener('input',showSafetyDecision);
for(const kind of ['recovery','marketguard']){
  const form=document.querySelector('#'+kind+'-form');
  form.addEventListener('submit',e=>{
    e.preventDefault();const payload=Object.fromEntries([...new FormData(form)].map(([k,v])=>[k,['scenario','session_date'].includes(k)?v:Number(v)]));
    startStudy('/api/'+kind,payload);
  });
  form.addEventListener('input',()=>{
    if(rollingJob?.status==='succeeded'&&rollingJob.kind===kind)document.querySelector('#rolling-status').textContent='参数已修改；图表和报告仍是上一次人工故障实验，请重新运行。';
  });
}
