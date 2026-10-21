"use strict";
const adaptiveLabels={fixed_twap:'固定均匀拆单',fixed_volume:'固定按历史成交量拆单',adaptive:'动态风险预警拆单'};
let adaptiveData=null,adaptiveToken=0;
function resetAdaptiveResult(){
  adaptiveToken++;adaptiveData=null;
  for(const id of ['#adaptive-chart','#adaptive-strategies','#adaptive-coverage','#adaptive-date'])document.querySelector(id).replaceChildren();
  document.querySelector('#adaptive-calibration').textContent='等待本次动态结果，尚无可用统计。';
  document.querySelector('#adaptive-decision').textContent='正在读取本次动态轨迹…';
  document.querySelector('#adaptive-date').disabled=true;document.querySelector('#adaptive-time').disabled=true;
  document.querySelector('#adaptive-time').value=0;
}
async function loadAdaptiveResult(id){
  resetAdaptiveResult();const token=adaptiveToken;
  try{
    const response=await fetch('/api/adaptive/'+encodeURIComponent(id));const data=await response.json();
    if(!response.ok)throw new Error(data.error||'动态轨迹读取失败');
    if(token!==adaptiveToken||rollingJob?.id!==id)return;
    adaptiveData=data;const s=data.dashboard_summary,c=data.calibration;
    const body=document.querySelector('#adaptive-strategies');body.replaceChildren();
    for(const r of s.strategies)workflowRow(body,[adaptiveLabels[r.planner],r.cases,r.completed,r.cases-r.completed,fmt(r.mean_residual),fmt(r.mean_assumed_impact),r.common_complete_count,fmt(r.common_complete_mean_marked_bps)]);
    document.querySelector('#adaptive-calibration').textContent=`区间检验：${c.independent_date_count} 个不同日期，${c.band_hits}/${c.band_count} 个时点落在历史场景 p10–p90 区间内（${fmt(c.band_coverage*100)}%）。容量覆盖场景占比 Brier 诊断 ${fmt(c.capacity_cover_brier)}。同日时点相互依赖，短样本不能证明已完成概率校准。`;
    const coverage=document.querySelector('#adaptive-coverage');coverage.replaceChildren();
    for(const r of c.checkpoints)workflowRow(coverage,[r.interval*5,r.dates,r.covered_dates,fmt(r.covered_dates/r.dates*100)+'%']);
    const dates=document.querySelector('#adaptive-date');dates.replaceChildren();
    for(const d of data.daily){const o=document.createElement('option');o.value=d.date;o.textContent=d.date;dates.append(o);}
    dates.value=data.daily.at(-1).date;dates.disabled=false;document.querySelector('#adaptive-time').disabled=false;document.querySelector('#adaptive-time').value=0;showAdaptiveDecision();
  }catch(e){if(token===adaptiveToken)document.querySelector('#adaptive-decision').textContent=e.message+'；可点击“重新查询任务”重试。';}
}
function showAdaptiveDecision(){
  if(!adaptiveData)return;
  const date=document.querySelector('#adaptive-date').value,day=adaptiveData.daily.find(d=>d.date===date);
  if(!day)return;const t=Number(document.querySelector('#adaptive-time').value),r=day.trace[t],trace=day.trace.slice(0,t+1);
  const keys=['capacity_p10','capacity_p50','capacity_p90','remaining_before'],colors=['#b07d32','#498379','#176b60','#ba4d48'];
  const ymax=Math.max(1,...trace.flatMap(x=>keys.map(k=>x[k]))),x=i=>65+i/77*675,y=v=>210-v/ymax*185;
  let svg='<svg viewBox="0 0 760 250" role="img" aria-label="截至当前决策时点的剩余容量场景与剩余订单">';
  for(let i=0;i<5;i++){const v=ymax*i/4;svg+=`<line x1="65" x2="740" y1="${y(v)}" y2="${y(v)}" stroke="#dce5df"/><text x="58" y="${y(v)+4}" text-anchor="end" font-size="11">${fmt(v)}</text>`;}
  keys.forEach((k,i)=>{const points=trace.map(r=>`${x(r.interval)},${y(r[k])}`).join(' ');svg+=`<polyline points="${points}" fill="none" stroke="${colors[i]}" stroke-width="2"/><circle cx="${x(t)}" cy="${y(r[k])}" r="3" fill="${colors[i]}"/>`;});
  svg+='<text x="65" y="240" font-size="11">开盘</text><text x="675" y="240" font-size="11">385 分钟</text></svg>';
  document.querySelector('#adaptive-chart').innerHTML=svg;
  const clock=String(9+Math.floor((30+r.minute)/60)).padStart(2,'0')+':'+String((30+r.minute)%60).padStart(2,'0');
  const action=r.remaining_before===0?'订单已完成':r.accelerated?'后续容量偏紧，提高本期尝试数量':r.risk==='normal'?'按当前计划推进':'容量覆盖不足，保留预警';
  document.querySelector('#adaptive-decision').textContent=`${date} ${clock} 开始前：已观察 ${t} 个五分钟时段，尚待卖出 ${fmt(r.remaining_before)} 股。剩余容量 p10–p90：${fmt(r.capacity_p10)}–${fmt(r.capacity_p90)} 股；容量覆盖场景 ${fmt(r.capacity_cover_share*100)}%，固定后续计划完成场景 ${fmt(r.continuation_completion_share*100)}%。${action}，本期尝试 ${fmt(r.request)} 股。该时段结束后回放成交 ${fmt(r.filled)} 股，剩余 ${fmt(r.remaining_after)} 股。`;
}
document.querySelector('#adaptive-date').addEventListener('change',()=>{document.querySelector('#adaptive-time').value=0;showAdaptiveDecision();});
document.querySelector('#adaptive-time').addEventListener('input',showAdaptiveDecision);
