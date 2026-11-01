"""Component-level design of the Raptor-class engine (fidelity L1/L2).

Thrust chamber and nozzle contour, regenerative cooling, main injector, turbopumps,
preburners, lines and valves, mass roll-up and bill of materials, drawings, and the
verification and iteration loop that ties them together. Entry points:

    from raptor_sim.components import design_io
    from raptor_sim.components.assembly import build_engine
    from raptor_sim.components.verification import all_checks

    b = build_engine(design_io.load())
    checks = all_checks(b)
"""
