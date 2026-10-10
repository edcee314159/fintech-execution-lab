# Cost-risk sensitivity in a simplified execution model

## Research question

How do risk aversion, volatility and temporary impact change a fixed sell-order schedule, and what additional expected cost buys reduced execution risk?

## Prespecified design

Main conditions: 50; total distinct conditions including scaling checks: 52. Each uses 2,000 independent Gaussian paths. The same standardized draws are reused across conditions; these are not independent batches whose sample counts can be added.
The design is fixed in design.json. Main comparisons vary lambda within five scenarios, changing only volatility or temporary impact relative to baseline. The two extra scaling conditions test a mathematical implication rather than search for a better result.

## Model and timing

Trade n_k at the start of interval k, then hold inventory x_k. tau=T/N; x_0=Q and x_N=0. Arithmetic Brownian reference prices have zero drift, innovations sigma*sqrt(tau)*Z. Linear temporary impact is eta*n_k/tau; orders fill in full.
E[C]=(eta/tau)*sum(n_k^2); Var[C]=sigma^2*tau*sum(x_k^2), k=1,...,N. Minimize E[C]+lambda*Var[C]. Risk is cost variance; plotted standard deviation is its square root. Currency is an arbitrary consistent unit, not a calibrated GBP/HKD forecast.
The continuous minimizer is unique for positive eta. A finite lambda grid samples the continuous cost-risk frontier; it does not draw every efficient point. Integer schedules use deterministic largest-remainder rounding and are feasible approximations, with no claim of globally optimal integer allocation. Connecting lines guide the eye. Grid nondominance is only relative to sampled integer schedules in the same scenario.

## Baseline findings

At lambda=1e-05, integer TWAP expected cost is 1666.67, versus 1896.03 for the optimized-and-rounded schedule (13.76% higher).
Cost variance falls by 30.03%; standard deviation falls by 16.35%. The weighted objective falls by 8.70%. These are analytic model comparisons, not estimated real-market gains.
The schedule executes 38.85% of the order strictly before T/4.

| Scenario at the same lambda | Expected cost | Cost std | Executed before T/4 |
|---|---:|---:|---:|
| baseline | 1896.03 | 11081.05 | 38.85% |
| volatility_low | 1687.62 | 6287.32 | 29.13% |
| volatility_high | 3035.51 | 16721.74 | 59.49% |
| impact_low | 1140.86 | 9809.24 | 47.92% |
| impact_high | 3479.63 | 12001.83 | 32.76% |

Paired Monte Carlo AC-minus-TWAP mean: 280.9330809205188; marginal 95% mean interval: [165.57624993303145, 396.28991190800616]. Check its status and conditional/all-path labels in results.json before interpreting it.

## Mathematical scaling result

The continuous schedule depends on the dimensionless coefficient c=lambda*sigma^2*tau^2/eta. Holding c fixed while doubling sigma requires dividing lambda by four; doubling eta requires doubling lambda. Schedules coincide even though their cost and variance units change.
Checked coefficient values: [0.0009000000000000001, 0.0009000000000000001, 0.0009000000000000001]. Maximum normalized trade difference: 0; identical integer schedules: True.

## Validation and interpretation

Continuous cost increases and variance decreases along each lambda grid: True. All direct accounting reconciliations passed: True. Maximum relative integer objective gap: 8e-08.
Invalid pairs summed across correlated conditions: 0. This sum counts condition-path occurrences, not distinct independent paths.
Mean intervals use the core's Student-t method on independent paths within one condition; they are marginal intervals, with no simultaneous-coverage or multiple-testing claim. A confidence interval missing the analytic mean is possible under repeated sampling. Monte Carlo uncertainty is separate from misspecification, volatility-estimation or impact-estimation uncertainty.
No invalid path is clipped or resampled. Full masks and reasons are retained. Conditional summaries of surviving paths cannot support unconditional performance claims.
Higher lambda or sigma increases urgency; higher eta makes immediate trading more expensive and pushes allocation toward a flatter schedule. Compare financial outcomes only within a consistent scenario and objective. A larger lambda means a different preference, not a universally better strategy.

## Limits and reproducibility

Synthetic constant parameters, guaranteed fills, no spread/fees/permanent impact, no liquidity constraints, no market data calibration or alpha. This is an execution-model research artifact, not an investment recommendation or proof of superior returns.
results.json stores all configurations, continuous and integer schedules, analytic and empirical moments, invalid-path diagnostics and provenance. raw-paths.npz stores deduplicated reference prices, preserved innovations, integer costs and validity masks. Reconstruct execution prices as reference_price_before_trade - eta*n/tau, and costs as analytic_impact - innovations @ inventory[1:]. manifest.json hashes actual output bytes.
Provenance records core source digest, package/runtime versions, and this driver digest. Core source stays unchanged. Run the study twice into separate empty directories; compare numeric results and raw arrays while allowing creation timestamps to differ.

## Reference

[Almgren and Chriss (2001), Optimal execution of portfolio transactions](https://doi.org/10.21314/JOR.2001.041). This study implements a simplified discrete temporary-impact reference and does not reproduce every assumption of that paper.
