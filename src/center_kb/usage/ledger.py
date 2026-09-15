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

from pydantic import BaseModel, ValidationError

from center_kb.errors import KbError

UNATTRIBUTED = "_unattributed"

# A stem is read out of transcript CONTENT and then used as a filename, so it
# is validated, not sanitised: anything that is not obviously a ticket name is
# rejected outright rather than silently rewritten into one.
STEM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")


class LedgerError(KbError):
    """A ticket id cannot be turned into a ledger file name. Its CLI call
    site already converts it to a one-line message -- joins the KbError
    family (Wave G fix round 2, item 7)."""


def is_safe_stem(stem: str) -> bool:
    # fullmatch, not match: Python's `$` also matches just before a trailing
    # newline, so `match` would accept "open-new-flight\n" — and a trailing
    # newline is exactly what survives naive line handling of the transcript
    # this stem is read out of. On POSIX that forks one ticket's ledger into
    # two files; on Windows it raises OSError from inside a Stop hook.
    return stem not in {".", ".."} and bool(STEM_RE.fullmatch(stem))


class UsageRow(BaseModel):
    """One API call's usage, as recorded by the assistant that made it.

    ONE API CALL, not one transcript row. Claude Code splits a single assistant
    message across several transcript rows and repeats the same `usage` block on
    each, so `uuid` (the row's id) is finer than a call: keying on it counted one
    call once per row, measured as 516 rows for 239 real calls across six live
    transcripts — 55.8% too much money. `request` carries the call's own identity
    and `transcript.py` collapses on it.

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
    # Defaulted, not required: ledgers written before this field existed are
    # committed to git and must keep loading. An empty value means "written by a
    # build that could not tell one call from one row" — those files were
    # inflated and need re-ingesting, which `kb usage report` cannot infer.
    request: str = ""


@dataclass
class AppendReport:
    written: int = 0
    duplicates: int = 0
    files: list[str] = field(default_factory=list)


def usage_dir(kb_dir: Path) -> Path:
    return kb_dir / "usage"


def hook_errors(kb_dir: Path) -> tuple[int, str]:
    """(number of logged hook failures, last log line) — (0, '') without a log."""
    path = usage_dir(kb_dir) / "ingest-errors.log"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0, ""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return len(lines), (lines[-1] if lines else "")


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
    """Every uuid already stored in one ledger file.

    Scanned on every append (global dedup, invariant I2), so one
    unparseable line here must never be skipped — a skipped uuid would be
    re-appended on the next ingest. It raises `LedgerError` naming
    `path:lineno` instead, so a corrupt line blocks the write loudly rather
    than silently duplicating the row it hid.
    """
    if not path.exists():
        return set()
    found: set[str] = set()
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            uuid = json.loads(line)["uuid"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise LedgerError(f"unparseable ledger line {path}:{lineno}: {exc}") from exc
        found.add(uuid)
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
                fh.write(json.dumps(row.model_dump(mode="json"), ensure_ascii=False) + "\n")
        report.written += len(bucket)
        report.files.append(path.name)
    return report


def read_rows(kb_dir: Path) -> list[UsageRow]:
    """Every row in the ledger, files in name order, rows in file order.

    A line that is not valid JSON or does not fit `UsageRow`'s schema raises
    `LedgerError` naming `path:lineno` rather than a raw `json.JSONDecodeError`
    or `pydantic.ValidationError` traceback — these files are committed and
    appended from multiple branches, so merge-resolution damage is the
    realistic source of a corrupt line, not an exotic one.
    """
    out: list[UsageRow] = []
    directory = usage_dir(kb_dir)
    if not directory.exists():
        return out
    for path in sorted(directory.glob("*.jsonl")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                out.append(UsageRow.model_validate_json(line))
            except ValidationError as exc:
                # pydantic's own JSON parser raises ValidationError (not
                # json.JSONDecodeError) for malformed JSON too — this one
                # except clause covers both a bad line and a well-formed
                # line that fails UsageRow's schema.
                raise LedgerError(f"unparseable ledger line {path}:{lineno}: {exc}") from exc
    return out
