# Execution solver: numerical accuracy and local performance

## Question and financial system

Does the reference optimizer agree with independent numerical and closed-form solutions, and how do solve time and input storage grow as the fixed execution horizon is divided into more intervals?
For interior inventory y=(x_1,...,x_(N-1)), the first-order condition is Ay=b, with diagonal 2+c, adjacent diagonals -1, b_1=Q, and c=lambda*sigma^2*tau^2/eta. The matrix is symmetric positive definite for c>=0. Inventory endpoints are Q and zero. The objective is temporary-impact cost plus lambda times cost variance.
This solver computes continuous quantities. Largest-remainder integerization is a separate feasible approximation; a fast linear solve does not imply every step of the full product has linear complexity.

## Three methods and independent accuracy reference

Compare the original Python Thomas elimination, SciPy solve_banded with fixed lower/upper bandwidth one, and an explicitly dense positive-definite solve (assume_a='pos'). Both library methods preserve inputs and retain finite checks. Explicit dense mode avoids automatic structure detection. [SciPy banded solver](https://docs.scipy.org/doc/scipy-1.16.2/reference/generated/scipy.linalg.solve_banded.html), [SciPy dense solver](https://docs.scipy.org/doc/scipy-1.16.2/reference/generated/scipy.linalg.solve.html).
For c>0, gamma=2*asinh(sqrt(c)/2) and x_k=Q*sinh((N-k)*gamma)/sinh(N*gamma). Evaluate this with exp and expm1 to avoid overflow or cancellation. At c=0 use Q*(1-k/N). This is a mathematical reference, not another call to the tested elimination.
Record maximum inventory error normalized by Q, relative financial-objective error, and infinity-norm backward error ||Ay-b||/(||A||*||y||+||b||). The analytic condition number uses extremal eigenvalues c+4*sin²(pi/(2N)) and c+4*cos²(pi/(2N)). A small residual alone cannot guarantee small forward error in a poorly conditioned system.
Accuracy design: 33 conditions across three methods, including N=1, zero preference/volatility, weak and strong coefficients and a large order. Thresholds are fixed in design.json. All passed: True. Maximum normalized inventory error: 9.38e-12; maximum relative objective error: 3.16e-16; maximum normalized backward error: 1.19e-16.

## Timing protocol

Two comparable scopes: prebuilt matrix solve (including solver copies and finite checks), and configuration-to-continuous-inventory (including validation, allocation, representation construction and boundary assembly). A third scope times the unchanged original make_ac integer-plan pipeline only. Import/setup and file/plot creation are excluded.
Sizes: [10, 30, 60, 100, 300, 600, 1000]. Warmups: 3; repeated batches: 9. Loop counts are calibrated to the same minimum batch duration and capped; order is deterministically shuffled each repeat. Report medians and IQR, keep all samples and outliers. IQR is not a confidence interval. [Python timing documentation](https://docs.python.org/3.12/library/timeit.html).
Thread requests are one; actual BLAS threads verified: True. Hardware/runtime and clock metadata are in results.json, with no hostname or user paths. Finite checks remain enabled; dense/band arrays are Fortran-contiguous.
Timing measurements include operating-system scheduling and hardware/cache effects. Exact runtimes will vary between runs; numerical solutions and representation sizes are reproducible. Descriptive finite-size log-log slopes do not prove asymptotic complexity. Algorithmic operation counts give linear work for fixed-bandwidth elimination and cubic work for generic dense Cholesky; full integerization includes sorting.

## Local runtime medians (microseconds)

| N | Thomas prepared | Banded prepared | Dense SPD prepared | Original full integer plan |
|---:|---:|---:|---:|---:|
| 10 | 25.66 | 15.77 | 17.49 | 184.06 |
| 30 | 52.82 | 16.98 | 24.98 | 210.17 |
| 60 | 93.80 | 16.90 | 41.41 | 254.30 |
| 100 | 136.05 | 16.80 | 71.34 | 287.76 |
| 300 | 375.11 | 21.11 | 568.36 | 551.55 |
| 600 | 747.42 | 28.01 | 3716.41 | 930.93 |
| 1000 | 1232.08 | 36.20 | 14316.00 | 1451.80 |

## Memory representation and interpretation

Storage numbers are actual input-array nbytes: Thomas diagonals 8*(3m-2), band storage 8*3m, and dense storage 8*m², where m=N-1. The RHS and solution each require another 8m bytes. These are not process peak RAM, temporary allocation totals or native solver workspace.
The specialized structure avoids allocating a dense quadratic matrix. Nevertheless compiled library constants can make the banded library faster than a Python implementation of the same asymptotic complexity. Do not equate personal implementation with universal speed superiority, or infer financial performance from solver timing.
Descriptive slopes over measured N>=100: {'prepared_system:thomas': 0.9537886053584648, 'prepared_system:scipy_banded': 0.32694671099738304, 'prepared_system:scipy_dense_spd': 2.2949211387029775, 'inventory_end_to_end:thomas': 0.9045955519416347, 'inventory_end_to_end:scipy_banded': 0.2277725878089443, 'inventory_end_to_end:scipy_dense_spd': 2.226222160204681, 'product_integer_schedule:original_make_ac': 0.6940466394736474}. Limited sizes, overhead and hardware effects constrain their interpretation.

## Reproducibility and limits

Solutions, closed-form references, financial metrics, matrices' representation sizes, all calibration counts and raw timings are retained with source/runtime/input digests. Repeat numerical checks independently; timing data are deliberately not asserted byte-identical. Original core source remains unchanged.
This is a local benchmark with maximum N=1000 under the original model limits. It does not establish real-market latency, benchmark every solver, measure peak native memory, or change the financial model. All methods optimize the same continuous mathematical objective; integerized feasibility is distinct from global integer optimality.
