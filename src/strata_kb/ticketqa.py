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
import re
import sqlite3
import unicodedata
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from strata_kb import lintcore, planrev, ticketfetch
from strata_kb import ticket as ticketmod
from strata_kb.errors import KbError
from strata_kb.hub import HubHandle

MAX_QUESTION = 4000
MAX_ANSWER = 4000
MAX_CONTEXT = 1000
MAX_NAME = 100
MAX_OPEN_PER_TICKET = 50
MAX_SECTIONS = 50
MAX_QUESTION_ID = 2**63 - 1  # SQLite INTEGER

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
    answered_at TEXT,
    asked_from TEXT,
    proposed_blocks TEXT,
    confirmed_by TEXT
)
"""
_COLUMNS = (
    "id, repo, ticket, question, context, blocks, asked_by, asked_at, asked_rev, "
    "answer, answer_rev, ticket_sections, answered_by, answered_at, "
    "asked_from, proposed_blocks, confirmed_by"
)
# Added after the first release: an older db gets them by ALTER in QaStore.
_ADDED_COLUMNS = ("asked_from", "proposed_blocks", "confirmed_by")


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
    asked_from: str | None = None
    proposed_blocks: str | None = None
    confirmed_by: str | None = None


def qa_db_path(hub_root: Path) -> Path:
    return hub_root / ".kb-qa" / "qa.db"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _text(label: str, value: str, cap: int, *, required: bool = True) -> None:
    if required and not value.strip():
        raise QaError(f"{label} must not be empty")
    if len(value) > cap:
        raise QaError(f"{label} is {len(value)} characters; the limit is {cap}")


def _name(label: str, value: str) -> None:
    """A name or section name: one printable line, so it cannot forge a line
    in a list, a log or the web page."""
    _text(label, value, MAX_NAME)
    if any(unicodedata.category(c).startswith("C") for c in value):
        raise QaError(f"{label} must not contain a control character")


def _check_answer_rev(answer_rev: int | None) -> None:
    if answer_rev is not None and answer_rev < 1:
        raise QaError(f"answer_rev must be 1 or more, not {answer_rev}")


def _row_to_question(row: tuple) -> Question:
    (id, repo, ticket, question, context, blocks, asked_by, asked_at, asked_rev) = row[
        :9
    ]
    answer, answer_rev, sections, answered_by, answered_at = row[9:14]
    asked_from, proposed_blocks, confirmed_by = row[14:]
    return Question(
        id, repo, ticket, question, context, blocks, asked_by, asked_at, asked_rev,
        answer, answer_rev, json.loads(sections), answered_by, answered_at,
        asked_from, proposed_blocks, confirmed_by,
    )  # fmt: skip


class QaStore:
    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.execute(_SCHEMA)
            conn.execute("BEGIN IMMEDIATE")  # two openers must not both ALTER
            have = {r[1] for r in conn.execute("PRAGMA table_info(questions)")}
            for col in _ADDED_COLUMNS:
                if col not in have:
                    conn.execute(f"ALTER TABLE questions ADD COLUMN {col} TEXT")

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
        asked_from: str | None = None,
    ) -> Question:
        _text("question", question, MAX_QUESTION)
        _text("context", context, MAX_CONTEXT, required=False)
        _text("blocks", blocks, MAX_CONTEXT, required=False)
        _name("asked_by", asked_by)
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
                "asked_by, asked_at, asked_rev, asked_from) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    repo,
                    ticket,
                    question,
                    context,
                    blocks,
                    asked_by,
                    now,
                    asked_rev,
                    asked_from,
                ),
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
            asked_from,
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
        _name("answered_by", answered_by)
        _check_answer_rev(answer_rev)
        if answer_rev is not None and not ticket_sections:
            raise QaError(
                "ticket_sections must name what changed when answer_rev is set"
            )
        if answer_rev is None and ticket_sections:
            raise QaError("ticket_sections must be empty when answer_rev is not set")
        if len(ticket_sections) > MAX_SECTIONS:
            raise QaError(
                f"ticket_sections names {len(ticket_sections)} sections; "
                f"at most {MAX_SECTIONS}"
            )
        for name in ticket_sections:
            _name("ticket section name", name)
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

    def _update_open(self, id: int, sql: str, args: tuple, *, need_proposal: bool):
        """Run `sql` on an unanswered question, under the write lock."""
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT answer, proposed_blocks FROM questions WHERE id = ?", (id,)
            ).fetchone()
            if row is None:
                raise QaError(f"Q{id} does not exist")
            if row[0] is not None:
                raise QaError(f"Q{id} is already answered")
            if need_proposal and row[1] is None:
                raise QaError(f"Q{id} has no proposed blocks to confirm")
            conn.execute(sql, (*args, id))
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM questions WHERE id = ?",  # noqa: S608 - constant columns
                (id,),
            ).fetchone()
        return _row_to_question(row)

    def propose_blocks(self, id: int, blocks: str, reason: str) -> Question:
        """Record "<AC ids> — <reason>", replacing any earlier proposal and
        its confirmation. It blocks nothing until `confirm_blocks`."""
        _text("blocks", blocks, MAX_CONTEXT)
        _text("reason", reason, MAX_CONTEXT)
        ids = sorted(ac_ids(blocks), key=lambda a: int(a[2:]))
        if not ids:
            raise QaError(f"blocks names no AC id (e.g. AC2): {blocks!r}")
        return self._update_open(
            id,
            "UPDATE questions SET proposed_blocks = ?, confirmed_by = NULL WHERE id = ?",
            (f"{', '.join(ids)} — {reason.strip()}",),
            need_proposal=False,
        )

    def confirm_blocks(self, id: int, confirmed_by: str) -> Question:
        _name("confirmed_by", confirmed_by)
        return self._update_open(
            id,
            "UPDATE questions SET confirmed_by = ? WHERE id = ?",
            (confirmed_by,),
            need_proposal=True,
        )


def derive_state(q: Question, hub_rev: int | None) -> State:
    if q.answer is None:
        return "open"
    if q.answer_rev is None:
        return "answered"
    return "waiting" if hub_rev is None or hub_rev < q.answer_rev else "answered"


def _read_section(hub: HubHandle, repo: str, ticket: str) -> str:
    _, doc, l3 = ticketfetch.find(hub, f"{repo}:{ticket}")
    return ticketfetch.read_section(l3, doc, ticket)


def _read_revision(hub: HubHandle, repo: str, ticket: str) -> int:
    """One federation load and one L3 read: no `render`, no git call (the
    Q&A list asks for every ticket it shows)."""
    return planrev.parse_revision(_read_section(hub, repo, ticket)) or 1


_AC_REF_RE = re.compile(r"\bAC-?(\d+)\b", re.I)


def ac_ids(text: str) -> frozenset[str]:
    """`AC3`, `AC-3` and `ac3` in `text`, each normalised to `AC3`."""
    return frozenset(f"AC{int(n)}" for n in _AC_REF_RE.findall(text))


def effective_blocks(q: Question) -> frozenset[str]:
    """The ACs the question blocks: its own `blocks`, plus the Dev's
    proposal once a BA has confirmed it."""
    ids_part = (q.proposed_blocks or "").partition(" — ")[0]  # not the reason
    proposed = ac_ids(ids_part) if q.confirmed_by else frozenset()
    return ac_ids(q.blocks) | proposed


def _parent_pin(section: str) -> tuple[str, int] | None:
    return ticketmod.parent_story_pin(ticketfetch.source_text(section))


def _ticket_acs(section: str) -> frozenset[str]:
    items = lintcore.ac_items(ticketfetch.source_text(section))
    return frozenset(
        f"AC{int(m.group(1))}" for i in items if (m := _AC_REF_RE.match(i))
    )


def ticket_revision(hub: HubHandle, repo: str, ticket: str) -> int | None:
    """The ticket's `> Revision: N` on the hub (1 when absent); None when the
    ticket is no longer published. Any other lookup failure (unreadable file,
    ambiguity) propagates: it is not "gone"."""
    try:
        return _read_revision(hub, repo, ticket)
    except ticketfetch.TicketNotOnHub:
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
    section = _read_section(hub, repo, ticket)
    pin = _parent_pin(section)
    if pin is None:
        rev = planrev.parse_revision(section) or 1
        return store.ask(repo, ticket, question, context, blocks, asked_by, rev)
    parent = pin[0]
    try:
        rev = _read_revision(hub, repo, parent)
    except ticketfetch.TicketNotOnHub as exc:
        raise QaError(
            f"parent story {parent} is not on the hub — publish it before asking "
            f"about {ticket}"
        ) from exc
    return store.ask(
        repo, parent, question, context, blocks, asked_by, rev, asked_from=ticket
    )


def answer_question(
    hub: HubHandle,
    store: QaStore,
    id: int,
    answer: str,
    answered_by: str,
    answer_rev: int | None,
    ticket_sections: list[str],
) -> Question:
    if not 1 <= id <= MAX_QUESTION_ID:
        raise QaError(f"id must be a question number from 1 to {MAX_QUESTION_ID}")
    q = store.get(id)
    if q is None:
        raise QaError(f"Q{id} does not exist")
    if q.answer is not None:
        raise QaError(
            f"Q{id} was already answered by {q.answered_by} at {q.answered_at}"
        )
    _check_answer_rev(answer_rev)
    if answer_rev is not None:
        hub_rev = ticket_revision(hub, q.repo, q.ticket)
        if hub_rev is None:
            raise QaError(
                f"{q.repo}:{q.ticket} is not on the hub — publish it before "
                "recording an answer that changes it"
            )
        if answer_rev <= hub_rev:
            raise QaError(
                f"the hub already has revision {hub_rev} — amend the ticket "
                "and bump its revision"
            )
    return store.answer(id, answer, answered_by, answer_rev, ticket_sections)


def _check_id(id: int) -> None:
    if not 1 <= id <= MAX_QUESTION_ID:
        raise QaError(f"id must be a question number from 1 to {MAX_QUESTION_ID}")


def propose_blocks(store: QaStore, id: int, blocks: str, reason: str) -> Question:
    _check_id(id)
    return store.propose_blocks(id, blocks, reason)


def confirm_blocks(store: QaStore, id: int, confirmed_by: str) -> Question:
    _check_id(id)
    return store.confirm_blocks(id, confirmed_by)


def list_questions(
    hub: HubHandle,
    store: QaStore,
    ticket_ref: str = "",
    repo: str = "",
    status: str = "open",
) -> list[tuple[Question, str, int | None, bool | None]]:
    """Rows `(question, state, hub revision, blocks_this)`. With a
    `ticket_ref`, a split child's list also holds its parent's questions, and
    `blocks_this` says whether the question blocks that ticket (None without
    one)."""
    if status not in STATUSES:
        raise QaError(f"status must be one of {', '.join(STATUSES)}, not {status!r}")
    ticket = None
    if ticket_ref.strip():
        ref_repo, ticket = ticketfetch.split_ref(ticket_ref)
        repo = ref_repo or repo
    found = list(store.list(repo or None, ticket))
    if ticket is not None:
        found += _parent_questions(hub, store, repo, ticket)
        found = sorted({q.id: q for q in found}.values(), key=lambda q: q.id)
    revisions: dict[tuple[str, str], int | None] = {}
    acs: dict[str, frozenset[str]] = {}
    rows: list[tuple[Question, str, int | None, bool | None]] = []
    for q in found:
        key = (q.repo, q.ticket)
        if key not in revisions:
            revisions[key] = ticket_revision(hub, *key)
        state = derive_state(q, revisions[key])
        if status not in ("all", state):
            continue
        blocks_this = None
        if ticket is not None:
            if q.repo not in acs:
                acs[q.repo] = _acs_on_hub(hub, q.repo, ticket)
            blocks_this = bool(effective_blocks(q) & acs[q.repo])
        rows.append((q, state, revisions[key], blocks_this))
    return rows


def _acs_on_hub(hub: HubHandle, repo: str, ticket: str) -> frozenset[str]:
    try:
        return _ticket_acs(_read_section(hub, repo, ticket))
    except ticketfetch.TicketNotOnHub:
        return frozenset()


def _parent_questions(
    hub: HubHandle, store: QaStore, repo: str, ticket: str
) -> list[Question]:
    """The parent-story questions of `ticket` in `repo`, or in every repo
    that holds it when `repo` is empty. A repo whose copy is unreadable or
    ambiguous adds none."""
    repos = [repo] if repo else _repos_holding(hub, ticket)
    out: list[Question] = []
    for r in repos:
        try:
            pin = _parent_pin(_read_section(hub, r, ticket))
        except ticketfetch.TicketFetchError:
            continue
        if pin is not None:
            out += store.list(r, pin[0])
    return out


def _repos_holding(hub: HubHandle, ticket: str) -> list[str]:
    return sorted(
        {
            fed.meta.repo_id
            for fed, manifest in ticketfetch.plan_docs(hub, None)
            if any(sec.id == ticket for sec in manifest.sections)
        }
    )


def _field(label: str, value: str) -> str:
    return f"  {label}: " + value.replace("\n", "\n    ")


def format_questions(
    rows: list[tuple[Question, str, int | None, bool | None]],
) -> str:
    if not rows:
        return "No questions."
    blocks = []
    for q, state, rev, blocks_this in rows:
        lines = [
            f"Q{q.id} [{state}] {q.repo}:{q.ticket} (hub rev {'—' if rev is None else rev})",
            _field("question", q.question),
            _field("context", q.context or "-"),
            _field("blocks", q.blocks or "-"),
            _field("asked", f"{q.asked_by} at {q.asked_at} (rev {q.asked_rev})"),
        ]
        if q.proposed_blocks:
            lines.append(_field("proposed blocks", q.proposed_blocks))
        if q.confirmed_by:
            lines.append(_field("confirmed by", q.confirmed_by))
        if blocks_this is not None:
            lines.append(_field("blocks this ticket", "yes" if blocks_this else "no"))
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
