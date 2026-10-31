"""Interplanetary transfers for crewed missions: window scans, trip-time
trades and round-trip (conjunction and opposition class) mission design.

Method: Lambert arcs between planet positions from the Standish ephemeris
(see orbits.py). Departure burns start from a circular parking orbit; arrival
is either aerocapture/direct entry (no burn, entry speed reported) or a
propulsive capture into an elliptical orbit. Gravity assists are not
modelled (ESTIMATE: Venus swing-by opposition missions save roughly 1 to 2
km/s and are noted in the report only).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..mission import MU_EARTH, MU_MARS, R_EARTH, R_MARS, burn_from_orbit
from ..mission import MU_SUN
from .orbits import DAY, date_from_jd, jd_from_date, lambert, planet_state

ENTRY_INTERFACE = {"earth": 120e3, "mars": 125e3}  # m, conventional values
MU = {"earth": MU_EARTH, "mars": MU_MARS}
RADIUS = {"earth": R_EARTH, "mars": R_MARS}


@dataclass(frozen=True)
class Leg:
    origin: str
    target: str
    depart_jd: float
    tof_days: float
    vinf_depart: float  # m/s
    vinf_arrive: float  # m/s
    c3: float  # km^2/s^2

    @property
    def depart(self) -> str:
        return date_from_jd(self.depart_jd)

    @property
    def arrive(self) -> str:
        return date_from_jd(self.depart_jd + self.tof_days)


def leg(origin: str, target: str, depart_jd: float, tof_days: float) -> Leg | None:
    r1, v1p = planet_state(origin, depart_jd)
    r2, v2p = planet_state(target, depart_jd + tof_days)
    sol = lambert(r1, r2, tof_days * DAY)
    if sol is None:
        return None
    vi1 = float(np.linalg.norm(sol[0] - v1p))
    vi2 = float(np.linalg.norm(sol[1] - v2p))
    return Leg(origin, target, depart_jd, tof_days, vi1, vi2, vi1**2 / 1e6)


def entry_speed(body: str, vinf: float) -> float:
    """Speed at entry interface from hyperbolic excess speed (m/s)."""
    r = RADIUS[body] + ENTRY_INTERFACE[body]
    return math.sqrt(vinf**2 + 2 * MU[body] / r)


def departure_dv(body: str, vinf: float, alt: float = 300e3) -> float:
    return burn_from_orbit(vinf, MU[body], RADIUS[body] + alt)


def capture_dv(body: str, vinf: float, peri_alt: float = 250e3, period_days: float = 1.0) -> float:
    """Propulsive capture into an elliptical orbit of given period (ESTIMATE: 1-sol orbit at Mars)."""
    mu, rp = MU[body], RADIUS[body] + peri_alt
    a = (mu * (period_days * DAY / (2 * math.pi)) ** 2) ** (1 / 3)
    return math.sqrt(vinf**2 + 2 * mu / rp) - math.sqrt(mu * (2 / rp - 1 / a))


def scan(origin: str, target: str, center: str, half_width_days: int, tofs: range, step: int = 2,
         cost=lambda L: L.vinf_depart) -> list[Leg]:
    """Grid of legs around a centre date; returns all solutions."""
    jd0 = jd_from_date(center)
    out = []
    for dd in range(-half_width_days, half_width_days + 1, step):
        for tof in tofs:
            L = leg(origin, target, jd0 + dd, tof)
            if L is not None:
                out.append(L)
    return out


def best_leg(legs: list[Leg], cost) -> Leg:
    return min(legs, key=cost)


@dataclass(frozen=True)
class TripTimePoint:
    tof_days: int
    leg: Leg
    tmi_dv: float  # m/s from 300 km LEO
    arrival_entry_speed: float  # m/s at Mars entry interface (aerocapture)
    arrival_capture_dv: float  # m/s if captured propulsively


def trip_time_trade(center: str = "2028-12-01", tofs=range(70, 271, 10), half_width: int = 120,
                    max_entry_speed: float | None = None) -> list[TripTimePoint]:
    """For each flight time, the cheapest Earth-to-Mars departure in the window.

    Cost = TMI delta-v (arrival by aerocapture). If max_entry_speed is set,
    legs whose Mars entry speed exceeds it are rejected.
    """
    out = []
    jd0 = jd_from_date(center)
    for tof in tofs:
        best = None
        for dd in range(-half_width, half_width + 1, 2):
            L = leg("earth", "mars", jd0 + dd, tof)
            if L is None:
                continue
            ve = entry_speed("mars", L.vinf_arrive)
            if max_entry_speed and ve > max_entry_speed:
                continue
            dv = departure_dv("earth", L.vinf_depart)
            if best is None or dv < best[0]:
                best = (dv, L, ve)
        if best:
            dv, L, ve = best
            out.append(TripTimePoint(tof, L, dv, ve, capture_dv("mars", L.vinf_arrive)))
    return out


@dataclass(frozen=True)
class RoundTrip:
    kind: str
    outbound: Leg
    inbound: Leg
    stay_days: float
    total_days: float
    tmi_dv: float
    mars_entry_speed: float
    tei_dv: float  # from 300 km low Mars orbit (or ascent then TEI)
    earth_entry_speed: float

    @property
    def transit_days(self) -> float:
        return self.outbound.tof_days + self.inbound.tof_days


def round_trip(kind: str, depart_center: str, out_tofs, stay_range, in_tofs, max_total_days: float | None = None,
               half_width: int = 60, step: int = 4, max_earth_entry: float = 12_500.0,
               max_mars_entry: float = 8_500.0, keep_outbound: int = 40) -> RoundTrip:
    """Cheapest round trip (TMI + TEI delta-v) for given leg-time and stay ranges.

    Conjunction class: long stay waiting for the next low-energy return.
    Opposition class: short stay, at the cost of a high-energy leg.
    """
    jd0 = jd_from_date(depart_center)
    outs = []
    for dd in range(-half_width, half_width + 1, step):
        for tof in out_tofs:
            L = leg("earth", "mars", jd0 + dd, tof)
            if L and entry_speed("mars", L.vinf_arrive) <= max_mars_entry:
                outs.append(L)
    # keep the cheapest outbound legs to limit the search
    outs.sort(key=lambda L: departure_dv("earth", L.vinf_depart))
    best = None
    for L in outs[:keep_outbound]:
        arr = L.depart_jd + L.tof_days
        for stay in stay_range:
            for tin in in_tofs:
                total = L.tof_days + stay + tin
                if max_total_days and total > max_total_days:
                    continue
                R = leg("mars", "earth", arr + stay, tin)
                if R is None or entry_speed("earth", R.vinf_arrive) > max_earth_entry:
                    continue
                cost = departure_dv("earth", L.vinf_depart) + departure_dv("mars", R.vinf_depart)
                if best is None or cost < best[0]:
                    best = (cost, L, R, stay, total)
    if best is None:
        raise ValueError(f"no {kind} round trip meets the constraints")
    _, L, R, stay, total = best
    return RoundTrip(kind, L, R, stay, total, departure_dv("earth", L.vinf_depart),
                     entry_speed("mars", L.vinf_arrive), departure_dv("mars", R.vinf_depart),
                     entry_speed("earth", R.vinf_arrive))


def conjunction_class(depart_center: str = "2028-12-01") -> RoundTrip:
    return round_trip("conjunction", depart_center, range(150, 241, 10), range(400, 621, 10), range(150, 241, 10))


def opposition_class(depart_center: str = "2028-12-01", stay_days: int = 30, max_total: float = 650,
                     max_earth_entry: float = 14_000.0) -> RoundTrip:
    """Short-stay mission. Earth entry is allowed up to 14 km/s (ESTIMATE, a
    capsule-class heat-shield limit; Stardust entered at 12.9 km/s)."""
    return round_trip("opposition", depart_center, range(120, 301, 15), range(stay_days, stay_days + 1),
                      range(150, 451, 10), max_total_days=max_total, half_width=240, step=8,
                      max_earth_entry=max_earth_entry, max_mars_entry=9_000.0, keep_outbound=400)


def circular_transfer(r1: float, r2: float, tof_days: float) -> tuple[float, float]:
    """Cheapest departure and arrival v-infinity for a transfer between circular coplanar orbits."""
    best = None
    for ang in np.radians(np.arange(40, 181, 2)):
        a = np.array([r1, 0.0, 0.0])
        b = np.array([r2 * math.cos(ang), r2 * math.sin(ang), 0.0])
        if ang >= math.pi - 1e-6:
            b = np.array([-r2, 1e-3 * r2, 0.0])
        sol = lambert(a, b, tof_days * DAY)
        if sol is None:
            continue
        v1c = np.array([0.0, math.sqrt(MU_SUN / r1), 0.0])
        v2c = math.sqrt(MU_SUN / r2) * np.array([-math.sin(ang), math.cos(ang), 0.0])
        d, arr = float(np.linalg.norm(sol[0] - v1c)), float(np.linalg.norm(sol[1] - v2c))
        if best is None or d + arr < best[0] + best[1]:
            best = (d, arr)
    return best
