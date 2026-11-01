"""Published hydrogen/oxygen engine figures used to calibrate and check the model.

Sources (checked 2026-11-01):
  [RS25]  https://en.wikipedia.org/wiki/RS-25
  [RL10]  https://en.wikipedia.org/wiki/RL10
  [VINCI] https://en.wikipedia.org/wiki/Vinci_(rocket_engine)
  [BE7]   https://en.wikipedia.org/wiki/BE-7
  [mem]   value from memory of NASA/Aerojet literature, not re-checked online; low confidence

Use: RS-25 vacuum Isp is the only calibration target for the nozzle efficiency.
Every other number is an independent check the calibrated model must predict.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RefEngine:
    name: str
    cycle: str  # "staged" (fuel-rich staged combustion) or "expander" (closed expander)
    thrust_vac: float  # N
    isp_vac: float  # s
    pc: float  # Pa
    mixture_ratio: float
    eps: float
    mass: float  # kg dry
    isp_sl: float | None = None
    thrust_sl: float | None = None
    source: str = ""


RS_25 = RefEngine(
    "RS-25D (109%)", "staged", 2_279e3, 452.3, 206.4e5, 6.03, 69.0, 3_177.0, isp_sl=366.0, thrust_sl=1_860e3,
    source="[RS25]; area ratio 69 from the article text (the infobox says 78)",
)
RS_25_HPFTP_DISCHARGE = 45e6  # Pa, high-pressure fuel pump discharge [RS25]

RL10B_2 = RefEngine(
    "RL10B-2", "expander", 110.1e3, 465.5, 44.1e5, 5.88, 280.0, 301.0,
    source="[RL10]; chamber pressure 640 psia [mem]",
)
RL10C_1 = RefEngine(
    "RL10C-1", "expander", 101.5e3, 449.7, 42.0e5, 5.5, 130.0, 190.0,
    source="[RL10]; chamber pressure about 610 psia [mem]",
)
RL10A_4_2 = RefEngine(
    "RL10A-4-2", "expander", 99.0e3, 451.0, 42.0e5, 5.5, 84.0, 170.0,
    source="[RL10]; mixture ratio and chamber pressure [mem]",
)
VINCI = RefEngine("Vinci", "expander", 180e3, 457.2, 60e5, 6.1, 240.0, 550.0, source="[VINCI]")
BE_7_ISP_VAC = 460.0  # s [BE7], 44 kN dual expander, chamber pressure not published

ALL = (RS_25, RL10B_2, RL10C_1, RL10A_4_2, VINCI)

# Gate tolerances, the same as the methane engine's G3 and G7.
H3_ISP_TOLERANCE = 0.03
H7_TOLERANCE = 0.05
