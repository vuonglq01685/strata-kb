# PR review rubric — local overrides

Your repo's own review criteria. `kb init` creates this file once and never
rewrites it, so anything you put here survives every upgrade — unlike
`docs/pr-review-rubric.md`, which is refreshed with the CLI.

The review subagents read `docs/pr-review-rubric.md` first, then this file;
where the two disagree, this file wins.

This is where stack-specific rules belong — the base file is deliberately
framework-agnostic.

## Pre-code axes — extra checklist items

<!-- e.g. - [ ] Every new endpoint names the feature flag that gates it. -->

## Merge-risk axes — extra checklist items

<!-- e.g. - [ ] (Security) Every controller declares its permission decorator. -->
<!-- e.g. - [ ] (Contract) Every user-facing message has an EN and a VI key. -->

## Base items we do not apply

<!-- e.g. - [ ] (Migration) "rolled back" — we ship forward-only migrations by
     policy; this criterion never applies here. -->
