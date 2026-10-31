"""Component checks, subsystem validation and whole-engine validation.

Every check records the value, the limit, where the limit comes from, and
whether the check is a gate (G4, G5, G6) or a design rule. The iteration
loop in `iterate.py` reads the failures and applies fixes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from ..benchmarks import RAPTOR_2_SEA_LEVEL
from ..cycle import solve_cycle
from .assembly import EngineBuild
from .materials import MATERIALS

# Limits that are design rules rather than physics. Sources in brackets.
MAX_EXIT_DIAMETER = 1.40  # m, packaging limit carried over from the optimizer (step 3)
MIN_CHANNEL_WIDTH = 0.6e-3  # m, slitting-saw / AM minimum [Huzel & Huang sec. 4.5]
MAX_CHANNEL_ASPECT = 8.0  # depth / width for milled channels [NASA TM-2005-213955, high aspect ratio channels]
MIN_INJECTOR_STIFFNESS = 0.15  # dp / Pc [Huzel & Huang sec. 4.4]
MIN_ANNULUS_GAP = 0.5e-3  # m
MAX_SUCTION_SPECIFIC_SPEED_US = 30_000.0  # inducer practice [NASA SP-8052]
MIN_BLADE_HEIGHT = 5e-3  # m
WALL_TEMPERATURE_MARGIN = 0.95  # hot wall must stay below 95% of the material limit
VALVE_LOSS_COEFFICIENT = 0.5  # velocity heads across an open ball/poppet valve
G6_MASS_TOLERANCE = 0.30  # engine mass within 30% of the public figure (low-confidence benchmark)
G6_MIN_THRUST_TO_WEIGHT = 100.0
FILM_ISP_PENALTY_PER_FLOW = 0.5  # fractional Isp loss per fraction of total flow used as film [estimate]


@dataclass(frozen=True)
class Check:
    id: str
    level: str  # "component", "subsystem", "system"
    component: str
    description: str
    value: float
    limit: float
    unit: str
    passed: bool
    gate: str = ""  # "G4", "G5", "G6", or "" for a design rule
    basis: str = ""


def _le(id_, level, comp, desc, value, limit, unit, gate="", basis="") -> Check:
    return Check(id_, level, comp, desc, value, limit, unit, value <= limit, gate, basis)


def _ge(id_, level, comp, desc, value, limit, unit, gate="", basis="") -> Check:
    return Check(id_, level, comp, desc, value, limit, unit, value >= limit, gate, basis)


def film_flow(b: EngineBuild) -> float:
    """Fuel used as film coolant, kg/s."""
    return b.inputs.cooling.film_fraction_of_fuel * b.perf.mdot_fuel


def delivered_isp(b: EngineBuild) -> tuple[float, float]:
    """Sea-level and vacuum Isp after the film-cooling loss."""
    loss = FILM_ISP_PENALTY_PER_FLOW * film_flow(b) / b.perf.mdot
    return b.perf.isp_sl * (1 - loss), b.perf.isp_vac * (1 - loss)


def component_checks(b: EngineBuild) -> list[Check]:
    c: list[Check] = []
    ci = b.inputs
    pc = b.perf.design.pc

    # Thrust chamber
    c.append(_le("TC-1", "component", "Thrust chamber", "Nozzle exit diameter", 2 * b.contour.re, MAX_EXIT_DIAMETER, "m",
                 basis="packaging limit from the optimizer"))
    c.append(_ge("TC-2", "component", "Thrust chamber", "Sea-level separation margin (Summerfield)",
                 b.perf.separation_margin, 1.0, "-", basis="exit pressure above 0.4 of ambient"))

    # Regenerative cooling
    st = b.cooling.stations
    for mat_key in sorted({s.material for s in st}):
        mat = MATERIALS[mat_key]
        hot = max((s for s in st if s.material == mat_key), key=lambda s: s.t_wall_gas)
        c.append(_le(f"CL-1{'a' if mat_key == 'GRCop-42' else 'b'}", "component", "Cooling",
                     f"Peak hot-wall temperature, {mat_key} (x = {hot.x * 1e3:.0f} mm)", hot.t_wall_gas,
                     WALL_TEMPERATURE_MARGIN * mat.max_service_temperature, "K", "G4",
                     f"95% of {mat.max_service_temperature:.0f} K service limit"))
    worst_hw = max(st, key=lambda s: s.hot_wall_stress / s.hot_wall_allowable)
    c.append(_le("CL-2", "component", "Cooling", f"Hot-wall pressure bending stress / allowable (x = {worst_hw.x * 1e3:.0f} mm)",
                 worst_hw.hot_wall_stress / worst_hw.hot_wall_allowable, 1.0, "-", "G4", "SF 1.25 yield, 1.5 ultimate at wall temperature"))
    worst_rib = max(st, key=lambda s: s.rib_stress / s.rib_allowable)
    c.append(_le("CL-3", "component", "Cooling", f"Rib tensile stress / allowable (x = {worst_rib.x * 1e3:.0f} mm)",
                 worst_rib.rib_stress / worst_rib.rib_allowable, 1.0, "-", "G4"))
    c.append(_le("CL-4", "component", "Cooling", "Coolant pressure drop vs cycle budget",
                 b.cooling.pressure_drop / 1e5, ci.cycle.dp_cooling * pc / 1e5, "bar", "G4", "budget = dp_cooling x Pc in the cycle"))
    c.append(_ge("CL-5", "component", "Cooling", "Narrowest channel", min(s.width for s in st) * 1e3, MIN_CHANNEL_WIDTH * 1e3, "mm",
                 basis="manufacturing minimum"))
    c.append(_le("CL-6", "component", "Cooling", "Largest channel aspect ratio (depth / width)",
                 max(s.depth / s.width for s in st), MAX_CHANNEL_ASPECT, "-", basis="milling limit"))

    # Injector
    inj = b.injector
    c.append(_ge("IN-1", "component", "Main injector", "Injector stiffness dp / Pc", inj.pressure_drop / pc, MIN_INJECTOR_STIFFNESS, "-",
                 basis="combustion stability rule of thumb"))
    c.append(_ge("IN-2", "component", "Main injector", "Fuel / oxidizer velocity ratio", inj.velocity_ratio,
                 ci.injector.min_velocity_ratio, "-", basis="gas-gas shear coax mixing guideline"))
    c.append(_ge("IN-3", "component", "Main injector", "Metal ligament between neighbouring elements",
                 inj.ligament * 1e3, ci.injector.min_ligament * 1e3, "mm", basis="manufacturing minimum"))
    c.append(_ge("IN-4", "component", "Main injector", "Fuel annulus gap",
                 (inj.annulus_outer_diameter - inj.post_outer_diameter) / 2 * 1e3, MIN_ANNULUS_GAP * 1e3, "mm"))
    c.append(_le("IN-5", "component", "Main injector", "Face plate stress / allowable", inj.face_stress / inj.face_allowable, 1.0, "-"))
    c.append(Check("IN-6", "component", "Main injector", "Oxygen-rich dome material is oxygen compatible", 1.0, 1.0, "-",
                   MATERIALS[ci.injector.ox_dome_material].oxygen_compatible))

    # Turbopumps
    for tag, tp in (("F", b.fuel_tp), ("O", b.ox_tp)):
        p, t = tp.pump, tp.turbine
        name = tp.name.capitalize()
        c.append(_le(f"TP-{tag}1", "component", name, "Suction specific speed (US units)", p.suction_specific_speed_us,
                     MAX_SUCTION_SPECIFIC_SPEED_US, "-", "G5", "inducer practice"))
        c.append(_le(f"TP-{tag}2", "component", name, f"Impeller diameter ({p.stages} stage(s), {p.rpm:,.0f} rpm)",
                     p.impeller_diameter, ci.turbopump.max_impeller_diameter, "m", "G5", "packaging limit"))
        c.append(_le(f"TP-{tag}3", "component", name, "Impeller disc stress / allowable", p.disc_stress / p.disc_allowable, 1.0, "-", "G5"))
        c.append(_ge(f"TP-{tag}4", "component", name, "Pump efficiency predicted vs assumed in cycle",
                     p.efficiency_predicted, p.efficiency_assumed, "-", "G5", "Gulich eq. 3.28"))
        c.append(_ge(f"TP-{tag}5", "component", name, "Turbine efficiency predicted vs assumed in cycle",
                     t.efficiency_predicted, t.efficiency_assumed, "-", "G5", "u/c0 curve"))
        c.append(_le(f"TP-{tag}6", "component", name, "Turbine blade root stress / allowable",
                     t.blade_root_stress / t.blade_allowable, 1.0, "-", "G5"))
        c.append(_le(f"TP-{tag}7", "component", name, "Turbine tip speed", t.tip_speed, ci.turbopump.turbine_tip_speed_limit, "m/s", "G5"))
        c.append(_ge(f"TP-{tag}8", "component", name, "Turbine blade height", t.blade_height * 1e3, MIN_BLADE_HEIGHT * 1e3, "mm", "G5"))
    ox_mats = [ci.turbopump.ox_impeller_material, ci.turbopump.ox_turbine_material, ci.turbopump.shaft_material_ox]
    c.append(Check("TP-O9", "component", "Oxidizer turbopump", "All oxygen-wetted materials oxygen compatible", 1.0, 1.0, "-",
                   all(MATERIALS[m].oxygen_compatible for m in ox_mats), "G5"))

    # Preburners
    for tag, pb in (("F", b.fuel_pb), ("O", b.ox_pb)):
        mat = MATERIALS[pb.material]
        c.append(_le(f"PB-{tag}1", "component", pb.name.capitalize(), "Hoop stress / allowable", pb.hoop_stress / pb.allowable, 1.0, "-"))
        c.append(_le(f"PB-{tag}2", "component", pb.name.capitalize(), "Wall temperature (with streaks)", pb.wall_temperature,
                     mat.max_service_temperature, "K"))
    c.append(Check("PB-O3", "component", "Oxygen-rich preburner", "Material oxygen compatible", 1.0, 1.0, "-",
                   MATERIALS[b.ox_pb.material].oxygen_compatible))
    for ln in b.lines:
        if "LOX" in ln.fluid or "ox-rich" in ln.fluid:
            c.append(Check(f"FL-{ln.tag}", "component", "Lines", f"{ln.tag} material oxygen compatible", 1.0, 1.0, "-",
                           MATERIALS[ln.material].oxygen_compatible))
    return c


def pressure_ladder(b: EngineBuild) -> list[dict]:
    """Supply minus losses versus the pressure each consumer needs, for every flow path."""
    a = b.inputs.cycle
    pc = b.perf.design.pc
    fu, ox = b.cycle.fuel_shaft, b.cycle.ox_shaft
    L = {ln.tag: ln for ln in b.lines}

    def valve(tag: str) -> float:
        ln = L[tag]
        return VALVE_LOSS_COEFFICIENT * 0.5 * ln.density * ln.velocity**2

    need_fpb = fu.preburner_pressure * (1 + a.dp_pb_injector)
    need_opb = ox.preburner_pressure * (1 + a.dp_pb_injector)
    p_man = pc * (1 + a.dp_main_injector)
    kick_supply = max(fu.pump_discharge_pressure, need_opb + a.dp_liquid_lines * pc) if a.fuel_kick_stage else fu.pump_discharge_pressure
    ox_kick_supply = max(ox.pump_discharge_pressure, need_fpb + a.dp_liquid_lines * pc) if a.ox_kick_stage else ox.pump_discharge_pressure
    paths = [
        ("Fuel pump -> L05 -> cooling jacket -> L06 -> CCV -> fuel-rich preburner", fu.pump_discharge_pressure,
         L["L05"].pressure_drop + valve("L05") + b.cooling.pressure_drop + L["L06"].pressure_drop + valve("L06"), need_fpb),
        ("Oxidizer pump -> L03 -> MOV -> oxygen-rich preburner", ox.pump_discharge_pressure,
         L["L03"].pressure_drop + valve("L03"), need_opb),
        ("Oxidizer pump" + (" + kick stage" if a.ox_kick_stage else "") + " -> L04 -> FPOV -> fuel-rich preburner", ox_kick_supply,
         L["L04"].pressure_drop + valve("L04"), need_fpb),
        ("Fuel pump" + (" + kick stage" if a.fuel_kick_stage else "") + " -> L07 -> OPFV -> oxygen-rich preburner", kick_supply,
         L["L07"].pressure_drop + valve("L07"), need_opb),
        ("Oxidizer turbine exit -> L08 -> main injector oxygen-rich manifold", ox.preburner_pressure / ox.turbine_pressure_ratio,
         L["L08"].pressure_drop, p_man),
        ("Fuel turbine exit -> L09 -> main injector fuel-rich manifold", fu.preburner_pressure / fu.turbine_pressure_ratio,
         L["L09"].pressure_drop, p_man),
    ]
    return [
        {"path": name, "supply_bar": s / 1e5, "losses_bar": loss / 1e5, "delivered_bar": (s - loss) / 1e5,
         "required_bar": need / 1e5, "margin_bar": (s - loss - need) / 1e5}
        for name, s, loss, need in paths
    ]


def subsystem_checks(b: EngineBuild) -> list[Check]:
    c = []
    for k, row in enumerate(pressure_ladder(b), start=1):
        c.append(_ge(f"SS-{k}", "subsystem", "Pressure ladder", row["path"], row["margin_bar"], 0.0, "bar",
                     basis="delivered pressure minus required"))
    # Turbopump-cycle consistency: re-solve the cycle with the lower of assumed and predicted efficiencies.
    a = b.inputs.cycle
    pred = replace(
        a,
        eta_pump_fuel=min(a.eta_pump_fuel, b.fuel_tp.pump.efficiency_predicted),
        eta_pump_ox=min(a.eta_pump_ox, b.ox_tp.pump.efficiency_predicted),
        eta_turbine_fuel=min(a.eta_turbine_fuel, b.fuel_tp.turbine.efficiency_predicted),
        eta_turbine_ox=min(a.eta_turbine_ox, b.ox_tp.turbine.efficiency_predicted),
    )
    closed = solve_cycle(b.perf, pred).closed
    c.append(Check("SS-7", "subsystem", "Turbopumps + cycle", "Cycle closes with predicted component efficiencies",
                   float(closed), 1.0, "-", closed, "G5"))
    # Thrust chamber: the cooling flow equals the fuel-rich preburner's fuel; heat picked up is consistent.
    fu = b.cycle.fuel_shaft
    f1 = fu.turbine_flow / (1 + fu.preburner_mixture_ratio)
    c.append(_le("SS-8", "subsystem", "Thrust chamber + cooling", "Coolant flow mismatch vs fuel-rich preburner fuel",
                 abs(b.cooling.coolant_flow - f1) / f1, 1e-6, "-"))
    return c


def system_checks(b: EngineBuild) -> list[Check]:
    c = []
    from ..gates import gate_g2

    g2 = gate_g2(b.cycle)
    c.append(Check("SY-1", "system", "Engine", "G2 cycle balance with all component-derived assumptions", float(bool(g2.passed)),
                   1.0, "-", bool(g2.passed), "G2", g2.detail))
    ref = RAPTOR_2_SEA_LEVEL["mass"].value
    c.append(_le("SY-2", "system", "Engine", f"Dry mass vs public Raptor 2 figure ({ref:.0f} kg, low confidence)",
                 abs(b.mass - ref) / ref, G6_MASS_TOLERANCE, "-", "G6", f"model {b.mass:.0f} kg"))
    c.append(_ge("SY-3", "system", "Engine", "Sea-level thrust-to-weight", b.thrust_to_weight, G6_MIN_THRUST_TO_WEIGHT, "-", "G6"))
    isp_sl, isp_vac = delivered_isp(b)
    c.append(_le("SY-4", "system", "Engine", "Sea-level Isp error after film-cooling loss vs 327 s",
                 abs(isp_sl - RAPTOR_2_SEA_LEVEL["isp_sl"].value) / RAPTOR_2_SEA_LEVEL["isp_sl"].value, 0.05, "-", "G7",
                 f"{isp_sl:.1f} s"))
    return c


def all_checks(b: EngineBuild) -> list[Check]:
    return component_checks(b) + subsystem_checks(b) + system_checks(b)
