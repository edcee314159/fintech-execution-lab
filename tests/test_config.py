import pytest
from execution_lab.config import ExecutionConfig

def test_defaults_and_small_order():
    c = ExecutionConfig()
    c.validate()
    assert c.tau == 1
    c = ExecutionConfig.from_dict({"quantity": 1, "intervals": 1000, "trials": 2})
    assert c.quantity == 1
    assert c.to_dict()["intervals"] == 1000

@pytest.mark.parametrize("data", [
    {"quantity": True}, {"duration": 0}, {"impact": 0}, {"volatility": float("nan")},
    {"price": float("inf")}, {"unknown": 1}, {"trials": 100000, "intervals": 1000},
    {"intervals": 1.5}, {"seed": -1}, {"risk_aversion": -1}, {"price": "100"},
])
def test_reject_invalid_before_allocation(data):
    with pytest.raises(ValueError):
        ExecutionConfig.from_dict(data)

def test_non_object_rejected():
    with pytest.raises(ValueError):
        ExecutionConfig.from_dict([])

@pytest.mark.parametrize('field', ['quantity', 'duration'])
def test_huge_integer_is_a_validation_error(field):
    with pytest.raises(ValueError):
        ExecutionConfig.from_dict({field: 10**400})
