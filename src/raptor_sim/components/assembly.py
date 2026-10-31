"""Whole-engine build: runs every component model in order and collects masses and the BOM.

Order: performance -> cycle balance -> turbopumps -> chamber contour -> regenerative
cooling -> main injector -> preburners -> lines and valves -> mass roll-up.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from ..cycle import CycleAssumptions, CycleResult, solve_cycle
from ..engine import EngineDesign, EnginePerformance, size_engine
from .chamber import ChamberInputs, Contour
from .cooling import CoolingInputs, CoolingResult, methane_h, solve_cooling
from .feed import FeedInputs, Line, Valve, design_feed
from .injector import InjectorDesign, InjectorInputs, design_injector
from .materials import MATERIALS, allowable
from .preburner import PreburnerDesign, PreburnerInputs, design_preburners
from .turbopump import TurbopumpDesign, TurbopumpInputs, design_turbopumps


@dataclass(frozen=True)
class ComponentInputs:
    """Every design choice below the L1 engine model, in one place."""

    engine: EngineDesign = field(default_factory=EngineDesign)
    cycle: CycleAssumptions = field(default_factory=CycleAssumptions)
    chamber: ChamberInputs = field(default_factory=ChamberInputs)
    cooling: CoolingInputs = field(default_factory=CoolingInputs)
    injector: InjectorInputs = field(default_factory=InjectorInputs)
    turbopump: TurbopumpInputs = field(default_factory=TurbopumpInputs)
    preburner: PreburnerInputs = field(default_factory=PreburnerInputs)
    feed: FeedInputs = field(default_factory=FeedInputs)
    # Items not sized from physics. Estimates, kg.
    gimbal_and_thrust_block: float = 45.0
    controller_and_harness: float = 35.0
    igniters: float = 6.0
    sensors: float = 10.0


@dataclass(frozen=True)
class BomItem:
    part_number: str
    name: str
    assembly: str
    material: str
    quantity: int
    unit_mass: float  # kg
    basis: str  # "sized" (from the models here) or "estimate"
    note: str = ""

    @property
    def mass(self) -> float:
        return self.quantity * self.unit_mass


@dataclass
class EngineBuild:
    inputs: ComponentInputs
    perf: EnginePerformance
    cycle: CycleResult
    contour: Contour | None = None
    cooling: CoolingResult | None = None
    injector: InjectorDesign | None = None
    fuel_tp: TurbopumpDesign | None = None
    ox_tp: TurbopumpDesign | None = None
    fuel_pb: PreburnerDesign | None = None
    ox_pb: PreburnerDesign | None = None
    lines: list[Line] = field(default_factory=list)
    valves: list[Valve] = field(default_factory=list)
    bom: list[BomItem] = field(default_factory=list)
    tca_mass_breakdown: dict[str, float] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.cycle.closed and self.cooling is not None

    @property
    def mass(self) -> float:
        return sum(b.mass for b in self.bom)

    @property
    def thrust_to_weight(self) -> float:
        return self.perf.design.thrust_sl / (self.mass * 9.80665)


def coolant_inlet_temperature(cycle: CycleResult, t_in: float = 111.6) -> float:
    """Methane temperature after the fuel pump: pump losses heat the liquid."""
    import CoolProp.CoolProp as CP

    a = cycle.assumptions
    p_d = cycle.fuel_shaft.pump_discharge_pressure
    h_in = methane_h(a.p_pump_inlet, t_in)
    rho = CP.PropsSI("D", "P", a.p_pump_inlet, "T", t_in, "Methane")
    h_out = h_in + (p_d - a.p_pump_inlet) / (rho * a.eta_pump_fuel)
    return float(CP.PropsSI("T", "P", p_d, "H", h_out, "Methane"))


def _tca_mass(contour: Contour, cooling: CoolingResult, ci: CoolingInputs) -> dict[str, float]:
    liner = {"GRCop-42": 0.0, "IN718": 0.0}
    closeout = 0.0
    st = cooling.stations
    for s0, s1 in zip(st[:-1], st[1:]):
        ds = math.hypot(s1.x - s0.x, s1.r - s0.r)
        r = 0.5 * (s0.r + s1.r)
        t_w = s0.wall_thickness
        rib_frac = s0.rib / (s0.width + s0.rib)
        t_liner = t_w + s0.depth * rib_frac
        liner[s0.material] += MATERIALS[s0.material].density * 2 * math.pi * r * t_liner * ds
        r_out = r + t_w + s0.depth
        closeout += MATERIALS[ci.closeout_material].density * 2 * math.pi * r_out * s0.closeout_thickness * ds
    # Coolant manifolds: tori at the nozzle exit (inlet) and at the injector end (outlet).
    def torus(r_major: float, p: float, t_k: float) -> float:
        d_tube = 0.07
        mat = MATERIALS["IN718"]
        t = max(p * d_tube / 2 / allowable(mat, t_k), 2e-3)
        return mat.density * 2 * math.pi * r_major * math.pi * d_tube * t
    inlet = torus(contour.re + 0.04, cooling.coolant_inlet_pressure, cooling.coolant_inlet_temperature)
    outlet = torus(contour.rc + 0.04, st[0].p_coolant, st[0].t_coolant)
    return {
        "liner_GRCop42": liner["GRCop-42"],
        "nozzle_liner_IN718": liner["IN718"],
        "closeout_jacket": closeout,
        "coolant_inlet_manifold": inlet,
        "coolant_outlet_manifold": outlet,
    }


def build_engine(ci: ComponentInputs | None = None) -> EngineBuild:
    ci = ci or ComponentInputs()
    perf = size_engine(ci.engine)
    cycle = solve_cycle(perf, ci.cycle)
    b = EngineBuild(ci, perf, cycle)
    if not cycle.closed:
        return b
    b.fuel_tp, b.ox_tp = design_turbopumps(cycle, ci.turbopump)
    b.contour = Contour(perf, ci.chamber)
    f1 = cycle.fuel_shaft.turbine_flow / (1 + cycle.fuel_shaft.preburner_mixture_ratio)
    b.cooling = solve_cooling(
        perf, b.contour, ci.cooling,
        coolant_flow=f1,
        coolant_inlet_pressure=cycle.fuel_shaft.pump_discharge_pressure - ci.cycle.dp_liquid_lines * perf.design.pc,
        coolant_inlet_temperature=coolant_inlet_temperature(cycle, ci.turbopump.t_fuel_inlet),
    )
    b.injector = design_injector(perf, cycle, b.contour, ci.injector)
    b.fuel_pb, b.ox_pb = design_preburners(cycle, ci.preburner)
    b.lines, b.valves = design_feed(perf, cycle, b.cooling, b.injector, ci.feed)
    b.tca_mass_breakdown = _tca_mass(b.contour, b.cooling, ci.cooling)
    b.bom = make_bom(b)
    return b


def make_bom(b: EngineBuild) -> list[BomItem]:
    ci = b.inputs
    items: list[BomItem] = []
    tca = b.tca_mass_breakdown
    inj = b.injector
    add = items.append
    # 100 Thrust chamber assembly
    add(BomItem("RC-110", "Combustion chamber and throat liner, milled coolant channels", "100 Thrust chamber",
                "GRCop-42", 1, tca["liner_GRCop42"], "sized",
                f"{b.cooling.stations[0].n_channels} channels at the chamber, hot wall {ci.cooling.hot_wall_thickness * 1e3:.2f} mm"))
    add(BomItem("RC-120", "Nozzle channel-wall liner", "100 Thrust chamber", "IN718", 1, tca["nozzle_liner_IN718"], "sized",
                f"from area ratio {ci.cooling.copper_to_area_ratio:.0f} to {b.perf.design.eps:.1f}"))
    add(BomItem("RC-130", "Structural closeout jacket", "100 Thrust chamber", ci.cooling.closeout_material, 1,
                tca["closeout_jacket"], "sized", "electroformed / brazed closeout over the channels"))
    add(BomItem("RC-140", "Coolant inlet manifold (nozzle exit)", "100 Thrust chamber", "IN718", 1,
                tca["coolant_inlet_manifold"], "sized"))
    add(BomItem("RC-150", "Coolant outlet manifold (chamber)", "100 Thrust chamber", "IN718", 1,
                tca["coolant_outlet_manifold"], "sized"))
    # 200 Main injector
    face_area = math.pi * b.contour.rc**2
    face = MATERIALS[ci.injector.face_material].density * face_area * inj.face_thickness
    posts = (MATERIALS[ci.injector.ox_dome_material].density * math.pi / 4
             * (inj.post_outer_diameter**2 - inj.post_inner_diameter**2) * 0.08)
    dome = MATERIALS[ci.injector.ox_dome_material].density * 2 * math.pi * b.contour.rc**2 * inj.dome_thickness
    fuel_man = MATERIALS[ci.injector.face_material].density * 2 * math.pi * b.contour.rc * 0.08 * inj.dome_thickness * 1.5
    add(BomItem("IN-210", "Injector face plate", "200 Main injector", ci.injector.face_material, 1, face, "sized",
                f"{inj.face_thickness * 1e3:.1f} mm, porous/transpiration cooling not modelled"))
    add(BomItem("IN-220", "Coaxial element ox post", "200 Main injector", ci.injector.ox_dome_material,
                inj.placed_elements, posts, "sized", f"ID {inj.post_inner_diameter * 1e3:.2f} mm, 80 mm long"))
    add(BomItem("IN-230", "Oxygen-rich gas dome", "200 Main injector", ci.injector.ox_dome_material, 1, dome, "sized"))
    add(BomItem("IN-240", "Fuel-rich gas manifold ring and body", "200 Main injector", ci.injector.face_material, 1,
                fuel_man + 0.3 * (face + dome), "estimate", "body scaled from face and dome"))
    # 300/400 turbopumps
    for pn, tp in (("300", b.fuel_tp), ("400", b.ox_tp)):
        asm = f"{pn} {tp.name.capitalize()}"
        mats = {
            "impellers_and_inducer": tp.pump.material,
            "turbine_disc_and_blades": tp.turbine.material,
            "shaft": ci.turbopump.shaft_material_fuel if tp is b.fuel_tp else ci.turbopump.shaft_material_ox,
            "pump_housing": "IN718" if tp is b.fuel_tp else "OXSA",
            "turbine_housing": tp.turbine.material,
            "kick_stage": tp.pump.material,
            "bearings_seals_flanges": "various",
        }
        for k, (part, m) in enumerate(tp.mass_breakdown.items(), start=1):
            basis = "estimate" if part == "bearings_seals_flanges" else "sized"
            add(BomItem(f"TP-{pn[0]}{k:02d}", part.replace("_", " ").capitalize(), asm, mats[part], 1, m, basis,
                        "turbopump masses +-50%"))
    # 500 preburners
    for k, pb in enumerate((b.fuel_pb, b.ox_pb), start=1):
        add(BomItem(f"PB-5{k}0", pb.name.capitalize(), "500 Preburners", pb.material, 1, pb.mass, "sized",
                    f"{pb.diameter * 1e3:.0f} mm dia x {pb.length * 1e3:.0f} mm, wall {pb.wall_thickness * 1e3:.1f} mm"))
    # 600 lines and valves
    for ln in b.lines:
        add(BomItem(f"FL-6{ln.tag[1:]}", ln.description, "600 Lines and ducts", ln.material, 1, ln.mass, "sized",
                    f"ID {ln.inner_diameter * 1e3:.0f} mm, wall {ln.wall_thickness * 1e3:.1f} mm, {ln.length:.1f} m (length estimated)"))
    for v in b.valves:
        if "vehicle side" in v.description:
            continue
        add(BomItem(f"VA-7{v.tag[1:]}", v.description, "700 Valves", v.material, 1, v.mass, "estimate",
                    f"{v.kind}, {v.diameter * 1e3:.0f} mm, {v.pressure / 1e5:.0f} bar"))
    # 800 other
    add(BomItem("GM-810", "Gimbal block and thrust structure", "800 Engine systems", "Ti64", 1, ci.gimbal_and_thrust_block, "estimate"))
    add(BomItem("EC-820", "Engine controller and harness", "800 Engine systems", "various", 1, ci.controller_and_harness, "estimate"))
    add(BomItem("IG-830", "Spark-torch igniters (main chamber and preburners)", "800 Engine systems", "IN718", 3, ci.igniters / 3, "estimate"))
    add(BomItem("SN-840", "Pressure and temperature sensors", "800 Engine systems", "various", 1, ci.sensors, "estimate"))
    return items


def with_changes(ci: ComponentInputs, **groups) -> ComponentInputs:
    """Copy of the inputs with fields changed inside named groups: with_changes(ci, cooling={...})."""
    kw = {}
    for group, changes in groups.items():
        kw[group] = replace(getattr(ci, group), **changes) if isinstance(changes, dict) else changes
    return replace(ci, **kw)
