"""Monte Carlo risk on schedule and cost.

Each run samples:
  * a program-wide efficiency factor (lognormal, sigma 0.12) applied to every
    development and build duration: common-cause risk such as funding gaps or
    staffing, which makes slips correlated;
  * each step's duration and cost from its triangular range;
  * a development failure for technology steps, with probability 0.1 per TRL
    level still to climb (cap 0.6); a failure adds 20-80% of the step's
    duration and 15-50% of its cost (redesign and retest);
  * mission failures: each attempt succeeds with the step's p_success; a
    failure re-flies at the next window (or after retry_dur) and costs 80% again.
Cost grows with schedule: every 10% of overrun on a step adds 5% to its cost
(the standing army).

All of these probabilities are estimates.
"""
from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .catalog import KEY_MILESTONES, Program
from .schedule import driving_path, forward_pass, to_year

SIGMA_PROGRAM = 0.12
P_FAIL_PER_TRL = 0.10
P_FAIL_CAP = 0.6
REWORK_DUR = (0.2, 0.4, 0.8)
REWORK_COST = (0.15, 0.30, 0.50)
COST_PER_SLIP = 0.5
MAX_FAILS = 3


def tri(rng: random.Random, t: tuple) -> float:
    lo, mode, hi = t
    return rng.triangular(lo, hi, mode)


def spread(y0: float, y1: float) -> list[tuple[int, float]]:
    """Share of a step's cost falling in each calendar year, spent evenly over its span."""
    y1 = max(y1, y0 + 1 / 12)
    out = []
    for y in range(math.floor(y0), math.floor(y1) + 1):
        overlap = min(y + 1, y1) - max(y, y0)
        if overlap > 0:
            out.append((y, overlap / (y1 - y0)))
    return out


def mode_plan(prog: Program) -> tuple[dict, dict]:
    """Deterministic plan: most likely durations and costs, no failures."""
    return ({k: s.dur[1] for k, s in prog.steps.items()}, {k: s.cost[1] for k, s in prog.steps.items()})


@dataclass
class Run:
    finish: dict[str, float]
    cost: dict[str, float]
    spend_by_year: dict[int, float]
    critical: list[str]
    critical_outer: list[str]
    fails: dict[str, int]


def sample_run(prog: Program, rng: random.Random, crit_target: str = "MARS-CREW-1",
               crit_target2: str = "OUTER-CREW-1") -> Run:
    eff = math.exp(rng.gauss(0.0, SIGMA_PROGRAM))
    dur, cost, fails, retry = {}, {}, {}, {}
    for sid, s in prog.steps.items():
        d = tri(rng, s.dur)
        if s.kind in ("tech", "build"):
            d *= eff
        c = tri(rng, s.cost)
        if s.trl:
            p = min(P_FAIL_CAP, P_FAIL_PER_TRL * max(0, s.trl[1] - s.trl[0]))
            if rng.random() < p:
                d += tri(rng, REWORK_DUR) * s.dur[1]
                c += tri(rng, REWORK_COST) * s.cost[1]
        slip = max(0.0, d / s.dur[1] - 1.0)
        c *= 1.0 + COST_PER_SLIP * slip
        n = 0
        while n < MAX_FAILS and rng.random() > s.p_success:
            n += 1
        if n:
            fails[sid] = n
            c *= 1.0 + 0.8 * n
            retry[sid] = tri(rng, s.retry_dur)
        dur[sid], cost[sid] = d, c
    tm = forward_pass(prog, dur, fails, retry)
    spend: dict[int, float] = defaultdict(float)
    for sid, t in tm.items():
        for y, share in spread(to_year(t.start), to_year(t.finish)):
            spend[y] += cost[sid] * share
    return Run({k: t.finish for k, t in tm.items()}, cost, dict(spend),
               driving_path(prog, tm, crit_target), driving_path(prog, tm, crit_target2), fails)


def pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    if not xs:
        return float("nan")
    i = q * (len(xs) - 1)
    lo, hi = math.floor(i), math.ceil(i)
    return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


@dataclass
class MCResult:
    n: int
    milestones: dict[str, dict] = field(default_factory=dict)
    cost_total: dict = field(default_factory=dict)
    cost_by_phase: dict = field(default_factory=dict)
    cost_to: dict = field(default_factory=dict)
    spend_by_year: dict = field(default_factory=dict)
    criticality: dict = field(default_factory=dict)
    criticality_outer: dict = field(default_factory=dict)
    failure_rate: dict = field(default_factory=dict)
    prob_by: dict = field(default_factory=dict)


def run_monte_carlo(prog: Program, n: int = 5000, seed: int = 2026,
                    prob_years: dict[str, list[int]] | None = None) -> MCResult:
    rng = random.Random(seed)
    runs = [sample_run(prog, rng) for _ in range(n)]
    res = MCResult(n)
    for m in KEY_MILESTONES:
        ys = [to_year(r.finish[m]) for r in runs]
        res.milestones[m] = {"p10": pct(ys, 0.1), "p50": pct(ys, 0.5), "p90": pct(ys, 0.9), "mean": sum(ys) / n}
    totals = [sum(r.cost.values()) for r in runs]
    res.cost_total = {"p10": pct(totals, 0.1), "p50": pct(totals, 0.5), "p90": pct(totals, 0.9), "mean": sum(totals) / n}
    for ph in sorted({s.phase for s in prog.steps.values()}):
        xs = [sum(c for k, c in r.cost.items() if prog.steps[k].phase == ph) for r in runs]
        res.cost_by_phase[ph] = {"p10": pct(xs, 0.1), "p50": pct(xs, 0.5), "p90": pct(xs, 0.9)}
    # Cost to reach a milestone: the milestone and everything upstream of it
    for m in ("ORBITAL-1", "LUNAR-CREW-1", "MARS-CREW-RETURN", "SETTLEMENT-100", "OUTER-CREW-1"):
        up = _upstream(prog, m)
        xs = [sum(r.cost[k] for k in up) for r in runs]
        res.cost_to[m] = {"p10": pct(xs, 0.1), "p50": pct(xs, 0.5), "p90": pct(xs, 0.9)}
    years = sorted({y for r in runs for y in r.spend_by_year})
    for y in years:
        xs = [r.spend_by_year.get(y, 0.0) for r in runs]
        res.spend_by_year[y] = {"p10": pct(xs, 0.1), "p50": pct(xs, 0.5), "p90": pct(xs, 0.9), "mean": sum(xs) / n}
    c1, c2 = Counter(), Counter()
    for r in runs:
        c1.update(set(r.critical))
        c2.update(set(r.critical_outer))
    res.criticality = {k: c1[k] / n for k in prog.order if c1[k]}
    res.criticality_outer = {k: c2[k] / n for k in prog.order if c2[k]}
    fc = Counter()
    for r in runs:
        fc.update({k: 1 for k in r.fails})
    res.failure_rate = {k: fc[k] / n for k in prog.order if fc[k]}
    prob_years = prob_years or {
        "MSR-RETURN": [2031, 2033, 2035], "ORBITAL-1": [2030, 2031, 2032], "LUNAR-CREW-1": [2033, 2034, 2035, 2036],
        "MARS-CARGO-1": [2034, 2036, 2038], "MARS-CREW-1": [2037, 2040, 2042, 2045],
        "SETTLEMENT-100": [2050, 2055, 2060], "OUTER-CREW-1": [2050, 2055, 2060],
    }
    for m, ys in prob_years.items():
        res.prob_by[m] = {y: sum(1 for r in runs if to_year(r.finish[m]) < y + 1) / n for y in ys}
    return res


def _upstream(prog: Program, target: str) -> set[str]:
    seen, stack = set(), [target]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack.extend(prog.preds[n])
    return seen
