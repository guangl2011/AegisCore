# Project Summary — AegisCore

**Cyber-Resilient Universal Edge Control and Safety Supervisor Architecture for Heterogeneous Outdoor Robotics**

*Spotlize1 · NSF SBIR Phase I · Prepared for further improvement and optimization*

> **Provenance note (not part of the submission).** Every measured number in this summary comes from the CI-run bench harness snapshot `benchmarks/latest.json` (commit `b3faa97`); market and regulatory figures are cited from the research findings artifact (art_Hj9mvlI3). Narrative source of truth: [docs/nsf/PITCH.md](../PITCH.md).

## Overview

Commercial outdoor autonomous service robots — turf-care mowers, municipal maintenance machines, inspection platforms — are locked to proprietary OEM controllers: closed boards, opaque safety circuits, and unverified command links. Mixed-brand fleets run segregated maintenance pipelines, and municipalities cannot audit a foreign-manufactured controller they deploy on public grounds. AegisCore is a cyber-resilient universal edge controller and safety supervisor that sits between operational software and OEM actuators: a zero-trust gateway authenticates commands and admits only hash-pinned model artifacts, a Semantic Capability Abstraction Layer (SCAL) translates one command language across chassis kinematics, and a deterministic governor — the sole writer of actuator commands — enforces safety envelopes and a six-state failover ladder independent of upstream compromise. An optional advisory perception layer (OpenVINO on Intel edge hardware, onnxruntime fallback) can narrow the governor's margins but is structurally barred from writing commands.

## The innovation

No shipping product provides retrofit, deterministic safety supervision for outdoor service robots. Fleet-orchestration platforms monitor and dispatch but never touch low-level control; ROS-Industrial explicitly does not replace OEM controllers; universal controller hardware targets indoor AMR builders. AegisCore unites an existing scientific lineage — reference/command governors, control-barrier-function QP filters, the Safe-ROS separation of intelligence from safety authority, and safety-MCU watchdog patterns — into one verified edge stack with four components: the deterministic safety-bounded command governor, SCAL, the zero-trust gateway, and a domestic hardware-assurance topology aligned with NDAA Section 889 and federal covered-list procurement rules.

## Technical objectives and current evidence

Phase I validates determinism, latency bounds, and cross-platform generalizability across three dissimilar mower chassis (differential-drive electric, Ackermann-steer, hybrid multi-motor). The CI-run bench harness — a fixed-seed 100-trajectory corpus and an 8-fault × 3-chassis fault matrix — has already produced measured results against aims 1–2 and the advisory-layer experiment (aim 4, stub providers):

| Phase I aim | Target | Measured result (simulation, benchmark snapshot at commit `5c3cd65`) | Remaining Phase I work |
| --- | --- | --- | --- |
| 1. Semantic translation across 3 chassis | < 5 ms per command, zero kinematic violations | p50 66.5 µs, p99 184 µs, max 492 µs over 1,161 commands; 0 violations on the 100-trajectory corpus | Reproduce on live OEM adapters (proprietary CAN/serial drivers) |
| 2. Deterministic fail-safe governor | ≤ 50 ms transition, 100% decision logging | Max transition 30 ms across 24 fault scenarios, all ending in defined safe states; 1,998,144 of 1,998,144 decisions logged | Move enforcement onto a dedicated safety MCU and measure scheduler jitter — Python cannot prove WCET |
| 3. Adapter complexity reduction | ≥ 30% vs. per-OEM integration in trials | Measurement scaffold shipped (configuration-surface counting, network-loss fault class); simulation cannot produce this number | HIL bench and instrumented outdoor trials on 3 platforms |
| 4. Perception-driven advisory safety | Advisory signals narrow margins fast enough to be useful without touching the command path | Stub-provider experiment: advisory consumption adds p99 13.8 µs per governor cycle; 160.4 advisory-driven descents per 10,000 cycles; 36,307 stale offers rejected — advisory output can narrow a margin, never write a command | Measure OpenVINO inference latency on Core Ultra-class NPUs on target hardware; degrade-path validation |

The simulation results are algorithmic-level feasibility evidence, not hard real-time guarantees; Phase I hardware milestones carry the wall-clock claims.

## Market opportunity

The commercial robotic mower market is projected to grow from $2.1–2.8B in 2025 to about $3.4B by 2030, a 10–14% CAGR (Ken Research 2025; DataIntelo 2025; Mordor Intelligence 2026). Policy converts growth into procurement: in July 2026 the FCC added foreign-produced advanced robotic devices to its Covered List, citing data exfiltration, remote disruption, and possible remote commandeering; an October 2026 White House proclamation flags imported-robotics cyber risk; CISA and FBI guidance requires bill-of-materials transparency, U.S.-controlled updates, and independent testing. Domestic, verifiable, NDAA-compliant edge control is a procurement necessity, not a preference. Spotlize1's beachhead is domestic landscape contractors and autonomous-mower fleet operators running 20–150 units, starting with pilot operators already supplying chassis, field logs, and trial sites. Revenue: U.S.-assembled controller/gateway hardware, per-device annual software licenses, and hardware-migration certification packages. Adjacent markets: snow removal, airport perimeter inspection, industrial sweepers.

## Company and team

Spotlize1 is an early-stage robotics technology company building secure, interoperable embedded infrastructure and control architectures for commercial autonomous fleets. Technical direction is led by founder Richard Lu, a systems and robotics software engineer with experience in distributed systems, monorepo robotics tooling, and real-time embedded systems, and principal developer of the deterministic bench harness behind the results above. Dr. Jizhong Xiao (CUNY Robotics Lab) — Professor of Electrical Engineering, Director of the CCNY Robotics Lab and PRISM Center, and NSF CAREER Award recipient — serves as primary academic research collaborator (subaward), anchoring formal-methods review of the safety-supervisor and control algorithms. Commercial landscaping pilot operators provide chassis, field logs, and trial sites, and are the named initial customers for the Phase I beachhead. Phase I closes the two capability gaps — embedded firmware engineering for safety-MCU integration and safety-certification support — through contractors or hires, with the subaward covering formal verification review.
