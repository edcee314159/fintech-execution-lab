from pathlib import Path
import shutil,subprocess
import pytest


def test_failed_result_fetch_does_not_leave_previous_jobs_metrics():
    node=shutil.which('node')
    if node is None:pytest.skip('Node is optional for browser script unit checks')
    source=Path(__file__).resolve().parents[1]/'tools/adaptive.js'
    script=r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const nodes=new Map();
function node(id){if(!nodes.has(id))nodes.set(id,{textContent:'',children:[],disabled:false,value:'',replaceChildren(){this.children=[];this.textContent='';},addEventListener(){}});return nodes.get(id);}
const context={document:{querySelector:node},fetch:async()=>{throw Error('network failure');},rollingJob:{id:'B'}};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
for(const id of ['#adaptive-strategies','#adaptive-coverage','#adaptive-date'])node(id).children=['old A data'];
node('#adaptive-calibration').textContent='old A calibration';
(async()=>{
    vm.runInContext('resetAdaptiveResult()',context);
    await vm.runInContext('loadAdaptiveResult("B")',context);
    for(const id of ['#adaptive-strategies','#adaptive-coverage','#adaptive-date'])assert.equal(node(id).children.length,0,id+' retained old data');
    assert(!node('#adaptive-calibration').textContent.includes('old A'));
    assert(node('#adaptive-decision').textContent.includes('network failure'));
    assert(node('#adaptive-date').disabled&&node('#adaptive-time').disabled);
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    result=subprocess.run([node,'-e',script,str(source)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_failed_extension_fetch_clears_previous_signal_or_queue_data():
    node=shutil.which('node')
    if node is None:pytest.skip('Node is optional for browser script unit checks')
    source=Path(__file__).resolve().parents[1]/'tools/extensions.js'
    if not source.exists():pytest.fail('Extension browser module is missing')
    script=r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert'),nodes=new Map();
function node(id){if(!nodes.has(id))nodes.set(id,{textContent:'',children:[],disabled:false,value:'',replaceChildren(){this.children=[];this.textContent='';},addEventListener(){}});return nodes.get(id);}
const ctx={document:{querySelector:node},fetch:async()=>{throw Error('network failure');},rollingJob:{id:'B',kind:'signal'}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
for(const id of ['#extension-rows','#extension-headers','#extension-date','#extension-policy','#extension-events','#extension-chart'])node(id).children=['old data'];
node('#extension-note').textContent='old data';
(async()=>{await vm.runInContext('loadExtensionResult("B","signal")',ctx);
for(const id of ['#extension-rows','#extension-headers','#extension-date','#extension-policy','#extension-events','#extension-chart'])assert.equal(node(id).children.length,0,id);
assert(!node('#extension-note').textContent.includes('old data'));assert(node('#extension-detail').textContent.includes('network failure'));
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    result=subprocess.run([node,'-e',script,str(source)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
