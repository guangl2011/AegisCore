# Results from Prior Work — AegisCore

*Spotlize1 · NSF SBIR Phase I · Prepared for further improvement and optimization*

> **Provenance note (not part of the submission).** This document is scaffolded only from what verifiably exists: the public repository `guangl2011/AegisCore` and its CI evidence. No prior NSF awards, federal contracts, or published collaborations are claimed — none exist. Narrative source of truth: [docs/nsf/PITCH.md](../PITCH.md).

## Prior NSF awards

None. Spotlize1 has not previously received NSF SBIR/STTR or other NSF awards, and this proposal does not report results from prior federal awards. The prior-work basis below is company-funded internal R&D, presented because NSF review benefits from knowing what the team has already demonstrated before requesting Phase I funds.

## Company-funded prior work: the AegisCore software MVP and evidence harness

Before this proposal, Spotlize1 designed and built a software-first MVP of the complete AegisCore edge-control stack — runnable in simulation, CI-tested on every change, with an evidence harness that measures exactly the quantities the Phase I aims promise. It lives in the public repository `guangl2011/AegisCore` (`main` at commit `ba5422c`; benchmark snapshot from commit `b3faa97`), where every pull request runs the full test suite and the benchmark gates in GitHub Actions.

What that prior work demonstrably produced, all verifiable in the repository:

- **Semantic Capability Abstraction Layer (SCAL)** — a translator from platform-agnostic task primitives (`MoveTo`, `FollowPath`, `SetBlade`, `Dock`) to chassis-specific command streams, with validated profiles for differential, Ackermann, and hybrid multi-motor kinematics.
- **Deterministic safety-bounded command governor and six-state failover FSM** — the sole writer of actuator commands, enforcing kinetic-energy envelopes, proximity-based e-stop precedence, command-age validation, and heartbeat leases, with per-cycle decision logging.
- **Zero-trust gateway skeleton** — certificate-based mutual authentication, per-session command leases, and nonce-based replay rejection, with negative tests proving replayed, expired-lease, and unauthenticated commands never reach translation. The gateway's pinning extension accepts only hash-pinned (SHA-256, reviewed revision) model artifacts before any perception serving surface is exposed behind it, refusing unpinned artifacts and hash mismatches by test.
- **Optional advisory perception/anomaly layer** — an OpenVINO-backed advisory provider for Intel edge hardware (Core Ultra-class NPUs, iGPU, CPU) with a silent degrade to CPU when the accelerator is unavailable, an onnxruntime provider when OpenVINO is absent, and a null provider when no runtime exists. The layer's only output is an advisory constraint (proximity margin, anomaly flag, terrain risk) that the governor consumes as a margin input; no type in the layer can express an actuator command, and a CI import-graph check keeps the deterministic cores free of advisory imports.
- **Bench harness and evidence gates** — a fixed-seed 100-trajectory corpus (seed 20261102), an 8-fault × 3-chassis fault injection matrix, an advisory latency/coverage experiment (stub providers; CI runs no inference), JSON metric emission, and CI gates that fail the build when thresholds are breached. The gates have been demonstrated red on a seeded violation before being trusted green.
- **Test suite passing** on `main`, CI-run on Python 3.11 and 3.12, covering translation correctness per kinematic model, property-based kinematic safety (no admissible command exceeds profile limits on any corpus trajectory), gateway security and artifact pinning, advisory-provider fallback and the no-command invariant, fail-safe transition latency, and safety-log completeness.

Measured feasibility results this prior work already produced (simulation, `benchmarks/latest.json`; timing is machine-dependent — the CI gates assert the bounds, not the specific figures):

- Translation latency p50 66.5 µs, p99 184 µs, max 492 µs per command across 1,161 commands on three chassis — roughly 27× under the 5 ms Phase I aim — with zero kinematic violations.
- Maximum fail-safe transition latency 30 ms across all 24 fault scenarios, every scenario terminating in a defined safe state; unmodeled faults default to controlled stop, never to nominal.
- Safety-log completeness 1,998,144 of 1,998,144 governor decisions (100%).
- Advisory-layer experiment (stub providers; CI runs no inference): advisory consumption adds p99 13.8 µs to a governor cycle; advisory-driven failover descents fired at 160.4 per 10,000 governor cycles; all 36,307 deliberately stale advisory offers were rejected by the governor's freshness check. This measures the governor-side cost of the advisory path, not OpenVINO inference speed — that is a Phase I measurement on target hardware.

## What prior work does not yet show

Stated plainly, because the application's credibility depends on the boundary: the MVP proves the algorithms on kinematic models with simulated faults. It does not yet show wall-clock determinism (Python cannot prove WCET — that moves to the dedicated safety MCU in Phase I), real sensor-noise and latency conditions of OEM buses, physical braking response, or operator configuration effort in trials. Those are the Phase I milestones, each with a named experiment in the [work plan](WORK_PLAN.md), and the application never presents simulation evidence as hardware evidence.

## Academic collaboration

Dr. Jizhong Xiao (CUNY Robotics Lab) — Professor of Electrical Engineering, Director of the CCNY Robotics Lab and PRISM Center, and NSF CAREER Award recipient — serves as the proposed Phase I academic research collaborator (subaward) for formal-methods review of the safety-supervisor and control algorithms. This is a proposed Phase I collaboration, not a completed prior one; no joint results are claimed here.

## Commercial pilots

Commercial landscaping pilot operators are providing mower chassis, operational field logs, and trial sites for the Phase I hardware milestones, and are the named initial customers for the beachhead (domestic contractors and fleet operators running 20–150 units). Their trial results will form the adapter-complexity evidence for Aim 3; no trial results exist yet and none are claimed.
