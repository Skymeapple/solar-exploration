"""Turbopump preliminary design: inducer/impeller pumps and axial turbines (gate G5).

Method (Gulich, "Centrifugal Pumps", 3rd ed.; Huzel & Huang ch. 6; NASA SP-8107 turbopump systems):

1. Shaft speed from the suction limit: S = w sqrt(Q) / (g NPSH)^0.75 must not exceed the
   inducer's suction specific speed.
2. Stage count from the impeller tip speed: u2 = sqrt(g H_stage / psi), limited by the
   rotating-disc stress of the impeller material and by a packaging limit on diameter.
3. Pump efficiency predicted from the stage specific speed and flow (Gulich eq. 3.28) and
   compared with the value the cycle balance assumed.
4. Turbine mean diameter from the blade-to-gas speed ratio u/c0, efficiency from the
   u/c0 curve of a single-stage reaction turbine, blade root stress from A*N^2.
5. Shaft diameter from torsion.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .. import thermo
from ..constants import G0, R_UNIVERSAL
from ..cycle import CycleResult, ShaftResult
from .materials import MATERIALS, allowable

US_PER_SI_SPECIFIC_SPEED = 2733.0  # N_s(rpm, gpm, ft) per dimensionless N_s (rad/s, m^3/s, m)


@dataclass(frozen=True)
class TurbopumpInputs:
    """Design choices. Values are typical practice, not Raptor data."""

    suction_specific_speed_us: float = 25_000.0  # inducer design value (US units); 20k-30k is usual with an inducer
    head_coefficient: float = 0.50  # psi = g H / u2^2 per stage
    max_impeller_diameter: float = 0.36  # m, packaging limit
    max_stages: int = 3
    turbine_velocity_ratio: float = 0.55  # u / c0 at the mean diameter
    turbine_axial_velocity_fraction: float = 0.30  # c_ax / c0
    turbine_tip_speed_limit: float = 550.0  # m/s
    blade_taper_factor: float = 0.6
    t_ox_inlet: float = 90.0  # K, LOX at the pump inlet (normal boiling point; subcooling adds margin)
    t_fuel_inlet: float = 111.6  # K, methane at the pump inlet
    fuel_impeller_material: str = "Ti64"
    ox_impeller_material: str = "MonelK500"
    fuel_turbine_material: str = "IN718"
    ox_turbine_material: str = "OXSA"
    shaft_material_fuel: str = "IN718"
    shaft_material_ox: str = "OXSA"


@dataclass(frozen=True)
class PumpDesign:
    name: str
    flow: float  # kg/s
    density: float
    volume_flow: float  # m^3/s
    head: float  # m, total
    npsh_available: float  # m
    speed: float  # rad/s
    stages: int
    specific_speed: float  # dimensionless per stage
    nq: float  # Gulich units: rpm, m^3/s, m
    suction_specific_speed_us: float
    tip_speed: float  # m/s
    impeller_diameter: float  # m
    inducer_diameter: float  # m
    efficiency_predicted: float
    efficiency_assumed: float
    disc_stress: float  # Pa, impeller rotating-disc stress at the tip speed
    disc_allowable: float
    material: str

    @property
    def rpm(self) -> float:
        return self.speed * 60 / (2 * math.pi)


@dataclass(frozen=True)
class TurbineDesign:
    name: str
    flow: float
    inlet_temperature: float
    inlet_pressure: float
    pressure_ratio: float
    isentropic_enthalpy_drop: float  # J/kg
    spouting_velocity: float  # m/s
    mean_diameter: float  # m
    blade_height: float  # m
    tip_speed: float
    velocity_ratio: float
    efficiency_predicted: float
    efficiency_assumed: float
    an2: float  # m^2 rpm^2
    blade_root_stress: float
    blade_allowable: float
    exit_temperature: float
    material: str


@dataclass(frozen=True)
class TurbopumpDesign:
    name: str
    pump: PumpDesign
    turbine: TurbineDesign
    shaft_diameter: float  # m
    torque: float  # N m
    power: float  # W
    mass: float  # kg, estimated
    mass_breakdown: dict[str, float]
    kick_stage_diameter: float = 0.0  # m
    kick_stage_power: float = 0.0  # W


def vapor_pressure(fluid: str, t: float) -> float:
    import CoolProp.CoolProp as CP

    return float(CP.PropsSI("P", "T", t, "Q", 0, fluid))


def gulich_efficiency(nq: float, q: float) -> float:
    """Best efficiency of a single-stage radial pump, Gulich eq. 3.28 (Q in m^3/s, nq in rpm-m^3/s-m units)."""
    q_ref = 1.0
    a = 1.0
    m = 0.08 * a * (q_ref / q) ** 0.15 * (45.0 / nq) ** 0.06
    return 1.0 - 0.095 * (q_ref / q) ** m - 0.3 * (0.35 - math.log10(nq / 23.0)) ** 2 * (q_ref / q) ** 0.05


def gas_properties(p: float, mixture_ratio: float) -> tuple[float, float, float, float]:
    """Preburner gas: temperature K, frozen cp J/(kg K), frozen gamma, gas constant J/(kg K)."""
    g = thermo.chamber(p, mixture_ratio)
    r_gas = R_UNIVERSAL / (g.molecular_weight / 1000.0)
    gamma = g.cp_frozen / (g.cp_frozen - r_gas)
    return g.temperature, g.cp_frozen, gamma, r_gas


def turbine_exit_temperature(shaft: ShaftResult, p_out: float, eta: float) -> float:
    _t, cp, gamma, _r = gas_properties(shaft.preburner_pressure, shaft.preburner_mixture_ratio)
    t_in = shaft.turbine_inlet_temperature
    return t_in * (1 - eta * (1 - (p_out / shaft.preburner_pressure) ** ((gamma - 1) / gamma)))


def _pump(
    name: str, mdot: float, rho: float, p_in: float, p_out: float, p_vap: float, eta_assumed: float,
    ti: TurbopumpInputs, material: str,
) -> PumpDesign:
    q = mdot / rho
    head = (p_out - p_in) / (rho * G0)
    npsh = (p_in - p_vap) / (rho * G0)
    s_si = ti.suction_specific_speed_us / US_PER_SI_SPECIFIC_SPEED
    speed = s_si * (G0 * npsh) ** 0.75 / math.sqrt(q)
    mat = MATERIALS[material]
    sig_allow = allowable(mat, 293.0)
    # Fewest stages that keep the impeller inside the diameter limit.
    for stages in range(1, ti.max_stages + 1):
        u2 = math.sqrt(G0 * head / stages / ti.head_coefficient)
        d2 = 2 * u2 / speed
        if d2 <= ti.max_impeller_diameter:
            break
    ns = speed * math.sqrt(q) / (G0 * head / stages) ** 0.75
    nq = ns * 52.9
    eta = gulich_efficiency(nq, q)
    # Inducer tip diameter for a flow coefficient of 0.10 at the inducer tip with a 0.3 hub ratio.
    phi = 0.10
    d_ind = (8 * q / (math.pi * phi * speed * (1 - 0.3**2))) ** (1 / 3)
    nu = 0.3
    disc_stress = (3 + nu) / 8 * mat.density * u2**2
    return PumpDesign(
        name, mdot, rho, q, head, npsh, speed, stages, ns, nq,
        speed * math.sqrt(q) / (G0 * npsh) ** 0.75 * US_PER_SI_SPECIFIC_SPEED,
        u2, d2, d_ind, eta, eta_assumed, disc_stress, sig_allow, material,
    )


def _turbine(
    name: str, shaft: ShaftResult, p_out: float, speed: float, eta_assumed: float, ti: TurbopumpInputs, material: str
) -> TurbineDesign:
    t_in, cp, gamma, r_gas = gas_properties(shaft.preburner_pressure, shaft.preburner_mixture_ratio)
    t_in = shaft.turbine_inlet_temperature
    pr = shaft.preburner_pressure / p_out
    dh_s = cp * t_in * (1 - pr ** (-(gamma - 1) / gamma))
    c0 = math.sqrt(2 * dh_s)
    u = ti.turbine_velocity_ratio * c0
    d_m = 2 * u / speed
    t_out = t_in - eta_assumed * dh_s / cp
    rho_out = p_out / (r_gas * t_out)
    c_ax = ti.turbine_axial_velocity_fraction * c0
    area = shaft.turbine_flow / (rho_out * c_ax)
    h = area / (math.pi * d_m)
    tip = speed * (d_m / 2 + h / 2)
    # Single-stage reaction turbine: peak about 0.88 at u/c0 = 0.65, parabolic fall-off
    # (Huzel & Huang fig. 6-41, smoothed).
    nu_opt, eta_peak = 0.65, 0.88
    eta = eta_peak * (1 - ((ti.turbine_velocity_ratio - nu_opt) / nu_opt) ** 2)
    # Blade-height penalty: tip clearance and secondary losses grow when blades are short.
    if h < 0.015:
        eta -= 0.5 * (0.015 - h) / 0.015 * 0.10
    rpm = speed * 60 / (2 * math.pi)
    mat = MATERIALS[material]
    stress = ti.blade_taper_factor * mat.density * speed**2 * area / (2 * math.pi)
    return TurbineDesign(
        name, shaft.turbine_flow, t_in, shaft.preburner_pressure, pr, dh_s, c0, d_m, h, tip,
        ti.turbine_velocity_ratio, eta, eta_assumed, area * rpm**2, stress, allowable(mat, t_in), t_out, material,
    )


def _shell_mass(p: float, radius: float, length: float, material: str, temperature: float = 293.0) -> float:
    mat = MATERIALS[material]
    t = max(p * radius / allowable(mat, temperature), 3e-3)
    side = 2 * math.pi * radius * length * t
    ends = 2 * math.pi * radius**2 * t
    return mat.density * (side + ends)


def design_turbopumps(
    cycle: CycleResult, ti: TurbopumpInputs | None = None
) -> tuple[TurbopumpDesign, TurbopumpDesign]:
    """Fuel and oxidizer turbopumps from a closed cycle."""
    from ..constants import RHO_LCH4, RHO_LOX

    ti = ti or TurbopumpInputs()
    a = cycle.assumptions
    designs = []
    for shaft, fluid, rho, t_in, eta_p, eta_t, imp_mat, tur_mat, sh_mat in (
        (cycle.fuel_shaft, "Methane", RHO_LCH4, ti.t_fuel_inlet, a.eta_pump_fuel, a.eta_turbine_fuel,
         ti.fuel_impeller_material, ti.fuel_turbine_material, ti.shaft_material_fuel),
        (cycle.ox_shaft, "Oxygen", RHO_LOX, ti.t_ox_inlet, a.eta_pump_ox, a.eta_turbine_ox,
         ti.ox_impeller_material, ti.ox_turbine_material, ti.shaft_material_ox),
    ):
        pump_flow = shaft.pump_flow
        pump = _pump(
            shaft.name, pump_flow, rho, a.p_pump_inlet, shaft.pump_discharge_pressure,
            vapor_pressure(fluid, t_in), eta_p, ti, imp_mat,
        )
        p_out = shaft.preburner_pressure / shaft.turbine_pressure_ratio
        turb = _turbine(shaft.name, shaft, p_out, pump.speed, eta_t, ti, tur_mat)
        torque = shaft.pump_power / pump.speed  # includes the kick stage
        tau = 0.577 * allowable(MATERIALS[sh_mat], 600.0)
        d_shaft = (16 * torque / (math.pi * tau)) ** (1 / 3)

        # Mass estimate (+-50%): rotating parts as solid discs at 40% solidity, casings as
        # pressure shells, then a 1.4 factor for bearings, seals, flanges and the volute.
        imp = MATERIALS[imp_mat]
        rotor = pump.stages * 0.4 * imp.density * math.pi / 4 * pump.impeller_diameter**2 * 0.12 * pump.impeller_diameter
        rotor += 0.4 * imp.density * math.pi / 4 * pump.inducer_diameter**2 * 0.6 * pump.inducer_diameter
        disc = 0.4 * MATERIALS[tur_mat].density * math.pi / 4 * (turb.mean_diameter - turb.blade_height) ** 2 * 0.05
        shaft_len = (0.5 * pump.stages + 0.6) * pump.impeller_diameter + 0.15
        shaft_m = MATERIALS[sh_mat].density * math.pi / 4 * d_shaft**2 * shaft_len
        pump_case = _shell_mass(
            shaft.pump_discharge_pressure, 0.8 * pump.impeller_diameter,
            (0.45 * pump.stages + 0.4) * pump.impeller_diameter, "IN718" if fluid == "Methane" else "OXSA",
        )
        turb_case = _shell_mass(
            shaft.preburner_pressure, 0.5 * turb.mean_diameter + turb.blade_height + 0.02, 0.12,
            tur_mat, shaft.turbine_inlet_temperature,
        )
        breakdown = {
            "impellers_and_inducer": rotor,
            "turbine_disc_and_blades": disc,
            "shaft": shaft_m,
            "pump_housing": pump_case,
            "turbine_housing": turb_case,
        }
        d_kick = 0.0
        if shaft.kick_power > 0:
            # kick_power = m_kick * g * H / eta, with m_kick the other preburner's share of this propellant.
            other = cycle.ox_shaft if shaft is cycle.fuel_shaft else cycle.fuel_shaft
            if shaft is cycle.fuel_shaft:
                m_kick = other.turbine_flow / (1 + other.preburner_mixture_ratio)
            else:
                m_kick = other.turbine_flow * other.preburner_mixture_ratio / (1 + other.preburner_mixture_ratio)
            head_k = shaft.kick_power * eta_p / (m_kick * G0)
            d_kick = 2 * math.sqrt(G0 * head_k / ti.head_coefficient) / pump.speed
            breakdown["kick_stage"] = 0.4 * imp.density * math.pi / 4 * d_kick**2 * 0.12 * d_kick + 5.0
        breakdown["bearings_seals_flanges"] = 0.4 * sum(breakdown.values())
        designs.append(
            TurbopumpDesign(
                f"{shaft.name} turbopump", pump, turb, d_shaft, torque, shaft.pump_power, sum(breakdown.values()),
                breakdown, d_kick, shaft.kick_power,
            )
        )
    return designs[0], designs[1]
