"""Life support (ECLSS) mass balance and consumables sizing.

Per crew-member-day values follow NASA's Life Support Baseline Values and
Assumptions Document (BVAD), NASA/TP-2015-218570/REV2 (Anderson et al. 2018),
nominal values rounded (CITED, rounded):
  O2 consumed 0.82 kg, CO2 produced 1.04 kg, metabolic water produced 0.35 kg,
  drinking + food-preparation water 2.5 kg, food solids ~0.65 kg (as-packaged
  food ~1.8 kg/d incl. water and packaging), urine 1.5 kg, respiration and
  perspiration water ~2.3 kg.
The values are adjusted slightly (ESTIMATE) so the per-day balance closes
exactly in mass: food solids follow from O2 + solids -> CO2 + metabolic water.

ISS loop performance (CITED): water recovery 98% after the Brine Processor
Assembly (NASA, June 2023). Sabatier CO2 reduction recovers roughly half of
the oxygen in CO2 because hydrogen from electrolysis limits it and methane is
vented (CITED order of magnitude: ISS Sabatier ~50% O2 loop closure).

Hardware and spares masses are ESTIMATES (system-level, for 4 crew), from the
order of magnitude of ISS ECLSS racks and published Mars architecture studies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# Per crew-member-day (kg)
O2_USE = 0.82
CO2_OUT = 1.04
METABOLIC_WATER = 0.35
DRINK_FOOD_WATER = 2.50
FOOD_WATER_CONTENT = 0.95  # water already in the food as eaten (ESTIMATE within BVAD range)
UNDIGESTED_SOLIDS = 0.03  # fecal solids
URINE_SOLIDS = 0.06
FOOD_PACKAGING = 0.20  # ESTIMATE
HYGIENE_WATER = 0.40  # ESTIMATE (ISS-like low-water hygiene, no laundry)
FLUSH_WATER = 0.50  # ESTIMATE
URINE_WATER = 1.50
FECAL_WATER = 0.09


def food_solids() -> float:
    """Food solids implied by the metabolic mass balance (kg/CM-d)."""
    metabolised = CO2_OUT + METABOLIC_WATER - O2_USE
    return metabolised + UNDIGESTED_SOLIDS + URINE_SOLIDS


def vapor_out() -> float:
    """Respiration + perspiration water implied by the water balance (kg/CM-d)."""
    water_in = DRINK_FOOD_WATER + FOOD_WATER_CONTENT + METABOLIC_WATER
    return water_in - URINE_WATER - FECAL_WATER


@dataclass(frozen=True)
class CrewDay:
    inputs: dict
    outputs: dict

    @property
    def imbalance(self) -> float:
        return sum(self.inputs.values()) - sum(self.outputs.values())


def crew_day_balance() -> CrewDay:
    """Human metabolic mass balance per crew-member-day; closes by construction."""
    inputs = {"O2": O2_USE, "drink+prep water": DRINK_FOOD_WATER, "food water": FOOD_WATER_CONTENT,
              "food solids": food_solids()}
    outputs = {"CO2": CO2_OUT, "urine water": URINE_WATER, "urine solids": URINE_SOLIDS,
               "fecal water": FECAL_WATER, "fecal solids": UNDIGESTED_SOLIDS, "vapor": vapor_out()}
    return CrewDay(inputs, outputs)


@dataclass(frozen=True)
class Loop:
    name: str
    water_recovery: float  # fraction of urine + condensate + hygiene + flush water recovered
    o2_from_co2: float  # fraction of the O2 in exhaled CO2 recovered
    food_grown: float  # fraction of food mass produced on board
    hardware_kg: float  # fixed hardware for 4 crew (ESTIMATE)
    spares_kg_per_day: float  # whole system, 4 crew (ESTIMATE)
    power_kw: float  # ESTIMATE


LOOPS = {
    "open": Loop("Open loop (stored O2, water, food)", 0.0, 0.0, 0.0, 600.0, 0.0, 0.5),
    "iss": Loop("ISS-class physico-chemical (98% water, Sabatier)", 0.98, 0.50, 0.0, 5_000.0, 1.5, 4.0),
    "advanced": Loop("Advanced (98% water, Bosch/pyrolysis ~90% O2, 10% food grown)", 0.98, 0.90, 0.10,
                     7_500.0, 1.0, 8.0),
    "bioregenerative": Loop("Bioregenerative (plants, ~50% food)", 0.99, 0.95, 0.50, 20_000.0, 1.5, 60.0),
}


@dataclass(frozen=True)
class Consumables:
    loop: str
    crew: int
    days: float
    o2_kg: float
    water_kg: float
    food_kg: float  # as packaged (solids + water content + packaging)
    spares_kg: float
    hardware_kg: float
    reserve_kg: float
    total_kg: float


def consumables(crew: int, days: float, loop: str = "iss", reserve_fraction: float = 0.10) -> Consumables:
    """Launch mass of consumables + ECLSS hardware for a mission (kg)."""
    L = LOOPS[loop]
    cd = crew * days
    # water used per crew-day by the habitat (drink+prep, hygiene, flush). Food water comes in the food.
    water_use = DRINK_FOOD_WATER + HYGIENE_WATER + FLUSH_WATER
    # water streams available to recover: urine water, vapor (condensate), hygiene and flush
    recoverable = URINE_WATER + vapor_out() + HYGIENE_WATER + FLUSH_WATER
    # O2 production by electrolysis consumes water: 1 kg O2 needs 1.125 kg H2O.
    o2_from_co2 = L.o2_from_co2 * CO2_OUT * 32 / 44
    o2_need = max(O2_USE - o2_from_co2, 0.0)
    if L.water_recovery > 0:
        # O2 made by electrolysis of recovered water
        water_net = water_use + 1.125 * o2_need - L.water_recovery * recoverable
        o2_stored = 0.0
    else:
        water_net = water_use
        o2_stored = O2_USE
    water_net = max(water_net, 0.0)
    food = (food_solids() + FOOD_WATER_CONTENT + FOOD_PACKAGING) * (1 - L.food_grown)
    o2 = o2_stored * cd
    water = water_net * cd
    food_kg = food * cd
    spares = L.spares_kg_per_day * days * crew / 4
    hardware = L.hardware_kg * (0.5 + 0.5 * crew / 4)
    reserve = reserve_fraction * (o2 + water + food_kg)
    total = o2 + water + food_kg + spares + hardware + reserve
    return Consumables(loop, crew, days, o2, water, food_kg, spares, hardware, reserve, total)


def break_even_days(crew: int, loop: str, against: str = "open") -> float:
    """Mission length beyond which the closed loop is lighter than the other one."""
    a0, a1 = consumables(crew, 0, loop).total_kg, consumables(crew, 1000, loop).total_kg
    b0, b1 = consumables(crew, 0, against).total_kg, consumables(crew, 1000, against).total_kg
    sa, sb = (a1 - a0) / 1000, (b1 - b0) / 1000
    if sb <= sa:
        return math.inf
    return (a0 - b0) / (sb - sa)


@dataclass
class StockHistory:
    day: list = field(default_factory=list)
    o2: list = field(default_factory=list)
    water: list = field(default_factory=list)
    co2_vented: float = 0.0
    mass_error: float = 0.0  # kg, conservation residual over the run
    ran_out: bool = False


def simulate_stocks(crew: int, days: int, loop: str = "iss", o2_reserve: float = 300.0,
                    water_reserve: float = 1_000.0, failures: tuple[tuple[int, int, str], ...] = ()) -> StockHistory:
    """Day-by-day O2 and water stocks with optional failures.

    failures: (start_day, length_days, "oga"|"wrs"|"sabatier") windows where that
    unit is down. Tracks mass conservation of the O and H2O inventory.
    """
    L = LOOPS[loop]
    hist = StockHistory()
    o2, water = o2_reserve, water_reserve
    total_in = o2 + water
    consumed_into_body_or_vented = 0.0
    recoverable = URINE_WATER + vapor_out() + HYGIENE_WATER + FLUSH_WATER
    water_use = DRINK_FOOD_WATER + HYGIENE_WATER + FLUSH_WATER
    for d in range(days):
        down = {u for s, n, u in failures if s <= d < s + n}
        if "oga" in down:
            down.add("sabatier")  # Sabatier needs electrolysis hydrogen
        # crew draws
        o2 -= O2_USE * crew
        water -= water_use * crew
        consumed_into_body_or_vented += (O2_USE + water_use) * crew
        # returns from the loop
        if L.water_recovery > 0 and "wrs" not in down:
            rec = L.water_recovery * recoverable * crew
            water += rec
            consumed_into_body_or_vented -= rec
        if L.o2_from_co2 > 0 and "sabatier" not in down:
            o2_rec = L.o2_from_co2 * CO2_OUT * 32 / 44 * crew
            o2 += o2_rec
            consumed_into_body_or_vented -= o2_rec
        if L.water_recovery > 0 and "oga" not in down:
            # electrolyse water to restore O2 toward the reserve level
            deficit = max(o2_reserve - o2, 0.0)
            make = min(deficit, max(water, 0.0) / 1.125)
            o2 += make
            water -= 1.125 * make
            consumed_into_body_or_vented += 0.125 * make  # H2 to Sabatier/vent
        hist.day.append(d)
        hist.o2.append(o2)
        hist.water.append(water)
        if o2 < 0 or water < 0:
            hist.ran_out = True
    hist.mass_error = total_in - (o2 + water) - consumed_into_body_or_vented
    return hist


def reserve_for_failure(crew: int, outage_days: int, unit: str = "oga") -> float:
    """O2 (or water) reserve in kg that rides out an outage of the given unit."""
    if unit == "oga":
        return O2_USE * crew * outage_days
    if unit == "wrs":
        return (DRINK_FOOD_WATER + HYGIENE_WATER + FLUSH_WATER) * crew * outage_days
    raise ValueError(unit)
