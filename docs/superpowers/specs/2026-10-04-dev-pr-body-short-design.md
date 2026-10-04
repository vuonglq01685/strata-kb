# Dev-repo PR body: Ticket / Changes / Testing — design

Date: 2026-10-04 · Status: approved in chat, pending spec review

## Problem

`dev-handover` assembles a dev repo's PR body from
`templates/init/pull-request-template.md`, and CI (`kb pr lint`) requires nine
sections: Ticket, kb-context, AC→test map, Placeholder resolutions,
Verification, TDD exemptions, Findings, Usage, Review. The result is long and
mostly repeats artefacts the branch already carries (ticket, context cache,
plan, usage ledger, `docs/impl/<id>-review/merge-risk.md`). The body still
lacks the two things a reviewer asks for first: what changed, and what is out
of scope or not handled.

Goal: a PR body says what the ticket asked, what the PR did, and how it was
tested. Nothing else unless there is something to flag.

## Target body

````markdown
## Ticket
ABC-12 — <what the ticket asked for, 1–2 lines>

## Changes
- payments/refund.py: POST /refund
- migration 0042: refunds table

## Testing
AC1 → test_refund_ok · AC2 → test_refund_limit
```
$ pytest -q
212 passed in 8.1s
```
Blocking: No

## Notes
<optional — only when there is something: out of scope, not handled,
findings for the BA/KB, amend needed, stale citation, no -svc yet>
````

`Blocking: No` may sit anywhere in `## Testing`; the template puts it last.

## Lint canon (`src/strata_kb/prlint.py`)

- `REQUIRED_SECTIONS = ("Ticket", "Changes", "Testing")`. Each must be present
  once and non-empty after HTML comments are stripped (existing
  `missing-section`, `duplicate-section`, `empty-section` rules).
- `## Notes` is optional; the linter never requires or inspects it (extra `##`
  sections are already ignored).
- `## Testing` carries the two checks that used to live in other sections:
  - a fenced block with real output (`no-verification-output`), and — when the
    plan is found — the plan's `cmd.test` inside a fence
    (`verification-missing-cmd`, plus the existing `plan-*` / `ticket-id-*`
    warnings). Only the section name changes from Verification to Testing.
  - the A5 verdict: a `Blocking: No` line (`no-review-verdict` when absent,
    `review-blocking` on any `Blocking: Yes`). Same `_BLOCKING` regex, same
    fail-closed rule.
- Deleted: `SENTINEL_SECTIONS`, `EXEMPTION_SLUGS` and the exemption-line check,
  the `AC->test map` heading alias. Dead once their sections leave the canon.
- The module docstring and `render()` text follow the new count.

## What leaves the PR body, and where it lives instead

| Was | Now |
|---|---|
| kb-context | the ticket's own `## KB context` block |
| Placeholder resolutions | `docs/impl/<id>-context.md` placeholder map |
| Verification (full log) | `## Testing`: command line + summary lines only |
| Freshness re-check output | still run; reported in `## Notes` only when not `ok` |
| TDD exemptions | the plan's `Exempt:` lines (still reviewed at plan approval) |
| Findings | `## Notes`, only when there are any — dropping one silently still violates DoD |
| Usage table | not in the PR; `kb usage` ledger unchanged |
| Review table | `docs/impl/<id>-review/merge-risk.md`; only `Blocking: No` in Testing; NOTE/NITS worth a reviewer's attention go to Notes |

## Files

- `src/strata_kb/prlint.py` — canon and checks above.
- `src/strata_kb/templates/init/pull-request-template.md` — four headings,
  one short comment each.
- `dev-handover` skill + three wrappers (`claude-skill-`, `claude-command-`,
  `copilot-…prompt.md`, `cursor-`): rewrite the "assemble the PR description"
  step to the target body; drop "paste the Usage table into the PR"; A5 copies
  only the verdict line; spike recommendation, missing `-svc`, `amend needed`
  and non-ok freshness go to `## Notes`.
- `dev-plan` skill + wrappers, `tdd-exemptions.md`, `QUICKSTART-dev.md`,
  `initcmd.py` — wherever they say an item is copied into the PR's TDD
  exemptions / Usage / Review sections.
- `dev-design` wrappers (spike recommendation → `## Notes`) and the
  `conventions-*.md` packs (narrowed lint rules → `## Notes`).
- A guard test fails on any shipped template that still names a retired PR
  section; `kb pr lint` reports `unclosed-fence` for a fence left open in
  `## Testing`, since nothing required follows it to go missing.
- `kb-pr-lint.yml` — comments only. Workflow file name and job name
  stay frozen (branch protection keys on them).
- Docs: `docs/src/guide-dev.{en,vi}.md`, README §13, CHANGELOG Unreleased.

## Compatibility

`kb-pr-lint.yml` installs `strata-kb=={version}` pinned at scaffold time, so a
dev repo keeps the nine-section lint until it re-runs `kb init`, which updates
the template, the wrappers and the pinned lint together. CHANGELOG marks this
**Breaking** for dev repos on re-init: an open PR written against the old
template fails the new lint until its body is rewritten.

## Testing

- `tests/test_prlint.py`: new canon passes; each of Ticket/Changes/Testing
  missing or empty fails; Notes absent passes; Testing without a fence fails;
  `cmd.test` check now reads Testing; `Blocking: Yes` / missing verdict in
  Testing fail; an old nine-section body fails on missing Changes/Testing.
  Tests for deleted checks are removed.
- `tests/test_templates.py`: template headings equal the canon in order; every
  required section is named in the four `dev-handover` wrappers; wrapper
  assertions about Usage/Review/TDD-exemption pasting updated to the new text.

## Out of scope

- BA ticket template and `kb ticket lint` (separate canon, unchanged).
- `kb usage` ledger and the A1–A5 review flow themselves (only where their
  output is written changes).
- Rebuilding the guide PDFs (needs the macOS fonts `docs/src/build_pdf.py`
  reads; a follow-up on a Mac).
