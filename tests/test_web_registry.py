"""The admin-only Registry page (`/ui/registry*`).

Most tests inject the push step (`registry_push=`) and record what the page
handed it; the `real_push` tests run the production push path against a bare
`origin` so a lost race and the post-push pull are the real git behaviour.
"""

import contextlib
import json
import re
import secrets
from pathlib import Path

import pytest
import yaml
from starlette.testclient import TestClient

from strata_kb import ghapp, gitio, intake
from strata_kb.serving.accounts import Accounts
from strata_kb.serving.config import ServerConfig
from strata_kb.web import registry_routes
from strata_kb.web.app import create_app

ROOT = Path(__file__).parent.parent
REGISTRY = "federation/registry.yaml"
SEED = """\
repos:
  acme/icao: icao-kb
  acme/web:
    repo_id: web-kb
    kind: dev
    workflow: acme/web/.github/workflows/kb-code.yml@refs/heads/main
"""
ADD_FORM = {"repo": "acme/new", "repo_id": "new", "kind": "dev", "auto_merge": "on"}


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch):
    for who in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{who}_NAME", "test")
        monkeypatch.setenv(f"GIT_{who}_EMAIL", "test@test.local")


@pytest.fixture
def registry_hub(fed_hub: Path, tmp_path: Path, run_git) -> Path:
    """fed_hub + a bare origin it has pushed to + a seeded registry."""
    branch = gitio.current_branch(fed_hub)
    origin = tmp_path / "hub-origin.git"
    run_git(tmp_path, "init", "--bare", "-b", branch, str(origin))
    (fed_hub / REGISTRY).write_text(SEED, encoding="utf-8", newline="\n")
    run_git(fed_hub, "add", "-A")
    run_git(fed_hub, "commit", "-m", "seed registry")
    run_git(fed_hub, "remote", "add", "origin", str(origin))
    run_git(fed_hub, "push", "-u", "origin", "HEAD")
    run_git(fed_hub, "remote", "set-head", "origin", branch)
    return fed_hub


def _fake_http(req):
    url = req.full_url
    if req.get_method() == "GET" and url.endswith("/installation"):
        return 200, json.dumps({"id": 9}).encode()
    if req.get_method() == "POST" and url.endswith("/access_tokens"):
        return 201, json.dumps({"token": "fake-installation-token"}).encode()
    raise AssertionError(f"unexpected http call: {req.get_method()} {url}")


@pytest.fixture
def intake_config(registry_hub: Path) -> intake.IntakeConfig:
    return intake.IntakeConfig(
        hub_ref=str(registry_hub),
        audience="https://kb.test",
        creds=ghapp.AppCreds(app_id="1", private_key_pem="unused-fake-http"),
        http=_fake_http,
        push_via_token_url=False,
    )


@pytest.fixture
def pushes() -> list[dict]:
    return []


@pytest.fixture
def recording_push(pushes):
    def push(work: Path, branch: str) -> None:
        pushes.append(
            {
                "branch": branch,
                "subject": gitio._run(work, "log", "-1", "--format=%s").stdout.strip(),
                "registry": (work / REGISTRY).read_text(encoding="utf-8"),
            }
        )

    return push


@pytest.fixture
def make_client(registry_hub: Path, token: str, intake_config):
    """Factory: a TestClient over the full app. `push=...` is the injected
    push, `real=True` runs the production one, `intake=False` disables intake."""
    with contextlib.ExitStack() as stack:

        def make(push=None, intake: bool = True) -> TestClient:
            config = ServerConfig(kb_dir=registry_hub / ".kb", hub=str(registry_hub))
            app = create_app(
                config,
                token,
                intake_cfg=intake_config if intake else None,
                registry_push=push,
            )
            return stack.enter_context(TestClient(app))

        yield make


def _login(client: TestClient, username: str, password: str) -> TestClient:
    resp = client.post(
        "/ui/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    return client


@pytest.fixture
def admin_registry_client(make_client, recording_push, admin_user):
    return _login(make_client(recording_push), *admin_user)


@pytest.fixture
def dev_client(make_client, recording_push, registry_hub: Path):
    password = secrets.token_urlsafe(12)
    Accounts(registry_hub / ".kb-auth" / "users.db").add("dev1", password, "dev")
    return _login(make_client(recording_push), "dev1", password)


def csrf_of(client: TestClient) -> str:
    page = client.get("/ui/registry")
    assert page.status_code == 200, page.text
    match = re.search(r'name="csrf" value="([^"]+)"', page.text)
    assert match, "no csrf field on the page"
    return match.group(1)


def post(client: TestClient, path: str, **fields):
    fields.setdefault("csrf", csrf_of(client))
    return client.post(path, data=fields, follow_redirects=False)


def commit_text(hub: Path, run_git, text: str, subject: str = "edit registry") -> None:
    """Land `text` as the registry on the checked-out branch (local commit)."""
    (hub / REGISTRY).write_text(text, encoding="utf-8", newline="\n")
    run_git(hub, "commit", "-am", subject)


def registry_bytes(hub: Path) -> bytes:
    return (hub / REGISTRY).read_bytes()


def test_anonymous_redirects_bearer_and_non_admin_get_403(
    make_client, dev_client, token
):
    anon = make_client()
    assert anon.get("/ui/registry", follow_redirects=False).status_code == 302
    assert (
        anon.post("/ui/registry/add", data=ADD_FORM, follow_redirects=False).status_code
        == 302
    )
    bearer = {"Authorization": f"Bearer {token}"}
    assert anon.get("/ui/registry", headers=bearer).status_code == 403
    for path in ("add", "remove", "auto-merge"):
        resp = anon.post(
            f"/ui/registry/{path}",
            data=ADD_FORM,
            headers=bearer,
            follow_redirects=False,
        )
        assert resp.status_code == 403, path
    assert dev_client.get("/ui/registry").status_code == 403
    for path in ("add", "remove", "auto-merge"):
        resp = dev_client.post(f"/ui/registry/{path}", data={"repo": "acme/icao"})
        assert resp.status_code == 403
    assert "/ui/registry" not in dev_client.get("/ui").text


def test_admin_lists_entries_and_history(admin_registry_client):
    resp = admin_registry_client.get("/ui/registry")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    body = resp.text
    for needle in ("acme/icao", "icao-kb", "acme/web", "web-kb", "badge-dev"):
        assert needle in body
    assert "acme/web/.github/workflows/kb-code.yml@refs/heads/main" in body
    assert 'aria-checked="false"' in body and 'aria-checked="true"' not in body
    assert '<span class="switch-state">Off</span>' in body  # readable without CSS
    assert "seed registry" in body  # the last commit subject
    assert 'href="/ui/registry"' in body  # nav item
    template = ROOT / "src/strata_kb/templates/web/registry.html"
    assert "style=" not in template.read_text(encoding="utf-8")


def test_registry_keys_are_html_escaped(
    admin_registry_client, registry_hub: Path, run_git
):
    commit_text(registry_hub, run_git, "repos:\n  'a<script>/b': rb\n")
    body = admin_registry_client.get("/ui/registry").text
    assert "a<script>/b" not in body and "a&lt;script&gt;/b" in body


def test_post_without_or_with_wrong_csrf_is_403(
    admin_registry_client, registry_hub: Path, pushes
):
    before = registry_bytes(registry_hub)
    missing = admin_registry_client.post("/ui/registry/add", data=ADD_FORM)
    wrong = admin_registry_client.post(
        "/ui/registry/add", data={**ADD_FORM, "csrf": "0" * 64}
    )
    assert (missing.status_code, wrong.status_code) == (403, 403)
    assert pushes == [] and registry_bytes(registry_hub) == before


def test_csrf_token_depends_on_key_and_session_cookie():
    token = registry_routes.csrf_token(b"k" * 32, "cookie-a")
    assert token == registry_routes.csrf_token(b"k" * 32, "cookie-a")
    assert token != registry_routes.csrf_token(b"k" * 32, "cookie-b")
    assert token != registry_routes.csrf_token(b"j" * 32, "cookie-a")


def test_add_writes_yaml_commits_and_pushes(
    admin_registry_client, registry_hub: Path, pushes
):
    r = post(admin_registry_client, "/ui/registry/add", **ADD_FORM)
    assert r.status_code == 303 and r.headers["location"] == "/ui/registry?done=added"
    assert len(pushes) == 1
    assert pushes[0]["subject"] == "registry: add acme/new (by admin)"
    assert pushes[0]["branch"] == gitio.default_branch(registry_hub)
    repos = yaml.safe_load(pushes[0]["registry"])["repos"]
    assert list(repos) == ["acme/icao", "acme/web", "acme/new"]  # appended last
    assert repos["acme/new"] == {"repo_id": "new", "kind": "dev", "auto_merge": True}
    assert "Repository added." in admin_registry_client.get(r.headers["location"]).text


def test_add_with_workflow_pin_and_defaults(admin_registry_client, pushes):
    pin = "acme/p/.github/workflows/x.yml@refs/heads/main"
    r = post(
        admin_registry_client,
        "/ui/registry/add",
        repo="acme/p",
        repo_id="p-kb",
        kind="",
        workflow=pin,
    )
    assert r.status_code == 303
    assert yaml.safe_load(pushes[0]["registry"])["repos"]["acme/p"] == {
        "repo_id": "p-kb",
        "workflow": pin,
    }


def test_toggle_auto_merge(admin_registry_client, pushes):
    on = post(
        admin_registry_client, "/ui/registry/auto-merge", repo="acme/icao", on="1"
    )
    assert on.status_code == 303
    assert pushes[0]["subject"] == "registry: auto-merge on acme/icao (by admin)"
    entry = yaml.safe_load(pushes[0]["registry"])["repos"]["acme/icao"]
    assert entry == {"repo_id": "icao-kb", "auto_merge": True}
    off = post(
        admin_registry_client, "/ui/registry/auto-merge", repo="acme/web", on="0"
    )
    assert off.headers["location"] == "/ui/registry?done=nochange"  # already off
    assert len(pushes) == 1


def test_remove_is_two_step_and_keeps_published_content(
    admin_registry_client, registry_hub: Path, pushes
):
    first = post(admin_registry_client, "/ui/registry/remove", repo="acme/icao")
    assert first.status_code == 200 and pushes == []
    assert "Confirm remove" in first.text and "not deleted" in first.text
    assert "federation/icao-kb/" in first.text
    done = post(
        admin_registry_client, "/ui/registry/remove", repo="acme/icao", confirm="yes"
    )
    assert done.status_code == 303
    assert pushes[0]["subject"] == "registry: remove acme/icao (by admin)"
    assert list(yaml.safe_load(pushes[0]["registry"])["repos"]) == ["acme/web"]
    assert (registry_hub / "federation" / "icao-kb").is_dir()


def test_invalid_add_leaves_file_untouched_and_shows_message(
    admin_registry_client, registry_hub: Path, pushes
):
    before = registry_bytes(registry_hub)
    r = post(
        admin_registry_client,
        "/ui/registry/add",
        repo="acme/bad",
        repo_id="../x",
        kind="dev",
    )
    assert r.status_code == 400
    assert "repo-id" in r.text and "acme/bad" in r.text  # message + form kept
    assert pushes == [] and registry_bytes(registry_hub) == before
    for dup in (
        {"repo": "ACME/ICAO", "repo_id": "other"},  # key case-collides
        {"repo": "acme/other", "repo_id": "icao-kb"},  # repo-id claimed
        {"repo": "acme/other", "repo_id": "ARINC-KB"},  # case-collides with a dir
    ):
        assert post(admin_registry_client, "/ui/registry/add", **dup).status_code == 400
    assert pushes == []


def test_remove_or_toggle_of_a_key_that_is_gone_is_409(admin_registry_client, pushes):
    gone = post(
        admin_registry_client, "/ui/registry/remove", repo="acme/gone", confirm="yes"
    )
    assert gone.status_code == 409 and "acme/gone" in gone.text
    ask = post(admin_registry_client, "/ui/registry/remove", repo="acme/gone")
    assert ask.status_code == 409
    toggle = post(
        admin_registry_client, "/ui/registry/auto-merge", repo="acme/gone", on="1"
    )
    assert toggle.status_code == 409
    assert pushes == []


def test_read_only_when_intake_disabled(make_client, admin_user, registry_hub: Path):
    client = _login(make_client(intake=False), *admin_user)
    page = client.get("/ui/registry")
    assert page.status_code == 200
    assert "Read-only" in page.text and "STRATA_KB_GH_APP_ID" in page.text
    assert "acme/icao" in page.text  # still lists
    assert 'action="/ui/registry/add"' not in page.text
    assert 'action="/ui/registry/remove"' not in page.text
    before = registry_bytes(registry_hub)
    resp = client.post("/ui/registry/add", data=ADD_FORM)
    assert resp.status_code == 409 and registry_bytes(registry_hub) == before


def test_read_only_when_hub_has_no_remote(
    make_client, recording_push, admin_user, registry_hub: Path, run_git, pushes
):
    run_git(registry_hub, "remote", "remove", "origin")
    client = _login(make_client(recording_push), *admin_user)
    assert "no GitHub remote" in client.get("/ui/registry").text
    assert client.post("/ui/registry/add", data=ADD_FORM).status_code == 409
    assert pushes == []


def test_push_rejected_shows_error_and_no_local_change(
    make_client, admin_user, registry_hub: Path, run_git
):
    def rejected(work: Path, branch: str) -> None:
        raise gitio.GitError(
            "push to 'main' failed: ! [remote rejected] HEAD -> main "
            "(protected branch hook declined)"
        )

    client = _login(make_client(rejected), *admin_user)
    before = registry_bytes(registry_hub)
    r = post(client, "/ui/registry/add", **ADD_FORM)
    assert r.status_code == 502 and "protected branch" in r.text
    assert "Traceback" not in r.text
    assert registry_bytes(registry_hub) == before
    assert run_git(registry_hub, "status", "--porcelain") == ""
    assert run_git(registry_hub, "worktree", "list").count("\n") == 0  # none left
    assert not registry_routes.registry_lock.locked()


def test_stale_base_rejection_is_409_hub_moved(make_client, admin_user):
    def stale(work: Path, branch: str) -> None:
        raise gitio.GitError(
            "push to 'main' failed: ! [rejected] HEAD -> main (fetch first)"
        )

    client = _login(make_client(stale), *admin_user)
    r = post(client, "/ui/registry/add", **ADD_FORM)
    assert r.status_code == 409
    assert "hub moved" in r.text and "Reload" in r.text


def test_unexpected_error_is_a_clean_500_page(make_client, admin_user):
    def boom(work: Path, branch: str) -> None:
        raise RuntimeError("secret detail /etc/passwd")

    client = _login(make_client(boom), *admin_user)
    r = post(client, "/ui/registry/add", **ADD_FORM)
    assert r.status_code == 500 and "secret detail" not in r.text
    assert not registry_routes.registry_lock.locked()


def test_unreadable_registry_shows_message_and_is_read_only(
    admin_registry_client, registry_hub: Path, run_git
):
    commit_text(registry_hub, run_git, "repos: [oops")
    page = admin_registry_client.get("/ui/registry")
    assert page.status_code == 200
    assert "invalid" in page.text and 'action="/ui/registry/add"' not in page.text


@pytest.fixture
def real_push(monkeypatch):
    monkeypatch.setattr(ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(ghapp, "repo_full_from_url", lambda url: "acme/hub")


def test_real_push_lands_on_origin_and_pulls_the_checkout(
    make_client, admin_user, registry_hub: Path, tmp_path: Path, run_git, real_push
):
    client = _login(make_client(None), *admin_user)
    r = post(client, "/ui/registry/add", **ADD_FORM)
    assert r.status_code == 303
    origin = tmp_path / "hub-origin.git"
    branch = gitio.default_branch(registry_hub)
    assert (
        run_git(origin, "log", "-1", "--format=%s", branch)
        == "registry: add acme/new (by admin)"
    )
    # the checkout was fast-forwarded, so the page (and intake) see it now
    assert "acme/new" in (registry_hub / REGISTRY).read_text(encoding="utf-8")
    # and the next edit builds on it
    t = post(client, "/ui/registry/auto-merge", repo="acme/new", on="0")
    assert t.status_code == 303
    assert run_git(origin, "log", "-1", "--format=%s", branch).startswith(
        "registry: auto-merge off acme/new"
    )
    assert "registry: add acme/new" in client.get("/ui/registry").text


def test_real_push_pulls_before_editing(
    make_client, admin_user, registry_hub: Path, tmp_path: Path, run_git, real_push
):
    """Another admin's change on origin must be the base of this edit."""
    origin = tmp_path / "hub-origin.git"
    other = tmp_path / "other"
    run_git(tmp_path, "clone", str(origin), str(other))
    (other / REGISTRY).write_text(
        SEED + "  acme/theirs: theirs-kb\n", encoding="utf-8", newline="\n"
    )
    run_git(other, "commit", "-am", "registry: add acme/theirs (by bob)")
    run_git(other, "push", "origin", "HEAD")
    client = _login(make_client(None), *admin_user)
    assert post(client, "/ui/registry/add", **ADD_FORM).status_code == 303
    repos = yaml.safe_load((registry_hub / REGISTRY).read_text(encoding="utf-8"))
    assert {"acme/theirs", "acme/new"} <= set(repos["repos"])


def test_real_push_losing_a_race_is_409_and_never_forced(
    make_client, admin_user, registry_hub: Path, tmp_path: Path, run_git, real_push
):
    origin = tmp_path / "hub-origin.git"
    branch = gitio.default_branch(registry_hub)
    other = tmp_path / "other"
    run_git(tmp_path, "clone", str(origin), str(other))
    (other / "note.txt").write_text("remote", encoding="utf-8", newline="\n")
    run_git(other, "add", "note.txt")
    run_git(other, "commit", "-m", "remote moved")
    run_git(other, "push", "origin", "HEAD")
    # the hub checkout diverged too, so its pull (ff-only) cannot catch up
    (registry_hub / "local.txt").write_text("local", encoding="utf-8", newline="\n")
    run_git(registry_hub, "add", "local.txt")
    run_git(registry_hub, "commit", "-m", "local drift")
    client = _login(make_client(None), *admin_user)
    r = post(client, "/ui/registry/add", **ADD_FORM)
    assert r.status_code == 409 and "hub moved" in r.text
    assert run_git(origin, "log", "-1", "--format=%s", branch) == "remote moved"


def test_oversized_post_body_is_413(admin_registry_client, pushes):
    resp = admin_registry_client.post(
        "/ui/registry/add", data={**ADD_FORM, "workflow": "x" * 20000}
    )
    assert resp.status_code == 413 and pushes == []


def test_edit_starts_from_the_default_branch_not_an_off_branch_checkout(
    admin_registry_client, registry_hub: Path, run_git, pushes
):
    default = gitio.default_branch(registry_hub)
    run_git(registry_hub, "checkout", "-b", "side")
    commit_text(registry_hub, run_git, SEED + "  acme/stale: stale-kb\n")
    assert gitio.current_branch(registry_hub) != default
    page = admin_registry_client.get("/ui/registry")
    assert "acme/stale" not in page.text and "acme/icao" in page.text
    r = post(admin_registry_client, "/ui/registry/add", **ADD_FORM)
    assert r.status_code == 303
    repos = yaml.safe_load(pushes[0]["registry"])["repos"]
    assert list(repos) == ["acme/icao", "acme/web", "acme/new"]  # no acme/stale


def test_uncommitted_hand_edit_is_not_committed(
    admin_registry_client, registry_hub: Path, pushes
):
    dirty = SEED + "  acme/handmade: hand-kb\n"
    (registry_hub / REGISTRY).write_text(dirty, encoding="utf-8", newline="\n")
    assert "acme/handmade" not in admin_registry_client.get("/ui/registry").text
    r = post(admin_registry_client, "/ui/registry/add", **ADD_FORM)
    assert r.status_code == 303
    assert "acme/handmade" not in pushes[0]["registry"]
    assert registry_bytes(registry_hub) == dirty.encode()  # left as the operator had it


def test_head_and_options_are_not_a_way_around_the_admin_check(make_client, dev_client):
    anon = make_client()
    for method in ("HEAD", "OPTIONS"):
        resp = anon.request(method, "/ui/registry", follow_redirects=False)
        assert resp.status_code == 302
    assert dev_client.head("/ui/registry").status_code == 403
    options = dev_client.options("/ui/registry")
    assert options.status_code in (403, 405) and "acme/icao" not in options.text


def test_csrf_token_of_another_session_is_rejected(
    make_client, recording_push, admin_user, registry_hub: Path, pushes
):
    Accounts(registry_hub / ".kb-auth" / "users.db").add(
        "admin2", "pw-two-xyz", "admin"
    )
    one = _login(make_client(recording_push), *admin_user)
    two = _login(make_client(recording_push), "admin2", "pw-two-xyz")
    stolen = csrf_of(one)
    assert csrf_of(two) != stolen
    resp = two.post("/ui/registry/add", data={**ADD_FORM, "csrf": stolen})
    assert resp.status_code == 403 and pushes == []


def test_chunked_oversized_body_is_413_and_not_pushed(admin_registry_client, pushes):
    def chunks():
        for _ in range(40):
            yield b"workflow=" + b"x" * 1000 + b"&"

    resp = admin_registry_client.post(
        "/ui/registry/add",
        content=chunks(),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 413 and pushes == []


def test_script_in_workflow_subject_and_echoed_form_is_escaped(
    admin_registry_client, registry_hub: Path, run_git
):
    xss = "<script>alert(1)</script>"
    commit_text(
        registry_hub,
        run_git,
        f"repos:\n  a/b:\n    repo_id: rb\n    workflow: '{xss}'\n",
        subject=f"registry: {xss}",
    )
    body = admin_registry_client.get("/ui/registry").text
    assert xss not in body and "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    bad = post(
        admin_registry_client,
        "/ui/registry/add",
        repo="acme/x",
        repo_id="<script>alert(2)</script>",
    )
    assert bad.status_code == 400
    assert "<script>alert(2)" not in bad.text and "&lt;script&gt;alert(2)" in bad.text


def test_remote_url_credentials_never_reach_the_page(
    make_client, admin_user, registry_hub: Path, run_git, monkeypatch
):
    from strata_kb import hub as hub_mod

    monkeypatch.setattr(hub_mod, "pull_once", lambda hub: False)  # no network
    run_git(
        registry_hub,
        "remote",
        "set-url",
        "origin",
        "https://u:hunter2@example.com/h.git",
    )
    client = _login(make_client(None), *admin_user)  # real push path
    r = post(client, "/ui/registry/add", **ADD_FORM)
    assert r.status_code == 502
    assert "hunter2" not in r.text and "u:hunter" not in r.text


def test_pull_failure_after_a_landed_push_is_not_a_500(
    make_client, admin_user, registry_hub: Path, recording_push, monkeypatch
):
    import sqlite3

    from strata_kb import hub as hub_mod

    def boom(hub: str) -> bool:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(hub_mod, "pull_once", boom)
    client = _login(make_client(recording_push), *admin_user)
    r = post(client, "/ui/registry/add", **ADD_FORM)
    assert r.status_code == 303
    page = client.get(r.headers["location"])
    assert "Repository added." in page.text
    assert "this hub&#39;s checkout did not refresh" in page.text


def test_successful_pull_after_a_landed_push_has_no_stale_notice(
    make_client, admin_user, registry_hub: Path, recording_push, monkeypatch
):
    from strata_kb import hub as hub_mod

    monkeypatch.setattr(hub_mod, "pull_once", lambda hub: False)
    client = _login(make_client(recording_push), *admin_user)
    r = post(client, "/ui/registry/add", **ADD_FORM)
    page = client.get(r.headers["location"])
    assert "Repository added." in page.text and "did not refresh" not in page.text
