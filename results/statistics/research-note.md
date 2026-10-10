# Multi-seed statistical validation of an execution simulator

## Research question

Do simulated cost moments and confidence intervals behave as predicted when the random stream changes and the number of paths grows? How much does shared-path pairing improve the precision of a cost-difference estimate?

## Fixed design and dependence

100 prespecified distinct integer seeds; nested sample sizes [100, 500, 2000, 10000]. Simulate 10,000 paths once per seed, using prefixes for smaller sizes. There are 1,000,000 maximum-size market paths, not the sum of nested sample counts. Each strategy shares prices with the other.
The full seed list is stored before simulation; no seed, batch or interval is selected based on favorable results. Across replicates, separate pseudorandom streams are used. Independence is a simulation assumption; prefixes within a seed and statistics across strategies are correlated.
Integer schedules, financial configuration and preference are fixed. This examines Monte Carlo error under the same model, not parameter-estimation error, model misspecification, real-market performance or a new execution algorithm.
SeedSequence child states were deterministically mapped to distinct uint32 integer seeds because the core accepts integer seeds. This uses NumPy's seeding machinery but does not pass full child objects to the core. [NumPy random-stream documentation](https://numpy.org/doc/2.3/reference/random/parallel.html).

## Statistical methods

For n independent Gaussian cost draws, estimate mean and unbiased variance (ddof=1). The mean interval is sample mean +/- t_(1-alpha/2,n-1)*sample std/sqrt(n). The variance interval is [(n-1)*s^2/chi2_(1-alpha/2,n-1), (n-1)*s^2/chi2_(alpha/2,n-1)]. The Gaussian assumption follows from fixed inventories applied linearly to Gaussian price innovations in the algebraic model. [SciPy Student-t distribution](https://docs.scipy.org/doc/scipy-1.16.2/reference/generated/scipy.stats.t.html), [NIST variance interval derivation](https://www.itl.nist.gov/div898/handbook/eda/section3/eda358.htm).
Aggregate bias and root mean squared error (RMSE) across all prespecified replicates separately for each sample size and channel. Mean RMSE theory is population std/sqrt(n); relative variance RMSE theory is sqrt(2/(n-1)). Finite-replicate measurements fluctuate; a single path-prefix mean error need not decrease monotonically.
At each size/channel, coverage is the fraction of replicate intervals containing the known analytic moment. Exact Clopper-Pearson binomial intervals quantify uncertainty in that fraction. Do not pool correlated sizes/channels, require every interval to cover, or interpret multiple marginal intervals as simultaneous coverage. Degenerate zero-variance channels have point intervals and target coverage one. [SciPy exact binomial interval documentation](https://docs.scipy.org/doc/scipy-1.16.2/reference/generated/scipy.stats._result_classes.BinomTestResult.proportion_ci.html).
If any batch at a sample size has invalid prices, nominal unconditional coverage at that size is suppressed for all channels. All-path moments remain algebraic diagnostics and no Gaussian interval is assigned to the truncated surviving samples. Invalid paths are kept without clipping or resampling.

## Paired precision and financial interpretation

Analytic paired expected cost difference AC-minus-TWAP: 229.363920. Analytic weighted-objective difference: -297.669252. These are different quantities.
Paired cost-difference variance: 6850065.379500; an independent-strategy comparison at equal per-strategy n would have variance 298282689.200700. Independent/paired variance ratio: 43.544502523050696. The independent comparison is calculated analytically; it is not an additional simulated experiment.
The covariance of costs under common paths reduces the variance of their difference. Plot comparators use known-population-variance Gaussian interval widths; the empirical paired widths use Student-t intervals with estimated variance. These methods differ slightly at finite n. More precise mean-cost intervals do not establish real-market superiority or quantify a weighted-objective confidence interval. Synthetic currency units are not calibrated GBP/HKD forecasts.

## Results

| Paths per seed | Paired mean RMSE | Theory RMSE | Average paired mean interval width | Mean coverage (exact binomial interval) | Variance coverage (exact binomial interval) |
|---:|---:|---:|---:|---:|---:|
| 100 | 237.698 | 261.726 | 1040.339 | 0.970 [0.915, 0.994] | 0.970 [0.915, 0.994] |
| 500 | 100.116 | 117.048 | 458.627 | 0.970 [0.915, 0.994] | 0.950 [0.887, 0.984] |
| 2000 | 62.897 | 58.524 | 229.386 | 0.920 [0.848, 0.965] | 0.930 [0.861, 0.971] |
| 10000 | 24.590 | 26.173 | 102.610 | 0.980 [0.930, 0.998] | 0.980 [0.930, 0.998] |

Descriptive log-log mean-RMSE slopes: {'twap': -0.5083263628018785, 'ac': -0.5131921342525992, 'paired': -0.4795619409648877}; theoretical slope -0.5. The four nested sample sizes are correlated, so this fit carries no regression p-value or independent-point uncertainty claim.
All individual results, coverage success counts and exact coverage uncertainty intervals appear in results.json and CSV. Coverage misses are retained, not treated as bugs merely for missing the theoretical moment.

## Verification and provenance

All prespecified seeds retained: True; all direct accounting reconciliations passed: True; invalid maximum-size path occurrences: 0.
raw-costs.npz retains both maximum-size cost arrays and validity masks for every seed. Prices and innovations are regenerated from the recorded configuration, integer seed and pinned runtime; their SHA256 hashes are recorded per replicate (C-contiguous little-endian float64 bytes). Thus full raw price matrices need not be duplicated in the archive.
Source and input digests, core commit/digest, versions and output byte hashes accompany the data. An independent verification regenerates every seed, reconstructs costs and masks, and checks stored statistics. Repeating into a fresh directory must reproduce numeric records and raw arrays in the same environment; creation timestamps may differ.

## Limits

The fixed simple model assumes arithmetic Brownian reference prices, linear temporary impact, guaranteed fills, no spread/fees/permanent impact and no liquidity constraints. Normal-cost calibration is a model-specific check. Running more paths narrows simulation error; it does not fix an incorrect financial model. A nominal 95% mean interval is not a 95% prediction interval for a new realized cost or real-market execution.
Finite seed counts produce coverage-estimation uncertainty. Nested sizes, pairing and selected plotted examples are explicitly accounted for; all seeds are shown rather than a best seed. This is statistical verification of a research prototype, not evidence of predictive trading returns.
