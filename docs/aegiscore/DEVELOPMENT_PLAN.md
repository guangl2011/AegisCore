# AegisCore — Product Development Plan (Phase I)

**Status:** Draft for review · 2026-11-02
**Scope:** Phase I software-first MVP and the evidence pipeline behind the NSF aims. Hardware bring-up, HIL benches, and outdoor trials appear here as planned later milestones, not as current work.
**Related:** [DESIGN.md](DESIGN.md) · [TESTING_PLAN.md](TESTING_PLAN.md)

This plan maps each Phase I aim to the experiment that produces its evidence, sequences the milestones that build those experiments, and names the risks the plan already carries. The controlling rule throughout: **the pitch cites only numbers the MVP actually produces.** Where a target is not yet measured at pitch-writing time, the pitch states it as a Phase I target with the experiment named — never as a result.

## 1. Phase I aims → experiments

Each aim is stated as a research question, because that is what NSF review scores: named technical unknowns with a risk-reduction experiment attached, not engineering targets asserted without method.

### Aim 1 — Semantic translation: <5 ms across three chassis types

**Research question:** Can a single semantic abstraction translate task primitives across three kinematic classes (differential, Ackermann, hybrid multi-motor) within 5 ms per command, with zero kinematic violations?

**Experiment:** The 100-trajectory benchmark corpus (DESIGN.md §7). Every trajectory runs through the SCAL translator against all three chassis profiles; the harness emits p50/p99 translation latency per command and counts kinematic violations (wheel speeds beyond profile limits, on any trajectory).

**Success criterion:** p99 translation latency <5 ms and zero kinematic violations across the full corpus — measured in CI, gated automatically (TESTING_PLAN.md §4).

**Current status:** Target, not yet measured. The MVP milestones below produce this number.

### Aim 2 — Deterministic fail-safe: ≤50 ms under fault injection

**Research question:** Can a runtime governor guarantee a fail-safe transition — bounded deceleration or halt in a defined safe state — within 50 ms of any injected fault, with 100% of decisions logged?

**Experiment:** The fault-injection suite. ≥6 fault classes (spoofed command, stale heartbeat, sensor loss, network loss, watchdog miss, braking loss) drive the six-state failover ladder; every run asserts termination in a defined safe state, logs transition latency per fault, and asserts safety-log completeness (100% of governor decisions logged).

**Success criterion:** Max observed transition latency ≤50 ms across the fault matrix, zero faults terminating outside a defined safe state, and 100% decision-logging completeness — all asserted in CI.

**Current status:** Target, not yet measured.

### Aim 3 — Adapter complexity: ≥30% configuration reduction in trials

**Research question:** Does one SCAL profile per chassis reduce adapter configuration effort by ≥30% versus per-OEM integration, in HIL bench and outdoor trials?

**Experiment:** Phase I's third aim promises HIL bench and outdoor trials on 3 platforms with ≥30% adapter configuration-complexity reduction and zero safety compromise under loss-of-network. The MVP contributes the measurement scaffold: adapter configuration surface per chassis (parameters an integrator must set), counted and compared against a per-OEM baseline in simulation. The hardware trials then measure the real operators' configuration effort against that scaffold.

**Success criterion:** ≥30% reduction in adapter configuration complexity, measured in HIL/outdoor trials on 3 platforms. **This evidence is open until the hardware milestones** (TESTING_PLAN.md §2, Aim 3 row). The MVP produces no trial numbers, and the pitch must not imply otherwise.

## 2. Milestones

Milestones follow the spec's deliverables 1–6. Each milestone's exit is its PR merged to `main` with CI green; nothing here requires hardware.

| # | Milestone | Contents | Evidence produced |
| --- | --- | --- | --- |
| D1 | SCAL translator + chassis profiles | Profiles for differential, Ackermann, hybrid; translation of ≥4 task primitives; per-command latency measurement; property-based unit tests per kinematic model | Translation latency metrics; kinematic-violation count (feeds Aim 1) |
| D2 | Governor + failover FSM | Envelope checks (kinetic energy, proximity precedence, command age, heartbeat lease); six-state ladder; fault-injection suite covering ≥6 fault classes | Transition latencies; safe-state terminations; safety-log completeness (feeds Aim 2) |
| D3 | Zero-trust gateway skeleton | Certificate-based mutual auth, per-session lease, nonce/replay rejection; negative tests (replay, expiry, unauthenticated) | Gateway security test suite results |
| D4 | Bench harness + corpus | Deterministic sim of three chassis; 100-trajectory corpus; fault matrix; JSON metric emission; CI gates on thresholds | The metrics artifact every aim's claim cites |
| D5 | Docs (this PR) | DESIGN.md, DEVELOPMENT_PLAN.md, TESTING_PLAN.md under `docs/aegiscore/` | Reviewable design and plans |
| D6 | NSF pitch rewrite + application doc set | Four-section pitch within limits (3,500/3,500/1,750/1,750 chars), market figures cited, each aim paired with its experiment; project summary, innovation statement, work plan skeleton, results-from-prior-work | Submission-ready pitch citing only measured results or named-target experiments |

**Sequencing and the evidence rule.** D1–D4 may proceed in parallel with pitch drafting, but the pitch PR does not merge until every number it cites matches harness output on the tested commit. This is what separates a defensible pitch from an aspirational one. The harness gate must be shown to fail on a seeded violation — a gate that has never failed is not evidence.

## 3. Risks

| Risk | Framing | Mitigation |
| --- | --- | --- |
| **Python determinism claim is attackable** | Python cannot prove real-time determinism; a GC pause breaks the ≤50 ms story at the wall-clock level | The MVP measures algorithmic latency on the benchmark harness and says exactly that; hard real-time enforcement is the safety MCU's responsibility in the hardware phase (DESIGN.md §8), consistent with the pitch's own architecture. Reviewers see algorithmic-level feasibility evidence, not a WCET claim |
| **Sim-to-hardware gap** | Kinematic-model constraints proven in simulation are not sensor-noise, traction, or latency realities | TESTING_PLAN.md maps, per aim, exactly which claims await hardware validation; Phase I trials are scoped as the remaining work the hardware milestones cover, never as done |
| **HIL deferred** | Aim 3 (≥30% adapter reduction, zero safety compromise under network loss on real platforms) has no software-only substitute | The MVP ships the measurement scaffold (configuration-surface counting, network-loss fault class); HIL bench and outdoor trials on 3 platforms are planned Phase I hardware milestones; the pitch presents them as remaining Phase I work |
| **Pitch number without a source** | Any market or performance figure without provenance fails review | Market figures come from the cited research (commercial robotic mower forecasts: $2.1–2.8B in 2025 → ~$3.4B by 2030, CAGR ~10–14% per Ken Research, DataIntelo, Mordor — the draft's uncited "$2.8B by 2030, CAGR 18.5%" is replaced); performance figures come only from harness output or are stated as targets |

## 4. Explicit non-goals (current build)

No hardware, no PCB bring-up, no field trials, no ROS 2 deployment claim, no Gazebo dependency, and no changes to the unrelated InsmartFix documents already in the repository. A ROS 2 bridge can be an adapter later; it is not the spine now.
