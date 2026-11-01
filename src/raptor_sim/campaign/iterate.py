"""Design iteration: evaluate the campaign, apply a rule to each failing objective, re-run.

Each rule is the change an engineer would make first for that failure. The loop
stops when every objective passes or after max_rounds. Every round is logged with
the objectives that failed and the changes made, so the history can be audited.
"""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np

from .campaign import CampaignReport, Design, evaluate


def _round_up(x: float, step: float) -> float:
    return math.ceil(x / step) * step


def size_power(d: Design, need: float, stay_days: float, target: float = 0.97) -> tuple[Design, str]:
    """Smallest power system that makes `need` kg with probability >= target: solar arrays up to
    40,000 m2 (about 4 ha, ~40 t of thin-film arrays [est]), then fission units in 10 kWe steps."""
    from .mars_ops import isru_monte_carlo

    def p(plant):
        return isru_monte_carlo(plant, need, stay_days, n=300, seed=21).p_success

    plant = d.isru
    for area in range(int(plant.solar_array_m2), 40_001, 2_000):
        trial = replace(plant, solar_array_m2=float(area))
        if p(trial) >= target:
            return replace(d, isru=trial), f"O11: solar array {plant.solar_array_m2:,.0f} -> {area:,} m2"
    lo, hi = plant.nuclear_kwe, plant.nuclear_kwe + 1000.0
    base = replace(plant, solar_array_m2=40_000.0)
    while hi - lo > 10.0:
        mid = 0.5 * (lo + hi)
        if p(replace(base, nuclear_kwe=mid)) >= target:
            hi = mid
        else:
            lo = mid
    kwe = _round_up(hi, 10.0)
    return (replace(d, isru=replace(base, nuclear_kwe=kwe)),
            f"O11: arrays capped at 40,000 m2; add {kwe:.0f} kWe of fission power so dust storms cannot stop production")


def propose(rep: CampaignReport) -> tuple[Design, list[str]]:
    d = rep.design
    n = rep.numbers
    s = rep.samples
    changes: list[str] = []
    failing = {o.id for o in rep.failing()}

    if "O2" in failing:
        d = replace(d, q_limit_throttle=33e3)
        changes.append("O2: add a booster throttle bucket holding dynamic pressure near 33 kPa")
    if "O1" in failing and "O4" not in failing and d.booster_adaptive_draw < 0.04:
        new = round(d.booster_adaptive_draw + 0.01, 3)
        changes.append(f"O1: adaptive booster cut-off may draw {new:.0%} of booster propellant from the return reserve "
                       "on a short launch (booster possibly expended)")
        d = replace(d, booster_adaptive_draw=new)
    if "O4" in failing:
        why = n.get("booster_failures", {})
        p5 = float(np.percentile(s["booster_margin"], 5)) if len(s["booster_margin"]) else -1.0
        if why.get("propellant", 0) or p5 < 0.03:
            new = round(d.booster_reserve_fraction + 0.02, 3)
            changes.append(f"O4: booster return reserve {d.booster_reserve_fraction:.0%} -> {new:.0%} of loaded propellant")
            d = replace(d, booster_reserve_fraction=new)
    if "O8" in failing or "O9" in failing:
        why = n.get("mars_edl_failures", {})
        p99 = float(np.percentile(s["mars_landing_prop_t"], 99)) * 1e3
        cor = n["mars_entry"]["corridor_deg"]
        if why.get("propellant", 0) or why.get("crash", 0) or p99 >= 0.97 * d.landing_propellant or not cor:
            new = _round_up(max(p99, d.landing_propellant) * 1.15, 5e3)
            changes.append(f"O8: Mars landing propellant {d.landing_propellant/1e3:.0f} t -> {new/1e3:.0f} t (failures {why})")
            d = replace(d, landing_propellant=new)
        elif cor:
            centre = round(0.5 * (cor[0] + cor[1]), 2)
            if abs(centre - d.mars_entry_fpa) > 0.05:
                changes.append(f"O8/O9: retarget Mars entry angle {d.mars_entry_fpa} -> {centre} deg (corridor centre)")
                d = replace(d, mars_entry_fpa=centre)
            elif why.get("touchdown speed", 0):
                d = replace(d, v_srp=d.v_srp + 100.0)
                changes.append(f"O8: light the landing engines earlier, at {d.v_srp:.0f} m/s")
    if "O7" in failing:
        p99 = float(np.percentile(s["tcm"], 99))
        new = _round_up(p99 * 1.2, 5.0)
        changes.append(f"O7: correction budget {d.tcm_budget:.0f} -> {new:.0f} m/s")
        d = replace(d, tcm_budget=new)
    if "O5" in failing:
        plan = d.refill
        if plan.boiloff_per_day > 0.0003:
            plan = replace(plan, boiloff_per_day=0.0003)
            changes.append("O5: add sunshade and tank insulation on the waiting ship (boil-off 0.1 -> 0.03 %/day)")
        elif plan.pads < 3:
            plan = replace(plan, pads=plan.pads + 1)
            changes.append(f"O5: add a launch pad ({plan.pads} pads)")
        else:
            plan = replace(plan, lead_days=plan.lead_days + 20)
            changes.append(f"O5: start the campaign earlier ({plan.lead_days} days before the window)")
        d = replace(d, refill=plan)
    if "O12" in failing:
        ee = n["earth_entry"]
        why = ee.get("failures", {})
        cor = n.get("earth_corridor_deg")
        if why.get("heating", 0) and not d.return_tps_upgrade:
            d = replace(d, return_tps_upgrade=True)
            changes.append("O12: ablative windward heat shield on the return ship (+6 t) instead of a braking burn")
        elif cor and (cor[1] - cor[0]) >= 0.6:
            centre = round(0.5 * (cor[0] + cor[1]), 2)
            if abs(centre - d.earth_entry_fpa) > 0.02:
                changes.append(f"O12: retarget Earth entry angle {d.earth_entry_fpa} -> {centre} deg (corridor centre)")
                d = replace(d, earth_entry_fpa=centre)
        if not changes or not changes[-1].startswith("O12"):
            # Corridor too narrow at this speed: brake before entry to widen it.
            d = replace(d, earth_braking_dv=d.earth_braking_dv + 300.0)
            changes.append(f"O12: braking burn before Earth entry, now {d.earth_braking_dv:.0f} m/s (corridor {cor})")
    if "O11" in failing or "O10" in failing:
        need = n["isru_load_t"] * 1e3
        if math.isfinite(need):
            d, msg = size_power(d, need, n["surface_stay_days"])
            changes.append(msg)
    return d, changes


def iterate(d: Design | None = None, max_rounds: int = 10, n_mc: int = 120, quick: bool = True, log=print):
    d = d or Design()
    history = []
    rep = None
    for k in range(max_rounds):
        rep = evaluate(d, n_mc=n_mc, quick=quick, seed=11 + k)
        failing = [o.id for o in rep.failing()]
        entry = {"round": k, "failing": failing,
                 "objectives": {o.id: {"value": o.value, "limit": o.limit, "passed": o.passed} for o in rep.objectives},
                 "changes": []}
        log(f"round {k}: {len(failing)} failing {failing}")
        if not failing:
            history.append(entry)
            break
        d, changes = propose(rep)
        entry["changes"] = changes
        for c in changes:
            log("   " + c)
        history.append(entry)
        if not changes:
            log("   no rule applies; stopping")
            break
    return d, rep, history
