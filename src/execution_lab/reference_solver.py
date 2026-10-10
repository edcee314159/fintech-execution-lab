"""Thomas elimination for the discrete continuous-quantity reference."""
import numpy as np
from .config import ExecutionConfig

def solve_tridiagonal(lower, diagonal, upper, rhs) -> np.ndarray:
    a, b, c, d = (np.array(v, dtype=float, copy=True) for v in (lower, diagonal, upper, rhs))
    n = b.size
    if n < 1 or any(v.ndim != 1 for v in (a, b, c, d)):
        raise ValueError("tridiagonal vectors must be nonempty one-dimensional arrays")
    if a.size != n - 1 or c.size != n - 1 or d.size != n:
        raise ValueError("incompatible tridiagonal dimensions")
    if not all(np.isfinite(v).all() for v in (a, b, c, d)):
        raise ValueError("tridiagonal vectors must be finite")
    with np.errstate(over="raise", divide="raise", invalid="raise"):
        try:
            for i in range(1, n):
                if b[i - 1] == 0:
                    raise ValueError("zero elimination pivot; pivoting is not supported")
                factor = a[i - 1] / b[i - 1]
                b[i] -= factor * c[i - 1]
                d[i] -= factor * d[i - 1]
            x = np.empty(n)
            if b[-1] == 0:
                raise ValueError("zero elimination pivot; pivoting is not supported")
            x[-1] = d[-1] / b[-1]
            for i in range(n - 2, -1, -1):
                if b[i] == 0:
                    raise ValueError("zero elimination pivot")
                x[i] = (d[i] - c[i] * x[i + 1]) / b[i]
        except FloatingPointError as error:
            raise ValueError("numerically invalid tridiagonal system") from error
    if not np.isfinite(x).all():
        raise ValueError("nonfinite solution")
    return x

def continuous_inventory(config: ExecutionConfig) -> np.ndarray:
    config.validate()
    n, q = config.intervals, config.quantity
    if n == 1:
        return np.array([q, 0.0])
    coefficient = config.risk_aversion * config.volatility**2 * config.tau**2 / config.impact
    if coefficient == 0:
        return np.linspace(q, 0, n + 1)
    rhs = np.zeros(n - 1)
    rhs[0] = q
    interior = solve_tridiagonal(-np.ones(n - 2),
        np.full(n - 1, 2 + coefficient), -np.ones(n - 2), rhs)
    return np.concatenate(([q], interior, [0.0]))
