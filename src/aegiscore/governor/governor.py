"""Deterministic governor core — the only writer of actuator commands.

Every call to :meth:`GovernorCore.step` is one supervisor cycle: classify the
world, apply the failover ladder, project the requested command onto the safe
set (CBF/RG-style minimum-norm correction), admit at most one actuator command,
and append exactly one record to the safety log. A decision is a pure function
of the cycle inputs (state, cmd, now_us, fault) and the governor's own counters
— no wall-clock input beyond the latency measurement, no randomness.

Cycle precedence (first match wins):

1. Emergency faults — braking-authority loss, proximal e-stop — jump straight
   to E_STOP from any state.
2. Command-integrity violations (spoof), network loss, watchdog miss, and
   unmodeled faults descend toward CONTROLLED_STOP.
3. Stale heartbeat (lease lost) descends toward HOLD.
4. Sensor degradation is CONSERVATIVE; persistent loss descends toward HOLD.
5. Stale or malformed commands are rejected (logged) without moving the ladder.
6. Envelope filtering: proximity braking-distance barrier, kinetic-energy
   envelope, and mode gates (CONSERVATIVE speed cap, high-energy refusal).

A cycle with an active fault stops actuating immediately: upper-rung fault
cycles emit a zero-velocity (braking) drive command rather than passing task
traffic while the ladder walks down; HOLD emits zero velocity; CONTROLLED_STOP
emits bounded deceleration; E_STOP emits nothing (torque removal is the
independent hardware e-stop path).

``admitted=None`` means "no new actuation this cycle" — upstream software never
writes actuators, so None cannot smuggle a command past this module.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from math import isfinite, sqrt

from aegiscore.core.model import (
    ActuatorCommand,
    ChassisProfile,
    GovernorDecision,
    GovMode,
    RobotState,
    TaskCommand,
)
from aegiscore.governor.config import GovernorConfig
from aegiscore.governor.faults import Fault
from aegiscore.governor.fsm import FailoverFSM, TransitionAudit
from aegiscore.governor.safety_log import SafetyLog, SafetyLogRecord

TASK_PRIMITIVES = frozenset({"MoveTo", "FollowPath", "SetBlade", "Dock"})
MOTION_PRIMITIVES = frozenset({"MoveTo", "FollowPath", "Dock"})


class _Kind(Enum):
    NONE = "none"
    EMERGENCY = "emergency"
    DESCENT = "descent"


@dataclass(frozen=True)
class _Assessment:
    """Result of classifying one cycle's inputs. No mutation, no side effects."""

    kind: _Kind
    target: GovMode | None
    reason: str | None
    degraded_sensor: bool = False


class GovernorCore:
    """The deterministic safety supervisor for one chassis.

    Construct one per robot with the chassis' :class:`ChassisProfile` and a
    :class:`GovernorConfig` validated against its safety case. ``step`` is the
    single supervisor cycle and the only path by which actuator commands exist.
    """

    def __init__(self, profile: ChassisProfile, config: GovernorConfig | None = None) -> None:
        drive_id = profile.actuators.get("drive")
        if drive_id is None:
            raise ValueError("chassis profile must map a 'drive' actuator role")
        self._profile = profile
        self._cfg = config or GovernorConfig()
        self._fsm = FailoverFSM()
        self._log = SafetyLog()
        self._drive_id = drive_id
        self._blade_id = profile.actuators.get("blade")
        self._brake_id = profile.actuators.get("brake")
        self._ke_limit_j = (
            self._cfg.max_kinetic_energy_j
            if self._cfg.max_kinetic_energy_j is not None
            else 0.5 * self._cfg.chassis_mass_kg * profile.max_linear_speed**2
        )
        self._last_cycle_us: int | None = None
        self._mode_entered_us = 0
        self._degraded_cycles = 0
        self._healthy_cycles = 0
        self._blade_on = False
        self._seq = 0

    # ------------------------------------------------------------------ API

    @property
    def mode(self) -> GovMode:
        """Current rung of the failover ladder."""
        return self._fsm.mode

    @property
    def safety_log(self) -> SafetyLog:
        """The append-only decision log (one record per step call)."""
        return self._log

    @property
    def fsm_audit(self) -> tuple[TransitionAudit, ...]:
        """Every mode transition ever applied, with its trigger kind."""
        return self._fsm.audit

    def step(
        self,
        state: RobotState,
        cmd: TaskCommand | None,
        now_us: int,
        fault: Fault | None = None,
    ) -> GovernorDecision:
        """One deterministic supervisor cycle: validate, filter, decide, log."""
        t0 = time.perf_counter_ns()
        transition_from = self._fsm.mode
        assessment = self._classify(state, cmd, now_us, fault)

        if assessment.kind is _Kind.EMERGENCY:
            self._fsm.demand_emergency(assessment.reason)
            admitted, reason = None, assessment.reason
        elif assessment.kind is _Kind.DESCENT:
            self._fsm.demand_descend(assessment.target, assessment.reason)
            admitted, reason = self._safe_output(state, now_us), assessment.reason
        else:
            admitted, reason = self._supervise(state, cmd, now_us)

        if assessment.degraded_sensor:
            self._degraded_cycles += 1
        else:
            self._degraded_cycles = 0

        margins = self._margins(state, cmd, now_us)
        transition_to = self._fsm.mode if self._fsm.mode is not transition_from else None
        if transition_to is not None:
            self._mode_entered_us = now_us

        t1 = time.perf_counter_ns()
        self._log.append(
            SafetyLogRecord(
                seq=self._seq,
                timestamp_us=now_us,
                mode=self._fsm.mode,
                admitted_actuator_id=admitted.actuator_id if admitted else None,
                admitted_command_type=admitted.command_type if admitted else None,
                admitted_value=admitted.value if admitted else None,
                margins=dict(margins),
                reason=reason,
                transition_from=transition_from if transition_to is not None else None,
                transition_to=transition_to,
                latency_us=(t1 - t0) / 1000.0,
            )
        )
        self._seq += 1
        self._last_cycle_us = now_us
        return GovernorDecision(
            admitted=admitted,
            mode=self._fsm.mode,
            margins=margins,
            reason=reason,
        )

    def re_arm(self, operator_authorised: bool, now_us: int) -> bool:
        """Operator-authorised re-arm; only valid from CONTROLLED_STOP.

        E_STOP is deliberately not re-armable here — its "physical re-arm" is a
        hardware path outside the supervisor. Landing on CONSERVATIVE (not
        NOMINAL) keeps post-re-arm operation speed-capped until margins recover.
        """
        if not self._fsm.re_arm(operator_authorised):
            return False
        self._mode_entered_us = now_us
        self._healthy_cycles = 0
        self._degraded_cycles = 0
        return True

    # ------------------------------------------------------------ classification

    def _classify(
        self, state: RobotState, cmd: TaskCommand | None, now_us: int, fault: Fault | None
    ) -> _Assessment:
        """Map one cycle's inputs onto the fault taxonomy. First match wins."""
        cfg = self._cfg
        hb_age = now_us - state.last_heartbeat_us
        gap = now_us - self._last_cycle_us if self._last_cycle_us is not None else 0

        if fault is Fault.BRAKING_LOSS or self._braking_lost(state):
            return _Assessment(_Kind.EMERGENCY, None, "braking_authority_lost")
        if fault is Fault.PROXIMITY_E_STOP or self._proximity_estop(state):
            return _Assessment(_Kind.EMERGENCY, None, "proximal_e_stop")
        if fault is Fault.SPOOFED_COMMAND or self._spoofed(cmd, now_us):
            return _Assessment(_Kind.DESCENT, GovMode.CONTROLLED_STOP, "spoof_suspected")
        if fault is Fault.NETWORK_LOSS or hb_age > cfg.network_loss_timeout_us:
            return _Assessment(_Kind.DESCENT, GovMode.CONTROLLED_STOP, "network_loss")
        if fault is Fault.WATCHDOG_MISS or gap > cfg.watchdog_timeout_us:
            return _Assessment(_Kind.DESCENT, GovMode.CONTROLLED_STOP, "watchdog_miss")
        if fault is Fault.STALE_HEARTBEAT or hb_age > cfg.heartbeat_lease_us:
            if (
                self._fsm.mode is GovMode.HOLD
                and now_us - self._mode_entered_us > cfg.hold_timeout_us
            ):
                return _Assessment(_Kind.DESCENT, GovMode.CONTROLLED_STOP, "hold_timeout")
            return _Assessment(_Kind.DESCENT, GovMode.HOLD, "heartbeat_lease_lost")
        degraded, sensor = self._sensor_degraded(state)
        if fault is Fault.SENSOR_LOSS or degraded:
            persistent = self._degraded_cycles + 1 >= cfg.sensor_loss_persistent_cycles
            target = GovMode.HOLD if persistent else GovMode.CONSERVATIVE
            return _Assessment(
                _Kind.DESCENT, target, f"sensor_loss:{sensor}", degraded_sensor=True
            )
        if fault is Fault.UNMODELED:
            # Any fault without a dedicated mapping defaults to CONTROLLED_STOP,
            # never NOMINAL — the fail-safe default rule.
            return _Assessment(_Kind.DESCENT, GovMode.CONTROLLED_STOP, "unmodeled_fault")
        return _Assessment(_Kind.NONE, None, None)

    def _braking_lost(self, state: RobotState) -> bool:
        """Braking authority is gone when the brake actuator reports zero/none."""
        if self._brake_id is None:
            return False
        value = state.actuator_states.get(self._brake_id)
        return value is not None and isfinite(value) and value <= 0.0

    def _proximity_estop(self, state: RobotState) -> bool:
        d = state.nearest_obstacle_m
        return d is not None and isfinite(d) and d < self._cfg.e_stop_radius_m

    def _spoofed(self, cmd: TaskCommand | None, now_us: int) -> bool:
        """Command-integrity violations: impossible timestamps, unknown
        primitives, or non-finite parameters (NaN is an integrity failure, not
        a value)."""
        if cmd is None:
            return False
        if cmd.issued_us > now_us:
            return True
        if cmd.primitive not in TASK_PRIMITIVES:
            return True
        return any(not isfinite(v) for v in cmd.params.values())

    def _sensor_degraded(self, state: RobotState) -> tuple[bool, str]:
        """NaN/inf in any supervised measurement means sensor loss."""
        for key in ("x", "y", "theta"):
            value = state.pose.get(key)
            if value is None or not isfinite(value):
                return True, f"pose.{key}"
        if not isfinite(state.linear_velocity):
            return True, "linear_velocity"
        if not isfinite(state.angular_velocity):
            return True, "angular_velocity"
        if state.nearest_obstacle_m is not None and not isfinite(state.nearest_obstacle_m):
            return True, "proximity"
        for act_id, value in state.actuator_states.items():
            if not isfinite(value):
                return True, f"actuator:{act_id}"
        return False, ""

    # ------------------------------------------------------------- safe outputs

    def _safe_output(self, state: RobotState, now_us: int) -> ActuatorCommand | None:
        """The mode's stop-behaviour output while a fault is active.

        Upper-rung walk cycles brake immediately (zero velocity); CONTROLLED_STOP
        decelerates in a bounded way; E_STOP commands nothing at all.
        """
        mode = self._fsm.mode
        if mode is GovMode.E_STOP:
            return None
        if mode is GovMode.CONTROLLED_STOP:
            return self._stop_command(now_us, self._decel_target(state, now_us))
        return self._stop_command(now_us, 0.0)

    def _stop_command(self, now_us: int, v_target: float) -> ActuatorCommand:
        """One command per cycle: blade-off takes precedence over drive output."""
        if self._blade_on and self._blade_id is not None:
            self._blade_on = False
            return ActuatorCommand(self._blade_id, "blade_off", 0.0, now_us)
        return ActuatorCommand(self._drive_id, "drive_speed", v_target, now_us)

    def _decel_target(self, state: RobotState, now_us: int) -> float:
        """Bounded-deceleration velocity target for CONTROLLED_STOP."""
        return max(0.0, self._measured_v(state) - self._cfg.brake_decel_mps2 * self._dt(now_us))

    def _supervise(
        self, state: RobotState, cmd: TaskCommand | None, now_us: int
    ) -> tuple[ActuatorCommand | None, str | None]:
        """Healthy-world pipeline: recovery exits, command validation, gating, filter."""
        mode = self._fsm.mode

        if mode is GovMode.HOLD:
            # Classification guarantees the lease is fresh on a healthy cycle (a
            # stale lease would have been a DESCENT cycle): the table's recovery
            # exit applies directly.
            self._fsm.try_recover(GovMode.CONSERVATIVE, "heartbeat_lease_restored")
            mode = self._fsm.mode

        if mode is GovMode.CONTROLLED_STOP:
            return self._stop_command(now_us, self._decel_target(state, now_us)), "controlled_stop"
        if mode is GovMode.E_STOP:
            return None, "e_stop_terminal"

        return self._filter_command(state, cmd, now_us, mode)

    def _filter_command(
        self, state: RobotState, cmd: TaskCommand | None, now_us: int, mode: GovMode
    ) -> tuple[ActuatorCommand | None, str | None]:
        """Command validation, mode gates, and the minimum-norm safe projection."""
        if cmd is None:
            self._healthy_cycles += 1
            if mode is GovMode.CONSERVATIVE:
                self._maybe_recover_nominal()
            return None, "no_task_command"

        age = now_us - cmd.issued_us
        if age > self._cfg.max_command_age_us:
            # Upstream jitter: reject quietly, no ladder movement — sustained
            # upstream loss surfaces as the heartbeat/command-age faults instead.
            return None, "stale_command_rejected"

        if cmd.primitive == "SetBlade":
            return self._blade_supervise(cmd, now_us, mode)

        if "target_speed" not in cmd.params:
            return None, "malformed_command_rejected"
        v_req = cmd.params["target_speed"]
        v_hi = self._safe_velocity_hi(state, mode)
        v_lo = -self._cfg.reverse_speed_fraction * self._profile.max_linear_speed

        if v_hi <= 0.0:
            # The braking-distance barrier is infeasible: brake to rest now and
            # descend to CONSERVATIVE (spec table: "infeasible -> CONSERVATIVE").
            self._fsm.demand_descend(GovMode.CONSERVATIVE, "infeasible_safe_margin")
            self._healthy_cycles = 0
            return self._stop_command(now_us, 0.0), "infeasible_safe_margin"

        v_adm = min(max(v_req, v_lo), v_hi)
        if v_adm != v_req:
            # Minimum-norm correction: the closest admissible command in the
            # 1-D velocity space. Only ever descends NOMINAL -> FILTERED.
            self._fsm.demand_descend(GovMode.FILTERED, "min_norm_projection")
            self._healthy_cycles = 0
            cmd_out = ActuatorCommand(self._drive_id, "drive_speed", v_adm, now_us)
            return cmd_out, "min_norm_projection"

        # Unfiltered admission with positive margins: recovery path for FILTERED.
        self._healthy_cycles += 1
        if mode is GovMode.FILTERED:
            self._fsm.try_recover(GovMode.NOMINAL, "margins_recovered")
        if self._fsm.mode is GovMode.CONSERVATIVE:
            self._maybe_recover_nominal()
        return ActuatorCommand(self._drive_id, "drive_speed", v_req, now_us), None

    def _blade_supervise(
        self, cmd: TaskCommand, now_us: int, mode: GovMode
    ) -> tuple[ActuatorCommand | None, str | None]:
        if self._blade_id is None:
            return None, "no_blade_actuator"
        blade_on = cmd.params.get("on", 0.0) > 0.5
        if not blade_on:
            self._blade_on = False
            self._healthy_cycles += 1
            return ActuatorCommand(self._blade_id, "blade_off", 0.0, now_us), None
        if mode is GovMode.CONSERVATIVE:
            # CONSERVATIVE refuses high-energy primitives (spec table).
            return None, "high_energy_command_refused"
        self._blade_on = True
        self._healthy_cycles += 1
        if mode is GovMode.FILTERED:
            self._fsm.try_recover(GovMode.NOMINAL, "margins_recovered")
        return ActuatorCommand(self._blade_id, "blade_on", 1.0, now_us), None

    def _maybe_recover_nominal(self) -> None:
        """Table recovery exit: a healthy streak lifts CONSERVATIVE to NOMINAL."""
        if self._healthy_cycles >= self._cfg.conservative_recovery_cycles:
            self._fsm.try_recover(GovMode.NOMINAL, "recovery_streak")

    # ------------------------------------------------------------------ physics

    def _safe_velocity_hi(self, state: RobotState, mode: GovMode) -> float:
        """Highest admissible speed: the minimum of every binding envelope."""
        profile, cfg = self._profile, self._cfg
        v_cap = profile.max_linear_speed
        # Kinetic-energy envelope: v such that (1/2) m v^2 stays within the limit.
        v_cap = min(v_cap, sqrt(2.0 * self._ke_limit_j / cfg.chassis_mass_kg))
        # Proximity barrier (CBF): v such that braking keeps safe_margin_m of
        # stopping distance in front of the robot.
        d = state.nearest_obstacle_m
        if d is not None and isfinite(d):
            room = max(0.0, d - cfg.safe_margin_m)
            v_cap = min(v_cap, sqrt(2.0 * cfg.brake_decel_mps2 * room))
        if mode is GovMode.CONSERVATIVE:
            v_cap = min(v_cap, cfg.conservative_speed_fraction * profile.max_linear_speed)
        return max(0.0, v_cap)

    def _margins(
        self, state: RobotState, cmd: TaskCommand | None, now_us: int
    ) -> dict[str, float]:
        """Constraint margins (positive = remaining headroom) for the safety log."""
        cfg = self._cfg
        margins: dict[str, float] = {}

        def put(name: str, value: float) -> None:
            if isfinite(value):
                margins[name] = value

        v = self._measured_v(state)
        put("kinetic_energy_j", self._ke_limit_j - 0.5 * cfg.chassis_mass_kg * v * v)
        put("heartbeat_us", cfg.heartbeat_lease_us - (now_us - state.last_heartbeat_us))
        d = state.nearest_obstacle_m
        if d is not None:
            put("proximity_m", d - cfg.safe_margin_m)
        if self._blade_id is not None:
            blade_w = state.actuator_states.get(self._blade_id, 0.0)
            if isfinite(blade_w):
                put("blade_speed_rad_s", self._profile.max_wheel_speed - abs(blade_w))
        if cmd is not None:
            put("command_age_us", cfg.max_command_age_us - (now_us - cmd.issued_us))
            if "target_speed" in cmd.params and cmd.primitive in MOTION_PRIMITIVES:
                put(
                    "speed_mps",
                    self._safe_velocity_hi(state, self._fsm.mode) - cmd.params["target_speed"],
                )
        return margins

    def _measured_v(self, state: RobotState) -> float:
        return state.linear_velocity if isfinite(state.linear_velocity) else 0.0

    def _dt(self, now_us: int) -> float:
        if self._last_cycle_us is None:
            return self._cfg.cycle_dt_default_s
        return max(0.0, now_us - self._last_cycle_us) / 1_000_000.0
