"""Microgravity deconditioning and artificial gravity sizing.

CITED
- Bone mineral density loss in weight-bearing bone ~1-1.5% per month in
  microgravity (LeBlanc et al., J Musculoskelet Neuronal Interact 2000;
  also NASA Human Research Program evidence reports).
- Comfort limits for rotating habitats are not settled. Commonly used design
  envelope (Hall 1997/2006 synthesis of Graybiel, Stone, Cramer studies):
  spin rate <= 2 rpm needs no adaptation, <= 4 rpm with adaptation, ~6 rpm
  upper limit for trained crew; rim speed >= 6 m/s and gravity at least
  ~0.035 g to keep "down" defined.
ESTIMATES
- Exercise (ARED-class) halves bone-loss rate (ISS crews with ARED show far
  smaller loss than Mir crews; the factor 0.5 is ours).
- Head-to-foot gravity gradient should stay below ~15% for a 1.8 m person.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..constants import G0

BONE_LOSS_PER_MONTH = 0.0125  # CITED midpoint of 1-1.5 %/month
EXERCISE_FACTOR = 0.5  # ESTIMATE


def bone_loss_fraction(days_microgravity: float, exercise: bool = True, partial_g: float = 0.0) -> float:
    """Cumulative bone mineral density loss in weight-bearing bone (fraction).

    partial_g scales the loss rate linearly down to zero at 1 g (ESTIMATE; the
    real dose-response for 0.38 g is unknown - a key research gap).
    """
    rate = BONE_LOSS_PER_MONTH * (EXERCISE_FACTOR if exercise else 1.0) * max(1 - partial_g, 0.0)
    return 1 - (1 - rate) ** (days_microgravity / 30.44)


@dataclass(frozen=True)
class SpinDesign:
    g_level: float
    rpm: float
    radius_m: float
    rim_speed: float
    gradient_head_foot: float  # fraction over 1.8 m
    coriolis_ratio: float  # Coriolis / centripetal for 1 m/s walking along the rim
    meets_envelope: bool


def spin_design(g_level: float, rpm: float, height: float = 1.8) -> SpinDesign:
    omega = rpm * 2 * math.pi / 60
    r = g_level * G0 / omega**2
    rim = omega * r
    grad = height / r
    cor = 2 * omega * 1.0 / (g_level * G0)
    ok = rpm <= 4.0 and rim >= 6.0 and grad <= 0.15
    return SpinDesign(g_level, rpm, r, rim, grad, cor, ok)


def min_radius(g_level: float, max_rpm: float = 4.0) -> float:
    return spin_design(g_level, max_rpm).radius_m


@dataclass(frozen=True)
class TetheredPair:
    """Two masses spinning about their centre: e.g. crew ship + spent stage."""
    m_crew_t: float
    m_counter_t: float
    g_level: float
    rpm: float
    tether_length_m: float
    tether_mass_kg: float
    spin_up_dv: float  # m/s, tangential speed of crew module


def tethered_pair(m_crew_t: float = 150.0, m_counter_t: float = 150.0, g_level: float = 0.38, rpm: float = 4.0,
                  tether_specific_strength: float = 2.5e6, safety: float = 5.0) -> TetheredPair:
    """Tether sizing (ESTIMATE): Zylon/Dyneema-class specific strength ~2.5 MN*m/kg, safety factor 5."""
    omega = rpm * 2 * math.pi / 60
    r_crew = g_level * G0 / omega**2
    r_counter = r_crew * m_crew_t / m_counter_t
    L = r_crew + r_counter
    tension = m_crew_t * 1e3 * g_level * G0
    # uniform tether: mass = tension * L * SF / specific strength (ignores self-load, small here)
    m_tether = tension * L * safety / tether_specific_strength
    return TetheredPair(m_crew_t, m_counter_t, g_level, rpm, L, m_tether, omega * r_crew)
