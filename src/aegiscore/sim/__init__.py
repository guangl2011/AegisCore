"""Sim: deterministic kinematic chassis simulation (the bench "hardware").

Public API: the fixed-timestep :class:`ChassisSim` for the three reference
chassis and the :class:`KinematicViolation` record. The simulator draws no
randomness and reads no clock — determinism is its contract.
"""

from aegiscore.sim.simulator import SIM_DT_US, ChassisSim, KinematicViolation

__all__ = [
    "SIM_DT_US",
    "ChassisSim",
    "KinematicViolation",
]
