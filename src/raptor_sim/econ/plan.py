"""Fifteen-year business plan: revenue, cost, cash flow, scenarios, sensitivity and financing.

All schedule and price numbers here are estimates (see inputs.py for the cited anchors).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from . import inputs as I
from .costs import VehicleCost, engine_cost, lunar_tankers

YEARS = list(range(2027, 2042))
MARS_WINDOWS = {2028, 2031, 2033, 2035, 2037, 2039, 2041}  # about every 26 months


@dataclass
class Scenario:
    name: str
    # Schedule from the master roadmap (PR #8) P50: first orbital flight 2032.6, first Mars cargo
    # landing 2038.3, i.e. launched in the 2037 window. Fractional years: the first year of operation
    # counts only the months after first flight.
    first_orbital_year: float = 2032.6
    first_mars_window: int = 2037
    dev_cost_factor: float = 1.0
    price_factor: float = 1.0
    flight_rate_factor: float = 1.0
    reuse_factor: float = 1.0
    mars_price_factor: float = 1.0
    mars_demand_factor: float = 1.0
    engine_cost_factor: float = 1.0
    payload_leo_t: float = 100.0
    discount_rate: float = 0.12
    terminal_growth: float = 0.03
    tax_rate: float = 0.21

    # Non-recurring development, $M by year (estimate): engine, vehicle, pads and factory, lunar/Mars variants
    # Pre-flight years (2027-2032) sum to $7,344M, the roadmap's P50 cost to first orbital flight
    # (PR #8); the shape is the original 2031 plan stretched by one more year of engine and ship work.
    dev_musd: dict = field(default_factory=lambda: {
        2027: 300, 2028: 800, 2029: 1200, 2030: 1600, 2031: 1744, 2032: 1700,
        2033: 800, 2034: 600, 2035: 500, 2036: 400, 2037: 350, 2038: 300,
        2039: 300, 2040: 300, 2041: 300})
    # Government development and propulsion contracts, $M (estimate; HLS-class awards are cited as scale)
    gov_dev_musd: dict = field(default_factory=lambda: {
        2027: 20, 2028: 60, 2029: 120, 2030: 200, 2031: 300, 2032: 400, 2033: 400,
        2034: 300, 2035: 200, 2036: 150, 2037: 150, 2038: 150, 2039: 150, 2040: 150, 2041: 150})
    # Base external LEO launches per year after first orbital flight, by year of operation
    leo_ramp: tuple = (2, 5, 9, 14, 19, 24, 29, 34, 38, 42, 45)
    lunar_ramp: tuple = (0, 0, 0, 1, 2, 3, 3, 4, 4, 4, 4)       # missions per year of operation
    mars_per_window: tuple = (0, 1, 2, 3, 4, 5, 6)             # missions per window after first orbit
    science_ramp: tuple = (0, 0, 0, 1, 1, 1, 2, 2, 2, 2, 2)
    station_musd_ramp: tuple = (0, 0, 50, 100, 150, 200, 250, 300, 350, 400, 450)


BASE = Scenario("Base")
BEAR = replace(BASE, name="Bear", first_orbital_year=2034.9, first_mars_window=2039, dev_cost_factor=1.5, price_factor=0.8,
               flight_rate_factor=0.6, reuse_factor=0.5, mars_price_factor=0.7, mars_demand_factor=0.5)
BULL = replace(BASE, name="Bull", first_orbital_year=2031.4, first_mars_window=2035, dev_cost_factor=0.85, price_factor=1.1,
               flight_rate_factor=1.3, reuse_factor=1.0, mars_price_factor=1.2, mars_demand_factor=1.5)
SCENARIOS = [BEAR, BASE, BULL]


def _ramp(seq: tuple, k: int) -> float:
    if k < 0:
        return 0.0
    return float(seq[min(k, len(seq) - 1)])


def leo_price_musd(k: int, s: Scenario) -> float:
    """Dedicated 100 t launch price: starts under Falcon 9 list ($74M, cited), falls to $35M."""
    return s.price_factor * max(35.0, 65.0 - 5.0 * k)


def lunar_price_musd(k: int, s: Scenario) -> float:
    return s.price_factor * max(250.0, 500.0 - 40.0 * k)


def mars_price_musd(k: int, s: Scenario) -> float:
    """Price per 100 t Mars cargo landing: $10,000/kg falling to $5,000/kg (estimate)."""
    return s.mars_price_factor * max(500.0, 1000.0 - 75.0 * k)


ANOMALY_RESERVE = 0.15  # share of flight cost held for failures and stand-downs (estimate)
SCIENCE_PRICE_MUSD = 300.0  # dedicated refuelled-ship science mission; MSR cost ($8-11B, cited) sets the ceiling


def flight_cost_musd(k: int, cum_flights: float, s: Scenario, expended: bool = False) -> float:
    eng = engine_cost()
    eng.t1_labour *= s.engine_cost_factor
    eng.t1_material *= s.engine_cost_factor
    eng.t1_purchased *= s.engine_cost_factor
    vehicle_unit = max(1, int(3 + cum_flights / 6))
    vc = VehicleCost(eng, vehicle_unit=vehicle_unit, engine_unit=vehicle_unit * 39)
    b_life = max(3.0, min(I.BOOSTER_LIFE_FLIGHTS, 5 + 6 * k) * s.reuse_factor)
    s_life = max(2.0, min(I.SHIP_LIFE_FLIGHTS, 3 + 2 * k) * s.reuse_factor)
    b, sh = vc.booster(), vc.ship()
    cost = (b / b_life + b * I.BOOSTER_REFURB_FRACTION + vc.propellant() + I.LAUNCH_OPS_USD
            + (sh if expended else sh / s_life + sh * I.SHIP_REFURB_FRACTION))
    return cost / 1e6


def _mars_ship_extra_usd(cum_flights: float, s: Scenario) -> float:
    from .costs import mars_ship_changes_usd

    eng = engine_cost()
    eng.t1_labour *= s.engine_cost_factor
    eng.t1_material *= s.engine_cost_factor
    eng.t1_purchased *= s.engine_cost_factor
    unit = max(1, int(3 + cum_flights / 6))
    return mars_ship_changes_usd(VehicleCost(eng, vehicle_unit=unit, engine_unit=unit * 39))


@dataclass
class YearRow:
    year: int
    flights: float = 0.0
    revenue: dict = field(default_factory=dict)
    cost: dict = field(default_factory=dict)
    tax: float = 0.0

    @property
    def revenue_total(self) -> float:
        return sum(self.revenue.values())

    @property
    def cost_total(self) -> float:
        return sum(self.cost.values())

    @property
    def ebitda(self) -> float:
        return self.revenue_total - (self.cost_total - self.cost.get("development", 0.0))

    @property
    def fcf(self) -> float:
        return self.revenue_total - self.cost_total - self.tax


def project(s: Scenario = BASE) -> list[YearRow]:
    rows: list[YearRow] = []
    cum_flights = 0.0
    nol = 0.0
    _, lunar_tk = lunar_tankers()
    mars_tk = I.MODEL["mars_tankers"]
    window_index = 0
    for y in YEARS:
        r = YearRow(y)
        t_op = y + 1 - s.first_orbital_year  # years of operation by the end of year y
        k = math.ceil(t_op) - 1 if t_op > 0 else -1
        frac = min(t_op, 1.0) if t_op > 0 else 0.0  # part of the first year after first flight
        leo = _ramp(s.leo_ramp, k) * s.flight_rate_factor * frac
        lunar = round(_ramp(s.lunar_ramp, k) * s.flight_rate_factor)
        mars = 0
        if y in MARS_WINDOWS and k >= 0 and y >= s.first_mars_window:
            mars = round(_ramp(s.mars_per_window, window_index) * s.mars_demand_factor)
            window_index += 1
        sci = round(_ramp(s.science_ramp, k))
        reusable_flights = leo + lunar * lunar_tk + mars * mars_tk + sci * 3
        expended = lunar + mars
        r.flights = reusable_flights + expended + sci
        cf = flight_cost_musd(k, cum_flights, s) if k >= 0 else 0.0
        mars_extra = _mars_ship_extra_usd(cum_flights, s) if mars else 0.0
        cfx = flight_cost_musd(k, cum_flights, s, expended=True) if k >= 0 else 0.0
        cum_flights += r.flights

        r.revenue = {
            "Government development contracts": s.gov_dev_musd.get(y, 0.0),
            "LEO launch": leo * leo_price_musd(k, s),
            "Lunar cargo": lunar * lunar_price_musd(k, s),
            "Mars cargo": mars * mars_price_musd(window_index - 1, s) if mars else 0.0,
            "Science missions": sci * SCIENCE_PRICE_MUSD * s.price_factor,
            "LEO station logistics": _ramp(s.station_musd_ramp, k) * s.price_factor * frac,
        }
        r.cost = {
            "development": s.dev_musd.get(y, 0.0) * s.dev_cost_factor,
            "flight operations": (reusable_flights + sci) * cf,
            "expended ships": expended * cfx + mars * mars_extra / 1e6,
            "anomaly reserve": ANOMALY_RESERVE * ((reusable_flights + sci) * cf + expended * cfx),
            "mission operations": (mars * I.MISSION_OPS_MARS_USD + lunar * I.MISSION_OPS_MOON_USD) / 1e6,
            "station logistics delivery": 0.6 * r.revenue["LEO station logistics"],
            "SG&A": 40.0 + 15.0 * min(y - 2027, 10) + 0.04 * sum(r.revenue.values()),
        }
        pre_tax = r.revenue_total - r.cost_total
        if pre_tax < 0:
            nol += -pre_tax
        else:
            used = min(nol, pre_tax)
            nol -= used
            r.tax = (pre_tax - used) * s.tax_rate
        rows.append(r)
    return rows


def npv(cash: list[float], rate: float) -> float:
    return sum(c / (1 + rate) ** i for i, c in enumerate(cash))


def irr(cash: list[float]) -> float | None:
    lo, hi = -0.99, 5.0
    f = lambda r: npv(cash, r)
    if f(lo) * f(hi) > 0:
        return None
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if f(lo) * f(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


@dataclass
class Valuation:
    scenario: str
    rows: list[YearRow]
    npv_musd: float
    terminal_musd: float
    irr: float | None
    trough_musd: float
    trough_year: int
    breakeven_year: int | None
    payback_year: int | None
    revenue_2041: float
    fcf_2041: float


def value(s: Scenario = BASE) -> Valuation:
    rows = project(s)
    cash = [r.fcf for r in rows]
    last = cash[-1]
    terminal = last * (1 + s.terminal_growth) / (s.discount_rate - s.terminal_growth) if last > 0 else 0.0
    with_tv = cash[:-1] + [last + terminal]
    cum, trough, ty, payback = 0.0, 0.0, YEARS[0], None
    for y, c in zip(YEARS, cash):
        cum += c
        if cum < trough:
            trough, ty = cum, y
        if payback is None and cum >= 0 and y > ty:
            payback = y
    be = next((r.year for r in rows if r.fcf > 0 and r.year > 2030), None)
    return Valuation(s.name, rows, npv(with_tv, s.discount_rate), terminal, irr(with_tv), trough, ty, be,
                     payback, rows[-1].revenue_total, last)


TORNADO = [
    ("Schedule at roadmap P90 / P10", {"first_orbital_year": 2034.9, "first_mars_window": 2039},
     {"first_orbital_year": 2031.4, "first_mars_window": 2035}),
    ("Development cost +/-30%", {"dev_cost_factor": 1.3}, {"dev_cost_factor": 0.7}),
    ("Launch and mission prices +/-20%", {"price_factor": 0.8}, {"price_factor": 1.2}),
    ("Flight rate +/-30%", {"flight_rate_factor": 0.7}, {"flight_rate_factor": 1.3}),
    ("Reuse life half / as planned", {"reuse_factor": 0.5}, {"reuse_factor": 1.0}),
    ("Mars price +/-30%", {"mars_price_factor": 0.7}, {"mars_price_factor": 1.3}),
    ("Mars demand half / 1.5x", {"mars_demand_factor": 0.5}, {"mars_demand_factor": 1.5}),
    ("Engine unit cost +/-40%", {"engine_cost_factor": 1.4}, {"engine_cost_factor": 0.6}),
    ("Discount rate 15% / 10%", {"discount_rate": 0.15}, {"discount_rate": 0.10}),
]


def tornado(base: Scenario = BASE) -> list[tuple[str, float, float, float]]:
    b = value(base).npv_musd
    out = []
    for label, low, high in TORNADO:
        lo = value(replace(base, **low)).npv_musd
        hi = value(replace(base, **high)).npv_musd
        out.append((label, lo - b, hi - b, b))
    out.sort(key=lambda t: -abs(t[2] - t[1]))
    return out


@dataclass
class Round:
    name: str
    year: int
    raise_musd: float
    pre_money_musd: float
    milestone: str

    @property
    def post(self) -> float:
        return self.pre_money_musd + self.raise_musd


ROUNDS = [  # estimate; sized so base-case cash stays positive with a buffer of at least $100M
    Round("Seed", 2026, 30, 90, "Team, preburner and injector test articles, data package from this repo"),
    Round("Series A", 2027, 400, 600, "Full-scale preburner and turbopump hot fire"),
    Round("Series B", 2028, 900, 1_800, "Full engine hot fire at rated chamber pressure"),
    Round("Series C", 2029, 1_800, 4_000, "Engine qualification; booster structural test article"),
    Round("Series D", 2030, 2_500, 7_500, "Integrated stack on pad; anchor government contract signed"),
    # Re-sized 2026-11-01 for the roadmap schedule (first orbit 2032.6) and the campaign tanker count.
    Round("Series E / strategic", 2032, 2_000, 12_000, "First orbital flight (roadmap P50 2032.6) and booster catch attempts"),
]
CONTINGENT_DEBT_MUSD = 3_000  # asset-backed fleet debt held in reserve for the bear case (estimate)


def cap_table(rounds: list[Round] = ROUNDS, founders: float = 1.0, pool: float = 0.10):
    """Ownership after each equity round, with a 10% option pool set at seed."""
    holders = {"Founders": founders * (1 - pool), "Option pool": pool}
    table = []
    for rd in rounds:
        if rd.pre_money_musd <= 0:
            table.append((rd, dict(holders)))
            continue
        new = rd.raise_musd / rd.post
        holders = {k: v * (1 - new) for k, v in holders.items()}
        holders[rd.name] = new
        table.append((rd, dict(holders)))
    return table


def cash_balance(s: Scenario = BASE, rounds: list[Round] = ROUNDS) -> list[tuple[int, float]]:
    """End-of-year cash with the financing plan, $M."""
    inflow: dict[int, float] = {}
    for rd in rounds:
        inflow[rd.year] = inflow.get(rd.year, 0.0) + rd.raise_musd
    bal = inflow.get(2026, 0.0)
    out = []
    for r in project(s):
        bal += inflow.get(r.year, 0.0) + r.fcf
        out.append((r.year, bal))
    return out
