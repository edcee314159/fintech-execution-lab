"""Fault recovery and market-state invariants; synthetic broker only."""
from pathlib import Path
import importlib.util,json,copy
import pytest

def module(name):
    p=Path(__file__).resolve().parents[1]/'tools'/f'{name}.py'
    if not p.exists():pytest.fail(f'{name} is not implemented')
    spec=importlib.util.spec_from_file_location('test_'+name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def recovery_config():
    return dict(quantity=1000,scenario='mixed',seed=7)
def guard_config():
    return dict(quantity=1000,scenario='mixed',seed=7,stale_after=3,recovery_ticks=5,
                max_child=40,participation_rate=.1,session_date='2026-10-23')

def test_unknown_intent_reserves_quantity_and_restart_cannot_resend(tmp_path):
    m=module('order_recovery');ledger=m.OrderLedger(tmp_path/'orders.jsonl',100)
    assert ledger.reconcile(m.snapshot(0,[],[],100))
    order=ledger.intent(60)
    assert ledger.summary()['reserved']==60
    assert ledger.summary()['available']==0
    other=m.OrderLedger(tmp_path/'orders.jsonl',100)
    assert other.summary()['reserved']==60
    with pytest.raises(ValueError):other.intent(60)
    assert not other.reconcile(m.snapshot(1,[],[],100))
    assert other.summary()['reserved']==60 and not other.summary()['ready']

def test_execution_dedup_status_and_complete_snapshot_are_not_added_twice(tmp_path):
    m=module('order_recovery');l=m.OrderLedger(tmp_path/'orders.jsonl',100)
    l.reconcile(m.snapshot(0,[],[],100));oid=l.intent(60)
    execution={'execution_id':'E1','client_id':oid,'quantity':20}
    l.execution(execution);l.execution(execution);l.status(oid,20,'active')
    assert l.summary()['confirmed_filled']==20
    orders=[{'client_id':oid,'quantity':60,'filled':20,'status':'active'}]
    assert l.reconcile(m.snapshot(1,orders,[execution],80))
    assert l.summary()['confirmed_filled']==20 and l.summary()['reserved']==40
    assert l.summary()['available']==40
    l.status(oid,0,'active')  # delayed earlier callback cannot roll back fills
    assert l.summary()['confirmed_filled']==20

def test_cancel_pending_and_partial_snapshot_never_release_possible_fills(tmp_path):
    m=module('order_recovery');l=m.OrderLedger(tmp_path/'orders.jsonl',100)
    l.reconcile(m.snapshot(0,[],[],100));oid=l.intent(60)
    l.cancel(oid);l.status(oid,20,'cancelled')
    assert l.summary()['reserved']==40 and not l.summary()['ready']
    orders=[dict(client_id=oid,quantity=60,filled=20,status='cancelled')]
    e=[dict(execution_id='E1',client_id=oid,quantity=20)]
    assert not l.reconcile(m.snapshot(1,orders,e,80,complete=False))
    assert l.summary()['reserved']==40
    assert l.reconcile(m.snapshot(2,orders,e,80))
    assert l.summary()['reserved']==0 and l.summary()['available']==80

def test_conflicting_execution_and_position_mismatch_fail_closed(tmp_path):
    m=module('order_recovery');l=m.OrderLedger(tmp_path/'orders.jsonl',100)
    l.reconcile(m.snapshot(0,[],[],100));oid=l.intent(60)
    l.execution(dict(execution_id='E1',client_id=oid,quantity=20))
    assert not l.execution(dict(execution_id='E1',client_id=oid,quantity=21))
    assert not l.summary()['ready']
    orders=[dict(client_id=oid,quantity=60,filled=20,status='active')]
    assert not l.reconcile(m.snapshot(1,orders,[dict(execution_id='E1',client_id=oid,quantity=20)],99))
    assert not l.summary()['ready']

def test_journal_torn_or_tampered_record_is_not_silently_repaired(tmp_path):
    m=module('order_recovery');p=tmp_path/'orders.jsonl';l=m.OrderLedger(p,100)
    l.reconcile(m.snapshot(0,[],[],100));l.intent(60)
    raw=p.read_text();p.write_text(raw.replace('"quantity":60','"quantity":61'))
    with pytest.raises(ValueError):m.OrderLedger(p,100)
    p.write_text(raw[:-3])
    with pytest.raises(ValueError):m.OrderLedger(p,100)

@pytest.mark.parametrize('scenario',['mixed','lost_ack','cancel_race','unresolved'])
def test_recovery_stress_respects_parent_and_keeps_failure(tmp_path,scenario):
    m=module('order_recovery');c=recovery_config();c['scenario']=scenario
    r=m.run_study(c,tmp_path)
    safe=r['policies']['reconciled']
    assert safe['actual_filled']<=c['quantity']
    assert safe['duplicate_order_submissions']==0 and safe['oversold']==0
    assert all(x['known_filled']+x['reserved']<=c['quantity'] for x in safe['trace'])
    if scenario=='unresolved':assert safe['residual']>0 and safe['trace'][-1]['reserved']>0
    else:assert safe['residual']==0
    assert len(r['journal'])>5
    json.dumps(r,allow_nan=False)

def quote(seq,t,bid=10000,ask=10002,resync=False):
    return dict(seq=seq,source_tick=t,bid=bid,ask=ask,resync=resync)
def event(t,q=None,status=None,volume=1000):
    return dict(tick=t,quote=q,status=status,observed_volume=volume,session_open=True)
def trading(seq=1):return dict(seq=seq,state='trading')

def test_zero_volume_is_not_a_halt_and_old_quote_does_not_refresh_age():
    m=module('market_guard');g=m.MarketGuard(3,2)
    for t in range(6):last=g.update(event(t,quote(t+1,t),trading() if t==0 else None,volume=0))
    assert last['state']=='normal' and last['allow']
    for t in range(6,10):last=g.update(event(t,quote(1,0)))
    assert last['state']=='stale_data' and not last['allow']

def test_quote_only_and_halt_require_explicit_trade_resume_and_ramp():
    m=module('market_guard');g=m.MarketGuard(3,5)
    for t in range(8):g.update(event(t,quote(t+1,t),trading() if t==0 else None))
    assert g.update(event(8,quote(9,8),dict(seq=2,state='halted')))['state']=='halted'
    assert g.update(event(9,quote(10,9),dict(seq=3,state='quote_only')))['state']=='quote_only'
    assert g.update(event(10,quote(11,10),dict(seq=2,state='trading')))['state']=='quote_only'
    x=g.update(event(11,quote(12,11),trading(4)));assert not x['allow']
    g.update(event(12,quote(13,12)))
    x=g.update(event(13,quote(14,13)))
    assert x['state']=='recovering' and 0<x['ramp']<1

def test_sequence_gap_needs_snapshot_and_crossed_future_quotes_block():
    m=module('market_guard');g=m.MarketGuard(3,3)
    g.update(event(0,quote(1,0),trading()))
    assert g.update(event(1,quote(3,1)))['state']=='feed_gap'
    assert g.update(event(2,quote(4,2)))['state']=='feed_gap'
    assert g.update(event(3,quote(5,3,resync=True)))['state']=='recovering'
    assert g.update(event(4,quote(6,4,bid=10003,ask=10002)))['state']=='invalid_data'
    assert not g.update(event(5,quote(7,9)))['allow']

def test_2026_calendar_handles_holiday_early_close_and_unknown_year():
    m=module('market_guard')
    assert m.session_bounds('2026-11-26') is None
    assert m.session_bounds('2026-11-27')==(570,780)
    assert m.session_bounds('2026-12-24')==(570,780)
    assert m.session_bounds('2026-10-23')==(570,960)
    with pytest.raises(ValueError):m.session_bounds('2027-01-04')

@pytest.mark.parametrize('scenario',['mixed','stale','halt','zero','gap','early_close'])
def test_guard_replay_never_fills_halts_or_closed_and_limits_recovery(scenario):
    m=module('market_guard');c=guard_config();c['scenario']=scenario
    if scenario=='early_close':c['session_date']='2026-11-27'
    r=m.run_study(c)
    safe=r['policies']['guarded']
    assert all(x['filled']==0 for x in safe['trace'] if x['actual_halted'] or not x['session_open'])
    assert all(x['request']<=c['max_child'] for x in safe['trace'])
    assert sum(x['filled'] for x in safe['trace'])+safe['residual']==c['quantity']
    assert safe['unsafe_attempts']==0
    assert safe['quote_only_attempts']==0
    json.dumps(r,allow_nan=False)

def test_guard_future_events_do_not_change_prefix():
    m=module('market_guard');c=guard_config();events=m.generate_events(c)
    other=copy.deepcopy(events)
    for e in other[50:]:
        e['truth_volume']=0;e['quote']=None;e['status']={'seq':1000+e['tick'],'state':'halted'}
    a=m.replay(c,events,'guarded');b=m.replay(c,other,'guarded')
    assert a['trace'][:50]==b['trace'][:50]

@pytest.mark.parametrize('kind',['order_recovery','market_guard'])
@pytest.mark.parametrize('bad',[True,float('nan'),-1])
def test_safety_rejects_invalid_parameters(kind,bad):
    m=module(kind);c=recovery_config() if kind=='order_recovery' else guard_config()
    c['quantity']=bad
    with pytest.raises(ValueError):m.options(c)

@pytest.mark.parametrize('bad',[None,{}, {'seq':2,'orders':[{}],'executions':[],'position':100,'complete':True}])
def test_malformed_snapshot_closes_previously_ready_ledger(tmp_path,bad):
    m=module('order_recovery');l=m.OrderLedger(tmp_path/'orders.jsonl',100)
    l.reconcile(m.snapshot(0,[],[],100))
    assert not l.reconcile(bad)
    assert not l.summary()['ready']

def test_late_snapshot_cannot_rewrite_terminal_fill_and_overcommit_parent(tmp_path):
    m=module('order_recovery');l=m.OrderLedger(tmp_path/'orders.jsonl',100)
    l.reconcile(m.snapshot(0,[],[],100));oid=l.intent(60)
    e1=dict(execution_id='E1',client_id=oid,quantity=20)
    closed=dict(client_id=oid,quantity=60,filled=20,status='cancelled')
    assert l.reconcile(m.snapshot(1,[closed],[e1],80))
    other=l.intent(80)
    e2=dict(execution_id='E2',client_id=oid,quantity=20)
    changed=dict(closed,filled=40)
    live=dict(client_id=other,quantity=80,filled=0,status='active')
    assert not l.reconcile(m.snapshot(2,[changed,live],[e1,e2],60))
    s=l.summary()
    assert not s['ready'] and s['confirmed_filled']+s['reserved']<=100
    with pytest.raises(ValueError):l.intent(1)
