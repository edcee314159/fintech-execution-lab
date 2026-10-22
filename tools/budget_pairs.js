"use strict";
const businessLabels={uniform:'均匀分批',frontloaded:'前快后慢',independent:'两笔独立执行',coordinated:'双资产协同'};
let businessData=null,businessKind=null,businessToken=0;
function resetBusinessResult(){
  businessToken++;businessData=null;businessKind=null;
  for(const id of ['#business-headers','#business-rows','#business-choice','#business-chart'])document.querySelector(id).replaceChildren();
  document.querySelector('#business-note').textContent='等待本次任务结果。';
  document.querySelector('#business-detail').textContent='';
  for(const id of ['#business-choice','#business-time'])document.querySelector(id).disabled=true;
}
async function loadBusinessResult(id,kind){
  resetBusinessResult();const token=businessToken;
  try{
    const response=await fetch('/api/extensions/'+encodeURIComponent(id)),data=await response.json();
    if(!response.ok)throw new Error(data.error||'读取结果失败');
    if(token!==businessToken||rollingJob?.id!==id||rollingJob?.kind!==kind)return;
    businessData=data;businessKind=kind;
    const budget=kind==='budget';
    const headers=budget?['分钟','节奏','规划时长/达标前沿','规划达标/256','验证完成/256','验证达标/256','验证超预算/256','验证未完成/256','完成路径P95（基点）','共同完成均值（基点）']:['方法','两边完成/32','平均A剩余','平均B剩余','平均风险积分','平均峰值风险','平均最大进度差','现金受限场景','共同完成均值（基点）'];
    for(const text of headers){const th=document.createElement('th');th.textContent=text;document.querySelector('#business-headers').append(th);}
    const body=document.querySelector('#business-rows'),choice=document.querySelector('#business-choice');
    if(budget){
      for(const r of data.candidates){
        const v=r.validation;
        workflowRow(body,[r.horizon,businessLabels[r.pace],r.on_planning_frontier?'是':'否',r.planning.successes,v.completed,v.successes,v.budget_breaches,v.unfinished,fmt(v.p95_complete_bps),fmt(v.common_complete_mean_bps)]);
        const o=document.createElement('option');o.value=r.id;o.textContent=r.horizon+'分钟 · '+businessLabels[r.pace]+(r.id===data.selected_id?' · 规划推荐':'');choice.append(o);
      }
      const chosen=data.candidates.find(r=>r.id===data.selected_id);
      choice.value=chosen?.id||data.candidates.at(-2).id;
      document.querySelector('#business-note').textContent=(chosen?'规划推荐 '+chosen.horizon+' 分钟 · '+businessLabels[chosen.pace]+'。独立验证达标 '+chosen.validation.successes+'/256（要求 '+fmt(data.design.required_success*100)+'%），'+(chosen.validation.joint_success_rate>=data.design.required_success?'验证比例达到要求':'验证比例未达到要求，仍保留原推荐供检查')+'。':'本次8个候选没有达到规划要求；这不能证明其他方法均不可行。')+' 达标指按时全部完成且成本不超预算。完成路径P95是条件样本，不能直接跨候选排名；共同完成均值使用同一组 '+data.dashboard_summary.common_complete_count+' 条路径。预算不是硬止损。';
    }else{
      for(const r of data.dashboard_summary.strategies)workflowRow(body,[businessLabels[r.planner],r.completed,fmt(r.mean_sell_remaining),fmt(r.mean_buy_remaining),fmt(r.mean_integrated_target_variance),fmt(r.mean_peak_target_risk_std),fmt(r.mean_max_progress_gap*100)+'%',r.cash_limited_scenarios,fmt(r.common_complete_mean_bps)]);
      for(const p of ['independent','coordinated']){const o=document.createElement('option');o.value=p;o.textContent=businessLabels[p];choice.append(o);}choice.value='coordinated';
      document.querySelector('#business-note').textContent=data.funding_note+' 以上是32条配对人工路径，成本只比较 '+data.dashboard_summary.common_complete_count+' 条共同完成路径。图表是输入种子的单条回放。卖出资金当分钟可用是假设；不借款、不做空。协同不保证更低成本或更高完成率。风险积分单位：货币²·分钟；峰值风险单位：货币。';
    }
    for(const id of ['#business-choice','#business-time'])document.querySelector(id).disabled=false;
    document.querySelector('#business-time').value=0;showBusinessDecision();
  }catch(e){if(token===businessToken)document.querySelector('#business-detail').textContent=e.message+'；可重新查询任务。';}
}
function showBusinessDecision(){
  if(!businessData)return;
  const budget=businessKind==='budget',choice=document.querySelector('#business-choice').value,slider=document.querySelector('#business-time');
  const row=budget?businessData.candidates.find(r=>r.id===choice):businessData.policies[choice];
  const trace=budget?row.validation_trace:row.trace;slider.max=trace.length-1;
  if(Number(slider.value)>=trace.length)slider.value=trace.length-1;
  const t=Number(slider.value),r=trace[t],series={};
  if(budget){
    series['剩余股数']=[businessData.design.quantity,...trace.slice(0,t+1).map(x=>x.remaining)];
    document.querySelector('#business-detail').textContent='独立验证第一条人工路径，第 '+r.minute+' 分钟结束：尝试 '+r.request+' 股，容量 '+r.capacity+' 股，成交 '+r.filled+' 股，剩余 '+r.remaining+' 股。本分钟半价差成本 '+fmt(r.spread_cost)+'、费用 '+fmt(r.fee_cost)+'、冲击成本 '+fmt(r.impact_cost)+'、时机成本 '+fmt(r.timing_cost)+'（均为货币）。负时机成本表示相对起始中价有利。';
  }else{
    for(const [p,v] of Object.entries(businessData.policies)){
      series[businessLabels[p]+' · A剩余%']=[100,...v.trace.slice(0,t+1).map(x=>x.sell_remaining/businessData.design.sell_quantity*100)];
      series[businessLabels[p]+' · B剩余%']=[100,...v.trace.slice(0,t+1).map(x=>x.buy_remaining/businessData.design.buy_quantity*100)];
    }
    document.querySelector('#business-detail').textContent=businessLabels[choice]+'，第 '+r.minute+' 分钟结束：卖A '+r.sell_filled+' 股、买B '+r.buy_filled+' 股；剩余A '+r.sell_remaining+' 股、B '+r.buy_remaining+' 股；现金 '+fmt(r.cash_cents/100)+'，目标偏离风险 '+fmt(r.risk_std)+'，两边进度差 '+fmt(r.progress_gap*100)+'%。'+(r.cash_limited?'本分钟买入受到现金约束。':'')+'完整现金账本和全部场景的期末标记诊断见报告。';
  }
  const max=Math.max(1,...Object.values(series).flat()),colors=['#b07d32','#176b60','#ba4d48','#426f9a'];
  let svg='<svg viewBox="0 0 800 280" role="img" aria-label="截至滑块时点的剩余数量或比例">';
  Object.entries(series).forEach(([name,values],k)=>{
    svg+='<polyline points="'+values.map((v,i)=>(55+i/trace.length*725)+','+(210-v/max*185)).join(' ')+'" fill="none" stroke="'+colors[k]+'" stroke-width="2"/><text x="'+(55+(k%2)*370)+'" y="'+(240+Math.floor(k/2)*20)+'" font-size="11" fill="'+colors[k]+'">'+name+'</text>';
  });
  document.querySelector('#business-chart').innerHTML=svg+'</svg>';
}
document.querySelector('#business-choice').addEventListener('change',showBusinessDecision);
document.querySelector('#business-time').addEventListener('input',showBusinessDecision);
for(const kind of ['budget','pairs']){
  const form=document.querySelector('#'+kind+'-form');
  form.addEventListener('submit',e=>{
    e.preventDefault();const payload=Object.fromEntries([...new FormData(form)].map(([k,v])=>[k,k==='scenario'?v:Number(v)]));
    startStudy('/api/'+kind,payload);
  });
  form.addEventListener('input',()=>{
    if(rollingJob?.status==='succeeded'&&rollingJob.kind===kind)document.querySelector('#rolling-status').textContent='参数已修改；图表和报告仍对应上次实验，请重新运行。';
  });
}
