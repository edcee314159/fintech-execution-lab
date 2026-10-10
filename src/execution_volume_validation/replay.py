"""After-event volume-cap replay; close-price marks are assumed diagnostics."""
from decimal import Decimal,ROUND_FLOOR
from numbers import Integral,Real
import math
import numpy as np


def _integer_vector(values,label):
    raw=np.asarray(values,dtype=object)
    if raw.ndim!=1 or not len(raw) or any(isinstance(x,(bool,np.bool_)) or not isinstance(x,Integral) or not 0<=x<=10**12 for x in raw):raise ValueError(f"{label} must be nonnegative integers")
    return np.array(raw,dtype=np.int64)


def replay_schedule(quantities,volumes,participation_rate):
    q=_integer_vector(quantities,"quantities");v=_integer_vector(volumes,"volumes")
    r=participation_rate
    if q.shape!=v.shape or isinstance(r,(bool,np.bool_)) or not isinstance(r,Real) or not math.isfinite(r) or not 0<r<=1:raise ValueError("matching arrays and participation rate in (0,1] required")
    total=sum(map(int,q))
    if not 1<=total<=10_000_000:raise ValueError("order must contain 1 to 10 million shares")
    caps=np.array([int((Decimal(str(r))*Decimal(int(x))).to_integral_value(rounding=ROUND_FLOOR)) for x in v],dtype=np.int64)
    fills=np.zeros_like(q);released=0;executed=0
    for k in range(len(q)):
        released+=int(q[k]);fills[k]=min(released-executed,int(caps[k]));executed+=int(fills[k])
    maximum=min(total,sum(map(int,caps)));residual=total-executed
    return {"caps":caps,"fills":fills,"remaining":total-np.r_[0,np.cumsum(fills)],"residual":residual,
            "completion_fraction":executed/total,"complete":residual==0,"planned_cap_violations":int(np.count_nonzero(q>caps)),
            "planned_excess_shares":int(np.maximum(q-caps,0).sum()),"maximum_capacity_fill":maximum,
            "unavoidable_capacity_shortfall":total-maximum,"avoidable_residual":maximum-executed}


def price_diagnostic(quantity,arrival_price,fills,prices,impact,tau):
    q=_integer_vector(fills,"fills");p=np.asarray(prices,dtype=float)
    if isinstance(quantity,bool) or not isinstance(quantity,Integral) or quantity<1 or q.sum()>quantity:raise ValueError("valid full-order quantity required")
    if p.shape!=q.shape or not np.isfinite(p).all() or np.any(p<=0):raise ValueError("positive finite close prices required")
    if any(isinstance(x,bool) or not isinstance(x,Real) or not math.isfinite(x) for x in (arrival_price,impact,tau)) or arrival_price<=0 or impact<0 or tau<=0:raise ValueError("valid price, impact and interval length required")
    residual=int(quantity-q.sum());executed=float(np.dot(q,arrival_price-p));mark=float(residual*(arrival_price-p[-1]));assumed=float(impact/tau*np.dot(q.astype(float),q.astype(float)))
    return {"executed_price_shortfall":executed,"residual_mark_shortfall":mark,"assumed_impact":assumed,
            "marked_total_shortfall":executed+mark+assumed,"marked_total_bps":(executed+mark+assumed)/(quantity*arrival_price)*10000,
            "residual_shares":residual,"completed":residual==0,
            "interpretation":"Assumed fills at observed interval Close, hypothetical constant impact; residual marked, not filled. Not realized execution cost."}
