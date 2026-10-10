import numpy as np
import pytest
from scipy.optimize import minimize
from execution_lab.config import ExecutionConfig
from execution_lab.reference_solver import solve_tridiagonal, continuous_inventory
from execution_lab.schedule import make_ac

def test_hand_linear_system():
    np.testing.assert_allclose(solve_tridiagonal([-1], [3, 3], [-1], [12, 0]), [4.5, 1.5])

def test_hand_inventory_and_objective():
    c = ExecutionConfig.from_dict(dict(quantity=12, duration=2, intervals=2,
        impact=1, volatility=1, risk_aversion=1))
    np.testing.assert_allclose(continuous_inventory(c), [12, 4, 0])
    s = make_ac(c, integer=False)
    assert sum(s.quantities**2) == pytest.approx(80)
    assert sum(s.inventory[1:]**2) == pytest.approx(16)
    assert sum(s.quantities**2) + sum(s.inventory[1:]**2) == pytest.approx(96)
    assert 6**2 + 6**2 + 6**2 == 108

@pytest.mark.parametrize("args", [
    ([], [0], [], [1]), ([], [1, 1], [], [1, 1]),
    ([], [float("nan")], [], [1]), ([1], [1, 1], [1], [1, 1]),
    ([], [[1]], [], [1]),
])
def test_bad_system_rejected(args):
    with pytest.raises(ValueError):
        solve_tridiagonal(*args)

@pytest.mark.parametrize("n", [2, 3, 10])
@pytest.mark.parametrize("coefficient", [0, 1, 10])
def test_independent_constrained_optimizer(n, coefficient):
    # Direct normalized objective; an off-diagonal/sign/scaling error is caught here.
    c = ExecutionConfig.from_dict(dict(quantity=12, duration=n, intervals=n,
        impact=1, volatility=1, risk_aversion=coefficient))
    def objective(w):
        exposure = 1 - np.cumsum(w)
        return np.dot(w, w) + coefficient * np.dot(exposure, exposure)
    result = minimize(objective, np.full(n, 1 / n), method="SLSQP",
        bounds=[(0, 1)] * n, constraints={"type": "eq", "fun": lambda w: sum(w) - 1},
        options={"ftol": 1e-13, "maxiter": 1000})
    assert result.success, result.message
    assert abs(sum(result.x) - 1) < 1e-9
    assert min(result.x) >= -1e-10
    weights = make_ac(c, integer=False).quantities / c.quantity
    np.testing.assert_allclose(weights, result.x, atol=1e-6, rtol=0)
    assert objective(weights) == pytest.approx(result.fun, rel=1e-8)
