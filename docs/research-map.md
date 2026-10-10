# Research map

| ID | Question | Frozen full-study evidence |
|---|---|---|
| core | How does inventory risk trade off against temporary-impact cost? | ../results/core/results.json |
| sensitivity | How do volatility, impact and risk aversion change schedules? | ../results/sensitivity/results.json |
| robustness | What is the regret under misspecified parameters? | ../results/robustness/results.json |
| statistics | Do repeated-stream Monte Carlo intervals and convergence agree with model theory? | ../results/statistics/results.json |
| solver | Do three numerical methods agree, and what is their observed local runtime/storage? | ../results/solver/results.json |
| historical | How do lagged volatility estimates perform on a held-out historical FX period? | ../results/historical/results.json |
| volume | How do synthetic volume profiles affect arrival and VWAP comparisons? | ../results/volume/results.json |
| participation | When is the order feasible, and how do capped schedules compare? | ../results/participation/results.json |
| real-volume | Do past-only equity volume forecasts support subsequent capacity-feasible execution plans? | ../results/real-volume/results.json |

Each evidence folder contains a manifest, numerical output and figures/notes. Original designs are packaged under src/execution_research/inputs or src/execution_research/studies/<ID>/inputs. These full designs are the default for the unified run command.

Finance assumptions remain those of the individual modules. Daily ECB reference rates are not executable quotes, impact parameters and synthetic market volumes are not empirically calibrated execution liquidity, and guaranteed planned fills omit stochastic fill risk. Timing fits over tested sizes do not establish asymptotic complexity.

A participation-constrained plan is checked against integer interval caps and continuous relaxation certificates. Its objective difference against the original rounded plan includes constraints and rounding effects. It is not a pure constraint premium, nor an integer global-optimality proof.
