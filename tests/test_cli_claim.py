"""`kb claim take|update|release|list` over a patched ClaimClient."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from typer.testing import CliRunner

from strata_kb import claimcmd
from strata_kb.claimclient import ClaimLostError, ClaimTakenError, LocalClaims
from strata_kb.cli import app
from strata_kb.initcmd import read_template

runner = CliRunner()


class FakeClient:
    def __init__(self):
        self.calls: list[tuple] = []
        self.take_error: Exception | None = None
        self.update_error: Exception | None = None
        self.claims: list[dict] = []

    def take(self, ticket, holder, claim_token=None):
        self.calls.append(("take", ticket, holder, claim_token))
        if self.take_error:
            raise self.take_error
        return {"id": 4, "ticket": ticket, "holder": holder}, "ct"

    def update(self, claim_id, claim_token, **fields):
        self.calls.append(("update", claim_id, claim_token, fields))
        if self.update_error:
            raise self.update_error
        return {"id": claim_id}

    def release(self, claim_id, claim_token, reason):
        self.calls.append(("release", claim_id, claim_token, reason))

    def held(self, repo="", ticket=""):
        return self.claims


@pytest.fixture
def fake(monkeypatch, tmp_path) -> FakeClient:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".kb").mkdir()
    monkeypatch.delenv("STRATA_KB_CLAIM_AS", raising=False)
    fc = FakeClient()
    monkeypatch.setattr(claimcmd.claimclient, "from_env", lambda: fc)
    return fc


def local(tmp_path) -> LocalClaims:
    return LocalClaims(tmp_path / ".kb")


def test_take_prints_holder_and_stores_token(fake, tmp_path):
    result = runner.invoke(app, ["claim", "take", "US1", "--as", "a@m1"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "claimed US1 as a@m1"
    assert local(tmp_path).get("US1") == (4, "ct")
    assert fake.calls == [("take", "US1", "a@m1", None)]


def test_take_resends_stored_token(fake, tmp_path):
    local(tmp_path).put("US1", 4, "ct")
    runner.invoke(app, ["claim", "take", "US1", "--as", "a@m1"])
    assert fake.calls[0][3] == "ct"


def test_take_taken_exit_3(fake, tmp_path):
    last_seen = (datetime.now(UTC) - timedelta(minutes=5)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    fake.take_error = ClaimTakenError(
        {"holder": "a@m1", "phase": "design", "last_seen": last_seen}
    )
    result = runner.invoke(app, ["claim", "take", "US1", "--as", "b@m2"])
    assert result.exit_code == 3
    assert "taken by a@m1 (design, updated 5 min ago)" in result.output
    assert local(tmp_path).get("US1") is None


def test_update_without_local_claim(fake):
    result = runner.invoke(app, ["claim", "update", "US1", "--phase", "plan"])
    assert result.exit_code == 1
    assert result.output.strip() == (
        "no claim held for US1 on this machine — run kb claim take US1"
    )
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert fake.calls == []


def test_update_sends_fields(fake, tmp_path):
    local(tmp_path).put("US1", 4, "ct")
    result = runner.invoke(
        app, ["claim", "update", "US1", "--phase", "review", "--pr", "u", "--active"]
    )
    assert result.exit_code == 0, result.output
    assert fake.calls == [
        ("update", 4, "ct", {"phase": "review", "pr": "u", "state": "active"})
    ]


def test_update_stopped_sets_state_and_reason(fake, tmp_path):
    local(tmp_path).put("US1", 4, "ct")
    runner.invoke(app, ["claim", "update", "US1", "--stopped", "waiting on QA"])
    assert fake.calls[0][3] == {"state": "stopped", "stop_reason": "waiting on QA"}


def test_update_stopped_and_active_conflict(fake, tmp_path):
    local(tmp_path).put("US1", 4, "ct")
    result = runner.invoke(
        app, ["claim", "update", "US1", "--stopped", "x", "--active"]
    )
    assert result.exit_code == 1
    assert fake.calls == []


def test_update_lost_exit_3_drops_local(fake, tmp_path):
    local(tmp_path).put("US1", 4, "ct")
    fake.update_error = ClaimLostError("expired", "hub")
    result = runner.invoke(app, ["claim", "update", "US1", "--phase", "plan"])
    assert result.exit_code == 3
    assert "lost: expired by hub" in result.output
    assert local(tmp_path).get("US1") is None


def test_release_drops_local(fake, tmp_path):
    local(tmp_path).put("US1", 4, "ct")
    result = runner.invoke(app, ["claim", "release", "US1", "--reason", "done"])
    assert result.exit_code == 0, result.output
    assert fake.calls == [("release", 4, "ct", "done")]
    assert local(tmp_path).get("US1") is None


def test_release_without_local_claim(fake):
    result = runner.invoke(app, ["claim", "release", "US1"])
    assert result.exit_code == 1
    assert "no claim held for US1 on this machine" in result.output


def test_release_lost_exit_3_drops_local(fake, tmp_path):
    local(tmp_path).put("US1", 4, "ct")
    fake.update_error = None
    fake.release = lambda *_a: (_ for _ in ()).throw(ClaimLostError("released", "x"))
    result = runner.invoke(app, ["claim", "release", "US1"])
    assert result.exit_code == 3
    assert local(tmp_path).get("US1") is None


def test_list_json(fake):
    fake.claims = [{"id": 1, "ticket": "US1", "holder": "a@m1", "phase": "plan"}]
    result = runner.invoke(app, ["claim", "list", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == fake.claims


def test_list_text(fake):
    fake.claims = [{"id": 1, "ticket": "US1", "holder": "a@m1", "phase": "plan"}]
    result = runner.invoke(app, ["claim", "list"])
    assert "US1" in result.output and "a@m1" in result.output


def test_claim_error_is_exit_1_not_traceback(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".kb").mkdir()
    monkeypatch.delenv("STRATA_KB_HUB_URL", raising=False)
    result = runner.invoke(app, ["claim", "list"])
    assert result.exit_code == 1
    assert "STRATA_KB_HUB_URL is not set" in result.output


def test_auto_settings_allow_kb_claim():
    allow = json.loads(read_template("claude-settings-auto.json"))["permissions"][
        "allow"
    ]
    assert "Bash(kb claim *)" in allow
    assert allow.index("Bash(kb claim *)") == allow.index("Bash(kb pr *)") + 1
