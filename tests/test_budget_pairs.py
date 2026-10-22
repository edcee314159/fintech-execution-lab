"""Decision invariants for synthetic budget and two-leg execution research."""
from pathlib import Path
import importlib.util
import json
import numpy as np
import pytest

def engine(name):
    path=Path(__file__).resolve().parents[1]/'tools'/f'{name}_execution.py'
    if not path.exists():
        pytest.fail(f'{name} engine is not implemented')
    spec=importlib.util.spec_from_file_location(f'test_{name}',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m

def budget_config(**changes):
    return dict(quantity=1000,price=100.,deadline=30,volume_per_minute=1500,
                volatility_bps=3.,spread_bps=2.,fee_bps=.5,impact_bps=20.,
                participation_rate=.1,budget_bps=10.,required_success=.9,seed=7,**changes)

def pair_config():
    return dict(sell_quantity=1000,buy_quantity=1000,sell_price=100.,buy_price=100.,
                initial_cash=1000.,deadline=30,participation_rate=.1,
                volatility_bps=5.,correlation=.8,spread_bps=2.,fee_bps=.5,
                impact_bps=20.,risk_weight=4.,max_progress_gap=.15,scenario='buy_slow',seed=7)

def test_budget_joint_success_retains_unfinished_and_price_cost_components():
    m=engine('budget');c=budget_config();r=m.run_study(c)
    assert r['data_kind']=='synthetic_budget_scenarios'
    assert r['planning_seed']!=r['validation_seed']
    assert len(r['candidates'])==8
    for row in r['candidates']:
        for split in ('planning','validation'):
            s=row[split]
            assert s['successes']+s['budget_breaches']+s['unfinished']==s['trials']
            assert s['completed']+s['unfinished']==s['trials']
            assert s['joint_success_rate']==s['successes']/s['trials']
        t=row['validation_trace']
        assert sum(x['filled'] for x in t)+t[-1]['remaining']==c['quantity']
        assert all(x['filled']<=x['capacity'] for x in t)
        assert sum(x['spread_cost']+x['fee_cost']+x['impact_cost']+x['timing_cost'] for x in t)==pytest.approx(row['validation_first_shortfall'])
    json.dumps(r,allow_nan=False)

def test_budget_fixed_plans_do_not_see_actual_future_volume():
    m=engine('budget');c=budget_config()
    a=m.generate_paths(c,123,4);b={k:v.copy() for k,v in a.items()}
    b['volumes'][:,5:]=0;b['mids'][:,5:]*=1.5
    x=m.replay(c,30,'uniform',a);y=m.replay(c,30,'uniform',b)
    assert [t['request'] for t in x['trace'][:6]]==[t['request'] for t in y['trace'][:6]]
    assert [t['filled'] for t in x['trace'][:5]]==[t['filled'] for t in y['trace'][:5]]

def test_budget_no_feasible_candidate_is_explicit_not_guaranteed_impossibility():
    m=engine('budget');c=budget_config();c.update(quantity=100000,volume_per_minute=10,budget_bps=0)
    r=m.run_study(c)
    assert r['selected_id'] is None and r['status']=='no_candidate_meets_target'
    assert all(x['validation']['unfinished']==x['validation']['trials'] for x in r['candidates'])

def test_budget_selection_uses_planning_only():
    m=engine('budget');rows=[
        {'id':'a','horizon':10,'planning':{'joint_success_rate':.95,'mean_complete_bps':5.,'p95_complete_bps':8.},'validation':{'joint_success_rate':0}},
        {'id':'b','horizon':20,'planning':{'joint_success_rate':1.,'mean_complete_bps':1.,'p95_complete_bps':2.},'validation':{'joint_success_rate':1}}]
    assert m.select_candidate(rows,.9)=='a'
    rows[0]['validation']['joint_success_rate']=1
    rows[1]['validation']['joint_success_rate']=0
    assert m.select_candidate(rows,.9)=='a'

def test_pair_cash_ledger_integer_conservation_and_same_parent_constraints():
    m=engine('pairs');c=pair_config();r=m.run_study(c)
    assert r['data_kind']=='synthetic_two_asset_scenarios'
    assert set(r['policies'])=={'independent','coordinated'}
    for p in r['policies'].values():
        assert sum(x['sell_filled'] for x in p['trace'])+p['sell_remaining']==c['sell_quantity']
        assert sum(x['buy_filled'] for x in p['trace'])+p['buy_remaining']==c['buy_quantity']
        cash=round(c['initial_cash']*100)
        for t in p['trace']:
            cash+=t['sell_proceeds_cents']-t['buy_spend_cents']
            assert cash==t['cash_cents'] and cash>=0 and isinstance(cash,int)
            assert t['sell_filled']<=t['sell_capacity'] and t['buy_filled']<=t['buy_capacity']
            assert t['risk_variance']>=0
    json.dumps(r,allow_nan=False)

def test_pair_zero_cash_and_unaffordable_target_never_borrow_or_fabricate_fills():
    m=engine('pairs');c=pair_config();c.update(initial_cash=0.,buy_price=1000.,scenario='balanced')
    r=m.run_study(c)
    assert r['funding_warning']
    for p in r['policies'].values():
        assert p['buy_remaining']>0 and min(t['cash_cents'] for t in p['trace'])>=0
    assert r['dashboard_summary']['common_complete_count']==0
    assert all(s['common_complete_mean_bps'] is None for s in r['dashboard_summary']['strategies'])

def test_pair_future_price_and_volume_cannot_change_past_requests():
    m=engine('pairs');c=pair_config();events=m.generate_events(c,7)
    other=[dict(e) for e in events]
    for e in other[8:]:
        e['sell_mid_cents']+=1000;e['buy_mid_cents']+=500
        e['sell_volume']=0;e['buy_volume']=1
    for policy in ('independent','coordinated'):
        a=m.replay(c,events,policy);b=m.replay(c,other,policy)
        assert [(x['sell_request'],x['buy_request']) for x in a['trace'][:8]]==[(x['sell_request'],x['buy_request']) for x in b['trace'][:8]]
    other=[dict(e) for e in events];other[8]['buy_volume']=0
    a=m.replay(c,events,'coordinated');b=m.replay(c,other,'coordinated')
    assert (a['trace'][8]['sell_request'],a['trace'][8]['buy_request'])==(b['trace'][8]['sell_request'],b['trace'][8]['buy_request'])

def test_pair_covariance_risk_uses_opposite_target_deviations():
    m=engine('pairs')
    assert m.target_variance(10000.,-10000.,.01,1.)==pytest.approx(0,abs=1e-8)
    assert m.target_variance(10000.,-10000.,.01,0.)==pytest.approx(20000.)
    assert m.target_variance(10000.,-10000.,.01,-1.)==pytest.approx(40000.)

@pytest.mark.parametrize('name',['budget','pairs'])
@pytest.mark.parametrize('bad',[float('nan'),float('inf'),True,-1])
def test_engines_reject_invalid_numeric_inputs(name,bad):
    m=engine(name);c=budget_config() if name=='budget' else pair_config()
    c['participation_rate']=bad
    with pytest.raises(ValueError):m.run_study(c)

def test_budget_flat_price_costs_have_known_units():
    m=engine('budget');c=budget_config();c.update(quantity=100,deadline=4)
    paths={'mids':np.full((2,4),100.),'volumes':np.full((2,4),1000,dtype=int)}
    r=m.replay(c,4,'uniform',paths)
    assert r['summary']['mean_complete_bps']==pytest.approx(2.)
    assert r['first_shortfall']==pytest.approx(2.)

def test_pair_forecast_gap_target_reduces_asymmetric_leg_gap():
    m=engine('pairs');c=pair_config();c.update(volatility_bps=0,correlation=1.,initial_cash=100000.)
    events=[dict(sell_mid_cents=10000,buy_mid_cents=10000,sell_volume=1500,
                 buy_volume=150 if t<18 else 1500) for t in range(30)]
    a=m.replay(c,events,'independent');b=m.replay(c,events,'coordinated')
    assert a['complete'] and b['complete']
    assert b['max_progress_gap']<a['max_progress_gap']
