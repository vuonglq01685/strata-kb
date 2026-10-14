"""Ticket Q&A on the hub: a Dev asks the BA a question about a published
ticket, the BA answers it, and the answer may amend the ticket.

Questions live in SQLite at `<hub root>/.kb-qa/qa.db` (kept out of git), one
short-lived connection per call, in the style of `serving/accounts`. State is
derived, never stored: `open` (no answer), `waiting` (answered with an
`answer_rev` the hub's ticket has not reached yet), `answered`. A ticket's
revision is its own `> Revision: N` line (`planrev`), not the hub's git HEAD.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from strata_kb import planrev, ticketfetch
from strata_kb.errors import KbError
from strata_kb.hub import HubHandle

MAX_QUESTION = 4000
MAX_ANSWER = 4000
MAX_CONTEXT = 1000
MAX_NAME = 100
MAX_OPEN_PER_TICKET = 50

State = Literal["open", "waiting", "answered"]
STATUSES: tuple[str, ...] = ("open", "waiting", "answered", "all")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT NOT NULL,
    ticket TEXT NOT NULL,
    question TEXT NOT NULL,
    context TEXT NOT NULL,
    blocks TEXT NOT NULL,
    asked_by TEXT NOT NULL,
    asked_at TEXT NOT NULL,
    asked_rev INTEGER NOT NULL,
    answer TEXT,
    answer_rev INTEGER,
    ticket_sections TEXT NOT NULL DEFAULT '[]',
    answered_by TEXT,
    answered_at TEXT
)
"""
_COLUMNS = (
    "id, repo, ticket, question, context, blocks, asked_by, asked_at, asked_rev, "
    "answer, answer_rev, ticket_sections, answered_by, answered_at"
)


class QaError(KbError):
    """Invalid Q&A operation (bad text, unknown or already-answered question, cap hit)."""


@dataclass(frozen=True)
class Question:
    id: int
    repo: str
    ticket: str
    question: str
    context: str
    blocks: str
    asked_by: str
    asked_at: str
    asked_rev: int
    answer: str | None
    answer_rev: int | None
    ticket_sections: list[str]
    answered_by: str | None
    answered_at: str | None


def qa_db_path(kb_dir: Path) -> Path:
    return kb_dir.parent / ".kb-qa" / "qa.db"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _text(label: str, value: str, cap: int, *, required: bool = True) -> None:
    if required and not value.strip():
        raise QaError(f"{label} must not be empty")
    if len(value) > cap:
        raise QaError(f"{label} is {len(value)} characters; the limit is {cap}")


def _row_to_question(row: tuple) -> Question:
    (id, repo, ticket, question, context, blocks, asked_by, asked_at, asked_rev) = row[
        :9
    ]
    answer, answer_rev, sections, answered_by, answered_at = row[9:]
    return Question(
        id, repo, ticket, question, context, blocks, asked_by, asked_at, asked_rev,
        answer, answer_rev, json.loads(sections), answered_by, answered_at,
    )  # fmt: skip


class QaStore:
    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.execute(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, timeout=10)

    def ask(
        self,
        repo: str,
        ticket: str,
        question: str,
        context: str,
        blocks: str,
        asked_by: str,
        asked_rev: int,
    ) -> Question:
        _text("question", question, MAX_QUESTION)
        _text("context", context, MAX_CONTEXT, required=False)
        _text("asked_by", asked_by, MAX_NAME)
        now = _now()
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "BEGIN IMMEDIATE"
            )  # the open-count check and insert are one step
            (open_count,) = conn.execute(
                "SELECT COUNT(*) FROM questions "
                "WHERE repo = ? AND ticket = ? AND answer IS NULL",
                (repo, ticket),
            ).fetchone()
            if open_count >= MAX_OPEN_PER_TICKET:
                raise QaError(
                    f"{repo}:{ticket} already has {MAX_OPEN_PER_TICKET} open "
                    "questions — wait for answers before asking more"
                )
            cur = conn.execute(
                "INSERT INTO questions (repo, ticket, question, context, blocks, "
                "asked_by, asked_at, asked_rev) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (repo, ticket, question, context, blocks, asked_by, now, asked_rev),
            )
        return Question(
            cur.lastrowid or 0,
            repo,
            ticket,
            question,
            context,
            blocks,
            asked_by,
            now,
            asked_rev,
            None,
            None,
            [],
            None,
            None,
        )

    def get(self, id: int) -> Question | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM questions WHERE id = ?",  # noqa: S608 - constant columns
                (id,),
            ).fetchone()
        return _row_to_question(row) if row else None

    def list(
        self, repo: str | None = None, ticket: str | None = None
    ) -> list[Question]:
        where = [
            f"{col} = ?" for col, val in (("repo", repo), ("ticket", ticket)) if val
        ]
        args = [val for val in (repo, ticket) if val]
        clause = f" WHERE {' AND '.join(where)}" if where else ""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM questions{clause} ORDER BY id",  # noqa: S608 - fixed fragments
                args,
            ).fetchall()
        return [_row_to_question(r) for r in rows]

    def answer(
        self,
        id: int,
        answer: str,
        answered_by: str,
        answer_rev: int | None,
        ticket_sections: list[str],
    ) -> Question:
        _text("answer", answer, MAX_ANSWER)
        _text("answered_by", answered_by, MAX_NAME)
        if answer_rev is not None and not ticket_sections:
            raise QaError(
                "ticket_sections must name what changed when answer_rev is set"
            )
        if answer_rev is None and ticket_sections:
            raise QaError("ticket_sections must be empty when answer_rev is not set")
        for name in ticket_sections:
            _text("ticket section name", name, MAX_NAME)
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "BEGIN IMMEDIATE"
            )  # two answerers: the second must see the first
            row = conn.execute(
                "SELECT answer, answered_by, answered_at FROM questions WHERE id = ?",
                (id,),
            ).fetchone()
            if row is None:
                raise QaError(f"Q{id} does not exist")
            if row[0] is not None:
                raise QaError(f"Q{id} was already answered by {row[1]} at {row[2]}")
            conn.execute(
                "UPDATE questions SET answer = ?, answer_rev = ?, ticket_sections = ?, "
                "answered_by = ?, answered_at = ? WHERE id = ?",
                (
                    answer,
                    answer_rev,
                    json.dumps(ticket_sections),
                    answered_by,
                    _now(),
                    id,
                ),
            )
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM questions WHERE id = ?",  # noqa: S608 - constant columns
                (id,),
            ).fetchone()
        return _row_to_question(row)


def derive_state(q: Question, hub_rev: int | None) -> State:
    if q.answer is None:
        return "open"
    if q.answer_rev is None:
        return "answered"
    return "waiting" if hub_rev is None or hub_rev < q.answer_rev else "answered"


def _read_revision(hub: HubHandle, repo: str, ticket: str) -> int:
    text = ticketfetch.render(hub, f"{repo}:{ticket}")
    return planrev.parse_revision(text) or 1


def ticket_revision(hub: HubHandle, repo: str, ticket: str) -> int | None:
    """The ticket's `> Revision: N` on the hub (1 when absent); None when the
    ticket is no longer published."""
    try:
        return _read_revision(hub, repo, ticket)
    except ticketfetch.TicketFetchError:
        return None


def ask_question(
    hub: HubHandle,
    store: QaStore,
    ticket_ref: str,
    question: str,
    asked_by: str,
    context: str = "",
    blocks: str = "",
) -> Question:
    repo, _, _ = ticketfetch.find(hub, ticket_ref)
    ticket = ticketfetch.split_ref(ticket_ref)[1]
    rev = _read_revision(hub, repo, ticket)
    return store.ask(repo, ticket, question, context, blocks, asked_by, rev)


def answer_question(
    hub: HubHandle,
    store: QaStore,
    id: int,
    answer: str,
    answered_by: str,
    answer_rev: int | None,
    ticket_sections: list[str],
) -> Question:
    q = store.get(id)
    if q is None:
        raise QaError(f"Q{id} does not exist")
    if q.answer is not None:
        raise QaError(
            f"Q{id} was already answered by {q.answered_by} at {q.answered_at}"
        )
    if answer_rev is not None:
        hub_rev = ticket_revision(hub, q.repo, q.ticket)
        # Ticket gone from the hub: nothing to compare with, the answer waits.
        if hub_rev is not None and answer_rev <= hub_rev:
            raise QaError(
                f"the hub already has revision {hub_rev} — amend the ticket "
                "and bump its revision"
            )
    return store.answer(id, answer, answered_by, answer_rev, ticket_sections)


def list_questions(
    hub: HubHandle,
    store: QaStore,
    ticket_ref: str = "",
    repo: str = "",
    status: str = "open",
) -> list[tuple[Question, str, int | None]]:
    if status not in STATUSES:
        raise QaError(f"status must be one of {', '.join(STATUSES)}, not {status!r}")
    ticket = None
    if ticket_ref.strip():
        ref_repo, ticket = ticketfetch.split_ref(ticket_ref)
        repo = ref_repo or repo
    revisions: dict[tuple[str, str], int | None] = {}
    rows: list[tuple[Question, str, int | None]] = []
    for q in store.list(repo or None, ticket):
        key = (q.repo, q.ticket)
        if key not in revisions:
            revisions[key] = ticket_revision(hub, *key)
        state = derive_state(q, revisions[key])
        if status in ("all", state):
            rows.append((q, state, revisions[key]))
    return rows


def _field(label: str, value: str) -> str:
    return f"  {label}: " + value.replace("\n", "\n    ")


def format_questions(rows: list[tuple[Question, str, int | None]]) -> str:
    if not rows:
        return "No questions."
    blocks = []
    for q, state, rev in rows:
        lines = [
            f"Q{q.id} [{state}] {q.repo}:{q.ticket} (hub rev {'—' if rev is None else rev})",
            _field("question", q.question),
            _field("context", q.context or "-"),
            _field("blocks", q.blocks or "-"),
            _field("asked", f"{q.asked_by} at {q.asked_at} (rev {q.asked_rev})"),
        ]
        if q.answer is not None:
            lines += [
                _field("answer", q.answer),
                _field(
                    "answer_rev", "-" if q.answer_rev is None else str(q.answer_rev)
                ),
                _field("sections", ", ".join(q.ticket_sections) or "-"),
                _field("answered", f"{q.answered_by} at {q.answered_at}"),
            ]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
