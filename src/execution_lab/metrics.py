"""Analytic moments and Monte Carlo uncertainty for actual schedules."""
import numpy as np
from scipy.stats import t
from .config import ExecutionConfig
from .types import Experiment, Schedule
from .schedule import validate_schedule

def predictions(config: ExecutionConfig, schedule: Schedule) -> dict:
    validate_schedule(schedule, config)
    mean = float(config.impact / config.tau * np.dot(schedule.quantities, schedule.quantities))
    variance = float(config.volatility**2 * config.tau * np.dot(schedule.inventory[1:], schedule.inventory[1:]))
    return {"mean": mean, "variance": variance, "std": float(np.sqrt(variance)),
        "objective": mean + config.risk_aversion * variance,
        "quantity_mode": "integer_approximation" if schedule.integer else "continuous_reference"}

def _stats(values, label, *, inferential=True):
    count = int(values.size)
    result = {"label": label, "count": count, "mean": None, "variance": None,
        "std": None, "standard_error": None, "ci95_mean": None}
    if count < 2:
        return result
    mean = float(np.mean(values))
    variance = float(np.var(values, ddof=1))
    result.update(mean=mean, variance=variance, std=float(np.sqrt(variance)))
    if inferential:
        se = float(np.sqrt(variance / count))
        radius = float(t.ppf(.975, count - 1)) * se if variance else 0.0
        result.update(standard_error=se, ci95_mean=[mean-radius, mean+radius])
    return result

def summarize(experiment: Experiment) -> dict:
    c, e = experiment.config, experiment
    valid = int(np.count_nonzero(e.valid_pairs))
    invalid = c.trials - valid
    status = "valid" if not invalid else ("invalid_model" if valid == 0 else "partially_invalid")
    all_label = "all_model_paths" if not invalid else "outside_model_algebraic_diagnostics"
    selected_label = "all_model_paths" if not invalid else "conditional_selected_valid_paths"
    strategies = {}
    for name, schedule in e.schedules.items():
        strategies[name] = {
            "prediction": predictions(c, schedule),
            "empirical": _stats(e.costs[name][e.valid_pairs], selected_label),
            "all_paths": _stats(e.costs[name], all_label, inferential=not invalid),
        }
    delta = e.costs["ac_simplified"] - e.costs["twap"]
    exposure_delta = e.schedules["ac_simplified"].inventory[1:] - e.schedules["twap"].inventory[1:]
    variance = float(c.volatility**2 * c.tau * np.dot(exposure_delta, exposure_delta))
    paired = {
        "direction": "ac_simplified_minus_twap",
        "prediction": {"mean": strategies["ac_simplified"]["prediction"]["mean"] -
            strategies["twap"]["prediction"]["mean"], "variance": variance},
        "empirical": _stats(delta[e.valid_pairs], selected_label),
        "all_paths": _stats(delta, all_label, inferential=not invalid),
    }
    return {"status": status, "total_pairs": c.trials, "valid_pairs": valid,
        "invalid_pairs": invalid, "confidence_level": .95, "strategies": strategies,
        "paired": paired, "interpretation": (
            "The continuous reference optimizes mean cost plus weighted variance; integer schedules are feasible approximations. "
            "Front-loading can increase expected impact cost while reducing exposure risk. "
            "Synthetic results do not establish real-market performance. "
            + ("Invalid paths are preserved; conditional estimates cannot establish unconditional superiority." if invalid else
               "Intervals quantify Monte Carlo mean uncertainty, not real-world forecast uncertainty."))}
