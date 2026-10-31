# Study summary

## Reference engine gates (Raptor 2 class)

| Gate | Result | Detail |
| --- | --- | --- |
| G0 Requirements | PASS | 100 t to Mars needs 546 t of propellant in LEO (4 tanker launches); return with 20 t needs 642 t made on Mars |
| G1 Thermochemistry | PASS | Tc CEA 3762 K vs Cantera 3766 K (0.10%); MW 22.63 vs 22.64 g/mol (0.04%) |
| G2 Cycle balance | PASS | fuel preburner 569 bar, pump 34.3 MW; ox preburner 772 bar, pump 56.9 MW |
| G3 Performance | PASS | Isp SL 326.7 s (0.10%), vac 348.0 s (0.29%); exit pressure 0.95 bar, separation margin 2.34 |
| G4 Cooling | not run | regenerative cooling model not built yet |
| G5 Turbopumps | not run | pump detail model not built yet |
| G6 Engine system | not run | mass model not built yet |
| G7 Benchmark | PASS | largest error Vacuum specific impulse, sea-level nozzle 0.29%; sanity check: flow 704 kg/s vs quoted 650 (8%) |

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
| Payload to LEO, reusable (t) | 155 | 158 |
| Liftoff thrust-to-weight | 1.31 | 1.31 |
| Vacuum engine Isp (s) | 362.7 | 362.3 |
| Trans-Mars injection from LEO (m/s) | 3951 | 3951 |
| Transfer time, minimum energy (days) | 259 | 259 |
| Propellant in LEO to land 100 t on Mars (t) | 546 | 546 |
| Tanker launches needed | 4 | 4 |
| Mars surface to Earth transfer (m/s) | 6401 | 6401 |
| Propellant made on Mars for return with 20 t (t) | 642 | 638 |
| Mission closes | yes | yes |

## Sensitivity: ship dry mass

| Ship dry mass (t) | Payload to LEO (t) | Tanker launches |
| --- | --- | --- |
| 100 | 158 | 4 |
| 125 | 133 | 5 |
| 150 | 108 | 7 |
| 175 | 83 | 9 |

SpaceX states about 100 t to LEO for Block 3. Raptor Vacuum is quoted at 380 s.
