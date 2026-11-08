"""Bench metrics: the JSON evidence schema and the CI gates that read it.

The metrics JSON is designed so that a full harness run is a pure function of
its inputs: every field except translation latency is computed from simulation
state (deterministic by construction), and translation latency is measured
through the harness's injectable clock. With a deterministic clock the whole
document is byte-identical across runs — the property the harness determinism
test asserts. Under the default wall clock only the latency fields vary.

Gate thresholds implement the CI evidence table in ``docs/aegiscore/TESTING_PLAN.md``
§1 and the Phase I aims:

- translation p99 < 5 ms per command (a p99 at or over 5 ms fails the run);
- fail-safe transition latency ≤ 50 ms from fault onset to the mapped safe
  state, measured in simulation time;
- zero kinematic violations anywhere in the pipeline;
- 100% decision-logging completeness (one safety-log record per governor cycle);
- every fault-matrix scenario terminates in its defined safe state (at or
  below the mapped rung on the failover ladder);
- the advisory experiment pass (stub providers) observed advisory-driven
  margin descents — evaluated only when the advisory pass is enabled, which
  the default configuration always does.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from aegiscore.harness.advisory_exp import AdvisoryExperimentMetrics
from aegiscore.scal.instrumentation import LatencyReport

#: Translation p99 at or above this fails the run (Phase I aim: < 5 ms).
P99_TRANSLATION_LIMIT_NS = 5_000_000

#: Fail-safe transition latency above this fails the run (Phase I aim: ≤ 50 ms).
FAIL_SAFE_LIMIT_US = 50_000

#: The CI budget for a full corpus + fault-matrix run (TESTING_PLAN §1).
RUNTIME_BUDGET_S = 600.0

SCHEMA_VERSION = 2


@dataclass(frozen=True)
class GateReport:
    """Outcome of evaluating the CI evidence gates against one metrics dict."""

    passed: bool
    failures: tuple[str, ...]

    @property
    def gates(self) -> dict[str, bool]:
        names = (
            "translation_p99_under_5ms",
            "fail_safe_within_50ms",
            "no_kinematic_violations",
            "all_decisions_logged",
            "all_scenarios_in_defined_safe_state",
            "advisory_descents_observed",
        )
        return {name: name not in self.failures for name in names}


def evaluate_gates(
    *,
    p99_translation_ns: int,
    max_transition_latency_us: float | None,
    kinematic_violation_count: int,
    decision_logging_completeness: float,
    scenarios_in_defined_safe_state: int,
    scenario_count: int,
    advisory_descents: int | None = None,
) -> GateReport:
    """Pure gate evaluation — the same function the CI step and tests call.

    ``advisory_descents=None`` means the advisory experiment pass was disabled
    for this run; that gate is then not evaluated (the default configuration
    always enables the pass, so the CI evidence run always demonstrates it).
    """
    failures: list[str] = []

    if p99_translation_ns >= P99_TRANSLATION_LIMIT_NS:
        failures.append("translation_p99_under_5ms")
    if max_transition_latency_us is None or max_transition_latency_us > FAIL_SAFE_LIMIT_US:
        failures.append("fail_safe_within_50ms")
    if kinematic_violation_count != 0:
        failures.append("no_kinematic_violations")
    if decision_logging_completeness != 1.0:
        failures.append("all_decisions_logged")
    if scenarios_in_defined_safe_state != scenario_count:
        failures.append("all_scenarios_in_defined_safe_state")
    if advisory_descents is not None and advisory_descents == 0:
        failures.append("advisory_descents_observed")

    return GateReport(passed=not failures, failures=tuple(failures))


@dataclass(frozen=True)
class ScenarioRecord:
    """One fault-matrix scenario's outcome, in simulation time."""

    chassis: str
    fault: str
    onset_cycle: int
    arrival_cycle: int
    transition_latency_us: int
    mapped_safe_state: str
    final_mode: str
    in_defined_safe_state: bool
    steps: int
    logged_records: int
    kinematic_violations: int


@dataclass
class BenchmarkMetrics:
    """Aggregate evidence from one full harness run."""

    corpus_seed: int
    corpus_size: int
    sim_dt_us: int
    translation_latency_ns: LatencyReport | None
    translation_latency_by_chassis_ns: dict[str, LatencyReport] = field(default_factory=dict)
    corpus_steps: int = 0
    corpus_transitions: int = 0
    corpus_trajectories: int = 0
    fault_matrix_seed: int = 0
    scenarios: tuple[ScenarioRecord, ...] = ()
    step_calls: int = 0
    logged_records: int = 0
    violations: tuple[dict[str, float | int | str], ...] = ()
    advisory: AdvisoryExperimentMetrics | None = None

    # ------------------------------------------------------------ aggregates

    @property
    def max_transition_latency_us(self) -> float | None:
        if not self.scenarios:
            return None
        return max(s.transition_latency_us for s in self.scenarios)

    @property
    def kinematic_violation_count(self) -> int:
        return len(self.violations)

    @property
    def decision_logging_completeness(self) -> float:
        if self.step_calls == 0:
            return 0.0
        return self.logged_records / self.step_calls

    @property
    def scenarios_in_defined_safe_state(self) -> int:
        return sum(1 for s in self.scenarios if s.in_defined_safe_state)

    def summary(self) -> str:
        """One-line human summary for CI logs and completion notes."""
        tl = self.translation_latency_ns
        max_lat = self.max_transition_latency_us or -1
        text = (
            f"{self.corpus_trajectories} trajectories / {len(self.scenarios)} fault scenarios, "
            f"translation p50={tl.p50_ns}ns p99={tl.p99_ns}ns max={tl.max_ns}ns, "
            f"max transition={max_lat:.0f}us, "
            f"kinematic violations={self.kinematic_violation_count}, "
            f"decision logging={self.decision_logging_completeness:.1%}"
        )
        if self.advisory is not None:
            text += (
                f", advisory descents={self.advisory.advisory_descents}"
                f" ({self.advisory.descents_per_10k_cycles:.1f}/10k cycles),"
                f" stale rejections={self.advisory.rejected_stale}"
            )
        return text

    def to_dict(self) -> dict:
        """The canonical JSON shape (sort_keys at dump time keeps bytes stable)."""
        doc: dict = {
            "schema_version": SCHEMA_VERSION,
            "config": {
                "corpus_seed": self.corpus_seed,
                "corpus_size": self.corpus_size,
                "fault_matrix_seed": self.fault_matrix_seed,
                "sim_dt_us": self.sim_dt_us,
            },
            "corpus_runs": {
                "trajectories": self.corpus_trajectories,
                "governor_steps": self.corpus_steps,
                "fsm_transitions": self.corpus_transitions,
            },
            "decision_logging": {
                "step_calls": self.step_calls,
                "logged_records": self.logged_records,
                "completeness": self.decision_logging_completeness,
            },
            "kinematic_violations": {
                "count": self.kinematic_violation_count,
                "details": list(self.violations),
            },
            "translation_latency_ns": _latency_dict(self.translation_latency_ns),
            "translation_latency_by_chassis_ns": {
                model: _latency_dict(report)
                for model, report in sorted(self.translation_latency_by_chassis_ns.items())
            },
        }

        per_fault: dict[str, int] = {}
        for scenario in self.scenarios:
            worst = per_fault.get(scenario.fault)
            per_fault[scenario.fault] = max(worst or 0, scenario.transition_latency_us)
        doc["fail_safe"] = {
            "max_transition_latency_us": self.max_transition_latency_us,
            "per_fault_max_transition_latency_us": dict(sorted(per_fault.items())),
            "scenarios": len(self.scenarios),
            "scenarios_in_defined_safe_state": self.scenarios_in_defined_safe_state,
        }
        doc["fault_matrix_rows"] = [
            {
                "arrival_cycle": s.arrival_cycle,
                "chassis": s.chassis,
                "fault": s.fault,
                "final_mode": s.final_mode,
                "in_defined_safe_state": s.in_defined_safe_state,
                "kinematic_violations": s.kinematic_violations,
                "logged_records": s.logged_records,
                "mapped_safe_state": s.mapped_safe_state,
                "onset_cycle": s.onset_cycle,
                "steps": s.steps,
                "transition_latency_us": s.transition_latency_us,
            }
            for s in self.scenarios
        ]
        # null when the advisory pass was disabled for this run — explicit
        # "not run", distinct from a run that observed zero activity.
        doc["advisory"] = self.advisory.to_dict() if self.advisory is not None else None

        report = gate_report(self)
        gates = report.gates
        gates["all_pass"] = report.passed
        doc["gates"] = gates
        return doc


def gate_report(metrics: BenchmarkMetrics) -> GateReport:
    """Evaluate the CI gates against one metrics object (shared by CLI and JSON)."""
    return evaluate_gates(
        p99_translation_ns=(
            metrics.translation_latency_ns.p99_ns if metrics.translation_latency_ns else 0
        ),
        max_transition_latency_us=metrics.max_transition_latency_us,
        kinematic_violation_count=metrics.kinematic_violation_count,
        decision_logging_completeness=metrics.decision_logging_completeness,
        scenarios_in_defined_safe_state=metrics.scenarios_in_defined_safe_state,
        scenario_count=len(metrics.scenarios),
        advisory_descents=(
            metrics.advisory.advisory_descents if metrics.advisory is not None else None
        ),
    )


def metrics_to_json(metrics: BenchmarkMetrics) -> str:
    """Serialize metrics to the canonical byte-stable form."""
    return json.dumps(metrics.to_dict(), indent=2, sort_keys=True) + "\n"


def _latency_dict(report: LatencyReport | None) -> dict:
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
