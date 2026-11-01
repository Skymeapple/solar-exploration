"""Physical data for the Sun, planets and small bodies used by the sample return models.

Gravitational parameters and radii are standard IAU/JPL values [memory].
Planetary mean elements are the J2000 values and mean-longitude rates from JPL's
"Approximate Positions of the Planets" table (valid 1800-2050) [memory]. Only the
mean longitude is propagated; the other elements are held at J2000, which gives
positions good to a few thousand km, ample for launch-window studies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

AU = 1.495978707e11  # m
DAY = 86_400.0  # s
G0 = 9.80665  # m/s^2
MU_SUN = 1.32712440018e20  # m^3/s^2


@dataclass(frozen=True)
class Body:
    name: str
    mu: float  # m^3/s^2
    radius: float  # m (mean)
    rotation_period: float | None = None  # s, sidereal; None for small bodies
    # Exponential atmosphere near the surface (0 for none)
    rho0: float = 0.0  # kg/m^3
    scale_height: float = 0.0  # m
    sma_au: float | None = None  # heliocentric semi-major axis, for comparisons

    @property
    def surface_gravity(self) -> float:
        return self.mu / self.radius**2

    @property
    def escape_speed(self) -> float:
        return math.sqrt(2 * self.mu / self.radius)

    def circular_speed(self, altitude: float) -> float:
        return math.sqrt(self.mu / (self.radius + altitude))

    @property
    def rotation_rate(self) -> float:
        return 0.0 if not self.rotation_period else 2 * math.pi / self.rotation_period


EARTH = Body("Earth", 3.986004418e14, 6.371e6, 86_164.1, 1.225, 7_200.0, 1.0)
MOON = Body("Moon", 4.9028e12, 1.7374e6, 2_360_591.5, sma_au=1.0)
# Mars surface density and scale height: mean near-surface values [memory]
MARS = Body("Mars", 4.282837e13, 3.3895e6, 88_642.66, 0.020, 11_100.0, 1.523679)
PHOBOS = Body("Phobos", 7.087e5, 11.08e3, sma_au=1.523679)
# Bennu: GM 4.89 m^3/s^2, mean radius 245 m [memory] (OSIRIS-REx results)
BENNU = Body("Bennu", 4.89, 245.0, sma_au=1.126)
# Comet 67P: mass 1.0e13 kg, mean radius ~2 km [memory] (Rosetta results)
COMET_67P = Body("67P/C-G", 6.67430e-11 * 1.0e13, 2.0e3, sma_au=3.46)
EUROPA = Body("Europa", 3.2027e12, 1.5608e6, sma_au=5.2038)
ENCELADUS = Body("Enceladus", 7.211e9, 252.1e3, sma_au=9.5826)
JUPITER = Body("Jupiter", 1.26686534e17, 6.9911e7, sma_au=5.2038)
SATURN = Body("Saturn", 3.7931187e16, 5.8232e7, sma_au=9.5826)


@dataclass(frozen=True)
class MeanElements:
    """J2000 mean elements: a [AU], e, i, L, varpi, Omega [deg], L rate [deg/century]."""

    a: float
    e: float
    i: float
    L: float
    varpi: float
    Omega: float
    L_rate: float


# JPL approximate elements, J2000 epoch [memory]
ELEMENTS = {
    "Earth": MeanElements(1.00000261, 0.01671123, -0.00001531, 100.46457166, 102.93768193, 0.0, 35999.37244981),
    "Mars": MeanElements(1.52371034, 0.09339410, 1.84969142, -4.55343205, -23.94362959, 49.55953891, 19140.30268499),
}

J2000_JD = 2_451_545.0


def jd_from_date(year: int, month: int, day: float) -> float:
    """Julian date (TDB ~ UTC here) for a Gregorian calendar date at 0h + fractional day."""
    if month <= 2:
        year -= 1
        month += 12
    a = year // 100
    b = 2 - a + a // 4
    return int(365.25 * (year + 4716)) + int(30.6001 * (month + 1)) + day + b - 1524.5


def date_from_jd(jd: float) -> str:
    """ISO date string (YYYY-MM-DD) for a Julian date."""
    jd += 0.5
    z = int(jd)
    f = jd - z
    alpha = int((z - 1_867_216.25) / 36_524.25)
    a = z + 1 + alpha - alpha // 4
    b = a + 1524
    c = int((b - 122.1) / 365.25)
    d = int(365.25 * c)
    e = int((b - d) / 30.6001)
    day = b - d - int(30.6001 * e) + f
    month = e - 1 if e < 14 else e - 13
    year = c - 4716 if month > 2 else c - 4715
    return f"{year:04d}-{month:02d}-{int(day):02d}"


def _solve_kepler(M: float, e: float) -> float:
    E = M if e < 0.8 else math.pi
    for _ in range(50):
        dE = (E - e * math.sin(E) - M) / (1 - e * math.cos(E))
        E -= dE
        if abs(dE) < 1e-14:
            break
    return E


def planet_state(name: str, jd: float) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Heliocentric ecliptic position (m) and velocity (m/s) of a planet at Julian date jd."""
    el = ELEMENTS[name]
    T = (jd - J2000_JD) / 36_525.0
    a = el.a * AU
    e = el.e
    i = math.radians(el.i)
    L = math.radians(el.L + el.L_rate * T)
    varpi = math.radians(el.varpi)
    Om = math.radians(el.Omega)
    w = varpi - Om
    M = (L - varpi) % (2 * math.pi)
    E = _solve_kepler(M, e)
    # Perifocal position and velocity
    n = math.sqrt(MU_SUN / a**3)
    cosE, sinE = math.cos(E), math.sin(E)
    r = a * (1 - e * cosE)
    xp = a * (cosE - e)
    yp = a * math.sqrt(1 - e * e) * sinE
    vxp = -a * n * sinE / (1 - e * cosE)
    vyp = a * n * math.sqrt(1 - e * e) * cosE / (1 - e * cosE)
    del r
    cw, sw, cO, sO, ci, si = math.cos(w), math.sin(w), math.cos(Om), math.sin(Om), math.cos(i), math.sin(i)
    R = (
        (cO * cw - sO * sw * ci, -cO * sw - sO * cw * ci),
        (sO * cw + cO * sw * ci, -sO * sw + cO * cw * ci),
        (sw * si, cw * si),
    )
    pos = tuple(R[k][0] * xp + R[k][1] * yp for k in range(3))
    vel = tuple(R[k][0] * vxp + R[k][1] * vyp for k in range(3))
    return pos, vel  # type: ignore[return-value]
