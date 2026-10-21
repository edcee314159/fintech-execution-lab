from pathlib import Path
from datetime import datetime,timedelta
import importlib.util,base64,json,time,threading,urllib.request,urllib.error
import pytest
spec=importlib.util.spec_from_file_location('adaptive_dashboard',Path(__file__).resolve().parents[1]/'tools/dashboard.py')
d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)


def sample():
    rows=['timestamp,open,high,low,close,volume'];day=datetime(2026,9,1,9,30)
    for n in range(4):
        rows.extend(f'{day+timedelta(days=n,minutes=k):%Y-%m-%d %H:%M:%S},100,101,99,100,{1000 if n<3 or k<195 else 0}' for k in range(390))
    return ('\n'.join(rows)+'\n').encode()


def wait(service,job):
    for _ in range(1000):
        state=service.status(job['id'])
        if state['status'] in ('succeeded','failed'):return state
        time.sleep(.02)
    pytest.fail('adaptive job timed out')


def test_adaptive_upload_to_saved_report_and_evidence(tmp_path):
    u=d.store_upload({'symbol':'SYNTH','timezone':'America/New_York','csv_base64':base64.b64encode(sample()).decode()},tmp_path)
    service=d.workflows.WorkflowService(tmp_path,validator=d.audit_csv,normalizer=d._csv_records)
    config={'upload_id':u['upload_id'],'lookback':3,'evaluation_days':1,'fraction':.05,'participation_rate':.1}
    try:job=service.start(config,adaptive=True)
    except TypeError:pytest.fail('Adaptive background mode is missing')
    state=wait(service,job);assert state['status']=='succeeded',state
    assert state['kind']=='adaptive' and state['summary']['cases']==3
    result=service.adaptive_result(job['id']);assert len(result['daily'][0]['trace'])==78
    assert result['input_provenance']['source_sha256']==u['source_sha256']
    with pytest.raises(ValueError):service.report({'kind':'rolling','id':job['id']})
    report=service.report({'kind':'adaptive','id':job['id']})
    folder=tmp_path/'reports'/report['id'];page=(folder/'report.html').read_text(encoding='utf-8')
    assert '<svg' in page and 'capacity_cover' not in page
    assert '<script src=' not in page and 'http://' not in page
    assert json.loads((folder/'evidence.json').read_text(encoding='utf-8'))['kind']=='adaptive'
    assert len((folder/'report.md').read_text(encoding='utf-8'))>200
    source=tmp_path/'rolling'/job['id']/'result.json'
    record=json.loads(source.read_text(encoding='utf-8'));record['input_provenance']['origin_note']='<script>alert(1)</script>'
    source.write_text(json.dumps(record),encoding='utf-8')
    report=service.report({'kind':'adaptive','id':job['id']})
    page=(tmp_path/'reports'/report['id']/'report.html').read_text(encoding='utf-8')
    assert '<script>alert(1)</script>' not in page and '&lt;script&gt;' in page


def test_http_adaptive_endpoint_and_result_validation(tmp_path):
    u=d.store_upload({'symbol':'SYNTH','timezone':'America/New_York','csv_base64':base64.b64encode(sample()).decode()},tmp_path)
    server=d.make_server(0,tmp_path);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base='http://127.0.0.1:'+str(server.server_port)
    def get(path):
        with urllib.request.urlopen(base+path,timeout=10) as response:return json.load(response)
    def post(path,payload):
        with urllib.request.urlopen(urllib.request.Request(base+path,json.dumps(payload).encode(),{'Content-Type':'application/json','Origin':base}),timeout=20) as response:return json.load(response)
    try:
        try:job=post('/api/adaptive',{'upload_id':u['upload_id'],'lookback':3,'evaluation_days':1,'fraction':.05,'participation_rate':.1})
        except urllib.error.HTTPError as e:pytest.fail('adaptive HTTP endpoint failed: '+str(e.code))
        for _ in range(1000):
            state=get('/api/rolling/'+job['id'])
            if state['status'] in ('succeeded','failed'):break
            time.sleep(.02)
        assert state['status']=='succeeded',state
        assert get('/api/adaptive/'+job['id'])['adaptive_schema']=='1.0'
        with pytest.raises(urllib.error.HTTPError):get('/api/adaptive/../../secret')
        report=post('/api/report',{'kind':'adaptive','id':job['id']})
        with urllib.request.urlopen(base+report['html_url']) as response:assert b'<svg' in response.read()
    finally:server.shutdown();server.server_close();thread.join()


def test_adaptive_rechecks_input_integrity(tmp_path):
    u=d.store_upload({'symbol':'SYNTH','timezone':'America/New_York','csv_base64':base64.b64encode(sample()).decode()},tmp_path)
    (tmp_path/'uploads'/u['upload_id']/'source.csv').write_bytes(b'changed')
    service=d.workflows.WorkflowService(tmp_path,validator=d.audit_csv,normalizer=d._csv_records)
    try:job=service.start({'upload_id':u['upload_id'],'lookback':3,'evaluation_days':1,'fraction':.05,'participation_rate':.1},adaptive=True)
    except TypeError:pytest.fail('Adaptive background mode is missing')
    state=wait(service,job);assert state['status']=='failed'
    assert not (tmp_path/'rolling'/job['id']/'result.json').exists()
