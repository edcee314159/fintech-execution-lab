import hashlib
import json
import numpy as np
import pytest
from execution_research.studies.sensitivity.sensitivity_study import enumerate_cases, run_study, export_study

def small_design():
    return {"schema_version":"1.0", "base":{"quantity":12,"duration":2,"intervals":2,"price":100,"volatility":1,"impact":1,"risk_aversion":1,"trials":100,"seed":17},
        "risk_aversions":[0,1,4], "scenarios":[{"name":"baseline","changes":{}}],
        "scaling_cases":[{"name":"scaling_baseline","changes":{}},{"name":"sigma_twice","changes":{"volatility":2,"risk_aversion":0.25}},{"name":"eta_half","changes":{"impact":0.5,"risk_aversion":0.5}}]}

def test_hand_solvable_two_intervals_and_frontier():
    study, raw = run_study(small_design())
    main = [r for r in study["cases"] if r["role"]=="main"]
    for row, x, cost, var in zip(main,[6,4,2],[72,80,104],[36,16,4]):
        assert row["continuous"]["ac"]["inventory"] == pytest.approx([12,x,0])
        assert row["continuous"]["ac"]["prediction"]["mean"] == pytest.approx(cost)
        assert row["continuous"]["ac"]["prediction"]["variance"] == pytest.approx(var)
        assert row["checks"]["continuous_optimal_vs_twap"]
    assert study["scaling_check"]["max_normalized_quantity_difference"] < 1e-12
    assert study["verification"]["continuous_monotonicity"]
    assert len(study["cases"]) == 5
    assert study["independent_base_paths"] == 100
    assert len([k for k in raw if k.endswith("_innovations")]) == 2

def test_common_random_numbers_cost_reconstruction_and_timing():
    study, raw = run_study(small_design())
    for row in study["cases"]:
        market = raw[row["market_key"]+"_innovations"]
        for strategy, core_name in [("ac","ac_simplified"),("twap","twap")]:
            schedule = row["integer"][strategy]
            reconstructed = schedule["prediction"]["mean"]-market@np.array(schedule["inventory"][1:])
            np.testing.assert_allclose(raw[row["id"]+"_"+core_name+"_costs"], reconstructed)
        assert row["integer"]["ac"]["fraction_before_quarter"] == pytest.approx(row["integer"]["ac"]["quantities"][0]/12)
    first, second = [raw[k] for k in raw if k.endswith("_innovations")]
    np.testing.assert_allclose(second, first*2)

def test_design_rejects_confounding_duplicates_and_excess_work():
    d=small_design()
    d["scenarios"].append({"name":"confounded","changes":{"volatility":2,"impact":2}})
    with pytest.raises(ValueError,match="one-factor"):
        enumerate_cases(d)
    d=small_design(); d["risk_aversions"]=[0,0]
    with pytest.raises(ValueError,match="unique"):
        enumerate_cases(d)
    d=small_design(); d["base"]["trials"]=100000; d["base"]["intervals"]=19
    d["scenarios"]=[{"name":str(i),"changes":{}} for i in range(20)]
    with pytest.raises(ValueError,match="study budget"):
        enumerate_cases(d)

def test_invalid_paths_retained_without_unconditional_inference():
    d=small_design(); d["base"]["price"]=0.01
    study,raw=run_study(d)
    assert study["verification"]["invalid_pairs_across_conditions"] > 0
    for row in study["cases"]:
        assert not row["summary"]["status"]=="valid"
        assert row["summary"]["paired"]["all_paths"]["ci95_mean"] is None
        assert len(raw[row["id"]+"_valid"])==100

def test_export_hashes_and_refuse_overwrite(tmp_path):
    study,raw=run_study(small_design())
    target=tmp_path/"results"
    export_study(study,raw,target,figures=False)
    manifest=json.loads((target/"manifest.json").read_text())
    for name,digest in manifest["sha256"].items():
        assert hashlib.sha256((target/name).read_bytes()).hexdigest()==digest
    restored=np.load(target/"raw-paths.npz",allow_pickle=False)
    for name,array in raw.items():
        np.testing.assert_array_equal(restored[name],array)
    with pytest.raises(FileExistsError):
        export_study(study,raw,target,figures=False)
