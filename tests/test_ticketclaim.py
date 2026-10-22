"""Ticket claim store: atomic grant, lazy expiry, token-guarded updates."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from strata_kb.errors import KbError
from strata_kb.ticketclaim import (
    DEFAULT_TTL,
    PHASES,
    STATES,
    WORKING_PHASES,
    BadClaimToken,
    ClaimError,
    ClaimLost,
    ClaimStore,
    ClaimTaken,
    UnknownClaim,
    claims_db_path,
)

PR = "https://github.com/acme/dev/pull/7"


class Clock:
    def __init__(self) -> None:
        self.t = datetime(2026, 10, 22, 9, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.t

    def advance(self, seconds: int) -> None:
        self.t += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(tmp_path: Path, clock: Clock) -> ClaimStore:
    return ClaimStore(tmp_path / "claims.db", ttl=100, now=clock)


def test_constants_and_path(tmp_path: Path):
    assert len(PHASES) == 8
    assert set(WORKING_PHASES) < set(PHASES)
    assert STATES == ("active", "stopped")
    assert DEFAULT_TTL == 14400
    assert claims_db_path(tmp_path) == tmp_path / ".kb-qa" / "claims.db"
    assert issubclass(ClaimTaken, ClaimError) and issubclass(ClaimError, KbError)


def test_take_then_taken(store):
    claim, token = store.take("ba-one", "US1", "a@m1")
    assert (claim.phase, claim.state, claim.holder) == ("claimed", "active", "a@m1")
    assert token
    with pytest.raises(ClaimTaken) as exc:
        store.take("ba-one", "US1", "b@m2")
    assert exc.value.claim.holder == "a@m1"


def test_take_other_ticket_is_independent(store):
    store.take("ba-one", "US1", "a@m1")
    store.take("ba-one", "US2", "b@m2")
    store.take("other", "US1", "c@m3")
    assert len(store.held()) == 3
    assert [c.ticket for c in store.held(repo="ba-one")] == ["US1", "US2"]
    assert [c.repo for c in store.held(ticket="US1")] == ["ba-one", "other"]


def test_retake_with_own_token_is_same_claim(store):
    claim, token = store.take("ba-one", "US1", "a@m1")
    again, token2 = store.take("ba-one", "US1", "a@m1", token=token)
    assert (again.id, token2) == (claim.id, token)


def test_take_with_wrong_token_is_taken(store):
    store.take("ba-one", "US1", "a@m1")
    with pytest.raises(ClaimTaken):
        store.take("ba-one", "US1", "a@m1", token="nope")


def test_concurrent_take_has_one_winner(tmp_path: Path, clock: Clock):
    path = tmp_path / "claims.db"
    ClaimStore(path, now=clock)
    barrier = threading.Barrier(8)
    winners: list[str] = []
    taken: list[str] = []

    def work(n: int) -> None:
        mine = ClaimStore(path, now=clock)
        barrier.wait()
        try:
            claim, _ = mine.take("ba-one", "US1", f"h{n}@m")
            winners.append(claim.holder)
        except ClaimTaken as e:
            taken.append(e.claim.holder)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(winners) == 1 and len(taken) == 7
    assert set(taken) == set(winners)


def test_expiry_boundary(store, clock):
    store.take("ba-one", "US1", "a@m1")
    clock.advance(99)
    assert store.held()
    clock.advance(1)
    assert store.held() == []
    assert store.last_closed("ba-one", "US1").close_reason == "expired"


def test_take_after_expiry_succeeds(store, clock):
    _, old = store.take("ba-one", "US1", "a@m1")
    clock.advance(100)
    claim, token = store.take("ba-one", "US1", "b@m2")
    assert claim.holder == "b@m2" and token != old


def test_update_bumps_last_seen_and_keeps_alive(store, clock):
    claim, token = store.take("ba-one", "US1", "a@m1")
    clock.advance(90)
    updated = store.update(claim.id, token, phase="design")
    assert updated.phase == "design" and updated.last_seen > claim.last_seen
    clock.advance(90)
    assert [c.phase for c in store.held()] == ["design"]


def test_update_after_expiry_raises_lost(store, clock):
    claim, token = store.take("ba-one", "US1", "a@m1")
    clock.advance(100)
    with pytest.raises(ClaimLost) as exc:
        store.update(claim.id, token, phase="design")
    assert exc.value.close_reason == "expired"
    assert exc.value.closed_by == "hub"
    assert store.last_closed("ba-one", "US1").close_reason == "expired"


def test_update_after_release_raises_lost(store):
    claim, token = store.take("ba-one", "US1", "a@m1")
    store.admin_release(claim.id, "root", "gone home")
    with pytest.raises(ClaimLost) as exc:
        store.update(claim.id, token, phase="design")
    assert (exc.value.close_reason, exc.value.closed_by) == ("admin: gone home", "root")


def test_update_bad_token_and_unknown_claim(store):
    claim, _ = store.take("ba-one", "US1", "a@m1")
    with pytest.raises(BadClaimToken):
        store.update(claim.id, "wrong", phase="design")
    with pytest.raises(UnknownClaim):
        store.update(999, "wrong", phase="design")
    assert store.held()[0].phase == "claimed"


def test_review_with_pr_never_expires(store, clock):
    claim, token = store.take("ba-one", "US1", "a@m1")
    store.update(claim.id, token, phase="review", pr=PR)
    clock.advance(10_000)
    assert [c.pr for c in store.held()] == [PR]


def test_publishing_with_pr_never_expires(store, clock):
    claim, token = store.take("ba-one", "US1", "a@m1")
    store.update(claim.id, token, phase="publishing", pr=PR)
    clock.advance(10_000)
    assert [c.phase for c in store.held()] == ["publishing"]


def test_review_without_pr_expires(store, clock):
    claim, token = store.take("ba-one", "US1", "a@m1")
    store.update(claim.id, token, phase="review")
    clock.advance(100)
    assert store.held() == []


def test_stopped_never_expires(store, clock):
    claim, token = store.take("ba-one", "US1", "a@m1")
    store.update(claim.id, token, state="stopped", stop_reason="ci-red x")
    clock.advance(10_000)
    (held,) = store.held()
    assert (held.state, held.stop_reason) == ("stopped", "ci-red x")


def test_stopped_resumed_to_active(store, clock):
    claim, token = store.take("ba-one", "US1", "a@m1")
    store.update(claim.id, token, state="stopped", stop_reason="ci-red x")
    clock.advance(10_000)
    resumed = store.update(claim.id, token, state="active")
    assert (resumed.state, resumed.stop_reason) == ("active", "")
    clock.advance(100)
    assert store.held() == []


def test_pr_closed_restarts_clock(store, clock):
    claim, token = store.take("ba-one", "US1", "a@m1")
    store.update(claim.id, token, phase="review", pr=PR)
    clock.advance(10_000)
    back = store.pr_closed(claim.id, PR)
    assert (back.phase, back.pr) == ("execute", "")
    clock.advance(99)
    assert store.held()
    clock.advance(1)
    assert store.held() == []


def test_pr_closed_wrong_pr(store):
    claim, token = store.take("ba-one", "US1", "a@m1")
    store.update(claim.id, token, phase="review", pr=PR)
    with pytest.raises(ClaimError, match="pr_mismatch"):
        store.pr_closed(claim.id, PR + "0")
    assert store.held()[0].pr == PR


def test_pr_closed_without_pr_is_mismatch(store):
    claim, _ = store.take("ba-one", "US1", "a@m1")
    with pytest.raises(ClaimError, match="pr_mismatch"):
        store.pr_closed(claim.id, "")


def test_pr_closed_unknown_claim(store):
    with pytest.raises(UnknownClaim):
        store.pr_closed(999, PR)


def test_release_frees_ticket(store):
    claim, token = store.take("ba-one", "US1", "a@m1")
    with pytest.raises(BadClaimToken):
        store.release(claim.id, "wrong", "done early")
    store.release(claim.id, token, "switching")
    last = store.last_closed("ba-one", "US1")
    assert (last.closed_by, last.close_reason) == ("a@m1", "released: switching")
    again, _ = store.take("ba-one", "US1", "b@m2")
    assert again.holder == "b@m2"


def test_release_twice_is_lost(store):
    claim, token = store.take("ba-one", "US1", "a@m1")
    store.release(claim.id, token, "x")
    with pytest.raises(ClaimLost):
        store.release(claim.id, token, "x")


def test_admin_release(store):
    claim, _ = store.take("ba-one", "US1", "a@m1")
    store.admin_release(claim.id, "root", "gone home")
    last = store.last_closed("ba-one", "US1")
    assert (last.closed_by, last.close_reason) == ("root", "admin: gone home")
    assert last.closed_at
    with pytest.raises(ClaimError):
        store.admin_release(claim.id, "root", "again")
    with pytest.raises(UnknownClaim):
        store.admin_release(999, "root", "x")


def test_close_done(store):
    store.take("ba-one", "US1", "a@m1")
    store.take("ba-one", "US2", "a@m1")
    store.close_done({("ba-one", "US1"), ("ba-one", "US9")})
    assert [c.ticket for c in store.held()] == ["US2"]
    last = store.last_closed("ba-one", "US1")
    assert (last.close_reason, last.closed_by) == ("done", "hub")
    store.close_done(set())


def test_last_closed_returns_newest(store):
    c1, t1 = store.take("ba-one", "US1", "a@m1")
    store.release(c1.id, t1, "one")
    c2, t2 = store.take("ba-one", "US1", "b@m2")
    store.release(c2.id, t2, "two")
    assert store.last_closed("ba-one", "US1").id == c2.id
    assert store.last_closed("ba-one", "nope") is None


@pytest.mark.parametrize(
    "holder", ["", "   ", "x" * 101, "a\nb@m"], ids=["empty", "blank", "long", "ctrl"]
)
def test_rejects_bad_holder(store, holder):
    with pytest.raises(ClaimError):
        store.take("ba-one", "US1", holder)


def test_rejects_bad_update_input(store):
    claim, token = store.take("ba-one", "US1", "a@m1")
    for kwargs in (
        {"phase": "coding"},
        {"state": "paused"},
        {"pr": "ftp://x"},
        {"pr": "https://" + "x" * 500},
        {"stop_reason": "x" * 1001},
    ):
        with pytest.raises(ClaimError):
            store.update(claim.id, token, **kwargs)
    with pytest.raises(ClaimError):
        store.release(claim.id, token, "x" * 1001)
    with pytest.raises(ClaimError):
        store.admin_release(claim.id, "", "x")
    assert store.held()[0].phase == "claimed"


def test_token_not_stored_in_clear(store, tmp_path):
    _, token = store.take("ba-one", "US1", "a@m1")
    assert token.encode() not in (tmp_path / "claims.db").read_bytes()
    assert not hasattr(store.held()[0], "token")
