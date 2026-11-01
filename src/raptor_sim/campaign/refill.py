"""Phase 3: tanker launch campaign that refills the Mars ship in low Earth orbit.

Event-driven Monte Carlo of launches from several pads. The Mars ship launches
first and waits in orbit; each tanker docks and transfers what it brought up.
Every rate below is an estimate (SpaceX has not flown an operational refilling
campaign as of 2026-10-31) and is varied in the risk cases.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

import numpy as np


@dataclass(frozen=True)
class RefillPlan:
    pads: int = 2  # [est] Starbase plus one Florida pad
    pad_turnaround_days: float = 12.0  # [est] per pad between tanker launches
    launch_success: float = 0.97  # [est] per tanker flight
    failure_standdown_days: float = 30.0  # [est] all pads stop after a failure
    scrub_probability: float = 0.15  # [est] weather or technical scrub per attempt (1 day slip)
    transfer_loss: float = 0.02  # [est] fraction lost to chill-down and venting per transfer
    boiloff_per_day: float = 0.001  # [est] passive LEO boil-off, fraction of stored propellant per day
    lead_days: int = 75  # first launch (the Mars ship) this many days before the window opens
    max_tankers: int = 20


@dataclass
class RefillResult:
    on_time: np.ndarray  # bool per sample
    tankers_launched: np.ndarray
    departure_offset_days: np.ndarray  # days after window opening
    boiloff_kg: np.ndarray

    @property
    def p_on_time(self) -> float:
        return float(np.mean(self.on_time))


def refill_monte_carlo(plan: RefillPlan, window_open: date, window_days: int, required: Callable[[int], float],
                       ship_residual: float, delivery_samples: np.ndarray, n: int = 2000, seed: int = 5) -> RefillResult:
    """required(day_offset) gives the propellant the ship must hold at departure on that day (kg)."""
    rng = np.random.default_rng(seed)
    on_time = np.zeros(n, dtype=bool)
    launched = np.zeros(n, dtype=int)
    dep = np.full(n, np.nan)
    boil = np.zeros(n)
    for k in range(n):
        t = -float(plan.lead_days)  # days relative to window opening
        stored = ship_residual
        pad_free = [t + 2.0 + i * plan.pad_turnaround_days / plan.pads for i in range(plan.pads)]
        standdown_until = -1e9
        count = 0
        lost = 0.0
        while True:
            # Next launch: earliest available pad, after any stand-down.
            i = int(np.argmin(pad_free))
            t_next = max(pad_free[i], standdown_until)
            while rng.random() < plan.scrub_probability:
                t_next += 1.0
            # Can the ship leave before this launch? Check every day until then.
            day = max(t, 0.0)
            left = False
            while day <= min(max(t_next, 0.0), window_days):
                s_day = stored * (1 - plan.boiloff_per_day) ** (day - t)
                if day >= 0 and s_day >= required(int(day)):
                    lost += stored - s_day
                    on_time[k] = True
                    dep[k] = day
                    left = True
                    break
                day += 1.0
            if left or t_next > window_days or count >= plan.max_tankers:
                break
            decayed = stored * (1 - plan.boiloff_per_day) ** (t_next - t)
            lost += stored - decayed
            stored = decayed
            t = t_next
            count += 1
            if rng.random() < plan.launch_success:
                stored += rng.choice(delivery_samples) * (1 - plan.transfer_loss)
                pad_free[i] = t + plan.pad_turnaround_days
            else:
                standdown_until = t + plan.failure_standdown_days
                pad_free[i] = t + plan.pad_turnaround_days + plan.failure_standdown_days
        launched[k] = count
        boil[k] = lost
    return RefillResult(on_time, launched, dep, boil)


def window_from_launch_period(days: list[date]) -> tuple[date, int]:
    return days[0], (days[-1] - days[0]).days
