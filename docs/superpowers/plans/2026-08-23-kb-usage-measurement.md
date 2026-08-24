# `kb usage` Measurement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every ticket's token and money cost visible in the repository that produced it — captured automatically from Claude Code transcripts, stored as an append-only ledger in git, and readable as a static HTML page.

**Architecture:** A new package `src/center_kb/usage/` with four modules that each know one thing: `ledger.py` owns the on-disk row shape, `transcript.py` turns a Claude Code transcript into rows using two attribution cursors, `prices.py` turns a model id into rates, `report.py` aggregates and renders. A `usage_app` sub-typer exposes three commands. A scaffolded `Stop` hook calls `kb usage ingest-transcript --hook-stdin` once per turn. No MCP tool is added and no skill wrapper is edited.

**Tech Stack:** Python 3.11+, pydantic v2, typer, Jinja2, PyYAML, pytest. All already dependencies — **this plan adds none**.

**Spec:** `docs/superpowers/specs/2026-08-23-kb-usage-measurement-design.md`

## Global Constraints

- **No new dependency.** `jinja2`, `PyYAML`, `pydantic`, `typer` are already in `pyproject.toml:18-28`. Nothing else may be added.
- **No sixth MCP tool, and no change to any existing tool's signature or docstring.** `tests/test_mcp.py` must pass untouched, as must the real MCP contract golden — **`tests-gate/golden/mcp_tools.json`**, compared by `tests-gate/regression/test_mcp_contract.py`. (Task 5's review established that `tests/mcp_tools.json`, which this plan originally named, does not exist and that `tests/test_mcp.py` compares no golden. `tests-gate/` sits outside `testpaths`, so a plain `pytest` run never reaches it.) A golden break is a defect signal, never a reason to regenerate the golden.
- **No skill-wrapper edit.** `tests/test_templates.py` (canon) must pass untouched. Wiring usage into `dev-handover` / `ba-ticket-author` is roadmap B4 and belongs to the shared template round.
- **One deliberate trip-wire bump:** `tests/test_init.py:1432` reads `assert len(expected_files("dev")) == 43` and becomes `44`. That is the only numeric scaffold pin in the suite; kind `ba` is asserted against the derived list (`tests/test_init.py:681`) and needs no number change.
- **A stem read out of transcript content is untrusted input.** It becomes a filename, so it is accepted only when it matches `^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$`; `.kb/usage/<stem>.jsonl` must never escape `.kb/usage/`.
- **Ticket ids are file stems and are never validated against `M-<slug>-US<n>`.** Real tickets are named `open-new-flight.md`. Validating against `mission.us_id_re` (`src/center_kb/mission.py:88`) would discard every real ticket.
- **Never infer a phase from skill names appearing in message content.** Only a `<command-name>` marker or a `Skill` tool call counts. A session that edits the dev skills mentions `dev-handover` 339 times while running something else.
- **In `--hook-stdin` mode the process always exits 0.** A `Stop` hook exiting non-zero blocks Claude from ending its turn.
- Python style as the rest of the repo: `from __future__ import annotations`, type hints, deferred imports inside CLI command bodies.
- Commit messages follow conventional commits (`feat:`, `fix:`, `test:`, `docs:`, `chore:`).

## File Structure

**Create:**

| File | Responsibility |
|---|---|
| `src/center_kb/usage/__init__.py` | Empty package marker (the modules are imported by path, as `codeingest/` does). |
| `src/center_kb/usage/ledger.py` | `UsageRow` model, stem validation, ledger path resolution, append-with-dedupe, read-back. The only module that knows the on-disk shape. |
| `src/center_kb/usage/transcript.py` | Parse a transcript JSONL; run the ticket and phase cursors; produce `UsageRow`s. Knows nothing about prices or HTML. |
| `src/center_kb/usage/prices.py` | `ModelRates` / `PriceTable`, package default + per-model repo override, per-row cost, staleness. |
| `src/center_kb/usage/report.py` | Aggregate rows into totals; render HTML / Markdown / JSON. |
| `src/center_kb/templates/usage/usage-prices.yaml` | Package default price table. Package data, **not** in `initcmd`'s scaffold map. |
| `src/center_kb/templates/usage/report.html.j2` | Self-contained report template, inline CSS, no JS, no CDN. |
| `src/center_kb/templates/init/claude-settings-usage.json` | The scaffolded `.claude/settings.json` for kinds `ba` and `dev`. |
| `tests/test_usage_ledger.py` | Task 1. |
| `tests/test_usage_transcript.py` | Task 2, including invariant I1 and the anti-test for phase inference. |
| `tests/test_usage_prices.py` | Task 3, including invariant I5's price half. |
| `tests/test_usage_report.py` | Task 4, including invariant I5's report half. |
| `tests/test_cli_usage.py` | Task 5. |

**Modify:**

| File | Change |
|---|---|
| `src/center_kb/cli.py:35-36` | Add `usage_app` next to `svc_app`; add three commands. |
| `src/center_kb/initcmd.py:69-90` (`BA_TEMPLATES`) and `:96-145` (`DEV_TEMPLATES`) | One row each: `.claude/settings.json` → `claude-settings-usage.json`. |
| `src/center_kb/initcmd.py:145` (`PROTECTED_FILES`) | Add `.claude/settings.json`. |
| `src/center_kb/templates/init/QUICKSTART-ba.md`, `QUICKSTART-dev.md` | Document the hook, the ~0.6 s per-turn cost, the CLI reference entries, and backfill. |
| `tests/test_init.py:1432` | `43` → `44`, plus new tests for the scaffolded settings file. |

**Deliberate deviation from the spec, and why:** the spec says fixtures live under `tests/fixtures/transcripts/`. This plan builds each synthetic transcript with a `write_transcript(...)` helper inside the test module instead. The data then sits next to the assertion that depends on it, which matters here because most tests differ by one row; a directory of near-identical JSONL files hides exactly the difference each test is about. The spec's real requirement — *never commit a real transcript* — is preserved.

---

### Task 1: The ledger — row model, stem safety, append with de-duplication

Nothing in this task knows what a transcript is. It is the on-disk contract every later task writes through.

**Files:**
- Create: `src/center_kb/usage/__init__.py`, `src/center_kb/usage/ledger.py`
- Test: `tests/test_usage_ledger.py`

**Interfaces:**
- Consumes: nothing from other tasks. `pydantic.BaseModel`.
- Produces:
  - `class LedgerError(RuntimeError)`
  - `STEM_RE: re.Pattern[str]` — `^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$`
  - `def is_safe_stem(stem: str) -> bool`
  - `class UsageRow(BaseModel)` with fields `uuid: str`, `ts: str`, `session: str`, `actor: str`, `phase: str`, `ticket: str | None`, `model: str`, `tokens_in: int`, `tokens_out: int`, `cache_read: int`, `cache_write_5m: int`, `cache_write_1h: int`, `sidechain: bool`, `branch: str | None`, `assistant: str`, `est: bool`
  - `UNATTRIBUTED = "_unattributed"`
  - `def usage_dir(kb_dir: Path) -> Path` → `kb_dir / "usage"`
  - `def ledger_path(kb_dir: Path, ticket: str | None) -> Path`
  - `class AppendReport` (dataclass) with `written: int`, `duplicates: int`, `files: list[str]`
  - `def append_rows(kb_dir: Path, rows: list[UsageRow]) -> AppendReport`
  - `def read_rows(kb_dir: Path) -> list[UsageRow]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_usage_ledger.py`:

```python
from pathlib import Path

import pytest

from center_kb.usage import ledger


def row(uuid: str, ticket: str | None = "open-new-flight", **kw) -> ledger.UsageRow:
    """A row with every field filled, so a test only states what it varies."""
    base = dict(
        uuid=uuid,
        ts="2026-08-23T09:59:22.432Z",
        session="6c012668-dbc8-4086-a0eb-6fdb6566bc90",
        actor="ba",
        phase="ba-ticket-author",
        ticket=ticket,
        model="claude-sonnet-5",
        tokens_in=4,
        tokens_out=1837,
        cache_read=181392,
        cache_write_5m=0,
        cache_write_1h=3204,
        sidechain=False,
        branch=None,
        assistant="claude-code",
        est=False,
    )
    base.update(kw)
    return ledger.UsageRow(**base)


def test_ledger_path_is_named_after_the_ticket(tmp_path: Path):
    assert ledger.ledger_path(tmp_path, "open-new-flight") == (
        tmp_path / "usage" / "open-new-flight.jsonl"
    )


def test_ledger_path_for_no_ticket_is_the_unattributed_file(tmp_path: Path):
    assert ledger.ledger_path(tmp_path, None) == (
        tmp_path / "usage" / "_unattributed.jsonl"
    )


@pytest.mark.parametrize(
    "stem",
    ["..", ".", "../../etc/passwd", "a/b", "a\\b", "-leading-dash", "", " sp",
     "ok\n", "ok\r"],
)
def test_ledger_path_refuses_a_stem_that_could_escape_the_usage_dir(
    tmp_path: Path, stem: str
):
    # The stem is read out of transcript CONTENT, which is not trusted input.
    with pytest.raises(ledger.LedgerError) as exc:
        ledger.ledger_path(tmp_path, stem)
    assert "ticket id" in str(exc.value)


def test_ledger_path_accepts_the_real_ticket_names(tmp_path: Path):
    # Invariant I4: a real ticket is a file stem, not 'M-<slug>-US<n>'.
    for stem in ("open-new-flight", "remove-witness-crew-stock-transfer"):
        assert ledger.ledger_path(tmp_path, stem).name == f"{stem}.jsonl"


def test_append_writes_one_json_line_per_row(tmp_path: Path):
    report = ledger.append_rows(tmp_path, [row("u1"), row("u2")])

    lines = (tmp_path / "usage" / "open-new-flight.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert report.written == 2
    assert report.duplicates == 0
    assert len(lines) == 2


def test_append_preserves_the_order_rows_were_given_in(tmp_path: Path):
    ledger.append_rows(tmp_path, [row("u1"), row("u2"), row("u3")])

    text = (tmp_path / "usage" / "open-new-flight.jsonl").read_text(encoding="utf-8")
    assert [r.uuid for r in ledger.read_rows(tmp_path)] == ["u1", "u2", "u3"]
    assert text.index("u1") < text.index("u2") < text.index("u3")


def test_append_skips_a_uuid_the_file_already_carries(tmp_path: Path):
    ledger.append_rows(tmp_path, [row("u1"), row("u2")])

    report = ledger.append_rows(tmp_path, [row("u2"), row("u3")])

    assert (report.written, report.duplicates) == (1, 1)
    assert [r.uuid for r in ledger.read_rows(tmp_path)] == ["u1", "u2", "u3"]


def test_append_dedupes_within_one_call_too(tmp_path: Path):
    report = ledger.append_rows(tmp_path, [row("u1"), row("u1")])

    assert (report.written, report.duplicates) == (1, 1)


def test_append_splits_rows_across_files_by_ticket(tmp_path: Path):
    ledger.append_rows(
        tmp_path,
        [
            row("u1", ticket="open-new-flight"),
            row("u2", ticket="remove-witness-crew-stock-transfer"),
            row("u3", ticket=None),
        ],
    )

    names = sorted(p.name for p in (tmp_path / "usage").glob("*.jsonl"))
    assert names == [
        "_unattributed.jsonl",
        "open-new-flight.jsonl",
        "remove-witness-crew-stock-transfer.jsonl",
    ]


def test_a_uuid_never_lands_in_two_files(tmp_path: Path):
    # Invariant I2.
    ledger.append_rows(tmp_path, [row("u1", ticket=None)])
    ledger.append_rows(tmp_path, [row("u1", ticket="open-new-flight")])

    seen = [r.uuid for r in ledger.read_rows(tmp_path)]
    assert seen.count("u1") == 1


def test_read_rows_on_an_empty_repo_is_empty(tmp_path: Path):
    assert ledger.read_rows(tmp_path) == []


def test_read_rows_ignores_a_blank_line(tmp_path: Path):
    ledger.append_rows(tmp_path, [row("u1")])
    path = tmp_path / "usage" / "open-new-flight.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    assert [r.uuid for r in ledger.read_rows(tmp_path)] == ["u1"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_usage_ledger.py -v`
Expected: FAIL at collection — `ModuleNotFoundError: No module named 'center_kb.usage'`.

- [ ] **Step 3: Implement the ledger**

Create `src/center_kb/usage/__init__.py` as an empty file (the package is a namespace for the four modules; `codeingest/` follows the same pattern).

Create `src/center_kb/usage/ledger.py`:

```python
"""ledger — the on-disk shape of `.kb/usage/`.

One row per Claude Code transcript row that carried a `usage` block. Files are
named after the ticket (`<stem>.jsonl`) rather than after the session, so a
ticket's cost travels with the ticket in git history and a PR can carry its own
number (roadmap B4). Rows with no ticket go to `_unattributed.jsonl` so a gap in
attribution is visible instead of being guessed at.

Append-only and de-duplicated by the transcript row's `uuid`: the `Stop` hook
re-ingests the same growing transcript every turn, so appending must be safe to
repeat forever.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

UNATTRIBUTED = "_unattributed"

# A stem is read out of transcript CONTENT and then used as a filename, so it
# is validated, not sanitised: anything that is not obviously a ticket name is
# rejected outright rather than silently rewritten into one.
STEM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")


class LedgerError(RuntimeError):
    """A ticket id cannot be turned into a ledger file name."""


def is_safe_stem(stem: str) -> bool:
    # fullmatch, not match: Python's `$` also matches just before a trailing
    # newline, so `match` would accept "open-new-flight\n" — and a trailing
    # newline is exactly what survives naive line handling of the transcript
    # this stem is read out of. On POSIX that forks one ticket's ledger into
    # two files; on Windows it raises OSError from inside a Stop hook.
    return stem not in {".", ".."} and bool(STEM_RE.fullmatch(stem))


class UsageRow(BaseModel):
    """One API call's usage, as recorded by the assistant that made it.

    `assistant` and `est` exist for the deferred Copilot/Cursor path: those
    assistants have no hook, so their only option is a self-reported estimate,
    and a dashboard must be able to tell a measured row from an estimated one.
    Every row this codebase writes from a transcript has `est=False`.
    """

    uuid: str
    ts: str
    session: str
    actor: str
    phase: str
    ticket: str | None
    model: str
    tokens_in: int
    tokens_out: int
    cache_read: int
    cache_write_5m: int
    cache_write_1h: int
    sidechain: bool
    branch: str | None
    assistant: str
    est: bool


@dataclass
class AppendReport:
    written: int = 0
    duplicates: int = 0
    files: list[str] = field(default_factory=list)


def usage_dir(kb_dir: Path) -> Path:
    return kb_dir / "usage"


def ledger_path(kb_dir: Path, ticket: str | None) -> Path:
    if ticket is None:
        return usage_dir(kb_dir) / f"{UNATTRIBUTED}.jsonl"
    if not is_safe_stem(ticket):
        raise LedgerError(
            f"unusable ticket id '{ticket}' — a ticket id becomes a file name "
            "under .kb/usage/, so it must match "
            "[A-Za-z0-9][A-Za-z0-9._-]{0,80}"
        )
    return usage_dir(kb_dir) / f"{ticket}.jsonl"


def _existing_uuids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    found: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        found.add(json.loads(line)["uuid"])
    return found


def append_rows(kb_dir: Path, rows: list[UsageRow]) -> AppendReport:
    """Append rows to their tickets' ledgers, skipping any uuid already stored.

    De-duplication is global, not per file: a row that moved from
    `_unattributed` to a real ticket on a later ingest would otherwise be
    counted twice (invariant I2).
    """
    report = AppendReport()
    seen: set[str] = set()
    directory = usage_dir(kb_dir)
    if directory.exists():
        for path in sorted(directory.glob("*.jsonl")):
            seen |= _existing_uuids(path)
    buckets: dict[Path, list[UsageRow]] = {}
    for row in rows:
        if row.uuid in seen:
            report.duplicates += 1
            continue
        seen.add(row.uuid)
        buckets.setdefault(ledger_path(kb_dir, row.ticket), []).append(row)
    for path, bucket in buckets.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            for row in bucket:
                fh.write(json.dumps(row.model_dump(mode="json"), ensure_ascii=False))
                fh.write("\n")
        report.written += len(bucket)
        report.files.append(path.name)
    return report


def read_rows(kb_dir: Path) -> list[UsageRow]:
    """Every row in the ledger, files in name order, rows in file order."""
    out: list[UsageRow] = []
    directory = usage_dir(kb_dir)
    if not directory.exists():
        return out
    for path in sorted(directory.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            out.append(UsageRow.model_validate_json(line))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_usage_ledger.py -v`
Expected: PASS, all tests.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/usage/__init__.py src/center_kb/usage/ledger.py tests/test_usage_ledger.py
git commit -m "feat: usage ledger — append-only rows keyed by ticket, deduped by uuid"
```

---

### Task 2: Transcript parsing and the two attribution cursors

The heart of the capture path, and the only place attribution rules live.

**Files:**
- Create: `src/center_kb/usage/transcript.py`
- Test: `tests/test_usage_transcript.py`

**Interfaces:**
- Consumes: `ledger.UsageRow`, `ledger.is_safe_stem` from Task 1.
- Produces:
  - `TICKET_PATH_RE: re.Pattern[str]` — matches `tickets/<stem>.md`, `missions/<stem>.md`, `docs/impl/<stem>-design.md`, `docs/impl/<stem>-plan.md`, with `/` or `\` (repeated, because a Windows path is `\\`-escaped inside JSON) as the separator
  - `COMMAND_RE: re.Pattern[str]` — `<command-name>([^<]{1,80})</command-name>`
  - `PHASE_RE: re.Pattern[str]` — `^(?:ba|dev|kb)-[a-z0-9-]+$`
  - `SYNTHETIC_MODEL = "<synthetic>"`
  - `def rows_from_transcript(path: Path, *, actor: str, session_fallback: str = "", forced_ticket: str | None = None) -> list[UsageRow]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_usage_transcript.py`:

```python
import json
from pathlib import Path

from center_kb.usage import transcript


def usage_row(uuid: str, *, model: str = "claude-sonnet-5", out: int = 100, **kw):
    """An assistant row shaped like Claude Code writes it."""
    row = {
        "type": "assistant",
        "uuid": uuid,
        "sessionId": "sess-1",
        "timestamp": "2026-08-23T09:59:22.432Z",
        "gitBranch": "feat/x",
        "isSidechain": False,
        "message": {
            "model": model,
            "usage": {
                "input_tokens": 7,
                "output_tokens": out,
                "cache_read_input_tokens": 1000,
                "cache_creation_input_tokens": 300,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 0,
                    "ephemeral_1h_input_tokens": 300,
                },
            },
        },
    }
    row.update(kw)
    return row


def user_row(text: str, **kw):
    row = {
        "type": "user",
        "uuid": f"u-{abs(hash(text)) % 10**8}",
        "sessionId": "sess-1",
        "timestamp": "2026-08-23T09:59:00.000Z",
        "message": {"role": "user", "content": text},
    }
    row.update(kw)
    return row


def skill_call_row(skill: str):
    return {
        "type": "assistant",
        "uuid": f"s-{skill}",
        "sessionId": "sess-1",
        "timestamp": "2026-08-23T09:58:00.000Z",
        "message": {
            "model": "claude-sonnet-5",
            "content": [
                {"type": "tool_use", "name": "Skill", "input": {"skill": skill}}
            ],
        },
    }


def write_transcript(tmp_path: Path, rows: list[dict], name: str = "t.jsonl") -> Path:
    path = tmp_path / name
    path.write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8", newline="\n"
    )
    return path


def test_a_usage_row_becomes_a_ledger_row_with_the_numbers_copied(tmp_path: Path):
    path = write_transcript(tmp_path, [usage_row("a1")])

    (row,) = transcript.rows_from_transcript(path, actor="ba")

    assert (row.uuid, row.model, row.actor) == ("a1", "claude-sonnet-5", "ba")
    assert (row.tokens_in, row.tokens_out) == (7, 100)
    assert (row.cache_read, row.cache_write_5m, row.cache_write_1h) == (1000, 0, 300)
    assert row.assistant == "claude-code"
    assert row.est is False  # invariant I3


def test_rows_without_a_usage_block_are_ignored(tmp_path: Path):
    path = write_transcript(tmp_path, [user_row("hello"), usage_row("a1")])

    assert [r.uuid for r in transcript.rows_from_transcript(path, actor="ba")] == ["a1"]


def test_a_synthetic_model_row_is_skipped(tmp_path: Path):
    # Claude Code writes an all-zero '<synthetic>' row for an API error; it is
    # not an API call and must not appear as one.
    path = write_transcript(tmp_path, [usage_row("a1", model="<synthetic>")])

    assert transcript.rows_from_transcript(path, actor="ba") == []


def test_a_row_without_a_uuid_is_skipped(tmp_path: Path):
    # Without a uuid the row cannot be de-duplicated, so ingesting it twice
    # would double-count. Dropping it is the safe failure.
    row = usage_row("a1")
    del row["uuid"]
    path = write_transcript(tmp_path, [row])

    assert transcript.rows_from_transcript(path, actor="ba") == []


def test_the_ticket_cursor_is_set_by_a_tickets_path(tmp_path: Path):
    path = write_transcript(
        tmp_path,
        [user_row("please read tickets/open-new-flight.md"), usage_row("a1")],
    )

    (row,) = transcript.rows_from_transcript(path, actor="ba")

    assert row.ticket == "open-new-flight"


def test_the_ticket_cursor_reads_a_windows_path_too(tmp_path: Path):
    # Inside the JSONL a Windows path is backslash-escaped: docs\\impl\\x-plan.md
    path = write_transcript(
        tmp_path,
        [user_row("see docs\\impl\\ATM-7-plan.md"), usage_row("a1")],
    )

    (row,) = transcript.rows_from_transcript(path, actor="dev")

    assert row.ticket == "ATM-7"


def test_the_ticket_cursor_follows_missions_and_docs_impl(tmp_path: Path):
    path = write_transcript(
        tmp_path,
        [
            user_row("open missions/M-stock.md"),
            usage_row("a1"),
            user_row("now docs/impl/M-stock-US2-design.md"),
            usage_row("a2"),
        ],
    )

    rows = transcript.rows_from_transcript(path, actor="dev")

    assert [r.ticket for r in rows] == ["M-stock", "M-stock-US2"]


def test_rows_before_any_ticket_mention_have_no_ticket(tmp_path: Path):
    path = write_transcript(
        tmp_path,
        [usage_row("a1"), user_row("tickets/open-new-flight.md"), usage_row("a2")],
    )

    rows = transcript.rows_from_transcript(path, actor="ba")

    assert [(r.uuid, r.ticket) for r in rows] == [
        ("a1", None),
        ("a2", "open-new-flight"),
    ]


def test_the_template_file_is_not_a_ticket(tmp_path: Path):
    path = write_transcript(
        tmp_path, [user_row("read docs/tickets/TEMPLATE.md"), usage_row("a1")]
    )

    (row,) = transcript.rows_from_transcript(path, actor="ba")

    assert row.ticket is None


def test_a_traversal_stem_is_treated_as_no_mention(tmp_path: Path):
    path = write_transcript(
        tmp_path, [user_row("tickets/../../etc/passwd.md"), usage_row("a1")]
    )

    (row,) = transcript.rows_from_transcript(path, actor="ba")

    assert row.ticket is None


def test_the_last_mention_wins_and_mission_does_not_stack_with_ticket(tmp_path: Path):
    path = write_transcript(
        tmp_path,
        [
            user_row("missions/M-stock.md"),
            user_row("tickets/open-new-flight.md"),
            usage_row("a1"),
        ],
    )

    (row,) = transcript.rows_from_transcript(path, actor="ba")

    assert row.ticket == "open-new-flight"


def test_forced_ticket_overrides_every_cursor_result(tmp_path: Path):
    path = write_transcript(
        tmp_path, [user_row("tickets/open-new-flight.md"), usage_row("a1")]
    )

    (row,) = transcript.rows_from_transcript(
        path, actor="ba", forced_ticket="remove-witness-crew-stock-transfer"
    )

    assert row.ticket == "remove-witness-crew-stock-transfer"


def test_the_phase_cursor_is_set_by_a_command_marker(tmp_path: Path):
    path = write_transcript(
        tmp_path,
        [user_row("<command-name>/ba-ticket-author</command-name>"), usage_row("a1")],
    )

    (row,) = transcript.rows_from_transcript(path, actor="ba")

    assert row.phase == "ba-ticket-author"


def test_the_phase_cursor_is_set_by_a_skill_tool_call(tmp_path: Path):
    path = write_transcript(tmp_path, [skill_call_row("dev-execute"), usage_row("a1")])

    (row,) = transcript.rows_from_transcript(path, actor="dev")

    assert row.phase == "dev-execute"


def test_phase_is_unknown_before_any_command(tmp_path: Path):
    path = write_transcript(tmp_path, [usage_row("a1")])

    (row,) = transcript.rows_from_transcript(path, actor="ba")

    assert row.phase == "unknown"


def test_clear_resets_the_phase(tmp_path: Path):
    path = write_transcript(
        tmp_path,
        [
            user_row("<command-name>/ba-ticket-author</command-name>"),
            usage_row("a1"),
            user_row("<command-name>/clear</command-name>"),
            usage_row("a2"),
        ],
    )

    rows = transcript.rows_from_transcript(path, actor="ba")

    assert [r.phase for r in rows] == ["ba-ticket-author", "unknown"]


def test_an_unrelated_command_leaves_the_phase_alone(tmp_path: Path):
    path = write_transcript(
        tmp_path,
        [
            user_row("<command-name>/ba-ticket-author</command-name>"),
            user_row("<command-name>/model</command-name>"),
            usage_row("a1"),
        ],
    )

    (row,) = transcript.rows_from_transcript(path, actor="ba")

    assert row.phase == "ba-ticket-author"


def test_a_non_workflow_skill_is_not_a_phase(tmp_path: Path):
    path = write_transcript(
        tmp_path, [skill_call_row("superpowers:writing-plans"), usage_row("a1")]
    )

    (row,) = transcript.rows_from_transcript(path, actor="dev")

    assert row.phase == "unknown"


def test_a_skill_name_mentioned_in_content_is_not_a_phase(tmp_path: Path):
    # THE anti-test. A session that edits the dev skills mentions
    # 'dev-handover' hundreds of times while running something else; counting
    # mentions produced a phase breakdown that was wrong and looked right.
    path = write_transcript(
        tmp_path,
        [
            user_row("edit claude-skill-dev-handover.md — dev-handover, dev-handover"),
            usage_row("a1"),
        ],
    )

    (row,) = transcript.rows_from_transcript(path, actor="dev")

    assert row.phase == "unknown"


def test_sidechain_and_branch_are_carried_through(tmp_path: Path):
    path = write_transcript(tmp_path, [usage_row("a1", isSidechain=True)])

    (row,) = transcript.rows_from_transcript(path, actor="dev")

    assert row.sidechain is True
    assert row.branch == "feat/x"


def test_a_head_branch_is_recorded_as_none(tmp_path: Path):
    # A repo that is not a git repository reports 'HEAD' for every row; that is
    # not a branch and must not be shown as one.
    path = write_transcript(tmp_path, [usage_row("a1", gitBranch="HEAD")])

    (row,) = transcript.rows_from_transcript(path, actor="ba")

    assert row.branch is None


def test_reingesting_a_longer_transcript_reproduces_the_earlier_rows(tmp_path: Path):
    # Invariant I1: both cursors depend only on PRECEDING rows, so a prefix and
    # the full file must agree on every row the prefix contained.
    prefix = [user_row("tickets/open-new-flight.md"), usage_row("a1")]
    full = prefix + [user_row("<command-name>/clear</command-name>"), usage_row("a2")]

    short = transcript.rows_from_transcript(
        write_transcript(tmp_path, prefix, "short.jsonl"), actor="ba"
    )
    long = transcript.rows_from_transcript(
        write_transcript(tmp_path, full, "long.jsonl"), actor="ba"
    )

    assert [r.model_dump() for r in short] == [r.model_dump() for r in long[:1]]


def test_a_malformed_line_does_not_lose_the_rest_of_the_file(tmp_path: Path):
    path = tmp_path / "t.jsonl"
    path.write_text(
        json.dumps(usage_row("a1")) + "\n{ not json\n" + json.dumps(usage_row("a2"))
        + "\n",
        encoding="utf-8",
    )

    assert [r.uuid for r in transcript.rows_from_transcript(path, actor="ba")] == [
        "a1",
        "a2",
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_usage_transcript.py -v`
Expected: FAIL at collection — `ImportError: cannot import name 'transcript' from 'center_kb.usage'`.

- [ ] **Step 3: Implement the parser**

Create `src/center_kb/usage/transcript.py`:

```python
"""transcript — turn a Claude Code transcript into ledger rows.

A transcript lives at `~/.claude/projects/<slug>/<session-id>.jsonl`. Every row
whose `message` carries a `usage` block is one API call, and that block is the
assistant's own accounting — not an estimate — so the numbers here are copied,
never computed (invariant I3).

Attribution is two cursors walked in file order. Both depend only on rows
BEFORE the current one, which is what makes re-ingestion of a growing
transcript stable: the `Stop` hook re-reads the same file every turn, and rows
already stored must never change (invariant I1).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from center_kb.usage.ledger import UsageRow, is_safe_stem

# A ticket file mention. The separator class allows one or more of `/` and `\`
# because a Windows path inside the JSONL is backslash-escaped
# (`docs\\impl\\x-plan.md`), so a single-character class would match the first
# backslash and then fail on the second.
_SEP = r"[/\\]+"
TICKET_PATH_RE = re.compile(
    rf"(?:tickets|missions){_SEP}(?P<stem>[^/\\\"]+?)\.md"
    rf"|docs{_SEP}impl{_SEP}(?P<impl>[^/\\\"]+?)-(?:design|plan)\.md"
)

# The only two phase signals. A slash command's marker is injected into the
# user message; a Skill tool call names the skill in its input.
COMMAND_RE = re.compile(r"<command-name>([^<]{1,80})</command-name>")
PHASE_RE = re.compile(r"^(?:ba|dev|kb)-[a-z0-9-]+$")

SYNTHETIC_MODEL = "<synthetic>"
UNKNOWN_PHASE = "unknown"
_NOT_A_TICKET = {"TEMPLATE"}


def _ticket_in(blob: str) -> str | None:
    """The last ticket stem mentioned in one row, or None.

    Last, not first: a row that mentions two files (a tool result listing a
    directory, say) leaves the cursor on whichever came latest, matching how
    the cursor behaves across rows.
    """
    found: str | None = None
    for match in TICKET_PATH_RE.finditer(blob):
        stem = match.group("stem") or match.group("impl")
        if stem in _NOT_A_TICKET or not is_safe_stem(stem):
            # A traversal attempt, a template, or anything else that cannot be
            # a ticket file name is treated as no mention at all — never
            # rewritten into something that looks safe.
            continue
        found = stem
    return found


def _phase_in(row: dict, blob: str) -> str | None:
    """The phase this row switches to, `UNKNOWN_PHASE` for a reset, or None
    for "leave the cursor alone".

    Deliberately NOT derived from skill names appearing in content: a session
    that edits the dev skills mentions `dev-handover` hundreds of times while
    running something else entirely, and counting mentions produced a phase
    breakdown that was wrong and looked right.
    """
    names: list[str] = [m.strip() for m in COMMAND_RE.findall(blob)]
    message = row.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "tool_use"
                    and block.get("name") == "Skill"
                ):
                    skill = (block.get("input") or {}).get("skill")
                    if isinstance(skill, str):
                        names.append(skill)
    result: str | None = None
    for raw in names:
        name = raw.lstrip("/").strip()
        if name == "clear":
            # /clear wipes the context the phase was running in, so the phase
            # is over — not merely unchanged.
            result = UNKNOWN_PHASE
        elif PHASE_RE.match(name):
            result = name
    return result


def _int(usage: dict, key: str) -> int:
    value = usage.get(key)
    return int(value) if isinstance(value, (int, float)) else 0


def rows_from_transcript(
    path: Path,
    *,
    actor: str,
    session_fallback: str = "",
    forced_ticket: str | None = None,
) -> list[UsageRow]:
    """Every API call in this transcript, attributed.

    `forced_ticket` overrides the cursor entirely — the escape hatch for a
    session the cursor read wrongly.
    """
    rows: list[UsageRow] = []
    ticket: str | None = None
    phase = UNKNOWN_PHASE
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            # One truncated line (a transcript being written while we read it)
            # must not cost the rest of the file.
            continue
        if not isinstance(row, dict):
            continue
        # AMENDED after Task 2's review (see the note below): this was
        # `blob = line`, which let a tool_result payload — the text of any file
        # the agent merely read — drive both cursors. Build the scan text from
        # the trusted channels only.
        found = _ticket_in(_ticket_blob(row))
        if found is not None:
            ticket = found
        switched = _phase_in(row, blob)
        if switched is not None:
            phase = switched

        message = row.get("message")
        usage = message.get("usage") if isinstance(message, dict) else None
        if not isinstance(usage, dict):
            continue
        model = message.get("model") or ""
        uuid = row.get("uuid")
        if model == SYNTHETIC_MODEL or not isinstance(uuid, str) or not uuid:
            continue
        creation = usage.get("cache_creation") or {}
        branch = row.get("gitBranch")
        rows.append(
            UsageRow(
                uuid=uuid,
                ts=str(row.get("timestamp") or ""),
                session=str(row.get("sessionId") or session_fallback),
                actor=actor,
                phase=phase,
                ticket=forced_ticket if forced_ticket is not None else ticket,
                model=str(model),
                tokens_in=_int(usage, "input_tokens"),
                tokens_out=_int(usage, "output_tokens"),
                cache_read=_int(usage, "cache_read_input_tokens"),
                cache_write_5m=_int(creation, "ephemeral_5m_input_tokens"),
                cache_write_1h=_int(creation, "ephemeral_1h_input_tokens"),
                sidechain=bool(row.get("isSidechain")),
                # 'HEAD' is what a non-git directory reports for every row; it
                # is not a branch, so it is not recorded as one.
                branch=branch if isinstance(branch, str) and branch != "HEAD" else None,
                assistant="claude-code",
                est=False,
            )
        )
    return rows
```

**AMENDMENT (post-review, and the implemented behaviour — `src/center_kb/usage/transcript.py` as committed is the authority):** the code above scanned the raw JSON line, so a `<command-name>` marker or a ticket path anywhere in a `tool_result` payload drove the cursors. Reproduced: a session that ran `/kb-ingest`, then read this very plan file, came out as `phase='unknown' ticket='ATM-7'` — the plan's own markers (last one `/clear`) wiped the phase and its `docs\impl\ATM-7-plan.md` example forged a ticket.

The rule now is: **a cursor advances on what the session does or says, never on what it reads.**

- `_ticket_blob(row)` assembles the scan text from a user row's `str` content or its `type == "text"` blocks, and from an assistant row's text blocks plus each `tool_use` block's serialised `input` (a `file_path` is the strongest ticket signal there is and must keep working). Every other block type — `tool_result` above all — contributes nothing.
- `_command_text(row)` returns `""` unless `row["type"] == "user"`, so `COMMAND_RE` cannot see a marker on any other channel. The `Skill` path already read structured `input.skill` and was unchanged.
- `PHASE_RE` is applied with `fullmatch`, and the stem expression ends `or ""` so `is_safe_stem` is never handed `None`.

Four tests pin it: a `tool_result` carrying `<command-name>/clear</command-name>` does not reset the phase; a `tool_result` carrying a `tickets/*.md` path does not set the ticket; a `tool_use` whose `input` has `{"file_path": "tickets/open-new-flight.md"}` does set it; assistant *text* naming a ticket still sets it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_usage_transcript.py -v`
Expected: PASS, all tests.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/usage/transcript.py tests/test_usage_transcript.py
git commit -m "feat: parse Claude Code transcripts into usage rows with ticket/phase cursors"
```

---

### Task 3: The price table

**Files:**
- Create: `src/center_kb/templates/usage/usage-prices.yaml`, `src/center_kb/usage/prices.py`
- Test: `tests/test_usage_prices.py`

**Interfaces:**
- Consumes: `ledger.UsageRow` from Task 1.
- Produces:
  - `class ModelRates(BaseModel)` — `input: float`, `output: float`, `cache_read: float`, `cache_write_5m: float`, `cache_write_1h: float`
  - `class PriceTable(BaseModel)` — `effective_date: str`, `currency: str = "USD"`, `unit: str = "per_mtok"`, `models: dict[str, ModelRates]`
  - `PRICES_FILE = "usage-prices.yaml"`
  - `def load_prices(kb_dir: Path) -> PriceTable`
  - `def cost_of(row: UsageRow, table: PriceTable) -> float | None` — `None` means unpriced
  - `def stale_days(table: PriceTable, today: date) -> int`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_usage_prices.py`:

```python
from datetime import date
from pathlib import Path

import pytest
import yaml

from center_kb.usage import prices
from tests.test_usage_ledger import row


def test_the_packaged_table_prices_the_models_we_actually_run(tmp_path: Path):
    table = prices.load_prices(tmp_path)

    for model in ("claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"):
        assert model in table.models, model
    assert table.effective_date


def test_the_packaged_table_has_five_rates_per_model(tmp_path: Path):
    # A single 'cache write' rate understates a 1h write by ~37%, and a table
    # with no cache_read rate is off by more than half the bill.
    rates = prices.load_prices(tmp_path).models["claude-opus-5"]

    assert (rates.input, rates.output) == (5.0, 25.0)
    assert (rates.cache_read, rates.cache_write_5m, rates.cache_write_1h) == (
        0.5,
        6.25,
        10.0,
    )


def test_a_repo_override_replaces_only_the_models_it_names(tmp_path: Path):
    (tmp_path / "usage-prices.yaml").write_text(
        yaml.safe_dump(
            {
                "effective_date": "2026-09-01",
                "models": {
                    "claude-sonnet-5": {
                        "input": 2.0,
                        "output": 10.0,
                        "cache_read": 0.2,
                        "cache_write_5m": 2.5,
                        "cache_write_1h": 4.0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    table = prices.load_prices(tmp_path)

    assert table.models["claude-sonnet-5"].input == 2.0
    assert table.models["claude-opus-5"].input == 5.0  # kept from the default
    assert table.effective_date == "2026-09-01"


def test_cost_sums_all_five_components(tmp_path: Path):
    table = prices.load_prices(tmp_path)
    r = row(
        "u1",
        model="claude-opus-5",
        tokens_in=1_000_000,
        tokens_out=1_000_000,
        cache_read=1_000_000,
        cache_write_5m=1_000_000,
        cache_write_1h=1_000_000,
    )

    assert prices.cost_of(r, table) == pytest.approx(5.0 + 25.0 + 0.5 + 6.25 + 10.0)


def test_a_measured_session_prices_to_the_number_we_verified(tmp_path: Path):
    # The real 305-row Opus 5 session from the spec's evidence, as one row.
    table = prices.load_prices(tmp_path)
    r = row(
        "u1",
        model="claude-opus-5",
        tokens_in=610,
        tokens_out=433_409,
        cache_read=76_847_719,
        cache_write_5m=0,
        cache_write_1h=914_048,
    )

    assert prices.cost_of(r, table) == pytest.approx(58.40, abs=0.01)


def test_an_unknown_model_is_unpriced_not_free(tmp_path: Path):
    # Invariant I5. A silent $0 is the failure that makes a dashboard worse
    # than no dashboard.
    table = prices.load_prices(tmp_path)

    assert prices.cost_of(row("u1", model="claude-nonexistent-9"), table) is None


def test_stale_days_counts_from_the_effective_date(tmp_path: Path):
    table = prices.load_prices(tmp_path)
    table.effective_date = "2026-06-24"

    assert prices.stale_days(table, date(2026, 9, 22)) == 90


def test_an_unparseable_effective_date_reads_as_maximally_stale(tmp_path: Path):
    table = prices.load_prices(tmp_path)
    table.effective_date = "not-a-date"

    assert prices.stale_days(table, date(2026, 9, 22)) > 3650
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_usage_prices.py -v`
Expected: FAIL at collection — `ImportError: cannot import name 'prices'`.

- [ ] **Step 3: Write the default table**

Create `src/center_kb/templates/usage/usage-prices.yaml`:

```yaml
# Anthropic first-party API list prices, per million tokens (USD).
#
# Rates are written out explicitly rather than as multipliers of `input`
# (cache_read is 0.1x, cache_write_5m 1.25x, cache_write_1h 2x input today):
# a multiplier convention rots silently the day one model prices its cache
# differently, and this file is meant to be edited by hand.
#
# Standard rates only, never promotional ones. Claude Sonnet 5 carries an
# introductory 2.0 / 10.0 that expires 2026-08-31; a repo that needs that
# window copies this file to `.kb/usage-prices.yaml` and overrides that one
# model. An override merges per model, so the rest of the table survives.
#
# `kb usage report` prints effective_date and warns once it is over 90 days
# old. A model missing from this table is reported as `unpriced` with its
# token counts — never as costing nothing.
effective_date: "2026-06-24"
currency: USD
unit: per_mtok
models:
  claude-opus-5:     {input: 5.0,  output: 25.0, cache_read: 0.50, cache_write_5m: 6.25, cache_write_1h: 10.0}
  claude-opus-4-8:   {input: 5.0,  output: 25.0, cache_read: 0.50, cache_write_5m: 6.25, cache_write_1h: 10.0}
  claude-opus-4-7:   {input: 5.0,  output: 25.0, cache_read: 0.50, cache_write_5m: 6.25, cache_write_1h: 10.0}
  claude-opus-4-6:   {input: 5.0,  output: 25.0, cache_read: 0.50, cache_write_5m: 6.25, cache_write_1h: 10.0}
  claude-fable-5:    {input: 10.0, output: 50.0, cache_read: 1.00, cache_write_5m: 12.5, cache_write_1h: 20.0}
  claude-sonnet-5:   {input: 3.0,  output: 15.0, cache_read: 0.30, cache_write_5m: 3.75, cache_write_1h: 6.0}
  claude-sonnet-4-6: {input: 3.0,  output: 15.0, cache_read: 0.30, cache_write_5m: 3.75, cache_write_1h: 6.0}
  claude-haiku-4-5:  {input: 1.0,  output:  5.0, cache_read: 0.10, cache_write_5m: 1.25, cache_write_1h: 2.0}
```

- [ ] **Step 4: Implement the loader**

Create `src/center_kb/usage/prices.py`:

```python
"""prices — model id to money.

The package ships a default table; a repo overrides it at
`.kb/usage-prices.yaml`. The override merges PER MODEL, so a repo correcting
one model's price keeps the rest of the table instead of inheriting a
half-filled one.

An unknown model is `unpriced`, never $0: a dashboard that quietly values an
unrecognised model at nothing is worse than no dashboard, because the number it
shows looks complete.
"""
from __future__ import annotations

from datetime import date, datetime
from importlib import resources
from pathlib import Path

import yaml
from pydantic import BaseModel

from center_kb.usage.ledger import UsageRow

PRICES_FILE = "usage-prices.yaml"
_MTOK = 1_000_000


class ModelRates(BaseModel):
    input: float
    output: float
    cache_read: float
    cache_write_5m: float
    cache_write_1h: float


class PriceTable(BaseModel):
    effective_date: str = ""
    currency: str = "USD"
    unit: str = "per_mtok"
    models: dict[str, ModelRates] = {}


def _packaged() -> dict:
    text = (
        resources.files("center_kb")
        .joinpath("templates/usage")
        .joinpath(PRICES_FILE)
        .read_text(encoding="utf-8")
    )
    return yaml.safe_load(text) or {}


def load_prices(kb_dir: Path) -> PriceTable:
    data = _packaged()
    override_path = kb_dir / PRICES_FILE
    if override_path.exists():
        override = yaml.safe_load(override_path.read_text(encoding="utf-8")) or {}
        models = dict(data.get("models") or {})
        models.update(override.get("models") or {})
        data = {**data, **override, "models": models}
    return PriceTable.model_validate(data)


def cost_of(row: UsageRow, table: PriceTable) -> float | None:
    """USD for one row, or None when the model has no rates."""
    rates = table.models.get(row.model)
    if rates is None:
        return None
    return (
        row.tokens_in * rates.input
        + row.tokens_out * rates.output
        + row.cache_read * rates.cache_read
        + row.cache_write_5m * rates.cache_write_5m
        + row.cache_write_1h * rates.cache_write_1h
    ) / _MTOK


def stale_days(table: PriceTable, today: date) -> int:
    """Age of the table in days. An unparseable date reads as ancient, so a
    typo surfaces as a loud warning rather than as a fresh table.
    """
    try:
        effective = datetime.strptime(table.effective_date, "%Y-%m-%d").date()
    except ValueError:
        return 36_500
    return (today - effective).days
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_usage_prices.py -v`
Expected: PASS. In particular `test_a_measured_session_prices_to_the_number_we_verified` must land on $58.40 — that number was computed from a real transcript before this code existed, so a mismatch means the formula is wrong, not the test.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/templates/usage/usage-prices.yaml src/center_kb/usage/prices.py tests/test_usage_prices.py
git commit -m "feat: usage price table with per-model repo override and unpriced models"
```

---

### Task 4: Aggregation and the report

**Files:**
- Create: `src/center_kb/usage/report.py`, `src/center_kb/templates/usage/report.html.j2`
- Test: `tests/test_usage_report.py`

**Interfaces:**
- Consumes: `ledger.UsageRow`, `ledger.read_rows`, `prices.PriceTable`, `prices.load_prices`, `prices.cost_of`, `prices.stale_days`.
- Produces:
  - `class Bucket(BaseModel)` — `key: str`, `rows: int`, `tokens_in: int`, `tokens_out: int`, `cache_read: int`, `cache_write: int`, `cost: float`, `unpriced_rows: int`
  - `class Aggregate(BaseModel)` — `total: Bucket`, `by_ticket/by_phase/by_model/by_actor: list[Bucket]`, `main: Bucket`, `sidechain: Bucket`, `unattributed: Bucket`, `unpriced_models: list[str]`, `effective_date: str`, `currency: str`, `stale_days: int`, `generated: str`
  - `def aggregate(rows, table, *, today, generated) -> Aggregate`
  - `def render_html(agg: Aggregate) -> str`
  - `def render_markdown(agg: Aggregate) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_usage_report.py`:

```python
from datetime import date
from pathlib import Path

import pytest

from center_kb.usage import prices, report
from tests.test_usage_ledger import row

GEN = "2026-08-23T12:00:00Z"
TODAY = date(2026, 8, 23)


def agg_of(rows, tmp_path: Path):
    return report.aggregate(
        rows, prices.load_prices(tmp_path), today=TODAY, generated=GEN
    )


def test_total_sums_tokens_and_cost(tmp_path: Path):
    rows = [
        row("u1", model="claude-opus-5", tokens_out=1_000_000, cache_read=0,
            cache_write_1h=0, cache_write_5m=0, tokens_in=0),
        row("u2", model="claude-opus-5", tokens_out=1_000_000, cache_read=0,
            cache_write_1h=0, cache_write_5m=0, tokens_in=0),
    ]

    agg = agg_of(rows, tmp_path)

    assert agg.total.rows == 2
    assert agg.total.tokens_out == 2_000_000
    assert agg.total.cost == pytest.approx(50.0)


def test_buckets_split_by_ticket_phase_model_and_actor(tmp_path: Path):
    rows = [
        row("u1", ticket="open-new-flight", phase="ba-ticket-author", actor="ba"),
        row("u2", ticket="ATM-7", phase="dev-execute", actor="dev",
            model="claude-opus-5"),
    ]

    agg = agg_of(rows, tmp_path)

    assert {b.key for b in agg.by_ticket} == {"open-new-flight", "ATM-7"}
    assert {b.key for b in agg.by_phase} == {"ba-ticket-author", "dev-execute"}
    assert {b.key for b in agg.by_model} == {"claude-sonnet-5", "claude-opus-5"}
    assert {b.key for b in agg.by_actor} == {"ba", "dev"}


def test_buckets_are_sorted_by_cost_descending(tmp_path: Path):
    rows = [
        row("u1", ticket="cheap", tokens_out=1),
        row("u2", ticket="dear", tokens_out=1_000_000),
    ]

    assert [b.key for b in agg_of(rows, tmp_path).by_ticket] == ["dear", "cheap"]


def test_sidechain_cost_is_reported_apart_from_main(tmp_path: Path):
    rows = [row("u1", sidechain=False), row("u2", sidechain=True)]

    agg = agg_of(rows, tmp_path)

    assert (agg.main.rows, agg.sidechain.rows) == (1, 1)


def test_unattributed_rows_are_their_own_bucket_and_not_a_ticket(tmp_path: Path):
    agg = agg_of([row("u1", ticket=None), row("u2", ticket="ATM-7")], tmp_path)

    assert agg.unattributed.rows == 1
    assert [b.key for b in agg.by_ticket] == ["ATM-7"]


def test_an_unknown_model_is_counted_in_tokens_but_not_in_money(tmp_path: Path):
    # Invariant I5, report half.
    rows = [
        row("u1", model="claude-opus-5", tokens_out=1_000_000, tokens_in=0,
            cache_read=0, cache_write_1h=0, cache_write_5m=0),
        row("u2", model="claude-nonexistent-9", tokens_out=1_000_000, tokens_in=0,
            cache_read=0, cache_write_1h=0, cache_write_5m=0),
    ]

    agg = agg_of(rows, tmp_path)

    assert agg.total.cost == pytest.approx(25.0)
    assert agg.total.tokens_out == 2_000_000
    assert agg.total.unpriced_rows == 1
    assert agg.unpriced_models == ["claude-nonexistent-9"]


def test_stale_days_is_carried_into_the_aggregate(tmp_path: Path):
    agg = report.aggregate(
        [row("u1")], prices.load_prices(tmp_path), today=date(2030, 1, 1),
        generated=GEN,
    )

    assert agg.stale_days > 90


def test_html_is_self_contained(tmp_path: Path):
    html = report.render_html(agg_of([row("u1")], tmp_path))

    assert "<table" in html
    assert "<script" not in html.lower()
    assert "http://" not in html and "https://" not in html


def test_html_names_the_price_table_date_and_the_ticket(tmp_path: Path):
    html = report.render_html(agg_of([row("u1", ticket="open-new-flight")], tmp_path))

    assert "open-new-flight" in html
    assert "2026-06-24" in html


def test_html_escapes_a_field_that_carries_arbitrary_text(tmp_path: Path):
    # `model` is copied verbatim out of the transcript and is NOT stem-validated
    # the way `ticket` is, so it is the field that can actually carry markup.
    # (A hostile ticket name cannot reach here — STEM_RE rejects '<'.)
    html = report.render_html(
        agg_of([row("u1", model="<script>alert(1)</script>")], tmp_path)
    )

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_html_warns_when_the_price_table_is_old(tmp_path: Path):
    agg = report.aggregate(
        [row("u1")], prices.load_prices(tmp_path), today=date(2030, 1, 1),
        generated=GEN,
    )

    assert "out of date" in report.render_html(agg)


def test_html_says_so_when_a_model_is_unpriced(tmp_path: Path):
    agg = agg_of([row("u1", model="claude-nonexistent-9")], tmp_path)

    html = report.render_html(agg)

    assert "unpriced" in html
    assert "claude-nonexistent-9" in html


def test_markdown_is_a_compact_table_for_a_pr_body(tmp_path: Path):
    md = report.render_markdown(agg_of([row("u1", ticket="open-new-flight")], tmp_path))

    assert md.startswith("| ")
    assert "open-new-flight" in md
    assert "\n\n\n" not in md
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_usage_report.py -v`
Expected: FAIL at collection — `ImportError: cannot import name 'report'`.

- [ ] **Step 3: Implement aggregation and rendering**

Create `src/center_kb/usage/report.py`:

```python
"""report — aggregate ledger rows and render them.

Reads the committed ledger, never a transcript: the ledger is the record, and
a report that re-derived from transcripts would disagree with what git holds.

HTML is static and self-contained on purpose — no server to run, no CDN to
reach, no JavaScript. Tables, not charts: a self-contained chart means shipping
a library, and a table survives a git diff.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape
from pydantic import BaseModel

from center_kb.usage.ledger import UsageRow
from center_kb.usage.prices import PriceTable, cost_of, stale_days

STALE_AFTER_DAYS = 90


class Bucket(BaseModel):
    key: str = ""
    rows: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read: int = 0
    cache_write: int = 0
    cost: float = 0.0
    unpriced_rows: int = 0


class Aggregate(BaseModel):
    total: Bucket = Bucket(key="total")
    by_ticket: list[Bucket] = []
    by_phase: list[Bucket] = []
    by_model: list[Bucket] = []
    by_actor: list[Bucket] = []
    main: Bucket = Bucket(key="main")
    sidechain: Bucket = Bucket(key="sidechain")
    unattributed: Bucket = Bucket(key="unattributed")
    unpriced_models: list[str] = []
    effective_date: str = ""
    currency: str = "USD"
    stale_days: int = 0
    stale: bool = False
    generated: str = ""


def _add(bucket: Bucket, row: UsageRow, cost: float | None) -> None:
    bucket.rows += 1
    bucket.tokens_in += row.tokens_in
    bucket.tokens_out += row.tokens_out
    bucket.cache_read += row.cache_read
    bucket.cache_write += row.cache_write_5m + row.cache_write_1h
    if cost is None:
        bucket.unpriced_rows += 1
    else:
        bucket.cost += cost


def _ranked(buckets: dict[str, Bucket]) -> list[Bucket]:
    return sorted(buckets.values(), key=lambda b: (-b.cost, -b.tokens_out, b.key))


def aggregate(
    rows: list[UsageRow],
    table: PriceTable,
    *,
    today: date,
    generated: str,
) -> Aggregate:
    agg = Aggregate(
        total=Bucket(key="total"),
        main=Bucket(key="main"),
        sidechain=Bucket(key="sidechain"),
        unattributed=Bucket(key="unattributed"),
        effective_date=table.effective_date,
        currency=table.currency,
        generated=generated,
    )
    agg.stale_days = stale_days(table, today)
    agg.stale = agg.stale_days > STALE_AFTER_DAYS
    tickets: dict[str, Bucket] = defaultdict(Bucket)
    phases: dict[str, Bucket] = defaultdict(Bucket)
    models: dict[str, Bucket] = defaultdict(Bucket)
    actors: dict[str, Bucket] = defaultdict(Bucket)
    unpriced: set[str] = set()
    for row in rows:
        cost = cost_of(row, table)
        if cost is None:
            unpriced.add(row.model)
        _add(agg.total, row, cost)
        _add(agg.sidechain if row.sidechain else agg.main, row, cost)
        if row.ticket is None:
            _add(agg.unattributed, row, cost)
        else:
            tickets[row.ticket].key = row.ticket
            _add(tickets[row.ticket], row, cost)
        for store, key in ((phases, row.phase), (models, row.model), (actors, row.actor)):
            store[key].key = key
            _add(store[key], row, cost)
    agg.by_ticket = _ranked(tickets)
    agg.by_phase = _ranked(phases)
    agg.by_model = _ranked(models)
    agg.by_actor = _ranked(actors)
    agg.unpriced_models = sorted(unpriced)
    return agg


_env = Environment(
    loader=PackageLoader("center_kb", "templates/usage"),
    autoescape=select_autoescape(enabled_extensions=("j2", "html"), default=True),
)


def render_html(agg: Aggregate) -> str:
    return _env.get_template("report.html.j2").render(agg=agg)


def _md_row(bucket: Bucket, currency: str) -> str:
    money = f"{bucket.cost:.2f} {currency}" if bucket.rows else "-"
    if bucket.unpriced_rows:
        money += f" (+{bucket.unpriced_rows} unpriced)"
    return (
        f"| {bucket.key} | {bucket.rows} | {bucket.tokens_out:,} | "
        f"{bucket.cache_read:,} | {money} |"
    )


def render_markdown(agg: Aggregate) -> str:
    """A PR-body table: what it cost, and where the cost went."""
    lines = [
        "| scope | calls | output tokens | cache read | cost |",
        "| --- | --- | --- | --- | --- |",
        _md_row(agg.total, agg.currency),
    ]
    for bucket in agg.by_ticket:
        lines.append(_md_row(bucket, agg.currency))
    for bucket in agg.by_phase:
        lines.append(_md_row(Bucket(**{**bucket.model_dump(), "key": f"phase: {bucket.key}"}), agg.currency))
    lines.append("")
    lines.append(
        f"Prices effective {agg.effective_date} ({agg.stale_days} days old); "
        f"generated {agg.generated}."
    )
    return "\n".join(lines)
```

- [ ] **Step 4: Write the HTML template**

Create `src/center_kb/templates/usage/report.html.j2`:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KB usage report</title>
<style>
  :root { color-scheme: light dark; }
  body { font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
         margin: 2rem auto; max-width: 60rem; padding: 0 1rem; }
  h1 { font-size: 1.4rem; } h2 { font-size: 1.1rem; margin-top: 2rem; }
  table { border-collapse: collapse; width: 100%; margin: 0.5rem 0 1.5rem; }
  th, td { border-bottom: 1px solid #8883; padding: 0.35rem 0.6rem;
           text-align: right; }
  th:first-child, td:first-child { text-align: left; }
  thead th { border-bottom: 2px solid #8886; }
  .meta { color: #8889; font-size: 0.85rem; }
  .warn { border-left: 3px solid #c60; padding: 0.5rem 0.8rem; margin: 1rem 0;
          background: #c6601a1a; }
</style>
</head>
<body>
<h1>KB usage report</h1>
<p class="meta">
  Generated {{ agg.generated }} · prices effective {{ agg.effective_date }}
  ({{ agg.stale_days }} days old) · amounts in {{ agg.currency }}
</p>

{% if agg.stale %}
<p class="warn">The price table is out of date ({{ agg.stale_days }} days).
Override it in <code>.kb/usage-prices.yaml</code>.</p>
{% endif %}

{% if agg.unpriced_models %}
<p class="warn">Some rows are <strong>unpriced</strong> — no rates for
{{ agg.unpriced_models | join(', ') }}. Their tokens are counted below; their
cost is not, and is not treated as zero.</p>
{% endif %}

{% macro rows(buckets, label) %}
<table>
  <thead><tr><th>{{ label }}</th><th>calls</th><th>in</th><th>out</th>
    <th>cache read</th><th>cache write</th><th>cost</th></tr></thead>
  <tbody>
  {% for b in buckets %}
    <tr><td>{{ b.key }}</td><td>{{ b.rows }}</td><td>{{ "{:,}".format(b.tokens_in) }}</td>
      <td>{{ "{:,}".format(b.tokens_out) }}</td>
      <td>{{ "{:,}".format(b.cache_read) }}</td>
      <td>{{ "{:,}".format(b.cache_write) }}</td>
      <td>{{ "%.2f"|format(b.cost) }}{% if b.unpriced_rows %}
        + {{ b.unpriced_rows }} unpriced{% endif %}</td></tr>
  {% endfor %}
  </tbody>
</table>
{% endmacro %}

<h2>Total</h2>
{{ rows([agg.total], "scope") }}

<h2>By ticket</h2>
{{ rows(agg.by_ticket, "ticket") }}

<h2>By phase</h2>
{{ rows(agg.by_phase, "phase") }}

<h2>By model</h2>
{{ rows(agg.by_model, "model") }}

<h2>By actor</h2>
{{ rows(agg.by_actor, "actor") }}

<h2>Main thread vs subagents</h2>
{{ rows([agg.main, agg.sidechain], "thread") }}

<h2>Unattributed</h2>
<p class="meta">Calls made before any ticket file was mentioned in the session.
A large number here means the attribution cursor is missing work, not that the
work was free.</p>
{{ rows([agg.unattributed], "scope") }}
</body>
</html>
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_usage_report.py -v`
Expected: PASS, all tests.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/usage/report.py src/center_kb/templates/usage/report.html.j2 tests/test_usage_report.py
git commit -m "feat: aggregate usage rows into a self-contained HTML/Markdown report"
```

---

### Task 5: The CLI — `kb usage ingest-transcript`, `note`, `report`

**Files:**
- Modify: `src/center_kb/cli.py` (add `usage_app` after `svc_app` at `cli.py:35-36`; add three commands next to the `svc_note` command block that ends around `cli.py:800`)
- Test: `tests/test_cli_usage.py`

**Interfaces:**
- Consumes: everything from Tasks 1-4; `config.load_config(kb_dir).kind` (`src/center_kb/config.py:41`).
- Produces: CLI commands `kb usage ingest-transcript`, `kb usage note`, `kb usage report`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_usage.py`:

```python
import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from center_kb.cli import app
from center_kb.usage import ledger
from tests.test_usage_transcript import usage_row, user_row, write_transcript

runner = CliRunner()


def kb_dir(tmp_path: Path, kind: str = "ba") -> Path:
    d = tmp_path / ".kb"
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.yaml").write_text(
        yaml.safe_dump({"kind": kind, "repo_id": "KS-BA"}), encoding="utf-8"
    )
    return d


def test_ingest_writes_the_ledger_and_reports_counts(tmp_path: Path):
    d = kb_dir(tmp_path)
    t = write_transcript(
        tmp_path, [user_row("tickets/open-new-flight.md"), usage_row("a1")]
    )

    result = runner.invoke(app, ["usage", "ingest-transcript", str(t), "--kb-dir", str(d)])

    assert result.exit_code == 0, result.output
    assert "1" in result.output
    rows = ledger.read_rows(d)
    assert [(r.uuid, r.ticket, r.actor) for r in rows] == [
        ("a1", "open-new-flight", "ba")
    ]


def test_ingest_is_idempotent(tmp_path: Path):
    d = kb_dir(tmp_path)
    t = write_transcript(tmp_path, [usage_row("a1")])

    runner.invoke(app, ["usage", "ingest-transcript", str(t), "--kb-dir", str(d)])
    runner.invoke(app, ["usage", "ingest-transcript", str(t), "--kb-dir", str(d)])

    assert len(ledger.read_rows(d)) == 1


def test_ingest_takes_the_actor_from_the_config_kind(tmp_path: Path):
    d = kb_dir(tmp_path, kind="dev")
    t = write_transcript(tmp_path, [usage_row("a1")])

    runner.invoke(app, ["usage", "ingest-transcript", str(t), "--kb-dir", str(d)])

    assert ledger.read_rows(d)[0].actor == "dev"


def test_ingest_with_no_kind_records_an_unknown_actor(tmp_path: Path):
    d = tmp_path / ".kb"
    d.mkdir()
    t = write_transcript(tmp_path, [usage_row("a1")])

    runner.invoke(app, ["usage", "ingest-transcript", str(t), "--kb-dir", str(d)])

    assert ledger.read_rows(d)[0].actor == "unknown"


def test_ingest_forced_ticket_wins(tmp_path: Path):
    d = kb_dir(tmp_path)
    t = write_transcript(
        tmp_path, [user_row("tickets/open-new-flight.md"), usage_row("a1")]
    )

    runner.invoke(
        app,
        ["usage", "ingest-transcript", str(t), "--ticket", "ATM-7", "--kb-dir", str(d)],
    )

    assert ledger.read_rows(d)[0].ticket == "ATM-7"


def test_ingest_without_a_path_or_hook_stdin_is_a_usage_error(tmp_path: Path):
    d = kb_dir(tmp_path)

    result = runner.invoke(app, ["usage", "ingest-transcript", "--kb-dir", str(d)])

    assert result.exit_code == 2
    assert "exactly one" in result.output


def test_hook_mode_reads_the_transcript_path_from_stdin(tmp_path: Path):
    d = kb_dir(tmp_path)
    t = write_transcript(tmp_path, [usage_row("a1")])
    payload = json.dumps(
        {"session_id": "sess-1", "transcript_path": str(t), "cwd": str(tmp_path)}
    )

    result = runner.invoke(
        app, ["usage", "ingest-transcript", "--hook-stdin", "--kb-dir", str(d)],
        input=payload,
    )

    assert result.exit_code == 0, result.output
    assert len(ledger.read_rows(d)) == 1


def test_hook_mode_exits_zero_on_garbage_stdin_and_logs_it(tmp_path: Path):
    # A Stop hook exiting non-zero blocks Claude from ending its turn. An
    # ingest failure must never be able to freeze a session.
    d = kb_dir(tmp_path)

    result = runner.invoke(
        app, ["usage", "ingest-transcript", "--hook-stdin", "--kb-dir", str(d)],
        input="not json at all",
    )

    assert result.exit_code == 0, result.output
    log = (d / "usage" / "ingest-errors.log").read_text(encoding="utf-8")
    assert "not json" in log or "JSON" in log


def test_hook_mode_exits_zero_when_the_transcript_is_missing(tmp_path: Path):
    d = kb_dir(tmp_path)
    payload = json.dumps({"transcript_path": str(tmp_path / "nope.jsonl")})

    result = runner.invoke(
        app, ["usage", "ingest-transcript", "--hook-stdin", "--kb-dir", str(d)],
        input=payload,
    )

    assert result.exit_code == 0, result.output
    assert (d / "usage" / "ingest-errors.log").exists()


def test_note_appends_a_row_by_hand(tmp_path: Path):
    d = kb_dir(tmp_path)

    result = runner.invoke(
        app,
        ["usage", "note", "--ticket", "ATM-7", "--phase", "dev-plan",
         "--model", "claude-opus-5", "--tokens-in", "10", "--tokens-out", "20",
         "--kb-dir", str(d)],
    )

    assert result.exit_code == 0, result.output
    (row,) = ledger.read_rows(d)
    assert (row.ticket, row.phase, row.tokens_out, row.est) == ("ATM-7", "dev-plan", 20, False)


def test_note_est_marks_the_row_as_an_estimate(tmp_path: Path):
    d = kb_dir(tmp_path)

    runner.invoke(
        app,
        ["usage", "note", "--ticket", "ATM-7", "--phase", "dev-plan",
         "--model", "claude-opus-5", "--tokens-in", "1", "--tokens-out", "2",
         "--est", "--assistant", "copilot", "--kb-dir", str(d)],
    )

    (row,) = ledger.read_rows(d)
    assert (row.est, row.assistant) == (True, "copilot")


def test_note_refuses_an_unusable_ticket_id(tmp_path: Path):
    d = kb_dir(tmp_path)

    result = runner.invoke(
        app,
        ["usage", "note", "--ticket", "../escape", "--phase", "dev-plan",
         "--model", "claude-opus-5", "--tokens-in", "1", "--tokens-out", "2",
         "--kb-dir", str(d)],
    )

    assert result.exit_code == 1
    assert "ticket id" in result.output


def test_report_writes_a_self_contained_html_file(tmp_path: Path):
    d = kb_dir(tmp_path)
    t = write_transcript(
        tmp_path, [user_row("tickets/open-new-flight.md"), usage_row("a1")]
    )
    runner.invoke(app, ["usage", "ingest-transcript", str(t), "--kb-dir", str(d)])

    result = runner.invoke(app, ["usage", "report", "--kb-dir", str(d)])

    assert result.exit_code == 0, result.output
    html = (d / "usage" / "report.html").read_text(encoding="utf-8")
    assert "open-new-flight" in html
    assert "<script" not in html.lower()


def test_report_md_prints_to_stdout_and_writes_nothing(tmp_path: Path):
    d = kb_dir(tmp_path)
    t = write_transcript(tmp_path, [usage_row("a1")])
    runner.invoke(app, ["usage", "ingest-transcript", str(t), "--kb-dir", str(d)])

    result = runner.invoke(app, ["usage", "report", "--md", "--kb-dir", str(d)])

    assert result.exit_code == 0, result.output
    assert result.output.lstrip().startswith("| ")
    assert not (d / "usage" / "report.html").exists()


def test_report_ticket_filter_keeps_only_that_ticket(tmp_path: Path):
    d = kb_dir(tmp_path)
    t = write_transcript(
        tmp_path,
        [
            user_row("tickets/open-new-flight.md"), usage_row("a1"),
            user_row("tickets/ATM-7.md"), usage_row("a2"),
        ],
    )
    runner.invoke(app, ["usage", "ingest-transcript", str(t), "--kb-dir", str(d)])

    result = runner.invoke(
        app, ["usage", "report", "--ticket", "ATM-7", "--json", "--kb-dir", str(d)]
    )

    data = json.loads(result.output)
    assert [b["key"] for b in data["by_ticket"]] == ["ATM-7"]


def test_report_on_an_empty_ledger_says_so_and_exits_zero(tmp_path: Path):
    d = kb_dir(tmp_path)

    result = runner.invoke(app, ["usage", "report", "--md", "--kb-dir", str(d)])

    assert result.exit_code == 0, result.output
    assert "no usage" in result.output.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cli_usage.py -v`
Expected: FAIL with exit code 2 — typer reports `No such command 'usage'`.

- [ ] **Step 3: Register the sub-typer**

In `src/center_kb/cli.py`, immediately after the `svc_app` registration (`cli.py:35-36`), add:

```python
usage_app = typer.Typer(
    help="Token/cost measurement: ingest transcripts, record rows, render a report."
)
app.add_typer(usage_app, name="usage")
```

- [ ] **Step 4: Add the three commands**

In `src/center_kb/cli.py`, add the following after the body of `svc_note` — the last `@svc_app.command` in the file — so the file keeps its one-group-after-another order. Do not interleave these with another group's commands.

```python
def _usage_actor(kb_dir: Path) -> str:
    """The row's actor is the repo's declared kind, never an agent's claim.

    An unset `kind:` reads as "unknown" rather than being guessed from the
    directory layout: a wrong actor silently mis-attributes a whole repo's
    cost to the other side of the workflow.
    """
    from center_kb import config

    return config.load_config(kb_dir).kind or "unknown"


def _usage_log_error(kb_dir: Path, message: str) -> None:
    from center_kb.usage import ledger as _ledger

    path = _ledger.usage_dir(kb_dir) / "ingest-errors.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(message.rstrip() + "\n")


@usage_app.command("ingest-transcript")
def usage_ingest_transcript(
    path: Path | None = typer.Argument(
        None, help="Claude Code transcript JSONL (omit with --hook-stdin)"
    ),
    hook_stdin: bool = typer.Option(
        False, "--hook-stdin", help="Read the hook payload (JSON) from stdin"
    ),
    ticket: str = typer.Option(
        "", "--ticket", help="Force this ticket id for every row in the file"
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    json_out: bool = typer.Option(False, "--json", help="Machine-readable report"),
) -> None:
    """Append this transcript's API calls to the usage ledger.

    Safe to repeat: rows are de-duplicated by the transcript row's uuid, which
    is what lets the `Stop` hook re-ingest the same growing file every turn.
    """
    from center_kb.usage import ledger, transcript

    session = ""
    source = path
    if hook_stdin:
        raw = sys.stdin.read()
        try:
            payload = json.loads(raw)
            source = Path(payload["transcript_path"])
            session = str(payload.get("session_id") or "")
        except (ValueError, KeyError, TypeError) as exc:
            # ALWAYS exit 0 in hook mode: a Stop hook exiting non-zero blocks
            # Claude from ending its turn, so a bad payload must not be able to
            # freeze a dev's session.
            _usage_log_error(kb_dir, f"hook payload unreadable ({exc}): {raw[:200]}")
            return
        if path is not None:
            _usage_log_error(
                kb_dir, "both a path and --hook-stdin were given; used the payload"
            )
    elif source is None:
        # Written to stdout, not stderr, matching `svc_note`'s failure style at
        # cli.py:784-788. The suite's CliRunner reads `result.output`, and
        # whether that includes stderr varies with the Click version — a
        # message the test cannot see is a message that stops being checked.
        typer.secho(
            "pass exactly one of a transcript path or --hook-stdin",
            fg=typer.colors.RED,
        )
        raise typer.Exit(2)

    try:
        rows = transcript.rows_from_transcript(
            source,
            actor=_usage_actor(kb_dir),
            session_fallback=session,
            forced_ticket=ticket or None,
        )
        report = ledger.append_rows(kb_dir, rows)
    except (OSError, ledger.LedgerError) as exc:
        if hook_stdin:
            _usage_log_error(kb_dir, f"ingest failed for {source}: {exc}")
            return
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)

    if hook_stdin:
        return  # silent: the hook's output would land in the session
    if json_out:
        typer.echo(
            json.dumps(
                {
                    "written": report.written,
                    "duplicates": report.duplicates,
                    "files": report.files,
                }
            )
        )
    else:
        typer.echo(
            f"{report.written} new row(s), {report.duplicates} already recorded"
            + (f" -> {', '.join(report.files)}" if report.files else "")
        )


@usage_app.command("note")
def usage_note(
    ticket: str = typer.Option(..., "--ticket", help="Ticket / mission id"),
    phase: str = typer.Option(..., "--phase", help="Workflow phase, e.g. dev-plan"),
    model: str = typer.Option(..., "--model", help="Model id"),
    tokens_in: int = typer.Option(..., "--tokens-in"),
    tokens_out: int = typer.Option(..., "--tokens-out"),
    cache_read: int = typer.Option(0, "--cache-read"),
    cache_write_1h: int = typer.Option(0, "--cache-write-1h"),
    cache_write_5m: int = typer.Option(0, "--cache-write-5m"),
    est: bool = typer.Option(
        False, "--est", help="Mark the numbers as an estimate, not a measurement"
    ),
    assistant: str = typer.Option("claude-code", "--assistant"),
    session: str = typer.Option("", "--session"),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
) -> None:
    """Append one usage row by hand — for an assistant with no hook, or to
    repair an attribution the cursor got wrong."""
    import uuid as _uuid
    from datetime import datetime, timezone

    from center_kb.usage import ledger

    row = ledger.UsageRow(
        uuid=str(_uuid.uuid4()),
        ts=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        session=session,
        actor=_usage_actor(kb_dir),
        phase=phase,
        ticket=ticket,
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cache_read=cache_read,
        cache_write_5m=cache_write_5m,
        cache_write_1h=cache_write_1h,
        sidechain=False,
        branch=None,
        assistant=assistant,
        est=est,
    )
    try:
        report = ledger.append_rows(kb_dir, [row])
    except ledger.LedgerError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.echo(f"recorded -> {', '.join(report.files)}")


@usage_app.command("report")
def usage_report(
    ticket: str = typer.Option("", "--ticket", help="Only this ticket"),
    md: bool = typer.Option(False, "--md", help="Print Markdown to stdout"),
    json_out: bool = typer.Option(False, "--json", help="Print JSON to stdout"),
    out: Path | None = typer.Option(
        None, "--out", help="HTML output path (default: <kb-dir>/usage/report.html)"
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
) -> None:
    """Aggregate the usage ledger: per ticket, phase, model, actor."""
    from datetime import date, datetime, timezone

    from center_kb.usage import ledger, prices, report as report_mod

    rows = ledger.read_rows(kb_dir)
    if ticket:
        rows = [r for r in rows if r.ticket == ticket]
    if not rows:
        typer.echo(
            "no usage recorded yet — run `kb usage ingest-transcript <path>` on a "
            "Claude Code transcript, or check that the Stop hook is wired"
        )
        return
    agg = report_mod.aggregate(
        rows,
        prices.load_prices(kb_dir),
        today=date.today(),
        generated=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    if md:
        typer.echo(report_mod.render_markdown(agg))
        return
    if json_out:
        typer.echo(agg.model_dump_json(indent=2))
        return
    target = out or (ledger.usage_dir(kb_dir) / "report.html")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report_mod.render_html(agg), encoding="utf-8", newline="\n")
    typer.echo(f"wrote {target}")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_cli_usage.py -v`
Expected: PASS, all tests.

- [ ] **Step 6: Verify the frozen trip-wires did not move**

Run: `python -m pytest tests/test_mcp.py tests/test_templates.py -v`
Expected: PASS. Check `tests-gate/golden/mcp_tools.json` for modification, not `tests/mcp_tools.json` — that path does not exist (see the Global Constraints note). If `test_mcp.py` fails, an MCP tool's signature or docstring was touched — revert that, never regenerate the golden.

- [ ] **Step 7: Commit**

```bash
git add src/center_kb/cli.py tests/test_cli_usage.py
git commit -m "feat: kb usage ingest-transcript / note / report"
```

---

### Task 6: Scaffold the hook, and document it

The capture path only exists in a repo once the hook is wired, and a wrong
`settings.json` write destroys a dev's own configuration — so the scaffold, the
protected-file entry, and the docs ship together.

**Files:**
- Create: `src/center_kb/templates/init/claude-settings-usage.json`
- Modify: `src/center_kb/initcmd.py` (`BA_TEMPLATES` at `:69-90`, `DEV_TEMPLATES` at `:96-145`, `PROTECTED_FILES` at `:145`)
- Modify: `src/center_kb/templates/init/QUICKSTART-ba.md`, `src/center_kb/templates/init/QUICKSTART-dev.md`
- Test: `tests/test_init.py`

**Interfaces:**
- Consumes: the `kb usage ingest-transcript --hook-stdin` command from Task 5. Scaffolding a hook that calls a command which does not exist would wire every `ba`/`dev` repo to a failing hook.
- Produces: no code interface. Scaffolded files and prose.

The hook JSON shape below is **copied from a working `~/.claude/settings.json` on
this machine**, not inferred: an event name maps to a list of groups, each group
has a `hooks` list of `{type, command}` objects, and `matcher` is optional and
omitted for events that have no tool to match.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_init.py`:

```python
def test_settings_json_is_scaffolded_for_ba_and_dev(tmp_path: Path):
    for kind in ("ba", "dev"):
        target = tmp_path / kind
        init_repo(target, kind)
        settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
        commands = [
            hook["command"]
            for group in settings["hooks"]["Stop"]
            for hook in group["hooks"]
        ]
        assert commands == ["kb usage ingest-transcript --hook-stdin"], kind


def test_settings_json_is_not_scaffolded_for_hub_or_child(tmp_path: Path):
    # A hub or child repo authors no tickets, so every row would be
    # unattributed — 0.6s per turn for noise.
    for kind in ("hub", "child"):
        assert ".claude/settings.json" not in expected_files(kind), kind


def test_settings_json_is_protected_from_a_second_init(tmp_path: Path):
    # initcmd overwrites any file outside PROTECTED_FILES, and a dev's own
    # hooks live in this file.
    init_repo(tmp_path, "dev")
    path = tmp_path / ".claude" / "settings.json"
    path.write_text('{"hooks": {}, "mine": true}', encoding="utf-8")

    report = init_repo(tmp_path, "dev")

    assert ".claude/settings.json" in report.skipped
    assert json.loads(path.read_text(encoding="utf-8"))["mine"] is True


def test_quickstart_ba_documents_the_usage_hook(tmp_path: Path):
    init_repo(tmp_path, "ba")
    text = " ".join((tmp_path / "QUICKSTART-BA.md").read_text(encoding="utf-8").split())
    assert "kb usage report" in text
    assert "adds about 0.6s per turn" in text
    assert "kb usage ingest-transcript" in text
    # The ledger is the record; the HTML is derived. Someone who commits the
    # HTML and edits it has edited nothing that survives the next report run.
    assert "generated, not a record" in text


def test_quickstart_dev_documents_the_usage_hook(tmp_path: Path):
    init_repo(tmp_path, "dev")
    text = " ".join((tmp_path / "QUICKSTART-DEV.md").read_text(encoding="utf-8").split())
    assert "kb usage report" in text
    assert "adds about 0.6s per turn" in text
```

`tests/test_init.py` does **not** import `json` today (its import block at
`tests/test_init.py:1-13` is `os`, `shutil`, `subprocess`, `sys`, `Path`,
`pytest`, `yaml`, `CliRunner`, `initcmd`, `app`, `expected_files`, `init_repo`,
`write_cli_stub`). Add `import json` alongside `import os`.

Then change the numeric pin at `tests/test_init.py:1432`:

```python
    # 27 (Stage A) + 4 (dev-code-seed's own four-way wrappers) + 12 (the
    # reused kb-summarize/kb-approve/kb-publish rows the seed flow needs,
    # Stage C) + 1 (.claude/settings.json, the usage Stop hook) = 44.
    assert len(expected_files("dev")) == 44
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_init.py -k "settings_json or usage_hook or kind_dev" -v`
Expected: FAIL — `FileNotFoundError` for `.claude/settings.json`, and the dev count assertion fails at 43 != 44.

- [ ] **Step 3: Write the settings template**

Create `src/center_kb/templates/init/claude-settings-usage.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "kb usage ingest-transcript --hook-stdin",
            "timeout": 30,
            "statusMessage": "Recording token usage..."
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 4: Wire it into `initcmd`**

In `src/center_kb/initcmd.py`, add one row to `BA_TEMPLATES` (after
`".mcp.json"`, keeping the file's grouping) and the same row to
`DEV_TEMPLATES`:

```python
    ".claude/settings.json": "claude-settings-usage.json",
```

Then extend `PROTECTED_FILES` (`initcmd.py:145`):

```python
# User data — never refreshed by default; only overwritten with --force.
# `.claude/settings.json` joins the set because a dev's own hooks, permissions
# and model settings live there: initcmd overwrites anything outside this set
# (see the write branch below), which would silently delete their config on the
# next `kb init`. The cost of protecting it is that a repo scaffolded before
# the usage hook existed never gains it automatically — QUICKSTART carries the
# snippet to paste, which is the cheaper failure.
PROTECTED_FILES: frozenset[str] = frozenset(
    {".kb/index.yaml", ".kb/config.yaml", ".claude/settings.json"}
)
```

- [ ] **Step 5: Document it in both QUICKSTARTs**

In `src/center_kb/templates/init/QUICKSTART-ba.md`, add a section before
`## CLI reference`:

```markdown
## Token and cost measurement

`kb init` wrote `.claude/settings.json` with one `Stop` hook that calls
`kb usage ingest-transcript --hook-stdin` after each turn. It reads Claude
Code's own transcript — the numbers are the assistant's real usage, not an
estimate — and appends them to `.kb/usage/<ticket>.jsonl`, which is committed,
so a ticket's cost travels with the ticket.

It **adds about 0.6s per turn** (the cost of starting the `kb` CLI; parsing the
transcript itself is ~60ms). That is the price of the data.

- `kb usage report` — writes `.kb/usage/report.html`; open it in a browser. Per
  ticket, per phase, per model, plus a `_unattributed` bucket.
- `kb usage report --ticket <id> --md` — a Markdown table for a PR body.
- `kb usage ingest-transcript <path>` — backfill. Every transcript under
  `~/.claude/projects/<this-repo>/` can be ingested now; re-ingesting is safe,
  rows are de-duplicated by the transcript's own row ids.
- `kb usage note --ticket <id> --phase <p> --model <m> --tokens-in N --tokens-out N`
  — record a row by hand, or repair one the automatic attribution got wrong.

A row is attributed to whichever ticket file the session mentioned most
recently (`tickets/<id>.md`, `missions/<id>.md`,
`docs/impl/<id>-{design,plan}.md`). Work done before any ticket file is
mentioned lands in `_unattributed.jsonl` — a large bucket there means
attribution is missing work, not that the work was free.

If this repo already had a `.claude/settings.json`, `kb init` left it alone.
Merge the hook in by hand:

```json
{"hooks": {"Stop": [{"hooks": [
  {"type": "command", "command": "kb usage ingest-transcript --hook-stdin"}
]}]}}
```

`.kb/usage/report.html` is generated, not a record — the committed `.jsonl`
ledgers are. Regenerate it whenever you want with `kb usage report`; commit it
only if you want it browsable on GitHub.

Prices come from a table shipped with the package; override it per model in
`.kb/usage-prices.yaml`. The report prints the table's `effective_date` and
warns when it is over 90 days old. A model with no rates is reported as
`unpriced` with its token counts — never as free.
```

Add to that file's CLI reference:

```markdown
- `kb usage report [--ticket <id>] [--md]` — token and cost totals for this
  repo's tickets
- `kb usage ingest-transcript <path>` — backfill usage from a Claude Code
  transcript
```

In `src/center_kb/templates/init/QUICKSTART-dev.md`, add the same
"Token and cost measurement" section, with two changes: say
`docs/impl/<ticket-id>-{design,plan}.md` first in the attribution list (that is
what a dev session touches), and add this line after the backfill bullet:

```markdown
- Subagent cost is recorded separately (`sidechain`), so a `dev-execute` run
  that fans work out to subagents shows where the tokens actually went.
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_init.py -v`
Expected: PASS, including the four new tests and the updated `44` pin.

- [ ] **Step 7: Commit**

```bash
git add src/center_kb/templates/init/claude-settings-usage.json src/center_kb/initcmd.py src/center_kb/templates/init/QUICKSTART-ba.md src/center_kb/templates/init/QUICKSTART-dev.md tests/test_init.py
git commit -m "feat: scaffold the usage Stop hook for ba/dev repos and document it"
```

---

### Task 7: Prove it on real data (operations, no code)

Unit tests prove the rules; this proves the pipeline against transcripts nobody
designed for it. It has no test cycle — its deliverable is observed output.

**Files:**
- Modify: none in this repository. Writes ledger files in the BA repo being measured.

**Interfaces:**
- Consumes: the installed build from Tasks 1-6.
- Produces: a populated `.kb/usage/` and a rendered report in a real repo, plus the numbers reported back.

- [ ] **Step 1: Install this branch's build**

```bash
python -m pip install -e .
kb usage report --help
```

Expected: the help text prints. If `usage` is not a known command group, the wrong build is installed — fix that before continuing, or the rest of this task measures nothing.

- [ ] **Step 2: Backfill a real BA repo**

The operator names the BA repo and its transcript directory. If you were not
given them, stop and ask — do not guess a path.

```bash
BA_REPO="<path to the BA repo>"
PROJ="$HOME/.claude/projects/<slug for that repo>"
for f in "$PROJ"/*.jsonl; do
  kb usage ingest-transcript "$f" --kb-dir "$BA_REPO/.kb"
done
```

Expected: each run prints `N new row(s), M already recorded`. Running the whole
loop a second time must print `0 new row(s)` for every file — that is invariant
I1 observed on real data, not on a fixture.

- [ ] **Step 3: Render and read the report**

```bash
kb usage report --kb-dir "$BA_REPO/.kb"
```

Open the written `report.html`. Check four things and write down what you see:

1. Tickets in the report match the ticket files that repo really has.
2. The `_unattributed` bucket is a minority of the total. If it dominates, the
   ticket cursor is missing the way that repo refers to its tickets — report the
   number, do not tune the rule to fit one repo.
3. Phases are real workflow names (`ba-ticket-author`, …), not `unknown`
   everywhere. All-`unknown` means the `<command-name>` marker is not where the
   parser looks.
4. No model lands in `unpriced` unless it genuinely is a model the price table
   does not carry.

- [ ] **Step 4: Verify the live hook once**

In the BA repo, with the scaffolded `.claude/settings.json` in place, run one
short Claude Code session that touches a ticket file. Then:

```bash
git -C "$BA_REPO" status --short .kb/usage/
```

Expected: the ticket's `.jsonl` grew. If nothing changed, the hook did not fire —
check the `hooks` block's shape against `/hooks` and check
`.kb/usage/ingest-errors.log`.

- [ ] **Step 5: Report**

State plainly: how many transcripts were ingested, how many rows, the totals per
ticket, what fraction was unattributed, which phases appeared, and whether the
live hook fired. Report the unattributed fraction even when it is embarrassing —
it is the number that says whether attribution works.

---

## Verification before claiming done

Run and paste the output — do not summarise:

```bash
python -m pytest -q
```

Expected: all tests pass. Specifically confirm:

- `tests/test_mcp.py` passed. **Correction found during Task 5's review: `tests/mcp_tools.json` does not exist.** `tests/test_mcp.py` compares no golden; the real MCP contract golden is `tests-gate/golden/mcp_tools.json`, compared by `tests-gate/regression/test_mcp_contract.py`, and `tests-gate/` sits outside `testpaths` so a plain `pytest` run never reaches it. Check that file, not the one this plan originally named. The structural reason the golden is safe: `src/center_kb/mcp.py` never imports `center_kb.cli`, so a new typer group cannot reach the tool list.
- `tests/test_templates.py` passed with no canon edit — no skill wrapper was touched.
- `tests/test_init.py` passed with the dev pin at `44`, and that this is the only scaffold-count change.
- `git diff --stat` lists nothing under `src/center_kb/templates/init/claude-skill-*`, `copilot-*`, or `cursor-*`.
