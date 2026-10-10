# Real equity volume validation: chronological research pilot

Source: [FirstRate Data](https://firstratedata.com/free-intraday-data), [format and permissions](https://firstratedata.com/about/FAQ), [license](https://firstratedata.com/about/license). Instruments: SPY, AAPL. Frozen input dates: 2026-09-21 to 2026-10-02. Raw data accessed 2026-10-09; report prepared 2026-10-10. 20 complete symbol-sessions, 7,800 retained regular-session minute bars, aggregated into 78 five-minute intervals per session. Changes are documented in the source design, not silently substituted.

## Question and method
Does a plan feasible under a past-only volume forecast remain feasible against subsequent observed volume? Exactly 5 preceding sessions predict each target date. There are 5 evaluation date(s), 2 selected instrument(s), and 10 symbol-days. The rolling window can include earlier completed evaluation dates, never the current date. Training dates are retained for every forecast and plan.

Predictors: uniform shape; equal-weight mean historical daily-normalized shape; previous-day absolute interval volumes. Uniform and historical shape share the past-window mean total; every predictor shares the same order size based on that past ADV. Orders are 1%, 5%, 9% of past ADV; participation ceiling 10%. Three planners: capped uniform, capped forecast-volume and constrained arrival, using the unchanged reviewed kernel. Volatility uses only within-day price changes in training. Horizon 390 minutes; five-minute intervals; assumed eta=1e-05, lambda=1e-05. Impact and risk preferences are not empirically calibrated.

## Results and interpretation
30 forecasts; 270 planner-case records. 264 generated plans and 229 completed in replay. 35 generated plans retained terminal shares; 6 cases correctly produced no plan. Repeated scenarios and planners on the same historical dates are not independent market observations. No-plan cases stay in the completion denominator.

| Instrument | Predictor | Mean daily APE | Mean interval WAPE | Mean cumulative share MAE |
|---|---|---:|---:|---:|
| SPY | Uniform | 10.05% | 55.64% | 8.25% |
| SPY | Historical shape | 10.05% | 38.56% | 6.30% |
| SPY | Previous day | 11.39% | 52.94% | 8.54% |
| AAPL | Uniform | 16.00% | 54.19% | 9.17% |
| AAPL | Historical shape | 16.00% | 29.02% | 3.06% |
| AAPL | Previous day | 19.75% | 43.06% | 4.27% |

WAPE is sum of absolute interval-volume errors divided by the observed day total. Daily APE compares total volume; cumulative share MAE compares cumulative normalized curves. Percentages are descriptive averages over target dates, not confidence intervals. A lower forecast error does not guarantee completion or cheaper execution. When forecast volume is uniform, the capped-uniform and capped-volume targets can coincide; they are not additional independent evidence.

| Instrument | Predictor | Order / past ADV | TWAP complete / 5 | Volume complete / 5 | Arrival complete / 5 | Common complete dates |
|---|---|---:|---:|---:|---:|---:|
| SPY | Uniform | 1% | 5 | 5 | 5 | 5 |
| SPY | Uniform | 5% | 5 | 5 | 5 | 5 |
| SPY | Uniform | 9% | 3 | 3 | 4 | 3 |
| SPY | Historical shape | 1% | 5 | 5 | 5 | 5 |
| SPY | Historical shape | 5% | 5 | 5 | 5 | 5 |
| SPY | Historical shape | 9% | 3 | 2 | 4 | 2 |
| SPY | Previous day | 1% | 5 | 5 | 5 | 5 |
| SPY | Previous day | 5% | 5 | 4 | 5 | 4 |
| SPY | Previous day | 9% | 2 | 2 | 3 | 2 |
| AAPL | Uniform | 1% | 5 | 5 | 5 | 5 |
| AAPL | Uniform | 5% | 5 | 5 | 5 | 5 |
| AAPL | Uniform | 9% | 2 | 2 | 2 | 2 |
| AAPL | Historical shape | 1% | 5 | 5 | 5 | 5 |
| AAPL | Historical shape | 5% | 5 | 5 | 5 | 5 |
| AAPL | Historical shape | 9% | 4 | 3 | 4 | 3 |
| AAPL | Previous day | 1% | 5 | 5 | 5 | 5 |
| AAPL | Previous day | 5% | 5 | 4 | 5 | 4 |
| AAPL | Previous day | 9% | 3 | 2 | 3 | 2 |

## What replay and price diagnostics mean
Each interval executes min(cumulative released plan - previous fills, floor(rho * observed interval volume)). Backlog carries forward; missed earlier capacity cannot be borrowed retroactively. Residual shares stay explicitly unfilled. Summed observed quotas give an after-event volume-only capacity upper bound, not an executable policy. Finished-interval volume becomes known after the event: this replay cannot establish live fill availability.

The sell-price diagnostic assumes each fill at five-minute Close plus constant temporary impact. Marked shortfall = Q*first Open - sum(fills*Close) - residual*final Close + eta/5*sum(fills^2). Residual marking is not execution. Price comparisons use only dates where all three planners of the SAME predictor/order size produced AND completed plans. Different predictors can have different common subsets; their means must not be used as an across-predictor performance ranking. A negative shortfall may reflect favorable price movement, not strategy alpha or a verified profit.

Fixed-schedule impact sensitivity below: historical shape, order 5% of past ADV, mean marked shortfall in bps on the same common completed dates. Plans are held fixed, not re-optimised for each eta.

| Instrument | Planner | Common complete dates | eta=0 | eta=1e-5 | eta=5e-5 |
|---|---|---:|---:|---:|---:|
| SPY | Capped uniform | 5 | 16.460 | 16.937 | 18.847 |
| SPY | Capped volume | 5 | 16.544 | 17.382 | 20.737 |
| SPY | Constrained arrival | 5 | 15.340 | 16.306 | 20.168 |
| AAPL | Capped uniform | 5 | 4.369 | 5.122 | 8.137 |
| AAPL | Capped volume | 5 | 4.746 | 6.004 | 11.036 |
| AAPL | Constrained arrival | 5 | -6.395 | -3.853 | 6.316 |

## Limits and reproduction
This is a short, selected-instrument pilot. No significance tests, annualisation or long-run superiority claims. Supplier reported intraday volume can differ from official daily totals; complete consolidated volume coverage has not been independently established. No order book, spread, fees, queue priority, auction-specific modelling or true trade-by-trade VWAP. Hypothetical own orders do not alter historical volume or prices. Prices use the vendor's historical adjustment conventions rather than point-in-time unadjusted quotes. Rounded constrained plans have continuous-relaxation bounds, not proofs of integer global optimality.

Raw OHLCV, raw volume/price arrays and vendor HTML remain local and are excluded from the public package. Independently fetch vendor data; frozen hashes reject rotated/changed samples. A changed data file requires a new named design and report. Public outputs contain derived metrics, strategy schedules/fills and static figures. [Reproduction guide](../../docs/real-volume.md).

AI-assisted implementation and research preparation. Prior studies remain separately labelled; this pilot does not replace their full-study evidence.

## Figures
![01-volume-curves.png](figures/01-volume-curves.png)

![02-forecast-errors.png](figures/02-forecast-errors.png)

![03-completion.png](figures/03-completion.png)

![04-replay-example.png](figures/04-replay-example.png)

![05-paired-price-diagnostic.png](figures/05-paired-price-diagnostic.png)
