from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

import pytest

from strata_kb import assetcmd, assetstore, gitio, models
from strata_kb.federation import FederationMeta
from strata_kb.hub import HubHandle

DATA = b"MIGRATEME"
SHA = hashlib.sha256(DATA).hexdigest()

DATA_A = b"MIGRATEME-A"
SHA_A = hashlib.sha256(DATA_A).hexdigest()
DATA_B = b"MIGRATEME-B"
SHA_B = hashlib.sha256(DATA_B).hexdigest()


def _seed_rid_entry(root: Path, repo_id: str) -> None:
    """Write _meta.yaml + index.yaml so `federation/<repo_id>` is a leaf
    entry per federation.iter_entry_dirs — the asset test fixtures predate
    the nested-entry mirror layout and need this to be discovered."""
    entry = root / "federation" / repo_id
    models.save_yaml_model(
        entry / "_meta.yaml",
        FederationMeta(repo_id=repo_id, source_commit="abc1234"),
    )
    models.save_yaml_model(entry / "index.yaml", models.KBIndex())


@pytest.fixture
def hub_root(tmp_path, run_git) -> Path:
    root = tmp_path / "hub"
    assets = root / "federation" / "rid-a" / "doc1" / "assets"
    assets.mkdir(parents=True)
    (assets / f"{SHA}.png").write_bytes(DATA)
    (root / "federation" / "rid-a" / "doc1" / "ch1.md").write_text(
        f"![x](assets/{SHA}.png)\n", encoding="utf-8"
    )
    _seed_rid_entry(root, "rid-a")
    (root / ".kb").mkdir()
    (root / ".kb" / "config.yaml").write_text(
        "kind: hub\nasset_store:\n  mode: s3\n  bucket: b\n", encoding="utf-8"
    )
    run_git(root, "init")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "seed")
    return root


@pytest.fixture
def hub_root_two_assets(tmp_path, run_git) -> Path:
    """Same shape as hub_root, but rid-a/doc1/assets/ carries TWO assets.

    A single-asset fixture makes the failure-restore path vacuous: divert
    uploads-before-unlinks, so a store that fails on the very first put()
    never gets to unlink anything — the except-block restore then runs
    against an already-pristine tree and passes even if deleted outright.
    With two assets, a store that succeeds on the first put() and fails on
    the second lets the first asset actually get uploaded+unlinked before
    the exception — giving the restore real work to undo.
    """
    root = tmp_path / "hub"
    assets = root / "federation" / "rid-a" / "doc1" / "assets"
    assets.mkdir(parents=True)
    (assets / f"{SHA_A}.png").write_bytes(DATA_A)
    (assets / f"{SHA_B}.png").write_bytes(DATA_B)
    (root / "federation" / "rid-a" / "doc1" / "ch1.md").write_text(
        f"![a](assets/{SHA_A}.png)\n![b](assets/{SHA_B}.png)\n", encoding="utf-8"
    )
    _seed_rid_entry(root, "rid-a")
    (root / ".kb").mkdir()
    (root / ".kb" / "config.yaml").write_text(
        "kind: hub\nasset_store:\n  mode: s3\n  bucket: b\n", encoding="utf-8"
    )
    run_git(root, "init")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "seed")
    return root


def test_migrate_uploads_strips_records_commits(hub_root):
    store = assetstore.MemoryStore()
    report = assetcmd.migrate_assets(HubHandle(root=hub_root), store=store)
    assert report.per_rid == {"rid-a": 1}
    assert report.committed
    assert store.get(f"{SHA}.png") == DATA
    dest = hub_root / "federation" / "rid-a"
    assert not (dest / "doc1" / "assets" / f"{SHA}.png").exists()
    rec = models.load_yaml_model(dest / "_assets.yaml", models.AssetsRecord)
    assert rec.assets == [f"doc1/assets/{SHA}.png"]
    tracked = gitio._run(hub_root, "ls-files", "--", "federation").stdout
    assert f"{SHA}.png" not in tracked and "_assets.yaml" in tracked
    status = gitio._run(hub_root, "status", "--porcelain").stdout.strip()
    assert status == ""  # everything committed


def test_migrate_second_run_noop(hub_root):
    store = assetstore.MemoryStore()
    assetcmd.migrate_assets(HubHandle(root=hub_root), store=store)
    report = assetcmd.migrate_assets(HubHandle(root=hub_root), store=store)
    assert report.per_rid == {} or all(n == 0 for n in report.per_rid.values())
    assert not report.committed


def test_migrate_rerun_over_unreadable_record_aborts_without_deleting(
    hub_root, monkeypatch
):
    """P32, measured (this round's report): migrate is documented
    idempotent and expected to be re-run. On a re-run every entry has
    nothing left to divert (diverted == []) -- before this fix, an
    unreadable committed record self-healed to the same "empty" inside
    divert_and_record's merge, and the record was unlinked while the
    store still held the only copy of what it named. This must now abort
    loudly instead, leaving the committed record byte-identical on disk."""
    store = assetstore.MemoryStore()
    assetcmd.migrate_assets(HubHandle(root=hub_root), store=store)
    record_path = hub_root / "federation" / "rid-a" / assetstore.RECORD_NAME
    before = record_path.read_bytes()
    assert before  # sanity: a real, non-empty committed record

    def _flaky_load(path, model):
        raise PermissionError(f"permission denied: {path}")

    monkeypatch.setattr(models, "load_yaml_model", _flaky_load)

    with pytest.raises(assetstore.AssetStoreError, match=re.escape(str(record_path))):
        assetcmd.migrate_assets(HubHandle(root=hub_root), store=store)

    monkeypatch.undo()
    # bytes on disk: untouched, not deleted
    assert record_path.exists()
    assert record_path.read_bytes() == before
    # git porcelain: nothing staged, nothing left dirty by the abort
    status = gitio._run(hub_root, "status", "--porcelain").stdout.strip()
    assert status == ""


def test_migrate_rerun_over_zero_byte_record_aborts_without_deleting(
    hub_root, run_git
):
    """Critical 1 (wave I-1 round 2, P47): a zero-byte record is present,
    readable and PARSES -- models.load_yaml_model is `yaml.safe_load(...)
    or {}`, so b"" reads back as a *successful* empty AssetsRecord, not a
    failure the OSError/YAMLError guard above catches. No monkeypatch:
    this is the shape shipped code produces on its own --
    models.save_yaml_model truncates before writing (no
    temp-file-and-rename), so an interrupted publish leaves exactly this
    file, committed as-is. Same measured signature as the unreadable-record
    test above: before the fix, the re-run's empty merge unlinked the
    record while the store still held the only copy of what it named."""
    store = assetstore.MemoryStore()
    assetcmd.migrate_assets(HubHandle(root=hub_root), store=store)
    record_path = hub_root / "federation" / "rid-a" / assetstore.RECORD_NAME
    before = record_path.read_bytes()
    assert before  # sanity: a real, non-empty committed record

    # simulate an interrupted publish's truncated write, committed as-is
    record_path.write_bytes(b"")
    run_git(hub_root, "add", "-A")
    run_git(hub_root, "commit", "-m", "simulate interrupted write")

    with pytest.raises(assetstore.AssetStoreError, match=re.escape(str(record_path))):
        assetcmd.migrate_assets(HubHandle(root=hub_root), store=store)

    # bytes on disk: the zero-byte record survives, not unlinked further
    assert record_path.exists()
    assert record_path.read_bytes() == b""
    # git porcelain: nothing staged, nothing left dirty by the abort
    status = gitio._run(hub_root, "status", "--porcelain").stdout.strip()
    assert status == ""


def test_migrate_dir_shaped_record_aborts_instead_of_diverting_past_it(
    hub_root, run_git
):
    """Important 1 (wave I-1 round 3): the round-2 `exists()` -> `is_file()`
    change in load_record read a record path that EXISTS but is not a
    regular file (a directory) as ABSENT rather than raising -- a direct
    P47 violation, and the opposite of what pre-round-2 code did (which
    raised AssetStoreError here, via read_text's IsADirectoryError). Before
    this fix, "absent" let migrate proceed straight into divert_and_record
    for the still-undiverted asset below: the measured sequence was an
    upload that succeeded, the raw bytes unlinked from the hub tree, and
    then an UNCAUGHT PermissionError from save_yaml_model writing onto the
    directory path -- past this function's own `except
    assetstore.AssetStoreError` restore guard (a bare PermissionError is
    not one), leaving the deletion uncommitted in the hub clone with
    nothing left to undo it. Fixed: load_record's own pre-flight (this
    function's first line inside the loop) now raises AssetStoreError for
    the directory-shaped record BEFORE divert_and_record ever runs, so
    this restore guard catches it, the raw asset is never touched, and the
    working tree is left exactly as committed -- porcelain clean both
    before and after, not `D federation/rid-a/doc1/assets/<sha>.png` as
    measured pre-fix."""
    record_path = hub_root / "federation" / "rid-a" / assetstore.RECORD_NAME
    # simulate a record path clobbered by something external (a bad
    # archive extraction, a sync tool, an operator `mkdir`) -- committed as
    # a directory rather than the regular file this codebase always writes
    record_path.mkdir()
    (record_path / "stray.txt").write_text("not a record\n", encoding="utf-8")
    run_git(hub_root, "add", "-A")
    run_git(hub_root, "commit", "-m", "simulate a directory clobbering the record path")

    asset_path = hub_root / "federation" / "rid-a" / "doc1" / "assets" / f"{SHA}.png"
    assert asset_path.is_file()  # sanity: still raw, undiverted
    before_status = gitio._run(hub_root, "status", "--porcelain").stdout.strip()
    assert before_status == ""

    store = assetstore.MemoryStore()
    with pytest.raises(assetstore.AssetStoreError, match=re.escape(str(record_path))):
        assetcmd.migrate_assets(HubHandle(root=hub_root), store=store)

    # the raw asset was never touched -- divert_and_record never ran, the
    # pre-flight load_record raised first
    assert asset_path.is_file()
    assert asset_path.read_bytes() == DATA
    assert store.get(f"{SHA}.png") is None
    # the directory survives, untouched -- not partially overwritten
    assert record_path.is_dir()
    assert (record_path / "stray.txt").read_text(encoding="utf-8") == "not a record\n"
    # git porcelain: still clean -- nothing staged, nothing left dirty
    after_status = gitio._run(hub_root, "status", "--porcelain").stdout.strip()
    assert after_status == ""


def test_migrate_requires_s3_mode(hub_root):
    (hub_root / ".kb" / "config.yaml").write_text("kind: hub\n", encoding="utf-8")
    with pytest.raises(assetcmd.AssetCmdError, match="mode"):
        assetcmd.migrate_assets(HubHandle(root=hub_root))


def test_migrate_reports_a_broken_entry_as_skipped_not_as_nothing_to_migrate(
    tmp_path, run_git
):
    """Item 3 (ruling P53, wave L1 brief): a federation/ entry holding
    exactly one of _meta.yaml/index.yaml -- committed raw bytes whose
    mid-tier source stopped publishing, in the reproduction this was
    measured against -- is invisible to federation.iter_entry_dirs's own
    sweep (it logs a warning and moves on, never yielding the entry to
    _rid_dirs). Before this fix, migrate_assets' per_rid came back empty
    for a hub in exactly this shape and the CLI printed "nothing to
    migrate" at exit 0 -- a false all-clear directly beneath the warning
    saying something WAS found and skipped. report.skipped closes the
    gap: populated from federation.scan_broken_entries (read-only,
    additive -- does not widen what actually gets diverted, only what the
    caller is told), so the caller can tell "genuinely nothing under
    federation/" apart from "something was there and could not be
    migrated"."""
    root = tmp_path / "hub"
    broken = root / "federation" / "rid-b" / "doc1"
    broken.mkdir(parents=True)
    models.save_yaml_model(
        broken / "_meta.yaml", FederationMeta(repo_id="rid-b", source_commit="abc1234")
    )
    # index.yaml deliberately absent: has_meta and not has_index is the
    # exact shape federation.py's own warning names.
    (root / ".kb").mkdir()
    (root / ".kb" / "config.yaml").write_text(
        "kind: hub\nasset_store:\n  mode: s3\n  bucket: b\n", encoding="utf-8"
    )
    run_git(root, "init")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "seed a broken entry")

    report = assetcmd.migrate_assets(HubHandle(root=root), store=assetstore.MemoryStore())

    assert report.per_rid == {}
    assert report.skipped == ["rid-b/doc1"]
    assert report.committed is False


def test_migrate_cli_does_not_print_a_false_all_clear_when_something_was_skipped(
    monkeypatch,
):
    """CLI wiring pin, item 3: the specific bug was the COMBINATION of an
    empty per_rid, the old unconditional "nothing to migrate" line, and
    exit 0 -- the report-level test above only pins report.skipped: this
    one pins that cli.py actually acts on it. Monkeypatches
    assetcmd.migrate_assets and cli._hub_or_exit directly (real hub
    resolution needs a git clone this test has no reason to pay for; the
    CLI print/exit branch under test starts after both of those calls)."""
    from typer.testing import CliRunner

    from strata_kb import cli

    monkeypatch.setattr(cli, "_hub_or_exit", lambda hub, kb_dir: HubHandle(root=Path(".")))
    monkeypatch.setattr(
        assetcmd,
        "migrate_assets",
        lambda handle, store=None: assetcmd.MigrateReport(per_rid={}, skipped=["rid-b/doc1"]),
    )
    result = CliRunner().invoke(cli.app, ["assets", "migrate"])
    assert result.exit_code == 1
    assert "nothing to migrate" not in result.stdout
    assert "rid-b/doc1" in result.stdout
    assert "nothing migrated" in result.stdout


def test_migrate_cli_still_prints_a_true_all_clear_when_nothing_was_skipped(monkeypatch):
    """No-op control for the test above: an empty per_rid with NOTHING
    skipped is the one case the old "nothing to migrate" / exit 0 pair is
    still correct for, and this fix must leave it alone."""
    from typer.testing import CliRunner

    from strata_kb import cli

    monkeypatch.setattr(cli, "_hub_or_exit", lambda hub, kb_dir: HubHandle(root=Path(".")))
    monkeypatch.setattr(
        assetcmd,
        "migrate_assets",
        lambda handle, store=None: assetcmd.MigrateReport(per_rid={}, skipped=[]),
    )
    result = CliRunner().invoke(cli.app, ["assets", "migrate"])
    assert result.exit_code == 0
    assert "nothing to migrate — no in-git assets under federation/" in result.stdout


def test_migrate_failure_restores_failed_rid(hub_root_two_assets):
    hub_root = hub_root_two_assets

    class _FailOnSecondPut(assetstore.MemoryStore):
        """Succeeds once (so the first asset is genuinely uploaded and
        unlinked from disk), then fails — forcing migrate_assets to restore
        real, on-disk deletions rather than a tree it never touched."""

        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def put(self, name, data):
            self.calls += 1
            if self.calls >= 2:
                raise assetstore.AssetStoreError("bucket down")
            super().put(name, data)

    with pytest.raises(assetstore.AssetStoreError):
        assetcmd.migrate_assets(HubHandle(root=hub_root), store=_FailOnSecondPut())

    # failed rid restored: BOTH binaries present (the first one was really
    # uploaded + unlinked before the second put() failed, so its presence
    # here proves `git checkout` did the restoring, not "was never touched")
    assets_dir = hub_root / "federation" / "rid-a" / "doc1" / "assets"
    assert (assets_dir / f"{SHA_A}.png").exists()
    assert (assets_dir / f"{SHA_B}.png").exists()
    status = gitio._run(
        hub_root, "status", "--porcelain", "--", "federation"
    ).stdout.strip()
    assert status == ""  # nothing staged, nothing left dirty
    assert not (hub_root / "federation" / "rid-a" / "_assets.yaml").exists()


def _migrated_hub(hub_root) -> assetstore.MemoryStore:
    store = assetstore.MemoryStore()
    assetcmd.migrate_assets(HubHandle(root=hub_root), store=store)
    return store


def test_verify_ok_after_migrate(hub_root):
    store = _migrated_hub(hub_root)
    report = assetcmd.verify_assets(HubHandle(root=hub_root), store=store)
    assert report.ok
    assert report.missing_records == [] and report.dangling_refs == []


def test_verify_computes_record_entry_basenames_via_pureposixpath_not_hostbound_path(
    monkeypatch, hub_root
):
    """Item 6 (wave L1 brief), a mechanism pin, not a live-bug reproduction.

    A coordinator follow-up found assetcmd.py repeating the exact
    host-bound `Path(rel).name` mechanism assetstore.py's P49 fix
    (b92637f) closed for record entries: `rel` is a POSIX-spelled relative
    path by construction (assetstore.divert_assets, the only writer of
    record entries anywhere in this tree, writes `.as_posix()`), but
    `Path(rel).name` binds to whatever `Path` is on the host running it --
    a WindowsPath splits a backslash-spelled entry's basename correctly, a
    PosixPath does not, so the same record entry's "basename" differed by
    host. Fixed here to `PurePosixPath(rel).name` at both of
    _entry_resolves' call sites and verify_assets' `recorded` dict key,
    matching the technique assetstore.asset_sha/is_asset_name already use.

    These three sites are dead ground through the real call chain today:
    assetstore.load_record now rejects any entry `is_asset_name` refuses
    -- including a backslash-bearing one -- before _record_entries can
    hand it here, so no value-based test can exercise the actual
    divergence end to end. It could not on THIS host either way: Windows'
    Path IS WindowsPath, which also treats backslash as a separator, so
    Path(rel).name and PurePosixPath(rel).name agree for a backslash
    input right here, diverging only on POSIX CI. What this test pins
    instead is the MECHANISM: this run's real, well-formed (forward-slash)
    record entries must be resolved through PurePosixPath, not Path, so a
    regression back to Path is caught even though it would not change any
    assertion's VALUE on this host. See the report for the RED/GREEN
    mutation this was checked against (reverting all three call sites to
    Path(rel).name empties `calls` below and fails the assert)."""
    calls: list[tuple] = []
    real_pure_posix_path = assetcmd.PurePosixPath

    class _SpyPurePosixPath:
        def __new__(cls, *args):
            calls.append(args)
            return real_pure_posix_path(*args)

    monkeypatch.setattr(assetcmd, "PurePosixPath", _SpyPurePosixPath)

    store = _migrated_hub(hub_root)
    report = assetcmd.verify_assets(HubHandle(root=hub_root), store=store)

    assert report.ok
    assert calls, (
        "expected verify_assets/_entry_resolves to compute a record "
        "entry's basename via PurePosixPath, not host-bound Path"
    )


def test_verify_reports_missing_record_entry(hub_root):
    store = _migrated_hub(hub_root)
    store.data.clear()  # bytes vanished from the bucket
    report = assetcmd.verify_assets(HubHandle(root=hub_root), store=store)
    assert not report.ok
    assert any(SHA in m for m in report.missing_records)
    assert any(SHA in d for d in report.dangling_refs)


def test_verify_reports_dangling_ref(hub_root):
    store = _migrated_hub(hub_root)
    ghost = "9" * 64
    md = hub_root / "federation" / "rid-a" / "doc1" / "ch1.md"
    md.write_text(md.read_text(encoding="utf-8") + f"![g](assets/{ghost}.png)\n", encoding="utf-8")
    report = assetcmd.verify_assets(HubHandle(root=hub_root), store=store)
    assert any(ghost in d for d in report.dangling_refs)


def test_verify_reports_orphan_record_entry(hub_root):
    store = _migrated_hub(hub_root)
    md = hub_root / "federation" / "rid-a" / "doc1" / "ch1.md"
    md.write_text("no refs anymore\n", encoding="utf-8")
    report = assetcmd.verify_assets(HubHandle(root=hub_root), store=store)
    assert report.ok  # orphans are informational only
    assert any(SHA in o for o in report.orphans)


def test_verify_reports_a_tampered_object_as_not_ok(hub_worktree, run_git):
    from tests.conftest import make_fed_entry

    data = b"real image bytes"
    name = hashlib.sha256(data).hexdigest() + ".png"
    fed = hub_worktree / "federation"
    entry = make_fed_entry(fed, "child", "doc")
    (entry / "doc" / "assets").mkdir(parents=True, exist_ok=True)
    store = assetstore.MemoryStore()
    store.data[name] = b"tampered"
    models.save_yaml_model(
        entry / assetstore.RECORD_NAME,
        models.AssetsRecord(assets=[f"doc/assets/{name}"]),
    )
    report = assetcmd.verify_assets(HubHandle(root=hub_worktree), store=store)
    assert report.ok is False
    assert any(name in line for line in report.corrupt)


def test_verify_propagates_a_transport_error_instead_of_reporting_corrupt(
    hub_worktree,
):
    """A down bucket is not corruption. S3Store.get raises the base
    AssetStoreError for a transport failure, same as get_verified raises
    for a hash mismatch -- narrowly catching only AssetIntegrityError keeps
    the two apart so a store outage propagates instead of being reported
    (and silenced) as `corrupt`."""
    from tests.conftest import make_fed_entry

    class _Down(assetstore.MemoryStore):
        def get(self, name):
            raise assetstore.AssetStoreError("bucket unreachable")

    data = b"real image bytes"
    name = hashlib.sha256(data).hexdigest() + ".png"
    fed = hub_worktree / "federation"
    entry = make_fed_entry(fed, "child", "doc")
    (entry / "doc" / "assets").mkdir(parents=True, exist_ok=True)
    models.save_yaml_model(
        entry / assetstore.RECORD_NAME,
        models.AssetsRecord(assets=[f"doc/assets/{name}"]),
    )
    with pytest.raises(assetstore.AssetStoreError, match="bucket unreachable") as exc:
        assetcmd.verify_assets(HubHandle(root=hub_worktree), store=_Down())
    assert not isinstance(exc.value, assetstore.AssetIntegrityError)


def test_verify_reports_a_corrupt_local_asset_as_not_ok(hub_worktree):
    """The local-file branch of _entry_resolves must hash-check too, or
    `kb assets verify` and the web UI disagree about the same bytes on
    disk. A prior version of this test suite left this branch untested;
    deleting the verify_bytes() call in the local-file branch left the
    whole suite green."""
    from tests.conftest import make_fed_entry

    data = b"real image bytes"
    name = hashlib.sha256(data).hexdigest() + ".png"
    fed = hub_worktree / "federation"
    entry = make_fed_entry(fed, "child", "doc")
    assets_dir = entry / "doc" / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / name).write_bytes(b"tampered")  # exists on disk, wrong hash
    models.save_yaml_model(
        entry / assetstore.RECORD_NAME,
        models.AssetsRecord(assets=[f"doc/assets/{name}"]),
    )
    report = assetcmd.verify_assets(HubHandle(root=hub_worktree))
    assert report.ok is False
    assert any(name in line for line in report.corrupt)


@pytest.mark.parametrize(
    "write_broken_record",
    [
        lambda p: p.write_bytes(b""),
        lambda p: p.write_text("{{not yaml", encoding="utf-8"),
    ],
    ids=["zero-byte", "corrupt-yaml"],
)
def test_verify_reports_a_broken_record_as_corrupt(hub_worktree, write_broken_record):
    """Important 3 (wave I-1 round 2): `_record_entries` used to swallow
    every read failure with a bare `except Exception: return []` and
    report nothing -- `kb assets verify`'s whole job is telling an
    operator the store and the records disagree, and it reported clean on
    exactly the records that were broken (the command exited non-zero only
    incidentally, via a dangling_refs line blaming a markdown file, and
    only while some markdown still referenced the asset). Now goes through
    assetstore.load_record, the same primitive migrate's pre-flight uses,
    and surfaces its raise as a finding naming the file instead of hiding
    it."""
    from tests.conftest import make_fed_entry

    fed = hub_worktree / "federation"
    entry = make_fed_entry(fed, "child", "doc")
    (entry / "doc" / "assets").mkdir(parents=True, exist_ok=True)
    record_path = entry / assetstore.RECORD_NAME
    write_broken_record(record_path)

    report = assetcmd.verify_assets(HubHandle(root=hub_worktree))
    assert report.ok is False
    assert any(str(record_path) in line for line in report.corrupt)
    # no markdown references anything here -- unlike the pre-fix bug, the
    # finding must not depend on a dangling_refs line to notice at all
    assert report.dangling_refs == []


def test_verify_reports_an_unreadable_record_as_corrupt(hub_worktree, monkeypatch):
    """Important 3, third broken shape: a record that exists and parses
    fine for anyone else but fails this read specifically (a lock, a
    permission bit) -- must be reported the same way as the corrupt and
    zero-byte shapes above, not silently skipped."""
    from tests.conftest import make_fed_entry

    fed = hub_worktree / "federation"
    entry = make_fed_entry(fed, "child", "doc")
    (entry / "doc" / "assets").mkdir(parents=True, exist_ok=True)
    record_path = entry / assetstore.RECORD_NAME
    models.save_yaml_model(
        record_path, models.AssetsRecord(assets=[f"doc/assets/{'a' * 64}.png"])
    )

    real_load = models.load_yaml_model

    def _flaky(path, model):
        if path == record_path:
            raise PermissionError(f"permission denied: {path}")
        return real_load(path, model)

    monkeypatch.setattr(models, "load_yaml_model", _flaky)
    report = assetcmd.verify_assets(HubHandle(root=hub_worktree))

    assert report.ok is False
    assert any(str(record_path) in line for line in report.corrupt)


def test_a_nested_entry_gets_its_record_at_the_leaf(hub_worktree):
    from tests.conftest import make_fed_entry

    data = b"nested image"
    name = hashlib.sha256(data).hexdigest() + ".png"
    fed = hub_worktree / "federation"
    leaf = make_fed_entry(fed / "mid", "deep", "doc")
    assets = leaf / "doc" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / name).write_bytes(data)

    store = assetstore.MemoryStore()
    assetcmd.migrate_assets(HubHandle(root=hub_worktree), store=store)

    assert (leaf / assetstore.RECORD_NAME).is_file()
    assert not (fed / "mid" / assetstore.RECORD_NAME).exists()
    entries = assetstore.synthesized_asset_entries(leaf)
    assert entries == {f"doc/assets/{name}": hashlib.sha256(data).hexdigest()}


def test_verify_local_mode_checks_files(hub_root):
    # mode none: record entries must resolve as local files
    (hub_root / ".kb" / "config.yaml").write_text(
        "kind: hub\nasset_store:\n  mode: none\n", encoding="utf-8"
    )
    dest = hub_root / "federation" / "rid-a"
    models.save_yaml_model(
        dest / "_assets.yaml", models.AssetsRecord(assets=["doc1/assets/" + "8" * 64 + ".png"])
    )
    report = assetcmd.verify_assets(HubHandle(root=hub_root))
    assert not report.ok and report.missing_records


def make_dangling_link(path: Path) -> str | None:
    """Put a link at `path` whose target does not exist. Returns a short
    description of what kind of link was created, or None when this
    machine can create neither (the caller should skip).

    Deliberately a local twin of tests/test_assetstore.py's helper of the
    same name/shape rather than an import from it -- that file is held by
    another implementer in this same checkout (wave L1 brief) and must not
    become an import-time dependency of this one. A real POSIX symlink is
    tried first; Windows refuses os.symlink without
    SeCreateSymbolicLinkPrivilege, so there it falls back to an NTFS
    junction via `mklink /J`, whose target is then removed. Both present
    exists()=False, is_file()=False, os.path.lexists()=True -- the shape
    item 2 (wave L1 brief) is about.
    """
    target = path.parent / "no-such-target"
    try:
        os.symlink(target, path)
        return "posix symlink"
    except (OSError, NotImplementedError, AttributeError):
        pass
    if os.name != "nt":
        return None
    target.mkdir()
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(path), str(target)],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    target.rmdir()
    return "ntfs junction" if os.path.lexists(path) else None


def remove_dangling_link(path: Path) -> None:
    """Undo make_dangling_link. A junction is a directory entry (os.rmdir);
    a dangling symlink is not (os.unlink)."""
    for remove in (os.rmdir, os.unlink):
        try:
            remove(path)
            return
        except OSError:
            continue


def test_verify_reports_a_broken_link_instead_of_crashing(hub_root):
    """Item 2 (wave L1 brief): assetcmd used to build `local_names` with
    `root.glob("**/assets/*")`, and pathlib's recursive '**' selector
    raises an uncaught FileNotFoundError partway through a walk that meets
    a broken link -- measured pre-existing on 2fe4d62, found by the
    asset-store wave and correctly left out of that wave's scope. Verified
    by direct reproduction (see the report) that
    `Path("federation").glob("**/assets/*")` dies with exactly that
    traceback over this shape. `kb assets verify` is read-only and its
    whole job is naming problems, so the broken link must become a finding
    -- report.ok False, a [broken] line naming the path and the remedy --
    not a raise (that shape is reserved for assetstore.load_record's
    destructive-action gate, which this reader is not) and not a silent
    empty result."""
    store = assetstore.MemoryStore()
    assets_dir = hub_root / "federation" / "rid-a" / "doc1" / "assets"
    broken = assets_dir / "broken"
    kind = make_dangling_link(broken)
    if kind is None:  # pragma: no cover - depends on the host's privileges
        pytest.skip("this machine can create neither a symlink nor a junction")
    try:
        report = assetcmd.verify_assets(HubHandle(root=hub_root), store=store)
    finally:
        remove_dangling_link(broken)

    assert report.ok is False
    assert len(report.broken_links) == 1
    line = report.broken_links[0]
    assert str(Path("federation") / "rid-a" / "doc1" / "assets" / "broken") in line
    assert "remove or restore" in line
    # the rest of the walk must still complete -- the real asset in the
    # same assets/ dir is unaffected by its broken sibling
    assert report.missing_records == []
