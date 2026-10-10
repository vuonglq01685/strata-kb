"""ingest — which transcript files one ingest reads, and with what cursor.

A session is a main transcript plus one transcript per subagent. A `Stop`
hook ingests the main file and sweeps its subagents, holding back each
subagent's last call because that call may still be streaming. A
`SubagentStop` hook ingests one finished subagent file in full. A manual
backfill ingests whatever path it is given, the session being over.

The two hooks overlap on purpose, and can run at the same moment (a
background subagent finishing while the main turn ends). That is safe
because `ledger.append_rows` runs its global uuid dedup (I2) and its append
under one lock: whichever ingest takes the lock first stores a call, and the
other counts it as a duplicate. The held-back last call is the one thing only `SubagentStop`
(or a later manual backfill) can store, because only it knows the subagent
has finished.

This module owns orchestration only. Parsing and attribution stay in
`transcript`, storage in `ledger`; how a failure is reported (a red line, or
one line in `ingest-errors.log`) stays with the caller.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from strata_kb.usage import ledger, transcript
from strata_kb.usage.ledger import UsageRow


@dataclass
class IngestResult:
    """What one ingest stored, plus anything it had to work around.

    `notes` are not failures: every call was still read and stored, but
    something cost attribution (a parent transcript that could not be read,
    say). The caller decides where a note goes; in hook mode that is the
    error log, the only channel a hook has.
    """

    report: ledger.AppendReport = field(default_factory=ledger.AppendReport)
    notes: list[str] = field(default_factory=list)

    def add(self, other: ledger.AppendReport) -> None:
        self.report.written += other.written
        self.report.duplicates += other.duplicates
        self.report.files = sorted(set(self.report.files) | set(other.files))


def _parent(parent: Path | None, result: IngestResult) -> transcript.ParentCursor | None:
    if parent is None:
        return None
    try:
        return transcript.parent_cursor(parent)
    except (OSError, ValueError) as exc:
        # `parent_cursor` reads the file with errors="replace" and skips any
        # line that is not JSON, so reading it is the only way it can fail:
        # `OSError` for a missing or unreadable file, `ValueError` for a path
        # the OS cannot even name (an embedded NUL from a hook payload).
        # No call is dropped for want of attribution: the subagent's own
        # cursor still applies, and the miss is reported.
        result.notes.append(f"parent transcript unreadable, own cursor only: {parent}: {exc}")
        return None


def _subagent_rows(path: Path, *, cursor: transcript.ParentCursor | None, actor: str,
                   session: str, ticket: str | None,
                   hold_back_last: bool) -> list[UsageRow]:
    """Read one subagent transcript, every row sidechain, starting from the
    parent's `cursor` at the subagent's first timestamp.

    Reading is the only step of a subagent ingest that can raise `OSError`
    for that one file, which is why it is kept apart from the ledger write:
    the main sweep absorbs exactly this failure and nothing else.
    """
    return transcript.rows_from_transcript(
        path, actor=actor, session_fallback=session, forced_ticket=ticket,
        subagent=True, parent=cursor, hold_back_last=hold_back_last)


def ingest_subagent(kb_dir: Path, path: Path, *, parent: Path | None, actor: str,
                    session: str = "", ticket: str | None = None,
                    hold_back_last: bool = False,
                    result: IngestResult | None = None) -> IngestResult:
    """One subagent transcript, attributed from `parent`'s cursor.

    `result`, when given, is filled in place and returned: a caller that must
    report notes even if this raises (hook mode) passes its own.
    """
    result = result if result is not None else IngestResult()
    rows = _subagent_rows(path, cursor=_parent(parent, result), actor=actor,
                          session=session, ticket=ticket, hold_back_last=hold_back_last)
    result.add(ledger.append_rows(kb_dir, rows))
    return result


def ingest_main(kb_dir: Path, main: Path, *, actor: str, session: str = "",
                ticket: str | None = None, hold_back_subagents: bool,
                result: IngestResult | None = None) -> IngestResult:
    """A main transcript in full, then every subagent transcript beside it.

    The main file is never held back: a `Stop` hook fires once the main
    agent's turn is over, so its last call is complete. A subagent can still
    be running then (a background agent), so the hook passes
    `hold_back_subagents=True`; a manual backfill, the session being over,
    passes False. A subagent file that cannot be read becomes a note and the
    sweep moves on to the next one; the main transcript itself still raises.

    The parent cursor is walked once per sweep, not once per subagent, and
    the whole session is stored in ONE `append_rows` call: one ledger scan
    and one lock per `Stop`, whatever the number of subagents.
    """
    result = result if result is not None else IngestResult()
    rows = transcript.rows_from_transcript(
        main, actor=actor, session_fallback=session, forced_ticket=ticket)
    subs = transcript.subagent_transcripts(main)
    cursor = _parent(main, result) if subs else None
    for sub in subs:
        try:
            rows += _subagent_rows(sub, cursor=cursor, actor=actor, session=session,
                                   ticket=ticket, hold_back_last=hold_back_subagents)
        except OSError as exc:
            # One subagent file that cannot be read (deleted between the glob
            # and the read, a directory that matches the pattern, no
            # permission) costs that file only: the main rows and the other
            # subagents are still stored, and the next `Stop` (or that
            # subagent's own `SubagentStop`) retries it. Only the READ is
            # absorbed — a ledger failure (`LedgerError`, or an `OSError`
            # writing the ledger) happens below, outside this `try`, and
            # still propagates.
            result.notes.append(f"subagent transcript unreadable, skipped: {sub}: {exc}")
    result.add(ledger.append_rows(kb_dir, rows))
    return result


def ingest_path(kb_dir: Path, path: Path, *, actor: str,
                ticket: str | None = None,
                result: IngestResult | None = None) -> IngestResult:
    """The manual entry point: whatever transcript a human names.

    A `subagents/agent-*.jsonl` path is ingested as a subagent, attributed
    from its session's main transcript when that file is still there (a note
    says so when it is not); any other path is a main transcript, its
    subagents included. Nothing is held back — a backfill runs after the
    session is over. `result` as in `ingest_subagent`.
    """
    result = result if result is not None else IngestResult()
    if transcript.is_subagent_transcript(path):
        parent = transcript.parent_of(path)
        if not parent.is_file():
            result.notes.append(f"no parent transcript, own cursor only: {parent}")
        return ingest_subagent(kb_dir, path, parent=parent if parent.is_file() else None,
                               actor=actor, ticket=ticket, result=result)
    return ingest_main(kb_dir, path, actor=actor, ticket=ticket, hold_back_subagents=False,
                       result=result)


def _payload_path(payload: dict, key: str) -> Path:
    """A path the hook payload must carry, or a `ValueError` naming the key."""
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"hook payload has no usable {key}: {value!r}")
    return Path(value)


def ingest_hook_payload(kb_dir: Path, payload: object, *, actor: str,
                        ticket: str | None = None,
                        result: IngestResult | None = None) -> IngestResult:
    """Dispatch one `Stop` or `SubagentStop` hook payload (parsed JSON).

    A `SubagentStop` payload carries `agent_transcript_path`: that one
    finished subagent is ingested in full. Its `transcript_path` (the main
    transcript) only lends attribution, so a missing, empty, non-string or
    unreadable one is a note, never a failure — the subagent is stored on its
    own cursor. A `Stop` payload ingests its `transcript_path` and sweeps the
    subagents, holding back each one's possibly in-flight last call for
    `SubagentStop`.

    Raises on a payload that names nothing to ingest; the caller, which must
    exit 0 whatever happens, logs it. Pass `result` to keep notes collected
    before a failure.
    """
    result = result if result is not None else IngestResult()
    if not isinstance(payload, dict):
        raise ValueError(f"hook payload is not a JSON object: {type(payload).__name__}")
    session = str(payload.get("session_id") or "")
    if payload.get("agent_transcript_path") is not None:
        agent = _payload_path(payload, "agent_transcript_path")
        raw_parent = payload.get("transcript_path")
        parent: Path | None = None
        if isinstance(raw_parent, str) and raw_parent:
            parent = Path(raw_parent)
        else:
            result.notes.append(
                f"hook payload has no usable transcript_path ({raw_parent!r}), "
                f"own cursor only: {agent}")
        return ingest_subagent(kb_dir, agent, parent=parent, actor=actor,
                               session=session, ticket=ticket, result=result)
    return ingest_main(kb_dir, _payload_path(payload, "transcript_path"), actor=actor,
                       session=session, ticket=ticket, hold_back_subagents=True,
                       result=result)
