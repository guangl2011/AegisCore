"""Advisory-layer latency/coverage experiment — the harness's stub advisory pass.

Spec design update (Nov 2026, deliverable 7): the pitch's fourth research
question — *"Can perception-driven advisory signals narrow safety margins fast
enough to be operationally useful without ever touching the command path?"* —
must be answerable from harness output. This module answers the measurable
half of it: it re-runs the seeded corpus and fault matrix with a deterministic
**stub** advisory provider wired into the governor's consumption path and
emits, into the evidence-gates JSON:

- **issuance latency** (p50/p99/...) — one sample per stub ``poll()``;
- **consumption latency** — one sample per ``GovernorCore.on_advisory`` call;
- **margin-descent coverage** — FSM descents whose reason starts with
  ``advisory:`` (how often advisory inputs actually drive FILTERED /
  CONSERVATIVE descents), per 10k governor cycles;
- **staleness rejections** — offers the governor's intake-time freshness
  check refused (the stub schedules one stale offer every ``stale_window``
  polls; ``stale_age_ns`` exceeds the governor default ``advisory_max_age_ns``,
  so every stale offer is deterministically rejected).

Stub providers only: the experiment imports ``aegiscore.advisory`` (the
harness is not a protected core) but never physicalai/OpenVINO/onnxruntime —
CI needs no inference runtime and no network. Timing uses the harness's
injectable clock, and every non-latency value is a pure function of sim
state, so with a deterministic clock the advisory block is byte-stable like
the rest of the metrics document.

The simulated monotonic timeline: the governor stamps and checks advisory
freshness against ``time.monotonic_ns()``-style values. The experiment derives
that timeline from simulation time — ``now_monotonic_ns = now_us * 1_000`` —
so freshness behaviour is deterministic under both the wall and deterministic
latency clocks. The real advisory layer stamps ``time.monotonic_ns()``; the
simulated timeline exercises the identical governor code path.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from time import perf_counter_ns

from aegiscore.advisory.constraints import AdvisoryConstraint, AdvisoryKind
from aegiscore.governor.fsm import TransitionAudit
from aegiscore.governor.governor import GovernorCore
from aegiscore.scal.instrumentation import Clock, LatencyRecorder, LatencyReport, LatencySample

#: Seed for the stub provider's severity schedule (same family as the corpus
#: and fault-matrix seeds).
ADVISORY_EXPERIMENT_SEED = 20261107

#: Simulated-monotonic timestamp of a deliberately stale offer. Exceeds the
#: governor's default ``advisory_max_age_ns`` (100 ms) by 2x, so the intake
#: freshness check rejects it at any sim time.
STALE_AGE_NS = 200_000_000

#: Prefix the governor puts on every advisory-driven descent reason.
ADVISORY_REASON_PREFIX = "advisory:"

#: The simulated monotonic timeline is simulation time expressed in ns —
#: freshness is a pure function of sim state (see module docstring).
SIM_MONOTONIC_NS_PER_US = 1_000


@dataclass(frozen=True)
class AdvisoryExperimentConfig:
    """Knobs of the advisory pass. Defaults are the CI evidence run."""

    seed: int = ADVISORY_EXPERIMENT_SEED
    poll_every_cycles: int = 5
    """Poll cadence: one provider poll every *k* governor cycles."""

    quiet_rate: float = 0.55
    """Fraction of polls that yield no constraint (the perception layer saw
    nothing worth reporting — the common case in the field)."""

    zero_margin_rate: float = 0.35
    """Fraction of *emitted* constraints at severity 1.0 — zero remaining
    margin, the only severity that drives a FILTERED descent."""

    stale_window: int = 11
    """One poll in *k* offers a deliberately stale constraint (see
    :data:`STALE_AGE_NS`) so the freshness-rejection path is exercised and
    measured in every evidence run."""

    model_ref: str = f"stub/advisory-bench@{'a' * 40}"
    """Pinned artifact reference stamped on every stub constraint."""


class StubAdvisoryProvider:
    """Deterministic poll-only provider standing in for the OpenVINO backend.

    Same poll-only, command-free shape as the runtime providers (the
    ``AdvisoryProvider`` protocol): ``poll()`` returns at most one
    :class:`AdvisoryConstraint`, severity drawn from a seeded schedule.
    ``stamp_ns`` is the *simulated* monotonic time at poll — injected by the
    wiring so freshness is a function of sim state, not the wall clock.
    """

    device = "stub"
    degraded = False

    def __init__(self, config: AdvisoryExperimentConfig) -> None:
        self._cfg = config
        self._rng = random.Random(config.seed)

    def poll(self, *, stamp_ns: int) -> tuple[AdvisoryConstraint, ...]:
        roll = self._rng.random()
        if roll < self._cfg.quiet_rate:
            return ()
        severity_roll = self._rng.random()
        if severity_roll < self._cfg.zero_margin_rate:
            severity = 1.0
        else:
            severity = 0.1 + 0.8 * severity_roll
        return (
            AdvisoryConstraint(
                kind=AdvisoryKind.PROXIMITY_MARGIN,
                severity=severity,
                source_model=self._cfg.model_ref,
                issued_monotonic_ns=stamp_ns,
            ),
        )

    def close(self) -> None:
        return None


class AdvisoryWiring:
    """Drives the stub advisory path one governor cycle at a time.

    Called by the run pipelines *before* each governor cycle: polls the stub
    provider on its cadence, feeds any constraint (plus a scheduled stale
    offer) to ``governor.on_advisory``, and records latency, intake, and
    descent counters. Purely observational — it never touches the command
    path, and the only call it makes into the governor is ``on_advisory``,
    which has no API to produce or modify an actuator command.
    """

    def __init__(self, config: AdvisoryExperimentConfig, *, clock: Clock | None = None) -> None:
        self._cfg = config
        self._clock: Clock = clock if clock is not None else perf_counter_ns
        self._provider = StubAdvisoryProvider(config)
        self._issuance = LatencyRecorder()
        self._consumption = LatencyRecorder()
        self.cycles = 0
        self.polls = 0
        self.offered = 0
        self.accepted = 0
        self.rejected_stale = 0
        self.descents = 0
        self.descents_by_target: dict[str, int] = {}

    # ------------------------------------------------------------- per cycle

    def before_cycle(self, governor: GovernorCore, now_monotonic_ns: int) -> None:
        """One advisory observation opportunity before a governor cycle."""
        self.cycles += 1
        if self.cycles % self._cfg.poll_every_cycles != 0:
            return
        self.polls += 1

        start = self._clock()
        constraints = self._provider.poll(stamp_ns=now_monotonic_ns)
        self._issuance.record(
            LatencySample(
                primitive="advisory_poll", profile_model=self._provider.device,
                duration_ns=self._clock() - start,
            )
        )

        stale_offer = self.polls % self._cfg.stale_window == 0
        if stale_offer and not constraints:
            # Force the scheduled stale offer even on a quiet poll so the
            # stale-offer path is exercised in every evidence run. (Whether a
            # stale offer is actually rejected stays measured: one landing in
            # a run's first freshness window is genuinely fresh and accepted.)
            constraints = (
                AdvisoryConstraint(
                    kind=AdvisoryKind.PROXIMITY_MARGIN,
                    severity=0.5,
                    source_model=self._cfg.model_ref,
                    issued_monotonic_ns=now_monotonic_ns,
                ),
            )
        for constraint in constraints:
            if stale_offer:
                # Rewrite the offer stale: the constraint the governor sees is
                # older than its freshness window by construction (clamped at
                # zero — stamps are non-negative; with the default 10 ms sim
                # step the first stale poll sits far past the freshness window
                # either way, so every stale offer is rejected).
                constraint = replace(
                    constraint,
                    issued_monotonic_ns=max(0, now_monotonic_ns - STALE_AGE_NS),
                )
            self.offered += 1
            start = self._clock()
            accepted = governor.on_advisory(constraint, now_monotonic_ns=now_monotonic_ns)
            self._consumption.record(
                LatencySample(
                    primitive="on_advisory", profile_model=self._provider.device,
                    duration_ns=self._clock() - start,
                )
            )
            if accepted:
                self.accepted += 1
            else:
                # The stub never emits malformed input, so every rejection is
                # the freshness gate refusing a stale constraint.
                self.rejected_stale += 1

    def collect(self, governor: GovernorCore) -> None:
        """Fold one finished run's FSM audit into the descent counters."""
        for audit in governor.fsm_audit:
            self._count_descent(audit)

    def _count_descent(self, audit: TransitionAudit) -> None:
        if audit.reason is None or not audit.reason.startswith(ADVISORY_REASON_PREFIX):
            return
        self.descents += 1
        target = audit.to_mode.value
        self.descents_by_target[target] = self.descents_by_target.get(target, 0) + 1

    # ------------------------------------------------------------- reporting

    def metrics(self) -> AdvisoryExperimentMetrics:
        return AdvisoryExperimentMetrics(
            device=self._provider.device,
            degraded=self._provider.degraded,
            polls=self.polls,
            constraints_offered=self.offered,
            accepted=self.accepted,
            rejected_stale=self.rejected_stale,
            governor_cycles=self.cycles,
            advisory_descents=self.descents,
            descents_by_target=dict(sorted(self.descents_by_target.items())),
            issuance_latency_ns=(
                self._issuance.report() if self._issuance.samples else None
            ),
            consumption_latency_ns=(
                self._consumption.report() if self._consumption.samples else None
            ),
        )


@dataclass
class AdvisoryExperimentMetrics:
    """Aggregate outcome of the advisory pass over corpus + fault matrix."""

    device: str
    degraded: bool
    polls: int
    constraints_offered: int
    accepted: int
    rejected_stale: int
    governor_cycles: int
    advisory_descents: int
    descents_by_target: dict[str, int] = field(default_factory=dict)
    issuance_latency_ns: LatencyReport | None = None
    consumption_latency_ns: LatencyReport | None = None

    @property
    def descents_per_10k_cycles(self) -> float:
        if self.governor_cycles == 0:
            return 0.0
        return self.advisory_descents * 10_000.0 / self.governor_cycles

    def to_dict(self) -> dict:
        return {
            "provider": {"device": self.device, "degraded": self.degraded},
            "polls": self.polls,
            "constraints_offered": self.constraints_offered,
            "accepted": self.accepted,
            "rejected_stale": self.rejected_stale,
            "descent_coverage": {
                "advisory_descents": self.advisory_descents,
                "by_target_mode": dict(self.descents_by_target),
                "governor_cycles": self.governor_cycles,
                "descents_per_10k_cycles": self.descents_per_10k_cycles,
            },
            "issuance_latency_ns": _report_dict(self.issuance_latency_ns),
            "consumption_latency_ns": _report_dict(self.consumption_latency_ns),
        }


def _report_dict(report: object) -> dict:
    if report is None:
        return {"count": 0}
    return {
        "count": report.count,
        "mean_ns": report.mean_ns,
        "min_ns": report.min_ns,
        "p50_ns": report.p50_ns,
        "p99_ns": report.p99_ns,
        "max_ns": report.max_ns,
    }
