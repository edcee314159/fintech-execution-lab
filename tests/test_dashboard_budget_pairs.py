"""HTTP and portable report acceptance for the two synthetic execution extensions."""
from pathlib import Path
import importlib.util,json,time,threading,urllib.request,urllib.error
import pytest
spec=importlib.util.spec_from_file_location('bp_dashboard',Path(__file__).resolve().parents[1]/'tools/dashboard.py')
d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
from test_budget_pairs import budget_config,pair_config

@pytest.mark.parametrize('kind,config',[('budget',budget_config),('pairs',pair_config)])
def test_budget_pairs_http_jobs_report_and_invalid_inputs(tmp_path,kind,config):
    server=d.make_server(0,tmp_path);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base='http://127.0.0.1:'+str(server.server_port)
    def post(path,payload):
        req=urllib.request.Request(base+path,json.dumps(payload).encode(),{'Content-Type':'application/json','Origin':base})
        with urllib.request.urlopen(req,timeout=30) as f:return json.load(f)
    def get(path):
        with urllib.request.urlopen(base+path,timeout=30) as f:return f.read()
    try:
        invalid=config();invalid['seed']=True
        with pytest.raises(urllib.error.HTTPError) as e:post('/api/'+kind,invalid)
        assert e.value.code==400
        job=post('/api/'+kind,config())
        for _ in range(1500):
            state=json.loads(get('/api/rolling/'+job['id']))
            if state['status'] in ('succeeded','failed'):break
            time.sleep(.01)
        assert state['status']=='succeeded' and state['kind']==kind,state
        result=json.loads(get('/api/extensions/'+job['id']))
        assert result['data_kind'].startswith('synthetic_')
        wrong='pairs' if kind=='budget' else 'budget'
        with pytest.raises(urllib.error.HTTPError):post('/api/report',{'kind':wrong,'id':job['id']})
        report=post('/api/report',{'kind':kind,'id':job['id']})
        page=get(report['html_url']).decode()
        assert '<svg' in page and '人工' in page and '<script' not in page
        assert '规划' in page if kind=='budget' else '现金' in page
        evidence=json.loads(get(report['json_url']))
        assert evidence['kind']==kind and evidence['experiment']==result
        assert get(report['markdown_url']).decode().startswith('# ')
        assert (tmp_path/'rolling'/job['id']/'result.json').exists()
        assert b'loadBusinessResult' in get('/budget_pairs.js')
    finally:server.shutdown();server.server_close();thread.join()
