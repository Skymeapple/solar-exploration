"""Crewed mission cases that combine the crew models into one assessment each.

Cases: Moon reference sortie, Mars conjunction class on a Starship-class
chemical ship (this repo's vehicle), fastest Mars transit that ship can fly,
Mars opposition class on nuclear thermal propulsion, Mars by nuclear
electric propulsion, and two farther targets (Ceres, Callisto).

Constraints used for pass/fail (see report for sources):
- Career dose < 600 mSv (CITED NASA-STD-3001).
- Peak entry deceleration <= 5 g for crew after long microgravity (ESTIMATE;
  NASA-STD-3001 Vol 2 limits depend on duration and axis; 5 g sustained +Gx is
  our conservative reading for deconditioned crew; Apollo returns were ~6-7 g).
- Earth entry speed <= 12.5 km/s for a crewed heat shield (ESTIMATE).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace

import numpy as np

from ..constants import G0
from ..mission import AU, MU_SUN, MissionAssumptions, Vehicle, vehicle_performance
from . import entry as E
from . import life_support as LS
from . import radiation as RAD
from .gravity import bone_loss_fraction
from .orbits import DAY, lambert
from .propulsion import CHEM_CH4, NTP_LH2, NEPSystem, nep_trip, stage_mass, staged_stack
from .transfers import (capture_dv, circular_transfer, conjunction_class, departure_dv, entry_speed, opposition_class,
                        trip_time_trade)

G_LIMIT_DECONDITIONED = 5.0  # ESTIMATE
EARTH_ENTRY_LIMIT = 12_500.0  # ESTIMATE
MARS_ENTRY_LIMIT = 7_500.0  # ESTIMATE for a Starship-class ship (no public figure)
CALLISTO_MSV_D = 0.10  # CITED approx.: NASA HOPE study (Troutman et al. 2003), ~0.01 rem/day at Callisto
OUTFITTING_T = 25.0  # ESTIMATE crew cabin, ECLSS integration, EVA suits, rover for a 6-crew Mars ship


@dataclass
class CrewMission:
    name: str
    propulsion: str
    crew: int
    outbound_days: float
    stay_days: float
    return_days: float
    surface: str
    hull_gcm2: float
    dose_solar_min: float
    dose_solar_max: float
    consumables_t: float
    entry_speed_return: float
    entry_peak_g: float
    bone_loss: float
    notes: list = field(default_factory=list)

    @property
    def total_days(self) -> float:
        return self.outbound_days + self.stay_days + self.return_days

    @property
    def dose_ok(self) -> bool:
        return self.dose_solar_min < RAD.CAREER_LIMIT_MSV

    @property
    def g_ok(self) -> bool:
        return self.entry_peak_g <= G_LIMIT_DECONDITIONED

    def row(self) -> dict:
        d = asdict(self)
        d.update(total_days=self.total_days, dose_ok=self.dose_ok, g_ok=self.g_ok)
        return d


def guided_entry_peak_g(vehicle: E.EntryVehicle, planet: str, v_entry: float, g_limit: float) -> float:
    """Peak g for an entry flown at the middle of the corridor with a mid-bank angle (ESTIMATE of guidance)."""
    c = E.entry_corridor(vehicle, planet, v_entry, g_limit)
    if c.width_deg <= 0:
        return E.simulate_entry(vehicle, planet, v_entry, c.shallow_deg - 0.2, bank=0.0).peak_g
    gam = 0.5 * (c.shallow_deg + c.steep_deg)
    return E.simulate_entry(vehicle, planet, v_entry, gam, bank=0.0).peak_g


def _dose(transit, stay, surface, hull=20.0, material="aluminum"):
    lo = RAD.mission_dose(transit, stay, surface, hull_gcm2=hull, hull_material=material, solar="min").total_msv
    hi = RAD.mission_dose(transit, stay, surface, hull_gcm2=hull, hull_material=material, solar="max").total_msv
    return lo, hi


def moon_reference(crew: int = 4, stay: float = 10.0) -> CrewMission:
    lo, hi = _dose(6.0, stay, "moon_surface")
    v = 11_000.0  # CITED order: lunar return entry ~11 km/s
    g = guided_entry_peak_g(E.CAPSULE_ORION_CLASS, "earth", v, 8.0)
    cons = LS.consumables(crew, 6 + stay, "open").total_kg / 1e3
    return CrewMission("Moon sortie (reference)", "chemical", crew, 3, stay, 3, "moon_surface", 20.0, lo, hi, cons,
                       v, g, bone_loss_fraction(6), ["Detailed lunar work is in the crewed lunar missions thread."])


@dataclass(frozen=True)
class StarshipCrewCapability:
    ship_dry_t: float
    payload_t: float
    tmi_capability: float  # m/s with full tanks in LEO, keeping the Mars landing propellant
    fastest_tof_days: int  # with the Mars entry-speed limit
    fastest_entry_speed: float
    fastest_tof_no_entry_limit: int  # if the ship could survive any Mars entry speed


def starship_crew_capability(ship_dry_t: float = 120.0, crew: int = 6, mission_days: float = 950.0) -> StarshipCrewCapability:
    """How fast this repo's Starship-class ship can get crew to Mars after full LEO refilling."""
    v = Vehicle(ship_dry_t=ship_dry_t)
    m = MissionAssumptions()
    perf = vehicle_performance(v, m)
    payload = OUTFITTING_T + LS.consumables(crew, mission_days, "iss").total_kg / 1e3
    end = ship_dry_t + payload
    land_prop = end * (math.exp(m.dv_mars_landing / (perf.sl_vac_isp * G0)) - 1)
    tmi_cap = perf.rvac_isp * G0 * math.log((end + v.ship_propellant_t) / (end + land_prop))
    trade = trip_time_trade(tofs=range(80, 281, 10), max_entry_speed=MARS_ENTRY_LIMIT)
    feasible = [p for p in trade if p.tmi_dv <= tmi_cap]
    fastest = min(feasible, key=lambda p: p.tof_days) if feasible else None
    free = [p for p in trip_time_trade(tofs=range(80, 281, 10)) if p.tmi_dv <= tmi_cap]
    return StarshipCrewCapability(ship_dry_t, payload, tmi_cap, fastest.tof_days if fastest else -1,
                                  fastest.arrival_entry_speed if fastest else float("nan"),
                                  min(p.tof_days for p in free) if free else -1)


def mars_conjunction(crew: int = 6, depart: str = "2028-12-01") -> tuple[CrewMission, object]:
    rt = conjunction_class(depart)
    lo, hi = _dose(rt.transit_days, rt.stay_days, "mars_surface")
    cons = LS.consumables(crew, rt.total_days, "iss").total_kg / 1e3
    g_e = guided_entry_peak_g(E.SHIP_STARSHIP_CLASS, "earth", rt.earth_entry_speed, G_LIMIT_DECONDITIONED)
    cm = CrewMission("Mars conjunction class", "chemical CH4/LOX, LEO refilling, Mars ISRU", crew,
                     rt.outbound.tof_days, rt.stay_days, rt.inbound.tof_days, "mars_surface", 20.0, lo, hi, cons,
                     rt.earth_entry_speed, g_e, bone_loss_fraction(rt.transit_days, partial_g=0.0),
                     [f"Depart {rt.outbound.depart}, return {rt.inbound.arrive}",
                      f"TMI {rt.tmi_dv:.0f} m/s, TEI {rt.tei_dv:.0f} m/s, Mars entry {rt.mars_entry_speed:.0f} m/s"])
    return cm, rt


def mars_opposition_ntp(crew: int = 6, depart: str = "2033-04-01", stay: int = 30) -> tuple[CrewMission, object]:
    rt = opposition_class(depart, stay_days=stay)
    lo, hi = _dose(rt.transit_days, rt.stay_days, "mars_surface")
    cons = LS.consumables(crew, rt.total_days, "iss").total_kg / 1e3
    g_e = guided_entry_peak_g(E.CAPSULE_ORION_CLASS, "earth", rt.earth_entry_speed, G_LIMIT_DECONDITIONED)
    # NTP stack: TMI + Mars capture (propulsive, 1-sol) + TEI; crew returns in capsule
    payload = 60.0 + cons  # habitat 60 t (ESTIMATE, DRA 5.0 order) + consumables
    dv = rt.tmi_dv + capture_dv("mars", 0) * 0 + rt.tei_dv
    prop, m0 = stage_mass(NTP_LH2, payload, dv)
    prop_c, m0_c = stage_mass(CHEM_CH4, payload, dv)
    cm = CrewMission("Mars opposition class (30-day stay)", "nuclear thermal LH2", crew, rt.outbound.tof_days,
                     rt.stay_days, rt.inbound.tof_days, "mars_surface", 20.0, lo, hi, cons, rt.earth_entry_speed,
                     g_e, bone_loss_fraction(rt.transit_days),
                     [f"Depart {rt.outbound.depart}; TMI {rt.tmi_dv:.0f} m/s, TEI {rt.tei_dv:.0f} m/s",
                      f"Earth entry {rt.earth_entry_speed:.0f} m/s exceeds the 12.5 km/s estimate; capsule heat shield needed",
                      f"Single-stage mass in LEO (TMI+TEI, aerocapture at Mars): NTP {m0:.0f} t vs CH4/LOX {m0_c:.0f} t"])
    return cm, rt


def mars_nep(crew: int = 6, power_mwe: float = 10.0, alpha: float = 5.0) -> CrewMission:
    sysm = NEPSystem(f"NEP {power_mwe:g} MWe, {alpha:g} kg/kWe", power_mwe, alpha, 4_000.0, 0.6)
    payload = 60.0 + LS.consumables(crew, 600, "iss").total_kg / 1e3
    trip = nep_trip(sysm, payload)
    one_way = trip.trip_days
    lo, hi = _dose(2 * one_way, 30, "mars_surface")
    cons = LS.consumables(crew, 2 * one_way + 30, "iss").total_kg / 1e3
    return CrewMission(f"Mars by NEP ({power_mwe:g} MWe, {alpha:g} kg/kWe)", "nuclear electric", crew, one_way, 30,
                       one_way, "mars_surface", 20.0, lo, hi, cons, 11_600.0,
                       guided_entry_peak_g(E.CAPSULE_ORION_CLASS, "earth", 11_600.0, G_LIMIT_DECONDITIONED),
                       bone_loss_fraction(2 * one_way),
                       [f"L0 estimate: heliocentric leg only, {trip.initial_mass_t:.0f} t initial mass, "
                        f"thrust {sysm.thrust():.0f} N", "Assumes crew taxi to a high Earth orbit and a capsule return",
                        "Ignores planetary phasing: a 30-day stay return needs opposition-class geometry"])


def hohmann_days(r1: float, r2: float) -> float:
    return math.pi * math.sqrt(((r1 + r2) / 2) ** 3 / MU_SUN) / DAY


def far_target(name: str, a_au: float, crew: int = 6, tof_days: float | None = None, stay: float = 90.0,
               surface_rate: float | None = None, system=NTP_LH2) -> CrewMission:
    r2 = a_au * AU
    tof = tof_days or hohmann_days(AU, r2)
    vd, va = circular_transfer(AU, r2, tof)
    lo, hi = _dose(2 * tof, 0, "mars_surface")
    s = stay * (surface_rate if surface_rate is not None else RAD.gcr_rate(10.0, solar="min", environment="moon_surface"))
    lo, hi = lo + s, hi + s
    cons = LS.consumables(crew, 2 * tof + stay, "advanced").total_kg / 1e3
    vin = entry_speed("earth", vd)
    # Burns: Earth departure from LEO, capture at target, target departure, Earth capture down to the
    # entry limit. Target burns get no gravity-well (Oberth) credit: conservative L0 estimate.
    earth_brake = max(vd - math.sqrt(max(EARTH_ENTRY_LIMIT**2 - (vin**2 - vd**2), 0.0)), 0.0)
    burns = [departure_dv("earth", vd), va, va, earth_brake]
    m0 = staged_stack(system, 60.0 + cons, burns)
    return CrewMission(f"{name} ({tof:.0f}-day legs)", system.name, crew, tof, stay, tof, "low-gravity surface",
                       20.0, lo, hi, cons, vin, guided_entry_peak_g(E.CAPSULE_ORION_CLASS, "earth", min(vin, 13_500), G_LIMIT_DECONDITIONED),
                       bone_loss_fraction(2 * tof), [f"v-inf depart {vd/1e3:.1f} km/s, arrive {va/1e3:.1f} km/s; "
                                                    f"staged {system.name} stack {m0:,.0f} t in LEO (L0, no target gravity-well credit)"])


def all_cases() -> dict:
    out = {}
    out["moon"] = moon_reference()
    out["mars_conjunction"], rt_c = mars_conjunction()
    out["mars_opposition_ntp"], rt_o = mars_opposition_ntp()
    out["mars_nep"] = mars_nep()
    out["ceres_ntp"] = far_target("Ceres", 2.77, tof_days=None, stay=90)
    out["callisto_ntp"] = far_target("Callisto (Jupiter)", 5.20, tof_days=None, stay=30, surface_rate=CALLISTO_MSV_D)
    out["callisto_fast"] = far_target("Callisto fast", 5.20, tof_days=700, stay=30, surface_rate=CALLISTO_MSV_D)
    return out
