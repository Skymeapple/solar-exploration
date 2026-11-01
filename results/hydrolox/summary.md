# Hydrogen/oxygen engine model: design points and verification

Calibration: eta_cstar 0.99, eta_cf 0.9873 (fitted to RS-25 vacuum Isp only); expander heat factor 0.410 on Bartz (fitted so RL10B-2 hydrogen leaves the jacket at 220 K).

## Gates

| Gate | Result | Detail |
| --- | --- | --- |
| H1 Thermochemistry | PASS | RS-25D (109%): Tc 3604 vs 3609 K (0.13%), MW 0.05%; RL10B-2: Tc 3417 vs 3422 K (0.13%), MW 0.05% |
| H2 Cycle balance | PASS | RS-25 fuel pump discharge 45.0 MPa vs 45.0 (0.1%), preburner 347 bar, pumps 73 MW; RL10B-2 closes True (turbine 220 K, PR 1.59); RL10C-1 closes True (turbine 193 K, PR 1.69); RL10A-4-2 closes True (turbine 194 K, PR 1.69); Vinci expander wall 57.7 bar vs flown 60 bar (3.8%) |
| H3 Performance | PASS | RS-25 sea level 372.9 vs 366.0 s (1.9%); vacuum is the calibration point; RL10B-2 470.3 vs 465.5 s (1.0%); RL10C-1 461.7 vs 449.7 s (2.7%); RL10A-4-2 455.6 vs 451.0 s (1.0%); Vinci 468.6 vs 457.2 s (2.5%) |
| H4 Design margins | PASS | HL-44 heat margin 17%, turbine 317 K; HL-250 (expander) heat margin 19%, turbine 216 K; HL-250 (staged combustion) fuel pump 366 bar |
| H5 Turbopumps | NOT RUN | component-level pump model exists for methane only (PR #2); not run |
| H6 Engine mass | NOT RUN | estimate only: thrust-to-weight of RL10C-1 (expander) or RS-25 (staged) |
| H7 Benchmark | PASS | HL-44 468.5 s vs BE-7 460.0 s (1.8%); HL-250 (expander) 458.8 s vs Vinci 457.2 s (0.3%); HL-250 (staged combustion) 464.1 s vs RS-25 452.3 s (2.6%) |

## Design points

| Engine | Cycle | Thrust vac (kN) | Pc (bar) | MR | Area ratio | Isp vac (s) | Isp for studies (s) | Exit D (m) | Mass est (kg) | Use |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| HL-44 | expander | 44 | 71.2 | 6.39 | 249 | 468.5 | 460.2 | 0.98 | 82 | crewed lunar hydrogen lander (9 engines), raptor_sim.crewed_lunar |
| HL-250 (expander) | expander | 250 | 48.5 | 6.27 | 120 | 458.8 | 450.6 | 1.98 | 468 | lunar hydrogen tanker / shuttle, raptor_sim.lunar_base.depot |
| HL-250 (staged combustion) | staged | 250 | 178.6 | 5.34 | 150 | 464.1 | 464.1 | 1.17 | 349 | alternative for the lunar tanker |

Isp for studies removes the mean +1.8% over-prediction the model shows on flown expander engines (H3).
Lunar studies read these values from `raptor_sim.hydrolox.study_isp()`.
