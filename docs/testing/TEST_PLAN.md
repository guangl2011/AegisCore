# InsmartFix v1 — Test Plan & Test Environments

**Version:** 1.0 · **Date:** 2026-11-02 · **Status:** ✅ Approved at G1 with the spec; executed in S4–S5; results judged at **G2 Test Review**.
**Traces to:** [`docs/specs/INSMARTFIX_V1_SPEC.md`](../specs/INSMARTFIX_V1_SPEC.md) (FR/NFR IDs).

---

## 1 · Objectives

1. Prove every FR acceptance criterion on **all three clients** (web, Android, iOS) where it applies.
2. Prove the two never-break guarantees (D§11): **a completion is never lost**, and **the inbox self-heals / accept is server-authoritative**.
3. Prove the **identity gate** can't be bypassed (FR-1.4, R10).
4. Prove every state in design §10 exists and renders correctly (loading, empty, error, offline, special).
5. Prove color discipline, accessibility and field ergonomics (NFR-2–4).

## 2 · Test levels & tooling

| Level | Scope | Tooling | Runs |
|---|---|---|---|
| **Unit (API)** | services, identity gate, calibration labeler, SLA expiry, lifecycle derivation | pytest, hypothesis (property tests) | every PR |
| **Integration (API)** | routes against a real Postgres + MinIO | pytest + httpx, testcontainers / CI services | every PR |
| **Contract** | API conforms to `openapi.json`; generated client in sync | schemathesis (fuzz against the schema), `openapi-diff` drift check | every PR |
| **Unit (shared core)** | SLA formatter, ordering, validation, draft store, offline queue | vitest | every PR |
| **Component (web)** | each component in every state | vitest + React Testing Library + MSW | every PR |
| **Component (mobile)** | each screen in every state | jest + React Native Testing Library + MSW | every PR |
| **E2E (web)** | full loop on mobile viewports (Pixel 7, iPhone 14) + desktop | Playwright against the compose stack (live) | every PR (smoke) · nightly (full) |
| **E2E (Android)** | full loop on emulator, API 34 | Maestro on GitHub Actions ubuntu + KVM | nightly + release |
| **E2E (iOS)** | full loop on simulator, iPhone 15 / iOS 17 | Maestro on GitHub Actions macOS runner | nightly + release |
| **Accessibility** | axe (web), RN a11y lint + labels audit (mobile), contrast check on tokens | @axe-core/playwright, eslint-plugin-react-native-a11y | every PR (web) · nightly |
| **Visual regression** | screenshot per screen × state × theme | Playwright screenshots (web), Maestro screenshots (mobile) | nightly; baseline approved at G2 |
| **Performance** | API load; web Lighthouse | k6 (50 rps, 10 min); Lighthouse CI | nightly on staging |
| **Security** | identity-gate matrix, authz fuzzing, dependency and secret scan, OWASP ZAP baseline | pytest matrix, schemathesis auth checks, pip-audit, pnpm audit, gitleaks, ZAP | every PR (scans) · release (ZAP) |
| **Resilience / chaos** | offline, flaky network, 5xx injection, app kill, clock skew | Playwright `setOffline` + route interception; Maestro `stopApp` / airplane mode; toxiproxy on API | nightly |

## 3 · Test environments

| Env | Purpose | How it's built | Data | Who uses it |
|---|---|---|---|---|
| **local-mock** | UI dev, demos with no backend | `pnpm dev:mock` — `DATA_SOURCE=mock`, MSW | contract fixtures | engineers, demos |
| **local-stack** | full loop locally | `docker compose -f infra/docker-compose.yml up` → postgres, minio, api, web (+ toxiproxy) ; mobile via Expo Go / dev client pointing at the local API | `make seed` | engineers, agents |
| **ci-ephemeral** | per-PR and nightly verification | GitHub Actions spins up the same compose stack; Android emulator (KVM) and iOS simulator (macOS) run against it | seeded fresh per run | CI |
| **staging** | release candidate verification, G2 evidence, perf/ZAP | auto-deployed from `main` after green CI (host per spec D8); Postgres with nightly reset; mobile *preview* builds via EAS internal distribution | `make seed ENV=staging` + test accounts below | QA agent, product owner at G2 |
| **production** | live | promoted from the tagged RC after G2 | real | contractors |

**Environment parity:** one Dockerfile per service is used by local, CI and staging. Config only through env vars (`DATABASE_URL`, `S3_*`, `JWT_SECRET`, `DATA_SOURCE`, `API_BASE_URL`). Clocks: the API can run with `FAKE_CLOCK=1` in test environments, controlled via `POST /__test/clock` (route compiled out of production builds) so SLA tests are deterministic.

## 4 · Coverage & quality thresholds (CI-enforced)

| Package | Line coverage | Branch coverage |
|---|---|---|
| `apps/api` | ≥ 85% | ≥ 80% |
| `apps/api` modules `identity_gate`, `dispatch`, `calibration` | ≥ 95% | ≥ 90% |
| `packages/core` | ≥ 95% | ≥ 90% |
| `apps/web`, `apps/mobile` | ≥ 75% | — |

Plus: 0 lint errors, 0 type errors, 0 high/critical vulnerable dependencies, 0 secrets detected, 0 axe serious/critical violations.

## 5 · Test data (seed fixtures)

| Fixture | Purpose |
|---|---|
| Tenant **Midtown Properties**; owner `owner@test.insmart.ai` | owner override, dispatch API |
| Contractor **Marco Rossi** `marco@test.insmart.ai` (company Rossi HVAC) | primary persona |
| Contractor **Ana Lee** `ana@test.insmart.ai` | second candidate: reassign, race and spoof tests |
| Contractor **Zed** in another tenant `zed@other.insmart.ai` | cross-tenant isolation |
| Asset **RTU-04**, Midtown Tower Roof, full packet, predicted `COMP-CONTACTOR` 82% | happy path |
| Asset **AHU-NEW-01**, no history, `pre_diagnostic_available=false` | no-packet fallback |
| Offers with SLA at 12 m, 4 m, 45 s, and already past the deadline | SLA label table, ordering, expiry |
| One ACCEPTED and one ARRIVED job for Marco | active group, ordering, resume |

Passwords for test accounts live in the GitHub `staging` environment secrets, never in the repo.

## 6 · Test cases (traceability matrix)

IDs: `T-<area>-<n>`. Platform: **A**=API, **W**=web, **D**=Android, **I**=iOS.

### 6.1 Auth & identity
| ID | Case | FR | Platforms |
|---|---|---|---|
| T-AUTH-1 | Valid login → inbox | 1.1 | A W D I |
| T-AUTH-2 | Bad credentials → inline error, fields kept | 1.1 | W D I |
| T-AUTH-3 | Network down at login → connection message + Retry works | 1.1 | W D I |
| T-AUTH-4 | JWT not readable from JS on web (cookie flags, no storage) | 1.2 | W |
| T-AUTH-5 | Token stored only in secure store on mobile | 1.3 | D I |
| T-AUTH-6 | **Identity-gate matrix**: {contractor own, contractor other, owner same tenant, owner other tenant, no token, expired token} × {schedule, accept, decline, get WO, transition, photo, complete} → expected 2xx/401/403/404 for every cell | 1.4 | A |
| T-AUTH-7 | Editing the URL or id in a web request cannot act as another contractor (proxy ignores a client-sent id) | 1.4 | W |
| T-AUTH-8 | Login rate-limit triggers after 5 attempts | NFR-6 | A |

### 6.2 Inbox & SLA
| ID | Case | FR | Platforms |
|---|---|---|---|
| T-INBOX-1 | Offers sorted soonest deadline first; active sorted by most recently advanced | 2.2 | A W D I |
| T-INBOX-2 | OfferCard anatomy; status color only on the risk line (DOM/style assertion) | 2.3, NFR-4 | W D I |
| T-SLA-1 | Formatter table: 12m / 4m (medium) / 45s (bold) / Expiring / Expired, no color | 2.4 | core |
| T-SLA-2 | Device clock off by ±5 min → countdown still matches server time | 2.4 | W D I |
| T-INBOX-3 | Auto-refresh at 20 s and on focus picks up a new offer | 2.5 | W D I |
| T-INBOX-4 | Refresh failure keeps last list + error + Retry | 2.5, 2.7 | W D I |
| T-INBOX-5 | **Stale-offer race**: Ana's offer expires/reassigns while Marco's countdown shows time → Marco taps Accept → 409 → toast → card leaves | 2.6, 5.3 | A W D I |
| T-INBOX-6 | Empty offers copy; empty active collapses | 2.7 | W D I |
| T-INBOX-7 | Skeleton shown during load (no spinner) | 2.7 | W D I |
| T-INBOX-8 | Offline banner, read-only cards | 2.7 | W D I |
| T-DISP-1 | Concurrent accept by two contractors → exactly one 200 (100-iteration property test) | 5.3 | A |
| T-DISP-2 | Expiry by sweeper with no traffic, and lazily on read | 5.1, 5.2 | A |
| T-DISP-3 | Decline/expiry re-offers to next rank; last candidate → NO_CONTRACTORS | 4.3, 5.1 | A |

### 6.3 Detail & packet
| ID | Case | FR | Platforms |
|---|---|---|---|
| T-WO-1 | Decision summary renders health (band color + number + label), risk, cause, action, evidence expand | 3.2 | W D I |
| T-WO-2 | Packet sections all render for RTU-04 | 3.3 | W D I |
| T-WO-3 | **No-packet fallback** for AHU-NEW-01: exact copy, no empty boxes, no cause shown | 3.4 | A W D I |
| T-WO-4 | Contractor response contains no `ranked_candidates` key | 3.5 | A |
| T-WO-5 | Sticky bar shows exactly one primary action per state; always visible while scrolling | 3.7 | W D I |
| T-WO-6 | Loading / error + Retry / offline-last-packet states | 3.8 | W D I |

### 6.4 Accept / decline / lifecycle
| ID | Case | FR | Platforms |
|---|---|---|---|
| T-ACC-1 | Accept returns full packet; detail ready without a second fetch | 4.1 | A W D I |
| T-DEC-1 | Decline with reason persisted; Skip declines in one tap; sheet dismissible | 4.2 | A W D I |
| T-LIFE-1 | En route → Arrived with confirm; events appended | 6.1, 6.2 | A W D I |
| T-LIFE-2 | Undo within 10 s appends CORRECTION; stage reverts; history intact | 6.3 | A W D I |
| T-LIFE-3 | Out-of-order transition → 409; duplicate idempotency key → same event | 6.4 | A |
| T-LIFE-4 | Stage advanced on device 1 shows on device 2 after refresh | 6.4 | W D |
| T-MEM-1 | App DB role cannot UPDATE/DELETE `memory_events` | 6.1 | A |

### 6.5 Completion & calibration
| ID | Case | FR | Platforms |
|---|---|---|---|
| T-COMP-1 | Required-field validation (failure code, matched toggle, labor bounds) | 7.1 | core W D I |
| T-COMP-2 | Predicted code offered first; override saves the contractor's code | 7.1, 7.4 | W D I |
| T-COMP-3 | **Draft survives**: navigate away, reload (web), background + kill (mobile) | 7.2 | W D I |
| T-COMP-4 | **Submit failure keeps data**: 500 and timeout → message + Retry → success | 7.3 | W D I |
| T-COMP-5 | **Offline queue**: submit offline → banner → reconnect → auto-flush once → calibration recorded once | 7.3 | W D I |
| T-COMP-6 | Idempotent repeat submit; different key after completion → 409 | 7.4 | A |
| T-CAL-1 | Labels MATCH / PARTIAL / MISS / NO_PREDICTION (property test over the code catalog) | 7.5 | A |
| T-COMP-7 | Success copy then Inbox navigation; draft cleared | 7.6 | W D I |
| T-PHOTO-1 | Upload valid image; reject > 10 MB and non-image; EXIF GPS stripped | 7.7 | A W D I |
| T-PHOTO-2 | Photo queued offline then uploaded before the completion flush | 7.7 | D I |

### 6.6 Account, shell, theming, a11y
| ID | Case | FR/NFR | Platforms |
|---|---|---|---|
| T-ACCT-1 | Account shows identity; sign out clears session and warns about unsent drafts | 8.1 | W D I |
| T-NAV-1 | Two nav items + disabled Voice stub; routes resolve | 9.1 | W D I |
| T-A11Y-1 | axe: 0 serious/critical on every screen × state | NFR-3 | W |
| T-A11Y-2 | Screen reader announces countdown, pills, risk labels | NFR-3 | W D I |
| T-ERGO-1 | All interactive elements ≥ 44×44 pt; body ≥ 16 px (automated measurement) | NFR-2 | W D I |
| T-THEME-1 | Light + dark visual baseline for every screen; status solids only in `HealthScore`/`RiskBadge` (lint) | NFR-4, NFR-9 | W D I |
| T-PERF-1 | k6: p95 < 300 ms at 50 rps | NFR-1 | A |
| T-PERF-2 | Lighthouse (mobile, throttled): perf ≥ 85, a11y ≥ 95 | NFR-1, NFR-3 | W |

## 7 · Defect management

Defects are GitHub issues labeled `bug` + severity:
- **P0** — data loss, security or identity bypass, crash on the core loop.
- **P1** — a core-loop step can't be completed on a platform, or a wrong calibration label.
- **P2** — a state or copy deviates from the design, or an a11y issue with a workaround.
- **P3** — cosmetic.

The QA agent files them; the owning engineer agent fixes P0/P1 immediately, before continuing feature work.

## 8 · Exit criteria (what G2 checks)

1. 100% of T-cases executed on every listed platform; pass rate 100% for P0/P1-mapped cases, ≥ 98% overall with every failure triaged.
2. 0 open P0/P1; P2s listed with a fix plan.
3. Coverage thresholds (§4) met.
4. Security: identity-gate matrix 100% green, ZAP baseline with 0 high findings, security-reviewer agent sign-off.
5. Visual baselines for every screen × state × theme × platform attached for review.
6. NFR-1 performance numbers from staging.
7. Rollback rehearsed on staging (LAUNCH_PLAN §4).

## 9 · Test Review Report (the G2 artifact)

The QA agent generates `docs/testing/TEST_REVIEW_REPORT.md` and publishes a visual version linked from the release PR:
- Summary verdict per exit criterion (✅/❌ with evidence links).
- Results by level and platform, with CI run links.
- Traceability: FR → T-cases → result.
- Coverage table.
- Open defects by severity.
- Screenshot gallery: each screen × state on web / Android / iOS, light and dark.
- Known limitations and deferred items.
