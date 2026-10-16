"""cloud — the cloud switch and the hub URL + token pair."""

import pytest

from strata_kb import cloud


@pytest.mark.parametrize(
    "env,expected",
    [
        ({}, False),
        ({"CLAUDE_CODE_REMOTE": "true"}, True),
        ({"CLAUDE_CODE_REMOTE": "TRUE"}, True),
        ({"CLAUDE_CODE_REMOTE": "1"}, True),
        ({"CLAUDE_CODE_REMOTE": "0"}, False),
        ({"CLAUDE_CODE_REMOTE": "true", "STRATA_KB_CLOUD": "0"}, False),
        ({"STRATA_KB_CLOUD": "1"}, True),
    ],
)
def test_is_cloud(monkeypatch, env, expected):
    for var in ("CLAUDE_CODE_REMOTE", "STRATA_KB_CLOUD"):
        monkeypatch.delenv(var, raising=False)
    for var, value in env.items():
        monkeypatch.setenv(var, value)
    assert cloud.is_cloud() is expected


def test_hub_http_needs_both_vars(monkeypatch):
    monkeypatch.delenv("STRATA_KB_HUB_URL", raising=False)
    monkeypatch.delenv("STRATA_KB_HTTP_TOKEN", raising=False)
    assert cloud.hub_http() is None
    monkeypatch.setenv("STRATA_KB_HUB_URL", "https://hub.example/")
    assert cloud.hub_http() is None
    monkeypatch.setenv("STRATA_KB_HTTP_TOKEN", "tok")
    assert cloud.hub_http() == ("https://hub.example", "tok")
    monkeypatch.setenv("STRATA_KB_HUB_URL", "")
    assert cloud.hub_http() is None
