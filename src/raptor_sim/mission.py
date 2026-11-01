"""Step 4: two-stage vehicle sizing and Mars mission check.

The vehicle is a Starship-class two-stage system built around our engine. The
mission is Earth to Mars cargo with propellant refilled in low Earth orbit, and
a crewed-ship return using propellant made on Mars (ISRU).

Orbital mechanics are patched conics with circular coplanar planetary orbits.
That gives the minimum-energy (Hohmann) transfer; real windows need up to
about 10% more departure delta-v, which the margins below cover.

Vehicle numbers marked "public" come from https://en.wikipedia.org/wiki/SpaceX_Starship
(Block 3, checked 2026-10-31). Everything else is an assumption, named as such.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from scipy.optimize import brentq

from .constants import G0
from .engine import EngineDesign, size_engine

# Gravitational parameters (m^3/s^2), radii (m), orbit radii (m)
MU_SUN = 1.32712440018e20
MU_EARTH = 3.986004418e14
MU_MARS = 4.282837e13
R_EARTH = 6.371e6
R_MARS = 3.3895e6
AU = 1.495978707e11
A_EARTH = 1.0 * AU
A_MARS = 1.523679 * AU


def hohmann_vinf(r1: float = A_EARTH, r2: float = A_MARS) -> tuple[float, float, float]:
    """Hyperbolic excess speeds at departure and arrival (m/s) and transfer time (days)."""
    a_t = 0.5 * (r1 + r2)
    v1 = math.sqrt(MU_SUN / r1)
    v2 = math.sqrt(MU_SUN / r2)
    vp = math.sqrt(MU_SUN * (2 / r1 - 1 / a_t))
    va = math.sqrt(MU_SUN * (2 / r2 - 1 / a_t))
    tof = math.pi * math.sqrt(a_t**3 / MU_SUN) / 86400
    return vp - v1, v2 - va, tof


def burn_from_orbit(vinf: float, mu: float, r: float) -> float:
    """Delta-v from a circular orbit of radius r to a hyperbola with excess speed vinf."""
    return math.sqrt(vinf**2 + 2 * mu / r) - math.sqrt(mu / r)


@dataclass(frozen=True)
class MissionAssumptions:
    dv_to_leo: float = 9_400.0  # m/s including gravity and drag losses, assumption
    leo_altitude: float = 300e3  # m
    tmi_margin: float = 1.10  # covers non-Hohmann windows and finite burns
    # Mars retropropulsion after entry. Was 700 m/s (assumption); the Mars campaign's 6-DOF-lite EDL
    # simulation (raptor_sim.campaign) needs about 1,540 m/s equivalent: 121 t burned nominal by the
    # 109.8 t Mars ship with 100 t cargo at the steeper -12.4 deg entry (135 t loaded).
    dv_mars_landing: float = 1_540.0  # m/s, model (campaign P6, 2026-11-01)
    mars_entry_fpa_deg: float = -12.4  # entry flight-path angle at 125 km, steepened for thin-air robustness (campaign R6)
    dv_mars_ascent_to_lmo: float = 4_100.0  # m/s Mars surface to low orbit incl. losses, assumption
    lmo_altitude: float = 300e3  # m
    dv_earth_return_entry: float = 0.0  # direct entry at Earth, no capture burn
    booster_landing_reserve: float = 0.14  # fraction kept for return; campaign booster-return sim needs 14% (was 8%)
    ship_landing_reserve_t: float = 30.0  # t kept by every ship for landing, assumption
    mars_cargo_requirement_t: float = 100.0  # G0 requirement: cargo landed on Mars


@dataclass(frozen=True)
class Vehicle:
    """Starship-class two-stage vehicle (Block 3 public figures where stated)."""

    booster_propellant_t: float = 3_650.0  # public
    booster_dry_t: float = 275.0  # public
    booster_engines: int = 33  # public
    ship_propellant_t: float = 1_600.0  # public
    # Standard ship: what tankers and lunar ships fly. The Mars cargo ship adds the campaign
    # design changes on top of this, see mars_ship().
    ship_dry_t: float = 100.0  # Block 1 public; Block 3 not stated
    ship_sl_engines: int = 3  # public
    ship_vac_engines: int = 3  # public
    vac_eps: float = 80.0  # Raptor Vacuum area ratio, public (low confidence)
    engine: EngineDesign = field(default_factory=EngineDesign)


# Mars cargo ship changes from the Mars campaign (PR #12), now part of the main design:
# a 4th sea-level engine so the ship lands with one engine out (risk R7, +1.63 t at the public
# engine mass) and an ablative windward heat shield for the 12.3 km/s Earth return (risk R9, +6 t).
# Tankers and lunar ships keep the standard ship (raptor_sim.campaign.vehicle.tanker_stack).
MARS_SHIP_ADDED_ENGINES = 1
MARS_SHIP_ADDED_DRY_T = 1.63 + 6.0


def mars_ship(v: "Vehicle | None" = None) -> "Vehicle":
    """The Mars cargo ship: the standard ship ``v`` plus the campaign design changes."""
    v = v or Vehicle()
    return replace(v, ship_dry_t=v.ship_dry_t + MARS_SHIP_ADDED_DRY_T,
                   ship_sl_engines=v.ship_sl_engines + MARS_SHIP_ADDED_ENGINES)


@dataclass(frozen=True)
class VehiclePerformance:
    booster_isp: float  # s, average of sea level and vacuum
    ship_isp: float  # s, all six ship engines firing in vacuum (ascent to orbit)
    rvac_isp: float  # s, vacuum engines alone (in-space burns)
    sl_vac_isp: float  # s, sea-level engines in vacuum (Mars landing and ascent)
    liftoff_mass_t: float
    liftoff_thrust_to_weight: float
    payload_to_leo_t: float


def vehicle_performance(v: Vehicle, m: MissionAssumptions | None = None) -> VehiclePerformance:
    m = m or MissionAssumptions()
    sl = size_engine(v.engine)
    vac = size_engine(replace(v.engine, eps=v.vac_eps), p_ambient=0.0)
    # Vacuum engine: same chamber and flow as the sea-level engine.
    vac_thrust = sl.mdot * vac.isp_vac * G0
    ship_isp = (v.ship_sl_engines * sl.thrust_vac + v.ship_vac_engines * vac_thrust) / (
        (v.ship_sl_engines + v.ship_vac_engines) * sl.mdot * G0
    )
    booster_isp = 0.5 * (sl.isp_sl + sl.isp_vac)

    def leo_dv(payload_t: float) -> float:
        usable_b = v.booster_propellant_t * (1 - m.booster_landing_reserve)
        ship_full = v.ship_dry_t + v.ship_propellant_t + payload_t
        m0 = v.booster_dry_t + v.booster_propellant_t + ship_full
        m1 = m0 - usable_b
        dv1 = booster_isp * G0 * math.log(m0 / m1)
        ship_end = v.ship_dry_t + payload_t + m.ship_landing_reserve_t
        dv2 = ship_isp * G0 * math.log(ship_full / ship_end)
        return dv1 + dv2

    if leo_dv(0.0) < m.dv_to_leo:
        payload = 0.0
    else:
        payload = brentq(lambda p: leo_dv(p) - m.dv_to_leo, 0.0, 2_000.0)

    liftoff = v.booster_dry_t + v.booster_propellant_t + v.ship_dry_t + v.ship_propellant_t + payload
    twr = v.booster_engines * v.engine.thrust_sl / (liftoff * 1e3 * G0)
    return VehiclePerformance(booster_isp, ship_isp, vac.isp_vac, sl.isp_vac, liftoff, twr, payload)


@dataclass(frozen=True)
class MarsResult:
    tmi_dv: float  # m/s
    transfer_days: float
    cargo_requirement_t: float
    propellant_needed_t: float  # in LEO, to land the required cargo
    cargo_max_t: float  # cargo the ship could land with full tanks, ignoring structure
    tanker_flights: int  # tanker launches to supply that propellant
    return_dv: float  # m/s Mars surface to Earth transfer
    isru_propellant_t: float  # propellant made on Mars for return with return_payload_t
    return_payload_t: float
    meets_requirement: bool


def mars_mission(
    v: Vehicle | None = None,
    m: MissionAssumptions | None = None,
    return_payload_t: float = 20.0,
) -> MarsResult:
    """Mars cargo mission. ``v`` is the standard ship: the tankers fly it as is, and the cargo
    ship is ``mars_ship(v)`` (4th sea-level engine and ablator)."""
    base = v or Vehicle()
    m = m or MissionAssumptions()
    v = mars_ship(base)
    perf = vehicle_performance(v, m)
    tanker_payload = vehicle_performance(base, m).payload_to_leo_t
    ve_rvac = perf.rvac_isp * G0  # trans-Mars and trans-Earth burns
    ve_sl = perf.sl_vac_isp * G0  # landing and ascent on the sea-level engines

    vinf_dep, vinf_arr, tof = hohmann_vinf()
    tmi = m.tmi_margin * burn_from_orbit(vinf_dep, MU_EARTH, R_EARTH + m.leo_altitude)

    # Propellant the ship needs in LEO to land the required cargo:
    # (dry + cargo + prop) / (dry + cargo) = exp(dv / ve)
    ratio = math.exp(tmi / ve_rvac + m.dv_mars_landing / ve_sl)
    cargo_req = m.mars_cargo_requirement_t
    prop_needed = (v.ship_dry_t + cargo_req) * (ratio - 1)
    # Most cargo the ship could land with full tanks (before structural limits).
    cargo_max = max((v.ship_propellant_t - (ratio - 1) * v.ship_dry_t) / (ratio - 1), 0.0)

    # Tankers: each is a ship that delivers its LEO payload as propellant. The
    # cargo ship reaches orbit holding its landing reserve; the rest is refilled.
    to_fill = max(prop_needed - m.ship_landing_reserve_t, 0.0)
    tankers = math.ceil(to_fill / tanker_payload) if tanker_payload > 0 else 10**6

    # Return: Mars surface to low orbit, then a burn onto the Earth transfer.
    tei = burn_from_orbit(vinf_arr, MU_MARS, R_MARS + m.lmo_altitude)
    tei_dv = m.tmi_margin * tei + m.dv_earth_return_entry
    ret = m.dv_mars_ascent_to_lmo + tei_dv
    isru = (v.ship_dry_t + return_payload_t) * (math.exp(m.dv_mars_ascent_to_lmo / ve_sl + tei_dv / ve_rvac) - 1)

    return MarsResult(
        tmi_dv=tmi,
        transfer_days=tof,
        cargo_requirement_t=cargo_req,
        propellant_needed_t=prop_needed,
        cargo_max_t=cargo_max,
        tanker_flights=tankers,
        return_dv=ret,
        isru_propellant_t=isru,
        return_payload_t=return_payload_t,
        meets_requirement=prop_needed <= v.ship_propellant_t and isru <= v.ship_propellant_t,
    )
