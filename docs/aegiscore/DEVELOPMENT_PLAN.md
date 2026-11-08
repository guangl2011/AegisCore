# AegisCore — Product Development Plan (Phase I)

**Status:** Draft for review · 2026-11-02 · *Updated 2026-11-08 (OpenVINO design update): MVP evidence recorded, advisory aim (Aim 4) added, hardware milestones and Intel-stack risks incorporated.*
**Scope:** Phase I software-first MVP and the evidence pipeline behind the NSF aims. Hardware bring-up, HIL benches, and outdoor trials appear here as planned later milestones, not as current work.
**Related:** [DESIGN.md](DESIGN.md) · [TESTING_PLAN.md](TESTING_PLAN.md)

This plan maps each Phase I aim to the experiment that produces its evidence, sequences the milestones that build those experiments, and names the risks the plan already carries. The controlling rule throughout: **the pitch cites only numbers the MVP actually produces.** Where a target is not yet measured, the pitch states it as a Phase I target with the experiment named — never as a result.

## 1. Phase I aims → experiments

Each aim is stated as a research question, because that is what NSF review scores: named technical unknowns with a risk-reduction experiment attached, not engineering targets asserted without method.

### Aim 1 — Semantic translation: <5 ms across three chassis types

**Research question:** Can a single semantic abstraction translate task primitives across three kinematic classes (differential, Ackermann, hybrid multi-motor) within 5 ms per command, with zero kinematic violations?

**Experiment:** The 100-trajectory benchmark corpus (DESIGN.md §8). Every trajectory runs through the SCAL translator against all three chassis profiles; the harness emits p50/p99 translation latency per command and counts kinematic violations (wheel speeds beyond profile limits, on any trajectory).

**Success criterion:** p99 translation latency <5 ms and zero kinematic violations across the full corpus — measured in CI, gated automatically (TESTING_PLAN.md §1).

**Current status:** Measured in simulation (`benchmarks/latest.json`, commit `5c3cd65`): p50 66.5 µs, p99 184 µs, max 492 µs per command across 1,161 commands on three chassis — roughly 27× under the 5 ms aim — with zero kinematic violations. Timing is machine-dependent; the CI gate asserts the bound, not the figure. Remaining: re-test on target compute against live OEM buses (milestone M2).

### Aim 2 — Deterministic fail-safe: ≤50 ms under fault injection

**Research question:** Can a runtime governor guarantee a fail-safe transition — bounded deceleration or halt in a defined safe state — within 50 ms of any injected fault, with 100% of decisions logged?

**Experiment:** The fault-injection suite. Eight fault classes (spoofed command, stale heartbeat, sensor loss, network loss, watchdog miss, braking loss, proximity e-stop, unmodeled fault) drive the six-state failover ladder; every run asserts termination in a defined safe state, logs transition latency per fault, and asserts safety-log completeness (100% of governor decisions logged).

**Success criterion:** Max observed transition latency ≤50 ms across the fault matrix, zero faults terminating outside a defined safe state, and 100% decision-logging completeness — all asserted in CI.

**Current status:** Measured in simulation (`benchmarks/latest.json`, commit `5c3cd65`): worst transition 30 ms across all 24 fault scenarios (8 classes × 3 chassis), every scenario in a defined safe state, and 1,998,144 of 1,998,144 decisions logged. Remaining: re-prove the bound as a hardware contract on the safety MCU with measured jitter (milestone M3) — Python cannot evidence WCET.

### Aim 3 — Adapter complexity: ≥30% configuration reduction in trials

**Research question:** Does one SCAL profile per chassis reduce adapter configuration effort by ≥30% versus per-OEM integration, in HIL bench and outdoor trials?

**Experiment:** Phase I's third aim promises HIL bench and outdoor trials on 3 platforms with ≥30% adapter configuration-complexity reduction and zero safety compromise under loss-of-network. The MVP contributes the measurement scaffold: adapter configuration surface per chassis (parameters an integrator must set), counted and compared against a per-OEM baseline in simulation. The hardware trials then measure the real operators' configuration effort against that scaffold.

**Success criterion:** ≥30% reduction in adapter configuration complexity, measured in HIL/outdoor trials on 3 platforms. **This evidence is open until the hardware milestones** (TESTING_PLAN.md §2, Aim 3 row). The MVP produces no trial numbers, and the pitch must not imply otherwise.

### Aim 4 — Advisory perception narrows margins without touching the command path

**Research question:** Can perception-driven advisory signals, accelerated on Intel edge hardware, narrow safety margins fast enough to be operationally useful without ever touching the command path?

**Experiment:** The harness's advisory latency/coverage experiment (DESIGN.md §8): the corpus and fault matrix re-run with a deterministic stub advisory provider wired into the governor's consumption path, emitting issuance latency per poll, consumption latency per governor intake, advisory-driven descent coverage per 10,000 governor cycles, and stale-constraint rejections. Structural tests carry the invariant half of the question: no advisory type can express an actuator command, margins only tighten, and the import graph keeps the advisory package out of the deterministic cores (TESTING_PLAN.md §5).

**Success criterion:** advisory consumption cost measured and bounded, advisory-driven descents observed (CI gate `advisory_descents_observed`), zero staleness violations, and the no-command invariant holding under test.

**Current status:** Measured on stub providers (`benchmarks/latest.json`, commit `5c3cd65`): consumption p99 13.8 µs per governor intake, advisory-driven descents at 160.4 per 10,000 governor cycles (all to FILTERED), and 36,307 of 199,508 offered constraints rejected as stale. This bounds the governor-side cost of the advisory path only — OpenVINO inference latency on real Intel NPUs is a Phase I hardware measurement (advisory maturation track below).

## 2. Milestones

### 2.1 MVP milestones — shipped

Milestones D1–D6 delivered the software MVP. Each exited as a PR merged to `main` with CI green; nothing required hardware.

| # | Milestone | Contents | Evidence produced |
| --- | --- | --- | --- |
| D1 | SCAL translator + chassis profiles | Profiles for differential, Ackermann, hybrid; translation of ≥4 task primitives; per-command latency measurement; property-based unit tests per kinematic model | Translation latency metrics; kinematic-violation count (Aim 1) |
| D2 | Governor + failover FSM | Envelope checks (kinetic energy, proximity precedence, command age, heartbeat lease); six-state ladder; fault-injection suite covering eight fault classes | Transition latencies; safe-state terminations; safety-log completeness (Aim 2) |
| D3 | Zero-trust gateway skeleton | Certificate-based mutual auth, per-session lease, nonce/replay rejection; negative tests (replay, expiry, unauthenticated) | Gateway security test suite results |
| D4 | Bench harness + corpus | Deterministic sim of three chassis; 100-trajectory corpus; fault matrix; JSON metric emission; CI gates on thresholds | The metrics artifact every aim's claim cites |
| D5 | Docs | DESIGN.md, DEVELOPMENT_PLAN.md, TESTING_PLAN.md under `docs/aegiscore/` | Reviewable design and plans |
| D6 | NSF pitch rewrite + application doc set | Four-section pitch within limits (3,500/3,500/1,750/1,750 chars), market figures cited, each aim paired with its experiment; project summary, innovation statement, work plan, results-from-prior-work | Submission-ready pitch citing only measured results or named-target experiments |

**Sequencing and the evidence rule.** D1–D4 proceeded in parallel with pitch drafting, but the pitch merged only after every number it cited matched harness output on the tested commit. The harness gates were shown to fail on a seeded violation before being trusted green — a gate that has never failed is not evidence.

### 2.2 Phase I hardware and maturation milestones — planned

| Milestone | Scope | Acceptance criterion |
| --- | --- | --- |
| M2 · OEM adapter prototypes | Adapters for the three reference chassis' proprietary CAN/serial buses; per-OEM hardware SCAL profiles; latency instrumentation on target compute | Translation p99 < 5 ms sustained on target compute, zero kinematic violations on live buses (closes Aim 1 on hardware interfaces) |
| M3 · Safety MCU port | Governor core ported to a no-dynamic-allocation C/Rust core; HIL bench with the existing simulator as environment twin; scheduler-jitter and WCET-style measurement | The ≤50 ms fail-safe bound holds as a hardware contract with measured worst-case jitter documented (closes the Python determinism gap) |
| M4 · HIL bench and outdoor trials | HIL protocols per chassis; loss-of-network and sensor-fault drills on physical platforms; instrumented trials with pilot operators | ≥30% adapter configuration-complexity reduction vs. per-OEM integration and zero safety compromise under loss-of-network across 3 platforms (Aim 3) |
| M5 · Verification and safety case | Formal-methods review with the academic collaborator (subaward); safety case documentation; NDAA Section 889-aligned hardware-assurance documentation | Simulation evidence, MCU hardware contract, and formal review hold as one auditable document chain |
| Advisory maturation (parallel track) | `aegiscore[advisory]` on target hardware: OpenVINO/physicalai provider on Intel Core Ultra-class NPU/iGPU, ONNX Runtime fallback verified, end-to-end advisory latency (frame → constraint → governor margin) measured; model artifacts license-checked and hash-pinned per artifact | Advisory end-to-end latency and margin-narrowing coverage measured on real accelerators; silent degrade to CPU demonstrated on target hardware; per-artifact license records filed with the gateway pin store |

M2 and M3 run in parallel; M4 requires both; M5 runs continuously; the advisory track runs alongside M2–M4 without gating them — by design, since the advisory layer is optional and the deterministic core never depends on it.

## 3. Risks

| Risk | Framing | Mitigation |
| --- | --- | --- |
| **Python determinism claim is attackable** | Python cannot prove real-time determinism; a GC pause breaks the ≤50 ms story at the wall-clock level | The MVP measures algorithmic latency on the benchmark harness and says exactly that; hard real-time enforcement is the safety MCU's responsibility in the hardware phase (DESIGN.md §9), consistent with the pitch's own architecture. Reviewers see algorithmic-level feasibility evidence, not a WCET claim |
| **Pre-1.0 API churn in the advisory stack** | The OpenVINO/physicalai runtime is young and fast-moving, with breaking deprecations landing inside 30-day windows; silent breakage would reach CI undetected | Exact-version pins, integration against public documented APIs only, upgrade smoke tests in CI, and an ONNX Runtime fallback bounding the runtime dependency — the advisory layer is optional, so a total exit costs acceleration, not safety claims |
| **Intel suite preview quality and lock-in** | Intel's robotics suite self-labels preview; repo migrations have re-tagged releases and rotted paths | Pin the standalone repo at a named release, integrate through the AegisCore provider interface, re-verify at every upgrade; the ONNX fallback and the framework-free deterministic core bound the lock-in |
| **NPU availability and driver stability** | A flaky NPU would gut the acceleration story in trials even though safety is unaffected | Silent degrade to CPU provider, then ONNX Runtime fallback; deployment targets documented; trials record which provider served each session |
| **Model and artifact licensing** | Model weights and vendored components carry their own terms; per-repo assumptions (e.g., Apache-2.0 at the repo root) do not cover them | License check per component and per pinned model artifact, recorded alongside the gateway's SHA-256 pinning; outdoor-domain models are AegisCore-selected and converted, not adopted ready-made |
| **Sim-to-hardware gap** | Kinematic-model constraints proven in simulation are not sensor-noise, traction, or latency realities | TESTING_PLAN.md maps, per aim, exactly which claims await hardware validation; Phase I trials are scoped as the remaining work the hardware milestones cover, never as done |
| **HIL deferred** | Aim 3 (≥30% adapter reduction, zero safety compromise under network loss on real platforms) has no software-only substitute | The MVP ships the measurement scaffold (configuration-surface counting, network-loss fault class); HIL bench and outdoor trials on 3 platforms are planned Phase I hardware milestones; the pitch presents them as remaining Phase I work |
| **Pitch number without a source** | Any market or performance figure without provenance fails review | Market figures come from the cited research (commercial robotic mower forecasts: $2.1–2.8B in 2025 → ~$3.4B by 2030, CAGR ~10–14% per Ken Research, DataIntelo, Mordor — the draft's uncited "$2.8B by 2030, CAGR 18.5%" is replaced); performance figures come only from harness output or are stated as targets |

## 4. Explicit non-goals (current build)

No hardware, no PCB bring-up, no field trials, no ROS 2 deployment claim, and no Gazebo dependency. A ROS 2 bridge can be an adapter later; it is not the spine now. CI runs no inference runtime and no network access: the advisory experiment uses stub providers, and real-accelerator measurement is the advisory maturation milestone's job.
