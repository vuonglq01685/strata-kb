# Maturity review rubric — local overrides

Your repo's own review criteria. `kb init` creates this file once and
never rewrites it, so anything you put here survives every upgrade —
unlike `docs/review-rubric.md`, which is refreshed with the CLI.

The review agents read `docs/review-rubric.md` first, then this file;
where the two disagree, this file wins.

## Business coverage — extra checklist items

<!-- e.g. - [ ] Every fare rule cites the tariff section it comes from. -->

## Dev implementability — extra checklist items

<!-- e.g. - [ ] Every AC touching the feed names the record type. -->

## Base items we do not apply

<!-- e.g. - [ ] (Business coverage) "Every screen names its owning team" —
     we're a single-team repo; this criterion never applies here. -->
