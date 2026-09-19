from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from strata_kb import assetstore, config, models


NAME_PNG = "a" * 64 + ".png"
NAME_WEBP = "b" * 64 + ".webp"


def test_memory_store_roundtrip():
    store = assetstore.MemoryStore()
    assert not store.exists(NAME_PNG)
    assert store.get(NAME_PNG) is None
    store.put(NAME_PNG, b"PNGDATA")
    assert store.exists(NAME_PNG)
    assert store.get(NAME_PNG) == b"PNGDATA"


def test_from_config_none_and_s3():
    assert assetstore.from_config(config.AssetStoreConfig()) is None
    cfg = config.AssetStoreConfig(mode="s3", bucket="kb-assets")
    store = assetstore.from_config(cfg)
    assert isinstance(store, assetstore.S3Store)


def test_s3_mode_requires_bucket():
    with pytest.raises(assetstore.AssetStoreError, match="bucket"):
        assetstore.from_config(config.AssetStoreConfig(mode="s3"))


class _FakeClientError(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}


class _StubS3Client:
    """Stands in for boto3's S3 client — records calls, no network."""

    def __init__(self):
        self.objects: dict[str, dict] = {}
        self.put_calls: list[str] = []

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise _FakeClientError("404")
        return {}

    def put_object(self, Bucket, Key, Body, ContentType, CacheControl):
        self.objects[Key] = {
            "Body": Body, "ContentType": ContentType, "CacheControl": CacheControl,
        }
        self.put_calls.append(Key)

    def get_object(self, Bucket, Key):
        import io

        if Key not in self.objects:
            raise _FakeClientError("NoSuchKey")
        return {"Body": io.BytesIO(self.objects[Key]["Body"])}


def _s3(client):
    cfg = config.AssetStoreConfig(mode="s3", bucket="kb-assets", prefix="assets/")
    return assetstore.S3Store(cfg, client=client)


def test_s3_put_sets_metadata_and_prefix():
    client = _StubS3Client()
    _s3(client).put(NAME_PNG, b"PNGDATA")
    obj = client.objects[f"assets/{NAME_PNG}"]
    assert obj["ContentType"] == "image/png"
    assert "immutable" in obj["CacheControl"]


def test_s3_put_skips_existing_key():
    client = _StubS3Client()
    store = _s3(client)
    store.put(NAME_WEBP, b"X")
    store.put(NAME_WEBP, b"X")
    assert client.put_calls == [f"assets/{NAME_WEBP}"]


def test_s3_get_and_exists_and_miss():
    client = _StubS3Client()
    store = _s3(client)
    assert store.get(NAME_PNG) is None
    assert not store.exists(NAME_PNG)
    store.put(NAME_PNG, b"PNGDATA")
    assert store.exists(NAME_PNG)
    assert store.get(NAME_PNG) == b"PNGDATA"


def test_s3_non_missing_error_wraps_as_assetstoreerror():
    class _Boom:
        def head_object(self, Bucket, Key):
            raise _FakeClientError("AccessDenied")

    with pytest.raises(assetstore.AssetStoreError):
        _s3(_Boom()).exists(NAME_PNG)


def test_missing_boto3_names_the_extra(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def block(name, *a, **kw):
        if name.startswith("boto3"):
            raise ImportError(name)
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", block)
    cfg = config.AssetStoreConfig(mode="s3", bucket="kb-assets")
    store = assetstore.S3Store(cfg)  # construction OK — import is lazy
    with pytest.raises(assetstore.AssetStoreError, match=r"strata-kb\[s3\]"):
        store.exists(NAME_PNG)


def test_store_for_hub_reads_hub_config(tmp_path):
    from strata_kb.hub import HubHandle

    kb = tmp_path / ".kb"
    kb.mkdir()
    handle = HubHandle(root=tmp_path)
    assert assetstore.store_for_hub(handle) is None  # no config file → none
    (kb / "config.yaml").write_text(
        "asset_store:\n  mode: s3\n  bucket: kb-assets\n", encoding="utf-8"
    )
    assert isinstance(assetstore.store_for_hub(handle), assetstore.S3Store)


# Real content hashes: spec A guarantees filename sha == sha256(bytes), and
# Task 7's round-trip test depends on this fixture honoring that invariant.
SHA_A = hashlib.sha256(b"A").hexdigest()
SHA_B = hashlib.sha256(b"B").hexdigest()
SHA_C = hashlib.sha256(b"C").hexdigest()


def _tree(tmp_path: Path) -> Path:
    root = tmp_path / "rid"
    (root / "doc1" / "assets").mkdir(parents=True)
    (root / "doc1" / "assets" / f"{SHA_A}.png").write_bytes(b"A")
    (root / "doc1" / "assets" / f"{SHA_B}.webp").write_bytes(b"B")
    (root / "doc1" / "ch1-intro.md").write_text("x", encoding="utf-8")
    (root / "doc1" / "assets" / "notes.txt").write_bytes(b"skip me")
    return root


def test_divert_assets_uploads_strips_and_skips_nonassets(tmp_path):
    root = _tree(tmp_path)
    store = assetstore.MemoryStore()
    diverted = assetstore.divert_assets(root, store)
    assert diverted == [
        f"doc1/assets/{SHA_A}.png",
        f"doc1/assets/{SHA_B}.webp",
    ]
    assert store.get(f"{SHA_A}.png") == b"A"
    assert store.get(f"{SHA_B}.webp") == b"B"
    assert not (root / "doc1" / "assets" / f"{SHA_A}.png").exists()
    assert (root / "doc1" / "assets" / "notes.txt").exists()  # not an asset name
    assert (root / "doc1" / "ch1-intro.md").exists()


def test_divert_assets_prunes_empty_assets_dir(tmp_path):
    root = tmp_path / "rid"
    (root / "doc2" / "assets").mkdir(parents=True)
    (root / "doc2" / "assets" / f"{SHA_C}.png").write_bytes(b"C")
    assetstore.divert_assets(root, assetstore.MemoryStore())
    assert not (root / "doc2" / "assets").exists()


def test_divert_and_record_merges_with_existing_and_deletes(tmp_path):
    root = _tree(tmp_path)
    old = f"doc0/assets/{SHA_C}.png"
    gone = f"doc9/assets/{'d' * 64}.png"
    models.save_yaml_model(
        root / assetstore.RECORD_NAME,
        models.AssetsRecord(assets=[old, gone]),
    )
    assetstore.divert_and_record(root, assetstore.MemoryStore(), deletes=[gone])
    rec = models.load_yaml_model(root / assetstore.RECORD_NAME, models.AssetsRecord)
    assert rec.assets == sorted(
        [old, f"doc1/assets/{SHA_A}.png", f"doc1/assets/{SHA_B}.webp"]
    )


def test_divert_and_record_corrupt_record_treated_as_empty(tmp_path):
    """divert_and_record's OWN read stays lenient on purpose (P32): this is
    the function publish._snapshot calls directly, with no pre-check, for
    every plain child publish, and that call site was measured
    byte-identical whether or not the old record can be read (see
    load_record's docstring) -- apply_assets re-diverts every currently
    live byte regardless. Do not "fix" this test into expecting a raise."""
    root = _tree(tmp_path)
    (root / assetstore.RECORD_NAME).write_text("{{not yaml", encoding="utf-8")
    assetstore.divert_and_record(root, assetstore.MemoryStore())
    rec = models.load_yaml_model(root / assetstore.RECORD_NAME, models.AssetsRecord)
    assert f"doc1/assets/{SHA_A}.png" in rec.assets


def test_divert_and_record_unreadable_record_self_heals_not_raises(tmp_path, monkeypatch):
    """Same contract as the corrupt-record test above, for OSError instead
    of bad YAML -- load_record now raises AssetStoreError for both (P32),
    and divert_and_record must keep shielding its own callers from that."""
    root = _tree(tmp_path)
    record_path = root / assetstore.RECORD_NAME
    models.save_yaml_model(record_path, models.AssetsRecord(assets=[]))
    real_load = models.load_yaml_model

    def _flaky_load(path, model):
        if path == record_path:
            raise PermissionError(f"permission denied: {path}")
        return real_load(path, model)

    monkeypatch.setattr(models, "load_yaml_model", _flaky_load)
    diverted = assetstore.divert_and_record(root, assetstore.MemoryStore())
    assert diverted == [f"doc1/assets/{SHA_A}.png", f"doc1/assets/{SHA_B}.webp"]


def test_load_record_absent_is_empty(tmp_path):
    root = tmp_path / "rid"
    root.mkdir()
    assert assetstore.load_record(root).assets == []


def test_load_record_raises_on_unreadable_record(tmp_path, monkeypatch):
    root = tmp_path / "rid"
    root.mkdir()
    record_path = root / assetstore.RECORD_NAME
    models.save_yaml_model(record_path, models.AssetsRecord(assets=["doc/assets/x.png"]))

    def _flaky_load(path, model):
        raise PermissionError(f"permission denied: {path}")

    monkeypatch.setattr(models, "load_yaml_model", _flaky_load)
    with pytest.raises(assetstore.AssetStoreError, match=re.escape(str(record_path))):
        assetstore.load_record(root)


def test_load_record_raises_on_corrupt_yaml(tmp_path):
    """P32's own decision: corrupt YAML is folded into the same raise as
    unreadable, not treated as absent -- measured (see this round's
    report) that nothing in this tree relies on a corrupt hub-owned record
    silently reading back empty, and publish._dest_record_assets --
    already implementing P28 correctly -- has drawn this exact line."""
    root = tmp_path / "rid"
    root.mkdir()
    (root / assetstore.RECORD_NAME).write_text("{{not yaml", encoding="utf-8")
    with pytest.raises(assetstore.AssetStoreError):
        assetstore.load_record(root)


def test_load_record_raises_on_record_that_parses_but_fails_schema(tmp_path):
    """Valid YAML, wrong shape (a mapping instead of the `assets:` list) --
    a pydantic ValidationError, not a yaml.YAMLError. Folded into the same
    raise as the other two failure shapes for the same reason."""
    root = tmp_path / "rid"
    root.mkdir()
    (root / assetstore.RECORD_NAME).write_text("assets: not-a-list\n", encoding="utf-8")
    with pytest.raises(assetstore.AssetStoreError):
        assetstore.load_record(root)


@pytest.mark.parametrize(
    "content", [b"", b"\n", b"{}\n"], ids=["zero-byte", "whitespace-only", "empty-mapping"]
)
def test_load_record_raises_on_present_but_empty_record(tmp_path, content):
    """Critical 1 (wave I-1 round 2, P47): models.load_yaml_model is
    `yaml.safe_load(...) or {}`, so all three of these shapes parse as a
    SUCCESSFUL read of an empty AssetsRecord -- the OSError/YAMLError/
    ValidationError guard above never fires. Before this fix, that meant a
    caller merging on top of this read (divert_and_record's own lenient
    read, reached without a pre-flight at assetcmd.migrate_assets and
    intake._publish_in_worktree before P32/this round) derived "nothing to
    preserve" from a record that was never actually confirmed empty, and
    unlinked it while the object store still held the only copy of what it
    named. No monkeypatch: `models.save_yaml_model` truncates before
    writing (no temp-file-and-rename), so this is exactly the file an
    interrupted publish, a full disk, or a crash leaves behind."""
    root = tmp_path / "rid"
    root.mkdir()
    (root / assetstore.RECORD_NAME).write_bytes(content)
    with pytest.raises(assetstore.AssetStoreError, match="names no assets"):
        assetstore.load_record(root)


def test_load_record_a_legitimately_empty_entry_still_reads_back_empty(tmp_path):
    """The other half of P47: an entry whose assets were all removed must
    still work. divert_and_record already represents "nothing left" by
    DELETING the record rather than writing `assets: []` (see its
    docstring) -- so the legitimate case never reaches the new empty-check
    above at all; it takes the unchanged `not record_path.is_file()`
    branch, exactly like a record that was never written in the first
    place. Driven through the real merge-and-delete path, not just the
    absent-file unit test above."""
    root = _tree(tmp_path)
    gone = f"doc1/assets/{SHA_A}.png"
    other_gone = f"doc1/assets/{SHA_B}.webp"
    assetstore.divert_and_record(root, assetstore.MemoryStore())
    record_path = root / assetstore.RECORD_NAME
    assert record_path.is_file()  # sanity: the first divert wrote a record

    # a second pass with nothing new to divert and both names deleted --
    # the merge empties out, and divert_and_record unlinks rather than
    # writing an empty file.
    assetstore.divert_and_record(
        root, assetstore.MemoryStore(), deletes=[gone, other_gone]
    )
    assert not record_path.exists()
    assert assetstore.load_record(root).assets == []


def test_load_record_dir_shaped_record_raises_instead_of_reading_absent(tmp_path):
    """Important 1 (wave I-1 round 3), replacing this test's old shape.

    Round 2's premise for choosing is_file() over exists() here -- "exists()
    swallows a failed stat and reports False" -- does not reproduce:
    exists() and is_file() share the exact same OSError handling for a
    failed stat (measured, CPython 3.11.15's `_ignore_error`), so this
    test used to pin a divergence between them (a lying `Path.exists`
    monkeypatch) that cannot actually occur. The real divergence is a
    record path that EXISTS but is not a regular file -- in practice, a
    directory. There exists() is True and is_file() is False, and ruling
    P47 says an EXISTING record path is evidence names existed; only its
    ABSENCE may read as "nothing to preserve". Reading a directory-shaped
    record as absent (the shape round 2 shipped) let a caller divert past
    it and then fail writing the record onto the directory path -- an
    uncaught PermissionError, past migrate's own AssetStoreError-only
    restore guard, with the raw bytes already unlinked. This needs no
    monkeypatch: a directory at the record path is a real, reachable shape
    (a bad archive extraction, a sync tool, an operator `mkdir`)."""
    root = tmp_path / "rid"
    root.mkdir()
    record_path = root / assetstore.RECORD_NAME
    record_path.mkdir()
    with pytest.raises(assetstore.AssetStoreError, match=re.escape(str(record_path))):
        assetstore.load_record(root)


def test_load_record_raises_on_record_truncated_mid_path(tmp_path):
    """Important 2 (wave I-1 round 3): "truncated mid-list is
    indistinguishable from a deliberately shorter list" (round 2's own
    documented gap, endorsed by the re-review) was measured false --
    truncation lands mid-path, not on an entry boundary, because
    models.save_yaml_model's write is not atomic. A record cut inside an
    entry's hex name is still valid YAML and still a non-empty list, but
    its last entry is a mangled name (`doc2/assets/<partial-hex>`, not
    `<sha256>.(png|webp)`) that survives to become this function's return
    value unless caught -- assetstore._ASSET_NAME_RE, the same regex
    divert_assets already uses to decide what counts as a recorded name,
    catches it (measured: 395 of the 404 offsets of a real 423-byte
    5-asset record that survive the empty check, see load_record's
    docstring)."""
    root = tmp_path / "rid"
    root.mkdir()
    record_path = root / assetstore.RECORD_NAME
    models.save_yaml_model(
        record_path,
        models.AssetsRecord(
            assets=[f"doc1/assets/{SHA_A}.png", f"doc2/assets/{SHA_B}.png"]
        ),
    )
    full = record_path.read_bytes()
    cut = full.index(SHA_B.encode()) + 8  # mid-hex-name, not on a line boundary
    record_path.write_bytes(full[:cut])
    with pytest.raises(
        assetstore.AssetStoreError, match="not a content-addressed asset name"
    ):
        assetstore.load_record(root)


@pytest.mark.parametrize(
    "asset",
    [
        "doc-a/assets/{sha}.png",
        "doc-a/assets/{sha}.webp",
        "tài-liệu/assets/{sha}.png",
        "a/b/c/d/e/f/g/h/i/j/assets/{sha}.png",
        "./doc-a/assets/{sha}.png",
        "C:/kb/doc-a/assets/{sha}.png",
        "{sha}.png",
    ],
    ids=[
        "png", "webp", "unicode-doc-id", "deeply-nested",
        "dot-slash-prefix", "windows-drive-prefix", "bare-filename",
    ],
)
def test_load_record_accepts_every_legal_path_shape(tmp_path, asset):
    """The mirror of publish's test of the same name (wave I-1 round 5,
    Critical): this reader had NO legal-shape coverage at all, which is part
    of why the platform split lived here for two rounds unseen. The
    name-shape check keys on the entry's basename, never on the directory
    part, so every legal spelling of a path to a content-addressed asset
    still reads back."""
    root = tmp_path / "rid"
    root.mkdir()
    entry = asset.format(sha=SHA_A)
    models.save_yaml_model(
        root / assetstore.RECORD_NAME, models.AssetsRecord(assets=[entry])
    )
    assert assetstore.load_record(root).assets == [entry]


@pytest.mark.parametrize(
    "asset",
    ["doc-a\\assets\\{sha}.png", "doc-a/assets\\{sha}.png"],
    ids=["all-backslashes", "mixed-separators"],
)
def test_load_record_rejects_a_backslash_spelled_entry_on_every_host(
    tmp_path, asset
):
    """The mirror of publish's rejection test, and the half of the Critical
    that is NOT new in round 4: this reader has keyed on `Path(a).name` since
    round 3, so a backslash-spelled hub record already read back fine on a
    Windows hub and raised on a Linux one. Round 3 simply shipped no test
    asserting either answer, so CI stayed green and nobody saw it. Both
    readers now answer the same on every host, and both say no -- see
    assetstore.asset_sha's docstring for the two pre-existing rulings that
    decide which way."""
    root = tmp_path / "rid"
    root.mkdir()
    entry = asset.format(sha=SHA_A)
    assert assetstore._ASSET_NAME_RE.match(PureWindowsPath(entry).name)
    assert not assetstore._ASSET_NAME_RE.match(PurePosixPath(entry).name)
    models.save_yaml_model(
        root / assetstore.RECORD_NAME, models.AssetsRecord(assets=[entry])
    )
    with pytest.raises(
        assetstore.AssetStoreError, match="not a content-addressed asset name"
    ):
        assetstore.load_record(root)


def test_every_load_record_refusal_names_the_recovery_that_works(tmp_path):
    """Wave I-1 round 5, Important 1: all four of this reader's hard
    refusals route their way-forward through assetstore.restore_clause, so
    none of them can drift back to `git checkout -- <path>` -- the form that
    restores from the index, which is where the corruption is, and therefore
    exits 0 having done nothing (measured; see restore_clause's docstring,
    and tests/test_publish.py's end-to-end run of both commands).

    The not-a-regular-file arm is deliberately not in this list: something
    that is not a file at the record path may not be tracked at all, so
    remove-or-restore-whatever-is-there is the right instruction and a git
    checkout is not."""
    root = tmp_path / "rid"
    root.mkdir()
    record_path = root / assetstore.RECORD_NAME
    good = f"assets:\n- doc1/assets/{SHA_A}.png\n"
    shapes = {
        "corrupt-yaml": "assets: [unclosed\n",
        "present-but-empty": "",
        "mangled-name": "assets:\n- doc1/assets/mangled\n",
        "no-trailing-newline": good.rstrip("\n"),
    }
    for label, text in shapes.items():
        record_path.write_text(text, encoding="utf-8")
        with pytest.raises(assetstore.AssetStoreError) as excinfo:
            assetstore.load_record(root)
        msg = str(excinfo.value)
        # the commands spelled out, NOT `restore_clause(record_path) in msg` --
        # that would move with the mutation and pass for any clause at all
        assert f"git log --oneline -- {record_path}" in msg, label
        assert f"git checkout <commit> -- {record_path}" in msg, label
        # and all four arms go through the one helper, so they cannot drift
        assert assetstore.restore_clause(record_path) in msg, label


def test_asset_sha_takes_the_basename_with_posix_semantics_on_every_host():
    """The mechanism the two tests above pin, at the unit level (ruling P49).

    `Path` binds to WindowsPath or PosixPath depending on the interpreter,
    and those two disagree about exactly one input class. asset_sha must not
    inherit that disagreement, in either direction: it must not start reading
    backslashes as separators on Linux, and it must not keep reading them as
    separators on Windows."""
    assert assetstore.asset_sha(f"doc-a/assets/{SHA_A}.png") == SHA_A
    assert assetstore.asset_sha(f"{SHA_A}.webp") == SHA_A
    assert assetstore.asset_sha(f"doc-a\\assets\\{SHA_A}.png") is None
    assert assetstore.is_asset_name(f"a/b/assets/{SHA_B}.png")
    assert not assetstore.is_asset_name(f"doc-a/assets/{SHA_B[:8]}")
    # and the answer is the POSIX one, stated without depending on the host
    for entry in (f"doc-a\\assets\\{SHA_A}.png", f"doc-a/assets\\{SHA_A}.png"):
        assert assetstore.asset_sha(entry) is None
        assert assetstore._ASSET_NAME_RE.match(PureWindowsPath(entry).name)


def test_load_record_raises_on_record_missing_trailing_newline(tmp_path):
    """Important 2's other measured check: the 5 (of 404 surviving)
    truncation offsets that land exactly on an entry boundary -- so every
    remaining entry is a complete, valid asset name -- but cut off the
    file's final newline, which models.save_yaml_model's yaml.safe_dump
    always writes. Complements the name-shape check above (together: 400
    of 404); a record whose own content does not end in a newline is
    evidence of a truncated write even when every entry it does contain
    still parses as a legitimate name."""
    root = tmp_path / "rid"
    root.mkdir()
    record_path = root / assetstore.RECORD_NAME
    models.save_yaml_model(
        record_path, models.AssetsRecord(assets=[f"doc1/assets/{SHA_A}.png"])
    )
    full = record_path.read_bytes()
    assert full.endswith(b"\n")  # sanity: a real write always does
    record_path.write_bytes(full[:-1])
    with pytest.raises(
        assetstore.AssetStoreError, match="does not end with a trailing newline"
    ):
        assetstore.load_record(root)


def test_snapshot_plain_child_publish_self_heals_an_unreadable_dest_record(
    tmp_path, monkeypatch
):
    """Minor 3 (wave I-1 round 2): divert_and_record's own lenient read is
    reasoned about in its docstring as safe for publish._snapshot -- its
    actual caller for every plain child publish, with no pre-check -- but
    nothing in the tree drove that call site for real with an unreadable
    dest record; making divert_and_record strict only turned unit-level
    tests red (Minor 3's own finding). This goes through _snapshot itself:
    the child's live .kb/ still holds the asset byte-for-byte, so
    apply_sync re-copies it into dest before divert_and_record ever runs,
    and the self-healed-to-empty old record is rebuilt correctly from what
    divert_assets finds on disk -- nothing is lost even though the read
    that fed the merge failed."""
    from strata_kb import publish
    from strata_kb.hub import HubHandle

    kb_abs = tmp_path / "child" / ".kb"
    kb_abs.mkdir(parents=True)
    models.save_yaml_model(kb_abs / "index.yaml", models.KBIndex())
    data = b"minor-3 -- a real _snapshot call site"
    name = hashlib.sha256(data).hexdigest() + ".png"
    (kb_abs / "doc1" / "assets").mkdir(parents=True)
    (kb_abs / "doc1" / "assets" / name).write_bytes(data)
    (kb_abs / "doc1" / "ch1.md").write_text(f"![x](assets/{name})\n", encoding="utf-8")

    handle = HubHandle(root=tmp_path / "hub")
    handle.federation_dir.mkdir(parents=True)
    dest = handle.federation_dir / "rid-a"
    dest.mkdir(parents=True)
    record_path = dest / assetstore.RECORD_NAME
    stale = f"doc0/assets/{'c' * 64}.png"
    models.save_yaml_model(record_path, models.AssetsRecord(assets=[stale]))

    real_load = models.load_yaml_model

    def _flaky(path, model):
        if path == record_path:
            raise PermissionError(f"permission denied: {path}")
        return real_load(path, model)

    monkeypatch.setattr(models, "load_yaml_model", _flaky)

    store = assetstore.MemoryStore()
    n_docs, changed, _skipped = publish._snapshot(
        kb_abs, handle, "rid-a", "c0ffee", source_url="https://example.test/child.git",
        store=store,
    )
    assert changed is True
    assert n_docs == 0

    monkeypatch.undo()
    rec = models.load_yaml_model(record_path, models.AssetsRecord)
    assert rec.assets == [f"doc1/assets/{name}"]  # rebuilt from the tree, not merged
    assert stale not in rec.assets  # unreadable old record -- self-healed, not preserved
    assert store.get(name) == data


def test_synthesized_asset_entries_self_heals_unreadable_record(tmp_path, monkeypatch):
    """Feeds a manifest diff, never a write (publish._snapshot,
    intake.hub_manifest) -- self-healing to empty here only makes the diff
    treat those assets as changed, which a subsequent divert rebuilds
    correctly. Must not let load_record's raise escape."""
    root = tmp_path / "rid"
    root.mkdir()
    models.save_yaml_model(
        root / assetstore.RECORD_NAME,
        models.AssetsRecord(assets=[f"doc1/assets/{SHA_A}.png"]),
    )

    def _flaky_load(path, model):
        raise PermissionError(f"permission denied: {path}")

    monkeypatch.setattr(models, "load_yaml_model", _flaky_load)
    assert assetstore.synthesized_asset_entries(root) == {}


def test_synthesized_asset_entries_uses_filename_sha(tmp_path):
    root = tmp_path / "rid"
    root.mkdir()
    models.save_yaml_model(
        root / assetstore.RECORD_NAME,
        models.AssetsRecord(assets=[f"doc1/assets/{SHA_A}.png"]),
    )
    entries = assetstore.synthesized_asset_entries(root)
    assert entries == {f"doc1/assets/{SHA_A}.png": SHA_A}


def test_synthesized_asset_entries_empty_when_no_record(tmp_path):
    root = tmp_path / "rid"
    root.mkdir()
    assert assetstore.synthesized_asset_entries(root) == {}


def _named(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest() + ".png"


def test_verify_bytes_accepts_matching_content():
    data = b"real image bytes"
    assert assetstore.verify_bytes(_named(data), data) is True


def test_verify_bytes_rejects_tampered_content():
    data = b"real image bytes"
    assert assetstore.verify_bytes(_named(data), b"tampered") is False


def test_get_verified_refuses_a_tampered_object():
    data = b"real image bytes"
    name = _named(data)
    store = assetstore.MemoryStore()
    store.data[name] = b"tampered"
    with pytest.raises(assetstore.AssetStoreError, match="does not match its name"):
        assetstore.get_verified(store, name)


def test_get_verified_returns_a_clean_object():
    data = b"real image bytes"
    name = _named(data)
    store = assetstore.MemoryStore()
    store.put(name, data)
    assert assetstore.get_verified(store, name) == data


def test_get_verified_passes_a_miss_through():
    store = assetstore.MemoryStore()
    assert assetstore.get_verified(store, _named(b"absent")) is None


def test_divert_then_synthesis_roundtrip_no_rediff(tmp_path):
    from strata_kb import hashsync

    child = _tree(tmp_path)  # child-side snapshot (assets present)
    dest = tmp_path / "dest"
    local_man = hashsync.build_manifest(child)
    changed, deleted = hashsync.diff_manifests(local_man, {})
    hashsync.apply_sync(child, dest, changed, deleted)
    assetstore.divert_and_record(dest, assetstore.MemoryStore(), deleted)

    hub_man = hashsync.build_manifest(dest, exclude=("_meta.yaml", assetstore.RECORD_NAME))
    hub_man.update(assetstore.synthesized_asset_entries(dest))
    changed2, deleted2 = hashsync.diff_manifests(local_man, hub_man)
    assert changed2 == [] and deleted2 == []


LINK_CLAUSE = (
    "is not a regular file -- it may be a directory, or a link whose "
    "target is gone"
)


def make_dangling_link(path: Path) -> str | None:
    """Put a link at `path` whose target does not exist. Returns a short
    description of what kind of link was created, or None when this machine
    can create neither kind (the caller should skip).

    Two kinds are attempted because no single one is portable. A real POSIX
    symlink is preferred and is what CI on Linux exercises; Windows refuses
    os.symlink without SeCreateSymbolicLinkPrivilege (`WinError 1314, A
    required privilege is not held by the client` -- measured on this
    machine, Developer Mode off, no elevation), so there it falls back to an
    NTFS junction created through `mklink /J`, whose target is then removed.
    Both present the shape this is about: exists() False, is_file() False,
    os.path.lexists() True.
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
    """Undo make_dangling_link. A junction is a directory entry (os.rmdir); a
    dangling symlink is not (os.unlink). Neither is left for the tmp_path
    teardown to guess at."""
    for remove in (os.rmdir, os.unlink):
        try:
            remove(path)
            return
        except OSError:
            continue


def test_load_record_dangling_link_at_the_record_path_raises_instead_of_reading_absent(
    tmp_path,
):
    """Minor 4 (wave I-1 round 4): the P47 hole one shape over from the
    directory-shaped record above. Path.exists() and Path.is_file() both
    FOLLOW a link, so a link at the record path whose target is gone reads
    back exists()=False -- ABSENT -- while something is very much sitting
    there. Measured with a broken NTFS junction on this machine, on both
    this reader and publish._dest_record_assets: exists=False, is_file=False,
    lexists=True, and both returned [] before this fix -- the same "nothing
    to preserve" answer that P47 exists to refuse, and the same one that
    flows on into divert_and_record unlinking the record. os.path.lexists()
    asks the question P47 actually asks -- is anything at this name -- and
    closes it.

    Not a regression introduced by round 3; it behaved identically before.
    It is listed with the round-4 Critical because it reaches the same
    deletion by the same route."""
    root = tmp_path / "rid"
    root.mkdir()
    record_path = root / assetstore.RECORD_NAME
    kind = make_dangling_link(record_path)
    if kind is None:  # pragma: no cover - depends on the host's privileges
        pytest.skip("this machine can create neither a symlink nor a junction")
    try:
        assert not record_path.exists()  # the trap: "absent" by exists()
        assert os.path.lexists(record_path)  # but something IS there
        # the whole shared clause, not just its first half -- wave I-1 round
        # 5, Minor 1: round 4 added "or a link whose target is gone" here
        # and not to publish._dest_record_assets' matching message, and
        # reverting it left 38 tests passing. Both readers now pin it.
        with pytest.raises(assetstore.AssetStoreError) as excinfo:
            assetstore.load_record(root)
        msg = str(excinfo.value)
        # spelled out, NOT `not_a_regular_file_clause(record_path) in msg` --
        # that moves with the mutation and passes for any clause at all
        assert LINK_CLAUSE in msg
        # and both readers go through the one helper, so they cannot drift
        assert assetstore.not_a_regular_file_clause(record_path) in msg
    finally:
        remove_dangling_link(record_path)


def test_load_record_names_every_mangled_entry_not_just_the_first(tmp_path):
    """Nit 2 (wave I-1 round 4): the name-shape refusal reported `bad[0]`
    only, so a record with several mangled entries told the operator about
    one of them and left the rest to be discovered one failed retry at a
    time. Capped at assetstore.BAD_NAMES_SHOWN so a wholly-garbled record
    cannot turn one error line into a dump of its whole contents."""
    root = tmp_path / "rid"
    root.mkdir()
    bad = [f"doc1/assets/mangled-{i}" for i in range(assetstore.BAD_NAMES_SHOWN + 2)]
    models.save_yaml_model(
        root / assetstore.RECORD_NAME,
        models.AssetsRecord(assets=[f"doc1/assets/{SHA_A}.png", *bad]),
    )
    with pytest.raises(assetstore.AssetStoreError) as exc_info:
        assetstore.load_record(root)
    message = str(exc_info.value)
    for name in bad[: assetstore.BAD_NAMES_SHOWN]:
        assert repr(name) in message
    assert "(and 2 more)" in message
    assert "none of which is a content-addressed asset name" in message
    # the one good name is not paraded through the error message
    assert SHA_A not in message
