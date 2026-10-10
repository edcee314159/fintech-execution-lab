import numpy as np
import matplotlib.pyplot as plt
import pytest
from execution_lab.config import ExecutionConfig
from execution_lab.schedule import make_twap, make_ac
from execution_lab.simulation import run_paired
from execution_lab.metrics import summarize
from execution_lab.export import build_bundle
from execution_lab.plotting import render_figures

@pytest.mark.parametrize("intervals,vertices", [
    (1, [[0,12],[0,0],[2,0]]),
    (2, [[0,12],[0,6],[1,6],[1,0],[2,0]]),
])
def test_reference_inventory_uses_start_of_interval_trade_timing(tmp_path, monkeypatch, intervals, vertices):
    c = ExecutionConfig.from_dict(dict(quantity=12,duration=2,intervals=intervals,
        price=1000,impact=1,volatility=1,risk_aversion=1,trials=2))
    e = run_paired(c,{"twap":make_twap(c),"ac_simplified":make_ac(c)})
    closed = []
    original_close = plt.close
    def record_real_figure_then_close(figure=None):
        if hasattr(figure,"axes"):
            closed.append(figure)
        original_close(figure)
    monkeypatch.setattr(plt,"close",record_real_figure_then_close)
    render_figures(build_bundle(e,summarize(e)),tmp_path)
    reference_line = next(line for line in closed[0].axes[1].lines if line.get_linestyle()=="--")
    # Inspect the actual rendered line geometry, not a mocked plotting call.
    np.testing.assert_array_equal(reference_line.get_path().vertices,vertices)
