"""Save and load the component design point as JSON, so the converged design can be
rebuilt without re-running the iteration (which takes several minutes)."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from ..cycle import CycleAssumptions
from ..engine import EngineDesign
from .assembly import ComponentInputs
from .chamber import ChamberInputs
from .cooling import CoolingInputs
from .feed import FeedInputs
from .injector import InjectorInputs
from .preburner import PreburnerInputs
from .turbopump import TurbopumpInputs

DESIGN_POINT = Path(__file__).with_name("design_point.json")
_GROUPS = {
    "engine": EngineDesign, "cycle": CycleAssumptions, "chamber": ChamberInputs, "cooling": CoolingInputs,
    "injector": InjectorInputs, "turbopump": TurbopumpInputs, "preburner": PreburnerInputs, "feed": FeedInputs,
}


def save(ci: ComponentInputs, path: Path = DESIGN_POINT) -> None:
    path.write_text(json.dumps(dataclasses.asdict(ci), indent=2, sort_keys=True) + "\n")


def load(path: Path = DESIGN_POINT) -> ComponentInputs:
    raw = json.loads(path.read_text())
    kw = {}
    for key, value in raw.items():
        kw[key] = _GROUPS[key](**value) if key in _GROUPS else value
    return ComponentInputs(**kw)
