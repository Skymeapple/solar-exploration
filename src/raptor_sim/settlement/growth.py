"""Settlement growth versus resupply: from outpost to city, one launch window at a time.

Each Earth-Mars window (synodic period, computed from the orbits in
raptor_sim.mission) sends a fleet of ships, each landing 100 t (PR #1 G0
requirement). Cargo goes first to keep existing residents supplied; what is
left brings new settlers and the equipment each one needs.

Per resident per year the settlement needs consumables (life_support model) and
manufactured goods (spares, tools, electronics, medicine: an estimate). Each new
settler needs a "kit": habitat volume, a share of the power plant (energy
model), greenhouse, ISRU and workshop. The share of all of that made locally,
f_local, rises with population, because a bigger economy supports more kinds of
industry. How fast it rises is the single most important unknown in settlement
planning, so it is a parameter (N_half: population at which half of needs are
made locally), and the study runs it at 1,000, 10,000 and 100,000.

The fleet ramps by doubling each window to a cap (SpaceX's stated aspiration is
~1,000 ships per window). Ships that go home are refuelled with Mars-made
propellant (642 t each, PR #1), which sets the propellant plant's power.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..mission import A_EARTH, A_MARS, MU_SUN, hohmann_vinf
from . import energy, life_support
from .inputs import v

YEAR_S = 365.25 * 86400


def synodic_period_days() -> float:
    t_e = 2 * math.pi * math.sqrt(A_EARTH**3 / MU_SUN)
    t_m = 2 * math.pi * math.sqrt(A_MARS**3 / MU_SUN)
    return 1.0 / (1.0 / t_e - 1.0 / t_m) / 86400.0


def transfer_days() -> float:
    return hohmann_vinf()[2]


@dataclass
class GrowthScenario:
    name: str = "baseline"
    windows: int = 40  # ~85 years
    first_ships: int = 2
    fleet_growth: float = 2.0  # per window
    fleet_cap: int = 1000
    n_half: float = 10_000.0  # unknown: population at which half of needs are made locally
    f_max: float = 0.999
    steepness: float = 2.5  # per decade of population
    goods_t_per_person_year: float = 3.0  # unknown: manufactured goods per resident
    kit_t_per_settler: float = 15.0  # estimate: habitat, greenhouse, workshop share (power added separately)
    natural_growth: float = 0.01  # per year once families form (estimate; TFR 2.5 gives ~1%)
    return_share: float = 0.5  # share of landed ships refuelled and flown home (estimate)
    industry_kw: float = field(default_factory=lambda: v("industry_power_per_person"))
    power_kg_per_kwe: float = field(default_factory=energy.fission_mass_per_kwe)
    cutoff_window: int | None = None  # Earth resupply stops after this window
    tolerable_unmet: float = 0.005  # estimate: share of needs a settlement can substitute or forgo
    shortfall_severity: float = 20.0  # estimate: decline rate per year per unit of unmet share beyond tolerable


@dataclass
class GrowthStep:
    window: int
    year: float
    ships: int
    population: float
    f_local: float
    sustain_t: float
    unmet_share: float
    settlers: float
    import_t_per_person_year: float
    power_mw: float
    propellant_plant_mw: float
    crop_area_ha: float
    life_support_stage: str


def f_local(n: float, s: GrowthScenario) -> float:
    if n <= 1:
        return 0.0
    x = math.log10(n) - math.log10(s.n_half)
    return s.f_max / (1.0 + math.exp(-s.steepness * x))


def stage_for(n: float) -> str:
    if n < 100:
        return "outpost"
    if n < 2000:
        return "isru"
    return "bioregen"


def run(s: GrowthScenario) -> list[GrowthStep]:
    period_yr = synodic_period_days() / 365.25
    cargo_per_ship = v("ship_cargo_mars")
    demand = energy.demand_per_person(industry_kw=s.industry_kw)["total_kw"]
    n = 0.0
    out = []
    for w in range(s.windows):
        year = w * period_yr
        ships = 0 if (s.cutoff_window is not None and w > s.cutoff_window) else int(min(s.fleet_cap, s.first_ships * s.fleet_growth**w))
        cargo = ships * cargo_per_ship
        fl = f_local(n, s)
        stage = life_support.STAGES[stage_for(n)]
        consumables_t = life_support.import_per_person_year(stage) / 1000.0
        need_per_person_yr = (consumables_t + s.goods_t_per_person_year) * (1 - fl)
        full_need = sum(b.demand_kg for b in life_support.person_year(stage)) / 1000.0 + s.goods_t_per_person_year
        sustain = n * need_per_person_yr * period_yr
        spare = cargo - sustain
        kit = (s.kit_t_per_settler + demand * s.power_kg_per_kwe / 1000.0) * (1 - fl)
        settlers = max(0.0, spare / (v("mass_per_passenger") + kit))
        settlers = min(settlers, ships * v("people_per_ship"))
        # Unmet share of residents' total needs. Beyond what can be substituted,
        # it shrinks the population (evacuation or deaths): crude, an estimate.
        unmet = max(0.0, -spare) / max(n * full_need * period_yr, 1e-9) if n > 0 else 0.0
        decline = math.exp(-s.shortfall_severity * max(0.0, unmet - s.tolerable_unmet) * period_yr)
        n = n * (1 + s.natural_growth) ** period_yr * decline + settlers
        returning = ships * s.return_share
        prop_mw = energy.propellant_plant_kw(returning * v("return_propellant_isru"), synodic_period_days()) / 1000.0
        out.append(
            GrowthStep(
                window=w,
                year=year,
                ships=ships,
                population=n,
                f_local=f_local(n, s),
                sustain_t=sustain,
                unmet_share=unmet,
                settlers=settlers,
                import_t_per_person_year=need_per_person_yr,
                power_mw=n * demand / 1000.0 + prop_mw,
                propellant_plant_mw=prop_mw,
                crop_area_ha=n * v("crop_area_per_person") * life_support.STAGES[stage_for(n)].food_local / 1e4,
                life_support_stage=stage.name,
            )
        )
    return out


def milestones(steps: list[GrowthStep]) -> dict[str, float | None]:
    def first(pred):
        for st in steps:
            if pred(st):
                return round(st.year, 1)
        return None

    return {
        "year_pop_1000": first(lambda st: st.population >= 1_000),
        "year_pop_10000": first(lambda st: st.population >= 10_000),
        "year_pop_100000": first(lambda st: st.population >= 100_000),
        "year_pop_1000000": first(lambda st: st.population >= 1_000_000),
        "year_f_local_90": first(lambda st: st.f_local >= 0.90),
        "year_f_local_98": first(lambda st: st.f_local >= 0.98),
        "final_population": steps[-1].population,
        "final_year": round(steps[-1].year, 1),
        "peak_power_mw": max(st.power_mw for st in steps),
        "peak_population": max(st.population for st in steps),
        "max_unmet_share": max(st.unmet_share for st in steps),
    }


def scenarios() -> list[GrowthScenario]:
    return [
        GrowthScenario("baseline (N_half 10k)"),
        GrowthScenario("fast industry (N_half 1k)", n_half=1_000.0),
        GrowthScenario("slow industry (N_half 100k)", n_half=100_000.0),
        GrowthScenario("small fleet (cap 100)", fleet_cap=100),
        GrowthScenario("Earth cutoff after 10 windows (~21 yr)", cutoff_window=10),
        GrowthScenario("Earth cutoff after 15 windows (~32 yr)", cutoff_window=15),
        GrowthScenario("Earth cutoff after 30 windows (~64 yr)", cutoff_window=30),
        GrowthScenario("slow industry, cutoff after 30 windows", n_half=100_000.0, cutoff_window=30),
    ]
