# InsmartFix v1 — Launch Plan

**Version:** 1.0-draft · **Date:** 2026-11-02 · **Runs after:** G2 Test Review approval (fully automated from there).

## 1 · Prerequisites (one-time, need the owner's accounts — spec D8)

| Item | Needed for | Stored as |
|---|---|---|
| Container host account (e.g. Fly.io / Render) + API token | staging + production API and web | GitHub env secret `DEPLOY_TOKEN` |
| Managed Postgres (prod) + S3-compatible bucket | production data and photos | `DATABASE_URL`, `S3_*` |
| Expo account + `EXPO_TOKEN` | EAS Build / Submit | GitHub secret |
| Apple Developer Program + App Store Connect API key | TestFlight, App Store | EAS credentials |
| Google Play Console + service-account JSON | Play internal / production tracks | EAS credentials |
| Domain + DNS (e.g. `fix.insmartai.com`, `api.fix.insmartai.com`) | web + API | DNS provider |
| Support URL and privacy policy URL | store listings, Account screen | config |

The release-manager agent verifies these exist at S5 and reports any missing ones as *blocked* early, so G2 isn't held up.

## 2 · Release rings (automated after G2)

| Ring | Web + API | Mobile | Promotion gate (automated) |
|---|---|---|---|
| R0 Staging | auto-deploy RC tag `v1.0.0-rc.N` | EAS *preview* build, internal distribution | smoke suite green |
| R1 Internal beta | production infra, feature flag `insmartfix_enabled` for internal tenant only | TestFlight internal + Play internal track | 48 h: crash-free ≥ 99.5%, API 5xx < 0.5%, 0 P0/P1 |
| R2 Pilot | flag on for the pilot tenant (NYC pilot contractors) | TestFlight external + Play closed track | 7 days: same SLOs + ≥ 1 completed job per pilot contractor without data loss |
| R3 GA | flag on for all tenants | App Store + Play production, staged rollout 10% → 50% → 100% over 3 days | SLOs held at each step |

Store review time (Apple 1–3 days) runs in parallel with R1/R2; the submission is made at the start of R1.

## 3 · Release mechanics
1. After G2, the release-manager agent tags `v1.0.0`, generates the changelog from Conventional Commits, and drafts store listing text from the design voice (D§9).
2. CI builds immutable images (GHCR) and mobile binaries (EAS) from the tag. Database migrations run as a separate pre-deploy job (expand/contract only; no destructive migration in a release that can be rolled back).
3. Deploy, then run the smoke suite (login → inbox → open WO → accept → arrive → complete, against seeded smoke accounts) at every ring.
4. Mobile: an OTA (EAS Update) channel per ring for JS-only fixes; native changes go through a new store build.

## 4 · Rollback
- **Web/API:** redeploy the previous image tag (one command, rehearsed on staging before G2). Migrations are backward-compatible, so no DB rollback is needed.
- **Feature:** turn `insmartfix_enabled` off per tenant.
- **Mobile:** roll back the EAS Update channel; halt the staged rollout in the Play console / pause phased release in App Store Connect.
- **Trigger:** automatic rollback if the post-deploy smoke fails or 5xx > 2% for 5 min.

## 5 · Monitoring & SLOs (S7)
- API availability 99.5%, p95 latency < 300 ms, 5xx < 0.5%.
- Mobile crash-free sessions ≥ 99.5%.
- **Product health:** completion-submit success rate (target ≥ 99.9% eventual success including queued), offer accept 409 rate (race frequency), calibration label distribution (MATCH/PARTIAL/MISS) as the first read on Decision Engine accuracy.
- Weekly report posted to the repo as an issue; findings feed the next slice's spec (which reopens G1 for that slice).
