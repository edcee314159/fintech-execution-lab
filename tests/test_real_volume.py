import importlib.util
from datetime import date, datetime, timedelta
from pathlib import Path
import csv
import numpy as np
import pytest


def api():
    assert importlib.util.find_spec("execution_volume_validation") is not None, "real-volume validation package has not been implemented"
    from execution_volume_validation import data, forecasting, replay
    return data, forecasting, replay


def fixture_csv(path, days=1, drop=None, duplicate=False, conflict=False, bad=None):
    rows=[]
    for d in range(days):
        start=datetime(2026,9,21+d,9,30)
        for k in range(390):
            row=[(start+timedelta(minutes=k)).strftime("%Y-%m-%d %H:%M:%S"),100,101,99,100,10]
            if k==drop: continue
            if k==bad: row[5]="1.5"
            rows.append(row)
    if duplicate: rows.append(list(rows[0]))
    if conflict:
        row=list(rows[0]);row[-1]=11;rows.append(row)
    rows.append(["2026-09-21 08:00:00",100,101,99,100,5])
    with path.open("w",newline="") as f:csv.writer(f).writerows(rows)
    return path


def test_package_exists(): api()


def test_session_aggregation_and_exact_duplicate(tmp_path):
    data,_,_=api()
    days,audit=data.load_sessions(fixture_csv(tmp_path/"x.csv",duplicate=True),"TEST")
    assert len(days)==1 and days[0].volume.shape==(78,)
    assert days[0].volume.tolist()==[50]*78
    assert days[0].open_price==100 and days[0].close.tolist()==[100]*78
    assert audit["exact_duplicates"]==1 and audit["outside_session_rows"]==1
    assert audit["excluded_sessions"]==[]


@pytest.mark.parametrize("options,reason",[({"drop":10},"incomplete_session"),({"conflict":True},"conflicting_duplicate"),({"bad":10},"invalid_ohlcv")])
def test_incomplete_invalid_conflicting_sessions_are_excluded(tmp_path,options,reason):
    data,_,_=api()
    days,audit=data.load_sessions(fixture_csv(tmp_path/"x.csv",**options),"TEST")
    assert days==[] and reason in audit["excluded_sessions"][0]["reasons"]


def test_invalid_ohlc_and_nonfinite_are_excluded(tmp_path):
    data,_,_=api();p=fixture_csv(tmp_path/"x.csv")
    t=p.read_text().replace(",100,101,99,100,10",",100,nan,99,100,10",1);p.write_text(t)
    days,audit=data.load_sessions(p,"TEST")
    assert not days and "invalid_ohlcv" in audit["excluded_sessions"][0]["reasons"]


def test_forecast_past_only_and_equal_normalized_weights(tmp_path):
    data,forecasting,_=api()
    days,_=data.load_sessions(fixture_csv(tmp_path/"x.csv",days=5),"TEST")
    from dataclasses import replace
    a=np.arange(1,79,dtype=np.int64)
    days=[replace(d,volume=(a if k%2 else a[::-1])*(k+1)) for k,d in enumerate(days)]
    f=forecasting.predict(days,date(2026,9,28),"historical_shape",5)
    expected=np.mean([d.volume/d.volume.sum() for d in days],axis=0)*np.mean([d.volume.sum() for d in days])
    np.testing.assert_allclose(f.volume,expected)
    assert f.train_dates==tuple(d.day.isoformat() for d in days)
    with pytest.raises(ValueError,match="past"):
        forecasting.predict(days,days[-1].day,"historical_shape",5)
    with pytest.raises(ValueError,match="five|5|history"):
        forecasting.predict(days[:4],date(2026,9,28),"historical_shape",5)


def test_predictor_totals_and_same_order_sizing(tmp_path):
    data,forecasting,_=api();days,_=data.load_sessions(fixture_csv(tmp_path/"x.csv",days=5),"TEST")
    fs=[forecasting.predict(days,date(2026,9,28),name,5) for name in forecasting.PREDICTORS]
    assert len(fs)==3 and len({forecasting.order_quantity(f.adv,.05) for f in fs})==1
    assert fs[-1].volume.tolist()==days[-1].volume.tolist()
    assert forecasting.order_quantity(1001,.01)==10


def test_replay_uses_floor_carries_backlog_and_never_borrows():
    _,_,replay=api()
    r=replay.replay_schedule(np.array([1,1,8]),np.array([99,1,100]),.1)
    assert r["caps"].tolist()==[9,0,10]
    assert r["fills"].tolist()==[1,0,9]
    assert r["residual"]==0 and r["completion_fraction"]==1
    assert np.all(np.cumsum(r["fills"])<=np.cumsum([1,1,8]))
    r=replay.replay_schedule(np.array([0,10]),np.array([100,0]),.1)
    assert r["fills"].tolist()==[0,0] and r["residual"]==10
    assert r["maximum_capacity_fill"]==10 and r["avoidable_residual"]==10


@pytest.mark.parametrize("q,v,rho",[([1,-1],[10,10],.1),([1.5,2],[10,10],.1),([1,2],[10],.1),([1,2],[10,10],True),([1,2],[10,-1],.1)])
def test_replay_rejects_invalid_inputs(q,v,rho):
    _,_,replay=api()
    with pytest.raises(ValueError):replay.replay_schedule(q,v,rho)


def test_residual_mark_accounting_is_not_full_execution():
    _,_,replay=api()
    d=replay.price_diagnostic(10,100,np.array([2,3]),np.array([99.,98.]),1.,5.)
    assert d["residual_shares"]==5 and d["completed"] is False
    assert d["executed_price_shortfall"]==8 and d["residual_mark_shortfall"]==10
    assert d["assumed_impact"]==pytest.approx(2.6)
    assert d["marked_total_shortfall"]==pytest.approx(20.6)


def test_no_trades_and_zero_forecast_history(tmp_path):
    data,forecasting,replay=api();days,_=data.load_sessions(fixture_csv(tmp_path/"x.csv",days=5),"TEST")
    from dataclasses import replace
    zeros=[replace(d,volume=np.zeros(78,dtype=np.int64)) for d in days]
    with pytest.raises(ValueError,match="positive"):
        forecasting.predict(zeros,date(2026,9,28),"historical_shape",5)
    r=replay.replay_schedule(np.array([2,3]),np.array([0,0]),.1)
    assert r["residual"]==5 and r["caps"].sum()==0


def synthetic_inputs(tmp_path):
    import hashlib
    p=fixture_csv(tmp_path/"TEST_1min.csv",days=8)
    dates=["2026-09-21","2026-09-22","2026-09-23","2026-09-24","2026-09-25","2026-09-28"]
    design={"symbols":["TEST"],"expected_dates":dates,"lookback":5,"fractions":[.01,.05,.09],"participation_rate":.1,"impact":1e-5,"risk_aversion":1e-5,
            "sources":{"TEST":{"csv_member":p.name,"csv_sha256":hashlib.sha256(p.read_bytes()).hexdigest()}}}
    return p,design


def test_integrated_study_and_public_arrays(tmp_path):
    api()
    from execution_volume_validation.study import run_study
    _,design=synthetic_inputs(tmp_path)
    result,private,public=run_study(tmp_path,design)
    assert len(result["forecasts"])==3 and len(result["records"])==27
    assert result["evaluation_calendar_dates"]==["2026-09-28"]
    assert all(r["planning_feasible"] and r["replay"]["complete"] for r in result["records"])
    assert all(max(r["train_dates"])<r["date"] for r in result["records"])
    assert all(key.endswith(("_planned", "_fills", "_remaining")) for key in public)
    assert len(public)==81 and len(private)>len(public)
    assert all(s["common_complete_dates"]==["2026-09-28"] for s in result["comparisons"])
    assert all(f["scores"]["interval_wape"]==0 for f in result["forecasts"])


def test_changed_inputs_fail_closed(tmp_path):
    api()
    from execution_volume_validation.study import run_study
    p,design=synthetic_inputs(tmp_path);p.write_text(p.read_text()+"\n")
    with pytest.raises(ValueError,match="hash"):
        run_study(tmp_path,design)


def test_absent_expected_day_cannot_be_zero_filled(tmp_path):
    api()
    from execution_volume_validation.study import run_study
    _,design=synthetic_inputs(tmp_path);design["expected_dates"].append("2026-09-29")
    with pytest.raises(ValueError,match="missing|absent|eligible"):
        run_study(tmp_path,design)


def test_current_day_does_not_change_plan(tmp_path):
    api()
    import hashlib
    from execution_volume_validation.study import run_study
    p,design=synthetic_inputs(tmp_path);a,_,pa=run_study(tmp_path,design)
    t=p.read_text();t=t.replace("2026-09-28", "2026-09-28")
    lines=[]
    for line in t.splitlines():
        if line.startswith("2026-09-28"):
            fields=line.split(",");fields[-1]="1";line=",".join(fields)
        lines.append(line)
    p.write_text("\n".join(lines)+"\n");design["sources"]["TEST"]["csv_sha256"]=hashlib.sha256(p.read_bytes()).hexdigest()
    b,_,pb=run_study(tmp_path,design)
    assert [r["quantity"] for r in a["records"]]==[r["quantity"] for r in b["records"]]
    for key in pa:
        if key.endswith("_planned"):np.testing.assert_array_equal(pa[key],pb[key])
    assert all(not r["replay"]["complete"] for r in b["records"])


def test_planning_infeasible_has_no_fake_cost_or_schedule(tmp_path):
    api()
    from execution_volume_validation.study import run_study
    _,design=synthetic_inputs(tmp_path);design["fractions"]=[.2]
    result,private,public=run_study(tmp_path,design)
    assert len(result["records"])==9 and not public
    assert all(not r["planning_feasible"] and r["price_diagnostic"] is None and r["replay"] is None for r in result["records"])
    assert all(not s["common_complete_dates"] for s in result["comparisons"])


def test_report_cli_produces_figures_and_honest_sample_counts(tmp_path,monkeypatch):
    import json
    from execution_volume_validation.cli import main
    _,design=synthetic_inputs(tmp_path)
    spec=tmp_path/"design.json";spec.write_text(json.dumps(design))
    output=tmp_path/"output"
    monkeypatch.setattr("sys.argv",["execution-volume-validate","run","--input-dir",str(tmp_path),"--design",str(spec),"--output",str(output)])
    main()
    assert len(list((output/"figures").glob("*.png")))==5
    english=(output/"research-note.md").read_text(encoding="utf-8")
    chinese=(output/"中文研究解读.md").read_text(encoding="utf-8")
    assert "1 evaluation date" in english and "1 个评估日期" in chinese
    assert "27" in english and "AI-assisted" in english
    assert "2 selected instruments" not in english and "five evaluation dates" not in english
    for name in ("results.json","derived-schedules.npz","manifest.json"):
        assert (output/name).is_file()


def test_save_preserves_existing_research_output(tmp_path):
    from execution_volume_validation.study import save_study
    output=tmp_path/"existing";output.mkdir();sentinel=output/"results.json";sentinel.write_text("original study")
    with pytest.raises(ValueError,match="empty|exist"):
        save_study({"design":{}},{},{},output)
    assert sentinel.read_text()=="original study"


@pytest.mark.parametrize("acquired", ["2024-02-03", None])
def test_report_uses_recorded_acquisition_and_actual_preparation_date(tmp_path, acquired):
    import json
    from datetime import date as calendar_date
    from execution_volume_validation.study import run_study
    from execution_volume_validation.reporting import write_report
    _, design = synthetic_inputs(tmp_path)
    if acquired is not None:
        design["source_access_date"] = acquired
    result, private, public = run_study(tmp_path, design)
    output = tmp_path/"report"
    write_report(result, private, public, output)
    english = (output/"research-note.md").read_text(encoding="utf-8")
    chinese = (output/"中文研究解读.md").read_text(encoding="utf-8")
    assert f"Raw data accessed {acquired or 'not recorded'}" in english
    assert f"report prepared {calendar_date.today().isoformat()}" in english
    assert (acquired or "未记录") in chinese
    provenance = json.loads((output/"report-provenance.json").read_text())
    assert provenance["source_access_date"] == acquired
    assert provenance["report_prepared_date"] == calendar_date.today().isoformat()


def test_sparse_design_cannot_skip_an_eligible_interior_session(tmp_path):
    from execution_volume_validation.study import run_study
    _, design = synthetic_inputs(tmp_path)
    design["expected_dates"].remove("2026-09-23")
    design["lookback"] = 4
    with pytest.raises(ValueError, match="interior|omitted|consecutive"):
        run_study(tmp_path, design)
