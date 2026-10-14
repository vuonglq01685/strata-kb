"""Ticket Q&A store and hub-aware operations."""

from __future__ import annotations

import re
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from strata_kb import ticketfetch
from strata_kb.ticketqa import (
    QaError,
    QaStore,
    answer_question,
    ask_question,
    derive_state,
    format_questions,
    list_questions,
    qa_db_path,
    ticket_revision,
)
from tests.test_planingest import US1
from tests.test_planingest import context_block as _context_block
from tests.test_ticketfetch import publish_plan

REPO = "ba-one"


@pytest.fixture
def store(tmp_path: Path) -> QaStore:
    return QaStore(tmp_path / "qa" / "qa.db")


def test_qa_db_path_sits_in_the_hub_root(tmp_path: Path):
    assert qa_db_path(tmp_path) == tmp_path / ".kb-qa" / "qa.db"


def test_ask_records_hub_revision_and_lists_open(hub_with_ticket, store):
    hub = hub_with_ticket(rev=3)
    q = ask_question(
        hub,
        store,
        US1,
        "Which currency?",
        "dev1",
        context="design §Pricing",
        blocks="AC-2",
    )
    assert (q.repo, q.ticket, q.asked_rev, q.blocks) == (REPO, US1, 3, "AC-2")
    assert (q.answer, q.answer_rev, q.ticket_sections) == (None, None, [])
    [(row, state, rev)] = list_questions(hub, store, ticket_ref=US1)
    assert (row, state, rev) == (q, "open", 3)


def test_ask_accepts_qualified_ref(hub_with_ticket, store):
    q = ask_question(hub_with_ticket(), store, f"{REPO}:{US1}", "Why?", "dev1")
    assert (q.repo, q.ticket) == (REPO, US1)


def test_answer_with_rev_is_waiting_until_hub_catches_up(hub_with_ticket, store):
    hub = hub_with_ticket(rev=3)
    q = ask_question(hub, store, US1, "Which currency?", "dev1")
    a = answer_question(hub, store, q.id, "EUR", "ba1", 4, ["Acceptance Criteria"])
    assert (a.answer, a.answer_rev, a.answered_by) == ("EUR", 4, "ba1")
    assert a.ticket_sections == ["Acceptance Criteria"] and a.answered_at
    assert list_questions(hub, store, status="open") == []
    [(_, state, rev)] = list_questions(hub, store, status="waiting")
    assert (state, rev) == ("waiting", 3)
    hub_with_ticket(rev=4)
    [(_, state, rev)] = list_questions(hub, store, status="answered")
    assert (state, rev) == ("answered", 4)


def test_answer_without_rev_is_answered_at_once(hub_with_ticket, store):
    hub = hub_with_ticket()
    q = ask_question(hub, store, US1, "Q?", "dev1")
    answer_question(hub, store, q.id, "already in AC-1", "ba1", None, [])
    [(_, state, _)] = list_questions(hub, store, status="all")
    assert state == "answered"


def test_answer_rev_must_exceed_hub_revision(hub_with_ticket, store):
    hub = hub_with_ticket(rev=3)
    q = ask_question(hub, store, US1, "Q?", "dev1")
    with pytest.raises(QaError, match="the hub already has revision 3"):
        answer_question(hub, store, q.id, "EUR", "ba1", 3, ["Scope"])
    assert store.get(q.id).answer is None  # type: ignore[union-attr]


def test_sections_required_iff_answer_rev(hub_with_ticket, store):
    hub = hub_with_ticket(rev=3)
    q = ask_question(hub, store, US1, "Q?", "dev1")
    with pytest.raises(QaError, match="ticket_sections"):
        answer_question(hub, store, q.id, "EUR", "ba1", 4, [])
    with pytest.raises(QaError, match="ticket_sections"):
        answer_question(hub, store, q.id, "EUR", "ba1", None, ["Scope"])
    assert answer_question(hub, store, q.id, "EUR", "ba1", None, []).answer == "EUR"


def test_answering_twice_names_first_answerer(hub_with_ticket, store):
    hub = hub_with_ticket()
    q = ask_question(hub, store, US1, "Q?", "dev1")
    answer_question(hub, store, q.id, "EUR", "ba1", None, [])
    with pytest.raises(QaError, match="ba1"):
        answer_question(hub, store, q.id, "USD", "ba2", None, [])
    with pytest.raises(QaError, match="ba1"):
        store.answer(q.id, "USD", "ba2", None, [])
    assert store.get(q.id).answer == "EUR"  # type: ignore[union-attr]


def test_answer_unknown_id(hub_with_ticket, store):
    with pytest.raises(QaError, match="Q99"):
        answer_question(hub_with_ticket(), store, 99, "x", "ba1", None, [])


def test_second_answer_session_still_needs_a_higher_rev(hub_with_ticket, store):
    hub = hub_with_ticket(rev=3)
    q1 = ask_question(hub, store, US1, "Q1?", "dev1")
    q2 = ask_question(hub, store, US1, "Q2?", "dev1")
    answer_question(hub, store, q1.id, "A1", "ba1", 4, ["Scope"])
    hub_with_ticket(rev=4)
    with pytest.raises(QaError, match="the hub already has revision 4"):
        answer_question(hub, store, q2.id, "A2", "ba1", 4, ["Scope"])
    assert answer_question(hub, store, q2.id, "A2", "ba1", 5, ["Scope"]).answer_rev == 5


def test_caps_and_empties(hub_with_ticket, store):
    hub = hub_with_ticket()
    for kwargs in (
        {"question": "x" * 4001},
        {"question": ""},
        {"question": "  "},
        {"context": "x" * 1001},
        {"asked_by": "x" * 101},
        {"asked_by": ""},
    ):
        args = {"question": "Q?", "asked_by": "dev1", **kwargs}
        with pytest.raises(QaError):
            ask_question(hub, store, US1, **args)
    assert store.list() == []
    ask_question(hub, store, US1, "x" * 4000, "d" * 100, context="c" * 1000)

    q = ask_question(hub, store, US1, "Q?", "dev1")
    for bad in ("", "x" * 4001):
        with pytest.raises(QaError):
            answer_question(hub, store, q.id, bad, "ba1", None, [])
    with pytest.raises(QaError):
        answer_question(hub, store, q.id, "A", "", None, [])
    with pytest.raises(QaError):
        answer_question(hub, store, q.id, "A", "x" * 101, None, [])


def test_ticket_sections_are_capped_at_fifty(hub_with_ticket, store):
    hub = hub_with_ticket(rev=3)
    q = ask_question(hub, store, US1, "Q?", "dev1")
    with pytest.raises(QaError, match="at most 50"):
        answer_question(hub, store, q.id, "A", "ba1", 4, [f"S{i}" for i in range(51)])
    assert store.get(q.id).answer is None  # type: ignore[union-attr]
    ok = answer_question(hub, store, q.id, "A", "ba1", 4, [f"S{i}" for i in range(50)])
    assert len(ok.ticket_sections) == 50


@pytest.mark.parametrize("bad", ["a\nb", "a\rb", "a\tb", "a\x0bb", "a\x0cb", "a\x00b"])
def test_names_reject_control_characters(hub_with_ticket, store, bad):
    hub = hub_with_ticket(rev=3)
    with pytest.raises(QaError, match="control character"):
        ask_question(hub, store, US1, "Q?", bad)
    assert store.list() == []
    q = ask_question(hub, store, US1, "Q?", "dev1")
    with pytest.raises(QaError, match="control character"):
        answer_question(hub, store, q.id, "A", bad, None, [])
    with pytest.raises(QaError, match="control character"):
        answer_question(hub, store, q.id, "A", "ba1", 4, [bad])
    assert store.get(q.id).answer is None  # type: ignore[union-attr]
    # question and answer text keep their newlines
    ask_question(hub, store, US1, "line one\nline two", "dev1")
    assert answer_question(hub, store, q.id, "x\ny", "ba1", None, []).answer == "x\ny"


@pytest.mark.parametrize("bad_id", [0, -1, 2**63, 10**30])
def test_answer_id_outside_sqlite_range_is_a_qa_error(hub_with_ticket, store, bad_id):
    with pytest.raises(QaError, match="question number"):
        answer_question(hub_with_ticket(), store, bad_id, "x", "ba1", None, [])


def test_fifty_first_open_question_on_a_ticket_is_refused(hub_with_ticket, store):
    hub = hub_with_ticket()
    for i in range(50):
        ask_question(hub, store, US1, f"Q{i}?", "dev1")
    with pytest.raises(QaError, match="50 open"):
        ask_question(hub, store, US1, "one too many", "dev1")
    first = store.list()[0]
    answer_question(hub, store, first.id, "A", "ba1", None, [])
    ask_question(hub, store, US1, "fits again", "dev1")


def test_unknown_and_ambiguous_ticket_reuse_ticketfetch_errors(
    hub_with_ticket, store, tmp_path
):
    hub = hub_with_ticket()
    with pytest.raises(ticketfetch.TicketFetchError, match="not on the hub"):
        ask_question(hub, store, "M-nope-US9", "Q?", "dev1")
    publish_plan(hub.root, "ba-two", tmp_path / "ba-two", _context_block(hub.root))
    with pytest.raises(ticketfetch.TicketFetchError, match="qualify it as"):
        ask_question(hub, store, US1, "Q?", "dev1")
    assert store.list() == []


def test_ticket_removed_from_hub_keeps_questions(hub_with_ticket, store):
    hub = hub_with_ticket(rev=3)
    open_q = ask_question(hub, store, US1, "open?", "dev1")
    done = ask_question(hub, store, US1, "done?", "dev1")
    wait = ask_question(hub, store, US1, "wait?", "dev1")
    answer_question(hub, store, done.id, "yes", "ba1", None, [])
    answer_question(hub, store, wait.id, "later", "ba1", 4, ["Scope"])
    shutil.rmtree(hub.root / "federation" / REPO)

    assert ticket_revision(hub, REPO, US1) is None
    rows = list_questions(hub, store, repo=REPO, status="all")
    assert [(r.id, s, rev) for r, s, rev in rows] == [
        (open_q.id, "open", None),
        (done.id, "answered", None),
        (wait.id, "waiting", None),
    ]
    assert "hub rev —" in format_questions(rows)


def test_nested_repo_id_round_trips(hub_with_ticket, store):
    q = store.ask("mid/ba-x", "M-x-US1", "Q?", "", "", "dev1", 1)
    store.ask(REPO, "M-x-US1", "other", "", "", "dev1", 1)
    assert store.get(q.id) == q
    assert [
        r.id for r, _, _ in list_questions(hub_with_ticket(), store, repo="mid/ba-x")
    ] == [q.id]
    assert [r.id for r in store.list(repo="mid/ba-x", ticket="M-x-US1")] == [q.id]


def test_list_filters_by_ticket_ref_and_status(hub_with_ticket, store):
    hub = hub_with_ticket()
    q = ask_question(hub, store, US1, "Q?", "dev1")
    store.ask(REPO, "M-other-US2", "else", "", "", "dev1", 1)
    got = list_questions(hub, store, ticket_ref=f"{REPO}:{US1}", status="all")
    assert [r.id for r, _, _ in got] == [q.id]
    assert list_questions(hub, store, ticket_ref=f"nope:{US1}") == []
    with pytest.raises(QaError, match="status"):
        list_questions(hub, store, status="bogus")


def test_format_questions(hub_with_ticket, store):
    hub = hub_with_ticket(rev=3)
    q = ask_question(
        hub, store, US1, "Which currency?", "dev1", "design §Pricing", "AC-2"
    )
    answer_question(hub, store, q.id, "EUR", "ba1", 4, ["Scope", "Acceptance Criteria"])
    text = format_questions(list_questions(hub, store, status="all"))
    assert text.startswith(f"Q{q.id} [waiting] {REPO}:{US1} (hub rev 3)")
    for needle in (
        "Which currency?",
        "design §Pricing",
        "AC-2",
        "dev1",
        "EUR",
        "ba1",
        "Scope, Acceptance Criteria",
    ):
        assert needle in text
    assert format_questions([]) == "No questions."


def test_derive_state_table(store):
    def q(answer, answer_rev):
        base = store.ask(REPO, "T", "Q?", "", "", "d", 1)
        return replace(base, answer=answer, answer_rev=answer_rev)

    assert derive_state(q(None, None), 3) == "open"
    assert derive_state(q("a", None), 3) == "answered"
    assert derive_state(q("a", None), None) == "answered"
    assert derive_state(q("a", 4), 3) == "waiting"
    assert derive_state(q("a", 4), 4) == "answered"
    assert derive_state(q("a", 4), None) == "waiting"


def test_answer_rev_refused_while_ticket_is_off_the_hub(hub_with_ticket, store):
    hub = hub_with_ticket(rev=3)
    q = ask_question(hub, store, US1, "Q?", "dev1")
    shutil.rmtree(hub.root / "federation" / REPO)
    with pytest.raises(
        QaError,
        match=re.escape(
            f"{REPO}:{US1} is not on the hub — publish it before recording "
            "an answer that changes it"
        ),
    ):
        answer_question(hub, store, q.id, "EUR", "ba1", 4, ["Scope"])
    assert store.get(q.id).answer is None  # type: ignore[union-attr]
    done = answer_question(hub, store, q.id, "no change", "ba1", None, [])
    assert done.answer == "no change"


def test_unreadable_ticket_is_an_error_not_gone(hub_with_ticket, store):
    hub = hub_with_ticket()
    q = ask_question(hub, store, US1, "Q?", "dev1")
    l3 = ticketfetch.find(hub, US1)[2]
    l3.unlink()
    l3.mkdir()  # exists but cannot be read as a file
    with pytest.raises(ticketfetch.TicketFetchError, match="could not read"):
        ticket_revision(hub, REPO, US1)
    with pytest.raises(ticketfetch.TicketFetchError, match="could not read"):
        list_questions(hub, store)
    with pytest.raises(ticketfetch.TicketFetchError, match="could not read"):
        answer_question(hub, store, q.id, "A", "ba1", 2, ["Scope"])
    assert store.get(q.id).answer is None  # type: ignore[union-attr]


def test_blocks_is_capped_and_answer_rev_must_be_positive(hub_with_ticket, store):
    hub = hub_with_ticket()
    with pytest.raises(QaError, match="blocks"):
        ask_question(hub, store, US1, "Q?", "dev1", blocks="x" * 1001)
    ask_question(hub, store, US1, "Q?", "dev1", blocks="x" * 1000)
    q = store.list()[0]
    for bad in (0, -1):
        with pytest.raises(QaError, match="answer_rev must be 1 or more"):
            answer_question(hub, store, q.id, "A", "ba1", bad, ["Scope"])
        with pytest.raises(QaError, match="answer_rev must be 1 or more"):
            store.answer(q.id, "A", "ba1", bad, ["Scope"])
    assert store.get(q.id).answer is None  # type: ignore[union-attr]


def test_ticket_revision_loads_once_and_makes_no_git_call(hub_with_ticket, monkeypatch):
    hub = hub_with_ticket(rev=4)
    finds = []
    real_find = ticketfetch.find

    def counting_find(*args):
        finds.append(args)
        return real_find(*args)

    def forbidden(*_a, **_k):
        raise AssertionError("ticket_revision must not render or call git")

    monkeypatch.setattr(ticketfetch, "find", counting_find)
    monkeypatch.setattr(ticketfetch, "render", forbidden)
    monkeypatch.setattr(ticketfetch.gitio, "head_commit", forbidden)

    assert ticket_revision(hub, REPO, US1) == 4
    assert len(finds) == 1


def test_ticket_revision_none_when_gone_and_error_when_unreadable(hub_with_ticket):
    hub = hub_with_ticket(rev=2)
    assert ticket_revision(hub, REPO, "TAL-GONE") is None
    ticketfetch.find(hub, US1)[2].unlink()
    with pytest.raises(ticketfetch.TicketFetchError, match="could not read"):
        ticket_revision(hub, REPO, US1)
