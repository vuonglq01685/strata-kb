# S3 Asset Delivery (Spec B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Divert content-addressed image assets to an S3-compatible object store at the publish boundary, keep hub git text-only, and serve the bytes through the existing authenticated `/assets` route.

**Architecture:** A new `assetstore.py` owns the store seam (`S3Store` via lazy boto3, `MemoryStore` for tests), the divert-and-record helper, and manifest-entry synthesis from `_assets.yaml` (filename sha == content sha, per spec A). Divert runs on the **destination** tree after `hashsync.apply_sync` — one uniform pattern for intake, direct, and pr transports — always before any git commit. The `/assets` route gains a local → store → disk-cache fallthrough.

**Tech Stack:** Python ≥3.11, pydantic, boto3 (optional `s3` extra, lazy import), Starlette, pytest.

**Spec:** `docs/superpowers/specs/2026-07-16-s3-asset-delivery-design.md`

## Global Constraints

- Run all tests with `.venv/bin/python -m pytest` from the repo root.
- Tests hermetic: no boto3 import required in CI, no network. `S3Store` tests inject a stubbed client; everything else uses `MemoryStore`.
- `mode: none` (the default) must leave every existing behavior bit-for-bit unchanged — the full existing suite passes untouched.
- Asset names are always the bare `<sha256>.<png|webp>` filename; the store applies the configured `prefix` (default `assets/`).
- Upload failure aborts the publish/intake **before any git commit**; binaries never silently enter git.
- `_assets.yaml` is a hub-side artifact: excluded from hub manifests handed to children (like `_meta.yaml`) and protected from child-sent deletes.
- Record updates are a **merge**: (existing record) ∪ (newly diverted) − (this publish's deletes).
- boto3 lives behind the new extra `s3 = ["boto3>=1.34"]`; missing boto3 raises a clear error naming `pip install "center-kb[s3]"` at first use, not at import.
- Commit messages: `<type>: <description>`, no attribution footer.

---

### Task 1: `AssetStoreConfig` in config.py

**Files:**
- Modify: `src/center_kb/config.py` (KBConfig at lines 22-26)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `config.AssetStoreConfig` (pydantic BaseModel: `mode: Literal["none","s3"] = "none"`, `bucket: str = ""`, `region: str = ""`, `endpoint: str = ""`, `prefix: str = "assets/"`); `KBConfig.asset_store: AssetStoreConfig` (defaulted). Later tasks read `load_config(kb_dir).asset_store`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_config.py`, matching its existing style)

```python
def test_asset_store_defaults_to_none(tmp_path):
    (tmp_path / "config.yaml").write_text("hub: '.'\n", encoding="utf-8")
    cfg = config.load_config(tmp_path)
    assert cfg.asset_store.mode == "none"
    assert cfg.asset_store.prefix == "assets/"


def test_asset_store_parses_s3_block(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "hub: '.'\n"
        "asset_store:\n"
        "  mode: s3\n"
        "  bucket: kb-assets\n"
        "  region: ap-southeast-1\n"
        "  endpoint: https://minio.local:9000\n",
        encoding="utf-8",
    )
    store_cfg = config.load_config(tmp_path).asset_store
    assert store_cfg.mode == "s3"
    assert store_cfg.bucket == "kb-assets"
    assert store_cfg.region == "ap-southeast-1"
    assert store_cfg.endpoint == "https://minio.local:9000"
    assert store_cfg.prefix == "assets/"


def test_asset_store_rejects_unknown_mode(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "asset_store:\n  mode: ftp\n", encoding="utf-8"
    )
    with pytest.raises(Exception):
        config.load_config(tmp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_config.py -v -k asset_store`
Expected: FAIL — `AttributeError: 'KBConfig' object has no attribute 'asset_store'` (and the reject test fails because no validation exists)

- [ ] **Step 3: Implement**

In `src/center_kb/config.py`, add above `KBConfig`:

```python
class AssetStoreConfig(BaseModel):
    """Object-store settings for image assets (spec B). Credentials never
    live here — boto3's standard chain (env / instance role) supplies them."""

    mode: Literal["none", "s3"] = "none"
    bucket: str = ""
    region: str = ""
    endpoint: str = ""  # S3-compatible endpoint (MinIO, R2); empty = AWS
    prefix: str = "assets/"
```

and extend `KBConfig`:

```python
class KBConfig(BaseModel):
    hub: str = ""
    repo_id: str = ""
    kind: Literal["", "hub", "child"] = ""
    intake: str = ""  # intake service base URL — child publishes via OIDC CI
    asset_store: AssetStoreConfig = AssetStoreConfig()
```

(`from pydantic import BaseModel` and `Literal` are already imported.)

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/config.py tests/test_config.py
git commit -m "feat: asset_store config block (mode none|s3)"
```

---

### Task 2: `assetstore.py` — store seam, S3Store, MemoryStore

**Files:**
- Create: `src/center_kb/assetstore.py`
- Modify: `pyproject.toml` (add `s3` extra)
- Test: `tests/test_assetstore.py`

**Interfaces:**
- Consumes: `config.AssetStoreConfig` (Task 1); `hub.HubHandle.kb_dir` (existing).
- Produces: `AssetStoreError(RuntimeError)`; `MemoryStore()` with `.data: dict[str, bytes]`; `S3Store(cfg, client=None)`; all stores expose `exists(name) -> bool`, `put(name, data: bytes) -> None`, `get(name) -> bytes | None`; `from_config(cfg: AssetStoreConfig) -> AssetStore | None` (None when mode none); `store_for_hub(handle) -> AssetStore | None` (reads `load_config(handle.kb_dir).asset_store`).

- [ ] **Step 1: Add the extra**

In `pyproject.toml` under `[project.optional-dependencies]` add:

```toml
s3 = ["boto3>=1.34"]
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_assetstore.py`:

```python
from __future__ import annotations

import pytest

from center_kb import assetstore, config


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
    with pytest.raises(assetstore.AssetStoreError, match=r"center-kb\[s3\]"):
        store.exists(NAME_PNG)


def test_store_for_hub_reads_hub_config(tmp_path):
    from center_kb.hub import HubHandle

    kb = tmp_path / ".kb"
    kb.mkdir()
    handle = HubHandle(root=tmp_path)
    assert assetstore.store_for_hub(handle) is None  # no config file → none
    (kb / "config.yaml").write_text(
        "asset_store:\n  mode: s3\n  bucket: kb-assets\n", encoding="utf-8"
    )
    assert isinstance(assetstore.store_for_hub(handle), assetstore.S3Store)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_assetstore.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'center_kb.assetstore'`

- [ ] **Step 4: Implement**

Create `src/center_kb/assetstore.py`:

```python
"""Object-store seam for image assets (spec B).

Asset names are bare content-addressed filenames `<sha256>.<png|webp>`
(spec A); the store prepends the configured key prefix. `mode: none`
returns no store and leaves all existing behavior unchanged.
"""
from __future__ import annotations

import logging
from pathlib import Path

from center_kb import config as config_mod
from center_kb import models

logger = logging.getLogger("center_kb.assetstore")

_MEDIA = {".png": "image/png", ".webp": "image/webp"}
_IMMUTABLE = "private, max-age=31536000, immutable"


class AssetStoreError(RuntimeError):
    """Store unreachable / misconfigured / operation failed."""


def _media_type(name: str) -> str:
    return _MEDIA.get(Path(name).suffix, "application/octet-stream")


class MemoryStore:
    """Dict-backed store for tests."""

    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def exists(self, name: str) -> bool:
        return name in self.data

    def put(self, name: str, data: bytes) -> None:
        self.data.setdefault(name, data)

    def get(self, name: str) -> bytes | None:
        return self.data.get(name)


def _is_missing(exc: Exception) -> bool:
    code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
    return code in {"404", "NoSuchKey", "NotFound"}


class S3Store:
    """S3-compatible store. boto3 imports lazily at first use so `mode: none`
    installs never need it; `client` is a test seam."""

    def __init__(self, cfg: config_mod.AssetStoreConfig, client=None) -> None:
        if not cfg.bucket:
            raise AssetStoreError("asset_store.mode is s3 but no bucket is set")
        self._cfg = cfg
        self._client = client

    def _c(self):
        if self._client is None:
            try:
                import boto3
            except ImportError as exc:
                raise AssetStoreError(
                    'S3 asset store needs boto3 — run: pip install "center-kb[s3]"'
                ) from exc
            kwargs: dict = {}
            if self._cfg.region:
                kwargs["region_name"] = self._cfg.region
            if self._cfg.endpoint:
                kwargs["endpoint_url"] = self._cfg.endpoint
            self._client = boto3.client("s3", **kwargs)
        return self._client

    def _key(self, name: str) -> str:
        return f"{self._cfg.prefix}{name}"

    def exists(self, name: str) -> bool:
        try:
            self._c().head_object(Bucket=self._cfg.bucket, Key=self._key(name))
            return True
        except AssetStoreError:
            raise
        except Exception as exc:  # noqa: BLE001 — classify, then wrap
            if _is_missing(exc):
                return False
            raise AssetStoreError(f"asset store HEAD failed: {exc}") from exc

    def put(self, name: str, data: bytes) -> None:
        if self.exists(name):
            return  # content-addressed → identical bytes, idempotent
        try:
            self._c().put_object(
                Bucket=self._cfg.bucket,
                Key=self._key(name),
                Body=data,
                ContentType=_media_type(name),
                CacheControl=_IMMUTABLE,
            )
        except Exception as exc:  # noqa: BLE001
            raise AssetStoreError(f"asset store PUT failed: {exc}") from exc

    def get(self, name: str) -> bytes | None:
        try:
            resp = self._c().get_object(
                Bucket=self._cfg.bucket, Key=self._key(name)
            )
            return resp["Body"].read()
        except AssetStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            if _is_missing(exc):
                return None
            raise AssetStoreError(f"asset store GET failed: {exc}") from exc


def from_config(cfg: config_mod.AssetStoreConfig):
    """Store per config; None when mode is 'none' (spec A status quo)."""
    if cfg.mode == "none":
        return None
    return S3Store(cfg)


def store_for_hub(handle):
    """The hub repo's own config declares its storage mode — read it from
    the hub clone so children and the intake server need no local config."""
    return from_config(config_mod.load_config(handle.kb_dir).asset_store)
```

(`models` import is used by Task 3's additions to this file; leaving it in now is fine — Task 3 lands in the same module.)

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_assetstore.py tests/test_config.py -v`
Expected: PASS (all)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/center_kb/assetstore.py tests/test_assetstore.py
git commit -m "feat: asset store seam — S3Store (lazy boto3) + MemoryStore"
```

---

### Task 3: divert + record + manifest synthesis

**Files:**
- Modify: `src/center_kb/assetstore.py`, `src/center_kb/models.py`
- Test: `tests/test_assetstore.py`

**Interfaces:**
- Consumes: stores from Task 2; `models.save_yaml_model` / `models.load_yaml_model` (existing).
- Produces: `models.AssetsRecord` (BaseModel, `assets: list[str] = []`); `assetstore.divert_assets(tree_root: Path, store) -> list[str]`; `assetstore.divert_and_record(dest: Path, store, deletes: list[str] | None = None) -> list[str]` (merge semantics); `assetstore.synthesized_asset_entries(dest: Path) -> dict[str, str]`; constant `assetstore.RECORD_NAME = "_assets.yaml"`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_assetstore.py`)

```python
import hashlib
from pathlib import Path

from center_kb import models

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
    root = _tree(tmp_path)
    (root / assetstore.RECORD_NAME).write_text("{{not yaml", encoding="utf-8")
    assetstore.divert_and_record(root, assetstore.MemoryStore())
    rec = models.load_yaml_model(root / assetstore.RECORD_NAME, models.AssetsRecord)
    assert f"doc1/assets/{SHA_A}.png" in rec.assets


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_assetstore.py -v -k "divert or synthesized"`
Expected: FAIL — `AttributeError: ... has no attribute 'divert_assets'`

- [ ] **Step 3: Implement**

In `src/center_kb/models.py` add (near the other small models):

```python
class AssetsRecord(BaseModel):
    """Relative paths of assets diverted to the object store for one rid.
    The filename's sha256 IS the file content's sha256 (spec A), so hub
    manifests can synthesize exact entries without holding the bytes."""

    assets: list[str] = []
```

In `src/center_kb/assetstore.py` add:

```python
import re

RECORD_NAME = "_assets.yaml"
_ASSET_NAME_RE = re.compile(r"^([0-9a-f]{64})\.(?:png|webp)$")


def divert_assets(tree_root: Path, store) -> list[str]:
    """Upload every content-addressed asset under tree_root and strip it
    from the tree. Returns sorted relative posix paths. Any store failure
    raises AssetStoreError — the caller must not have committed yet."""
    diverted: list[str] = []
    for path in sorted(tree_root.rglob("assets/*")):
        if not path.is_file() or not _ASSET_NAME_RE.match(path.name):
            continue
        store.put(path.name, path.read_bytes())
        rel = path.relative_to(tree_root).as_posix()
        path.unlink()
        diverted.append(rel)
        try:
            path.parent.rmdir()  # only succeeds when now empty
        except OSError:
            pass
    return sorted(diverted)


def _load_record(dest: Path) -> "models.AssetsRecord":
    record_path = dest / RECORD_NAME
    if not record_path.exists():
        return models.AssetsRecord()
    try:
        return models.load_yaml_model(record_path, models.AssetsRecord)
    except Exception as exc:  # noqa: BLE001 — corrupt record self-heals
        logger.warning("%s unreadable (%s) — treating as empty", record_path, exc)
        return models.AssetsRecord()


def divert_and_record(dest: Path, store, deletes: list[str] | None = None) -> list[str]:
    """Divert assets under dest, then merge the record: existing ∪ new − deletes.
    Intake uploads are incremental, so a plain overwrite would drop
    previously-diverted assets from the record."""
    diverted = divert_assets(dest, store)
    merged = sorted(
        (set(_load_record(dest).assets) | set(diverted)) - set(deletes or [])
    )
    record_path = dest / RECORD_NAME
    if merged:
        models.save_yaml_model(record_path, models.AssetsRecord(assets=merged))
    elif record_path.exists():
        record_path.unlink()
    return diverted


def synthesized_asset_entries(dest: Path) -> dict[str, str]:
    """Manifest entries for diverted assets: {relpath: sha}, sha taken from
    the filename — exact by spec A construction, no bytes needed."""
    entries: dict[str, str] = {}
    for rel in _load_record(dest).assets:
        m = _ASSET_NAME_RE.match(Path(rel).name)
        if m:
            entries[rel] = m.group(1)
    return entries
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_assetstore.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/assetstore.py src/center_kb/models.py tests/test_assetstore.py
git commit -m "feat: asset divert, merge record, manifest synthesis"
```

---

### Task 4: intake wiring — divert on the branch tree, synthesized hub manifest

**Files:**
- Modify: `src/center_kb/intake.py` (`hub_manifest` at lines 250-253, `intake_publish` at lines 256-345)
- Test: `tests/test_intake_core.py`

**Interfaces:**
- Consumes: `assetstore.store_for_hub`, `assetstore.divert_and_record`, `assetstore.synthesized_asset_entries`, `assetstore.AssetStoreError`, `assetstore.RECORD_NAME` (Tasks 2-3).
- Produces: `intake_publish` accepts an optional `store=None` test seam (None → `store_for_hub(handle)`); hub git tree stays text-only when a store is configured; `hub_manifest` returns synthesized asset entries and never lists `_assets.yaml`.

- [ ] **Step 1: Read the existing intake tests**

Read `tests/test_intake_core.py` fully — reuse its fixtures for hub setup, archives, and `IntakeConfig(push_via_token_url=False, ...)` seams.

- [ ] **Step 2: Write the failing tests** (append to `tests/test_intake_core.py`, adapted to its fixture style; the assertions below are canonical)

```python
SHA_X = "e" * 64


def _archive_with_asset() -> bytes:
    # build a tar (the file's existing archive helper) containing:
    #   doc1/ch1-intro.md         → b"text"
    #   doc1/assets/<SHA_X>.png   → b"PNGBYTES"
    ...


def test_intake_diverts_assets_to_store(...existing hub fixtures...):
    store = assetstore.MemoryStore()
    url = intake.intake_publish(
        cfg, "child-a", "abc123", "org/child-a", [], _archive_with_asset(),
        store=store,
    )
    dest = hub_root / "federation" / "child-a"
    assert store.get(f"{SHA_X}.png") == b"PNGBYTES"
    assert not (dest / "doc1" / "assets" / f"{SHA_X}.png").exists()
    assert (dest / "doc1" / "ch1-intro.md").exists()
    rec = models.load_yaml_model(dest / "_assets.yaml", models.AssetsRecord)
    assert rec.assets == [f"doc1/assets/{SHA_X}.png"]
    # the branch commit is text-only: no asset path is tracked
    tracked = gitio._run(hub_root, "ls-files", "--", "federation").stdout
    assert f"{SHA_X}.png" not in tracked


def test_intake_upload_failure_aborts_before_commit(...):
    class _FailingStore(assetstore.MemoryStore):
        def put(self, name, data):
            raise assetstore.AssetStoreError("bucket down")

    before = gitio.head_commit(hub_root)
    with pytest.raises(intake.IntakeError) as exc:
        intake.intake_publish(
            cfg, "child-a", "abc123", "org/child-a", [], _archive_with_asset(),
            store=_FailingStore(),
        )
    assert exc.value.status == 502
    assert gitio.head_commit(hub_root) == before  # nothing committed


def test_hub_manifest_synthesizes_assets_and_hides_record(...):
    # after a successful diverted publish (as above):
    man = intake.hub_manifest(str(hub_root), "child-a")
    assert man[f"doc1/assets/{SHA_X}.png"] == SHA_X
    assert "_assets.yaml" not in man
    assert "_meta.yaml" not in man


def test_intake_deletes_cannot_touch_assets_record(...):
    # deletes=["_assets.yaml"] must be filtered exactly like "_meta.yaml"
    intake.intake_publish(
        cfg, "child-a", "abc124", "org/child-a", ["_assets.yaml"],
        _archive_with_asset(), store=assetstore.MemoryStore(),
    )
    assert (hub_root / "federation" / "child-a" / "_assets.yaml").exists()
```

Note `exc.value.status` — `IntakeError` carries `(status, detail)`; check its actual attribute names in `intake.py:24-34` and match them.

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_intake_core.py -v -k "divert or synthesizes or assets_record or aborts"`
Expected: FAIL — `TypeError: intake_publish() got an unexpected keyword argument 'store'`

- [ ] **Step 4: Implement**

In `src/center_kb/intake.py`:

1. Import the module near the top: `from center_kb import assetstore`.

2. `hub_manifest` (lines 250-253) — exclude the record, add synthesis:

```python
def hub_manifest(hub_ref: str, rid: str) -> dict[str, str]:
    handle = _resolve_hub_or_503(hub_ref)
    dest = _dest_for_rid(handle.federation_dir, rid)
    man = hashsync.build_manifest(
        dest, exclude=("_meta.yaml", assetstore.RECORD_NAME)
    )
    man.update(assetstore.synthesized_asset_entries(dest))
    return man
```

3. `intake_publish` — add the seam parameter and guard the deletes list:

```python
def intake_publish(
    cfg: IntakeConfig,
    rid: str,
    source_commit: str,
    source_repo_full: str,
    deletes: list[str],
    archive: bytes,
    store=None,
) -> str:
```

```python
    deletes = [d for d in deletes if d not in ("_meta.yaml", assetstore.RECORD_NAME)]
```

4. Inside the branch checkout, immediately after `hashsync.apply_sync(tmp_kb, dest, sorted(local_man), deletes)` and **before** the `dirty = ...` check:

```python
                active_store = store if store is not None else assetstore.store_for_hub(handle)
                if active_store is not None:
                    try:
                        assetstore.divert_and_record(dest, active_store, deletes)
                    except assetstore.AssetStoreError as exc:
                        raise IntakeError(502, f"asset store upload failed: {exc}")
```

The `finally` block already restores the original branch; the working-tree changes on `publish/<rid>` are uncommitted at failure time, and the next publish resets or reuses the branch per the existing hybrid checkout rule — no extra cleanup needed (verify this reasoning against the surrounding code while implementing; if the reused-branch path would see leftover dirty state, add a `git checkout -- federation` / `git reset --hard` restore in the failure path and test it).

- [ ] **Step 5: Run the intake suites**

Run: `.venv/bin/python -m pytest tests/test_intake_core.py tests/test_intake_http.py tests/test_intake_publish.py -v`
Expected: PASS (all — existing tests untouched because `store_for_hub` returns None without an `asset_store` block)

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/intake.py tests/test_intake_core.py
git commit -m "feat: intake diverts assets to the object store before commit"
```

---

### Task 5: publish wiring — `_snapshot` divert for direct/pr modes

**Files:**
- Modify: `src/center_kb/publish.py` (`_snapshot` at lines 56-103)
- Test: `tests/test_publish.py`

**Interfaces:**
- Consumes: `assetstore.store_for_hub`, `assetstore.divert_and_record`, `assetstore.synthesized_asset_entries`, `assetstore.RECORD_NAME`, `assetstore.AssetStoreError` (Tasks 2-3).
- Produces: `_snapshot(kb_abs, handle, rid, source_commit, source_url=None, store=None)` — extra `store` test seam; child `.kb/` is never mutated; second identical publish is still a no-op.

- [ ] **Step 1: Read the existing publish tests**

Read `tests/test_publish.py` — reuse its hub/child fixtures.

- [ ] **Step 2: Write the failing tests** (append to `tests/test_publish.py`, adapted to its fixture style)

```python
SHA_Y = "f" * 64


def _child_kb_with_asset(tmp_path) -> Path:
    # the file's existing child-kb fixture, plus:
    #   <kb>/doc1/assets/<SHA_Y>.png  → b"YBYTES"
    ...


def test_snapshot_diverts_assets_and_keeps_child_intact(...):
    store = assetstore.MemoryStore()
    n, changed = publish._snapshot(kb_abs, handle, "rid-a", "c0ffee", store=store)
    assert changed
    dest = handle.federation_dir / "rid-a"
    assert store.get(f"{SHA_Y}.png") == b"YBYTES"
    assert not (dest / "doc1" / "assets" / f"{SHA_Y}.png").exists()
    rec = models.load_yaml_model(dest / "_assets.yaml", models.AssetsRecord)
    assert rec.assets == [f"doc1/assets/{SHA_Y}.png"]
    # the child's live .kb is untouched
    assert (kb_abs / "doc1" / "assets" / f"{SHA_Y}.png").exists()


def test_snapshot_second_publish_is_noop_with_store(...):
    store = assetstore.MemoryStore()
    publish._snapshot(kb_abs, handle, "rid-a", "c0ffee", store=store)
    n, changed = publish._snapshot(kb_abs, handle, "rid-a", "c0ffee", store=store)
    assert not changed  # synthesized entries make diverted assets look present


def test_snapshot_upload_failure_raises_before_any_write_is_kept(...):
    class _FailingStore(assetstore.MemoryStore):
        def put(self, name, data):
            raise assetstore.AssetStoreError("bucket down")

    with pytest.raises(assetstore.AssetStoreError):
        publish._snapshot(kb_abs, handle, "rid-a", "c0ffee", store=_FailingStore())
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_publish.py -v -k "divert or noop_with_store or upload_failure"`
Expected: FAIL — `TypeError: _snapshot() got an unexpected keyword argument 'store'`

- [ ] **Step 4: Implement**

In `src/center_kb/publish.py`, rework `_snapshot` (the docstring stays; changed lines shown):

```python
def _snapshot(
    kb_abs: Path,
    handle: hub_mod.HubHandle,
    rid: str,
    source_commit: str,
    source_url: str | None = None,
    store=None,
) -> tuple[int, bool]:
    from center_kb import assetstore, hashsync

    dest = handle.federation_dir / rid
    fed_root = handle.federation_dir.resolve()
    if not dest.resolve().is_relative_to(fed_root):
        raise PublishError(
            f"repo-id '{rid}' escapes the federation/ directory on the hub — refusing to publish"
        )
    active_store = store if store is not None else assetstore.store_for_hub(handle)
    local_index = models.load_yaml_model(kb_abs / "index.yaml", models.KBIndex)
    local_man = hashsync.build_manifest(kb_abs)
    dest_man = hashsync.build_manifest(
        dest, exclude=("_meta.yaml", assetstore.RECORD_NAME)
    )
    if active_store is not None:
        dest_man.update(assetstore.synthesized_asset_entries(dest))
    changed, deleted = hashsync.diff_manifests(local_man, dest_man)
    if not changed and not deleted:
        return len(local_index.docs), False
    hashsync.apply_sync(kb_abs, dest, changed, deleted)
    if active_store is not None:
        assetstore.divert_and_record(dest, active_store, deleted)
    meta = federation.FederationMeta(
        ...  # unchanged from the current code
    )
    models.save_yaml_model(dest / "_meta.yaml", meta)
    return len(local_index.docs), True
```

(Divert runs on **dest** after `apply_sync` — the child's `.kb/` is read-only to this function. `AssetStoreError` propagates: `_publish_direct`/`_publish_pr` have not committed yet at this point, so a failure leaves only uncommitted working-tree changes in the hub clone, which the next publish's `apply_sync` reconciles.)

- [ ] **Step 5: Run the publish suites**

Run: `.venv/bin/python -m pytest tests/test_publish.py tests/test_federation.py tests/test_federation_e2e.py -v`
Expected: PASS (all)

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/publish.py tests/test_publish.py
git commit -m "feat: publish snapshot diverts assets for direct and pr modes"
```

---

### Task 6: serving — store fallthrough + disk cache in `/assets`

**Files:**
- Modify: `src/center_kb/web/ui.py` (`_find_asset` at lines 247-265, `asset` handler at lines 267-283)
- Test: `tests/test_web_ui.py`

**Interfaces:**
- Consumes: `assetstore.store_for_hub`, `assetstore.AssetStoreError` (Task 2); `hub._cache_base()` (existing).
- Produces: `/assets/{name}` behavior — local hit unchanged; local miss + store hit → bytes served and cached at `hub._cache_base() / "asset-cache" / <name>`; store miss → 404; `AssetStoreError` → 503. `build_routes(config, token, store_factory=None)` — optional test seam, default `assetstore.store_for_hub`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_web_ui.py`, reusing its `_authed_client` / fixtures from spec A's asset tests)

```python
def test_asset_route_falls_through_to_store(tmp_path, monkeypatch, ...):
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "hubcache"))
    sha = "9" * 64
    store = assetstore.MemoryStore()
    store.put(f"{sha}.webp", b"WEBPBYTES")
    client = _authed_client(..., store_factory=lambda handle: store)
    resp = client.get(f"/assets/{sha}.webp", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/webp"
    assert resp.content == b"WEBPBYTES"
    # cached on disk for the next request
    assert (tmp_path / "hubcache" / "asset-cache" / f"{sha}.webp").read_bytes() == b"WEBPBYTES"


def test_asset_route_store_miss_404_and_error_503(...):
    class _Boom(assetstore.MemoryStore):
        def get(self, name):
            raise assetstore.AssetStoreError("down")

    client_miss = _authed_client(..., store_factory=lambda handle: assetstore.MemoryStore())
    assert client_miss.get(f"/assets/{'8' * 64}.png", headers=AUTH_HEADERS).status_code == 404
    client_err = _authed_client(..., store_factory=lambda handle: _Boom())
    assert client_err.get(f"/assets/{'8' * 64}.png", headers=AUTH_HEADERS).status_code == 503


def test_asset_route_no_store_behaves_as_before(...):
    client = _authed_client(...)  # store_factory default; hub config has no asset_store
    assert client.get(f"/assets/{'7' * 64}.png", headers=AUTH_HEADERS).status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_web_ui.py -v -k "falls_through or store_miss or no_store"`
Expected: FAIL — `TypeError: build_routes() got an unexpected keyword argument 'store_factory'` (or 404 where 200 expected)

- [ ] **Step 3: Implement**

In `src/center_kb/web/ui.py`:

1. Add imports: `from center_kb import assetstore, hub as hub_mod`.

2. Change the signature: `def build_routes(config: ServerConfig, token: str, store_factory=None) -> list[Route]:` and inside, next to `asset_cache`:

```python
    resolve_store = store_factory or assetstore.store_for_hub
    store_cache: dict[str, object] = {}  # hub root → store (or None), built once

    def _store_for(hub):
        key = str(hub.root)
        if key not in store_cache:
            store_cache[key] = resolve_store(hub)
        return store_cache[key]

    def _disk_cache_dir() -> Path:
        return hub_mod._cache_base() / "asset-cache"
```

(`from pathlib import Path` is already imported per spec A.)

3. Extend `_find_asset` — after the existing local-dir loop, before `return None`:

The contract stays `Path | None`. On a store hit, bytes are written to the disk cache and that path is served; if the cache write fails, the bytes go to a temp file instead so the request still succeeds (spec §7: cache-write failure must not fail the request):

```python
        cache_file = _disk_cache_dir() / name
        if cache_file.is_file():
            asset_cache[name] = cache_file
            return cache_file
        store = _store_for(hub)
        if store is not None:
            data = store.get(name)  # AssetStoreError propagates to the handler
            if data is not None:
                target = cache_file
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                except OSError as exc:
                    logger.warning("asset disk cache write failed: %s", exc)
                    import tempfile

                    fd, tmp_name = tempfile.mkstemp(suffix=Path(name).suffix)
                    import os

                    with os.fdopen(fd, "wb") as fh:
                        fh.write(data)
                    target = Path(tmp_name)
                asset_cache[name] = target
                return target
        return None
```

(`ui.py` needs a module logger if it lacks one: `logger = logging.getLogger("center_kb.web.ui")`.)

4. In the `asset` handler, wrap the lookup for the 503 case:

```python
        try:
            path = await run_in_threadpool(_find_asset, hub, name)
        except assetstore.AssetStoreError as exc:
            logger.warning("asset store lookup failed: %s", exc)
            return Response("asset store unavailable", status_code=503)
```

5. `web/app.py` calls `ui.build_routes(config, token)` — the new parameter is keyword-optional, no change needed there.

- [ ] **Step 4: Run the web suites**

Run: `.venv/bin/python -m pytest tests/test_web_ui.py tests/test_web_app.py tests/test_web_auth.py -v`
Expected: PASS (all — spec A asset tests unchanged; default path has no store)

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/web/ui.py tests/test_web_ui.py
git commit -m "feat: /assets falls through to the object store with disk cache"
```

---

### Task 7: end-to-end round-trip, README, full verification

**Files:**
- Test: `tests/test_assetstore.py` (round-trip), possibly `tests-gate` goldens (none expected)
- Modify: `README.md` (one short paragraph in the hub/publish section)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the round-trip test** (append to `tests/test_assetstore.py`)

The no-churn property end-to-end at the manifest level (no git needed):

```python
def test_divert_then_synthesis_roundtrip_no_rediff(tmp_path):
    from center_kb import hashsync

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
```

Note: this asserts the exact spec §6 property — after one diverted publish, the child's unchanged manifest diffs to nothing. Task 3's `_tree` fixture already writes bytes whose sha256 equals the filename (its SHA constants are computed with `hashlib.sha256(...)`), so `build_manifest`'s real hashes agree with the synthesized filename hashes and the fixture is shared unchanged.

- [ ] **Step 2: Run test to verify it fails, then passes**

Run: `.venv/bin/python -m pytest tests/test_assetstore.py -v -k roundtrip`
Expected: with Tasks 1-6 done this should PASS immediately — if it fails, the synthesis/diff contract is broken: STOP and fix the implementation, not the test.

- [ ] **Step 3: README**

Add one short paragraph to the hub/publish section of `README.md`: a hub can declare `asset_store: {mode: s3, bucket: …}` in its `.kb/config.yaml`; publishes then upload image assets to the bucket instead of committing them (recorded in `_assets.yaml`), and `/assets` serves them through the hub with a local cache; requires `pip install "center-kb[s3]"` and standard AWS credentials on the machines that publish or serve; `mode: none` (default) keeps assets in git.

- [ ] **Step 4: Full verification**

Run: `.venv/bin/python -m pytest tests -q`
Expected: all pass (target: prior count + new tests, 0 failures).
Run the release gate per the repo's documented invocation (`scripts/gate.sh`).
Expected: all tiers green; goldens untouched (this feature changes nothing with `mode: none`).

- [ ] **Step 5: Commit**

```bash
git add tests/test_assetstore.py README.md
git commit -m "docs: document S3 asset delivery; round-trip no-churn test"
```

---

## Self-Review Notes

- Spec §3 (config) → Task 1. §4 (store seam, boto3 extra, lazy import, idempotent put) → Task 2. §5 (divert + record merge, loud failure before commit) → Tasks 3-5. §6 (synthesis, `_assets.yaml` exclusion + delete guard) → Tasks 3-5, round-trip in Task 7. §7 (serving fallthrough, disk cache, 503/404) → Task 6. §8 (testing) → every task. §9 non-goals honored (no presigned, no GC, no init/doctor/migrate).
- Design deviation from spec §5 text, intentional and safer: divert runs on the **dest** tree after `apply_sync` for ALL transports (spec described intake diverting on the extracted tmp tree). Rationale: `_snapshot` must never mutate the child's live `.kb/`, and one uniform post-sync divert covers all three modes with a single code path. The spec's stated properties all still hold (bytes in store before commit; text-only commits; record merge; no re-upload churn).
- Type consistency: `store` seam parameter name and `AssetStoreError` used identically in Tasks 2-6; `RECORD_NAME` single source; `divert_and_record(dest, store, deletes)` signature consistent across Tasks 3, 4, 5.
