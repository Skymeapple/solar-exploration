# Study summary

## Reference engine gates (Raptor 2 class)

| Gate | Result | Detail |
| --- | --- | --- |
| G0 Requirements | PASS | 100 t to Mars needs 782 t of propellant in LEO (6 tanker launches); return with 20 t needs 682 t made on Mars |
| G1 Thermochemistry | PASS | Tc CEA 3760 K vs Cantera 3764 K (0.10%); MW 22.62 vs 22.63 g/mol (0.04%) |
| G2 Cycle balance | PASS | fuel preburner 551 bar, pump 33.3 MW; ox preburner 710 bar, pump 52.4 MW |
| G3 Performance | PASS | Isp SL 326.3 s (0.23%), vac 348.2 s (0.34%); exit pressure 0.92 bar, separation margin 2.28 |
| G4 Cooling | PASS | 5/5 checks pass |
| G5 Turbopumps | PASS | 18/18 checks pass |
| G6 Engine system | PASS | 2/2 checks pass; dry mass 1,935 kg, sea-level thrust-to-weight 119 |
| G7 Benchmark | PASS | largest error Main chamber pressure 1.67%; sanity check: flow 705 kg/s vs quoted 650 (8%) |

## Optimizer (300 designs, 187 passed every gate)

| Quantity | Reference | Best found |
| --- | --- | --- |
| Chamber pressure (bar) | 300 | 314 |
| Mixture ratio | 3.60 | 3.46 |
| Area ratio | 34.3 | 37.2 |
| Oxygen-rich turbine inlet (K) | 800 | 837 |
| Fuel-rich turbine inlet (K) | 1000 | 1033 |
| Sea-level Isp (s) | 326.7 | 327.5 |
| Vacuum Isp (s) | 348.0 | 349.8 |
| Nozzle exit diameter (m) | 1.36 | 1.39 |
| Oxygen pump discharge (bar) | 888 | 968 |

Winner re-checked with independent chemistry: G1 Thermochemistry PASS (Tc CEA 3756 K vs Cantera 3760 K (0.10%); MW 22.28 vs 22.29 g/mol (0.04%)).

Why designs failed:

- G2 No power balance on the oxidizer shaft: 57
- nozzle too wide to package: 53
- G2 No power balance on the fuel and oxidizer shaft: 3
- G2 pump discharge over limit: 2

## Vehicle and Mars mission

| Quantity | Reference engine | Optimized engine |
| --- | --- | --- |
| Payload to LEO, reusable (t) | 131 | 133 |
| Liftoff thrust-to-weight | 1.32 | 1.32 |
| Vacuum engine Isp (s) | 362.7 | 362.3 |
| Trans-Mars injection from LEO (m/s) | 3951 | 3951 |
| Transfer time, minimum energy (days) | 259 | 259 |
| Propellant in LEO to land 100 t on Mars (t) | 782 | 781 |
| Tanker launches needed | 6 | 6 |
| Mars surface to Earth transfer (m/s) | 6401 | 6401 |
| Propellant made on Mars for return with 20 t (t) | 683 | 678 |
| Mission closes | yes | yes |

## Sensitivity: ship dry mass

| Ship dry mass (t) | Payload to LEO (t) | Tanker launches |
| --- | --- | --- |
| 100 | 133 | 6 |
| 125 | 108 | 8 |
| 150 | 83 | 12 |
| 175 | 58 | 18 |

SpaceX states about 100 t to LEO for Block 3. Raptor Vacuum is quoted at 380 s.
