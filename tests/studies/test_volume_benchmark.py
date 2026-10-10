import json,math
import numpy as np
import pytest
from execution_lab.config import ExecutionConfig
from execution_lab.schedule import make_twap,make_ac
from execution_research.studies.volume.volume_benchmark import normalize_volume,make_volume_weighted,impact_coefficients,continuous_optimum,make_optimized,simulate_common,benchmark_costs,benchmark_prediction,run_study,export_study,validate_design

def config(**changes):
    return ExecutionConfig.from_dict({"quantity":12,"duration":2,"intervals":2,"price":100,"volatility":1,"impact":1,"risk_aversion":1,"trials":3,"seed":17}|changes)
def test_volume_weighted_hand_schedule_and_zero_slots():
    s=make_volume_weighted(config(),[1,2],integer=True)
    np.testing.assert_array_equal(s.quantities,[4,8]);np.testing.assert_array_equal(s.inventory,[12,8,0])
    s=make_volume_weighted(config(),[0,2],integer=True)
    np.testing.assert_array_equal(s.quantities,[0,12])
    assert not s.quantities.flags.writeable and not s.inventory.flags.writeable

def test_uniform_volume_equals_twap_including_rounding():
    c=config(quantity=13,intervals=4)
    s=make_volume_weighted(c,np.ones(4),integer=True);t=make_twap(c,integer=True)
    np.testing.assert_array_equal(s.quantities,t.quantities)
    np.testing.assert_array_equal(s.inventory,t.inventory)

def test_weight_scaling_invariance_and_safe_large_values():
    c=config();a=make_volume_weighted(c,[1,2],integer=False)
    b=make_volume_weighted(c,[1e307,2e307],integer=False)
    np.testing.assert_allclose(a.quantities,b.quantities,atol=1e-14)
    np.testing.assert_allclose(normalize_volume([1e308,1e308],2),[.5,.5])

@pytest.mark.parametrize("weights",[[0,0],[-1,2],[1,float("nan")],[1,float("inf")],[1],[True,2],[[1,2]]])
def test_invalid_forecast_volume_rejected(weights):
    with pytest.raises(ValueError):make_volume_weighted(config(),weights)

def test_variable_impact_solver_has_hand_solution():
    c=config();a=np.array([1.,2.]);x=continuous_optimum(c,a)
    # (1+2+1)*x1=1*12.
    np.testing.assert_allclose(x,[12,3,0],atol=1e-13)

def test_uniform_impact_matches_existing_continuous_ac():
    c=config(intervals=20,duration=20,quantity=1000,impact=.001,risk_aversion=.0001)
    a=impact_coefficients(c,np.ones(20),"constant")
    np.testing.assert_allclose(continuous_optimum(c,a),make_ac(c,integer=False).inventory,rtol=1e-10,atol=1e-9)

def test_inverse_volume_risk_neutral_optimum_is_volume_schedule():
    c=config(risk_aversion=0)
    a=impact_coefficients(c,[1,2],"inverse_expected_volume")
    np.testing.assert_allclose(continuous_optimum(c,a),[12,8,0],atol=1e-13)
    with pytest.raises(ValueError):impact_coefficients(c,[0,2],"inverse_expected_volume")

def test_three_strategy_accounting_matches_direct_proceeds():
    c=config();s={"twap":make_twap(c),"ac_simplified":make_ac(c),"volume_weighted":make_volume_weighted(c,[1,2])}
    increments=np.array([[1.,2.],[-1.,3.],[0.,-2.]])
    prices=np.column_stack([np.full(3,100.),100+np.cumsum(increments,axis=1)])
    result=simulate_common(c,s,np.ones(2),prices,increments)
    for name,plan in s.items():
        fills=prices[:,:-1]-plan.quantities
        np.testing.assert_allclose(result["arrival_costs"][name],1200-fills@plan.quantities)
    assert result["valid_mask"].all()

def test_vwap_cost_uses_external_volume_not_own_fills():
    c=config(volatility=0,risk_aversion=0);s=make_volume_weighted(c,[1,2],integer=False)
    prices=np.array([[100.,103.,106.],[100.,99.,99.],[100.,102.,104.]])
    increments=np.diff(prices,axis=1)
    costs=benchmark_costs(c,s,np.ones(2),increments,[1,2])
    np.testing.assert_allclose(costs,np.full(3,80.))
    prediction=benchmark_prediction(c,s,np.ones(2),[1,2])
    assert prediction["variance"]==pytest.approx(0)
    shifted=benchmark_costs(c,s,np.ones(2),increments,[2,1])
    assert not np.array_equal(shifted,costs)
    np.testing.assert_array_equal(s.quantities,[4,8])

def test_common_invalid_mask_preserves_paths_and_suppresses_inference():
    c=config(price=10)
    s={"twap":make_twap(c),"ac_simplified":make_ac(c),"volume_weighted":make_volume_weighted(c,[0,1])}
    prices=np.array([[10.,10.,10.],[10.,10.,-1.],[10.,10.,10.]]);increments=np.diff(prices,axis=1)
    result=simulate_common(c,s,np.ones(2),prices,increments)
    assert result["valid_mask"].tolist()==[False,False,False]
    assert len(result["arrival_costs"]["twap"])==3
    assert result["status"]=="invalid_model"
    d=design()
    d["base"].update(price=10,volatility=0,impact=1)
    study,raw=run_study(d)
    assert study["verification"]["total_invalid_case_paths"]==80
    for row in study["strategy_metrics"]+study["paired_metrics"]:
        assert row["all_paths"]["count"]==10
        assert row["all_paths"]["ci95_mean"] is None
        assert row["all_paths"]["standard_error"] is None
        assert row["valid_subset"]["count"]==0
    assert all(len(raw[c["case_id"]+"_volume_weighted_arrival_costs"])==10 for c in study["cases"])

def design():
    return {"schema_version":"1.0","base":config(quantity=100,duration=4,intervals=4,volatility=.01,impact=.001,trials=10).to_dict(),
        "profiles":["flat","front_loaded"],"risk_aversions":[0,.01],"impact_models":["constant","inverse_expected_volume"],
        "benchmark_volume_cases":["matched","shifted"],"shift_fraction":.25}

def test_small_study_has_three_strategies_and_two_benchmarks():
    result,raw=run_study(design())
    assert len(result["cases"])==8 and len(result["strategy_metrics"])==72
    assert len(result["paired_metrics"])==72
    assert all(c["valid_paths"]==10 for c in result["cases"])
    assert result["verification"]["all_accounting_reconciled"]
    assert result["verification"]["continuous_lower_bounds_respected"]
    assert set(r["benchmark"] for r in result["strategy_metrics"])=={"arrival","market_vwap"}

def test_design_budget_and_export_integrity(tmp_path):
    d=design();d["risk_aversions"]=[0,0]
    with pytest.raises(ValueError):validate_design(d)
    d=design();r,raw=run_study(d);dest=tmp_path/"out"
    export_study(r,raw,dest,figures=False)
    saved=json.loads((dest/"results.json").read_text(encoding="utf-8"))
    assert len(saved["cases"])==8
    with pytest.raises(FileExistsError):export_study(r,raw,dest,figures=False)
