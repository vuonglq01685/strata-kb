# L3 AI structure fix and hub reader upgrade — design

Date: 2026-10-31
Status: draft, awaiting owner approval
Mockup: https://claude.ai/artifact/SbFbyPMUyTN2X3vjrdYCTz (before/after of one
section, the 7 changes, the layout contract)

Two parts, shipped in this order as separate releases:

- **Part 1 — hub reader upgrade** (`web/mdrender.py`, section page). Small,
  independent, helps every document even with AI off.
- **Part 2 — AI structure fix of L3** (switch, `kb l3 lint`, `kb l3 fix`,
  skill/command for Claude Code, Copilot and Cursor).

## 1. Intent

Since the L3 fidelity check (v1.31.1, spec `2026-10-27-l3-fidelity-check-design.md`)
the owner can *see* what is wrong with an ingested document, but every fix is
manual. Many documents still come out of `kb ingest` with wrong or synthetic
section ids, wrong heading levels, paragraphs cut in the middle, repeated
blocks, PDF page headers/footers inside the text, and they look broken on the
hub.

The owner trusts AI enough now to let it **repair L3 during the ingest
workflow**, under three conditions:

1. It is behind a switch the user turns on and off.
2. It runs only through the AI tools the team already uses in chat
   (Claude Code, GitHub Copilot, Cursor), never through an API key.
3. **The content must not change meaning.** This is the one thing that
   matters most. AI fixes structure; text changes are allowed only to make L3
   match the PDF, and code — not the AI — proves it.

Part of "looks broken" is not L3 at all: the hub renderer does not understand
numbered lists, nested lists, bold/italic or inline code, so correct Markdown
still shows raw `1.`, `**`, `` ` `` (mockup change 6). That is Part 1.

## 2. Goals

Part 1
- Hub renders numbered lists, nested lists (2 levels), `**bold**`, `*italic*`
  / `_italic_` and `` `inline code` `` in L2 and L3 outside tables.
- Section page shows a one-line document header (title, revision, chapter)
  under the section title, from data the page already has.
- Tables still render character for character.

Part 2
- With the switch on, after `kb ingest` (Docker or local) the chat AI repairs
  flagged and lint-failing sections of L3 to the layout contract (§6).
- Every AI change is verified by `kb l3 fix apply` against the PDF and the
  contract before it touches L3; a change that fails is rejected for that
  section and the original stays.
- Every section the AI changed needs a human confirmation before
  summarize/build/publish, exactly like an L3 check finding today.
- Works the same in Claude Code, Copilot Chat and Cursor, because the rules
  live in the `kb` command, not in the prompt.
- Expected effect (estimate, not measured): 70–80 % of flagged problems fixed
  automatically; scanned/bad-font sections and tables still need a human.

## 3. Non-goals

- Fixing root causes in docling, `parser` or `sectioner`.
- A headless runner (`claude -p` / `copilot`) for the fix. The Docker image has
  no AI CLI, and Cursor has no headless runner; the chat AI does the work.
- AI edits to tables, in L2 or L3, ever.
- Moving content between chapter files (cross-file reorder). The AI may
  reorder, split or merge `##` units only inside one `.raw.md` file.
- Showing AI-fix status on the hub.
- Fixing documents already summarized (§7.6).
- Blockquotes, links, headings deeper than `####`, HTML passthrough in the
  renderer.

## 4. Anti-goals (failure even if it "works")

- L3 contains a word that is not in the PDF and no human saw it.
- L3 loses a word the PDF has and no human saw it.
- A table differs by one byte from what ingest wrote.
- The AI clears a flag or confirms a section by itself.
- The switch is off and anything behaves differently from 1.32.0.
- Upgrading blocks KBs ingested before this release.
- An older hub drops a repo because a published file changed shape.

## 5. Constraints (from the code)

- `SectionEntry` / `Manifest` are `extra="forbid"` and parsed cross-install
  off the hub's mirror (`models.py`). No new manifest field. AI-fix records
  go in a **new local file** `_l3fix.yaml`, never in `_manifest.yaml`,
  `index.yaml` or `_l3check.yaml` (an older CI parsing `_l3check.yaml` with a
  new `FindingKind` would fail).
- `pubgate.is_kb_artifact` refuses unknown files on publish, so `_l3fix.yaml`
  stays out of the hub without new code; check it is also kept out of the
  publish "skipped" warning, as was done for `_l3check.yaml`.
- A unit is `## <id> <title>` to the next `## ` line (`mdutils.section_map`);
  folded children are `### <id> …` (`slice_subsection`). Ids may repeat in a
  file (`heading_occurrences`).
- L2 skeleton per section: same heading, `<!-- TODO:summarize <id> -->`, then
  the section's tables verbatim (`tests-gate/fixtures/pending-kb/demo-doc`).
- Confirmations are bound to the section's L3 digest
  (`l3report.digest_slices`); any L3 edit re-blocks the section. Part 2 relies
  on this.
- PDF text: `pdftext.page_texts(pdf)`. Page furniture:
  `parser.furniture_by_page(parser.load_or_parse(pdf, work_dir/<id>))`, which
  reads the docling cache `.kb-work/<id>/parsed-v2.json` (kept by Docker:
  compose mounts `./:/data`) and re-parses if it is missing.
- `Manifest` has no source path, only `source_sha256`; the PDF is passed in
  and its sha is checked.
- `KBConfig` (`config.py`) has the `auto:` switch pattern
  (`AutoConfig.enabled`, `autorun/switch.py`).
- Per-tool commands are shipped by `kb init` from `templates/init/`
  (`claude-command-*.md`, `copilot-*.prompt.md`, `cursor-*.md`,
  `initcmd.py` map).
- `web/uidata.inject_heading_anchors` regex-parses mdrender's attribute-less
  `<hN>` output; inline tags inside headings must keep that working.

## 6. The layout contract (the "template")

Approved in the mockup. One `.raw.md` per chapter (unchanged).

```
## 4.2 NGHỈ PHÉP NĂM          one unit = one hub page; id as numbered in the PDF
### 4.2.1 Thủ tục đăng ký     sub-section
#### 4.2.1.1 …                max 4 levels
### LƯU Ý VỀ PHÉP TỒN         unnumbered sub-heading, text exactly as in the PDF
```

Rules (`kb l3 lint` checks each one per section):

| # | Rule |
|---|---|
| R1 | Unit id is the PDF's own numbering; no fallback id (`x1`, title slug) unless the PDF heading truly has no number (front matter, part roots — same exclusions as the `fallback` finding). |
| R2 | Unit id is not duplicated in the file unless the PDF repeats it. |
| R3 | Heading levels do not skip (`##` → `####`), no empty heading, nothing deeper than `####`. |
| R4 | No two identical prose blocks (after `detect.normalize_words`) in one unit. |
| R5 | No line equal to a page header/footer of the unit's pages. |
| R6 | Only these blocks: paragraph, `-`/`*`/`1.` list (2 levels), table, image, fenced code, `**`/`*`/`_`/`` ` `` inline. |
| R7 | Every code fence closed. |
| R8 | No paragraph that is a `break` finding with no terminal punctuation and a contiguous PDF join (reuses `detect.break_findings`). |

Document metadata (title, revision, chapter) is shown by the hub from the
manifest, **not** written into L3 — L3 would then hold words the PDF does not.

## 7. Approaches

| | Approach | Trade-off |
|---|---|---|
| **A (chosen)** | Chat AI writes proposed sections to a draft folder; `kb l3 fix apply` verifies each against the PDF and the contract, writes passing ones to L3, rejects the rest. Human confirms. | More Python (lint, verifier, apply). Rules hold for every AI tool because code enforces them. |
| B | Skill only: AI edits `.raw.md` directly, following instructions. | Little code, but "content unchanged" rests on the AI obeying; nothing re-checks L3 without a re-ingest. Contradicts the owner's top priority. |
| C | `kb ingest --ai-fix` calls `claude -p` itself. | Docker image has no AI CLI; Cursor has no headless mode. Dropped. |

Owner picked A, and Part 1 before Part 2.

## 8. Part 1 — hub reader upgrade

### 8.1 Renderer (`web/mdrender.py`)

- Ordered list items `^\s*\d+[.)] ` → `<ol>`; bullets keep `^[-*] `.
- Nesting: an item indented ≥ 2 spaces more than its parent opens a nested
  list, max 2 levels; deeper indents stay at level 2. Mixed `ol`/`ul` allowed.
  A continuation line indented under an item joins that item.
- Inline, applied to paragraph, list item and heading text only:
  `` `code` `` first (its content is not further parsed), then `**strong**`,
  then `*em*` / `_em_`. Delimiters must hug non-space text (`a * b` stays
  literal; `snake_case_word` stays literal). Unmatched delimiters stay literal.
- Text is escaped before inline tags are added; no raw HTML ever passes.
- Keyword highlighting (`<mark>`) still works inside formatted text and never
  splits a tag.
- **Table cells are not inline-parsed.** They stay exactly as today.
- Headings may contain inline tags; `inject_heading_anchors` must still build
  the TOC label from the text (it already strips tags via `_TAG_STRIP_RE` —
  keep a test).

### 8.2 Section page

Under the `<h1>` of `section.html`, one muted line: document title ·
revision · chapter (the unit's `file` stem mapped to its chapter label).
Builder decides where the doc title comes from (manifest is already loaded for
`prev_next`). No page number: `SectionEntry` has no page field and adding one
is a wire break. CSS for `ol`, nested lists, `strong`, `em`, inline `code` in
`style.css`, in both themes and the mobile breakpoints.

### 8.3 Tests and release

- `tests/test_web_mdrender.py`: each new construct, the literal cases
  (`a * b`, `snake_case`, unmatched `**`), escaping, highlight inside
  `<strong>`, table cells with `**x**` unchanged, nested and mixed lists.
- `tests/test_web_ui.py`: doc header line present.
- `scripts/mobile_ui_check.cjs` desktop baselines will change where demo data
  uses these constructs; regenerate and say so in the PR.
- CHANGELOG, hub-only upgrade. Version: next minor (1.33.0) — builder's call.

## 9. Part 2 — AI structure fix

### 9.1 Switch

`.kb/config.yaml`:

```yaml
l3_fix:
  enabled: false   # default; off = exactly 1.32.0 behaviour
```

`KBConfig.l3_fix: L3FixConfig` (`enabled: bool = False`). Toggle with
`kb l3 fix on|off` (same pattern as `autorun/switch.py`). `kb l3 fix apply`
refuses with a clear message while the switch is off. The skill reads the
switch before doing anything.

### 9.2 Flow

```
kb ingest (container)  ->  .raw.md + _manifest.yaml + _l3check.yaml
        |
switch on? -- no --> today's flow (kb l3 report, human confirm, summarize)
        | yes
chat AI:  kb l3 lint <id> --pdf <pdf>        which sections break the contract
          kb l3 report <id>                   l3check findings + evidence
          kb l3 fix pages <id> --page N       page image, only when needed (§9.5)
          write .kb-work/<id>/l3fix/<section>.md   proposed slice per unit
          kb l3 fix apply <id> --pdf <pdf>    verify + write L3 or reject
        |
human:    kb l3 report <id> (now lists AI changes) + git diff of .raw.md
          kb l3 confirm <id> --section ...
        |
kb summarize -> kb build -> kb publish   (unchanged)
```

Drafts live under `.kb-work/` (git-ignored scratch), not `.kb/`.

### 9.3 `kb l3 lint <doc-id> --pdf <pdf>`

Read-only. Runs R1–R8 per unit, prints `section · rule · line · evidence`,
exit 1 on any problem. Available with the switch off too (a reviewer may use
it); it never gates anything by itself, so old KBs are not blocked.

### 9.4 `kb l3 fix apply <doc-id> --pdf <pdf> [--section <id> ...]`

Checks `sha256(pdf) == manifest.source_sha256`, then for each draft file
(one draft = one current unit, named by the unit's current id; the draft may
contain one or more `##` units, which is how split/merge/re-id is expressed):

1. **Tables**: the multiset of table blocks in the draft equals the original
   unit's, byte for byte, and in the same order. Else reject.
2. **Contract**: the draft passes R1–R8. Else reject.
3. **Content vs PDF**, using `detect` over the unit's page span with
   furniture removed:
   - no new uncovered L3 run: every `content` "extra" run in the draft was
     already an extra run in the original (the AI added no word that is not in
     the PDF);
   - missing runs did not grow: no PDF run that the original covered is
     missing in the draft;
   - every word sequence removed from the original is one of: an exact
     duplicate of a block that stays (R4), a furniture line (R5), or an
     "extra" run of the original.
   Else reject.
4. **Ids**: new unit ids do not clash with other units in the doc (same check
   as `scaffold._check_no_id_clash`).
5. **Section status**: every touched unit is `pending` (§7.6). Else reject.

A passing draft is written atomically: the unit's slice in `.raw.md` is
replaced; the file's manifest rows are rebuilt in file order (id, title,
`tokens.l3` recounted, everything else of untouched rows kept); the L2
skeleton of the touched units is regenerated (heading, TODO marker, tables);
`_l3check.yaml` entries of renamed units move to the new id. Each run prints
per section: `applied` / `rejected: <rule or check> <evidence>`, exit 1 if
any was rejected. The draft of an applied section is deleted; a rejected one
is kept for the AI to retry.

Builder decides how the content check reuses `detect` internals
(`_content_runs`, `_stream`) and the exact matching of removed runs; tune on
the fixture PDFs so that a pure re-id / heading-level / paragraph-join draft
always passes and an inserted sentence always fails.

### 9.5 Pages without a usable text layer

When a unit has an `unverifiable` finding, or its `content` findings cover a
large share of its words (threshold is the builder's, e.g. > 30 %), the PDF
text cannot be the reference. Owner decision: **the AI reads the page and
fixes it anyway; a human reviews after.**

- `kb l3 fix pages <doc-id> --pdf <pdf> --page N [--page M]` renders the page
  to `.kb-work/<id>/pages/p<N>.png` (reuse `parser._render_page`). Chat tools
  can read workspace images.
- The draft is applied with `--from-image <section-id>`; apply then skips
  check 3 for that section only, still runs checks 1, 2, 4, 5, and records
  the change as `verified: false`.
- `--from-image` is refused for a section that does not meet the condition
  above, so it cannot be used to bypass check 3 on a normal page.
- Tables are never fixed from an image either.

### 9.6 `_l3fix.yaml` and the gate

`.kb/<doc-id>/_l3fix.yaml`, committed, never published:

```yaml
sections:
  - id: "4.2"             # id after the fix
    was: "x1"             # id before, if renamed
    l3_sha256: <digest after the fix>
    verified: true        # false = applied with --from-image
    by: <AI tool name as given by --assistant, e.g. claude-code|copilot|cursor>
    at: <ts>
    changes: [re-id, heading-level, join, dedupe, furniture, text-to-pdf]
    confirmed: null       # or {by, at, l3_sha256}
```

- `blocked_docs` also blocks a doc with any `_l3fix.yaml` section whose
  `confirmed.l3_sha256` differs from its current digest. Same effect on
  summarize/build/publish/ci-publish as the L3 check.
- `kb l3 report` lists AI-fixed sections first, `verified: false` ones on top
  and marked, with the `changes` list and the hint
  `git diff -- .kb/<id>/<file>.raw.md`.
- `kb l3 confirm` confirms both the `_l3check.yaml` and `_l3fix.yaml` entry of
  that section in one go.
- A doc with no `_l3fix.yaml` behaves as today.
- CI pin note: a CI on ≤ 1.32 ignores `_l3fix.yaml` (no gate); bump the pin
  (CHANGELOG/QUICKSTART, like 1.31.1).

### 9.7 Skill / command for the three tools

New `kb-l3-fix` command shipped by `kb init` for all three tools
(`templates/init/claude-command-kb-l3-fix.md`, `copilot-kb-l3-fix.prompt.md`,
`cursor-kb-l3-fix.md`, plus this repo's `.claude/skills/kb-l3-fix/SKILL.md`),
and `kb-ingest` step 4 changed: when `l3_fix.enabled`, run the kb-l3-fix flow
before showing the report; when off, unchanged. Key instructions:

- Fix only structure, and text only to match the PDF. Never add, reword or
  "clean up" text. Never touch a table.
- One draft per unit, full slice, starting at its `##` heading.
- Run `apply`; on rejection read the reason, retry at most twice per section,
  then leave it for the human.
- Use page images only for sections `apply` would accept with `--from-image`.
- Never run `kb l3 confirm`. Report applied / rejected / left-for-human.
- Docker: prefix commands with `docker compose run --rm hub`.

### 9.8 Tests and release

- Unit tests for each lint rule, each apply check (accept and reject cases),
  `--from-image` refusal, id rename keeping `_l3check.yaml` entries, manifest
  and L2 skeleton rebuild, gate via `_l3fix.yaml`, switch on/off, sha mismatch.
- A fixture PDF + broken L3 with the mockup's 7 defects: the corrected draft
  applies; drafts with one inserted word, one dropped sentence, one table cell
  changed are each rejected.
- `kb init` template map test includes the new files.
- README §14, guides (EN/VI) sources, CHANGELOG. Version: next minor after
  Part 1 — builder's call.

## 10. Decided by the owner

- AI fixes structure; text only to match the PDF; meaning must not change.
- Bad text layer: AI reads the page and fixes; human reviews after.
- Runs from the chat AI after the container ingest, not via API.
- Switch on/off. Layout contract as in the mockup.
- Approach A; Part 1 before Part 2.

## 11. My calls (owner to check)

- Switch default **off**; `kb l3 fix apply` refuses while off.
- Records in a new `_l3fix.yaml`, not in `_l3check.yaml` (old-CI parse safety).
- Drafts under `.kb-work/`, not `.kb/`.
- No cross-file moves; split/merge/reorder only inside one chapter file.
- Only `pending` sections may be fixed.
- Doc header on the hub without page number (wire-compat).
- `kb l3 lint` is advisory, never a gate on its own.
- AI retries a rejected section at most twice.

## 12. Left to the builder

Thresholds, exact regexes, module layout (suggest `l3check/lint.py`,
`l3check/fix.py`), how apply reuses `detect` internals, CLI help text,
version numbers, where the hub reads the doc title.
