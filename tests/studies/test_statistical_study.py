import json
import hashlib
import numpy as np
import pytest
from execution_research.studies.statistics.statistical_study import validate_design, gaussian_stats, exact_binomial_interval, run_study, export_study

def design():
    return {"schema_version":"1.0","base":{"quantity":12,"duration":2,"intervals":2,"price":100,"volatility":1,"impact":.5,"risk_aversion":1,"trials":40,"seed":17},
        "sample_sizes":[10,20,40],"seeds":[17,23,29,31,37],"confidence_level":.95}

def test_mean_variance_intervals_hand_case():
    s=gaussian_stats(np.array([1.,2.,3.]),truth={"mean":2.,"variance":1.},confidence=.95)
    assert s["mean"]==2
    assert s["variance"]==1
    assert s["standard_error"]==pytest.approx(1/np.sqrt(3))
    assert s["ci_mean"]==pytest.approx([-.4841377117,4.4841377117])
    assert s["ci_variance"]==pytest.approx([.2710850307,39.4978902052])
    assert s["mean_covered"] and s["variance_covered"]

def test_binomial_interval_handles_zero_all_and_small_counts():
    assert exact_binomial_interval(0,100,.95)==pytest.approx([0,1-.025**.01])
    assert exact_binomial_interval(100,100,.95)==pytest.approx([.025**.01,1])
    assert exact_binomial_interval(0,0,.95) is None

def test_analytic_hand_model_and_prefix_statistics():
    result,raw=run_study(design())
    assert result["theory"]["twap"]["mean"]==pytest.approx(36)
    assert result["theory"]["twap"]["variance"]==pytest.approx(36)
    assert result["theory"]["ac"]["mean"]==pytest.approx(45)
    assert result["theory"]["ac"]["variance"]==pytest.approx(9)
    assert result["theory"]["paired"]["mean"]==pytest.approx(9)
    assert result["theory"]["paired"]["variance"]==pytest.approx(9)
    assert result["pairing"]["independent_over_paired_variance"]==pytest.approx(5)
    for row in result["batches"]:
        values=raw["ac_costs"][row["replicate_index"],:row["sample_size"]]
        assert row["channels"]["ac"]["mean"]==pytest.approx(values.mean())
        assert row["channels"]["ac"]["variance"]==pytest.approx(values.var(ddof=1))
    assert result["unique_market_paths"]==200
    assert len(result["batches"])==15

def test_complete_seed_retention_and_reproducibility():
    d=design();a,x=run_study(d);b,y=run_study(d)
    assert [r["seed"] for r in a["replicates"]]==d["seeds"]
    assert len(a["aggregates"])==9
    for key in x:np.testing.assert_array_equal(x[key],y[key])
    for r in a["replicates"]:
        assert r["invalid_paths"]==0
        assert r["accounting_reconciled"]
    assert a["batches"]==b["batches"]

def test_invalid_paths_disable_nominal_coverage_claims():
    d=design();d["base"]["price"]=.01
    result,raw=run_study(d)
    assert result["verification"]["invalid_path_occurrences"]==200
    for row in result["batches"]:
        assert not row["eligible_for_nominal_coverage"]
        assert row["channels"]["ac"]["ci_mean"] is None
        assert row["channels"]["ac"]["ci_variance"] is None
    for aggregate in result["aggregates"]:
        assert aggregate["status"]=="selection_affected"
        assert aggregate["mean_coverage"] is None
        assert aggregate["variance_coverage"] is None

def test_degenerate_paired_distribution():
    d=design();d["base"]["risk_aversion"]=0
    result,raw=run_study(d)
    assert result["pairing"]["independent_over_paired_variance"] is None
    for row in result["batches"]:
        p=row["channels"]["paired"]
        assert p["ci_mean"]==[0,0]
        assert p["ci_variance"]==[0,0]
        assert p["mean_covered"] and p["variance_covered"]

def test_design_budget_and_duplicates():
    d=design();d["seeds"]=[17,17]
    with pytest.raises(ValueError,match="unique"):validate_design(d)
    d=design();d["sample_sizes"]=[10,10,40]
    with pytest.raises(ValueError,match="unique"):validate_design(d)
    d=design();d["sample_sizes"]=[1,40]
    with pytest.raises(ValueError,match="at least two"):validate_design(d)
    d=design();d["base"].update(intervals=19,trials=100000);d["sample_sizes"]=[100,100000];d["seeds"]=list(range(100))
    with pytest.raises(ValueError,match="study budget"):validate_design(d)

def test_strict_export_hashes_and_no_overwrite(tmp_path):
    result,raw=run_study(design());dest=tmp_path/"study"
    export_study(result,raw,dest,figures=False)
    restored=np.load(dest/"raw-costs.npz",allow_pickle=False)
    for k,v in raw.items():np.testing.assert_array_equal(v,restored[k])
    manifest=json.loads((dest/"manifest.json").read_text())
    for name,digest in manifest["sha256"].items():
        assert hashlib.sha256((dest/name).read_bytes()).hexdigest()==digest
    with pytest.raises(FileExistsError):export_study(result,raw,dest,figures=False)

def test_selection_affected_aggregate_does_not_keep_only_good_batches():
    from execution_research.studies.statistics.statistical_study import aggregate_batches
    truth={k:{"mean":2.,"variance":1.} for k in ("twap","ac","paired")}
    rows=[]
    for eligible in (True,False):
        channels={k:gaussian_stats(np.arange(10,dtype=float),truth=truth[k],confidence=.95,inferential=eligible) for k in truth}
        rows.append({"sample_size":10,"eligible_for_nominal_coverage":eligible,"channels":channels})
    aggregates,slopes=aggregate_batches(rows,truth,[10],.95)
    for row in aggregates:
        assert row["replicates"]==2 and row["eligible_replicates"]==1
        assert row["status"]=="selection_affected"
        assert row["mean_coverage"] is None
        assert row["mean_coverage_interval"] is None
    assert all(v is None for v in slopes.values())
