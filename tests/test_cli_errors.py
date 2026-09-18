from typer.testing import CliRunner

from center_kb.cli import app

runner = CliRunner()


def _invoke_publish(git_kb, hub, repo_id):
    return runner.invoke(
        app,
        ["publish", "--hub", str(hub), "--repo-id", repo_id,
         "--kb-dir", str(git_kb["kb"]), "--direct"],
    )


def _assert_no_propagated_exception(result) -> None:
    """Finding 3: under click 8.4.2 / typer 0.24.2, CliRunner(catch_exceptions=True)
    stores an uncaught exception in result.exception and prints NOTHING to
    result.output -- `"Traceback" not in result.output` is true whether or not
    the CLI actually caught anything, so it can never fail and proves nothing.
    A `typer.Exit`/`SystemExit` is the one exception CLI commands are expected
    to raise on purpose (see tests/test_cli_hub.py:303 for the same idiom)."""
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_over_long_repo_id_is_one_line_not_a_traceback(git_kb, hub_worktree):
    result = _invoke_publish(git_kb, hub_worktree, "x" * 300)
    assert result.exit_code == 1
    _assert_no_propagated_exception(result)
    assert "the limit is 64" in result.output


def test_reserved_device_name_is_one_line(git_kb, hub_worktree):
    result = _invoke_publish(git_kb, hub_worktree, "CON")
    assert result.exit_code == 1
    _assert_no_propagated_exception(result)
    # Finding 3: this test's only assertions used to be exit_code == 1 and the
    # tautology above -- it passed even when nothing was actually caught.
    assert "reserved Windows device name" in result.output


def test_a_failing_gh_pr_create_is_one_line(git_kb, hub_with_origin, monkeypatch):
    from center_kb import ghio

    monkeypatch.setattr(ghio, "can_open_pr", lambda root: True)
    monkeypatch.setattr(ghio, "pr_url_for_branch", lambda root, branch: "")

    def _boom(root, branch, title, body):
        raise ghio.GHError("gh pr create failed: HTTP 404")

    monkeypatch.setattr(ghio, "create_pr", _boom)
    result = runner.invoke(
        app,
        ["publish", "--hub", str(hub_with_origin), "--repo-id", "demo-kb",
         "--kb-dir", str(git_kb["kb"]), "--pr"],
    )
    assert result.exit_code == 1
    _assert_no_propagated_exception(result)
    assert "gh pr create failed" in result.output


def test_unreadable_registry_is_one_line(git_kb, hub_worktree, run_git):
    fed = hub_worktree / "federation"
    fed.mkdir(exist_ok=True)
    (fed / "registry.yaml").write_text("repos: [broken\n", encoding="utf-8")
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "hub: broken registry")
    result = _invoke_publish(git_kb, hub_worktree, "demo-kb")
    assert result.exit_code == 1
    _assert_no_propagated_exception(result)
    assert "registry.yaml is invalid" in result.output


def test_corrupt_index_yaml_is_one_line(git_kb, hub_worktree):
    """F-D9 finding 2: models.load_yaml_model's yaml.safe_load raises
    yaml.YAMLError on malformed YAML -- _snapshot reads .kb/index.yaml with
    no try/except of its own, so this used to reach the interpreter as a raw
    ParserError traceback."""
    (git_kb["kb"] / "index.yaml").write_text("docs: [broken\n", encoding="utf-8")
    result = _invoke_publish(git_kb, hub_worktree, "demo-kb")
    assert result.exit_code == 1
    _assert_no_propagated_exception(result)
    assert "index.yaml" in result.output


def test_schema_invalid_index_yaml_is_one_line(git_kb, hub_worktree):
    """F-D9 finding 2: valid YAML, wrong schema (docs must be a list) --
    model_validate raises pydantic.ValidationError."""
    (git_kb["kb"] / "index.yaml").write_text('docs: "not-a-list"\n', encoding="utf-8")
    result = _invoke_publish(git_kb, hub_worktree, "demo-kb")
    assert result.exit_code == 1
    _assert_no_propagated_exception(result)
    assert "index.yaml" in result.output


def test_non_utf8_index_yaml_is_one_line(git_kb, hub_worktree):
    """F-D9 finding 2: path.read_text(encoding="utf-8") raises
    UnicodeDecodeError -- a ValueError, NOT an OSError, so an except OSError
    arm alone does not catch it."""
    (git_kb["kb"] / "index.yaml").write_bytes(b"docs:\n- id: \xff\xfe bad bytes\n")
    result = _invoke_publish(git_kb, hub_worktree, "demo-kb")
    assert result.exit_code == 1
    _assert_no_propagated_exception(result)
    assert "index.yaml" in result.output


def test_corrupt_config_yaml_is_one_line(git_kb, hub_worktree):
    """F-D9 finding 2: `cfg = load_config(kb_dir)` used to sit outside any
    try/except at the top of cli.publish() -- a corrupt .kb/config.yaml
    escaped before the command did anything else."""
    (git_kb["kb"] / "config.yaml").write_text("hub: [broken\n", encoding="utf-8")
    result = _invoke_publish(git_kb, hub_worktree, "demo-kb")
    assert result.exit_code == 1
    _assert_no_propagated_exception(result)
    assert "config.yaml" in result.output


def test_reindex_read_only_index_yaml_is_one_line_not_a_traceback(fed_hub, git_kb):
    """F-D9 finding 6: reindex's first try/except (gitio.GitError, OSError)
    had no coverage -- reverting it still passed the 48-test wave set, even
    though it is genuinely reachable: a read-only federation/index.yaml
    makes models.save_yaml_model's path.write_text raise PermissionError."""
    import os
    import stat

    index_path = fed_hub / "federation" / "index.yaml"
    os.chmod(index_path, stat.S_IREAD)
    try:
        result = runner.invoke(
            app, ["reindex", "--hub", str(fed_hub), "--kb-dir", str(git_kb["kb"])]
        )
        assert result.exit_code == 1
        _assert_no_propagated_exception(result)
        assert "reindex failed" in result.output
        # N-2 (Wave G fix round 4 re-review, review-waveG-fix3-verdict.md):
        # this exercises the FIRST OSError arm (write_federation_index /
        # commit_paths, cli.py:~1810) -- Minor 1 pinned the way-forward
        # clause on the sibling arm below (searchdb.sync) but left this one
        # unasserted, so replacing the whole message here would still pass.
        # Same one-line fix as Minor 1: pin the clause itself.
        assert "check file permissions under the hub and retry" in result.output
    finally:
        os.chmod(index_path, stat.S_IWRITE | stat.S_IREAD)


def test_reindex_searchdb_permission_error_is_one_line_not_a_traceback(
    fed_hub, git_kb, monkeypatch
):
    """Section 6 (CRITICAL, routed): reindex's SECOND try/except (guarding
    searchdb.sync) had no OSError arm -- its sibling arm above (the
    write_federation_index/commit_paths block) already has one, added by an
    earlier round; this one was missed. Measured by the re-reviewer: a
    locked file under the hub raised PermissionError here with nothing to
    catch it -- exit 1, but no message printed at all. reindex is one of the
    three commands the spec names by name for "no traceback reaches a
    user"."""
    from center_kb import searchdb as searchdb_mod

    def boom(handle, embedder):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(searchdb_mod, "sync", boom)
    result = runner.invoke(
        app, ["reindex", "--hub", str(fed_hub), "--kb-dir", str(git_kb["kb"])]
    )
    assert result.exit_code == 1
    _assert_no_propagated_exception(result)
    assert "reindex failed" in result.output
    assert "search index" in result.output
    # Minor 1 (Wave G fix round 2 re-review): the two assertions above
    # identify the failure but assert nothing about a way forward -- the
    # spec's requirement is "names the way forward", not just "names the
    # failure". Pin the clause itself, the way item 3's locked-cache test
    # already does with "delete" in result.output.
    assert "check file permissions under the hub and retry" in result.output


def test_reindex_on_an_untracked_federation_dir_does_not_false_flag(
    git_kb, run_git, tmp_path
):
    """F-D9 finding 7 bullet 4: with default -unormal, an entirely-untracked
    federation/ (nothing under it ever committed) collapses to one
    "?? federation/" porcelain line, so the strays check flagged the whole
    directory even though the commit right after this correctly captured
    index.yaml -- the only file that existed. --untracked-files=all lists
    the file individually instead."""
    hub = tmp_path / "fresh-hub"
    (hub / ".kb").mkdir(parents=True)
    (hub / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    run_git(hub, "init")
    run_git(hub, "config", "user.name", "test")
    run_git(hub, "config", "user.email", "test@test.local")
    run_git(hub, "add", "-A")
    run_git(hub, "commit", "-m", "hub v1 -- no federation/ yet")
    (hub / "federation").mkdir()  # exists on disk, never `git add`ed

    result = runner.invoke(
        app, ["reindex", "--hub", str(hub), "--kb-dir", str(git_kb["kb"])]
    )
    assert result.exit_code == 0
    assert "was NOT committed by reindex" not in result.output


def test_assets_verify_corrupt_only_report_exits_nonzero_and_names_the_asset(
    hub_worktree,
):
    """I1: `kb assets verify` used to print nothing and still exit 1 when the
    only finding was a corrupt asset -- cli.py rendered missing_records,
    dangling_refs and orphans, but not the newer VerifyReport.corrupt, even
    though VerifyReport.ok already treats a corrupt-only report as failing.
    The asset is referenced from the doc's markdown (and not orphaned) so the
    corrupt finding is the ONLY thing wrong with this report -- proving the
    name shows up because of the [corrupt] line, not the [orphan] one."""
    import hashlib

    from center_kb import assetstore, models
    from tests.conftest import make_fed_entry

    data = b"real image bytes"
    name = hashlib.sha256(data).hexdigest() + ".png"
    fed = hub_worktree / "federation"
    entry = make_fed_entry(fed, "child", "doc", l2=f"![x](assets/{name})\n")
    assets_dir = entry / "doc" / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / name).write_bytes(b"tampered")  # exists on disk, wrong hash
    models.save_yaml_model(
        entry / assetstore.RECORD_NAME,
        models.AssetsRecord(assets=[f"doc/assets/{name}"]),
    )
    result = runner.invoke(
        app,
        ["assets", "verify", "--hub", str(hub_worktree),
         "--kb-dir", str(hub_worktree / ".kb")],
    )
    assert result.exit_code == 1
    assert name in result.output
    assert "[corrupt]" in result.output
    assert "[orphan]" not in result.output
    assert "[missing]" not in result.output


# --- Wave F fix round 2, item 1 (CRITICAL): round 1's own
# publish._load_manifest_or_raise wraps a corrupt/schema-invalid/non-UTF-8
# <doc>/_manifest.yaml into PublishError, but the *_CONFIG_READ_ERRORS,
# OSError guard around _apply_unreviewed_gate(...) in cli.publish, and the
# (cipublish.CIPublishError, gitio.GitError, OSError, *_CONFIG_READ_ERRORS)
# tuple in cli.ci_publish, did not include it -- PublishError is a
# RuntimeError, not a ValueError, so it escaped both commands as a raw
# traceback with empty CliRunner output. Fixed by giving PublishError (and
# GateError, CIPublishError, assetstore.AssetStoreError) a shared base,
# center_kb.errors.KbError, and catching that base at every guard instead of
# re-enumerating siblings one at a time.


def test_corrupt_doc_manifest_via_publish_is_one_line_not_a_traceback(git_kb, hub_worktree):
    (git_kb["kb"] / "demo-doc" / "_manifest.yaml").write_text(
        "id: [broken\n", encoding="utf-8"
    )
    result = _invoke_publish(git_kb, hub_worktree, "demo-kb")
    assert result.exit_code == 1
    _assert_no_propagated_exception(result)
    assert "_manifest.yaml" in result.output


def test_corrupt_doc_manifest_via_ci_publish_is_one_line_not_a_traceback(git_kb):
    (git_kb["kb"] / "demo-doc" / "_manifest.yaml").write_text(
        "id: [broken\n", encoding="utf-8"
    )
    result = runner.invoke(
        app,
        ["ci-publish", "--repo-id", "demo-kb", "--kb-dir", str(git_kb["kb"]),
         "--intake", "https://intake.example"],
    )
    assert result.exit_code == 1
    _assert_no_propagated_exception(result)
    assert "_manifest.yaml" in result.output


def test_reindex_names_an_unreadable_manifest_while_syncing(fed_hub, fixture_kb):
    """Wave F fix round 2, item 4 (second target): reindex's second
    try/except -- the `_CONFIG_READ_ERRORS` arm wrapped around
    `searchdb.sync` -- survived the whole 203-test wave set with no test of
    its own (re-review I3). `searchdb._sync_repo` reads each referenced
    doc's `_manifest.yaml` via `models.load_yaml_model` directly, unwrapped
    (unlike `federation.load_federation`, which skips a broken entry with a
    warning instead of raising) -- so a corrupt manifest here is genuinely
    reachable, not belt-and-suspenders. Also doubles as this round's
    per-command corrupt-manifest coverage for `reindex` (item 1): reindex has
    no `unreviewed_gate` call, so this is a different escape route than
    publish/ci-publish's PublishError wrap -- a raw yaml.YAMLError here,
    already in `_CONFIG_READ_ERRORS`."""
    manifest_path = fed_hub / "federation" / "icao-kb" / "icao-annex-2" / "_manifest.yaml"
    manifest_path.write_text("id: [broken\n", encoding="utf-8")
    result = runner.invoke(
        app, ["reindex", "--hub", str(fed_hub), "--kb-dir", str(fixture_kb)]
    )
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "fix or re-ingest that document" in result.output


def test_reindex_names_a_non_ascii_stray_as_utf8(fed_hub, fixture_kb):
    """Wave F fix round 1's finding 7 bullet 3 (`-c core.quotePath=false` on
    reindex's `dirty_before` status check) shipped with no test -- of round
    1's three untested Minor bullets, the re-review judged this the one not
    acceptable to ship untested: eight lines, load-bearing. A real hub with
    an untracked non-ASCII federation/ stray prints the UTF-8 name today;
    reverted (quotePath left at its git default), the same probe degrades to
    C-quoted octal escapes (measured: `\\303\\272` for the two-byte utf-8
    encoding of 'ú')."""
    (fed_hub / "federation" / "ghi-chú.md").write_text("stray\n", encoding="utf-8")
    result = runner.invoke(
        app, ["reindex", "--hub", str(fed_hub), "--kb-dir", str(fixture_kb)]
    )
    assert result.exit_code == 0
    assert "ghi-chú.md" in result.output
    assert "\\303" not in result.output


def test_asset_store_outage_via_publish_is_one_line_not_a_traceback(
    git_kb, hub_worktree, monkeypatch
):
    """Wave F fix round 2, item 4 (first target): round 1 added
    `assetstore.AssetStoreError` to cli.publish's plain-publish `except`
    tuple with no test -- re-review I3 measured that deleting the whole
    addition still left the 203-test wave set green, and confirmed
    (probe P-A) that with it deleted a store outage driven through
    `kb publish --direct` genuinely propagates as a raw traceback."""
    import hashlib

    from center_kb import assetstore

    data = b"asset bytes for the outage test"
    name = hashlib.sha256(data).hexdigest() + ".png"
    assets_dir = git_kb["kb"] / "demo-doc" / "assets"
    assets_dir.mkdir()
    (assets_dir / name).write_bytes(data)

    class _FailingStore(assetstore.MemoryStore):
        def put(self, name, data):
            raise assetstore.AssetStoreError("bucket down")

    monkeypatch.setattr(assetstore, "store_for_hub", lambda handle: _FailingStore())

    result = _invoke_publish(git_kb, hub_worktree, "demo-kb")
    assert result.exit_code == 1
    _assert_no_propagated_exception(result)
    assert "bucket down" in result.output


def test_locked_hub_cache_discard_is_one_line_not_a_traceback(
    git_kb, tmp_path, run_git, monkeypatch, undiscardable_hub_cache
):
    """Important 3: `kb publish` used to print a bare [WinError 32] naming
    no way forward when a legacy cache's discard hit an open file handle
    (the common Windows cause -- a `kb query`/MCP/web process still has
    .kb-work/search.sqlite3 open). hub._discard_cache now wraps that OSError
    into gitio.GitError with a message naming the cache and the fix --
    already caught by this command's except tuple (gitio.GitError, OSError
    are both already in it), so no cli.py change was needed, only a better
    message at the source.

    Ruling P49 (round 5): the undiscardable-cache recipe is the shared
    `undiscardable_hub_cache` fixture, so this runs on Linux too. See
    tests/conftest.py."""
    from center_kb import hub as hub_mod

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

    cache_base = tmp_path / "cache"
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(cache_base))
    key = hub_mod.cache_key(str(origin))
    legacy = cache_base / key
    run_git(tmp_path, "clone", str(origin), str(legacy))
    run_git(legacy, "config", "core.autocrlf", "true")  # legacy -- needs re-clone

    with undiscardable_hub_cache(legacy):
        result = _invoke_publish(git_kb, origin, "demo-kb")
        assert result.exit_code == 1
        _assert_no_propagated_exception(result)
        assert str(legacy) in result.output
        assert "delete" in result.output


def test_doctor_locked_hub_cache_discard_is_one_line_not_a_traceback(
    git_kb, tmp_path, run_git, monkeypatch, undiscardable_hub_cache
):
    """cli._hub_or_exit (Wave G fix round 4, release review 2026-09-11):
    the last unguarded resolve_hub call site -- `_hub_or_exit` (used by 11
    commands including `doctor`) called resolve_hub with no try/except, so
    a locked hub cache made `kb doctor` print a raw traceback. This
    matters beyond the bug: the 0.21.0 CHANGELOG claims "kb publish, kb
    ci-publish and kb doctor print one line and exit 1 on a refusal
    instead of a traceback" -- `doctor` is named there and was not yet
    true. Same locked-cache recipe as
    test_locked_hub_cache_discard_is_one_line_not_a_traceback (kb publish's
    sibling, above) and test_hub.test_discard_cache_failure_names_the_cache_
    and_the_fix -- `_discard_cache`'s own GitError message (names the
    cache, says it is disposable, tells the operator to delete it) must
    reach the terminal unwrapped, the same shape as reindex's
    `except gitio.GitError as exc: typer.secho(str(exc), ...)`.

    Ruling P49 (round 5): round 4 shipped this test with no guard at all and
    the re-review measured it as a hard failure on the three ubuntu legs of
    _gate.yml T1 (`assert str(legacy) in result.output` at what was then
    line 445). It now uses the shared `undiscardable_hub_cache` fixture and
    really runs there. See tests/conftest.py."""
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

    from center_kb import hub as hub_mod

    cache_base = tmp_path / "doctor-cache"
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(cache_base))
    key = hub_mod.cache_key(str(origin))
    legacy = cache_base / key
    run_git(tmp_path, "clone", str(origin), str(legacy))
    run_git(legacy, "config", "core.autocrlf", "true")  # legacy -- needs re-clone

    with undiscardable_hub_cache(legacy):
        result = runner.invoke(
            app, ["doctor", "--hub", str(origin), "--kb-dir", str(git_kb["kb"])]
        )
        assert result.exit_code == 1
        _assert_no_propagated_exception(result)
        assert str(legacy) in result.output
        assert "delete" in result.output


def test_asset_store_outage_via_hub_to_hub_publish_is_one_line_not_a_traceback(
    tmp_path, run_git, monkeypatch
):
    """Section 8 (IMPORTANT, routed): cli.publish's hub-to-hub `except`
    tuple catches assetstore.AssetStoreError only via the shared KbError
    base -- re-enumerating that tuple without it left 181 passed, 0 failed,
    because nothing drove a real store outage through THIS branch
    specifically (test_asset_store_outage_via_publish_is_one_line_not_a_traceback
    above covers only the plain-publish tuple; Wave F fix round 2's own
    report flagged this exact gap and left it for the coordinator to route).
    Mirrors that test's shape, driven through the CLI's hub-to-hub dispatch
    (a hub-kind repo whose `hub:` config points at another hub) instead."""
    import hashlib

    from center_kb import assetstore
    from tests.conftest import make_fed_entry
    from tests.test_publish_hub import _git_repo

    data = b"asset bytes for the hub-to-hub outage test"
    name = hashlib.sha256(data).hexdigest() + ".png"

    mid = tmp_path / "mid"
    (mid / ".kb").mkdir(parents=True)
    (mid / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    entry = make_fed_entry(mid / "federation", "repo-a", "doc-a")
    assets_dir = entry / "doc-a" / "assets"
    assets_dir.mkdir()
    (assets_dir / name).write_bytes(data)

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

    class _FailingStore(assetstore.MemoryStore):
        def put(self, name, data):
            raise assetstore.AssetStoreError("bucket down")

    monkeypatch.setattr(assetstore, "store_for_hub", lambda handle: _FailingStore())

    result = runner.invoke(app, ["publish", "--kb-dir", str(mid / ".kb")])
    assert result.exit_code == 1
    _assert_no_propagated_exception(result)
    assert "bucket down" in result.output


def test_every_cli_terminal_exception_joins_kb_error_or_is_allowlisted():
    """Wave G fix round 2, item 7(c): the hardcoded four-class tuple this
    test used to walk could never see a fifth sibling that forgets to join
    the family -- a re-reviewer proved it by adding a real
    ManifestBoundsError(RuntimeError), raised from unreviewed_sections on
    the live `kb publish` path: the full suite stayed at 2614 passed, 6
    skipped, 0 failed, and the CLI probe gave `exit=1
    exception=ManifestBoundsError output=''` -- the exact F-D9 traceback
    signature the whole family exists to prevent.

    Discover every exception class center_kb actually defines instead
    (pkgutil.walk_packages -- the same technique the re-reviewer prototyped)
    and require each one to either derive from KbError or be named below
    with a reason. Scoped to Exception, not RuntimeError: CodeIngestError,
    RunnerError, AmbiguousDocError and SvcNoteError are CLI-terminal but sit
    outside the RuntimeError family entirely -- a RuntimeError-scoped walk
    would reproduce the exact blind spot this test exists to close, one
    family over.
    """
    import importlib
    import inspect
    import pkgutil
    import sys

    import center_kb
    from center_kb.errors import KbError

    # Important 4 (Wave G fix round 2 re-review): replacing the old
    # hardcoded four-class test deleted the only assertion that pinned
    # `KbError(RuntimeError)` -- the whole suite (2682 tests) stays green
    # if KbError's base is flipped to plain Exception, even though
    # errors.py's own module docstring still promises "deriving from
    # RuntimeError ... keeps every existing except RuntimeError working
    # unchanged", and cli.py:458's `except (ValueError, RuntimeError)`
    # around run_ingest depends on exactly that. Make the promise
    # structural again.
    assert issubclass(KbError, RuntimeError)

    walked = 0
    for m in pkgutil.walk_packages(center_kb.__path__, prefix="center_kb."):
        importlib.import_module(m.name)  # zero ImportErrors expected -- 76 modules
        walked += 1
    # Minor 5 (Wave G fix round 2 re-review): this must run BEFORE the
    # ALLOWLIST resolution below, not after `checked` -- a fully neutered
    # walk (`for m in []: ...`) makes `sys.modules[mod_name]` raise
    # KeyError at the very next line for whichever ALLOWLIST'd module
    # nobody else happened to import first, which pre-empts any assertion
    # placed later in this function. Checking `walked` here is what
    # actually, deterministically guards against a broken walk silently
    # checking nothing -- not an assertion on `checked` a dozen lines down.
    #
    # Minor 2 (Wave G fix round 4 re-review): the round-4 version of this
    # comment claimed both that `checked >= 27` "WOULD have caught a dead
    # walk in every context measured" and that it "was unreachable". At
    # most one of those can be true. Re-measured for round 5 -- neutered
    # walk (`for m in []`), this `walked` assertion disabled, and ALLOWLIST
    # entries whose module is absent skipped rather than resolved:
    #
    #   context                          checked   ALLOWLIST modules absent
    #   this test alone                        1                         14
    #   tests/test_cli_errors.py alone         1                         14
    #   whole-suite collection                25                          0
    #   whole-suite, healthy walk             27                          0
    #
    # Both halves were wrong, in different contexts. Under a whole-suite
    # run -- the CI context, and the only one that decides whether CI would
    # have caught it -- no ALLOWLIST module is absent, the KeyError never
    # fires, `assert checked >= 27` IS reached, and it fails (25 < 27): it
    # would have caught a dead walk there. The KeyError pre-empts it only
    # in an isolated or single-file run. (That isolated number is an
    # artefact of HOW the KeyError is suppressed: a harness that IMPORTS
    # the absent modules instead of skipping them measures 20, because the
    # resolution itself does the importing that a dead walk skipped. The
    # whole-suite numbers are harness-independent, which is why they are
    # the ones quoted above for reachability.)
    #
    # `checked >= 27`'s real weakness is its detection margin -- 2 (27
    # healthy against 25 under a dead walk), not the 0 the round-4 wording
    # implied by comparing 27 healthy with the 27 threshold. `walked >= 70`
    # against a measured population of 76 modules with zero ImportErrors is
    # unconditional and context-free, which is why it is the assertion
    # actually doing the job.
    assert walked >= 70

    # Every class that stays OUT of the family, with the reason. Minor 4
    # (Wave G fix round 4, review-waveG-fix3-verdict.md): matching used to
    # be transitive (`issubclass(cls, allowed)`), so a NEW subclass of an
    # allowlisted class -- one nobody had reviewed or written a reason for
    # -- was silently exempt too (measured: a bare
    # `class ProbeSubGitError(gitio.GitError): pass` survives under that
    # matching). Exact-identity matching below closes that: every class
    # that stays out now needs its own entry, reason included. The two
    # kbcontext subclasses that used to ride the transitive exemption are
    # named explicitly instead.
    ALLOWLIST: dict[str, str] = {
        "center_kb.gitio.GitError": (
            "ruling: handling is deliberately site-specific -- swallowed in "
            "hub.resolve_hub/publish._publish_direct, re-wrapped in "
            "cli.reindex"
        ),
        "center_kb.federation.RegistryError": (
            "ruling: not CLI-reachable -- converted to a message/response at "
            "both callers, fail-closed by design"
        ),
        "center_kb.ghapp.GHAppError": "ruling: server-side only (GitHub App auth)",
        "center_kb.intake.IntakeError": (
            "ruling: server-side only -- carries (status, detail) and maps "
            "to an HTTP response, not a CLI one-liner; folding it in would "
            "make a CLI guard claim a contract it does not have"
        ),
        "center_kb.web.api.SnapshotCorruptError": (
            "ruling: server-side only (M8) -- raised inside Starlette "
            "endpoint handlers (api.py's doc_detail/section/api_search) and "
            "consumed by app.py's exception_handlers entry, which maps it "
            "to a 503 JSON body or the error-page shell; never reaches "
            "cli.py, same shape as intake.IntakeError above"
        ),
        "center_kb.searchdb.IndexBusyError": (
            "ruling: transient and deliberately swallowed in "
            "publish._publish_direct -- joining would invite a guard to "
            "turn a retryable condition into a terminal refusal"
        ),
        "center_kb.codeingest.core.CodeIngestError": (
            "not a RuntimeError (Exception) -- outside KbError's "
            "inheritance shape"
        ),
        "center_kb.llm.RunnerError": (
            "not a RuntimeError (Exception) -- outside KbError's "
            "inheritance shape"
        ),
        "center_kb.query.AmbiguousDocError": (
            "not a RuntimeError (LookupError) -- outside KbError's "
            "inheritance shape"
        ),
        "center_kb.svcnote.SvcNoteError": (
            "not a RuntimeError (Exception) -- outside KbError's "
            "inheritance shape"
        ),
        "center_kb.kbcontext.KBContextError": (
            "not a RuntimeError (ValueError) -- doctor.check_context and "
            "resolve_refs convert it themselves"
        ),
        "center_kb.kbcontext.KBRefNotFoundError": (
            "subclass of KBContextError above -- same call sites convert "
            "it the same way, named explicitly rather than covered by "
            "transitive issubclass matching (Minor 4)"
        ),
        "center_kb.kbcontext.UnknownTagError": (
            "subclass of KBContextError above -- same call sites convert "
            "it the same way, named explicitly rather than covered by "
            "transitive issubclass matching (Minor 4)"
        ),
        "center_kb.query.InvalidLevelError": (
            "not a RuntimeError (ValueError) -- outside KbError's "
            "inheritance shape"
        ),
        "center_kb.searchdb.TooManyTagsError": (
            "not a RuntimeError (ValueError) -- outside KbError's "
            "inheritance shape"
        ),
    }
    allowed_classes = set()
    for qualname in ALLOWLIST:
        mod_name, _, cls_name = qualname.rpartition(".")
        allowed_classes.add(getattr(sys.modules[mod_name], cls_name))

    checked = 0
    for name, mod in list(sys.modules.items()):
        if not name.startswith("center_kb"):
            continue
        for cname, cls in vars(mod).items():
            if not (inspect.isclass(cls) and issubclass(cls, Exception)):
                continue
            if cls.__module__ != mod.__name__:
                continue  # imported into this module's namespace, not defined here
            checked += 1
            if issubclass(cls, KbError):
                continue
            # Minor 4: exact-identity, not issubclass -- a subclass of an
            # allowlisted class is NOT silently covered by its parent's
            # entry; it must be named in ALLOWLIST itself, with its own
            # reason (see the two kbcontext entries above).
            if cls in allowed_classes:
                continue
            raise AssertionError(
                f"{cls.__module__}.{cls.__qualname__} is a new center_kb "
                "exception class that is neither a KbError subclass nor "
                "allowlisted with a reason -- a CLI command that catches "
                "KbError will let this one traceback to the user (the F-D9 "
                "failure mode). Either derive it from KbError, or add it to "
                "ALLOWLIST above with a one-line reason."
            )
    # Sanity: the sweep actually found the known population of exception
    # classes (27 at the time this test was written). NOT a guard against a
    # broken walk (see the `walked` assertion above, which is) -- this one
    # just confirms the class-sweep loop itself iterated a realistic number
    # of candidates.
    assert checked >= 27
