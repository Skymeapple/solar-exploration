"""Earth-Moon delta-v legs and departures to Mars from the Earth-Moon system.

This is the shared set of lunar delta-v values for the project. The crewed
lunar missions work (``raptor_sim.crewed_lunar``) imports from here, so change
values here only, and keep each one tagged with where it came from.

Legs between the lunar surface and low lunar orbit come from the integrated
powered descent and ascent simulation in ``raptor_sim.crewed_lunar.landing``
(PR #10). That simulation shows one Raptor cannot hover at touchdown, so the
final ~150 m is flown on landing thrusters.

Departures to Mars from a high orbit (NRHO or Earth-Moon L1) use a two-burn
patched-conic sequence: a small burn drops perigee to 300 km altitude, then a
perigee burn (Oberth effect) reaches the Mars hyperbolic excess speed. The
lunar gravity assist that real trajectories use is ignored, which is
conservative by roughly 100 to 200 m/s.
"""

from __future__ import annotations

import math

from ..mission import MU_EARTH, R_EARTH, burn_from_orbit, hohmann_vinf
from .provenance import Value

MU_MOON = 4.9048695e12  # m^3/s^2
R_MOON = 1.7374e6  # m, mean radius
A_MOON = 3.844e8  # m, mean Earth-Moon distance
G_MOON = MU_MOON / R_MOON**2  # 1.625 m/s^2
OMEGA_MOON = math.sqrt((MU_EARTH + MU_MOON) / A_MOON**3)  # rad/s
R_EML1 = 3.2605e8  # m, Earth-Moon L1 distance from Earth's centre
LEO_ALT = 300e3  # m, same as mission.MissionAssumptions
LLO_ALT = 100e3  # m

NTRS_HLS = "NASA HLS STRIVES paper, NTRS 20230002566"
CREWED_LUNAR = "integrated descent/ascent sim, raptor_sim.crewed_lunar.landing (PR #10)"
NASA_NRHO = "NASA NRHO overview https://www.nasa.gov/wp-content/uploads/2023/10/nrho-artemis-orbit.pdf"


def tli_from_leo(alt: float = LEO_ALT) -> float:
    """Trans-lunar injection from a circular LEO: apogee raised to the Moon's distance."""
    r = R_EARTH + alt
    a = 0.5 * (r + A_MOON)
    return math.sqrt(MU_EARTH * (2 / r - 1 / a)) - math.sqrt(MU_EARTH / r)


def llo_capture(alt: float = LLO_ALT) -> float:
    """Capture into circular LLO from a Hohmann-type TLI arrival (patched conic)."""
    r = R_EARTH + LEO_ALT
    a = 0.5 * (r + A_MOON)
    v_apo = math.sqrt(MU_EARTH * (2 / A_MOON - 1 / a))
    v_moon = OMEGA_MOON * A_MOON
    vinf = v_moon - v_apo
    rl = R_MOON + alt
    return math.sqrt(vinf**2 + 2 * MU_MOON / rl) - math.sqrt(MU_MOON / rl)


def _perigee_drop_from_circular(r_high: float, v_high: float, rp: float) -> float:
    """Burn at r_high (moving at v_high) that sets perigee to rp."""
    v_apo = math.sqrt(2 * MU_EARTH * rp / (r_high * (r_high + rp)))
    return abs(v_high - v_apo)


def _perigee_speed(r_high: float, rp: float) -> float:
    return math.sqrt(2 * MU_EARTH * r_high / (rp * (r_high + rp)))


def departure_from_high_orbit(vinf: float, r_high: float, drop_dv: float | None = None) -> tuple[float, float]:
    """(drop burn, perigee burn) in m/s to leave from a high orbit with excess speed vinf.

    If drop_dv is None, the drop burn is computed for a body co-moving with the Moon
    at radius r_high (true for EML1). For NRHO pass the cited departure burn.
    """
    rp = R_EARTH + LEO_ALT
    if drop_dv is None:
        drop_dv = _perigee_drop_from_circular(r_high, OMEGA_MOON * r_high, rp)
    vp = _perigee_speed(r_high, rp)
    perigee = math.sqrt(vinf**2 + 2 * MU_EARTH / rp) - vp
    return drop_dv, perigee


def lunar_surface_to_earth_perigee() -> float:
    """Leaving LLO onto an Earth-return ellipse with perigee at 300 km (computed)."""
    rp = R_EARTH + LEO_ALT
    v_apo = math.sqrt(2 * MU_EARTH * rp / (A_MOON * (A_MOON + rp)))
    vinf_moon = OMEGA_MOON * A_MOON - v_apo
    rl = R_MOON + LLO_ALT
    return math.sqrt(vinf_moon**2 + 2 * MU_MOON / rl) - math.sqrt(MU_MOON / rl)


def mars_vinf() -> float:
    return hohmann_vinf()[0]


# The shared table. Keys are "from->to".
LEGS: dict[str, Value] = {
    "LEO->TLI": Value(round(tli_from_leo()), "m/s", "computed", "patched conic, 300 km LEO to Moon distance"),
    "TLI->NRHO": Value(500.0, "m/s", "estimated", f"half of the cited 1,000 m/s NRHO insertion plus departure, {NASA_NRHO}"),
    "NRHO->TEI": Value(500.0, "m/s", "estimated", f"half of the cited 1,000 m/s NRHO insertion plus departure, {NASA_NRHO}"),
    "NRHO->LLO": Value(705.0, "m/s", "cited", NTRS_HLS),
    "LLO->NRHO": Value(705.0, "m/s", "cited", NTRS_HLS),
    "TLI->LLO": Value(round(llo_capture()), "m/s", "computed", "patched conic capture into 100 km LLO"),
    "LLO->surface": Value(1_960.0, "m/s", "computed", CREWED_LUNAR + ": 120 t-dry lander, braking on one Raptor plus terminal, no margin"),
    "surface->LLO": Value(1_830.0, "m/s", "computed", CREWED_LUNAR + ": ascent to LLO, no margin"),
    "surface->NRHO (NASA)": Value(2_610.0, "m/s", "cited", NASA_NRHO + " (ascent)"),
    "LLO->Earth perigee": Value(round(lunar_surface_to_earth_perigee()), "m/s", "computed", "patched conic"),
    "EML1->surface": Value(2_520.0, "m/s", "estimated", "commonly quoted EML1 to lunar surface value, about 2.5 km/s"),
    "surface->EML1": Value(2_520.0, "m/s", "estimated", "symmetric to EML1->surface"),
    "LEO->EML1": Value(3_770.0, "m/s", "estimated", "commonly quoted LEO to EML1 value, about 3.77 km/s"),
}


def leg(key: str) -> float:
    return LEGS[key].value


def surface_to_nrho() -> float:
    return leg("surface->LLO") + leg("LLO->NRHO")


def nrho_to_surface() -> float:
    return leg("NRHO->LLO") + leg("LLO->surface")


def mars_departure(origin: str, margin: float = 1.10) -> float:
    """Delta-v (m/s) to depart for Mars (minimum-energy v-infinity) from an origin.

    origin: "LEO", "EML1", "NRHO" or "LLO". The same 10% margin as the Mars study in
    ``raptor_sim.mission`` covers non-Hohmann windows and finite burns.
    """
    vinf = mars_vinf()
    if origin == "LEO":
        return margin * burn_from_orbit(vinf, MU_EARTH, R_EARTH + LEO_ALT)
    if origin == "EML1":
        a, b = departure_from_high_orbit(vinf, R_EML1)
        return margin * (a + b)
    if origin == "NRHO":
        a, b = departure_from_high_orbit(vinf, A_MOON, drop_dv=leg("NRHO->TEI"))
        return margin * (a + b)
    if origin == "LLO":
        a, b = departure_from_high_orbit(vinf, A_MOON, drop_dv=leg("LLO->Earth perigee"))
        return margin * (a + b)
    raise ValueError(origin)
