"""Phased buildup from robotic prospecting to a spaceport and a settlement.

Each phase has a manifest of landed items (estimated masses), a critical power
load and an ISRU target. The model sizes power and ISRU with the other modules,
counts one-way Starship-class cargo landings (100 t each) and converts them to
Earth launches with the project's vehicle model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import construction, isru, mars_benefit, plume, power, site


@dataclass(frozen=True)
class Item:
    name: str
    mass_t: float
    note: str = ""


@dataclass(frozen=True)
class Phase:
    name: str
    years: str
    crew: int
    critical_kw: float
    propellant_t_yr: float  # lunar propellant (hydrolox) target
    lox_t_yr: float  # lunar oxygen for methalox customers
    items: tuple[Item, ...] = field(default_factory=tuple)
    pads: int = 0


PHASES: tuple[Phase, ...] = (
    Phase("0. Robotic prospecting", "years 1-3", 0, 5.0, 0.0, 0.0, (
        Item("Prospecting rovers and drills (CLPS-class landers)", 4.0, "map ice at 1 m depth across target PSRs"),
        Item("Solar tower demonstrator, 50 kW", 2.0),
        Item("Ice extraction and electrolysis pilot, 10 t water/yr", 5.0),
        Item("Pad sintering demonstrator", 3.0),
        Item("Comms relay and navigation beacons", 2.0),
    )),
    Phase("1. Outpost (4 crew, rotating)", "years 3-6", 4, 40.0, 0.0, 0.0, (
        Item("Habitat module, inflatable", 25.0),
        Item("Regolith excavators, 4 units", 12.0),
        Item("Pressurised rovers, 2", 10.0),
        Item("Logistics and consumables, first two years", 20.0),
        Item("First landing pad: sintering kit and paving robot", 10.0),
        Item("Spares, tools, workshop", 10.0),
    ), pads=1),
    Phase("2. Propellant plant", "years 5-9", 8, 100.0, 500.0, 0.0, (
        Item("Tent-mining rovers and haulers", 0.0, "sized by isru"),
        Item("Electrolysers, liquefiers, radiators", 0.0, "sized by isru"),
        Item("Surface depot tanks, 1,000 t", 40.0),
        Item("Second habitat and workshop", 30.0),
    ), pads=2),
    Phase("3. Transit spaceport", "years 8-14", 24, 300.0, 2_000.0, 1_000.0, (
        Item("Plant expansion", 0.0, "sized by isru"),
        Item("Pads 3 and 4 with blast berms", 20.0),
        Item("Assembly and maintenance hangar (pressurised bay plus gantry crane)", 60.0),
        Item("NRHO depot, 1,500 t", 90.0),
        Item("Hydrolox surface-to-NRHO shuttles, 2", 120.0),
        Item("Habitats for 24", 100.0),
    ), pads=4),
    Phase("4. Settlement (about 100 residents)", "years 14-25", 100, 1_500.0, 5_000.0, 3_000.0, (
        Item("Plant expansion", 0.0, "sized by isru"),
        Item("Settlement blocks, 6 x 16 crew", 300.0),
        Item("Greenhouses and food production", 150.0),
        Item("Regolith metallurgy pilot (oxygen plus Fe/Al/Si by molten regolith electrolysis)", 80.0),
        Item("Medical, science, maintenance", 120.0),
    ), pads=6),
)


@dataclass(frozen=True)
class PhaseResult:
    phase: Phase
    isru_kw: float
    isru_plant_t: float
    water_t_yr: float
    power_arch: str
    power_mass_t: float
    landed_t: float
    cargo_landings: int
    earth_launches: float
    cover_m: float


def evaluate(ice_frac: float = 0.056) -> list[PhaseResult]:
    s = site.rank_sites()[0][0]
    sun = site.illumination_series(s)
    lit = float(sun.mean())
    c = mars_benefit.context()
    per_t = mars_benefit.lunar_cargo_launches_per_t(c)
    cover = construction.cover_for_dose()
    out = []
    prev_plant = prev_power = 0.0
    for ph in PHASES:
        kw = plant_t = water = 0.0
        if ph.propellant_t_yr:
            p = isru.plant_for_production(ph.propellant_t_yr, ice_frac, "hydrolox", capacity_factor=lit)
            kw += p.total_kw
            plant_t += p.plant_mass_t
            water += p.water_t_yr
        if ph.lox_t_yr:
            p = isru.plant_for_production(ph.lox_t_yr, ice_frac, "methalox", capacity_factor=lit)
            kw += p.total_kw
            plant_t += p.plant_mass_t
            water += p.water_t_yr
        options = power.size_architectures(sun, ph.critical_kw)
        if ph.crew:  # crewed phases must survive one power-source fault
            options = [o for o in options if "no spare" not in o[0].name]
        arch, m = options[0]
        pm = m["total_t"]
        if kw:
            pm += power.system_mass_t(power.PowerSystem("isru", kw, 0.0, "none"))["total_t"]
        # Only the increment over the previous phase is landed.
        new = sum(i.mass_t for i in ph.items) + max(plant_t - prev_plant, 0.0) + max(pm - prev_power, 0.0)
        prev_plant, prev_power = max(plant_t, prev_plant), max(pm, prev_power)
        landings = math.ceil(new / mars_benefit.SPEC["lunar_cargo_t"].value)
        out.append(PhaseResult(ph, kw, plant_t, water, arch.name + (" + solar for ISRU" if kw else ""), pm, new,
                               landings, new * per_t, cover))
    return out


def pad_summary() -> list[dict[str, float | str]]:
    ref = plume.erosion_index(plume.landers()[0])
    rows = []
    for l in plume.landers():
        s = plume.size_pad(l, ref)
        w = construction.pad_works(s)
        rows.append({"lander": l.name, "peak_kpa": s.peak_pressure_kpa, "pad_radius_m": s.pad_radius_m,
                     "fines_radius_m": s.fines_erosion_radius_m, "disturbed_radius_m": s.disturbed_radius_m,
                     "erosion_vs_apollo": s.erosion_index, "sinter_mwh": w.sinter_energy_mwh,
                     "sinter_days_200kw": w.sinter_days_at_kw, "berm_m": w.berm_height_m,
                     "berm_t": w.berm_mass_t})
    return rows
