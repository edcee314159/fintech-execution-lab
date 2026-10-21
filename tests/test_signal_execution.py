from pathlib import Path
from datetime import date,timedelta
import importlib.util
import numpy as np
import pytest
from execution_volume_validation.data import Day


def module():
    p=Path(__file__).resolve().parents[1]/'tools/signal_execution.py'
    if not p.exists():pytest.fail('Signal module not implemented')
    s=importlib.util.spec_from_file_location('test_signal_engine',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def days(n=5,flat=False):
    return [Day('SYNTH',date(2026,9,1)+timedelta(days=i),np.full(78,1000,dtype=int),np.full(78,100.) if flat else 100*np.exp(np.cumsum(np.sin(np.arange(78)/5)*.001)),100.) for i in range(n)]


def test_signal_adjustment_direction_fallback_and_capacity_floor():
    m=module()
    assert m.adjust_request(100,20,500,-.001,100.,0)==100
    assert m.adjust_request(100,20,500,-.001,100.,1)>100
    assert 20<=m.adjust_request(100,20,500,.001,100.,1)<100


def test_flat_signal_reliability_falls_back_to_capacity_policy():
    m=module();h=days(3,True);model=m.fit_model(h)
    assert model['reliability']==0
    r=m.replay_day(h,days(1,True)[0],1000,.1)
    assert r['strategies']['capacity']['fills']==r['strategies']['trusted']['fills']


def test_signal_and_volume_future_changes_do_not_change_earlier_requests():
    m=module();h=days(3);target=days(1)[0];close=target.close.copy();close[10:]*=1.2;volume=target.volume.copy();volume[10:]=0
    other=Day(target.symbol,target.day,volume,close,target.open_price)
    a=m.replay_day(h,target,3000,.1);b=m.replay_day(h,other,3000,.1)
    for policy in a['traces']:
        assert [x['request'] for x in a['traces'][policy][:11]]==[x['request'] for x in b['traces'][policy][:11]]
    for s in a['strategies'].values():assert sum(s['fills'])+s['residual']==3000 and max(s['fills'])<=100


def test_signal_study_records_past_validation_and_common_complete_subset():
    m=module();r=m.run_study(days(5),{'lookback':3,'evaluation_days':2,'fraction':.05,'participation_rate':.1,'signal_scenario':'inverted'})
    assert r['dashboard_summary']['evaluation_days']==2 and len(r['records'])==6
    for d in r['daily']:
        assert max(d['model']['train_dates'])<d['date']
        assert all(x['train_end']<x['validation_date']<d['date'] for x in d['model']['validation_folds'])
    common=[d['date'] for d in r['daily'] if all(x['complete'] for x in r['records'] if x['date']==d['date'])]
    assert all(s['common_complete_count']==len(common) for s in r['dashboard_summary']['strategies'])


def test_zero_signal_stress_makes_all_policies_identical():
    m=module();r=m.replay_day(days(3),days(1)[0],3000,.1,scenario='zero')
    assert r['strategies']['capacity']['fills']==r['strategies']['always']['fills']==r['strategies']['trusted']['fills']


def test_comparable_impact_is_empty_when_no_policy_set_completes():
    m=module();r=m.run_study(days(4,True),{'lookback':3,'evaluation_days':1,'fraction':.05,'participation_rate':.01,'signal_scenario':'learned'})
    assert all(x['common_complete_count']==0 and x['mean_assumed_impact'] is None for x in r['dashboard_summary']['strategies'])
