"""Cislunar delta-v legs computed from patched conics.

These are the "computed" side of the budget. NRHO legs cannot be done with
patched conics (they are three-body orbits), so those come from cited NASA
values in reference.TRAJECTORY. Once raptor_sim.lunar_base.orbits exists, the
shared constants live there; the functions here are the independent check.
"""

from __future__ import annotations

import math

from ..mission import MU_EARTH, R_EARTH

MU_MOON = 4.9048695e12  # m^3/s^2
R_MOON = 1_737.4e3  # m, mean radius
A_MOON = 384_400e3  # m, mean Earth-Moon distance
V_MOON = math.sqrt(MU_EARTH / A_MOON)  # about 1,018 m/s, circular approximation
G_MOON = MU_MOON / R_MOON**2  # 1.62 m/s^2
ENTRY_INTERFACE = 122e3  # m, the conventional entry interface altitude


def circular_speed(mu: float, r: float) -> float:
    return math.sqrt(mu / r)


def tli_dv(leo_alt: float = 300e3) -> float:
    """Trans-lunar injection from a circular LEO: Hohmann ellipse to the Moon's distance."""
    r1 = R_EARTH + leo_alt
    a = 0.5 * (r1 + A_MOON)
    return math.sqrt(MU_EARTH * (2 / r1 - 1 / a)) - circular_speed(MU_EARTH, r1)


def tli_transfer_days(leo_alt: float = 300e3) -> float:
    a = 0.5 * (R_EARTH + leo_alt + A_MOON)
    return math.pi * math.sqrt(a**3 / MU_EARTH) / 86400


def arrival_vinf(leo_alt: float = 300e3) -> float:
    """Speed relative to the Moon on arrival from a Hohmann transfer (coplanar)."""
    r1 = R_EARTH + leo_alt
    a = 0.5 * (r1 + A_MOON)
    v_apogee = math.sqrt(MU_EARTH * (2 / A_MOON - 1 / a))
    return V_MOON - v_apogee


def lunar_orbit_insertion_dv(llo_alt: float = 100e3, leo_alt: float = 300e3) -> float:
    """Capture from the arrival hyperbola into a circular low lunar orbit (one burn)."""
    r = R_MOON + llo_alt
    vinf = arrival_vinf(leo_alt)
    return math.sqrt(vinf**2 + 2 * MU_MOON / r) - circular_speed(MU_MOON, r)


def descent_orbit_insertion_dv(llo_alt: float = 100e3, perilune_alt: float = 15.24e3) -> float:
    """Lower perilune from a circular LLO to the powered descent start."""
    r_a = R_MOON + llo_alt
    r_p = R_MOON + perilune_alt
    a = 0.5 * (r_a + r_p)
    return circular_speed(MU_MOON, r_a) - math.sqrt(MU_MOON * (2 / r_a - 1 / a))


def perilune_speed(llo_alt: float = 100e3, perilune_alt: float = 15.24e3) -> float:
    r_a = R_MOON + llo_alt
    r_p = R_MOON + perilune_alt
    a = 0.5 * (r_a + r_p)
    return math.sqrt(MU_MOON * (2 / r_p - 1 / a))


def earth_entry_speed(entry_alt: float = ENTRY_INTERFACE) -> float:
    """Inertial speed at entry interface for a return from the Moon's distance.

    Energy of an ellipse with apogee at the Moon and perigee at the entry
    interface; the Moon's own pull on departure adds a few m/s and is ignored.
    """
    r = R_EARTH + entry_alt
    a = 0.5 * (r + A_MOON)
    return math.sqrt(MU_EARTH * (2 / r - 1 / a))


def leo_return_entry_speed(leo_alt: float = 300e3, entry_alt: float = ENTRY_INTERFACE) -> float:
    """Entry speed for a deorbit from LEO, for comparison (about 7.8 km/s)."""
    r1 = R_EARTH + leo_alt
    r = R_EARTH + entry_alt
    a = 0.5 * (r1 + r)
    return math.sqrt(MU_EARTH * (2 / r - 1 / a))
