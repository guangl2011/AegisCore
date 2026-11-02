"""CI entry point: ``python -m aegiscore.harness``.

Runs the full evidence benchmark (corpus + fault matrix), writes the metrics
JSON snapshot, and exits nonzero when any CI gate fails — the workflow's
``timeout-minutes: 10`` is the runtime-budget enforcement (TESTING_PLAN §1).
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from aegiscore.harness.metrics import (
    RUNTIME_BUDGET_S,
    gate_report,
    metrics_to_json,
)
from aegiscore.harness.runner import BenchConfig, run_benchmark
from aegiscore.scal.corpus import CORPUS_SIZE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aegiscore-harness",
        description="AegisCore bench harness: corpus + fault matrix + CI gates.",
    )
    parser.add_argument(
        "--output",
        default="bench/metrics-snapshot.json",
        help="path for the generated metrics JSON snapshot",
    )
    parser.add_argument(
        "--corpus-size",
        type=int,
        default=CORPUS_SIZE,
        help="number of corpus trajectories (default: the full 100)",
    )
    args = parser.parse_args(argv)

    started = time.perf_counter()
    metrics = run_benchmark(BenchConfig(corpus_size=args.corpus_size))
    elapsed = time.perf_counter() - started

    report = gate_report(metrics)
    payload = metrics_to_json(metrics)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(payload)

    summary = metrics.summary()
    gate_bits = " ".join(f"{name}={'PASS' if ok else 'FAIL'}" for name, ok in report.gates.items())
    print(
        f"bench harness: {summary}\n"
        f"runtime: {elapsed:.2f}s (budget {RUNTIME_BUDGET_S:.0f}s)\n"
        f"gates: {'PASS' if report.passed else 'FAIL'} ({gate_bits})\n"
        f"metrics written to {output}"
    )
    if elapsed > RUNTIME_BUDGET_S:
        print(f"FAIL: harness runtime budget exceeded ({elapsed:.2f}s > {RUNTIME_BUDGET_S:.0f}s)")
        return 1
    return 0 if report.passed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
