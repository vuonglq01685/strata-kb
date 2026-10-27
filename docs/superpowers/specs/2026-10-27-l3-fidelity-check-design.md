# L3 fidelity check with reviewer gate — design (v1.31.1)

Date: 2026-10-27
Status: draft, awaiting owner approval (builder check done)

## 1. Intent

L3 (`<stem>.raw.md`) is the complete-content layer: it must say what the
source PDF says, in the PDF's order. Owners publishing to the hub see four
recurring defects after `kb ingest`:

1. Sections come out in the wrong order.
2. A heading is not recognised and the section gets a synthetic fallback id
   (`x1`, a title slug).
3. Paragraphs are broken in the middle for no reason.
4. Text differs from the PDF: missing, extra or garbled.

Today the sectioner already *knows* some of this (`SectioningNotes`:
fallbacks, page inversions) but only prints warnings that scroll away, and
nothing compares L3 to the PDF. Wrong L3 then flows into L2/L1/L0 and onto
the hub.

The owner wants every ingest to be checked against the original, every
suspect section flagged, and a **human reviewer to confirm before the
pipeline continues**. The check reports and flags. It never rewrites L3.

Probable causes, for context (fixing them is not this release's goal):
- `_reorder_inverted_pages` only repairs *numbered sibling* headings that
  descend on *one* page; unnumbered or cross-page inversions pass silently.
- docling splits one paragraph into several text items (column or page
  break); each item becomes its own L3 paragraph, so `_clean` never sees the
  join.

## 2. Goals

- After `kb ingest`, every section of the document is checked
  deterministically against the PDF's own text layer for the four defects
  above, and each finding is written to a per-document report file.
- The "broken paragraph" findings, the only ones that need judgement, get a
  short verdict from an LLM agent (Sonnet) to speed up the human review.
- A document with any unconfirmed finding cannot be summarized, built or
  published until a reviewer confirms each flagged section.
- The ingest output ends with a clear summary: N sections flagged, by
  kind, and the command to review them.
- `kb summarize` and the rest of the LLM config default to model alias
  `sonnet` (resolves to the newest Sonnet) instead of `sonnet-5`.
- Ship as v1.31.1.

## 3. Non-goals

- Fixing the root causes in docling, `parser` or `sectioner`.
- Any automatic edit of L3 (by the check, the agent or the confirm command).
- Showing findings in the hub web UI.
- OCR for scanned PDFs.
- Re-running the check without re-ingesting (docling's JSON cache under the
  work dir already makes a re-ingest cheap).

## 4. Anti-goals (failure even if it "works")

- The agent alters, paraphrases or "cleans up" L3 text.
- The agent's verdict clears a flag or confirms a section by itself.
- So many false positives that reviewers confirm everything blind. Every
  finding must carry the evidence (page, L3 snippet, PDF snippet) needed to
  decide in seconds.
- Upgrading to 1.31.1 blocks existing KBs that were ingested before the
  check existed.
- A hub running an older strata-kb drops a repo because a published file
  changed shape.

## 5. Constraints

- `SectionEntry` and `Manifest` are `extra="forbid"` and are parsed
  cross-install off the hub's mirrored trees (`models.py` comments). A new
  field there is a wire-compat break. **Findings live in a separate file**,
  never in `_manifest.yaml` or `index.yaml`.
- Ingest runs locally in the child repo (docling, `ingestcmd._run_ingest`);
  the hub only receives published KBs via `intake.py`.
- Runner calls go through `llm.Runner` (`claude -p` or `copilot`), prompt on
  stdin, as `summarize` does. No runner available is a normal case.
- `pypdfium2` is already a dependency (`ingest/pdftext.py`).

## 6. Approaches considered

| | Approach | Trade-off |
|---|---|---|
| A | Deterministic check inside `kb ingest` + reviewer gate | No tokens, same input gives same findings; strong on missing/garbled text and fallbacks, good on order, weak on "is this break wrong" (false positives on lists, labels, heading-like lines). |
| **B (chosen)** | **A + Sonnet agent that gives a verdict on broken-paragraph findings only** | Adds tokens and run-to-run variance, but only on the one finding kind that needs meaning; the human still decides. |
| C | Separate `kb l3-check` command, same gate | Easy to forget to run; the gate then only says "not checked". Rejected. |

Reference text for the comparison: **PDF text layer via pypdfium2**, not
docling's JSON. L3 is produced from docling's JSON, so comparing with it is
blind to docling's own errors (split paragraphs, reading order, glyphs) —
which are most of the defects. docling's JSON is used only for what it is
good at: page numbers and which page-furniture text to ignore.

## 7. Design

### 7.1 Where it runs

At the end of `ingestcmd._run_ingest`, after `scaffold_doc` wrote L3. The
check reads L3 **as written** (the `.raw.md` files), so losses in sectioner
or scaffold are caught too, not only docling's. Inputs it needs that only
exist during ingest (items with pages, `SectioningNotes`, the docling doc)
are passed in directly.

On `--sections` re-ingest, only the re-ingested chapters are re-checked;
other chapters' findings and confirmations are kept.

### 7.2 Finding kinds

Each finding has: `kind`, `section` id, `page` (or range), `evidence`
(short L3 snippet and/or PDF snippet, capped), and for `break` an optional
`agent` verdict.

| kind | Detection |
|---|---|
| `fallback` | Taken from `SectioningNotes.fallbacks`, **excluding** fallbacks inside front matter and bookmark-part roots (FOREWORD, Introduction, Glossary, part titles are unnumbered on purpose). Evidence: the raw heading text. |
| `order` | Section start pages must not decrease in L3 order; additionally each section heading is located in the PDF text layer and the (page, offset) sequence must increase. Inversions already recorded in `SectioningNotes.inversions` with `reordered=False` are included. Evidence: the two section ids and their PDF positions. |
| `content` | Per section, compare L3 words against the PDF text of the section's page span (start page to the next section's start page; boundary pages shared with the neighbour). Normalise both sides: NFKC, casefold, collapse whitespace, re-join end-of-line hyphenation, strip Markdown syntax (table pipes, image links, fences, emphasis). Ignore page-furniture text docling labelled `page_header` / `page_footer` (taken from the docling doc). Flag runs of ≥ 5 consecutive PDF words absent from L3 (**missing**) and runs of ≥ 5 L3 words absent from the PDF span (**extra/garbled**). Evidence: the run, its page. |
| `break` | Inside one section, two consecutive L3 paragraphs where the first does not end in terminal punctuation, and the tail of the first plus the head of the second appear contiguous (whitespace/newline only between them) in the PDF text. Evidence: both snippets and the PDF join. |
| `unverifiable` | Every page of the section has no text layer (scanned). One finding per such section, so the reviewer knows it was not checked. |

Every finding is attached to the **enclosing manifest unit**: a fallback or
heading folded into its parent unit (`### x1 …`) reports under the parent's
id, so `kb l3 confirm --section` and `l3_sha256` always have a real unit.

Thresholds (run length, snippet caps) are constants in the module; the
builder tunes them on the test PDFs so a clean document yields zero
findings.

### 7.3 The agent (break findings only)

- Runs after the deterministic pass, only on `break` findings, only when
  `llm.detect_runner` finds a runner and `--no-llm-review` was not passed
  to `kb ingest`.
- One call per finding, parallel with the configured `max_workers`, using
  the same `LLMConfig` (model `sonnet` by default).
- Input: the two L3 paragraphs and the PDF text window around the join.
  Output, strict JSON: `{"verdict": "spurious" | "intentional" | "unsure",
  "reason": "<≤ 30 words>"}`. Anything else is stored as `unsure` with the
  runner error as reason; an agent failure never fails the ingest.
- The verdict is attached to the finding. It does not remove or confirm it.
- The prompt says explicitly: judge only, do not rewrite.

### 7.4 Report file

`.kb/<doc-id>/_l3check.yaml`, one per document, written by ingest:

```yaml
checked_at: 2026-10-27T10:00:00Z
source_sha256: <sha of the PDF checked>
sections:
  - id: "5.2"
    l3_sha256: <sha of the section's L3 at check time>
    findings:
      - kind: break
        page: 41
        evidence: {l3: "...the aircraft shall", next: "remain clear of...", pdf: "...the aircraft shall remain clear of..."}
        agent: {verdict: spurious, reason: "sentence continues across a column break"}
    confirmed: null            # or {by: <git user.name>, at: <ts>, l3_sha256: <sha>}
```

Only sections with findings appear. The file is **committed** in the child
repo (owner decision), so teammates see each other's confirmations and the
`kb ci-publish` gate works in CI. It is **not sent to the hub**: `pubgate.is_kb_artifact` already refuses
it on the child side and in the hub's intake (correction after the builder
check: there *is* an allowlist). 1.31.1 only keeps it out of the publish
"skipped" warning.

Upgrade note (CHANGELOG + QUICKSTART): bump the CI pin to
`strata-kb==1.31.1`. A CI still on 1.31.0 simply has no gate; `kb doctor`
already warns on pin drift.

### 7.5 Reviewer commands

- `kb l3 report [<doc-id>]` — list unconfirmed findings per section with
  evidence and agent verdict; exit 1 when any are unconfirmed.
- `kb l3 confirm <doc-id> --section <id> [--section <id> ...] | --all` —
  record `{by, at, l3_sha256}` for those sections. `--all` asks for
  interactive confirmation unless `--yes`.
- `kb status` adds a line per document: `L3 check: N section(s) awaiting
  review`.

A confirmation is valid only while the section's current `l3_sha256`
matches the one confirmed. A re-ingest rewrites the file, so changed
sections must be reviewed again; unchanged sections whose findings are
identical keep their confirmation.

### 7.6 The gate

A document is **blocked** when its `_l3check.yaml` has any section with
findings and no valid confirmation.

- `kb summarize`: skips blocked documents, names them and the
  `kb l3 report` command; exits non-zero if it skipped any.
- `kb build`: error for a blocked document (not only under `--strict`).
- `kb publish` / `kb ci-publish`: refuse while any document is blocked.
- A document with **no** `_l3check.yaml` (ingested before 1.31.1, or a
  `-code` / authored document) is not gated.

### 7.7 Model default

- `models.LLMConfig.model` default `"sonnet-5"` → `"sonnet"`.
- `templates/init/index.yaml` `model: sonnet-5` → `model: sonnet`.
- Existing repos that already have `llm.model: sonnet-5` in their
  `index.yaml` are **not** rewritten: that is a value the owner chose.

### 7.8 Hub web UI tweaks (owner request, same patch)

- Left rail wider: `.columns` grid in `templates/web/static/style.css`
  goes from `248px` to `288px` in both the default and the ≤ 1279px
  breakpoint (≤ 899px still hides it).
- Reader opens L3 by default: the section route in `web/ui.py` defaults
  `level` to `"l3"` (and falls back to `"l3"` on an invalid value). Every
  link without `?level=` (doc section list, left-rail tree, overview cites,
  pager prev/next) therefore opens L3. Pager prev/next always open L3, even
  when the reader had switched to L2. The L2/L3 toggle keeps working.
- The JSON API (`web/api.py`) default stays `l2`; only the UI changes.

### 7.9 Release

Version `1.31.1` in `pyproject.toml`, CHANGELOG entry, and the Claude /
Copilot / Cursor templates under `templates/init/` that describe the
ingest → summarize flow mention the review step (`kb l3 report`,
`kb l3 confirm`).

## 8. Decisions made by Claude (owner to check)

- Findings file is not sent to the hub (committed in the child repo is the owner's decision).
- Pre-1.31.1 documents are not gated.
- No standalone re-check command; re-ingest re-checks.
- Agent judges `break` findings only; it runs inside ingest and is skipped
  with `--no-llm-review` or when no runner exists.
- `kb build` blocks regardless of `--strict`.
- Fallbacks in front matter / bookmark-part roots are not flagged; findings
  attach to the enclosing manifest unit.
- No per-runner model mapping: `copilot --model sonnet` may be rejected, but
  today's `sonnet-5` is not a Copilot model name either, so this is no
  regression. Copilot users set `llm.model` explicitly.

## 9. Left to the builder

- Module layout (suggested: `src/strata_kb/ingest/l3check.py` for the
  deterministic pass, the agent call next to it or in `summarize`-style
  helper), CLI wiring as a `kb l3` sub-app.
- Exact normalisation details and threshold values, tuned on test PDFs so a
  clean document gives zero findings.
- How publish excludes `_l3check.yaml`.
- Acceptance: the owner tests on real defective PDFs locally (they cannot
  be shared). The builder's own proof is synthetic: small generated PDFs /
  item streams that reproduce each defect, plus `docs/strata-*.pdf` and
  `tests/fixtures/mono-diagram.pdf` producing zero findings.
- Tests: one per finding kind on small synthetic PDFs/items, the gate on
  each command, confirmation invalidation by `l3_sha256`, agent output
  parsing (valid, invalid, runner error).
