# InsmartFix — Product Design

**Version:** 1.0
**Date:** 2026-11-02
**Status:** Living product-design doc for the InsmartFix contractor app (Phase-1 slice 2, sub-slice B). Pairs with the implementation plan `docs/plans/2026-09-09-insmartfix-contractor-app-slice.md` (the *how/tasks*) — this doc is the *what/why/how-it-feels*. Derives all color from `docs/design/COLOR_LANGUAGE.md` (v1.2) and all memory behavior from `docs/MEMORY_DESIGN.md`. Where this doc and the plan diverge, reconcile here first.
**Audience:** whoever builds InsmartFix (an implementation agent or a human), plus Claude-in-Chrome if it mirrors the field app on the marketing site. Self-contained — readable without the rest of the repo in context.

---

## 0 · What InsmartFix is, in one paragraph

**InsmartFix is the field app for the contractor who actually fixes the equipment.** Insmart Core (the facility-owner dashboard) decides *what* work a building needs and *why*; InsmartFix is where that decision reaches the person with the wrench. A contractor opens it on a phone, sees a dispatch **offer** with a live countdown, reads a **pre-diagnostic packet** (the asset's health, likely root cause, recent history, and predicted parts — assembled by the Decision Engine *before they arrive*), accepts or declines, drives out, does the job, and records what they actually found. That last step — the real failure and outcome — flows back into the asset's memory and **calibrates** the engine that made the prediction. InsmartFix is both the hands of the system and the feedback loop that makes it smarter.

**The core job:** *get a qualified contractor to the right asset, already knowing what's likely wrong, and capture what actually happened — in under a minute of screen time, often on bad signal.*

---

## 1 · The differentiator (what makes this not just another work-order app)

Every field-service app has a job list. One thing makes InsmartFix different, and the whole design must protect it:

> **The contractor arrives already briefed.** Before they accept, they can see the Decision Engine's read on the asset — health score, failure risk, probable root cause, recommended action, and the parts likely needed — with the evidence behind it. No other dispatch tool hands the tech a *diagnosis* with the job.

This is the **pre-diagnostic packet**, and it is the hero of the product. Design consequence: the packet is never buried, never an afterthought screen; it is the reason a contractor accepts an InsmartFix job over a cold call. The offer card teases it ("Likely: compressor contactor — 82% match"); the detail screen delivers it in full.

---

## 2 · Who it's for

**Primary persona — "Marco," the field contractor.**
- On a phone, one-handed, often standing, frequently in a mechanical room with poor signal.
- Paid per job; time is money. Will not tolerate a slow, chatty, or multi-tap flow.
- Skilled but skeptical — an app telling him "it's the contactor" earns trust only if it shows *why*, and only if it's right often enough. The pre-diagnostic must read as *a helpful colleague's note*, not *a black-box verdict*.
- Success for Marco: fewer wasted trips, the right parts in the van the first time, fast accept/decline, and getting paid for completed work.

**Secondary — "Dana," the contractor-company dispatcher.** In Phase 1, Dana mostly lives in Insmart Core (the owner/FM dashboard) with a tenant-wide override. InsmartFix v1 is built for Marco; Dana's richer company-level views are a later slice. *Design now so Dana's needs don't require a rebuild later — see §14 seams.*

**Not a persona here:** the facility owner. That's the Core dashboard. InsmartFix deliberately shows the contractor *less* than the owner sees (e.g. not the full ranked list of competing contractors) — see §12.

---

## 3 · Design principles

1. **Field-first, not mobile-responsive.** This is designed *for* the phone-in-a-boiler-room case, then it happens to work on a tablet. Big tap targets, thumb-reachable primary actions, legible in bright light, resilient to a dropped connection. The dashboard is calm desk software; InsmartFix is a tool you use with one glove off.
2. **Speed over completeness on the inbox; care over speed on completion.** Accept/decline is one tap. The completion form — the calibration feed — is where we ask for rigor, and where we must never lose the contractor's input to a bad connection.
3. **The packet earns the accept.** Lead every offer with the engine's read. Explainable, evidence-linked, honest about confidence.
4. **Honest states, always.** Empty, loading, error, offline, expired, no-packet — each is a named, designed state, not a blank or a crash. The system says what it knows and what it doesn't (an asset with no history says so; it never fabricates a diagnosis).
5. **Status color is reserved; dispatch color is not.** The green→amber→orange→red scale means *health/risk only* (`COLOR_LANGUAGE.md` §3). Dispatch state, SLA urgency, and lifecycle use **neutral + brand** tones and a **non-color urgency signal** (weight, label, icon) so urgency reads without stealing the risk axis.
6. **One teal per view.** Teal `#12879A` is the single brand accent and marks the one primary action on each screen — Accept, Submit, Continue. It is punctuation, never fill.
7. **Every completed job teaches the system.** The design makes the feedback loop legible: the contractor sees that what they report updates the asset's memory, which is why their accuracy matters.

---

## 4 · The core loop (end-to-end journey)

```
   OFFER  →  DECIDE  →  TRAVEL  →  DIAGNOSE  →  FIX  →  LEARN
  (inbox)   (accept/   (en route/ (packet +   (complete  (outcome →
            decline)    arrived)   on-site)    form)      calibration)
     └──────────────── the asset's memory compounds ───────────────┘
```

| Step | Screen | What the contractor does | What the system does |
|---|---|---|---|
| **Offer** | Inbox | Scans offers, sees asset/symptom/match + live SLA countdown | Surfaces PENDING assignments scoped to *this* contractor; counts down the SLA |
| **Decide** | Inbox / Detail | Taps Accept (or Decline + reason) | Binds the WO to the contractor; delivers the full packet synchronously on accept |
| **Travel** | Detail | Marks *En route*, then *Arrived* | Appends lifecycle events to memory (auditable, cross-device) |
| **Diagnose** | Detail | Reads the pre-diagnostic packet on site; confirms or revises | Shows the engine's read + evidence; no fabrication if history is thin |
| **Fix** | Completion | Records failure code, parts, labor, notes (+ photo, see §6.6) | Validates; drafts survive bad signal |
| **Learn** | — | (nothing — it's automatic) | `complete_workorder` writes the outcome through the seam → calibration labels the decision MATCH/PARTIAL/MISS |

The loop is the product. Each screen below serves one step.

---

## 5 · Information architecture

A deliberately **shallow** app — three primary surfaces, no deep nav. A field worker should never be more than one tap from the thing they need.

```
InsmartFix (mobile shell: top bar + minimal bottom nav)
├── Login                         (unauthenticated)
├── Inbox            /inbox       ← home: Offers + Active jobs
│   └── Work Order   /jobs/[id]   ← detail: packet + lifecycle + completion
└── Account          /account     ← who am I, sign out (thin in v1)
        ·  Voice intake (disabled stub — seam for Voicequest / sub-slice C)
```

- **Bottom nav** is two items in v1 (Inbox, Account) — present so adding "Voice" (C) and "History" later is a change of items, not of structure.
- The **Work Order detail** is where travel, diagnosis, and completion all happen — one scrolling screen with a **sticky action bar** so the primary action (Accept / Mark arrived / Submit) is always thumb-reachable, never below the fold.

---

## 6 · Screen-by-screen

Each screen specifies: purpose · layout · anatomy · **every state** (empty / loading / error / offline where they apply) · the data behind it.

### 6.1 Login (`/login`)

- **Purpose:** authenticate the contractor; bind the session to their `contractor_id` (see §13).
- **Layout:** centered, generous. Slab-serif "InsmartFix" wordmark (ink, not teal), one-line tagline ("Jobs that arrive diagnosed."), email + password, one teal **Sign in** button. Nothing else.
- **States:**
  - *Default* — empty form, Sign-in enabled when both fields non-empty.
  - *Submitting* — button shows a spinner, form disabled.
  - *Error* — wrong credentials → inline message under the form ("Email or password is incorrect"), fields preserved. Network error → "Can't reach InsmartFix. Check your connection and try again," with a Retry.
- **Data:** `POST /api/auth/login` → httpOnly cookie. The JWT never touches client JS (see §13).

### 6.2 Offer Inbox (`/inbox`) — the home screen

The most-used screen. Two stacked groups:

**A. Offers** (dispatch state PENDING) — decisions waiting on the contractor.
**B. Active jobs** (ACCEPTED / IN_PROGRESS) — work in flight.

**OfferCard anatomy (the card that must sell the accept):**
```
┌─────────────────────────────────────────────┐
│ RTU-04 · Midtown Tower, Roof        ⟡ 4m left│  ← asset · site · SLA countdown
│ Discharge air too warm                        │  ← symptom (plain language)
│ Likely: compressor contactor  ·  82% match    │  ← packet teaser + match score
│ ▸ High risk · Health 44                       │  ← risk/health (the ONLY reserved-color element)
│                      [ Decline ]   [ Accept ] │  ← actions (Accept = teal)
└─────────────────────────────────────────────┘
```
- The **SLA countdown** (`⟡ 4m left`) is the urgency signal. It uses the **non-color urgency system** (§7.5): as time shrinks the label gets heavier and more explicit (`4m left` → `90s left` → **`Expiring`** → **`Expired`**), optionally with a small clock glyph — never turning red (red is risk, not time).
- Risk/health is the *one* place the reserved scale appears on this card, always with its text label ("High", "Health 44"), never color alone.
- **Active-job cards** drop the Accept/Decline, show current lifecycle stage ("En route", "On site") and a tap-through to continue.

**Ordering:** Offers sorted by **soonest SLA deadline first** (the thing most about to expire is on top). Active jobs sorted by **most recently advanced**. (Resolves the review gap: a contractor with several jobs always sees "what needs me next" at the top.)

**States:**
- *Loading* — skeleton cards (not a spinner), so the shape is familiar before data lands.
- *Empty — no offers* — a calm empty state: "No open offers right now. We'll show new dispatch here the moment it arrives." (This empty state *is* the notification surface — see refresh below.)
- *Empty — no active jobs* — collapses the section; doesn't show a lonely header.
- *Error* — "Couldn't load your jobs," with Retry; last-known list stays visible if we have one (don't blank the screen on a refresh failure).
- *Offline* — a thin persistent banner "You're offline — showing your last update," cards dimmed to read-only.

**Refresh & the stale-offer race (critical).** The inbox is **pull-based** (no push in Phase 1), *and* offers expire/escalate **server-side** — an offer can be reassigned to another contractor while Marco's countdown still shows time. So:
- The inbox **re-fetches** on a short interval and on tab-focus/visibility change (not a one-time load), so the list self-heals.
- **Accept is server-authoritative.** If Marco taps Accept on an offer that already expired or was reassigned, the server rejects it; the UI shows a non-alarming toast ("This offer just expired — it's been reassigned") and the card animates out as the list refreshes. We never let the client's stale countdown override the server's truth.

**Data:** server component resolves `GET /me` → `contractor_id` → `GET /contractor/{id}/schedule`. The client never supplies the id (see §13).

### 6.3 Work Order detail + pre-diagnostic packet (`/jobs/[id]`)

The deepest screen; everything about one job. Scrolls top-to-bottom in the order a contractor needs it, with a **sticky action bar** pinned to the bottom.

**6.3.a — Header.** Asset (RTU-04), site + location, symptom, current dispatch/lifecycle state as a **neutral pill**, and the SLA countdown (same non-color system) if still time-bound.

**6.3.b — Decision summary (the "why this job exists").** A compact card:
- **Health score** (band solid color — reserved scale, allowed here) and **failure risk** band, each labeled.
- **Probable root cause** in plain language ("Compressor contactor failing — coil resistance drift + short-cycling pattern").
- **Recommended action** ("Replace contactor; verify phase balance before restart").
- A one-line **confidence/why** ("Based on 3 recent events + 2 active insights") that expands to the evidence.
- *Restraint:* the contractor sees the engine's read on the asset and **their own** match, but **not** the full ranked list of competing contractors (that's the owner's view). See §12.

**6.3.c — Pre-diagnostic packet.** The briefing, in sections:
- **Asset identity** — make/model/age, location, duty.
- **Recent events** — the last few sensor/inspection/log events feeding the read.
- **Recent maintenance** — what was done before, by whom.
- **Active insights** — what the system currently believes about this asset ("tends to short-cycle in summer peak").
- **Predicted parts** — likely parts to bring ("1× contactor (40A), possible 1× capacitor").

**No-packet fallback (named state).** `pre_diagnostic_available` can be **false** — a new asset with no history. In that case the packet section does **not** show empty boxes or imply breakage; it shows an honest panel:
> *"No history on this asset yet. Proceed with the reported symptom and your own inspection — this job will start building the asset's record."*
The decision summary degrades gracefully to symptom-only. (We never fabricate a diagnosis to fill the space — principle 4.)

**States:** loading (skeleton of the summary + packet), error ("Couldn't load this job" + Retry), offline (shows last-fetched packet, banner).

### 6.4 Accept / Decline

- **Accept** — the sticky-bar primary (teal). On tap: optimistic "Accepting…", then the server binds the WO and returns the **full packet synchronously** (so the briefing is ready the instant it confirms). On the stale/expired race → the toast + refresh from §6.2.
- **Decline** — secondary. Opens a light sheet with an **optional reason** (chips: *Too far · No capacity · Wrong skill · Other*) and a **Skip** that declines with no reason. Reason is optional by ruling — one tap to decline must remain possible. The reason is a future match-quality signal, not a gate.

### 6.5 Lifecycle (en route · arrived · complete)

A horizontal **LifecycleTracker** on the detail screen: `En route → Arrived → Complete`. The current stage is a **neutral/brand** chip (never reserved color).
- Advancing a stage is a deliberate tap on the sticky action bar ("Mark en route", then "Mark arrived", then "Start completion").
- **Each advance is an append-only memory event** (auditable, survives a refresh or a second device — see §13). Because it's permanent, a mis-tap matters: each advance shows a **lightweight confirm** ("Mark arrived? This is logged.") and, immediately after, a brief **Undo** affordance that appends a corrective event (we don't mutate history, we correct it forward). (Resolves the review gap: one fat-finger tap shouldn't silently write a wrong timestamp into the record.)
- **Terminology note:** the UI's "Arrived" is an InsmartFix fulfillment stage; the underlying `Maintenance.status` stays `IN_PROGRESS`. The PRD's canonical sequence is pending/accepted/en-route/in-progress/complete/closed — "Arrived" is our on-site marker within IN_PROGRESS, not a new backend status. (Flag for the contract so a future reader doesn't see a divergent state model.)

### 6.6 Completion form — the calibration feed

The most important data-capture in the product. This is where the real-world outcome enters the system and calibrates the Decision Engine. Design asks for **rigor** here and protects the contractor's input fiercely.

**Fields (match `CompletionReport`):**
- **Failure code** (required) — what was actually wrong. A searchable picker, pre-filtered to the asset's subtype; the engine's *predicted* cause is offered at the top as a one-tap confirm ("Confirm: compressor contactor") but the contractor can override — **their truth wins, never the prediction** (`failure_code` is append-only and set once; we never write the predicted code as if it were found).
- **Actual fault found** (toggle) — did reality match the brief? This single toggle is gold for calibration.
- **Parts used** (repeatable rows).
- **Labor hours** (required, numeric).
- **Root cause / notes** (optional free text).
- **Photo** (see disposition below).
- `technician_id` is **self-reported** (the person who did the work may differ from the login) — captured as free text/selection, *not* an authenticated identity in Phase 1. Don't build accountability assumptions on it yet.

**Photo — explicit disposition.** The PRD lists a completion photo (§2.9.3). `CompletionReport` was frozen without a photo field. **Decision needed before the contract freezes** (open item §15): either (a) add a photo field to `CompletionReport` + an upload path, or (b) explicitly defer "completion photo" to a later slice with a note. This doc flags it rather than letting it vanish silently.

**Field resilience (non-negotiable for this screen).** This is the worst-connectivity moment in the whole product — contractor under the equipment, job done, filling a multi-field form. So:
- **Draft autosaves locally** on every change and **survives navigation, reload, and app backgrounding.** Nothing is lost if the screen closes.
- **Submit is resilient:** on a failed submit the form stays filled with a clear "Couldn't submit — your entry is saved. Retry," and a one-tap Retry. We **never** drop the contractor to a blank screen or a silent redirect that eats their input.
- Optional: a queued/offline submit that flushes when signal returns (nice-to-have; at minimum the draft must never be lost).
- On success: a brief confirmation that closes the loop legibly — *"Logged. This updates RTU-04's record and the system's prediction."* — then **navigate back to the Inbox** (never a dead-end "done" screen).

### 6.7 Account (`/account`)

Thin in v1: who's signed in (name, company, `contractor_id` badge), a link to support, **Sign out**. The home for later settings (notifications, availability) — present so growth is additive.

---

## 7 · Visual design system (field-tuned)

Inherits `COLOR_LANGUAGE.md` v1.2 wholesale; this section says how it's *applied* on a phone.

### 7.1 Color roles in InsmartFix
- **Brand teal `--brand` (#12879A):** the one primary action per screen (Accept, Submit, Sign in), active nav, the wordmark accent. One teal per view.
- **Neutral slate:** canvas (`--surface-0`), cards (`--surface-2`), text, borders, and **all dispatch/lifecycle/SLA elements**.
- **Reserved status scale:** *only* health score + failure risk. Appears on the OfferCard risk line and the detail decision summary — nowhere else.
- **Dispatch/status pills** (Undispatched, Pending, Accepted, En route, Arrived, Escalated, No contractors, Completed): neutral/brand tones, each with a text label. **Never** a `--status-*` hex.

### 7.2 Typography
- **Display/wordmark:** the industrial slab-serif from the Insmart family (ink `--text-primary`), used for "InsmartFix" and section titles — a restrained, sturdy, *tool-like* voice (not the loud marketing scale).
- **UI text:** the neutral system/sans stack, sized up for field legibility — **minimum 16px body**, larger for primary data (asset id, health number, countdown).
- **Monospace micro-labels** (sparingly): SLA countdown, part codes, match %.

### 7.3 Spacing & layout
- Generous vertical rhythm; cards with comfortable padding (thumbs, gloves).
- **Tap targets ≥ 44×44pt.** Primary actions in a **sticky bottom bar**, thumb-zone.
- Single-column always; the detail screen scrolls, with the action bar pinned.

### 7.4 Components (the kit)
`TopBar`, `BottomNav`, `OfferCard`, `SlaCountdown`, `AcceptDeclineActions`, `DecisionSummaryCard`, `PreDiagnosticPacket` (+ its no-data panel), `LifecycleTracker`, `CompletionForm`, and the shared `Button`, `StatusChip`, `EmptyState`, `ErrorState`, `Skeleton`. Every screen wires the empty/error/skeleton trio — none is optional.

### 7.5 The SLA urgency system (non-color)
Because time-urgency must not borrow the risk scale, urgency is encoded **without color**:
| Remaining | Label | Weight | Glyph |
|---|---|---|---|
| > 5 min | `12m left` | regular | ⟡ |
| 1–5 min | `4m left` | medium | ⟡ |
| < 60 s | `45s left` | bold | ⟡ (subtle pulse) |
| past deadline (advisory) | **`Expiring`** | bold | ⟡ |
| server-expired | `Expired` | bold, muted | — |
The countdown ticks client-side for responsiveness but **server `sla_deadline` is the source of truth**; expiry in the UI is advisory until the server confirms (see §6.2 race). Mirrors the dashboard's proven `formatSlaDeadline` (bold text, no color) so the two products read consistently.

### 7.6 Dark mode
Inherit the v1.2 dark tokens. Field use is often outdoors/bright, so **light is the default**, but respect the device setting; verify the countdown and status labels stay legible on the dark surfaces.

---

## 8 · Interaction & motion
- **Instant feedback, optimistic where safe.** Accept/advance show immediate state, reconciled against the server; completion submit is explicit (not optimistic — we must confirm the calibration write landed).
- **Motion is functional, not decorative:** cards animate out when an offer resolves; the lifecycle tracker advances with a short transition; skeletons fade to content. Nothing that slows a fast accept.
- **No modal traps.** Decline uses a dismissible sheet; confirms are lightweight inline, never a blocking dialog that a gloved thumb fights.

---

## 9 · Content & voice
- **Plain, imperative, short.** "Mark arrived." "Bring: 1× contactor." Not "Please indicate your arrival status."
- **English-only**, consistent with the Insmart storefront/customer convention.
- **Honest, never hype.** The packet says "Likely" and "82% match," not "The problem is." Empty/no-history states say what's missing.
- **Numbers over adjectives** where it helps a tech ("Health 44", "90s left", "82% match").

---

## 10 · The states model (every screen)
A screen is not done until all of these are designed:
| Screen | Loading | Empty | Error | Offline | Special |
|---|---|---|---|---|---|
| Login | submitting | — | bad creds / network | — | — |
| Inbox | skeleton cards | no offers / no active | load fail (keep last) | banner, read-only | **stale-offer race**, auto-refresh |
| WO detail | skeleton | — | load fail + retry | last packet + banner | **no-packet fallback** |
| Completion | — | — | submit fail (**keep draft**) | **draft persists**, queued submit | required-field validation |
| Account | — | — | — | cached identity | — |

---

## 11 · Field resilience & offline (summary of the hard requirement)
InsmartFix must assume bad signal. The two things that must **never** break:
1. **A completion in progress is never lost** — local draft, survives reload/background; submit failures keep the data and offer Retry.
2. **The inbox self-heals** — auto-refresh + server-authoritative accept, so a stale countdown never silently hands a contractor a job that's gone.
Everything else degrades gracefully with a banner and last-known data.

---

## 12 · Explainability & trust (what the contractor sees — and doesn't)
- **Sees:** the engine's read on the asset (health/risk/root cause/recommended action), the evidence behind it, their own match score + a plain reason, and the predicted parts. This is what earns the accept and builds trust in the system over time.
- **Doesn't see:** the full ranked list of *competing contractors* for the offer (that's the owner/dispatcher view in Core). A contractor sees their own standing, not the leaderboard.
- **Trust loop:** completion closes visibly ("this updates the record and the prediction"), so the contractor understands their accuracy feeds the system — the reason the failure-code step asks for their real finding, not a rubber-stamp of the prediction.

---

## 13 · Data & backend mapping
InsmartFix is a thin, honest client over the existing FastAPI backend — it calls HTTP only, never touches the vault/DB directly.

| Screen / action | Backend | Notes |
|---|---|---|
| Login | `POST /auth/login` (via `/api/auth/login` proxy) | sets httpOnly cookie; JWT off the client |
| Identity | `GET /me` → `contractor_id` | resolved **server-side**; client never sends an id |
| Inbox | `GET /contractor/{id}/schedule` | id injected by the proxy from the session |
| Accept | `POST /contractor/{id}/accept/{wo}` | returns packet synchronously |
| Decline | `POST /contractor/{id}/decline/{wo}` (+ optional `reason`) | reason persisted on the dispatch sidecar |
| Detail / packet | `GET /workorders/{wo}` | `pre_diagnostic_available` drives the fallback |
| Lifecycle | `POST /workorders/{wo}/transition {stage}` | appends a memory event via the seam |
| Complete | `POST /workorders/{wo}/complete` | the calibration feed, through `complete_workorder` |

**The identity binding (closes "R10").** A contractor principal is bound to exactly one `contractor_id` in the token; the server gates accept/decline/complete so a contractor can act **only on their own** work orders (owner/FM keep a tenant-wide override). The client **never** supplies a `contractor_id` — the server proxy injects it from the session, so the binding can't be spoofed by editing a URL.

**Mock vs live.** `DATA_SOURCE=mock` runs the entire loop offline against an in-memory store (for demos and e2e); `live` talks to the backend. Same screens, same code paths.

---

## 14 · Seams left for later (so growth is additive, not a rebuild)
- **Voicequest (sub-slice C):** a disabled "Voice intake" nav stub exists now; the inbox already renders an (empty) voice-bookings group and shows `wo_source`, so a voice-originated job appears with no structural change. **Note:** the PRD's "InsmartFix usable with zero Insmart Core orders" standalone criterion only *closes* with Voicequest — under Smart Dispatch alone every job still originates from Core. This app delivers the contractor UI that criterion needs; it does not by itself satisfy it.
- **Dispatcher (Dana) views:** company-level multi-contractor screens are a later slice; v1's per-contractor model and tenant-wide override leave room for them.
- **Ratings/reviews:** `avg_rating` is static now; a review pipeline is future.
- **Real credential store:** Phase-1 interim auth is extended, not replaced; hashed credentials + self-service onboarding are a tracked follow-up.

---

## 15 · Open design questions (to resolve before/at build)
1. **Completion photo** (§6.6) — add a `CompletionReport` photo field + upload, or explicitly defer with a target slice? (PRD asks for it; contract is otherwise frozen.)
2. **Offline submit depth** — is "draft never lost + retry" enough for v1, or do we build a queued/auto-flush offline submit now?
3. **Push later** — v1 is pull + auto-refresh by design; confirm push notification is out until a later slice (it's the thing that would most change the inbox's role).
4. *(Carried from the plan review, not a design question but open):* the **code-reviewer pass** on the implementation plan never completed (it died on an API error) — the memory-integrity/auth-bypass review of the identity gate and the en-route/arrived-as-events design still needs to run before build.

---

## 16 · Changelog
- **v1.0 (2026-11-02):** Initial InsmartFix product design. Derived from the sub-slice-B plan (`2026-09-09`) and its whole-team review; folds in the QA/UX review gaps (stale-offer race, no-packet fallback, completion-form resilience, non-color SLA urgency, lifecycle undo, multi-job ordering, post-completion nav) and the PO review notes (photo disposition, standalone-AC caveat, `technician_id` as self-reported, en-route/arrived terminology mapping). Color per `COLOR_LANGUAGE.md` v1.2; memory behavior per `MEMORY_DESIGN.md`.
