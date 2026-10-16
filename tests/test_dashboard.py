from pathlib import Path
import importlib.util,json,threading,urllib.request,urllib.error
import numpy as np
import pytest
from execution_lab.config import ExecutionConfig
from execution_lab.schedule import make_ac, make_twap
from execution_lab.simulation import run_paired
from execution_lab.metrics import summarize

spec=importlib.util.spec_from_file_location('dashboard',Path(__file__).resolve().parents[1]/'tools/dashboard.py')
dashboard=importlib.util.module_from_spec(spec)
spec.loader.exec_module(dashboard)

def test_dashboard_reuses_financial_kernel_and_seed():
    data={'quantity':12345,'intervals':12,'trials':80,'seed':17}
    result=dashboard.run_experiment(data)
    c=ExecutionConfig.from_dict(data)
    expected=summarize(run_paired(c,{'twap':make_twap(c),'ac_simplified':make_ac(c)}))
    assert result['summary']==expected
    assert dashboard.run_experiment(data)==result
    for s in result['schedules'].values():
        assert sum(s['quantities'])==c.quantity
        assert len(s['quantities'])==c.intervals
        assert s['inventory'][0]==c.quantity and s['inventory'][-1]==0
    json.dumps(result,allow_nan=False)

@pytest.mark.parametrize('data',[{'trials':2001},{'intervals':121},{'trials':2000,'intervals':120},{'quantity':True},{'price':float('nan')},{'unknown':1}])
def test_rejects_unsafe_or_oversized_inputs(data):
    with pytest.raises(ValueError):dashboard.run_experiment(data)

def test_invalid_price_paths_remain_explicit():
    result=dashboard.run_experiment({'price':.001,'volatility':100,'trials':10,'intervals':2})
    assert result['summary']['invalid_pairs']>0
    assert result['summary']['status']!='valid'


def test_http_saves_only_to_external_output_and_rejects_cross_origin(tmp_path):
    server=dashboard.make_server(0,tmp_path)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base='http://127.0.0.1:'+str(server.server_port)
    try:
        with urllib.request.urlopen(base) as r:
            html=r.read().decode();assert '拆单实验室' in html
        def post(data,origin=base):
            return urllib.request.urlopen(urllib.request.Request(base+'/api/run',json.dumps(data).encode(),{'Content-Type':'application/json','Origin':origin}),timeout=20)
        with post({'trials':10,'intervals':3}) as r: result=json.load(r)
        assert len(list(tmp_path.glob('*.json')))==1
        assert json.loads(next(tmp_path.glob('*.json')).read_text(encoding='utf-8'))==result
        with pytest.raises(urllib.error.HTTPError) as e:post({},'https://example.com')
        assert e.value.code==403
        with pytest.raises(urllib.error.HTTPError) as e:post({'quantity':-1})
        assert e.value.code==400
        with pytest.raises(urllib.error.HTTPError) as e:urllib.request.urlopen(base+'/../README.md')
        assert e.value.code==404
    finally: server.shutdown();server.server_close();thread.join()


def test_output_cannot_be_inside_source():
    with pytest.raises(ValueError):dashboard.make_server(0,Path(__file__).resolve().parents[1]/'outputs')
