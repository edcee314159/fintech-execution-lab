"""Integer participation quotas and a certified continuous arrival-cost relaxation."""
from decimal import Decimal,localcontext,ROUND_FLOOR
from numbers import Real,Integral
import math
import numpy as np
from scipy.optimize import minimize
from execution_lab.types import Schedule
from execution_lab.schedule import validate_schedule
from execution_research.studies.volume.volume_benchmark import normalize_volume

def participation_limits(config,market_volumes,participation_rate):
    config.validate()
    r=participation_rate
    if isinstance(r,(bool,np.bool_)) or not isinstance(r,Real) or not math.isfinite(r) or not 0<r<=1:
        raise ValueError("participation rate must be finite in (0,1]")
    original=np.asarray(market_volumes,dtype=object)
    if original.shape!=(config.intervals,) or any(isinstance(v,(bool,np.bool_)) or not isinstance(v,Real) for v in original):
        raise ValueError("one numeric market volume per interval required")
    volumes=np.asarray(original,dtype=float)
    if not np.isfinite(volumes).all() or np.any(volumes<0) or np.any(volumes>1e12):
        raise ValueError("market volumes must be finite, nonnegative and at most 1e12 per interval")
    with localcontext() as ctx:
        ctx.prec=50
        quotas=[Decimal(str(r))*Decimal(str(v)) for v in original]
        total=sum(quotas,Decimal(0))
        caps=np.array([int(q.to_integral_value(rounding=ROUND_FLOOR)) for q in quotas],dtype=np.int64)
        continuous_ok=total>=config.quantity
    integer_total=sum(int(v) for v in caps);feasible=integer_total>=config.quantity
    return {"caps":caps,"feasible":feasible,"reason":"feasible" if feasible else ("integer_rounding_shortage" if continuous_ok else "continuous_capacity_shortage"),
        "raw_capacity_total":float(total),"integer_capacity_total":integer_total,
        "shortfall_shares":max(0,config.quantity-integer_total)}

def _inputs(values,quantity,caps):
    if isinstance(quantity,bool) or not isinstance(quantity,Integral) or not 1<=quantity<=10_000_000:
        raise ValueError("quantity must be a positive integer at most 10 million")
    raw=np.asarray(caps,dtype=object)
    if raw.ndim!=1 or not len(raw) or len(raw)>1000 or any(isinstance(v,(bool,np.bool_)) or not isinstance(v,Integral) or not 0<=v<=10**12 for v in raw):
        raise ValueError("caps must be nonnegative integers")
    cap=np.array(raw,dtype=np.int64)
    if sum(int(v) for v in cap)<quantity:raise ValueError("insufficient integer capacity")
    original=np.asarray(values,dtype=object)
    if original.shape!=cap.shape or any(isinstance(v,(bool,np.bool_)) or not isinstance(v,Real) for v in original):
        raise ValueError("one numeric quantity per cap required")
    q=np.asarray(values,dtype=float)
    if not np.isfinite(q).all() or np.any(q<0) or not math.isclose(math.fsum(float(v) for v in q),quantity,rel_tol=1e-12,abs_tol=1e-8):
        raise ValueError("target must be nonnegative and conserve quantity")
    return q,cap

def _repair_sum(q,quantity,cap):
    q=np.clip(np.asarray(q,dtype=float),0,cap)
    for _ in range(3):
        residual=float(quantity)-math.fsum(float(v) for v in q)
        if residual==0:break
        room=cap-q if residual>0 else q
        index=int(np.argmax(room))
        if room[index]+1e-10<abs(residual):raise ArithmeticError("cannot repair total within caps")
        q[index]+=residual
    if np.any(q<0) or np.any(q>cap) or abs(math.fsum(float(v) for v in q)-quantity)>1e-8:
        raise ArithmeticError("feasibility repair failed")
    return q

def project_target(target,quantity,caps):
    q,cap=_inputs(target,quantity,caps)
    if int(cap.sum())==quantity:return cap.astype(float)
    low=float(np.min(-q));high=float(np.max(np.minimum(cap,quantity)-q))
    for _ in range(100):
        theta=(low+high)/2
        if np.clip(q+theta,0,cap).sum()<quantity:low=theta
        else:high=theta
    return _repair_sum(np.clip(q+(low+high)/2,0,cap),quantity,cap)

def round_capped(continuous,quantity,caps):
    q,cap=_inputs(continuous,quantity,caps)
    if np.any(q>cap+1e-8):raise ValueError("continuous plan exceeds capacity")
    q=_repair_sum(q,quantity,cap)
    result=np.minimum(np.floor(q).astype(np.int64),cap)
    left=quantity-int(result.sum());fractions=np.round(q-result,12)
    order=np.lexsort((np.arange(len(q)),-fractions));eligible=[k for k in order if result[k]<cap[k]]
    if not 0<=left<=len(eligible):raise ArithmeticError("invalid capped rounding remainder")
    result[eligible[:left]]+=1
    if result.sum()!=quantity or np.any(result>cap):raise ArithmeticError("integer feasibility failed")
    return result

def _schedule(config,name,q,caps):
    quantities=round_capped(q,config.quantity,caps)
    inventory=np.r_[np.cumsum(quantities[::-1])[::-1],0.]
    s=Schedule(name,quantities,inventory,True);validate_schedule(s,config)
    return s

def make_capped_twap(config,caps):
    config.validate()
    q=project_target(np.full(config.intervals,config.quantity/config.intervals),config.quantity,caps)
    return _schedule(config,"twap_capped",q,caps)

def make_capped_volume(config,forecast,caps):
    config.validate();v=normalize_volume(forecast,config.intervals)
    q=project_target(config.quantity*v,config.quantity,caps)
    return _schedule(config,"volume_capped",q,caps)

def arrival_matrix(config):
    config.validate();n=config.intervals
    remaining=np.triu(np.ones((n,n)),1)
    return np.eye(n)*(config.impact/config.tau)+config.risk_aversion*config.volatility**2*config.tau*(remaining.T@remaining)

def linear_minimizer(gradient,caps,quantity):
    remaining=float(quantity);q=np.zeros(len(caps))
    for k in np.argsort(gradient,kind="stable"):
        q[k]=min(float(caps[k]),remaining);remaining-=q[k]
        if remaining<=0:break
    if remaining>1e-8:raise ValueError("infeasible linear oracle")
    return q

def _polish(y,h,upper):
    # Refine the SLSQP active set, including release of falsely active bounds.
    # A near-zero SLSQP coordinate is not proof that its lower bound is optimal.
    y=y.copy();lower=y<=1e-9;higher=((upper-y)<=1e-9)&~lower
    tolerance=64*np.finfo(float).eps*max(1.,float(np.max(np.abs(h@y))))
    for _ in range(20*len(y)**2):
        free=~(lower|higher)
        if not free.any():
            lows=np.flatnonzero(lower&(upper>0));highs=np.flatnonzero(higher)
            if not len(lows) or not len(highs):return y
            g=h@y;lo=lows[np.argmin(g[lows])];hi=highs[np.argmax(g[highs])]
            if g[lo]>=g[hi]-tolerance:return y
            lower[lo]=False;higher[hi]=False;continue
        candidate=np.zeros(len(y));candidate[higher]=upper[higher];fixed=~free
        hf=h[np.ix_(free,free)]
        rhs=np.column_stack((-h[np.ix_(free,fixed)]@candidate[fixed],np.ones(free.sum())))
        solved=np.linalg.solve(hf,rhs);base,weight=solved[:,0],solved[:,1]
        mu=(base.sum()-(1-candidate[fixed].sum()))/weight.sum()
        candidate[free]=base-mu*weight
        direction=candidate-y;alpha=1.;hit=None;side=None
        for index in np.flatnonzero(free):
            if candidate[index]<-1e-12 and direction[index]<0:
                step=-y[index]/direction[index]
                if step<alpha:alpha=step;hit=index;side="low"
            elif candidate[index]>upper[index]+1e-12 and direction[index]>0:
                step=(upper[index]-y[index])/direction[index]
                if step<alpha:alpha=step;hit=index;side="high"
        if hit is not None:
            y+=max(0.,alpha)*direction
            if side=="low":y[hit]=0.;lower[hit]=True
            else:y[hit]=upper[hit];higher[hit]=True
            continue
        y=_repair_sum(candidate,1.,upper);reduced=h@y+mu
        violations=np.zeros(len(y))
        violations[lower&(upper>0)]=np.maximum(-reduced[lower&(upper>0)],0)
        violations[higher]=np.maximum(reduced[higher],0)
        index=int(np.argmax(violations))
        if violations[index]<=tolerance:return y
        lower[index]=False;higher[index]=False
    raise ArithmeticError("KKT active-set refinement did not converge")

def solve_constrained(config,caps):
    config.validate();n=config.intervals;quantity=config.quantity
    _,cap=_inputs(np.full(n,quantity/n),quantity,caps)
    if len(cap)!=n:raise ValueError("capacity dimensions differ from config")
    h_original=arrival_matrix(config);scale=float(np.diag(h_original).max());h=h_original/scale
    upper=np.minimum(cap,quantity)/quantity
    if int(cap.sum())==quantity:
        y=cap/quantity;message="singleton feasible set";iterations=0
    else:
        start=project_target(np.full(n,quantity/n),quantity,cap)/quantity
        result=minimize(lambda z:float(z@h@z),start,jac=lambda z:2*h@z,method="SLSQP",
            bounds=list(zip(np.zeros(n),upper)),
            constraints={"type":"eq","fun":lambda z:float(z.sum()-1),"jac":lambda z:np.ones(n)},
            options={"ftol":1e-13,"maxiter":1000})
        if not result.success:raise ArithmeticError("continuous optimizer failed: "+str(result.message))
        y=_repair_sum(result.x,1.,upper);y=_polish(y,h,upper)
        message=str(result.message);iterations=int(result.nit)
    q=_repair_sum(y*quantity,quantity,cap)
    gradient=2*h_original@q
    oracle=linear_minimizer(gradient,cap,quantity)
    objective=float(q@h_original@q)
    raw_gap=float(gradient@(q-oracle))
    tolerance=128*np.finfo(float).eps*max(1.,abs(objective),float(np.sum(np.abs(gradient*q))),float(np.sum(np.abs(gradient*oracle))))
    if raw_gap < -tolerance:raise ArithmeticError("negative convex certificate gap exceeds roundoff")
    gap=max(0.,raw_gap)+tolerance
    if gap>max(1e-6,1e-7*objective):raise ArithmeticError(f"continuous certificate too loose: gap={gap}, objective={objective}")
    certificate={"objective":objective,"gap":gap,"lower_bound":objective-gap,
        "gap_roundoff_allowance":tolerance,"certificate":"Convex gradient lower bound over the box-and-sum feasible set",
        "solver":"SciPy SLSQP with analytic gradient and active-set KKT refinement","iterations":iterations,"message":message,
        "max_capacity_violation":float(np.maximum(q-cap,0).max()),"total_quantity_error":float(abs(q.sum()-quantity))}
    schedule=_schedule(config,"arrival_constrained",q,cap)
    x=schedule.inventory
    integer_objective=float(config.impact/config.tau*np.dot(schedule.quantities,schedule.quantities)+config.risk_aversion*config.volatility**2*config.tau*np.dot(x[1:],x[1:]))
    if integer_objective<certificate["lower_bound"]-1e-7:raise AssertionError("integer objective below certified bound")
    certificate["integer_objective"]=integer_objective
    certificate["integer_suboptimality_upper_bound"]=integer_objective-certificate["lower_bound"]
    return schedule,{"continuous_quantities":q,"certificate":certificate}
