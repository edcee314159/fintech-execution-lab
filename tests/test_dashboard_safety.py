"""HTTP safety experiments and complete, type-bound portable evidence."""
from pathlib import Path
import importlib.util,json,time,threading,urllib.request,urllib.error
import pytest
from test_execution_safety import recovery_config,guard_config
s=importlib.util.spec_from_file_location('safety_dashboard',Path(__file__).resolve().parents[1]/'tools/dashboard.py')
d=importlib.util.module_from_spec(s);s.loader.exec_module(d)

@pytest.mark.parametrize('kind,config',[('recovery',recovery_config),('marketguard',guard_config)])
def test_safety_http_jobs_and_portable_evidence(tmp_path,kind,config):
    server=d.make_server(0,tmp_path);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base='http://127.0.0.1:'+str(server.server_port)
    def post(path,payload):
        req=urllib.request.Request(base+path,json.dumps(payload).encode(),{'Content-Type':'application/json','Origin':base})
        with urllib.request.urlopen(req,timeout=30) as f:return json.load(f)
    def get(path):
        with urllib.request.urlopen(base+path,timeout=30) as f:return f.read()
    try:
        bad=config();bad['quantity']=True
        with pytest.raises(urllib.error.HTTPError) as e:post('/api/'+kind,bad)
        assert e.value.code==400
        job=post('/api/'+kind,config())
        for _ in range(1000):
            state=json.loads(get('/api/rolling/'+job['id']))
            if state['status'] in ('succeeded','failed'):break
            time.sleep(.01)
        assert state['status']=='succeeded' and state['kind']==kind,state
        result=json.loads(get('/api/extensions/'+job['id']))
        assert result['data_kind'].startswith('synthetic_')
        wrong='marketguard' if kind=='recovery' else 'recovery'
        with pytest.raises(urllib.error.HTTPError):post('/api/report',{'kind':wrong,'id':job['id']})
        report=post('/api/report',{'kind':kind,'id':job['id']})
        page=get(report['html_url']).decode()
        assert '<svg' in page and '<script' not in page and '人工' in page
        assert '预留' in page if kind=='recovery' else '只报价' in page
        assert json.loads(get(report['json_url']))['experiment']==result
        assert get(report['markdown_url']).decode().startswith('# ')
        if kind=='recovery':assert (tmp_path/'rolling'/job['id']/'orders.jsonl').exists()
        assert b'loadSafetyResult' in get('/execution_safety.js')
    finally:server.shutdown();server.server_close();thread.join()
