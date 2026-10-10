# Model and derivation

This is a discrete reference model inspired by Almgren–Chriss, not a complete implementation of their original model. All orders are sales and every planned trade fills. Time is measured in minutes, inventory in shares, and price in currency/share.

At time t_(k-1), sell n_k = x_(k-1) - x_k. Hold x_k over the next interval of length tau = T/N; x_0 = Q and x_N = 0. The reference price follows S_k = S_(k-1) + sigma sqrt(tau) Z_k with independent standard-normal Z_k, zero drift and no permanent impact. Execution price is S_(k-1) - eta n_k/tau. There are no fees, spread, queueing or liquidity restrictions.

Implementation shortfall in currency:
C = Q S_0 - sum(n_k P_exec,k)
  = (eta/tau) sum(n_k^2) - sum(x_k (S_k - S_(k-1)).

Consequently E[C] = (eta/tau) sum(n_k^2), Var(C) = sigma^2 tau sum(x_k^2).
The objective is J = E[C] + lambda Var(C).
sigma has units currency/share/sqrt(minute); eta has units currency*minute/share^2; lambda has units 1/currency.

Differentiate J over interior inventory. Dividing by 2 eta/tau gives:
(2+c) x_j - x_(j-1) - x_(j+1) = 0,
c = lambda sigma^2 tau^2/eta.
The first right-hand-side is Q; the rest is zero. The matrix is positive definite for c>=0. Thomas forward elimination and back substitution take O(N) time and O(N) storage. The public generic solver does not pivot and rejects zero elimination pivots.

For Q=12, T=N=2, eta=sigma=lambda=1, the continuous solution is inventory [12,4,0] and trades [8,4]. E[C]=80, lambda Var(C)=16, J=96. TWAP [6,6] has J=108. Zero risk aversion or volatility gives uniform continuous trades.

Largest-remainder integerization floors each trade and distributes remaining shares by decreasing fractional part, with earlier intervals breaking ties (fractions rounded to 12 decimals). It preserves quantity and nonnegativity. It is a feasible approximation, not a claim to solve the integer optimization globally. All reported model predictions are recomputed for the actual integer schedule.

Shared price paths pair the two strategies. If either strategy has a nonpositive execution price, or any reference price is nonpositive, the whole path pair is flagged. Draws and costs remain available, without clipping, replacements or concealed exclusions. All-path algebraic summaries are labelled outside the model when such paths occur; conditional summaries of valid paths are selected samples.

Student-t 95% confidence intervals refer to Monte Carlo estimates of means, not single-path prediction intervals. A zero sample variance yields a point interval. Fewer than two valid pairs yields null inferential summaries. Synthetic experiments do not establish real-market performance or parameter calibration.

## Sources

Almgren and Chriss, [Optimal execution of portfolio transactions](https://doi.org/10.21314/JOR.2001.041). Only the temporary-impact, zero-drift mean–variance idea is used here; permanent impact and other features of the original model are omitted.

Independent optimizer: [SciPy SLSQP](https://docs.scipy.org/doc/scipy/reference/optimize.minimize-slsqp.html). Mean-interval quantiles: [SciPy Student-t](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.t.html).

## Numerical accounting

The cost/exposure identity is evaluated using the preserved raw Gaussian price innovations, rather than subtracting two large notionals. Rounded price levels may lose innovations smaller than their floating-point precision. The result bundle therefore includes price_innovations and accounting diagnostics. Notional-minus-proceeds is separately reconciled using a conservative bound proportional to machine epsilon, interval count and gross notional/proceeds. At Q=10,000,000, T=10,000, N=1,000, price=1,000,000, eta=1e-12 and zero volatility, the stable cost is 0.01. This handles numerical precision without changing the financial model, clipping paths or introducing new randomness.
