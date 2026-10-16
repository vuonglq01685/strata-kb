"""GET /api/plan/next, GET /api/registry/entry, POST /api/resolve: the live
hub reads a cloud session makes instead of copying the hub."""

import pytest
import yaml

from strata_kb import planstatus
from tests.test_planingest import context_block


@pytest.fixture
def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def write_registry(hub_dir, repos: dict) -> None:
    (hub_dir / "federation" / "registry.yaml").write_text(
        yaml.safe_dump({"repos": repos}), encoding="utf-8", newline="\n"
    )


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/plan/next"),
        ("get", "/api/registry/entry?repo_id=x"),
        ("post", "/api/resolve"),
    ],
)
def test_routes_require_auth(web_client, method, path):
    assert getattr(web_client, method)(path).status_code == 401


def test_plan_next_matches_next_from_hub(web_client, hub_with_ticket, auth):
    hub = hub_with_ticket(rev=1)
    stories, unparented, notes = planstatus.next_from_hub(hub)

    resp = web_client.get("/api/plan/next", headers=auth)

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"stories", "unparented", "notes"}
    assert [s["us_id"] for s in body["stories"]] == [s.us_id for s in stories]
    assert [s["us_id"] for s in body["unparented"]] == [s.us_id for s in unparented]
    assert body["notes"] == notes
    for item in body["stories"] + body["unparented"]:
        assert set(item) == {
            "us_id", "mission_id", "title", "status", "reasons", "depends_on",
        }  # fmt: skip
        assert isinstance(item["reasons"], list)
        assert isinstance(item["depends_on"], list)
    assert body["stories"] or body["unparented"]


def test_plan_next_repo_filter(web_client, hub_with_ticket, auth):
    hub_with_ticket(rev=1)
    body = web_client.get("/api/plan/next?repo=nope", headers=auth).json()
    assert body["stories"] == [] and body["unparented"] == []
    assert body["notes"]


def test_registry_entry_is_one_repo_without_pins(web_client, hub_dir, auth):
    write_registry(
        hub_dir,
        {
            "acme/ba-one": {
                "repo_id": "ba-one",
                "workflow": "acme/ba-one/.github/workflows/kb.yml@refs/heads/main",
                "kind": "ba",
                "auto_merge": True,
            },
            "acme/dev-a": "dev-a",
            "acme/dev-b": {"repo_id": "dev-b", "kind": "dev"},
            "acme/dev-c": {"repo_id": "dev-c", "kind": "dev"},
        },
    )

    resp = web_client.get("/api/registry/entry?repo_id=ba-one", headers=auth)

    assert resp.status_code == 200
    assert resp.json() == {
        "repo_id": "ba-one",
        "kind": "ba",
        "auto_merge": True,
        "dev_repos": 2,
    }
    assert "workflow" not in resp.text and "acme" not in resp.text


def test_registry_entry_plain_string_value(web_client, hub_dir, auth):
    write_registry(hub_dir, {"acme/dev-a": "dev-a"})
    body = web_client.get("/api/registry/entry?repo_id=dev-a", headers=auth).json()
    assert body == {
        "repo_id": "dev-a", "kind": "", "auto_merge": False, "dev_repos": 0,
    }  # fmt: skip


def test_registry_entry_unknown_is_404(web_client, hub_dir, auth):
    write_registry(hub_dir, {"acme/dev-a": "dev-a"})
    resp = web_client.get("/api/registry/entry?repo_id=ghost", headers=auth)
    assert resp.status_code == 404
    assert resp.json()["error"] == "repo_not_registered"


def test_registry_entry_without_registry_file_is_404(web_client, hub_dir, auth):
    (hub_dir / "federation" / "registry.yaml").unlink(missing_ok=True)
    resp = web_client.get("/api/registry/entry?repo_id=ghost", headers=auth)
    assert resp.status_code == 404


def test_registry_entry_needs_repo_id(web_client, auth):
    assert web_client.get("/api/registry/entry", headers=auth).status_code == 400


def test_registry_entry_invalid_registry_is_503_without_leaking(
    web_client, hub_dir, auth
):
    write_registry(
        hub_dir,
        {
            "acme/ba-one": {
                "repo_id": "ba-one",
                "workflw": "typo-pin@refs/heads/main",
            }
        },
    )
    resp = web_client.get("/api/registry/entry?repo_id=ba-one", headers=auth)
    assert resp.status_code == 503
    assert resp.json() == {
        "error": "registry_invalid",
        "detail": "hub registry is invalid",
    }
    assert "typo-pin" not in resp.text and "acme" not in resp.text


def test_resolve_returns_results(web_client, hub_dir, auth):
    block = context_block(hub_dir)

    resp = web_client.post("/api/resolve", content=block, headers=auth)

    assert resp.status_code == 200
    body = resp.json()
    assert body["version"]
    assert body["results"]
    for r in body["results"]:
        assert set(r) == {
            "ref", "status", "citation", "content", "tokens", "reason", "pinned_rev",
        }  # fmt: skip
        assert r["status"] in ("ok", "stale", "broken")
        assert r["citation"]


def test_resolve_git_error_is_503(web_client, hub_dir, auth, monkeypatch):
    from strata_kb import gitio, resolve

    def boom(hub, ctx):
        raise gitio.GitError("git exploded: secret-detail")

    monkeypatch.setattr(resolve, "resolve_refs", boom)
    resp = web_client.post("/api/resolve", content=context_block(hub_dir), headers=auth)
    assert resp.status_code == 503
    assert resp.json()["error"] == "git_error"
    assert "secret-detail" not in resp.text


def test_resolve_bad_context_is_400(web_client, auth):
    resp = web_client.post("/api/resolve", content="no block here", headers=auth)
    assert resp.status_code == 400
    assert resp.json()["error"] == "kb_context_error"


def test_resolve_oversized_body_is_413(web_client, auth):
    big = "x" * (200 * 1024)
    assert web_client.post("/api/resolve", content=big, headers=auth).status_code == 413


def test_resolve_oversized_chunked_body_is_413(web_client, auth):
    def chunks():
        for _ in range(200):
            yield b"x" * 1024

    resp = web_client.post("/api/resolve", content=chunks(), headers=auth)
    assert resp.status_code == 413


def test_503_when_hub_unreachable(token, auth, tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from strata_kb.mcp import ServerConfig
    from strata_kb.web import api
    from strata_kb.web.app import create_app

    monkeypatch.setattr(api, "hub_handle", lambda config: None)
    config = ServerConfig(kb_dir=tmp_path / ".kb", hub=str(tmp_path / "none"))
    with TestClient(create_app(config, token)) as client:
        for resp in (
            client.get("/api/plan/next", headers=auth),
            client.get("/api/registry/entry?repo_id=x", headers=auth),
            client.post("/api/resolve", content="x", headers=auth),
        ):
            assert resp.status_code == 503
            assert resp.json()["error"] == "hub_unreachable"
