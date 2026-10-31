"""Crewed lunar landing and return missions.

Modules:
  reference     cited figures (Apollo, Orion, Starship HLS, Blue Moon, NASA trajectory papers)
  legs          patched-conic cislunar delta-v and Earth entry speed
  landing       powered descent and ascent simulation for any lander
  architecture  end-to-end sizing of NRHO, LLO, direct-ship and reusable ISRU architectures
  earth_return  entry at lunar return speed (uses raptor_sim.crew.entry when present)
"""
