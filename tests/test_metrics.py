import numpy as np
import pytest
from execution_lab.config import ExecutionConfig
from execution_lab.schedule import make_twap, make_ac
from execution_lab.simulation import run_paired
from execution_lab.metrics import predictions, summarize

def experiment(c):
    return run_paired(c, {"twap": make_twap(c), "ac_simplified": make_ac(c)})

def test_zero_volatility_identical_costs_and_point_intervals():
    c = ExecutionConfig.from_dict(dict(quantity=10, duration=2, intervals=2,
        impact=.1, volatility=0, trials=4))
    e = experiment(c)
    s = summarize(e)
    assert predictions(c, e.schedules["twap"])["variance"] == 0
    assert s["strategies"]["twap"]["empirical"]["ci95_mean"] == [5, 5]
    assert s["paired"]["empirical"]["ci95_mean"] == [0, 0]
    assert s["paired"]["empirical"]["variance"] == 0

def test_invalid_model_has_no_inferential_claims():
    c = ExecutionConfig.from_dict(dict(quantity=100, duration=1, intervals=1,
        price=1, impact=1, volatility=0, trials=4))
    s = summarize(experiment(c))
    assert s["status"] == "invalid_model"
    assert s["valid_pairs"] == 0 and s["invalid_pairs"] == 4
    assert s["paired"]["empirical"]["mean"] is None
    assert s["paired"]["empirical"]["ci95_mean"] is None
    assert s["paired"]["all_paths"]["label"] == "outside_model_algebraic_diagnostics"
    assert s["paired"]["all_paths"]["ci95_mean"] is None

def test_integer_predictions_and_monte_carlo_consistency():
    c = ExecutionConfig.from_dict(dict(quantity=12, duration=2, intervals=2,
        price=1000, impact=1, volatility=.5, risk_aversion=1, trials=20000))
    e = experiment(c)
    np.testing.assert_array_equal(e.schedules["twap"].quantities, [6,6])
    np.testing.assert_array_equal(e.schedules["ac_simplified"].quantities, [7,5])
    s = summarize(e)
    for name, mean, variance in [("twap",72,9), ("ac_simplified",74,6.25)]:
        p = s["strategies"][name]["prediction"]
        assert p["mean"] == mean and p["variance"] == variance
        observed = s["strategies"][name]["empirical"]
        assert abs(observed["mean"]-mean) < 4*np.sqrt(variance/c.trials)
        assert observed["variance"] == pytest.approx(variance, rel=.05)
    p = s["paired"]["prediction"]
    assert p["mean"] == 2 and p["variance"] == .25
    observed = s["paired"]["empirical"]
    assert abs(observed["mean"]-2) < 4*np.sqrt(.25/c.trials)
    assert observed["variance"] == pytest.approx(.25, rel=.05)
    # Front-loading may cost more in expectation; there is no blanket cost/risk win.
    assert s["strategies"]["ac_simplified"]["prediction"]["mean"] > 72

def test_one_valid_pair_does_not_produce_a_confidence_interval():
    c = ExecutionConfig.from_dict({"intervals": 1, "trials": 2})
    e = experiment(c)
    e.valid_pairs[:] = [True, False]
    s = summarize(e)
    assert s["status"] == "partially_invalid"
    assert s["paired"]["empirical"]["mean"] is None
    assert s["paired"]["empirical"]["ci95_mean"] is None
