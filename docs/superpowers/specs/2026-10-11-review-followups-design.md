# Review follow-ups: scheduled staleness, end-to-end ticket cost, usage in the PR

**Status:** approved design (decisions taken 2026-10-11)
**Source:** §8 đợt 3 item 11 (H14, B4, G15, C7) and §7.1 #4–#5 of
`docs/superpowers/reviews/2026-10-10-full-framework-review.vi.md`. This is
batch 3e-1 of wave 3. 3e-2 (module docstrings and provenance comments)
follows separately.

**Decisions** (2026-10-11):
- Wave 3e splits in two.
- Cost comes back to the PR body as a short table.
- The scheduled staleness check keeps one issue up to date.

## Goal

| Finding | Today |
|---|---|
| H14 | Amendment is only detected when a PR touches a ticket, or when someone runs `kb doctor --context`. A merged ticket is never re-checked when the hub publishes later. |
| §7.1 #4 / B4 | A ticket's cost is split across two repos: the BA ledger holds `ba-*`/`sa-*`, the Dev ledger holds `dev-*`. Nothing gives the end-to-end total. |
| §7.1 #5 / B4 | Since 1.7.0 the PR body carries no cost. `dev-handover` says to leave the usage table out. |
| G15 | `kb svc note` sorts ticket ids as strings, so `T-10` comes before `T-2`. |
| C7 | There is no negative test that an unpublished `.kb/` doc never shows up through search or get. |

## Design

### 1. `kb ticket stale` + `kb-doctor.yml` (H14)

- **`ticketstale.scan(paths, hub) -> list[StaleFile]`** walks the given
  files and directories (default `tickets/` and `missions/`, `*.md`).
  - It parses each file's kb-context block. A file without one is
    skipped, and so is one whose block does not parse; `kb ticket lint`
    reports those.
  - It resolves the block with `resolve_refs` and keeps the refs that are
    `stale` or `broken`.
- **`kb ticket stale [PATH...] [--json|--md]`.**
  - Output lists each file with its stale and broken refs. `--md`
    produces the issue body.
  - Exit codes: 0 when everything is current, 2 when something is stale
    (as `kb resolve` does), 1 on any broken ref.
- **`kb-doctor.yml`** is scaffolded for the `ba` and `dev` kinds only.
  - Runs daily on a cron (`17 3 * * *`) and on `workflow_dispatch`.
  - It installs the pinned `strata-kb` and authenticates the hub as
    `kb-ticket-lint.yml` does, then runs `kb ticket stale --md`.
  - With `gh`, it keeps one open issue labelled `kb-stale-citations`:
    - on findings, it creates the issue or edits its body;
    - when everything is current, it closes the issue with a comment.
  - Needs `permissions: issues: write`.

### 2. `kb usage report --with <kb-dir>` (B4 merge)

- **Repeatable flag.** `--with <kb-dir>` reads the ledger of another
  repo's `.kb/`, typically the BA repo's clone, and aggregates its rows
  together with this repo's.
- **Duplicates.** A row is dropped when its `(session, uuid)` was
  already read, so pointing `--with` at the same `.kb/` twice does not
  double count.
- **Read-only.** Nothing is written into either ledger.
- **Combined with `--ticket T`**, this is the ticket's cost across the BA
  and Dev repos.

### 3. Usage back in the PR body (B4)

- **`kb usage report --ticket T --summary`** prints a short Markdown
  block:
  - a `## Usage` heading;
  - one total line with calls, tokens and cost;
  - at most 6 phase rows, costliest first, plus a "N more" row.
- **`dev-handover`** puts that block in the PR as an optional `## Usage`
  section. It no longer says to leave the usage table out.
- **The PR template** gets an optional `## Usage` section. `kb pr lint`
  keeps requiring only Ticket, Changes and Testing. Usage is allowed,
  never required.

### 4. Natural sort for `hist.*` (G15)

`svcnote` orders rows with a natural key (`T-2` before `T-10`). The key
splits the id into text and number runs.

### 5. C7 negative test

- **Setup.** A hub whose own `.kb/` holds an unpublished document with a
  unique word. `federation/` has a different document.
- **Assertions.** The unpublished document never comes back from:
  - `query.search_detailed` (`kb query`);
  - the MCP `kb_search` and `kb_get_section` tools;
  - `kb get`;
  - the Web UI search.

## Out of scope

- Docstrings and provenance comments (3e-2).
- Committing `report.html`. It was rejected in favour of the PR-body
  table.

## Testing

- `tests/test_ticketstale.py`:
  - a current ticket, a stale ticket and a broken ticket;
  - skipped files: a file with no kb-context block, and one whose block
    does not parse;
  - `--md` and `--json` output;
  - exit codes.
- `tests/test_usage_with.py`:
  - two ledgers merge by ticket;
  - a duplicate `--with` does not double count;
  - `--summary` caps the phase rows at 6.
- **Scaffolding:** `kb-doctor.yml` is in the expected files for `ba` and
  `dev` only, and its YAML parses.
- **Templates:**
  - the `dev-handover` body mentions `--summary`;
  - `kb pr lint` accepts a PR body with or without `## Usage`.
- **`svcnote`:** a natural-sort test with `T-2`, `T-10` and `T-9`.
- **C7:** the negative test above.

## Delivery

One PR, release **1.16.0**: new commands, flags and a new workflow
template.
