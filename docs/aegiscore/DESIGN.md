# AegisCore — System Design

**Status:** Draft for review · 2026-11-02
**Scope:** Software-first MVP (simulation-level). Hardware bring-up, HIL benches, and outdoor trials are later milestones — see [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md) and [TESTING_PLAN.md](TESTING_PLAN.md).
**Related:** [TESTING_PLAN.md](TESTING_PLAN.md) · NSF pitch draft "Cyber-Resilient Universal Edge Control and Safety Supervisor Architecture for Heterogeneous Outdoor Robotics"

AegisCore is a cyber-resilient universal edge controller and safety supervisor for heterogeneous commercial outdoor robots. It decouples high-level operational commands from untrusted low-level OEM actuators through four components: a Semantic Capability Abstraction Layer (SCAL), a deterministic safety-bounded command governor, a zero-trust gateway, and a bench harness that produces the measurable evidence behind the Phase I aims. This document specifies those components as built in the MVP and sketches the hardware-assurance topology they are designed to migrate onto.

## 1. Design principles

Three rules shape every component below.

**The governor is the only writer of actuator commands.** Operational software, the SCAL translator, and the gateway propose; the governor disposes. Every actuator command in the system passes through one deterministic supervisor cycle, which makes the safety argument auditable in a single place.

**Any unmodeled fault defaults to CONTROLLED STOP, never to NOMINAL.** The fail-safe default rule means an unknown failure mode degrades toward rest, not toward operation. Tests assert this behavior explicitly (see TESTING_PLAN.md §3).

**The MVP measures algorithmic behavior; hardware enforces hard real time.** Python cannot prove WCET-style determinism — a GC pause breaks any wall-clock guarantee. The MVP therefore measures algorithmic latency on the benchmark harness, and the design assigns hard real-time enforcement to the safety MCU in the hardware phase (§8). This division is deliberate and is stated up front so the simulation evidence is never oversold.

## 2. System overview

Four modules plus a harness, each mapping to one of the pitch's four innovations. Everything runs in-process under CI; the "hardware" boundary is an interface stub the simulated chassis implements.

```
 operator / fleet tasks                 (untrusted network)
        │                                        │
        ▼                                        ▼
 ┌──────────────┐   task primitives   ┌─────────────────────────┐
 │ SCAL          │───────────────────▶│ Zero-trust gateway       │
 │ translator    │   (post-translation)│ mutual auth · lease ·    │
 └──────────────┘                     │ replay rejection         │
        ▲                              └───────────┬─────────────┘
        │ chassis profiles                          │ asserted envelopes
        │                                           ▼
 ┌──────┴───────┐   chassis cmd stream   ┌─────────────────────────┐
 │ Chassis       │──────────────────────▶│ Governor core             │
 │ profiles      │                        │ CBF/RG filter · FSM ·     │
 │ (diff/acker/  │                        │ safety log                │
 │  hybrid)      │                        └───────────┬─────────────┘
 └──────────────┘                                    │ admitted commands
                                                     ▼
                                          ┌─────────────────────┐
   Bench harness ── measurement (dashed) ──▶ Sim chassis + actuators│
   (latency, violations, FSM latency)      └─────────────────────┘
```

Dashed edges are observation and measurement, not command flow. Commands flow in one direction: gateway → SCAL output → governor → actuators.

## 3. SCAL translator

The SCAL translator consumes platform-agnostic task primitives and a chassis profile, and emits chassis-specific command streams. Supported primitives: `MoveTo`, `FollowPath`, `SetBlade`, `Dock` (the MVP ships at least these four; the acceptance criterion is translation of ≥4 primitives per the spec). Supported kinematics: differential, Ackermann, and hybrid multi-motor.

A chassis profile declares, as frozen data:

- kinematics class (differential / Ackermann / hybrid multi-motor)
- actuator map (logical role → actuator id)
- limits: max linear speed (m/s), max acceleration (m/s²), max wheel speed (rad/s per actuator)
- blade inertia (kg·m²) where present, which enables the kinetic-energy envelope in the governor

Translation is a pure function of (primitive, profile, state). Purity is what makes the <5 ms per-command latency target measurable and the property tests possible: the same inputs must always produce the same command stream, and no admissible command may produce wheel speeds beyond the profile's limits on any corpus trajectory (TESTING_PLAN.md §2, property P1).

## 4. Governor core

The governor implements a CBF/RG-style safety filter — the runtime-supervisor pattern from the reference-governor and control-barrier-function literature (§9). It owns four checks per cycle:

1. **Kinematic/energy envelope** — projected state and command must remain inside the profile's safe set; blade kinetic energy is bounded via the profile's inertia term where present.
2. **Proximity-based e-stop precedence** — a proximal e-stop trigger outranks any admitted command, regardless of source.
3. **Command age validation** — stale commands are not admitted; age thresholds are profile-level configuration.
4. **Host-heartbeat lease** — the upstream host must hold a valid lease; expiry drives the failover ladder (§5).

Every cycle appends a decision record to the safety log: admitted command, margins per constraint, mode, and a reason when a command was filtered or rejected. This is the MVP's concrete form of the pitch's "100% deterministic safety logging" — completeness of the log is a CI gate (TESTING_PLAN.md §4).

The governor hides behind one narrow interface, which is the seam a future Rust/C port re-implements:

```python
class GovernorCore(Protocol):
    """Narrow seam for a future Rust/C port — everything else calls this."""
    def step(self, state: RobotState, cmd: TaskCommand, now_us: int) -> GovernorDecision:
        """One deterministic supervisor cycle: validate, filter, decide, log."""
```

`GovernorDecision` carries the admitted command (or None), the mode, per-constraint margins, and a rejection reason. Everything else in the system calls this protocol; nothing reaches past it.

## 5. Failover state machine

The failover ladder is the governor's contract with the safety argument. Each state has defined entry conditions, bounded transition latency, and a defined safe state. Transitions may only descend the ladder, except the explicit operator-authorised re-arm path from CONTROLLED STOP — the descent-only rule is what makes determinism provable.

```
 NOMINAL ──▶ FILTERED ──▶ CONSERVATIVE ──▶ HOLD ──▶ CONTROLLED STOP ──▶ E-STOP
    ▲            │              │                        │  ▲               │
    └────────────┘              │                        │  └─ operator-    │
    margins recover             └── recovery ────────────┘     authorised   │
                                       ▲                      re-arm       │
                                       └── lease restored ────┘            │
 E-STOP is terminal until physical re-arm ◀─────────────────────────────────┘
```

| State | Entry condition | Behavior | Exit |
| --- | --- | --- | --- |
| NOMINAL | All envelope margins positive; commands fresh; lease valid | Pass commands through | Margin ≤ 0 → FILTERED; fault → deeper state |
| FILTERED | Governor projects command onto safe set (CBF/RG filter) | Emit minimum-norm safe command | Margins recover → NOMINAL; infeasible → CONSERVATIVE |
| CONSERVATIVE | Repeated filtering, degraded sensors, or high command age | Speed capped to fraction of limit; refuse high-energy primitives | Recovery → NOMINAL; worsening → HOLD |
| HOLD | Loss of operator/lease signal, persistent sensor degradation | Zero-velocity command, actuators powered | Lease restored → CONSERVATIVE; timeout → CONTROLLED STOP |
| CONTROLLED STOP | Network loss, watchdog miss, spoof detection | Bounded deceleration to rest; blade off | At rest → remain, await re-arm; loss of braking → E-STOP |
| E-STOP | Braking authority lost, hardware fault, proximal e-stop trigger | Torque removal / independent e-stop path | Terminal until physical re-arm |

The fault-injection suite drives this ladder with ≥6 fault classes: spoofed command, stale heartbeat, sensor loss, network loss, watchdog miss, and braking loss. Each injected fault must terminate in a defined safe state with transition latency ≤50 ms asserted by test (TESTING_PLAN.md §3).

## 6. Zero-trust gateway skeleton

The gateway is the trust boundary between the network and everything downstream of SCAL. The MVP ships the protocol skeleton and its violation tests, not production crypto:

- **Certificate-based mutual authentication** — in-simulation certificates stand in for the hardware crypto root of trust the production module will carry.
- **Per-session command lease** — commands are valid only inside a session lease; the governor's heartbeat check (§4) reads the same lease state.
- **Nonce/replay rejection** — every command carries a nonce; replayed commands are rejected before they reach SCAL.
- **Envelope assertion** — the gateway asserts command envelopes (shape, bounds, session validity) before anything downstream sees them.

The security property the negative tests enforce: a replayed command is rejected, an expired lease is rejected, and an unauthenticated command never reaches SCAL (TESTING_PLAN.md §5). The regulatory context makes this boundary load-bearing rather than optional: FCC's July 2026 addition of foreign-produced advanced robotic devices to its Covered List cites data exfiltration, remote disruption, insecure OTA updates, and possible remote commandeering, and CISA/FBI guidance for connected autonomous equipment calls for SBOM/HBOM, signed and U.S.-controlled updates, and independent testing. The gateway skeleton is the software-side answer to the remote-commandeering class of that guidance.

## 7. Bench harness

The harness turns the Phase I aims into evidence. It is deliberately lightweight — no Gazebo dependency — because determinism, speed, and CI-friendliness matter more than physical fidelity at this stage.

- **Kinematic simulation of the three chassis** (differential, Ackermann, hybrid), deterministic and in-process.
- **A 100-trajectory benchmark corpus** shared by the SCAL latency benchmark and the property tests.
- **Fault-injection driver** covering the six fault classes of §5.
- **Metric emission as JSON**, which CI gates fail on: p50/p99 translation latency, max transition latency, kinematic violations, safety-log completeness.

The full corpus and fault matrix must run in CI in under 10 minutes; the harness fails the build when p99 translation latency reaches 5 ms, when any kinematic violation occurs, or when any failover transition exceeds 50 ms (TESTING_PLAN.md §4).

## 8. Hardware-assurance topology — later-milestone sketch

The MVP's module boundaries are drawn so the safety path migrates onto hardware without redesign. The production topology assigns each concern to a layer with independent enforcement authority:

```
 ┌───────────────────────────────────────────────────────┐
 │  Application SoM (Linux)                              │
 │   fleet comms · task planning · SCAL · zero-trust gw  │
 └──────────────────────────┬────────────────────────────┘
                host heartbeat lease (valid cycle only)
 ┌──────────────────────────▼────────────────────────────┐
 │  Safety MCU (deterministic, no OS, fixed-period loop)  │
 │   governor core · failover FSM · watchdog serviced     │
 │   only after a valid control cycle · local fallback    │
 └──────────────────────────┬────────────────────────────┘
                             │ torque / brake lines
 ┌──────────────────────────▼────────────────────────────┐
 │  Actuation · independent e-stop path                   │
 └───────────────────────────────────────────────────────┘
```

The safety-MCU enforcement pattern is the one the prior art documents: a fixed-period deterministic loop, a host-heartbeat lease that must be renewed by valid cycles, and a watchdog serviced only after a valid control cycle. The MCU holds the governor core's ported implementation; Linux-side compromise cannot write actuator commands because the MCU is the sole writer (§1) and the hardware root of trust anchors its firmware. The board is U.S.-assembled and auditable, NDAA-compliant, per the pitch's fourth innovation — that is the hardware-phase milestone, not MVP scope.

## 9. Prior art and design lineage

The MVP implements an established research lineage rather than inventing a new one; the pitch cites the same sources as feasibility grounding.

- **Reference/command governors** — add-on runtime supervisors enforcing pointwise-in-time state and control constraints, with QP-based minimum-norm projection. This is the §4 filter's mathematical basis.
- **Control-barrier-function (CBF) QP safety filters** — real-time constraint enforcement via quadratic programs; the minimum-norm safe command in FILTERED state is a CBF-style projection.
- **Safe-ROS architecture** — intelligent control separated from a Safety System holding independent e-stop authority. The §8 safety MCU inherits this separation; the governor never trusts the host's judgment, only its lease.
- **Runtime safety supervisor patterns for AMRs** — the monitor–shield pattern and the deterministic fallback ladder (admit → filter → conservative → hold → controlled decel → e-stop), which §5 instantiates with entry conditions and bounded latencies.
- **Safety-MCU enforcement** — fixed-period deterministic loop, host-heartbeat lease, watchdog serviced only after a valid cycle, local fallback controllers. §8 adopts this pattern wholesale.

The Phase I aims align with this literature, which is the argument that AegisCore is genuine research with named technical unknowns — not incremental product refinement.
