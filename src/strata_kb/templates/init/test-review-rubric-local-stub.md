# Test review rubric — local overrides

Your repo's own test review criteria. `kb init` creates this file once and never
rewrites it, so anything you put here survives every upgrade — unlike
`docs/test-review-rubric.md`, which is refreshed with the CLI.

The review subagents read `docs/test-review-rubric.md` first, then this file;
where the two disagree, this file wins.

## Q1 axes — extra checklist items

<!-- e.g. - [ ] Every checkout test names the payment sandbox it uses. -->

## Q2 axes — extra checklist items

<!-- e.g. - [ ] A failing payment TC is re-run once against a fresh seed. -->

## Base items we do not apply

<!-- e.g. - [ ] "seed scripts touch only $<url_env>" — our seeds call a shared
     fixture service by policy. -->
