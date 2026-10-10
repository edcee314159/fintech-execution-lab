"""Declarative study entry points and offline default inputs."""
from pathlib import Path

STUDIES = {
    "core": ("execution_lab", "Core TWAP / temporary-impact execution"),
    "sensitivity": ("execution_research.studies.sensitivity.sensitivity_study", "Cost-risk sensitivity"),
    "robustness": ("execution_research.studies.robustness.robustness_study", "Misspecified parameters"),
    "statistics": ("execution_research.studies.statistics.statistical_study", "Monte Carlo coverage and convergence"),
    "solver": ("execution_research.studies.solver.solver_benchmark", "Numerical accuracy and local runtime"),
    "historical": ("execution_research.studies.historical.historical_calibration", "ECB historical volatility calibration"),
    "volume": ("execution_research.studies.volume.volume_benchmark", "Synthetic volume and VWAP benchmarks"),
    "participation": ("execution_research.studies.participation.capacity_study", "Capacity feasibility and constrained optimization"),
}

def default_input(name):
    if name not in STUDIES:
        raise ValueError("unknown study: " + name)
    root = Path(__file__).resolve().parent
    return root / "inputs/default.json" if name == "core" else root / "studies" / name / "inputs/design.json"
