# Insmart AI — Color Language

**Version:** 1.3
**Date:** 2026-11-02
**Status:** Living design-system doc. The dashboard, marketing site, and all future Insmart UI (incl. InsmartFix) derive their color from this file; update here first, then propagate.
**Direction:** "Trusted Instrument" — a cool, precise system built on **one cyan-teal brand accent** from the logo, rendered in **two registers**: a **light content register** (the app, and the marketing site's body) and a **navy expressive register** (the marketing hero and CTA bands). Serious, mechanical, instrument-like — never artsy.

**v1.3 change — re-synced to the shipped site (`insmartai.com`).** Three real changes were pulled from the live site and are now canonical:
1. **Brand teal refined:** primary moved `#12879A` → **`#0396A6`**; the ramp is now a 5-stop teal (tint · lite · **bright** · primary · deep), with a dedicated **bright `#2DD4DE`** for teal on the navy ground.
2. **Dual register (reverses v1.2's "light only").** The marketing site ships a **navy expressive register** (`--navy*`) for the hero and CTA/accent bands — see §5. The **app stays light**; navy is a marketing register, not the app's ground.
3. **`--accent-band` is now navy** (`#0C1420`, was deep-teal), plus a **`--crit-bright #FF5C5C`** for the critical signal on navy. Status (risk) scale is otherwise unchanged. Type faces are now fixed (§6).

> **Downstream note:** the dashboard and the InsmartFix design doc were written against the old `#12879A` primary. Re-point `--brand` to `#0396A6` when propagating. See §8.

---

## The one rule that shapes everything

Insmart's core output is **Health Score** and **Failure Risk** — `LOW / MEDIUM / HIGH / CRITICAL`. That means the traffic-light axis (green → amber → orange → red) is **functional, reserved, load-bearing color** across the entire product.

**The brand color must live outside that axis.** A cyan-teal brand accent reads as *trust, precision, intelligence* and never gets misread as a status. This is why teal, not the coral/green/amber a generic SaaS template would reach for.

There are exactly **four color languages**, each with a distinct job. Never let one do another's job.

| # | Language | Job | Family |
|---|---|---|---|
| 1 | **Brand** | Identity, primary actions, active state | Cyan-teal (from the logo) |
| 2 | **Neutral** | Canvas, surfaces, text, structure | Cool slate-grey — *light register* + *navy register* |
| 3 | **Status** | Health / risk / outcome — the product's core signal | Green → amber → orange → red (reserved) |
| 4 | **Data-viz** | Chart series, categorical encoding | Distinct hues that avoid the status axis |

---

## 1 · Brand — cyan-teal

Derived from the logo mark. The shipped ramp is **five named stops**; `--teal` (primary) is the default, `--teal-bright` is the on-navy accent.

| Token | Hex | Role |
|---|---|---|
| `--teal-tint` | `#E6F8FA` | Lightest tint — stat-card fills, hover backgrounds (light register) |
| `--teal-lite` | `#5BCCD9` | Logo light facet, light accents, focus rings, gradient start |
| **`--teal-bright`** | **`#2DD4DE`** | **Teal on the navy ground** — hero accent word, CTA on dark, live-dot |
| **`--teal`** | **`#0396A6`** | **Primary brand** — buttons, active nav, links, key accents (light register) |
| `--teal-deep` | `#026873` | Hover / pressed; high-emphasis teal text on light |

- **Logo gradient:** `linear-gradient(115deg, #5BCCD9, #0396A6)` (≈115°). Mark and rare hero moments only — never a fill behind text or on buttons (flat teal for those).
- **Primary is `#0396A6`** on the light register. **On the navy register, step up to `#2DD4DE`** (bright) for the accent/CTA so teal stays legible on dark — this is why the hero's "before" word and the "Book a demo" button read `#2DD4DE`, not `#0396A6`.
- Wordmark is ink (`--ink`), not teal; only the logo *mark* carries the gradient.
- **App ramp alias:** where the dashboard uses `--brand-50…900`, anchor `--brand-600 = #0396A6`, `--brand-300 = #5BCCD9`, `--brand-50 = #E6F8FA`, `--brand-800 = #026873`; `--brand = --brand-600`.

## 2 · Neutral — cool slate-grey (two registers)

**2a · Light register** — the app's ground and the marketing body.

| Role | Token (site) | App alias | Value |
|---|---|---|---|
| Page background | `--bg` | `--surface-0` | `#F4F6F8` |
| Subtle fill (metric card) | `--surface-1` | `--surface-1` | `#EDF1F4` |
| Raised card / panel | `--card` | `--surface-2` | `#FFFFFF` |
| Hairline border | `--line` | `--border` | `#E2E8EC` |
| Strong border (hover) | `--line-strong` | `--border-strong` | `#CBD5DC` |
| Text primary (ink) | `--ink` | `--text-primary` | `#0B1A24` |
| Text secondary | `--ink-muted` | `--text-secondary` | `#54657A` |
| Text muted (hints, axes) | `--ink-faint` | `--text-muted` | `#8495A6` |

**2b · Navy register** — the marketing hero and CTA/accent bands (NOT the app). Teal steps to `--teal-bright` on these grounds; status critical steps to `--crit-bright`.

| Role | Token | Value |
|---|---|---|
| Navy ground (hero, accent band) | `--navy` / `--accent-band` | `#0C1420` |
| Navy raised (panel on navy) | `--navy-2` | `#111E2E` |
| Navy raised-2 (card on navy) | `--navy-3` | `#16263A` |
| Text on navy | `--navy-ink` | `#D7E2EE` |
| Dim text on navy | `--navy-ink-dim` | `#9AACC0` |
| Hairline on navy | `--navy-line` | `#24344A` |

## 3 · Status — the reserved risk scale

The product's most important color. Maps 1:1 to the Decision Engine bands (PRD §2.4). **Never used for brand, decoration, or chart series.** Always paired with a text label and/or icon — never color alone (accessibility + colorblind safety). **Unchanged in v1.3.**

| Band | Health Score | Failure Risk | Solid | Light fill | Text on fill |
|---|---|---|---|---|---|
| **Healthy** | 80–100 | LOW | `#15A34A` | `#E9F7EE` | `#14532A` |
| **Medium** | 60–79 | MEDIUM | `#E0A106` | `#FBF1DB` | `#6E4A05` |
| **High** | 40–59 | HIGH | `#E5661B` | `#FCEBDF` | `#77320F` |
| **Critical** | <40 | CRITICAL | `#DC2626` | `#FBE9E9` | `#7E1D1D` |

**On the navy register** — the critical signal brightens so it stays legible on dark (the hero's `31 · CRITICAL`):

| Token | Value | Use |
|---|---|---|
| `--crit-bright` | `#FF5C5C` | Critical number / pill on navy ground |

**Light-mode dark (app dark theme)** — brighten solids, darken fills (unchanged from v1.2):

| Band | Solid (dark) | Fill (dark) | Text on fill (dark) |
|---|---|---|---|
| Healthy | `#22C55E` | `#123122` | `#86EFAC` |
| Medium | `#F5B942` | `#3A2C0C` | `#FCD97D` |
| High | `#FB7B3C` | `#3A1F10` | `#FDBA8C` |
| Critical | `#F05252` | `#3A1515` | `#FCA5A5` |

Usage: the big Health Score number takes the band solid (or `--crit-bright` on navy); risk pills use the light fill + text-on-fill; a full-bleed CRITICAL banner may use the solid with white text.

## 4 · Data-viz — categorical chart series

For trends and multi-asset comparison. Brand teal leads; the rest are chosen to be **distinct from the status axis** so a chart series is never mistaken for a health signal. Assign in fixed order, never cycle a rainbow.

| Slot | Hue | Light | Dark / on-navy |
|---|---|---|---|
| 1 | Teal (brand) | `#0396A6` | `#2DD4DE` |
| 2 | Blue | `#2A78D6` | `#3987E5` |
| 3 | Violet | `#6D5AE0` | `#9085E9` |
| 4 | Magenta | `#D4537E` | `#E87BA4` |
| 5 | Slate | `#64748B` | `#94A3B8` |
| 6 | Deep aqua | `#0E7490` | `#22A7C4` |

Rules: single series → brand teal, no legend. One series is the point → brand teal + the rest grey (emphasis). Magnitude/heatmap → one-hue sequential on the teal ramp. Never green/amber/orange/red for a categorical series — those belong to Status only.

---

## 5 · Expressive use — the two registers

The four languages define *what colors mean*; this defines *how loud to be, and on what ground*.

**The app = light register, quiet.** Light canvas (`--bg`), teal `#0396A6` as a small accent (one primary button per view, active nav, the logo), status reserved. Calm, for daily use. No navy, no industrial display scale.

**The marketing site = light body + navy expressive bands, loud.** Loudness comes from **scale, industrial type, and the navy register** used deliberately:
- **Navy hero & CTA bands** (`--navy #0C1420`, panels `--navy-2`/`--navy-3`) carry the big moments. On navy, teal steps to **`--teal-bright #2DD4DE`** (the "before" accent word, the "Book a demo" CTA, the live-dot), and the critical signal to `--crit-bright #FF5C5C`.
- **Industrial display type** — a heavy grotesque headline (`Space Grotesk` 700) at large scale (`clamp` into the 3–6rem range), tight tracking, **mixed-case** (the shipped hero is "Know what's failing *before* it fails." — not uppercase). The headline is ink on light, `--navy-ink` on navy — never teal (teal is the single accent word only).
- **Monospace micro-labels** — `IBM Plex Mono`, small, uppercase, letter-spaced, in teal or muted: `AI DECISION ENGINE · PHYSICAL ASSETS`, `NEW YORK PILOT → U.S. SCALE-UP`, `BRICK · HAYSTACK · OPC UA`. Technical texture, sparingly.
- **Status stays reserved** — a Critical reads red (`#DC2626` on light, `#FF5C5C` on navy); status never borrows teal.
- **Photography** — real facility/HVAC imagery carries editorial weight on the production site.

---

## 6 · Type

| Role | Family | Use |
|---|---|---|
| Display | **`Space Grotesk`** (700), fallback Inter | Headlines, wordmark — industrial, mechanical, mixed-case |
| UI / body | **`Inter`**, system fallback | All interface and body text |
| Mono | **`IBM Plex Mono`**, SF Mono fallback | Micro-labels, codes, metrics, SLA countdown |

Radii are small and technical: `--r-sm 3px`, `--r-md 4px`, `--r-lg 6px`.

---

## 7 · Ready-to-use CSS variables (synced to insmartai.com)

```css
:root {
  /* 1 · Brand teal (5-stop) */
  --teal-tint:#E6F8FA; --teal-lite:#5BCCD9; --teal-bright:#2DD4DE;
  --teal:#0396A6; --teal-deep:#026873;
  --brand:var(--teal);
  --brand-gradient:linear-gradient(115deg,#5BCCD9,#0396A6);  /* logo mark only */

  /* App ramp aliases (dashboard uses --brand-50…900) */
  --brand-50:#E6F8FA; --brand-300:#5BCCD9; --brand-400:#2DD4DE;
  --brand-600:#0396A6; --brand-800:#026873;

  /* 2a · Neutral — light register */
  --bg:#F4F6F8; --surface-1:#EDF1F4; --card:#FFFFFF;
  --line:#E2E8EC; --line-strong:#CBD5DC;
  --ink:#0B1A24; --ink-muted:#54657A; --ink-faint:#8495A6;
  /* app aliases */
  --surface-0:#F4F6F8; --surface-2:#FFFFFF; --border:#E2E8EC; --border-strong:#CBD5DC;
  --text-primary:#0B1A24; --text-secondary:#54657A; --text-muted:#8495A6;

  /* 2b · Neutral — navy expressive register (marketing) */
  --navy:#0C1420; --navy-2:#111E2E; --navy-3:#16263A;
  --navy-ink:#D7E2EE; --navy-ink-dim:#9AACC0; --navy-line:#24344A;
  --accent-band:#0C1420;   /* hero / CTA ground */

  /* 3 · Status (reserved risk scale) */
  --status-healthy:#15A34A; --status-healthy-bg:#E9F7EE; --status-healthy-fg:#14532A;
  --status-medium:#E0A106;  --status-medium-bg:#FBF1DB;  --status-medium-fg:#6E4A05;
  --status-high:#E5661B;    --status-high-bg:#FCEBDF;    --status-high-fg:#77320F;
  --status-critical:#DC2626;--status-critical-bg:#FBE9E9;--status-critical-fg:#7E1D1D;
  --crit-bright:#FF5C5C;    /* critical on navy ground */

  /* 4 · Data-viz */
  --series-1:#0396A6; --series-2:#2A78D6; --series-3:#6D5AE0;
  --series-4:#D4537E; --series-5:#64748B; --series-6:#0E7490;

  /* Type + radii */
  --display:"Space Grotesk","Inter",system-ui,sans-serif;
  --sans:"Inter",system-ui,sans-serif;
  --mono:"IBM Plex Mono","SF Mono",ui-monospace,monospace;
  --r-sm:3px; --r-md:4px; --r-lg:6px;
}

@media (prefers-color-scheme: dark) {
  :root {
    /* app dark theme (distinct from the marketing navy register) */
    --surface-0:#0D1417; --surface-1:#1B262B; --surface-2:#151E22;
    --border:#26333A; --border-strong:#33434B;
    --text-primary:#F1F5F7; --text-secondary:#9FB0B8; --text-muted:#6B7C84;

    --status-healthy:#22C55E; --status-healthy-bg:#123122; --status-healthy-fg:#86EFAC;
    --status-medium:#F5B942;  --status-medium-bg:#3A2C0C;  --status-medium-fg:#FCD97D;
    --status-high:#FB7B3C;    --status-high-bg:#3A1F10;    --status-high-fg:#FDBA8C;
    --status-critical:#F05252;--status-critical-bg:#3A1515;--status-critical-fg:#FCA5A5;

    --series-1:#2DD4DE; --series-2:#3987E5; --series-3:#9085E9;
    --series-4:#E87BA4; --series-5:#94A3B8; --series-6:#22A7C4;
  }
}
```

---

## 8 · Propagation (what to update now that the primary moved)

The shipped site is the ground truth; these derive from it and still carry the **old `#12879A`** primary:
- **Dashboard** (`InsmartAI/dashboard/`) — `--brand`/`--brand-600` and any hardcoded `#12879A`. Re-point to `#0396A6` (and `--brand-300` to `#5BCCD9`).
- **InsmartFix design doc** (`docs/design/INSMARTFIX_PRODUCT_DESIGN.md`) — references `#12879A` as the brand; update to `#0396A6`, and note the on-navy accent `#2DD4DE` if any InsmartFix surface uses a dark band.
- **InsmartData sibling** (`InsmartData/docs/design/COLOR_LANGUAGE.md`) — independent (enterprise-blue); not affected.

## 9 · Do / don't

- **Do** keep the **app** light and airy; teal `#0396A6` in small, deliberate doses (one primary button per view, active nav, the logo).
- **Do** use `--teal-bright #2DD4DE` for teal **on the navy register**, and `--crit-bright #FF5C5C` for critical on navy — teal/critical must stay legible on dark.
- **Do** reserve green/amber/orange/red exclusively for health/risk; pair every status color with a label or icon.
- **Don't** use the logo gradient behind text or on buttons — flat teal only.
- **Don't** bring the navy register into the app — navy is a marketing register; the app ground is `--bg`.
- **Don't** introduce a second brand accent. Distinctiveness comes from teal + disciplined neutrals (light + navy), not more hues.
- **Don't** let a chart series borrow a status color, or a status borrow the brand teal.

## 10 · Accessibility

Text-on-fill pairs in §3 and the neutral text tokens meet WCAG AA (4.5:1) for body text. `--teal #0396A6` on white is AA for large text / UI controls; for teal body text or inline links on white, step to `--teal-deep #026873`. On the navy register, `--teal-bright #2DD4DE` and `--navy-ink #D7E2EE` on `--navy #0C1420` carry the contrast. Never rely on color alone — status always carries a label or icon.
