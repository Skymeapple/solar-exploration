"""Hydrogen/oxygen combustion chemistry, same interface as `raptor_sim.thermo`.

NASA CEA (RocketCEA, fuel "LH2", oxidizer "LOX") is the primary source. Cantera
(GRI-Mech 3.0, which contains the full H/O system) is the independent
cross-check for gate H1. The functions match `raptor_sim.thermo`, so this module
can be passed as `chem=` to `raptor_sim.engine.size_engine`.
"""

from __future__ import annotations

from functools import lru_cache

from scipy.optimize import brentq

from ..constants import DH_LOX_J_PER_MOL, MW_O2
from ..thermo import ChamberGas

OXIDIZER = "LOX"
FUEL = "LH2"

# H2(L) at its 20.27 K boiling point minus H2 gas at 298.15 K, NASA CEA thermo
# library entry H2(L) (heat of formation -9,012 J/mol). [cited: CEA thermo.inp]
DH_LH2_J_PER_MOL = -9_012.0
MW_H2 = 0.00201588  # kg/mol


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
        viscosity_units="poise",
        thermal_cond_units="W/cm-degC",
    )


def chamber(pc: float, mixture_ratio: float) -> ChamberGas:
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
    cea = _cea()
    if p_ambient <= 0.0:
        return float(cea.get_Isp(Pc=pc, MR=mixture_ratio, eps=eps))
    isp, _mode = cea.estimate_Ambient_Isp(Pc=pc, MR=mixture_ratio, eps=eps, Pamb=p_ambient)
    return float(isp)


def exit_pressure(pc: float, mixture_ratio: float, eps: float) -> float:
    return pc / float(_cea().get_PcOvPe(Pc=pc, MR=mixture_ratio, eps=eps))


def throat_transport(pc: float, mixture_ratio: float) -> dict[str, float]:
    """Gas properties at the throat for the Bartz heat-transfer correlation (SI units)."""
    cp, visc_poise, _cond, pr = _cea().get_Throat_Transport(Pc=pc, MR=mixture_ratio, frozen=0)
    return {"cp": float(cp), "mu": float(visc_poise) * 0.1, "pr": float(pr)}


def cantera_chamber(pc: float, mixture_ratio: float) -> tuple[float, float]:
    """Independent equilibrium (T in K, MW in g/mol) from Cantera, liquids at their boiling points."""
    import cantera as ct

    gas = ct.Solution("gri30.yaml")
    y_ox = mixture_ratio / (1.0 + mixture_ratio)
    y_fuel = 1.0 - y_ox
    comp = {"O2": y_ox, "H2": y_fuel}
    gas.TPY = 298.15, pc, comp
    h_target = gas.enthalpy_mass + y_ox * DH_LOX_J_PER_MOL / MW_O2 + y_fuel * DH_LH2_J_PER_MOL / MW_H2

    def residual(t: float) -> float:
        gas.TPY = t, pc, comp
        gas.equilibrate("TP")
        return gas.enthalpy_mass - h_target

    t_eq = brentq(residual, 500.0, 5000.0, xtol=1e-3)
    residual(t_eq)
    return t_eq, gas.mean_molecular_weight
