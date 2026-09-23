> This file extends [common/security.md](../common/security.md) with Playwright e2e-specific content.

# Playwright e2e security

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/e2e-playwright.local.md`.

## Test credentials

- Never commit a real credential to a spec, a fixture, or a
  `playwright.config.*`. Read them from the environment:
  `process.env.E2E_PASSWORD`, and fail loudly when the variable is unset.
- Test accounts are test accounts: never reuse a staff, admin or customer
  login that exists outside the test environment.
- A recorded `storageState.json` holds live session cookies. Write it to a
  gitignored path and never check it in.

## Target environment

- e2e runs against a disposable environment. Never point a suite at
  production, and never at a database whose contents someone else depends
  on.
- Seed and tear down the data a spec needs; a spec that only works against
  a hand-prepared account is not reproducible.

## Trace artefacts

- Traces, videos and screenshots capture whatever was on the page,
  including tokens and personal data. Upload them to the CI run's private
  artefacts, never to a public bucket or a PR comment.
- Redact or avoid asserting on real personal data; use generated fixtures.
