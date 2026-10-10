import itertools,json
import numpy as np
import pytest
from execution_lab.config import ExecutionConfig
from execution_lab.schedule import make_ac,validate_schedule
from execution_research.studies.participation.participation import participation_limits,project_target,round_capped,make_capped_twap,make_capped_volume,solve_constrained
from execution_research.studies.participation.capacity_study import run_study,export_study

def config(**changes):
    return ExecutionConfig.from_dict(dict(quantity=12,duration=2,intervals=2,price=100,volatility=1,impact=1,risk_aversion=1,trials=10,seed=17)|changes)

def test_decimal_quota_and_rounding_only_shortage():
    r=participation_limits(config(quantity=58,intervals=1),[100],.58)
    assert r["caps"].tolist()==[58] and r["feasible"]
    r=participation_limits(config(quantity=3),[15,15],.1)
    assert r["raw_capacity_total"]==3 and r["integer_capacity_total"]==2
    assert not r["feasible"] and r["reason"]=="integer_rounding_shortage"
    assert r["shortfall_shares"]==1

def test_total_shortage_and_no_future_capacity_assumed():
    r=participation_limits(config(),[20,20],.1)
    assert r["reason"]=="continuous_capacity_shortage"
    assert r["integer_capacity_total"]==4 and r["shortfall_shares"]==8

@pytest.mark.parametrize("volumes,rate",[
    ([1],.1),([1,-1],.1),([1,float("nan")],.1),([1,float("inf")],.1),
    ([True,1],.1),([[1,2]],.1),([1,1],0),([1,1],1.01),([1,1],True),
    ([1,1],float("nan")),([1,1],float("inf"))])
def test_invalid_market_inputs(volumes,rate):
    with pytest.raises(ValueError):participation_limits(config(),volumes,rate)

def test_projection_redistributes_clipped_quantity():
    np.testing.assert_allclose(project_target([5,5],10,[2,10]),[2,8],atol=1e-12)
    assert np.minimum([5,5],[2,10]).sum()==7
    np.testing.assert_allclose(project_target([10/3]*3,10,[0,4,9]),[0,4,6],atol=1e-12)

def test_rounding_respects_caps_and_total_and_ties():
    q=round_capped([1.9,1.9,.2],4,[2,2,1])
    assert q.tolist()==[2,2,0]
    assert round_capped([1.5,1.5],3,[2,2]).tolist()==[2,1]
    assert round_capped([0,4,6],10,[0,4,9]).tolist()==[0,4,6]

@pytest.mark.parametrize("target,total,caps",[
    ([1,1],3,[2,2]),([1,-1],0,[2,2]),([1,1],2,[1,0]),
    ([1,1],2,[1.5,1]),([1,1],2,[True,1]),([1,1],True,[2,2])])
def test_invalid_projection_and_rounding(target,total,caps):
    with pytest.raises(ValueError):project_target(target,total,caps)
    with pytest.raises(ValueError):round_capped(target,total,caps)

def test_constrained_two_interval_hand_optimum():
    c=config();schedule,info=solve_constrained(c,[4,12])
    assert schedule.quantities.tolist()==[4,8]
    np.testing.assert_allclose(info["continuous_quantities"],[4,8],atol=1e-8)
    assert info["certificate"]["objective"]==pytest.approx(144)
    assert info["certificate"]["lower_bound"]<=144+1e-8
    assert info["certificate"]["gap"]<1e-5
    validate_schedule(schedule,c)

def test_loose_caps_recover_core_continuous_ac():
    c=config(quantity=1000,intervals=20,duration=20,impact=.001,risk_aversion=.0001)
    schedule,info=solve_constrained(c,np.full(20,1000))
    original=make_ac(c,integer=False)
    np.testing.assert_allclose(info["continuous_quantities"],original.quantities,rtol=1e-8,atol=1e-6)
    assert info["certificate"]["gap"]<1e-5

def test_singleton_feasible_set_and_zero_volume_slots():
    c=config(quantity=10)
    for schedule in (make_capped_twap(c,[3,7]),make_capped_volume(c,[1,2],[3,7]),solve_constrained(c,[3,7])[0]):
        assert schedule.quantities.tolist()==[3,7]
    c=config(quantity=10,intervals=3,duration=3,risk_aversion=0)
    schedule,info=solve_constrained(c,[0,4,9])
    assert schedule.quantities.tolist()==[0,4,6]
    assert info["certificate"]["gap"]<1e-6

def test_infeasible_optimization_rejected():
    with pytest.raises(ValueError):solve_constrained(config(),[5,6])

def test_small_integer_enumeration_brackets_certified_optimum():
    c=config(quantity=8,intervals=3,duration=3,impact=.2,risk_aversion=.1,volatility=.4)
    cap=np.array([2,4,5]);schedule,info=solve_constrained(c,cap)
    def cost(q):
        x=np.r_[np.cumsum(np.array(q)[::-1])[::-1],0]
        return c.impact/c.tau*np.dot(q,q)+c.risk_aversion*c.volatility**2*c.tau*np.dot(x[1:],x[1:])
    best=min(cost(q) for q in itertools.product(*(range(int(v)+1) for v in cap)) if sum(q)==c.quantity)
    assert info["certificate"]["lower_bound"]<=best+1e-8
    assert best<=cost(schedule.quantities)+1e-8

def design():
    return {"schema_version":"1.0","base":config(quantity=100,duration=4,intervals=4,volatility=.01,impact=.001,risk_aversion=.01).to_dict(),
        "profiles":["flat","u_shape"],"risk_aversions":[0,.01],
        "scenarios":[{"name":"short","market_volume":600,"participation_rate":.1},{"name":"feasible","market_volume":2000,"participation_rate":.1}]}

def test_study_distinguishes_infeasible_and_feasible_and_preserves_paths():
    study,raw=run_study(design())
    assert len(study["cases"])==8
    feasible=[c for c in study["cases"] if c["feasible"]]
    assert len(feasible)==4 and len(study["strategy_metrics"])==12 and len(study["paired_metrics"])==12
    for case in study["cases"]:
        if not case["feasible"]:assert case["strategies"]==[] and case["status"]=="capacity_infeasible"
    assert study["verification"]["all_accounting_reconciled"]
    assert study["verification"]["all_plans_respect_caps"]

def test_invalid_prices_suppress_inference_without_dropping_samples():
    d=design();d["base"].update(price=.001,impact=1)
    study,raw=run_study(d)
    for row in study["strategy_metrics"]+study["paired_metrics"]:
        assert row["all_paths"]["count"]==10
        assert row["all_paths"]["ci95_mean"] is None
        assert row["all_paths"]["standard_error"] is None
    assert study["verification"]["invalid_feasible_case_paths"]>0

def test_export_does_not_overwrite_and_design_validation(tmp_path):
    d=design();study,raw=run_study(d)
    export_study(study,raw,tmp_path/"out",figures=False)
    assert json.loads((tmp_path/"out/results.json").read_text(encoding="utf-8"))["cases"]
    with pytest.raises(FileExistsError):export_study(study,raw,tmp_path/"out",figures=False)
    d["scenarios"][1]["name"]="short"
    with pytest.raises(ValueError):run_study(d)

def test_kkt_polish_releases_a_falsely_active_zero_bound():
    c=config(quantity=29,intervals=8,duration=8,impact=.1,volatility=.3,risk_aversion=12,trials=2)
    schedule,info=solve_constrained(c,[29]*8)
    original=make_ac(c,integer=False)
    np.testing.assert_allclose(info["continuous_quantities"],original.quantities,rtol=1e-6,atol=1e-10)
    assert info["continuous_quantities"][-1]>0
    assert info["certificate"]["gap"]<1e-7
    validate_schedule(schedule,c)
