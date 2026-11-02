# AegisCore — Development Process (Spec → Code → Test → Launch)

**Version:** 1.0 · **Date:** 2026-11-02
**Scope:** InsmartFix v1 (web portal, backend API, iOS, Android). Reused for later slices.

## 0 · The rule: two human gates, everything else automated

| Gate | Who decides | How approval is given | What it unlocks |
|---|---|---|---|
| **G1 · Spec Review** | Product owner (human) | Approve the `spec/*` pull request on GitHub (or comment `/approve-spec`) | Planning, scaffolding, build, automated testing |
| **G2 · Test Review** | Product owner (human) | Approve the `release/*` pull request carrying the Test Review Report (or comment `/approve-tests`) | Release candidate, staging → beta → production launch |

Every other step runs without asking. The agents still stop and report — they do not ask — when something is **blocked** (a missing credential, a failing gate they can't fix after 3 attempts, or a decision that changes the approved spec). A change to the approved spec reopens G1 for that delta only.

## 1 · Stages

```
 S0 Intake ─► S1 Spec ─► [G1 Spec Review] ─► S2 Plan ─► S3 Scaffold + Test Env ─► S4 Build (milestones)
                 ▲                                                                        │
                 └──────── spec delta (reopens G1 for the delta only) ◄───────────────────┤
                                                                                          ▼
 S7 Operate ◄─ S6 Launch ◄─ [G2 Test Review] ◄──────────────────── S5 System Test + Hardening
```

| Stage | Owner agent(s) | Input | Output (artifact in repo) | Exit criteria (automated check) |
|---|---|---|---|---|
| **S0 Intake** | orchestrator | Design docs | `docs/design/*` committed | Design docs present on `main` |
| **S1 Spec** | product-manager, architect, ux-designer, qa-engineer | Design docs | `docs/specs/INSMARTFIX_V1_SPEC.md`, `docs/testing/TEST_PLAN.md`, `docs/launch/LAUNCH_PLAN.md` | Every design § mapped to a requirement ID; every requirement has an acceptance criterion and a planned test |
| **G1** | **human** | Spec PR | Approval + answers to the spec's decision log | PR approved |
| **S2 Plan** | architect | Approved spec | `docs/plans/IMPLEMENTATION_PLAN.md` — milestones, tasks, dependency order, per-task test IDs | Every FR covered by ≥1 task |
| **S3 Scaffold + Test Env** | devops-engineer | Plan | Monorepo, Docker Compose env, CI workflows, seed data, OpenAPI contract | `docker compose up` healthy; CI green on an empty-feature skeleton |
| **S4 Build** | backend-engineer, web-engineer, mobile-engineer | Plan + contract | One PR per milestone task, test-first | See §2 automated PR gate; auto-merge when green |
| **S5 System Test + Hardening** | qa-engineer, security-reviewer, ux-designer | `main` | E2E runs on web/Android/iOS, security review, a11y/perf reports, `docs/testing/TEST_REVIEW_REPORT.md` | TEST_PLAN §8 exit criteria all met |
| **G2** | **human** | Release PR + Test Review Report | Approval | PR approved |
| **S6 Launch** | release-manager, devops-engineer | Approved RC | Tagged release, staging → beta → production per LAUNCH_PLAN | Smoke tests pass at each ring; rollback rehearsed |
| **S7 Operate** | devops-engineer, qa-engineer | Production | Monitoring, incident log, feedback into next slice spec | Error-rate / crash-free SLOs held for 7 days |

## 2 · The automated PR gate (S4, no human needed)

Every build PR goes through this sequence. A PR auto-merges (squash) to `main` only if all pass:

1. **CI** — lint, typecheck, unit + integration tests, contract tests, coverage thresholds (TEST_PLAN §4), build of every affected app.
2. **Code review agent** — runs `/code-review high` on the diff. Any CONFIRMED correctness finding blocks; the author agent fixes and re-runs (max 3 loops, then escalate as *blocked*).
3. **Security review agent** — mandatory when the diff touches `auth`, identity binding, `/contractor/*` gates, uploads, or token handling (design §13, R10).
4. **Design compliance (ux-designer agent)** — for UI diffs: color roles (status scale only on health/risk; one teal per view), 44pt targets, 16px min body, every state from design §10 present.
5. **Spec conformance** — PR description lists the FR/AC IDs it implements and the test IDs that prove them; a script checks those test IDs exist and pass.

Conventions: branch `feat/<milestone>-<task>`, Conventional Commits, PR template in `.github/pull_request_template.md`. Never commit secrets; secrets live in GitHub Actions secrets / environments.

## 3 · Test-first loop inside each task

```
read FR + AC  ─►  write failing tests (unit/contract/e2e IDs from TEST_PLAN)  ─►  implement  ─►  green locally
   ─►  open PR  ─►  §2 gate  ─►  auto-merge  ─►  nightly full E2E on main (web + Android + iOS)
```

A nightly failure on `main` opens a GitHub issue labeled `regression` and the owning agent fixes it before the next milestone starts.

## 4 · Milestones (detailed in S2 plan)

| # | Milestone | Main agents |
|---|---|---|
| M1 | Contract + backend core: auth, identity gate, schedule, accept/decline, SLA expiry/re-offer | backend |
| M2 | Backend job flow: WO detail + packet, lifecycle events + undo, completion + calibration, photos, failure codes | backend |
| M3 | Shared packages: design tokens, `core` logic (SLA formatter, ordering, validation, draft/queue), generated API client | web + mobile |
| M4 | Web portal (Next.js): login, inbox, detail, completion, account, all states | web |
| M5 | Mobile app (Expo — iOS + Android): same screens, secure storage, offline queue | mobile |
| M6 | Hardening: offline, a11y, performance, security pass, visual regression baseline | qa, security, ux |

M4 and M5 run in parallel once M3 lands.

## 5 · Blocked-state reporting

When an agent is blocked it posts one comment on the active PR (or an issue labeled `blocked`) with: what is blocked, why, what it already tried, and the smallest thing the human can do to unblock. It then continues any work that doesn't depend on it.
