"""Engine and vehicle data used by the campaign simulations.

Every number carries a tag:
  [public]  published by SpaceX or in the sources listed in benchmarks.py
  [model]   computed by this repository's engine model (PR #1)
  [comp]    from the component-level design (PR #2, design_data.json, 2026-10-31)
  [est]     engineering estimate made for this study, to be replaced by better data
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path

from ..constants import G0

# PR #2 component design outputs (results/components/design_data.json). Snapshot updated
# 2026-10-31 after PR #2 moved its design point to 295 bar: 1,935 kg, about 324 s sea level
# and 347 s vacuum (sea-level nozzle).
COMPONENT_DESIGN_FILE = Path(__file__).resolve().parents[3] / "results" / "components" / "design_data.json"
COMPONENT_DEFAULTS = {
    "mass_kg": 1935.0,  # [comp] 19% over the public 1,630 kg
    "isp_sl_loss_s": 326.67 - 324.0,  # [comp] Isp lost to fuel film cooling and the lower chamber pressure
    "isp_vac_loss_s": 348.02 - 347.0,  # [comp]
}


def component_inputs() -> dict[str, float]:
    """Engine mass and film-cooling loss from PR #2 if its results are present, else the snapshot."""
    try:
        d = json.loads(COMPONENT_DESIGN_FILE.read_text())
        p = d["performance"]
        return {
            "mass_kg": float(d["mass_kg"]),
            "isp_sl_loss_s": p["isp_sl_s"] - p["isp_sl_after_film_s"],
            "isp_vac_loss_s": p["isp_vac_s"] - p["isp_vac_after_film_s"],
        }
    except (OSError, KeyError, ValueError):
        return dict(COMPONENT_DEFAULTS)


@dataclass(frozen=True)
class EngineData:
    thrust_vac: float  # N, sea-level nozzle in vacuum
    isp_vac: float  # s, sea-level nozzle in vacuum
    exit_area: float  # m^2, sea-level nozzle
    rvac_thrust: float  # N, vacuum engine
    rvac_isp: float  # s
    mass: float  # kg per engine
    min_throttle: float = 0.40  # [est] Raptor deep throttle is quoted near 40% [public, low confidence]

    @property
    def mdot(self) -> float:
        return self.thrust_vac / (self.isp_vac * G0)

    def thrust(self, p_ambient: float) -> float:
        return self.thrust_vac - p_ambient * self.exit_area

    def scaled(self, isp_factor: float = 1.0, thrust_factor: float = 1.0) -> "EngineData":
        return replace(
            self,
            thrust_vac=self.thrust_vac * thrust_factor * isp_factor,
            isp_vac=self.isp_vac * isp_factor,
            exit_area=self.exit_area,
            rvac_thrust=self.rvac_thrust * thrust_factor * isp_factor,
            rvac_isp=self.rvac_isp * isp_factor,
        )


@lru_cache(maxsize=4)
def engine_from_model(rvac_isp_override: float | None = None) -> EngineData:
    """Build EngineData from the PR #1 engine model plus the PR #2 component results."""
    from ..engine import EngineDesign, size_engine

    d = EngineDesign()
    sl = size_engine(d)
    vac = size_engine(replace(d, eps=80.0), p_ambient=0.0)
    comp = component_inputs()
    isp_vac = sl.isp_vac - comp["isp_vac_loss_s"]
    rvac_isp = rvac_isp_override or (vac.isp_vac - comp["isp_vac_loss_s"])
    exit_area = math.pi * sl.exit_diameter**2 / 4
    return EngineData(
        thrust_vac=sl.mdot * isp_vac * G0,
        isp_vac=isp_vac,
        exit_area=exit_area,
        rvac_thrust=sl.mdot * rvac_isp * G0,
        rvac_isp=rvac_isp,
        mass=comp["mass_kg"],
    )


PUBLIC_ENGINE_MASS = 1630.0  # kg [public, low confidence]


@dataclass(frozen=True)
class Stack:
    """Two-stage Starship-class stack. Masses in kg."""

    booster_propellant: float = 3_650e3  # [public] Block 3
    booster_dry_base: float = 275e3  # [public] includes 33 engines at the public engine mass
    booster_engines: int = 33  # [public]
    booster_landing_engines: int = 3  # [public] centre engines for the landing burn
    booster_boostback_engines: int = 13  # [public] inner ring
    booster_reserve_fraction: float = 0.08  # [est] propellant kept for boostback and landing
    booster_cd_descent: float = 1.0  # [est] tail-first with grid fins
    ship_propellant: float = 1_600e3  # [public]
    ship_dry_base: float = 100e3  # [public] Block 1 figure; Block 3 not published
    ship_dry_growth: float = 0.0  # kg added by the iteration loop if mass grows
    ship_sl_engines: int = 4  # design change (campaign risk R7): public ship has 3; a 4th lets the ship land with one out
    ship_ablator_mass: float = 6e3  # kg, design change (campaign R9): ablative windward heat shield for 12.3 km/s Earth return [est]
    ship_vac_engines: int = 3  # [public]
    diameter: float = 9.0  # m [public]
    stack_length: float = 124.0  # m [public] Block 3, approximate
    max_axial_g: float = 4.0  # [est] ship throttles to hold this
    q_limit_throttle: float = 0.0  # Pa; >0 means throttle the booster to hold dynamic pressure
    engine: EngineData = field(default_factory=engine_from_model)

    @property
    def area(self) -> float:
        return math.pi * self.diameter**2 / 4

    def _engine_mass_delta(self) -> float:
        return self.engine.mass - PUBLIC_ENGINE_MASS

    @property
    def booster_dry(self) -> float:
        return self.booster_dry_base + self.booster_engines * self._engine_mass_delta()

    @property
    def ship_dry(self) -> float:
        n = self.ship_sl_engines + self.ship_vac_engines
        # The public dry mass includes 3 + 3 engines; engines beyond that add a whole engine.
        added_engines = max(self.ship_sl_engines - 3, 0) + max(self.ship_vac_engines - 3, 0)
        return (self.ship_dry_base + added_engines * PUBLIC_ENGINE_MASS + n * self._engine_mass_delta()
                + self.ship_ablator_mass + self.ship_dry_growth)


def ascent_cd(mach: float) -> float:
    """Drag coefficient of the stacked vehicle, nose first, at zero angle of attack. [est]

    Shape typical of slender launch vehicles (Saturn V and Falcon 9 wind-tunnel
    trends): about 0.3 subsonic, a transonic peak near 0.55, falling to 0.25.
    """
    table = [(0.0, 0.30), (0.8, 0.33), (1.05, 0.55), (1.3, 0.50), (2.0, 0.40), (3.0, 0.32), (5.0, 0.26), (10.0, 0.25)]
    if mach >= table[-1][0]:
        return table[-1][1]
    for (m0, c0), (m1, c1) in zip(table, table[1:]):
        if mach < m1:
            return c0 + (c1 - c0) * (mach - m0) / (m1 - m0)
    return table[-1][1]
