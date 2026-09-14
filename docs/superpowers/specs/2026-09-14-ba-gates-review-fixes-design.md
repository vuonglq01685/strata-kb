# BA gate review fixes — a Definition-of-Ready gate that reads the body, not just the headings

**Status:** approved design, ready for an implementation plan
**Source:** reviewer E of the 2026-09-08 full framework review,
`docs/superpowers/reviews/2026-09-08-full-framework-review/E-ba-gates.md`
(findings HIGH-1…HIGH-4, MEDIUM-1…MEDIUM-7, L1…L10), and §5 đợt 3 item 1 of
`docs/superpowers/reviews/2026-09-08-full-framework-review.vi.md`.
**Predecessor:** `2026-09-11-federation-publish-ci-review-fixes-design.md`
(reviewer D, merged as PR #49). That batch made the federation layer keep
C7, C15 and C17; this batch makes the BA gate keep the Dev-readiness half
of C10, plus the BA halves of C8 and C16.
**Approach:** as approved on 2026-09-14 — put every content rule in
`acquality.py` and leave `lintcore.py` a text-primitive module; make the
bracketed `[doc-id §section]` the one citation form the gate parses; and
promote presence-only checks to substance checks at error level in one
release rather than over a two-release ramp.

## Goal

Reviewer E built a hub, a publishing KB repo and a BA repo from scratch,
pinned a real `arinc-424 §5.129` block against a real hub commit, and ran
41 adversarial mutations of a golden ticket and a golden mission through
the shipped lints. The verdict splits cleanly in two.

The **grounding half is strong and could not be broken**: a ghost tag, a
random-hex version, an empty version, a commit predating the document, a
citation to an unpinned section, a ghost parent mission, a filename outside
the mission backlog and a mistyped `--missions-dir` are each a hard error;
`kb resolve` exits 0/1/2 as specified; the `--json` envelope is exactly
C10's contract; MCP parity is honest, reporting the two filesystem checks
it cannot run as notes that reach the agent.

The **Dev-readiness half is presence-only**, and the 2026-08-12 upgrade
spec's own goal — *"Make BA missions/tickets Dev-ready by construction"* —
is not delivered:

- A ticket whose nine required sections are all present and all read `TBD`
  passes with warnings (HIGH-1). So does one whose ACs are *"The system
  shall behave correctly and handle all edge cases gracefully"*, whose NFR
  row is `| Speed | fast | eyeball | n/a |`, whose UI spec is *"Looks
  nice."*, and whose `## Review record` self-declares
  `| 2026-09-08 | 1 | 5 | 5 | me |` — with every Definition-of-Ready
  checkbox unticked.
- `check_headings` (`lintcore.py:132-156`) strips fences but not HTML
  comments, while two sibling checks do strip them. Four required sections
  can be commented out and the gate still passes (HIGH-2).
- `section_body` (`lintcore.py:98-113`) terminates a section at the first
  line starting with `# `, scanning raw text, so a `# comment` line inside a
  fenced example truncates the section. Two perfectly valid tickets are
  rejected (HIGH-3). Every body-level check reads through this helper, so
  the blast radius is the whole gate.
- `INLINE_CITE_RE` (`lintcore.py:50-53`) takes the last whitespace-delimited
  token before `§` as the doc-id and compares case-sensitively, so
  `per ARINC 424 §5.129` is parsed as doc-id `424` and fails at error level,
  `(ARINC-424 §5.129)` fails on case, and `arinc-424 § 5.129` matches
  nothing at all (HIGH-4). In a regulated-aviation repo, an error-level gate
  that rejects prose naming the standard the way the standard names itself
  teaches BAs to stop writing `§` — which defeats the grounding the gate
  exists to enforce.
- A second `## KB context` block is never parsed (`kbcontext.py:157-175`
  returns the first), so an unvalidated pin can sit in a ticket looking
  authoritative, and the verdict depends on block order (MEDIUM-1).
- `docs/review-rubric.md` — the file whose own first lines say *"Edit this
  file to tune the criteria for your domain"* — is silently overwritten by
  `kb init --kind ba`, because `PROTECTED_FILES` (`initcmd.py:179-181`) has
  three entries and no `.local.md` escape exists on the BA side, unlike the
  dev side's `docs/conventions/<lang>.local.md` (MEDIUM-5).
- `QUICKSTART-ba.md:111-129`, under **"DoR rules (what CI enforces)"**,
  claims CI rejects stale refs and enforces citations *"(and vice versa)"*.
  Both are false: an amendment to a cited aviation standard turns no BA gate
  red, and the reverse direction is a warning (MEDIUM-2).
- The scaffolded gate runs `pip install center-kb` unpinned
  (`kb-ticket-lint.yml:40`) while `kb-code.yml` and `kb-publish.yml` already
  pin `=={version}`; it has no `concurrency:` block, and it prints failures
  inside a `::group::`, which GitHub renders collapsed (MEDIUM-6).

The suite is green — 222 tests across the eight BA lint modules, 123
template tests, 20 MCP tests. Every finding here is a shape the suite does
not cover, not a broken test.

## Decisions taken during brainstorming (2026-09-14)

1. **Every new substance check lands at error level in 0.22.0.** Reviewer E
   proposed a two-release ramp (warnings first, errors one minor later).
   Rejected: the gate's whole value is being a gate, and a release that
   ships the rule as a warning ships a gate that still passes an empty
   ticket. The cost is accepted explicitly — existing BA tickets may fail on
   upgrade, so the batch ends with a real run against KrisShop's tickets and
   a Breaking section in the changelog.
2. **`[doc-id §section]` becomes the citation form the gate parses.**
   Reviewer E proposed re-anchoring the bare-prose regex against pinned
   doc-ids; §5 đợt 3 proposed requiring the bracketed form. The bracketed
   form wins: it removes the guess entirely rather than making the guess
   better, so no amount of natural prose can produce a false error. The
   migration cost (templates, wrappers, rubric, existing tickets) is paid
   with a migration warning rather than a hard failure — see §2.
3. **`## Review record` gets a schema check at error level; the score
   threshold and the round cap stay warnings.** The 2026-08-12 review-agents
   spec chose warning-only for the whole record. This batch splits it: the
   *shape* of the row is machine-checkable and a fabricated row should be
   visible, while *"is a 4 really a 4"* and *"was three rounds enough"* stay
   the BA's judgment. The reversal is recorded in the older spec.
4. **Stale refs become an error only behind `--fail-on-stale`.** Default
   behaviour still matches the 2026-07-17 spec (stale = warning). The flag
   plus a documentation fix closes the honesty gap without turning every
   upstream amendment into a wall of red PRs.
5. **`docs/review-rubric.md` and `docs/ac-quality.md` get `.local.md`
   siblings**, created once and never refreshed, exactly as
   `conventions.py:121-139` already does for the dev side — rather than
   being added to `PROTECTED_FILES`, which would freeze a BA repo's rubric
   at whatever version it was initialised with.
6. **All content rules live in `acquality.py`.** `lintcore.py` keeps text
   primitives and severity wiring; `ticketlint.py` and `missionlint.py` stay
   wiring. `lintcore`'s own docstring says nothing in it knows the ticket or
   mission heading contracts, and AC/NFR rules are contract-specific.
7. **L1 (HTML comments in the citation scan) is pulled into this batch**
   even though the rest of the LOW findings are deferred: the HIGH-2 fix
   already brings `HTML_COMMENT_RE` into the same call path, and leaving the
   citation scanner comment-blind would keep a BA's own
   `<!-- TODO check [arinc-424 §9.999] -->` failing the gate.

## Scope

**In:** HIGH-1, HIGH-2, HIGH-3, HIGH-4, MEDIUM-1, MEDIUM-2, MEDIUM-4,
MEDIUM-5, MEDIUM-6, the review-record half of MEDIUM-3, and L1.

**Out, by name** (each stays a live finding for a later batch):

- MEDIUM-3's trip-wire tests: the ticket-wrapper parity test the mission
  side already has (`tests/test_init.py:963`), assertions for the 3-round
  cap and the `≥ 4` threshold across all 8 wrappers, a numeric pin on
  `len(expected_files("ba"))`, and the stale 7-tuple
  `BA_TICKET_AUTHOR_PIPELINE_STEPS` that is missing `"Maturity review"`.
- MEDIUM-7: the "500–800 token" budget that no wrapper's CLI or MCP example
  actually passes.
- MEDIUM-4 item 5: making `acquality` read its deny-list from
  `docs/ac-quality.md` instead of hardcoding it.
- L2 (a ticket with no `> Parent mission:` line has no traceability check),
  L3 (mission coverage counts any file with the right name), L6
  (`%%TODO%%` inside HTML comments counted by `missionlint`, so the shipped
  `mission-template.md` warns about its own guidance), L8 (the
  `N/A — <reason>` escape hatch missing from the four mission wrappers), L9
  (the dead Acceptance-Criterion rule in the mission wrappers), L10
  (`## Review record` in neither heading tuple).
- Installing the scaffolded gate into this repo's own
  `.github/workflows/`: this repo has no `tickets/` directory, so the gate
  would always take its "nothing changed" arm.

## Design

### 1. `acquality.py` becomes the content-rule module

`acquality.py` is 85 lines today: `OPEN_RE`, a bilingual `WEASEL_PHRASES`
tuple, `_WEASEL_RE`, `_MEANS_RE` and `weasel_hits`. It grows to hold every
rule about what a section *says*, keeping its bilingual (EN + VI) character
— ticket bodies follow the BA's working language, so no rule here may
assume English.

New public surface:

- `PLACEHOLDER_PHRASES` — the deny-list for an unfilled body: `TBD`,
  `TODO`, `N/A`, `NA`, `none yet`, `xxx`, `...`, `…`, `<...>`, a lone `-`,
  and the Vietnamese `chưa rõ`, `chưa có`, `đang cập nhật`, `cập nhật sau`.
- `is_unfilled(body: str) -> bool` — true when the body, after HTML comments
  and fences are stripped, is empty or consists only of placeholder tokens
  and punctuation.
- `GWT_RE` — a Given/When/Then triple, bilingual: `given` / `when` / `then`
  and `giả sử` or `cho trước` / `khi` / `thì`. All three parts, in order.
- `MEASURABLE_RE` — a digit, a comparison operator (`<`, `>`, `<=`, `>=`,
  `=`), or an identifier-shaped token (backticked code, `snake_case`,
  `CamelCase`, a dotted path).
- `owned_open_markers(text) -> list[str]` — `OPEN(...)` markers whose owner
  is real. Owners `TBD`, `?`, `n/a`, `-` and the empty string no longer
  count as owned; `OPEN_RE` keeps matching them, so `_check_owned_unknowns`
  (`ticketlint.py:95-116`) still counts them as unknowns needing a row.
- `ac_substance(item: str) -> str | None` — `None` when the AC carries a GWT
  triple, a measurable token, or an owned `OPEN(...)`; otherwise the reason
  to report.
- `nfr_target_ok(cell: str) -> bool` — the Target column needs a digit or an
  owned `OPEN(...)`.
- `parse_review_row(cells) -> ReviewRow | str` — a parsed row, or the reason
  it is malformed.

`weasel_hits` changes one behaviour: an `OPEN(...)` marker now suppresses
only the banned phrases **inside its own parentheses**, not every phrase on
the line. `"Values are configured OPEN(alice) and appropriate and a subset
and responsive."` reports three hits instead of none. The AC as a whole
still clears the error-level substance bar through its owned marker — the
escape hatch survives where it belongs, at error level, while the prose
around it stays visible at warning level.

### 2. The citation form (HIGH-4)

`BRACKET_CITE_RE` is added to `lintcore.py` next to `INLINE_CITE_RE`:

```
\[ (?:<repo>:)? <doc-id> \s* § \s* <section-id> \]
```

The repo, doc-id and section-id character classes are copied verbatim from
`INLINE_CITE_RE` — including the nested `/`-joined repo segments that
multi-tier federation needs — with two differences the brackets make safe:
whitespace is allowed around `§`, and the section id no longer has to end on
a non-punctuation character, because `]` terminates it. Backticks around a
citation are irrelevant: an inline code span is not a fence, so
`` `[arinc-424 §5.129]` `` matches like any other occurrence.

`INLINE_CITE_RE` keeps its name and its pattern but changes role: it is now
only a **migration detector** and can no longer produce an error.

`check_citation_consistency` (`lintcore.py:361-390`) is rewritten as three
passes over `citation_scan_text(text)`:

1. **Forward** — every `BRACKET_CITE_RE` match that no pinned ref satisfies
   is an **error**, message unchanged in shape.
2. **Reverse** — a pinned ref that nothing cites is a **warning**, as
   before. A *bare* citation matching the ref counts as citing it, so a
   pre-bracket ticket does not collect a second warning for the same place.
3. **Migration** — a bare citation matching a pinned ref is a **warning**:
   `citation 'arinc-424 §5.129' is not bracketed — write
   '[arinc-424 §5.129]'`. A bare token matching no pinned ref produces
   nothing at all. That is the point of the change: `per ARINC 424 §5.129`,
   `(ARINC-424 §5.129)`, `ICAO Annex 3 §4.2.1` and
   `Refer to section §5.129 of arinc-424.` all become invisible instead of
   failing.

`_check_ac_citations` (`ticketlint.py:60-68`) counts bracketed citations
only, staying a warning. An AC written in the old form therefore reports
both "has no citation" and the migration warning — one edit fixes both.

Templates, the 8 wrappers, `review-rubric.md`, `ac-quality.md` and
`QUICKSTART-ba.md` switch their examples to the bracketed form and state the
rule; `ticket-template.md:14` and `:23` and the mission equivalents are the
concrete lines.

### 3. Text scanning (HIGH-2, HIGH-3, L1)

- `check_headings` (`lintcore.py:132-156`) strips `HTML_COMMENT_RE` before
  `FENCE_RE`. `check_recommended_sections` (`lintcore.py:234-261`) strips it
  in its heading-presence pass too — it already strips comments when judging
  emptiness, so the two halves of one check currently disagree.
- `citation_scan_text` (`lintcore.py:346-350`) strips `HTML_COMMENT_RE` as
  well (L1). G6 (the only citation living in a comment) stops satisfying the
  reverse check, and G7 (a BA's own `<!-- TODO check … -->`) stops failing
  the gate.
- `section_body` (`lintcore.py:98-113`) becomes fence-aware through a new
  private helper `_blank_fenced_lines(text) -> str`, which replaces the
  *contents* of every `FENCE_RE` match with empty lines while preserving the
  line count. The terminator scan runs on the blanked copy; the slice is
  taken from the original lines, so callers still receive the real text. An
  unpaired fence leaves `FENCE_RE` unmatched and the helper degrades to
  today's behaviour — the same documented limitation `check_headings`
  already carries. This one fix closes both G3 (a `# comment` inside a bash
  fence truncating `## Acceptance Criteria`) and G4 (a `# ` line in a text
  fence hiding the mermaid fence below it).

### 4. Substance checks and their severities (HIGH-1, MEDIUM-3, M8)

All of the following are new in 0.22.0. Error unless stated.

| Check | Level | Detail |
|---|---|---|
| A required section is unfilled | error | `acquality.is_unfilled` over `REQUIRED_HEADINGS` (`ticket.py:17-27`), one issue per section. `## KB context`, `## Sequence diagram` and `## Business flow` are excluded — each already has a stronger check, and a second error would only duplicate it |
| User Story has three real parts | error | `STORY_RE` (`ticket.py:45`) keeps matching the shape; each captured part must be ≥ 2 words and not a placeholder. `As a x, I want y, so that z` fails |
| At least 2 Acceptance Criteria | error | `_check_ac_present` (`ticketlint.py:41-57`) today requires ≥ 1 |
| Each AC carries substance | error | `acquality.ac_substance`: a GWT triple, a measurable token, or an owned `OPEN(...)` |
| AC ids are unique | error | Two rows labelled `AC1` (T15) |
| NFR Target cells | error | Every data row of `## Non-functional requirements` needs a digit or an owned `OPEN(...)` in Target. The section is RECOMMENDED, so its *absence* stays a warning; a present table with meaningless targets is an error |
| Mermaid fence has at least one edge | error | `check_diagram` (`lintcore.py:159-193`) additionally requires one of `-->`, `->>`, `->`, `--`, `..>` inside the fence. T4 (keyword plus garbage) and an empty fence both fail |
| `## Definition of Ready` has checkbox rows | error | The section is required but never read today. This check replaces `is_unfilled` for that one section, so an empty checklist reports one error, not two |
| Unticked Definition-of-Ready boxes | warning | Naming each unticked item. Cannot be an error: the wrappers forbid the agent from ticking a box itself (`claude-skill-ba-ticket-author.md:171-174`), so the ticket is authored with them unticked by design |
| `## Review record` schema | error | Header with the five expected columns; ≥ 1 data row; all five cells non-empty; both scores integers 1–5; round a positive integer, strictly increasing across rows; `Reviewer` = `gap-verifier` from round 2 |
| Scores ≥ 4, at most 3 rounds | warning | Human judgment, per the 2026-08-12 spec. The cap is deliberately *not* part of the schema error above: a fourth round is a process smell to report, not a malformed row |
| A mission's required sections are unfilled | error | The same `is_unfilled` rule via `missionlint`; M8. No AC rules apply — missions have no `## Acceptance Criteria` |

`check_review_record` (`lintcore.py:271-303`) keeps its three existing
warnings for a missing, empty or placeholder record and gains the schema
errors, which run only when a record is present and past the placeholder.

### 5. A second kb-context block (MEDIUM-1)

`kbcontext.parse` counts `_KEY_RE` matches at any indent before extracting.
More than one raises `KBContextError("two 'kb-context:' blocks found — a
ticket pins exactly one; delete the extra block, and never re-run
`kb context new`")`, matching the remediation wording the tag check already
uses. Verified against the scaffold: `ticket-template.md` and
`mission-template.md` carry exactly one block each, so no shipped template
regresses.

### 6. `--fail-on-stale` (MEDIUM-2, L4)

`kb ticket lint` and `kb mission lint` — missions pin a kb-context block too
— gain `--fail-on-stale`, default off. With the flag, a stale ref is an
error rather than a warning. Exit codes mirror `kb resolve`: **2** when
staleness is the only reason the lint failed, **1** when any other error is
present, **0** on pass. The `--json` envelope is unchanged in shape; a stale
ref simply appears under `errors` instead of `warnings`.

The scaffolded gate passes the flag when `vars.KB_FAIL_ON_STALE` is set, so
a repo that wants amendment safety opts in without editing the workflow.

`QUICKSTART-ba.md:111-129` is corrected: "no stale refs" and the "(and vice
versa)" clause move out of *"DoR rules (what CI enforces)"* into *"what lint
does not enforce"*, with one line saying the reverse direction is a warning
and one line naming the flag.

### 7. Rubric overrides (MEDIUM-5)

`kb init --kind ba` creates `docs/review-rubric.local.md` and
`docs/ac-quality.local.md` from stubs on first init and never touches them
again, reporting them as `(local overrides — never refreshed)` — the exact
mechanism and reporting `conventions.py:121-139` uses for
`docs/conventions/<lang>.local.md`. The base files keep being refreshed, so
a BA repo still receives improved criteria on upgrade. All 8 BA wrappers
gain one line: read the base file, then the `.local.md` sibling if present;
local wins.

### 8. The scaffolded CI gate (MEDIUM-6)

`templates/init/kb-ticket-lint.yml`:

- `pip install center-kb=={version}`, the substitution `kb-code.yml:31` and
  `kb-publish.yml:20` already use. `templates/init/kb-pr-lint.yml:48` has
  the same unpinned install and is fixed in the same pass.
- A `concurrency:` block keyed on the workflow and the PR ref, matching this
  repo's own `ci.yml`.
- Each lint runs with `--json`; the step emits one `::error::` per error and
  writes a per-file summary table to `$GITHUB_STEP_SUMMARY`, keeping the
  existing `::group::` for the full human-readable output. A reviewer sees
  why the check is red without expanding anything.
- The token step stops assuming `https://`: the scheme is split off
  generically and re-attached, so a hub URL on any scheme keeps working.
- `QUICKSTART-ba.md` documents `vars.CENTER_KB_HUB` and
  `secrets.KB_HUB_TOKEN`, and states that a PR from a fork has no secret and
  will fail with a hub-unreachable message — with what to do about it.

### 9. Release

`pyproject.toml` goes from 0.21.0 to **0.22.0**. `CHANGELOG.md` opens with a
Breaking section listing, one line each: the checks promoted to error, the
bracketed citation form and its migration warning, the `## Review record`
schema, the duplicate-kb-context-block error, and the `--fail-on-stale`
flag with its exit code 2. The scaffolded workflows pin the new version, so
the release and the pin land in the same commit.

## Error handling

Every new error message names the section it is about and the edit that
fixes it, in the style the tag check already sets (*"did you mean … ; never
re-run `kb context new`"*). No new traceback paths: `KBContextError` from
the duplicate-block check surfaces through the same handler as every other
kb-context failure. `--fail-on-stale` changes an issue's level, never the
report's shape, so `--json` consumers and the MCP tool see the same four
keys. A malformed `## Review record` reports the first structural problem
per row rather than a cascade.

## Testing

TDD, real filesystem and real git, no mocks — as in the rest of the suite. A
failing test per finding first, grouped by module:

- `tests/test_lintcore.py`: fence-aware `section_body` (G3, G4);
  comment-blind `check_headings` (G2, G5); comment-stripped
  `citation_scan_text` (G6, G7); `BRACKET_CITE_RE` against the bare forms
  F1, F2 and T9c and against the bracketed positives; the migration warning;
  the mermaid-edge requirement.
- `tests/test_acquality.py`: the placeholder deny-list in both languages;
  GWT and measurable-token detection; phrase-scoped `OPEN(...)` muting;
  `OPEN(TBD)` and `OPEN(?)` no longer owned; NFR target cells; review-row
  parsing.
- `tests/test_ticketlint.py`: the severity table end to end, including T1,
  T3, T22, T15, T18 and the G1 capstone, each of which must now fail; the
  Definition-of-Ready checkbox rules; `--fail-on-stale` promoting a stale
  ref and leaving everything else alone.
- `tests/test_missionlint.py`: M8; the mission `--fail-on-stale` path.
- `tests/test_kbcontext.py`: two blocks in either order both error (T14,
  T20); one block still parses.
- `tests/test_cli_ticket.py` and `tests/test_cli_mission.py`: exit 2 for
  stale-only, 1 for mixed, 0 for pass.
- `tests/test_init.py`: the two `.local.md` stubs are created once, survive
  a re-init byte-identical, and are reported as local overrides; the base
  rubric is still refreshed; the scaffolded workflows pin
  `center-kb==<version>` and carry a `concurrency:` block.
- `tests/test_templates.py`: every template, wrapper and doc example uses
  the bracketed citation form; the wrappers carry the `.local.md` rule.

`docs/tickets/TEMPLATE.md` is deliberately left failing the new gate — it is
placeholders by definition, and the scaffolded CI only lints paths under
`tickets/` and `missions/`, so no BA repo trips over it. The passing golden
ticket lives in the test fixtures.

The full suite runs 10–19 minutes, so it runs once at the end of the batch,
not per task.

## Acceptance

- Reviewer E's T1, T3, T22, T15, T18, M8 and the G1 capstone each exit 1.
- G2 reports missing-heading errors; G5 fails; G3, G4, G6 and G7 pass.
- `per ARINC 424 §5.129`, `(ARINC-424 §5.129)` and `arinc-424 § 5.129`
  produce no error; a ticket still using the bare form gets exactly one
  migration warning per citation and keeps its reverse-consistency clean.
- `[arinc-424 §5.126]` with only `§5.129` pinned is still an error.
- T14 and T20 both fail, with the same message, in either block order.
- The golden ticket and the golden mission still pass, unchanged except for
  bracketed citations.
- `kb ticket lint --fail-on-stale` exits 2 after a real upstream amendment
  and republish; without the flag it exits 0 with a warning.
- `kb init --kind ba` twice leaves an edited `docs/review-rubric.local.md`
  byte-identical and still refreshes `docs/review-rubric.md`.
- A freshly scaffolded `kb-ticket-lint.yml` pins `center-kb==<version>`, has
  a `concurrency:` block, and surfaces a failing ticket as an `::error::`
  annotation plus a step-summary row.
- `QUICKSTART-ba.md` describes only what the shipped code enforces.
- The new gate has been run against KrisShop's real BA tickets and the
  result recorded in the PR.
