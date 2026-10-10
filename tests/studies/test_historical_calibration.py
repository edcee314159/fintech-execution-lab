import json,math
from datetime import date,timedelta
import numpy as np
import pytest
from execution_research.studies.historical.historical_calibration import clean_rates, make_returns, fit_diffusion, forecast_rows, model_link, validate_design, export_study

def raw(rows):
    return ("Date,USD,GBP,HKD,\n"+"\n".join(rows)+"\n").encode()
def design():
    return {"schema_version":"1.0","data_start":"2021-12-01","data_end":"2025-12-31","training_start":"2022-01-01","training_end":"2023-12-31","evaluation_start":"2024-01-01","evaluation_end":"2025-12-31",
        "source":{"required_columns":["Date","USD","GBP","HKD"]},"assets":{"GBPUSD":{"numerator":"USD","denominator":"GBP","units":"USD per GBP"},"HKDUSD":{"numerator":"USD","denominator":"HKD","units":"USD per HKD"}},
        "rolling_windows":[2,3],"outlier_absolute_log_return_flag":.05,"min_training_returns":3,
        "calibration":{"normal_95_multiplier":1.959963984540054,"annual_calendar_minutes":525600,"benchmark_price":100},
        "base":{"quantity":100000,"duration":60,"intervals":60,"price":100,"volatility":.03,"impact":1e-5,"risk_aversion":1e-5,"trials":200,"seed":17}}

def test_clean_sort_cross_rates_and_reconcile_audit():
    data=raw(["2022-01-05,1.2,0.8,9.6,","2022-01-03,1.1,0.88,8.8,","2022-01-04,N/A,0.8,9.6,","2022-01-03,1.1,0.88,8.8,","2022-01-06,-1,0.8,9.6,","2026-01-01,1.2,0.8,9.6,"])
    rates,audit=clean_rates(data,design())
    assert [x["date"] for x in rates]==["2022-01-03","2022-01-05"]
    assert rates[0]["GBPUSD"]==pytest.approx(1.25)
    assert rates[0]["HKDUSD"]==pytest.approx(.125)
    assert audit["input_rows"]==audit["kept_rows"]+audit["duplicate_rows"]+audit["dropped_rows"]+audit["outside_range_rows"]
    assert audit["duplicate_rows"]==1 and audit["dropped_rows"]==2
    assert not audit["forward_filled"]

def test_conflicting_duplicate_and_invalid_schema_fail_loudly():
    with pytest.raises(ValueError,match="conflicting duplicate"):
        clean_rates(raw(["2022-01-03,1.1,0.8,9.6,","2022-01-03,1.2,0.8,9.6,"]),design())
    with pytest.raises(ValueError,match="required"):
        clean_rates(b"Date,USD\n2022-01-03,1.1\n",design())

def test_calendar_gap_and_extreme_return_are_retained():
    rates,_=clean_rates(raw(["2022-01-07,1,1,8,","2022-01-10,2,1,8,"]),design())
    returns=make_returns(rates,"GBPUSD",.05)
    assert returns[0]["elapsed_minutes"]==4320
    assert returns[0]["log_return"]==pytest.approx(math.log(2))
    assert returns[0]["extreme_flag"] is True and len(returns)==1

def test_weighted_diffusion_has_hand_computable_solution():
    # log returns [1,-1], elapsed [1,3]: mu=0, residual norm=1+1/3; df=1.
    r=fit_diffusion([1.,-1.],[1.,3.])
    assert r["drift_per_minute"]==0
    assert r["variance_per_minute"]==pytest.approx(4/3)
    assert r["sigma_per_sqrt_minute"]==pytest.approx(math.sqrt(4/3))
    fixed=fit_diffusion([1.,-1.],[2.,2.])
    assert fixed["variance_per_minute"]==pytest.approx(1)

def test_undersized_nonfinite_and_nonpositive_durations_rejected():
    for returns,durations in [([1],[1]),([1,2],[1,0]),([1,float("nan")],[1,1]),([1,2],[1])]:
        with pytest.raises(ValueError):fit_diffusion(returns,durations)

def histories():
    dates=[date(2023,12,25)+timedelta(days=i) for i in range(12)]
    return [{"start_date":a.isoformat(),"end_date":b.isoformat(),"elapsed_minutes":1440.,
        "log_return":float((i%3-1)*.01),"extreme_flag":False} for i,(a,b) in enumerate(zip(dates[:-1],dates[1:]))]

def test_rolling_forecasts_do_not_change_when_future_returns_change():
    d=design();original=histories();a=forecast_rows(original,d)
    changed=[dict(x) for x in original];changed[-1]["log_return"]=2.;b=forecast_rows(changed,d)
    # The final target can change the realized error, never any fitted mean/variance.
    for x,y in zip(a,b,strict=True):
        assert x["forecast_variance"]==y["forecast_variance"]
        assert x["forecast_mean"]==y["forecast_mean"]
        assert x["fit_last_date"]<=x["start_date"]<x["end_date"]
    target=next(x for x in a if x["method"]=="rolling_2")
    assert target["fit_sample_count"]==2

def test_static_fit_is_frozen_and_period_split_is_strict():
    d=design();a=forecast_rows(histories(),d)
    rows=[r for r in a if r["method"]=="static_training"]
    assert rows and len({r["sigma_per_sqrt_minute"] for r in rows})==1
    assert all(r["fit_last_date"]<=d["training_end"] and r["end_date"]>=d["evaluation_start"] for r in rows)
    bad=design();bad["evaluation_start"]=bad["training_end"]
    with pytest.raises(ValueError,match="overlap"):validate_design(bad)

def test_normalized_model_link_preserves_liquidation_and_common_evaluation():
    d=design();fit=fit_diffusion([.01,-.01,.005],[1440.,1440.,4320.])
    rows,arrays=model_link("GBPUSD",fit,fit,d)
    assert len(rows)==3
    for row in rows:
        x=arrays[row["array_key"]]
        assert x[0]==100000 and x[-1]==0 and np.all(np.diff(x)<=0)
        assert row["evaluation_config"]["volatility"]==pytest.approx(100*fit["sigma_per_sqrt_minute"])
        assert row["instrument_scope"]=="synthetic_100_price_normalized_exposure"
    calibrated=next(x for x in rows if x["policy"]=="calibrated_calendar")
    assumed=next(x for x in rows if x["policy"]=="original_assumption")
    assert calibrated["common_evaluation"]["objective"]<=assumed["common_evaluation"]["objective"]+1e-8

def test_export_is_strict_and_refuses_overwrite(tmp_path):
    study={"schema_version":"1.0","rates":[],"returns":[],"forecasts":[],"forecast_summary":[],"model_link":[],"verification":{"passed":True}}
    export_study(study,{},tmp_path/"out",figures=False)
    saved=json.loads((tmp_path/"out/results.json").read_text())
    assert saved["verification"]["passed"]
    with pytest.raises(FileExistsError):export_study(study,{},tmp_path/"out",figures=False)
