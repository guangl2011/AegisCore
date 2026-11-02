# Phase I Work Plan — AegisCore

*Spotlize1 · NSF SBIR Phase I · Prepared for further improvement and optimization*

> **Provenance note (not part of the submission).** Structure and risks come from the approved spec (art_Ie4Y09VE) and [docs/aegiscore/DEVELOPMENT_PLAN.md](../../aegiscore/DEVELOPMENT_PLAN.md); measured numbers come from `benchmarks/latest.json` (commit `b3faa97`). Narrative source of truth: [docs/nsf/PITCH.md](../PITCH.md).

## Plan summary

Phase I validates determinism, latency bounds, and cross-platform generalizability of the universal control supervisor across three dissimilar mower chassis (differential-drive electric, Ackermann-steer, hybrid multi-motor). The work is sequenced so that every claim the application makes is either already measured by the CI-run bench harness or carries a named experiment and milestone. Milestone M1 (the software MVP) is complete; the remaining milestones carry the hardware claims. Each milestone's exit is a deliverable accepted against a written criterion, not a date alone.

## Milestones

### M1 — Software MVP and evidence harness (complete)

The foundation the rest of Phase I stands on: SCAL translator and chassis profiles, the deterministic governor and six-state failover FSM, the zero-trust gateway skeleton, and the bench harness (fixed-seed 100-trajectory corpus, 8-fault × 3-chassis fault matrix, JSON metric emission, CI evidence gates). Built in Python 3.11+ with pytest/Hypothesis, CI-run on every PR.

*Deliverables:* `src/aegiscore/` (core, scal, governor, gateway, harness, sim); CI gates failing the build on any seeded violation; 243 tests passing; design, development, and testing plans under `docs/aegiscore/`; the rewritten pitch under `docs/nsf/`.

*Evidence produced (commit `b3faa97`):* translation p50 26.7 µs / p99 65.5 µs / max 158.2 µs over 1,161 commands with zero kinematic violations; max fail-safe transition 30 ms across 24 fault scenarios, all in defined safe states; 1,998,144 of 1,998,144 governor decisions logged (100%); all five evidence gates passing in CI.

### M2 — OEM adapter prototypes on live hardware interfaces

Reproduce Aim 1's measured translation results on real OEM command buses instead of simulation. Build adapters for the three reference chassis' proprietary CAN and serial drivers; the SCAL profile library gains per-OEM hardware profiles; the property-based conformance tests re-run against adapter output streams.

*Tasks:* per-OEM adapter implementations (differential, Ackermann, hybrid); latency instrumentation on target compute (the application SoM rather than CI runners); conformance re-test on live buses; adapter configuration-surface counts finalized against the per-OEM baseline for Aim 3's scaffold.

*Deliverables:* three validated OEM adapters; live-bus latency report; updated configuration-surface comparison. *Success criterion:* translation p99 < 5 ms sustained on target compute with zero kinematic violations on live buses (Aim 1 closed on hardware interfaces).

### M3 — Safety MCU port and jitter measurement

Move governor enforcement onto a dedicated safety MCU: fixed-period deterministic loop, host-heartbeat lease, watchdog serviced only after a valid control cycle, local fallback controllers. The software governor's decision logic ports to a no-dynamic-allocation C/Rust core behind the same narrow interface the Python MVP defined.

*Tasks:* safety-MCU board bring-up; governor-core port; hardware-in-the-loop bench integration with the existing simulator as the environment twin; scheduler-jitter measurement on target hardware; WCET-style measurement campaign.

*Deliverables:* safety-MCU firmware; HIL bench report; jitter measurement report. *Success criterion:* the ≤ 50 ms fail-safe bound holds as a hardware contract, with measured worst-case jitter documented — closing the Python-determinism gap left open at M1.

### M4 — HIL bench and outdoor trials, three platforms

Run the Aim 3 experiment the MVP could only scaffold: hardware-in-the-loop bench setups and instrumented outdoor trials on 3 platforms with commercial landscaping pilot operators — the named initial customers.

*Tasks:* HIL bench protocols per chassis; loss-of-network and sensor-fault drills on physical platforms (zero safety compromise is the criterion); instrumented outdoor trials with pilot operators; adapter configuration-effort measurement against the M2 baseline; incident and safety-log review with the academic collaborator.

*Deliverables:* trial reports on 3 platforms; measured adapter-complexity reduction; loss-of-network safety record. *Success criterion:* ≥ 30% adapter configuration-complexity reduction versus per-OEM integration and zero safety compromise under loss-of-network (Aim 3 closed).

### M5 — Verification, documentation, and submission package

Formal-methods review of the safety-supervisor and control algorithms with Dr. Jizhong Xiao's group (subaward); safety case documentation; the domestic hardware-assurance topology engineered for verifiable U.S. surface-mount assembly with hardware root of trust and auditable microcode.

*Deliverables:* formal verification review report; safety case documentation; NDAA Section 889-aligned hardware-assurance documentation. *Success criterion:* the safety argument — simulation evidence, MCU hardware contract, and formal review — holds as one auditable document chain.

## Dependencies and sequencing

M2 and M3 run in parallel (adapters on the host side, MCU port on the safety side); M4 requires both; M5 runs continuously with formal review at each milestone boundary. The controlling evidence rule carries through: a number enters the application only when the milestone that produces it has closed.

## Risks

| Risk | Framing | Mitigation |
| --- | --- | --- |
| **Python determinism claim is attackable** | Python cannot prove real-time determinism; a GC pause breaks the ≤ 50 ms story at the wall-clock level | The MVP measures algorithmic latency on the benchmark harness and says exactly that; hard real-time enforcement is the safety MCU's responsibility at M3, consistent with the architecture. Reviewers see algorithmic-level feasibility evidence, not a WCET claim |
| **Sim-to-hardware gap** | Kinematic-model constraints proven in simulation are not sensor-noise, traction, or latency realities | The testing plan maps, per aim, exactly which claims await hardware validation; M2/M3 close the interface and determinism gaps before M4 claims anything about physical platforms |
| **HIL deferred — no software-only substitute for Aim 3** | ≥ 30% adapter reduction and zero safety compromise under network loss cannot be produced in simulation | The MVP ships the measurement scaffold (configuration-surface counting, network-loss fault class); M4's trials on 3 platforms are the named remaining Phase I work, never presented as done |
| **Fault isolation inside proprietary drivers** | Trapping faults within closed motor drivers without cascading bus faults | Bounded-deceleration fallbacks and the braking-loss e-stop path, tested in the fault matrix; adapter work at M2 validates the boundary on real buses |
| **Pitch number without a source** | Any market or performance figure without provenance fails review | Market figures come from cited research ($2.1–2.8B in 2025 → ~$3.4B by 2030, CAGR 10–14%: Ken Research, DataIntelo, Mordor Intelligence); performance figures come only from harness output or are stated as named Phase I targets |
