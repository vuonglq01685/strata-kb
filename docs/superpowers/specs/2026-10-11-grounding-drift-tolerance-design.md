# Grounding drift tolerance — `kb ticket check` stops failing on a moved revision alone

Status: approved direction · 2026-10-11

## 1. Intent

A BA writes a ticket, the SA grounds it (`- Grounded on: <repo>:<repo>-code @ <rev>`),
and the ticket waits, Ready for Dev. Meanwhile the Dev repo keeps merging, and
every merge moves `-code`'s manifest `revision`. When a dev finally picks the
ticket up, `kb ticket check` fails with `stale grounding: ticket says @<old>,
<doc> is @<new>` (`ticketcheck._check_revision`, `ticketcheck.py:510`). The
ticket goes back to the BA, who asks the SA to re-run `/sa-ticket-ground`.

In practice the re-ground almost always changes only the `Grounded on:` line.
The cited ids, columns, routes, files and compose facts were still right. The
failure is noise, and it costs a BA → SA round trip per ticket.

Goal: `kb ticket check` fails only when the grounding is actually wrong
against the current `-code`, and then it says plainly that the SA must
re-ground. A moved revision alone never fails.

## 2. The two tiers

`kb ticket check` already verifies every cited fact against the **current**
`-code` document: ids (`_check_ids`), columns / routes / commands
(`_check_tables_routes_commands`), `Files:` (`_check_files`), Volumes /
Healthchecks / Devices (`_check_compose_facts`). Those checks decide the tier.
Call them the *fact checks*.

**Tier 1 — pass, the dev carries on.** Revision differs, and every fact check
passes.

| Case | Output | Exit |
|---|---|---|
| Revision differs; every cited section is byte-identical (stripped) between the baseline and the current `-code` | `[note] grounded @<old>, still valid at @<new> — cited sections unchanged` | 0 |
| Revision differs; some cited section changed, but every fact check passes (the **grey zone**) | one `[warn]` per changed section, carrying a unified diff of that section, baseline → current | 0 |
| Revision differs; the baseline cannot be found on the hub (`baseline not on hub`), or the doc came from the local fallback (no hub history) | `[warn] grounded @<old>, now @<new> — no baseline to diff, cited facts still hold` | 0 |

**Tier 2 — fail, back to `/sa-ticket-ground`.** Revision differs **and** at
least one fact check errors (a cited id is gone, a column is not in the table,
a route or command is gone, a `Files:` path is not in `struct.tree`, a compose
fact no longer matches). Output: the existing fact errors, unchanged, plus one
error:

`grounding drifted since @<old> (now @<new>) and no longer holds — re-run /sa-ticket-ground`

Exit 1, as today.

**Unchanged.** Revision matches → behaviour exactly as today. Errors that are
not drift (`Open decisions` not empty, `[NEW: D<k>]` not `DECIDED` or
`SUPERSEDED`, duplicate heading, malformed `Grounded on:`, no unique holder,
doc not found) stay errors and get no re-ground line. The empty-manifest-
revision warning stays.

The same rules apply to a mission plan (`--heading "## Services & order"`),
which runs through the same `check()`.

## 3. Goals, non-goals, anti-goals

Goals

1. `kb ticket check` exit 0 in every Tier 1 case, exit 1 in Tier 2.
2. A Tier 1 grey-zone run shows the dev the diff of each changed cited section,
   so the dev judges it (type change, payload change) without the SA.
3. A Tier 2 run names the broken facts and tells the reader to re-run
   `/sa-ticket-ground`.

Non-goals

- `kb ticket stale` and `kb-doctor.yml`. They keep their current output and
  exit codes (a changed cited section is still `stale` there). The user scoped
  this change to `kb ticket check`.
- Any bot that re-pins `Grounded on:` or opens PRs in the BA repo. Tier 1
  makes a re-pin unnecessary, and the anti-goal "CI writes nothing in the BA
  repo" (`2026-10-11-ba-plan-publish-design.md`) stands.
- Moving a ticket out of Ready for Dev automatically.
- Semantic comparison (column types, route payloads). The fact checks compare
  names; the grey-zone diff is how a dev sees anything subtler.

Anti-goals

- A ticket whose cited fact is gone passing `kb ticket check`.
- A new failure mode: a hub or git hiccup while computing the diff must
  degrade to the "no baseline to diff" warning, never to an error or a crash.
- `ticketcheck` importing `ticketstale` (`ticketstale` already imports
  `ticketcheck`; 1.16.3 removed every import cycle). The drift lookup is
  injected by the caller, like `load_doc` and `load_decisions`.

## 4. Constraints (verified)

- `ticketcheck.check(text, *, load_doc, heading, load_decisions)` is
  filesystem-free; the CLI (`cli.py:2947-3006`) injects `load_doc` (hub first,
  local `.kb/` fallback) and `load_decisions`.
- `ticketstale.architecture_refs` already finds the baseline: `_holder`, then
  `_baseline_commit` (newest hub commit whose `_manifest.yaml` carries the
  pinned revision), then `resolve_refs` over the cited ids, which returns
  `ResolvedRef` with `status` `ok | stale | broken` and `content` = the
  section text **at the baseline**. Section ids come from `_cited_ids`
  (`db.<t>.<col>` collapses to `db.<t>`, `[NEW]` lines skipped).
- The current section text is readable from `LoadedDoc` (the doc `load_doc`
  returned) or from the hub worktree.
- `LintReport.passed` is "no error"; warnings and notes never fail.
  `to_json()` exposes `errors`, `warnings`, `notes` as string lists.
- Existing tests pin the old behaviour: `tests/test_ticketcheck.py:183`
  (`test_revision_mismatch_is_stale_grounding`) must be rewritten to the new
  rules.
- Skill text that relies on the old behaviour:
  - `templates/init/bodies/ba-ticket-author.md:221-222` and
    `ba-mission-plan.md:185-187` skip `kb ticket check` on non-`architecture`
    amend triggers because "they would force a re-ground after every dev
    commit". That reason is no longer true.
  - `ba-ticket-author.md:269`: re-run `/sa-ticket-ground` "only when `-code`
    moves after handover" — becomes "only when `kb ticket check` fails".
  - `sa-ticket-ground.md` gate step (≈ line 116) should state that a Tier 1
    warning is a PASS and a Tier 2 failure means re-ground.

## 5. Decided

- Tier boundaries exactly as section 2 (user decision).
- Grey zone warns with a diff and does not block (user decision).
- Tier 2 always routes back to `/sa-ticket-ground` (user decision).
- Scope: `kb ticket check` only; `kb ticket stale` untouched (user decision).

## 6. Builder's calls (made by me, not the user — flag if wrong)

- **Shape of the injected callable.** Suggested: `check(..., load_drift=None)`
  where `load_drift(repo, doc_id, rev, section_ids) -> list[ResolvedRef] | None`
  (`None` = baseline unavailable). The CLI implements it by reusing
  `ticketstale`'s baseline lookup; make the helpers it needs public in
  `ticketstale` (or move them to a small module both import) rather than
  copying them. With no `load_drift` (library callers, tests), a revision
  mismatch behaves as "no baseline to diff".
- **Diff format.** `difflib.unified_diff` of the stripped baseline vs current
  section, labelled `<doc> §<id> @<old>` / `@<new>`, capped at 40 lines per
  section with a `… (<n> more lines)` tail. The warning is one multi-line
  string so `--json` carries it intact in `warnings`.
- **Tier 2 trigger order.** Run the fact checks first, then decide: revision
  mismatch + any fact-check error ⇒ append the re-ground error; else emit the
  Tier 1 note/warnings. A `broken` ref from the drift lookup with no fact-check
  error (section renamed but the cited id still resolves) stays a grey-zone
  warning — the fact checks are the source of truth.
- **Amend skills.** Remove the "skip `kb ticket check`" rule for non-
  `architecture` triggers in `ba-ticket-author` / `ba-mission-plan`: they now
  run `kb ticket check` on every amend, and hand off to the SA only when it
  fails. Regenerate the derived skill/command/prompt flavours with the repo's
  own template tooling, never by hand.
- **Release.** Minor bump to 1.18.0 (behaviour change of a gate), CHANGELOG
  entry, README `kb ticket check` row updated.

## 7. Done when

- New/updated tests cover: identical sections ⇒ PASS + note; changed section,
  facts hold ⇒ PASS + diff warning; baseline missing ⇒ PASS + warning; fact
  gone after revision moved ⇒ FAIL + re-ground error; revision matches ⇒
  unchanged behaviour; `load_drift` raising a git error ⇒ degrades to warning.
- The repo's gate (lint, format, pyright, test suite) passes.
