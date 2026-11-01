"""Engine, vehicle, per-flight and per-mission costs built up from the BOM."""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path

from . import inputs as I

BOM_CSV = Path(__file__).resolve().parents[3] / "results" / "components" / "bom.csv"


def wright(t1: float, unit: int, slope: float) -> float:
    """Cost of the n-th unit on a Wright learning curve."""
    return t1 * unit ** math.log2(slope)


@dataclass
class PartCost:
    part: str
    name: str
    assembly: str
    mass_kg: float
    material_usd: float
    labour_usd: float
    purchased_usd: float

    @property
    def total(self) -> float:
        return self.material_usd + self.labour_usd + self.purchased_usd


def _fab_rate(part: str) -> float:
    prefix = part.split("-")[0]
    if part in I.TP_ROTATING:
        return I.FAB_HOURS_PER_KG["TP-rot"]
    if prefix in ("TP",):
        return I.FAB_HOURS_PER_KG["TP-hsg"]
    return I.FAB_HOURS_PER_KG.get(prefix, 3.0)


def load_bom(path: Path = BOM_CSV) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def engine_part_costs(bom: list[dict] | None = None) -> list[PartCost]:
    """First-unit (T1) cost of every BOM line."""
    out = []
    for row in bom or load_bom():
        part, mass, qty = row["part_number"], float(row["mass_kg"]), int(row["quantity"])
        prefix = part.split("-")[0]
        mat = lab = buy = 0.0
        if part in I.PURCHASED_EACH_USD:
            buy = I.PURCHASED_EACH_USD[part] * qty
        elif part in I.PURCHASED_USD_PER_KG:
            buy = I.PURCHASED_USD_PER_KG[part] * mass
        elif prefix in I.PURCHASED_USD_PER_KG:
            buy = I.PURCHASED_USD_PER_KG[prefix] * mass
        else:
            price = I.MATERIAL_USD_PER_KG.get(row["material"], I.MATERIAL_USD_PER_KG["various"])
            mat = mass * I.BUY_TO_FLY.get(row["basis"], 1.5) * price
            lab = mass * _fab_rate(part) * I.LABOUR_USD_PER_HOUR
        out.append(PartCost(part, row["name"], row["assembly"], mass, mat, lab, buy))
    return out


@dataclass
class EngineCost:
    parts: list[PartCost]
    t1_material: float
    t1_labour: float
    t1_purchased: float
    t1_test: float

    @property
    def t1(self) -> float:
        return self.t1_material + self.t1_labour + self.t1_purchased + self.t1_test

    def unit(self, n: int) -> float:
        return (wright(self.t1_labour + self.t1_test, n, I.LEARNING_LABOUR)
                + wright(self.t1_material + self.t1_purchased, n, I.LEARNING_MATERIAL))

    def by_assembly(self) -> dict[str, float]:
        acc: dict[str, float] = {}
        for p in self.parts:
            acc[p.assembly] = acc.get(p.assembly, 0.0) + p.total
        return acc


def engine_cost(bom: list[dict] | None = None) -> EngineCost:
    parts = engine_part_costs(bom)
    return EngineCost(parts, sum(p.material_usd for p in parts), sum(p.labour_usd for p in parts),
                      sum(p.purchased_usd for p in parts), I.ASSEMBLY_TEST_T1_USD)


@dataclass
class VehicleCost:
    engine: EngineCost
    vehicle_unit: int = I.FLEET_UNIT_INDEX
    engine_unit: int = I.ENGINE_UNIT_INDEX
    m: dict = field(default_factory=lambda: dict(I.MODEL))

    def engine_price(self) -> float:
        return self.engine.unit(self.engine_unit)

    def booster(self) -> float:
        m = self.m
        struct_kg = m["booster_dry_t"] * 1e3 - m["booster_engines"] * m["engine_mass_kg"]
        airframe = wright(struct_kg * I.STRUCTURE_USD_PER_KG_T1 + I.BOOSTER_OTHER_T1_USD,
                          self.vehicle_unit, I.LEARNING_VEHICLE)
        return airframe + m["booster_engines"] * self.engine_price()

    def ship(self) -> float:
        m = self.m
        n_eng = m["ship_engines_sl"] + m["ship_engines_vac"]
        struct_kg = m["ship_dry_t"] * 1e3 - n_eng * m["engine_mass_kg"]
        airframe = wright(struct_kg * I.STRUCTURE_USD_PER_KG_T1 + I.SHIP_TILES * I.TILE_USD_T1
                          + I.SHIP_OTHER_T1_USD, self.vehicle_unit, I.LEARNING_VEHICLE)
        eng = (m["ship_engines_sl"] + m["ship_engines_vac"] * I.VAC_ENGINE_FACTOR) * self.engine_price()
        return airframe + eng

    def propellant(self) -> float:
        total_kg = (self.m["booster_propellant_t"] + self.m["ship_propellant_t"]) * 1e3
        mr = self.m["mixture_ratio"]
        ch4 = total_kg / (1 + mr)
        return ch4 * I.CH4_USD_PER_KG + (total_kg - ch4) * I.LOX_USD_PER_KG

    def flight_breakdown(self, ship_expended: bool = False) -> dict[str, float]:
        b, s = self.booster(), self.ship()
        return {
            "booster amortisation": b / I.BOOSTER_LIFE_FLIGHTS,
            "booster refurbishment": b * I.BOOSTER_REFURB_FRACTION,
            "ship amortisation": s if ship_expended else s / I.SHIP_LIFE_FLIGHTS,
            "ship refurbishment": 0.0 if ship_expended else s * I.SHIP_REFURB_FRACTION,
            "propellant": self.propellant(),
            "launch operations": I.LAUNCH_OPS_USD,
        }

    def flight_cost(self, ship_expended: bool = False) -> float:
        return sum(self.flight_breakdown(ship_expended).values())


def mass_ratio(dv: float, isp: float) -> float:
    return math.exp(dv / (isp * 9.80665))


def lunar_tankers(m: dict | None = None, payload_t: float | None = None) -> tuple[float, int]:
    """Propellant in LEO and tanker count for a one-way lunar cargo landing, scaled
    from the repository's Mars result by the rocket equation (estimate)."""
    m = m or I.MODEL
    isp = m["ship_isp_vac_s"]
    mars = mass_ratio(m["mars_dv_from_leo_ms"], isp) - 1
    moon = mass_ratio(I.LUNAR_DV_FROM_LEO_MS, isp) - 1
    prop = m["mars_prop_in_leo_t"] * moon / mars
    # Campaign delivery per tanker when known (the Mars ship's own residual is not tanker propellant).
    per_tanker = m.get("tanker_delivery_t") or m["mars_prop_in_leo_t"] / m["mars_tankers"]
    return prop, math.ceil(prop / per_tanker)


def mars_ship_changes_usd(vc: "VehicleCost") -> float:
    """Extra build cost of a Mars ship over a tanker: one more sea-level engine and the ablator (estimate)."""
    return vc.engine_price() + wright(I.ABLATOR_USD_T1, vc.vehicle_unit, I.LEARNING_VEHICLE)


@dataclass
class Mission:
    name: str
    flights: int
    ships_expended: int
    payload_t: float
    cost: float
    detail: dict

    @property
    def usd_per_kg(self) -> float:
        return self.cost / (self.payload_t * 1e3)


def missions(vc: VehicleCost, payload_leo_t: float) -> list[Mission]:
    reuse = vc.flight_cost()
    expend = vc.flight_cost(ship_expended=True)
    m = vc.m
    out = [Mission("LEO launch, reusable", 1, 0, payload_leo_t, reuse, {"flight": reuse})]
    nt = m["mars_tankers"]
    mars_ship_extra = mars_ship_changes_usd(vc)
    mars_cost = nt * reuse + expend + mars_ship_extra + I.MISSION_OPS_MARS_USD
    out.append(Mission("Mars cargo, 100 t landed", nt + 1, 1, m["mars_payload_t"], mars_cost,
                       {"tanker flights": nt * reuse, "cargo ship (stays on Mars)": expend,
                        "Mars ship changes (4th engine, ablator)": mars_ship_extra,
                        "mission operations": I.MISSION_OPS_MARS_USD}))
    prop, lt = lunar_tankers(m)
    moon_cost = lt * reuse + expend + I.MISSION_OPS_MOON_USD
    out.append(Mission("Lunar cargo, 100 t landed", lt + 1, 1, 100.0, moon_cost,
                       {"tanker flights": lt * reuse, "cargo ship (stays on Moon)": expend,
                        "mission operations": I.MISSION_OPS_MOON_USD, "propellant in LEO t": prop}))
    return out
