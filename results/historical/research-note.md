# Historical FX reference-data volatility calibration

## Research question

Can an auditable historical-data pipeline estimate volatility, preserve information boundaries and supply dimensionally explicit inputs to the existing execution model? Compare assumptions about time conversion and diagnose chronological holdout forecasts; do not presume that any rolling estimator must outperform a frozen one.

## Data and transformations

Source: European Central Bank euro reference-rate historical CSV archive. [Official reference-rate description](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html). Reference rates are informational and are not executable transaction quotes. The original download is retained unmodified, with retrieval time and SHA-256.

USD, GBP and HKD are quoted per euro. Derived USD/GBP = (USD/EUR)/(GBP/EUR); derived USD/HKD = (USD/EUR)/(HKD/EUR). The researcher sorts and filters the archive, derives cross-rates and log returns, and calculates statistics. [ECB reuse conditions](https://www.ecb.europa.eu/services/using-our-site/disclaimer/html/index.en.html); attribute the ECB and disclose these modifications. No ECB endorsement is implied.

Raw CSV rows: 7110; outside fixed range: 6064; identical selected-rate duplicates: 0; dropped missing/invalid rows: 0; retained prices: 1046. All counts reconcile. No forward filling; no extreme-return deletion. Structural date/schema errors and conflicting duplicates fail loudly. Missing, non-finite and non-positive rates are audited and omitted jointly from the cross-rate panel.

Data range: 2021-12-01 to 2025-12-31. Training return END dates: 2022-01-01 to 2023-12-31; holdout: 2024-01-01 to 2025-12-31. Pre-training observations provide the prior price and rolling history. Current historical snapshots may contain later revisions; chronological boundaries are not a point-in-time vintage-data guarantee.

## Time units and estimation

For r_i=log(P_i/P_(i-1)) and dt_i equal to elapsed calendar minutes:
mu_hat = sum(r_i)/sum(dt_i);
sigma_hat² = sum((r_i-mu_hat*dt_i)²/dt_i)/(n-1).
This is the one-drift-parameter, degrees-of-freedom-adjusted constant-diffusion fit under independent Gaussian innovations. An independent verifier recomputes the fit with high-precision arithmetic.

The primary mapping uses actual calendar gaps. A sensitivity mapping fixes every reference-observation step to 1,440 minutes, including steps across weekends and holidays. Daily-equivalent sigma is sigma_min*sqrt(1440); calendar-annual equivalent is sigma_min*sqrt(525600). The annual proxy uses calendar time, not the equity convention of 252 trading days.

Daily reference observations do not identify true intraday volatility, liquidity, spreads, jumps or market impact. Published quote precision and cross-rate arithmetic may contribute noise, particularly for small currency moves. The calendar model assigns diffusion time across weekends/holidays even when activity differs; the fixed-step model compresses those gaps. Both are explicit modeling conventions. Estimating log-return diffusion also differs from the arithmetic Brownian price model in the core.

## Frozen training estimates

| Asset | Training returns | Calendar σ at price 100 | Reference-step σ at price 100 | Calendar annualized log-vol proxy |
|---|---:|---:|---:|---:|
| GBPUSD | 512 | 0.0160008 | 0.0173983 | 11.60% |
| HKDUSD | 512 | 0.001183 | 0.00129641 | 0.86% |

## Chronological forecast diagnostics

The frozen estimator uses only training returns. Rolling windows of 20, 60 and 120 returns include only observations ending at or before the previous reference date. For each next observed reference interval, forecast mean=mu_hat*dt and variance=sigma_hat²*dt. Horizon length is the observed calendar interval; this is a retrospective interval-specific diagnostic, not a live service anticipating missing releases.

MSFE / forecast variance = sum((r-forecast_mean)²)/sum(forecast_variance). It measures squared forecast error, not pure variance alone: drift error and changing volatility both matter. Normal 95% coverage counts |error| <= 1.9599639845*sqrt(variance). QLIKE=log(variance)+error²/variance is also retained. Zero variance is recorded explicitly without inventing a positive floor.

| Asset | Estimator | Holdout n | MSFE / forecast variance | Empirical normal 95% coverage | Mean QLIKE (lower is better, within asset) |
|---|---|---:|---:|---:|---:|
| GBPUSD | rolling_120 | 511 | 0.792 | 94.91% | -9.808 |
| GBPUSD | rolling_20 | 511 | 0.856 | 92.95% | -9.605 |
| GBPUSD | rolling_60 | 511 | 0.818 | 94.32% | -9.820 |
| GBPUSD | static_training | 511 | 0.357 | 98.43% | -9.551 |
| HKDUSD | rolling_120 | 511 | 0.849 | 94.52% | -13.638 |
| HKDUSD | rolling_20 | 511 | 0.826 | 92.17% | -12.623 |
| HKDUSD | rolling_60 | 511 | 0.832 | 93.35% | -13.233 |
| HKDUSD | static_training | 511 | 1.201 | 94.13% | -13.746 |

These are descriptive holdout diagnostics. Correlated or heteroskedastic observations invalidate a simplistic independent-observation coverage confidence interval; none is claimed. Windows and dates were fixed before outcomes. Different periods can favor different estimators; no best window is selected or deployed after observing the holdout.

## Link to the execution model

The original core models a hypothetical price-100 instrument with quantities in shares. To preserve its units, carry the historical RELATIVE FX volatility into a synthetic price-normalized instrument: sigma_core=100*sigma_log_per_sqrt_minute. Also retain the actual quote-level sigma at the last training price, with units USD/GBP or USD/HKD per sqrt-minute.

Three continuous schedules per asset: the original assumed sigma=0.03, calendar-calibrated sigma, and reference-day-calibrated sigma. Compare all three under the same frozen calendar-calibrated model sigma, keeping eta=1e-5, lambda=1e-5, Q=100000, T=60 minutes and N=60. The calendar plan minimizes that continuous assumed objective by construction. Its objective advantage is a model consistency check, not evidence of superior historical trade execution.

This rescaling does not make GBP or HKD worth USD100, does not calibrate an actual equity, and does not infer eta from daily prices. Impact and risk preference remain assumptions. No historical transaction-price or real-market execution-profit backtest is performed.

## Reproducibility

Retain the raw official archive, metadata, fixed design, cleaned panel, returns, fits, every forecast and its fitting cutoff, period summaries, model inventory arrays and source/runtime hashes. Two runs using the same snapshot should agree numerically; a new download can change archive bytes as the provider adds observations or revises history.

Nine automated tests cover sorting and audit reconciliation, cross-rates, conflicts, missing data, calendar gaps, hand-worked fitting, invalid inputs, future-target perturbation, frozen training, normalized integration and strict exports. Source files of the original core are unchanged.
