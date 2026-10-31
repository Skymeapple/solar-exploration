"""Thrust chamber and nozzle contour (combustion chamber, throat, bell nozzle).

The contour follows the usual liquid-engine layout (Huzel & Huang, "Modern
Engineering for Design of Liquid-Propellant Rocket Engines", ch. 4):

* a cylindrical chamber sized from the characteristic length L*,
* a conical convergent section with an upstream throat arc of 1.5 Rt,
* a downstream throat arc of 0.382 Rt,
* a Rao thrust-optimized parabolic bell at 80% of the 15 degree cone length.

Axial coordinate x is zero at the throat and negative upstream.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cached_property

import numpy as np

from ..engine import EnginePerformance

# Rao bell angles for an 80% length bell, read from Huzel & Huang fig. 4-16
# (accuracy about +-1 degree). Columns: area ratio, initial angle, exit angle.
_RAO_80 = np.array(
    [
        [4.0, 21.5, 14.0],
        [5.0, 23.0, 13.0],
        [10.0, 26.3, 11.0],
        [20.0, 28.8, 9.0],
        [30.0, 30.0, 8.5],
        [40.0, 31.0, 8.0],
        [50.0, 31.5, 7.5],
        [100.0, 33.5, 7.0],
    ]
)


@dataclass(frozen=True)
class ChamberInputs:
    """Choices for the chamber shape. Values are design choices, not Raptor data."""

    l_star: float = 0.90  # m; gas-gas injection mixes fast, so the low end of the 0.8-1.3 m CH4/LOX range
    contraction_ratio: float = 3.5  # chamber area / throat area
    convergent_half_angle_deg: float = 30.0
    upstream_throat_arc: float = 1.5  # times Rt
    downstream_throat_arc: float = 0.382  # times Rt
    chamber_wall_arc: float = 1.0  # times Rt, rounds the cylinder-to-cone corner
    bell_fraction: float = 0.80


@dataclass(frozen=True)
class Contour:
    perf: EnginePerformance
    inputs: ChamberInputs

    # --- basic radii and lengths -------------------------------------------------
    @property
    def rt(self) -> float:
        return self.perf.throat_diameter / 2.0

    @property
    def rc(self) -> float:
        return self.rt * math.sqrt(self.inputs.contraction_ratio)

    @property
    def re(self) -> float:
        return self.rt * math.sqrt(self.perf.design.eps)

    @property
    def bell_angles_deg(self) -> tuple[float, float]:
        eps = self.perf.design.eps
        return (
            float(np.interp(eps, _RAO_80[:, 0], _RAO_80[:, 1])),
            float(np.interp(eps, _RAO_80[:, 0], _RAO_80[:, 2])),
        )

    @property
    def nozzle_length(self) -> float:
        """Throat to exit plane."""
        eps = self.perf.design.eps
        cone = (math.sqrt(eps) - 1.0) * self.rt / math.tan(math.radians(15.0))
        return self.inputs.bell_fraction * cone

    @property
    def chamber_volume_required(self) -> float:
        """Volume upstream of the throat from L* = Vc / At."""
        return self.inputs.l_star * math.pi * self.rt**2

    # --- contour -----------------------------------------------------------------
    def _convergent(self, n: int) -> tuple[np.ndarray, np.ndarray]:
        """Throat upstream arc, cone and chamber corner arc, running upstream from the throat."""
        i = self.inputs
        rt, rc = self.rt, self.rc
        th = math.radians(i.convergent_half_angle_deg)
        r1 = i.upstream_throat_arc * rt
        r2 = i.chamber_wall_arc * rt

        # Upstream throat arc, centre (0, rt + r1), from the throat to the cone tangent point P1.
        a = np.linspace(0.0, th, n)
        x1 = -r1 * np.sin(a)
        y1 = rt + r1 * (1.0 - np.cos(a))
        p1x, p1r = float(x1[-1]), float(y1[-1])
        # Corner arc, radius r2, tangent to the cylinder r = rc and to the cone at P2.
        p2r = rc - r2 * (1.0 - math.cos(th))
        p2x = p1x - (p2r - p1r) / math.tan(th)
        xc = p2x - r2 * math.sin(th)
        b = np.linspace(math.pi / 2 - th, math.pi / 2, n)
        x2 = xc + r2 * np.cos(b)
        y2 = rc - r2 + r2 * np.sin(b)
        # The straight cone runs between P1 and P2; the arcs' end points define it.
        return np.concatenate([x1, x2]), np.concatenate([y1, y2])

    @cached_property
    def _convergent_points(self) -> tuple[np.ndarray, np.ndarray]:
        return self._convergent(40)

    @property
    def convergent_length(self) -> float:
        xs, _ = self._convergent_points
        return -float(xs[-1])

    @cached_property
    def cylinder_length(self) -> float:
        """Cylinder length so that the volume up to the throat meets L*."""
        xs, ys = self._convergent_points
        order = np.argsort(xs)
        v_conv = float(np.trapezoid(math.pi * ys[order] ** 2, xs[order]))
        v_cyl = self.chamber_volume_required - v_conv
        if v_cyl <= 0:
            return 0.0
        return v_cyl / (math.pi * self.rc**2)

    @property
    def chamber_length(self) -> float:
        """Injector face to throat."""
        return self.cylinder_length + self.convergent_length

    def _divergent(self, n: int) -> tuple[np.ndarray, np.ndarray]:
        rt = self.rt
        thn, the = (math.radians(a) for a in self.bell_angles_deg)
        rd = self.inputs.downstream_throat_arc * rt
        a = np.linspace(-math.pi / 2, -math.pi / 2 + thn, max(n // 5, 8))
        x1 = rd * np.cos(a)
        y1 = rt + rd + rd * np.sin(a)
        nx, ny = float(x1[-1]), float(y1[-1])
        ex, ey = self.nozzle_length, self.re
        # Quadratic Bezier with control point at the intersection of the two tangents.
        m1, m2 = math.tan(thn), math.tan(the)
        qx = (ey - m2 * ex - ny + m1 * nx) / (m1 - m2)
        qy = m1 * (qx - nx) + ny
        t = np.linspace(0.0, 1.0, n)[1:]
        x2 = (1 - t) ** 2 * nx + 2 * (1 - t) * t * qx + t**2 * ex
        y2 = (1 - t) ** 2 * ny + 2 * (1 - t) * t * qy + t**2 * ey
        return np.concatenate([x1, x2]), np.concatenate([y1, y2])

    def points(self, n: int = 200) -> tuple[np.ndarray, np.ndarray]:
        """Inner wall contour (x, r) from injector face to nozzle exit, monotonic in x."""
        xc, yc = self._convergent(max(n // 6, 20))
        x_face = -self.chamber_length
        x_cyl = np.linspace(x_face, xc[-1], max(n // 8, 6), endpoint=False)
        y_cyl = np.full_like(x_cyl, self.rc)
        xd, yd = self._divergent(n)
        x = np.concatenate([x_cyl, xc[::-1], xd[1:]])
        y = np.concatenate([y_cyl, yc[::-1], yd[1:]])
        return x, y

    def summary(self) -> dict[str, float]:
        thn, the = self.bell_angles_deg
        return {
            "throat_diameter_mm": 2e3 * self.rt,
            "chamber_diameter_mm": 2e3 * self.rc,
            "exit_diameter_mm": 2e3 * self.re,
            "cylinder_length_mm": 1e3 * self.cylinder_length,
            "injector_to_throat_mm": 1e3 * self.chamber_length,
            "throat_to_exit_mm": 1e3 * self.nozzle_length,
            "overall_length_mm": 1e3 * (self.chamber_length + self.nozzle_length),
            "bell_initial_angle_deg": thn,
            "bell_exit_angle_deg": the,
        }
