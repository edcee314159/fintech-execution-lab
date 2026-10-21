from pathlib import Path
from datetime import datetime,timedelta
import csv,io,json,base64,hashlib,importlib.util,threading,urllib.request,urllib.error
import pytest
spec=importlib.util.spec_from_file_location('upload_dashboard',Path(__file__).resolve().parents[1]/'tools/dashboard.py')
d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)

def rows(days=1):
    result=[];day=datetime(2026,9,21,9,30)
    while days:
        if day.weekday()<5:
            result.extend([(day+timedelta(minutes=i)).strftime('%Y-%m-%d %H:%M:%S')+',100,101,99,100,1000' for i in range(390)])
            days-=1
        day+=timedelta(days=1)
    return result

def data(lines,header=True):
    return ((('timestamp,open,high,low,close,volume\n') if header else '')+'\n'.join(lines)+'\n').encode()

def test_complete_csv_and_headerless_have_same_sessions():
    a=d.audit_csv(data(rows(6)),'SPY');b=d.audit_csv(data(rows(6),False),'SPY')
    assert a['complete_sessions']==b['complete_sessions']==6
    assert a['usable_dates']==b['usable_dates']
    assert a['format_valid'] and a['ready_for_pilot']
    assert a['counts']['missing_minutes']==0
    one=d.audit_csv(data(rows()),'ABC')
    assert one['format_valid'] and not one['ready_for_pilot']


def test_gap_duplicates_order_and_bad_values_are_reported():
    r=rows();r.pop(20);r.append(r[10]);r.append(r[11].rsplit(',',1)[0]+',2000');r[30]=r[30].rsplit(',',1)[0]+',-1';r[40]=r[40].replace(',101,99,',',98,99,');r[50]='bad timestamp,100,101,99,100,1000'
    report=d.audit_csv(data(r),'SPY');c=report['counts']
    assert not report['format_valid'] and not report['ready_for_pilot']
    assert c['missing_minutes']>=1 and c['exact_duplicates']==1 and c['conflicting_duplicates']==1
    assert c['out_of_order']>0 and c['invalid_volume']==1 and c['invalid_ohlc']==1 and c['invalid_timestamp']==1
    assert report['examples'] and all('line' in e for e in report['examples'])

@pytest.mark.parametrize('volume',['NaN','Infinity','1.5','1000000000001','1e-400','1000.00000000000001'])
def test_bad_volumes_not_silently_corrected(volume):
    r=rows();r[0]=r[0].rsplit(',',1)[0]+','+volume
    report=d.audit_csv(data(r),'SPY')
    assert report['counts']['invalid_volume']==1 and not report['format_valid']


def test_zero_and_spike_volume_warn_without_deleting_rows():
    r=rows();r[100]=r[100].rsplit(',',1)[0]+',50000'
    report=d.audit_csv(data(r),'SPY')
    assert report['counts']['volume_spikes']==1 and report['complete_sessions']==1
    assert next(e for e in report['examples'] if e['code']=='volume_spikes')['line']==102
    z=d.audit_csv(data([r.rsplit(',',1)[0]+',0' for r in rows(6)]),'SPY')
    assert z['counts']['zero_volume_sessions']==6 and not z['ready_for_pilot']

@pytest.mark.parametrize('raw',[b'',b'wrong,header\n1,2\n',b'\xff\xfe',b'x'*(5*1024*1024+1)],ids=['empty','bad_header','bad_encoding','too_large'])
def test_bad_file_contracts_are_rejected(raw):
    with pytest.raises(ValueError):d.audit_csv(raw,'SPY')


def test_upload_stays_external_and_is_compatible_with_existing_loader(tmp_path):
    server=d.make_server(0,tmp_path);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    url='http://127.0.0.1:'+str(server.server_port)
    raw=data(rows(6));payload={'symbol':'spy','timezone':'America/New_York','csv_base64':base64.b64encode(raw).decode()}
    def post(p,origin=url):
        return urllib.request.urlopen(urllib.request.Request(url+'/api/upload',json.dumps(p).encode(),{'Content-Type':'application/json','Origin':origin}),timeout=20)
    try:
        with post(payload) as f:r=json.load(f)
        folder=tmp_path/'uploads'/r['upload_id']
        assert (folder/'source.csv').read_bytes()==raw
        assert r['source_sha256']==hashlib.sha256(raw).hexdigest()
        assert json.loads((folder/'audit.json').read_text(encoding='utf-8'))==r
        from execution_volume_validation.data import load_sessions
        sessions,audit=load_sessions(folder/'loader-input.csv','SPY')
        assert len(sessions)==6 and audit['accepted_sessions']==r['usable_dates']
        assert r['symbol']=='SPY' and r['ready_for_pilot']
        with pytest.raises(urllib.error.HTTPError) as e:post({**payload,'symbol':'../../other'})
        assert e.value.code==400
        with pytest.raises(urllib.error.HTTPError) as e:post({**payload,'timezone':'UTC'})
        assert e.value.code==400
        with pytest.raises(urllib.error.HTTPError) as e:post(payload,'https://example.com')
        assert e.value.code==403
        assert len(list((tmp_path/'uploads').iterdir()))==1
    finally:server.shutdown();server.server_close();thread.join()


@pytest.mark.parametrize('length', [13, 16])
def test_overlong_symbols_are_rejected_before_saving_upload(tmp_path, length):
    payload={'symbol':'A'*length,'timezone':'America/New_York',
             'csv_base64':base64.b64encode(data(rows(3))).decode()}
    with pytest.raises(ValueError, match=r'1 \u81f3 12 \u4f4d'):
        d.store_upload(payload,tmp_path)
    assert not (tmp_path/'uploads').exists()
