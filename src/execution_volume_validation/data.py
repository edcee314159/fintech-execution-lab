"""FirstRate six-column, Eastern-Time bar-start CSV data contract.

Only complete 390-minute sessions are accepted. Exclusions are retained in
an audit rather than silently inventing no-trade or unavailable minutes.
"""
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
import csv
import math
import numpy as np

@dataclass(frozen=True)
class Day:
    symbol: str
    day: date
    volume: np.ndarray
    close: np.ndarray
    open_price: float


def load_sessions(path: Path, symbol: str):
    groups={}; invalid={}; duplicates=0; outside=0; rows=0
    with Path(path).open(encoding="utf-8-sig",newline="") as f:
        for line,r in enumerate(csv.reader(f),1):
            rows+=1
            try: t=datetime.strptime(r[0],"%Y-%m-%d %H:%M:%S")
            except (ValueError,IndexError) as e: raise ValueError(f"invalid timestamp on line {line}") from e
            minute=t.hour*60+t.minute
            if not 570<=minute<960:
                outside+=1;continue
            key=t.date();g=groups.setdefault(key,{})
            try:
                if len(r)!=6 or t.second!=0 or key.weekday()>4: raise ValueError()
                o,h,l,c,v=map(float,r[1:])
                if not all(math.isfinite(x) for x in (o,h,l,c,v)):raise ValueError()
                if not 0<l<=min(o,c)<=max(o,c)<=h or v<0 or not v.is_integer() or v>1e12:raise ValueError()
                values=(o,h,l,c,int(v))
            except ValueError:
                invalid.setdefault(key,set()).add("invalid_ohlcv");continue
            if minute in g:
                if g[minute]==values:duplicates+=1
                else:invalid.setdefault(key,set()).add("conflicting_duplicate")
            else:g[minute]=values
    days=[];excluded=[];accepted=[]
    for key,g in sorted(groups.items()):
        reasons=set(invalid.get(key,set()))
        if set(g)!=set(range(570,960)): reasons.add("incomplete_session")
        if reasons:
            excluded.append({"date":key.isoformat(),"reasons":sorted(reasons),"observed_valid_minutes":len(g)})
            continue
        ordered=[g[k] for k in range(570,960)]
        volumes=np.array([x[4] for x in ordered],dtype=np.int64).reshape(78,5).sum(axis=1)
        closes=np.array([x[3] for x in ordered],dtype=float).reshape(78,5)[:,-1].copy()
        days.append(Day(symbol,key,volumes,closes,ordered[0][0]));accepted.append(key.isoformat())
    audit={"symbol":symbol,"input_rows":rows,"outside_session_rows":outside,"exact_duplicates":duplicates,
           "accepted_sessions":accepted,"excluded_sessions":excluded,"accepted_minutes":len(days)*390,
           "timezone":"America/New_York; source wall-clock ET, no UTC conversion",
           "missingness_policy":"Exclude incomplete sessions; no gap filling", "interval_minutes":5}
    return days,audit
