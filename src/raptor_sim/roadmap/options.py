"""Schedule acceleration options, each a change to the catalog, compared by Monte Carlo.

The baseline Mars chain needs three windows in a row before a crew can fly:
first cargo lands, then the ISRU plant goes out, then the plant proves a full
ship load. Each option below breaks one link; the recommended plan is the set
that buys the most schedule for the risk it adds.
"""
from __future__ import annotations

from dataclasses import replace

from .catalog import STEPS, Step


def _edit(steps: list[Step], sid: str, **kw) -> list[Step]:
    return [replace(s, **kw) if s.id == sid else s for s in steps]


def isru_with_first_cargo(steps: list[Step]) -> list[Step]:
    """Send the ISRU pilot in the same window as the first cargo ships.
    Risk: it lands before Mars entry is proven, so its landing odds drop to the cargo ship's."""
    steps = _edit(steps, "MARS-CARGO-2", needs=("isru_plant", "mars_power", "prop_transfer", "cadence",
                                                "hypersonic_edl", "depot"), p_success=0.75)
    return steps


def no_depot_first_cargo(steps: list[Step]) -> list[Step]:
    """Refill the first Mars ships tanker by tanker, without a depot; boil-off is taken in the ship.
    Applies to every ship in the first-cargo window, including an ISRU pilot flying with it."""
    out = []
    for s in steps:
        if s.id in ("MARS-CARGO-1", "MARS-CARGO-2"):
            s = replace(s, needs=tuple(c for c in s.needs if c != "depot"))
        out.append(s)
    return out


def second_engine_stand(steps: list[Step]) -> list[Step]:
    """Build a second engine test stand and a parallel hardware line: 20% faster, 20% dearer,
    and the rework after a failed test is shorter because two units are on test."""
    out = []
    for s in steps:
        if s.id in ("ENG-DEV", "VAC-ENG"):
            s = replace(s, dur=tuple(d * 0.8 for d in s.dur), cost=tuple(c * 1.2 for c in s.cost))
        out.append(s)
    return out


def crew_on_partial_isru(steps: list[Step]) -> list[Step]:
    """Launch the crew once the plant has landed and is producing, before a full load is made.
    The plant then has the crew's 26-month trip plus stay to finish; a shortfall strands the crew,
    so this one is shown for comparison and not recommended."""
    return _edit(steps, "MARS-CREW-1", needs=("crew_long_duration", "rad_protection", "isru_delivered",
                                              "deep_space_crew", "mars_landing"))


def nuclear_crew_transit(steps: list[Step]) -> list[Step]:
    """Make nuclear electric propulsion a gate for the first crew (PR #5: only a 10 MWe NEP ship keeps
    a Mars mission under 600 mSv). NEP development starts now instead of after the lunar reactor."""
    steps = _edit(steps, "NUC-PROP", needs=(), phase="P1")
    for s in steps:
        if s.id == "MARS-CREW-1":
            steps = _edit(steps, "MARS-CREW-1", needs=s.needs + ("nuclear_propulsion",))
    return steps


OPTIONS = {
    "isru_with_first_cargo": ("ISRU pilot flies with the first cargo", isru_with_first_cargo),
    "no_depot_first_cargo": ("First Mars cargo refilled without a depot", no_depot_first_cargo),
    "second_engine_stand": ("Second engine test stand", second_engine_stand),
    "crew_on_partial_isru": ("Crew launches before ISRU makes a full load", crew_on_partial_isru),
    "nuclear_crew_transit": ("Crew waits for nuclear electric propulsion (radiation limit)", nuclear_crew_transit),
}
RECOMMENDED = ("isru_with_first_cargo", "no_depot_first_cargo", "second_engine_stand", "nuclear_crew_transit")


def apply(keys, steps: list[Step] | None = None) -> list[Step]:
    steps = list(steps or STEPS)
    for k in keys:
        steps = OPTIONS[k][1](steps)
    return steps
