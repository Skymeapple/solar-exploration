"""Abort coverage for crewed missions.

1. Trans-Mars coast aborts: at each day after Earth departure, the smallest
   delta-v that puts the ship on a Lambert arc back to Earth arriving within a
   given time, and whether the Earth entry speed is survivable.
2. Mars surface aborts: waiting time from any day of the stay to the next
   low-energy return departure.
3. Ascent aborts are described in the report only (they depend on vehicle
   design: a capsule has a launch escape system, a Starship-class ship does
   not; no simulation here).

The method is ours; constraints (entry-speed ceiling, abort delta-v budget)
are ESTIMATES.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .orbits import DAY, lambert, planet_state, propagate
from .transfers import Leg, entry_speed, leg


@dataclass(frozen=True)
class AbortPoint:
    day: int  # days after departure
    best_dv: float  # m/s, cheapest return found within the time cap
    return_days: float  # time from abort to Earth arrival for that cheapest return
    earth_entry_speed: float  # m/s
    feasible: bool


def outbound_state(L: Leg, days_after: float):
    r1, v1p = planet_state(L.origin, L.depart_jd)
    r2, _ = planet_state(L.target, L.depart_jd + L.tof_days)
    v1, _ = lambert(r1, r2, L.tof_days * DAY)
    return propagate(r1, v1, days_after * DAY)


def trans_mars_abort(L: Leg, dv_budget: float = 2_000.0, max_return_days: float = 400.0,
                     max_entry: float = 12_500.0, step: int = 10) -> list[AbortPoint]:
    """Abort coverage along an Earth-to-Mars leg (excludes the Mars swing-by option)."""
    out = []
    for d in range(step, int(L.tof_days) - step + 1, step):
        r, v = outbound_state(L, d)
        jd_abort = L.depart_jd + d
        best = None
        for t in range(30, int(max_return_days) + 1, 5):
            re, ve = planet_state("earth", jd_abort + t)
            sol = lambert(r, re, t * DAY)
            if sol is None:
                continue
            dv = float(np.linalg.norm(sol[0] - v))
            vin = entry_speed("earth", float(np.linalg.norm(sol[1] - ve)))
            if vin > max_entry:
                continue
            if best is None or dv < best[0]:
                best = (dv, t, vin)
        if best is None:
            out.append(AbortPoint(d, float("inf"), float("nan"), float("nan"), False))
        else:
            out.append(AbortPoint(d, best[0], best[1], best[2], best[0] <= dv_budget))
    return out


def coverage(points: list[AbortPoint]) -> float:
    return sum(p.feasible for p in points) / max(len(points), 1)


def mars_surface_wait(arrive_jd: float, stay_days: int, return_dv_cap: float, tof_range=range(150, 301, 10),
                      search_days: int = 900) -> list[tuple[int, float]]:
    """For each day of the planned stay, days until a return leg with TEI below the cap exists."""
    from .transfers import departure_dv

    ok_days = []
    for dd in range(0, stay_days + search_days, 5):
        jd = arrive_jd + dd
        good = False
        for tof in tof_range:
            R = leg("mars", "earth", jd, tof)
            if R and departure_dv("mars", R.vinf_depart) <= return_dv_cap and entry_speed("earth", R.vinf_arrive) <= 12_500:
                good = True
                break
        if good:
            ok_days.append(dd)
    waits = []
    for day in range(0, stay_days + 1, 10):
        nxt = next((o for o in ok_days if o >= day), None)
        waits.append((day, float("inf") if nxt is None else float(nxt - day)))
    return waits
