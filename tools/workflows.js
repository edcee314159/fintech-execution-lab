'use strict';
const wq=s=>document.querySelector(s),workflowLabels={uniform:'均匀量',historical_shape:'历史分布',previous_day:'前一日',twap_capped:'均匀卖出',volume_capped:'按量分配',arrival_constrained:'成本风险权衡'};
let rollingJob=null,rollingPoll=null,rollingQueryBusy=false,generatedReport=null,reportToken=0;
function workflowRow(parent,values){const row=document.createElement('tr');for(const v of values){const cell=document.createElement('td');cell.textContent=String(v);row.append(cell);}parent.append(row);}
async function workflowPost(path,payload){const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const data=await response.json();if(!response.ok)throw new Error(data.error||'操作失败');return data;}
async function refreshRollingUploads(preferred){try{const response=await fetch('/api/uploads');if(!response.ok)throw new Error('无法读取已上传数据');const entries=await response.json(),select=wq('#rolling-upload'),before=select.value;select.replaceChildren();for(const r of entries){const option=document.createElement('option');option.value=r.id;option.textContent=`${r.symbol} · ${r.complete_sessions} 个完整日 · ${r.format_valid?'格式通过':'需要核实'} · ${r.origin_note}`;option.disabled=!r.format_valid;select.append(option);}const valid=entries.filter(r=>r.format_valid);if(!valid.length){const o=document.createElement('option');o.value='';o.textContent='请先上传并检查 CSV';select.append(o);select.value='';}else select.value=valid.some(r=>r.id===preferred)?preferred:(valid.some(r=>r.id===before)?before:valid[0].id);if(!rollingJob)wq('#rolling-status').textContent=valid.length?'数据列表已更新，请设置窗口。':'暂无格式通过的数据。先在上方上传；数据只保存在本机。';}catch(e){wq('#rolling-status').textContent=e.message;}}
function rollingBusy(value){for(const id of ['#rolling-form','#orderbook-form'])for(const c of wq(id).elements)c.disabled=value;}
function showRolling(state){
  rollingJob=state;wq('#rolling-status').textContent=state.phase+(state.error?'：'+state.error:'');
  if(state.status==='succeeded'){
    const s=state.summary,isAdaptive=state.kind==='adaptive',isExtension=['signal','orderbook'].includes(state.kind);
    wq('#extension-result').hidden=!isExtension;
    wq('#rolling-result').hidden=false;wq('#report-rolling').disabled=false;
    wq('#adaptive-result').hidden=!isAdaptive;
    wq('#rolling-strategies').closest('.metrics').hidden=isAdaptive||isExtension;
    wq('#rolling-regimes').closest('details').hidden=isAdaptive||isExtension;
    if(isExtension){
      wq('#rolling-overview').textContent=state.kind==='signal'?`信号验证：${s.evaluation_start} 至 ${s.evaluation_end}，${s.evaluation_days} 个评估日；三种执行方案共 ${s.cases} 条情形。`:`人工订单簿：种子 ${s.seed}，${s.ticks} 个1秒步，订单 ${s.quantity} 股。全部事件由程序生成。`;
      loadExtensionResult(state.id,state.kind);
    }else if(isAdaptive){
      wq('#rolling-overview').textContent=`动态验证：${s.evaluation_start} 至 ${s.evaluation_end}，${s.evaluation_days} 个评估日，三种方案共 ${s.cases} 条情形；${s.completed} 条完成。相同日期的方案不属于独立市场样本。`;
      loadAdaptiveResult(state.id);
    }else{
      wq('#rolling-overview').textContent=`${s.evaluation_start} 至 ${s.evaluation_end}，实际 ${s.evaluation_days} 个评估日；${s.cases} 条情形，${s.planned} 条生成计划，${s.completed} 条回放完成。分母保留所有情形；日期数不是策略情形数。`;
      const body=wq('#rolling-strategies');body.replaceChildren();
      for(const r of s.strategies)workflowRow(body,[workflowLabels[r.predictor],workflowLabels[r.planner],r.cases,r.planned,r.completed,r.cases-r.planned,fmt(r.mean_residual_planned)]);
      const grouped=wq('#rolling-regimes');grouped.replaceChildren();
      for(const r of s.regimes)workflowRow(grouped,[r.dimension,r.regime,workflowLabels[r.predictor],workflowLabels[r.planner],r.dates,r.cases,r.completed]);
    }
  }
  if(state.status==='succeeded'||state.status==='failed'){rollingBusy(false);rollingPoll=null;}
  else rollingPoll=setTimeout(pollRolling,1000);
}
async function pollRolling(){
  if(rollingQueryBusy){
    if(['queued','running'].includes(rollingJob?.status)){if(rollingPoll)clearTimeout(rollingPoll);rollingPoll=setTimeout(pollRolling,1000);}
    return;
  }if(rollingPoll)clearTimeout(rollingPoll);rollingPoll=null;
  if(!rollingJob){wq('#rolling-status').textContent='暂无本页启动的任务。';return;}
  const key=rollingJob.id;rollingQueryBusy=true;
  try{const response=await fetch('/api/rolling/'+encodeURIComponent(key)),state=await response.json();
    if(rollingJob?.id!==key)return;if(!response.ok)throw new Error(state.error||'读取任务状态失败');showRolling(state);
  }catch(e){if(rollingJob?.id===key){wq('#rolling-status').textContent=e.message+'；点击“重新查询任务”可重试。';rollingBusy(false);rollingPoll=null;}}
  finally{rollingQueryBusy=false;}
}
async function startStudy(path,payload){
  rollingBusy(true);rollingJob=null;reportToken++;wq('#report-core').disabled=false;
  wq('#rolling-result').hidden=true;wq('#report-rolling').disabled=true;wq('#rolling-status').textContent='正在创建后台任务…';
  wq('#report-actions').hidden=true;generatedReport=null;resetAdaptiveResult();resetExtensionResult();if(rollingPoll)clearTimeout(rollingPoll);
  try{showRolling(await workflowPost(path,payload));}
  catch(e){wq('#rolling-status').textContent=e.message;rollingBusy(false);}
}
wq('#rolling-form').addEventListener('submit',event=>{
  event.preventDefault();if(!wq('#rolling-upload').value)return;
  const payload={upload_id:wq('#rolling-upload').value,lookback:Number(wq('#rolling-lookback').value),evaluation_days:Number(wq('#rolling-days').value),fraction:Number(wq('#rolling-fraction').value),participation_rate:Number(wq('#rolling-rate').value)};
  const mode=wq('#rolling-mode').value;if(mode==='signal')payload.signal_scenario=wq('#signal-scenario').value;
  startStudy(mode==='signal'?'/api/signal':mode==='adaptive'?'/api/adaptive':'/api/rolling',payload);
});
wq('#orderbook-form').addEventListener('submit',event=>{
  event.preventDefault();startStudy('/api/orderbook',{scenario:wq('#book-scenario').value,quantity:Number(wq('#book-quantity').value),seed:Number(wq('#book-seed').value),participation_rate:Number(wq('#book-rate').value),latency_ticks:Number(wq('#book-latency').value)});
});
wq('#rolling-refresh').onclick=()=>refreshRollingUploads();wq('#rolling-retry').onclick=pollRolling;
async function generateReport(kind){
  if(kind==='rolling')kind=rollingJob?.kind||'rolling';
  const key=kind==='core'?(typeof current!=='undefined'?current?.experiment_id:null):(rollingJob?.status==='succeeded'?rollingJob.id:null);
  if(!key){wq('#report-status').textContent=kind==='core'?'请先运行基础实验。':'请先完成验证。';return;}
  const token=++reportToken;for(const id of ['#report-core','#report-rolling'])wq(id).disabled=true;
  wq('#report-status').textContent='正在生成报告…';wq('#report-actions').hidden=true;generatedReport=null;
  try{const report=await workflowPost('/api/report',{kind,id:key});if(token!==reportToken)return;
    generatedReport=report;wq('#report-actions').hidden=false;wq('#report-view').href=report.html_url;
    wq('#report-status').textContent=`报告已生成，任务类型 ${({core:'基础模拟',rolling:'固定计划验证',adaptive:'动态容量验证',signal:'信号执行',orderbook:'人工订单簿'})[kind]}，编号 ${key}。实验记录指纹：${report.source_sha256}`;
  }catch(e){if(token===reportToken)wq('#report-status').textContent=e.message;}
  finally{if(token===reportToken){wq('#report-core').disabled=false;wq('#report-rolling').disabled=rollingJob?.status!=='succeeded';}}
}
wq('#report-core').onclick=()=>generateReport('core');wq('#report-rolling').onclick=()=>generateReport('rolling');
for(const [selector,field,type,name] of [['#report-html','html_url','text/html;charset=utf-8','research-report.html'],['#report-md','markdown_url','text/markdown;charset=utf-8','research-report.md'],['#report-json','json_url','application/json','research-evidence.json']]){wq(selector).onclick=async()=>{if(!generatedReport)return;try{const response=await fetch(generatedReport[field]);if(!response.ok)throw new Error('读取报告失败');download(await response.text(),type,name);}catch(e){wq('#report-status').textContent=e.message;}};}
refreshRollingUploads();
