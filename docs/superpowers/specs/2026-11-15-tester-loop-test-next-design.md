# Tester loop, block 2 — `kb test next` (design)

Date: 2026-11-15 · Size: small change (block 2 of 3, release 1.37.3, no tag yet)

Builds on `2026-11-15-test-strategy-design.md` D3 (order) and D8 phase 2, and on
`2026-11-14-tester-role-design.md` D3 (testable story). Approved owner plan:
three blocks, one release; block 3 (`kb auto` for tester) picks its next story
from this command.

## Intent
The test order exists (`teststrategy.order`) and the hub shows it, but a Tester
on the VM — and the block 3 picker — has no command that says "test this story
next". `/tester-test-story` always needs a story id.

## Goals
1. `kb test next [--file docs/test-strategy.md] [--hub HUB] [--json] [--all]`
   in a tester repo: the testable stories in D3 order (retests first, then
   rank, unranked, `last`; `Depends on` inside a rank). Default prints the
   first one; `--all` the whole list. Each entry: story, tier, rank (or
   `last`/none), row target, match (`id | mission | area | outside`).
2. No strategy file, or `> Plan: —`: plan order over every plan
   (`plan_view(..., all_plans=True)`), with a warning line on stderr.
3. Exit 0 with a story; exit 3 when nothing is testable (block 3 treats it as
   idle); exit 1 on hub/read errors.
4. `/tester-test-story` with no argument runs `kb test next --json`, proposes
   the first story with its reason, and asks the Tester; with an argument it
   behaves as today.

## Non-goals / anti-goals
- No change to the order rules or the testable rule (both already reviewed).
- The strategy never blocks testing: `kb test next` works without one.
- Not on the hub API (the Tester runs on its VM with a cloned hub).

## Approach
One sensible way: a thin `strategyhub.next_stories(hub, strategy | None) ->
list[Placement]` over the existing `plan_view` + `teststrategy.order`, and a
CLI command beside `kb test stale`. Alternatives (a hub route, a new module)
add surface for no user gain.

## Left to the builder
Text output format; reuse of `test_stale`'s option and read-error handling.
