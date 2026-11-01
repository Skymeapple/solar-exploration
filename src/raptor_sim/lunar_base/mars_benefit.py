"""Does Moon-made propellant reduce Earth launches? Mars departures and lunar sorties.

The figure of merit is Earth launches per mission, using the project's vehicle
model (:mod:`raptor_sim.mission`): each tanker launch puts `payload_to_leo_t` of
propellant in LEO. Fractional launches are kept so that small differences show.

Mars scenarios (100 t cargo landed on Mars, same as mission.MissionAssumptions):

A. Earth only: the ship refills in LEO from Earth tankers (the project baseline).
B. NRHO departure: the ship flies LEO to NRHO on Earth propellant, refills there
   with lunar oxygen plus methane, then departs for Mars. Methane is carried from
   Earth to the lunar surface by cargo landers, because the methalox surface-to-NRHO
   shuttle burns methane as well as oxygen.
C. LEO refill with lunar oxygen: all-lunar hydrogen-oxygen tankers carry lunar LOX
   down to LEO (aerocapture), while Earth tankers bring only the methane.

Lunar sorties: a Starship-class lander going LEO to NRHO to the surface and back to
NRHO, with and without surface refilling from the base.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from ..constants import G0
from ..mission import MissionAssumptions, Vehicle, mars_mission, mars_ship, vehicle_performance
from . import depot, orbits
from .provenance import Value

SPEC: dict[str, Value] = {
    "aerocapture_dv": Value(100.0, "m/s", "estimated", "perigee raise and trim after aerocapture into LEO"),
    "h2_tanker_dry_t": Value(60.0, "t", "estimated", "reusable hydrogen-oxygen tanker with heat shield"),
    "h2_tanker_prop_t": Value(600.0, "t", "estimated", "LH2 tanks are bulky; 600 t at MR 6"),
    "h2_tanker_cargo_t": Value(400.0, "t", "estimated", "LOX cargo tank of the NRHO-to-LEO tanker, structural limit"),
    "h2_mr": Value(6.0, "-", "estimated", "hydrogen-oxygen engine mixture ratio"),
    "methalox_mr": Value(3.6, "-", "cited", "Raptor 2, raptor_sim.benchmarks"),
    "lunar_cargo_t": Value(100.0, "t", "estimated", "cargo per one-way Starship-class lunar cargo landing"),
    "sortie_payload_t": Value(20.0, "t", "estimated", "crew cabin plus surface cargo for a lunar sortie"),
}


def _ve(isp: float) -> float:
    return isp * G0


@dataclass(frozen=True)
class Context:
    v: Vehicle
    m: MissionAssumptions
    payload_leo: float
    ve_vac: float  # RVac engines, in-space burns
    ve_sl: float  # sea-level engines in vacuum, landing and ascent


def context(v: Vehicle | None = None, m: MissionAssumptions | None = None) -> Context:
    v = v or Vehicle()
    m = m or MissionAssumptions()
    p = vehicle_performance(v, m)
    return Context(v, m, p.payload_to_leo_t, _ve(p.rvac_isp), _ve(p.sl_vac_isp))


def prop_for(mass_end_t: float, *legs: tuple[float, float]) -> float:
    """Propellant (t) to fly legs [(dv, ve), ...] ending at mass_end_t."""
    return mass_end_t * (math.exp(sum(dv / ve for dv, ve in legs)) - 1)


def launches_for_leo_prop(c: Context, prop_t: float) -> float:
    """Tanker launches to put prop_t into a ship that arrived with its landing reserve."""
    return max(prop_t - c.m.ship_landing_reserve_t, 0.0) / c.payload_leo


def lunar_cargo_launches_per_t(c: Context) -> float:
    """Earth launches per tonne landed on the lunar surface by a one-way cargo ship refilled in LEO."""
    cargo = SPEC["lunar_cargo_t"].value
    legs = [(orbits.leg("LEO->TLI") + orbits.leg("TLI->LLO"), c.ve_vac), (orbits.leg("LLO->surface"), c.ve_sl)]
    prop = prop_for(c.v.ship_dry_t + cargo, *legs)
    if prop > c.v.ship_propellant_t:
        raise ValueError("cargo lander exceeds tank capacity")
    return (1.0 + launches_for_leo_prop(c, prop)) / cargo


@dataclass(frozen=True)
class MarsScenario:
    name: str
    earth_launches: float
    lunar_water_t: float  # mined per Mars mission
    lunar_oxygen_t: float  # lunar O2 consumed per Mars mission, including shuttle burn
    notes: str


def scenario_a(c: Context) -> MarsScenario:
    r = mars_mission(c.v, c.m)
    t = launches_for_leo_prop(c, r.propellant_needed_t)
    return MarsScenario("A. Earth only, LEO refill (baseline)", 1 + t, 0.0, 0.0,
                        f"{r.propellant_needed_t:.0f} t propellant in LEO")


def scenario_b(c: Context) -> MarsScenario:
    cargo = c.m.mars_cargo_requirement_t
    end = mars_ship(c.v).ship_dry_t + cargo
    # NRHO -> Mars, then landing; the ship arrives at NRHO dry except what it refills.
    mars_legs = [(orbits.mars_departure("NRHO"), c.ve_vac), (c.m.dv_mars_landing, c.ve_sl)]
    prop_nrho = prop_for(end, *mars_legs)
    # LEO -> NRHO on Earth propellant.
    to_nrho = orbits.leg("LEO->TLI") + orbits.leg("TLI->NRHO")
    prop_leo = prop_for(end, (to_nrho, c.ve_vac))
    t_leo = launches_for_leo_prop(c, prop_leo)

    mr = SPEC["methalox_mr"].value
    sh = [s for s in depot.shuttle_cases() if "Methalox" in s.name and "NRHO" in s.name][0]
    trips = prop_nrho / sh.delivered_t
    ch4_at_surface = trips * (sh.burned_t + sh.delivered_t) / (1 + mr)
    o2 = trips * (sh.burned_t + sh.delivered_t) * mr / (1 + mr)
    ch4_launches = ch4_at_surface * lunar_cargo_launches_per_t(c)
    water = o2 * 18.015 / 16
    return MarsScenario("B. NRHO departure, lunar LOX + Earth CH4 via the surface", 1 + t_leo + ch4_launches,
                        water, o2,
                        f"{prop_leo:.0f} t Earth propellant to reach NRHO, {prop_nrho:.0f} t refilled at NRHO, "
                        f"{trips:.2f} shuttle trips, {ch4_at_surface:.0f} t CH4 landed on the Moon")


def h2_chain_to_leo(c: Context) -> dict[str, float]:
    """All-lunar hydrolox chain: surface -> NRHO shuttle, then NRHO -> LEO aerocapture tanker.

    Returns tonnes of lunar water, O2 and H2 per tonne of LOX cargo delivered to LEO.
    """
    isp = depot.hydrolox_isp()
    ve = _ve(isp)
    dry, prop, mr = SPEC["h2_tanker_dry_t"].value, SPEC["h2_tanker_prop_t"].value, SPEC["h2_mr"].value
    # Leg 1: NRHO -> LEO tanker, fuelled at NRHO. Carries LOX cargo in addition to its own propellant.
    down = orbits.leg("NRHO->TEI") + SPEC["aerocapture_dv"].value
    up = orbits.leg("LEO->TLI") + orbits.leg("TLI->NRHO")
    ret = prop_for(dry, (up, ve))
    # At NRHO it loads LOX cargo x (limited by its cargo tank) and just enough hydrolox q:
    # (dry + q + x) / (dry + ret + x) = exp(down / ve)
    k = math.exp(down / ve)
    x = SPEC["h2_tanker_cargo_t"].value
    q = k * (dry + ret + x) - dry - x
    if q > prop:
        raise ValueError("hydrolox LEO tanker tanks too small for this cargo")
    burned1 = q / x  # hydrolox loaded at NRHO per t of LOX delivered to LEO
    at_nrho = 1.0 + burned1
    # Leg 2: surface -> NRHO hydrolox shuttle delivers `at_nrho` with its gear ratio.
    sh = [s for s in depot.shuttle_cases() if "Hydrolox" in s.name and "NRHO" in s.name][0]
    shuttle_burn = at_nrho * sh.burned_t / sh.delivered_t
    hydrolox_total = burned1 + shuttle_burn  # all burned at MR 6
    h2 = hydrolox_total / (1 + mr)
    o2 = hydrolox_total * mr / (1 + mr) + 1.0
    water = max(h2 * 18.015 / 2.016, o2 * 18.015 / 16.0)
    return {"water_t": water, "o2_t": o2, "h2_t": h2, "x_per_trip_t": x, "isp_s": isp}


def scenario_c(c: Context) -> MarsScenario:
    r = mars_mission(c.v, c.m)
    mr = SPEC["methalox_mr"].value
    need = max(r.propellant_needed_t - c.m.ship_landing_reserve_t, 0.0)
    lox, ch4 = need * mr / (1 + mr), need / (1 + mr)
    chain = h2_chain_to_leo(c)
    return MarsScenario("C. LEO refill, lunar LOX by hydrolox tankers + Earth CH4", 1 + ch4 / c.payload_leo,
                        lox * chain["water_t"], lox * chain["o2_t"],
                        f"{lox:.0f} t lunar LOX and {ch4:.0f} t Earth CH4 in LEO; "
                        f"{lox / chain['x_per_trip_t']:.1f} LEO tanker trips")


def mars_scenarios(v: Vehicle | None = None, m: MissionAssumptions | None = None) -> list[MarsScenario]:
    c = context(v, m)
    return [scenario_a(c), scenario_b(c), scenario_c(c)]


@dataclass(frozen=True)
class SortieResult:
    name: str
    earth_launches: float
    lunar_o2_t: float
    notes: str


def lunar_sorties(v: Vehicle | None = None, m: MissionAssumptions | None = None) -> list[SortieResult]:
    """Starship-class lander LEO -> NRHO -> surface -> NRHO with a sortie payload."""
    c = context(v, m)
    end = c.v.ship_dry_t + SPEC["sortie_payload_t"].value
    mr = SPEC["methalox_mr"].value
    to_nrho = orbits.leg("LEO->TLI") + orbits.leg("TLI->NRHO")
    down, up = orbits.nrho_to_surface(), orbits.surface_to_nrho()
    out = []
    p = prop_for(end, (to_nrho, c.ve_vac), (down, c.ve_sl), (up, c.ve_sl))
    note = "" if p <= c.v.ship_propellant_t else " (exceeds tank capacity)"
    out.append(SortieResult("Earth propellant only", 1 + launches_for_leo_prop(c, p), 0.0,
                            f"{p:.0f} t loaded in LEO{note}"))
    ascent = prop_for(end, (up, c.ve_sl))
    ch4 = ascent / (1 + mr)
    p2 = prop_for(end + ch4, (to_nrho, c.ve_vac), (down, c.ve_sl))
    out.append(SortieResult("Lunar LOX on the surface, ascent CH4 carried down", 1 + launches_for_leo_prop(c, p2),
                            ascent * mr / (1 + mr), f"{p2:.0f} t in LEO, {ascent:.0f} t loaded on the Moon"))
    p3 = prop_for(end, (to_nrho, c.ve_vac), (down, c.ve_sl))
    out.append(SortieResult("Full lunar methalox (needs lunar carbon, see isru)", 1 + launches_for_leo_prop(c, p3),
                            ascent * mr / (1 + mr), f"{p3:.0f} t in LEO"))
    return out


def sensitivity_dry_mass(dry_t: float = 150.0) -> list[MarsScenario]:
    """Same scenarios with the heavier ship that matches SpaceX's stated 100 t to LEO."""
    return mars_scenarios(replace(Vehicle(), ship_dry_t=dry_t))
