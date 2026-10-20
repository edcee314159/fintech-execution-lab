from pathlib import Path
import importlib.util,json,threading,urllib.request,urllib.error
import numpy as np
import pytest
spec=importlib.util.spec_from_file_location('replay_dashboard',Path(__file__).resolve().parents[1]/'tools/dashboard.py')
d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
ROOT=Path(__file__).resolve().parents[1]

def test_every_frozen_case_is_preserved_and_accounted_for():
    catalog=d.replay_catalog()
    assert len(catalog)==270 and len({c['id'] for c in catalog})==270
    evidence=json.loads((ROOT/'results/real-volume/results.json').read_text(encoding='utf-8'))
    with np.load(ROOT/'results/real-volume/derived-schedules.npz',allow_pickle=False) as arrays:
        unavailable=completed=unfinished=0
        for case in catalog:
            r=d.replay_case(case['id'])
            assert r['case']==case
            if not case['planning_feasible']:
                unavailable+=1;assert not r['available'];assert 'planned' not in r
                continue
            assert r['available'];q=case['quantity']
            planned=np.array(r['planned']);fills=np.array(r['fills']);remaining=np.array(r['remaining'])
            np.testing.assert_array_equal(planned,arrays[case['id']+'_planned'])
            np.testing.assert_array_equal(fills,arrays[case['id']+'_fills'])
            np.testing.assert_array_equal(remaining,arrays[case['id']+'_remaining'])
            assert len(planned)==len(fills)==78 and len(remaining)==79
            assert planned.sum()==q and remaining[0]==q
            np.testing.assert_array_equal(r['cumulative_planned'],np.r_[0,planned.cumsum()])
            np.testing.assert_array_equal(r['cumulative_filled'],q-remaining)
            np.testing.assert_array_equal(r['backlog'],np.r_[0,planned.cumsum()]-(q-remaining))
            assert min(r['backlog'])>=0
            assert r['capacity_limited']==[v>0 for v in r['backlog'][1:]]
            assert remaining[-1]==case['residual']
            if remaining[-1]:unfinished+=1
            else:completed+=1
        assert (completed,unfinished,unavailable)==(229,35,6)

@pytest.mark.parametrize('key',['../../private-data','', 'unknown'])
def test_unknown_case_is_rejected(key):
    with pytest.raises(ValueError):d.replay_case(key)

def test_http_replay_routes_and_no_plan_state(tmp_path):
    server=d.make_server(0,tmp_path);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base='http://127.0.0.1:'+str(server.server_port)
    try:
        with urllib.request.urlopen(base+'/api/replay-cases') as f:cases=json.load(f)
        no_plan=next(c for c in cases if not c['planning_feasible'])
        with urllib.request.urlopen(base+'/api/replay?id='+no_plan['id']) as f:r=json.load(f)
        assert r['available'] is False and r['case']==no_plan
        with pytest.raises(urllib.error.HTTPError) as e:urllib.request.urlopen(base+'/api/replay?id=unknown')
        assert e.value.code==400
        with pytest.raises(urllib.error.HTTPError) as e:urllib.request.urlopen(base+'/api/replay')
        assert e.value.code==400
        assert not list(tmp_path.iterdir())
    finally:server.shutdown();server.server_close();thread.join()
