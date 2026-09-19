# tests/test_federation_nested.py
from pathlib import Path

import pytest

from strata_kb import federation
from tests.conftest import make_fed_entry


def _make_nested_hub(tmp_path: Path) -> Path:
    """federation/ có 1 entry phẳng + 2 entry lồng dưới namespace mid/."""
    fed = tmp_path / "hub" / "federation"
    make_fed_entry(fed, "repo-flat", "flat-doc")
    make_fed_entry(fed / "mid", "repo-x", "doc-x")
    make_fed_entry(fed / "mid", "repo-y", "doc-y")
    return fed


def test_iter_entry_dirs_finds_flat_and_nested(tmp_path):
    fed = _make_nested_hub(tmp_path)
    ids = [pid for pid, _ in federation.iter_entry_dirs(fed)]
    assert ids == ["mid/repo-x", "mid/repo-y", "repo-flat"]


def test_load_federation_uses_path_id_for_nested_entries(tmp_path):
    fed = _make_nested_hub(tmp_path)
    repos = federation.load_federation(fed)
    assert [r.meta.repo_id for r in repos] == ["mid/repo-x", "mid/repo-y", "repo-flat"]
    # kb_dir trỏ đúng thư mục lồng
    assert repos[0].kb_dir == fed / "mid" / "repo-x"


def test_build_federation_index_includes_nested(tmp_path):
    fed = _make_nested_hub(tmp_path)
    idx = federation.build_federation_index(fed)
    assert {(e.repo_id, e.doc_id) for e in idx.docs} == {
        ("mid/repo-x", "doc-x"),
        ("mid/repo-y", "doc-y"),
        ("repo-flat", "flat-doc"),
    }


def test_namespace_dir_without_meta_is_not_an_entry(tmp_path):
    fed = _make_nested_hub(tmp_path)
    # thư mục mid/ không có _meta.yaml/index.yaml → namespace, không phải entry
    assert all(pid != "mid" for pid, _ in federation.iter_entry_dirs(fed))


def test_half_broken_entry_is_skipped_with_warning(tmp_path, caplog):
    fed = _make_nested_hub(tmp_path)
    broken = fed / "mid" / "repo-broken"
    broken.mkdir()
    (broken / "index.yaml").write_text("docs: []\n", encoding="utf-8")  # thiếu _meta.yaml
    ids = [pid for pid, _ in federation.iter_entry_dirs(fed)]
    assert "mid/repo-broken" not in ids
    assert any("mid/repo-broken" in r.message for r in caplog.records)


def test_old_slim_layout_still_skipped(tmp_path, caplog):
    fed = _make_nested_hub(tmp_path)
    slim = fed / "repo-old"
    (slim / "manifests").mkdir(parents=True)
    assert all(pid != "repo-old" for pid, _ in federation.iter_entry_dirs(fed))
    assert any("slim layout" in r.message for r in caplog.records)


def test_hub_to_hub_publish_diverts_still_raw_assets_into_upper_store(tmp_path):
    """F-D11 item 3: _snapshot_federation declared store=None and never
    referenced it, so a mid-tier hub with no asset store of its own just
    copied raw asset bytes straight through as committed git blobs on every
    hub above it -- even when an upper hub DOES configure a store. Fixed:
    still-raw bytes that land under dest get diverted into the upper hub's
    own store, exactly like a direct child publish (_snapshot) would."""
    import hashlib

    from strata_kb import assetstore, models, publish
    from strata_kb.hub import HubHandle

    data = b"still raw png bytes"
    name = hashlib.sha256(data).hexdigest() + ".png"

    fed_src = tmp_path / "mid" / "federation"
    entry = make_fed_entry(fed_src, "repo-a", "doc-a")
    assets_dir = entry / "doc-a" / "assets"
    assets_dir.mkdir()
    (assets_dir / name).write_bytes(data)

    upper = HubHandle(root=tmp_path / "root-hub")
    (upper.root / "federation").mkdir(parents=True)
    store = assetstore.MemoryStore()

    _n_docs, changed, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc1234", store=store
    )
    assert changed is True

    dest_entry = upper.federation_dir / "mid" / "repo-a"
    assert store.get(name) == data
    assert not (dest_entry / "doc-a" / "assets" / name).exists()
    record = models.load_yaml_model(
        dest_entry / assetstore.RECORD_NAME, models.AssetsRecord
    )
    assert record.assets == [f"doc-a/assets/{name}"]
    # the source hub's own federation tree is untouched (mirrors _snapshot's
    # "child .kb is untouched" contract)
    assert (entry / "doc-a" / "assets" / name).exists()


def test_hub_to_hub_publish_second_run_is_noop_with_store(tmp_path):
    """Regression for a bug in the F-D11 item 3 fix itself, caught before
    commit: _snapshot_federation's own divert_and_record call writes a
    dest-only _assets.yaml that fed_src never had. Left inside the generic
    file-diff, the very next publish reads that file as "absent from
    source" and hashsync deletes it -- the record the divert step had just
    written was gone one publish later, even though the store still held
    the bytes. Confirmed failing before the RECORD_NAME exclusion below was
    added (assertions after the second call: changed was True, and the
    record file no longer existed)."""
    import hashlib

    from strata_kb import assetstore, publish
    from strata_kb.hub import HubHandle

    data = b"repeat publish bytes"
    name = hashlib.sha256(data).hexdigest() + ".png"

    fed_src = tmp_path / "mid" / "federation"
    entry = make_fed_entry(fed_src, "repo-a", "doc-a")
    assets_dir = entry / "doc-a" / "assets"
    assets_dir.mkdir()
    (assets_dir / name).write_bytes(data)

    upper = HubHandle(root=tmp_path / "root-hub")
    (upper.root / "federation").mkdir(parents=True)
    store = assetstore.MemoryStore()

    publish._snapshot_federation(fed_src, upper, "mid", "abc1234", store=store)
    dest_record = upper.federation_dir / "mid" / "repo-a" / assetstore.RECORD_NAME
    assert dest_record.is_file()

    _n_docs, changed, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc1235", store=store
    )
    assert changed is False
    assert dest_record.is_file()  # not wiped by the second, no-op publish


def test_hub_to_hub_publish_carries_a_record_the_source_already_diverted(tmp_path):
    """Case A (repo-a): the source hub already diverted this asset itself
    (its own store already stripped the raw bytes) -- only a record names
    it, with no physical file anywhere under fed_src for divert_assets to
    find, or for synthesized_asset_entries' manifest entry to back with
    real bytes. A sibling entry (repo-b, Case B) carries genuinely raw
    bytes in the SAME publish, so active_store is actually engaged (a
    Case-A-only publish is already covered by the pre-existing keep_records
    tests in test_publish_hub.py regardless of active_store, so it would
    not tell this fix apart from before it existed). This must not crash
    trying to shutil.copy2 repo-a's asset (it has no backing file), and the
    inherited name must survive an unrelated republish."""
    import hashlib

    from strata_kb import assetstore, models, publish
    from strata_kb.hub import HubHandle

    inherited_name = "a" * 64 + ".png"
    fed_src = tmp_path / "mid" / "federation"
    entry_a = make_fed_entry(fed_src, "repo-a", "doc-a")
    models.save_yaml_model(
        entry_a / assetstore.RECORD_NAME,
        models.AssetsRecord(assets=[f"doc-a/assets/{inherited_name}"]),
    )
    raw_data = b"case b sibling bytes"
    raw_name = hashlib.sha256(raw_data).hexdigest() + ".png"
    entry_b = make_fed_entry(fed_src, "repo-b", "doc-b")
    raw_assets_dir = entry_b / "doc-b" / "assets"
    raw_assets_dir.mkdir()
    (raw_assets_dir / raw_name).write_bytes(raw_data)

    upper = HubHandle(root=tmp_path / "root-hub")
    (upper.root / "federation").mkdir(parents=True)
    store = assetstore.MemoryStore()

    _n_docs, changed, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc1234", store=store
    )
    assert changed is True
    assert store.get(raw_name) == raw_data  # Case B really diverted -- store engaged

    dest_a_record = upper.federation_dir / "mid" / "repo-a" / assetstore.RECORD_NAME
    assert models.load_yaml_model(dest_a_record, models.AssetsRecord).assets == [
        f"doc-a/assets/{inherited_name}"
    ]

    # an unrelated second publish must not lose the inherited record
    make_fed_entry(fed_src, "repo-c", "doc-c")
    _n_docs, changed, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc1235", store=store
    )
    assert changed is True
    assert dest_a_record.is_file()
    assert models.load_yaml_model(dest_a_record, models.AssetsRecord).assets == [
        f"doc-a/assets/{inherited_name}"
    ]


def test_hub_to_hub_publish_store_outage_then_retry_never_commits_binaries(
    tmp_path, hub_worktree
):
    """C1: _snapshot_federation's divert_and_record call (inside
    _reconcile_asset_records) had no AssetStoreError restore guard, though
    _snapshot's matching call did. A store outage after apply_sync has
    already copied raw bytes into the hub clone's working tree left them
    there uncommitted; a retry with a healthy store would see dest's
    manifest already match fed_src's (bytes already copied) and never reach
    divert again -- so the retry's own commit would land the binary
    straight into hub git, permanently, and no later publish would ever
    repair it. Mirrors
    test_snapshot_store_outage_then_retry_never_commits_binaries
    (tests/test_publish.py) for the hub-to-hub path."""
    import hashlib

    from strata_kb import assetstore, gitio, publish
    from strata_kb.hub import HubHandle

    data = b"store outage raw bytes"
    name = hashlib.sha256(data).hexdigest() + ".png"

    fed_src = tmp_path / "mid" / "federation"
    entry = make_fed_entry(fed_src, "repo-a", "doc-a")
    assets_dir = entry / "doc-a" / "assets"
    assets_dir.mkdir()
    (assets_dir / name).write_bytes(data)

    upper = HubHandle(root=hub_worktree)

    class _FailingStore(assetstore.MemoryStore):
        def put(self, name, data):
            raise assetstore.AssetStoreError("bucket down")

    with pytest.raises(assetstore.AssetStoreError):
        publish._snapshot_federation(
            fed_src, upper, "mid", "abc1234", store=_FailingStore()
        )

    # working tree restored: no leftover asset bytes, porcelain clean under federation
    status = gitio._run(
        upper.root, "status", "--porcelain", "--", "federation"
    ).stdout.strip()
    assert status == ""
    dest = upper.federation_dir / "mid" / "repo-a"
    assert not dest.exists()  # nothing left half-written

    # retry with a healthy store: diverts for real, no leftover binary
    store = assetstore.MemoryStore()
    _n_docs, changed, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc1234", store=store
    )
    assert changed is True
    assert store.get(name) == data
    assert not list(dest.rglob("*.png"))


def test_hub_to_hub_second_publish_keeps_name_the_hub_itself_diverted(tmp_path):
    """I1: the per-entry SOURCE-side RECORD_NAME pop keeps a name THIS hub
    diverted itself (Case B, absent from the source's own record) from
    being wiped when the source's smaller record is later diffed back over
    dest's. Without it, src_man keeps the source's literal record file
    (still just {A}) while the dest-side pop still runs, so the diff
    classifies RECORD_NAME as "changed" and apply_sync overwrites dest's
    merged {A, B} record with the source's smaller one -- deleting the name
    (B) whose only surviving copy lives in the upper hub's store. Also pins
    the "source-side half of the symmetry invariant" the review flagged as
    unpinned (the dest-side pop already had
    test_hub_to_hub_publish_second_run_is_noop_with_store)."""
    import hashlib

    from strata_kb import assetstore, models, publish
    from strata_kb.hub import HubHandle

    name_a = "a" * 64 + ".png"
    path_a = f"doc-a/assets/{name_a}"

    fed_src = tmp_path / "mid" / "federation"
    entry = make_fed_entry(fed_src, "repo-a", "doc-a")
    # source already migrated name A itself -- Case A, no raw bytes for it
    models.save_yaml_model(
        entry / assetstore.RECORD_NAME, models.AssetsRecord(assets=[path_a])
    )
    data_b = b"only the upper hub ever diverts this one"
    name_b = hashlib.sha256(data_b).hexdigest() + ".png"
    path_b = f"doc-a/assets/{name_b}"
    assets_dir = entry / "doc-a" / "assets"
    assets_dir.mkdir()
    (assets_dir / name_b).write_bytes(data_b)

    upper = HubHandle(root=tmp_path / "root-hub")
    (upper.root / "federation").mkdir(parents=True)
    store = assetstore.MemoryStore()

    _n_docs, changed, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc1234", store=store
    )
    assert changed is True
    dest_record = upper.federation_dir / "mid" / "repo-a" / assetstore.RECORD_NAME
    assert models.load_yaml_model(dest_record, models.AssetsRecord).assets == sorted(
        [path_a, path_b]
    )

    # second publish: nothing new at the source (still just names A)
    publish._snapshot_federation(fed_src, upper, "mid", "abc1235", store=store)

    # B's only surviving copy is in the store -- it must survive even though
    # the source never recorded it itself
    assert models.load_yaml_model(dest_record, models.AssetsRecord).assets == sorted(
        [path_a, path_b]
    )
    assert store.get(name_b) == data_b


def test_hub_to_hub_raw_dest_copy_survives_source_running_assets_migrate(tmp_path):
    """I2 + I3: publish.py's `src_man[path] = sha` (per-entry source-side
    asset-name synthesis) is what stops a not-yet-diverted raw copy sitting
    at dest from being classified "deleted" once the source migrates the
    same asset into its own record (Case A) -- without it, the path is
    absent from src_man and present in dest_man, so apply_sync unlinks it
    BEFORE divert_and_record's sweep ever reaches it: the bytes vanish from
    the upper hub entirely, never uploaded, never left on disk. The same
    scenario also pins the widened early-return guard (`and not
    synthesized_src_only`): reverting it to the old `if not changed and not
    deleted:` makes the function early-return before ever reaching the
    reconcile pass, so the raw bytes are never diverted either -- both
    mutants are killed by this one reproduction, verified independently."""
    import hashlib

    from strata_kb import assetstore, models, publish
    from strata_kb.hub import HubHandle

    data = b"raw bytes present before this hub ever had a store"
    name = hashlib.sha256(data).hexdigest() + ".png"

    fed_src = tmp_path / "mid" / "federation"
    entry = make_fed_entry(fed_src, "repo-a", "doc-a")
    assets_dir = entry / "doc-a" / "assets"
    assets_dir.mkdir()
    (assets_dir / name).write_bytes(data)

    upper = HubHandle(root=tmp_path / "root-hub")
    (upper.root / "federation").mkdir(parents=True)

    # publish 1: no store anywhere yet -- plain mirror, dest gets a real raw file
    _n_docs, changed, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc1234"
    )
    assert changed is True
    dest_entry = upper.federation_dir / "mid" / "repo-a"
    dest_asset = dest_entry / "doc-a" / "assets" / name
    assert dest_asset.exists()

    # mid hub migrates its own copy into its own store: raw bytes gone from
    # fed_src, its record now names it (Case A)
    (assets_dir / name).unlink()
    models.save_yaml_model(
        entry / assetstore.RECORD_NAME,
        models.AssetsRecord(assets=[f"doc-a/assets/{name}"]),
    )

    # publish 2: the upper hub gains a store between the two publishes
    store = assetstore.MemoryStore()
    _n_docs, changed, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc1235", store=store
    )
    assert changed is True
    # the raw bytes sitting at dest since before this hub had a store must
    # survive -- diverted into the store, not deleted outright
    assert store.get(name) == data
    assert not dest_asset.exists()
    record = models.load_yaml_model(
        dest_entry / assetstore.RECORD_NAME, models.AssetsRecord
    )
    assert record.assets == [f"doc-a/assets/{name}"]


def test_hub_to_hub_second_publish_keeps_record_when_store_goes_away(tmp_path):
    """I5 (shape: dest-only record, source has since dropped its own copy
    too). Once this hub's store is disabled, a record it wrote from a past
    divert must not be deleted just because neither this hub (no store to
    check) nor the source (dropped its own copy in between) can back it
    with a file any more -- the record is the only remaining pointer to
    bytes the store still holds. See also
    tests/test_assetcmd.py:test_verify_local_mode_checks_files, which
    already pins that `kb assets verify` flags exactly this shape as
    missing_records."""
    import hashlib

    from strata_kb import assetstore, models, publish
    from strata_kb.hub import HubHandle

    data = b"only the store will remember this one"
    name = hashlib.sha256(data).hexdigest() + ".png"

    fed_src = tmp_path / "mid" / "federation"
    entry = make_fed_entry(fed_src, "repo-a", "doc-a")
    assets_dir = entry / "doc-a" / "assets"
    assets_dir.mkdir()
    (assets_dir / name).write_bytes(data)

    upper = HubHandle(root=tmp_path / "root-hub")
    (upper.root / "federation").mkdir(parents=True)
    store = assetstore.MemoryStore()

    publish._snapshot_federation(fed_src, upper, "mid", "abc1234", store=store)
    dest_record = upper.federation_dir / "mid" / "repo-a" / assetstore.RECORD_NAME
    assert models.load_yaml_model(dest_record, models.AssetsRecord).assets == [
        f"doc-a/assets/{name}"
    ]

    # the source drops its own copy too, and this hub no longer has a store
    (assets_dir / name).unlink()
    publish._snapshot_federation(fed_src, upper, "mid", "abc1235")  # store=None

    assert dest_record.is_file()
    assert models.load_yaml_model(dest_record, models.AssetsRecord).assets == [
        f"doc-a/assets/{name}"
    ]
    assert store.get(name) == data  # the only remaining copy


def test_hub_to_hub_second_publish_does_not_truncate_record_when_store_goes_away(
    tmp_path,
):
    """I5 (shape: record = source names ∪ this hub's own diverted names).
    A record that started as the source's names union this hub's own
    diverted names must not collapse to the source's smaller subset once
    this hub's store is disabled -- a plain file-diff on RECORD_NAME would
    overwrite dest's superset with the source's copy the moment the two
    differ, silently truncating it."""
    import hashlib

    from strata_kb import assetstore, models, publish
    from strata_kb.hub import HubHandle

    name_a = "a" * 64 + ".png"
    path_a = f"doc-a/assets/{name_a}"
    fed_src = tmp_path / "mid" / "federation"
    entry = make_fed_entry(fed_src, "repo-a", "doc-a")
    models.save_yaml_model(
        entry / assetstore.RECORD_NAME, models.AssetsRecord(assets=[path_a])
    )
    data_b = b"diverted only by the upper hub, once"
    name_b = hashlib.sha256(data_b).hexdigest() + ".png"
    path_b = f"doc-a/assets/{name_b}"
    assets_dir = entry / "doc-a" / "assets"
    assets_dir.mkdir()
    (assets_dir / name_b).write_bytes(data_b)

    upper = HubHandle(root=tmp_path / "root-hub")
    (upper.root / "federation").mkdir(parents=True)
    store = assetstore.MemoryStore()

    publish._snapshot_federation(fed_src, upper, "mid", "abc1234", store=store)
    dest_record = upper.federation_dir / "mid" / "repo-a" / assetstore.RECORD_NAME
    assert models.load_yaml_model(dest_record, models.AssetsRecord).assets == sorted(
        [path_a, path_b]
    )

    # unrelated change so the second publish is not a pure no-op, and this
    # hub's store goes away
    make_fed_entry(fed_src, "repo-c", "doc-c")
    publish._snapshot_federation(fed_src, upper, "mid", "abc1235")  # store=None

    assert models.load_yaml_model(dest_record, models.AssetsRecord).assets == sorted(
        [path_a, path_b]
    )


def test_hub_to_hub_second_publish_keeps_raw_bytes_when_source_migrates_with_no_upper_store(
    tmp_path,
):
    """I6: spec item 3 says a migrated asset must stop "looking deleted" to
    an upstream hub -- including the DEFAULT config, where the upper hub has
    no asset store at all. Measured bug: the mid hub migrates its own copy
    of an asset into its own store between two publishes; with no store
    anywhere at the upper hub, the upper hub's last committed copy of that
    asset (mirrored in on an earlier, storeless publish) got deleted on the
    very next publish, because it read as present-at-dest/absent-from-source."""
    import hashlib

    from strata_kb import assetstore, models, publish
    from strata_kb.hub import HubHandle

    data = b"upper hub's only copy, no store anywhere"
    name = hashlib.sha256(data).hexdigest() + ".png"

    fed_src = tmp_path / "mid" / "federation"
    entry = make_fed_entry(fed_src, "repo-a", "doc-a")
    assets_dir = entry / "doc-a" / "assets"
    assets_dir.mkdir()
    (assets_dir / name).write_bytes(data)

    upper = HubHandle(root=tmp_path / "root-hub")
    (upper.root / "federation").mkdir(parents=True)

    # run 1: plain mirror, no store anywhere
    _n_docs, changed, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc1234"
    )
    assert changed is True
    dest_asset = upper.federation_dir / "mid" / "repo-a" / "doc-a" / "assets" / name
    assert dest_asset.exists()

    # mid hub migrates its own copy into its own (unrelated) store between
    # publishes -- the upper hub never gains a store of its own
    (assets_dir / name).unlink()
    models.save_yaml_model(
        entry / assetstore.RECORD_NAME,
        models.AssetsRecord(assets=[f"doc-a/assets/{name}"]),
    )

    # run 2: upper hub still has no store
    publish._snapshot_federation(fed_src, upper, "mid", "abc1235")

    assert dest_asset.exists()  # upper's last committed copy must survive


def test_publish_federation_public_path_diverts_via_store_for_hub(
    tmp_path, run_git, monkeypatch
):
    """I4: publish_federation()'s only production route to the asset-store
    feature is `store_for_hub(handle)` inside _snapshot_federation -- every
    test above (and the private-function tests in test_publish_hub.py)
    injects store=store directly into _snapshot_federation, short-circuiting
    that resolution, so the fallback to store_for_hub was never exercised by
    a committed test (mutant: `active_store = store` in place of the
    store_for_hub fallback -- every hub-to-hub test stays green).

    Drives the real publish_federation() public path with no store=
    injected anywhere -- forcing `_snapshot_federation` to take the
    `assetstore.store_for_hub(handle)` branch for real. `store_for_hub`
    itself is NOT monkeypatched: the upper hub's real `.kb/config.yaml`
    declares `asset_store: mode: s3`, so store_for_hub's own body
    genuinely runs (config_mod.load_config + from_config's mode dispatch).
    Only `assetstore.S3Store` -- the class from_config would otherwise
    construct -- is swapped for an in-memory fake with the same (cfg)
    constructor shape (N7, task 21 fix round 3: not the class's own
    documented `client` constructor seam -- from_config calls `S3Store(cfg)`
    with no `client` argument, so that seam is unreachable from this public
    path; the class itself is what has to move), so this needs no
    boto3/network. A shared
    dict across instances (from_config builds a fresh S3Store per call)
    keeps the diverted bytes inspectable after publish_federation returns."""
    import hashlib

    from strata_kb import assetstore, models, publish

    data = b"public path raw bytes"
    name = hashlib.sha256(data).hexdigest() + ".png"

    captured: dict[str, bytes] = {}

    class _FakeS3Store:
        """Same (cfg) constructor shape as assetstore.S3Store, so
        assetstore.from_config's `S3Store(cfg)` call works unmodified;
        backs onto `captured` (shared across instances, since from_config
        constructs a new one per store_for_hub call) instead of a network
        call."""

        def __init__(self, cfg):
            self.data = captured

        def exists(self, name):
            return name in self.data

        def put(self, name, data):
            self.data.setdefault(name, data)

        def get(self, name):
            return self.data.get(name)

    monkeypatch.setattr(assetstore, "S3Store", _FakeS3Store)

    mid = tmp_path / "mid"
    entry = make_fed_entry(mid / "federation", "repo-a", "doc-a")
    assets_dir = entry / "doc-a" / "assets"
    assets_dir.mkdir()
    (assets_dir / name).write_bytes(data)
    (mid / ".kb").mkdir(parents=True)
    (mid / ".kb" / "config.yaml").write_text(
        "kind: hub\nrepo_id: mid\n", encoding="utf-8"
    )
    (mid / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    run_git(mid, "init")
    run_git(mid, "config", "user.name", "test")
    run_git(mid, "config", "user.email", "test@test.local")
    run_git(mid, "add", "-A")
    run_git(mid, "commit", "-m", "mid v1")

    root = tmp_path / "root-hub"
    (root / ".kb").mkdir(parents=True)
    # The upper hub's OWN config declares the store -- this is what
    # store_for_hub(handle) actually reads (F-D11 item 3's whole point:
    # active_store is resolved from the destination hub, never the source).
    (root / ".kb" / "config.yaml").write_text(
        "kind: hub\nrepo_id: root-hub\nasset_store:\n  mode: s3\n"
        "  bucket: test-bucket\n",
        encoding="utf-8",
    )
    (root / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    (root / "federation").mkdir()
    (root / "federation" / ".gitkeep").write_text("", encoding="utf-8")
    run_git(root, "init")
    run_git(root, "config", "user.name", "test")
    run_git(root, "config", "user.email", "test@test.local")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "root v1")

    report = publish.publish_federation(
        mid / ".kb", str(root), repo_id="mid", mode="direct"
    )
    assert report.n_docs == 1
    assert captured.get(name) == data
    dest_entry = root / "federation" / "mid" / "repo-a"
    assert not (dest_entry / "doc-a" / "assets" / name).exists()
    record = models.load_yaml_model(
        dest_entry / assetstore.RECORD_NAME, models.AssetsRecord
    )
    assert record.assets == [f"doc-a/assets/{name}"]


def test_hub_to_hub_store_outage_restore_does_not_touch_files_outside_the_entry(
    tmp_path, hub_worktree, run_git
):
    """N1 (task 21 fix round 2), the most serious finding: resolve_hub hands
    back the operator's own directory directly for a local-path hub -- no
    clone in between -- so _restore_federation_after_store_failure's old
    whole-`federation` pathspec ran `git checkout` + `git clean -fd` over
    the operator's real working copy, not just the entry this publish
    writes. Measured (re-review): an unrelated tracked edit elsewhere under
    federation/ got reverted, and an unrelated untracked draft got deleted.
    Scoped to federation/<rid> (the only path either call site ever writes
    under), neither should be touched."""
    import hashlib

    from strata_kb import assetstore, gitio, publish
    from strata_kb.hub import HubHandle

    # unrelated tracked file elsewhere under federation/, committed then
    # edited (uncommitted) -- must survive
    other = hub_worktree / "federation" / "other-repo" / "NOTES.md"
    other.parent.mkdir(parents=True)
    other.write_text("committed\n", encoding="utf-8")
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "add other-repo notes")
    other.write_text("operator's uncommitted edit\n", encoding="utf-8")

    # unrelated untracked draft elsewhere under federation/ -- must survive
    draft = hub_worktree / "federation" / "scratch-draft.md"
    draft.write_text("untracked draft\n", encoding="utf-8")

    data = b"store outage raw bytes -- scoped restore"
    name = hashlib.sha256(data).hexdigest() + ".png"
    fed_src = tmp_path / "mid" / "federation"
    entry = make_fed_entry(fed_src, "repo-a", "doc-a")
    assets_dir = entry / "doc-a" / "assets"
    assets_dir.mkdir()
    (assets_dir / name).write_bytes(data)

    class _FailingStore(assetstore.MemoryStore):
        def put(self, name, data):
            raise assetstore.AssetStoreError("bucket down")

    upper = HubHandle(root=hub_worktree)
    with pytest.raises(assetstore.AssetStoreError):
        publish._snapshot_federation(
            fed_src, upper, "mid", "abc1234", store=_FailingStore()
        )

    # unrelated work outside federation/mid/ survives untouched
    assert other.read_text(encoding="utf-8") == "operator's uncommitted edit\n"
    assert draft.exists()
    assert draft.read_text(encoding="utf-8") == "untracked draft\n"

    # this publish's own entry is still cleaned up
    assert not (hub_worktree / "federation" / "mid" / "repo-a").exists()
    status = gitio._run(
        hub_worktree, "status", "--porcelain", "--", "federation/mid"
    ).stdout.strip()
    assert status == ""


def test_hub_to_hub_store_outage_restore_reverts_a_tracked_record_not_just_untracked_files(
    tmp_path, hub_worktree, run_git
):
    """N2 (task 21 fix round 2): the `git checkout` half of the restore was
    deletable with the whole suite green, because every committed test only
    ever produced UNTRACKED leftovers, which `git clean -fd` alone already
    satisfies. This is the discriminating shape: a first publish commits
    repo-a's _assets.yaml (making it a TRACKED file), then a second publish
    modifies it in place (the union-merge write) before failing on a
    sibling raw asset's divert -- only `git checkout` can undo a tracked
    modification; `git clean` cannot touch it."""
    import hashlib

    from strata_kb import assetstore, gitio, models, publish
    from strata_kb.hub import HubHandle

    # real hub caches always carry core.autocrlf=false/core.eol=lf, written
    # locally by gitio.clone (gitio.py:152/361) -- hub_worktree is a plain
    # `git init` with neither, so without this a `git checkout` on Windows
    # (autocrlf=true by default) re-materialises LF-committed YAML as CRLF,
    # which is a git-config artifact this test does not care about and
    # would otherwise fail the byte-identical assertion below for a reason
    # that has nothing to do with the fix.
    run_git(hub_worktree, "config", "core.autocrlf", "false")
    run_git(hub_worktree, "config", "core.eol", "lf")

    class _FailAfter(assetstore.MemoryStore):
        def __init__(self, succeed_n):
            super().__init__()
            self.succeed_n = succeed_n
            self.calls = 0

        def put(self, name, data):
            self.calls += 1
            if self.calls > self.succeed_n:
                raise assetstore.AssetStoreError("bucket down on later put")
            super().put(name, data)

    data_x = b"first publish, diverted and committed"
    name_x = hashlib.sha256(data_x).hexdigest() + ".png"
    fed_src = tmp_path / "mid" / "federation"
    entry = make_fed_entry(fed_src, "repo-a", "doc-a")
    assets_dir = entry / "doc-a" / "assets"
    assets_dir.mkdir()
    (assets_dir / name_x).write_bytes(data_x)

    store = _FailAfter(succeed_n=1)
    upper = HubHandle(root=hub_worktree)
    _n_docs, changed, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc1", store=store
    )
    assert changed is True
    dest_record = upper.federation_dir / "mid" / "repo-a" / assetstore.RECORD_NAME
    assert store.get(name_x) == data_x
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "publish repo-a v1")
    committed_bytes = dest_record.read_bytes()

    # source gains: its OWN record naming a name it already migrated (Case
    # A -- forces the union-merge write to dest's TRACKED record) plus a
    # fresh raw asset (Case B -- the divert that fails this run)
    name_y = "b" * 64 + ".png"
    models.save_yaml_model(
        entry / assetstore.RECORD_NAME,
        models.AssetsRecord(assets=[f"doc-a/assets/{name_y}"]),
    )
    data_z = b"second publish, this one never makes it into the store"
    name_z = hashlib.sha256(data_z).hexdigest() + ".png"
    (assets_dir / name_z).write_bytes(data_z)

    with pytest.raises(assetstore.AssetStoreError):
        publish._snapshot_federation(fed_src, upper, "mid", "abc2", store=store)

    # the tracked record is back to what was committed -- not left holding
    # the union-merge's uncommitted [X, Y]
    assert dest_record.read_bytes() == committed_bytes
    assert models.load_yaml_model(dest_record, models.AssetsRecord).assets == [
        f"doc-a/assets/{name_x}"
    ]
    # the untracked raw copy of Z never makes it in either
    assert not (
        upper.federation_dir / "mid" / "repo-a" / "doc-a" / "assets" / name_z
    ).exists()
    status = gitio._run(
        hub_worktree, "status", "--porcelain", "--", "federation/mid"
    ).stdout.strip()
    assert status == ""


def test_hub_to_hub_unreadable_source_record_self_heals_instead_of_aborting(
    tmp_path, monkeypatch
):
    """N3 + m2 (task 21 fix round 2): _record_assets only self-healed
    yaml.YAMLError/ValidationError/ValueError -- unlike its twin
    assetstore._load_record, which catches bare Exception -- so an OSError
    reading fed_src's own _assets.yaml (a permission bit, a lock) used to
    propagate straight out of _reconcile_asset_records' post-apply_sync
    window, past a guard that only caught AssetStoreError. Reproduced with
    models.load_yaml_model monkeypatched to raise PermissionError for
    exactly the unreadable record's path, real for everything else -- the
    shape the re-reviewer used -- across three publishes: the sibling
    entry's genuinely raw bytes must still get diverted normally despite
    the unrelated unreadable record, on every one of them."""
    import hashlib

    from strata_kb import assetstore, models, publish
    from strata_kb.hub import HubHandle

    fed_src = tmp_path / "mid" / "federation"
    entry_a = make_fed_entry(fed_src, "repo-a", "doc-a")
    models.save_yaml_model(
        entry_a / assetstore.RECORD_NAME,
        models.AssetsRecord(assets=[f"doc-a/assets/{'a' * 64}.png"]),
    )

    data_b = b"sibling raw bytes, unreadable-record shape"
    name_b = hashlib.sha256(data_b).hexdigest() + ".png"
    entry_b = make_fed_entry(fed_src, "repo-b", "doc-b")
    assets_b = entry_b / "doc-b" / "assets"
    assets_b.mkdir()
    (assets_b / name_b).write_bytes(data_b)

    upper = HubHandle(root=tmp_path / "root-hub")
    (upper.root / "federation").mkdir(parents=True)
    store = assetstore.MemoryStore()

    unreadable_record = entry_a / assetstore.RECORD_NAME
    real_load = models.load_yaml_model

    def _flaky_load(path, model):
        if path == unreadable_record:
            raise PermissionError(f"permission denied: {path}")
        return real_load(path, model)

    monkeypatch.setattr(models, "load_yaml_model", _flaky_load)

    for source_commit in ("abc1", "abc2", "abc3"):
        publish._snapshot_federation(
            fed_src, upper, "mid", source_commit, store=store
        )

    dest_b = upper.federation_dir / "mid" / "repo-b"
    assert (dest_b / "doc-b" / "_manifest.yaml").exists()
    # the sibling's raw bytes were diverted normally, never left committed
    # as a raw binary because of the unrelated unreadable record
    assert store.get(name_b) == data_b
    assert not (dest_b / "doc-b" / "assets" / name_b).exists()


def test_hub_to_hub_reconcile_write_failure_outside_divert_still_restores_scoped(
    hub_worktree, monkeypatch, tmp_path
):
    """N3 (task 21 fix round 2), the guard-widening half: the try/except in
    _reconcile_asset_records used to wrap only divert_and_record, but the
    same per-entry loop body also runs the Case A union-merge's
    models.save_yaml_model write unconditionally -- an OSError there (a
    lock, a full disk, a permission bit) escaped with no restore attempted
    at all, unlike a store outage. Reproduced by making
    models.save_yaml_model raise for exactly the dest record it is about to
    write."""
    from strata_kb import assetstore, gitio, models, publish
    from strata_kb.hub import HubHandle

    fed_src = tmp_path / "mid" / "federation"
    entry_a = make_fed_entry(fed_src, "repo-a", "doc-a")
    # source already diverted its own copy -- Case A, forces the
    # union-merge write this test targets
    models.save_yaml_model(
        entry_a / assetstore.RECORD_NAME,
        models.AssetsRecord(assets=[f"doc-a/assets/{'b' * 64}.png"]),
    )

    upper = HubHandle(root=hub_worktree)
    store = assetstore.MemoryStore()

    dest_record = upper.federation_dir / "mid" / "repo-a" / assetstore.RECORD_NAME
    real_save = models.save_yaml_model

    def _flaky_save(path, obj):
        if path == dest_record:
            raise PermissionError(f"permission denied writing {path}")
        return real_save(path, obj)

    monkeypatch.setattr(models, "save_yaml_model", _flaky_save)

    with pytest.raises(PermissionError):
        publish._snapshot_federation(fed_src, upper, "mid", "abc1234", store=store)

    # the entry this publish was writing is cleaned up, not left half-written
    assert not (hub_worktree / "federation" / "mid").exists()
    status = gitio._run(
        hub_worktree, "status", "--porcelain", "--", "federation/mid"
    ).stdout.strip()
    assert status == ""


def test_hub_to_hub_record_survives_when_entry_stops_being_a_valid_leaf(tmp_path):
    """N4 / P18 (task 21 fix round 2): the per-entry RECORD_NAME pop and
    asset-name synthesis in _prepare_hub_to_hub_manifests both used to
    iterate federation.iter_entry_dirs, whose leaf predicate (_meta.yaml AND
    index.yaml both present) build_manifest's own plain walk does not share.
    An entry that stops being a valid leaf between two publishes (its
    _meta.yaml goes missing here -- a state federation.py explicitly
    tolerates, warned rather than rejected) then escaped both: its
    hub-owned record read as "deleted" once dest also lost _meta.yaml as a
    side effect, and the raw binary the divert had already stripped out got
    copied straight back into hub git. Reproduced across three real
    publishes with store=MemoryStore(), the shape the re-reviewer measured."""
    import hashlib

    from strata_kb import assetstore, models, publish
    from strata_kb.hub import HubHandle

    data = b"n4 raw bytes -- entry goes half-broken after this"
    name = hashlib.sha256(data).hexdigest() + ".png"

    fed_src = tmp_path / "mid" / "federation"
    entry = make_fed_entry(fed_src, "repo-a", "doc-a")
    assets_dir = entry / "doc-a" / "assets"
    assets_dir.mkdir()
    (assets_dir / name).write_bytes(data)

    upper = HubHandle(root=tmp_path / "root-hub")
    (upper.root / "federation").mkdir(parents=True)
    store = assetstore.MemoryStore()
    dest_entry = upper.federation_dir / "mid" / "repo-a"
    dest_record = dest_entry / assetstore.RECORD_NAME

    # p1: healthy publish -- diverts, store holds the only copy
    _n_docs, changed, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc1", store=store
    )
    assert changed is True
    assert store.get(name) == data
    assert dest_record.is_file()

    # the source entry stops being a valid leaf
    (entry / "_meta.yaml").unlink()

    # p2: dest's own _meta.yaml is dropped as a side effect (source no
    # longer has one) -- the record must still survive this one
    _n_docs, changed, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc2", store=store
    )
    assert changed is True
    assert not (dest_entry / "_meta.yaml").exists()
    assert dest_record.is_file()
    assert models.load_yaml_model(dest_record, models.AssetsRecord).assets == [
        f"doc-a/assets/{name}"
    ]

    # p3: the branch that broke -- record must not be deleted, and the raw
    # binary the divert already stripped out must not be copied back
    _n_docs, changed, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc3", store=store
    )
    assert dest_record.is_file()
    assert models.load_yaml_model(dest_record, models.AssetsRecord).assets == [
        f"doc-a/assets/{name}"
    ]
    assert not (dest_entry / "doc-a" / "assets" / name).exists()


def test_hub_to_hub_unreadable_dest_record_aborts_instead_of_deleting_it(
    tmp_path, hub_worktree, run_git, monkeypatch
):
    """R3 / P28 (task 21 fix round 3): P21 widened _record_assets' except to
    include OSError so an unreadable record would self-heal -- correct for
    the SOURCE side (N3), but _reconcile_asset_records also used the same
    function for the DESTINATION read. When the destination record could
    not be read, self-healing to [] made the union-merge write `inherited`
    alone (dropping whatever the unreadable file actually held), and when
    active_store was set, divert_and_record's own read of the same file
    (assetstore._load_record, bare except) ALSO saw "empty", so
    `merged == []` unlinked the hub-owned record outright -- an unreadable
    file became a deleted file. P28: never delete or overwrite data on the
    strength of a failed read of that data -- the destination read must
    abort loudly instead, leaving the tracked record exactly as it was last
    committed."""
    import hashlib

    from strata_kb import assetstore, gitio, models, publish
    from strata_kb.hub import HubHandle

    # real hub caches always carry core.autocrlf=false/core.eol=lf (see the
    # N2 test above for why a plain `git init` worktree needs this set
    # explicitly for a byte-identical restore assertion)
    run_git(hub_worktree, "config", "core.autocrlf", "false")
    run_git(hub_worktree, "config", "core.eol", "lf")

    data_y = b"r3 -- only the store will ever hold this one"
    name_y = hashlib.sha256(data_y).hexdigest() + ".png"
    fed_src = tmp_path / "mid" / "federation"
    entry = make_fed_entry(fed_src, "repo-a", "doc-a")
    assets_dir = entry / "doc-a" / "assets"
    assets_dir.mkdir()
    (assets_dir / name_y).write_bytes(data_y)

    upper = HubHandle(root=hub_worktree)
    store = assetstore.MemoryStore()

    _n_docs, changed, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc1", store=store
    )
    assert changed is True
    dest_record = upper.federation_dir / "mid" / "repo-a" / assetstore.RECORD_NAME
    assert store.get(name_y) == data_y
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "publish repo-a v1")
    committed_bytes = dest_record.read_bytes()

    # source gains its own record naming a name it already migrated (Case A
    # -- forces the reconcile loop to read the now-unreadable dest record)
    name_x = "c" * 64 + ".png"
    models.save_yaml_model(
        entry / assetstore.RECORD_NAME,
        models.AssetsRecord(assets=[f"doc-a/assets/{name_x}"]),
    )

    real_load = models.load_yaml_model

    def _flaky_load(path, model):
        if path == dest_record:
            raise PermissionError(f"permission denied: {path}")
        return real_load(path, model)

    monkeypatch.setattr(models, "load_yaml_model", _flaky_load)

    # M-1 (task 21 fix round 4): a bare pytest.raises(OSError) here left
    # `raise OSError("read failed") from exc` green too -- the ruling's
    # third clause (name the file and the way forward) was shipped but
    # unpinned. Asserting both halves of the message discriminates it.
    with pytest.raises(OSError) as exc_info:
        publish._snapshot_federation(fed_src, upper, "mid", "abc2", store=store)
    assert str(dest_record) in str(exc_info.value)
    # wave I-1 round 5, Important 1: assert the form that actually RECOVERS.
    # A bare "git checkout --" was satisfied by the index-restoring form this
    # message used to name, which returns 0 and changes nothing when the
    # corruption is in the index -- so the way-forward half of the ruling was
    # shipped broken and still pinned green. See assetstore.restore_clause.
    assert f"git checkout <commit> -- {dest_record}" in str(exc_info.value)

    # the record survives, byte-identical to what was committed -- not
    # deleted, not truncated to [name_x] alone. Read with the saved
    # unpatched loader -- monkeypatch has not been undone yet within this
    # test body, and the point being proven is the file's own bytes, not
    # another call through the still-flaky seam.
    assert dest_record.is_file()
    assert dest_record.read_bytes() == committed_bytes
    assert real_load(dest_record, models.AssetsRecord).assets == [
        f"doc-a/assets/{name_y}"
    ]
    status = gitio._run(
        hub_worktree, "status", "--porcelain", "--", "federation/mid"
    ).stdout.strip()
    assert status == ""


def test_hub_to_hub_zero_byte_dest_record_aborts_instead_of_deleting_it(
    tmp_path, hub_worktree, run_git
):
    """Important 3 (wave I-1 round 3): P47 (wave I-1 round 2) closed the
    present-but-empty deletion at assetcmd.migrate_assets and
    intake._publish_in_worktree via assetstore.load_record, but
    publish._dest_record_assets -- the DESTINATION-side reader
    _reconcile_asset_records itself uses -- had no empty check at all.
    A zero-byte destination record reads back as a *successful*, empty
    AssetsRecord (models.load_yaml_model is `yaml.safe_load(...) or {}`),
    so the OSError/YAMLError guard never fires and the caller derives
    "nothing to preserve" from a read that never actually failed.

    What this test's own setup does before the fix, measured on the parent
    commit `711d5a5` rather than described (wave I-1 round 4, Minor 2 --
    this docstring used to claim the record was "unlinked outright,
    `record after: False`", which its setup does NOT produce):

        raised           : <nothing>
        record after     : True
        record bytes     : b'assets:\\n- doc-a/assets/4fa62287...a830.png\\n'
                           b'- doc-a/assets/cccc...cccc.png\\n'
        porcelain        : 'M federation/mid/repo-a/_assets.yaml'

    Modified, not deleted: `apply_sync` re-copies the source's still-raw
    asset, so there IS something to divert, and `name_x` IS inherited, so
    the merged set is non-empty and the record is rewritten rather than
    unlinked. The guard is still load-bearing here -- removing it turns
    this test red, and the rewrite silently drops whatever the zero-byte
    file had named -- but the deletion itself needs a different shape:
    nothing left to divert AND nothing inherited. That shape is pinned by
    test_hub_to_hub_zero_byte_dest_record_with_nothing_to_divert_is_not_
    unlinked below, and was covered by no committed test until round 4."""
    import hashlib

    from strata_kb import assetstore, gitio, models, publish
    from strata_kb.hub import HubHandle

    run_git(hub_worktree, "config", "core.autocrlf", "false")
    run_git(hub_worktree, "config", "core.eol", "lf")

    data_y = b"r3 -- only the store will ever hold this one"
    name_y = hashlib.sha256(data_y).hexdigest() + ".png"
    fed_src = tmp_path / "mid" / "federation"
    entry = make_fed_entry(fed_src, "repo-a", "doc-a")
    assets_dir = entry / "doc-a" / "assets"
    assets_dir.mkdir()
    (assets_dir / name_y).write_bytes(data_y)

    upper = HubHandle(root=hub_worktree)
    store = assetstore.MemoryStore()

    _n_docs, changed, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc1", store=store
    )
    assert changed is True
    dest_record = upper.federation_dir / "mid" / "repo-a" / assetstore.RECORD_NAME
    assert store.get(name_y) == data_y
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "publish repo-a v1")

    # simulate an interrupted publish's truncated write, committed as-is --
    # no monkeypatch, this is the shape models.save_yaml_model's
    # truncate-then-write leaves behind on its own
    dest_record.write_bytes(b"")
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "simulate interrupted write")
    committed_bytes = dest_record.read_bytes()
    assert committed_bytes == b""

    # source gains its own record naming a name it already migrated (Case A
    # -- forces the reconcile loop to read the now-empty dest record)
    name_x = "c" * 64 + ".png"
    models.save_yaml_model(
        entry / assetstore.RECORD_NAME,
        models.AssetsRecord(assets=[f"doc-a/assets/{name_x}"]),
    )

    with pytest.raises(OSError) as exc_info:
        publish._snapshot_federation(fed_src, upper, "mid", "abc2", store=store)
    assert str(dest_record) in str(exc_info.value)
    assert "names no assets" in str(exc_info.value)

    # the record survives, byte-identical to what was committed -- not
    # unlinked, not overwritten with just [name_x] alone.
    assert dest_record.is_file()
    assert dest_record.read_bytes() == committed_bytes
    assert store.get(name_y) == data_y
    status = gitio._run(
        hub_worktree, "status", "--porcelain", "--", "federation/mid"
    ).stdout.strip()
    assert status == ""


def test_hub_to_hub_source_half_broken_entry_keeps_name_only_the_upper_hub_diverted(
    tmp_path,
):
    """R1 (task 21 fix round 3): _prepare_hub_to_hub_manifests' SOURCE-side
    loop (the one popping RECORD_NAME and synthesizing already-migrated
    names into src_man) reverts to federation.iter_entry_dirs(fed_src) with
    all 128 tests green when only THIS call site is mutated back -- round
    2's own red/green reverted both call sites at once, so the dest-side
    test (test_hub_to_hub_record_survives_when_entry_stops_being_a_valid_leaf,
    above) masked this half entirely.

    Mechanism: once the source entry stops being a valid leaf, the mutant
    skips it, so repo-a/_assets.yaml is never popped from src_man (it is
    kept by keep_records=True) while the dest side still pops it fine (it
    already used _iter_record_dirs). The pair then diffs as "changed",
    apply_sync overwrites dest's record with the source's raw file verbatim
    BEFORE the reconcile union-merge ever runs, and the union-merge can then
    only re-add what the clobbered copy already held. A name whose only
    surviving bytes are in the upper hub's own store -- the source never
    even knew about it -- is silently dropped."""
    import hashlib

    from strata_kb import assetstore, models, publish
    from strata_kb.hub import HubHandle

    data_y = b"r1 -- only the upper hub ever diverts this one"
    name_y = hashlib.sha256(data_y).hexdigest() + ".png"

    fed_src = tmp_path / "mid" / "federation"
    entry = make_fed_entry(fed_src, "repo-a", "doc-a")
    assets_dir = entry / "doc-a" / "assets"
    assets_dir.mkdir()
    (assets_dir / name_y).write_bytes(data_y)

    upper = HubHandle(root=tmp_path / "root-hub")
    (upper.root / "federation").mkdir(parents=True)
    store = assetstore.MemoryStore()
    dest_record = upper.federation_dir / "mid" / "repo-a" / assetstore.RECORD_NAME

    # p1: healthy publish -- the upper hub diverts Y itself, store holds the
    # only copy
    _n_docs, changed, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc1", store=store
    )
    assert changed is True
    assert store.get(name_y) == data_y

    # the source gains its own record naming an unrelated name X (Case A --
    # never diverted by the source itself, no physical bytes anywhere) and
    # stops being a valid leaf
    name_x = "d" * 64 + ".png"
    models.save_yaml_model(
        entry / assetstore.RECORD_NAME,
        models.AssetsRecord(assets=[f"doc-a/assets/{name_x}"]),
    )
    (entry / "_meta.yaml").unlink()

    # p2: the branch this test pins -- both names must survive
    _n_docs, changed, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc2", store=store
    )
    assert changed is True
    assert models.load_yaml_model(dest_record, models.AssetsRecord).assets == sorted(
        [f"doc-a/assets/{name_x}", f"doc-a/assets/{name_y}"]
    )
    assert store.get(name_y) == data_y


def test_hub_to_hub_raw_asset_arriving_under_half_broken_entry_is_diverted(tmp_path):
    """R2 (task 21 fix round 3): _reconcile_asset_records walked
    federation.iter_entry_dirs(dest) only -- the leaf predicate, which a
    half-broken entry (its _meta.yaml gone, the same tolerated state
    N4/P18 already covers) fails. A raw asset landing under such an entry
    AFTER it already has a record was therefore never visited by Case B:
    apply_sync copies it straight into the hub tree, the entry is skipped
    by the reconcile walk, and it is never diverted -- the exact C1
    signature (raw bytes committed, changed=False forever, no later publish
    repairs it), reached through the branch N4/P18 was about. Four real
    publishes, mirroring the p1/p2 shape
    test_hub_to_hub_record_survives_when_entry_stops_being_a_valid_leaf
    already uses, with a brand-new raw asset Z added at p3."""
    import hashlib

    from strata_kb import assetstore, models, publish
    from strata_kb.hub import HubHandle

    data = b"r2 first asset -- diverted while the entry is still valid"
    name = hashlib.sha256(data).hexdigest() + ".png"

    fed_src = tmp_path / "mid" / "federation"
    entry = make_fed_entry(fed_src, "repo-a", "doc-a")
    assets_dir = entry / "doc-a" / "assets"
    assets_dir.mkdir()
    (assets_dir / name).write_bytes(data)

    upper = HubHandle(root=tmp_path / "root-hub")
    (upper.root / "federation").mkdir(parents=True)
    store = assetstore.MemoryStore()
    dest_entry = upper.federation_dir / "mid" / "repo-a"
    dest_record = dest_entry / assetstore.RECORD_NAME

    # p1: healthy publish -- diverts normally, entry has a record
    _n_docs, changed, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc1", store=store
    )
    assert changed is True
    assert dest_record.is_file()

    # the source entry stops being a valid leaf
    (entry / "_meta.yaml").unlink()

    # p2: no new content -- matches the already-fixed N4/P18 shape; dest's
    # own _meta.yaml drops as a side effect too
    publish._snapshot_federation(fed_src, upper, "mid", "abc2", store=store)
    assert not (dest_entry / "_meta.yaml").exists()

    # a brand-new raw asset Z lands under the still-half-broken entry
    data_z = b"r2 second asset -- arrives after the entry goes half-broken"
    name_z = hashlib.sha256(data_z).hexdigest() + ".png"
    (assets_dir / name_z).write_bytes(data_z)

    # p3: Z must be diverted, not copied straight into the hub tree
    _n_docs, changed, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc3", store=store
    )
    assert changed is True
    assert store.get(name_z) == data_z
    assert not (dest_entry / "doc-a" / "assets" / name_z).exists()
    assert models.load_yaml_model(dest_record, models.AssetsRecord).assets == sorted(
        [f"doc-a/assets/{name}", f"doc-a/assets/{name_z}"]
    )

    # p4: confirm p3 actually repaired it -- no leftover raw file to re-copy
    _n_docs, changed, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc4", store=store
    )
    assert not (dest_entry / "doc-a" / "assets" / name_z).exists()


def test_hub_to_hub_raw_asset_under_entry_that_never_had_a_record_is_diverted_not_committed(
    tmp_path, hub_worktree, run_git
):
    """C-1 / P31 (task 21 fix round 4): the union in _reconcile_asset_records
    used to key on something an entry must already HAVE -- a valid leaf
    pair (federation.iter_entry_dirs) or an existing record
    (_iter_record_dirs). An entry with NEITHER -- an interrupted publish on
    or before its *first ever* divert, so no record was ever written, the
    brief's own motivating input -- was in no walk at all: Case B never ran
    for it, while hashsync.build_manifest (no leaf predicate) still put its
    raw asset bytes in src_man, and apply_sync copied them straight into
    the hub tree. Character for character the original Critical: a raw
    binary permanently committed into hub git, changed=False on every
    retry, never repaired (assetcmd.migrate_assets walks past it too, via
    the same federation.iter_entry_dirs). Reproduced the way the re-review
    measured it: the SOURCE entry already lacks index.yaml before its very
    first publish, so dest ends up with the brief's exact shape (_meta.yaml
    present, index.yaml absent) on the very first call -- no walk visits
    it, exactly as measured below."""
    import hashlib

    from strata_kb import assetstore, federation, gitio, models, publish
    from strata_kb.hub import HubHandle

    data = b"c1 -- entry half-broken before its first ever publish"
    name = hashlib.sha256(data).hexdigest() + ".png"

    fed_src = tmp_path / "mid" / "federation"
    entry = make_fed_entry(fed_src, "repo-a", "doc-a")
    assets_dir = entry / "doc-a" / "assets"
    assets_dir.mkdir()
    (assets_dir / name).write_bytes(data)
    # the interrupted-publish shape the brief names: _meta.yaml present,
    # index.yaml never written -- so repo-a is not a valid leaf on its very
    # first publish, and (being the first publish) has never had a record
    # either
    (entry / "index.yaml").unlink()

    upper = HubHandle(root=hub_worktree)
    store = assetstore.MemoryStore()
    dest_ns = upper.federation_dir / "mid"
    dest_entry = dest_ns / "repo-a"

    _n_docs, changed, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc1", store=store
    )
    assert changed is True

    # repo-a is still not a valid leaf (index.yaml never arrives) -- the
    # first two union members alone would still find nothing here, the
    # exact gap C-1 measured
    assert federation.iter_entry_dirs(dest_ns) == []
    # ... yet the third member reached it anyway: a record now exists,
    # proof Case B actually ran for this entry
    assert publish._iter_record_dirs(dest_ns, assetstore.RECORD_NAME) == [
        ("repo-a", dest_entry)
    ]

    raw_path = dest_entry / "doc-a" / "assets" / name
    assert store.get(name) == data
    assert not raw_path.exists()
    assert models.load_yaml_model(
        dest_entry / assetstore.RECORD_NAME, models.AssetsRecord
    ).assets == [f"doc-a/assets/{name}"]

    gitio.commit_paths(hub_worktree, "publish repo-a v1", ["federation/mid"])
    tracked = gitio._run(hub_worktree, "ls-files", "--", "federation/mid").stdout
    assert f"federation/mid/repo-a/doc-a/assets/{name}" not in tracked.splitlines()

    # p2: stable -- no-op, nothing left to repair
    _n_docs, changed2, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc2", store=store
    )
    assert changed2 is False
    assert not raw_path.exists()
    assert store.get(name) == data


def test_hub_to_hub_unreadable_untracked_dest_record_survives_the_restore(
    tmp_path, hub_worktree, run_git, monkeypatch
):
    """M-2 / P33 (task 21 fix round 4): the abort's own restore
    (_restore_federation_after_store_failure's `git clean -fd` half) used
    to delete whatever the read failure's entry held that was not yet
    tracked -- the record included, whenever the entry had never been
    committed. P28's "leaves the record untouched" claim held only for a
    tracked record (the existing abort test, byte-identical); this is the
    untracked shape the re-review measured separately: record exists, is
    unreadable, and was never committed.

    Ruling P33 first asked for a blanket cause-split (read failure ->
    checkout only, skip clean entirely). Measured unsafe before shipping
    it (see the round-4 report): apply_sync runs for the WHOLE publish
    before this loop starts, so a brand-new raw asset that lands in the
    SAME entry as a read failure survives a checkout-only restore
    untracked, then matches as "unchanged" on every retry forever -- never
    diverted, never committed, no durable copy anywhere. The narrower fix
    ships instead: `git clean` still runs, excluding only the record path
    itself (`git clean -fd -e <record>`) -- this test's own sibling files
    (doc-a's manifest/chapters, _meta.yaml) are expected to be swept along
    with everything else; only the record's survival is asserted."""
    import hashlib

    from strata_kb import assetstore, models, publish
    from strata_kb.hub import HubHandle

    data_y = b"m2 -- only the store will ever hold this one"
    name_y = hashlib.sha256(data_y).hexdigest() + ".png"
    fed_src = tmp_path / "mid" / "federation"
    entry = make_fed_entry(fed_src, "repo-a", "doc-a")
    assets_dir = entry / "doc-a" / "assets"
    assets_dir.mkdir()
    (assets_dir / name_y).write_bytes(data_y)

    upper = HubHandle(root=hub_worktree)
    store = assetstore.MemoryStore()

    # p1: diverts normally, writes the record -- deliberately left
    # UNTRACKED (no commit here), the shape that discriminates this fix
    # from the already-shipped tracked-record test
    _n_docs, changed, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc1", store=store
    )
    assert changed is True
    dest_record = upper.federation_dir / "mid" / "repo-a" / assetstore.RECORD_NAME
    assert store.get(name_y) == data_y
    assert dest_record.is_file()

    # source gains its own record naming an unrelated name X (Case A --
    # forces the reconcile loop to read the now-unreadable dest record)
    name_x = "e" * 64 + ".png"
    models.save_yaml_model(
        entry / assetstore.RECORD_NAME,
        models.AssetsRecord(assets=[f"doc-a/assets/{name_x}"]),
    )

    real_load = models.load_yaml_model

    def _flaky_load(path, model):
        if path == dest_record:
            raise PermissionError(f"permission denied: {path}")
        return real_load(path, model)

    monkeypatch.setattr(models, "load_yaml_model", _flaky_load)

    with pytest.raises(OSError):
        publish._snapshot_federation(fed_src, upper, "mid", "abc2", store=store)

    # the record survives -- not deleted by the restore's clean half, even
    # though it was untracked
    assert dest_record.is_file()
    assert real_load(dest_record, models.AssetsRecord).assets == [
        f"doc-a/assets/{name_y}"
    ]
    assert store.get(name_y) == data_y


def test_hub_to_hub_nested_record_dropped_from_union_and_reported_skipped(
    tmp_path, monkeypatch, caplog
):
    """M-3 / P34 (task 21 fix round 4): _iter_record_dirs(dest, RECORD_NAME)
    yields a candidate for a stray record NESTED below a real entry
    (`repo-a/doc-a/_assets.yaml` when `repo-a` is the entry -- R5's shape,
    e.g. a leftover from something external; nothing in this system writes
    a record one level below an entry's own root). Fed into the union as
    if it were its own entry, that candidate got walked a second time by
    divert_and_record over bytes the true entry's own pass already
    consumed -- harmless only because the parent sorts first and the
    nested record survives non-empty; a nested record that happened to be
    empty would be unlinked by the second pass. Fixed: containment (a
    proper descendant of another candidate's root is not itself an
    entry), not depth, drops it from the union and reports it in
    `skipped`. The stray record is planted directly at dest (after a
    normal first publish gives the entry its own top-level record) rather
    than mirrored down from fed_src -- source-side RECORD_NAME popping in
    _prepare_hub_to_hub_manifests would strip a mirrored copy before it
    ever reached dest, which is R5's OWN "silently dropped" half, not this
    one; this test is only about what the union does once a nested record
    already sits at the destination."""
    import hashlib

    from strata_kb import assetstore, models, publish
    from strata_kb.hub import HubHandle

    data1 = b"m3 -- first asset, diverted on the normal p1 publish"
    name1 = hashlib.sha256(data1).hexdigest() + ".png"

    fed_src = tmp_path / "mid" / "federation"
    entry = make_fed_entry(fed_src, "repo-a", "doc-a")
    assets_dir = entry / "doc-a" / "assets"
    assets_dir.mkdir()
    (assets_dir / name1).write_bytes(data1)

    upper = HubHandle(root=tmp_path / "root-hub")
    (upper.root / "federation").mkdir(parents=True)
    store = assetstore.MemoryStore()

    # p1: ordinary publish -- repo-a gets its own top-level record
    _n_docs, changed1, _skipped1 = publish._snapshot_federation(
        fed_src, upper, "mid", "abc1", store=store
    )
    assert changed1 is True
    dest_entry = upper.federation_dir / "mid" / "repo-a"
    assert (dest_entry / assetstore.RECORD_NAME).is_file()

    # a stray record, nested one level below the entry root, planted
    # directly at dest -- non-empty, so it would survive being fed to
    # divert_and_record as if it were its own entry (the shape that makes
    # this Minor rather than Critical)
    models.save_yaml_model(
        dest_entry / "doc-a" / assetstore.RECORD_NAME,
        models.AssetsRecord(assets=["doc-a/assets/" + "a" * 64 + ".png"]),
    )

    # a second raw asset arrives, forcing Case B to run again for repo-a
    data2 = b"m3 -- second asset, arrives after the stray nested record"
    name2 = hashlib.sha256(data2).hexdigest() + ".png"
    (assets_dir / name2).write_bytes(data2)

    calls: list[str] = []
    real_divert = assetstore.divert_and_record

    def _tracking_divert(dest, store_, deletes=None):
        calls.append(str(dest))
        return real_divert(dest, store_, deletes)

    monkeypatch.setattr(assetstore, "divert_and_record", _tracking_divert)

    caplog.clear()
    _n_docs, changed2, skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc2", store=store
    )

    assert changed2 is True
    # divert_and_record ran exactly once, for the real entry -- not a
    # second time for the nested "repo-a/doc-a" candidate
    assert calls == [str(dest_entry)]
    assert store.get(name2) == data2
    # the drop reaches the operator through its OWN warning naming the real
    # path and the real reason, not through PublishReport.skipped, which
    # cli._echo_publish_report renders as a ".kb/ allowlist" line (task 21
    # fix round 5, M4-1) -- and never as a file that does not exist: the
    # directory is named, not a `<dir>/_assets.yaml` the drop may not hold
    messages = [r.getMessage() for r in caplog.records]
    assert any(
        m.endswith("/repo-a/doc-a sits inside the entry 'repo-a', so it is "
                   "content, not an entry of its own -- left exactly as it is")
        for m in messages
    ), messages
    assert skipped == []
    # the stray nested record itself is untouched -- divert_assets only
    # ever strips files under an "assets/" directory
    assert models.load_yaml_model(
        dest_entry / "doc-a" / assetstore.RECORD_NAME, models.AssetsRecord
    ).assets == ["doc-a/assets/" + "a" * 64 + ".png"]


def test_hub_to_hub_already_committed_raw_asset_is_diverted_by_a_publish_with_no_other_change(
    tmp_path, hub_worktree, run_git
):
    """C4-1 / P37 (task 21 fix round 5), the re-review's Arm B: the union
    _reconcile_asset_records walks was made correct in round 4, but the
    pass is reached only when the PLAIN FILE DIFF already has work to do
    (`if not changed and not deleted and not synthesized_src_only:
    return`). Once a raw asset is already sitting at the destination with
    the same bytes as the source, src_man and dest_man agree, the diff is
    empty, and reconcile never runs at all -- so the enumeration round 4
    got right is never consulted on the publishes that matter.

    Measured shape: a marker-less entry (index.yaml never written -- an
    interrupted first publish) whose raw binary is already committed into
    hub git, i.e. every hub that ran the pre-round-4 code. `kb assets
    migrate` cannot repair it either (assetcmd.migrate_assets enumerates
    with federation.iter_entry_dirs, which walks straight past a
    marker-less entry), so before this fix the binary stayed in hub git
    forever with changed=False on every later publish -- character for
    character the Critical this task exists to close.

    Pinned the way the brief asks: the damage first, then ONE publish with
    no other change, then `git ls-files` must show no .png and the store
    must hold the bytes."""
    import hashlib

    from strata_kb import assetstore, gitio, models, publish
    from strata_kb.hub import HubHandle

    data = b"c4-1 arm B -- raw bytes already committed into hub git"
    name = hashlib.sha256(data).hexdigest() + ".png"

    fed_src = tmp_path / "mid" / "federation"
    entry = make_fed_entry(fed_src, "repo-a", "doc-a")
    assets_dir = entry / "doc-a" / "assets"
    assets_dir.mkdir()
    (assets_dir / name).write_bytes(data)
    (entry / "index.yaml").unlink()  # marker-less: iter_entry_dirs walks past it

    upper = HubHandle(root=hub_worktree)
    dest_entry = upper.federation_dir / "mid" / "repo-a"
    raw_path = dest_entry / "doc-a" / "assets" / name
    tracked_raw = f"federation/mid/repo-a/doc-a/assets/{name}"

    # p1: this hub has no store yet -- the raw binary mirrors verbatim and
    # is COMMITTED. this is the damage every pre-fix hub already holds.
    _n_docs, changed1, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc1", store=None
    )
    assert changed1 is True
    gitio.commit_paths(hub_worktree, "publish repo-a v1", ["federation/mid"])
    before = gitio._run(
        hub_worktree, "ls-files", "--", "federation/mid"
    ).stdout.splitlines()
    assert tracked_raw in before
    assert raw_path.is_file()

    # p2: the hub now HAS a store, and NOTHING else about the source
    # changed -- the plain file diff is empty
    store = assetstore.MemoryStore()
    _n_docs, changed2, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc2", store=store
    )
    assert changed2 is True
    assert store.get(name) == data
    assert not raw_path.exists()
    assert models.load_yaml_model(
        dest_entry / assetstore.RECORD_NAME, models.AssetsRecord
    ).assets == [f"doc-a/assets/{name}"]

    gitio.commit_paths(hub_worktree, "publish repo-a v2", ["federation/mid"])
    after = gitio._run(
        hub_worktree, "ls-files", "--", "federation/mid"
    ).stdout.splitlines()
    assert tracked_raw not in after
    assert "federation/mid/repo-a/_assets.yaml" in after

    # p3: stable -- nothing left to repair, and the repair does not loop
    _n_docs, changed3, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc3", store=store
    )
    assert changed3 is False
    assert not raw_path.exists()
    assert store.get(name) == data


def test_hub_to_hub_storeless_publish_then_store_arrives_diverts_on_next_publish(
    tmp_path,
):
    """C4-1 / P37, the re-review's Arm A: the same gate, reached through a
    fully valid leaf entry and a completely well-formed tree -- a hub that
    published storeless and later gained an asset store. No malformed
    state anywhere; the diff is simply empty because dest already holds
    the same bytes the source does."""
    import hashlib

    from strata_kb import assetstore, models, publish
    from strata_kb.hub import HubHandle

    data = b"c4-1 arm A -- storeless publish first, store configured later"
    name = hashlib.sha256(data).hexdigest() + ".png"

    fed_src = tmp_path / "mid" / "federation"
    entry = make_fed_entry(fed_src, "repo-a", "doc-a")
    assets_dir = entry / "doc-a" / "assets"
    assets_dir.mkdir()
    (assets_dir / name).write_bytes(data)

    upper = HubHandle(root=tmp_path / "root-hub")
    (upper.root / "federation").mkdir(parents=True)
    dest_entry = upper.federation_dir / "mid" / "repo-a"
    raw_path = dest_entry / "doc-a" / "assets" / name

    _n_docs, changed1, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc1", store=None
    )
    assert changed1 is True
    assert raw_path.is_file()

    store = assetstore.MemoryStore()
    _n_docs, changed2, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc2", store=store
    )
    assert changed2 is True
    assert store.get(name) == data
    assert not raw_path.exists()
    assert models.load_yaml_model(
        dest_entry / assetstore.RECORD_NAME, models.AssetsRecord
    ).assets == [f"doc-a/assets/{name}"]


def test_hub_to_hub_divert_that_changes_no_record_byte_still_reports_changed(
    tmp_path,
):
    """C4-1 companion: `record_changed` used to be decided purely by the
    record file's bytes before/after. A reconcile pass that physically
    REMOVES raw bytes from the hub tree but merges no new name into the
    record (the asset was already recorded -- e.g. the binary reappeared
    at dest through a merge or a restore while the record still named it)
    would then return changed=False, so _publish_direct never commits and
    the hub clone is left holding an uncommitted deletion. A publish that
    changed the destination tree must say so."""
    import hashlib

    from strata_kb import assetstore, publish
    from strata_kb.hub import HubHandle

    data = b"c4-1 companion -- recorded already, raw byte came back"
    name = hashlib.sha256(data).hexdigest() + ".png"

    fed_src = tmp_path / "mid" / "federation"
    entry = make_fed_entry(fed_src, "repo-a", "doc-a")
    assets_dir = entry / "doc-a" / "assets"
    assets_dir.mkdir()
    (assets_dir / name).write_bytes(data)

    upper = HubHandle(root=tmp_path / "root-hub")
    (upper.root / "federation").mkdir(parents=True)
    store = assetstore.MemoryStore()
    dest_entry = upper.federation_dir / "mid" / "repo-a"

    _n_docs, changed1, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc1", store=store
    )
    assert changed1 is True
    record_before = (dest_entry / assetstore.RECORD_NAME).read_bytes()

    raw_path = dest_entry / "doc-a" / "assets" / name
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(data)

    _n_docs, changed2, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc2", store=store
    )
    assert not raw_path.exists()
    assert (dest_entry / assetstore.RECORD_NAME).read_bytes() == record_before
    assert changed2 is True


def test_hub_to_hub_namespace_record_never_evicts_the_reader_visible_leaf_entry(
    tmp_path, monkeypatch
):
    """C4-2 / P39 (task 21 fix round 5), shape (a). Round 4's P34
    containment filter drops any candidate that is a proper descendant of
    another candidate's root -- structurally true, and backwards in the
    one case that matters, because it has no notion of which candidate is
    AUTHORITATIVE. A legacy namespace-level `_assets.yaml` (precisely the
    artefact the old `kb assets migrate` bug left behind, as
    assetcmd._rid_dirs' own docstring records) makes _iter_record_dirs
    yield the namespace ABOVE a real entry -- and the real entry is then
    what gets deleted from the union, and reported to the operator as
    skipped. The new asset's bytes get stripped into the store while the
    record every reader consults (federation.iter_entry_dirs ->
    <entry>/_assets.yaml, fixed by spec 11.2) never learns its name.

    P39: a directory federation.iter_entry_dirs yields is an entry BY
    DEFINITION and must always be its own divert root; a candidate that is
    a proper ANCESTOR of such a leaf is not an entry at all."""
    import hashlib

    from strata_kb import assetstore, federation, models, publish
    from strata_kb.hub import HubHandle

    data1 = b"c4-2(a) -- first asset, diverted by the ordinary p1 publish"
    name1 = hashlib.sha256(data1).hexdigest() + ".png"

    fed_src = tmp_path / "mid" / "federation"
    entry = make_fed_entry(fed_src / "ns", "repo-a", "doc-a")
    assets_dir = entry / "doc-a" / "assets"
    assets_dir.mkdir()
    (assets_dir / name1).write_bytes(data1)

    upper = HubHandle(root=tmp_path / "root-hub")
    (upper.root / "federation").mkdir(parents=True)
    store = assetstore.MemoryStore()

    _n_docs, changed1, _skipped1 = publish._snapshot_federation(
        fed_src, upper, "mid", "abc1", store=store
    )
    assert changed1 is True
    dest = upper.federation_dir / "mid"
    dest_entry = dest / "ns" / "repo-a"
    assert [pid for pid, _ in federation.iter_entry_dirs(dest)] == ["ns/repo-a"]
    assert (dest_entry / assetstore.RECORD_NAME).is_file()

    # the legacy artefact: a record one level ABOVE the entry, naming the
    # asset at namespace-relative depth
    models.save_yaml_model(
        dest / "ns" / assetstore.RECORD_NAME,
        models.AssetsRecord(assets=[f"repo-a/doc-a/assets/{name1}"]),
    )

    data2 = b"c4-2(a) -- second asset, arrives while the legacy record sits above"
    name2 = hashlib.sha256(data2).hexdigest() + ".png"
    (assets_dir / name2).write_bytes(data2)

    calls: list[str] = []
    real_divert = assetstore.divert_and_record

    def _tracking_divert(dest_, store_, deletes=None):
        calls.append(str(dest_))
        return real_divert(dest_, store_, deletes)

    monkeypatch.setattr(assetstore, "divert_and_record", _tracking_divert)

    _n_docs, changed2, skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc2", store=store
    )

    assert changed2 is True
    # the leaf is the divert root -- the namespace above it is not
    assert calls == [str(dest_entry)]
    # ... and the leaf is never reported to the operator as dropped
    assert "ns/repo-a/_assets.yaml" not in skipped
    assert store.get(name2) == data2
    # the record every reader consults learned the new name, at the depth
    # spec 11.2 fixes
    assert models.load_yaml_model(
        dest_entry / assetstore.RECORD_NAME, models.AssetsRecord
    ).assets == sorted([f"doc-a/assets/{name1}", f"doc-a/assets/{name2}"])


def test_hub_to_hub_stray_namespace_assets_dir_does_not_evict_the_leaf_entry(
    tmp_path, monkeypatch
):
    """C4-2 / P39, shape (b) -- the arm the re-review measured as a
    REGRESSION introduced by round 4's own third union member, which
    manufactures the namespace candidate out of a stray `assets/`
    directory sitting at namespace depth. Before round 4 the entry was
    diverted correctly and the stray simply stayed raw (bad, but bounded);
    after it, the real entry lost its record entirely. The stray staying
    raw is the accepted outcome here -- the leaf losing its record is
    not."""
    import hashlib

    from strata_kb import assetstore, models, publish
    from strata_kb.hub import HubHandle

    data1 = b"c4-2(b) -- first asset of the real entry"
    name1 = hashlib.sha256(data1).hexdigest() + ".png"

    fed_src = tmp_path / "mid" / "federation"
    entry = make_fed_entry(fed_src / "ns", "repo-a", "doc-a")
    assets_dir = entry / "doc-a" / "assets"
    assets_dir.mkdir()
    (assets_dir / name1).write_bytes(data1)

    upper = HubHandle(root=tmp_path / "root-hub")
    (upper.root / "federation").mkdir(parents=True)
    store = assetstore.MemoryStore()

    _n_docs, changed1, _skipped1 = publish._snapshot_federation(
        fed_src, upper, "mid", "abc1", store=store
    )
    assert changed1 is True
    dest = upper.federation_dir / "mid"
    dest_entry = dest / "ns" / "repo-a"

    # the stray arrives the only way it can survive at dest: through the
    # SOURCE tree (anything at dest with no counterpart in fed_src is
    # deleted by apply_sync as an ordinary mirror deletion, long before
    # the reconcile pass ever sees it)
    data_j = b"c4-2(b) -- a stray asset at namespace depth, next to the entry"
    name_j = hashlib.sha256(data_j).hexdigest() + ".png"
    src_stray = fed_src / "ns" / "junk" / "assets" / name_j
    src_stray.parent.mkdir(parents=True)
    src_stray.write_bytes(data_j)
    stray = dest / "ns" / "junk" / "assets" / name_j

    data2 = b"c4-2(b) -- second asset of the real entry"
    name2 = hashlib.sha256(data2).hexdigest() + ".png"
    (assets_dir / name2).write_bytes(data2)

    calls: list[str] = []
    real_divert = assetstore.divert_and_record

    def _tracking_divert(dest_, store_, deletes=None):
        calls.append(str(dest_))
        return real_divert(dest_, store_, deletes)

    monkeypatch.setattr(assetstore, "divert_and_record", _tracking_divert)

    _n_docs, changed2, _skipped2 = publish._snapshot_federation(
        fed_src, upper, "mid", "abc2", store=store
    )

    assert changed2 is True
    assert calls == [str(dest_entry)]
    assert not (dest / "ns" / assetstore.RECORD_NAME).exists()
    assert models.load_yaml_model(
        dest_entry / assetstore.RECORD_NAME, models.AssetsRecord
    ).assets == sorted([f"doc-a/assets/{name1}", f"doc-a/assets/{name2}"])
    # bounded, as before round 4: the stray is left exactly where it is
    assert stray.is_file()


def test_restore_after_store_failure_protects_a_record_whose_path_has_glob_metacharacters(
    tmp_path, hub_worktree, run_git
):
    """I4-1 / P38 (task 21 fix round 5): the restore's
    `git clean -fd -e <record>` half passes the record's path as a
    GITIGNORE PATTERN, not a literal path. Measured on git 2.45.1: with
    `[`/`]` in a path segment the character class matched a DIFFERENT
    directory, so the exclusion protected the wrong path and deleted the
    one it was added for -- defeat and widening in a single run, on the
    one code path whose entire purpose is "never delete on the strength of
    a failed read" (P28).

    Both halves are asserted: the target survives AND the bystander whose
    name the character class accidentally matched is still swept."""
    from strata_kb import publish
    from strata_kb.hub import HubHandle

    handle = HubHandle(root=hub_worktree)
    dest = handle.federation_dir / "mid"
    target_dir = dest / "a[b]c"
    bystander_dir = dest / "abc"
    (target_dir / "doc-a" / "assets").mkdir(parents=True)
    bystander_dir.mkdir(parents=True)

    protect = target_dir / "_assets.yaml"
    protect.write_text("assets: []\n", encoding="utf-8")
    bystander = bystander_dir / "_assets.yaml"
    bystander.write_text("assets: []\n", encoding="utf-8")
    sibling = target_dir / "doc-a" / "assets" / ("a" * 64 + ".png")
    sibling.write_bytes(b"raw bytes the restore must still sweep")

    publish._restore_federation_after_store_failure(handle, dest, protect=protect)

    assert protect.is_file(), "the protected record was deleted by the clean"
    assert not bystander.exists(), "a different record was wrongly spared"
    assert not sibling.exists(), "the ordinary cleaned set was not swept"


def test_restore_after_store_failure_does_not_raise_when_protect_is_outside_the_root(
    tmp_path, hub_worktree, run_git
):
    """I4-1, second half: `protect.resolve().relative_to(handle.root
    .resolve())` can raise ValueError, which would replace the original
    OSError mid-restore and break this function's documented contract
    ("best-effort ... never raises on its own"). The `checkout` half
    already carries the equivalent guard."""
    from strata_kb import publish
    from strata_kb.hub import HubHandle

    handle = HubHandle(root=hub_worktree)
    dest = handle.federation_dir / "mid"
    dest.mkdir(parents=True)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    protect = outside / "_assets.yaml"
    protect.write_text("assets: []\n", encoding="utf-8")

    publish._restore_federation_after_store_failure(handle, dest, protect=protect)

    assert protect.is_file()


def test_hub_to_hub_entry_level_assets_dir_is_diverted_not_left_raw(tmp_path):
    """M4-3 (task 21 fix round 5): assetstore.divert_assets defines
    divertible as any `rglob("assets/*")` file matching the
    content-addressed name at ANY depth, and pubgate.is_kb_artifact's
    asset rule is explicitly depth-independent -- so `<entry>/assets/
    <sha>.png` mirrors to the destination, and the plain-publish path
    (_snapshot -> divert_and_record(dest)) diverts it correctly. Only the
    hub-to-hub path disagreed: round 4's third union member computed the
    entry root by a fixed `<entry>/<doc-id>/assets/<name>` arithmetic, so
    this placement resolved to the walk root and was silently skipped --
    raw bytes committed, changed=False forever."""
    import hashlib

    from strata_kb import assetstore, models, publish
    from strata_kb.hub import HubHandle

    data = b"m4-3 -- an assets/ directory at entry level, above doc level"
    name = hashlib.sha256(data).hexdigest() + ".png"

    fed_src = tmp_path / "mid" / "federation"
    entry = make_fed_entry(fed_src, "repo-a", "doc-a")
    (entry / "assets").mkdir()
    (entry / "assets" / name).write_bytes(data)
    (entry / "index.yaml").unlink()  # marker-less, so no leaf shortcut applies

    upper = HubHandle(root=tmp_path / "root-hub")
    (upper.root / "federation").mkdir(parents=True)
    store = assetstore.MemoryStore()
    dest_entry = upper.federation_dir / "mid" / "repo-a"

    _n_docs, changed, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc1", store=store
    )
    assert changed is True
    assert store.get(name) == data
    assert not (dest_entry / "assets" / name).exists()
    assert models.load_yaml_model(
        dest_entry / assetstore.RECORD_NAME, models.AssetsRecord
    ).assets == [f"assets/{name}"]


def test_hub_to_hub_asset_at_the_walk_root_is_reported_not_silently_dropped(
    tmp_path, caplog
):
    """M4-3, the other placement: `<dest>/assets/<sha>.png` has no entry
    to attribute it to at all (diverting it would write a record at
    namespace depth -- exactly the wrong-depth artefact spec 11.2
    forbids). Leaving it raw is the right call; leaving it raw SILENTLY is
    not -- a thing the system drops must be a thing the operator can see
    it dropped."""
    import hashlib

    from strata_kb import assetstore, publish
    from strata_kb.hub import HubHandle

    data = b"m4-3 -- an assets/ directory at the walk root itself"
    name = hashlib.sha256(data).hexdigest() + ".png"

    fed_src = tmp_path / "mid" / "federation"
    entry = make_fed_entry(fed_src, "repo-a", "doc-a")
    assets_dir = entry / "doc-a" / "assets"
    assets_dir.mkdir()
    other = hashlib.sha256(b"other").hexdigest() + ".png"
    (assets_dir / other).write_bytes(b"other")

    upper = HubHandle(root=tmp_path / "root-hub")
    (upper.root / "federation").mkdir(parents=True)
    store = assetstore.MemoryStore()

    _n_docs, changed1, _skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc1", store=store
    )
    assert changed1 is True

    # planted on the SOURCE: pubgate.is_kb_artifact's asset rule is
    # depth-independent, so `assets/<sha>.png` at the federation root
    # mirrors down like any other artefact. (Planting it at dest alone
    # would just be deleted by apply_sync as absent-from-source.)
    src_stray = fed_src / "assets" / name
    src_stray.parent.mkdir(parents=True)
    src_stray.write_bytes(data)
    stray = upper.federation_dir / "mid" / "assets" / name

    caplog.clear()
    publish._snapshot_federation(fed_src, upper, "mid", "abc2", store=store)

    assert stray.is_file()
    assert store.get(name) is None
    messages = [r.getMessage() for r in caplog.records]
    assert any(f"assets/{name}" in m for m in messages), messages
    assert not (upper.federation_dir / "mid" / assetstore.RECORD_NAME).exists()


def test_hub_to_hub_deeper_than_usual_asset_is_attributed_to_its_leaf_entry(
    tmp_path, monkeypatch, caplog
):
    """M4-1 (task 21 fix round 5), first half. Round 4 computed the entry
    root of a divertible file by a fixed `<entry>/<doc-id>/assets/<name>`
    arithmetic, so an asset one level deeper
    (`<entry>/<doc-id>/sub/assets/<name>` -- legal: divert_assets matches
    `assets/*` at ANY depth and pubgate.is_kb_artifact's asset rule is
    depth-independent) manufactured a candidate BELOW the real entry. The
    containment filter then dropped it and reported
    `repo-a/doc-a/_assets.yaml` as skipped -- naming a file that has never
    existed, while the only record that does exist is `repo-a/
    _assets.yaml`. Telling an operator a file was skipped that was never
    there is how warnings stop being read.

    Fixed at the source: a candidate is attributed to the nearest
    enclosing federation.iter_entry_dirs leaf when there is one (ruling
    P39's authority half), so no below-entry candidate is manufactured and
    nothing is dropped or reported at all."""
    import hashlib

    from strata_kb import assetstore, models, publish
    from strata_kb.hub import HubHandle

    data = b"m4-1 -- an asset one level deeper than the usual layout"
    name = hashlib.sha256(data).hexdigest() + ".png"

    fed_src = tmp_path / "mid" / "federation"
    entry = make_fed_entry(fed_src, "repo-a", "doc-a")
    deep = entry / "doc-a" / "sub" / "assets"
    deep.mkdir(parents=True)
    (deep / name).write_bytes(data)

    upper = HubHandle(root=tmp_path / "root-hub")
    (upper.root / "federation").mkdir(parents=True)
    store = assetstore.MemoryStore()
    dest_entry = upper.federation_dir / "mid" / "repo-a"

    calls: list[str] = []
    real_divert = assetstore.divert_and_record

    def _tracking_divert(dest_, store_, deletes=None):
        calls.append(str(dest_))
        return real_divert(dest_, store_, deletes)

    monkeypatch.setattr(assetstore, "divert_and_record", _tracking_divert)

    caplog.clear()
    _n_docs, changed, skipped = publish._snapshot_federation(
        fed_src, upper, "mid", "abc1", store=store
    )

    assert changed is True
    assert calls == [str(dest_entry)]
    assert store.get(name) == data
    assert models.load_yaml_model(
        dest_entry / assetstore.RECORD_NAME, models.AssetsRecord
    ).assets == [f"doc-a/sub/assets/{name}"]
    assert skipped == []
    # nothing was dropped, so nothing may be reported as dropped -- in
    # particular not a `repo-a/doc-a` that holds no record of its own
    messages = [r.getMessage() for r in caplog.records]
    assert not any("doc-a sits inside" in m for m in messages), messages


# --- wave I-1 round 4: the Critical's three doors ---------------------------
#
# Round 3 gave assetstore.load_record a per-entry name-shape check and a
# trailing-newline check and left publish._dest_record_assets without them.
# Measured end to end afterwards, that asymmetry did not merely fail to
# help: it DELETED hub-owned records. _dest_record_assets accepted a record
# load_record rejected, so nothing aborted and nothing was restored; the same
# loop then called assetstore.divert_and_record, whose own read of the SAME
# file went through load_record, raised, and was swallowed by that function's
# deliberate self-heal (existing = []); with nothing left to re-divert the
# merged set was empty and the record was unlinked outright -- porcelain
# "D federation/mid/repo-a/_assets.yaml", exit 0, the object store left
# holding the only copy of what it had named.
#
# Every one of these drives a REAL hub-to-hub publish with real git and no
# monkeypatch, and asserts the record survives byte-identical with clean
# porcelain -- the P47-correct outcome, not merely "a message was printed".


def _hub_to_hub_v1(tmp_path, hub_worktree, run_git):
    """One completed hub-to-hub publish: the upper hub holds a committed
    record naming an asset only its store still has, and nothing raw is left
    on either side for a later publish to divert. Returns everything the
    door tests need in order to corrupt one thing and publish again."""
    import hashlib

    from strata_kb import assetstore, publish
    from strata_kb.hub import HubHandle

    run_git(hub_worktree, "config", "core.autocrlf", "false")
    run_git(hub_worktree, "config", "core.eol", "lf")

    data_y = b"round 4 -- only the store will ever hold this one"
    name_y = hashlib.sha256(data_y).hexdigest() + ".png"
    fed_src = tmp_path / "mid" / "federation"
    entry = make_fed_entry(fed_src, "repo-a", "doc-a")
    assets_dir = entry / "doc-a" / "assets"
    assets_dir.mkdir()
    (assets_dir / name_y).write_bytes(data_y)

    upper = HubHandle(root=hub_worktree)
    store = assetstore.MemoryStore()
    publish._snapshot_federation(fed_src, upper, "mid", "abc1", store=store)
    dest_record = upper.federation_dir / "mid" / "repo-a" / assetstore.RECORD_NAME
    assert dest_record.is_file() and store.get(name_y) == data_y
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "publish repo-a v1")

    # the source migrated its own copy too -- the steady state once both
    # tiers have a store. Nothing raw is left anywhere for a later publish to
    # re-divert, which is what makes the merged set empty and the unlink
    # reachable at all.
    (assets_dir / name_y).unlink()
    assets_dir.rmdir()
    return fed_src, entry, upper, store, dest_record, name_y, data_y


def _ordinary_content_edit(entry):
    """The plainest possible next publish: one unrelated markdown file in the
    entry changed. Nothing about assets, nothing about records -- and it is
    all it takes to make _snapshot_federation run the reconcile pass over
    this entry, which is why the deletion below is not an exotic shape."""
    doc = entry / "doc-a" / "ch1.md"
    doc.write_text(
        doc.read_text(encoding="utf-8") + "\nnew paragraph.\n", encoding="utf-8"
    )


def _fed_porcelain(hub_worktree):
    from strata_kb import gitio

    return gitio._run(
        hub_worktree, "status", "--porcelain", "--", "federation/mid"
    ).stdout.strip()


def test_hub_to_hub_truncated_dest_record_survives_an_ordinary_publish(
    tmp_path, hub_worktree, run_git
):
    """Door A. A destination record truncated mid-path -- the exact corruption
    round 3's name-shape check was added to detect -- went from "survives,
    partially readable" to "deleted, exit 0" on the commit that added the
    detector. Measured before this fix, on this setup: publish raised
    nothing, dest record after: False, porcelain
    "D federation/mid/repo-a/_assets.yaml"."""
    from strata_kb import publish

    fed_src, entry, upper, store, dest_record, name_y, data_y = _hub_to_hub_v1(
        tmp_path, hub_worktree, run_git
    )
    full = dest_record.read_bytes()
    dest_record.write_bytes(full[: len(full) - 14])  # mid-hex-name, no boundary
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "simulate an interrupted write")
    committed = dest_record.read_bytes()
    _ordinary_content_edit(entry)

    with pytest.raises(OSError) as exc_info:
        publish._snapshot_federation(fed_src, upper, "mid", "abc2", store=store)
    assert str(dest_record) in str(exc_info.value)
    assert "not a content-addressed asset name" in str(exc_info.value)

    assert dest_record.is_file()
    assert dest_record.read_bytes() == committed
    assert store.get(name_y) == data_y
    assert _fed_porcelain(hub_worktree) == ""


def test_hub_to_hub_newline_stripped_dest_record_survives_an_ordinary_publish(
    tmp_path, hub_worktree, run_git
):
    """Door B. Same route, through the other of round 3's two checks: every
    name in the record is valid, only the file's final newline is gone.
    Before this fix that record was not merely accepted -- it was DELETED,
    where the code before round 3 had silently repaired it (porcelain "M").
    A fix that turns "repaired" into "deleted" for its own motivating input
    is worse than no fix, which is why this is pinned as its own test rather
    than folded into the one above."""
    from strata_kb import publish

    fed_src, entry, upper, store, dest_record, name_y, data_y = _hub_to_hub_v1(
        tmp_path, hub_worktree, run_git
    )
    full = dest_record.read_bytes()
    assert full.endswith(b"\n")  # sanity: a real write always does
    dest_record.write_bytes(full[:-1])
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "simulate an interrupted write")
    committed = dest_record.read_bytes()
    _ordinary_content_edit(entry)

    with pytest.raises(OSError) as exc_info:
        publish._snapshot_federation(fed_src, upper, "mid", "abc2", store=store)
    assert "does not end with a trailing newline" in str(exc_info.value)

    assert dest_record.is_file()
    assert dest_record.read_bytes() == committed
    assert store.get(name_y) == data_y
    assert _fed_porcelain(hub_worktree) == ""


def test_hub_to_hub_truncated_source_record_is_not_merged_into_the_hub_record(
    tmp_path, hub_worktree, run_git, caplog
):
    """Door C, which neither of the two checks above can close. The
    DESTINATION record is perfect and reads back cleanly; the corruption is
    upstream, in fed_src's own record, and reaches the hub through Case A's
    union merge. _record_assets is fully lenient by design (upstream data
    this hub does not own must not fail a publish), so pre-fix the mangled
    name was written INTO the hub-owned record, and
    assetstore.divert_and_record's read of that freshly-written file then
    rejected it, self-healed to [], and unlinked it -- measured before this
    fix: dest record after: False, porcelain
    "D federation/mid/repo-a/_assets.yaml", exit 0.

    The fix drops the untransferable name at the merge (it could never have
    been carried up anyway -- assetstore.synthesized_asset_entries skips
    exactly these names) and warns, rather than raising: an upstream record
    must still not be able to fail this hub's publish."""
    from strata_kb import assetstore, models, publish

    fed_src, entry, upper, store, dest_record, name_y, data_y = _hub_to_hub_v1(
        tmp_path, hub_worktree, run_git
    )
    committed = dest_record.read_bytes()
    truncated = f"doc-a/assets/{name_y[:20]}"
    models.save_yaml_model(
        entry / assetstore.RECORD_NAME,
        models.AssetsRecord(assets=[f"doc-a/assets/{name_y}", truncated]),
    )

    publish._snapshot_federation(fed_src, upper, "mid", "abc2", store=store)

    assert dest_record.is_file()
    assert dest_record.read_bytes() == committed
    # and it still reads back through the very reader whose refusal used to
    # be the trigger for the deletion
    assert assetstore.load_record(dest_record.parent).assets == [
        f"doc-a/assets/{name_y}"
    ]
    assert store.get(name_y) == data_y
    assert _fed_porcelain(hub_worktree) == ""
    # the drop is visible: a thing the system drops must be a thing the
    # operator can see it dropped (this module's own rule)
    assert any(
        r.name == "strata_kb.publish"
        and truncated in r.getMessage()
        and "not merged into" in r.getMessage()
        for r in caplog.records
    )


def test_hub_to_hub_zero_byte_dest_record_with_nothing_to_divert_is_not_unlinked(
    tmp_path, hub_worktree, run_git
):
    """Minor 2 (wave I-1 round 4): round 3's own zero-byte test documents an
    unlink its setup does not actually produce -- replayed without the guard,
    that setup leaves the record MODIFIED, not deleted, because apply_sync
    re-copies the source's still-raw asset and there is something to divert
    after all. This is the shape that really unlinks: nothing left to divert,
    nothing inherited, so the merged set is empty and divert_and_record
    deletes the file outright. It was covered by no committed test; round 3's
    present-but-empty check is what closes it."""
    from strata_kb import publish

    fed_src, entry, upper, store, dest_record, name_y, data_y = _hub_to_hub_v1(
        tmp_path, hub_worktree, run_git
    )
    dest_record.write_bytes(b"")
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "simulate an interrupted write")
    _ordinary_content_edit(entry)

    with pytest.raises(OSError) as exc_info:
        publish._snapshot_federation(fed_src, upper, "mid", "abc2", store=store)
    assert "names no assets" in str(exc_info.value)

    assert dest_record.is_file()
    assert dest_record.read_bytes() == b""
    assert store.get(name_y) == data_y
    assert _fed_porcelain(hub_worktree) == ""


def test_hub_to_hub_dir_shaped_dest_record_aborts_when_the_plain_diff_is_empty(
    tmp_path, hub_worktree, run_git
):
    """Minor 1 (wave I-1 round 4): round 3's not-a-regular-file guard on the
    DESTINATION side shipped inert -- "if False and record_path.exists():"
    left the whole federation suite green, because no test anywhere put a
    non-regular file at a destination record path.

    Reaching it needs one non-obvious ingredient, measured rather than
    guessed: hashsync.apply_sync ends by rmdir-ing every empty directory
    under dest, so on any publish whose plain file diff is non-empty the
    directory-shaped record is swept away BEFORE the reconcile pass ever
    reads it (measured: the guard never fires, and a tracked file inside the
    directory is deleted as a stray first). Only a publish that skips
    apply_sync entirely -- reached here through synthesized_src_only, a
    source record naming an asset already diverted, with no plain file
    changed -- gets the directory to the guard. That is exactly the publish
    shape Case A exists for, so the guard is reachable, not decorative.

    The directory is left EMPTY for the same measured reason: a file inside
    it is a file under dest, so it lands in the destination manifest, comes
    back as a deletion, and makes the plain diff non-empty -- which puts
    apply_sync back in front of the guard. An empty directory is invisible
    to both git and the manifest, so it is also the shape most likely to
    survive unnoticed on a real hub."""
    from strata_kb import assetstore, models, publish

    fed_src, entry, upper, store, dest_record, name_y, data_y = _hub_to_hub_v1(
        tmp_path, hub_worktree, run_git
    )
    models.save_yaml_model(
        entry / assetstore.RECORD_NAME,
        models.AssetsRecord(assets=[f"doc-a/assets/{name_y}"]),
    )
    dest_record.unlink()
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "record lost; a directory takes its place")
    dest_record.mkdir()

    with pytest.raises(OSError) as exc_info:
        publish._snapshot_federation(fed_src, upper, "mid", "abc2", store=store)
    assert str(dest_record) in str(exc_info.value)
    assert "is not a regular file" in str(exc_info.value)

    # nothing at that path was removed or replaced -- restore-or-remove-it is
    # the operator's call, not this code's
    assert dest_record.is_dir()
    assert store.get(name_y) == data_y
