from pathlib import Path
import importlib.util,copy
import pytest


def module():
    p=Path(__file__).resolve().parents[1]/'tools/orderbook_execution.py'
    if not p.exists():pytest.fail('Queue module not implemented')
    s=importlib.util.spec_from_file_location('test_queue_engine',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def events(n=40):return [{'bid_cents':10000,'ask_cents':10002,'bid_depths':[10,10,10],'ask_depth':0,'buy_volume':100,'sell_volume':100,'cancel_front':0} for _ in range(n)]


def test_synthetic_stream_is_deterministic_and_explicitly_labeled():
    m=module();config={'scenario':'balanced','quantity':500,'seed':7,'participation_rate':.1,'latency_ticks':1}
    a=m.run_study(config);b=m.run_study(config)
    assert a==b and a['data_kind']=='synthetic_order_book'
    assert len(a['policies'])==3
    assert all(len(x['trace'])==240 for x in a['policies'].values())


@pytest.mark.parametrize('policy',['passive','aggressive','dynamic'])
def test_queue_caps_no_oversell_and_no_fill_before_latency(policy):
    m=module();r=m.replay(events(),500,.29,policy,latency=3)
    assert sum(x['quantity'] for x in r['fills'])+r['residual']==500
    assert all(x['filled']==0 for x in r['trace'][:3])
    assert all(x['filled']<=58 for x in r['trace'])
    assert r['markout_eligible_shares']<=500-r['residual']


def test_market_depth_and_queue_ahead_prevent_guaranteed_fills():
    m=module();e=events();
    for x in e:x['bid_depths']=[0,0,0];x['ask_depth']=100000
    for policy in ('passive','aggressive','dynamic'):
        r=m.replay(e,500,.1,policy);assert r['residual']==500


def test_future_events_do_not_change_earlier_actions():
    m=module();a=events();b=copy.deepcopy(a)
    for x in b[10:]:x['bid_cents']+=100;x['ask_cents']+=100;x['buy_volume']=0
    for policy in ('passive','aggressive','dynamic'):
        x=m.replay(a,500,.1,policy);y=m.replay(b,500,.1,policy)
        assert x['trace'][:10]==y['trace'][:10]


def test_cancel_pending_fill_is_accounted_before_replacement():
    m=module();e=events(16)
    for i,x in enumerate(e):
        x['buy_volume']=100 if i==6 else 0;x['sell_volume']=100
        if i>=4:x['ask_cents']=10003
    r=m.replay(e,50,.1,'passive',latency=3)
    assert any(x['tick']==6 and x['quantity']>0 and x['cancel_pending'] for x in r['fills'])
    assert sum(x['quantity'] for x in r['fills'])+r['residual']==50
    assert any(x['status']=='cancelled' for x in r['orders'])


def test_invalid_market_event_is_rejected():
    m=module();e=events();e[2]['ask_cents']=9999
    with pytest.raises(ValueError):m.replay(e,500,.1,'dynamic')


def test_marketable_limit_never_walks_below_its_limit_price():
    m=module();e=events(3)
    e[0].update(bid_cents=9998,ask_cents=10000)
    for x in e[1:]:x.update(bid_cents=10000,ask_cents=10002,bid_depths=[1,10,10])
    r=m.replay(e,10,1.,'passive')
    assert all(f['price']>=100. for f in r['fills'])
    assert r['trace'][1]['filled']==1 and r['trace'][1]['remaining']==9


def test_aggressive_pacing_accounts_for_known_command_latency_when_depth_is_ample():
    m=module();e=events(20)
    for x in e:x.update(bid_depths=[10000,10000,10000],buy_volume=1000,sell_volume=1000)
    r=m.replay(e,100,1.,'aggressive',latency=3)
    assert r['complete'] and r['residual']==0


def test_resting_limit_remains_maker_when_external_quote_moves_through_it():
    m=module();e=events(4)
    for x in e[:2]:x.update(bid_cents=9998,ask_cents=10000,buy_volume=0,sell_volume=100)
    for x in e[2:]:x.update(bid_cents=10000,ask_cents=10002)
    r=m.replay(e,10,1.,'passive')
    assert r['complete'] and r['fills']
    assert all(f['liquidity']=='maker' and f['price']==100. for f in r['fills'])
