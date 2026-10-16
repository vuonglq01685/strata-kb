---
description: Close out a ticket — re-check citation freshness, run the full suite and paste the real output, record service history, and assemble the PR description
argument-hint: "[ticket id]"
---

Invoke the `dev-handover` skill with the Skill tool and follow its
workflow exactly. Pass "$ARGUMENTS" as the ticket id when given; when
empty, ask for it before continuing.

This is phase 4 and the last phase of the ticket-implementation
pipeline, invoked once every task in the plan is ticked.

*Counterpart in the superpowers plugin:
`superpowers:verification-before-completion`.*

**Hub access — MCP first.** Reach the hub through the `strata-kb` MCP
tools (`kb_search`, `kb_get_section`, `kb_resolve`, `kb_context_new`,
`kb_ticket_lint`, `kb_ticket_fetch`) whenever your client exposes them; fall back to the
matching CLI command only when it does not, or the MCP server cannot be
reached. `kb ticket fetch` runs as `kb_ticket_fetch`: save the text it returns
as `docs/impl/<ticket-id>/ticket.md`, the file the CLI would write. `kb pr lint`, `kb svc note`, `kb usage report` and the cache-writing `kb resolve --status-only --cache` /
`--write-cache` stay CLI-first; where a step below names an MCP path for
one, it is only the no-CLI fallback.

## Freshness re-check (run this FIRST, every time)

Cheap check first: `kb resolve --status-only --cache
docs/impl/<ticket-id>/context.md <ticket-file>` (no CLI → `kb_resolve`;
check the cache `version:` yourself). Exit 0 → use the cache, do NOT
re-pull pinned content. A `cache-*` line or a non-ok verdict → `kb resolve
--write-cache <same path> <ticket-file>` (no CLI → `kb_resolve`, write the
layout by hand), then fill `## Placeholder map` below the marker; never
edit above it.

- **broken** → STOP. Blocker: the BA must re-pin. Never implement around a
  citation that no longer resolves.
- **stale** → show BOTH versions, humans decide: the resolve gives the
  pinned content and the reason, `kb_get_section` (else `kb get …
  --level l3`) the hub's version. Do NOT use `kb diff` — it compares
  the local `.kb/` worktree to a local git rev, not this repo to the hub.
- **ok** → continue.

`<ticket-file>` may be `docs/impl/<ticket-id>/ticket.md`, the file
`kb_ticket_fetch` (CLI: `kb ticket fetch <ticket-id>`) fetched from the
hub.

Steps the skill enforces: for a `path: spike` design there is no plan and
usually no code — put the recommendation under `## Notes` in the PR body,
or as a ticket comment when there is no PR, and mark the ticket's plan state
`n/a (spike)`; otherwise, re-check freshness one final time — a hub publish
mid-implementation must surface here, not in review; report it under
`## Notes` only when it is not `ok` (the `--status-only` output when the
cache path was taken); run the full suite and linters (`cmd.test` and
`cmd.lint` from `-code §cmd.*`, or the commands recorded at the top of the
plan file) and paste the real output, since a completion claim without it is
not accepted — into the PR goes only the command line and its summary lines;
record service history by running `kb svc note <service> --ticket <id> --title
"<title>" --refs "<refs>"` for each service touched so the entries land in
this same PR (`kb svc note` regenerates `<repo_id>-code` from the working
tree first, so a service the ticket added is found once its files are
tracked (`git add`); if this repo has no `<repo_id>-svc` yet —
`dev-code-seed` never run — say so in one line under `## Notes` and record
the history there instead);
`kb svc note` is what makes `kb mission next` on the BA side see this
story as done once the row reaches the hub (after the merge, tell the Dev to
run `kb publish`: a push to the default branch publishes nothing), and a
ticket that skips either stays `draft` or `ready` forever; then
assemble the PR description using the repo's
`.github/pull_request_template.md`, whose sections CI checks with `kb pr
lint`. Keep it short: Ticket — the ticket id and what it asked for, one or
two lines; Changes — one bullet per change a reviewer should know about;
Testing — one line mapping each AC to its test, then a fenced block holding
the `cmd.test` command line itself (e.g. `$ pytest -q`) and only its summary
lines, never the full log, and `Blocking: No`, A5's verdict line, as the last
line; Notes — only when there is something: out of scope, not handled, every
`OPEN(...)`, KB gap, ambiguity or contradiction as a concrete feedback item
on the owning repo; Usage — paste the output of
`kb usage report --ticket <ticket-id> --summary` as is (add
`--with <path-to-the-BA-repo>/.kb` when that clone is at hand, so the cost
covers the BA side too); drop it when the ledger has no row for the ticket.
Leave out what the branch already carries: kb-context (the ticket),
placeholder resolutions (`docs/impl/<ticket-id>/context.md`), TDD exemptions
(the plan), the full usage breakdown (`kb usage report`), and A5's
finding table (`docs/impl/<ticket-id>/review/merge-risk.md`). A section left
as the template's comment counts as empty and fails the check. If the ticket
changed what a service is responsible for, report `amend needed:
<repo_id>-svc §svc.<name>` under `## Notes`. Never edit a `reviewed`
section. **GATE 3** — offered only after A5 comes
back clean — the Dev opens the PR; **GATE 4** the Dev merges. **The agent
does neither.** Option 1 in the Next-step block below is always "Open the PR
yourself" with the branch name already filled in — this is the terminal
phase of the flow, so there is no next automated command; a blocker takes
its place instead.

## A5 — merge-risk review (before GATE 3)

A4 asked whether the branch does what the ticket said. A5 asks a different
question, in a different context: is this safe to merge into the default
branch?

If `docs/impl/<ticket-id>/review/branch.diff` does not exist yet — a cold
handover session, a fresh clone or worktree, or hand-implemented code that
never ran `dev-execute` — build it yourself first, with the same command A4
uses: `mkdir -p docs/impl/<ticket-id>/review && git diff $(git merge-base
<default-branch> HEAD)..HEAD > docs/impl/<ticket-id>/review/branch.diff`.

Dispatch a `merge-risk-reviewer` subagent on the most capable model available.
Give it the persona plainly: a tech lead reviewing before a production deploy,
assuming real traffic, concurrent requests, retries, and more than one running
instance. Hand it `docs/impl/<ticket-id>/review/branch.diff`, the ticket, and
the `## Merge-risk axes` of `docs/pr-review-rubric.md` plus
`docs/pr-review-rubric.local.md`.

**The diff alone is not the review.** Say so in the dispatch: the reviewer
opens the files the change reaches — callers, siblings, migrations, permission
declarations, contracts, tests — and traces the affected flow end to end before
judging. A finding that only names a category is not a finding; it states why
this code, on this path, is dangerous.

It writes `docs/impl/<ticket-id>/review/merge-risk.md`: one row per finding
(severity, file, line, why it is dangerous, proposed fix), then the verdict
line `Blocking: Yes` while any BLOCKER stands, `Blocking: No` otherwise.
BLOCKER and SUGGESTED findings get a fix round, then re-review, at most 3
rounds — same routing as A3: only a standing BLOCKER keeps the verdict
`Blocking: Yes`.

Copy only the verdict line into the PR body, as the last line of
`## Testing` — `kb pr lint` fails the PR when it is missing and when it
reads `Blocking: Yes`. The table stays in `merge-risk.md`. NOTE and NITS
findings a reviewer should see go to `## Notes`, recorded rather than
fixed.

A branch whose A5 still reports `Blocking: Yes` never reaches GATE 3. Option 1
becomes the fix, not the PR.

## Review dispatch contract (every review in this flow)

- The author and the reviewer are NEVER the same subagent. A self-review
  never satisfies a review step.
- A reviewer starts from a fresh context and gets no conversation history —
  hand it only the paths it must read and the constraints that bind it.
- Artefacts move as FILE PATHS, never pasted into the dispatch prompt: the
  draft, the diff, the report. Whatever you paste stays in your context for
  the rest of the session.
- Never pre-judge: a dispatch prompt never tells a reviewer what not to flag
  and never rates a finding's severity for it.
- Name the model on every dispatch — a standard model for authors and
  implementers, the most capable one available for reviewers. Never inherit
  the session default silently.
- Findings → fix subagent → re-review, at most 3 rounds. A BLOCKER or SUGGESTED still
  standing after round 3 stops the flow and goes to the Dev.
- A finding that contradicts the approved design or plan is never auto-fixed:
  show the finding beside the text that mandates it and let the Dev choose.
- Criteria come from the source that matches the review: the rubric's
  `## Pre-code axes` for A1 and A2, its `## Merge-risk axes` for A5, and
  `docs/conventions/<lang>.md` — plus the five pack files it links under
  `docs/conventions/<lang>/` and `docs/conventions/common/` — for A3 and A4.
  Each one's own `.local.md` override wins over its base file. Severity is
  always BLOCKER / SUGGESTED / NOTE / NITS.
- Where the runtime cannot dispatch subagents, run the review as its own pass
  that reads ONLY the paths it was handed and reuses nothing it remembers from
  drafting, and write up its findings the same way — then STOP and hand the
  result to the Dev. The phase does not advance on a fallback pass: one
  context reviewing itself is a weaker substitute, not an equivalent — only
  the Dev's explicit go-ahead advances it, recorded in the tick itself, e.g.
  `Review: ✅ r<n> (fallback, Dev-approved)`.

## Hard rules

- A ticket without a resolvable `kb-context` is not implementable — send it back, never improvise the missing context.
- Broken citation = blocker; stale citation = both versions surfaced, humans decide; neither is ever silently ignored.
- No production code without a failing test observed first. No exception for small tickets, deadlines, or "obvious" changes.
- Never claim done without showing the verification output.
- Never invent or "remember" a standard value — every code/format/enum/threshold in code or tests is verbatim from the resolved section at the pinned version, with a citation comment.
- `<repo>-svc` is for locating and cross-checking work only. It is never a source for an AC or a standard value.
- The ticket is the BA's artifact: report placeholder resolutions and AC findings back; never edit the ticket.
- An AC that cannot be implemented as written becomes `OPEN(BA)` — never reinterpreted, and never pushed past mid-implementation.
- Never edit a test to make it pass; diagnose the cause.
- Code is ground truth: when either code-knowledge document disagrees with the code, trust the code and note the mismatch.
- Never modify a `reviewed` section of `-svc`; propose an amend.
- `hist.*` entries are appended only by `kb svc note`, never hand-edited.
- Never work on the default branch; never push to a protected branch; never merge; never tick DoD/AC checkboxes for humans.
- KB feedback items found during implementation go in the PR description — dropping them silently violates DoD.

`BA-Q:` comes from the local `## Open questions` lines of `design.md` /
`plan.md`, not from the hub: `none` when no `Q<id>` line lacks
`— answered rev N`, otherwise `open Q<ids>`; `dev-implement-ticket` refines
open and waiting from `kb_question_list`. A mixed state is written
`open Q1; waiting Q2`, and `unknown (Q&A unavailable)` is
`dev-implement-ticket`'s when the Q&A tools are refused.

## Next step — ALWAYS end your response with this block

Close every response with a state line and an ordered list of next steps.
Include it even when you stopped early or hit an error — especially then.

    ## Next step

    → 1. <next step in flow> — <what it does>   (next in flow)
      2. <revise the current phase> — <how>
      3. <stop/park> — <where the work is saved>

    State: design <✅ approved|📝 draft|⬜ not written> · plan <✅ approved|📝 draft|⬜ not written|⚠ missing, N commits|n/a (spike)> · tasks <n>/<m> · PR <✅ opened|✅ merged|❌ closed|⬜ not opened|? unknown> · BA-Q: none | open Q<ids> | waiting Q<ids>

Rules:
- Option 1 is ALWAYS the next step in flow order: design → plan → execute → handover.
- Show the exact command with the ticket id already filled in, ready to copy.
- The `State:` line always shows all five markers, even the ones not yet reached.
- A blocker takes option 1 instead and says so, e.g.
  `→ 1. Send back to the BA — ref ATM-STD §5.3 is broken, re-pin needed`.
  Flow order never hides a blocker.

## Auto mode

Run `kb auto status --json`. When `enabled` is false, this section does not apply. When true, the rules below replace the human gates named in them.

`/dev-implement-ticket <us-id>` or `/dev-fix-bug <BUG-id>` runs this skill as its last phase, on the ticket branch it created (`auto/<ticket-id>` for a story, `fix/<BUG-id>` or `hotfix/<BUG-id>` for a bug). Nobody answers questions during the run: a step above that says "the Dev opens", "the Dev merges" or "tell the Dev" is yours to carry out, under the rules below. Every step and every hard rule not named here stays as written.

**Decisions.** Write each decision as one `**Auto decision:**` line: what you checked, the options, the choice, and why. Append it to `docs/impl/<ticket-id>/auto-decisions.md` (create the file with the heading `# Auto decisions` when it is missing). Copy every line in that file into the PR description's `## Notes`.

**Already finished.** The runner re-runs a task after a crash, so check first. Run `gh pr list --head <branch> --state merged --json number,url`. A merged PR means the code is in and only the history row or the publish can be missing. Look in `.kb/<repo_id>-svc/` for this ticket id in a `hist.*` row (`kb svc note` wrote it). Row present: run `kb doctor`; when it says the hub lags, run `kb publish` once, then end `AUTO-RESULT: done`. Row missing: end `AUTO-RESULT: failed merged-without-history <pr-url>`. With no merged PR, look for an open one (`--state open`). An open PR means a crashed run: `git fetch origin && git switch auto/<ticket-id>` (a bug: `fix/<BUG-id>` or `hotfix/<BUG-id>`), then `git pull origin <branch>`, and continue at step 3 of the branch rule below (the CI step).

- **Re-check freshness: `stale` — "humans decide"** → decide as `dev-implement-ticket` does in its Auto mode: when the difference changes no AC this story implements, continue and report it under `## Notes`. Otherwise ask the BA with `kb_question_ask` and end `AUTO-RESULT: blocked-qa Q<id>`.
- **Review contract: a finding that contradicts the design or plan — "let the Dev choose"** → choose the reading closer to the ticket's ACs and the cited standards, fix on that reading, and log both texts and the choice in an Auto decision line.
- **Review contract: "round 3 stops the flow and goes to the Dev", and A5 "stop at once and hand the Dev the trend"** → a BLOCKER or SUGGESTED finding of A5 still standing after round 3 ends `AUTO-RESULT: failed merge-risk <ticket-id>`. The PR is not opened.
- **Review contract: "STOP and hand the result to the Dev" on a fallback pass, advanced only by "the Dev's explicit go-ahead"** → where the runtime cannot dispatch subagents, the separate pass stands in. Record the tick as `Review: ✅ r<n> (fallback, auto)` and go on.
- **Record service history: "tell the Dev to run `kb publish`"** → run `kb publish` yourself, after the merge, as the last step of the branch rule. The `hist` row has to reach the hub, or the story never shows `done`.
- **GATE 3 — "the Dev opens the PR"; GATE 4 — "the Dev merges. The agent does neither"** → the branch rule below, once A5 comes back clean.
- **Hard rule "Never work on the default branch; never push to a protected branch; never merge; never tick DoD/AC checkboxes for humans"** → you merge, under the branch rule only. The rest of the rule stands: no work on `main`, no push to `main`, no DoD or AC box ticked.

**The branch rule.** The ticket branch already exists. Check with `git branch --show-current` that you are on it and not on `main`.

1. Commit the remaining files (stage them by name, including `docs/impl/<ticket-id>/` and the `kb svc note` rows) with a message `<type>: <description>`, then `git push -u origin HEAD`.
2. Open the PR with `gh pr create --title "<ticket-id>: <short description>" --body "<the assembled PR description>"`. For a `hotfix` whose `hotfix_base` in `kb auto status --json` is not empty, add `--base <hotfix_base>`; for every other ticket the PR targets the default branch.
3. Wait for the checks with `gh pr checks --watch`. If a check is red, read the failure (`gh run view --log-failed`) and fix it, commit, `git push`, and watch again: up to 2 rounds in all. A red `kb-pr-lint` caused by the PR text is fixed with `gh pr edit` and costs no round. Still red after the second round: end `AUTO-RESULT: failed ci-red <pr-url>`. Never merge on red or pending checks.
4. Every check green: `gh pr merge --squash --delete-branch`. Only when the merge is refused for want of an approving review you cannot give, use `gh pr merge --squash --admin --delete-branch` instead, and only after every required check is green. After any merge error, run `gh pr view --json state,mergedAt` before you end `failed`: `gh` can report an error from a worktree after the merge went through. A merged PR is a success.
5. After the merge, run `kb publish` once. It mirrors `.kb/`, so the `hist` row reaches the hub. When it prints a hub PR URL, name it in the reply. When it fails, end `AUTO-RESULT: failed publish <reason>`.

### Result line

You run as the last phase of `/dev-implement-ticket` or `/dev-fix-bug`, which ends the task: report your outcome to it in plain words, with the reason when you stopped. When the runner started you directly as `/dev-handover <ticket-id>`, end the reply with exactly one line, and make it the last line. Nothing follows it: no code fence, no markdown, no closing remark. The `## Next step` block comes first. It has one of three forms:

- `AUTO-RESULT: done` — the PR is merged and `kb publish` has run, or the work was already finished. Write no text after `done`; always give a reason after `failed`.
- `AUTO-RESULT: blocked-qa Q<id>[,Q<id>...]` — a stale citation changes an AC and the BA must settle it.
- `AUTO-RESULT: failed <reason>` — anything else: `ci-red <pr-url>` after 2 fix rounds, `merge-risk <ticket-id>`, `publish <reason>`, or `merged-without-history <pr-url>`. The reason goes on the same line.
