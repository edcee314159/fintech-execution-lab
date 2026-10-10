import numpy as np
import pytest
from execution_lab.config import ExecutionConfig
from execution_lab.schedule import make_twap, make_ac, integerize, validate_schedule
from execution_lab.types import Schedule

def test_largest_remainder_ties_are_early():
    np.testing.assert_array_equal(integerize([3.4, 3.4, 3.2], 10), [4, 3, 3])

@pytest.mark.parametrize("n", [1, 10, 1000])
def test_small_orders_remain_feasible(n):
    c = ExecutionConfig.from_dict({"quantity": 1, "intervals": n, "trials": 2})
    for build in [make_twap, make_ac]:
        s = build(c)
        validate_schedule(s, c)
        assert s.quantities.sum() == 1
        assert s.inventory[0] == 1 and s.inventory[-1] == 0
        assert s.quantities.dtype == np.int64

def test_zero_risk_reduces_to_twap():
    c = ExecutionConfig.from_dict({"risk_aversion": 0})
    np.testing.assert_array_equal(make_ac(c).quantities, make_twap(c).quantities)
    np.testing.assert_allclose(make_ac(c, integer=False).quantities, np.full(60, 100000/60))

def test_single_interval():
    c = ExecutionConfig.from_dict({"quantity": 12, "intervals": 1})
    np.testing.assert_array_equal(make_ac(c).quantities, [12])

@pytest.mark.parametrize("q,total", [([1, -1], 0), ([2, 3], 10),
    ([float("inf")], 1), ([[1, 1]], 2), ([], 1)])
def test_invalid_integerization_rejected(q, total):
    with pytest.raises(ValueError):
        integerize(q, total)

def test_schedule_copies_and_rejects_infeasibility():
    quantities = np.array([5, 5])
    inventory = np.array([10, 5, 0])
    a = Schedule("twap", quantities, inventory, True)
    b = Schedule("ac_simplified", quantities, inventory, True)
    quantities[0] = 99
    inventory[1] = 99
    assert a.quantities[0] == b.quantities[0] == 5
    with pytest.raises(ValueError):
        a.quantities[0] = 4
    c = ExecutionConfig.from_dict({"quantity": 10, "intervals": 2})
    with pytest.raises(ValueError):
        validate_schedule(Schedule("bad", [5, 5], [10, 6, 0], True), c)
