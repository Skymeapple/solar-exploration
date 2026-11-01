"""Verification checks L1-L10 for the lunar base models, in the style of gates G0-G7.

Each check compares a model output with a cited reference or a physical
conservation law, with a stated tolerance. A failed check means the model,
not the base design, is suspect.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..mission import mars_mission
from . import depot, isru, mars_benefit, orbits, plume, power, site


@dataclass(frozen=True)
class Check:
    id: str
    name: str
    value: float
    target: str
    passed: bool
    note: str = ""


def run_checks() -> list[Check]:
    out: list[Check] = []

    # L1 orbits: our LLO-staged ascent against NASA's surface-to-NRHO figure.
    up = orbits.surface_to_nrho()
    ref = orbits.leg("surface->NRHO (NASA)")
    out.append(Check("L1", "Surface to NRHO delta-v vs NASA", up, f"within 5% of {ref:.0f} m/s",
                     abs(up / ref - 1) < 0.05, "LLO-staged sum of shared legs"))

    # L2 orbits: Mars departure from LEO equals the Mars study's TMI (same physics, two code paths).
    tmi = mars_mission().tmi_dv
    out.append(Check("L2", "Mars departure from LEO matches mission.py", orbits.mars_departure("LEO"),
                     f"within 0.1% of {tmi:.0f} m/s", abs(orbits.mars_departure("LEO") / tmi - 1) < 1e-3))

    # L3 site: synthetic illumination reproduces the cited lit fraction and dark spells.
    best = site.SITES[0]
    sun = site.illumination_series(best, hours=19 * 8766.0)
    spell = float(site.dark_spells_days(sun).max())
    out.append(Check("L3", "Connecting Ridge lit fraction (19 yr)", float(sun.mean()),
                     f"within 0.5% of {best.illumination.value:.4f}", abs(sun.mean() - best.illumination.value) < 0.005))
    out.append(Check("L4", "Connecting Ridge longest dark spell (19 yr)", spell, "3 to 5 days (Glaser 2014)",
                     3.0 <= spell <= 5.0))

    # L5 power: the selected outpost system carries the critical load every hour for two years.
    sun2 = site.illumination_series(best)
    arch = [a for a in power.size_architectures(sun2, 40.0) if a[0].storage == "rfc"][0][0]
    r = power.simulate(arch, sun2, 40.0)
    out.append(Check("L5", "Solar + RFC outpost, unmet critical energy (2 yr)", r.unmet_kwh, "< 1 kWh",
                     r.unmet_kwh < 1.0, f"{arch.storage_kwh:.0f} kWh storage, {arch.solar_kw:.0f} kW array"))

    # L6 ISRU: both Kornuta Table 1 sublimation powers within 10%, total plant power within 15%.
    k = isru.kornuta_check()
    worst = max(abs(k["4%"]["error"]), abs(k["30%"]["error"]))
    out.append(Check("L6", "Ice sublimation power vs Kornuta 2019 Table 1", worst, "both cases within 10%",
                     worst < 0.10, f"4 wt%: {k['4%']['model_kw']:.0f} vs 580 kW; 30 wt%: {k['30%']['model_kw']:.0f} vs 370 kW"))
    out.append(Check("L7", "Total plant power vs Kornuta 2019 (2.8 MW)", k["total"]["model_kw"], "within 15% of 2,800 kW",
                     abs(k["total"]["error"]) < 0.15))

    # L8 plume: normal pressure integrated over the ground equals the thrust (momentum conservation).
    n = plume.Nozzle(1e6, plume.raptor_exit_mach(), 1.22, height_m=5.0)
    rr = np.geomspace(1e-3, 5e4, 20000)
    p, _ = plume.surface_loads([n], rr, np.zeros_like(rr))
    force = float(np.trapezoid(p * 2 * math.pi * rr, rr))
    out.append(Check("L8", "Plume ground force / thrust", force / n.thrust_n, "within 2% of 1",
                     abs(force / n.thrust_n - 1) < 0.02))

    # L9 depot: shaded surface LOX depot loses less than 1% per month passively.
    d = depot.depot("LOX", 1250.0, "surface_shaded")
    out.append(Check("L9", "Shaded surface LOX depot boil-off", d.boiloff_pct_per_month, "< 1% per month",
                     d.boiloff_pct_per_month < 1.0))

    # L10 Earth-launch accounting reproduces the Mars study's tanker count.
    c = mars_benefit.context()
    a = mars_benefit.scenario_a(c)
    tankers = mars_mission().tanker_flights
    out.append(Check("L10", "Baseline tanker launches vs mission.py", a.earth_launches - 1,
                     f"ceil equals {tankers}", math.ceil(a.earth_launches - 1 - 1e-9) == tankers))
    return out


def all_pass(checks: list[Check] | None = None) -> bool:
    return all(c.passed for c in (checks or run_checks()))
