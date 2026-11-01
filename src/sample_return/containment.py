"""Planetary protection (restricted Earth return): probability of releasing
unsterilised Martian material into Earth's biosphere.

The requirement used for MSR studies is a probability of release below one in a
million for any unsterilised particle of 50 nm or larger [memory]. That is a
design driver: the passive EEV, the containment vessel (CV), the tube seals and
the break-the-chain sterilisation of the CV's outside all appear in the fault tree.

Paths (each a product of conditional probabilities, summed because they are rare
and nearly independent):

  P1  heat-shield failure during entry -> CV breached -> tube seals breached
      -> particles survive heating and dispersal
  P2  landing impact above the CV's qualified load -> CV breached -> tube seals breached
  P3  break-the-chain failure: Mars dust on the CV outside, not sterilised
      (brazing / thermal sterilisation fails) -> survives entry heating
  P4  EEV not recovered or recovery mishap opens it

Every conditional probability below is an [estimate] to show the allocation and
its sensitivities; it must be replaced by qualification test data. P2 uses the
impact distribution from the entry footprint Monte Carlo.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

REQUIREMENT = 1e-6  # [memory]


@dataclass(frozen=True)
class ContainmentInputs:
    p_tps_failure: float = 1e-5
    p_cv_breach_given_tps: float = 0.3
    p_tubes_breach_given_cv: float = 0.2
    p_particle_survives_heating: float = 0.1
    impact_rating_g: float = 400.0  # CV qualified mean crush deceleration [estimate]
    p_cv_breach_given_overload: float = 0.2
    p_tubes_breach_given_overload: float = 0.2
    p_dust_on_cv_exterior: float = 0.05
    p_sterilisation_failure: float = 1e-3
    p_dust_survives_entry: float = 1e-2
    p_recovery_mishap: float = 1e-4
    p_cv_breach_given_mishap: float = 1e-2
    p_tubes_breach_given_mishap: float = 0.1


@dataclass(frozen=True)
class ContainmentResult:
    paths: dict = field(default_factory=dict)

    @property
    def total(self) -> float:
        return sum(self.paths.values())

    @property
    def meets_requirement(self) -> bool:
        return self.total < REQUIREMENT


def p_overload(mean_g: float, sigma_g: float, rating_g: float) -> float:
    """Normal-tail probability that the impact deceleration exceeds the rating."""
    if sigma_g <= 0:
        return 0.0 if mean_g <= rating_g else 1.0
    z = (rating_g - mean_g) / sigma_g
    return 0.5 * math.erfc(z / math.sqrt(2))


def release_probability(ci: ContainmentInputs, impact_mean_g: float, impact_sigma_g: float) -> ContainmentResult:
    p1 = ci.p_tps_failure * ci.p_cv_breach_given_tps * ci.p_tubes_breach_given_cv * ci.p_particle_survives_heating
    p2 = (
        p_overload(impact_mean_g, impact_sigma_g, ci.impact_rating_g)
        * ci.p_cv_breach_given_overload
        * ci.p_tubes_breach_given_overload
    )
    p3 = ci.p_dust_on_cv_exterior * ci.p_sterilisation_failure * ci.p_dust_survives_entry
    p4 = ci.p_recovery_mishap * ci.p_cv_breach_given_mishap * ci.p_tubes_breach_given_mishap
    return ContainmentResult(
        {
            "P1 heat shield failure": p1,
            "P2 impact overload": p2,
            "P3 break-the-chain": p3,
            "P4 recovery mishap": p4,
        }
    )
