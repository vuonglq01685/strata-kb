# BA gate review fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `kb ticket lint` and `kb mission lint` judge what a section
*says*, not only that its heading exists, and stop the four text-scanning
bugs that make the gate pass invisible sections and reject valid markdown.

**Architecture:** `lintcore.py` stays a text-primitive module (fence and
comment blanking, heading/diagram/citation scanning, severity wiring);
`acquality.py` grows into the one home for content rules (placeholders,
Given/When/Then, measurable values, owned unknowns, review-record rows);
`ticketlint.py` and `missionlint.py` stay wiring. The bracketed
`[doc-id §section]` becomes the only citation form the gate parses, with the
old bare form downgraded to a migration warning.

**Tech Stack:** Python 3.12, typer CLI, pytest (real filesystem, real git,
no mocks), ruff. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-14-ba-gates-review-fixes-design.md`

## Global Constraints

- **No new dependencies.** `acquality.py` stays standard-library only.
- **Bilingual.** Ticket and mission bodies follow the BA's working language
  (EN or VI). Every new content rule accepts both, the way
  `acquality.WEASEL_PHRASES` already does. Never assume English.
- **`REQUIRED_HEADINGS` (`ticket.py:17-27`) and `REQUIRED_MISSION_HEADINGS`
  (`mission.py:17-27`) are compatibility contracts.** This batch adds no
  entries to either tuple; it only checks the bodies under the headings that
  are already there.
- **Severity discipline.** Everything this plan adds is `error` except the
  five warnings named explicitly: unticked Definition-of-Ready boxes, review
  scores below 4, more than 3 review rounds, the citation migration warning,
  and the widened weasel scan.
- **Message style.** Every error names the section it is about and the edit
  that fixes it, matching the tag check's wording (*"…; never by re-running
  `kb context new`"*, `lintcore.py:455-465`).
- **Target release 0.22.0.** `pyproject.toml:3` is `0.21.0` today; Task 14
  bumps it and writes the Breaking changelog entry.
- **Test command:** `.venv/Scripts/python -m pytest <file> -q` (this repo's
  `.venv` is uv-managed and has no `pip`). Lint: `.venv/Scripts/python -m
  ruff check .`
- **The full suite takes 10–19 minutes.** Run only the named test file(s)
  per task; the whole suite runs once, in Task 14.
- **Commit after every task.** Conventional Commits, and every commit
  message ends with:
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `src/center_kb/lintcore.py` | Text primitives: fence/comment blanking, `section_body`, heading + diagram + citation scanning, `LintReport` | 1, 2, 3, 7, 8, 10 |
| `src/center_kb/acquality.py` | Every rule about what a section *says* | 5, 8 |
| `src/center_kb/ticketlint.py` | Ticket wiring | 6, 10 |
| `src/center_kb/missionlint.py` | Mission wiring | 9, 10 |
| `src/center_kb/kbcontext.py` | kb-context block parsing | 4 |
| `src/center_kb/doctor.py` | `Issue` (gains a `code` field), `check_context` stale level | 10 |
| `src/center_kb/cli.py` | `kb ticket lint` / `kb mission lint` flags and exit codes | 10 |
| `src/center_kb/initcmd.py` | BA scaffold, `.local.md` stubs | 11 |
| `src/center_kb/templates/init/*` | Templates, 8 BA wrappers, QUICKSTART, CI workflows | 10, 11, 12, 13 |

---

## Task 1: Fence- and comment-aware `section_body` (HIGH-3)

`section_body` (`lintcore.py:98-113`) scans raw text for the terminating
`## `/`# ` line, so a `# comment` inside a fenced example truncates the
section. Reviewer E's G3 (a bash fence at the top of `## Acceptance
Criteria`) and G4 (a text fence above the mermaid fence) are both valid
markdown that the gate rejects. The same helper is how every body-level
check sees the document, so this one fix has the widest blast radius in the
batch.

**Files:**
- Modify: `src/center_kb/lintcore.py:98-113` (and move `HTML_COMMENT_RE`
  from `:200` up next to `FENCE_RE` at `:25`)
- Test: `tests/test_lintcore.py`

**Interfaces:**
- Consumes: `FENCE_RE`, `HTML_COMMENT_RE` (both existing).
- Produces: `lintcore._blank_invisible(text: str) -> str` — the text with
  fenced-block contents and HTML comments replaced by blank lines, line
  count preserved. `section_body(text, heading)` keeps its signature and
  return type (`str | None`) and returns the ORIGINAL text of the slice.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_lintcore.py`:

```python
# --- section_body: fences do not terminate a section ---


def test_section_body_ignores_a_hash_line_inside_a_fence():
    """BEFORE: `section_body` scanned raw lines for the next '# '/'## '
    line, so a bash comment inside a fenced example truncated the section
    and the AC check reported 'must have at least 1 - [ ] item' on a
    ticket that has two. AFTER: fence contents are blanked before the
    terminator scan, so the whole section comes back."""
    text = (
        "## Acceptance Criteria\n"
        "```bash\n"
        "# example invocation\n"
        "importer --file feed.dat\n"
        "```\n"
        "- [ ] AC1 — first\n"
        "- [ ] AC2 — second\n"
        "\n"
        "## Use cases\n"
        "content\n"
    )
    body = lintcore.section_body(text, "## Acceptance Criteria")
    assert "- [ ] AC1 — first" in body
    assert "- [ ] AC2 — second" in body
    assert "## Use cases" not in body


def test_section_body_returns_the_original_fence_text():
    """The blanking is a scanning view only — callers still receive the
    real text, or `check_diagram` would never find its mermaid fence."""
    text = (
        "## Sequence diagram\n"
        "```text\n"
        "# not a diagram\n"
        "```\n"
        "```mermaid\n"
        "sequenceDiagram\n"
        "  A->>B: go\n"
        "```\n"
    )
    body = lintcore.section_body(text, "## Sequence diagram")
    assert "sequenceDiagram" in body
    assert "# not a diagram" in body


def test_section_body_does_not_start_at_a_heading_inside_a_fence():
    """A heading pasted into a fenced example is not a section start —
    the same rule `check_headings` already applies to presence."""
    text = (
        "# Ticket\n"
        "```markdown\n"
        "## Summary\n"
        "pasted example body\n"
        "```\n"
        "## Summary\n"
        "the real summary\n"
    )
    assert lintcore.section_body(text, "## Summary").strip() == (
        "the real summary"
    )


def test_section_body_does_not_start_at_a_heading_inside_a_comment():
    text = (
        "# Ticket\n"
        "<!--\n"
        "## Summary\n"
        "commented-out guidance\n"
        "-->\n"
        "## Summary\n"
        "the real summary\n"
    )
    assert lintcore.section_body(text, "## Summary").strip() == (
        "the real summary"
    )


def test_section_body_still_returns_none_for_a_missing_heading():
    assert lintcore.section_body("# Ticket\n\nbody\n", "## Summary") is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_lintcore.py -q -k section_body`
Expected: FAIL — the first test reports `## Use cases` inside the body (or
`None`), the heading-in-fence tests return the pasted example.

- [ ] **Step 3: Implement**

Move the `HTML_COMMENT_RE` definition (currently `lintcore.py:196-200`,
comment included) up to sit directly under `FENCE_RE` at `:25`, so both
constants are defined before their first use. Then replace `section_body`:

```python
def _blank_invisible(text: str) -> str:
    """`text` with the CONTENT of every fenced block and every HTML
    comment replaced by blank lines, LINE COUNT PRESERVED.

    This is a scanning view, never a value handed to a caller: line
    numbers in the blanked copy index the same lines as the original, so
    a scan can decide "does a section end here" while the slice is taken
    from the real text.

    Both layers are blanked for the same reason: neither is visible in
    the rendered document. A '# ' line inside a bash example and a '## '
    heading inside a guidance comment are equally not section
    boundaries. An unpaired fence leaves `FENCE_RE` unmatched and the
    text degrades to its raw form — the same documented limitation
    `check_headings` carries.
    """

    def _blank(m: re.Match[str]) -> str:
        return "\n" * m.group(0).count("\n")

    return HTML_COMMENT_RE.sub(_blank, FENCE_RE.sub(_blank, text))


def section_body(text: str, heading: str) -> str | None:
    """Lines after an exact `heading` line, up to the next '# '/'## ' line.

    Both the heading search and the terminator search run on
    `_blank_invisible(text)`, so a fenced or commented-out heading never
    opens or closes a section; the returned slice is cut from the
    original lines.
    """
    lines = text.splitlines()
    scan = _blank_invisible(text).splitlines()
    if len(scan) != len(lines):  # defensive: never mis-slice
        scan = lines
    start = None
    for i, line in enumerate(scan):
        if line.strip() == heading:
            start = i + 1
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start, len(lines)):
        if scan[j].startswith("## ") or scan[j].startswith("# "):
            end = j
            break
    return "\n".join(lines[start:end])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_lintcore.py tests/test_ticketlint.py tests/test_missionlint.py -q`
Expected: PASS. Any pre-existing test that asserted the truncating
behaviour is a bug being fixed — update it and say so in its docstring.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/lintcore.py tests/test_lintcore.py
git commit -m "fix(lint): section_body ignores fences and comments (HIGH-3)"
```

---

## Task 2: Comment-blind heading and citation scanning (HIGH-2, L1)

`check_headings` (`lintcore.py:132-156`) strips fences but not HTML
comments, so wrapping `## Summary`, `## Background / Business context`,
`## Use cases` and `## Definition of Ready` in `<!-- … -->` leaves the gate
passing (reviewer E's G5). `citation_scan_text` (`:346-350`) has the same
blind spot in the other direction: a citation that exists only inside a
comment satisfies the reverse check (G6), and a BA's own
`<!-- TODO check arinc-424 §9.999 -->` fails the gate (G7).

**Files:**
- Modify: `src/center_kb/lintcore.py` — `check_headings`,
  `check_recommended_sections:234-261`, `citation_scan_text:346-350`; add
  `visible_body`
- Test: `tests/test_lintcore.py`

**Interfaces:**
- Consumes: `HTML_COMMENT_RE`, `FENCE_RE` (Task 1 moved the former).
- Produces: `lintcore.visible_body(body: str) -> str` — the body with HTML
  comments removed and outer whitespace stripped. Tasks 6 and 9 pass its
  output to `acquality.is_unfilled`.

- [ ] **Step 1: Write the failing tests**

```python
# --- check_headings / citations: HTML comments are not content ---


def test_check_headings_ignores_a_heading_inside_a_comment():
    """BEFORE: only fences were stripped, so four required sections could
    be commented out and the gate still passed (reviewer E's G5). AFTER:
    comments are stripped first — they are invisible in the rendered
    document, so a heading inside one is not present."""
    text = (
        "# Ticket\n"
        "<!--\n"
        "## Summary\n"
        "hidden\n"
        "-->\n"
        "## User Story\n"
    )
    issues = check_headings(text, ("## Summary", "## User Story"))
    assert [i.message for i in issues] == [
        "missing required heading: '## Summary'"
    ]


def test_visible_body_strips_comments():
    assert lintcore.visible_body("<!-- guidance -->\n\nreal text\n") == (
        "real text"
    )
    assert lintcore.visible_body("<!-- only guidance -->\n") == ""


def test_citation_scan_text_drops_comments():
    """G6/G7: a citation that only exists inside a comment is neither a
    citation nor an error."""
    scanned = lintcore.citation_scan_text(
        "body text\n<!-- TODO check arinc-424 §9.999 later -->\n"
    )
    assert "9.999" not in scanned
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_lintcore.py -q -k "comment or visible_body"`
Expected: FAIL — `check_headings` reports no missing heading;
`visible_body` does not exist; `9.999` is still in the scanned text.

- [ ] **Step 3: Implement**

In `lintcore.py`, add the helper next to `HTML_COMMENT_RE` and change three
call sites. Comments are stripped BEFORE fences everywhere, for one stated
reason: a commented-out region is invisible in the rendered document, so it
cannot contribute a fence, a heading, or a citation.

```python
def visible_body(body: str) -> str:
    """`body` with HTML comments removed, outer whitespace stripped — what
    a reader actually sees. The templates ship guidance in comments, so
    every emptiness judgement runs on this view."""
    return HTML_COMMENT_RE.sub("", body).strip()
```

In `check_headings`, replace the `present` set comprehension:

```python
    present = {
        line.strip()
        for line in FENCE_RE.sub("", HTML_COMMENT_RE.sub("", text)).splitlines()
    }
```

Make the identical change to the `present` set in
`check_recommended_sections` (its emptiness half already strips comments —
this makes both halves of one check agree), and rewrite
`citation_scan_text`:

```python
def citation_scan_text(text: str) -> str:
    """Body text with HTML comments, all fenced code blocks (mermaid + a
    fenced kb-context block) and any unfenced kb-context block stripped,
    for inline-citation scanning — refs pinned in kb-context are not
    themselves "citations", and text nobody can see is not a claim."""
    return strip_bare_kb_context(
        FENCE_RE.sub("", HTML_COMMENT_RE.sub("", text))
    )
```

Extend `check_headings`'s docstring with one sentence naming the comment
layer and G5.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_lintcore.py tests/test_ticketlint.py tests/test_missionlint.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/lintcore.py tests/test_lintcore.py
git commit -m "fix(lint): headings and citations ignore HTML comments (HIGH-2, L1)"
```

---

## Task 3: The bracketed citation form (HIGH-4)

`INLINE_CITE_RE` (`lintcore.py:50-53`) takes the last whitespace-delimited
token before `§` as the doc-id and compares case-sensitively, so
`per ARINC 424 §5.129` fails at error level with the useless message
`citation '424 §5.129' … is not in kb-context refs`, `(ARINC-424 §5.129)`
fails on case, and `arinc-424 § 5.129` matches nothing at all. The fix is to
stop guessing: `[doc-id §section]` is the form the gate parses, and the bare
form becomes a migration warning that only fires when it matches a pinned
ref.

**Files:**
- Modify: `src/center_kb/lintcore.py` — add `BRACKET_CITE_RE`, rewrite
  `check_citation_consistency:361-390`
- Modify: `src/center_kb/ticketlint.py:60-68` (`_check_ac_citations`)
- Test: `tests/test_lintcore.py`, `tests/test_ticketlint.py`

**Interfaces:**
- Consumes: `cite_matches_ref(ref, repo, doc, sec)` (`lintcore.py:353-358`,
  unchanged), `citation_scan_text` (Task 2).
- Produces: `lintcore.BRACKET_CITE_RE` with three groups — `(repo | None,
  doc, section)`, the same triple `INLINE_CITE_RE` yields, so
  `cite_matches_ref` takes either.

- [ ] **Step 1: Write the failing tests**

```python
# --- BRACKET_CITE_RE: the citation form the gate parses ---

_CTX = KBContext(
    version="272953a",
    refs=[KBRef(repo_id="aero", doc_id="arinc-424", section_id="5.129")],
    tags=["arinc424"],
)


def test_bracket_citation_matches_a_pinned_ref():
    issues = check_citation_consistency(
        "The designator is stored [arinc-424 §5.129].", _CTX
    )
    assert issues == []


def test_bracket_citation_tolerates_a_space_after_the_section_mark():
    assert check_citation_consistency("see [arinc-424 § 5.129]", _CTX) == []


def test_bracket_citation_with_a_repo_qualifier():
    assert check_citation_consistency("see [aero:arinc-424 §5.129]", _CTX) == []


def test_bracket_citation_to_an_unpinned_section_is_an_error():
    issues = check_citation_consistency("see [arinc-424 §5.126]", _CTX)
    assert [i.level for i in issues] == ["error"]
    assert "not in kb-context refs" in issues[0].message


@pytest.mark.parametrize(
    "prose",
    [
        "per ARINC 424 §5.129 the designator is stored",
        "see (ARINC-424 §5.129)",
        "ICAO Annex 3 §4.2.1 says so",
        "Refer to section §5.129 of arinc-424.",
    ],
)
def test_natural_prose_never_produces_an_error(prose):
    """BEFORE: the doc-id was the last token before '§', so every one of
    these failed the gate at error level (reviewer E's HIGH-4 table).
    AFTER: only bracketed citations are parsed, so prose is prose."""
    assert [
        i for i in check_citation_consistency(prose + " [arinc-424 §5.129]", _CTX)
        if i.level == "error"
    ] == []


def test_bare_citation_matching_a_ref_gets_a_migration_warning():
    issues = check_citation_consistency(
        "The designator is stored per arinc-424 §5.129.", _CTX
    )
    assert [i.level for i in issues] == ["warning"]
    assert "[arinc-424 §5.129]" in issues[0].message


def test_bare_citation_satisfies_the_reverse_check():
    """A pre-bracket ticket collects the migration warning and nothing
    else — never a second 'ref is never cited' warning for the same
    place."""
    issues = check_citation_consistency("stored per arinc-424 §5.129.", _CTX)
    assert len(issues) == 1


def test_a_pinned_ref_nobody_cites_is_still_a_warning():
    issues = check_citation_consistency("no citations here", _CTX)
    assert [i.level for i in issues] == ["warning"]
    assert "is never cited" in issues[0].message


def test_a_bracketed_citation_is_not_also_reported_as_bare():
    issues = check_citation_consistency("[arinc-424 §5.129]", _CTX)
    assert issues == []
```

And in `tests/test_ticketlint.py`, alongside the existing AC-citation tests:

```python
def test_ac_citation_warning_counts_bracketed_citations_only():
    from center_kb.ticketlint import _check_ac_citations

    assert _check_ac_citations(["AC1 — stored [arinc-424 §5.129]"]) == []
    assert len(_check_ac_citations(["AC1 — stored per arinc-424 §5.129"])) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_lintcore.py -q -k "bracket or prose or bare_citation"`
Expected: FAIL — `BRACKET_CITE_RE` does not exist; the prose cases produce
errors.

- [ ] **Step 3: Implement**

Add to `lintcore.py`, directly under `INLINE_CITE_RE`:

```python
# The citation form the gate parses: '[<doc-id> §<sec>]', optionally
# repo-qualified. The character classes are INLINE_CITE_RE's, so a
# bracketed citation accepts exactly the ids kbcontext accepts —
# including nested, '/'-joined repo segments for multi-tier federation.
# Two things the brackets make safe and the bare form could not: '§' may
# be surrounded by spaces, and the section id needs no
# "must not end on punctuation" rule, because ']' terminates it.
_CITE_REPO = r"[A-Za-z0-9][\w.-]*(?:/[A-Za-z0-9][\w.-]*)*"
_CITE_DOC = r"[A-Za-z0-9][\w.-]*"
BRACKET_CITE_RE = re.compile(
    rf"\[(?:({_CITE_REPO}):)?({_CITE_DOC})\s*§\s*([^\s\]]+)\]"
)
```

Extend `INLINE_CITE_RE`'s comment block with: *"Since 0.22.0 this pattern
is a MIGRATION DETECTOR only — it can never produce an error. The gate
parses `BRACKET_CITE_RE`; a bare match is reported as a warning, and only
when it names a ref the ticket already pins."*

Rewrite `check_citation_consistency`:

```python
def _cite_label(repo: str | None, doc: str, sec: str) -> str:
    return f"{repo}:{doc} §{sec}" if repo else f"{doc} §{sec}"


def check_citation_consistency(text: str, ctx: KBContext) -> list[Issue]:
    """Cross-check body citations against the pinned refs, both ways.

    Three passes. Bracketed citations are the contract: one that no
    pinned ref satisfies is an error. A BARE citation is never an error —
    the pattern cannot tell a doc-id from an ordinary word, which used to
    reject 'per ARINC 424 §5.129' outright — but when it does name a
    pinned ref it earns a migration warning and counts as citing that
    ref, so a pre-0.22.0 ticket reports one issue per citation, not two.
    """
    scan_text = citation_scan_text(text)
    bracketed = list(
        dict.fromkeys(
            (m.group(1), m.group(2), m.group(3))
            for m in BRACKET_CITE_RE.finditer(scan_text)
        )
    )
    bare = list(
        dict.fromkeys(
            (m.group(1), m.group(2), m.group(3))
            for m in INLINE_CITE_RE.finditer(BRACKET_CITE_RE.sub("", scan_text))
        )
    )

    issues: list[Issue] = []
    for repo, doc, sec in bracketed:
        if not any(cite_matches_ref(ref, repo, doc, sec) for ref in ctx.refs):
            label = _cite_label(repo, doc, sec)
            issues.append(
                Issue(
                    "error",
                    f"citation '{label}' in the body is not in kb-context refs",
                )
            )
    for repo, doc, sec in bare:
        if any(cite_matches_ref(ref, repo, doc, sec) for ref in ctx.refs):
            label = _cite_label(repo, doc, sec)
            issues.append(
                Issue(
                    "warning",
                    f"citation '{label}' is not bracketed — write "
                    f"'[{label}]' so the gate reads it as a citation",
                )
            )
    for ref in ctx.refs:
        cited = any(
            cite_matches_ref(ref, repo, doc, sec)
            for repo, doc, sec in bracketed + bare
        )
        if not cited:
            issues.append(
                Issue(
                    "warning",
                    f"kb-context ref '{ref}' is never cited in the body",
                )
            )
    return issues
```

In `ticketlint.py:60-68`, change `_check_ac_citations` to use
`lintcore.BRACKET_CITE_RE.search(item)` and reword its message to
`f"Acceptance Criterion has no '[doc-id §section]' citation: '{item.strip()}'"`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_lintcore.py tests/test_ticketlint.py tests/test_missionlint.py -q`
Expected: PASS. Two concrete fixture updates are required, not optional:

- `tests/test_ticketlint.py:_default_sections` — the two ACs cite
  `arinc-kb:arinc-424 §5.3` and `icao-kb:icao-annex-2 §1.1` in the bare
  form. Bracket both (`[arinc-kb:arinc-424 §5.3]`), or every ticket-lint
  test starts carrying two migration warnings.
- `tests/test_missionlint.py:_default_sections` — same change wherever it
  cites.

Update the fixtures to the bracketed form; never relax an assertion to
accommodate the bare form.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/lintcore.py src/center_kb/ticketlint.py tests/
git commit -m "feat(lint): [doc-id §section] is the citation form the gate parses (HIGH-4)"
```

---

## Task 4: A second kb-context block is an error (MEDIUM-1)

`_extract_block` (`kbcontext.py:157-175`) returns the FIRST block, so a
ticket with a valid block followed by a bogus one passes (T14) while the
same two blocks in the other order fails with three errors (T20). The
verdict depends on block order, and the unvalidated pin sits in the ticket
looking authoritative.

**Files:**
- Modify: `src/center_kb/kbcontext.py` — add `_count_blocks`, call it at the
  top of `parse`
- Test: `tests/test_kbcontext.py`

**Interfaces:**
- Consumes: `_KEY_RE` (existing, matches a bare `kb-context:` line at any
  indent).
- Produces: no new public surface — `parse` raises `KBContextError` as it
  already does for every other malformed block, so
  `lintcore.check_context_block` reports it unchanged.

- [ ] **Step 1: Write the failing test**

```python
def test_two_kb_context_blocks_are_an_error_in_either_order():
    """BEFORE: `_extract_block` returned the first block, so a valid pin
    followed by a bogus one passed (T14) while the reverse order failed
    (T20) — the verdict depended on block order. AFTER: two blocks is
    itself the error."""
    good = (
        "## KB context\n"
        "```yaml\n"
        "kb-context:\n"
        '  version: "272953a"\n'
        "  refs:\n"
        "    - aero:arinc-424 §5.129\n"
        "  tags: [arinc424]\n"
        "```\n"
    )
    bad = (
        "## KB context\n"
        "```yaml\n"
        "kb-context:\n"
        '  version: "0000000"\n'
        "  refs:\n"
        "    - aero:arinc-424 §9.999\n"
        "  tags: [ghost-tag]\n"
        "```\n"
    )
    for text in (good + bad, bad + good):
        with pytest.raises(kbcontext.KBContextError) as excinfo:
            kbcontext.parse(text)
        assert "2 'kb-context:' blocks" in str(excinfo.value)


def test_one_kb_context_block_still_parses():
    ctx = kbcontext.parse(
        "kb-context:\n"
        '  version: "272953a"\n'
        "  refs:\n"
        "    - aero:arinc-424 §5.129\n"
        "  tags: [arinc424]\n"
    )
    assert ctx.version == "272953a"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_kbcontext.py -q -k blocks`
Expected: FAIL — `good + bad` parses without raising.

- [ ] **Step 3: Implement**

```python
def _count_blocks(text: str) -> int:
    """How many bare 'kb-context:' key lines the text carries, at any
    indent — the same line `_extract_block` anchors on."""
    return sum(1 for line in text.splitlines() if _KEY_RE.match(line))
```

At the top of `parse`, before `_extract_block(text)`:

```python
    count = _count_blocks(text)
    if count > 1:
        raise KBContextError(
            f"{count} 'kb-context:' blocks found — a document pins exactly "
            "one. Delete the extra block by hand; never re-run "
            "`kb context new`, which would rewrite the pinned version and "
            "falsify when the document was grounded"
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_kbcontext.py tests/test_ticketlint.py tests/test_missionlint.py -q`
Expected: PASS. The shipped `ticket-template.md` and `mission-template.md`
carry exactly one block each, so no scaffold regresses.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/kbcontext.py tests/test_kbcontext.py
git commit -m "fix(kb-context): reject a second kb-context block (MEDIUM-1)"
```

---

## Task 5: Content rules in `acquality.py` (HIGH-1 primitives, MEDIUM-4)

`acquality.py` is 85 lines of weasel-phrase detection today. It becomes the
one home for every rule about what a section says. Two behaviour changes
ride along: `OPEN(...)` stops muting a whole line, and an owner of `TBD` or
`?` stops counting as an owner — reviewer E's G1 capstone passes today on
exactly those two holes.

**Files:**
- Modify: `src/center_kb/acquality.py`
- Test: `tests/test_acquality.py`

**Interfaces:**
- Consumes: nothing new (standard library only, as the module docstring
  requires).
- Produces, all used by Tasks 6, 8 and 9:
  - `PLACEHOLDER_PHRASES: tuple[str, ...]`
  - `is_unfilled(visible: str) -> bool`
  - `GWT_RE: re.Pattern[str]`
  - `MEASURABLE_RE: re.Pattern[str]`
  - `OPEN_OWNER_RE: re.Pattern[str]` (group 1 = the owner text)
  - `owned_open_markers(text: str) -> list[str]`
  - `ac_substance(item: str) -> str | None`
  - `nfr_target_ok(cell: str) -> bool`
  - `ReviewRow` (frozen dataclass: `date: str`, `round: int`,
    `business: int`, `dev: int`, `reviewer: str`)
  - `parse_review_row(cells: list[str]) -> ReviewRow | str` — the row, or
    the reason it is malformed
  - `weasel_hits(line)` keeps its signature; its muting rule changes

- [ ] **Step 1: Write the failing tests**

```python
import pytest

from center_kb import acquality


@pytest.mark.parametrize(
    "body",
    ["", "TBD", "  tbd  ", "TODO", "N/A", "...", "…", "<...>", "-", "xxx",
     "chưa rõ", "đang cập nhật"],
)
def test_is_unfilled_true_for_placeholders(body):
    assert acquality.is_unfilled(body) is True


@pytest.mark.parametrize(
    "body",
    ["The importer stores the designator.", "Bộ nhập lưu mã định danh.",
     "5 seconds", "None"],
)
def test_is_unfilled_false_for_real_content(body):
    assert acquality.is_unfilled(body) is False


def test_gwt_detects_both_languages():
    assert acquality.GWT_RE.search(
        "Given a Restrictive Airspace record, when it is imported, then …"
    )
    assert acquality.GWT_RE.search(
        "Giả sử có bản ghi vùng cấm, khi nhập, thì hệ thống lưu mã"
    )
    assert not acquality.GWT_RE.search("The system stores the designator")


@pytest.mark.parametrize(
    "item",
    [
        "AC1 — Given a record, when imported, then it is stored",
        "AC2 — the importer stores at most 200 records per batch",
        "AC3 — response time <= 2s",
        "AC4 — writes `runway_designator` to the feed table",
        "AC5 — the threshold is OPEN(alice)",
    ],
)
def test_ac_substance_accepts(item):
    assert acquality.ac_substance(item) is None


@pytest.mark.parametrize(
    "item",
    [
        "AC1 — The system shall behave correctly and handle all edge cases",
        "AC2 — Performance is acceptable and the data is validated properly",
        "AC3 — the threshold is OPEN(TBD)",
        "AC4 — the threshold is OPEN(?)",
    ],
)
def test_ac_substance_rejects(item):
    assert acquality.ac_substance(item) is not None


def test_owned_open_markers_ignores_placeholder_owners():
    assert acquality.owned_open_markers("value OPEN(alice)") == ["OPEN(alice)"]
    assert acquality.owned_open_markers("value OPEN(TBD)") == []
    assert acquality.owned_open_markers("value OPEN(?)") == []


def test_nfr_target_ok():
    assert acquality.nfr_target_ok("p95 < 200 ms") is True
    assert acquality.nfr_target_ok("OPEN(alice)") is True
    assert acquality.nfr_target_ok("fast") is False
    assert acquality.nfr_target_ok("") is False


def test_open_marker_mutes_only_its_own_parentheses():
    """BEFORE: an OPEN(...) anywhere on the line muted every banned
    phrase on it, so 'Values are configured OPEN(x) and appropriate and a
    subset and responsive.' reported nothing. AFTER: only the text inside
    the parentheses is muted."""
    hits = acquality.weasel_hits(
        "Values are configured OPEN(alice) and appropriate and a subset."
    )
    assert sorted(h.lower() for h in hits) == ["a subset", "appropriate", "configured"]


def test_open_marker_still_mutes_a_phrase_inside_it():
    assert acquality.weasel_hits("threshold OPEN(alice: appropriate?)") == []


def test_parse_review_row_accepts_a_well_formed_row():
    row = acquality.parse_review_row(
        ["2026-09-08", "1", "4", "5", "business-reviewer"]
    )
    assert isinstance(row, acquality.ReviewRow)
    assert (row.round, row.business, row.dev) == (1, 4, 5)


@pytest.mark.parametrize(
    "cells",
    [
        ["2026-09-08", "1", "5", "5", ""],          # empty reviewer
        ["2026-09-08", "one", "5", "5", "me"],      # round not an int
        ["2026-09-08", "1", "9", "5", "me"],        # score out of range
        ["2026-09-08", "1", "5", "5"],              # four cells
    ],
)
def test_parse_review_row_rejects(cells):
    assert isinstance(acquality.parse_review_row(cells), str)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_acquality.py -q`
Expected: FAIL — every new symbol is missing, and the existing
`weasel_hits` mute test (the one asserting `OPEN(...)` silences the line)
fails on the new expectation.

- [ ] **Step 3: Implement**

Append to `acquality.py` — put `from dataclasses import dataclass` with the
existing `import re` at the top of the module, not mid-file — and update the
module docstring's first paragraph to say it holds every content rule, not
only the weasel list:

```python
# Placeholders: what an unfilled section says. Bilingual, same reason as
# WEASEL_PHRASES. 'N/A' is here because a required section may not answer
# with it — the RECOMMENDED sections that legitimately accept
# 'N/A — <reason>' are checked by check_recommended_sections, not this.
PLACEHOLDER_PHRASES: tuple[str, ...] = (
    "tbd",
    "to be defined",
    "todo",
    "n/a",
    "na",
    "none yet",
    "xxx",
    "chưa rõ",
    "chưa có",
    "chưa xác định",
    "đang cập nhật",
    "cập nhật sau",
)

_PLACEHOLDER_RE = re.compile(
    "|".join(
        rf"\b{re.escape(p)}\b"
        for p in sorted(PLACEHOLDER_PHRASES, key=len, reverse=True)
    ),
    re.IGNORECASE,
)


def is_unfilled(visible: str) -> bool:
    """True when `visible` says nothing: empty, or only placeholder
    phrases and punctuation once they are removed.

    `visible` is what a reader sees — callers pass
    `lintcore.visible_body(body)`, so the templates' guidance comments
    never count as content.
    """
    remainder = _PLACEHOLDER_RE.sub("", visible)
    return not re.sub(r"[\W_]+", "", remainder, flags=re.UNICODE)


# A Given/When/Then triple, in order, in either working language.
GWT_RE = re.compile(
    r"(?:\bgiven\b|\bgiả sử\b|\bcho trước\b)"
    r".*?(?:\bwhen\b|\bkhi\b)"
    r".*?(?:\bthen\b|\bthì\b)",
    re.IGNORECASE | re.DOTALL,
)

# Something a tester can check: a number, a comparison, or an identifier
# naming a real thing (backticked code, snake_case, CamelCase, a dotted
# path). Deliberately generous — this separates "an outcome" from "a
# feeling", it does not grade the outcome.
MEASURABLE_RE = re.compile(
    r"\d"
    r"|<=|>=|==|[<>]"
    r"|`[^`]+`"
    r"|\b[a-z0-9]+(?:_[a-z0-9]+)+\b"
    r"|\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+\b"
    r"|\b[a-z][A-Za-z0-9]*(?:\.[a-z][A-Za-z0-9]*)+\b"
)

# 'OPEN(<owner>)' with the owner captured. OPEN_RE above stays the marker
# COUNTER (ticketlint._unknown_count pairs markers with Open-questions
# rows, and an unowned marker is still an unknown that needs a row); this
# one answers the different question "is the unknown owned".
OPEN_OWNER_RE = re.compile(r"OPEN\(([^)]*)\)")

# An owner that names nobody. 'OPEN(TBD)' is a placeholder wearing the
# costume of an owned unknown — reviewer E's G1 capstone passed on it.
_UNOWNED: frozenset[str] = frozenset(
    {"", "?", "-", "tbd", "todo", "n/a", "na", "chưa rõ", "chưa có"}
)


def owned_open_markers(text: str) -> list[str]:
    """The `OPEN(...)` markers in `text` that name a real owner."""
    return [
        m.group(0)
        for m in OPEN_OWNER_RE.finditer(text)
        if m.group(1).strip().lower() not in _UNOWNED
    ]


def ac_substance(item: str) -> str | None:
    """None when the AC can be acceptance-tested, else the reason.

    Three ways to pass, in the order a BA would try them: a Given/When/
    Then triple, an owned unknown, or a measurable value. Anything else
    is a sentence about how the system ought to feel.
    """
    if GWT_RE.search(item):
        return None
    if owned_open_markers(item):
        return None
    if MEASURABLE_RE.search(item):
        return None
    return (
        "has no Given/When/Then, no measurable value (a number, a "
        "comparison, or a named identifier) and no owned OPEN(<owner>)"
    )


def nfr_target_ok(cell: str) -> bool:
    """An NFR Target must be a number or an owned unknown — never a mood."""
    return bool(re.search(r"\d", cell)) or bool(owned_open_markers(cell))


@dataclass(frozen=True)
class ReviewRow:
    date: str
    round: int
    business: int
    dev: int
    reviewer: str


def parse_review_row(cells: list[str]) -> "ReviewRow | str":
    """A '| Date | Round | Business | Dev | Reviewer |' row, or the reason
    it is malformed. Scores are 1–5 (docs/review-rubric.md's maturity
    scale); the round is any positive integer — the 3-round cap is a
    warning the caller raises, not a malformed row."""
    if len(cells) != 5:
        return f"has {len(cells)} cells; the table has 5 columns"
    date, round_, business, dev, reviewer = (c.strip() for c in cells)
    if not all((date, round_, business, dev, reviewer)):
        return "has an empty cell; every column must be filled"
    try:
        round_i = int(round_)
    except ValueError:
        return f"Round '{round_}' is not a whole number"
    if round_i < 1:
        return f"Round '{round_}' must be 1 or more"
    scores: list[int] = []
    for name, raw in (("Business", business), ("Dev", dev)):
        try:
            value = int(raw)
        except ValueError:
            return f"{name} score '{raw}' is not a whole number"
        if not 1 <= value <= 5:
            return f"{name} score '{raw}' is outside the 1–5 maturity scale"
        scores.append(value)
    return ReviewRow(date, round_i, scores[0], scores[1], reviewer)
```

Then change `weasel_hits` to mute per phrase instead of per line:

```python
def weasel_hits(line: str) -> list[str]:
    """Banned phrases in ``line``, matched text verbatim.

    An ``OPEN(...)`` marker suppresses only what sits INSIDE its own
    parentheses: declared, owned vagueness is the documented exception,
    and one marker never licenses the rest of the sentence. (Before
    0.22.0 a single marker muted the whole line — 'Values are configured
    OPEN(x) and appropriate and a subset and responsive.' reported
    nothing at all.) The AC-level escape hatch lives at error level in
    ``ac_substance``; these stay warnings.
    """
    outside = OPEN_OWNER_RE.sub(" ", line)
    hits = [m.group(0) for m in _WEASEL_RE.finditer(outside)]
    if _MEANS_RE.search(line):
        hits = [h for h in hits if h.lower() not in CONDITIONAL_PHRASES]
    return hits
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_acquality.py tests/test_ticketlint.py -q`
Expected: PASS. Update the pre-existing whole-line-mute test in
`tests/test_acquality.py` to the new rule, with a BEFORE/AFTER docstring.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/acquality.py tests/test_acquality.py
git commit -m "feat(acquality): content rules — placeholders, GWT, measurable values, review rows"
```

---

## Task 6: Ticket substance checks at error level (HIGH-1)

With Task 5's primitives in place, wire them into the ticket gate. This is
the task that makes reviewer E's T1 (every body `TBD`), T3 (ACs with no
Given/When/Then and no value), T22 (`As a x, I want y, so that z`), T15
(duplicate AC ids) and the G1 capstone fail.

**Files:**
- Modify: `src/center_kb/ticketlint.py` — add `_check_required_filled`,
  `_check_story` (rewrite), `_check_ac_present` (min 2), `_check_ac_ids`,
  `_check_ac_substance`, `_check_nfr_targets`, `_check_dor_checklist`; wire
  them into `lint():226-263`
- Modify: `src/center_kb/ticket.py` — add `STORY_PARTS_RE`
- Modify: `src/center_kb/lintcore.py` — add `CHECKBOX_STATE_RE`
- Test: `tests/test_ticketlint.py`

**Interfaces:**
- Consumes: `acquality.is_unfilled`, `acquality.ac_substance`,
  `acquality.nfr_target_ok` (Task 5); `lintcore.visible_body` (Task 2);
  `lintcore.section_body` (Task 1); `lintcore.table_rows:306-320`.
- Produces: no new cross-task surface — `lint()` keeps its signature.

- [ ] **Step 1: Write the failing tests**

`tests/test_ticketlint.py` already has everything these need: the
`fed_hub` and `golden_block` fixtures, `_hub(fed_hub)`,
`_build_ticket(block, *, skip=None, title=..., overrides=None)` built over
`_default_sections(block)` (`tests/test_ticketlint.py:44-160`), and the
`_errors` / `_warnings` extractors. Use them — do not write a second ticket
builder.

```python
def test_a_ticket_of_placeholders_fails(fed_hub: Path, golden_block: str):
    """Reviewer E's T1: every required heading present, every body 'TBD'
    — DoR: PASS with warnings only, before 0.22.0."""
    text = _build_ticket(
        golden_block,
        overrides={
            "## Summary": "TBD",
            "## Background / Business context": "",
            "## Use cases": "…",
        },
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert report.passed is False
    assert (
        "'## Summary' is empty or only placeholder text — fill it in"
        in _errors(report)
    )
    assert (
        "'## Use cases' is empty or only placeholder text — fill it in"
        in _errors(report)
    )


def test_a_single_acceptance_criterion_fails(fed_hub: Path, golden_block: str):
    text = _build_ticket(
        golden_block,
        overrides={
            "## Acceptance Criteria": (
                "- [ ] AC1: Show airspace type per "
                "[arinc-kb:arinc-424 §5.3]"
            )
        },
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert any("at least 2 '- [ ]' items" in m for m in _errors(report))


def test_vague_acceptance_criteria_fail(fed_hub: Path, golden_block: str):
    text = _build_ticket(
        golden_block,
        overrides={
            "## Acceptance Criteria": (
                "- [ ] AC1: The system shall behave correctly\n"
                "- [ ] AC2: Performance is acceptable"
            )
        },
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert sum("no Given/When/Then" in m for m in _errors(report)) == 2


def test_duplicate_ac_ids_fail(fed_hub: Path, golden_block: str):
    text = _build_ticket(
        golden_block,
        overrides={
            "## Acceptance Criteria": (
                "- [ ] AC1: Show type per [arinc-kb:arinc-424 §5.3]\n"
                "- [ ] AC1: Show level per [arinc-kb:arinc-424 §5.3]"
            )
        },
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert any(
        "duplicate Acceptance Criterion id 'AC1'" in m for m in _errors(report)
    )


def test_a_one_letter_user_story_fails(fed_hub: Path, golden_block: str):
    text = _build_ticket(
        golden_block,
        overrides={"## User Story": "As a x, I want y, so that z."},
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert sum("User Story part" in m for m in _errors(report)) == 3


def test_a_short_but_real_user_story_passes(fed_hub: Path, golden_block: str):
    """Guard against over-reach: 'BA' is a two-character role and must
    keep passing — the rule rejects a part with fewer than 2 word
    characters, not a short word."""
    text = _build_ticket(
        golden_block,
        overrides={
            "## User Story": (
                "As a BA, I want the designator stored, so that the feed "
                "is auditable."
            )
        },
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert not any("User Story part" in m for m in _errors(report))


def test_an_unquantified_nfr_row_fails(fed_hub: Path, golden_block: str):
    text = _build_ticket(
        golden_block,
        overrides={
            "## Non-functional requirements": (
                "| Concern | Target | How to measure | Source |\n"
                "|---|---|---|---|\n"
                "| Speed | fast | eyeball | n/a |"
            )
        },
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert any("no measurable Target" in m for m in _errors(report))


def test_a_definition_of_ready_with_no_rows_fails(
    fed_hub: Path, golden_block: str
):
    text = _build_ticket(
        golden_block, overrides={"## Definition of Ready": "All good."}
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert any("no '- [ ]' checklist rows" in m for m in _errors(report))


def test_unticked_definition_of_ready_boxes_are_a_warning_only(
    fed_hub: Path, golden_block: str
):
    """The wrappers forbid the agent from ticking a box itself
    (claude-skill-ba-ticket-author.md:171-174), so an unticked checklist
    can never be an error — the golden ticket ships three unticked rows
    and still passes."""
    report = ticketlint.lint(_build_ticket(golden_block), _hub(fed_hub))
    unticked = [
        m for m in _warnings(report)
        if "Definition of Ready item is not ticked" in m
    ]
    assert len(unticked) == 3
    assert report.passed is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_ticketlint.py -q -k "placeholder or acceptance or story or nfr or definition_of_ready"`
Expected: FAIL — every assertion, because none of these checks exist.

- [ ] **Step 3: Implement**

In `lintcore.py`, next to `CHECKBOX_ROW_RE:203`:

```python
# The same row, with its tick state. CHECKBOX_ROW_RE stays as it is — its
# callers only want the text.
CHECKBOX_STATE_RE = re.compile(r"^-\s*\[(?P<mark>[ xX])\]\s*(?P<text>.+)$")
```

In `ticket.py`, under `STORY_RE:45`:

```python
# The same story shape, with each part captured, so the gate can ask
# whether the parts say anything. STORY_RE stays the shape check.
STORY_PARTS_RE = re.compile(
    r"as an?\s+(?P<role>.+?)\s*,?\s*i want\s+(?P<capability>.+?)"
    r"\s*,?\s*so that\s+(?P<value>.+)",
    re.I | re.S,
)
```

In `ticketlint.py`, add the checks and wire them into `lint()`:

```python
# Required sections whose body is checked by a stronger, section-specific
# check — a second "is it filled" error would only duplicate it.
_FILL_EXEMPT: frozenset[str] = frozenset(
    {
        "## KB context",          # parsed by check_context_block
        "## Sequence diagram",    # check_diagram
        "## Business flow",       # check_diagram
        "## Definition of Ready", # _check_dor_checklist, below
    }
)


def _check_required_filled(text: str) -> list[Issue]:
    """NT1 — a required section that says nothing is not a section.
    Presence was the whole contract before 0.22.0, so a ticket of nine
    headings over nine 'TBD's passed the gate (reviewer E's T1)."""
    issues: list[Issue] = []
    for heading in ticket.REQUIRED_HEADINGS:
        if heading in _FILL_EXEMPT:
            continue
        body = lintcore.section_body(text, heading)
        if body is None:
            continue  # missing heading — already reported by check_headings
        if acquality.is_unfilled(lintcore.visible_body(body)):
            issues.append(
                Issue(
                    "error",
                    f"'{heading}' is empty or only placeholder text — "
                    "fill it in",
                )
            )
    return issues


def _check_story(text: str) -> list[Issue]:
    body = lintcore.section_body(text, "## User Story")
    if body is None:
        return []  # heading missing — already reported by check_headings
    if not ticket.STORY_RE.search(body):
        return [
            Issue(
                "error",
                "User Story does not match 'As a <role>, I want "
                "<capability>, so that <value>.'",
            )
        ]
    match = ticket.STORY_PARTS_RE.search(body)
    if match is None:  # shape matched but parts did not — treat as unfilled
        return []
    issues: list[Issue] = []
    for name in ("role", "capability", "value"):
        part = match.group(name).strip().rstrip(".")
        letters = re.sub(r"[\W_]+", "", part, flags=re.UNICODE)
        if len(letters) < 2 or acquality.is_unfilled(part):
            issues.append(
                Issue(
                    "error",
                    f"User Story part <{name}> says nothing: '{part}' — "
                    "name the actual role, capability and value",
                )
            )
    return issues


def _check_ac_present(text: str) -> tuple[list[Issue], list[str]]:
    body = lintcore.section_body(text, "## Acceptance Criteria")
    if body is None:
        return [], []
    items = [
        m.group(1)
        for line in body.splitlines()
        if (m := _AC_ITEM_RE.match(line.strip()))
    ]
    if len(items) < 2:
        return [
            Issue(
                "error",
                "Acceptance Criteria must have at least 2 '- [ ]' items — "
                f"found {len(items)}",
            )
        ], items
    return [], items


_AC_ID_RE = re.compile(r"^(AC\d+)\b", re.I)


def _check_ac_ids(ac_items: list[str]) -> list[Issue]:
    """Two ACs sharing an id make every downstream reference ambiguous —
    the AC→test map in the PR template names ids."""
    seen: set[str] = set()
    issues: list[Issue] = []
    for item in ac_items:
        m = _AC_ID_RE.match(item.strip())
        if m is None:
            continue
        key = m.group(1).upper()
        if key in seen:
            issues.append(
                Issue(
                    "error",
                    f"duplicate Acceptance Criterion id '{m.group(1)}' — "
                    "give every AC its own id",
                )
            )
        seen.add(key)
    return issues


def _check_ac_substance(ac_items: list[str]) -> list[Issue]:
    issues: list[Issue] = []
    for item in ac_items:
        reason = acquality.ac_substance(item)
        if reason is not None:
            issues.append(
                Issue("error", f"AC {reason}: '{item.strip()}'")
            )
    return issues


_NFR_HEADING = "## Non-functional requirements"


def _check_nfr_targets(text: str) -> list[Issue]:
    """Every NFR row needs a number or an owned unknown in Target. The
    section itself is RECOMMENDED — its absence stays a warning from
    check_recommended_sections; a table of moods is an error."""
    body = lintcore.section_body(text, _NFR_HEADING)
    if body is None:
        return []
    rows = lintcore.table_rows(lintcore.visible_body(body))
    if len(rows) < 2:
        return []  # header only, or no table — emptiness is warned elsewhere
    header = [c.strip().lower() for c in rows[0]]
    target = header.index("target") if "target" in header else 1
    issues: list[Issue] = []
    for cells in rows[1:]:
        if len(cells) <= target:
            continue
        if not acquality.nfr_target_ok(cells[target]):
            concern = cells[0] if cells else "?"
            issues.append(
                Issue(
                    "error",
                    f"NFR row '{concern}' has no measurable Target "
                    f"('{cells[target]}') — give a number or OPEN(<owner>)",
                )
            )
    return issues


_DOR_HEADING = "## Definition of Ready"


def _check_dor_checklist(text: str) -> list[Issue]:
    """The checklist must exist; ticking it is the BA's job at review
    time, so an unticked box is a warning — the wrappers forbid the agent
    from ticking one itself."""
    body = lintcore.section_body(text, _DOR_HEADING)
    if body is None:
        return []
    rows = [
        m
        for line in body.splitlines()
        if (m := lintcore.CHECKBOX_STATE_RE.match(line.strip()))
    ]
    if not rows:
        return [
            Issue(
                "error",
                f"'{_DOR_HEADING}' has no '- [ ]' checklist rows — keep the "
                "template's checklist",
            )
        ]
    return [
        Issue(
            "warning",
            f"Definition of Ready item is not ticked: "
            f"'{m.group('text').strip()}'",
        )
        for m in rows
        if m.group("mark") == " "
    ]
```

Wire them into `lint()` in check order — structure, then story, then ACs,
then the rest:

```python
    issues += lintcore.check_headings(text, ticket.REQUIRED_HEADINGS)
    issues += _check_required_filled(text)
    issues += _check_story(text)

    ac_issues, ac_items = _check_ac_present(text)
    issues += ac_issues
    issues += _check_ac_ids(ac_items)
    issues += _check_ac_substance(ac_items)
```

and after `_check_owned_unknowns(text)`:

```python
    issues += _check_nfr_targets(text)
    issues += _check_dor_checklist(text)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_ticketlint.py tests/test_cli_ticket.py -q`
Expected: PASS. Existing fixtures written as minimal skeletons will now
fail the gate — fill them in (one real AC pair, a real story, a quantified
NFR row) rather than exempting them; that is the behaviour change this
batch exists to make.

`docs/tickets/TEMPLATE.md` is placeholders by definition and is expected to
FAIL the new gate. Do not soften a rule to make it pass, and do not add it
to any test that lints a document: the scaffolded CI only lints paths under
`tickets/` and `missions/`, so no BA repo trips over it.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/ticketlint.py src/center_kb/ticket.py src/center_kb/lintcore.py tests/
git commit -m "feat(ticket lint): substance checks at error level (HIGH-1)"
```

---

## Task 7: A mermaid fence must contain an edge (HIGH-1, T4)

`check_diagram` (`lintcore.py:159-193`) only needs the type keyword at the
start of a line, so a fence holding `sequenceDiagram` followed by `zzzz !!!
not a diagram at all` passes, and so does an empty fence with just the
keyword.

**Files:**
- Modify: `src/center_kb/lintcore.py:159-193`
- Test: `tests/test_lintcore.py`

**Interfaces:**
- Consumes: `FENCE_RE`, `section_body`.
- Produces: `check_diagram` keeps its signature; the error message gains a
  second form for "keyword but no edge".

- [ ] **Step 1: Write the failing tests**

```python
def test_check_diagram_rejects_a_fence_with_no_edge():
    """Reviewer E's T4: the type keyword was the whole contract, so a
    fence of garbage — or an empty one — passed."""
    text = (
        "## Sequence diagram\n"
        "```mermaid\n"
        "sequenceDiagram\n"
        "zzzz !!! not a diagram at all\n"
        "```\n"
    )
    issues = check_diagram(text, "## Sequence diagram", ("sequenceDiagram",))
    assert [i.level for i in issues] == ["error"]
    assert "no relationship" in issues[0].message


def test_check_diagram_accepts_a_sequence_arrow():
    text = (
        "## Sequence diagram\n"
        "```mermaid\n"
        "sequenceDiagram\n"
        "  Importer->>Store: write designator\n"
        "```\n"
    )
    assert check_diagram(text, "## Sequence diagram", ("sequenceDiagram",)) == []


def test_check_diagram_accepts_a_c4_rel_call():
    """C4 diagrams draw relationships with Rel(...), not arrows — the
    mission gate would break on every valid C4 diagram otherwise."""
    text = (
        "## System context (C4 L1)\n"
        "```mermaid\n"
        "C4Context\n"
        '  Person(ba, "BA")\n'
        '  Rel(ba, kb, "queries")\n'
        "```\n"
    )
    assert check_diagram(text, "## System context (C4 L1)", ("C4Context", "flowchart")) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_lintcore.py -q -k check_diagram`
Expected: FAIL on the first test — the garbage fence passes today.

- [ ] **Step 3: Implement**

Add next to `check_diagram` and use it:

```python
# A relationship in any diagram dialect the two gates accept: mermaid
# arrows (flowchart, sequence) and C4's Rel()/BiRel() calls. A diagram
# with nodes and no relationships is a list drawn in a box.
_EDGE_RE = re.compile(
    r"-->|->>|-\.->|\.\.>|->|--|\bRel\w*\(|\bBiRel\w*\("
)
```

In the fence loop, require both:

```python
    keyword_seen = False
    for lang, content in FENCE_RE.findall(body):
        if lang.strip().lower() != "mermaid" or not pattern.search(content):
            continue
        keyword_seen = True
        if _EDGE_RE.search(content):
            return []
    joined = " or ".join(f"'{k}'" for k in keywords)
    if keyword_seen:
        return [
            Issue(
                "error",
                f"'{heading}' has a ```mermaid fence with {joined} but no "
                "relationship in it (an arrow, or a C4 Rel(...)) — an empty "
                "diagram is not a diagram",
            )
        ]
    return [
        Issue(
            "error",
            f"'{heading}' must contain a ```mermaid fence with {joined} "
            "at the start of a line",
        )
    ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_lintcore.py tests/test_ticketlint.py tests/test_missionlint.py -q`
Expected: PASS. Fixture diagrams that were keyword-only need one real edge.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/lintcore.py tests/
git commit -m "feat(lint): a mermaid fence must contain a relationship (T4)"
```

---

## Task 8: `## Review record` schema (MEDIUM-3)

`check_review_record` (`lintcore.py:271-303`) checks that the section is
present, non-empty, and past the template placeholder. Reviewer E's T18 —
`| 2026-09-08 | 1 | 5 | 5 |  |`, an empty reviewer with a self-declared 5/5
— passes with no warning at all. The table shape is machine-checkable and
becomes an error; the score threshold and the round cap stay warnings,
because those are the BA's judgment.

The shipped header is `| Date | Round | Business | Dev | Reviewer |`
(`ticket-template.md:97`).

**Files:**
- Modify: `src/center_kb/lintcore.py:264-303`
- Test: `tests/test_lintcore.py`

**Interfaces:**
- Consumes: `acquality.parse_review_row`, `acquality.ReviewRow` (Task 5);
  `lintcore.table_rows:306-320`; `visible_body` (Task 2).
- Produces: `check_review_record` keeps its signature and its three
  existing warnings.

- [ ] **Step 1: Write the failing tests**

```python
_RECORD = (
    "## Review record\n"
    "| Date | Round | Business | Dev | Reviewer |\n"
    "|---|---|---|---|---|\n"
    "{rows}"
)


def test_review_record_with_an_empty_reviewer_cell_is_an_error():
    """Reviewer E's T18: a self-declared 5/5 with an empty reviewer cell
    passed with no warning at all."""
    text = _RECORD.format(rows="| 2026-09-08 | 1 | 5 | 5 |  |\n")
    issues = lintcore.check_review_record(text)
    assert [i.level for i in issues] == ["error"]
    assert "empty cell" in issues[0].message


def test_review_record_with_no_data_rows_is_an_error():
    text = _RECORD.format(rows="")
    issues = lintcore.check_review_record(text)
    assert [i.level for i in issues] == ["error"]
    assert "no review rows" in issues[0].message


def test_review_record_requires_the_gap_verifier_from_round_two():
    text = _RECORD.format(
        rows="| 2026-09-08 | 1 | 4 | 4 | business-reviewer |\n"
        "| 2026-09-09 | 2 | 5 | 5 | someone-else |\n"
    )
    issues = lintcore.check_review_record(text)
    assert any(
        "round 2 must be reviewed by 'gap-verifier'" in i.message
        and i.level == "error"
        for i in issues
    )


def test_review_record_rounds_must_increase():
    text = _RECORD.format(
        rows="| 2026-09-08 | 2 | 4 | 4 | gap-verifier |\n"
        "| 2026-09-09 | 1 | 5 | 5 | gap-verifier |\n"
    )
    assert any(
        "Round 1 does not follow round 2" in i.message and i.level == "error"
        for i in lintcore.check_review_record(text)
    )


def test_a_score_below_four_is_a_warning_not_an_error():
    text = _RECORD.format(rows="| 2026-09-08 | 1 | 3 | 4 | business-reviewer |\n")
    issues = lintcore.check_review_record(text)
    assert [i.level for i in issues] == ["warning"]
    assert "below the threshold of 4" in issues[0].message


def test_a_fourth_round_is_a_warning_not_an_error():
    rows = "".join(
        f"| 2026-09-0{n} | {n} | 5 | 5 | "
        f"{'business-reviewer' if n == 1 else 'gap-verifier'} |\n"
        for n in (1, 2, 3, 4)
    )
    issues = lintcore.check_review_record(_RECORD.format(rows=rows))
    assert [i.level for i in issues] == ["warning"]
    assert "more than 3 review rounds" in issues[0].message


def test_a_well_formed_record_is_clean():
    text = _RECORD.format(
        rows="| 2026-09-08 | 1 | 4 | 5 | business-reviewer |\n"
        "| 2026-09-09 | 2 | 5 | 5 | gap-verifier |\n"
    )
    assert lintcore.check_review_record(text) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_lintcore.py -q -k review_record`
Expected: FAIL — every record above passes today.

- [ ] **Step 3: Implement**

Extend `check_review_record` after its three existing early returns:

```python
REVIEW_RECORD_COLUMNS: tuple[str, ...] = (
    "date",
    "round",
    "business",
    "dev",
    "reviewer",
)

# docs/review-rubric.md: rounds 2 and 3 are a single gap-verifier pass.
GAP_VERIFIER = "gap-verifier"
REVIEW_SCORE_THRESHOLD = 4
REVIEW_ROUND_CAP = 3
```

```python
    # --- schema (errors) -------------------------------------------------
    rows = table_rows(visible_body(stripped))
    if not rows:
        return [
            Issue(
                "error",
                f"'{REVIEW_RECORD_HEADING}' has no review table — keep the "
                "template's '| Date | Round | Business | Dev | Reviewer |' "
                "table and append one row per round",
            )
        ]
    header = [c.strip().lower() for c in rows[0]]
    if tuple(header) != REVIEW_RECORD_COLUMNS:
        return [
            Issue(
                "error",
                f"'{REVIEW_RECORD_HEADING}' table header is "
                f"{rows[0]} — expected "
                "'| Date | Round | Business | Dev | Reviewer |'",
            )
        ]
    if len(rows) == 1:
        return [
            Issue(
                "error",
                f"'{REVIEW_RECORD_HEADING}' has no review rows — the "
                "maturity review appends one row per round "
                "(rubric: docs/review-rubric.md)",
            )
        ]

    issues: list[Issue] = []
    parsed: list[acquality.ReviewRow] = []
    previous: int | None = None
    for cells in rows[1:]:
        row = acquality.parse_review_row(cells)
        if isinstance(row, str):
            issues.append(
                Issue("error", f"'{REVIEW_RECORD_HEADING}' row {row}")
            )
            continue
        if previous is not None and row.round <= previous:
            issues.append(
                Issue(
                    "error",
                    f"'{REVIEW_RECORD_HEADING}': round {row.round} does not "
                    f"follow round {previous} — rounds are appended, never "
                    "renumbered",
                )
            )
        previous = row.round
        if row.round >= 2 and row.reviewer.strip().lower() != GAP_VERIFIER:
            issues.append(
                Issue(
                    "error",
                    f"'{REVIEW_RECORD_HEADING}': round {row.round} must be "
                    f"reviewed by '{GAP_VERIFIER}' (rounds 2-3 are the "
                    f"gap-verifier pass), not '{row.reviewer}'",
                )
            )
        parsed.append(row)
    if issues:
        return issues

    # --- judgment (warnings) --------------------------------------------
    last = parsed[-1]
    for axis, score in (("Business", last.business), ("Dev", last.dev)):
        if score < REVIEW_SCORE_THRESHOLD:
            issues.append(
                Issue(
                    "warning",
                    f"{axis} maturity is {score}, below the threshold of "
                    f"{REVIEW_SCORE_THRESHOLD} — run another review round",
                )
            )
    if len(parsed) > REVIEW_ROUND_CAP:
        issues.append(
            Issue(
                "warning",
                f"{len(parsed)} rows: more than {REVIEW_ROUND_CAP} review "
                "rounds — the rubric caps the loop at 3; escalate instead",
            )
        )
    return issues
```

Add `from center_kb import acquality` to `lintcore.py`'s imports. Update the
function docstring: the record's SHAPE is now an error, its SCORES stay
warnings, and say why (a fabricated row should be visible; whether a 4 is
really a 4 is not machine-checkable).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_lintcore.py tests/test_ticketlint.py tests/test_missionlint.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/lintcore.py tests/test_lintcore.py
git commit -m "feat(lint): Review record schema at error level (MEDIUM-3)"
```

---

## Task 9: Mission sections must say something (M8)

A mission with every heading present and every body `TBD` passes today,
mirroring HIGH-1 on the mission side.

**Files:**
- Modify: `src/center_kb/missionlint.py` — add `_check_required_filled`,
  wire into `lint():296-380`
- Test: `tests/test_missionlint.py`

**Interfaces:**
- Consumes: `acquality.is_unfilled`, `lintcore.visible_body`,
  `lintcore.section_body`, `mission.REQUIRED_MISSION_HEADINGS`.
- Produces: `lint()` keeps its signature.

- [ ] **Step 1: Write the failing test**

`tests/test_missionlint.py` already has `_build_mission(block, *,
skip=None, title=..., mission_line=..., overrides=None, extra=None)` over
`_default_sections(block)` (`:207-306`), plus `_hub`, `_errors` and
`_warnings`. Use them.

```python
def test_a_mission_of_placeholders_fails(fed_hub: Path, golden_block: str):
    """M8: structure intact, every body 'TBD' — PASS before 0.22.0."""
    text = _build_mission(
        golden_block,
        overrides={
            "## Business goal": "TBD",
            "## Scope": "",
            "## Constraints & assumptions": "chưa rõ",
        },
    )
    report = missionlint.lint(text, _hub(fed_hub))
    assert report.passed is False
    for heading in (
        "## Business goal",
        "## Scope",
        "## Constraints & assumptions",
    ):
        assert (
            f"'{heading}' is empty or only placeholder text — fill it in"
            in _errors(report)
        )


def test_a_filled_mission_reports_no_placeholder_errors(
    fed_hub: Path, golden_block: str
):
    report = missionlint.lint(_build_mission(golden_block), _hub(fed_hub))
    assert not [m for m in _errors(report) if "only placeholder" in m]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_missionlint.py -q -k placeholders`
Expected: FAIL — the placeholder mission passes.

- [ ] **Step 3: Implement**

```python
# Required sections with a stronger, section-specific check of their own.
_FILL_EXEMPT: frozenset[str] = frozenset(
    {
        "## KB context",                # check_context_block
        "## System context (C4 L1)",    # check_diagram
        "## Containers (C4 L2)",        # check_diagram
        "## US backlog",                # check_backlog
    }
)


def _check_required_filled(text: str) -> list[Issue]:
    """A required section that says nothing is not a section (M8)."""
    issues: list[Issue] = []
    for heading in mission.REQUIRED_MISSION_HEADINGS:
        if heading in _FILL_EXEMPT:
            continue
        body = lintcore.section_body(text, heading)
        if body is None:
            continue  # missing heading — already reported by check_headings
        if acquality.is_unfilled(lintcore.visible_body(body)):
            issues.append(
                Issue(
                    "error",
                    f"'{heading}' is empty or only placeholder text — "
                    "fill it in",
                )
            )
    return issues
```

Add `from center_kb import acquality` to the module imports, and call
`issues += _check_required_filled(text)` in `lint()` directly after
`check_headings`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_missionlint.py tests/test_cli_mission.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/missionlint.py tests/test_missionlint.py
git commit -m "feat(mission lint): required sections must say something (M8)"
```

---

## Task 10: `--fail-on-stale` and exit code 2 (MEDIUM-2, L4)

An amendment to a cited aviation standard turns no BA gate red:
`kb ticket lint` reports stale as a warning and exits 0, while
`QUICKSTART-ba.md:111-129` tells the BA that CI enforces *"no broken,
malformed, or stale refs"*. The default stays as the 2026-07-17 spec chose;
the flag makes the documented behaviour available, and the document stops
claiming what the code does not do.

**Files:**
- Modify: `src/center_kb/doctor.py` — `Issue` gains `code`;
  `check_context:177-195` gains `stale_level`
- Modify: `src/center_kb/lintcore.py` — `check_context_block` gains
  `fail_on_stale`; `LintReport` gains `stale_errors`
- Modify: `src/center_kb/ticketlint.py:226`, `src/center_kb/missionlint.py:296`
  — `lint()` gains `fail_on_stale`
- Modify: `src/center_kb/cli.py:2077` and `:2196` — the flag and exit codes
- Modify: `src/center_kb/templates/init/QUICKSTART-ba.md:111-129`
- Test: `tests/test_lintcore.py`, `tests/test_cli_ticket.py`,
  `tests/test_cli_mission.py`, `tests/test_templates.py`

**Interfaces:**
- Produces:
  - `doctor.Issue(level, message, code="")` — a defaulted third field; every
    existing construction stays valid.
  - `doctor.check_context(text, hub, *, stale_level: Literal["warning",
    "error"] = "warning")`
  - `lintcore.check_context_block(text, hub, *, fail_on_stale: bool = False)`
  - `LintReport.stale_errors: int` (property)
  - `ticketlint.lint(text, hub, *, path=None, missions_dir=None,
    fail_on_stale=False)`; `missionlint.lint(text, hub, *, path=None,
    tickets_dir=None, fail_on_stale=False)`

- [ ] **Step 1: Write the failing tests**

In `tests/test_ticketlint.py`, next to the existing `test_stale_ref_warns`
(`:337-349`), which is also the recipe for making a ref stale — append a
line to a published L2 file under `fed_hub/federation/…` after the block is
pinned:

```python
def _make_stale(fed_hub: Path) -> None:
    l2 = fed_hub / "federation" / "icao-kb" / "icao-annex-2" / "ch1.md"
    l2.write_text(
        l2.read_text(encoding="utf-8") + "\nEdited after publish.\n",
        encoding="utf-8",
    )


def test_fail_on_stale_promotes_the_warning_to_an_error(
    fed_hub: Path, golden_block: str
):
    text = _build_ticket(golden_block)
    _make_stale(fed_hub)
    report = ticketlint.lint(text, _hub(fed_hub), fail_on_stale=True)
    assert report.passed is False
    assert report.stale_errors == 1


def test_stale_errors_counts_only_stale_refs(
    fed_hub: Path, golden_block: str
):
    """Exit code 2 means 'nothing wrong but the upstream moved', so the
    count must exclude every other error."""
    text = _build_ticket(golden_block, skip="## Use cases")
    _make_stale(fed_hub)
    report = ticketlint.lint(text, _hub(fed_hub), fail_on_stale=True)
    errors = len(_errors(report))
    assert report.stale_errors == 1
    assert errors > 1
```

In `tests/test_cli_ticket.py` (the module already defines
`runner = CliRunner()` at `:18` and `_golden_block(fed_hub)` at `:21`):

```python
def test_lint_exits_2_when_only_the_ref_is_stale(fed_hub, tmp_path):
    block = _golden_block(fed_hub)
    path = tmp_path / "M-airspace-US1.md"
    path.write_text(_ticket(block), encoding="utf-8")
    _make_stale(fed_hub)

    result = runner.invoke(
        app,
        ["ticket", "lint", str(path), "--hub", str(fed_hub),
         "--fail-on-stale"],
    )
    assert result.exit_code == 2


def test_lint_exits_1_when_something_else_also_fails(fed_hub, tmp_path):
    block = _golden_block(fed_hub)
    path = tmp_path / "M-airspace-US1.md"
    path.write_text(
        _ticket(block).replace("## Use cases", "## Use case"), encoding="utf-8"
    )
    _make_stale(fed_hub)

    result = runner.invoke(
        app,
        ["ticket", "lint", str(path), "--hub", str(fed_hub),
         "--fail-on-stale"],
    )
    assert result.exit_code == 1


def test_lint_exits_0_on_a_stale_ref_without_the_flag(fed_hub, tmp_path):
    block = _golden_block(fed_hub)
    path = tmp_path / "M-airspace-US1.md"
    path.write_text(_ticket(block), encoding="utf-8")
    _make_stale(fed_hub)

    result = runner.invoke(
        app, ["ticket", "lint", str(path), "--hub", str(fed_hub)]
    )
    assert result.exit_code == 0
```

`_ticket(block)` is whatever the module already uses to render a passing
ticket (`_broken_ref_ticket`'s sibling at `tests/test_cli_ticket.py:29`);
reuse it rather than adding a third builder, and copy `_make_stale` from
the ticketlint module or lift it into `tests/conftest.py` if both files
need it.

In `tests/test_templates.py`:

```python
def test_quickstart_ba_does_not_claim_ci_enforces_stale_refs():
    text = _read_init_template("QUICKSTART-ba.md")
    enforced, _, not_enforced = text.partition("What lint does **not** enforce")
    assert "stale" not in enforced.lower()
    assert "stale" in not_enforced.lower()
    assert "--fail-on-stale" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_lintcore.py tests/test_cli_ticket.py -q -k stale`
Expected: FAIL — `fail_on_stale` is not a parameter; `stale_errors` does not
exist.

- [ ] **Step 3: Implement**

`doctor.py` — add the field and the level parameter:

```python
@dataclass
class Issue:
    level: Literal["error", "warning"]
    message: str
    # A stable machine tag for the checks a caller needs to tell apart —
    # today only "stale-ref", so `kb ticket lint --fail-on-stale` can
    # report exit code 2 ("only staleness failed") the way `kb resolve`
    # does. Defaulted, so every existing construction is unchanged.
    code: str = ""
```

```python
def check_context(
    text: str,
    hub: "HubHandle",
    *,
    stale_level: Literal["error", "warning"] = "warning",
) -> tuple[list[Issue], list[ResolvedRef]]:
    ...
        elif r.status == "stale":
            issues.append(Issue(stale_level, f"{r.ref}: {r.reason}", "stale-ref"))
```

`lintcore.py`:

```python
@property
def stale_errors(self) -> int:
    """Errors that exist only because `--fail-on-stale` promoted them."""
    return sum(
        1 for i in self.issues if i.level == "error" and i.code == "stale-ref"
    )
```

```python
def check_context_block(
    text: str, hub: "HubHandle | None", *, fail_on_stale: bool = False
) -> tuple[list[Issue], KBContext | None]:
    ...
        ctx_issues, _results = check_context(
            text, hub, stale_level="error" if fail_on_stale else "warning"
        )
```

`ticketlint.lint` / `missionlint.lint`: add the keyword-only
`fail_on_stale: bool = False` parameter and pass it through to
`check_context_block`.

`cli.py`, both commands — add the option:

```python
    fail_on_stale: bool = typer.Option(
        False,
        "--fail-on-stale",
        help="Treat a stale ref (the cited content changed upstream since "
        "the pinned commit) as an error; exit 2 when that is the only "
        "failure, mirroring `kb resolve`",
    ),
```

and replace the trailing `if not report.passed: raise typer.Exit(1)` with:

```python
    if report.passed:
        return
    errors = sum(1 for i in report.issues if i.level == "error")
    # Mirror `kb resolve`: 2 means "everything resolves, but the cited
    # content moved", which a caller may want to treat differently from a
    # ticket that is simply not ready.
    raise typer.Exit(2 if report.stale_errors == errors else 1)
```

`QUICKSTART-ba.md:111-129` — move the two false bullets. Under **"DoR rules
(what CI enforces)"** keep only what the gate does; under *"What lint does
**not** enforce"* add:

```markdown
- **Stale refs.** A ref still resolves after the cited section is amended
  upstream; lint reports it as a warning and exits 0. Run
  `kb ticket lint <file> --fail-on-stale` (exit 2 when staleness is the only
  failure) or set the repo variable `KB_FAIL_ON_STALE` to make the CI gate
  do it for you. `kb resolve <file> --status-only` reports the same thing on
  its own.
- **The reverse citation direction.** A pinned ref that the body never cites
  is a warning, not an error — the pin may be background the ticket did not
  need to quote.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_lintcore.py tests/test_cli_ticket.py tests/test_cli_mission.py tests/test_templates.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb tests/
git commit -m "feat(lint): --fail-on-stale with exit code 2, and an honest QUICKSTART (MEDIUM-2)"
```

---

## Task 11: `.local.md` overrides for the rubric (MEDIUM-5)

`kb init --kind ba` overwrites `docs/review-rubric.md`, the file whose own
line 7 says *"Edit this file to tune the criteria for your domain"*, and
`docs/ac-quality.md` with it. The dev side already solved this:
`conventions.py:121-139` creates a `.local.md` stub once and never touches
it again.

**Files:**
- Create: `src/center_kb/templates/init/review-rubric-local-stub.md`
- Create: `src/center_kb/templates/init/ac-quality-local-stub.md`
- Modify: `src/center_kb/initcmd.py` — add `scaffold_ba_local_overrides`,
  call it from the BA branch
- Modify: all 8 BA wrapper templates (`claude-skill-ba-ticket-author.md`,
  `claude-command-ba-ticket-author.md`,
  `copilot-ba-ticket-author.prompt.md`, `cursor-ba-ticket-author.md`, and
  the four `ba-mission-plan` equivalents)
- Test: `tests/test_init.py`, `tests/test_templates.py`

**Interfaces:**
- Consumes: `initcmd._write`, `initcmd._template_text`, `InitReport`.
- Produces: `initcmd.scaffold_ba_local_overrides(target: Path, report:
  InitReport) -> None`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_init.py` (the module calls `initcmd.init_repo(target, kind)`
and compares against `expected_files(kind)`):

```python
def test_ba_init_creates_the_local_override_stubs(tmp_path):
    initcmd.init_repo(tmp_path, "ba")
    assert (tmp_path / "docs" / "review-rubric.local.md").is_file()
    assert (tmp_path / "docs" / "ac-quality.local.md").is_file()


def test_ba_reinit_never_touches_a_local_override(tmp_path):
    initcmd.init_repo(tmp_path, "ba")
    local = tmp_path / "docs" / "review-rubric.local.md"
    local.write_text(
        "# our own criteria\n- [ ] cites an AIP\n", encoding="utf-8"
    )
    before = local.read_bytes()

    report = initcmd.init_repo(tmp_path, "ba")

    assert local.read_bytes() == before
    assert any(
        "local overrides — never refreshed" in entry
        for entry in report.skipped
    )


def test_ba_reinit_still_refreshes_the_base_rubric(tmp_path):
    initcmd.init_repo(tmp_path, "ba")
    base = tmp_path / "docs" / "review-rubric.md"
    base.write_text("clobbered\n", encoding="utf-8")

    initcmd.init_repo(tmp_path, "ba")

    assert "Maturity review rubric" in base.read_text(encoding="utf-8")
```

In `tests/test_templates.py` (`BA_WRAPPERS` at `:1090` is the 8-name tuple;
`_read_init_template` at `:42`):

```python
@pytest.mark.parametrize("name", BA_WRAPPERS)
def test_every_ba_wrapper_names_the_local_override(name):
    text = _read_init_template(name)
    assert "docs/review-rubric.local.md" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_init.py -q -k local_override`
Expected: FAIL — the stubs are not created.

- [ ] **Step 3: Implement**

`review-rubric-local-stub.md`:

```markdown
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
```

`ac-quality-local-stub.md`:

```markdown
# AC quality — local additions

Domain phrases your ACs must not use, and the wording you want instead.
`kb init` creates this file once and never rewrites it.

The review agents read `docs/ac-quality.md` first, then this file. Note
that `kb ticket lint`'s automatic weasel-phrase warnings come from the
CLI's built-in list; phrases you add here are enforced by the review
agents, not by lint.

| Banned phrase | Write this instead |
|---|---|
<!-- | "handled by the system" | name the component and the outcome | -->
```

In `initcmd.py`, next to `BA_TEMPLATES:74`. Note that `initcmd` has no
`_write`/`_template_text` helpers of its own — `init_repo:327` inlines the
resource read — so this adds one small reader rather than importing
`conventions`' private helpers:

```python
# Created once, never refreshed: the BA's own review criteria. Deliberately
# NOT in BA_TEMPLATES (that map is create-or-refresh) and NOT in
# PROTECTED_FILES (that set means "never written", which would freeze the
# BASE rubric at whatever version first scaffolded a repo). Same contract
# `conventions.scaffold_conventions` gives the dev side's
# `docs/conventions/<lang>.local.md` (C11).
BA_LOCAL_OVERRIDES: dict[str, str] = {
    "docs/review-rubric.local.md": "review-rubric-local-stub.md",
    "docs/ac-quality.local.md": "ac-quality-local-stub.md",
}


def _init_template_text(name: str) -> str:
    return (
        resources.files("center_kb")
        .joinpath("templates/init")
        .joinpath(name)
        .read_text(encoding="utf-8")
    )


def scaffold_ba_local_overrides(target: Path, report: InitReport) -> None:
    """Create the BA repo's `.local.md` override files once, then never
    touch them again. The base files stay package-owned and keep being
    refreshed, so a BA repo receives improved criteria on upgrade without
    losing its own."""
    for rel, resource_name in BA_LOCAL_OVERRIDES.items():
        dest = target / rel
        if dest.exists():
            report.skipped.append(f"{rel} (local overrides — never refreshed)")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            _init_template_text(resource_name), encoding="utf-8", newline="\n"
        )
        report.created.append(rel)
```

In `init_repo`, beside the existing dev-kind post-step
(`if kind == KIND_DEV: conventions.scaffold_conventions(...)`):

```python
    if kind == KIND_BA:
        scaffold_ba_local_overrides(target, report)
```

`expected_files("ba")` is `list(template_map("ba"))` and these two files are
not in that map, so the existing BA scaffold assertion
(`sorted(report.created) == sorted(expected_files("ba"))`, `tests/test_init.py`)
now sees two extra entries. Update that one assertion to
`sorted(expected_files("ba")) + sorted(initcmd.BA_LOCAL_OVERRIDES)` — sorted
as one list — rather than folding the stubs into the template map, which
would make them refreshable and undo the whole point.

In each of the 8 BA wrappers, in the maturity-review step where the rubric
is named, replace the rubric reference with:

```markdown
Read `docs/review-rubric.md`, then `docs/review-rubric.local.md` if it
exists — the local file overrides the base one. Same for
`docs/ac-quality.md` and `docs/ac-quality.local.md`.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_init.py tests/test_templates.py -q`
Expected: PASS, once the BA scaffold assertion described in Step 3 accounts
for the two stubs. `expected_files("ba")` itself does not change.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb tests/
git commit -m "feat(init): .local.md overrides for the BA rubric and AC quality list (MEDIUM-5)"
```

---

## Task 12: Templates, wrappers and docs use the bracketed citation

Task 3 changed what the gate parses. The scaffold must teach it, or every
newly authored ticket collects migration warnings from its first line.

**Files:**
- Modify: `src/center_kb/templates/init/ticket-template.md:14`, `:23`
- Modify: `src/center_kb/templates/init/mission-template.md` (the citation
  guidance lines)
- Modify: all 8 BA wrappers — the "no citation, no claim" rule and every
  example citation
- Modify: `src/center_kb/templates/init/review-rubric.md`,
  `src/center_kb/templates/init/ac-quality.md`,
  `src/center_kb/templates/init/QUICKSTART-ba.md`
- Test: `tests/test_templates.py`

**Interfaces:**
- Consumes: `lintcore.BRACKET_CITE_RE` (Task 3) — the tests assert the
  templates' examples match it.
- Produces: nothing in code.

- [ ] **Step 1: Write the failing tests**

```python
_CITATION_TEMPLATES = (
    "ticket-template.md",
    "mission-template.md",
    "review-rubric.md",
    "ac-quality.md",
    "QUICKSTART-ba.md",
    *BA_WRAPPERS,
)


@pytest.mark.parametrize("name", _CITATION_TEMPLATES)
def test_every_citation_example_is_bracketed(name):
    """A template that teaches the bare form teaches a migration
    warning."""
    text = _read_init_template(name)
    bare = [
        m.group(0)
        for m in lintcore.INLINE_CITE_RE.finditer(
            lintcore.BRACKET_CITE_RE.sub("", text)
        )
    ]
    assert bare == []


def test_the_ticket_template_shows_the_bracketed_form():
    assert "[doc-id §section]" in _read_init_template("ticket-template.md")
```

`INLINE_CITE_RE` is deliberately loose, so this test can flag prose in a
wrapper that merely looks like `<word> §<token>`. That is the point — if a
sentence trips it, a BA copying that sentence would trip the migration
warning too. Reword the sentence rather than narrowing the test.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_templates.py -q -k citation`
Expected: FAIL — `ticket-template.md:14` reads
`` every industry-standard claim cites `doc-id §section` ``.

- [ ] **Step 3: Implement**

In `ticket-template.md`, line 14 and line 23:

```markdown
## Background / Business context
<context; every industry-standard claim cites `[doc-id §section]`>
```

```markdown
- [ ] AC1 … (cite `[doc-id §section]` when it touches a standard)
```

Add to the `## Acceptance Criteria` guidance comment:

```markdown
Citations are bracketed: `[arinc-424 §5.129]`. Prose that merely names a
standard ("per ARINC 424") is not a citation and the gate ignores it.
```

Make the same substitution everywhere a citation appears in
`mission-template.md`, the 8 wrappers (including the `no citation, no
claim` rule), `review-rubric.md`, `ac-quality.md` and `QUICKSTART-ba.md`.
Add one line to `QUICKSTART-ba.md`'s DoR rules:

```markdown
- Citations are written `[doc-id §section]`. A citation in the old bare
  form still counts, with a warning telling you to bracket it.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_templates.py tests/test_init.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/templates tests/test_templates.py
git commit -m "docs(templates): teach the bracketed [doc-id §section] citation"
```

---

## Task 13: The scaffolded CI gate (MEDIUM-6)

`kb-ticket-lint.yml:40` installs `center-kb` unpinned, so a PyPI release can
turn every open BA PR red with no repo change — the exact argument
`_gate.yml:26-33` makes against unpinned lint tooling. It has no
`concurrency:` block, prints failures inside a collapsed `::group::`, and
mangles a non-`https://` hub at `:44`.

**Files:**
- Modify: `src/center_kb/templates/init/kb-ticket-lint.yml`
- Modify: `src/center_kb/templates/init/kb-pr-lint.yml:48`
- Modify: `src/center_kb/templates/init/QUICKSTART-ba.md`
- Test: `tests/test_init.py`, `tests/test_templates.py`

**Interfaces:**
- Consumes: `initcmd._render:263-288`, which already substitutes
  `{version}` in every non-`config-` template — adding the placeholder is
  the whole change on the Python side.
- Produces: nothing in code.

- [ ] **Step 1: Write the failing tests**

In `tests/test_init.py` (this is the pinning assertion the `kb-code.yml` and
`kb-publish.yml` tests already make — copy their shape):

```python
from importlib.metadata import version as _dist_version


@pytest.mark.parametrize(
    ("kind", "workflow"),
    [("ba", "kb-ticket-lint.yml"), ("dev", "kb-pr-lint.yml")],
)
def test_scaffolded_workflows_pin_the_cli(tmp_path, kind, workflow):
    initcmd.init_repo(tmp_path, kind)
    text = (tmp_path / ".github" / "workflows" / workflow).read_text(
        encoding="utf-8"
    )
    assert f"pip install center-kb=={_dist_version('center-kb')}" in text
    assert "{version}" not in text
```

In `tests/test_templates.py`:

```python
def test_ticket_lint_workflow_has_a_concurrency_block():
    assert "concurrency:" in _read_init_template("kb-ticket-lint.yml")


def test_ticket_lint_workflow_annotates_and_summarises():
    text = _read_init_template("kb-ticket-lint.yml")
    assert "--json" in text
    assert "GITHUB_STEP_SUMMARY" in text
    assert "::error file=" in text


def test_ticket_lint_workflow_keeps_a_non_https_hub_scheme():
    assert "${CENTER_KB_HUB#https://}" not in _read_init_template(
        "kb-ticket-lint.yml"
    )


def test_quickstart_ba_documents_the_ci_variables():
    text = _read_init_template("QUICKSTART-ba.md")
    assert "vars.CENTER_KB_HUB" in text
    assert "secrets.KB_HUB_TOKEN" in text
    assert "fork" in text.lower()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_init.py tests/test_templates.py -q -k "workflow or quickstart"`
Expected: FAIL on every assertion.

- [ ] **Step 3: Implement**

In `kb-ticket-lint.yml`:

```yaml
concurrency:
  # One in-flight run per PR: a force-push should cancel the old gate, not
  # race it. Mirrors this project's own ci.yml.
  group: kb-ticket-lint-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true
```

```yaml
      - run: pip install center-kb=={version}
```

Replace the token step's substitution so any scheme survives:

```yaml
      - name: Authenticate the hub URL (private hub only)
        if: env.KB_HUB_TOKEN != ''
        run: |
          # Split the scheme off generically and put it back: '#https://'
          # mangled every hub that was not https (a self-hosted http hub
          # became 'https://x-access-token:…@http://host/hub').
          scheme="${CENTER_KB_HUB%%://*}"
          rest="${CENTER_KB_HUB#*://}"
          echo "CENTER_KB_HUB=${scheme}://x-access-token:${KB_HUB_TOKEN}@${rest}" >> "$GITHUB_ENV"
```

Replace the per-file lint invocation so a failure is visible without
expanding anything, and honour the opt-in stale flag:

```yaml
            flags=""
            if [ -n "${KB_FAIL_ON_STALE}" ]; then flags="--fail-on-stale"; fi
            echo "::group::$cmd $f"
            if $cmd "$f" --hub "$CENTER_KB_HUB" $flags --json > "$RUNNER_TEMP/report.json"; then
              verdict="PASS"
            else
              rc=$?
              verdict="FAIL"
              [ "$rc" -eq 2 ] && verdict="STALE"
              status=1
            fi
            python - "$f" "$verdict" <<'PY' >> "$GITHUB_STEP_SUMMARY"
          import json, os, sys
          path, verdict = sys.argv[1], sys.argv[2]
          report = json.load(open(os.environ["RUNNER_TEMP"] + "/report.json"))
          print(f"| `{path}` | {verdict} | {len(report['errors'])} | {len(report['warnings'])} |")
          for message in report["errors"]:
              print(f"::error file={path}::{message}", file=sys.stderr)
          PY
            cat "$RUNNER_TEMP/report.json"
            echo "::endgroup::"
```

Add the step-summary table header before the loop, and
`KB_FAIL_ON_STALE: ${{ vars.KB_FAIL_ON_STALE }}` to the job's `env:`.

In `kb-pr-lint.yml:48`, change to `pip install center-kb=={version}`.

In `QUICKSTART-ba.md`, add a CI configuration subsection:

```markdown
### Configuring the CI gate

The scaffolded `kb-ticket-lint` workflow reads two repository settings:

| Setting | Where | What it is |
|---|---|---|
| `CENTER_KB_HUB` | Settings → Secrets and variables → Actions → **Variables** | The hub URL or path the gate resolves refs against |
| `KB_HUB_TOKEN` | same page → **Secrets** | A token with read access, for a private hub only |
| `KB_FAIL_ON_STALE` | **Variables**, optional | Set to any value to make an upstream amendment fail the gate |

A pull request opened **from a fork** cannot read repository secrets, so on
a private hub the gate fails there with a hub-unreachable message. That is
the gate refusing to go green without checking, not a network fault — merge
fork contributions through a branch in this repository, or make the hub
readable without a token.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_init.py tests/test_templates.py -q`
Expected: PASS. Then lint the workflow by eye against
`templates/init/kb-code.yml`, which already carries the pinned-install
idiom.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/templates tests/
git commit -m "fix(ci template): pin the CLI, add concurrency, surface failures (MEDIUM-6)"
```

---

## Task 14: Release 0.22.0 — changelog, full suite, real-repo validation

**Files:**
- Modify: `pyproject.toml:3`
- Modify: `CHANGELOG.md`
- Test: the full suite

**Interfaces:**
- Consumes: everything above.
- Produces: the released contract.

- [ ] **Step 1: Bump the version**

`pyproject.toml:3`: `version = "0.22.0"`.

- [ ] **Step 2: Write the changelog entry**

At the top of `CHANGELOG.md`, following the file's existing format:

```markdown
## 0.22.0

### Breaking — the BA Definition-of-Ready gate now reads section bodies

A ticket or mission that passed 0.21.0 on structure alone can fail here.
Run `kb ticket lint` over your open tickets before upgrading CI.

- Required sections that are empty or hold only placeholder text
  (`TBD`, `TODO`, `N/A`, `chưa rõ`, …) are errors.
- `## Acceptance Criteria` needs at least 2 items, unique ids, and each AC
  must carry a Given/When/Then triple, a measurable value, or an owned
  `OPEN(<owner>)`. `OPEN(TBD)` and `OPEN(?)` no longer count as owned.
- `## Non-functional requirements` rows need a number or an owned
  `OPEN(...)` in Target; `## Definition of Ready` needs its checklist rows
  (unticked boxes stay a warning).
- A `mermaid` fence must contain a relationship — an arrow or a C4
  `Rel(...)`.
- `## Review record` rows must match the shipped table: five filled cells,
  scores 1–5, increasing round numbers, `gap-verifier` from round 2. Scores
  below 4 and a fourth round remain warnings.
- **Citations are `[doc-id §section]`.** The bare `doc-id §section` form is
  no longer parsed as a citation; when it names a pinned ref it gets a
  warning telling you to bracket it. Natural prose such as
  `per ARINC 424 §5.129` no longer fails the gate.
- Two `kb-context:` blocks in one document is an error.

### Added

- `kb ticket lint --fail-on-stale` / `kb mission lint --fail-on-stale`:
  a stale ref becomes an error and the command exits 2 when that is the only
  failure, mirroring `kb resolve`. The scaffolded CI gate passes the flag
  when the repository variable `KB_FAIL_ON_STALE` is set.
- `kb init --kind ba` scaffolds `docs/review-rubric.local.md` and
  `docs/ac-quality.local.md` once and never refreshes them.

### Fixed

- `section_body` no longer ends a section at a `#` line inside a fenced
  block, so valid tickets stopped being rejected.
- Heading and citation scanning ignore HTML comments: commented-out
  sections read as missing, and a citation inside a comment is neither a
  citation nor an error.
- The scaffolded `kb-ticket-lint` and `kb-pr-lint` workflows pin
  `center-kb==<version>`, carry a `concurrency:` block, surface failures as
  annotations and a step summary, and keep a non-`https://` hub scheme
  intact.
```

- [ ] **Step 3: Run the full suite and the linter**

Run: `.venv/Scripts/python -m ruff check .`
Run: `.venv/Scripts/python -m pytest -q`
Expected: ruff clean; the suite green in 10–19 minutes. Fix anything red
before continuing — a fixture that needs filling in is the expected kind of
failure here.

- [ ] **Step 4: Validate against real BA tickets**

Run the new gate over KrisShop's real BA tickets (the validation repo for
this framework — it is a real git repo, unlike KS-BA):

```bash
for f in <krisshop-ba-repo>/tickets/*.md; do
  .venv/Scripts/python -m center_kb ticket lint "$f" --hub "$CENTER_KB_HUB" --json
done
```

Record the pass/fail counts and the most common error message in the PR
description. This is the evidence that "error level in one release" was the
right call — or the signal that a specific rule is over-strict and needs a
follow-up.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml CHANGELOG.md
git commit -m "chore: release 0.22.0 — BA gate reads section bodies"
```

---

## Deferred, by name

These stay live findings from reviewer E's report; they are **not** part of
this plan and must not be picked up opportunistically:

- MEDIUM-3's trip-wire tests (ticket-wrapper parity, the 3-round cap and
  `≥ 4` threshold strings across all 8 wrappers, a numeric pin on
  `len(expected_files("ba"))`, the stale `BA_TICKET_AUTHOR_PIPELINE_STEPS`
  7-tuple).
- MEDIUM-7: the "500–800 token" search budget no wrapper's example passes.
- MEDIUM-4 item 5: `acquality` reading its deny-list from
  `docs/ac-quality.md`.
- L2, L3, L6, L8, L9, L10.
- Installing the scaffolded gate into this repo's own `.github/workflows/`.
