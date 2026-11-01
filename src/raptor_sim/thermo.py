"""Combustion chemistry for liquid methane and liquid oxygen.

NASA CEA (through RocketCEA) is the primary source. Cantera with GRI-Mech 3.0
gives an independent equilibrium calculation for gate G1.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from scipy.optimize import brentq

from .constants import (
    DH_LCH4_J_PER_MOL,
    DH_LOX_J_PER_MOL,
    MW_CH4,
    MW_O2,
)

OXIDIZER = "LOX"
FUEL = "LCH4_NASA"


@lru_cache(maxsize=1)
def _cea():
    from rocketcea.cea_obj_w_units import CEA_Obj

    return CEA_Obj(
        oxName=OXIDIZER,
        fuelName=FUEL,
        pressure_units="Pa",
        temperature_units="K",
        cstar_units="m/s",
        isp_units="sec",
        specific_heat_units="J/kg-K",
        sonic_velocity_units="m/s",
    )


@dataclass(frozen=True)
class ChamberGas:
    """Equilibrium combustion gas in the chamber."""

    pc: float  # Pa
    mixture_ratio: float  # O/F by mass
    temperature: float  # K
    molecular_weight: float  # g/mol
    gamma: float  # equilibrium ratio of specific heats
    cp_frozen: float  # J/(kg K)
    cstar_ideal: float  # m/s


def chamber(pc: float, mixture_ratio: float) -> ChamberGas:
    """Equilibrium chamber state from NASA CEA."""
    cea = _cea()
    mw, gamma = cea.get_Chamber_MolWt_gamma(Pc=pc, MR=mixture_ratio)
    return ChamberGas(
        pc=pc,
        mixture_ratio=mixture_ratio,
        temperature=float(cea.get_Tcomb(Pc=pc, MR=mixture_ratio)),
        molecular_weight=float(mw),
        gamma=float(gamma),
        cp_frozen=float(cea.get_Chamber_Cp(Pc=pc, MR=mixture_ratio, frozen=1)),
        cstar_ideal=float(cea.get_Cstar(Pc=pc, MR=mixture_ratio)),
    )


def ideal_isp(pc: float, mixture_ratio: float, eps: float, p_ambient: float = 0.0) -> float:
    """Ideal equilibrium specific impulse in seconds at a given ambient pressure."""
    cea = _cea()
    if p_ambient <= 0.0:
        return float(cea.get_Isp(Pc=pc, MR=mixture_ratio, eps=eps))
    isp, _mode = cea.estimate_Ambient_Isp(Pc=pc, MR=mixture_ratio, eps=eps, Pamb=p_ambient)
    return float(isp)


def exit_pressure(pc: float, mixture_ratio: float, eps: float) -> float:
    """Nozzle exit static pressure in Pa (equilibrium expansion)."""
    return pc / float(_cea().get_PcOvPe(Pc=pc, MR=mixture_ratio, eps=eps))


def cantera_chamber(pc: float, mixture_ratio: float) -> tuple[float, float]:
    """Independent equilibrium (T in K, MW in g/mol) from Cantera GRI-Mech 3.0.

    The propellants enter as liquids at their boiling points, matching CEA.
    """
    import cantera as ct

    gas = ct.Solution("gri30.yaml")
    y_ox = mixture_ratio / (1.0 + mixture_ratio)
    y_fuel = 1.0 - y_ox
    comp = {"O2": y_ox, "CH4": y_fuel}

    gas.TPY = 298.15, pc, comp
    h_target = (
        gas.enthalpy_mass
        + y_ox * DH_LOX_J_PER_MOL / MW_O2
        + y_fuel * DH_LCH4_J_PER_MOL / MW_CH4
    )

    def residual(t: float) -> float:
        gas.TPY = t, pc, comp
        gas.equilibrate("TP")
        return gas.enthalpy_mass - h_target

    t_eq = brentq(residual, 500.0, 5000.0, xtol=1e-3)
    residual(t_eq)
    return t_eq, gas.mean_molecular_weight
