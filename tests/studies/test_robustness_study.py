import json
import hashlib
import numpy as np
import pytest
from execution_research.studies.robustness.robustness_study import enumerate_cases, run_study, export_study

def design():
    return {"schema_version":"1.0","base_true":{"quantity":12,"duration":2,"intervals":2,"price":100,"volatility":1,"impact":0.5,"risk_aversion":1,"trials":100,"seed":17},
        "risk_aversions":[1],"sigma_ratios":[0.5,1,2],"impact_ratios":[0.5,1,2],
        "true_scenarios":[{"name":"baseline","changes":{}}],
        "supplemental_cases":[{"name":"cancel_high","scenario":"baseline","risk_aversion":1,"sigma_ratio":0.5,"impact_ratio":0.25}]}

def test_hand_solution_uses_true_parameters_for_outcome():
    result,raw=run_study(design())
    row=next(r for r in result["cases"] if r["sigma_ratio"]==0.5 and r["impact_ratio"]==1 and r["role"]=="main")
    # Estimated coefficient .5, not true coefficient 2: post-first-trade inventory=4.8.
    assert row["continuous"]["inventory"]==pytest.approx([12,4.8,0])
    assert row["continuous"]["true_prediction"]["mean"]==pytest.approx(37.44)
    assert row["continuous"]["true_prediction"]["variance"]==pytest.approx(23.04)
    assert row["continuous"]["forecast"]["variance"]==pytest.approx(5.76)
    anchor=result["anchors"][row["anchor_id"]]
    assert anchor["oracle_continuous"]["inventory"]==pytest.approx([12,3,0])
    assert row["continuous_regret"]==pytest.approx(6.48)
    assert row["integer"]["inventory"]==[12,5,0]
    assert row["integer"]["true_prediction"]["objective"]==pytest.approx(62)
    assert row["integer_gap_vs_rounded_oracle"]==pytest.approx(8)

def test_correct_estimates_and_cancelled_errors_preserve_policy():
    result,raw=run_study(design())
    correct=next(r for r in result["cases"] if r["sigma_ratio"]==r["impact_ratio"]==1)
    cancel=next(r for r in result["cases"] if r["role"]=="supplemental")
    assert correct["continuous_regret"]==pytest.approx(0,abs=1e-10)
    assert correct["integer_gap_vs_rounded_oracle"]==0
    assert cancel["integer"]["quantities"]==correct["integer"]["quantities"]
    assert cancel["integer"]["forecast"]["mean"]/cancel["integer"]["true_prediction"]["mean"]==pytest.approx(.25)
    assert cancel["integer"]["forecast"]["variance"]/cancel["integer"]["true_prediction"]["variance"]==pytest.approx(.25)
    assert result["verification"]["max_cancellation_normalized_difference"]<1e-12

def test_paired_uncertainty_and_raw_reconstruction():
    result,raw=run_study(design())
    for row in result["cases"]:
        anchor=result["anchors"][row["anchor_id"]]
        innovation=raw[anchor["market_key"]+"_innovations"]
        plan=row["integer"]
        expect=plan["true_prediction"]["mean"]-innovation@np.array(plan["inventory"][1:])
        np.testing.assert_allclose(raw[row["id"]+"_costs"],expect)
        delta=raw[row["id"]+"_costs"]-raw[anchor["id"]+"_oracle_costs"]
        assert row["paired_vs_oracle"]["empirical"]["mean"]==pytest.approx(delta.mean())
        assert row["paired_vs_oracle"]["empirical"]["variance"]==pytest.approx(delta.var(ddof=1))
        assert row["forecast_ratios"]["variance"]==pytest.approx(row["sigma_ratio"]**2)
        assert row["forecast_ratios"]["mean"]==pytest.approx(row["impact_ratio"])
    assert result["independent_base_paths"]==100
    assert len([k for k in raw if k.endswith("_innovations")])==1

def test_joint_invalid_masks_and_no_unconditional_inference():
    d=design();d["base_true"]["price"]=.01
    result,raw=run_study(d)
    assert result["verification"]["invalid_case_path_occurrences"]>0
    for row in result["cases"]:
        assert row["status"]=="invalid_model"
        assert row["paired_vs_oracle"]["all_paths"]["ci95_mean"] is None
        assert row["paired_vs_oracle"]["empirical"]["mean"] is None
        assert not raw[row["id"]+"_valid"].any()
        assert row["invalid_reasons"]

def test_design_refuses_confounding_duplicates_and_large_jobs():
    d=design();d["true_scenarios"].append({"name":"bad","changes":{"volatility":2,"impact":.2}})
    with pytest.raises(ValueError,match="one-factor"):
        enumerate_cases(d)
    d=design();d["sigma_ratios"]=[1,1]
    with pytest.raises(ValueError,match="unique"):
        enumerate_cases(d)
    d=design();d["impact_ratios"]=[0,1]
    with pytest.raises(ValueError,match="positive"):
        enumerate_cases(d)
    d=design();d["base_true"].update(trials=100000,intervals=19)
    d["true_scenarios"]=[{"name":str(i),"changes":{}} for i in range(10)]
    with pytest.raises(ValueError,match="study budget"):
        enumerate_cases(d)

def test_export_is_strict_and_preserves_raw_data(tmp_path):
    result,raw=run_study(design())
    dest=tmp_path/"study"
    export_study(result,raw,dest,figures=False)
    j=json.loads((dest/"results.json").read_text())
    assert len(j["cases"])==10
    manifest=json.loads((dest/"manifest.json").read_text())
    for name,digest in manifest["sha256"].items():
        assert hashlib.sha256((dest/name).read_bytes()).hexdigest()==digest
    arrays=np.load(dest/"raw-paths.npz",allow_pickle=False)
    for name,value in raw.items():
        np.testing.assert_array_equal(value,arrays[name])
    with pytest.raises(FileExistsError):
        export_study(result,raw,dest,figures=False)

def test_three_strategy_mask_rejects_paths_invalid_for_oracle_only():
    d=design();d["base_true"]["price"]=4
    result,raw=run_study(d)
    row=next(r for r in result["cases"] if r["sigma_ratio"]==0.5 and r["impact_ratio"]==1 and r["role"]=="main")
    anchor=result["anchors"][row["anchor_id"]]
    assert raw[row["id"]+"_estimated_pair_valid"].any()
    assert not raw[anchor["id"]+"_valid"].any()
    expected=raw[row["id"]+"_estimated_pair_valid"] & raw[anchor["id"]+"_valid"]
    np.testing.assert_array_equal(raw[row["id"]+"_valid"],expected)
    assert row["empirical"]["estimated_policy"]["empirical"]["mean"] is None
