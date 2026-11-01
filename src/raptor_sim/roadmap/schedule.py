"""Schedule network: forward pass with launch windows, driving paths, float.

A step starts when all its predecessors finish. A window-gated step can only
start inside a launch window, so it waits for the next one; that wait is often
the biggest single delay in the program and makes float lumpy (a step can slip
up to a whole synodic period without moving anything, then one day more moves
everything by 26 months).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

from .catalog import Program
from .sources import JUPITER_SYNODIC_D, MARS_SYNODIC_D

START = date(2026, 11, 1)
DAYS_PER_MONTH = 30.4375

# Window openings in months from START and how long each stays open.
# Anchor: the 2028 window opens mid-November 2028 (model: PR #4 Lambert departure 2028-11-24,
# PR #5 cheapest crew departures 2028-11-17 to 2029-01-28); earlier and later windows step by
# the synodic period, good to about two months (real windows drift with Mars's eccentric orbit).
MARS_ANCHOR = (date(2028, 11, 15) - START).days / DAYS_PER_MONTH - MARS_SYNODIC_D / DAYS_PER_MONTH
WINDOWS = {
    # name: (first opening, period, open length), all months
    "mars": (MARS_ANCHOR, MARS_SYNODIC_D / DAYS_PER_MONTH, 2.0),
    # Conjunction-class return: leave Mars about 22 months after the Earth-side window opens
    # (PR #4 leaves Mars 2030-10-07, 22.7 months after its 2028-11-24 launch).
    "mars_return": (MARS_ANCHOR + 22.0, MARS_SYNODIC_D / DAYS_PER_MONTH, 2.0),
    # Jupiter: opening near each opposition, anchor January 2027 (estimate).
    "jupiter": ((date(2027, 1, 10) - START).days / DAYS_PER_MONTH, JUPITER_SYNODIC_D / DAYS_PER_MONTH, 1.0),
}


def to_date(m: float) -> date:
    return START + timedelta(days=m * DAYS_PER_MONTH)


def to_year(m: float) -> float:
    return 2026 + 10 / 12 + m / 12


def next_window(name: str, t: float) -> float:
    """Earliest start time >= t that lies inside a window."""
    first, period, length = WINDOWS[name]
    if t <= first:
        return first
    k = math.floor((t - first) / period)
    w = first + k * period
    if t <= w + length:
        return t
    return w + period


def window_dates(name: str, until_year: int = 2060) -> list[date]:
    first, period, _ = WINDOWS[name]
    out, k = [], 0
    while True:
        d = to_date(first + k * period)
        if d.year > until_year:
            return out
        out.append(d)
        k += 1


@dataclass
class Timing:
    start: float
    finish: float
    ready: float       # when predecessors were done
    driver: str | None  # predecessor that set `ready`
    attempts: int = 1


def forward_pass(prog: Program, dur: dict[str, float], fail: dict[str, int] | None = None,
                 retry: dict[str, float] | None = None, delay: dict[str, float] | None = None) -> dict[str, Timing]:
    """Schedule every step.

    dur:   duration of each step (months)
    fail:  number of failed attempts before success for missions
    retry: months to re-fly after a failure (non-window steps)
    delay: extra months added to a step's ready time (used for float)
    """
    fail = fail or {}
    retry = retry or {}
    delay = delay or {}
    out: dict[str, Timing] = {}
    for sid in prog.order:
        s = prog.steps[sid]
        ready, driver = 0.0, None
        for p in prog.preds[sid]:
            if out[p].finish > ready:
                ready, driver = out[p].finish, p
        ready += delay.get(sid, 0.0)
        start = next_window(s.window, ready) if s.window else ready
        n_fail = fail.get(sid, 0)
        for _ in range(n_fail):
            # A failed attempt uses the full duration, then the step tries again.
            t = start + dur[sid]
            start = next_window(s.window, t) if s.window else t + retry.get(sid, 6.0)
        out[sid] = Timing(start, start + dur[sid], ready, driver, n_fail + 1)
    return out


def driving_path(prog: Program, timing: dict[str, Timing], target: str) -> list[str]:
    """Chain of steps that set the target's start, earliest first."""
    path, n = [], target
    while n is not None:
        path.append(n)
        n = timing[n].driver
    return path[::-1]


def total_float(prog: Program, dur: dict[str, float], targets: list[str], step_months: float = 1.0,
                cap: float = 60.0) -> dict[str, float]:
    """Months each step can slip before any target finishes later (deterministic)."""
    base = forward_pass(prog, dur)
    ref = {t: base[t].finish for t in targets}
    out = {}
    for sid in prog.order:
        lo = 0.0
        d = step_months
        while d <= cap:
            tm = forward_pass(prog, dur, delay={sid: d})
            if any(tm[t].finish > ref[t] + 1e-6 for t in targets):
                break
            lo = d
            d += step_months
        out[sid] = lo
    return out
