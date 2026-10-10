"""Shared contracts; fills stores execution prices, not fill quantities."""
from dataclasses import dataclass
import numpy as np
from .config import ExecutionConfig

@dataclass(frozen=True)
class Schedule:
    strategy: str
    quantities: np.ndarray
    inventory: np.ndarray
    integer: bool

    def __post_init__(self):
        for name in ("quantities", "inventory"):
            array = np.array(getattr(self, name), copy=True)
            array.flags.writeable = False
            object.__setattr__(self, name, array)

@dataclass
class Experiment:
    config: ExecutionConfig
    schedules: dict[str, Schedule]
    prices: np.ndarray
    fills: dict[str, np.ndarray]
    costs: dict[str, np.ndarray]
    valid_pairs: np.ndarray
    invalid_reasons: list[dict]
    price_innovations: np.ndarray | None = None
    accounting: dict | None = None
