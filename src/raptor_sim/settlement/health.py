"""Long-term health: partial-gravity bone loss under competing hypotheses, and
medical capacity as a settlement grows.

Bone. We know the loss rate in weightlessness (1-1.5 %/month at weight-bearing
sites, NASA HRP) and we know 1 g. No human has lived at 0.38 g or 0.17 g, so the
shape in between is unknown. The model runs three hypotheses and reports all of
them; it is a way to see what each would mean, not a prediction:

  linear    - loss scales with the gravity deficit (1 - g)
  threshold - no loss above g_t = 0.3 g, linear below (some rodent data hint at
              partial protection near 1/3 g)
  sqrt      - loss scales with sqrt(1 - g): even a little gravity deficit hurts

Bone does not fall forever: it approaches a new set point. We assume the
maximum possible loss is 35 % (similar to long-term spinal-cord injury,
estimate), scaled by the same hypothesis function.

Medicine. Expected emergencies scale with population; the questions are when a
settlement can support a surgeon, and how likely a surgical emergency is before
the next ship.
"""
from __future__ import annotations

import math

from .inputs import v

GRAVITY_G = {  # surface gravity in Earth g (cited: standard planetary data)
    "Earth": 1.0,
    "Mars": 3.721 / 9.80665,
    "Moon": 1.62 / 9.80665,
    "Titan": 1.352 / 9.80665,
    "Callisto": 1.235 / 9.80665,
    "Ceres": 0.28 / 9.80665,
    "Free space": 0.0,
}
MAX_LOSS = 0.35  # estimate
OSTEOPOROSIS_LOSS = 0.25  # about -2.5 SD from young-adult peak (WHO T-score; SD ~10%)
THRESHOLD_G = 0.3

HYPOTHESES = {
    "linear": lambda g: max(0.0, 1.0 - g),
    "threshold": lambda g: max(0.0, (THRESHOLD_G - g) / THRESHOLD_G),
    "sqrt": lambda g: math.sqrt(max(0.0, 1.0 - g)),
}


def bone_fraction(years: float, g: float, hypothesis: str, exercise: bool = True) -> float:
    """Bone mineral density relative to arrival after `years` at gravity g."""
    h = HYPOTHESES[hypothesis](g)
    if h <= 0:
        return 1.0
    eff = v("exercise_effectiveness") if exercise else 0.0
    rate = v("bone_loss_0g") * 12.0 * h * (1.0 - eff)  # 1/yr initial
    floor = 1.0 - MAX_LOSS * h
    depth = 1.0 - floor
    return floor + depth * math.exp(-rate * years / depth)


def years_to_osteoporosis(g: float, hypothesis: str, exercise: bool = True) -> float:
    if 1.0 - MAX_LOSS * HYPOTHESES[hypothesis](g) >= 1.0 - OSTEOPOROSIS_LOSS:
        return math.inf
    lo, hi = 0.0, 200.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if bone_fraction(mid, g, hypothesis, exercise) > 1 - OSTEOPOROSIS_LOSS else (lo, mid)
    return hi


def bone_table() -> list[dict]:
    rows = []
    for site in ("Moon", "Mars", "Ceres", "Free space"):
        g = GRAVITY_G[site]
        for hyp in HYPOTHESES:
            rows.append(
                {
                    "site": site,
                    "g": g,
                    "hypothesis": hyp,
                    "bone_after_2_5_yr": bone_fraction(2.5, g, hyp),
                    "bone_after_10_yr": bone_fraction(10.0, g, hyp),
                    "set_point": 1.0 - MAX_LOSS * HYPOTHESES[hyp](g),
                    "years_to_osteoporosis": years_to_osteoporosis(g, hyp),
                }
            )
    return rows


def medical_capacity(population: int, months_between_ships: float = 26.0) -> dict[str, float]:
    """Staffing and emergency odds for a settlement of the given size."""
    yrs = months_between_ships / 12.0
    surg = population * v("surgical_emergency_rate")
    return {
        "population": population,
        "physicians_needed": population * v("physicians_per_1000") / 1000.0,
        "surgical_emergencies_per_year": surg,
        "p_surgical_emergency_between_ships": 1.0 - math.exp(-surg * yrs),
        "appendicitis_per_year": population * v("appendicitis_rate"),
        "births_per_year_at_tfr": population * 0.5 * 0.45 * v("tfr_target") / 24.0,  # 45% of women 18-42 (estimate)
    }


def comms_delay_minutes() -> tuple[float, float]:
    """One-way light time Earth-Mars at closest and farthest (circular orbits)."""
    au_s = 149_597_870.7e3 / 299_792_458.0
    return (1.523679 - 1.0) * au_s / 60.0, (1.523679 + 1.0) * au_s / 60.0
