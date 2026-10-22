"""RunnerClaims and ClaimBeat against a fake ClaimClient."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import pytest

from strata_kb import ghrest
from strata_kb.autorun.claimbeat import ClaimBeat
from strata_kb.autorun.claims import RunnerClaims
from strata_kb.claimclient import ClaimLostError, ClaimTakenError, LocalClaims
from strata_kb.errors import KbError


def claim_dict(ticket="US1", **over) -> dict:
    return {
        "id": 7,
        "ticket": ticket,
        "holder": "me@m1",
        "phase": "claimed",
        "state": "active",
        "pr": "",
        **over,
    }


class FakeClient:
    def __init__(self, **claim_over):
        self.claim_over = claim_over
        self.calls: list[tuple] = []
        self.held_rows: list[dict] = []
        self.take_error: Exception | None = None
        self.update_error: Exception | None = None
        self.phase = "claimed"

    def take(self, ticket, holder, claim_token=None):
        self.calls.append(("take", ticket, holder, claim_token))
        if self.take_error:
            raise self.take_error
        return claim_dict(ticket, **self.claim_over), "tok"

    def update(self, claim_id, claim_token, **fields):
        self.calls.append(("update", claim_id, claim_token, fields))
        if self.update_error:
            raise self.update_error
        self.phase = fields.get("phase", self.phase)
        return claim_dict(
            phase=self.phase, **{k: v for k, v in fields.items() if k != "phase"}
        )

    def release(self, claim_id, claim_token, reason):
        self.calls.append(("release", claim_id, claim_token, reason))

    def held(self, repo="", ticket=""):
        return self.held_rows

    def pr_closed(self, claim_id, pr):
        self.calls.append(("pr_closed", claim_id, pr))
        return {}


@pytest.fixture
def kb_dir(tmp_path: Path) -> Path:
    (tmp_path / ".kb" / "auto").mkdir(parents=True)
    return tmp_path / ".kb"


def make(kb_dir: Path, client: FakeClient) -> RunnerClaims:
    return RunnerClaims(kb_dir.parent, kb_dir, client, "me@m1")  # type: ignore[arg-type]


def test_claim_takes_and_stores_token(kb_dir):
    client = FakeClient()
    assert make(kb_dir, client).claim("US1") is True
    assert client.calls == [("take", "US1", "me@m1", None)]
    assert LocalClaims(kb_dir).get("US1") == (7, "tok")


def test_claim_reuses_stored_token(kb_dir):
    LocalClaims(kb_dir).put("US1", 7, "old")
    client = FakeClient()
    make(kb_dir, client).claim("US1")
    assert client.calls[0] == ("take", "US1", "me@m1", "old")


def test_claim_taken_is_false_and_names_holder(kb_dir, caplog):
    client = FakeClient()
    client.take_error = ClaimTakenError({"holder": "bob@m2"})
    with caplog.at_level(logging.INFO):
        assert make(kb_dir, client).claim("US1") is False
    assert "bob@m2" in caplog.text
    assert LocalClaims(kb_dir).get("US1") is None


def test_resume_reactivates_own_stopped_claim(kb_dir):
    client = FakeClient(state="stopped")
    assert make(kb_dir, client).claim("US1") is True
    assert client.calls[-1] == ("update", 7, "tok", {"state": "active"})


def test_phase_updates_hub(kb_dir):
    client = FakeClient()
    claims = make(kb_dir, client)
    claims.claim("US1")
    assert claims.phase("US1", "publishing") is True
    assert client.calls[-1] == ("update", 7, "tok", {"phase": "publishing"})


def test_phase_lost_drops_local_entry(kb_dir):
    client = FakeClient()
    claims = make(kb_dir, client)
    claims.claim("US1")
    client.update_error = ClaimLostError("expired", "hub")
    assert claims.phase("US1", "execute") is False
    assert LocalClaims(kb_dir).get("US1") is None
    assert claims.lost_reason("US1") == "expired by hub"


def test_stop_marks_stopped_with_reason(kb_dir):
    client = FakeClient()
    claims = make(kb_dir, client)
    claims.claim("US1")
    claims.stop("US1", "ci-red http://pr")
    assert client.calls[-1] == (
        "update",
        7,
        "tok",
        {"state": "stopped", "stop_reason": "ci-red http://pr"},
    )


def test_beat_transient_error_is_not_lost(kb_dir, caplog):
    client = FakeClient()
    claims = make(kb_dir, client)
    claims.claim("US1")
    client.update_error = KbError("hub unreachable")
    with caplog.at_level(logging.WARNING):
        assert claims.beat("US1") is True
    assert "hub unreachable" in caplog.text
    assert LocalClaims(kb_dir).get("US1") == (7, "tok")


def test_beat_lost_is_false(kb_dir):
    client = FakeClient()
    claims = make(kb_dir, client)
    claims.claim("US1")
    client.update_error = ClaimLostError("admin: taken over", "root")
    assert claims.beat("US1") is False
    assert LocalClaims(kb_dir).get("US1") is None


def claimed(kb_dir, client):
    claims = make(kb_dir, client)
    claims.claim("US1")
    client.calls.clear()
    return claims


def released(client) -> bool:
    return any(c[0] == "release" for c in client.calls)


def test_release_if_working_releases_a_working_phase(kb_dir):
    client = FakeClient()
    claims = claimed(kb_dir, client)
    client.held_rows = [claim_dict(phase="execute")]
    claims.release_if_working("US1", "runner stopped")
    assert client.calls[-1] == ("release", 7, "tok", "runner stopped")
    assert LocalClaims(kb_dir).get("US1") is None


@pytest.mark.parametrize("phase", ["publishing", "review"])
def test_release_if_working_keeps_publishing_and_review(kb_dir, phase):
    client = FakeClient()
    claims = claimed(kb_dir, client)
    client.held_rows = [claim_dict(phase=phase)]
    claims.release_if_working("US1", "runner stopped")
    assert not released(client)


def test_release_if_working_uses_the_hub_phase_not_the_cache(kb_dir):
    client = FakeClient()
    claims = claimed(kb_dir, client)  # the last reply we saw said `claimed`
    client.held_rows = [claim_dict(phase="review")]  # a skill moved it since
    claims.release_if_working("US1", "runner stopped")
    assert not released(client)


def test_release_if_working_keeps_a_stopped_claim(kb_dir):
    client = FakeClient()
    claims = claimed(kb_dir, client)
    client.held_rows = [claim_dict(phase="execute", state="stopped")]
    claims.release_if_working("US1", "runner stopped")
    assert not released(client)


def test_release_if_working_keeps_the_claim_when_the_hub_is_unreadable(kb_dir, caplog):
    client = FakeClient()
    claims = claimed(kb_dir, client)

    def boom(repo="", ticket=""):
        raise KbError("hub unreachable")

    client.held = boom  # type: ignore[method-assign]
    with caplog.at_level(logging.WARNING):
        claims.release_if_working("US1", "runner stopped")
    assert not released(client) and "hub unreachable" in caplog.text
    assert LocalClaims(kb_dir).get("US1") == (7, "tok")


def test_release_if_working_ignores_a_claim_that_is_not_ours(kb_dir):
    client = FakeClient()
    claims = claimed(kb_dir, client)
    client.held_rows = [claim_dict(phase="execute", id=99)]
    claims.release_if_working("US1", "runner stopped")
    assert not released(client)


def test_held_by_others_excludes_mine(kb_dir):
    client = FakeClient()
    client.held_rows = [claim_dict("US1"), claim_dict("US2", id=8), claim_dict("US3")]
    assert make(kb_dir, client).held_by_others("US2") == {"US1", "US3"}
    assert make(kb_dir, client).held_by_others(None) == {"US1", "US2", "US3"}


def review_row(pr="https://github.com/o/r/pull/12") -> dict:
    return claim_dict("US1", phase="review", pr=pr)


@pytest.fixture(autouse=True)
def origin(monkeypatch):
    monkeypatch.setattr(ghrest, "origin_slug", lambda root: ("github.com", "o/r"))


def test_held_by_others_skips_prs_of_other_repos(kb_dir, monkeypatch):
    client = FakeClient()
    client.held_rows = [review_row("https://github.com/org/B/pull/12")]
    monkeypatch.setattr(
        ghrest, "view_pr", lambda root, ref=None: pytest.fail("other repo's PR")
    )
    assert make(kb_dir, client).held_by_others(None) == {"US1"}
    assert client.calls == []


def test_held_by_others_matches_the_repo_case_insensitively(kb_dir, monkeypatch):
    client = FakeClient()
    client.held_rows = [review_row("https://github.com/O/R/pull/12")]
    monkeypatch.setattr(ghrest, "view_pr", lambda root, ref=None: {"state": "CLOSED"})
    make(kb_dir, client).held_by_others(None)
    assert [c[0] for c in client.calls] == ["pr_closed"]


def test_held_by_others_odd_pr_payload_does_not_break_the_pick(kb_dir, monkeypatch):
    client = FakeClient()
    client.held_rows = [review_row()]

    def odd(root, ref=None):
        raise TypeError("odd payload")

    monkeypatch.setattr(ghrest, "view_pr", odd)
    assert make(kb_dir, client).held_by_others(None) == {"US1"}


def test_held_by_others_reports_closed_pr(kb_dir, monkeypatch):
    client = FakeClient()
    client.held_rows = [review_row()]
    seen = []
    monkeypatch.setattr(
        ghrest,
        "view_pr",
        lambda root, ref=None: seen.append(ref) or {"state": "CLOSED"},
    )
    make(kb_dir, client).held_by_others(None)
    assert seen == ["12"]
    assert client.calls == [("pr_closed", 7, "https://github.com/o/r/pull/12")]


@pytest.mark.parametrize("state", ["OPEN", "MERGED"])
def test_held_by_others_ignores_open_or_merged_pr(kb_dir, monkeypatch, state):
    client = FakeClient()
    client.held_rows = [review_row()]
    monkeypatch.setattr(ghrest, "view_pr", lambda root, ref=None: {"state": state})
    make(kb_dir, client).held_by_others(None)
    assert client.calls == []


def test_held_by_others_pr_lookup_error_is_logged_not_raised(
    kb_dir, monkeypatch, caplog
):
    client = FakeClient()
    client.held_rows = [review_row()]

    def boom(root, ref=None):
        raise ghrest.GHError("no network")

    monkeypatch.setattr(ghrest, "view_pr", boom)
    with caplog.at_level(logging.WARNING):
        assert make(kb_dir, client).held_by_others(None) == {"US1"}
    assert "no network" in caplog.text


def test_claimbeat_beats_on_interval_and_stop_joins():
    beats: list[str] = []

    class Claims:
        def beat(self, ticket):
            beats.append(ticket)
            return True

    beat = ClaimBeat(Claims(), 0.01)  # type: ignore[arg-type]
    beat.start("US1")
    deadline = time.monotonic() + 5
    while len(beats) < 2 and time.monotonic() < deadline:
        time.sleep(0.005)
    beat.stop()
    assert len(beats) >= 2 and beats[0] == "US1" and not beat.lost
    assert not [t for t in threading.enumerate() if t.daemon and "_loop" in t.name]
    seen = len(beats)
    time.sleep(0.05)
    assert len(beats) == seen  # stopped means stopped


def test_claimbeat_sets_lost_and_ends():
    class Claims:
        def beat(self, ticket):
            return False

    beat = ClaimBeat(Claims(), 0.01)  # type: ignore[arg-type]
    beat.start("US1")
    deadline = time.monotonic() + 5
    while not beat.lost and time.monotonic() < deadline:
        time.sleep(0.005)
    beat.stop()
    assert beat.lost


@pytest.mark.parametrize("phase", ["review", "publishing"])
def test_begin_keeps_a_review_or_publishing_claim(kb_dir, phase):
    client = FakeClient(phase=phase, pr="https://github.com/a/b/pull/1")
    claims = make(kb_dir, client)
    assert claims.claim("US1") is True
    assert claims.begin("US1") is True
    assert [c[0] for c in client.calls] == ["take"]


@pytest.mark.parametrize("phase", ["claimed", "execute", "waiting-qa"])
def test_begin_moves_a_working_claim_to_claimed(kb_dir, phase):
    client = FakeClient(phase=phase)
    claims = make(kb_dir, client)
    claims.claim("US1")
    assert claims.begin("US1") is True
    assert client.calls[-1] == ("update", 7, "tok", {"phase": "claimed"})


def test_begin_reports_a_lost_claim(kb_dir):
    client = FakeClient()
    claims = make(kb_dir, client)
    claims.claim("US1")
    client.update_error = ClaimLostError("released", "admin")
    assert claims.begin("US1") is False
