# tests/test_ghapp.py
from __future__ import annotations

import json

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from center_kb import ghapp


@pytest.fixture(scope="module")
def rsa_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


class FakeHTTP:
    """Ghi lại request; trả response theo hàng đợi [(status, dict), ...]."""

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
    assert sent == {"title": "t", "body": "b", "head": "publish/child-a", "base": "main"}


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
