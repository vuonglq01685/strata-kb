# tests/test_ghapp.py
from __future__ import annotations

import json

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from strata_kb import ghapp


@pytest.fixture(scope="module")
def rsa_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


class FakeHTTP:
    """Records requests; returns responses from a queue of [(status, dict), ...]."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, req):
        self.requests.append(req)
        status, body = self.responses.pop(0)
        return status, json.dumps(body).encode()


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/acme/kb-hub.git", "acme/kb-hub"),
        ("https://github.com/acme/kb-hub", "acme/kb-hub"),
        ("git@github.com:acme/kb-hub.git", "acme/kb-hub"),
    ],
)
def test_repo_full_from_url(url, expected):
    assert ghapp.repo_full_from_url(url) == expected


def test_repo_full_from_url_rejects_non_github():
    with pytest.raises(ghapp.GHAppError):
        ghapp.repo_full_from_url("https://gitlab.com/a/b.git")


def test_mint_installation_token(rsa_pem):
    http = FakeHTTP([(200, {"id": 77}), (201, {"token": "ghs_test"})])
    creds = ghapp.AppCreds(app_id="1234", private_key_pem=rsa_pem)
    token = ghapp.mint_installation_token(creds, "acme/kb-hub", http=http)
    assert token == "ghs_test"
    # request 1: GET installation; request 2: POST access_tokens — mang app JWT
    assert "/repos/acme/kb-hub/installation" in http.requests[0].full_url
    assert "/app/installations/77/access_tokens" in http.requests[1].full_url
    auth = http.requests[0].headers["Authorization"]
    claims = pyjwt.decode(
        auth.removeprefix("Bearer "), options={"verify_signature": False}
    )
    assert claims["iss"] == "1234"


def test_create_pr_created(rsa_pem):
    http = FakeHTTP([(201, {"html_url": "https://github.com/acme/kb-hub/pull/5"})])
    url = ghapp.create_or_get_pr(
        "acme/kb-hub", "ghs_x", "publish/child-a", "t", "b", base="main", http=http
    )
    assert url.endswith("/pull/5")
    sent = json.loads(http.requests[0].data)
    assert sent == {
        "title": "t",
        "body": "b",
        "head": "publish/child-a",
        "base": "main",
    }


def test_create_pr_already_exists_returns_open_pr(rsa_pem):
    http = FakeHTTP(
        [
            (422, {"message": "already exists"}),
            (200, [{"html_url": "https://github.com/acme/kb-hub/pull/3"}]),
        ]
    )
    url = ghapp.create_or_get_pr(
        "acme/kb-hub", "ghs_x", "publish/child-a", "t", "b", http=http
    )
    assert url.endswith("/pull/3")


def test_http_error_raises_without_token_in_message():
    http = FakeHTTP([(500, {"message": "boom"})])
    with pytest.raises(ghapp.GHAppError) as exc:
        ghapp.create_or_get_pr("acme/kb-hub", "ghs_secret", "b", "t", "b", http=http)
    assert "ghs_secret" not in str(exc.value)


@pytest.mark.parametrize(
    "responses",
    [
        [(200, [{"id": 77}])],  # installation answered with a JSON array
        [(200, {"id": 77}), (201, ["ghs_test"])],  # token answered with an array
    ],
)
def test_mint_installation_token_refuses_a_non_object_reply(rsa_pem, responses):
    # A JSON array used to reach `inst["id"]` / `tok["token"]` and escape as a
    # bare TypeError instead of the one-line GHAppError every caller handles.
    creds = ghapp.AppCreds(app_id="1234", private_key_pem=rsa_pem)
    with pytest.raises(ghapp.GHAppError):
        ghapp.mint_installation_token(creds, "acme/kb-hub", http=FakeHTTP(responses))


def test_create_pr_refuses_a_non_object_reply():
    http = FakeHTTP([(201, ["https://github.com/acme/kb-hub/pull/5"])])
    with pytest.raises(ghapp.GHAppError):
        ghapp.create_or_get_pr("acme/kb-hub", "ghs_x", "b", "t", "b", http=http)


# --- rolling issue + contents helpers --------------------------------------


def test_find_open_issue_returns_newest_and_skips_pull_requests():
    http = FakeHTTP(
        [
            (
                200,
                [
                    {"number": 9, "body": "pr", "pull_request": {}},
                    {"number": 7, "body": "newest"},
                    {"number": 3, "body": "older"},
                ],
            )
        ]
    )
    assert ghapp.find_open_issue("acme/kb-hub", "t", "kb-code-sync", http=http) == (
        7,
        "newest",
    )
    url = http.requests[0].full_url
    assert "labels=kb-code-sync" in url and "state=open" in url
    assert "direction=desc" in url


def test_find_open_issue_accept_skips_bodies_it_rejects():
    http = FakeHTTP(
        [(200, [{"number": 9, "body": "human"}, {"number": 7, "body": "job"}])]
    )
    found = ghapp.find_open_issue(
        "a/b", "t", "l", http=http, accept=lambda body: body == "job"
    )
    assert found == (7, "job")
    http = FakeHTTP([(200, [{"number": 9, "body": None}])])
    assert ghapp.find_open_issue("a/b", "t", "l", http=http, accept=bool) is None


def test_find_open_issue_none_when_empty_and_error_hides_token():
    assert ghapp.find_open_issue("a/b", "t", "l", http=FakeHTTP([(200, [])])) is None
    with pytest.raises(ghapp.GHAppError) as exc:
        ghapp.find_open_issue("a/b", "ghs_secret", "l", http=FakeHTTP([(500, {})]))
    assert "ghs_secret" not in str(exc.value)


def test_find_open_pr_returns_number_or_none_and_error_hides_token():
    http = FakeHTTP([(200, [{"number": 4}]), (200, [])])
    assert ghapp.find_open_pr("acme/kb-hub", "t", "kb-bot/code-sync", http=http) == 4
    url = http.requests[0].full_url
    assert "/repos/acme/kb-hub/pulls?" in url and "state=open" in url
    assert "head=acme%3Akb-bot%2Fcode-sync" in url
    assert ghapp.find_open_pr("acme/kb-hub", "t", "b", http=http) is None
    with pytest.raises(ghapp.GHAppError) as exc:
        ghapp.find_open_pr("a/b", "ghs_secret", "b", http=FakeHTTP([(500, {})]))
    assert "ghs_secret" not in str(exc.value)


def test_create_issue_ensures_label_then_posts():
    http = FakeHTTP([(422, {}), (201, {"number": 12})])
    n = ghapp.create_issue("a/b", "t", "T", "B", "kb-code-sync", http=http)
    assert n == 12
    assert http.requests[0].full_url.endswith("/repos/a/b/labels")
    assert json.loads(http.requests[0].data)["name"] == "kb-code-sync"
    assert http.requests[1].full_url.endswith("/repos/a/b/issues")
    assert json.loads(http.requests[1].data) == {
        "title": "T",
        "body": "B",
        "labels": ["kb-code-sync"],
    }


def test_create_issue_fails_loudly_on_label_or_issue_error():
    with pytest.raises(ghapp.GHAppError):
        ghapp.create_issue("a/b", "t", "T", "B", "l", http=FakeHTTP([(403, {})]))
    with pytest.raises(ghapp.GHAppError):
        ghapp.create_issue(
            "a/b", "t", "T", "B", "l", http=FakeHTTP([(201, {}), (500, {})])
        )


def test_update_issue_body_patches():
    http = FakeHTTP([(200, {})])
    ghapp.update_issue_body("a/b", "t", 4, "new", http=http)
    assert http.requests[0].get_method() == "PATCH"
    assert http.requests[0].full_url.endswith("/repos/a/b/issues/4")
    assert json.loads(http.requests[0].data) == {"body": "new"}
    with pytest.raises(ghapp.GHAppError):
        ghapp.update_issue_body("a/b", "t", 4, "x", http=FakeHTTP([(404, {})]))


def test_close_issue_comments_then_closes():
    http = FakeHTTP([(201, {}), (200, {})])
    ghapp.close_issue("a/b", "t", 4, "done", http=http)
    assert http.requests[0].full_url.endswith("/issues/4/comments")
    assert json.loads(http.requests[0].data) == {"body": "done"}
    assert http.requests[1].get_method() == "PATCH"
    assert json.loads(http.requests[1].data)["state"] == "closed"
    with pytest.raises(ghapp.GHAppError):
        ghapp.close_issue("a/b", "t", 4, "c", http=FakeHTTP([(500, {})]))


def test_read_file_decodes_and_404_is_none():
    import base64

    enc = base64.encodebytes("baseline: abc\nünï\n".encode()).decode()
    http = FakeHTTP([(200, {"content": enc, "encoding": "base64"})])
    out = ghapp.read_file(
        "a/b", "t", "kb-code-sync.yaml", "kb-bot/code-sync", http=http
    )
    assert out == "baseline: abc\nünï\n"
    url = http.requests[0].full_url
    assert "/contents/kb-code-sync.yaml" in url and "ref=kb-bot%2Fcode-sync" in url
    assert ghapp.read_file("a/b", "t", "x", "main", http=FakeHTTP([(404, {})])) is None
    with pytest.raises(ghapp.GHAppError):
        ghapp.read_file("a/b", "t", "x", "main", http=FakeHTTP([(500, {})]))
    with pytest.raises(ghapp.GHAppError):  # a directory listing is not a file
        ghapp.read_file("a/b", "t", "x", "main", http=FakeHTTP([(200, [])]))
