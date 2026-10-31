"""Raptor-class CH4/LOX full-flow staged combustion engine model.

Implements the L0/L1 levels of the project's design and verification
procedure: combustion chemistry, thrust chamber and nozzle performance,
and the full-flow cycle power balance, each checked by a gate.
"""

from .engine import EngineDesign, EnginePerformance, size_engine
from .cycle import CycleAssumptions, CycleResult, solve_cycle
from .gates import GateResult, run_all_gates

__all__ = [
    "EngineDesign",
    "EnginePerformance",
    "size_engine",
    "CycleAssumptions",
    "CycleResult",
    "solve_cycle",
    "GateResult",
    "run_all_gates",
]
