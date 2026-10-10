import numpy as np
import pytest
from execution_lab.config import ExecutionConfig
from execution_lab.schedule import make_twap, make_ac
from execution_lab.simulation import generate_prices, run_paired

def schedules(c):
    return {"twap": make_twap(c), "ac_simplified": make_ac(c)}

def test_zero_volatility_accounting():
    c = ExecutionConfig.from_dict(dict(quantity=10, duration=2, intervals=2,
        price=100, impact=0.1, volatility=0, trials=4))
    e = run_paired(c, schedules(c))
    np.testing.assert_array_equal(e.prices, np.full((4, 3), 100))
    for name in e.schedules:
        np.testing.assert_allclose(e.fills[name], np.full((4, 2), 99.5))
        np.testing.assert_allclose(e.costs[name], [5]*4)
    assert e.valid_pairs.all()

def test_same_seed_shared_paths_and_exposure_identity():
    c = ExecutionConfig.from_dict(dict(quantity=12, duration=2, intervals=2,
        price=1000, impact=1, volatility=1, risk_aversion=1, trials=4))
    first = run_paired(c, schedules(c))
    second = run_paired(c, schedules(c))
    np.testing.assert_array_equal(first.prices, second.prices)
    assert first.prices.shape == (4, 3)
    for name, s in first.schedules.items():
        np.testing.assert_array_equal(first.costs[name], second.costs[name])
        np.testing.assert_allclose(first.fills[name], first.prices[:, :-1]-s.quantities)
        # Two-step hand identity: cost = deterministic impact - inventory after first trade * first innovation.
        expected = sum(s.quantities**2) - s.inventory[1] * (first.prices[:, 1]-1000)
        np.testing.assert_allclose(first.costs[name], expected, atol=1e-10)

def test_nonpositive_price_flagged_without_resampling():
    c = ExecutionConfig.from_dict(dict(quantity=100, duration=1, intervals=1,
        price=1, impact=1, volatility=0, trials=4))
    e = run_paired(c, schedules(c))
    np.testing.assert_array_equal(e.prices, generate_prices(c))
    assert not e.valid_pairs.any()
    assert len(e.invalid_reasons) == 4
    assert "nonpositive_execution_price" in e.invalid_reasons[0]["reasons"]
    assert e.fills["twap"][0,0] == -99

def test_reference_price_invalidates_whole_pair():
    c = ExecutionConfig.from_dict(dict(quantity=1, duration=1, intervals=1,
        price=0.001, impact=1e-12, volatility=100, trials=200))
    e = run_paired(c, schedules(c))
    assert (~e.valid_pairs).any()
    assert any("nonpositive_reference_price" in d["reasons"] for d in e.invalid_reasons)

def test_reject_wrong_strategy_contract():
    c = ExecutionConfig()
    with pytest.raises(ValueError):
        run_paired(c, {"twap": make_twap(c)})

def test_small_impact_high_notional_preserves_deterministic_cost():
    c = ExecutionConfig.from_dict(dict(quantity=10000000, duration=10000,
        intervals=1000, price=1000000, impact=1e-12, volatility=0, trials=5))
    e = run_paired(c, schedules(c))
    for costs in e.costs.values():
        np.testing.assert_allclose(costs, [.01]*5, rtol=1e-12, atol=0)
    assert e.valid_pairs.all()


def test_innovations_below_price_precision_still_carry_cost_risk():
    c = ExecutionConfig.from_dict(dict(quantity=10, duration=2, intervals=2,
        price=1000000, impact=1e-12, volatility=1e-14, risk_aversion=0,
        trials=2, seed=0))
    e = run_paired(c, schedules(c))
    np.testing.assert_array_equal(e.prices, np.full((2,3),1000000))
    expected = [5e-11 - 5e-14*.1257302210933933,
        5e-11 - 5e-14*.6404226504432821]
    np.testing.assert_allclose(e.costs['twap'], expected, rtol=1e-12, atol=0)
    assert e.price_innovations.shape == (2,2)
    assert e.accounting["strategies"]["twap"]["reconciled_within_roundoff"]
