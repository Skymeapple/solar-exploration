"""Campaign logistics: launches, propellant, fleet, pads and Mars ISRU power.

The manifest follows the schedule: each program step flies a set number of
ships while it runs, and commercial Mars cargo from the business case (PR #3)
rides on top. Every Mars ship is refilled in LEO by tankers, and all tanker
launches for a window crowd into the months just before it opens; that surge,
not the yearly total, sizes the pads and the depot.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from .catalog import Program
from .schedule import WINDOWS, Timing, to_year

G0 = 9.80665


@dataclass(frozen=True)
class VehicleCase:
    """Vehicle and refilling figures from PR #1 (model)."""
    name: str
    payload_leo_t: float
    mars_prop_in_leo_t: float
    mars_tankers: int


# model: campaign simulation with the Mars ship changes (2026-11-01): tankers (standard ship) carry 100 t
# to LEO; the Mars ship (4th engine, ablator) needs 806 t in LEO from 10 tankers. Before the changes
# (2026-10-31) it was 103 t and 9 tankers; PR #1's ideal vehicle gave 155 t and 4 tankers.
VEHICLE_CAMPAIGN = VehicleCase("Campaign vehicle (Mars ship changes: 100 t to LEO, 10 tankers)", 100.0, 806.0, 10)
VEHICLE_IDEAL = VehicleCase("Ideal vehicle (PR #1: 155 t to LEO, 4 tankers)", 155.0, 546.0, 4)


@dataclass(frozen=True)
class LogisticsAssumptions:
    booster_prop_t: float = 3_650.0      # public Block 3, via PR #1
    ship_prop_t: float = 1_600.0         # public Block 3, via PR #1
    mixture_ratio: float = 3.6           # model: PR #1 reference engine
    ship_isp_vac_s: float = 362.7        # model: PR #1 vacuum engine
    mars_dv_from_leo: float = 3_951.0 + 700.0   # model: PR #1 TMI + landing
    lunar_dv_from_leo: float = 3_200 + 900 + 2_000  # estimate, as in PR #3
    ship_reserve_t: float = 30.0         # model: PR #1 landing reserve
    surge_months: float = 4.0            # tankers for a window fly in the last 4 months, estimate
    pad_launches_per_month: float = 4.0  # one launch per pad per week, estimate
    boiloff_per_day: float = 0.001       # depot target 0.1%/day, estimate
    booster_life: int = 50               # flights, PR #3 estimate
    tanker_life: int = 20                # flights, PR #3 estimate
    engines_booster: int = 33
    engines_ship: int = 6
    isru_kwh_per_kg: float = 8.17        # model: PR #6 Mars Sabatier chain, 8.17 MWh per t (ideal 3.1)
    isru_return_prop_t: float = 642.0    # model: PR #1, return with 20 t
    isru_months: float = 12.6            # model: PR #12 makes return propellant in 383 days
    isru_duty: float = 0.9


# Ships flown per Mars window (mars) or per year (moon) while a step runs. Estimate;
# the Mars campaign and lunar threads own the real manifests.
MARS_SHIPS_PER_WINDOW = {
    "MARS-CARGO-1": 2, "MARS-CARGO-2": 2, "MARS-CREW-1": 4,  # sample return flies on a commercial launcher (PR #4)
    "MARS-BASE-1": 6, "SETTLEMENT-100": 12, "TRANSIT-NET": 1,
}
CREW_SHIPS = {"MARS-CREW-1": 2}
LUNAR_LANDINGS_PER_YEAR = {
    "LUNAR-CARGO-1": 1, "LUNAR-CREW-1": 1, "LUNAR-ISRU": 1, "LUNAR-BASE-1": 1, "LUNAR-SPACEPORT": 2,
    "LUNAR-SETTLE": 2,
}
# model: PR #9. Lunar oxygen refills on the surface cut Earth launches per lunar trip 9.6 -> 5.5;
# lunar oxygen delivered to LEO by hydrogen-oxygen tankers cuts launches per Mars ship 4.3 -> 1.7.
LUNAR_TRIP_FACTOR = (5.5 - 1) / (9.6 - 1)
MARS_TANKER_FACTOR_LUNAR_O2 = (1.7 - 1) / (4.3 - 1)
# Commercial Mars cargo per window after the first program landing (PR #3 base case ramp, model)
COMMERCIAL_MARS_RAMP = (0, 1, 2, 3, 4, 5, 6)
LEO_COMMERCIAL_RAMP = (2, 5, 9, 14, 19, 24, 29, 34, 38, 42, 45)  # PR #3 base, launches per year


def mass_ratio(dv: float, isp: float) -> float:
    return math.exp(dv / (isp * G0))


def lunar_tankers(v: VehicleCase, a: LogisticsAssumptions) -> int:
    """Scale PR #1's Mars refilling to the lunar delta-v (same method as PR #3)."""
    mars = mass_ratio(a.mars_dv_from_leo, a.ship_isp_vac_s) - 1
    moon = mass_ratio(a.lunar_dv_from_leo, a.ship_isp_vac_s) - 1
    prop = v.mars_prop_in_leo_t * moon / mars
    return math.ceil(max(prop - a.ship_reserve_t, 0) / v.payload_leo_t)


def isru_power_kw(a: LogisticsAssumptions, ships: float = 1.0) -> float:
    """Average electric power to refill `ships` return ships in the time available."""
    hours = a.isru_months * 730.5 * a.isru_duty
    return ships * a.isru_return_prop_t * 1e3 * a.isru_kwh_per_kg / hours


@dataclass
class YearLog:
    year: int
    mars_ships: int = 0
    lunar_landings: int = 0
    tanker_launches: int = 0
    commercial_leo: int = 0
    crew_flights: int = 0
    launches: int = 0
    propellant_kt: float = 0.0
    methane_kt: float = 0.0
    oxygen_kt: float = 0.0
    ships_built: int = 0
    boosters_built: int = 0
    engines_built: int = 0
    peak_launches_per_month: float = 0.0
    pads_needed: int = 0
    boiloff_t: float = 0.0
    mars_isru_kw: float = 0.0
    notes: list = field(default_factory=list)


def _mars_windows_in(start: float, finish: float) -> list[float]:
    first, period, _ = WINDOWS["mars"]
    k = max(0, math.ceil((start - first) / period - 1e-9))
    out = []
    while first + k * period <= finish + 1e-9:
        out.append(first + k * period)
        k += 1
    return out


def campaign(prog: Program, timing: dict[str, Timing], v: VehicleCase = VEHICLE_CAMPAIGN,
             a: LogisticsAssumptions | None = None, end_year: int = 2060) -> list[YearLog]:
    a = a or LogisticsAssumptions()
    years: dict[int, YearLog] = {}

    def row(y: int) -> YearLog:
        if y not in years:
            years[y] = YearLog(y)
        return years[y]

    lunar_tk = lunar_tankers(v, a)
    first_mars = timing["MARS-CARGO-1"].start
    first_orbit = timing["ORBITAL-1"].finish

    # Mars: ships per window from each program step that spans the window, plus commercial cargo
    window_ships: dict[float, int] = defaultdict(int)
    window_crew: dict[float, int] = defaultdict(int)
    for sid, n in MARS_SHIPS_PER_WINDOW.items():
        t = timing[sid]
        s = prog.steps[sid]
        ws = [t.start] if s.window else _mars_windows_in(t.start, t.finish)
        for w in ws:
            window_ships[round(w, 3)] += n
            window_crew[round(w, 3)] += CREW_SHIPS.get(sid, 0)
    first, period, _ = WINDOWS["mars"]
    k = 0
    while True:
        w = first + k * period
        if to_year(w) > end_year:
            break
        if w > first_mars + 1e-6:
            idx = int(round((w - first_mars) / period))
            window_ships[round(w, 3)] += COMMERCIAL_MARS_RAMP[min(idx, len(COMMERCIAL_MARS_RAMP) - 1)]
        k += 1

    lunar_o2 = timing["LUNAR-TANKER"].finish if "LUNAR-TANKER" in timing else float("inf")
    for w, ships in window_ships.items():
        if ships == 0:
            continue
        y = int(to_year(w))
        r = row(y)
        per_ship = v.mars_tankers * (MARS_TANKER_FACTOR_LUNAR_O2 if w >= lunar_o2 else 1.0)
        tankers = math.ceil(ships * per_ship)
        r.mars_ships += ships
        r.crew_flights += window_crew.get(w, 0)
        r.tanker_launches += tankers
        r.ships_built += ships  # Mars ships stay on Mars until ISRU returns them; treat as new builds
        rate = (ships + tankers) / a.surge_months
        r.peak_launches_per_month = max(r.peak_launches_per_month, rate)
        # Average tanker load sits in the depot half the surge.
        r.boiloff_t += tankers * v.payload_leo_t * a.boiloff_per_day * a.surge_months * 30.4 / 2
        returning = window_crew.get(w, 0)
        if returning:
            r.mars_isru_kw = max(r.mars_isru_kw, isru_power_kw(a, returning))

    # Moon: landings per year while lunar steps run (PR #9 phase cargo counts), then 6 per year after the spaceport
    for sid, n in LUNAR_LANDINGS_PER_YEAR.items():
        t = timing[sid]
        y0, y1 = int(to_year(t.start)), int(to_year(t.finish))
        for y in range(y0, y1 + 1):
            row(y).lunar_landings += n
    spaceport_done = to_year(timing["LUNAR-SPACEPORT"].finish)
    for y in range(int(spaceport_done) + 1, end_year + 1):
        row(y).lunar_landings += 6
    for y, r in years.items():
        # Lunar oxygen cuts the Earth tankers per landing once the spaceport runs (PR #9).
        tk = lunar_tk if y <= spaceport_done else math.ceil(lunar_tk * LUNAR_TRIP_FACTOR)
        r.tanker_launches += r.lunar_landings * tk
        r.ships_built += r.lunar_landings  # one-way landers until lunar refuelling is routine
    row(int(to_year(timing["LUNAR-CREW-1"].start))).crew_flights += 1

    # Commercial LEO launches (PR #3 ramp) after the first orbital flight
    y_orbit = int(to_year(first_orbit))
    for y in range(y_orbit, end_year + 1):
        k = y - y_orbit
        row(y).commercial_leo += LEO_COMMERCIAL_RAMP[min(k, len(LEO_COMMERCIAL_RAMP) - 1)]

    per_launch = a.booster_prop_t + a.ship_prop_t
    ch4_frac = 1 / (1 + a.mixture_ratio)
    out = []
    for y in sorted(years):
        if y > end_year:
            continue
        r = years[y]
        r.launches = r.mars_ships + r.lunar_landings + r.tanker_launches + r.commercial_leo
        r.propellant_kt = r.launches * per_launch / 1e3
        r.methane_kt = r.propellant_kt * ch4_frac
        r.oxygen_kt = r.propellant_kt - r.methane_kt
        r.boosters_built = math.ceil(r.launches / a.booster_life)
        r.ships_built += math.ceil((r.tanker_launches + r.commercial_leo) / a.tanker_life)
        r.engines_built = r.boosters_built * a.engines_booster + r.ships_built * a.engines_ship
        steady = r.launches / 12
        r.peak_launches_per_month = max(r.peak_launches_per_month + (r.launches - r.mars_ships - r.mars_ships * v.mars_tankers) / 12, steady)
        r.pads_needed = max(1, math.ceil(r.peak_launches_per_month / a.pad_launches_per_month))
        out.append(r)
    return out
