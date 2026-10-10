# Execution-policy robustness under parameter misspecification

## Research question

If a trader estimates volatility or temporary market impact incorrectly, how much does the resulting fixed execution schedule lose when evaluated under the true model, and how misleading are its forecasts?

## Prespecified design

135 main conditions and 2 supplemental cancellation checks; 15 cached true-parameter oracle/TWAP anchors. Each condition uses 2,000 independent Gaussian paths. One bank of standardized draws is reused across correlated conditions, not added up as independent samples.
Five true market scenarios change only true volatility or impact relative to baseline. Three fixed risk preferences and a 3x3 grid of volatility/impact estimate-to-truth ratios are specified before execution. Supplemental ratios are labelled off-grid. No parameters are estimated from historical observations: these are controlled misspecification experiments.
Risk preference lambda is treated as known. Quantity, horizon, interval timing and price-path specification are held fixed. Estimate-to-truth ratios describe a hindsight error, not information a real trader necessarily knows.

## Policy construction and true evaluation

Construct a continuous optimizer from estimated sigma and eta, then derive a feasible integer approximation with the core's deterministic rounding. Evaluate both plans using true sigma and eta. The true-parameter continuous oracle is the model lower bound; its integerized plan is only a rounded reference, not a globally optimal integer solution.
Trade at interval starts. With tau=T/N, E_true[C]=(eta_true/tau)*sum(n_k^2), Var_true[C]=sigma_true^2*tau*sum(x_k^2), k=1,...,N. J_true=E_true[C]+lambda*Var_true[C]. Every comparison to oracle/TWAP holds true parameters and lambda fixed.
Continuous regret is J_true(estimated continuous plan)-J_true(continuous oracle); the relative loss divides by the positive continuous oracle objective. Integer loss against the continuous oracle includes rounding. The signed integer gap against the rounded oracle is reported separately and is not mathematically guaranteed nonnegative.
Lower expected cost need not mean a lower weighted objective. Mean-cost paired intervals quantify only mean-cost differences; they are not confidence intervals for objective loss. Empirical mean-plus-lambda-times-sample-variance is recorded without an objective confidence interval.
Currency is an arbitrary consistent model unit; no GBP/HKD or real-market calibration is implied.

## Baseline results at lambda=1e-05

Rounded oracle true expected cost: 1896.03; cost variance: 122789686.00; weighted objective: 3123.93.

| Sigma estimate / true | Impact estimate / true | True expected cost, integer | True cost std, integer | Continuous loss vs oracle | Forecast variance / true |
|---:|---:|---:|---:|---:|---:|
| 0.5 | 0.5 | 1739.81 | 12001.83 | 1.80% | 0.25 |
| 0.5 | 1 | 1687.62 | 12574.64 | 4.64% | 0.25 |
| 0.5 | 2 | 1672.29 | 12897.58 | 6.78% | 0.25 |
| 1 | 0.5 | 2281.72 | 9809.24 | 3.84% | 1 |
| 1 | 1 | 1896.03 | 11081.05 | 0.00% | 1 |
| 1 | 2 | 1739.81 | 12001.83 | 1.80% | 1 |
| 2 | 0.5 | 4242.49 | 6974.12 | 51.37% | 4 |
| 2 | 1 | 3035.51 | 8360.87 | 19.55% | 4 |
| 2 | 2 | 2281.72 | 9809.24 | 3.84% | 4 |

The largest continuous loss in the baseline 3x3 grid at lambda=1e-05 is 51.37% at sigma ratio 2, impact ratio 0.5.
Across the full prespecified main grid, the largest loss is 64.14% in volatility_high at lambda=0.0001, sigma ratio=0.5, impact ratio=2. This is a sampled-grid maximum, not an unrestricted worst-case bound.
Higher volatility estimates or lower impact estimates produce more urgent plans. Underestimating volatility often lowers immediate impact cost while retaining more price exposure. The loss depends on true parameters and preference; comparisons cannot rank different true markets as universally superior.

## Forecast errors and cancellation

For the same plan, E_hat[C]/E_true[C]=eta_hat/eta_true. Var_hat[C]/Var_true[C]=(sigma_hat/sigma_true)^2, when true variance is positive. A volatility estimate at half truth reports one quarter of true variance: a 75% understatement, not a 50% understatement.
Schedule shape depends on c_hat=lambda*sigma_hat^2*tau^2/eta_hat. Joint errors cancel in decisions when (sigma_hat/sigma_true)^2/(eta_hat/eta_true)=1. Doubling estimated sigma while quadrupling estimated eta recovers the oracle schedule but overstates both expected cost and variance by four. Halving sigma and quartering eta likewise preserves the schedule but understates both moments by a factor of four. Correct decisions do not prove correct forecasts.
Supplemental cancellation cases checked: 2; maximum normalized continuous quantity difference: 0.

## Validation and uncertainty

Correct estimates recover the oracle: True. Continuous oracle lower bounds checked: True. All accounting reconciliations passed: True. Invalid case-path occurrences: 0.
All estimated-policy, rounded-oracle and TWAP costs use the same paths. The common validity mask is the intersection of both core paired experiments, so comparative empirical moments use the same three-strategy sample. Raw masks, invalid reasons and all-path costs remain in the output; no clipping or resampling.
For invalid paths, all-path summaries are algebraic diagnostics without inferential intervals, and surviving-path summaries are conditional. Marginal Student-t 95% intervals concern mean-cost simulation error only, with no simultaneous coverage, true-market forecast guarantee or multiple-comparison superiority claim.

## Limits and interpretation

Constant true parameters, arithmetic Brownian reference prices with zero drift, linear temporary impact, guaranteed fills, and no liquidity, spread, fees, permanent impact, learning or market-data estimation. This is not yet a statistically estimated robust optimizer or a minimax policy.
The findings can prioritize calibration checks within this model, especially the quadratic volatility-to-variance relation. They do not justify a universal claim that one parameter always matters more: error sizes, true coefficients and lambda all affect losses.

## Reproducibility

design.json preserves the fixed design; results.json stores complete true/estimated configurations, both quantity modes, all predictions, true-parameter anchors, empirical moments and invalid diagnostics. raw-paths.npz contains deduplicated market prices/innovations, benchmark costs and masks, estimated-policy costs and both pair/common masks.
Reconstruct integer costs as true temporary-impact cost minus preserved innovations @ inventory[1:]. Reconstruct fills from reference prices before each trade minus true impact*n/tau. manifest.json hashes output bytes; provenance includes core/source digests and runtime versions. Repeating into a new empty directory should reproduce all numeric records and raw arrays in the same recorded environment; creation timestamps may differ.

## Reference

[Almgren and Chriss (2001), Optimal execution of portfolio transactions](https://doi.org/10.21314/JOR.2001.041). This is a simplified discrete temporary-impact model, not a reproduction of every component of the original framework.
