"""Units: shares, minutes and currency per share."""
from dataclasses import asdict, dataclass, fields
import math
from numbers import Real

@dataclass(frozen=True)
class ExecutionConfig:
    quantity: int = 100000
    duration: float = 60.0
    intervals: int = 60
    price: float = 100.0
    volatility: float = 0.03
    impact: float = 0.00001
    risk_aversion: float = 0.00001
    trials: int = 200
    seed: int = 20261009

    @property
    def tau(self) -> float:
        return self.duration / self.intervals

    @classmethod
    def from_dict(cls, data: dict) -> "ExecutionConfig":
        if not isinstance(data, dict):
            raise ValueError("configuration must be a JSON object")
        unknown = set(data) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError("unknown configuration fields: " + ", ".join(sorted(unknown)))
        config = cls(**data)
        config.validate()
        return config

    def to_dict(self) -> dict:
        return asdict(self)

    def validate(self) -> None:
        limits = {
            "quantity": (1, 10_000_000), "duration": (0.001, 10_000),
            "intervals": (1, 1000), "price": (0.001, 1_000_000),
            "volatility": (0, 100), "impact": (1e-12, 1),
            "risk_aversion": (0, 10_000), "trials": (2, 100_000),
            "seed": (0, 2**32 - 1),
        }
        integers = {"quantity", "intervals", "trials", "seed"}
        for name, (low, high) in limits.items():
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, Real):
                raise ValueError(f"{name} must be numeric (booleans are not accepted)")
            if name in integers and not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
            if not low <= value <= high or not math.isfinite(value):
                raise ValueError(f"{name} must be finite and between {low} and {high}")
        if self.trials * (self.intervals + 1) > 2_000_000:
            raise ValueError("workload exceeds 2,000,000 price cells")
        derived = (
            self.impact / self.tau,
            self.volatility**2 * self.tau,
            self.risk_aversion * self.volatility**2 * self.tau**2 / self.impact,
        )
        if not all(math.isfinite(v) for v in derived):
            raise ValueError("derived model coefficients must be finite")
