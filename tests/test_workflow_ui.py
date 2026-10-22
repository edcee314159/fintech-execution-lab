from pathlib import Path
import shutil,subprocess
import pytest

PRELUDE=r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert'),nodes=new Map(),timers=new Map();let sequence=0;
function node(id){if(!nodes.has(id))nodes.set(id,{value:'',textContent:'',hidden:false,disabled:false,elements:[],children:[],replaceChildren(){this.children=[];},append(x){this.children.push(x);},addEventListener(){},closest(){return this;}});return nodes.get(id);}
const ctx={document:{querySelector:node,createElement:()=>node('created'+(++sequence))},current:{experiment_id:'core-A'},resetAdaptiveResult(){},resetExtensionResult(){},resetBusinessResult(){},resetSafetyResult(){},
fetch:async()=>({ok:true,json:async()=>[]}),setTimeout(f){const id=++sequence;timers.set(id,f);return id;},clearTimeout(id){timers.delete(id);}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
"""


def run_script(code):
    node=shutil.which('node')
    if node is None:pytest.skip('Optional Node browser unit runtime not available')
    source=Path(__file__).resolve().parents[1]/'tools/workflows.js'
    r=subprocess.run([node,'-e',PRELUDE+code,str(source)],capture_output=True,text=True)
    assert r.returncode==0,r.stderr


def test_new_study_invalidates_report_without_permanently_disabling_core_button():
    run_script(r"""
let resolveReport;ctx.fetch=async path=>path==='/api/report'?await new Promise(r=>resolveReport=r):({ok:false,json:async()=>({error:'expected creation failure'})});
(async()=>{const old=vm.runInContext('generateReport("core")',ctx);
await vm.runInContext('startStudy("/api/orderbook",{})',ctx);
resolveReport({ok:true,json:async()=>({html_url:'/old-report'})});await old;
assert.equal(node('#report-core').disabled,false,'core report stayed disabled');
assert.equal(node('#report-actions').hidden,true,'stale report became visible');
})().catch(e=>{console.error(e);process.exitCode=1;});
""")


def test_new_jobs_poll_is_not_lost_while_previous_jobs_retry_is_in_flight():
    run_script(r"""
let resolveOld,bFetches=0;ctx.fetch=async path=>{
if(path==='/api/rolling/A')return await new Promise(r=>resolveOld=r);
if(path==='/api/orderbook')return {ok:true,json:async()=>({id:'B',kind:'orderbook',status:'queued',phase:'queued'})};
if(path==='/api/rolling/B'){bFetches++;return {ok:true,json:async()=>({id:'B',kind:'orderbook',status:'running',phase:'running'})};}
throw Error('unexpected path '+path);};
(async()=>{vm.runInContext('rollingJob={id:"A",status:"succeeded"}',ctx);const old=vm.runInContext('pollRolling()',ctx);
await vm.runInContext('startStudy("/api/orderbook",{})',ctx);
for(const [id,f] of [...timers]){timers.delete(id);await f();}
resolveOld({ok:true,json:async()=>({id:'A',status:'succeeded'})});await old;
assert(timers.size>0,'new queued job lost its polling timer');
for(const [id,f] of [...timers]){timers.delete(id);await f();}
assert(bFetches>0,'new job was never queried');
})().catch(e=>{console.error(e);process.exitCode=1;});
""")
