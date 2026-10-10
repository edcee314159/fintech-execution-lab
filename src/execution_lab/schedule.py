"""Continuous reference schedules and deterministic feasible integer approximations."""
import numpy as np
from .config import ExecutionConfig
from .types import Schedule
from .reference_solver import continuous_inventory

def integerize(quantities, quantity: int) -> np.ndarray:
    values = np.asarray(quantities, dtype=float)
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        raise ValueError("total quantity must be a positive integer")
    if values.ndim != 1 or not values.size or not np.isfinite(values).all() or np.any(values < 0):
        raise ValueError("quantities must be a finite nonnegative vector")
    if not np.isclose(values.sum(), quantity, rtol=1e-12, atol=1e-8):
        raise ValueError("quantities do not sum to the requested order")
    if np.max(values) > np.iinfo(np.int64).max:
        raise ValueError("quantity exceeds integer representation")
    result = np.floor(values).astype(np.int64)
    remainder = quantity - int(result.sum())
    if not 0 <= remainder <= values.size:
        raise ValueError("invalid rounding remainder")
    fractions = np.round(values - result, 12)
    order = np.lexsort((np.arange(values.size), -fractions))
    result[order[:remainder]] += 1
    return result

def validate_schedule(schedule: Schedule, config: ExecutionConfig) -> None:
    config.validate()
    n, x = schedule.quantities, schedule.inventory
    if n.shape != (config.intervals,) or x.shape != (config.intervals + 1,):
        raise ValueError("schedule dimensions differ from configuration")
    if not np.isfinite(n).all() or not np.isfinite(x).all():
        raise ValueError("schedule must be finite")
    if np.any(n < 0) or np.any(x < 0) or np.any(np.diff(x) > 1e-8):
        raise ValueError("schedule must have nonnegative trades and monotone inventory")
    if not np.isclose(n.sum(), config.quantity, rtol=1e-12, atol=1e-8):
        raise ValueError("schedule does not liquidate the order")
    if x[0] != config.quantity or x[-1] != 0:
        raise ValueError("inventory endpoints are incorrect")
    if not np.allclose(x[:-1] - x[1:], n, rtol=1e-12, atol=1e-8):
        raise ValueError("trades disagree with inventory changes")
    if schedule.integer and (np.any(n != np.floor(n)) or np.any(x != np.floor(x))):
        raise ValueError("integer schedule contains fractional shares")

def _schedule(strategy, quantities, config, integer):
    q = integerize(quantities, config.quantity) if integer else np.array(quantities, dtype=float)
    # Reverse cumulative sum avoids negative terminal roundoff.
    inventory = np.concatenate((np.cumsum(q[::-1])[::-1], [0]))
    inventory[0] = config.quantity
    result = Schedule(strategy, q, inventory, integer)
    validate_schedule(result, config)
    return result

def make_twap(config: ExecutionConfig, *, integer: bool = True) -> Schedule:
    config.validate()
    return _schedule("twap", np.full(config.intervals, config.quantity / config.intervals), config, integer)

def make_ac(config: ExecutionConfig, *, integer: bool = True) -> Schedule:
    config.validate()
    if config.risk_aversion == 0 or config.volatility == 0:
        quantities = np.full(config.intervals, config.quantity / config.intervals)
    else:
        quantities = -np.diff(continuous_inventory(config))
    return _schedule("ac_simplified", quantities, config, integer)
