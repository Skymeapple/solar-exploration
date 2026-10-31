# Mars launch campaign: simulation and verification results

6 evaluation rounds (quick Monte Carlo iterations plus full verifications). Final verification: 13 of 13 objectives pass.

## Objectives (final verification)

| ID | Phase | Objective | Result | Limit | Pass | Note |
| --- | --- | --- | --- | --- | --- | --- |
| O1 | P1 ascent | Mars ship reaches 300 km orbit with 100 t cargo (Monte Carlo) | 0.997 probability | 0.99 | PASS | nominal residual 33.1 t |
| O2 | P1 ascent | Maximum dynamic pressure | 28.6 kPa | 35 | PASS | limit is an estimate (Falcon 9 class ~32 kPa) |
| O3 | P1 ascent | Gimbal angle to trim a 60 m/s crosswind at max-Q (control authority) | 0.411 deg | 15 | PASS |  |
| O4 | P2 booster return | Booster lands at the launch site with propellant left (Monte Carlo) | 1 probability | 0.99 | PASS | nominal margin 14.1% of reserve, miss 813 m; touchdown limit 3 m/s, miss limit 5 km (no terminal divert in L1); failures {} |
| O8 | P6 Mars EDL | Entry, descent and landing succeed under dispersions (Monte Carlo) | 1 probability | 0.99 | PASS | landing propellant used p99 112.0 t of 115 t loaded; failures {} |
| O9 | P6 Mars EDL | Entry corridor width (g and heating limits, no skip-out) | 3.3 deg | 0.6 | PASS | corridor (-13.4, -10.1); 0.6 deg = +/-3 sigma of the 0.1 deg delivery error |
| O6 | P4 TMI | Propellant needed in LEO fits the ship tanks (worst day of launch period) | 751 t | 1600 | PASS |  |
| O5 | P3 refilling | Ship is full and departs inside the launch period (Monte Carlo) | 0.998 probability | 0.95 | PASS | median 9 tanker launches, 95th pct 9 |
| O7 | P5 cruise | Trajectory correction delta-v, 99th percentile | 4.43 m/s | 30 | PASS |  |
| O10 | P8 Mars ascent | Return propellant made on Mars fits the tanks | 734 t | 1600 | PASS | ascent 3946 m/s, TEI 1980 m/s |
| O11 | P7 ISRU | Return propellant produced before the return window (Monte Carlo, dust storms) | 0.987 probability | 0.95 | PASS | 734 t needed in 383 days; 5th percentile production 765 t |
| O12 | P9 Earth entry | Earth entry within heating and g limits (Monte Carlo) | 0.997 probability | 0.99 | PASS | nominal 12.30 km/s, 152 W/cm2 vs 400, 3.3 g, corridor (-6.2, -5.6), failures {'g': 1} |
| O13 | Overall | End-to-end mission success (product of phase probabilities) | 0.978 probability | 0.9 | PASS | booster loss is an asset loss and is tracked by O4, not here |

## Iteration history

| Round | Failing objectives | Changes made |
| --- | --- | --- |
| 0 | O4, O8, O9, O11, O12, O13 | O4: booster return reserve 8% -> 10% of loaded propellant<br>O8: Mars landing propellant 60 t -> 70 t (failures {'crash': 60, 'propellant': 60, 'touchdown speed': 60})<br>O12: ablative windward heat shield on the return ship (+6 t) instead of a braking burn<br>O11: arrays capped at 40,000 m2; add 330 kWe of fission power so dust storms cannot stop production |
| 1 | O4, O8, O9, O11, O12, O13 | O4: booster return reserve 10% -> 12% of loaded propellant<br>O8: Mars landing propellant 70 t -> 85 t (failures {'crash': 60, 'propellant': 60, 'touchdown speed': 60})<br>O12: retarget Earth entry angle -6.0 -> -5.9 deg (corridor centre)<br>O11: arrays capped at 40,000 m2; add 360 kWe of fission power so dust storms cannot stop production |
| 2 | O4, O8, O13 | O4: booster return reserve 12% -> 14% of loaded propellant<br>O8: Mars landing propellant 85 t -> 100 t (failures {'crash': 26, 'propellant': 29, 'touchdown speed': 26}) |
| 3 | O8 | O8: Mars landing propellant 100 t -> 115 t (failures {'crash': 1, 'propellant': 1, 'touchdown speed': 1}) |
| 4 | none | (all pass) |
| 5 (full verification) | none | (all pass) |

## Mission timeline and key numbers

| Phase | Result |
| --- | --- |
| P1 ascent | Max-Q 28.6 kPa at Mach 1.34, 11.0 km; staging at 136 s, 57 km, 1432 m/s; orbit at 514 s. Gravity loss 2388 m/s, drag loss 10 m/s. Payload with tanker landing reserve: 103 t. Cargo ship arrives with 33 t propellant. |
| P2 booster return | Boostback 25 s, landing burn 42 s, 431 t used of 501 t reserve (14% margin), touchdown 1.0 m/s, 813 m from the pad. Reserve 14% of booster propellant. |
| P3 refilling | 723 t needed in LEO (751 t on the worst day). Each tanker delivers 97 t. 9 tanker launches median, 9 at 95%. P(on time) 0.998. Mean boil-off 39 t. Launch period 2028-11-08 to 2028-12-24. |
| P4 trans-Mars injection | Depart 2028-12-02, C3 8.9 km2/s2, 3603 m/s impulsive + 11 m/s gravity loss on 3 vacuum engines, 582 t burned. |
| P5 cruise | 320 days, arrive 2029-10-18. Correction delta-v 99th percentile 4.4 m/s (budget 30). |
| P6 Mars EDL | Entry 5.94 km/s at -12.0 deg, ballistic coefficient 587 kg/m2, peak 3.1 g and 44 W/cm2, corridor (-13.4, -10.1). Retropropulsion from 12.3 km; 104 t used nominal, 112 t at 99%, 115 t loaded. |
| P7 ISRU | 383 days on the surface. 7.6 kWh per kg of propellant [est]. 40,000 m2 arrays + 360 kWe fission. Needs 734 t; 5th percentile production 765 t. P(ready) 0.987. |
| P8 Mars ascent and TEI | Ascent 3946 m/s to a 300 km orbit, TEI 1980 m/s; depart 2030-11-05. |
| P9 Earth return | Arrive 2031-09-21 at 12.30 km/s, -5.9 deg; peak 3.3 g, 152 W/cm2 vs 400 limit, corridor (-6.2, -5.6). |
| Overall | P(mission success) 0.978 (product of phase probabilities). |

## Risks and mitigations (each checked in simulation)

| ID | Phase | Risk | Mitigation | Without mitigation | With mitigation | Verified |
| --- | --- | --- | --- | --- | --- | --- |
| R1 | P1/P2 | One booster engine fails 30 s after liftoff | Engine-out capability: the other 32 engines burn longer; return reserve sized with margin | No engine-out capability: abort, mission lost | orbit reached: True, ship residual 26.5 t; booster return margin 11.7% of reserve | yes |
| R2 | P1 | One ship sea-level engine fails 60 s after staging | Remaining five engines burn longer; cargo ship reaches orbit with less residual and takes one more tanker | Abort to a sub-orbital disposal | orbit reached: True, residual 28.6 t (nominal 33.1 t) | yes |
| R3 | P3 | Tanker flights less reliable (90%) and slower to turn around (20 days) | Third pad, campaign starts 40 days earlier, sunshade on the waiting ship | P(on time) 0.779 | P(on time) 0.983 | yes |
| R4 | P3 | Boil-off in LEO three times the estimate (0.3%/day) | Sunshade and insulation on the waiting ship (0.03%/day) [est] | P(on time) 0.989 | P(on time) 0.998 | yes |
| R5 | P4 | One vacuum engine fails at the start of trans-Mars injection | Fly on two vacuum engines (or add the three sea-level engines) and spend the 2% LEO margin | 2 RVac: 593 t burned vs 592 t nominal (gravity loss 26 m/s) | 2 RVac + 3 SL: 602 t; margin available 132 t | yes |
| R6 | P6 | Mars atmosphere density varies 35% (1-sigma) instead of 15%, e.g. during a dust storm | Steepen the entry to -12.4 deg with the final correction and carry 20 t more landing propellant when orbiters report thin air | P(EDL) 0.967 at -12.0 deg with 115 t | P(EDL) 0.993 at -12.4 deg with 135 t | yes |
| R7 | P6 | One of three landing engines fails to light | Design change: a fourth sea-level engine (+1.9 t) so one failure leaves three | 3 engines, one out: crashed=True, used 115 t, impact 592 m/s | 4 engines, one out: crashed=False, used 105 t of 115 t, touchdown 0.7 m/s | yes |
| R8 | P7 | Global dust storm during the surface stay (sunlight ~30% for 60-120 sols) | Fission power sized for a certain storm: 380 kWe (baseline 360 kWe) beside 40,000 m2 of arrays | solar only: P(ready) 0.000 | with 380 kWe fission: P(ready) 0.990 | yes |
| R9 | P9 | Earth entry at ~12.3 km/s overheats the tile heat shield | Ablative windward heat shield on the return ship (+6 t) [est rating 400 W/cm2] | peak 152 W/cm2 vs tile limit 100 W/cm2 | peak 152 W/cm2 vs ablator limit 400 W/cm2 | yes |

## Stress cases (whole campaign re-run, no redesign)

| Case | Objectives that fail | Tankers (median) | P(mission) |
| --- | --- | --- | --- |
| Isp 1% low on every engine | O1 (Mars ship reaches 300 km orbit with 100 t cargo (Monte Carlo)) | 9 | 0.909 |
| Ship dry mass +10 t | O1 (Mars ship reaches 300 km orbit with 100 t cargo (Monte Carlo)); O8 (Entry, descent and landing succeed under dispersions (Monte Carlo)); O13 (End-to-end mission success (product of phase probabilities)) | 10 | 0.827 |
| Booster reserve held at 12% | none | 8 | 0.990 |

## Sensitivity (deterministic, one change at a time)

| Case | Tanker delivery (t) | Tankers | LEO propellant (t) | Mars propellant (t) |
| --- | --- | --- | --- | --- |
| baseline | 95 | 8 | 723 | 734 |
| Isp -1% | 91 | 8 | 735 | 738 |
| Isp +1% | 103 | 7 | 712 | 719 |
| Ship dry +10 t | 87 | 9 | 742 | 766 |
| Ship dry -10 t | 104 | 7 | 705 | 690 |
| Booster reserve +2 pts | 88 | 8 | 723 | 734 |
| Landing propellant +20 t | 95 | 8 | 788 | 734 |
| Cargo +20 t | 95 | 8 | 762 | 734 |

![phases](phases.png)

![monte carlo](monte_carlo.png)

![porkchop](porkchop_2028.png)
