"""Thrust chamber and nozzle sizing (fidelity level L1)."""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import thermo
from .constants import G0, P_SEA_LEVEL

# Summerfield criterion: flow separates in an over-expanded nozzle when the
# exit pressure falls below about 0.4 of ambient. Kept as the G3 limit.
SUMMERFIELD_RATIO = 0.4


@dataclass(frozen=True)
class EngineDesign:
    """The design variables the optimizer will move later."""

    pc: float = 300e5  # chamber pressure, Pa
    mixture_ratio: float = 3.6  # O/F by mass
    eps: float = 34.34  # nozzle area ratio Ae/At
    thrust_sl: float = 2.256e6  # required sea-level thrust, N
    # Efficiencies relative to ideal equilibrium flow. Typical values for a
    # large regeneratively cooled engine; eta_cstar * eta_cf = 0.946 is what
    # turns ideal CEA numbers into Raptor 2's published Isp.
    eta_cstar: float = 0.975
    eta_cf: float = 0.970


@dataclass(frozen=True)
class EnginePerformance:
    design: EngineDesign
    chamber: thermo.ChamberGas
    cstar: float  # delivered, m/s
    isp_vac: float  # s
    isp_sl: float  # s
    thrust_vac: float  # N
    mdot: float  # total propellant flow, kg/s
    mdot_ox: float
    mdot_fuel: float
    throat_area: float  # m^2
    throat_diameter: float  # m
    exit_diameter: float  # m
    exit_pressure: float  # Pa
    separation_margin: float  # (pe / pa) / Summerfield limit; >1 means attached at sea level

    def summary(self) -> dict[str, float]:
        return {
            "chamber_pressure_bar": self.design.pc / 1e5,
            "mixture_ratio": self.design.mixture_ratio,
            "area_ratio": self.design.eps,
            "chamber_temperature_K": self.chamber.temperature,
            "cstar_m_s": self.cstar,
            "isp_sl_s": self.isp_sl,
            "isp_vac_s": self.isp_vac,
            "thrust_sl_kN": self.design.thrust_sl / 1e3,
            "thrust_vac_kN": self.thrust_vac / 1e3,
            "mdot_kg_s": self.mdot,
            "throat_diameter_m": self.throat_diameter,
            "exit_diameter_m": self.exit_diameter,
            "exit_pressure_bar": self.exit_pressure / 1e5,
            "separation_margin": self.separation_margin,
        }


def size_engine(design: EngineDesign, p_ambient: float = P_SEA_LEVEL) -> EnginePerformance:
    """Size the throat for the required thrust and compute delivered performance."""
    gas = thermo.chamber(design.pc, design.mixture_ratio)
    eta = design.eta_cstar * design.eta_cf

    cstar = design.eta_cstar * gas.cstar_ideal
    isp_vac = eta * thermo.ideal_isp(design.pc, design.mixture_ratio, design.eps)
    # Ambient back-pressure acting on the exit area: F = F_vac - pa * Ae,
    # and Ae / mdot = eps * cstar / pc.
    isp_sl = isp_vac - p_ambient * design.eps * cstar / (design.pc * G0)
    if isp_sl <= 0:
        raise ValueError("Nozzle produces no thrust at this ambient pressure")

    mdot = design.thrust_sl / (isp_sl * G0)
    throat_area = mdot * cstar / design.pc
    exit_area = throat_area * design.eps
    pe = thermo.exit_pressure(design.pc, design.mixture_ratio, design.eps)

    return EnginePerformance(
        design=design,
        chamber=gas,
        cstar=cstar,
        isp_vac=isp_vac,
        isp_sl=isp_sl,
        thrust_vac=mdot * isp_vac * G0,
        mdot=mdot,
        mdot_ox=mdot * design.mixture_ratio / (1 + design.mixture_ratio),
        mdot_fuel=mdot / (1 + design.mixture_ratio),
        throat_area=throat_area,
        throat_diameter=math.sqrt(4 * throat_area / math.pi),
        exit_diameter=math.sqrt(4 * exit_area / math.pi),
        exit_pressure=pe,
        separation_margin=(pe / p_ambient) / SUMMERFIELD_RATIO if p_ambient > 0 else math.inf,
    )
