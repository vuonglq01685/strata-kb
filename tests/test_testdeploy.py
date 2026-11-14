"""Deploy check and change set of a story, over fake GitHub answers."""

from pathlib import Path
from urllib.parse import quote

import pytest
import yaml

from strata_kb import testdeploy, testenv
from strata_kb.errors import KbError
from strata_kb.ghio import GHError
from strata_kb.hub import HubHandle
from tests.test_planingest import API, US1, WEB
from tests.test_planstatus_parents import build  # noqa: F401  (fixture)

EXAMPLE = Path(testenv.__file__).parent / "templates/init/test-env.example.yaml"
PUBLISH = {"demo": "aaa1111", "web": "bbb2222"}


def _publish(hub: HubHandle, commits: dict[str, str]) -> None:
    for repo, commit in commits.items():
        meta = hub.federation_dir / repo / "_meta.yaml"
        data = yaml.safe_load(meta.read_text(encoding="utf-8"))
        data["source_url"] = f"https://github.com/acme/{repo}"
        data["source_commit"] = commit
        meta.write_text(yaml.safe_dump(data), encoding="utf-8")


def _env(*repos: str, versioned: bool = True) -> testenv.TestEnv:
    data = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    app = data["apps"][0]
    data["apps"] = [
        {"repo": r, **({"version_check": app["version_check"]} if versioned else {})}
        for r in repos
    ]
    return testenv.TestEnv.model_validate(data)


def _api(statuses: dict[str, str], calls: list | None = None):
    def api(root, method, path, body=None):
        if calls is not None:
            calls.append(path)
        for slug, status in statuses.items():
            if path == f"repos/acme/{slug}/compare/{PUBLISH[slug]}...env-{slug}":
                return {"status": status}
        raise KbError(f"unexpected {path}")

    return api


def _commits(monkeypatch, repos=("demo", "web")):
    monkeypatch.setattr(
        testenv, "app_commits", lambda env, http=None: {r: f"env-{r}" for r in repos}
    )


def test_story_repos_split_maps_repo_to_children(build):  # noqa: F811
    assert testdeploy.story_repos(build(), US1) == {"demo": [API], "web": [WEB]}


def test_story_repos_of_unsplit_story_is_its_target(plan_hub):
    assert testdeploy.story_repos(plan_hub, "TAL-1580") == {"demo": ["TAL-1580"]}


def test_deployed_when_env_descends_from_publish(build, monkeypatch, tmp_path):  # noqa: F811
    hub = build()
    _publish(hub, PUBLISH)
    _commits(monkeypatch)
    api = _api({"demo": "ahead", "web": "identical"})
    assert (
        testdeploy.deployed(hub, _env("demo", "web"), US1, api=api, root=tmp_path) == []
    )


def test_not_deployed_when_behind(build, monkeypatch, tmp_path):  # noqa: F811
    hub = build()
    _publish(hub, PUBLISH)
    _commits(monkeypatch)
    api = _api({"demo": "ahead", "web": "behind"})
    reasons = testdeploy.deployed(hub, _env("demo", "web"), US1, api=api, root=tmp_path)
    assert reasons == ["web: env at env-web, publish at bbb2222 not deployed yet"]


def test_split_story_checks_every_child_repo(build, monkeypatch, tmp_path):  # noqa: F811
    hub = build()
    _publish(hub, PUBLISH)
    _commits(monkeypatch)
    calls: list[str] = []
    api = _api({"demo": "ahead", "web": "ahead"}, calls)
    testdeploy.deployed(hub, _env("demo", "web"), US1, api=api, root=tmp_path)
    assert sorted(calls) == [
        "repos/acme/demo/compare/aaa1111...env-demo",
        "repos/acme/web/compare/bbb2222...env-web",
    ]


def test_missing_version_check_is_a_reason(build, tmp_path):  # noqa: F811
    hub = build()
    _publish(hub, PUBLISH)
    reasons = testdeploy.deployed(
        hub, _env("demo", versioned=False), US1, api=_api({}), root=tmp_path
    )
    assert reasons == ["demo: no version_check", "web: no version_check"]


def test_unpublished_repo_is_a_reason(build, monkeypatch, tmp_path):  # noqa: F811
    hub = build()
    _commits(monkeypatch)
    reasons = testdeploy.deployed(
        hub, _env("demo", "web"), US1, api=_api({}), root=tmp_path
    )
    assert reasons == ["demo: not published", "web: not published"]


def test_changed_files_maps_child_to_pr_files(build, tmp_path):  # noqa: F811
    hub = build()
    _publish(hub, PUBLISH)

    def api(root, method, path, body=None):
        if path.startswith("search/issues"):
            slug = "demo" if "repo%3Aacme%2Fdemo" in path else "web"
            assert quote(f'"{API if slug == "demo" else WEB}"', safe="") in path
            return {"items": [{"number": 7 if slug == "demo" else 9}]}
        files = {
            "repos/acme/demo/pulls/7/files": [{"filename": "a.py"}],
            "repos/acme/web/pulls/9/files": [
                {"filename": "b.ts"},
                {"filename": "c.ts"},
            ],
        }
        return files[path.partition("?")[0]]

    assert testdeploy.changed_files(hub, US1, api=api, root=tmp_path) == {
        API: ["a.py"],
        WEB: ["b.ts", "c.ts"],
    }


def test_story_not_on_hub_raises(plan_hub):
    with pytest.raises(KbError):
        testdeploy.story_repos(plan_hub, "NOPE-1")


def test_cli_deployed_exits_4_with_reasons(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from strata_kb import cli

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(testenv, "load", lambda root: None)
    monkeypatch.setattr(cli, "_story_hub", lambda hub: None)
    monkeypatch.setattr(testdeploy, "deployed", lambda *a, **k: ["web: not published"])
    res = CliRunner().invoke(cli.app, ["test-env", "deployed", US1])
    assert (res.exit_code, res.output.strip()) == (4, "web: not published")
    monkeypatch.setattr(testdeploy, "deployed", lambda *a, **k: [])
    assert CliRunner().invoke(cli.app, ["test-env", "deployed", US1]).exit_code == 0


def test_github_error_is_not_a_not_yet_reason(build, monkeypatch, tmp_path):  # noqa: F811
    hub = build()
    _publish(hub, PUBLISH)
    _commits(monkeypatch)

    def api(root, method, path, body=None):
        raise GHError("gh: not logged in")

    with pytest.raises(GHError):
        testdeploy.deployed(hub, _env("demo", "web"), US1, api=api, root=tmp_path)


def test_empty_github_answer_is_an_error(build, monkeypatch, tmp_path):  # noqa: F811
    hub = build()
    _publish(hub, PUBLISH)
    _commits(monkeypatch)
    with pytest.raises(KbError, match="nothing for GET repos/acme/demo/compare"):
        testdeploy.deployed(
            hub, _env("demo", "web"), US1, api=lambda *a, **k: None, root=tmp_path
        )


def test_changed_files_follows_pages_and_quotes_the_query(build, tmp_path):  # noqa: F811
    hub = build()
    _publish(hub, PUBLISH)
    seen: list[str] = []

    def api(root, method, path, body=None):
        seen.append(path)
        if path.startswith("search/issues"):
            return {"items": [{"number": 7}]} if "demo" in path else {"items": []}
        page = int(path.rsplit("page=", 1)[1])
        n = 100 if page == 1 else 5
        return [{"filename": f"f{page}-{i}"} for i in range(n)]

    files = testdeploy.changed_files(hub, US1, api=api, root=tmp_path)
    assert len(files[API]) == 105 and files[WEB] == []
    assert any("per_page=100&page=2" in p for p in seen)
    assert not any('"' in p or " " in p for p in seen)


def test_story_repos_of_parent_bug_includes_own_fix_repo(monkeypatch):
    from strata_kb import ticketfetch
    from tests.test_ticketlint_family import bug_parent_text

    rows = (
        "| BUG-12 | demo | - | - | yes | first fix |\n"
        "| BUG-12.web | web | - | - | - | ui |\n"
    )
    text = bug_parent_text(rows=rows)
    monkeypatch.setattr(ticketfetch, "find", lambda hub, ref: ("ba", "ba-plan", None))
    monkeypatch.setattr(ticketfetch, "read_section", lambda *a: "x")
    monkeypatch.setattr(ticketfetch, "source_text", lambda s: text)
    assert testdeploy.story_repos(None, "BUG-12") == {
        "demo": ["BUG-12"],
        "web": ["BUG-12.web"],
    }
