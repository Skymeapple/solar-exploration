"""Main injector: gas-gas shear coaxial elements (full-flow staged combustion).

In a full-flow engine both propellants reach the main injector as gas: oxygen-rich
turbine exhaust through the centre post of each element, fuel-rich turbine exhaust
through the surrounding annulus. Element sizing follows the orifice equation with a
discharge coefficient; layout puts elements on concentric rings.

Design guidance used for the checks (estimates, not Raptor data):
* injector pressure drop at least 15% of chamber pressure for combustion stability
  (Huzel & Huang sec. 4.4),
* fuel-to-oxidizer velocity ratio above 1.5 for good shear mixing in gas-gas
  coaxial elements (NASA CR-182260 / Schuman, gas-gas injector tests),
* metal ligament between elements of at least 1.5 mm for manufacture.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..cycle import CycleResult
from ..engine import EnginePerformance
from .chamber import Contour
from .materials import MATERIALS, allowable
from .turbopump import gas_properties, turbine_exit_temperature


@dataclass(frozen=True)
class InjectorInputs:
    n_elements: int = 300
    discharge_coefficient: float = 0.85
    post_wall_thickness: float = 1.2e-3  # m
    post_recess: float = 3.0e-3  # m, ox post tip recessed behind the face
    min_ligament: float = 1.5e-3  # m
    edge_gap: float = 8.0e-3  # m, film-cooling ring to chamber wall
    min_velocity_ratio: float = 1.5
    face_material: str = "IN718"
    ox_dome_material: str = "OXSA"


@dataclass(frozen=True)
class InjectorDesign:
    inputs: InjectorInputs
    ox_flow: float  # kg/s through the posts (oxygen-rich gas)
    fuel_flow: float  # kg/s through the annuli (fuel-rich gas)
    ox_density: float
    fuel_density: float
    ox_temperature: float
    fuel_temperature: float
    manifold_pressure: float  # Pa
    pressure_drop: float  # Pa
    post_inner_diameter: float  # m
    post_outer_diameter: float
    annulus_outer_diameter: float
    ox_velocity: float
    fuel_velocity: float
    velocity_ratio: float
    momentum_flux_ratio: float  # fuel / ox
    rings: list[tuple[float, int]]  # (ring radius m, element count)
    element_pitch: float
    ligament: float
    face_thickness: float
    face_stress: float
    face_allowable: float
    dome_thickness: float
    usable_face_radius: float

    @property
    def placed_elements(self) -> int:
        return sum(n for _r, n in self.rings)

    def positions(self) -> list[tuple[float, float]]:
        pts = []
        for j, (r, n) in enumerate(self.rings):
            if r == 0.0:
                pts.append((0.0, 0.0))
                continue
            offset = (math.pi / n) * (j % 2)  # stagger alternate rings
            for k in range(n):
                a = 2 * math.pi * k / n + offset
                pts.append((r * math.cos(a), r * math.sin(a)))
        return pts


def _layout(n_target: int, min_pitch: float, r_max: float) -> tuple[list[tuple[float, int]], float]:
    """Spread n elements over concentric rings filling the usable face.

    Picks the fewest rings K whose capacity (one centre element plus floor(2 pi k) per ring)
    holds n, spaces the rings evenly out to r_max, and shares the elements between rings in
    proportion to circumference. Returns the rings and the smallest centre-to-centre spacing.
    """
    k_rings = 1
    while 1 + sum(int(2 * math.pi * k) for k in range(1, k_rings + 1)) < n_target:
        k_rings += 1
    spacing = r_max / k_rings
    caps = [int(2 * math.pi * k) for k in range(1, k_rings + 1)]
    share = (n_target - 1) / sum(caps)
    counts = [int(c * share) for c in caps]
    # hand out the remainder to the outer rings
    i = len(counts) - 1
    while sum(counts) < n_target - 1:
        counts[i] += 1
        i = i - 1 if i > 0 else len(counts) - 1
    rings = [(0.0, 1)] + [((k + 1) * spacing, n) for k, n in enumerate(counts)]
    in_ring = min(2 * math.pi * r / n for r, n in rings[1:] if n > 0)
    return rings, min(spacing, in_ring)


def design_injector(perf: EnginePerformance, cycle: CycleResult, contour: Contour,
                    ii: InjectorInputs | None = None) -> InjectorDesign:
    ii = ii or InjectorInputs()
    a = cycle.assumptions
    pc = perf.design.pc
    p_man = pc * (1 + a.dp_main_injector)
    dp = p_man - pc
    ox, fu = cycle.ox_shaft, cycle.fuel_shaft
    t_ox = turbine_exit_temperature(ox, p_man, a.eta_turbine_ox)
    t_fu = turbine_exit_temperature(fu, p_man, a.eta_turbine_fuel)
    _t, _cp, g_ox, r_ox = gas_properties(ox.preburner_pressure, ox.preburner_mixture_ratio)
    _t, _cp, g_fu, r_fu = gas_properties(fu.preburner_pressure, fu.preburner_mixture_ratio)
    rho_ox = p_man / (r_ox * t_ox)
    rho_fu = p_man / (r_fu * t_fu)
    # Compressible orifice: expansion factor Y = 1 - 0.41 (dp/p) / gamma (ISO 5167 for thin plates, approx).
    y_ox = 1 - 0.41 * (dp / p_man) / g_ox
    y_fu = 1 - 0.41 * (dp / p_man) / g_fu
    n = ii.n_elements
    a_ox = ox.turbine_flow / (ii.discharge_coefficient * y_ox * math.sqrt(2 * rho_ox * dp)) / n
    a_fu = fu.turbine_flow / (ii.discharge_coefficient * y_fu * math.sqrt(2 * rho_fu * dp)) / n
    d_i = math.sqrt(4 * a_ox / math.pi)
    d_o = d_i + 2 * ii.post_wall_thickness
    d_f = math.sqrt(d_o**2 + 4 * a_fu / math.pi)
    v_ox = ox.turbine_flow / n / (rho_ox * a_ox)
    v_fu = fu.turbine_flow / n / (rho_fu * a_fu)
    r_use = contour.rc - ii.edge_gap - d_f / 2
    rings, pitch = _layout(n, d_f + ii.min_ligament, r_use)
    ligament = pitch - d_f

    # Face plate between elements: clamped circular plate of diameter = pitch, loaded by the
    # fuel manifold-to-chamber drop. Roark table 11.2 case 10b: sigma = 0.75 q a^2 / t^2.
    mat = MATERIALS[ii.face_material]
    t_face_temp = t_fu
    sig = allowable(mat, t_face_temp)
    span = pitch / 2
    t_face = max(span * math.sqrt(0.75 * dp / sig), 3e-3)
    face_stress = 0.75 * dp * span**2 / t_face**2
    dome = MATERIALS[ii.ox_dome_material]
    t_dome = max(p_man * contour.rc / (2 * allowable(dome, t_ox)), 3e-3)
    return InjectorDesign(
        ii, ox.turbine_flow, fu.turbine_flow, rho_ox, rho_fu, t_ox, t_fu, p_man, dp, d_i, d_o, d_f,
        v_ox, v_fu, v_fu / v_ox, rho_fu * v_fu**2 / (rho_ox * v_ox**2), rings, pitch, ligament,
        t_face, face_stress, sig, t_dome, r_use,
    )
