from pathlib import Path
from datetime import date,timedelta
import importlib.util
import numpy as np
import pytest
from execution_volume_validation.data import Day


def module():
    path=Path(__file__).resolve().parents[1]/'tools/adaptive_execution.py'
    if not path.exists():pytest.fail('Adaptive execution module is not implemented')
    spec=importlib.util.spec_from_file_location('adaptive_test',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def test_forecast_conditions_only_on_observed_prefix_and_handles_zero_prefix():
    m=module();h=np.full((5,78),100,dtype=int);h[:,0]=0
    f=m.forecast(h,np.array([0]),.1)
    assert f['scenario_caps'].shape==(5,77)
    assert np.isfinite(f['scenario_caps']).all()
    assert f['capacity_p10']<=f['capacity_p50']<=f['capacity_p90']
    assert m.decision(h,np.array([],dtype=int),390,.1)['request']<=390


def test_decisions_do_not_change_when_current_and_future_volume_change():
    m=module();h=np.full((5,78),100,dtype=int);a=np.full(78,100,dtype=int);b=a.copy();b[10:]=1
    x=m.replay_day(h,a,390,.1);y=m.replay_day(h,b,390,.1)
    for t in range(11):
        for key in ('request','nominal','capacity_cover_share','capacity_p10','capacity_p90'):
            assert x['trace'][t][key]==y['trace'][t][key],(t,key)


def test_every_policy_conserves_quantity_and_obeys_exact_integer_caps():
    m=module();h=np.full((5,78),100,dtype=int);v=np.full(78,100,dtype=int)
    r=m.replay_day(h,v,390,.29)
    for s in r['strategies'].values():
        assert max(s['fills'])<=29
        assert sum(s['fills'])+s['residual']==390
        assert s['complete']==(s['residual']==0)
    assert m.capacities([100],.29).tolist()==[29]


def test_zero_capacity_and_impossible_deadline_remain_visible():
    m=module();h=np.full((5,78),100,dtype=int)
    r=m.replay_day(h,np.zeros(78,dtype=int),390,.1)
    assert all(s['residual']==390 and not s['complete'] for s in r['strategies'].values())
    assert any(t['capacity_cover_share']<.9 for t in r['trace'])
    assert r['calibration']['checkpoints'][0]['interval']==0
    assert r['calibration']['checkpoints'][0]['covered'] is False


def test_robust_policy_can_use_early_capacity_without_claiming_universal_improvement():
    m=module();h=np.full((5,78),100,dtype=int);h[0,39:]=0;h[1,39:]=0
    v=np.full(78,100,dtype=int);v[39:]=0
    r=m.replay_day(h,v,390,.1)
    assert r['strategies']['adaptive']['residual']<r['strategies']['fixed_twap']['residual']
    assert r['strategies']['adaptive']['assumed_impact']>=r['strategies']['fixed_twap']['assumed_impact']


def test_study_is_past_only_and_counts_dates_separately_from_policy_cases():
    m=module();days=[Day('SYNTH',date(2026,9,1)+timedelta(days=i),np.full(78,100,dtype=int),np.full(78,100.),100.) for i in range(5)]
    r=m.run_study(days,{'lookback':3,'evaluation_days':2,'fraction':.05,'participation_rate':.1})
    assert r['dashboard_summary']['evaluation_days']==2
    assert r['dashboard_summary']['cases']==6
    assert all(len(x['train_dates'])==3 and max(x['train_dates'])<x['date'] for x in r['records'])
    assert all(x['dates']==2 for x in r['dashboard_summary']['strategies'])
    assert r['calibration']['checkpoints'][0]['dates']==2


@pytest.mark.parametrize('rate',[0,True,float('nan'),1.1])
def test_invalid_participation_rates_are_rejected(rate):
    m=module()
    with pytest.raises(ValueError):m.replay_day(np.full((5,78),100),np.full(78,100),100,rate)
