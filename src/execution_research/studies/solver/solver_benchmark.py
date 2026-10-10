"""Numerical accuracy and local runtime benchmarking for the execution reference solver."""
from __future__ import annotations
import os
for _variable in ("OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS"):
    os.environ[_variable]="1"
import argparse,csv,ctypes,hashlib,json,platform,time,timeit
from pathlib import Path
from numbers import Real
import numpy as np
import scipy
from scipy.linalg import solve,solve_banded
from execution_lab.config import ExecutionConfig
from execution_lab.reference_solver import continuous_inventory,solve_tridiagonal
from execution_lab.schedule import make_ac
from execution_lab.export import _provenance

METHODS=("thomas","scipy_banded","scipy_dense_spd")

def validate_design(design):
    if design.get("schema_version")!="1.0":raise ValueError("unsupported schema")
    base=ExecutionConfig.from_dict(design["base"])
    for key,minimum in (("benchmark_intervals",2),("accuracy_intervals",1)):
        values=design[key]
        if not values or any(isinstance(n,bool) or not isinstance(n,int) or n<minimum for n in values):
            raise ValueError(key+" must contain at least two intervals" if minimum==2 else key+" must contain positive integers")
        if values!=sorted(values) or len(set(values))!=len(values):raise ValueError(key+" must be increasing and unique")
        for n in values:ExecutionConfig.from_dict({**base.to_dict(),"intervals":n})
    risks=design["accuracy_risk_aversions"]
    if not risks or len(set(risks))!=len(risks):raise ValueError("accuracy risks must be nonempty and unique")
    for risk in risks:ExecutionConfig.from_dict({**base.to_dict(),"risk_aversion":risk})
    extras=design["accuracy_extra_cases"]
    if len({e["name"] for e in extras})!=len(extras):raise ValueError("extra case names must be unique")
    for extra in extras:ExecutionConfig.from_dict({**base.to_dict(),**extra["changes"]})
    if len(risks)*len(design["accuracy_intervals"])+len(extras)>120:raise ValueError("accuracy budget exceeded")
    timing=design["timing"]
    for name in ("repeats","warmup_calls","max_loops","order_seed","requested_blas_threads"):
        if isinstance(timing[name],bool) or not isinstance(timing[name],int):raise ValueError("timing fields must be integers")
    minimum=timing["min_batch_seconds"]
    if (not 2<=timing["repeats"]<=25 or not 1<=timing["warmup_calls"]<=20 or
        not 1<=timing["max_loops"]<=8192 or isinstance(minimum,bool) or not isinstance(minimum,Real) or
        not .0001<=minimum<=.1 or not np.isfinite(minimum) or timing["requested_blas_threads"]!=1 or
        not 0<=timing["order_seed"]<=2**32-1 or
        len(design["benchmark_intervals"])*7*timing["repeats"]*minimum>30):
        raise ValueError("timing budget or requested settings invalid")
    for value in design["acceptance"].values():
        if isinstance(value,bool) or not isinstance(value,Real) or not np.isfinite(value) or value<=0:raise ValueError("accuracy tolerances must be positive")
    return base

def coefficient(c):
    return c.risk_aversion*c.volatility**2*c.tau**2/c.impact

def closed_form_inventory(c):
    c.validate()
    value=coefficient(c)
    if value==0:return np.linspace(c.quantity,0,c.intervals+1)
    k=np.arange(c.intervals+1,dtype=float)
    gamma=2*np.arcsinh(np.sqrt(value)/2)
    # Exponential form avoids overflowing sinh(N*gamma); expm1 protects tiny coefficients.
    with np.errstate(over="raise",divide="raise",invalid="raise",under="ignore"):
        x=c.quantity*np.exp(-k*gamma)*(-np.expm1(-2*(c.intervals-k)*gamma))/(-np.expm1(-2*c.intervals*gamma))
    x[0]=c.quantity;x[-1]=0
    return x

def _vectors(c):
    m=c.intervals-1
    if m<1:raise ValueError("no interior variables")
    lower=-np.ones(m-1);diagonal=np.full(m,2+coefficient(c));upper=-np.ones(m-1)
    rhs=np.zeros(m);rhs[0]=c.quantity
    return lower,diagonal,upper,rhs

def _band(lower,diagonal,upper):
    a=np.zeros((3,len(diagonal)),order="F")
    a[0,1:]=upper;a[1]=diagonal;a[2,:-1]=lower
    return a

def _dense(lower,diagonal,upper):
    m=len(diagonal);a=np.zeros((m,m),order="F");np.fill_diagonal(a,diagonal)
    index=np.arange(m-1);a[index,index+1]=upper;a[index+1,index]=lower
    return a

def build_system(c):
    c.validate();lower,diagonal,upper,rhs=_vectors(c)
    band=_band(lower,diagonal,upper);dense=_dense(lower,diagonal,upper)
    return {"lower":lower,"diagonal":diagonal,"upper":upper,"rhs":rhs,"band":band,"dense":dense,
        "matrix_storage":{"thomas":lower.nbytes+diagonal.nbytes+upper.nbytes,"scipy_banded":band.nbytes,"scipy_dense_spd":dense.nbytes}}

def solve_prepared(system,method):
    if method=="thomas":return solve_tridiagonal(system["lower"],system["diagonal"],system["upper"],system["rhs"])
    if method=="scipy_banded":return solve_banded((1,1),system["band"],system["rhs"],overwrite_ab=False,overwrite_b=False,check_finite=True)
    if method=="scipy_dense_spd":return solve(system["dense"],system["rhs"],assume_a="pos",lower=True,overwrite_a=False,overwrite_b=False,check_finite=True)
    raise ValueError("unknown method")

def solve_inventory(c,method):
    if method not in METHODS:raise ValueError("unknown method")
    if method=="thomas":return continuous_inventory(c)
    c.validate()
    if c.intervals==1:return np.array([c.quantity,0.])
    if coefficient(c)==0:return np.linspace(c.quantity,0,c.intervals+1)
    lower,diagonal,upper,rhs=_vectors(c)
    if method=="scipy_banded":
        interior=solve_banded((1,1),_band(lower,diagonal,upper),rhs,overwrite_ab=False,overwrite_b=False,check_finite=True)
    else:
        interior=solve(_dense(lower,diagonal,upper),rhs,assume_a="pos",lower=True,overwrite_a=False,overwrite_b=False,check_finite=True)
    return np.concatenate(([c.quantity],interior,[0.]))

def objective(c,inventory):
    n=-np.diff(inventory)
    mean=float(c.impact/c.tau*np.dot(n,n))
    variance=float(c.volatility**2*c.tau*np.dot(inventory[1:],inventory[1:]))
    return mean,variance,mean+c.risk_aversion*variance

def evaluate_accuracy(c,method,acceptance=None):
    if acceptance is None:acceptance={"normalized_inventory_max_error":1e-8,"relative_objective_error":1e-8,"normalized_backward_error":1e-10}
    x=solve_inventory(c,method);reference=closed_form_inventory(c)
    mean,var,j=objective(c,x);_,_,jr=objective(c,reference)
    forward=float(np.max(np.abs(x-reference))/c.quantity)
    relative_j=abs(j-jr)/max(abs(jr),1e-300)
    condition=None;backward=0.
    if c.intervals>1:
        lower,diagonal,upper,rhs=_vectors(c);interior=x[1:-1]
        residual=diagonal*interior-rhs
        residual[1:]+=lower*interior[:-1];residual[:-1]+=upper*interior[1:]
        row_norm=np.abs(diagonal).copy()
        row_norm[1:]+=np.abs(lower);row_norm[:-1]+=np.abs(upper)
        denominator=float(row_norm.max()*np.max(np.abs(interior))+np.max(np.abs(rhs)))
        backward=float(np.max(np.abs(residual))/denominator) if denominator else 0.
        angle=np.pi/(2*c.intervals);coef=coefficient(c)
        condition=float((coef+4*np.cos(angle)**2)/(coef+4*np.sin(angle)**2))
    feasible=bool(np.isfinite(x).all() and x[0]==c.quantity and x[-1]==0 and np.all(x>=0) and np.all(np.diff(x)<=1e-12*c.quantity))
    passed=feasible and forward<=acceptance["normalized_inventory_max_error"] and relative_j<=acceptance["relative_objective_error"] and backward<=acceptance["normalized_backward_error"]
    return {"method":method,"config":c.to_dict(),"coefficient":coefficient(c),
        "normalized_inventory_max_error":forward,"relative_objective_error":relative_j,
        "normalized_backward_error":backward,"analytic_condition_number_2":condition,
        "expected_cost":mean,"variance":var,"objective":j,"reference_objective":jr,
        "feasible":feasible,"passed":bool(passed)},{"inventory":x,"closed_form":reference}

def runtime_info():
    records=[]
    if platform.system()=="Windows":
        for package in (np,scipy):
            folder=Path(package.__file__).resolve().parent.parent/(package.__name__+".libs")
            for path in folder.glob("*openblas*.dll"):
                record={"package":package.__name__,"library":path.name,"actual_threads":None}
                try:
                    library=ctypes.CDLL(str(path))
                    for symbol in ("scipy_openblas_get_num_threads64_","scipy_openblas_get_num_threads","openblas_get_num_threads64_","openblas_get_num_threads"):
                        try:getter=getattr(library,symbol)
                        except AttributeError:continue
                        getter.argtypes=[];getter.restype=ctypes.c_int
                        record.update(symbol=symbol,actual_threads=getter());break
                except OSError:pass
                records.append(record)
    known=[r["actual_threads"] for r in records if r["actual_threads"] is not None]
    if any(v!=1 for v in known):raise RuntimeError("Start a fresh process with BLAS thread variables set to 1 before imports")
    info=time.get_clock_info("perf_counter")
    return {"processor":platform.processor(),"architecture":platform.machine(),"logical_cpu_count":os.cpu_count(),
        "thread_requests":{k:os.environ.get(k) for k in ("OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS")},
        "blas_runtime":records,"actual_blas_threads_verified":len(known)>=2 and all(v==1 for v in known),
        "clock":{"implementation":info.implementation,"resolution_seconds":info.resolution,"monotonic":info.monotonic},
        "matrix_layout":"Fortran-contiguous dense and band arrays; contiguous diagonal/RHS vectors",
        "finite_checks_enabled_for_all_methods":True}

def _calibrate(timer,minimum,max_loops):
    loops=1
    while True:
        elapsed=timer.timeit(loops)
        if elapsed>=minimum or loops==max_loops:return loops,elapsed
        loops=min(loops*2,max_loops)

def run_study(design,*,measure=True):
    base=validate_design(design);environment=runtime_info()
    accuracy=[];raw={};specs=[]
    for n in design["accuracy_intervals"]:
        for risk in design["accuracy_risk_aversions"]:
            specs.append((f"N{n}_lambda{risk:g}",ExecutionConfig.from_dict({**base.to_dict(),"intervals":n,"risk_aversion":risk})))
    for e in design["accuracy_extra_cases"]:
        specs.append((e["name"],ExecutionConfig.from_dict({**base.to_dict(),**e["changes"]})))
    for index,(name,c) in enumerate(specs):
        case_id=f"case_{index:03d}";reference=closed_form_inventory(c);raw[case_id+"_closed_form"]=reference
        for method in METHODS:
            record,arrays=evaluate_accuracy(c,method,design["acceptance"])
            accuracy.append({**record,"case_id":case_id,"case_name":name})
            raw[case_id+"_"+method]=arrays["inventory"]
            if not record["passed"]:raise AssertionError(f"accuracy threshold failed: {name}, {method}")
    timings=[];storage=[];orders=[]
    rng=np.random.default_rng(design["timing"]["order_seed"])
    for n in design["benchmark_intervals"]:
        c=ExecutionConfig.from_dict({**base.to_dict(),"intervals":n});system=build_system(c)
        snapshot={k:hashlib.sha256(v.tobytes()).hexdigest() for k,v in system.items() if isinstance(v,np.ndarray)}
        for method in METHODS:
            storage.append({"intervals":n,"interior_unknowns":n-1,"method":method,"matrix_input_bytes":system["matrix_storage"][method],
                "rhs_input_bytes":system["rhs"].nbytes,"solution_bytes":system["rhs"].nbytes,
                "memory_scope":"Input representation only; excludes solver copies, workspace and process peak RAM"})
        if not measure:continue
        jobs=[]
        for scope in ("prepared_system","inventory_end_to_end"):
            for method in METHODS:
                callback=(lambda method=method:solve_prepared(system,method)) if scope=="prepared_system" else (lambda method=method,c=c:solve_inventory(c,method))
                jobs.append((scope,method,callback))
        jobs.append(("product_integer_schedule","original_make_ac",lambda c=c:make_ac(c,integer=True)))
        active=[]
        for scope,method,callback in jobs:
            for _ in range(design["timing"]["warmup_calls"]):callback()
            timer=timeit.Timer(callback)
            loops,calibration=_calibrate(timer,design["timing"]["min_batch_seconds"],design["timing"]["max_loops"])
            active.append({"scope":scope,"method":method,"timer":timer,"loops":loops,"calibration_seconds":calibration,"samples":[]})
        for repeat in range(design["timing"]["repeats"]):
            order=rng.permutation(len(active)).tolist()
            orders.append({"intervals":n,"repeat":repeat,"job_order":[f"{active[i]['scope']}:{active[i]['method']}" for i in order]})
            for index in order:
                job=active[index];job["samples"].append(job["timer"].timeit(job["loops"])/job["loops"])
        for job in active:
            samples=np.array(job["samples"])
            timings.append({"intervals":n,"interior_unknowns":n-1,"scope":job["scope"],"method":job["method"],"loops":job["loops"],
                "calibration_seconds":job["calibration_seconds"],"seconds_per_call":job["samples"],
                "median_seconds":float(np.median(samples)),"q25_seconds":float(np.quantile(samples,.25)),
                "q75_seconds":float(np.quantile(samples,.75)),"min_seconds":float(samples.min()),"max_seconds":float(samples.max())})
        for key,digest in snapshot.items():
            if hashlib.sha256(system[key].tobytes()).hexdigest()!=digest:raise AssertionError("prepared inputs mutated")
    fits={}
    for scope in ("prepared_system","inventory_end_to_end","product_integer_schedule"):
        methods=METHODS if scope!="product_integer_schedule" else ("original_make_ac",)
        for method in methods:
            rows=[r for r in timings if r["scope"]==scope and r["method"]==method and r["intervals"]>=100]
            fits[scope+":"+method]=float(np.polyfit(np.log([r["interior_unknowns"] for r in rows]),np.log([r["median_seconds"] for r in rows]),1)[0]) if len(rows)>=3 else None
    provenance=_provenance();provenance["study_source_sha256"]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return {"schema_version":"1.0","study_name":"Execution solver accuracy and local performance","design":design,"provenance":provenance,
        "environment":environment,"accuracy_case_count":len(specs),"accuracy":accuracy,"timings":timings,"timing_orders":orders,
        "input_storage":storage,"descriptive_loglog_slopes":fits,
        "verification":{"all_accuracy_cases_passed":all(r["passed"] for r in accuracy),
            "max_normalized_inventory_error":max(r["normalized_inventory_max_error"] for r in accuracy),
            "max_relative_objective_error":max(r["relative_objective_error"] for r in accuracy),
            "max_normalized_backward_error":max(r["normalized_backward_error"] for r in accuracy),
            "prepared_inputs_preserved":True,
            "all_repeats_retained":all(len(r["seconds_per_call"])==design["timing"]["repeats"] for r in timings),
            "timings_are_measurements_not_deterministic_outputs":True}},raw

def _write_json(path,value):path.write_text(json.dumps(value,indent=2,allow_nan=False)+"\n",encoding="utf-8",newline="\n")

def export_study(study,raw,output,*,figures=True):
    output=Path(output)
    if output.exists() and any(output.iterdir()):raise FileExistsError("choose a new or empty output directory")
    output.mkdir(parents=True,exist_ok=True)
    _write_json(output/"results.json",study);_write_json(output/"design.json",study["design"])
    np.savez_compressed(output/"solutions.npz",**raw)
    fields=["intervals","interior_unknowns","scope","method","loops","repeat","seconds_per_call"]
    with (output/"timing-samples.csv").open("w",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fields,lineterminator="\n");writer.writeheader()
        for r in study["timings"]:
            for repeat,seconds in enumerate(r["seconds_per_call"]):
                writer.writerow({k:r[k] for k in fields[:5]}|{"repeat":repeat,"seconds_per_call":seconds})
    fields=["case_id","case_name","method","normalized_inventory_max_error","relative_objective_error","normalized_backward_error","analytic_condition_number_2","expected_cost","variance","objective","passed"]
    with (output/"accuracy.csv").open("w",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fields,lineterminator="\n");writer.writeheader()
        for r in study["accuracy"]:writer.writerow({k:r[k] for k in fields})
    (output/"research-note.md").write_text(research_note(study),encoding="utf-8",newline="\n")
    if figures:render_figures(study,output)
    _write_json(output/"manifest.json",{"sha256":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.iterdir()) if p.is_file()}})
    return output

def render_figures(study,output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size":10,"axes.spines.top":False,"axes.spines.right":False,"figure.dpi":140})
    colors={"thomas":"tab:blue","scipy_banded":"tab:orange","scipy_dense_spd":"tab:green"}
    fig,axes=plt.subplots(1,2,figsize=(12,4.7),layout="constrained")
    for ax,scope,title in [(axes[0],"prepared_system","Prepared system: solve, copies and finite checks"),(axes[1],"inventory_end_to_end","Configuration to continuous inventory")]:
        for method in METHODS:
            rows=[r for r in study["timings"] if r["scope"]==scope and r["method"]==method]
            if not rows:continue
            n=[r["intervals"] for r in rows];median=np.array([r["median_seconds"] for r in rows])*1e6
            low=np.array([r["q25_seconds"] for r in rows])*1e6;high=np.array([r["q75_seconds"] for r in rows])*1e6
            ax.loglog(n,median,"o-",label=method.replace("_"," "),color=colors[method])
            ax.fill_between(n,low,high,color=colors[method],alpha=.15)
        ax.set(xlabel="Execution intervals N",ylabel="Microseconds per call",title=title)
        ax.legend(fontsize=8)
    fig.suptitle("Local medians; shading: IQR across retained timing batches")
    fig.savefig(output/"01-runtime-scaling.png");plt.close(fig)

    fig,ax=plt.subplots(figsize=(9,4.8),layout="constrained")
    for method in METHODS:
        rows=[r for r in study["input_storage"] if r["method"]==method]
        ax.loglog([r["intervals"] for r in rows],[r["matrix_input_bytes"]/1024 for r in rows],"o-",label=method.replace("_"," "),color=colors[method])
    ax.set(xlabel="Execution intervals N",ylabel="Matrix input storage (KiB)",title="Linear versus quadratic input representations\nExcludes RHS, copies, native workspace and process peak memory")
    ax.legend(fontsize=9);fig.savefig(output/"02-input-storage.png");plt.close(fig)

    fig,axes=plt.subplots(1,2,figsize=(12,4.7),layout="constrained")
    for ax,field,title in [(axes[0],"normalized_inventory_max_error","Inventory error versus stable closed form"),(axes[1],"normalized_backward_error","Normalized equation residual")]:
        for method in METHODS:
            rows=[r for r in study["accuracy"] if r["method"]==method]
            ax.semilogy(range(len(rows)),[max(r[field],1e-18) for r in rows],".",label=method.replace("_"," "),color=colors[method])
        ax.axhline(study["design"]["acceptance"][field],color="black",ls="--",lw=1,label="Prespecified tolerance")
        ax.set(xlabel="Prespecified accuracy case index",ylabel=field.replace("_"," "),title=title)
        ax.legend(fontsize=8)
    fig.suptitle("Zeros displayed at 1e-18 only for log-axis plotting; raw zeros retained")
    fig.savefig(output/"03-numerical-accuracy.png");plt.close(fig)

    fig,ax=plt.subplots(figsize=(9,4.7),layout="constrained")
    rows=[r for r in study["timings"] if r["scope"]=="inventory_end_to_end" and r["method"]=="thomas"]
    product=[r for r in study["timings"] if r["scope"]=="product_integer_schedule"]
    if rows:ax.loglog([r["intervals"] for r in rows],[r["median_seconds"]*1e6 for r in rows],"o-",label="Original continuous inventory")
    if product:ax.loglog([r["intervals"] for r in product],[r["median_seconds"]*1e6 for r in product],"s-",label="Original full integer schedule")
    ax.set(xlabel="Execution intervals N",ylabel="Microseconds per call",title="Separate solver work from rounding and validation\nFull integer plan includes largest-remainder sorting")
    ax.legend(fontsize=9);fig.savefig(output/"04-product-pipeline.png");plt.close(fig)

def research_note(study):
    lines=["# Execution solver: numerical accuracy and local performance","",
        "## Question and financial system","",
        "Does the reference optimizer agree with independent numerical and closed-form solutions, and how do solve time and input storage grow as the fixed execution horizon is divided into more intervals?",
        "For interior inventory y=(x_1,...,x_(N-1)), the first-order condition is Ay=b, with diagonal 2+c, adjacent diagonals -1, b_1=Q, and c=lambda*sigma^2*tau^2/eta. The matrix is symmetric positive definite for c>=0. Inventory endpoints are Q and zero. The objective is temporary-impact cost plus lambda times cost variance.",
        "This solver computes continuous quantities. Largest-remainder integerization is a separate feasible approximation; a fast linear solve does not imply every step of the full product has linear complexity.","",
        "## Three methods and independent accuracy reference","",
        "Compare the original Python Thomas elimination, SciPy solve_banded with fixed lower/upper bandwidth one, and an explicitly dense positive-definite solve (assume_a='pos'). Both library methods preserve inputs and retain finite checks. Explicit dense mode avoids automatic structure detection. [SciPy banded solver](https://docs.scipy.org/doc/scipy-1.16.2/reference/generated/scipy.linalg.solve_banded.html), [SciPy dense solver](https://docs.scipy.org/doc/scipy-1.16.2/reference/generated/scipy.linalg.solve.html).",
        "For c>0, gamma=2*asinh(sqrt(c)/2) and x_k=Q*sinh((N-k)*gamma)/sinh(N*gamma). Evaluate this with exp and expm1 to avoid overflow or cancellation. At c=0 use Q*(1-k/N). This is a mathematical reference, not another call to the tested elimination.",
        "Record maximum inventory error normalized by Q, relative financial-objective error, and infinity-norm backward error ||Ay-b||/(||A||*||y||+||b||). The analytic condition number uses extremal eigenvalues c+4*sin²(pi/(2N)) and c+4*cos²(pi/(2N)). A small residual alone cannot guarantee small forward error in a poorly conditioned system.",
        f"Accuracy design: {study['accuracy_case_count']} conditions across three methods, including N=1, zero preference/volatility, weak and strong coefficients and a large order. Thresholds are fixed in design.json. All passed: {study['verification']['all_accuracy_cases_passed']}. Maximum normalized inventory error: {study['verification']['max_normalized_inventory_error']:.3g}; maximum relative objective error: {study['verification']['max_relative_objective_error']:.3g}; maximum normalized backward error: {study['verification']['max_normalized_backward_error']:.3g}.","",
        "## Timing protocol","",
        "Two comparable scopes: prebuilt matrix solve (including solver copies and finite checks), and configuration-to-continuous-inventory (including validation, allocation, representation construction and boundary assembly). A third scope times the unchanged original make_ac integer-plan pipeline only. Import/setup and file/plot creation are excluded.",
        f"Sizes: {study['design']['benchmark_intervals']}. Warmups: {study['design']['timing']['warmup_calls']}; repeated batches: {study['design']['timing']['repeats']}. Loop counts are calibrated to the same minimum batch duration and capped; order is deterministically shuffled each repeat. Report medians and IQR, keep all samples and outliers. IQR is not a confidence interval. [Python timing documentation](https://docs.python.org/3.12/library/timeit.html).",
        f"Thread requests are one; actual BLAS threads verified: {study['environment']['actual_blas_threads_verified']}. Hardware/runtime and clock metadata are in results.json, with no hostname or user paths. Finite checks remain enabled; dense/band arrays are Fortran-contiguous.",
        "Timing measurements include operating-system scheduling and hardware/cache effects. Exact runtimes will vary between runs; numerical solutions and representation sizes are reproducible. Descriptive finite-size log-log slopes do not prove asymptotic complexity. Algorithmic operation counts give linear work for fixed-bandwidth elimination and cubic work for generic dense Cholesky; full integerization includes sorting.","",
        "## Local runtime medians (microseconds)","",
        "| N | Thomas prepared | Banded prepared | Dense SPD prepared | Original full integer plan |","|---:|---:|---:|---:|---:|"]
    for n in study["design"]["benchmark_intervals"]:
        def get(scope,method):
            found=next((r for r in study["timings"] if r["intervals"]==n and r["scope"]==scope and r["method"]==method),None)
            return "not measured" if found is None else f"{found['median_seconds']*1e6:.2f}"
        lines.append(f"| {n} | {get('prepared_system','thomas')} | {get('prepared_system','scipy_banded')} | {get('prepared_system','scipy_dense_spd')} | {get('product_integer_schedule','original_make_ac')} |")
    lines += ["","## Memory representation and interpretation","",
        "Storage numbers are actual input-array nbytes: Thomas diagonals 8*(3m-2), band storage 8*3m, and dense storage 8*m², where m=N-1. The RHS and solution each require another 8m bytes. These are not process peak RAM, temporary allocation totals or native solver workspace.",
        "The specialized structure avoids allocating a dense quadratic matrix. Nevertheless compiled library constants can make the banded library faster than a Python implementation of the same asymptotic complexity. Do not equate personal implementation with universal speed superiority, or infer financial performance from solver timing.",
        f"Descriptive slopes over measured N>=100: {study['descriptive_loglog_slopes']}. Limited sizes, overhead and hardware effects constrain their interpretation.",
        "","## Reproducibility and limits","",
        "Solutions, closed-form references, financial metrics, matrices' representation sizes, all calibration counts and raw timings are retained with source/runtime/input digests. Repeat numerical checks independently; timing data are deliberately not asserted byte-identical. Original core source remains unchanged.",
        "This is a local benchmark with maximum N=1000 under the original model limits. It does not establish real-market latency, benchmark every solver, measure peak native memory, or change the financial model. All methods optimize the same continuous mathematical objective; integerized feasibility is distinct from global integer optimality.",""]
    return "\n".join(lines)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--design",type=Path,required=True);parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):parser.error("choose a new or empty output directory")
    source=args.design.read_bytes();study,raw=run_study(json.loads(source))
    study["provenance"]["prespecified_input_sha256"]=hashlib.sha256(source).hexdigest()
    export_study(study,raw,args.output)
    print(json.dumps({"accuracy_cases":study["accuracy_case_count"],"timing_rows":len(study["timings"]),
        "environment_threads_verified":study["environment"]["actual_blas_threads_verified"],"verification":study["verification"]},allow_nan=False))
if __name__=="__main__":main()
