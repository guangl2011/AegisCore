"""Fault taxonomy for the governor's fault-injection surface.

Production cycles pass ``fault=None``; the bench harness injects faults through
``GovernorCore.step(fault=...)`` to drive the fail-safe matrix. Faults that
cycle inputs express naturally (NaN sensors, stale heartbeats, spoofed command
envelopes) are also detected from the inputs themselves — the injection channel
exists so the harness can exercise each class deterministically.
"""

from __future__ import annotations

from enum import Enum


class Fault(Enum):
    """Fault classes the supervisor recognises."""

    SPOOFED_COMMAND = "spoofed_command"
    STALE_HEARTBEAT = "stale_heartbeat"
    SENSOR_LOSS = "sensor_loss"
    NETWORK_LOSS = "network_loss"
    WATCHDOG_MISS = "watchdog_miss"
    BRAKING_LOSS = "braking_loss"
    PROXIMITY_E_STOP = "proximity_e_stop"
    UNMODELED = "unmodeled"
