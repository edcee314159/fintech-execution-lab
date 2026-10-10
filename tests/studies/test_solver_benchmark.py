import hashlib,json
import numpy as np
import pytest
from execution_lab.config import ExecutionConfig
from execution_research.studies.solver.solver_benchmark import closed_form_inventory, build_system, solve_prepared, solve_inventory, evaluate_accuracy, run_study, export_study, validate_design

def design():
    return {"schema_version":"1.0","base":{"quantity":12,"duration":2,"intervals":2,"price":100,"volatility":1,"impact":1,"risk_aversion":1,"trials":10,"seed":17},
        "benchmark_intervals":[2,4],"accuracy_intervals":[1,2,4],"accuracy_risk_aversions":[0,1],
        "accuracy_extra_cases":[],
        "timing":{"repeats":3,"warmup_calls":1,"min_batch_seconds":.001,"max_loops":128,"order_seed":17,"requested_blas_threads":1},
        "acceptance":{"normalized_inventory_max_error":1e-8,"relative_objective_error":1e-8,"normalized_backward_error":1e-10}}

def test_two_interval_hand_solution_and_objective():
    c=ExecutionConfig.from_dict(design()["base"])
    assert closed_form_inventory(c)==pytest.approx([12,4,0])
    for method in ("thomas","scipy_banded","scipy_dense_spd"):
        assert solve_inventory(c,method)==pytest.approx([12,4,0])
        record,arrays=evaluate_accuracy(c,method)
        assert record["expected_cost"]==pytest.approx(80)
        assert record["variance"]==pytest.approx(16)
        assert record["objective"]==pytest.approx(96)
        assert record["passed"]

def test_banded_storage_and_inputs_are_preserved():
    c=ExecutionConfig.from_dict(design()["base"]|{"intervals":4})
    system=build_system(c)
    dense=system["dense"];band=system["band"]
    for i in range(3):
        for j in range(3):
            if abs(i-j)<=1:assert band[1+i-j,j]==dense[i,j]
    snapshot={k:v.copy() for k,v in system.items() if isinstance(v,np.ndarray)}
    for method in ("thomas","scipy_banded","scipy_dense_spd"):
        solve_prepared(system,method)
    for k,v in snapshot.items():np.testing.assert_array_equal(v,system[k])

def test_single_interval_and_zero_risk_fast_paths():
    for changes,expected in [({"intervals":1},[12,0]),({"risk_aversion":0},[12,6,0]),({"volatility":0},[12,6,0])]:
        c=ExecutionConfig.from_dict(design()["base"]|changes)
        for method in ("thomas","scipy_banded","scipy_dense_spd"):
            assert solve_inventory(c,method)==pytest.approx(expected)
            record,_=evaluate_accuracy(c,method)
            assert record["passed"]

def test_closed_form_extreme_coefficients_remain_finite():
    for changes in [{"intervals":1000,"risk_aversion":1e-10},{"intervals":1000,"risk_aversion":10000,"impact":1e-12}]:
        c=ExecutionConfig.from_dict(design()["base"]|changes)
        x=closed_form_inventory(c)
        assert np.isfinite(x).all() and np.all(np.diff(x)<=0)
        for method in ("thomas","scipy_banded","scipy_dense_spd"):
            record,_=evaluate_accuracy(c,method)
            assert record["passed"]

def test_storage_counts_are_input_storage_not_peak_memory():
    c=ExecutionConfig.from_dict(design()["base"]|{"intervals":4})
    s=build_system(c)
    assert s["matrix_storage"]["thomas"]==56
    assert s["matrix_storage"]["scipy_banded"]==72
    assert s["matrix_storage"]["scipy_dense_spd"]==72
    assert s["rhs"].nbytes==24

def test_timing_retains_all_repeats_and_scopes():
    result,raw=run_study(design())
    assert len(result["timings"])==14
    assert len(result["accuracy"])==18
    for row in result["timings"]:
        assert len(row["seconds_per_call"])==3
        assert row["loops"]>=1
        assert all(v>0 for v in row["seconds_per_call"])
        assert row["median_seconds"]==pytest.approx(np.median(row["seconds_per_call"]))
    assert {r["scope"] for r in result["timings"]}=={"prepared_system","inventory_end_to_end","product_integer_schedule"}
    assert result["verification"]["all_accuracy_cases_passed"]

def test_design_validation_rejects_invalid_sizes_and_excess_budgets():
    d=design();d["benchmark_intervals"]=[1,4]
    with pytest.raises(ValueError,match="at least two"):validate_design(d)
    d=design();d["benchmark_intervals"]=[2,2]
    with pytest.raises(ValueError,match="unique"):validate_design(d)
    d=design();d["timing"]["repeats"]=100000
    with pytest.raises(ValueError,match="timing budget"):validate_design(d)

def test_strict_exports_and_no_overwrite(tmp_path):
    result,raw=run_study(design());dest=tmp_path/"study"
    export_study(result,raw,dest,figures=False)
    manifest=json.loads((dest/"manifest.json").read_text())
    for name,digest in manifest["sha256"].items():
        assert hashlib.sha256((dest/name).read_bytes()).hexdigest()==digest
    saved=np.load(dest/"solutions.npz",allow_pickle=False)
    for k,v in raw.items():np.testing.assert_array_equal(v,saved[k])
    with pytest.raises(FileExistsError):export_study(result,raw,dest,figures=False)
