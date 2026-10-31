"""Closed-loop life support: a per-person mass balance with loop closure and ISRU.

Three loops are tracked per resident per year: oxygen, water and food. For each,
demand is met by (1) recycling, (2) local production (ISRU or crops), and
(3) whatever is left, imported from Earth. The balance is checked by
construction: demand = recycled + local + imported, and every kilogram that
leaves a loop (leak, brine, waste) is counted as a loss.

Stages map to how a settlement matures:
  outpost     - ISS-class physico-chemical loops, all food shipped
  isru        - plus ice mining and CO2 electrolysis (MOXIE-type) for make-up
  bioregen    - plus crops for most of the diet; plants close O2/CO2 too
"""
from __future__ import annotations

from dataclasses import dataclass

from .inputs import v

DAYS = 365.25


@dataclass(frozen=True)
class LoopSettings:
    name: str
    water_recovery: float
    o2_recovery: float
    food_local: float  # share of food mass grown locally
    water_isru: bool  # make-up water from local ice
    o2_isru: bool  # make-up O2 from local CO2 or water electrolysis


STAGES = {
    "outpost": LoopSettings("outpost", v("water_recovery_iss"), v("o2_recovery_sabatier"), 0.0, False, False),
    "isru": LoopSettings("isru", v("water_recovery_iss"), v("o2_recovery_sabatier"), 0.1, True, True),
    "bioregen": LoopSettings("bioregen", v("water_recovery_iss"), v("o2_recovery_bosch"), 0.9, True, True),
}


@dataclass(frozen=True)
class LoopBalance:
    loop: str
    demand_kg: float
    recycled_kg: float
    local_kg: float
    imported_kg: float
    lost_kg: float

    @property
    def closes(self) -> bool:
        return abs(self.demand_kg - (self.recycled_kg + self.local_kg + self.imported_kg)) < 1e-6


def person_year(stage: LoopSettings) -> list[LoopBalance]:
    """Mass balance for one resident over one Earth year (kg)."""
    out = []

    # Oxygen: metabolic need plus leak make-up. Recovery acts on exhaled CO2.
    o2_demand = (v("o2_per_person") + v("leak_per_person") * 0.23) * DAYS  # air is 23% O2 by mass
    o2_rec = v("o2_per_person") * DAYS * stage.o2_recovery
    if stage.food_local > 0:  # crops fix CO2 in proportion to food grown, Wheeler-scale area
        o2_rec = max(o2_rec, v("o2_per_person") * DAYS * min(1.0, stage.food_local * 1.05))
    o2_rec = min(o2_rec, o2_demand)
    o2_make = o2_demand - o2_rec
    o2_local = o2_make if stage.o2_isru else 0.0
    out.append(LoopBalance("oxygen", o2_demand, o2_rec, o2_local, o2_make - o2_local, o2_make))

    # Water: drinking + hygiene; recovery acts on all of it.
    w_demand = (v("drink_water") + v("hygiene_water")) * DAYS
    w_rec = w_demand * stage.water_recovery
    w_make = w_demand - w_rec
    w_local = w_make if stage.water_isru else 0.0
    out.append(LoopBalance("water", w_demand, w_rec, w_local, w_make - w_local, w_make))

    # Food: no recycling credit in kg terms (nutrients cycle through crops = local).
    f_demand = v("food_packaged") * DAYS
    f_local = f_demand * stage.food_local
    out.append(LoopBalance("food", f_demand, 0.0, f_local, f_demand - f_local, 0.0))
    return out


def import_per_person_year(stage: LoopSettings) -> float:
    """Earth-supplied consumables, kg per resident per year."""
    return sum(b.imported_kg for b in person_year(stage))


def closure(stage: LoopSettings) -> float:
    """Share of total consumable demand met without Earth (recycled or local)."""
    bs = person_year(stage)
    demand = sum(b.demand_kg for b in bs)
    return 1.0 - sum(b.imported_kg for b in bs) / demand


def stage_table() -> list[dict]:
    rows = []
    for key, st in STAGES.items():
        bs = person_year(st)
        rows.append(
            {
                "stage": key,
                "water_recovery": st.water_recovery,
                "o2_recovery": st.o2_recovery,
                "food_local": st.food_local,
                "demand_kg": sum(b.demand_kg for b in bs),
                "import_kg": sum(b.imported_kg for b in bs),
                "closure": closure(st),
                "balances_close": all(b.closes for b in bs),
            }
        )
    return rows
