from pathlib import Path
from datetime import datetime,timedelta
import importlib.util,base64,json,time,threading,urllib.request,urllib.error
import pytest
spec=importlib.util.spec_from_file_location('workflow_dashboard',Path(__file__).resolve().parents[1]/'tools/dashboard.py');d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)

def sample(days=9):
    lines=['timestamp,open,high,low,close,volume'];day=datetime(2026,9,1,9,30);n=0
    while n<days:
        if day.weekday()<5:
            for k in range(390):
                price=100+n*.01+(k%5)*.001
                lines.append(f'{day+timedelta(minutes=k):%Y-%m-%d %H:%M:%S},{price},{price+1},{price-1},{price},1000')
            n+=1
        day+=timedelta(days=1)
    return ('\n'.join(lines)+'\n').encode()

def upload(output,days=9):
    return d.store_upload({'symbol':'SYNTH','timezone':'America/New_York','csv_base64':base64.b64encode(sample(days)).decode()},output)

def service(output):return d.workflows.WorkflowService(output,validator=d.audit_csv,normalizer=d._csv_records)

def wait(s,job):
    deadline=time.monotonic()+40
    while time.monotonic()<deadline:
        state=s.status(job['id'])
        if state['status'] in ('succeeded','failed'):return state
        time.sleep(.02)
    pytest.fail('background job did not finish')

def test_rolling_is_past_only_bounded_and_reports_no_plan_cases(tmp_path):
    u=upload(tmp_path);s=service(tmp_path)
    job=s.start({'upload_id':u['upload_id'],'lookback':3,'evaluation_days':2,'fraction':.09,'participation_rate':.05})
    state=wait(s,job);assert state['status']=='succeeded',state
    result=json.loads((tmp_path/'rolling'/job['id']/'result.json').read_text(encoding='utf-8'))
    assert len(result['evaluation_calendar_dates'])==2 and len(result['records'])==18
    assert result['planned_record_count']==result['completed_record_count']==0
    assert 'FirstRate' not in result['source']
    for row in result['records']:
        assert len(row['train_dates'])==3 and all(day<row['date'] for day in row['train_dates'])
    assert len(result['regime_by_date'])==2
    assert sum(row['cases'] for row in state['summary']['strategies'])==18
    report=s.report({'kind':'rolling','id':job['id']})
    html=(tmp_path/'reports'/report['id']/'report.html').read_text(encoding='utf-8')
    assert '<svg' in html and '未生成计划' in html and '18' in html
    assert not (tmp_path/'rolling'/job['id']/'private-diagnostics').exists()


@pytest.mark.parametrize('filename',['source.csv','loader-input.csv'])
def test_input_tampering_and_insufficient_history_fail_without_fake_results(tmp_path,filename):
    u=upload(tmp_path,6);s=service(tmp_path)
    state=wait(s,s.start({'upload_id':u['upload_id'],'lookback':10,'evaluation_days':2,'fraction':.01,'participation_rate':.1}))
    assert state['status']=='failed'
    folder=tmp_path/'uploads'/u['upload_id'];(folder/filename).write_bytes(b'changed')
    state=wait(s,s.start({'upload_id':u['upload_id'],'lookback':5,'evaluation_days':1,'fraction':.01,'participation_rate':.1}))
    assert state['status']=='failed' and not (tmp_path/'rolling'/state['id']/'result.json').exists()

@pytest.mark.parametrize('key,value',[('lookback',True),('evaluation_days',61),('upload_id','../x'),('fraction',.5),('participation_rate',0)])
def test_rolling_options_reject_unsafe_inputs(tmp_path,key,value):
    payload={'upload_id':'a'*32,'lookback':5,'evaluation_days':1,'fraction':.01,'participation_rate':.1};payload[key]=value
    with pytest.raises(ValueError):service(tmp_path).start(payload)


def test_core_report_uses_saved_experiment_escapes_text_and_has_evidence(tmp_path):
    c=d.run_experiment({'trials':5,'intervals':3});eid='b'*32;c['experiment_id']=eid
    (tmp_path/(eid+'.json')).write_text(json.dumps(c),encoding='utf-8')
    s=service(tmp_path);r=s.report({'kind':'core','id':eid})
    html=(tmp_path/'reports'/r['id']/'report.html').read_text(encoding='utf-8')
    md=(tmp_path/'reports'/r['id']/'report.md').read_text(encoding='utf-8')
    assert '<svg' in html and '成本' in html and '95%' in md
    evidence=json.loads((tmp_path/'reports'/r['id']/'evidence.json').read_text(encoding='utf-8'))
    assert evidence['experiment']['config']==c['config'] and evidence['source_sha256']
    assert '&lt;script&gt;' in d.workflows.safe_text('<script>')
    with pytest.raises(ValueError):s.report({'kind':'core','id':'../../x'})


def test_http_saved_upload_catalog_jobs_and_report_files(tmp_path):
    u=upload(tmp_path,6);server=d.make_server(0,tmp_path);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)
    def post(path,body):
        with urllib.request.urlopen(urllib.request.Request(base+path,json.dumps(body).encode(),{'Content-Type':'application/json','Origin':base}),timeout=20) as f:return json.load(f)
    try:
        with urllib.request.urlopen(base+'/api/uploads') as f:assert json.load(f)[0]['id']==u['upload_id']
        core=post('/api/run',{'trials':5,'intervals':3});assert len(core['experiment_id'])==32
        report=post('/api/report',{'kind':'core','id':core['experiment_id']})
        with urllib.request.urlopen(base+report['html_url']) as f:assert b'<html' in f.read()
        with urllib.request.urlopen(base+report['markdown_url']) as f:assert f.read()
        with pytest.raises(urllib.error.HTTPError):urllib.request.urlopen(base+'/api/reports/'+report['id']+'/source.csv')
    finally:server.shutdown();server.server_close();thread.join()


def test_completed_rolling_has_real_plans_and_escaped_portable_reports(tmp_path):
    u=upload(tmp_path,8);path=tmp_path/'uploads'/u['upload_id']/'audit.json'
    audit=json.loads(path.read_text(encoding='utf-8'));audit['origin_note']='<script>alert(1)</script> synthetic fixture'
    path.write_text(json.dumps(audit),encoding='utf-8')
    s=service(tmp_path);state=wait(s,s.start({'upload_id':u['upload_id'],'lookback':3,'evaluation_days':4,'fraction':.01,'participation_rate':.1}))
    assert state['status']=='succeeded',state
    assert state['summary']['cases']==state['summary']['planned']==state['summary']['completed']==36
    result=json.loads((tmp_path/'rolling'/state['id']/'result.json').read_text(encoding='utf-8'))
    assert all(r['replay']['residual']==0 for r in result['records'])
    assert all(c['common_complete_count']==4 for c in result['comparisons'])
    report=s.report({'kind':'rolling','id':state['id']})
    page=(tmp_path/'reports'/report['id']/'report.html').read_text(encoding='utf-8')
    assert '<script>alert(1)</script>' not in page and '&lt;script&gt;' in page
    assert service(tmp_path).status(state['id'])['status']=='succeeded'
