"""AegisCore bench harness: metrics, gates, and the evidence pipeline.

Public API:
- :class:`BenchConfig` / :func:`run_benchmark` — the full evidence benchmark.
- :func:`run_nominal_trajectory` / :func:`run_fault_scenario` /
  :func:`run_fault_matrix` — composable run entry points.
- :func:`element_plan` / :func:`executed_twist` — the SCAL->governor bridge.
- :class:`BreachSeed` — the seeded governor-bypass used to demonstrate the
  gates red (TESTING_PLAN §1).
- :class:`BenchmarkMetrics` / :func:`metrics_to_json` /
  :func:`evaluate_gates` / :func:`gate_report` — metrics and CI gates.
- :data:`RUNTIME_BUDGET_S`, :data:`P99_TRANSLATION_LIMIT_NS`,
  :data:`FAIL_SAFE_BUDGET_US` — the Phase I evidence thresholds.
- ``python -m aegiscore.harness`` — the CI entry point.
"""

from aegiscore.harness.metrics import (
    FAIL_SAFE_LIMIT_US,
    P99_TRANSLATION_LIMIT_NS,
    RUNTIME_BUDGET_S,
    BenchmarkMetrics,
    GateReport,
    LatencyReport,
    ScenarioRecord,
    evaluate_gates,
    gate_report,
    metrics_to_json,
)
from aegiscore.harness.runner import (
    FAULT_MATRIX_SEED,
    SAFE_STATES,
    BenchConfig,
    BreachSeed,
    ElementPlan,
    TrajectoryRunResult,
    element_plan,
    executed_twist,
    run_benchmark,
    run_fault_matrix,
    run_fault_scenario,
    run_nominal_trajectory,
)

__all__ = [
    "FAULT_MATRIX_SEED",
    "SAFE_STATES",
    "BenchConfig",
    "BreachSeed",
    "ElementPlan",
    "TrajectoryRunResult",
    "run_benchmark",
    "run_fault_matrix",
    "run_fault_scenario",
    "run_nominal_trajectory",
    "element_plan",
    "executed_twist",
    "BenchmarkMetrics",
    "GateReport",
    "LatencyReport",
    "ScenarioRecord",
    "evaluate_gates",
    "gate_report",
    "metrics_to_json",
    "RUNTIME_BUDGET_S",
    "P99_TRANSLATION_LIMIT_NS",
    "FAIL_SAFE_LIMIT_US",
]
