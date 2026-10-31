"""Public Raptor figures used by gate G7.

SpaceX publishes very little, so these come from secondary sources and carry
uncertainty. Values checked on 2026-10-31.

Sources:
  [W] https://en.wikipedia.org/wiki/SpaceX_Raptor
  [E] https://everydayastronaut.com/spacex-raptor-engine-comparison/
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Benchmark:
    name: str
    value: float
    unit: str
    confidence: str  # "medium" values are calibration targets, "low" are sanity checks only
    source: str


RAPTOR_2_SEA_LEVEL: dict[str, Benchmark] = {
    "thrust_sl": Benchmark("Sea-level thrust", 2.256e6, "N", "medium", "230 tf [W][E]"),
    "isp_sl": Benchmark("Sea-level specific impulse", 327.0, "s", "medium", "[W][E]"),
    "isp_vac": Benchmark("Vacuum specific impulse, sea-level nozzle", 347.0, "s", "medium", "[W]"),
    "pc": Benchmark("Main chamber pressure", 300e5, "Pa", "medium", "[W][E]"),
    "mixture_ratio": Benchmark("Mixture ratio O/F", 3.6, "-", "low", "[W]; [W] also quotes about 3.8"),
    "eps": Benchmark("Nozzle area ratio", 34.34, "-", "low", "[W], version not stated"),
    "mdot": Benchmark("Total propellant flow", 650.0, "kg/s", "low", "[W], version not stated"),
    "mass": Benchmark("Engine dry mass", 1630.0, "kg", "low", "[W]; [E] gives 1,600"),
}

# G7 compares only these, at 5% tolerance.
G7_KEYS = ("thrust_sl", "isp_sl", "isp_vac", "pc")
G7_TOLERANCE = 0.05
