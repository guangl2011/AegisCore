"""Bench harness: the evidence engine integrating gateway, SCAL, governor, sim.

Pipeline per corpus command (nominal runs)::

    corpus TaskCommand -> zero-trust gateway (auth, lease, nonce)
        -> SCAL translate (latency-instrumented) -> ChassisCommand stream
        -> element plans -> governor-supervised simulation cycles
        -> executed twists -> violations / transitions / logging metrics

The bridge between SCAL's vocabulary (per-wheel ``ChassisCommand`` streams)
and the governor's vocabulary (body-speed supervision) is :func:`element_plan`
plus :func:`executed_twist`: each SCAL element is re-expressed as the body
twist its targets imply (``forward_twist``), the governor supervises the body
speed, and the simulator executes the *admitted* speed while tracking the
element's path curvature — so a filtered (slower) admission follows the same
path at reduced speed, exactly as a chassis tracking a decomposed path would.
For pure in-place rotations (differential/hybrid) the yaw rate executes only
under an unfiltered admission; any stop command halts rotation too.

Determinism: the simulator steps at a fixed ``dt_us``; scenario onsets are
sampled from a seeded ``random.Random``; commands are re-issued fresh each
cycle (a continuous command stream, as an upstream controller would emit);
the simulated host heartbeats every cycle. Translation latency is measured
through :class:`InstrumentedTranslator`'s injectable clock, so with a
deterministic clock the entire metrics document is byte-identical across runs.

The FSM transition latency reported in metrics is measured in *simulation
time* — fault onset to arrival at the fault class's mapped safe state (the
mapping the governor fault-injection suite asserts). Per-cycle wall-clock
decision latency is covered by the governor suite; it is deliberately excluded
from the metrics JSON to keep the document byte-stable.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from aegiscore.core.model import GovernorDecision, GovMode, TaskCommand
from aegiscore.gateway.auth import Certificate, TrustStore
from aegiscore.gateway.gateway import CommandEnvelope, ZeroTrustGateway
from aegiscore.governor import Fault, GovernorConfig, GovernorCore
from aegiscore.governor.fsm import LADDER
from aegiscore.harness.metrics import BenchmarkMetrics, ScenarioRecord
from aegiscore.scal.corpus import CORPUS_SEED, CORPUS_SIZE, Trajectory, build_corpus
from aegiscore.scal.instrumentation import (
    Clock,
    InstrumentedTranslator,
    LatencyRecorder,
)
from aegiscore.scal.kinematics import TwistSolution, forward_twist
from aegiscore.scal.profiles import REFERENCE_PROFILES, ScalProfile
from aegiscore.scal.translator import (
    BLADE_OFF,
    BLADE_ON,
    STEER_ANGLE,
    WHEEL_SPEED,
    ChassisCommand,
    Pose2D,
    SCALTranslator,
)
from aegiscore.sim import SIM_DT_US, ChassisSim, KinematicViolation

#: Seed for the fault-matrix onset sampler (same family as CORPUS_SEED).
FAULT_MATRIX_SEED = 20261102

#: Governor-vocabulary safe state per fault class — the mapping the governor
#: fault-injection suite (``tests/test_governor_faults.py`` matrix) asserts.
SAFE_STATES: dict[Fault, GovMode] = {
    Fault.SPOOFED_COMMAND: GovMode.CONTROLLED_STOP,
    Fault.STALE_HEARTBEAT: GovMode.HOLD,
    Fault.SENSOR_LOSS: GovMode.HOLD,
    Fault.NETWORK_LOSS: GovMode.CONTROLLED_STOP,
    Fault.WATCHDOG_MISS: GovMode.CONTROLLED_STOP,
    Fault.BRAKING_LOSS: GovMode.E_STOP,
    Fault.PROXIMITY_E_STOP: GovMode.E_STOP,
    Fault.UNMODELED: GovMode.CONTROLLED_STOP,
}

#: Proximity reading for the state-driven proximity e-stop scenario — inside
#: the default ``GovernorConfig.e_stop_radius_m`` (0.2 m).
PROXIMITY_SCENARIO_OBSTACLE_M = 0.15

# Twists with |omega| below this are treated as straight travel, matching the
# kinematics module's straight-travel epsilon.
_MOTION_EPS = 1e-9


@dataclass(frozen=True)
class ElementPlan:
    """Governor-and-sim execution plan for one SCAL ``ChassisCommand`` element."""

    source: str
    n_cycles: int
    is_motion: bool  # False for blade-only elements
    is_rotation: bool  # pure in-place spin (differential/hybrid only)
    v_mps: float  # requested body speed (0.0 for blade and rotation elements)
    omega_rad_s: float  # requested yaw rate (rotation elements) or 0.0
    kappa_inv_m: float  # path curvature tracked under speed filtering
    primitive: str  # governor-vocabulary primitive (motion elements)
    blade_on: bool = False
    blade_speed_rad_s: float = 0.0


@dataclass(frozen=True)
class TrajectoryRunResult:
    """Outcome of one nominal corpus trajectory."""

    trajectory_id: str
    model: str
    steps: int
    logged_records: int
    transitions: int
    violations: tuple[KinematicViolation, ...]


@dataclass(frozen=True)
class BreachSeed:
    """A one-cycle compromised-host actuator write that bypasses the governor.

    ``docs/aegiscore/TESTING_PLAN.md`` §1 requires the CI gates to be
    demonstrated red on a seeded violation before they are trusted green; this
    seed replays the exact threat AegisCore exists to stop — an upstream
    component writing the actuator bus directly while the supervisor cycles —
    and the executed-twist violation counter catches it.
    """

    speed_mps: float  # the over-limit body speed written directly to the sim
    trajectory_index: int = 0  # which corpus trajectory carries the breach
    cycle_offset: int = 0  # fires on the first motion cycle at or after this


@dataclass(frozen=True)
class BenchConfig:
    """Full-benchmark configuration; defaults are the CI evidence run."""

    corpus_seed: int = CORPUS_SEED
    corpus_size: int = CORPUS_SIZE
    sim_dt_us: int = SIM_DT_US
    fault_matrix_seed: int = FAULT_MATRIX_SEED
    #: Injectable nanosecond clock for translation latency. None = wall clock
    #: (the CI evidence run); a deterministic clock makes the metrics JSON
    #: byte-identical across runs (the harness determinism test).
    clock: Clock | None = None
    breach_seed: BreachSeed | None = None


# --------------------------------------------------------------- plan bridge


def element_plan(element: ChassisCommand, profile: ScalProfile, dt_us: int) -> ElementPlan:
    """Derive the simulator/governor plan for one SCAL command element."""
    n_cycles = max(1, round(element.duration_us / dt_us))
    blade_targets = [
        target
        for target in element.targets.values()
        if target.command_type in (BLADE_ON, BLADE_OFF)
    ]
    has_wheel_targets = any(
        target.command_type in (WHEEL_SPEED, STEER_ANGLE) for target in element.targets.values()
    )
    if blade_targets and not has_wheel_targets:
        target = blade_targets[0]
        return ElementPlan(
            source=element.source,
            n_cycles=n_cycles,
            is_motion=False,
            is_rotation=False,
            v_mps=0.0,
            omega_rad_s=0.0,
            kappa_inv_m=0.0,
            primitive=element.source.split(":")[0],
            blade_on=target.command_type == BLADE_ON,
            blade_speed_rad_s=target.value,
        )

    solution = TwistSolution(
        wheel_speeds={
            role: target.value
            for role, target in element.targets.items()
            if target.command_type == WHEEL_SPEED
        },
        steering_angles={
            role: target.value
            for role, target in element.targets.items()
            if target.command_type == STEER_ANGLE
        },
    )
    v, omega = forward_twist(profile, solution)
    is_rotation = abs(v) <= _MOTION_EPS and abs(omega) > _MOTION_EPS
    kappa = 0.0 if is_rotation or abs(v) <= _MOTION_EPS else omega / v
    return ElementPlan(
        source=element.source,
        n_cycles=n_cycles,
        is_motion=True,
        is_rotation=is_rotation,
        v_mps=v,
        omega_rad_s=omega,
        kappa_inv_m=kappa,
        primitive=element.source.split(":")[0],
    )


def executed_twist(plan: ElementPlan, decision: GovernorDecision) -> tuple[float, float]:
    """The body twist the chassis executes for one cycle under a governor decision.

    The governor admits (at most) a body speed; the executed yaw rate tracks
    the SCAL element's path curvature at that speed. No admitted drive command
    means no actuation — the chassis stands still for the cycle.
    """
    if not plan.is_motion:
        return 0.0, 0.0
    admitted = decision.admitted
    if admitted is None or admitted.command_type != "drive_speed":
        return 0.0, 0.0
    v = admitted.value
    if plan.is_rotation:
        # In-place spin only under an unfiltered admission; a stop command
        # (reason set) halts rotation as well.
        return v, (plan.omega_rad_s if decision.reason is None else 0.0)
    return v, plan.kappa_inv_m * v


def _cycle_step(
    sim: ChassisSim,
    governor: GovernorCore,
    plan: ElementPlan,
    now_us: int,
    fault: Fault | None = None,
    override_twist: tuple[float, float] | None = None,
) -> GovernorDecision:
    """One fixed-timestep cycle: state, governor decision, actuation.

    ``override_twist`` replaces the executed twist for the cycle (the seeded
    breach: the supervisor still cycles and logs, but its decision is not what
    reaches the actuators).
    """
    state = sim.make_state(now_us)
    if plan.is_motion:
        cmd = TaskCommand(
            primitive=plan.primitive, params={"target_speed": plan.v_mps}, issued_us=now_us
        )
    else:
        cmd = TaskCommand(
            primitive="SetBlade",
            params={"on": 1.0 if plan.blade_on else 0.0},
            issued_us=now_us,
        )
    decision = governor.step(state, cmd, now_us, fault=fault)
    if plan.is_motion:
        v, omega = override_twist if override_twist is not None else executed_twist(plan, decision)
        sim.integrate(v, omega)
    else:
        admitted = decision.admitted
        if admitted is not None and admitted.command_type == "blade_on":
            sim.set_blade(plan.blade_speed_rad_s)
        elif admitted is not None and admitted.command_type == "blade_off":
            sim.set_blade(0.0)
    return decision


# ----------------------------------------------------------- nominal corpus


class _ScalBridge:
    """The gateway's downstream boundary: hands admitted commands to SCAL."""

    def __init__(self, translator: InstrumentedTranslator, profile: ScalProfile) -> None:
        self._translator = translator
        self._profile = profile
        self.stream: list[ChassisCommand] | None = None

    def submit(self, command: TaskCommand, session_id: str) -> None:
        del session_id  # provenance only; the bench tracks it via the gateway
        # Corpus commands are expressed against the origin context pose (the
        # corpus contract); executed-motion composition is the simulator's job.
        self.stream = self._translator.translate(command, self._profile, Pose2D())


_BENCH_CA = Certificate(subject="bench-ca", issuer="bench-root", role="ca")
_BENCH_OPERATOR = Certificate(subject="bench-operator", issuer="bench-ca", role="operator")


def run_nominal_trajectory(
    traj: Trajectory,
    profile: ScalProfile,
    *,
    translator: InstrumentedTranslator,
    dt_us: int = SIM_DT_US,
    breach: BreachSeed | None = None,
) -> TrajectoryRunResult:
    """Run one corpus trajectory through gateway -> SCAL -> governor -> sim."""
    sim = ChassisSim(profile, dt_us)
    governor = GovernorCore(sim.governor_profile, GovernorConfig())
    bridge = _ScalBridge(translator, profile)
    gateway = ZeroTrustGateway(bridge, TrustStore(ca_certificates=frozenset({_BENCH_CA})))
    _, lease = gateway.open_session(_BENCH_OPERATOR, now_us=0)

    steps = 0
    cycle_index = 0
    breach_armed = breach is not None
    now_us = 0
    for cmd_index, cmd in enumerate(traj.commands):
        # Renew the session lease before it would lapse mid-trajectory; the
        # bench issues per-trajectory sessions, the gateway keeps the nonce
        # ledger across renewals.
        if now_us + dt_us >= lease.expires_us:
            _, lease = gateway.open_session(_BENCH_OPERATOR, now_us=now_us)
        envelope = CommandEnvelope(
            session_id=lease.session_id,
            nonce=f"{traj.trajectory_id}:{cmd_index}",
            sent_us=now_us,
            command=cmd,
        )
        gateway.submit(envelope, now_us)
        stream = bridge.stream
        if stream is None:  # pragma: no cover - the gateway submitted, by contract
            raise RuntimeError(f"{traj.trajectory_id}: command {cmd_index} never reached SCAL")

        for element in stream:
            plan = element_plan(element, profile, dt_us)
            for _ in range(plan.n_cycles):
                override: tuple[float, float] | None = None
                if (
                    breach is not None
                    and breach_armed
                    and plan.is_motion
                    and cycle_index >= breach.cycle_offset
                ):
                    override = (breach.speed_mps, 0.0)
                    breach_armed = False
                _cycle_step(sim, governor, plan, now_us, override_twist=override)
                steps += 1
                cycle_index += 1
                now_us += dt_us

    return TrajectoryRunResult(
        trajectory_id=traj.trajectory_id,
        model=profile.model,
        steps=steps,
        logged_records=len(governor.safety_log.records),
        transitions=len(governor.fsm_audit),
        violations=sim.violations,
    )


# ------------------------------------------------------------- fault matrix


def _at_or_below(mode: GovMode, target: GovMode) -> bool:
    """True when ``mode`` is ``target`` or deeper on the failover ladder."""
    return LADDER.index(mode) >= LADDER.index(target)


def _trajectory_plans(traj: Trajectory, profile: ScalProfile, dt_us: int) -> list[ElementPlan]:
    """Pre-translate a trajectory into element plans (uninstrumented)."""
    translator = SCALTranslator()
    plans: list[ElementPlan] = []
    for cmd in traj.commands:
        for element in translator.translate(cmd, profile, Pose2D()):
            plans.append(element_plan(element, profile, dt_us))
    return plans


def _onset_window(total_cycles: int) -> tuple[int, int]:
    """Fault onset window: after the mission is underway, before it ends."""
    low = max(1, total_cycles // 4)
    high = max(low + 1, (3 * total_cycles) // 4)
    return low, high


def run_fault_scenario(
    profile: ScalProfile,
    fault: Fault,
    plans: list[ElementPlan],
    *,
    dt_us: int = SIM_DT_US,
    onset_cycle: int,
) -> ScenarioRecord:
    """Inject one fault class mid-mission and record the fail-safe response.

    Seven classes inject through the governor's fault channel each cycle from
    onset; proximity e-stop is exercised through the state path (an obstacle
    inside the e-stop radius appears at onset). The scenario runs the full
    trajectory with the fault sustained, so the recorded final mode is the
    fail-safe outcome.
    """
    mapped = SAFE_STATES[fault]
    sim = ChassisSim(profile, dt_us)
    governor = GovernorCore(sim.governor_profile, GovernorConfig())

    arrival_cycle = -1
    steps = 0
    cycle_index = 0
    for plan in plans:
        for _ in range(plan.n_cycles):
            fault_arg: Fault | None = None
            if cycle_index >= onset_cycle:
                if fault is Fault.PROXIMITY_E_STOP:
                    sim.place_obstacle(PROXIMITY_SCENARIO_OBSTACLE_M)
                else:
                    fault_arg = fault
            _cycle_step(sim, governor, plan, now_us=cycle_index * dt_us, fault=fault_arg)
            if arrival_cycle < 0 and _at_or_below(governor.mode, mapped):
                arrival_cycle = cycle_index
            steps += 1
            cycle_index += 1

    final_mode = governor.mode
    logged_records = len(governor.safety_log.records)
    # A scenario that never reaches its mapped rung reports the full remaining
    # span as latency and fails the safe-state gate; the matrix unit tests
    # assert arrival explicitly.
    latency = (
        (arrival_cycle - onset_cycle) * dt_us
        if arrival_cycle >= 0
        else (steps - onset_cycle) * dt_us
    )
    return ScenarioRecord(
        chassis=profile.model,
        fault=fault.value,
        onset_cycle=onset_cycle,
        arrival_cycle=arrival_cycle,
        transition_latency_us=latency,
        mapped_safe_state=mapped.value,
        final_mode=final_mode.value,
        in_defined_safe_state=arrival_cycle >= 0 and _at_or_below(final_mode, mapped),
        steps=steps,
        logged_records=logged_records,
        kinematic_violations=len(sim.violations),
    )


def run_fault_matrix(
    corpus: list[Trajectory],
    *,
    dt_us: int = SIM_DT_US,
    seed: int = FAULT_MATRIX_SEED,
) -> tuple[ScenarioRecord, ...]:
    """Every fault class across all three reference chassis (3 x 8 scenarios)."""
    rng = random.Random(seed)
    records: list[ScenarioRecord] = []
    for profile in REFERENCE_PROFILES.values():
        traj = next(t for t in corpus if t.profile_name == profile.model)
        plans = _trajectory_plans(traj, profile, dt_us)
        total_cycles = sum(plan.n_cycles for plan in plans)
        low, high = _onset_window(total_cycles)
        for fault in Fault:
            onset = rng.randrange(low, high)
            records.append(
                run_fault_scenario(profile, fault, plans, dt_us=dt_us, onset_cycle=onset)
            )
    return tuple(records)


# --------------------------------------------------------------- benchmark


def run_benchmark(config: BenchConfig | None = None) -> BenchmarkMetrics:
    """Run the full evidence benchmark: corpus + fault matrix, aggregated."""
    cfg = config or BenchConfig()
    corpus = build_corpus(cfg.corpus_seed, cfg.corpus_size)
    translator = InstrumentedTranslator(clock=cfg.clock)

    corpus_steps = 0
    corpus_logged = 0
    corpus_transitions = 0
    violations: list[dict[str, float | int | str]] = []
    for index, traj in enumerate(corpus):
        profile = REFERENCE_PROFILES[traj.profile_name]
        breach = (
            cfg.breach_seed
            if cfg.breach_seed is not None and cfg.breach_seed.trajectory_index == index
            else None
        )
        result = run_nominal_trajectory(
            traj, profile, translator=translator, dt_us=cfg.sim_dt_us, breach=breach
        )
        corpus_steps += result.steps
        corpus_logged += result.logged_records
        corpus_transitions += result.transitions
        for violation in result.violations:
            violations.append(
                {
                    "chassis": result.model,
                    "detail": violation.detail,
                    "omega_rad_s": violation.omega_rad_s,
                    "step_index": violation.step_index,
                    "trajectory_id": result.trajectory_id,
                    "v_mps": violation.v_mps,
                }
            )

    by_model: dict[str, LatencyRecorder] = {}
    for sample in translator.recorder.samples:
        by_model.setdefault(sample.profile_model, LatencyRecorder()).record(sample)

    scenarios = run_fault_matrix(corpus, dt_us=cfg.sim_dt_us, seed=cfg.fault_matrix_seed)
    scenario_steps = sum(s.steps for s in scenarios)
    scenario_logged = sum(s.logged_records for s in scenarios)
    for record in scenarios:
        if record.kinematic_violations:
            violations.append(
                {
                    "chassis": record.chassis,
                    "detail": (
                        f"fault-matrix scenario {record.fault} executed an inadmissible twist"
                    ),
                    "omega_rad_s": 0.0,
                    "step_index": record.onset_cycle,
                    "trajectory_id": f"fault-matrix/{record.chassis}/{record.fault}",
                    "v_mps": 0.0,
                }
            )

    return BenchmarkMetrics(
        corpus_seed=cfg.corpus_seed,
        corpus_size=cfg.corpus_size,
        sim_dt_us=cfg.sim_dt_us,
        fault_matrix_seed=cfg.fault_matrix_seed,
        translation_latency_ns=translator.report(),
        translation_latency_by_chassis_ns={
            model: recorder.report() for model, recorder in by_model.items()
        },
        corpus_steps=corpus_steps,
        corpus_transitions=corpus_transitions,
        corpus_trajectories=len(corpus),
        scenarios=scenarios,
        step_calls=corpus_steps + scenario_steps,
        logged_records=corpus_logged + scenario_logged,
        violations=tuple(violations),
    )
