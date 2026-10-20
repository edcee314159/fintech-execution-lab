'use strict';
let replayCases=[],activeReplay=null,replayTimer=null,replayRequest=0;
const replaySelects={symbol:'#replay-symbol',date:'#replay-date',predictor:'#replay-predictor',order_fraction_adv:'#replay-fraction',planner:'#replay-planner'};
const replayLabels={uniform:'均匀成交量',historical_shape:'历史日内分布',previous_day:'前一交易日',twap_capped:'带上限的均匀卖出',volume_capped:'按预测成交量分配',arrival_constrained:'成本与风险权衡'};
const rq=s=>document.querySelector(s);
function pauseReplay(){if(replayTimer!==null)clearInterval(replayTimer);replayTimer=null;rq('#replay-play').textContent='播放';}
function paintReplay(){if(!activeReplay||!activeReplay.available)return;const r=activeReplay,k=Number(rq('#replay-slider').value),mins=k*r.interval_minutes;
 rq('#replay-clock').textContent=k===0?'开盘前 · 0 / 78 时段':`${mins} 分钟 · ${k} / 78 时段`;
 for(const [id,key] of [['planned','cumulative_planned'],['filled','cumulative_filled'],['remaining','remaining'],['backlog','backlog']])rq('#replay-'+id).textContent=fmt(r[key][k]);
 const message=rq('#replay-message'),backlog=r.backlog[k];message.className='notice'+(backlog?' warn':'');
 if(k===0)message.textContent=`尚未开始回放。本笔订单 ${fmt(r.case.quantity)} 股，每时段最多使用历史记录成交量的 ${fmt(r.case.participation_rate*100)}%。`;
 else if(k===78)message.textContent=r.remaining[k]?`交易日结束：完成 ${fmt(r.cumulative_filled[k])} 股，仍剩 ${fmt(r.remaining[k])} 股，未完成订单。剩余数量不会自动算作成交。`:'交易日结束：这条历史容量回放中的订单已全部完成，不能据此保证实盘成交。';
 else message.textContent=backlog?`本时段模拟完成 ${fmt(r.fills[k-1])} 股；时段结束仍有 ${fmt(backlog)} 股积压，表明已释放订单超过本时段可用的历史回放容量，积压顺延。`:`本时段模拟完成 ${fmt(r.fills[k-1])} 股；当前无积压。`;
 const times=Array.from({length:k+1},(_,i)=>i*r.interval_minutes);
 chart('#replay-chart',[r.cumulative_planned.slice(0,k+1),r.cumulative_filled.slice(0,k+1)],times,'累计计划量与历史容量回放完成量',{xmax:390,ymax:r.case.quantity});
 if(k===78)pauseReplay();
}
async function chooseReplay(){pauseReplay();const token=++replayRequest;activeReplay=null;rq('#replay-content').hidden=true;rq('#replay-status').textContent='正在读取所选情形…';
 const c=replayCases.find(c=>Object.entries(replaySelects).every(([key,selector])=>String(c[key])===rq(selector).value));
 try{if(!c)throw new Error('没有匹配的历史情形。');const response=await fetch('/api/replay?id='+encodeURIComponent(c.id));const r=await response.json();if(token!==replayRequest)return;if(!response.ok)throw new Error(r.error||'回放读取失败。');activeReplay=r;
 rq('#replay-status').textContent=r.available?`${r.case.symbol} · ${r.case.date} · 订单 ${fmt(r.case.quantity)} 股 · 每格为 5 分钟；这是固定历史情形。`:'该情形因预测成交容量不足，未生成计划，无法回放。这不等于“已卖出 0 股的有效计划”。';
 rq('#replay-content').hidden=!r.available;if(r.available){rq('#replay-slider').value='0';paintReplay();}
 }catch(e){if(token===replayRequest)rq('#replay-status').textContent=e.message;}
}
rq('#replay-slider').addEventListener('input',()=>{pauseReplay();paintReplay();});
rq('#replay-start').onclick=()=>{pauseReplay();rq('#replay-slider').value='0';paintReplay();};
rq('#replay-end').onclick=()=>{pauseReplay();rq('#replay-slider').value='78';paintReplay();};
rq('#replay-play').onclick=()=>{if(replayTimer!==null){pauseReplay();return;}if(!activeReplay||!activeReplay.available)return;if(Number(rq('#replay-slider').value)===78)rq('#replay-slider').value='0';rq('#replay-play').textContent='暂停';replayTimer=setInterval(()=>{rq('#replay-slider').value=String(Math.min(78,Number(rq('#replay-slider').value)+1));paintReplay();},200);};
async function initReplay(){try{const response=await fetch('/api/replay-cases');if(!response.ok)throw new Error('无法加载历史情形，请确认已重启新版面板服务。');replayCases=await response.json();if(!replayCases.length)throw new Error('暂无回放情形。');const initial=replayCases.find(c=>c.planning_feasible&&c.residual>0)||replayCases[0];
 for(const [key,selector] of Object.entries(replaySelects)){const select=rq(selector),values=[...new Set(replayCases.map(c=>String(c[key])))];for(const value of values){const option=document.createElement('option');option.value=value;option.textContent=key==='order_fraction_adv'?fmt(Number(value)*100)+'%':(replayLabels[value]||value);select.append(option);}select.value=String(initial[key]);select.disabled=false;select.addEventListener('change',chooseReplay);}await chooseReplay();
 }catch(e){rq('#replay-status').textContent=e.message;}}
initReplay();
