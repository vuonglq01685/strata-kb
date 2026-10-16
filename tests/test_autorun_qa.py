"""The runner's Q&A client: reads /api/questions with the MCP env vars."""

import json

import pytest

from strata_kb.autorun import qa
from strata_kb.errors import KbError

TOKEN = "s3cret-token"


class Stub:
    def __init__(self, status=200, payload=None):
        self.status = status
        self.body = json.dumps(payload if payload is not None else {"questions": []})
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, method, url, headers, body=None, timeout=60):
        self.calls.append((method, url, headers))
        return self.status, self.body.encode()


def test_list_builds_url_and_sends_bearer():
    rows = [{"id": 3, "state": "open"}]
    http = Stub(payload={"questions": rows})
    client = qa.QaClient("http://hub:8080", TOKEN, http=http)

    got = client.list(status="all", repo="ba one", ticket="US-1")

    assert got == rows
    method, url, headers = http.calls[0]
    assert method == "GET"
    assert url == "http://hub:8080/api/questions?status=all&repo=ba+one&ticket=US-1"
    assert headers["Authorization"] == f"Bearer {TOKEN}"


def test_list_defaults_to_open_and_omits_empty_filters():
    http = Stub()
    qa.QaClient("http://hub", TOKEN, http=http).list()
    assert http.calls[0][1] == "http://hub/api/questions?status=open"


def test_states_is_one_status_all_call_filtered_to_ids():
    http = Stub(
        payload={
            "questions": [
                {"id": 3, "state": "answered"},
                {"id": 4, "state": "open"},
            ]
        }
    )
    client = qa.QaClient("http://hub", TOKEN, http=http)

    assert client.states([3, 9]) == {3: "answered"}
    assert len(http.calls) == 1
    assert "status=all" in http.calls[0][1]


@pytest.mark.parametrize("status", [401, 400, 503])
def test_non_2xx_raises_kberror_without_the_token(status):
    http = Stub(status=status, payload={"error": "bad_status", "detail": TOKEN})
    client = qa.QaClient("http://hub", TOKEN, http=http)
    with pytest.raises(KbError) as exc:
        client.list()
    assert str(status) in str(exc.value)
    assert TOKEN not in str(exc.value)


def test_error_field_is_in_the_message():
    http = Stub(status=400, payload={"error": "bad_status"})
    with pytest.raises(KbError, match="400.*bad_status"):
        qa.QaClient("http://hub", TOKEN, http=http).list()


def test_transport_failure_raises_kberror():
    def down(method, url, headers, body=None, timeout=60):
        return 0, b"connection refused"

    with pytest.raises(KbError, match="connection refused"):
        qa.QaClient("http://hub", TOKEN, http=down).list()


def test_from_env_reads_vars_and_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("STRATA_KB_HUB_URL", "http://hub:8080/")
    monkeypatch.setenv("STRATA_KB_HTTP_TOKEN", TOKEN)
    client = qa.from_env()
    assert client.base_url == "http://hub:8080"


@pytest.mark.parametrize("missing", ["STRATA_KB_HUB_URL", "STRATA_KB_HTTP_TOKEN"])
def test_from_env_names_the_missing_var(monkeypatch, missing):
    monkeypatch.setenv("STRATA_KB_HUB_URL", "http://hub")
    monkeypatch.setenv("STRATA_KB_HTTP_TOKEN", TOKEN)
    monkeypatch.delenv(missing)
    with pytest.raises(KbError, match=missing):
        qa.from_env()
