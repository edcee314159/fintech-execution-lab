"""Untuned, past-only, five-session predictors and shared order sizing."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_FLOOR
from numbers import Real
import math
import numpy as np
from .data import Day

PREDICTORS=("uniform", "historical_shape", "previous_day")

@dataclass(frozen=True)
class Forecast:
    predictor: str
    volume: np.ndarray
    train_dates: tuple[str,...]
    adv: float
    volatility: float
    training_price: float


def predict(history: list[Day], target_date: date, predictor: str, lookback: int=5) -> Forecast:
    if predictor not in PREDICTORS:raise ValueError("unknown predictor")
    if isinstance(lookback,bool) or not isinstance(lookback,int) or lookback<1:raise ValueError("lookback must be positive integer")
    if len(history)<lookback:raise ValueError(f"at least {lookback} history sessions required")
    if any(d.day>=target_date for d in history):raise ValueError("training must be strictly in the past")
    if len({d.day for d in history})!=len(history) or len({d.symbol for d in history})!=1:raise ValueError("unique dates for one symbol required")
    h=sorted(history,key=lambda d:d.day)[-lookback:]
    volumes=np.array([d.volume for d in h],dtype=float)
    prices=np.array([d.close for d in h],dtype=float)
    if volumes.shape!=(lookback,78) or prices.shape!=(lookback,78) or not np.isfinite(volumes).all() or np.any(volumes<0):raise ValueError("78 finite nonnegative volumes required")
    totals=volumes.sum(axis=1)
    if np.any(totals<=0):raise ValueError("positive training daily volumes required")
    if not np.isfinite(prices).all() or np.any(prices<=0):raise ValueError("positive finite training prices required")
    adv=float(totals.mean())
    if predictor=="uniform":forecast=np.full(78,adv/78)
    elif predictor=="historical_shape":forecast=(volumes/totals[:,None]).mean(axis=0)*adv
    else:forecast=volumes[-1].copy()
    volatility=float(np.sqrt(np.mean(np.diff(prices,axis=1)**2)/5))
    return Forecast(predictor,forecast,tuple(d.day.isoformat() for d in h),adv,volatility,float(np.mean([d.open_price for d in h])))


def order_quantity(adv: float, fraction: float) -> int:
    if any(isinstance(x,bool) or not isinstance(x,Real) or not math.isfinite(x) for x in (adv,fraction)) or adv<=0 or not 0<fraction<=1:raise ValueError("positive finite ADV and fraction in (0,1] required")
    q=int((Decimal(str(adv))*Decimal(str(fraction))).to_integral_value(rounding=ROUND_FLOOR))
    if not 1<=q<=10_000_000:raise ValueError("order must contain 1 to 10 million shares")
    return q


def forecast_scores(forecast: np.ndarray, actual: np.ndarray):
    f=np.asarray(forecast,dtype=float);v=np.asarray(actual,dtype=float)
    if f.shape!=(78,) or v.shape!=f.shape or not np.isfinite(f).all() or not np.isfinite(v).all() or np.any(f<0) or np.any(v<0) or min(f.sum(),v.sum())<=0:raise ValueError("positive totals and 78 finite nonnegative intervals required")
    return {"daily_ape":float(abs(f.sum()-v.sum())/v.sum()),"interval_wape":float(np.abs(f-v).sum()/v.sum()),
            "cumulative_share_mae":float(np.abs(np.cumsum(f/f.sum())-np.cumsum(v/v.sum())).mean())}
