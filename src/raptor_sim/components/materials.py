"""Material property table for component sizing.

Values are typical handbook figures for design studies, not certified design
allowables. Strength at temperature is linearly interpolated between the
listed points. Every entry says where its numbers come from and how much to
trust them.

Sources:
  [MMPDS] MMPDS-17 / ASM handbook typical values (Inconel 718, 316L, Ti-6Al-4V, A-286, Monel K-500)
  [GRC]   Gradl et al., "GRCop-42 development and hot-fire testing using additive manufacturing
          powder bed fusion", AIAA 2019-4228; Ellis, NASA TM-2005-213566 (GRCop-84/42 properties)
  [EST]   Estimate. The SpaceX oxygen-rich superalloy (reported as "SX500") is unpublished;
          the entry uses Mondaloy 200 / Haynes 214-class values as a stand-in.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Material:
    key: str
    name: str
    density: float  # kg/m^3
    conductivity: float  # W/(m K) near operating temperature
    youngs_modulus: float  # Pa at room temperature
    t_points: tuple[float, ...]  # K
    yield_points: tuple[float, ...]  # Pa, 0.2% yield at each temperature
    ultimate_points: tuple[float, ...]  # Pa
    max_service_temperature: float  # K, design limit used by the checks
    oxygen_compatible: bool  # usable in hot, high-pressure oxygen-rich gas
    source: str
    confidence: str  # "handbook" or "estimated"

    def yield_at(self, t: float) -> float:
        return float(np.interp(t, self.t_points, self.yield_points))

    def ultimate_at(self, t: float) -> float:
        return float(np.interp(t, self.t_points, self.ultimate_points))


MATERIALS: dict[str, Material] = {
    m.key: m
    for m in (
        Material(
            "GRCop-42", "GRCop-42 copper alloy (Cu-Cr-Nb), additively manufactured",
            8790.0, 320.0, 115e9,
            (293.0, 600.0, 800.0, 1000.0), (190e6, 160e6, 125e6, 75e6), (370e6, 290e6, 210e6, 120e6),
            850.0, False, "[GRC]", "handbook",
        ),
        Material(
            "IN718", "Inconel 718, solution treated and aged",
            8190.0, 14.0, 200e9,
            (293.0, 700.0, 900.0, 1000.0), (1030e6, 950e6, 860e6, 700e6), (1240e6, 1150e6, 1000e6, 800e6),
            950.0, False, "[MMPDS]", "handbook",
        ),
        Material(
            "OXSA", "Oxygen-compatible Ni superalloy (SX500 / Mondaloy 200 class)",
            8300.0, 12.0, 200e9,
            (293.0, 700.0, 900.0, 1000.0), (900e6, 820e6, 700e6, 550e6), (1150e6, 1050e6, 900e6, 700e6),
            900.0, True, "[EST]", "estimated",
        ),
        Material(
            "SS316L", "316L stainless steel",
            8000.0, 16.0, 193e9,
            (77.0, 293.0, 700.0), (300e6, 205e6, 140e6), (690e6, 515e6, 450e6),
            700.0, True, "[MMPDS]", "handbook",
        ),
        Material(
            "Ti64", "Ti-6Al-4V (fuel side only; not oxygen compatible)",
            4430.0, 7.0, 114e9,
            (77.0, 293.0, 600.0), (1400e6, 880e6, 600e6), (1500e6, 950e6, 700e6),
            600.0, False, "[MMPDS]", "handbook",
        ),
        Material(
            "MonelK500", "Monel K-500 (oxygen-side pump parts)",
            8440.0, 17.0, 179e9,
            (77.0, 293.0, 600.0), (900e6, 790e6, 700e6), (1250e6, 1100e6, 1000e6),
            600.0, True, "[MMPDS]", "handbook",
        ),
        Material(
            "A286", "A-286 iron-nickel superalloy (bolts, lines, housings)",
            7920.0, 15.0, 201e9,
            (77.0, 293.0, 800.0), (900e6, 725e6, 620e6), (1300e6, 1000e6, 850e6),
            800.0, True, "[MMPDS]", "handbook",
        ),
    )
}

# Factors of safety on stress. NASA-STD-5012 asks for at least 1.1 on yield and
# 1.4 on ultimate for engine structures; these are a little stricter because the
# loads themselves are estimates.
SF_YIELD = 1.25
SF_ULTIMATE = 1.5


def allowable(material: Material, t: float) -> float:
    """Allowable stress at temperature: the lower of yield/SF_YIELD and ultimate/SF_ULTIMATE."""
    return min(material.yield_at(t) / SF_YIELD, material.ultimate_at(t) / SF_ULTIMATE)
