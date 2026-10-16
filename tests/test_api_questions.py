"""GET /api/questions: the runner's JSON view of the ticket Q&A store."""

import pytest

from strata_kb.mcp import ServerConfig
from strata_kb.ticketqa import QaStore, answer_question, ask_question, qa_db_path
from tests.test_planingest import US1

REPO = "ba-one"


@pytest.fixture
def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_requires_auth(web_client):
    assert web_client.get("/api/questions").status_code == 401


def test_lists_the_open_question(web_client, hub_with_ticket, auth):
    hub = hub_with_ticket(rev=1)
    ask_question(
        hub,
        QaStore(qa_db_path(hub.root)),
        US1,
        "Which currency?",
        "dev1",
        blocks="AC-2",
    )

    resp = web_client.get("/api/questions", headers=auth)

    assert resp.status_code == 200
    (q,) = resp.json()["questions"]
    assert q == {
        "id": 1,
        "repo": REPO,
        "ticket": US1,
        "state": "open",
        "question": "Which currency?",
        "asked_by": "dev1",
        "asked_at": q["asked_at"],
        "blocks": "AC-2",
        "answer": None,
        "answer_rev": None,
    }
    assert q["asked_at"]


def test_status_and_ticket_filters(web_client, hub_with_ticket, auth):
    hub = hub_with_ticket(rev=1)
    store = QaStore(qa_db_path(hub.root))
    ask_question(hub, store, US1, "first?", "dev1")
    ask_question(hub, store, US1, "second?", "dev1")
    answer_question(hub, store, 1, "EUR", "ba1", None, [])

    def ids(**params):
        resp = web_client.get("/api/questions", params=params, headers=auth)
        assert resp.status_code == 200
        return {q["id"]: q["state"] for q in resp.json()["questions"]}

    assert ids() == {2: "open"}
    assert ids(status="all") == {1: "answered", 2: "open"}
    assert ids(status="answered", repo=REPO, ticket=US1) == {1: "answered"}
    assert ids(status="all", ticket="nope") == {}
    answered = web_client.get(
        "/api/questions", params={"status": "answered"}, headers=auth
    ).json()["questions"][0]
    assert answered["answer"] == "EUR"


def test_bad_status_is_400(web_client, hub_with_ticket, auth):
    hub_with_ticket(rev=1)
    resp = web_client.get("/api/questions?status=bogus", headers=auth)
    assert resp.status_code == 400
    assert "status" in resp.json()["detail"]


def test_no_store_means_empty_list_and_no_db_created(web_client, hub_dir, auth):
    resp = web_client.get("/api/questions", headers=auth)
    assert resp.status_code == 200
    assert resp.json() == {"questions": []}
    assert not (hub_dir / ".kb-qa").exists()


def test_503_when_not_the_shared_hub(token, hub_dir, auth, tmp_path):
    from starlette.testclient import TestClient

    from strata_kb.web.app import create_app

    elsewhere = tmp_path / "dev-repo" / ".kb"
    elsewhere.mkdir(parents=True)
    config = ServerConfig(kb_dir=elsewhere, hub=str(hub_dir))
    with TestClient(create_app(config, token)) as client:
        resp = client.get("/api/questions", headers=auth)
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Q&A needs the shared hub server"
