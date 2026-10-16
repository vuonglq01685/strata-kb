"""Auto mode on Claude Code cloud: the runner reads the hub live over its API."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from strata_kb import hubapi, planstatus
from strata_kb.autorun import picker, switch
from strata_kb.autorun import runner as runner_mod
from strata_kb.autorun import state as autostate
from strata_kb.autorun.claude import TaskResult
from strata_kb.autorun.picker import Task, pick_dev
from strata_kb.autorun.runner import preflight, run_once
from strata_kb.errors import KbError
from strata_kb.hub import HubHandle
from tests.test_autorun_runner import (  # noqa: F401
    GOOD,
    FakeQa,
    Script,
    cfg_of,
    no_switch_check,
)

STORY = {
    "us_id": "M-x-US3", "mission_id": "M-x", "title": "t", "status": "ready",
    "reasons": [], "depends_on": [],
}  # fmt: skip


class FakeHub:
    """An `httpio.request` double: one canned (status, JSON) per route."""

    def __init__(self, **routes):
        self.routes = routes
        self.calls: list[str] = []

    def __call__(self, method, url, headers, body=None, timeout=60):
        route = "/api/" + url.split("/api/", 1)[1].split("?")[0]
        self.calls.append(route)
        code, payload = self.routes[route]
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return code, raw


def plan(stories=(STORY,), unparented=()):
    return 200, {"stories": list(stories), "unparented": list(unparented), "notes": []}


def entry(**facts):
    return 200, {
        "repo_id": "svc",
        "kind": "dev",
        "auto_merge": True,
        "dev_repos": 1,
    } | facts


@pytest.fixture(autouse=True)
def cloud(monkeypatch):
    monkeypatch.setenv("STRATA_KB_CLOUD", "1")


@pytest.fixture
def hub_api(monkeypatch):
    """Install a HubApi over `FakeHub` as what `hubapi.from_env` returns."""

    def install(**routes) -> FakeHub:
        http = FakeHub(**routes)
        monkeypatch.setattr(
            hubapi, "from_env", lambda: hubapi.HubApi("http://hub", "tok", http=http)
        )
        return http

    return install


@pytest.fixture
def kb_dir(tmp_path: Path) -> Path:
    path = tmp_path / ".kb"
    path.mkdir()
    return path


def test_picker_reads_the_plan_through_the_api(tmp_path: Path):
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "kb-test.yml").write_text("name: kb-test\n")
    http = FakeHub(**{"/api/plan/next": plan()})
    hub = hubapi.HubApi("http://hub", "tok", http=http)

    assert pick_dev(hub, tmp_path) == Task("dev-implement-ticket", "M-x-US3")  # type: ignore[arg-type]
    assert http.calls == ["/api/plan/next"]


def test_picker_still_calls_next_from_hub_by_module_attribute(tmp_path, monkeypatch):
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "kb-test.yml").write_text("name: kb-test\n")
    monkeypatch.setattr(
        planstatus, "next_from_hub", lambda hub, repo=None: ([], [], [])
    )
    assert pick_dev(HubHandle(root=tmp_path), tmp_path) is None


def test_cloud_runner_idles_when_hub_unreachable(tmp_path, kb_dir):
    autostate.save(
        kb_dir, autostate.AutoState("dev-implement-ticket:M-x-US3", 1, (), None, "")
    )
    hub = hubapi.HubApi(
        "http://hub", "tok", http=FakeHub(**{"/api/plan/next": (0, b"refused")})
    )
    script = Script(TaskResult("done"))

    outcome = run_once(
        tmp_path,
        kb_dir,
        cfg=cfg_of(),
        hub=hub,
        qa=FakeQa(),
        run_task=script,  # type: ignore[arg-type]
    )

    assert outcome == "idle"
    assert script.prompts == []
    assert autostate.load(kb_dir).attempts == 1


def test_cloud_runner_ends_done_from_the_api(tmp_path, kb_dir):
    done = dict(STORY, status="done")
    hub = hubapi.HubApi(
        "http://hub", "tok", http=FakeHub(**{"/api/plan/next": plan([done])})
    )
    outcome = run_once(
        tmp_path,
        kb_dir,
        cfg=cfg_of(),
        hub=hub,
        qa=FakeQa(),
        run_task=Script(),  # type: ignore[arg-type]
    )
    assert outcome == "done"


def test_cloud_resolve_hub_is_the_api_client_and_never_the_clone(
    kb_dir, hub_api, monkeypatch
):
    hub_api()
    monkeypatch.setattr(
        runner_mod, "resolve_hub", lambda ref: pytest.fail("cloud must not clone")
    )
    monkeypatch.setattr(
        runner_mod, "require_hub", lambda *a: pytest.fail("cloud has no hub path")
    )

    assert isinstance(runner_mod._resolve_hub(cfg_of(), kb_dir), hubapi.HubApi)


def test_cloud_build_deps_without_hub_env_is_a_kberror(kb_dir, monkeypatch):
    for var in ("STRATA_KB_HUB_URL", "STRATA_KB_HTTP_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(KbError):
        runner_mod._resolve_hub(cfg_of(), kb_dir)


@pytest.mark.usefixtures("no_switch_check")
def test_cloud_preflight_refuses_without_auto_merge(
    tmp_path, kb_dir, hub_api, monkeypatch
):
    monkeypatch.setattr(
        runner_mod, "registry_or_reason", lambda *a: pytest.fail("cloud reads the API")
    )
    (kb_dir / "config.yaml").write_text(GOOD, encoding="utf-8", newline="\n")
    hub_api(**{"/api/registry/entry": entry(auto_merge=False)})

    (reason,) = preflight(tmp_path, kb_dir)

    assert reason == (
        "the hub registry entry for 'svc' lacks `auto_merge: true`, "
        "so intake would not merge its publish PRs"
    )


@pytest.mark.usefixtures("no_switch_check")
def test_cloud_preflight_passes_with_auto_merge(tmp_path, kb_dir, hub_api):
    (kb_dir / "config.yaml").write_text(GOOD, encoding="utf-8", newline="\n")
    hub_api(**{"/api/registry/entry": entry()})
    assert preflight(tmp_path, kb_dir) == []


@pytest.mark.usefixtures("no_switch_check")
def test_cloud_preflight_unregistered_repo(tmp_path, kb_dir, hub_api):
    (kb_dir / "config.yaml").write_text(GOOD, encoding="utf-8", newline="\n")
    hub_api(**{"/api/registry/entry": (404, {"error": "repo_not_registered"})})
    assert preflight(tmp_path, kb_dir) == ["repo_id 'svc' is not in the hub registry"]


@pytest.mark.usefixtures("no_switch_check")
def test_cloud_preflight_unreachable_hub_is_a_reason(tmp_path, kb_dir, hub_api):
    (kb_dir / "config.yaml").write_text(GOOD, encoding="utf-8", newline="\n")
    hub_api(**{"/api/registry/entry": (0, b"connection refused")})
    (reason,) = preflight(tmp_path, kb_dir)
    assert reason.startswith("the hub registry could not be read: hub unreachable")


@pytest.mark.usefixtures("no_switch_check")
def test_cloud_preflight_old_hub_names_the_upgrade(tmp_path, kb_dir, hub_api):
    (kb_dir / "config.yaml").write_text(GOOD, encoding="utf-8", newline="\n")
    hub_api(**{"/api/registry/entry": (404, b"Not Found")})
    (reason,) = preflight(tmp_path, kb_dir)
    assert "upgrade it to strata-kb 1.30.0" in reason


def test_cloud_warnings_for_on_count_dev_repos(kb_dir, hub_api):
    (kb_dir / "config.yaml").write_text(GOOD, encoding="utf-8", newline="\n")
    hub_api(**{"/api/registry/entry": entry(dev_repos=2)})

    warnings = switch.warnings_for_on(kb_dir, "")

    assert any("admin" in w for w in warnings)
    assert any("one Dev repo per hub" in w and "lists 2" in w for w in warnings)


def test_cloud_warnings_for_on_one_dev_is_just_the_admin_line(kb_dir, hub_api):
    (kb_dir / "config.yaml").write_text(GOOD, encoding="utf-8", newline="\n")
    hub_api(**{"/api/registry/entry": entry()})
    assert len(switch.warnings_for_on(kb_dir, "")) == 1


def test_cloud_warnings_for_on_unreachable_says_registry_not_checked(kb_dir, hub_api):
    (kb_dir / "config.yaml").write_text(GOOD, encoding="utf-8", newline="\n")
    hub_api(**{"/api/registry/entry": (0, b"refused")})
    warnings = switch.warnings_for_on(kb_dir, "")
    assert any("registry not checked" in w.lower() for w in warnings)


def test_local_mode_unchanged(tmp_path, kb_dir, monkeypatch):
    monkeypatch.setenv("STRATA_KB_CLOUD", "0")
    monkeypatch.setattr(
        hubapi, "from_env", lambda: pytest.fail("local mode must not use the API")
    )
    hub_dir = tmp_path / "hub"
    (hub_dir / ".kb").mkdir(parents=True)

    handle = runner_mod._resolve_hub(cfg_of(), kb_dir, str(hub_dir))

    assert isinstance(handle, HubHandle)
    seen = []
    monkeypatch.setattr(
        runner_mod,
        "registry_or_reason",
        lambda kb, hub: seen.append(hub) or (None, "nope"),
    )
    monkeypatch.setattr(runner_mod, "_switch_refusals", lambda root: [])
    (kb_dir / "config.yaml").write_text(GOOD, encoding="utf-8", newline="\n")
    (reason,) = preflight(tmp_path, kb_dir, "/flag/hub")
    assert seen == ["/flag/hub"] and "nope" in reason


def test_picker_module_exposes_plan_next():
    assert picker.plan_next
