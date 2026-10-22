"""Stale/failed synthetic extension results must not leak across tasks."""
from pathlib import Path
import shutil,subprocess
import pytest
@pytest.mark.parametrize('mode',['failure','stale'])
def test_safety_result_is_cleared_and_old_response_cannot_repaint(mode):
    node=shutil.which('node')
    if node is None:pytest.skip('Node is optional for browser script checks')
    source=Path(__file__).resolve().parents[1]/'tools/execution_safety.js'
    script=r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert'),nodes=new Map();
function node(id){if(!nodes.has(id))nodes.set(id,{textContent:'',children:[],disabled:false,value:'',replaceChildren(){this.children=[];this.textContent='';},addEventListener(){}});return nodes.get(id);}
let resolve;
const ctx={document:{querySelector:node},rollingJob:{id:'A',kind:'recovery'},fetch:()=>new Promise(r=>resolve=r)};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
for(const id of ['#safety-headers','#safety-rows','#safety-policy','#safety-chart','#safety-events'])node(id).children=['old result'];
(async()=>{
 if(process.argv[2]==='failure'){
   ctx.fetch=async()=>{throw Error('network failure')};
   await vm.runInContext('loadSafetyResult("A","recovery")',ctx);
   assert(node('#safety-detail').textContent.includes('network failure'));
 }else{
   const pending=vm.runInContext('loadSafetyResult("A","recovery")',ctx);
   ctx.rollingJob={id:'B',kind:'marketguard'};vm.runInContext('resetSafetyResult()',ctx);
   resolve({ok:true,json:async()=>({dashboard_summary:{},candidates:[]})});await pending;
   assert.equal(vm.runInContext('safetyData',ctx),null);
 }
 for(const id of ['#safety-headers','#safety-rows','#safety-policy','#safety-chart','#safety-events'])assert.equal(node(id).children.length,0,id);
 assert(node('#safety-policy').disabled&&node('#safety-time').disabled);
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    result=subprocess.run([node,'-e',script,str(source),mode],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
