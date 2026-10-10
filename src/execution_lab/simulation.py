"""Paired exogenous price paths; numerically stable shortfall accounting."""
import numpy as np
from .config import ExecutionConfig
from .types import Experiment, Schedule
from .schedule import validate_schedule

def _market(config):
    config.validate()
    rng = np.random.default_rng(config.seed)
    increments = config.volatility * np.sqrt(config.tau) * rng.standard_normal(
        (config.trials, config.intervals))
    prices = np.empty((config.trials, config.intervals + 1))
    prices[:, 0] = config.price
    prices[:, 1:] = config.price + np.cumsum(increments, axis=1)
    return prices, increments

def generate_prices(config: ExecutionConfig) -> np.ndarray:
    return _market(config)[0]

def run_paired(config: ExecutionConfig, schedules: dict[str, Schedule]) -> Experiment:
    config.validate()
    if set(schedules) != {"twap", "ac_simplified"}:
        raise ValueError("provide exactly twap and ac_simplified schedules")
    for name, schedule in schedules.items():
        if name != schedule.strategy:
            raise ValueError("strategy key disagrees with schedule")
        validate_schedule(schedule, config)
    prices, increments = _market(config)
    fills, costs = {}, {}
    reference_bad = np.any(prices <= 0, axis=1)
    valid_pairs = ~reference_bad
    execution_bad = {}
    accounting = {"method": "temporary_impact_minus_inventory_times_preserved_innovations",
        "reconciliation": "direct notional-minus-proceeds checked with a conservative floating-point roundoff bound",
        "strategies": {}}
    eps = np.finfo(float).eps
    gamma = config.intervals * eps / (1 - config.intervals * eps)
    for name, schedule in schedules.items():
        fills[name] = prices[:, :-1] - config.impact * schedule.quantities / config.tau
        impact = config.impact / config.tau * np.dot(schedule.quantities, schedule.quantities)
        costs[name] = impact - increments @ schedule.inventory[1:]
        direct = config.quantity * config.price - fills[name] @ schedule.quantities
        residual = np.abs(costs[name] - direct)
        tolerance = 8 * gamma * (abs(config.quantity * config.price) +
            np.abs(fills[name]) @ schedule.quantities)
        reconciled = bool(np.all(residual <= tolerance))
        if not reconciled:
            raise ValueError("cost/proceeds accounting exceeds the floating-point roundoff bound")
        accounting["strategies"][name] = {
            "max_absolute_proceeds_residual_currency": float(residual.max()),
            "max_roundoff_bound_currency": float(tolerance.max()),
            "reconciled_within_roundoff": reconciled}
        execution_bad[name] = np.any(fills[name] <= 0, axis=1)
        valid_pairs &= ~execution_bad[name]
    diagnostics = []
    for index in np.flatnonzero(~valid_pairs):
        reasons = []
        if reference_bad[index]:
            reasons.append("nonpositive_reference_price")
        failing = [name for name in schedules if execution_bad[name][index]]
        if failing:
            reasons.append("nonpositive_execution_price")
        diagnostics.append({
            "pair_index": int(index), "reasons": reasons,
            "affected_strategies": failing,
            "minimum_reference_price": float(prices[index].min()),
            "minimum_execution_price": {name: float(fills[name][index].min()) for name in schedules},
        })
    return Experiment(config, dict(schedules), prices, fills, costs, valid_pairs, diagnostics,
        price_innovations=increments, accounting=accounting)
