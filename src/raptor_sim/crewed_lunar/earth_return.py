"""Earth return at lunar return speed, run on the crewed missions entry model.

Entry dynamics, heating and corridors come from raptor_sim.crew.entry (planar
3-DOF, Sutton-Graves convective plus Tauber-Sutton radiative heating). This
module only sets up the lunar cases: entry speed from legs.py, the two crew
vehicles, and the comparison with a LEO return so the change is visible.
"""

from __future__ import annotations

import math
from dataclasses import replace

from ..crew.entry import CAPSULE_ORION_CLASS, SHIP_STARSHIP_CLASS, entry_corridor, simulate_entry
from .legs import earth_entry_speed, leo_return_entry_speed
from .reference import EARTH_RETURN

# The direct crew ship of architecture C reaches Earth with 130 t dry, 1 t crew and
# samples and its 30 t landing reserve (all estimated in architecture.LunarAssumptions).
CREW_SHIP_LUNAR = replace(SHIP_STARSHIP_CLASS, name="Starship-class crew ship (lunar return)", mass=161_000.0)
G_LIMIT = 5.0  # g, crew limit used for the corridor (estimated, matches the crewed missions study)


def hold_down_guidance(t, h, v, gamma):
    """Simple bank law that prevents skip-out: lift up while diving, rolled over if the vehicle starts to climb.

    Real lunar-return guidance (Apollo, Orion) modulates bank to hit a landing
    point; this law only keeps the vehicle in the atmosphere so the loads are
    representative.
    """
    if gamma < math.radians(-0.5):
        return 0.0
    return 180.0 if gamma > 0 else 90.0


def _case(vehicle, v, gamma, bank=0.0):
    r = simulate_entry(vehicle, "earth", v, gamma, bank=bank)
    return {"gamma_deg": gamma, "peak_g": r.peak_g, "peak_conv_w_cm2": r.peak_convective / 1e4,
            "peak_rad_w_cm2": r.peak_radiative / 1e4, "peak_total_w_cm2": r.peak_heat_flux / 1e4,
            "heat_load_mj_m2": r.heat_load / 1e6, "skipped": r.skipped,
            "t": r.t[::20].tolist(), "h_km": (r.h[::20] / 1e3).tolist(), "g": r.g[::20].tolist()}


def earth_return_checks() -> dict:
    v_moon = earth_entry_speed()
    v_leo = leo_return_entry_speed()
    data = {"v_lunar": v_moon, "v_leo": v_leo, "cited_artemis2": EARTH_RETURN["artemis2_entry_speed"].value,
            "vehicles": {}}
    rows = []
    for veh in (CAPSULE_ORION_CLASS, CREW_SHIP_LUNAR):
        c = entry_corridor(veh, "earth", v_moon, G_LIMIT)
        mid = 0.5 * (c.shallow_deg + c.steep_deg) if c.width_deg > 0 else c.shallow_deg
        lunar = _case(veh, v_moon, mid, hold_down_guidance)
        leo = _case(veh, v_leo, -1.5)
        data["vehicles"][veh.name] = {"corridor": c.__dict__, "lunar": lunar, "leo": leo}
        rows.append(
            f"| {veh.name} | {c.shallow_deg:.2f} to {c.steep_deg:.2f} deg ({c.width_deg:.2f}) | "
            f"{lunar['peak_g']:.1f} g | {lunar['peak_conv_w_cm2']:,.0f} + {lunar['peak_rad_w_cm2']:,.0f} W/cm2 | "
            f"{lunar['heat_load_mj_m2']:,.0f} MJ/m2 | {leo['peak_total_w_cm2']:,.0f} W/cm2, {leo['heat_load_mj_m2']:,.0f} MJ/m2 |")
    md = [
        f"Entry speed from the Moon: {v_moon:,.0f} m/s computed, against about "
        f"{EARTH_RETURN['artemis2_entry_speed'].value:,.0f} m/s reported for Artemis II (cited). From LEO: {v_leo:,.0f} m/s.",
        "",
        f"Entry simulation from `raptor_sim.crew.entry` (mid-corridor flight path angle, lift up with a roll-over if it starts to climb, {G_LIMIT:.0f} g crew "
        "limit). LEO comparison: same vehicle, deorbit at -1.5 degrees.",
        "",
        "| Vehicle | Lunar-return corridor (width) | Peak g | Peak heat flux, convective + radiative | Heat load | LEO return for comparison |",
        "| --- | --- | --- | --- | --- | --- |",
        *rows,
        "",
        "Orion's Avcoat shield is designed for this; the Artemis I char-loss finding was handled on Artemis II by a "
        "steeper lofted entry instead of a long skip (cited). A Starship-class heat shield qualified only for LEO "
        "return would need new qualification for the higher heat flux and load before flying crew straight home.",
    ]
    return {"markdown": md, "data": data}
