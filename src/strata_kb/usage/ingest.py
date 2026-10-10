"""ingest — which transcript files one ingest reads, and with what cursor.

A session is a main transcript plus one transcript per subagent. A `Stop`
hook ingests the main file and sweeps its subagents, holding back each
subagent's last call because that call may still be streaming. A
`SubagentStop` hook ingests one finished subagent file in full. A manual
backfill ingests whatever path it is given, the session being over.

The two hooks overlap on purpose and global uuid dedup (I2) makes that safe:
whichever of them stores a call first stores it, and the other counts it as
a duplicate. The held-back last call is the one thing only `SubagentStop`
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
    except OSError as exc:
        # `parent_cursor` reads the file with errors="replace" and skips any
        # line that is not JSON, so reading it is the only way it can fail.
        # No call is dropped for want of attribution: the subagent's own
        # cursor still applies, and the miss is reported.
        result.notes.append(f"parent transcript unreadable, own cursor only: {parent}: {exc}")
        return None


def ingest_subagent(kb_dir: Path, path: Path, *, parent: Path | None, actor: str,
                    session: str = "", ticket: str | None = None,
                    hold_back_last: bool = False,
                    result: IngestResult | None = None) -> IngestResult:
    """One subagent transcript, every row sidechain, starting from `parent`'s
    cursor at the subagent's first timestamp.

    `result`, when given, is filled in place and returned: a caller that must
    report notes even if this raises (hook mode) passes its own, and the main
    sweep passes one so a whole session adds up to one report.
    """
    result = result if result is not None else IngestResult()
    rows = _subagent_rows(path, parent=parent, actor=actor, session=session,
                          ticket=ticket, hold_back_last=hold_back_last, result=result)
    result.add(ledger.append_rows(kb_dir, rows))
    return result


def _subagent_rows(path: Path, *, parent: Path | None, actor: str, session: str,
                   ticket: str | None, hold_back_last: bool,
                   result: IngestResult) -> list[UsageRow]:
    """Read one subagent transcript — the only step of a subagent ingest that
    can raise `OSError` for that file alone, kept apart from the ledger write
    so the main sweep can absorb exactly this failure and nothing else."""
    return transcript.rows_from_transcript(
        path, actor=actor, session_fallback=session, forced_ticket=ticket,
        subagent=True, parent=_parent(parent, result), hold_back_last=hold_back_last)


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
    """
    result = result if result is not None else IngestResult()
    rows = transcript.rows_from_transcript(
        main, actor=actor, session_fallback=session, forced_ticket=ticket)
    result.add(ledger.append_rows(kb_dir, rows))
    for sub in transcript.subagent_transcripts(main):
        try:
            rows = _subagent_rows(sub, parent=main, actor=actor, session=session,
                                  ticket=ticket, hold_back_last=hold_back_subagents,
                                  result=result)
        except OSError as exc:
            # One subagent file that cannot be read (deleted between the glob
            # and the read, a directory that matches the pattern, no
            # permission) costs that file only: the main rows are already
            # stored, the other subagents still are, and the next `Stop` (or
            # that subagent's own `SubagentStop`) retries it. Only the READ
            # is absorbed — a ledger failure (`LedgerError`, or an `OSError`
            # writing the ledger) still propagates, since every later file
            # would hit it too.
            result.notes.append(f"subagent transcript unreadable, skipped: {sub}: {exc}")
            continue
        result.add(ledger.append_rows(kb_dir, rows))
    return result


def ingest_path(kb_dir: Path, path: Path, *, actor: str,
                ticket: str | None = None) -> IngestResult:
    """The manual entry point: whatever transcript a human names.

    A `subagents/agent-*.jsonl` path is ingested as a subagent, attributed
    from its session's main transcript when that file is still there; any
    other path is a main transcript, its subagents included. Nothing is held
    back — a backfill runs after the session is over.
    """
    if transcript.is_subagent_transcript(path):
        parent = transcript.parent_of(path)
        return ingest_subagent(kb_dir, path, parent=parent if parent.is_file() else None,
                               actor=actor, ticket=ticket)
    return ingest_main(kb_dir, path, actor=actor, ticket=ticket, hold_back_subagents=False)
