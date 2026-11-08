# Innovation Statement — AegisCore

*Spotlize1 · NSF SBIR Phase I · Prepared for further improvement and optimization*

> **Provenance note (not part of the submission).** Measured numbers come from `benchmarks/latest.json` (commit `b3faa97`); competitive and regulatory claims come from the research findings artifact (art_Hj9mvlI3). Narrative source of truth: [docs/nsf/PITCH.md](../PITCH.md).

## The breakthrough claim

Swapping foreign robot controllers for domestic copies is manufacturing; making one edge architecture provably enforce safety across heterogeneous, untrusted actuators is science. The breakthrough AegisCore pursues is a single, deterministic, independently verifiable safety supervisor that sits between any operational software and any OEM actuator — enforcing kinetic-energy envelopes, proximity-based e-stop precedence, and command-freshness invariants even when upstream commands or vendor firmware are compromised — while translating one command language across chassis that differ in kinematics, torque curves, and stopping inertia.

The claim is unproven in the market and, until now, unmeasured in the lab. What makes it tractable is that the required mathematics exists but has never been united in one verified edge stack, and never for outdoor service robots.

## Prior-art positioning

AegisCore extends an established scientific lineage rather than inventing one:

- **Reference/command governors (RG)** — add-on runtime supervisors that enforce pointwise-in-time state and control constraints by projecting commanded inputs onto the admissible set. AegisCore's governor core is a QP-style minimum-norm projection of this kind.
- **Control-barrier-function (CBF) safety filters** — real-time constraint enforcement that computes the minimum-norm safe command when a requested command would leave the safe set. AegisCore's FILTERED mode implements this behavior.
- **Safe-ROS architecture** — separates the intelligent controller from an independent safety system holding its own e-stop authority. AegisCore adopts the separation: the governor is the sole writer of actuator commands, and no upstream process can bypass it.
- **Safety-MCU enforcement patterns** — fixed-period deterministic loops, host-heartbeat leases, and watchdogs serviced only after a valid control cycle. These patterns define how the software governor's guarantees move onto dedicated hardware in the Phase I safety-MCU milestone.

Each lineage element is published science; none of it exists today as a combined, certified, retrofit edge product for outdoor commercial robots. That combination is the contribution, and the Phase I research questions target the parts of the combination that remain unknown — cross-chassis translation latency, fail-safe transition bounds under arbitrary fault injection, adapter-complexity reduction in real trials, and whether perception-driven advisory signals can narrow safety margins usefully without ever touching the command path.

## The advisory perception layer — Intel edge hardware, off the control path

A fifth, optional module extends the stack without touching its safety core: an advisory perception and anomaly layer that consumes telemetry and camera frames and publishes advisory constraints — proximity margins, anomaly flags, terrain risk — the governor may use to narrow margins it already owns and descend the failover ladder. The invariant is structural, not procedural: no inference output can write or modify an actuator command, because no type in the advisory layer can express one. Integration is pinned and bounded: OpenVINO-compiled inference on domestic Intel edge silicon (Core Ultra-class NPUs, iGPU, CPU), a silent degrade to CPU when the NPU is unavailable, an onnxruntime provider when OpenVINO is absent, and a null provider when no runtime exists — the command path never depends on the layer. Every model artifact is hash-pinned to a reviewed revision and admitted only through the gateway's pinning boundary. The constraint kinds map directly to named, Apache-2.0 components of Intel's open Robotics AI Suite (GroundFloor Segmentation for terrain risk, ADBScan and YOLO-class detection for proximity margins); outdoor- and mower-domain models will be AegisCore-selected and converted, since no open suite ships them ready-made. This is also the fourth Phase I research question: whether advisory signals are operationally useful — measured by the harness's latency and descent-coverage experiment — without ever being on the command path.

## Measured feasibility (simulation, benchmark snapshot at commit `5c3cd65`)

- Translation of task primitives across differential, Ackermann, and hybrid multi-motor chassis: p50 66.5 µs, p99 184 µs, max 492 µs per command over 1,161 commands — roughly 27× under the 5 ms aim — with zero kinematic violations on the fixed-seed 100-trajectory corpus (seed 20261102). Timing is machine-dependent; the CI gates assert the 5 ms bound, not the specific figure.
- Six-state failover governor under an 8-fault × 3-chassis injection matrix: maximum fail-safe transition 30 ms across all 24 scenarios, every scenario terminating in a defined safe state, and 1,998,144 of 1,998,144 governor decisions logged (100%). Unmodeled faults default to controlled stop, never to nominal.
- Advisory-layer experiment (stub providers; CI runs no inference): advisory constraint consumption adds p99 13.8 µs to a governor cycle; advisory-driven failover descents fired at 160.4 per 10,000 governor cycles; all 36,307 deliberately stale advisory offers were rejected by the governor's freshness check. The experiment measures the governor-side cost of the advisory path — not OpenVINO inference speed, which is a Phase I measurement on Core Ultra-class NPUs.
- These are algorithmic latencies measured in simulation. Python cannot prove worst-case execution time; hard real-time enforcement is the safety MCU's responsibility in the hardware phase, consistent with the architecture above.

## Differentiation

The validated competitive gap: no shipping product offers independent, deterministic safety supervision with a zero-trust gateway as a retrofit for outdoor service robots.

| Category | Players | Why they do not answer the gap |
| --- | --- | --- |
| Fleet orchestration | InOrbit, Formant | Vendor-neutral monitoring and dispatch; no low-level control, no safety path |
| ROS-based platforms | MOV.AI, Rapyuta, Cogniteam | Middleware and deployment infrastructure; ROS-Industrial explicitly does not replace OEM controllers |
| Universal controller hardware | SEER Robotics (SRC series) | Controller platforms for indoor AMR builders, not safety-supervised outdoor retrofit |
| Autonomy ecosystems | Auterion, NVIDIA Isaac, Intrinsic | Portable OS/fleet layers within supported stacks; drone- and AMR-centric |
| OEM-native suites | MiR Fleet, OMRON FLOW, FANUC FIELD | Single-vendor only |

Fleet layers assume the vehicle works; safety stays with the OEM. AegisCore owns the layer between them: a safety-preserving OEM interface, the runtime governor on a dedicated safety MCU, and the abstraction layer above. The moat is not ROS — it is the validated OEM adapter library, the safety documentation, and the calibration workflows that regulators, insurers, and municipal procurers can audit.

Regulation widens the moat into procurement. In July 2026 the FCC added foreign-produced advanced robotic devices to its Covered List, citing data exfiltration, remote disruption, insecure OTA updates, and possible remote commandeering; an October 2026 White House proclamation flags imported-robotics cyber risk; CISA and FBI guidance requires SBOM/HBOM transparency, U.S.-controlled updates, and independent testing. A domestic, verifiable, NDAA-compliant supervisor is becoming a purchase requirement for municipalities — demand AegisCore is built to meet and foreign-manufactured controllers cannot.
