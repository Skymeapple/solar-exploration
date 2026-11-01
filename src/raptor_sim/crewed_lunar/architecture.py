"""Crewed lunar mission architectures, sized end to end on our engine and vehicle.

Architectures:
  A  "nrho_hls"      Artemis-style: Orion to NRHO; a Starship-class lander refilled
                     in LEO flies to NRHO, lands, returns crew to Orion. (Artemis IV plan.)
  B  "llo_orion"     Same, but staging in low lunar orbit. Tests whether Orion can do it.
  C  "direct_ship"   One crewed Starship refilled in LEO lands and flies the crew straight
                     back to an Earth entry at lunar return speed. No Orion, no SLS.
  D  "reusable_isru" Future: a lander that stays in NRHO and is refilled. Oxygen comes
                     from lunar ice on the surface; the rest is delivered from Earth.
                     Two variants: methane/oxygen (our Raptor; carbon from Earth) and
                     hydrogen/oxygen (all propellant from ice; a new engine).

All burns use the rocket equation. Descent and ascent delta-v come from the
integrated landing simulation for the actual lander mass and thrust, so
gravity losses follow the design. Patched-conic legs come from legs.py and
three-body NRHO legs from cited NASA values (reference.TRAJECTORY).

Inputs marked "estimated" are ours; every one is a field you can change.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from ..constants import G0
from ..mission import MissionAssumptions, Vehicle, vehicle_performance
from .landing import DescentProfile, Lander, simulate_ascent, simulate_descent
from .legs import descent_orbit_insertion_dv, lunar_orbit_insertion_dv, tli_dv, tli_transfer_days
from .reference import BLUE_MOON_MK2, LUNAR_RESOURCES, ORION, RAPTOR, TRAJECTORY


@dataclass(frozen=True)
class LunarAssumptions:
    crew: int = 4
    surface_cargo_t: float = 10.0  # estimated: crew, suits, rovers, science down to the surface
    ascent_payload_t: float = 1.0  # estimated: crew and samples carried up (cabin is in dry mass)
    hls_dry_t: float = 120.0  # estimated, see reference.STARSHIP_HLS["dry_mass"]
    crew_ship_dry_t: float = 130.0  # estimated: Starship with heat shield, crew cabin, legs
    dv_margin: float = 1.05  # estimated: on every computed or cited leg
    tanker_transfer_loss: float = 0.03  # estimated: fraction lost in each ship-to-ship transfer
    depot_launches: int = 1  # estimated: one depot ship, as in NASA's HLS concept
    leo_alt: float = 300e3
    llo_alt: float = 100e3
    braking_engines: int = 1  # Raptors used for braking (sea-level variant)
    landing_thruster_twr: float = 1.6  # estimated: landing thrusters' max thrust / lunar weight at touchdown
    landing_thruster_isp: float = 320.0  # estimated: gaseous methane/oxygen thrusters
    landing_thruster_throttle_min: float = 0.2  # estimated
    hydrolox_isp: float = 460.2  # model: HL-44 expander design point, raptor_sim.hydrolox (BE-7 class, cited 460 s)
    hydrolox_mixture_ratio: float = 6.39  # model: HL-44 design point
    hydrolox_dry_t: float = 25.0  # estimated: reusable hydrogen lander, larger tanks than Blue Moon MK2 (16 t, cited)
    hydrolox_thrust_n: float = 9 * 44_000.0  # nine HL-44 engines (raptor_sim.hydrolox)
    methane_mixture_ratio: float = 3.6  # our engine
    return_staging_dv: float | None = None  # m/s, LLO to NRHO; None = nominal cited 705, set 1,550 for anytime abort


@dataclass(frozen=True)
class Burn:
    name: str
    dv: float  # m/s, including margin
    isp: float
    propellant_t: float = 0.0
    mass_before_t: float = 0.0


@dataclass
class ArchitectureResult:
    key: str
    name: str
    feasible: bool
    burns: list[Burn]
    vehicle_dry_t: float
    propellant_in_leo_t: float  # what the main vehicle must hold when it leaves LEO
    tanker_launches: int
    total_launches: int  # every heavy launch for one crewed landing
    sls_launches: int
    notes: list[str] = field(default_factory=list)
    descent: object | None = None
    ascent: object | None = None


def _back_chain(final_mass_t: float, legs: list[tuple[str, float, float, float]]) -> tuple[float, list[Burn]]:
    """Work backward through burns. legs = [(name, dv, isp, mass_added_before_burn_t)] in flight order.

    mass_added is mass that is aboard during this burn and every earlier one but
    left behind after it (e.g. surface cargo unloaded after landing).
    """
    m = final_mass_t
    out: list[Burn] = []
    for name, dv, isp, drop in reversed(legs):
        m_after = m
        m_before = m_after * math.exp(dv / (isp * G0))
        out.append(Burn(name, dv, isp, m_before - m_after, m_before))
        m = m_before + drop
    out.reverse()
    return m, out


def _engines():
    perf = vehicle_performance(Vehicle())
    from ..engine import size_engine

    sl = size_engine(Vehicle().engine)
    return perf, sl


def _lander_for(mass_kg: float, a: LunarAssumptions, landed_mass_kg: float, isp_sl: float, thrust_sl_vac: float) -> Lander:
    return Lander(
        name="Starship-class lander",
        mass=mass_kg,
        thrust_max=a.braking_engines * thrust_sl_vac,
        isp=isp_sl,
        throttle_min=RAPTOR["throttle_min"].value,
        terminal_thrust_max=a.landing_thruster_twr * landed_mass_kg * 1.625,
        terminal_isp=a.landing_thruster_isp,
        terminal_throttle_min=a.landing_thruster_throttle_min,
    )


def _landing_legs(m_pdi_t: float, m_land_t: float, m_liftoff_t: float, a: LunarAssumptions, isp_sl: float,
                  thrust_sl_vac: float, profile: DescentProfile | None = None):
    """Run descent and ascent sims for the given masses; returns (descent, ascent) results."""
    lander = _lander_for(m_pdi_t * 1e3, a, m_land_t * 1e3, isp_sl, thrust_sl_vac)
    d = simulate_descent(lander, profile)
    asc = simulate_ascent(replace(lander, name="Starship-class ascent", mass=m_liftoff_t * 1e3))
    return d, asc


def _ship_lander_mission(key: str, name: str, a: LunarAssumptions, dry_t: float, outbound: list, inbound: list,
                         end_reserve_t: float, staging_dv_down: float, staging_dv_up: float, profile=None):
    """Size a ship that lands and ascends, iterating the landing sims to the converged masses.

    outbound: legs before the staging-orbit-to-surface leg; inbound: legs after reaching
    the staging orbit again. Each leg is (name, dv, isp, drop).
    """
    perf, sl = _engines()
    isp_rvac, isp_sl = perf.rvac_isp, perf.sl_vac_isp
    dv_desc, dv_asc = 2_000.0, 1_850.0
    for _ in range(4):
        legs = (
            outbound
            + [("staging orbit to descent orbit", a.dv_margin * staging_dv_down, isp_rvac, 0.0),
               ("powered descent", a.dv_margin * dv_desc, isp_sl, a.surface_cargo_t),
               ("ascent to lunar orbit", a.dv_margin * dv_asc, isp_sl, 0.0),
               ("lunar orbit to staging orbit", a.dv_margin * staging_dv_up, isp_rvac, 0.0)]
            + inbound
        )
        m_leo, burns = _back_chain(dry_t + a.ascent_payload_t + end_reserve_t, legs)
        i = [b.name for b in burns].index("powered descent")
        m_pdi = burns[i].mass_before_t
        m_land = m_pdi - burns[i].propellant_t
        m_lift = burns[i + 1].mass_before_t
        d, asc = _landing_legs(m_pdi, m_land, m_lift, a, isp_sl, sl.thrust_vac, profile)
        # Terminal phase runs on the landing thrusters at lower Isp: express it as equivalent dv at isp_sl.
        term_prop_frac = 1 - math.exp(-d.terminal_dv / (a.landing_thruster_isp * G0))
        term_equiv = -isp_sl * G0 * math.log(1 - term_prop_frac)
        new_desc = d.braking_dv + term_equiv
        if abs(new_desc - dv_desc) < 1 and abs(asc.total_dv - dv_asc) < 1:
            break
        dv_desc, dv_asc = new_desc, asc.total_dv
    prop = m_leo - dry_t - a.surface_cargo_t - a.ascent_payload_t
    return m_leo, prop, burns, d, asc, perf


def _tankers(prop_needed_t: float, arrives_with_t: float, payload_to_leo_t: float, a: LunarAssumptions) -> int:
    delivered = payload_to_leo_t * (1 - a.tanker_transfer_loss)
    return max(math.ceil((prop_needed_t - arrives_with_t) / delivered), 0)


def nrho_hls(a: LunarAssumptions | None = None, vehicle: Vehicle | None = None) -> ArchitectureResult:
    a = a or LunarAssumptions()
    v = vehicle or Vehicle()
    m_assume = MissionAssumptions()
    perf_v = vehicle_performance(v)
    perf, _ = _engines()
    T = TRAJECTORY
    staging = T["nrho_to_llo"].value
    outbound = [
        ("trans-lunar injection", a.dv_margin * tli_dv(a.leo_alt), perf.rvac_isp, 0.0),
        ("NRHO insertion", a.dv_margin * T["tli_to_nrho"].value, perf.rvac_isp, 0.0),
    ]
    m_leo, prop, burns, d, asc, _ = _ship_lander_mission(
        "nrho_hls", "NRHO staging", a, a.hls_dry_t, outbound, [], 0.0, staging,
        a.return_staging_dv if a.return_staging_dv is not None else staging,
    )
    # LLO descent orbit: DOI is small and inside the NRHO-to-LLO budget, so it is not added.
    burns[2] = replace(burns[2], name="NRHO to low lunar orbit")
    burns[5] = replace(burns[5], name="low lunar orbit to NRHO")
    tank = _tankers(prop, m_assume.ship_landing_reserve_t, perf_v.payload_to_leo_t, a)
    orion_dv = T["tli_to_nrho"].value + T["nrho_to_tei"].value
    orion_cap = ORION["dv_after_upper_stage_sep"].value
    notes = [
        f"Orion needs {orion_dv:.0f} m/s (cited sum) of its {orion_cap:.0f} m/s: feasible with "
        f"{orion_cap - orion_dv:.0f} m/s spare.",
        f"Lander holds {prop:.0f} t of propellant in LEO of {v.ship_propellant_t:.0f} t tank capacity.",
    ]
    feasible = prop <= v.ship_propellant_t and orion_dv <= orion_cap
    return ArchitectureResult(
        "nrho_hls", "A. NRHO staging (Orion + refilled lander)", feasible, burns, a.hls_dry_t, prop,
        tank, 1 + a.depot_launches + tank, 1, notes, d, asc,
    )


def llo_orion(a: LunarAssumptions | None = None) -> ArchitectureResult:
    """Can Orion itself reach low lunar orbit and come home? Patched-conic and cited answers."""
    a = a or LunarAssumptions()
    loi = lunar_orbit_insertion_dv(a.llo_alt, a.leo_alt)
    need_computed = 2 * loi  # insertion and the mirror-image departure
    need_cited = TRAJECTORY["llo_loi_plus_tei"].value
    cap = ORION["dv_after_upper_stage_sep"].value
    notes = [
        f"Patched conic, coplanar, no margin: {need_computed:.0f} m/s (LOI {loi:.0f} + TEI {loi:.0f}).",
        f"NASA figure with Artemis design factors (global access, margins): {need_cited:.0f} m/s.",
        f"Orion capability: {cap:.0f} m/s. Short by {need_computed - cap:.0f} m/s even in the ideal case,"
        " which is why Artemis stages in NRHO.",
    ]
    burns = [Burn("lunar orbit insertion", loi, 0.0), Burn("trans-Earth injection", loi, 0.0)]
    return ArchitectureResult("llo_orion", "B. Low lunar orbit staging with Orion", need_computed <= cap,
                              burns, ORION["cm_dry_mass"].value / 1e3, 0.0, 0, 0, 1, notes)


def direct_ship(a: LunarAssumptions | None = None, vehicle: Vehicle | None = None) -> ArchitectureResult:
    a = a or LunarAssumptions()
    v = vehicle or Vehicle()
    m_assume = MissionAssumptions()
    perf_v = vehicle_performance(v)
    perf, _ = _engines()
    loi = lunar_orbit_insertion_dv(a.llo_alt, a.leo_alt)
    doi = descent_orbit_insertion_dv(a.llo_alt)
    outbound = [
        ("trans-lunar injection", a.dv_margin * tli_dv(a.leo_alt), perf.rvac_isp, 0.0),
        ("low lunar orbit insertion", a.dv_margin * loi, perf.rvac_isp, 0.0),
    ]
    inbound = [("trans-Earth injection", a.dv_margin * loi, perf.rvac_isp, 0.0)]
    # End: ship keeps its Earth landing reserve through entry at lunar return speed.
    m_leo, prop, burns, d, asc, _ = _ship_lander_mission(
        "direct_ship", "Direct", a, a.crew_ship_dry_t, outbound, inbound, m_assume.ship_landing_reserve_t, doi, 0.0,
    )
    burns = [b for b in burns if b.name != "lunar orbit to staging orbit"]
    burns = [replace(b, name="descent orbit insertion") if b.name == "staging orbit to descent orbit" else b
             for b in burns]
    total_prop = prop + m_assume.ship_landing_reserve_t
    tank = _tankers(total_prop, m_assume.ship_landing_reserve_t, perf_v.payload_to_leo_t, a)
    notes = [
        f"Ship holds {total_prop:.0f} t in LEO (incl. {m_assume.ship_landing_reserve_t:.0f} t Earth landing reserve) "
        f"of {v.ship_propellant_t:.0f} t capacity.",
        "Earth entry at about 11 km/s on a Starship heat shield qualified for 7.8 km/s LEO returns: "
        "the key new capability; see the entry check.",
    ]
    return ArchitectureResult(
        "direct_ship", "C. Direct crewed ship (no Orion)", total_prop <= v.ship_propellant_t, burns,
        a.crew_ship_dry_t, total_prop, tank, 1 + a.depot_launches + tank, 0, notes, d, asc,
    )


@dataclass(frozen=True)
class CislunarTanker:
    """A Starship tanker refilled in LEO that carries propellant to NRHO and returns to LEO by aerobraking."""

    delivered_t: float  # propellant delivered to the customer in NRHO per trip
    leo_propellant_t: float  # propellant the tanker must hold in LEO
    earth_launches: int  # launches to fill that tanker (its own launch plus LEO tankers)
    launches_per_100t: float


def cislunar_tanker(a: LunarAssumptions | None = None, vehicle: Vehicle | None = None) -> CislunarTanker:
    a = a or LunarAssumptions()
    v = vehicle or Vehicle()
    perf_v = vehicle_performance(v)
    ve = perf_v.rvac_isp * G0
    m_assume = MissionAssumptions()
    dv_out = a.dv_margin * (tli_dv(a.leo_alt) + TRAJECTORY["tli_to_nrho"].value)
    dv_back = a.dv_margin * TRAJECTORY["nrho_to_tei"].value  # then aerobrake into LEO (assumption)
    m_end = v.ship_dry_t + m_assume.ship_landing_reserve_t
    m_after_unload = m_end * math.exp(dv_back / ve)
    # Full tanks in LEO: dry + 1,600 t; payload P carried as propellant in the same tanks.
    m_leo = v.ship_dry_t + v.ship_propellant_t
    m_arrive = m_leo / math.exp(dv_out / ve)
    delivered = (m_arrive - m_after_unload) * (1 - a.tanker_transfer_loss)
    fill = _tankers(v.ship_propellant_t, m_assume.ship_landing_reserve_t, perf_v.payload_to_leo_t, a)
    launches = 1 + fill
    return CislunarTanker(delivered, v.ship_propellant_t, launches, 100 * launches / delivered)


@dataclass
class IsruResult:
    variant: str
    lander_dry_t: float
    isp: float
    sortie_propellant_t: float  # NRHO -> surface -> NRHO
    from_moon_t: float
    from_earth_t: float
    earth_launches_per_sortie: float
    ice_regolith_t: float  # icy regolith processed per sortie at the LCROSS concentration (100% recovery)
    notes: list[str]
    liftoff_mass_t: float = 0.0


def reusable_isru(a: LunarAssumptions | None = None, variant: str = "methane",
                  vehicle: Vehicle | None = None) -> IsruResult:
    """Reusable lander based in NRHO, refilled on the surface for the whole next round trip.

    Each sortie: NRHO -> surface with crew and cargo, refill on the surface, then
    surface -> NRHO carrying the propellant for the next descent. Oxygen (and for
    hydrolox, hydrogen) comes from lunar ice; anything else is flown from Earth to
    NRHO by cislunar tanker.
    """
    a = a or LunarAssumptions()
    perf, _ = _engines()
    T = TRAJECTORY
    ice = LUNAR_RESOURCES["cabeus_water_wt_frac"].value
    stage = T["nrho_to_llo"].value
    if variant in ("methane", "methane_full"):
        dry, isp, mr = a.hls_dry_t, perf.sl_vac_isp, a.methane_mixture_ratio
        ref = nrho_hls(a, vehicle)  # reuse its simulated landing and ascent delta-v
        dv_desc = ref.burns[3].dv / a.dv_margin
        dv_asc = ref.burns[4].dv / a.dv_margin
        thrust, tmin = None, None
    elif variant == "hydrolox":
        dry, isp, mr = a.hydrolox_dry_t, a.hydrolox_isp, a.hydrolox_mixture_ratio
        dv_desc, dv_asc = 2_000.0, 1_850.0
        thrust, tmin = a.hydrolox_thrust_n, BLUE_MOON_MK2["be7_min_thrust"].value / BLUE_MOON_MK2["be7_thrust"].value
    else:
        raise ValueError(variant)

    def sizes(dv_d, dv_a):
        # Methane cannot be made on the Moon: the lander carries down, as cargo, the methane
        # it will load on the surface. Iterate because that cargo raises the descent propellant.
        fuel_cargo = 0.0
        for _ in range(30):
            cargo = a.surface_cargo_t + fuel_cargo
            down = [("NRHO to LLO", a.dv_margin * stage, isp, 0.0), ("descent", a.dv_margin * dv_d, isp, 0.0)]
            m_nrho, _ = _back_chain(dry + a.ascent_payload_t + cargo, down)
            down_prop = m_nrho - dry - a.ascent_payload_t - cargo
            up = [("ascent", a.dv_margin * dv_a, isp, 0.0), ("LLO to NRHO", a.dv_margin * stage, isp, 0.0)]
            carried_up = down_prop if variant != "methane" else 0.0  # next descent's propellant
            m_lift, _ = _back_chain(dry + a.ascent_payload_t + carried_up, up)
            up_prop = m_lift - dry - a.ascent_payload_t - carried_up
            if variant == "methane_full":
                new = (up_prop + down_prop) / (1 + mr)
            elif variant == "methane":
                new = up_prop / (1 + mr)
            else:
                new = 0.0
            if abs(new - fuel_cargo) < 1e-3:
                break
            fuel_cargo = new
        return up_prop, down_prop, m_nrho, m_lift

    for _ in range(3 if thrust else 0):  # simulate the hydrolox lander's own landing and ascent
        up, down, m_nrho, m_lift = sizes(dv_desc, dv_asc)
        m_pdi = m_nrho / math.exp(a.dv_margin * stage / (isp * G0))
        lander = Lander("hydrolox lander", m_pdi * 1e3, thrust, isp, tmin)
        dsc = simulate_descent(lander)
        asc = simulate_ascent(replace(lander, mass=m_lift * 1e3))
        dv_desc, dv_asc = dsc.total_dv, asc.total_dv
    up, down, m_nrho, m_lift = sizes(dv_desc, dv_asc)
    total = up + down
    if variant == "methane":
        # Descent propellant loaded in NRHO from Earth; ascent oxygen made on the surface;
        # ascent methane landed as cargo.
        from_moon = up * mr / (1 + mr)
        water = from_moon * 18.015 / 15.999
        notes = ["Lunar ice gives oxygen and hydrogen, not carbon, so methane comes from Earth.",
                 f"Descent propellant ({down:.0f} t) is loaded in NRHO; only ascent oxygen ({from_moon:.0f} t) "
                 f"is made on the Moon; ascent methane ({up - from_moon:.0f} t) is landed as cargo."]
    elif variant == "methane_full":
        ox = total * mr / (1 + mr)
        from_moon = ox
        water = ox * 18.015 / 15.999
        notes = ["All oxygen for the next round trip made on the Moon; all methane landed as cargo.",
                 "Carrying the next descent's propellant up to NRHO costs more than it saves."]
    else:
        ox = total * mr / (1 + mr)
        fuel = total - ox
        from_moon = total
        water = max(fuel * 18.015 / 2.016, ox * 18.015 / 15.999)
        notes = ["Water splits 8:1 oxygen to hydrogen by mass; at mixture ratio "
                 f"{mr:.1f} hydrogen is the limit and {water * 15.999 / 18.015 - ox:.0f} t oxygen is left over."]
    from_earth = total - from_moon
    tk = cislunar_tanker(a, vehicle)
    launches = from_earth / tk.delivered_t * tk.earth_launches
    return IsruResult(variant, dry, isp, total, from_moon, from_earth, launches, water / ice, notes,
                      m_lift)


def run_all(a: LunarAssumptions | None = None, vehicle: Vehicle | None = None) -> dict:
    a = a or LunarAssumptions()
    return {
        "A": nrho_hls(a, vehicle),
        "B": llo_orion(a),
        "C": direct_ship(a, vehicle),
        "D_methane": reusable_isru(a, "methane", vehicle),
        "D_methane_full": reusable_isru(a, "methane_full", vehicle),
        "D_hydrolox": reusable_isru(a, "hydrolox", vehicle),
        "tanker": cislunar_tanker(a, vehicle),
        "transfer_days": tli_transfer_days(a.leo_alt),
    }
