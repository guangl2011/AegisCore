## Summary
<!-- What changed and why, in 1–3 sentences. -->

## Stage / gate
- [ ] S1 Spec (→ G1 human review)
- [ ] S2 Plan · S3 Scaffold · S4 Build · S5 Hardening (automated gate)
- [ ] Release (→ G2 human test review)

## Requirements covered
<!-- FR/NFR IDs, e.g. FR-2.6, FR-5.3 -->

## Tests proving them
<!-- TEST_PLAN IDs, e.g. T-INBOX-5, T-DISP-1. All must exist and pass. -->

## Automated gate checklist
- [ ] CI green (lint, types, unit, integration, contract drift, coverage)
- [ ] Code review agent: no confirmed correctness findings
- [ ] Security review (required if auth / identity gate / uploads / tokens / memory events touched)
- [ ] Design compliance (required for UI changes): color roles, 44pt targets, all §10 states
- [ ] Screenshots attached for UI changes (light + dark)
