"""Base build-up: what each phase needs, how much comes from Earth, how many flights.

Three phases per site (all sizes are estimates for this study):

* outpost: 4 crew, ISRU sized for one full ship load (1,600 t) per year
* base:    50 crew, 10,000 t/yr of propellant (about six ship loads)
* city:    1,000 crew, 50,000 t/yr, local steel and habitat structure where metals allow

Also: how much of a Starship-class ship could be built on site in each phase,
using the material split of the project's engine BOM (PR #2) for the engines.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .isru import isru_plan
from .network import Network, Route, tankers_for_leo_departure
from .power import best_power
from .sites import Site


@dataclass(frozen=True)
class Phase:
    name: str
    crew: int
    propellant_t_per_yr: float
    hab_t_per_crew: float  # imported habitat + life support mass per person
    kwe_per_crew: float  # life support, food growth, industry per person
    workshop_t: float  # assembly and manufacturing equipment
    pad_t: float  # landing/launch pad equipment (sintering, blast walls, handling)


PHASES = (
    Phase("outpost", 4, 1_600.0, 10.0, 15.0, 0.0, 30.0),
    Phase("base", 50, 10_000.0, 6.0, 15.0, 100.0, 60.0),
    Phase("city", 1_000, 50_000.0, 3.0, 20.0, 1_000.0, 150.0),
)

DEPOT_TANK_FRACTION = 0.03  # estimate: tank mass per tonne stored (two ship loads)
DEPOT_POWER_RESERVE = 0.15  # estimate: share of ISRU power for cryocoolers and depot pumps
SHIELDING_EQUIPMENT_T = 20.0  # estimate: excavators/bulldozers to bury habitats
OCCUPATIONAL_LIMIT_MSV_YR = 50.0  # literature: ICRP annual worker limit used as a design line

# Ship dry-mass split (estimate) and engine material split (PR #2 BOM, 2,320 kg engine:
# IN718 40%, OXSA 21%, GRCop-42 10%, Monel 5%, Ti64 3%, other 21%).
SHIP_STRUCTURE_FRACTION = 0.80  # stainless steel tanks, skin, thrust structure
SHIP_ENGINE_FRACTION = 0.10  # six Raptor-class engines
SHIP_SYSTEMS_FRACTION = 0.10  # avionics, power, heat shield tiles, actuators


@dataclass(frozen=True)
class PhaseResult:
    site: str
    phase: str
    power_kwe: float
    power_kind: str
    power_t: float
    isru_plant_t: float
    hab_t: float
    other_t: float
    imported_t: float
    deliveries: float  # ship loads delivered to the site
    earth_launches: float  # deliveries plus LEO tanker launches
    earth_launches_direct: float  # same, flying straight from LEO without hubs (inf if impossible)
    shielding_needed: bool
    local_ship_fraction: float  # share of ship dry mass that can be made on site
    imported_ch4_t_per_yr: float  # for oxygen-only sites


def _launches(net: Network, route: Route, imported_t: float) -> float:
    if route.cargo_t <= 0:
        return math.inf
    deliveries = imported_t / route.cargo_t
    tankers = tankers_for_leo_departure(net, route.path[1], route.cargo_t)
    return deliveries * (1 + tankers)


def local_ship_fraction(site: Site, phase: str) -> float:
    m = site.resources.metals
    steel = m >= 0.5 and phase in ("base", "city") or m >= 0.3 and phase == "city"
    superalloy = m >= 0.6 and phase == "city"
    return SHIP_STRUCTURE_FRACTION * steel + SHIP_ENGINE_FRACTION * superalloy


def base_buildup(site: Site, net: Network, routes: dict[str, Route]) -> list[PhaseResult]:
    plan = isru_plan(site)
    route = routes[site.key]
    direct = Route(site.key, ("leo", site.key), route.direct_payload_t, 0.0, 0.0, route.direct_payload_t,
                   net.ship.max_payload_t)
    out = []
    for ph in PHASES:
        isru_kwe = ph.propellant_t_per_yr * plan.best.energy_kwh_per_t / 8766.0
        kwe = isru_kwe / (1 - DEPOT_POWER_RESERVE) + ph.crew * ph.kwe_per_crew
        pw = best_power(site, kwe)
        plant_t = ph.propellant_t_per_yr / 365.25 * 6.0
        local_share = site.resources.metals if ph.name == "city" else 0.0
        hab_t = ph.crew * ph.hab_t_per_crew
        depot_t = 2 * net.ship.propellant_t * DEPOT_TANK_FRACTION * (1 - local_share)
        shield = site.radiation_msv_yr > OCCUPATIONAL_LIMIT_MSV_YR
        other = ph.workshop_t + ph.pad_t + depot_t + (SHIELDING_EQUIPMENT_T if shield else 0.0)
        imported = pw.mass_t + plant_t + hab_t + other
        ch4_import = ph.propellant_t_per_yr * (1 - plan.best.local_fraction)
        out.append(
            PhaseResult(
                site.key, ph.name, kwe, pw.kind, pw.mass_t, plant_t, hab_t, other, imported,
                imported / route.cargo_t if route.cargo_t > 0 else math.inf,
                _launches(net, route, imported),
                _launches(net, direct, imported),
                shield, local_ship_fraction(site, ph.name), ch4_import,
            )
        )
    return out


@dataclass(frozen=True)
class RefillSim:
    site: str
    power_kwe: float
    window_days: float  # time between departures (synodic period of the onward leg)
    days_to_fill: float
    stored_at_window_t: float
    boiloff_t: float
    meets_window: bool


def simulate_refill(
    site: Site,
    power_kwe: float,
    target_t: float,
    window_days: float,
    boiloff_per_day: float | None = None,
    reserve_power_frac: float = DEPOT_POWER_RESERVE,
    crew_kwe: float = 0.0,
) -> RefillSim:
    """Day-by-day propellant production into a depot until the next departure window.

    `reserve_power_frac` of the power goes to the depot's cryocoolers and the
    base; boil-off defaults to 0.05%/day with active cooling and zero where the
    site is cold enough for passive storage (estimates).
    """
    plan = isru_plan(site)
    if boiloff_per_day is None:
        boiloff_per_day = 0.0 if plan.passive_cryo else 0.0005
    rate = plan.production_t_per_day((power_kwe - crew_kwe) * (1 - reserve_power_frac))
    stored, lost, filled_day = 0.0, 0.0, math.inf
    days = int(math.ceil(max(window_days, 3 * 365.25)))
    for day in range(1, days + 1):
        loss = stored * boiloff_per_day
        stored = stored + rate - loss
        lost += loss
        if stored >= target_t and filled_day == math.inf:
            filled_day = day
        stored = min(stored, 2 * target_t)  # depot holds two ship loads
        if day == int(math.ceil(window_days)):
            at_window = stored
    return RefillSim(site.key, power_kwe, window_days, filled_day, at_window, lost, filled_day <= window_days)
