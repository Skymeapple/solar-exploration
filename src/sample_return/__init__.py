"""End-to-end planetary sample return: architecture models and phase verification.

Phases, in mission order:

1. ``transfer``    interplanetary windows (Lambert solver on approximate ephemerides)
2. ``collection``  sample acquisition, tube sealing and the orbiting sample container
3. ``ascent``      Mars ascent vehicle trajectory (2D point mass, drag, two solid stages)
4. ``rendezvous``  orbiting-sample detection, approach and capture (Clohessy-Wiltshire)
5. ``entry``       Earth entry vehicle: heating, deceleration, footprint and impact
6. ``containment`` planetary protection fault tree (break-the-chain and containment)
7. ``campaign``    runs every phase and the verification gates SR-1 to SR-8
8. ``targets``     the same chain applied to Moon, Phobos, asteroid, comet and icy moons

Every number is tagged in its docstring or comment as one of:
  [cited]     taken from a public source named in ``references.py``
  [memory]    a public figure quoted from memory, not re-checked this study
  [estimate]  an engineering assumption made for this study
"""

__version__ = "0.1.0"
