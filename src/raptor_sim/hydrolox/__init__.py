"""Hydrogen/oxygen engine model built on the methane (Raptor) toolchain.

thermo      CEA LOX/LH2 chemistry with a Cantera cross-check (same API as raptor_sim.thermo)
engine      sizing through raptor_sim.engine.size_engine, efficiencies fitted to RS-25
cycles      closed-expander and fuel-rich staged-combustion power balance
design      Optuna design iteration for the HL-44 lander and HL-250 tanker engines
gates       H1-H7 verification against RS-25, RL10, Vinci and BE-7
"""

from .design import HL_44, HL_250_EXP, HL_250_SC  # noqa: F401

# Values the lunar studies use. Pinned from results/hydrolox/design_points.json
# (scripts/run_hydrolox.py, 2026-11-01) so importing them needs no CEA run.
STUDY_ISP_S = {"HL-44": 460.2, "HL-250": 450.6}
STUDY_MR = {"HL-44": 6.39, "HL-250": 6.27}


def study_isp(engine: str = "HL-250") -> float:
    """Bias-corrected vacuum Isp (s) of a project hydrogen engine design point."""
    return STUDY_ISP_S[engine]
