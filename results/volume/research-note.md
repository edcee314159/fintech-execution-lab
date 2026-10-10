# Forecast-volume execution and market-VWAP benchmarking

## Research question and implementation

Add a third schedule q_k = Q*vhat_k, where vhat is an expected, normalized market-volume curve fixed before execution. Compare it with TWAP and an arrival-objective optimizer under five synthetic volume profiles and two impact assumptions. These are static VWAP-style trajectories, not implementations of a broker's live algorithm.

VWAP is price weighted by traded volume; a trading trajectory and an ex-post price benchmark are separate objects. [IBKR VWAP definition](https://www.interactivebrokers.com/campus/glossary-terms/volume-weighted-average-price-vwap/). The industry algorithm has additional execution controls and fill uncertainty that this experiment omits. [IBKR algorithm documentation](https://www.interactivebrokers.com/docs/general/order-types/algorithmic-orders/ib-algorithms/vwap).

The original core source and its two-strategy run_paired interface remain unchanged. The extension consumes its immutable Schedule contract, validation, largest-remainder integerization, original AC/TWAP and tridiagonal solver. A separate three-schedule adapter uses the same preserved exogenous price innovations.

## Fixed design and model assumptions

30 conditions: 5 forecast profiles × 3 risk preferences × 2 impact assumptions. Each uses the same 2000 IID Gaussian innovation paths, N=60 intervals over 60 minutes. Price randomness is reused across all schedules and cases; import/setup does not alter the seeded generator. Every plan must sell Q=100000 shares.

Profiles are flat, U-shaped, front-loaded, back-loaded and midday-peaked. They are deterministic synthetic inputs, not empirical stock-volume estimates. Relative weights do not specify total market volume or capacity.

Constant impact: a_k=eta/tau, exactly the existing financial model.
Secondary assumed liquidity relation: a_k=eta/(tau*N*vhat_k). Volume-heavy intervals have smaller temporary-impact coefficients. This relation is introduced as an assumption, not a calibrated fact. It equals the original coefficient for flat volume.

The optimizer is appropriate to each arrival-cost objective. Constant impact uses the original AC schedule. The secondary model uses a separate variable-coefficient arrival optimizer. It does not optimize VWAP-tracking variance. A generalized optimizer's continuous interior system has diagonal a_(k-1)+a_k+b, adjacent entries -a_k, b=lambda*sigma²*tau, and first RHS a_0*Q. Symmetric positive-definite structure permits the reused tridiagonal solve.

At lambda=0 the continuous cost optimum allocates inversely to a_k: uniform for constant impact, proportional to forecast volume for the assumed inverse-volume coefficient. At positive risk preference, front-loading balances impact cost against exposure. Integerized schedules are feasible approximations; retain the continuous objective as a lower bound, not a guarantee of global integer optimality.

## Two price benchmarks, three evaluation groups

Use interval-start external reference prices P_k, excluding the agent's own impacted executions. Market VWAP = sum(v_realized_k*P_k). It is a model proxy rather than transaction-by-transaction traded VWAP.

Arrival shortfall for a sell = Q*P_0 - proceeds.
Market-VWAP shortfall = Q*VWAP_market - proceeds.
Positive values mean less sale proceeds than the specified benchmark.

Let x_post be remaining inventory after each trade, and u_post remaining normalized realized volume after each interval. With preserved price increments eps:
arrival cost = sum(a*q²) - eps@x_post;
market-VWAP cost = sum(a*q²) - eps@(x_post-Q*u_post).
Expected shortfall equals deterministic impact under either benchmark. Variance is sigma²*tau times the squared norm of the corresponding exposure vector. Mean-plus-lambda-variance is evaluated separately for each benchmark; an arrival optimizer need not optimize the VWAP objective.

Evaluation groups: arrival price, matched forecast/realized market-VWAP weights, and realized weights circularly shifted by 15 bins. Only the evaluation benchmark changes in the mismatch experiment. The planned quantities and the preset liquidity coefficients remain fixed. It is a tracking-error stress test, not an endogenous liquidity shock or complete stochastic volume-forecast model.

Exact matching continuous quantities cancel external VWAP price noise under the deterministic matched-volume assumption. Integer rounding leaves a small residual. This does not cancel arrival-price risk or guarantee equal realized market volumes.

## Actual analytic results at lambda=1e-05

Costs and standard deviations are in model currency. All plans shown are integerized.

| Profile | Impact assumption | Plan | Expected arrival cost | Arrival SD | Mean + λ variance | First-quarter sold |
|---|---|---|---:|---:|---:|---:|
| flat | constant | TWAP | 1666.67 | 13247.38 | 3421.60 | 25.00% |
| flat | constant | Forecast-volume | 1666.67 | 13247.38 | 3421.60 | 25.00% |
| flat | constant | AC (arrival) | 1896.03 | 11081.05 | 3123.93 | 38.85% |
| flat | inverse_expected_volume | TWAP | 1666.67 | 13247.38 | 3421.60 | 25.00% |
| flat | inverse_expected_volume | Forecast-volume | 1666.67 | 13247.38 | 3421.60 | 25.00% |
| flat | inverse_expected_volume | AC (volume-aware arrival) | 1896.03 | 11081.05 | 3123.93 | 38.85% |
| u_shape | constant | TWAP | 1666.67 | 13247.38 | 3421.60 | 25.00% |
| u_shape | constant | Forecast-volume | 2101.63 | 12583.23 | 3685.00 | 35.72% |
| u_shape | constant | AC (arrival) | 1896.03 | 11081.05 | 3123.93 | 38.85% |
| u_shape | inverse_expected_volume | TWAP | 2152.76 | 13247.38 | 3907.69 | 25.00% |
| u_shape | inverse_expected_volume | Forecast-volume | 1666.67 | 12583.23 | 3250.04 | 35.72% |
| u_shape | inverse_expected_volume | AC (volume-aware arrival) | 1932.69 | 9683.89 | 2870.47 | 52.84% |
| front_loaded | constant | TWAP | 1666.67 | 13247.38 | 3421.60 | 25.00% |
| front_loaded | constant | Forecast-volume | 1979.19 | 10870.21 | 3160.80 | 39.06% |
| front_loaded | constant | AC (arrival) | 1896.03 | 11081.05 | 3123.93 | 38.85% |
| front_loaded | inverse_expected_volume | TWAP | 2161.07 | 13247.38 | 3916.00 | 25.00% |
| front_loaded | inverse_expected_volume | Forecast-volume | 1666.67 | 10870.21 | 2848.28 | 39.06% |
| front_loaded | inverse_expected_volume | AC (volume-aware arrival) | 1807.42 | 9295.48 | 2671.48 | 51.46% |
| back_loaded | constant | TWAP | 1666.67 | 13247.38 | 3421.60 | 25.00% |
| back_loaded | constant | Forecast-volume | 1978.96 | 15909.54 | 4510.09 | 10.94% |
| back_loaded | constant | AC (arrival) | 1896.03 | 11081.05 | 3123.93 | 38.85% |
| back_loaded | inverse_expected_volume | TWAP | 2162.09 | 13247.38 | 3917.02 | 25.00% |
| back_loaded | inverse_expected_volume | Forecast-volume | 1666.67 | 15909.54 | 4197.80 | 10.94% |
| back_loaded | inverse_expected_volume | AC (volume-aware arrival) | 1941.55 | 13828.01 | 3853.69 | 20.85% |
| midday_peak | constant | TWAP | 1666.67 | 13247.38 | 3421.60 | 25.00% |
| midday_peak | constant | Forecast-volume | 2305.81 | 14240.18 | 4333.64 | 11.46% |
| midday_peak | constant | AC (arrival) | 1896.03 | 11081.05 | 3123.93 | 38.85% |
| midday_peak | inverse_expected_volume | TWAP | 2564.05 | 13247.38 | 4318.98 | 25.00% |
| midday_peak | inverse_expected_volume | Forecast-volume | 1666.67 | 14240.18 | 3694.50 | 11.46% |
| midday_peak | inverse_expected_volume | AC (volume-aware arrival) | 1824.06 | 12988.73 | 3511.13 | 19.35% |

## A measured example

For the U-shaped profile at the default risk weight, the volume plan's expected impact cost exceeds TWAP by 434.96 under constant impact. Under the separately assumed inverse-volume coefficients it is lower by 486.09. This change follows the explicit liquidity model, rather than a universal advantage of volume scheduling.

The same volume plan has arrival SD 12583.23, matched-VWAP tracking SD 0.131737, and shifted-VWAP tracking SD 3608.65. Near-zero matched tracking risk relies on the deterministic exact-volume assumption.

## Tracking versus arrival risk

| Profile | Impact assumption | Arrival SD | Matched-VWAP SD | Shifted-VWAP SD |
|---|---|---:|---:|---:|
| flat | constant | 13247.38 | 1.789413 | 1.79 |
| u_shape | constant | 12583.23 | 0.131737 | 3608.65 |
| front_loaded | constant | 10870.21 | 0.565288 | 3775.25 |
| back_loaded | constant | 15909.54 | 0.661627 | 3774.15 |
| midday_peak | constant | 14240.18 | 0.168234 | 4490.45 |
| flat | inverse_expected_volume | 13247.38 | 1.789413 | 1.79 |
| u_shape | inverse_expected_volume | 12583.23 | 0.131737 | 3608.65 |
| front_loaded | inverse_expected_volume | 10870.21 | 0.565288 | 3775.25 |
| back_loaded | inverse_expected_volume | 15909.54 | 0.661627 | 3774.15 |
| midday_peak | inverse_expected_volume | 14240.18 | 0.168234 | 4490.45 |

## Monte Carlo validation and paired inference

Export 270 strategy records and 270 paired comparisons, with every cost sample and schedule retained in paths-and-schedules.npz. Compare cost to direct notional-minus-proceeds accounting under a conservative floating-point bound. Invalid case-path count: 0; raw paths and common validity masks are preserved.

All three strategies use the same price innovations and a common mask requiring positive reference and execution prices. If any path is invalid, retain descriptive all-path and valid-subset statistics but suppress inferential intervals, avoiding conditional-selection superiority claims.

For valid experiments, Student-t 95% intervals quantify Monte Carlo uncertainty in mean shortfall and paired MEAN differences. They do not quantify uncertainty in calibrated parameters, actual execution performance, or the risk-weighted objective. No multiple-comparison family-wide significance claim is made.

For any pair, the common market-VWAP term cancels. Analytic paired variance is sigma²*tau*||x_A-x_B||² for all benchmark groups. Arrival and VWAP targets can change each strategy's individual risk while leaving the paired shortfall difference unchanged. This provides a useful accounting identity and illustrates why benchmark choice matters.

## Reproducibility and limits

Fixed design, shared market innovations, all trajectories, impact coefficients, continuous lower bounds, empirical moments, paired intervals and source/runtime digests are retained. Repeat the same design numerically; independently reconstruct proceeds, benchmark exposures, statistics and weighted linear-system solutions.

Eighteen automated cases include hand-worked weights/optima, safe normalization, invalid volume input, exact flat-profile TWAP identity, original-AC agreement, risk-neutral inverse-volume allocation, direct accounting, external-volume benchmark separation and common invalid masks.

There is no order book, partial filling, participation cap, fee/spread model, endogenous price-volume dependence, real volume-forecast learning or live execution. The extra impact relation is an explicit secondary model. Numerical evidence supports understanding of benchmarking and model assumptions, not a claim of real-market superiority.
