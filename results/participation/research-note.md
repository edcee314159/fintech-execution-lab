# Participation constraints and capacity feasibility

## Question and scope

Can a mathematically attractive execution plan actually satisfy a deterministic market-volume quota? This extension introduces nonnegative integer trades, interval participation limits and exact full-order conservation. It preserves the original constant temporary-impact arrival objective, isolating the effect of capacity from a change in the impact model.

The study uses 75 conditions: 5 synthetic volume profiles, 3 risk weights and 5 capacity scenarios. 45 are capacity feasible and 30 are infeasible. Every feasible condition compares three plans on the same 2000 seeded Gaussian price paths. Reusing these paths does not create additional independent market observations.

## Quota semantics and infeasibility

External interval volume V is an integer allocation of the scenario's total using the forecast profile. It excludes the seller's own trades. The participation denominator is that external volume: q/V, not q/(V+q), and not a broker's percentage of average daily volume. Each integer cap is floor(rho*V); decimal input semantics use Decimal(str(input)) before flooring.

Continuous capacity shortage means sum(rho*V)<Q. Integer-only shortage means the raw quota covers Q but sum(floor(rho*V))<Q. With unit shares, box constraints and a single sum constraint, sum(caps)>=Q is sufficient for integer feasibility. The maximal possible shares is min(Q,sum(caps)). Zero-volume intervals have cap zero.

Infeasible orders are explicitly diagnosed. No fictitious complete plan or financially incomparable partial-order cost is generated. Capacity feasibility does not establish positive prices, so price/fill validity is checked separately.

These volumes and quotas are known deterministic scenario inputs. Forecast capacity is not guaranteed actual available liquidity. There is no order book, fill probability, real-volume calibration, participation-triggered price feedback or live execution. A broker algorithm has additional controls and may fail to complete; this model does not replicate it. [IBKR VWAP controls](https://www.interactivebrokers.com/docs/general/order-types/algorithmic-orders/ib-algorithms/vwap).

## Three feasible plans

Capped uniform and capped volume plans project their original target onto the same bounded simplex:
min ||q-target||², subject to 0<=q<=cap and sum(q)=Q.
The water-filling solution is clip(target+theta,0,cap), with theta selected by bisection. Simple clipping loses the order total and is not used. The volume target uses only the predefined forecast curve.

The constrained arrival plan minimizes
J(q)=a*sum(q²)+lambda*sigma²*tau*sum(x_post²), a=eta/tau.
Writing x_post=Lq with L strictly upper triangular gives H=a*I+b*L.T@L and J=q.T@H@q. H is positive definite because a>0. Normalize q/Q for SciPy SLSQP, provide the analytic gradient, and polish free variables with an active-set KKT refinement that can release falsely active bounds. [SciPy SLSQP documentation](https://docs.scipy.org/doc/scipy/reference/optimize.minimize-slsqp.html).

All three continuous plans receive deterministic capacity-aware largest-remainder rounding. Extra shares go only to intervals with spare integer capacity. Every resulting Schedule passes the core conservation and inventory checks and an additional cap check. The original unconstrained AC plan is retained solely as a labelled feasibility diagnostic, not as an executable strategy in the paired comparisons.

## Numerical certificate, including integer limitations

For any feasible q and g=2Hq, convexity gives
J(z)>=J(q)+g.T@(z-q).
Minimize g.T@z over the same box-and-sum set by filling capacity in increasing gradient order. Let z_lin denote that solution. The first-order gap is g.T@(q-z_lin), with a conservative floating-point allowance added. Therefore J(q)-gap is a lower bound for the continuous optimum and also for the integer optimum.

The recorded gap measures continuous numerical optimality in model objective units. After rounding, J(q_integer)-lower_bound is an upper bound on the integer plan's suboptimality. Rounding is not a proof of global integer optimality or universal superiority over the integer benchmark plans. Max continuous certificate gap in this run: 1.55120378625e-09.

## A measured result

For u_shape / moderate_capacity at lambda=1e-05, integer capacity is 119,976 shares for a 100,000-share order. The original unconstrained integer AC plan violates 30 interval caps. Its reference arrival objective is 3123.93; the feasible integer constrained plan has objective 3283.60 and binds 41 intervals. This is the observed difference between two integer approximations. It combines capacity restrictions with rounding effects, and does not isolate the mathematical constraint premium or measure an actual market loss.

## Capacity diagnostics at the default risk weight

| Profile | Capacity scenario | Integer capacity (shares) | Feasible | Shortfall (shares) |
|---|---|---:|---|---:|
| flat | capacity_shortage | 60,000 | False | 40,000 |
| flat | integer_shortage | 99,960 | False | 40 |
| flat | near_capacity | 100,020 | True | 0 |
| flat | moderate_capacity | 120,000 | True | 0 |
| flat | loose_capacity | 3,000,000 | True | 0 |
| u_shape | capacity_shortage | 59,978 | False | 40,022 |
| u_shape | integer_shortage | 99,976 | False | 24 |
| u_shape | near_capacity | 100,032 | True | 0 |
| u_shape | moderate_capacity | 119,976 | True | 0 |
| u_shape | loose_capacity | 2,999,974 | True | 0 |
| front_loaded | capacity_shortage | 59,970 | False | 40,030 |
| front_loaded | integer_shortage | 99,970 | False | 30 |
| front_loaded | near_capacity | 100,033 | True | 0 |
| front_loaded | moderate_capacity | 120,000 | True | 0 |
| front_loaded | loose_capacity | 3,000,000 | True | 0 |
| back_loaded | capacity_shortage | 59,970 | False | 40,030 |
| back_loaded | integer_shortage | 99,970 | False | 30 |
| back_loaded | near_capacity | 100,033 | True | 0 |
| back_loaded | moderate_capacity | 120,000 | True | 0 |
| back_loaded | loose_capacity | 3,000,000 | True | 0 |
| midday_peak | capacity_shortage | 59,974 | False | 40,026 |
| midday_peak | integer_shortage | 99,980 | False | 20 |
| midday_peak | near_capacity | 100,034 | True | 0 |
| midday_peak | moderate_capacity | 119,978 | True | 0 |
| midday_peak | loose_capacity | 2,999,974 | True | 0 |

## Strategy results at the default risk weight

Costs and standard deviations are in model currency; the risk weight has the corresponding units for mean plus variance.

| Profile | Scenario | Plan | Expected impact | Arrival SD | Mean + λ variance | Binding intervals |
|---|---|---|---:|---:|---:|---:|
| flat | near_capacity | Capped uniform target | 1666.67 | 13247.38 | 3421.60 | 40 |
| flat | near_capacity | Capped forecast-volume | 1666.67 | 13247.38 | 3421.60 | 40 |
| flat | near_capacity | Constrained arrival | 1666.67 | 13247.23 | 3421.56 | 57 |
| flat | moderate_capacity | Capped uniform target | 1666.67 | 13247.38 | 3421.60 | 0 |
| flat | moderate_capacity | Capped forecast-volume | 1666.67 | 13247.38 | 3421.60 | 0 |
| flat | moderate_capacity | Constrained arrival | 1729.42 | 12237.83 | 3227.06 | 23 |
| flat | loose_capacity | Capped uniform target | 1666.67 | 13247.38 | 3421.60 | 0 |
| flat | loose_capacity | Capped forecast-volume | 1666.67 | 13247.38 | 3421.60 | 0 |
| flat | loose_capacity | Constrained arrival | 1896.03 | 11081.05 | 3123.93 | 0 |
| u_shape | near_capacity | Capped uniform target | 2100.90 | 12583.79 | 3684.41 | 58 |
| u_shape | near_capacity | Capped forecast-volume | 2101.63 | 12583.23 | 3685.00 | 30 |
| u_shape | near_capacity | Constrained arrival | 2100.90 | 12580.42 | 3683.57 | 59 |
| u_shape | moderate_capacity | Capped uniform target | 1858.47 | 12834.69 | 3505.76 | 38 |
| u_shape | moderate_capacity | Capped forecast-volume | 2101.63 | 12583.23 | 3685.00 | 0 |
| u_shape | moderate_capacity | Constrained arrival | 2029.40 | 11199.07 | 3283.60 | 41 |
| u_shape | loose_capacity | Capped uniform target | 1666.67 | 13247.38 | 3421.60 | 0 |
| u_shape | loose_capacity | Capped forecast-volume | 2101.63 | 12583.23 | 3685.00 | 0 |
| u_shape | loose_capacity | Constrained arrival | 1896.03 | 11081.05 | 3123.93 | 0 |
| front_loaded | near_capacity | Capped uniform target | 1978.66 | 10873.55 | 3161.00 | 59 |
| front_loaded | near_capacity | Capped forecast-volume | 1979.19 | 10870.20 | 3160.80 | 27 |
| front_loaded | near_capacity | Constrained arrival | 1979.24 | 10869.43 | 3160.69 | 54 |
| front_loaded | moderate_capacity | Capped uniform target | 1827.06 | 11879.95 | 3238.39 | 32 |
| front_loaded | moderate_capacity | Capped forecast-volume | 1979.19 | 10870.21 | 3160.80 | 0 |
| front_loaded | moderate_capacity | Constrained arrival | 1947.11 | 10908.94 | 3137.16 | 14 |
| front_loaded | loose_capacity | Capped uniform target | 1666.67 | 13247.38 | 3421.60 | 0 |
| front_loaded | loose_capacity | Capped forecast-volume | 1979.19 | 10870.21 | 3160.80 | 0 |
| front_loaded | loose_capacity | Constrained arrival | 1896.03 | 11081.05 | 3123.93 | 0 |
| back_loaded | near_capacity | Capped uniform target | 1978.66 | 15909.24 | 4509.70 | 59 |
| back_loaded | near_capacity | Capped forecast-volume | 1979.05 | 15910.02 | 4510.33 | 30 |
| back_loaded | near_capacity | Constrained arrival | 1978.66 | 15909.24 | 4509.70 | 59 |
| back_loaded | moderate_capacity | Capped uniform target | 1827.06 | 15134.44 | 4117.57 | 32 |
| back_loaded | moderate_capacity | Capped forecast-volume | 1978.96 | 15909.54 | 4510.09 | 0 |
| back_loaded | moderate_capacity | Constrained arrival | 1832.96 | 15085.42 | 4108.66 | 37 |
| back_loaded | loose_capacity | Capped uniform target | 1666.67 | 13247.40 | 3421.60 | 0 |
| back_loaded | loose_capacity | Capped forecast-volume | 1978.96 | 15909.54 | 4510.09 | 0 |
| back_loaded | loose_capacity | Constrained arrival | 1896.03 | 11081.05 | 3123.93 | 0 |
| midday_peak | near_capacity | Capped uniform target | 2305.49 | 14240.14 | 4333.30 | 58 |
| midday_peak | near_capacity | Capped forecast-volume | 2305.94 | 14240.33 | 4333.81 | 32 |
| midday_peak | near_capacity | Constrained arrival | 2305.50 | 14240.02 | 4333.28 | 58 |
| midday_peak | moderate_capacity | Capped uniform target | 2051.55 | 14029.48 | 4019.81 | 40 |
| midday_peak | moderate_capacity | Capped forecast-volume | 2305.81 | 14240.18 | 4333.64 | 0 |
| midday_peak | moderate_capacity | Constrained arrival | 2063.40 | 13939.89 | 4006.61 | 40 |
| midday_peak | loose_capacity | Capped uniform target | 1666.67 | 13247.38 | 3421.60 | 0 |
| midday_peak | loose_capacity | Capped forecast-volume | 2305.81 | 14240.18 | 4333.64 | 0 |
| midday_peak | loose_capacity | Constrained arrival | 1896.03 | 11081.05 | 3123.93 | 0 |

## Statistical checks and reproducibility

There are 135 strategy rows and 135 paired rows. All paths, plans, integer quotas, absolute market volumes, continuous constrained quantities and original unconstrained diagnostics are retained. The same price innovations and a mask common to all three feasible plans are used. Nonpositive reference/fill paths are preserved; any invalid path suppresses inferential intervals. Invalid feasible-case paths here: 0.

Direct initial notional minus proceeds is checked against impact minus inventory times preserved price innovations under a floating-point bound. Analytic variance is sigma²*tau*||x_post||². Paired variance uses inventory differences. Student-t intervals quantify Monte Carlo mean uncertainty, not risk-objective uncertainty, liquidity forecast uncertainty or actual-market performance; no family-wide significance claim is made.

Independent checks reconstruct Decimal quotas, order accounting, statistics, the convex lower bound and a separate active-set reference solution. Two runs must reproduce numerical JSON and raw arrays exactly. Source/runtime digests and file manifests are retained. The separate tests also cover a hand-worked two-interval case, zero capacities, the singleton feasible set and small integer enumeration.

## Limits and attribution

This is a deterministic full-order capacity model. The 10% quota is an illustrative design choice, not a recommended trading setting. Capacity inputs are not estimated from real volume. A smaller realized volume could breach a forecast-based participation constraint or prevent actual completion. The extension adds no partial-fill accounting or endpoint liquidation penalty; infeasibility is reported rather than assigning an arbitrary economic value to unfinished shares.

This research software was developed with AI assistance.
