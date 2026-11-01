"""Cross-target comparison: how the sample return chain changes from Moon to Saturn.

For each target we estimate, with circular-coplanar Hohmann transfers [estimate]
(real missions use gravity assists and eccentric orbits, so treat these as
first-order), the outbound launch energy, the ascent delta-v from the surface,
the one-way flight time, the Earth entry speed of the returning capsule, and the
peak heating that entry gives the MSR-class EEV. Where a flown mission gives the
real entry speed, that is used and marked [cited].
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .bodies import AU, BENNU, COMET_67P, DAY, EARTH, ENCELADUS, EUROPA, MARS, MOON, MU_SUN, PHOBOS, Body
from .entry import MSR_EEV, EntryConditions, simulate_entry
from .transfer import entry_speed, hohmann_vinf

INTERFACE_ALT = 125e3


@dataclass(frozen=True)
class TargetCase:
    body: Body
    planet_sma_au: float  # heliocentric orbit of the body (or its planet)
    pp_category: str  # COSPAR planetary-protection category for Earth return
    heritage: str
    entry_speed_cited: float | None = None  # m/s if a flown mission gives it
    ascent_note: str = ""


@dataclass(frozen=True)
class TargetRow:
    name: str
    c3_depart: float  # km^2/s^2
    vinf_arrive: float  # km/s at the planet (heliocentric Hohmann)
    one_way_days: float
    ascent_dv: float  # m/s, surface to low orbit (or to escape for small bodies)
    entry_speed: float  # km/s at 125 km
    entry_source: str
    peak_heat_W_cm2: float
    peak_decel_g: float
    pp_category: str
    heritage: str


CASES = [
    TargetCase(
        MOON, 1.0, "V unrestricted", "Apollo, Luna 16/20/24, Chang'e 5 and 6 (1,935 g from the far side, 2024) [cited]",
        11_000.0,
    ),
    TargetCase(
        MARS, 1.523679, "V restricted", "none flown; NASA-ESA MSR cancelled Jan 2026; Tianwen-3 targets 2028 launch, 2031 return [cited]"
    ),
    TargetCase(PHOBOS, 1.523679, "V unrestricted [memory]", "JAXA MMX launched 20 Oct 2026, >=10 g, return 2031 [cited]"),
    TargetCase(
        BENNU, 1.126, "V unrestricted", "OSIRIS-REx (121.6 g [memory], landed 24 Sep 2023 [cited]); Hayabusa2 at Ryugu (12 km/s entry [cited])",
        12_000.0,
    ),
    TargetCase(COMET_67P, 3.46, "V unrestricted", "Stardust coma flyby (12.9 km/s entry, Jan 2006 [cited]); nucleus return only studied (CAESAR) [memory]", 12_900.0),
    TargetCase(EUROPA, 5.2038, "V restricted", "none; lander concepts only [memory]"),
    TargetCase(ENCELADUS, 9.5826, "V restricted", "none; plume fly-through capture studied [memory]"),
]


MARS_ASCENT_IDEAL_DV = 4_200.0  # m/s, rounded from the MAV simulation (ascent.py)


def ascent_dv(body: Body, loss_factor: float = 1.15) -> float:
    """Surface-to-orbit delta-v [estimate].

    Small bodies: 1.5 x escape speed (leaving, not orbiting). Airless moons: circular
    speed at 15 km times a gravity-loss factor. Mars: the MAV simulation's ideal delta-v."""
    if body is MARS:
        return MARS_ASCENT_IDEAL_DV
    if body.radius < 50e3:
        return body.escape_speed * 1.5
    return body.circular_speed(15e3) * loss_factor


def compare_targets(gamma_deg: float = -10.5) -> list[TargetRow]:
    rows = []
    for case in CASES:
        b = case.body
        if b is MOON:
            c3, vinf_a, days = -2.0, 0.8, 4.5  # typical TLI and lunar arrival [memory]
            vinf_e = None
        else:
            vd, va, tof = hohmann_vinf(AU, case.planet_sma_au * AU, MU_SUN)
            c3, vinf_a, days = (vd / 1e3) ** 2, va / 1e3, tof / DAY
            vinf_e = vd  # return Hohmann arrives at Earth with the same excess speed
        if case.entry_speed_cited:
            v_e, src = case.entry_speed_cited, "flown mission [cited]"
        else:
            v_e, src = entry_speed(vinf_e, EARTH, INTERFACE_ALT), "Hohmann return [estimate]"
        er = simulate_entry(MSR_EEV, EntryConditions(v_e, gamma_deg))
        rows.append(
            TargetRow(
                name=b.name,
                c3_depart=c3,
                vinf_arrive=vinf_a,
                one_way_days=days,
                ascent_dv=ascent_dv(b),
                entry_speed=v_e / 1e3,
                entry_source=src,
                peak_heat_W_cm2=er.peak_heat_flux / 1e4,
                peak_decel_g=er.peak_decel_g,
                pp_category=case.pp_category,
                heritage=case.heritage,
            )
        )
    return rows
