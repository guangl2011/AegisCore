# AegisCore

Monorepo for **InsmartFix** — the Insmart AI field app for contractors (web portal, backend API, iOS and Android apps).

- Product design: [`docs/design/INSMARTFIX_PRODUCT_DESIGN.md`](docs/design/INSMARTFIX_PRODUCT_DESIGN.md)
- Color language: [`docs/design/COLOR_LANGUAGE.md`](docs/design/COLOR_LANGUAGE.md)

## How this repo is built
- **Process:** [`docs/process/DEVELOPMENT_PROCESS.md`](docs/process/DEVELOPMENT_PROCESS.md): spec → **G1 Spec Review (human)** → plan → scaffold → build → system test → **G2 Test Review (human)** → launch. Everything between the two gates is automated by the agent team in [`.claude/agents/`](.claude/agents).
- **Spec:** [`docs/specs/INSMARTFIX_V1_SPEC.md`](docs/specs/INSMARTFIX_V1_SPEC.md)
- **Test plan & environments:** [`docs/testing/TEST_PLAN.md`](docs/testing/TEST_PLAN.md)
- **Launch plan:** [`docs/launch/LAUNCH_PLAN.md`](docs/launch/LAUNCH_PLAN.md)

## Layout (after scaffold)
```
apps/api      FastAPI backend
apps/web      Next.js contractor web portal
apps/mobile   Expo app (iOS + Android)
packages/     contracts · core · tokens · ui-web
infra/        docker compose test environment, seed data
```
