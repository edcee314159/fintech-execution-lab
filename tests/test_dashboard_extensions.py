from pathlib import Path
from datetime import datetime,timedelta
import importlib.util,base64,json,time,threading,urllib.request,urllib.error
import pytest
spec=importlib.util.spec_from_file_location('extensions_dashboard',Path(__file__).resolve().parents[1]/'tools/dashboard.py');d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)


def uploaded(output):
    first=datetime(2026,9,1,9,30);rows=[]
    for day in range(4):
        for k in range(390):rows.append(f'{first+timedelta(days=day,minutes=k):%Y-%m-%d %H:%M:%S},100,101,99,100,1000')
    return d.store_upload({'symbol':'SYNTH','timezone':'America/New_York','csv_base64':base64.b64encode(('\n'.join(rows)+'\n').encode()).decode()},output)


@pytest.mark.parametrize('kind',['signal','orderbook'])
def test_extensions_http_end_to_end_and_report_kind_isolation(tmp_path,kind):
    u=uploaded(tmp_path) if kind=='signal' else None;server=d.make_server(0,tmp_path);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)
    def post(path,p):
        with urllib.request.urlopen(urllib.request.Request(base+path,json.dumps(p).encode(),{'Content-Type':'application/json','Origin':base}),timeout=30) as f:return json.load(f)
    def get(path):
        with urllib.request.urlopen(base+path,timeout=30) as f:return json.load(f)
    try:
        payload={'upload_id':u['upload_id'],'lookback':3,'evaluation_days':1,'fraction':.05,'participation_rate':.1,'signal_scenario':'zero'} if kind=='signal' else {'scenario':'adverse','quantity':500,'seed':7,'participation_rate':.1,'latency_ticks':3}
        try:job=post('/api/'+kind,payload)
        except urllib.error.HTTPError as e:pytest.fail('Missing extension endpoint: '+str(e.code))
        for _ in range(1500):
            state=get('/api/rolling/'+job['id'])
            if state['status'] in ('succeeded','failed'):break
            time.sleep(.02)
        assert state['status']=='succeeded' and state['kind']==kind,state
        result=get('/api/extensions/'+job['id']);assert kind+'_schema' in result
        with pytest.raises(urllib.error.HTTPError):post('/api/report',{'kind':'adaptive','id':job['id']})
        report=post('/api/report',{'kind':kind,'id':job['id']})
        with urllib.request.urlopen(base+report['html_url']) as f:page=f.read().decode()
        assert '<svg' in page and '<script src=' not in page
        evidence=get(report['json_url']);assert evidence['kind']==kind
        if kind=='orderbook':assert evidence['experiment']['data_kind']=='synthetic_order_book'
        with pytest.raises(urllib.error.HTTPError):get('/api/extensions/../../secret')
    finally:server.shutdown();server.server_close();thread.join()


def test_signal_rejects_tampered_upload_and_bad_stress_option(tmp_path):
    u=uploaded(tmp_path);s=d.workflows.WorkflowService(tmp_path,validator=d.audit_csv,normalizer=d._csv_records)
    payload={'upload_id':u['upload_id'],'lookback':3,'evaluation_days':1,'fraction':.05,'participation_rate':.1,'signal_scenario':'unknown'}
    if not hasattr(s,'start_signal'):pytest.fail('signal service is missing')
    with pytest.raises(ValueError):s.start_signal(payload)
    payload['signal_scenario']='learned';(tmp_path/'uploads'/u['upload_id']/'source.csv').write_bytes(b'changed');job=s.start_signal(payload)
    for _ in range(500):
        state=s.status(job['id'])
        if state['status'] in ('succeeded','failed'):break
        time.sleep(.01)
    assert state['status']=='failed' and not (tmp_path/'rolling'/job['id']/'result.json').exists()
