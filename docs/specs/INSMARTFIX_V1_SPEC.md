# InsmartFix v1 — Product & Technical Specification

**Version:** 1.0-draft · **Date:** 2026-11-02 · **Status:** ⏳ Awaiting **G1 Spec Review**
**Source of truth for *what/why/feel*:** [`docs/design/INSMARTFIX_PRODUCT_DESIGN.md`](../design/INSMARTFIX_PRODUCT_DESIGN.md) (v1.0) and [`docs/design/COLOR_LANGUAGE.md`](../design/COLOR_LANGUAGE.md) (v1.3).
**This doc adds:** testable requirements, the API contract, architecture, and the decisions the design left open. Section references like "D§6.2" point into the design doc.

---

## 1 · Decision log — please confirm at G1

Each row has a recommendation. Approving the spec PR accepts every recommendation you don't change.

| ID | Question | Recommendation | Why |
|---|---|---|---|
| **D1** | Backend: does AegisCore build the FastAPI backend, or point at an existing Insmart backend? | **Build it in AegisCore**, implementing the contract in §5. The Decision Engine and asset memory are behind adapters (§4.3); v1 ships a seeded stub engine and a Postgres-backed append-only memory. | AegisCore is empty, and the design assumes a backend exists. Owning the contract here lets every client be tested end to end. If a live Insmart backend exists, swap the adapter, not the clients. |
| **D2** | Completion photo (D§6.6, D§15.1) | **Include in v1**: optional, up to 4 photos, `photo_ids` on `CompletionReport`, upload via `POST /workorders/{wo}/photos`. | The PRD asks for it, and the contract isn't frozen in this repo yet. Cheap now, a contract break later. |
| **D3** | Offline submit depth (D§15.2) | **Queued auto-flush submit**: draft is always saved, and a failed or offline submit queues and retries when the connection returns. An `idempotency_key` makes retries safe. | The idempotency key removes the double-submit risk that usually makes queues dangerous. |
| **D4** | Push notifications (D§15.3) | **Out of v1.** Pull + auto-refresh (20 s and on focus). | As designed. |
| **D5** | Brand teal | **`#0396A6`** (COLOR_LANGUAGE v1.3), not `#12879A` from the design doc. The app stays in the light register; no navy. | COLOR_LANGUAGE §8 says to re-point. |
| **D6** | Mobile stack | **Expo (React Native, TypeScript)**, one codebase for iOS and Android, sharing `core`, tokens and the API client with the web app. | One team, one logic layer, identical behavior on all three clients. Native Swift/Kotlin would roughly double M5. |
| **D7** | "Web portal" meaning | **The InsmartFix contractor web app** (Next.js, mobile-first), the same product as the mobile apps. The owner/dispatcher portal stays in Insmart Core (D§2). A minimal **dispatch API** (owner/FM role) plus seed scripts create offers for testing and demos. | Matches the design's IA (D§5). Dana's UI is a later slice (D§14). |
| **D8** | Hosting for staging and production | **Needs your input before S6 only** (doesn't block build). Default plan: container images to GHCR; API + Postgres + web on one managed container host (e.g. Fly.io or Render); mobile via Expo EAS → TestFlight and Play internal track. | Requires your accounts: a hosting provider, an Apple Developer account, a Google Play Console account, and an Expo account. |
| **D9** | Credentials | **Hashed passwords (argon2id) from day one**, admin-seeded accounts; no self-service sign-up in v1. | Hashing is as cheap as the interim store. Self-service onboarding stays a follow-up (D§14). |
| **D10** | Pre-build security review (D§15.4) | Run the **security-reviewer agent on this spec's identity gate and event model** before M1 merges, and again on code in M6. | Closes the review that died on an API error. |

---

## 2 · Scope

**In v1:** Login · Offer Inbox (offers + active jobs, auto-refresh) · Work Order detail with decision summary and pre-diagnostic packet (incl. no-packet fallback) · Accept / Decline (optional reason) · Lifecycle (En route → Arrived → Complete) with confirm and undo · Completion form (failure code, fault-matched toggle, parts, labor, notes, technician, photos) with local draft and queued submit · Calibration labeling · Account / sign out · Light and dark themes · Web, iOS, Android.

**Out of v1:** push notifications, Voicequest (a disabled nav stub only), dispatcher (Dana) UI, ratings pipeline, self-service onboarding, i18n (English only, D§9).

---

## 3 · Functional requirements

Format: **FR-x.y** requirement → **AC** acceptance criteria (Given/When/Then, condensed). Test IDs live in TEST_PLAN §6.

### FR-1 Authentication & identity (D§6.1, D§13)
- **FR-1.1** Email + password login. *AC:* valid credentials → session established and user lands on `/inbox`. Invalid → "Email or password is incorrect", fields preserved. Network failure → "Can't reach InsmartFix. Check your connection and try again." + Retry.
- **FR-1.2** Web session is an httpOnly, Secure, SameSite=Lax cookie set by the Next.js `/api/auth/login` proxy. *AC:* no JWT is readable from `document.cookie`, localStorage, or JS memory.
- **FR-1.3** Mobile stores the token in the OS keychain/keystore (`expo-secure-store`) only.
- **FR-1.4** A contractor principal carries exactly one `contractor_id` in the token. Clients never send their own id: the web proxy injects it, and mobile calls `/me/*` aliases. *AC:* a request for `/contractor/{other_id}/…` by a contractor → **403**; `/workorders/{wo}` actions on a WO not bound or offered to them → **403/404**; owner/FM roles keep a tenant-wide override; cross-tenant → **404**.
- **FR-1.5** Sign in is enabled only when both fields are non-empty, and the form is disabled with a spinner while submitting.

### FR-2 Offer Inbox (D§6.2, D§7.5, D§11)
- **FR-2.1** Two groups: **Offers** (PENDING) and **Active** (ACCEPTED / IN_PROGRESS). A **voice bookings** group is supported by the contract (always empty in v1, `wo_source` shown).
- **FR-2.2** Offers are sorted by soonest `sla_deadline`; Active by most recent `last_advanced_at`.
- **FR-2.3** OfferCard shows asset · site, SLA countdown, symptom, packet teaser ("Likely: X · NN% match"), and risk/health with a text label. Reserved status color appears **only** on that risk/health line.
- **FR-2.4** SLA countdown follows the D§7.5 table exactly (thresholds, labels, weights, no color). The countdown is computed against **server time** (`server_time` in each response) to cancel device clock skew.
- **FR-2.5** Auto-refresh every **20 s** while visible, and immediately on focus or visibility change. A refresh failure keeps the last list visible and shows an error with Retry.
- **FR-2.6** Accept is server-authoritative. On `409 OFFER_UNAVAILABLE` → toast "This offer just expired — it's been reassigned", and the card animates out on the next refresh.
- **FR-2.7** States: skeleton loading; empty offers ("No open offers right now. We'll show new dispatch here the moment it arrives."); empty Active section collapses; error with last-known list; offline banner "You're offline — showing your last update" with read-only cards.
- **FR-2.8** Active-job cards show the lifecycle stage and open the detail; no Accept/Decline.

### FR-3 Work Order detail & pre-diagnostic packet (D§6.3, D§12)
- **FR-3.1** Header: asset, site + location, symptom, a neutral state pill, and the SLA countdown if time-bound.
- **FR-3.2** Decision summary: health score (band solid color + number), failure-risk band + label, probable root cause, recommended action, and a confidence line ("Based on N recent events + M active insights") that expands to the evidence.
- **FR-3.3** Packet sections: asset identity, recent events, recent maintenance, active insights, predicted parts.
- **FR-3.4** When `pre_diagnostic_available=false`: show the honest no-history panel (exact copy from D§6.3) and a symptom-only summary. No fabricated cause, no empty boxes.
- **FR-3.5** The contractor never sees other contractors' rankings. The API response for the contractor role **omits** `ranked_candidates` entirely; it is not merely hidden in the UI.
- **FR-3.6** Before accepting, a contractor sees the **teaser and decision summary**, and the full packet is available on the detail screen (D§1 "before they accept"). Accept also returns the full packet synchronously.
- **FR-3.7** A sticky bottom action bar holds the single primary action for the current state (Accept → Mark en route → Mark arrived → Start completion → Submit).
- **FR-3.8** States: skeleton loading, error + Retry, offline (last-fetched packet + banner).

### FR-4 Accept / Decline (D§6.4)
- **FR-4.1** Accept: optimistic "Accepting…", then the server binds the WO (dispatch → ACCEPTED) and returns the WorkOrderDetail.
- **FR-4.2** Decline opens a dismissible sheet with optional reason chips (*Too far · No capacity · Wrong skill · Other* + optional note) and **Skip**. One tap to decline must remain possible. The reason is persisted on the dispatch record.
- **FR-4.3** A declined offer is re-offered server-side to the next ranked candidate. If none remain → `NO_CONTRACTORS` (visible to owner/FM).

### FR-5 SLA expiry & re-offer (server, D§6.2)
- **FR-5.1** Each offer has an `sla_deadline`. Past the deadline the server marks it EXPIRED and re-offers to the next ranked candidate (new deadline) or sets `ESCALATED` / `NO_CONTRACTORS`.
- **FR-5.2** Expiry runs both lazily (any read or write touching the offer) and in a sweeper every 15 s, so state is correct without depending on traffic.
- **FR-5.3** Accept is atomic against expiry (row lock or compare-and-set on dispatch version). Exactly one winner in a race.

### FR-6 Lifecycle (D§6.5)
- **FR-6.1** Stages: `EN_ROUTE`, `ARRIVED` (both within backend `IN_PROGRESS`), then completion. Advancing appends an immutable memory event `{wo, stage, actor, at, idempotency_key}`.
- **FR-6.2** Each advance shows a lightweight inline confirm ("Mark arrived? This is logged."), then an **Undo** affordance for 10 s.
- **FR-6.3** Undo appends a `CORRECTION` event that references the corrected event id. The derived current stage reflects corrections; history is never mutated or deleted.
- **FR-6.4** Transitions are idempotent by key, and must follow order (no `ARRIVED` before `EN_ROUTE`) → otherwise `409 INVALID_TRANSITION`. They work across devices: the derived stage is server state.

### FR-7 Completion & calibration (D§6.6, D§11)
- **FR-7.1** Fields: `failure_code` (required, searchable, pre-filtered by asset subtype, with the predicted code offered first as "Confirm: …"); `actual_fault_matched` (bool, required); `parts_used[]` `{part_code?, description, qty}`; `labor_hours` (required, 0 < h ≤ 24, 0.25 step); `notes` (optional, ≤ 4000 characters); `technician_id` (self-reported free text, defaults to the user's name); `photo_ids[]` (0–4, D2).
- **FR-7.2** The draft autosaves on every change (debounced 300 ms) to local storage keyed by WO, and survives navigation, reload, backgrounding and app kill. The draft is cleared only after a confirmed successful submit.
- **FR-7.3** Submit is explicit, not optimistic. On failure: "Couldn't submit — your entry is saved. Retry", with the form intact. Offline: queued, with a banner "Saved — will submit when you're back online"; the queue flushes automatically when the connection returns (D3).
- **FR-7.4** `failure_code` is set once and append-only. The predicted code is never written unless the contractor chose it. A repeat submit with the same idempotency key returns the original result; a different key on a completed WO → `409 ALREADY_COMPLETED`.
- **FR-7.5** Calibration: the server labels the decision **MATCH** (same failure code as predicted), **PARTIAL** (same component group), **MISS** (different group), or **NO_PREDICTION** (no packet). It stores the label alongside `actual_fault_matched`, and appends the outcome to the asset's memory.
- **FR-7.6** Success: "Logged. This updates {asset}'s record and the system's prediction." → navigate to Inbox.
- **FR-7.7** Photo upload: JPEG/PNG/HEIC, ≤ 10 MB each, resized client-side to ≤ 2048 px, EXIF GPS stripped server-side, stored in S3-compatible storage. Uploads queue offline like the submit.

### FR-8 Account (D§6.7)
- **FR-8.1** Shows name, company and a `contractor_id` badge, a support link, and Sign out (clears cookie/keychain **and** local drafts for that user after confirming any unsent drafts).

### FR-9 Shell & navigation (D§5)
- **FR-9.1** Top bar + bottom nav with two items (Inbox, Account) and a disabled "Voice intake" stub. Routes: `/login`, `/inbox`, `/jobs/[id]`, `/account` (same structure in expo-router).

### FR-10 Dispatch & seed API (owner/FM — test and demo support, D7)
- **FR-10.1** Owner/FM can create a work order with a ranked candidate list and an SLA window (`POST /dispatch/workorders`), and view dispatch state including `ranked_candidates`.
- **FR-10.2** `make seed` loads the fixture dataset (TEST_PLAN §5) into any non-production environment.

---

## 4 · Architecture

### 4.1 Repository layout (pnpm + Turborepo monorepo; Python via uv)
```
apps/
  api/        FastAPI · Python 3.12 · Pydantic v2 · SQLAlchemy 2 · Alembic · Postgres 16
  web/        Next.js 15 (App Router, RSC) · TypeScript · Tailwind wired to tokens
  mobile/     Expo SDK (React Native) · expo-router · TypeScript
packages/
  contracts/  openapi.json (exported from api) → generated TS types + typed fetch client
  core/       pure TS: SLA formatter, ordering, completion validation, draft store + offline queue (storage-adapter based)
  tokens/     COLOR_LANGUAGE v1.3 → CSS variables (web) + RN theme object (mobile), light + dark
  ui-web/     web component kit (D§7.4)
infra/        docker-compose.yml, Dockerfiles, seed data, k6 scripts
.github/      CI workflows, PR template
```

### 4.2 Request flow
- **Web:** Browser → Next.js server (RSC and `/api/*` route handlers; reads the httpOnly cookie and injects the bearer token and `contractor_id`) → FastAPI. No direct browser → API calls.
- **Mobile:** App → FastAPI directly with a bearer token, using `/me/*` routes (server resolves `contractor_id` from the token).
- **`DATA_SOURCE=mock`** (web + mobile): the client talks to an MSW mock implementing the same contract, generated from `packages/contracts` fixtures, for offline demos and fast UI tests. `live` talks to the API. Same screens, same code paths (D§13).

### 4.3 Backend modules
| Module | Responsibility |
|---|---|
| `auth` | login, argon2id, JWT (HS256, 12 h, claims: `sub, role, tenant_id, contractor_id`), `get_principal` dependency |
| `identity_gate` | single policy function `authorize(principal, action, wo)`, used by **every** contractor route (one place to review) |
| `dispatch` | offers, ranked candidates, accept/decline, SLA expiry sweeper, re-offer, optimistic-locking `version` |
| `workorders` | WO read model, lifecycle derivation from events |
| `memory` (adapter) | append-only `memory_events` table (no UPDATE/DELETE grants for the app role); the `MemorySeam` interface |
| `decision_engine` (adapter) | `get_packet(asset)`, `predicted_failure_code`; v1 = `StubDecisionEngine` reading seeded packets |
| `calibration` | MATCH/PARTIAL/MISS/NO_PREDICTION labeling, `calibration_records` |
| `media` | photo upload, validation, EXIF strip, S3 (MinIO in dev/test) |
| `catalog` | failure codes by asset subtype + component group |

### 4.4 Data model (core tables)
`tenants` · `users(id, tenant_id, email, password_hash, role, contractor_id?)` · `contractors(id, tenant_id, name, company, avg_rating)` · `sites` · `assets(id, site_id, name, subtype, make, model, install_year, location, duty)` · `workorders(id, tenant_id, asset_id, symptom, wo_source, status, failure_code?, completed_at?)` · `dispatch(wo_id, state, current_contractor_id?, sla_deadline, version, decline_reason?)` · `dispatch_candidates(wo_id, contractor_id, rank, match_score, match_reason, state)` · `memory_events(id, asset_id, wo_id, type, payload jsonb, actor, at, idempotency_key unique, corrects_event_id?)` · `completion_reports(wo_id pk, …, idempotency_key)` · `calibration_records(wo_id, predicted_code, actual_code, label)` · `photos(id, wo_id, key, content_type, bytes)` · `failure_codes(code, subtype, component_group, label)`.

Dispatch states: `UNDISPATCHED → PENDING → ACCEPTED → (IN_PROGRESS) → COMPLETED`, plus `EXPIRED` (per candidate), `ESCALATED`, `NO_CONTRACTORS`. `Maintenance.status` stays on the PRD's sequence; `ARRIVED` is derived from events only (D§6.5 terminology note).

---

## 5 · API contract (v1)

Base path `/v1`. JSON. Errors: `{"error": {"code": "STRING", "message": "human text"}}`. Every response includes `server_time` (ISO-8601 UTC). Mutations accept an `Idempotency-Key` header.

| Method & path | Role | Request | Success | Errors |
|---|---|---|---|---|
| `POST /auth/login` | public | `{email, password}` | `{access_token, expires_at, user}` | 401 `INVALID_CREDENTIALS`, 429 rate-limited |
| `GET /me` | any | — | `{user_id, name, role, tenant_id, contractor_id?, company?}` | 401 |
| `GET /contractor/{cid}/schedule` · alias `GET /me/schedule` | contractor (own), owner/FM | — | `{offers: OfferSummary[], active: OfferSummary[], voice_bookings: [], server_time}` | 403 |
| `POST /contractor/{cid}/accept/{wo}` · alias `POST /me/accept/{wo}` | contractor (own) | — | `WorkOrderDetail` | 409 `OFFER_UNAVAILABLE {reason: expired\|reassigned\|withdrawn}`, 403 |
| `POST /contractor/{cid}/decline/{wo}` · alias `/me/decline/{wo}` | contractor (own) | `{reason?: too_far\|no_capacity\|wrong_skill\|other, note?}` | `204` | 409, 403 |
| `GET /workorders/{wo}` | offered/bound contractor, owner/FM | — | `WorkOrderDetail` | 404 |
| `POST /workorders/{wo}/transition` | bound contractor | `{action: advance\|undo, stage?: EN_ROUTE\|ARRIVED, corrects_event_id?}` | `{lifecycle_stage, event_id, history[]}` | 409 `INVALID_TRANSITION` |
| `POST /workorders/{wo}/photos` | bound contractor | multipart `file` | `{photo_id}` | 413, 415 |
| `POST /workorders/{wo}/complete` | bound contractor | `CompletionReport` | `{calibration_label, record_updated: true}` | 422 validation, 409 `ALREADY_COMPLETED` |
| `GET /failure-codes?subtype=` | any | — | `FailureCode[]` | — |
| `POST /dispatch/workorders` | owner/FM | `{asset_id, symptom, sla_minutes, candidates:[{contractor_id, match_score, reason}]}` | `{wo_id}` | 422 |
| `GET /healthz`, `GET /readyz` | public | — | `200` | — |

**OfferSummary:** `wo_id, asset{id,name,subtype}, site{name,location}, symptom, wo_source, dispatch_state, lifecycle_stage?, sla_deadline?, match_score, match_reason, teaser{likely_cause?, confidence?}, health_score?, failure_risk?, last_advanced_at?`

**WorkOrderDetail:** `OfferSummary` + `decision{health_score, failure_risk, root_cause, recommended_action, evidence_summary, evidence[]}?` + `pre_diagnostic_available: bool` + `packet{asset_identity, recent_events[], recent_maintenance[], active_insights[], predicted_parts[]}?` + `lifecycle_history[]` + `predicted_failure_code?`. Never includes `ranked_candidates` for the contractor role.

**CompletionReport:** `failure_code, actual_fault_matched, parts_used[{part_code?, description, qty}], labor_hours, notes?, technician_id, photo_ids[]`.

The contract is exported to `packages/contracts/openapi.json` on every API build; CI fails if the generated client drifts.

---

## 6 · Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-1 Performance | API p95 < 300 ms at 50 rps on staging; inbox first contentful paint < 1.5 s on throttled 4G (web); mobile cold start < 2.5 s on a mid-range Android. |
| NFR-2 Field UX | Tap targets ≥ 44×44 pt; body text ≥ 16 px; primary action always in the sticky bar; usable one-handed. |
| NFR-3 Accessibility | WCAG 2.2 AA; axe: 0 serious/critical violations; status always paired with a label; screen-reader labels on the countdown and pills. |
| NFR-4 Color discipline | Status hex values used only by `HealthScore` and `RiskBadge` components (enforced by a lint rule); one `--brand` primary button per view. |
| NFR-5 Resilience | No completion data loss under offline, reload, app kill or 5xx (tested). Inbox self-heals within 20 s. |
| NFR-6 Security | OWASP ASVS L1; login rate-limit (5/min/IP+email); JWT secret ≥ 256-bit from env; CORS locked; security headers (CSP, HSTS) on web; no PII in logs; dependency scanning (Dependabot + `pip-audit`/`pnpm audit`) in CI. |
| NFR-7 Observability | Structured JSON logs with request id; `/healthz` and `/readyz`; error tracking (Sentry-compatible DSN optional); mobile crash reporting. |
| NFR-8 Compatibility | Web: last 2 versions of Safari iOS, Chrome Android, Chrome/Edge/Firefox desktop. Mobile: iOS 16+, Android 10+ (API 29+). |
| NFR-9 Theming | Light default; follows the device dark setting using the v1.3 app-dark tokens; countdown and labels verified legible in both. |

---

## 7 · Traceability (design → requirement)

| Design § | Requirements |
|---|---|
| §1 differentiator / packet | FR-2.3, FR-3.2–3.6 |
| §3 principles 4–6 | FR-3.4, NFR-4, FR-2.4 |
| §4 core loop | FR-2 → FR-7 |
| §5 IA | FR-9 |
| §6.1–6.7 screens | FR-1, FR-2, FR-3, FR-4, FR-6, FR-7, FR-8 |
| §7 visual system | NFR-2, NFR-4, NFR-9, `packages/tokens` |
| §8 interaction | FR-4.1, FR-6.2, FR-7.3 |
| §10 states model | FR-1.1, FR-2.7, FR-3.8, FR-7.2–7.3, TEST_PLAN §6 matrix |
| §11 resilience | FR-2.5–2.6, FR-5, FR-7.2–7.3, NFR-5 |
| §12 explainability | FR-3.5 |
| §13 data mapping | §5 contract, FR-1.4 |
| §14 seams | FR-2.1 voice group, FR-9.1 stub, adapters in §4.3 |
| §15 open questions | D2, D3, D4, D10 |
