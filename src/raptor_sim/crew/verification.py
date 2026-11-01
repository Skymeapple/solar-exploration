"""Verification items for the crew models (CV1 to CV8).

Each item compares a model against an analytic result, a conservation law,
or published data, with a stated pass band.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..mission import A_EARTH, A_MARS, hohmann_vinf
from . import entry as E
from . import life_support as LS
from . import radiation as RAD
from .orbits import DAY, jd_from_date, lambert, planet_state, propagate
from .propulsion import edelbaum_dv, spiral
from ..mission import AU


@dataclass(frozen=True)
class Check:
    id: str
    name: str
    value: float
    reference: float
    error: float
    band: str
    passed: bool
    basis: str  # analytic | conservation | published data | weak (calibration-informed)


def cv1_ephemeris() -> Check:
    """Mars oppositions 2025-01-16, 2027-02-19, 2029-03-25 (public almanac dates)."""
    errs = []
    for d in ("2025-01-16", "2027-02-19", "2029-03-25"):
        jd = jd_from_date(d)
        re, _ = planet_state("earth", jd)
        rm, _ = planet_state("mars", jd)
        errs.append(abs(math.degrees(math.remainder(math.atan2(rm[1], rm[0]) - math.atan2(re[1], re[0]), 2 * math.pi))))
    e = max(errs)
    return Check("CV1", "Ephemeris: Earth-Mars longitude at 3 published oppositions", e, 0.0, e, "< 1 deg", e < 1.0,
                 "published data")


def cv2_lambert_propagator() -> Check:
    r0, v0 = planet_state("earth", jd_from_date("2028-11-01"))
    v0 = v0 * 1.08
    r1, v1 = propagate(r0, v0, 200 * DAY)
    s = lambert(r0, r1, 200 * DAY)
    e = float(max(np.linalg.norm(s[0] - v0), np.linalg.norm(s[1] - v1)))
    return Check("CV2", "Lambert solver inverts the Kepler propagator (200-day arc)", e, 0.0, e, "< 1e-3 m/s", e < 1e-3,
                 "analytic")


def cv3_hohmann() -> Check:
    """Lambert on circular coplanar orbits at a 179 deg transfer vs the Hohmann formula."""
    vd_ref, va_ref, tof = hohmann_vinf(A_EARTH, A_MARS)
    ang = math.radians(179.0)
    r1 = np.array([A_EARTH, 0, 0])
    r2 = A_MARS * np.array([math.cos(ang), math.sin(ang), 0])
    from ..mission import MU_SUN
    # time for 179 deg on the Hohmann ellipse (near the full half period)
    s = lambert(r1, r2, tof * DAY * 0.9935)
    vd = float(np.linalg.norm(s[0] - np.array([0, math.sqrt(MU_SUN / A_EARTH), 0])))
    e = abs(vd / vd_ref - 1)
    return Check("CV3", "Lambert vs Hohmann departure v-infinity (Earth-Mars, circular)", vd, vd_ref, e, "< 2%",
                 e < 0.02, "analytic")


def cv4_allen_eggers() -> Check:
    veh = E.EntryVehicle("ballistic test", 9_300.0, 19.6, 1.3, 0.0, 6.0)
    sim = E.simulate_entry(veh, "earth", 11_000.0, -10.0, gravity=False).peak_g
    ref = E.allen_eggers_peak_g(11_000.0, -10.0, E.PLANETS["earth"]["H"])
    e = abs(sim / ref - 1)
    return Check("CV4", "Entry integrator vs Allen-Eggers ballistic peak g (11 km/s, -10 deg)", sim, ref, e, "< 1%",
                 e < 0.01, "analytic")


def cv5_edelbaum() -> Check:
    dv, _ = spiral(AU, 1.524 * AU, 1e-5, 3000.0)
    ref = edelbaum_dv(AU, 1.524 * AU)
    e = abs(dv / ref - 1)
    return Check("CV5", "Low-thrust spiral integration vs Edelbaum delta-v (1 to 1.524 AU)", dv, ref, e, "< 1%",
                 e < 0.01, "analytic")


def cv6_mass_balance() -> Check:
    day = LS.crew_day_balance().imbalance
    hist = LS.simulate_stocks(6, 950, "iss", failures=((100, 30, "oga"), (400, 20, "wrs")))
    e = max(abs(day), abs(hist.mass_error))
    return Check("CV6", "Life support: crew-day and 950-day stock mass conservation", e, 0.0, e, "< 1e-6 kg",
                 e < 1e-6, "conservation")


def cv7_failure_reserve() -> Check:
    res = LS.reserve_for_failure(6, 30, "oga")
    hist = LS.simulate_stocks(6, 950, "iss", o2_reserve=res * 1.05, failures=((200, 30, "oga"),))
    m = min(hist.o2)
    return Check("CV7", "O2 reserve sized for a 30-day oxygen generator outage keeps O2 > 0", m, 0.0, 0.0, "min O2 > 0",
                 m > 0 and not hist.ran_out, "conservation")


def cv8_radiation_moon() -> Check:
    pred = RAD.CAL.predict_moon()
    ref = RAD.CE4_MOON_SURFACE_MSV_D
    e = abs(pred / ref - 1)
    return Check("CV8", "GCR model (fit to Curiosity RAD) vs Chang'e-4 lunar surface dose", pred, ref, e, "< 25%",
                 e < 0.25, "weak (calibration-informed)")


def run_all() -> list[Check]:
    return [cv1_ephemeris(), cv2_lambert_propagator(), cv3_hohmann(), cv4_allen_eggers(), cv5_edelbaum(),
            cv6_mass_balance(), cv7_failure_reserve(), cv8_radiation_moon()]
