# tests/test_codesync_issue.py
from __future__ import annotations

import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from strata_kb.codesync import issue, scan
from strata_kb.codesync.changes import ChangedItem

SHA = "a1b2c3d4e5f6" + "0" * 28


class FakeHTTP:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, req):
        self.requests.append(req)
        status, body = self.responses.pop(0)
        return status, json.dumps(body).encode()

    def methods(self):
        return [r.get_method() for r in self.requests]


def result(*terms: str) -> scan.ScanResult:
    findings = tuple(
        scan.Finding(
            "doc-a",
            "1",
            "Intro",
            t,
            False,
            ChangedItem(
                "repo", "x-code", "1", "T", "changed", frozenset(), frozenset()
            ),
        )
        for t in terms
    )
    return scan.ScanResult(SHA, None, "none", findings, ())


def test_findings_and_no_issue_creates_one_with_label():
    r = result("alpha")
    http = FakeHTTP([(200, []), (201, {}), (201, {"number": 5})])
    assert issue.sync_issue(r, repo_full="a/b", token="t", http=http) == "created"
    assert http.methods() == ["GET", "POST", "POST"]
    sent = json.loads(http.requests[2].data)
    assert sent["title"] == issue.TITLE
    assert sent["labels"] == [issue.LABEL] == ["kb-code-sync"]
    assert sent["body"] == scan.render_markdown(r)


def test_same_digest_does_not_patch():
    r = result("alpha")
    http = FakeHTTP([(200, [{"number": 5, "body": scan.render_markdown(r)}])])
    assert issue.sync_issue(r, repo_full="a/b", token="t", http=http) == "unchanged"
    assert http.methods() == ["GET"]


def test_new_digest_updates_body():
    old = scan.render_markdown(result("alpha"))
    new = result("alpha", "beta")
    http = FakeHTTP([(200, [{"number": 5, "body": old}]), (200, {})])
    assert issue.sync_issue(new, repo_full="a/b", token="t", http=http) == "updated"
    assert http.methods() == ["GET", "PATCH"]
    assert json.loads(http.requests[1].data) == {"body": scan.render_markdown(new)}


def test_existing_issue_without_marker_is_rewritten():
    http = FakeHTTP([(200, [{"number": 5, "body": None}]), (200, {})])
    out = issue.sync_issue(result("alpha"), repo_full="a/b", token="t", http=http)
    assert out == "updated"


def test_zero_findings_closes_with_comment():
    http = FakeHTTP([(200, [{"number": 5, "body": "old"}]), (201, {}), (200, {})])
    assert issue.sync_issue(result(), repo_full="a/b", token="t", http=http) == "closed"
    assert json.loads(http.requests[1].data) == {
        "body": "kb code-sync: nothing left to update as of a1b2c3d4e5f6."
    }
    assert json.loads(http.requests[2].data)["state"] == "closed"


def test_zero_findings_and_no_issue_is_none():
    http = FakeHTTP([(200, [])])
    assert issue.sync_issue(result(), repo_full="a/b", token="t", http=http) == "none"
    assert http.methods() == ["GET"]


@pytest.fixture
def clean_env(monkeypatch):
    for k in ("STRATA_KB_GH_TOKEN", "STRATA_KB_GH_APP_ID", "STRATA_KB_GH_APP_KEY"):
        monkeypatch.delenv(k, raising=False)


def test_issue_token_prefers_app_creds_then_env_token(clean_env, monkeypatch, tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = tmp_path / "app.pem"
    pem.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    assert issue.issue_token("a/b") is None  # nothing configured

    monkeypatch.setenv("STRATA_KB_GH_TOKEN", "ghp_env")
    http = FakeHTTP([])
    assert issue.issue_token("a/b", http=http) == "ghp_env"
    assert http.requests == []  # no App creds: the token is the fallback

    monkeypatch.setenv("STRATA_KB_GH_APP_ID", "1234")
    monkeypatch.setenv("STRATA_KB_GH_APP_KEY", str(pem))
    http = FakeHTTP([(200, {"id": 77}), (201, {"token": "ghs_app"})])
    assert issue.issue_token("a/b", http=http) == "ghs_app"  # App wins over token


def test_issue_token_unreadable_pem_is_none(clean_env, monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("STRATA_KB_GH_APP_ID", "1234")
    monkeypatch.setenv("STRATA_KB_GH_APP_KEY", str(tmp_path / "missing.pem"))
    assert issue.issue_token("a/b", http=FakeHTTP([])) is None
    assert "missing.pem" in caplog.text


def _huge_result() -> scan.ScanResult:
    return result(*(f"term{i:05d}" + "x" * 80 for i in range(1000)))


def test_oversized_body_is_truncated_with_marker_last():
    r = _huge_result()
    assert len(scan.render_markdown(r)) > issue.MAX_BODY_CHARS
    http = FakeHTTP([(200, []), (201, {}), (201, {"number": 5})])
    assert issue.sync_issue(r, repo_full="a/b", token="t", http=http) == "created"
    body = json.loads(http.requests[2].data)["body"]
    assert len(body) <= issue.MAX_BODY_CHARS
    assert "kb code-sync scan --md" in body
    lines = body.splitlines()
    assert lines[-1] == f"{scan.DIGEST_PREFIX}{scan.digest(r)} -->"
    assert issue.TRUNCATED_LINE in lines


def test_oversized_body_same_digest_is_unchanged():
    r = _huge_result()
    first = FakeHTTP([(200, []), (201, {}), (201, {"number": 5})])
    issue.sync_issue(r, repo_full="a/b", token="t", http=first)
    stored = json.loads(first.requests[2].data)["body"]
    http = FakeHTTP([(200, [{"number": 5, "body": stored}])])
    assert issue.sync_issue(r, repo_full="a/b", token="t", http=http) == "unchanged"
