"""Sample collection, sealing and the orbiting sample (OS) container.

Covers the mass budget of the cached samples, and the gas-tightness of the two
barriers between a Mars sample and Earth's air: the tube seal and the brazed
containment vessel (CV) closed around the OS in Mars orbit ("break the chain").

Leak model: molecular-flow conductance taken from a helium leak-rate spec
(std cm^3/s at 1 atm differential), scaled by sqrt(M_He / M_gas). A sealed volume
then behaves as a first-order system with time constant tau = V / C.

[cited] Perseverance carries 43 tubes; 33 cached by July 2025; 10 tubes left at the
Three Forks depot; the OS holds 30 tubes; a 14-16 kg OS package.
[memory] core size about 13 mm x 60 mm.
[estimate] sample mass per tube, tube headspace volume, leak rates, CV volume,
time from landing to opening in the receiving facility.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

M_HE = 4.0026
M_CO2 = 44.01
M_AIR = 28.97
MARS_SURFACE_PRESSURE = 610.0  # Pa, mean [memory]
P_ATM = 101_325.0


@dataclass(frozen=True)
class SampleCache:
    tubes: int = 30  # OS capacity [cited]
    sample_mass_per_tube: float = 0.012  # kg (12 g core) [estimate]
    empty_tube_mass: float = 0.075  # kg incl. seal [estimate]
    os_structure: float = 12.0  # kg shell, lid, tube holders [estimate]; full OS ~14.6 kg vs cited 14-16 kg

    @property
    def sample_mass(self) -> float:
        return self.tubes * self.sample_mass_per_tube

    @property
    def os_mass(self) -> float:
        return self.os_structure + self.tubes * (self.empty_tube_mass + self.sample_mass_per_tube)


@dataclass(frozen=True)
class SealDesign:
    tube_leak_he: float = 1e-10  # std cm^3/s He at 1 atm [estimate]
    tube_headspace_cm3: float = 2.0  # [estimate]
    cv_leak_he: float = 1e-9  # brazed containment vessel [estimate]
    cv_free_volume_cm3: float = 3_000.0  # [estimate]


def conductance(leak_he: float, molar_mass: float) -> float:
    """Volumetric conductance (cm^3/s) for a gas, from a helium leak spec."""
    return leak_he * math.sqrt(M_HE / molar_mass)


def headspace_retained(seal: SealDesign, days_in_vacuum: float) -> float:
    """Fraction of Martian headspace gas (CO2) still in a tube after days in vacuum
    (ascent, orbit, cruise). The CV is closed in Mars orbit, so it is treated as
    vacuum outside the tube (conservative)."""
    tau = seal.tube_headspace_cm3 / conductance(seal.tube_leak_he, M_CO2)
    return math.exp(-days_in_vacuum * 86_400 / tau)


def earth_air_ingress(seal: SealDesign, days_on_earth: float, days_in_vacuum: float = 700.0) -> float:
    """Moles of Earth air that reach a tube's headspace, as a fraction of the Martian
    gas still there, after days_on_earth between landing and opening.

    The CV fills from outside (linear while its pressure is far below 1 atm), and the
    tube fills from the CV, so the tube ingress grows with t^2."""
    t = days_on_earth * 86_400
    c_cv = conductance(seal.cv_leak_he, M_AIR)
    c_tube = conductance(seal.tube_leak_he, M_AIR)
    # p_cv(t) = P_ATM * c_cv * t / V_cv ; ingress (in pressure x volume) = c_tube * integral p_cv dt
    ingress_pv = c_tube * P_ATM * c_cv * t**2 / (2 * seal.cv_free_volume_cm3)
    mars_pv = MARS_SURFACE_PRESSURE * seal.tube_headspace_cm3 * headspace_retained(seal, days_in_vacuum)
    return ingress_pv / mars_pv


@dataclass(frozen=True)
class SurfaceCampaign:
    """Sampling cadence model [estimate], calibrated loosely to Perseverance's pace
    (about 33 samples cached in about 4.4 years of surface operations [cited])."""

    samples_wanted: int = 30
    sols_per_attempt: float = 8.0  # coring, abrasion, proximity science, sealing
    attempt_success: float = 0.9  # first-attempt success (some rocks crumble)
    traverse_sols_per_sample: float = 30.0

    def expected_sols(self) -> float:
        attempts = self.samples_wanted / self.attempt_success
        return attempts * self.sols_per_attempt + self.samples_wanted * self.traverse_sols_per_sample
