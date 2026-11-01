"""Hydrogen/oxygen thrust chamber performance, reusing the methane engine sizing.

`raptor_sim.engine.size_engine` does the sizing; this module only supplies the
hydrogen chemistry and hydrogen-specific efficiencies.

Efficiency calibration: the methane engine's eta_cstar * eta_cf = 0.946 (fitted
to Raptor 2) under-predicts hydrogen engines by 2-3% (RS-25 437.8 s vs 452.3 s),
so it does not transfer. Hydrogen burns faster and more completely, and large
hydrogen engines report c* efficiencies near 0.99. We keep eta_cstar = 0.99 [est]
and fit eta_cf to RS-25 vacuum Isp alone; every other engine is a prediction.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..constants import P_SEA_LEVEL
from ..engine import EngineDesign, EnginePerformance, size_engine
from . import thermo
from .benchmarks import RS_25, RefEngine

ETA_CSTAR = 0.99  # [est]


def _fit_eta_cf() -> float:
    ideal = thermo.ideal_isp(RS_25.pc, RS_25.mixture_ratio, RS_25.eps)
    return RS_25.isp_vac / (ETA_CSTAR * ideal)


_ETA_CF: float | None = None


def eta_cf() -> float:
    global _ETA_CF
    if _ETA_CF is None:
        _ETA_CF = _fit_eta_cf()
    return _ETA_CF


def design(pc: float, mixture_ratio: float, eps: float, thrust: float) -> EngineDesign:
    """An EngineDesign with hydrogen efficiencies. `thrust` is the thrust at the sizing ambient pressure."""
    return EngineDesign(pc=pc, mixture_ratio=mixture_ratio, eps=eps, thrust_sl=thrust, eta_cstar=ETA_CSTAR, eta_cf=eta_cf())


def size(d: EngineDesign, p_ambient: float = 0.0) -> EnginePerformance:
    """Size a hydrogen engine. p_ambient = 0 sizes a vacuum engine on its vacuum thrust."""
    return size_engine(d, p_ambient=p_ambient, chem=thermo)


def reference_design(ref: RefEngine) -> EngineDesign:
    return design(ref.pc, ref.mixture_ratio, ref.eps, ref.thrust_vac)


def sea_level_isp(perf: EnginePerformance) -> float:
    """Sea-level Isp of an engine sized in vacuum (same throat, ambient back-pressure on the exit)."""
    from ..constants import G0

    return perf.isp_vac - P_SEA_LEVEL * perf.design.eps * perf.cstar / (perf.design.pc * G0)


def with_thrust(d: EngineDesign, thrust: float) -> EngineDesign:
    return replace(d, thrust_sl=thrust)


def expander_isp_bias() -> float:
    """Mean fractional over-prediction of vacuum Isp across the flown expander engines.

    The RS-25 calibration carries over to the expanders with a +1.0% to +2.7%
    bias (their small, long nozzles lose more to boundary layers). Design points
    report a bias-corrected Isp so the lunar studies do not inherit it.
    """
    from .benchmarks import ALL

    errs = [size(reference_design(r)).isp_vac / r.isp_vac - 1 for r in ALL if r.cycle == "expander"]
    return sum(errs) / len(errs)
