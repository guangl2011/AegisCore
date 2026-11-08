"""Governor configuration thresholds.

All timing values are monotonic microseconds; all physical values are SI.
Defaults are engineering placeholders for the MVP bench harness — a deployment
must validate them against the chassis safety case before use.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GovernorConfig:
    """Deterministic thresholds for one governor instance."""

    max_command_age_us: int = 50_000
    """Commands older than this are rejected as stale (upstream jitter guard)."""

    heartbeat_lease_us: int = 100_000
    """Host heartbeat older than this loses the lease -> HOLD (stale heartbeat)."""

    network_loss_timeout_us: int = 500_000
    """Heartbeat older than this is treated as network loss -> CONTROLLED_STOP."""

    watchdog_timeout_us: int = 20_000
    """Gap between supervisor cycles beyond this is a watchdog miss."""

    hold_timeout_us: int = 2_000_000
    """Sustained HOLD beyond this descends toward CONTROLLED_STOP."""

    sensor_loss_persistent_cycles: int = 3
    """Consecutive degraded-sensor cycles before the loss counts as persistent (-> HOLD)."""

    conservative_speed_fraction: float = 0.3
    """Speed cap fraction applied while in CONSERVATIVE mode."""

    conservative_recovery_cycles: int = 10
    """Consecutive healthy cycles in CONSERVATIVE before automatic recovery to NOMINAL."""

    e_stop_radius_m: float = 0.2
    """Obstacle distance below which proximity triggers immediate E_STOP."""

    safe_margin_m: float = 0.5
    """Obstacle distance the braking-distance filter keeps in front of the robot."""

    brake_decel_mps2: float = 1.5
    """Assured deceleration used by the safe-velocity (RG) computation and controlled stop."""

    chassis_mass_kg: float = 60.0
    """Driven mass used by the kinetic-energy envelope."""

    max_kinetic_energy_j: float | None = None
    """Translational kinetic-energy limit; None derives it from max_linear_speed at construction."""

    reverse_speed_fraction: float = 0.3
    """Reverse speed cap fraction (the proximity barrier supervises forward motion)."""

    cycle_dt_default_s: float = 1e-3
    """dt assumed for deceleration shaping on the first cycle after (re)start."""

    advisory_max_age_ns: int = 100_000_000
    """
    Maximum age (time.monotonic_ns) of an advisory constraint before it counts
    as stale and is rejected/expired — advisory staleness is treated like any
    stale sensor input: no ladder movement, no margin effect.
    """
