# AegisCore — Testing Plan

**Status:** Draft for review · 2026-11-02
**Scope:** What CI proves today (software MVP, simulation-level) and what hardware validation remains open per NSF aim. The two columns are kept separate on purpose: simulation evidence is never presented as hardware evidence.
**Related:** [DESIGN.md](DESIGN.md) · [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md)

## 1. CI gate thresholds

The bench harness emits JSON metrics on every CI run and fails the build on any of these gates. A gate that has never failed is not evidence — CI must be demonstrated red on a seeded violation before the gates are trusted green.

| Gate | Threshold | Metric source |
| --- | --- | --- |
| Translation latency | p99 < 5 ms per command (p50 also emitted) | SCAL latency benchmark over the 100-trajectory corpus |
| Fail-safe transition | Max transition latency ≤ 50 ms | Fault-injection suite across the failover FSM |
| Kinematic safety | Zero violations (no admissible command produces wheel speeds beyond profile limits on any corpus trajectory) | Property test P1 + harness corpus run |
| Safety-log completeness | 100% of governor decisions logged (admitted command, margins, mode, reason) | Safety-log completeness test over every governor cycle |
| Harness budget | Full corpus + fault matrix completes in CI in under 10 minutes | CI run time |

## 2. NSF aims → CI evidence vs. open hardware validation

Every aim has both a CI evidence column and an open-hardware column. A pitch may cite only the CI column until the hardware rows close.

| NSF aim | CI evidence source | Hardware validation that remains open |
| --- | --- | --- |
| **Aim 1 — Semantic translation, <5 ms, 3 chassis types, zero kinematic violations** | p99/p50 translation latency over the 100-trajectory corpus; property test P1 (no admissible command produces wheel speeds beyond profile limits, differential/Ackermann/hybrid); zero-violation count | Sensor-noise and latency realities of real OEM controllers; translation timing on target compute (application SoM) rather than CI runners; HIL bench confirming command streams are accepted by real actuator buses |
| **Aim 2 — Deterministic fail-safe, ≤50 ms, 100% decision logging** | Fault-injection suite over ≥6 fault classes (spoofed command, stale heartbeat, sensor loss, network loss, watchdog miss, braking loss); per-fault transition latency asserted ≤50 ms; safe-state termination asserted; safety-log completeness test at 100% | Wall-clock determinism on the safety MCU (fixed-period loop, watchdog serviced only after a valid control cycle) — Python CI measures algorithmic latency, not WCET; braking/actuator response times on real hardware; loss-of-network behavior with real radios on 3 platforms |
| **Aim 3 — Adapter configuration complexity, ≥30% reduction** | Configuration-surface count per chassis (integrator-facing parameters) compared against a per-OEM baseline, computed in the harness and reported in metrics JSON — the measurement scaffold the trials will use | HIL bench and outdoor trials on 3 platforms with real operators — this evidence does not exist until the hardware milestones run; zero safety compromise under loss-of-network on physical platforms |

## 3. Fault-injection coverage

The suite covers six fault classes; each test asserts three things: the FSM terminates in a defined safe state (per the failover ladder in DESIGN.md §5), transition latency ≤50 ms, and the decision is recorded in the safety log.

| # | Fault class | Injected as | Required safe state |
| --- | --- | --- | --- |
| F1 | Spoofed command | Forged command stream at the gateway boundary | Rejected at gateway; if past it, CONTROLLED STOP |
| F2 | Stale heartbeat | Host lease not renewed within threshold | HOLD → CONTROLLED STOP on timeout |
| F3 | Sensor loss | Dropped/degraded state feedback | CONSERVATIVE → HOLD |
| F4 | Network loss | Communication channel severed | CONTROLLED STOP (bounded deceleration, blade off) |
| F5 | Watchdog miss | Supervisor cycle exceeds its period | CONTROLLED STOP |
| F6 | Braking loss | Braking authority unavailable during stop | E-STOP (torque removal, independent path) |

Two coverage rules beyond the table: a fault class without a test fails the fault-matrix coverage check, and any unmodeled fault must default to CONTROLLED STOP, never NOMINAL — the fail-safe default rule is itself asserted by test.

## 4. Property tests and unit tests

- **P1 (kinematic safety, property-based):** for every chassis profile and every one of the 100 corpus trajectories, no admissible command produces wheel speeds beyond the profile's limits.
- **Translation correctness (unit, per kinematic model):** each task primitive (`MoveTo`, `FollowPath`, `SetBlade`, `Dock`) translates to the expected chassis-specific command stream for each of the three kinematics classes.
- **Gateway security (negative tests):** a replayed command is rejected; an expired lease is rejected; an unauthenticated command never reaches SCAL.
- **Safety-log completeness:** running the corpus and fault matrix, every governor cycle produces a log record; the count matches exactly.

## 5. What CI cannot prove — carried to hardware validation

Stated once, plainly: CI proves the algorithms on kinematic models with simulated faults. It cannot prove wall-clock determinism under a real OS scheduler (Python's GC pause is the known limit; hard real-time enforcement is the safety MCU's job in the hardware phase), cannot exercise real braking hardware, and cannot measure operator effort on real fleets. Every row in the third column of §2 is therefore a named deliverable of the HIL and outdoor trial milestones, and the Phase I pitch scopes them as remaining work — the MVP's evidence is algorithmic-level feasibility, and the docs never claim more.
