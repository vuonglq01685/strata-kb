# Phase 5 Stage B — handover notes for Stages C and D

Stage B is complete: `feat/phase-5-code-ingest`, final whole-branch review fix
pass on top of `c53acb7`, version 0.17.0. Full suite green: 1567 passed /
5 skipped / 1 pre-existing warning (up from the 1547/5/1 baseline; this fix
pass added 20 new `def test_*` functions — see the fix pass's own report
for the per-finding breakdown).

This file exists for the same reason Stage A's did: things learned while
executing Stage B — and while fixing its final whole-branch review — are
obligations on the *later* stages, and neither sibling plan currently
discharges them. They are not defects in what shipped — they are debts the
next plan pays. Most of them live only in `.superpowers/sdd/` today, which
is gitignored and disappears with this worktree; this file is the only
place they survive.

## 1. Service ids over 40 characters carry an opaque `-<sha6>` suffix, unconditionally

`services.py`'s `_assign_slugs()` caps a service's id slug at `_ID_CAP = 40`
characters (matching `mdutils.slugify_id`'s own truncation length). Any
service whose full normalized name exceeds that cap gets a `-<sha6>` suffix
— six hex characters from `_stable_suffix()`, a SHA-256 of the record's own
full normalized name — appended **unconditionally**, not only when a real
collision is detected among that run's siblings. This is deliberate
(Ruling R30 part 3: the suffix must depend only on the record's own name,
never on sibling order or an index, so a service's id never shifts just
because an unrelated sibling was added or removed), but it means:

- A container named e.g. `airspace-flight-plan-validation-orchestrator`
  (46 characters after normalization) gets an id like
  `airspace-flight-plan-validation-orches-a1b2c3` — not the truncated name
  alone, and not stable-looking to a human skimming the document; the
  suffix is a hash, not a version or a counter.
- **`svc.<name>` is the public join key** (`services.py`'s own module
  docstring: "Stage C's curated `-svc` document reuses these ids and
  `kb svc note` validates ticket ↔ service history against them"). Stage C
  must be told about this suffix **before** it builds `kb svc note` or any
  other tooling that parses, displays, or lets a human type a `svc.*` id by
  hand — a hand-typed id that drops or mistypes the suffix will silently
  fail to match, and a UI that truncates a long id for display must not
  truncate the suffix itself, since that is the only stable part of the id
  for the truncated-name case.
- The suffix is present for *this* run's set of names deterministically —
  running `kb code-ingest` again on an unchanged repo reproduces the exact
  same suffix — but it is opaque: nothing in the rendered document explains
  what the six hex characters mean or how to reconstruct them by hand.
  Stage C's `-svc` seed prompt and any human-facing documentation of
  `svc.*` ids should say plainly "this may carry a hash suffix; copy it,
  don't retype it."

This is, in the reviewer's own words, "the single most important item" in
this handover.

## 2. The `tables:` line in the `-svc` scaffold is inert on realistic repos

`core.py`'s `_service_evidence()` computes a service's `tables:` L3 evidence
line by taking the service name's tokens (`_name_tokens(sec.title)`) and
keeping every `db.<table>` id whose *own* name tokens are a **superset** of
the service's. On the shipped fixture this never fires: `airspace-service`
tokenizes to `{airspace, service}`, but the fixture's only table,
`db.restrictive_airspace`, tokenizes to `{restrictive, airspace}` — missing
`service` — so the subset test fails and every service in the shipped
document renders `tables:\n  - none`, even though the service and the
table are obviously related to a human reading both.

The rule only fires when a service is literally named after (a superset
containing) a table's own name tokens, which is not how most repos name
their containers — a service is usually named after what it *does*
(`airspace-service`, `notification-worker`), while a table is named after
what it *stores* (`restrictive_airspace`, `notifications`). A human curator
reading the scaffold's `-svc` L2 will see `tables:\n  - none` and may read
that as "this service touches no tables" — a factual-sounding claim the
extractor cannot actually back up; it only means "no table name happened to
be a superset match."

Stage C should decide, before building on this line, whether to (a) drop
it, (b) relabel it honestly as a name-match heuristic rather than a
structural finding, or (c) replace it with a real signal (e.g. connection
strings / ORM model references, which this stage deliberately did not
attempt). Left as-is, a Dev curator amending the `-svc` document by hand
has no reason to distrust a line that looks like ground truth but rarely
is.

## 3. The `Technology` column renders `none` on every service in the shipped fixture

`services.py`'s technology labelling (`_technology_for` and friends) runs
`detect_frameworks()` over a service's own code directory when it can find
one, else over its image name. On the shipped `build_code_repo()` fixture,
both `svc.airspace-service` and `svc.postgres` render `Technology | none`
in `services.md` — verified directly against a fresh ingest of the fixture
in this fix pass. The `build:`-context enhancement (reading a compose
service's `build:` block to find its own Dockerfile/source directory and
detect frameworks from *that*, rather than only from a directory guessed
from the service's own name — falling back to the image's base name when
that guess misses, per `_technology_for` in `services.py`) was deferred,
per the stage's own plan. Stage C/D should not assume `Technology` is
populated for services built from source; a curator amending `-svc` by
hand may need to fill this in manually until that enhancement lands.

## 4. The `-svc` L3 evidence is a file list only — no file contents, by deliberate security ruling

Controller Ruling R42 removed an earlier version of `_service_evidence()`
that opened each matched file and embedded its first few lines as
"evidence" — a file's content can carry a secret (a DSN in a header
comment, a password on an `.env`-shaped file's first line) regardless of
how comment-shaped the surrounding text looks, and `.kb/` is published to
the federation hub in full. The evidence a `-svc` scaffold section gets is
now **only**:

- The service extractor's own already-sanitised `l3_md` (image, ports,
  depends-on, env **keys**, source file) — spec §3.11-compliant by
  construction.
- A bare, sorted list of file **paths** whose name tokens are a superset of
  the service's own (never a byte of file content).
- A bare list of `db.<table>` ids by the same name-token rule (see §2
  above, and its limits).

Stage C's seed prompt for `/dev-code-seed` (writing the actual human-facing
`description`/`Rel(...)` prose for a `-svc` section) has meaningfully
**less to work with than the original plan imagined** if it assumed any
file content would be available as grounding. The seed step will need to
either (a) accept writing from file *paths* and the extractor's own
structured fields alone, or (b) have the seeding agent read the actual
repo checkout directly (which it can — `dev-code-seed` runs with the repo
present locally, unlike this extractor, which by design never opens a file
beyond what `.kb/` is allowed to publish).

## 5. Trip-wire counts a later stage will hit

In the style of Stage A's handover §3 — these are deliberate, not
oversights, but they *will* need a conscious bump:

- `tests/test_init.py::test_init_kind_dev_scaffolds_exactly_the_stage_a_set`
  — `assert len(expected_files("dev")) == 27` (Stage A shipped at 26; this
  stage's `kb-code.yml` row raised it to 27, and this fix pass added no new
  scaffolded file). Stage C's `dev-code-seed` skill plus its Claude-command
  / Copilot-prompt / Cursor-command wrappers will raise it again — likely
  by four, matching the four-file-per-skill pattern the existing five
  `dev-*` skills already use.
- `tests/test_templates.py` — `assert len(names) == 20, names` in the
  shared-block canon test (`SHARED_BLOCK_TEXT`/`DEV_WORKFLOW_SKILLS`
  section). Still 20 as of this fix pass — Stage B added no sixth wrapped
  skill. A `dev-code-seed` skill landed with the same four-wrapper,
  three-shared-block pattern as the existing five will make it 24; per
  Stage A's own note, do not "fix" the test by regenerating canon from a
  wrapper — the canon and the 20 (soon 24) wrappers are a deliberate
  two-place edit.
- New in this fix pass: `tests/test_codeingest_core.py`'s
  `test_full_extractor_set_on_the_fixture_repo_builds_clean` now also
  asserts `report.sections_by_extractor[name] > 0` for all seven
  extractors, not just that they appear in `report.detected` (closing a
  test gap the review found: the old assertion would stay green even if
  one extractor silently produced zero sections). Any future extractor
  Stage C/D adds to `ALL_EXTRACTORS` that fires on the shared fixture must
  actually contribute a section, or this test fails — which is the point,
  but worth knowing before debugging an unrelated-looking failure.

## 6. Two new shared modules exist — reuse them, don't re-copy the pattern

This fix pass closed two "N independent copies of the same half-implemented
rule" defects the same way `_envkeys.py` already closed one in Stage A/B:

- `center_kb.codeingest.extractors._envkeys.redact_userinfo(text)` —
  rewrites `scheme://user:pass@` (or bare `scheme://token@`) to
  `scheme://***@` wherever it appears. Used by `deps.py` (`_fmt_dep` and
  its L2 section renderer), `commands.py` (`_render_section`), and
  `api.py` (`_extract_servers`) to mask a credential a Dev already
  committed to source in plaintext (a PEP 508 direct-URL dependency, an
  npm `git+https://token@...` dependency, an OpenAPI `servers[*].url`, or
  a shell command that happens to embed one) before it reaches a document
  `.kb/`'s `_snapshot` republishes to the federation hub.
- `center_kb.codeingest.extractors._mdcells.escape_cell(text)` — replaces
  all six byte-identical `_escape_pipe(text) -> text.replace("|", "\\|")`
  copies that used to live in `api.py`, `commands.py`, `deps.py`,
  `integrations.py`, `schema.py`, and `services.py`. It also collapses
  embedded whitespace (including a newline) before escaping the pipe — the
  old copies only ever handled half the rule; an embedded newline in a
  YAML literal-block value or a multi-line npm script body broke an L2
  table just as surely as an unescaped `|`.

**Any new extractor Stage C or D adds that renders a Markdown table cell,
or that might echo a URL a Dev committed to source, must import from these
two modules rather than writing a seventh/fourth copy.** This exact class
of defect (a security or correctness rule duplicated across modules until
one copy drifts) has now recurred at least three times across Stages A-B
(`_envkeys.sanitize_env_key`'s two-round fix, then this fix pass's two
findings) — it is worth treating as a standing rule for this codebase, not
a one-off cleanup.

## 7. `schema.py`'s CREATE TABLE parser was rewritten under review — know the new shape

The Critical finding on this branch (`CREATE_RE`'s body scan running to the
first literal `");"` anywhere in the rest of the *file*, not the table's
own closing paren) is fixed by locating the table's real closing paren via
paren-depth counting on a quote-masked copy of the text
(`_mask_quoted_spans`), then finding the statement's terminating `;`
wherever it actually falls — so a MySQL `) ENGINE=...;`, a SQLite
`) WITHOUT ROWID;`, a Postgres `) PARTITION BY RANGE (id);`, and a final
`CREATE TABLE` with no trailing `;` at all now all parse correctly instead
of one of: silently dropping the table, smearing its tail into the next
table's columns, or deleting the next table outright.

Two things Stage C/D should know before touching this module again:

- There is a **new warning shape**: if a file's (comment-stripped) text
  contains more `CREATE\s+TABLE` occurrences than the reader actually
  recognised — a name shape outside `[A-Za-z_][\w.]*`, most plausibly — it
  now warns `"found {N} CREATE TABLE statement(s) in {file} but recognised
  only {M} — the rest were skipped, not guessed at"`. Anything that parses
  or displays this module's `warnings` list (there is nothing today, but a
  future Stage C/D tool might) should expect this new message.
- The quote-masking fix (`_mask_quoted_spans`) is not fully general: it
  falls back to the *unmasked* text (plain, non-quote-aware paren counting)
  when `_resolve_scan` can't produce a trustworthy reading at all (both
  backslash-escaping readings desync) — an already-rare, already-warned-
  about case. That fallback happens to still work correctly for every
  case this stage's fixtures exercise (paren counts across the whole
  intended span stay balanced), but it is not a proof it always will for
  an arbitrarily pathological file. Out of scope for this fix pass; worth
  a note if `schema.py` is revisited.

## 8. `kb-code.yml` gained hardening this fix pass — preserve it on any future edit

The shipped CI template now has a `concurrency: {group: kb-code-${{
github.ref }}, cancel-in-progress: false}` block (two quick merges must not
race two `kb ci-publish` runs each opening their own hub PR), a
`permissions: {contents: read}` block on the `validate` job (it previously
inherited the repo's default token scope), no `fetch-depth: 0` on the
publish job's checkout (it was unnecessary — `code-ingest` only ever runs
`rev-parse HEAD` and `show -s --format=%cs HEAD`, both satisfied by a
shallow checkout — and its own comment stated a false reason for it), and
a `tests/test_templates.py::test_kb_code_trigger_list_is_pinned` test
pinning the exact `on:` trigger set (so a later `pull_request_target`
addition — which would make the publish job's `if:
github.event_name != 'pull_request'` true for a PR-controlled ref while
`id-token: write` is set — fails a test instead of shipping quietly). Any
Stage C/D task that regenerates or hand-edits this template must keep all
four; `kb init --kind dev` overwrites the file on every re-run from the
template, so a manually-added `--db` flag (already called out in the
template's own comment) is the only thing a re-run can lose today, but a
future task adding a fifth workflow feature to this file should check this
handover and the pinning test before assuming the shape is up for grabs.

## 9. `QUICKSTART-DEV.md` now documents the auto-merge policy — the plan's location was wrong

Spec §11 says the auto-merge-of-`-code`-hub-PRs policy is "documented in
QUICKSTART-DEV, not tool behaviour"; the Stage B plan's own wording (Task
B10, Step 3) never said where, and the README that shipped pointed at
"documented per-hub in that hub's own setup" — a location that does not
exist anywhere in this codebase (`grep -rn "auto-merg"
src/center_kb/templates/` was empty before this fix pass). This is a plan
defect, not an implementation one: spec outranks plan, and the spec's
instruction was simply never carried into an actual file. Fixed in this
pass by adding the paragraph to `QUICKSTART-dev.md` (Setup step 3) and
re-pointing the README at it. If Stage C or D ever revisits per-hub
publishing setup documentation, this paragraph is the canonical location —
don't duplicate it into a third place.

## 10. Minor findings carried, not fixed

Triaged as safe to carry by the whole-branch review and its final re-review
(see each review's own "Out of scope — do not fix" list for the full,
authoritative set). Recorded here only so the Stage-C/D-relevant ones are
not rediscovered as new:

- `os.walk`'s `onerror=None` silently drops an unreadable subtree from
  every extractor's tree walk — no warning, no diagnostic. A repo with a
  permission-denied directory partway down its tree will simply have that
  subtree invisible to `kb code-ingest`, with nothing in the output saying
  so.
- The `-svc` document's merged-tag sections (when two OpenAPI tags collapse
  to the same `_safe_tag_id`, per `api.py`'s own Ruling on tag-id
  collisions) are invisible in the *published* document in the sense that
  nothing marks which raw tag spellings contributed — a Dev reading only
  the hub copy cannot tell a merge happened without also reading
  `result.warnings` at ingest time, which is not itself published anywhere.
- The "found {N} CREATE TABLE statement(s) … recognised only {M}" warning
  (`schema.py:690`) counts `CREATE\s+TABLE` occurrences on `text` —
  comment-stripped but **not** quote-masked — so a `CREATE TABLE` sitting
  inside a string literal inflates the count:
  `INSERT INTO audit(msg) VALUES ('CREATE TABLE');` alone is enough to emit
  `found 2 CREATE TABLE statement(s) … recognised only 1`, even though
  nothing was actually skipped. Over-warning only, no wrong data — comments
  are stripped first, so `-- was: CREATE TABLE legacy …` correctly does not
  warn. One-line fix: count on `masked` (already computed two lines above)
  instead of `text`.
- `CREATE TEMPORARY TABLE` — and the `UNLOGGED`/`GLOBAL` variants — matches
  neither `CREATE_RE` nor the counting regex at `schema.py:690`, so it is
  dropped with **no warning at all**: the "a skipped statement is never
  silent" guarantee README.md:667-670 states has this gap unqualified. A
  future stage should either widen both regexes to recognise the modifier
  keyword or narrow the README sentence to say so.
- `_matching_close_paren` (`schema.py:838`) returns `len(text) - 1`, with
  no warning, when a paren it's tracking never closes before end-of-file —
  so malformed SQL with an unclosed paren ahead of the next `CREATE TABLE`
  can still fabricate a smeared column silently. Strictly better than the
  pre-fix behaviour, which also deleted the following table outright — but
  the fabrication class isn't fully closed for malformed input. The same
  regex-over-unmasked-text mechanism means a `CREATE_RE` match sitting
  inside a string literal (`VALUES ('CREATE TABLE ghost (x INT)')`) still
  yields a ghost table; that is pre-existing and equally wrong before and
  after this fix pass.
- `redact_userinfo` (`_envkeys.py`, §6 above) rewrites only URL userinfo —
  `scheme://user:pass@` → `scheme://***@` — which was the mandated scope.
  A credential passed as a **command flag or query string**
  (`pytest --token=SECRET`, `https://host/?token=SECRET`) is still
  republished verbatim into `.kb/` and therefore to the federation hub;
  worth a decision in a later stage. It also over-redacts in the other
  direction: `git+ssh://git@github.com/...` becomes `git+ssh://***@…`,
  masking the conventional non-secret `git` username — cosmetic, not a
  security gap.
