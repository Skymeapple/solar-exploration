"""Physical constants and propellant data (SI units throughout)."""

G0 = 9.80665  # standard gravity, m/s^2
P_SEA_LEVEL = 101_325.0  # Pa
R_UNIVERSAL = 8.314462618  # J/(mol K)

# Liquid densities near the normal boiling point. Raptor runs subcooled
# propellants, which are denser; these are conservative for pump power.
RHO_LOX = 1141.0  # kg/m^3 at 90 K
RHO_LCH4 = 422.6  # kg/m^3 at 111.6 K

# Enthalpy of each liquid propellant at its boiling point minus the ideal gas
# at 298.15 K, used by the independent Cantera cross-check. Values match the
# NASA CEA thermo library entries O2(L) and CH4(L).
DH_LOX_J_PER_MOL = -12_979.0
DH_LCH4_J_PER_MOL = -89_233.0 + 74_600.0
MW_O2 = 0.0319988  # kg/mol
MW_CH4 = 0.0160425  # kg/mol
