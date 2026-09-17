from typer.testing import CliRunner

from center_kb.cli import app

runner = CliRunner()


def test_query_reads_federation_only(fed_hub, fixture_kb):
    # fixture_kb holds demo-doc, which is NOT published — it must not show up
    result = runner.invoke(
        app,
        ["query", "restrictive airspace designation",
         "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)],
    )
    assert result.exit_code == 0
    assert "arinc-kb:arinc-424 §5.3" in result.output
    assert "demo-doc" not in result.output


def test_query_without_hub_config_errors_with_guide(fixture_kb, monkeypatch):
    monkeypatch.delenv("CENTER_KB_HUB", raising=False)
    result = runner.invoke(
        app, ["query", "anything", "--kb-dir", str(fixture_kb)]
    )
    assert result.exit_code == 1
    assert "config.yaml" in result.output


def test_query_hub_from_config_file(fed_hub, fixture_kb, monkeypatch):
    monkeypatch.delenv("CENTER_KB_HUB", raising=False)
    (fixture_kb / "config.yaml").write_text(f"hub: {fed_hub}\n", encoding="utf-8")
    result = runner.invoke(
        app, ["query", "restrictive airspace", "--kb-dir", str(fixture_kb)]
    )
    assert result.exit_code == 0
    assert "arinc-kb:arinc-424" in result.output


def test_get_with_repo_and_l3(fed_hub, fixture_kb):
    result = runner.invoke(
        app,
        ["get", "arinc-424", "5.3", "--level", "l3", "--repo", "arinc-kb",
         "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)],
    )
    assert result.exit_code == 0
    assert "Full raw restrictive airspace" in result.output


def test_get_ambiguous_doc_errors(fed_hub, fixture_kb):
    from tests.conftest import make_fed_entry

    make_fed_entry(fed_hub / "federation", "dup-kb", "arinc-424", sec_id="5.3")
    result = runner.invoke(
        app,
        ["get", "arinc-424", "5.3", "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)],
    )
    assert result.exit_code == 1
    assert "dup-kb:arinc-424" in result.output


def test_query_warns_when_the_hub_cache_is_stale(fed_hub, fixture_kb, monkeypatch):
    """M17 judgment call 2: `_hub_or_exit` already prints
    "[warn] hub cache is stale (~Xs)" to stderr for every CLI command that
    resolves a stale HubHandle -- `query` and `get` both call it (traced in
    cli.py: both do `handle = _hub_or_exit(hub, kb_dir)` before anything
    else) -- so this pins the EXISTING warning rather than adding a second,
    duplicate one from `stale_hub_note` (which stays MCP/REST-only). Not
    falsifiable against this task's own changes (cli.py is untouched), only
    against a future regression in `_hub_or_exit`'s existing warning."""
    from center_kb import hub as hub_mod
    from center_kb.hub import HubHandle

    monkeypatch.setattr(
        hub_mod, "resolve_hub",
        lambda hub_ref: HubHandle(root=fed_hub, stale=True, age_seconds=1234.0),
    )
    result = runner.invoke(
        app,
        ["query", "restrictive airspace designation",
         "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)],
    )
    assert result.exit_code == 0
    assert result.stderr.count("hub cache is stale") == 1


def test_get_warns_when_the_hub_cache_is_stale(fed_hub, fixture_kb, monkeypatch):
    """Same as test_query_warns_when_the_hub_cache_is_stale, for `get`."""
    from center_kb import hub as hub_mod
    from center_kb.hub import HubHandle

    monkeypatch.setattr(
        hub_mod, "resolve_hub",
        lambda hub_ref: HubHandle(root=fed_hub, stale=True, age_seconds=1234.0),
    )
    result = runner.invoke(
        app,
        ["get", "arinc-424", "5.3", "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)],
    )
    assert result.exit_code == 0
    assert result.stderr.count("hub cache is stale") == 1


def test_reindex_repairs_aggregate_index(git_kb, hub_worktree):
    from center_kb.publish import publish

    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    (hub_worktree / "federation" / "index.yaml").write_text(
        "docs: []\n", encoding="utf-8"
    )
    result = runner.invoke(
        app, ["reindex", "--hub", str(hub_worktree), "--kb-dir", str(git_kb["kb"])]
    )
    assert result.exit_code == 0
    from center_kb import models

    idx = models.load_yaml_model(
        hub_worktree / "federation" / "index.yaml", models.FederationIndex
    )
    assert [(e.repo_id, e.doc_id) for e in idx.docs] == [("demo-kb", "demo-doc")]


def test_publish_cli_prints_pr_url(git_kb, hub_worktree, monkeypatch):
    from center_kb import publish as publish_mod

    calls: dict = {}

    def fake_publish(kb_dir, hub_ref, repo_id=None, mode="auto", self_publish=False):
        calls["self_publish"] = self_publish
        return publish_mod.PublishReport(
            repo_id="demo-kb", source_commit="abc1234", n_docs=1,
            pushed=True, mode="pr", pr_url="https://github.com/org/hub/pull/7",
        )

    monkeypatch.setattr(publish_mod, "publish", fake_publish)
    result = runner.invoke(
        app, ["publish", "--hub", str(hub_worktree), "--kb-dir", str(git_kb["kb"])]
    )
    assert result.exit_code == 0
    assert "pull/7" in result.output
    # cli.py now always passes self_publish through -- a plain (non-hub-self)
    # publish must pass False, never omit it.
    assert calls["self_publish"] is False


def test_reindex_builds_search_db(fed_hub, git_kb):
    result = runner.invoke(
        app, ["reindex", "--hub", str(fed_hub), "--kb-dir", str(git_kb["kb"])]
    )
    assert result.exit_code == 0
    assert (fed_hub / ".kb-work" / "search.db").exists()
    assert "search index" in result.output


def test_reindex_commits_index_before_search_sync(fed_hub, git_kb, run_git, monkeypatch):
    # a sync (embed) blowup must still surface the error, but the rebuilt
    # federation/index.yaml must not sit uncommitted — commit first, sync after
    from center_kb import searchdb as searchdb_mod

    (fed_hub / "federation" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    run_git(fed_hub, "add", "-A")
    run_git(fed_hub, "commit", "-m", "corrupt index")

    def boom(handle, embedder):
        raise RuntimeError("embed exploded")

    monkeypatch.setattr(searchdb_mod, "sync", boom)
    result = runner.invoke(
        app, ["reindex", "--hub", str(fed_hub), "--kb-dir", str(git_kb["kb"])]
    )
    assert result.exit_code != 0  # strict embed error — must surface
    assert run_git(fed_hub, "status", "--porcelain", "--", "federation") == ""


def test_reindex_push_threads_the_hub_token(tmp_path, run_git, monkeypatch, git_kb):
    """Important 1 (mutant MU4): cli.reindex's push call site
    (gitio.push(handle.root, handle.token)) dropped the token with 87 tests
    still green -- the gitio-level push test supplies a token directly and
    cannot see this call site regress. Pre-seed a credentialed-hub-ref
    cache, the same trick test_publish.py's
    test_direct_publish_threads_the_hub_token_into_the_push uses."""
    import hashlib
    import time

    from center_kb import gitio

    origin = tmp_path / "hub-origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    seed = tmp_path / "hub-seed"
    (seed / ".kb").mkdir(parents=True)
    (seed / "federation").mkdir()
    (seed / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8", newline="\n")
    (seed / "federation" / ".gitkeep").write_text("", encoding="utf-8")
    run_git(tmp_path, "init", str(seed))
    run_git(seed, "add", "-A")
    run_git(seed, "commit", "-m", "hub v0")
    run_git(seed, "remote", "add", "origin", str(origin))
    run_git(seed, "push", "-u", "origin", "HEAD")

    fake_hub_ref = "https://x-access-token:ghs_REINDEXTOKEN@example.invalid/hub.git"
    stripped = "https://example.invalid/hub.git"
    cache_base = tmp_path / "cache"
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(cache_base))
    key = hashlib.sha1(stripped.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
    cache = cache_base / key
    cache_base.mkdir(parents=True, exist_ok=True)
    run_git(tmp_path, "clone", str(origin), str(cache))
    run_git(cache, "config", "core.autocrlf", "false")  # a "healthy" cache
    run_git(cache, "config", "user.name", "test")
    run_git(cache, "config", "user.email", "test@test.local")
    (cache_base / f"{key}.last-pull").write_text(str(time.time()), encoding="utf-8")

    calls: list[dict] = []
    real_run = gitio.subprocess.run

    def spy(cmd, **kwargs):
        calls.append({"argv": list(cmd), "env": kwargs.get("env")})
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(gitio.subprocess, "run", spy)

    # A fresh cache has no federation/index.yaml yet -- write_federation_index
    # creates it, so reindex has a real commit (and therefore a real push)
    # to make, no extra staging required.
    result = runner.invoke(
        app, ["reindex", "--hub", fake_hub_ref, "--kb-dir", str(git_kb["kb"])]
    )
    assert result.exit_code == 0, result.output

    push_calls = [
        c for c in calls
        if c["argv"][:2] == ["git", "push"] and "origin" in c["argv"] and "HEAD" in c["argv"]
    ]
    assert push_calls, "reindex never pushed"
    env = push_calls[0]["env"]
    assert env is not None, "the push carried no credential env at all"
    assert env["GIT_CONFIG_VALUE_0"].startswith("Authorization: Basic ")
    assert "ghs_REINDEXTOKEN" not in push_calls[0]["argv"]


def test_cli_publish_hub_kind_dispatches_federation(tmp_path, run_git, monkeypatch):
    from typer.testing import CliRunner

    from center_kb.cli import app
    from tests.conftest import make_fed_entry
    from tests.test_publish_hub import _git_repo

    mid = tmp_path / "mid"
    (mid / ".kb").mkdir(parents=True)
    make_fed_entry(mid / "federation", "repo-a", "doc-a")
    (mid / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    root_hub = tmp_path / "root-hub"
    (root_hub / ".kb").mkdir(parents=True)
    (root_hub / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    (root_hub / "federation").mkdir()
    (root_hub / "federation" / ".gitkeep").write_text("", encoding="utf-8")
    _git_repo(run_git, root_hub)
    (mid / ".kb" / "config.yaml").write_text(
        f"kind: hub\nrepo_id: mid\nhub: {root_hub}\n", encoding="utf-8"
    )
    _git_repo(run_git, mid)

    result = CliRunner().invoke(app, ["publish", "--kb-dir", str(mid / ".kb")])
    assert result.exit_code == 0, result.output
    assert (root_hub / "federation" / "mid" / "repo-a" / "index.yaml").exists()


def test_cli_publish_root_hub_without_upstream_errors(tmp_path, run_git):
    from typer.testing import CliRunner

    from center_kb.cli import app
    from tests.test_publish_hub import _git_repo

    root_hub = tmp_path / "root-hub"
    (root_hub / ".kb").mkdir(parents=True)
    (root_hub / ".kb" / "config.yaml").write_text("kind: hub\n", encoding="utf-8")
    (root_hub / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    (root_hub / "federation").mkdir()
    _git_repo(run_git, root_hub)

    result = CliRunner().invoke(app, ["publish", "--kb-dir", str(root_hub / ".kb")])
    assert result.exit_code == 1
    assert "root hub" in result.output


def test_doctor_hub_kind_without_self_entry_stays_green(tmp_path, run_git, monkeypatch):
    """Fix round 4: corrects fix round 1's Important-5 test, which was
    written from the same false premise as the plan's Step 5 ("a hub with
    no self-entry gets an accurate 'has not published' warning"). A
    self-hub (its own configured `hub:` resolves to itself) does not
    ordinarily publish itself into its own federation/<repo_id>/, so that
    warning is meaningless there -- a pre-existing test elsewhere
    (test_doctor_hubkind.py::test_cli_doctor_hub_kind_self_hub_no_false_
    warnings) already asserted it must not appear, and this test's old
    assertion (the warning MUST appear) contradicted it. check_hub now
    suppresses the warning specifically for the self-hub shape; still exit
    0 either way (never an error, never hub_stale)."""
    from tests.test_publish_hub import _git_repo

    hub = tmp_path / "hub"
    (hub / ".kb").mkdir(parents=True)
    (hub / ".kb" / "index.yaml").write_text(
        "docs: []\n", encoding="utf-8", newline="\n"
    )
    (hub / ".kb" / "config.yaml").write_text(
        "kind: hub\nrepo_id: hub-self\nhub: .\n", encoding="utf-8", newline="\n"
    )
    (hub / "federation").mkdir()
    from center_kb.federation import write_federation_index

    write_federation_index(hub / "federation")
    _git_repo(run_git, hub)

    # monkeypatch.chdir over bare os.chdir + try/finally (fix round 2, item
    # 3): this file already uses it (test_cli_publish_hub_kind_self_hub_dot_
    # from_other_cwd) alongside the older os.chdir pattern, and it restores
    # the cwd on pytest's own teardown -- no risk of leaking a wrong cwd into
    # a later test if something above raises.
    monkeypatch.chdir(hub)
    result = runner.invoke(app, ["doctor", "--kb-dir", str(hub / ".kb")])

    assert result.exit_code == 0, result.output
    assert "has not published to the hub yet" not in result.output, result.output


def test_doctor_hub_kind_self_entry_digest_compare_runs(tmp_path, run_git, monkeypatch):
    """Fix round 4: keeps coverage of the truthy-repo_id path's OTHER
    branch (entry.is_dir() True) -- a self-hub that HAS published its own
    .kb into federation/<repo_id>/ gets the same local-vs-published digest
    comparison a child gets (Task 6's actual point). Falsifiable by
    construction: tamper the LOCAL .kb after publish, without republishing
    -- a clean match alone would not distinguish "the comparison ran and
    passed" from "the comparison never ran", but a real drift warning can
    only appear if the comparison actually executed."""
    from tests.test_publish_hub import _git_repo

    hub = tmp_path / "hub"
    doc = hub / ".kb" / "own-doc"
    doc.mkdir(parents=True)
    (doc / "ch1.md").write_text("## 1.1 T\n\nBody.\n", encoding="utf-8", newline="\n")
    (doc / "ch1.raw.md").write_text(
        "## 1.1 T\n\nBody.\n", encoding="utf-8", newline="\n"
    )
    (doc / "_manifest.yaml").write_text(
        "id: own-doc\ntitle: own-doc\nsections:\n"
        "  - id: '1.1'\n    title: T\n    summary: s\n    status: summarized\n    file: ch1\n",
        encoding="utf-8",
        newline="\n",
    )
    (hub / ".kb" / "index.yaml").write_text(
        "docs:\n  - id: own-doc\n    title: own-doc\n    summary: d\n",
        encoding="utf-8",
        newline="\n",
    )
    (hub / "federation").mkdir()
    (hub / "federation" / ".gitkeep").write_text("", encoding="utf-8", newline="\n")
    (hub / ".kb" / "config.yaml").write_text(
        "kind: hub\nrepo_id: hub-self\nhub: .\n", encoding="utf-8", newline="\n"
    )
    _git_repo(run_git, hub)

    monkeypatch.chdir(hub)
    publish_result = runner.invoke(app, ["publish", "--kb-dir", str(hub / ".kb")])
    assert publish_result.exit_code == 0, publish_result.output
    assert (hub / "federation" / "hub-self" / "own-doc" / "_manifest.yaml").exists()

    # Tamper the LOCAL .kb only -- federation/hub-self/ still holds the
    # bytes kb publish just wrote there.
    (doc / "ch1.md").write_text(
        "## 1.1 T\n\nTAMPERED locally.\n", encoding="utf-8", newline="\n"
    )

    result = runner.invoke(app, ["doctor", "--kb-dir", str(hub / ".kb")])

    assert result.exit_code == 0, result.output
    assert "differs from the published snapshot" in result.output, result.output


def test_cli_publish_hub_kind_self_hub_publishes_own_kb(tmp_path, run_git):
    from typer.testing import CliRunner

    from center_kb.cli import app
    from tests.test_publish_hub import _git_repo

    hub = tmp_path / "hub"
    doc = hub / ".kb" / "own-doc"
    doc.mkdir(parents=True)
    (doc / "ch1.md").write_text("## 1.1 T\n\nBody.\n", encoding="utf-8")
    (doc / "ch1.raw.md").write_text("## 1.1 T\n\nBody.\n", encoding="utf-8")
    (doc / "_manifest.yaml").write_text(
        "id: own-doc\ntitle: own-doc\nsections:\n"
        "  - id: '1.1'\n    title: T\n    summary: s\n    status: summarized\n    file: ch1\n",
        encoding="utf-8",
    )
    (hub / ".kb" / "index.yaml").write_text(
        "docs:\n  - id: own-doc\n    title: own-doc\n    summary: d\n", encoding="utf-8"
    )
    (hub / "federation").mkdir()
    (hub / "federation" / ".gitkeep").write_text("", encoding="utf-8")
    (hub / ".kb" / "config.yaml").write_text(
        "kind: hub\nrepo_id: hub-self\nhub: .\n", encoding="utf-8"
    )
    _git_repo(run_git, hub)

    import os

    cwd = os.getcwd()
    os.chdir(hub)
    try:
        result = CliRunner().invoke(app, ["publish", "--kb-dir", str(hub / ".kb")])
    finally:
        os.chdir(cwd)
    assert result.exit_code == 0, result.output
    assert (hub / "federation" / "hub-self" / "own-doc" / "_manifest.yaml").exists()


def test_cli_publish_hub_kind_self_hub_dot_from_other_cwd(tmp_path, run_git, monkeypatch):
    from typer.testing import CliRunner

    from center_kb.cli import app
    from tests.test_publish_hub import _git_repo

    hub = tmp_path / "hub2"
    doc = hub / ".kb" / "own-doc"
    doc.mkdir(parents=True)
    (doc / "ch1.md").write_text("## 1.1 T\n\nBody.\n", encoding="utf-8")
    (doc / "ch1.raw.md").write_text("## 1.1 T\n\nBody.\n", encoding="utf-8")
    (doc / "_manifest.yaml").write_text(
        "id: own-doc\ntitle: own-doc\nsections:\n"
        "  - id: '1.1'\n    title: T\n    summary: s\n    status: summarized\n    file: ch1\n",
        encoding="utf-8",
    )
    (hub / ".kb" / "index.yaml").write_text(
        "docs:\n  - id: own-doc\n    title: own-doc\n    summary: d\n", encoding="utf-8"
    )
    (hub / "federation").mkdir()
    (hub / ".kb" / "config.yaml").write_text(
        "kind: hub\nrepo_id: hub2\nhub: .\n", encoding="utf-8"
    )
    _git_repo(run_git, hub)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    result = CliRunner().invoke(app, ["publish", "--kb-dir", str(hub / ".kb")])
    assert result.exit_code == 0, result.output
    assert (hub / "federation" / "hub2" / "own-doc" / "_manifest.yaml").exists()


def test_cli_publish_hub_kind_intake_without_direct_or_pr_errors(tmp_path, run_git):
    from typer.testing import CliRunner

    from center_kb.cli import app
    from tests.test_publish_hub import _git_repo

    root_hub = tmp_path / "root-hub-intake"
    (root_hub / ".kb").mkdir(parents=True)
    (root_hub / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    (root_hub / "federation").mkdir()
    (root_hub / "federation" / ".gitkeep").write_text("", encoding="utf-8")
    _git_repo(run_git, root_hub)

    mid = tmp_path / "mid-intake"
    (mid / ".kb").mkdir(parents=True)
    (mid / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    from tests.conftest import make_fed_entry

    make_fed_entry(mid / "federation", "repo-a", "doc-a")
    (mid / ".kb" / "config.yaml").write_text(
        f"kind: hub\nrepo_id: mid\nhub: {root_hub}\nintake: https://intake.example\n",
        encoding="utf-8",
    )
    _git_repo(run_git, mid)

    result = CliRunner().invoke(app, ["publish", "--kb-dir", str(mid / ".kb")])
    assert result.exit_code == 1, result.output
    assert "not supported" in result.output


def test_publish_cli_prints_gate_refusal_not_a_traceback(git_kb, hub_worktree, run_git):
    """F-D9 regression (task 5-6 fix round 1, item 1): pubgate.GateError must
    reach the user as a clean red line + exit 1 through the real CLI, not an
    uncaught traceback. cli.py did not import pubgate and did not catch
    GateError at any of the publish command's three call sites -- it caught
    only PublishError/GitError, so every gate refusal escaped as a Python
    traceback with empty CliRunner output."""
    import yaml

    fed = hub_worktree / "federation"
    (fed / "registry.yaml").write_text(
        yaml.safe_dump({"repos": {"org/victim": "victim"}}),
        encoding="utf-8",
        newline="\n",
    )
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "hub: register org/victim")

    run_git(git_kb["root"], "remote", "add", "origin", "https://github.com/org/attacker.git")

    result = runner.invoke(
        app,
        ["publish", "--repo-id", "victim", "--direct",
         "--hub", str(hub_worktree), "--kb-dir", str(git_kb["kb"])],
    )
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "registry" in result.output.lower()  # the message actually reached the user


def test_hub_to_hub_publish_gate_refusal_is_one_line_not_a_traceback(
    tmp_path, run_git, monkeypatch
):
    """Wave F fix round 2, item 3: the re-review measured that narrowing the
    hub-to-hub `except` tuple (cli.publish's `not is_self` branch) to
    `PublishError` alone still leaves the whole wave test set green --
    `test_cli_hub_to_hub_publish_error_is_one_line_not_a_traceback` (see
    test_publish_hub.py) drives a federation *cycle*, and both cycle sites
    raise PublishError, which the pre-round tuple already caught. The tuple's
    actual, still-uncovered gap is `pubgate.GateError`:
    `publish_federation` -> `pubgate.decide_mode` raises it when the upstream
    hub has a remote `gh` cannot open a PR against. Mutation-proven in this
    round: narrowing this branch's tuple back to `except
    (publish_mod.PublishError,)` turns this test red."""
    from center_kb import ghio
    from tests.conftest import make_fed_entry
    from tests.test_publish_hub import _git_repo

    root_hub = tmp_path / "root-hub"
    (root_hub / ".kb").mkdir(parents=True)
    (root_hub / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    (root_hub / "federation").mkdir()
    (root_hub / "federation" / ".gitkeep").write_text("", encoding="utf-8")
    _git_repo(run_git, root_hub)
    origin = tmp_path / "root-hub-origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    run_git(root_hub, "remote", "add", "origin", str(origin))
    run_git(root_hub, "push", "-u", "origin", "HEAD")

    mid = tmp_path / "mid"
    (mid / ".kb").mkdir(parents=True)
    (mid / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    make_fed_entry(mid / "federation", "repo-a", "doc-a")
    (mid / ".kb" / "config.yaml").write_text(
        f"kind: hub\nrepo_id: mid\nhub: {root_hub}\n", encoding="utf-8",
    )
    _git_repo(run_git, mid)

    # has_remote True (root_hub has origin) + can_pr False + mode "auto" (no
    # --pr/--direct passed) -> pubgate.decide_mode's final branch raises
    # GateError whose message says `gh` "cannot open a pull request".
    monkeypatch.setattr(ghio, "can_open_pr", lambda root: False)

    result = runner.invoke(app, ["publish", "--kb-dir", str(mid / ".kb")])
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "cannot open a pull request" in result.output


def test_publish_pr_and_direct_is_exit_1_not_the_stale_code(tmp_path):
    """M11: a CI script reading the README's 'exit 2 = citation stale' used
    to see a misconfigured publish as a stale citation. --pr/--direct are
    checked before any config is read, so no kb-dir setup is needed here."""
    result = runner.invoke(
        app,
        ["publish", "--kb-dir", str(tmp_path / ".kb"), "--pr", "--direct"],
    )
    assert result.exit_code == 1, result.output
