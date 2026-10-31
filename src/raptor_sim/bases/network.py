"""Delta-v network between transit bases, with refuelling at each hub.

Orbital mechanics: patched conics, circular coplanar orbits, Hohmann transfers
(no gravity assists, no plane changes). Interplanetary burns carry the same
10% margin as :mod:`raptor_sim.mission`.

* Airless site: one impulsive burn from (or to) the surface,
  ``dv = k * sqrt(v_inf^2 + v_esc^2)``, with a small loss factor ``k``.
* Site with an atmosphere: ascent to a low parking orbit, then an Oberth burn
  there; arrival by aerocapture and entry, plus a propulsive trim if the entry
  speed is above the heat shield's limit.
* Moon of a giant planet: the ship leaves the moon's sphere of influence with
  the speed (relative to the moon) needed to reach the planet-frame velocity
  of the transfer orbit at the moon's distance.

The ship is the project's Starship-class upper stage. Each hop starts with full
tanks at a hub; the payload it can carry over the hop is solved from the rocket
equation. Earth's hub is low Earth orbit, filled by tanker launches.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

from ..constants import G0
from .isru import isru_plan
from .sites import AU, PLANETS, SITES, Site

MU_SUN = 1.32712440018e20
R_LEO = 6.371e6 + 300e3
MU_EARTH = PLANETS["earth"][1]

AIRLESS_LOSS = 1.05  # estimate: gravity loss and pointing for direct ascent/landing
AIRLESS_LOSS_DV = 50.0  # m/s, estimate: hover and terminal manoeuvres
INTERPLANETARY_MARGIN = 1.10  # same as MissionAssumptions.tmi_margin
ENTRY_SPEED_LIMIT = 12_500.0  # m/s, estimate: heat-shield limit for aerocapture/entry
EARTH_RETURN_TO_LEO_DV = 150.0  # m/s, estimate: aerocapture into LEO plus circularisation


@dataclass(frozen=True)
class Ship:
    """Starship-class upper stage. Defaults reproduce raptor_sim.mission.vehicle_performance."""

    dry_t: float = 100.0  # public Block 1 figure; 150 t closes the LEO-payload gap
    propellant_t: float = 1_600.0  # public
    isp_space: float = 362.7  # s, RVac from the engine model
    isp_surface: float = 348.0  # s, sea-level engines in vacuum, from the engine model
    max_payload_t: float = 150.0  # estimate: structural limit
    payload_to_leo_t: float = 155.5  # t, from the vehicle model (for tanker counts)

    @classmethod
    def from_engine_model(cls, dry_t: float = 100.0) -> "Ship":
        from ..mission import Vehicle, vehicle_performance

        v = Vehicle(ship_dry_t=dry_t)
        p = vehicle_performance(v)
        return cls(dry_t, v.ship_propellant_t, p.rvac_isp, p.sl_vac_isp, payload_to_leo_t=p.payload_to_leo_t)

    def payload(self, dv_space: float, dv_surface: float) -> float:
        """Payload the propellant could push over the hop with full tanks, before the
        structural cap; negative means the hop cannot be flown."""
        r = math.exp(dv_space / (self.isp_space * G0) + dv_surface / (self.isp_surface * G0))
        return (self.propellant_t - (r - 1) * self.dry_t) / (r - 1)

    def cargo(self, dv_space: float, dv_surface: float) -> float:
        """Payload actually carried: propulsive capacity limited by the structural cap."""
        return min(self.payload(dv_space, dv_surface), self.max_payload_t)

    def propellant_for(self, dv_space: float, dv_surface: float, payload_t: float) -> float:
        r = math.exp(dv_space / (self.isp_space * G0) + dv_surface / (self.isp_surface * G0))
        return (self.dry_t + payload_t) * (r - 1)


# ---------------------------------------------------------------------------
# geometry helpers


def planet_of(key: str) -> str:
    if key == "leo":
        return "earth"
    s = SITES[key]
    return s.body if s.parent == "sun" else s.parent


def _orbit_radius_in_planet_frame(key: str) -> float:
    """Distance from the planet's centre at which the node sits."""
    if key == "leo":
        return R_LEO
    s = SITES[key]
    if s.parent == "sun":
        return s.radius_m + s.low_orbit_alt_m if s.aero else s.radius_m
    return s.moon_orbit_m


def _circ(mu: float, r: float) -> float:
    return math.sqrt(mu / r)


def _airless_burn(s: Site, v_inf: float) -> float:
    return AIRLESS_LOSS * math.hypot(v_inf, s.v_escape) + AIRLESS_LOSS_DV


def _burn_from_orbit(v_inf: float, mu: float, r: float) -> float:
    return math.sqrt(v_inf**2 + 2 * mu / r) - math.sqrt(mu / r)


@dataclass(frozen=True)
class Leg:
    origin: str
    dest: str
    dv_space: float  # m/s, margin included
    dv_surface: float  # m/s, ascent and landing
    tof_days: float
    synodic_days: float  # time between launch windows
    entry_speed: float = 0.0  # m/s at the destination, if aerocapture is used

    @property
    def dv_total(self) -> float:
        return self.dv_space + self.dv_surface


def _depart(key: str, v_inf: float) -> tuple[float, float]:
    """(space, surface) dv to leave node `key` with excess speed v_inf relative to its body."""
    if key == "leo":
        return _burn_from_orbit(v_inf, MU_EARTH, R_LEO), 0.0
    s = SITES[key]
    if s.aero:
        return _burn_from_orbit(v_inf, s.gm, s.radius_m + s.low_orbit_alt_m), s.ascent_dv
    total = _airless_burn(s, v_inf)
    surf = min(AIRLESS_LOSS * s.v_escape + AIRLESS_LOSS_DV, total)
    return total - surf, surf


def _arrive(key: str, v_inf: float) -> tuple[float, float, float]:
    """(space, surface, entry_speed) to arrive at node `key` from excess speed v_inf."""
    if key == "leo":
        v_entry = math.sqrt(v_inf**2 + 2 * MU_EARTH / 6.471e6)
        trim = max(v_entry - ENTRY_SPEED_LIMIT, 0.0)
        return trim, EARTH_RETURN_TO_LEO_DV, v_entry
    s = SITES[key]
    if s.aero:
        v_entry = math.hypot(v_inf, s.v_escape)
        trim = max(v_entry - ENTRY_SPEED_LIMIT, 0.0)
        return trim, s.landing_dv, v_entry
    sp, su = _depart(key, v_inf)
    return sp, su, 0.0


def _vrel_at_moon(planet: str, r_moon: float, v_inf_planet: float) -> float:
    """Speed relative to a moon needed to reach the planet's escape hyperbola (or come in on one)."""
    mu = PLANETS[planet][1]
    return math.sqrt(v_inf_planet**2 + 2 * mu / r_moon) - _circ(mu, r_moon)


def _is_moon(key: str) -> bool:
    return key != "leo" and SITES[key].parent != "sun"


def leg_dv(origin: str, dest: str) -> Leg:
    pa, pb = planet_of(origin), planet_of(dest)
    if pa == pb:
        mu = PLANETS[pa][1]
        r1, r2 = _orbit_radius_in_planet_frame(origin), _orbit_radius_in_planet_frame(dest)
        a_t = 0.5 * (r1 + r2)
        v1t = math.sqrt(mu * (2 / r1 - 1 / a_t))
        v2t = math.sqrt(mu * (2 / r2 - 1 / a_t))
        tof = math.pi * math.sqrt(a_t**3 / mu) / 86400
        dep_inf = abs(v1t - _circ(mu, r1))
        arr_inf = abs(v2t - _circ(mu, r2))
        # A planet-surface or LEO node departs from its low orbit; that burn is dep_inf itself.
        if _is_moon(origin):
            d_sp, d_su = _depart(origin, dep_inf)
        else:
            d_sp, d_su = dep_inf, (SITES[origin].ascent_dv or 0.0) if origin != "leo" else 0.0
        if _is_moon(dest):
            a_sp, a_su, v_entry = _arrive(dest, arr_inf)
        elif dest == "leo" or SITES[dest].aero:
            # Coming down to the planet: aerobrake from the transfer orbit's periapsis.
            v_entry = math.sqrt(mu * (2 / r2 - 1 / a_t)) if dest != "leo" else v2t
            a_sp = 0.0
            a_su = EARTH_RETURN_TO_LEO_DV if dest == "leo" else SITES[dest].landing_dv
        else:
            a_sp, a_su, v_entry = arr_inf, 0.0, 0.0
        synodic = 0.0
        # Burns inside one planet's system get a 5% margin rather than 10%.
        return Leg(origin, dest, 1.05 * (d_sp + a_sp), d_su + a_su, tof, synodic, v_entry)

    ra, rb = PLANETS[pa][0] * AU, PLANETS[pb][0] * AU
    a_t = 0.5 * (ra + rb)
    va, vb = _circ(MU_SUN, ra), _circ(MU_SUN, rb)
    vpa = math.sqrt(MU_SUN * (2 / ra - 1 / a_t))
    vpb = math.sqrt(MU_SUN * (2 / rb - 1 / a_t))
    vinf_a, vinf_b = abs(vpa - va), abs(vpb - vb)
    tof = math.pi * math.sqrt(a_t**3 / MU_SUN) / 86400
    pa_period = 2 * math.pi * math.sqrt(ra**3 / MU_SUN)
    pb_period = 2 * math.pi * math.sqrt(rb**3 / MU_SUN)
    synodic = 1 / abs(1 / pa_period - 1 / pb_period) / 86400

    va_rel = _vrel_at_moon(pa, SITES[origin].moon_orbit_m, vinf_a) if _is_moon(origin) else vinf_a
    vb_rel = _vrel_at_moon(pb, SITES[dest].moon_orbit_m, vinf_b) if _is_moon(dest) else vinf_b
    d_sp, d_su = _depart(origin, va_rel)
    a_sp, a_su, v_entry = _arrive(dest, vb_rel)
    return Leg(origin, dest, INTERPLANETARY_MARGIN * (d_sp + a_sp), d_su + a_su, tof, synodic, v_entry)


# ---------------------------------------------------------------------------
# network


@dataclass
class Network:
    ship: Ship
    nodes: list[str]
    hubs: list[str]  # nodes where the ship can be filled with local propellant
    legs: dict[tuple[str, str], Leg] = field(default_factory=dict)
    payload: dict[tuple[str, str], float] = field(default_factory=dict)


def full_hubs(min_local_fraction: float = 0.99) -> list[str]:
    """Sites whose ISRU chain makes the whole propellant load locally, plus LEO."""
    return ["leo"] + [k for k, s in SITES.items() if isru_plan(s).best.local_fraction >= min_local_fraction]


def build_network(ship: Ship | None = None, hubs: list[str] | None = None) -> Network:
    ship = ship or Ship()
    nodes = ["leo"] + list(SITES)
    net = Network(ship, nodes, hubs if hubs is not None else full_hubs())
    for a, b in itertools.permutations(nodes, 2):
        leg = leg_dv(a, b)
        net.legs[(a, b)] = leg
        net.payload[(a, b)] = ship.payload(leg.dv_space, leg.dv_surface)
    return net


@dataclass(frozen=True)
class Route:
    dest: str
    path: tuple[str, ...]
    bottleneck_payload_t: float  # least propulsive payload capacity over all hops (uncapped)
    dv_total: float
    tof_days: float
    direct_payload_t: float  # LEO to dest in one hop

    max_payload_t: float = 150.0

    @property
    def feasible(self) -> bool:
        return self.bottleneck_payload_t > 0

    @property
    def cargo_t(self) -> float:
        """Cargo per ship along the route, after the structural cap."""
        return max(min(self.bottleneck_payload_t, self.max_payload_t), 0.0)


def stepping_stone_routes(net: Network, max_stops: int = 3, min_gain_t: float = 5.0) -> dict[str, Route]:
    """Best path from LEO to every site through refuelling hubs.

    "Best" means the most cargo per ship (least hop capacity, capped by the
    structure); a route with more stops is kept only if it raises the cargo by
    at least `min_gain_t`, and among equal cargo the shorter trip wins.
    """
    routes: dict[str, Route] = {}
    inter = [h for h in net.hubs if h != "leo"]
    for dest in net.nodes:
        if dest == "leo":
            continue
        best: Route | None = None
        for n in range(0, max_stops + 1):
            for mids in itertools.permutations([h for h in inter if h != dest], n):
                path = ("leo", *mids, dest)
                hops = list(zip(path[:-1], path[1:]))
                bott = min(net.payload[h] for h in hops)
                dv = sum(net.legs[h].dv_total for h in hops)
                tof = sum(net.legs[h].tof_days for h in hops)
                cand = Route(dest, path, bott, dv, tof, net.payload[("leo", dest)], net.ship.max_payload_t)
                if best is None:
                    best = cand
                    continue
                gain = cand.cargo_t - best.cargo_t
                more_stops = len(path) > len(best.path)
                if (cand.cargo_t > 0 or best.cargo_t > 0):
                    better = gain >= min_gain_t if more_stops else gain > 1e-6
                    if not better and abs(gain) <= 1e-6 and not more_stops and tof < best.tof_days:
                        better = True
                else:  # nothing works: keep the route that comes closest
                    better = cand.bottleneck_payload_t > best.bottleneck_payload_t
                if better:
                    best = cand
        routes[dest] = best
    return routes


def tankers_for_leo_departure(net: Network, dest: str, payload_t: float) -> int:
    """Tanker launches to fill the ship in LEO for a hop to `dest` carrying `payload_t`."""
    leg = net.legs[("leo", dest)]
    need = net.ship.propellant_for(leg.dv_space, leg.dv_surface, payload_t)
    return math.ceil(max(need, 0.0) / net.ship.payload_to_leo_t)
