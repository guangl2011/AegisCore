# AegisCore — instructions for Claude (orchestrator)

AegisCore is the monorepo for **InsmartFix** (contractor field app): `apps/api` (FastAPI), `apps/web` (Next.js), `apps/mobile` (Expo, iOS + Android), and the shared `packages/*`.

## Read first
1. `docs/process/DEVELOPMENT_PROCESS.md` — stages S0–S7, the two human gates, the automated PR gate.
2. `docs/specs/INSMARTFIX_V1_SPEC.md` — requirements (FR/NFR IDs), the API contract, architecture, decision log.
3. `docs/testing/TEST_PLAN.md` — test levels, environments, test IDs, exit criteria.
4. `docs/launch/LAUNCH_PLAN.md` — rings and rollback.
5. `docs/design/*` — the product design and color language (v1.3 wins on color: brand `#0396A6`).

## Human gates — the ONLY places to ask for approval
- **G1 Spec Review:** the `spec/*` PR. Don't start S2+ until it's approved.
- **G2 Test Review:** the `release/*` PR with `docs/testing/TEST_REVIEW_REPORT.md`. Don't launch until it's approved.

Everything else is automated: plan, scaffold, build, review, merge, test, deploy, promote. Don't ask for permission between gates. When blocked (missing credential, a gate failing after 3 fix attempts, a needed change to the approved spec), report per DEVELOPMENT_PROCESS §5 and keep working on anything unblocked.

## Agent team (`.claude/agents/`)
| Agent | Use for |
|---|---|
| product-manager | spec, decision log, spec deltas |
| architect | contract, data model, implementation plan, module boundaries |
| backend-engineer | `apps/api` |
| web-engineer | `apps/web`, `packages/ui-web`, web tokens |
| mobile-engineer | `apps/mobile`, EAS, Maestro |
| ux-designer | design-compliance gate on UI PRs, screenshot gallery |
| qa-engineer | E2E, resilience, defect triage, Test Review Report |
| security-reviewer | auth, identity gate, uploads, memory integrity, release security pass |
| devops-engineer | scaffold, compose env, CI/CD, deploys |
| release-manager | launch after G2 |

Run independent milestone tasks in parallel (e.g. M4 web and M5 mobile once M3 lands), each in its own worktree and branch.

## Conventions
- Branches: `spec/*`, `feat/<milestone>-<task>`, `fix/*`, `release/*`. Conventional Commits. Squash-merge.
- Tests are named by TEST_PLAN IDs (`T-AREA-N`). PR descriptions list the FR and test IDs they cover.
- Never commit secrets. Never weaken a test to make it pass; fix the code or raise a spec delta.
- Do not put model identifiers in commits, PRs or code.
