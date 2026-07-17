from __future__ import annotations

import io
import json
import subprocess
import tarfile
import time
from pathlib import Path

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from center_kb import assetstore, ghapp, gitio, intake, models

AUD = "https://kb.internal:8321"


@pytest.fixture(scope="module")
def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return pem, key.public_key()


def _token(pem, pub, **overrides):
    now = int(time.time())
    claims = {
        "iss": intake.GITHUB_ISSUER,
        "aud": AUD,
        "iat": now,
        "exp": now + 300,
        "repository": "acme/flight-docs",
        "ref": "refs/tags/kb-publish/20260715-010101",
    }
    claims.update(overrides)
    return pyjwt.encode(claims, pem, algorithm="RS256")


class TestVerifyOIDC:
    def test_valid_token_returns_claims(self, keypair):
        pem, pub = keypair
        claims = intake.verify_oidc(_token(pem, pub), AUD, key_resolver=lambda t: pub)
        assert claims["repository"] == "acme/flight-docs"

    @pytest.mark.parametrize(
        "override",
        [
            {"aud": "https://other"},
            {"iss": "https://evil.example"},
            {"exp": int(time.time()) - 10},
        ],
    )
    def test_bad_claims_rejected_401(self, keypair, override):
        pem, pub = keypair
        with pytest.raises(intake.IntakeError) as exc:
            intake.verify_oidc(
                _token(pem, pub, **override), AUD, key_resolver=lambda t: pub
            )
        assert exc.value.status == 401

    def test_wrong_signature_rejected(self, keypair):
        pem, _ = keypair
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with pytest.raises(intake.IntakeError) as exc:
            intake.verify_oidc(
                _token(pem, None), AUD, key_resolver=lambda t: other.public_key()
            )
        assert exc.value.status == 401


class TestAuthorize:
    REG = models.Registry(repos={"acme/flight-docs": "flight-docs"})

    def test_known_repo_returns_rid(self):
        claims = {
            "repository": "acme/flight-docs",
            "ref": "refs/tags/kb-publish/x",
        }
        assert intake.authorize(claims, self.REG) == "flight-docs"

    def test_unknown_repo_403_with_registry_hint(self):
        claims = {"repository": "evil/repo", "ref": "refs/tags/kb-publish/x"}
        with pytest.raises(intake.IntakeError) as exc:
            intake.authorize(claims, self.REG)
        assert exc.value.status == 403
        assert "registry.yaml" in exc.value.detail

    def test_non_publish_ref_403(self):
        claims = {"repository": "acme/flight-docs", "ref": "refs/heads/main"}
        with pytest.raises(intake.IntakeError) as exc:
            intake.authorize(claims, self.REG)
        assert exc.value.status == 403

    def test_registry_rid_with_path_separator_500(self):
        reg = models.Registry(repos={"acme/flight-docs": "../evil"})
        claims = {
            "repository": "acme/flight-docs",
            "ref": "refs/tags/kb-publish/x",
        }
        with pytest.raises(intake.IntakeError) as exc:
            intake.authorize(claims, reg)
        assert exc.value.status == 500


def _tar_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


class TestSafeExtract:
    def test_extracts_regular_files(self, tmp_path):
        data = _tar_bytes({"index.yaml": b"docs: []", "d/s.md": b"hi"})
        intake.safe_extract(data, tmp_path)
        assert (tmp_path / "index.yaml").read_bytes() == b"docs: []"
        assert (tmp_path / "d" / "s.md").read_bytes() == b"hi"

    @pytest.mark.parametrize("name", ["../up.md", "/abs.md", "a/../../out.md"])
    def test_traversal_rejected_400(self, tmp_path, name):
        with pytest.raises(intake.IntakeError) as exc:
            intake.safe_extract(_tar_bytes({name: b"x"}), tmp_path)
        assert exc.value.status == 400

    def test_symlink_rejected_400(self, tmp_path):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            info = tarfile.TarInfo("link.md")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tf.addfile(info)
        with pytest.raises(intake.IntakeError) as exc:
            intake.safe_extract(buf.getvalue(), tmp_path)
        assert exc.value.status == 400

    def test_oversize_rejected_413(self, tmp_path):
        data = _tar_bytes({"big.md": b"x" * 2048})
        with pytest.raises(intake.IntakeError) as exc:
            intake.safe_extract(data, tmp_path, max_bytes=100)
        assert exc.value.status == 413


class TestStatusStore:
    def test_set_get_roundtrip_and_persistence(self, tmp_path):
        path = tmp_path / "status.json"
        store = intake.StatusStore(path)
        store.set("flight-docs", "abc1234", "done", pr_url="https://x/pull/1")
        got = store.get("flight-docs", "abc1234")
        assert got == {"state": "done", "pr_url": "https://x/pull/1", "detail": ""}
        # reload from file
        store2 = intake.StatusStore(path)
        assert store2.get("flight-docs", "abc1234")["state"] == "done"

    def test_unknown_returns_none(self, tmp_path):
        store = intake.StatusStore(None)
        assert store.get("x", "y") is None


def test_repo_lock_same_id_same_lock():
    assert intake.repo_lock("a") is intake.repo_lock("a")
    assert intake.repo_lock("a") is not intake.repo_lock("b")


# --- intake wiring: divert to the asset store, synthesized hub manifest ----


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8"
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


@pytest.fixture
def hub_root(tmp_path):
    """Hub = local clone with an origin bare — mirrors the hub cache used by intake."""
    bare = tmp_path / "hub-origin.git"
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-b", "main")
    _git(seed, "config", "user.email", "t@t")
    _git(seed, "config", "user.name", "t")
    (seed / ".kb").mkdir()
    (seed / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    (seed / "federation").mkdir()
    (seed / "federation" / ".gitkeep").write_text("", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-m", "init")
    _git(tmp_path, "clone", "--bare", str(seed), str(bare))
    clone = tmp_path / "hub-clone"
    _git(tmp_path, "clone", str(bare), str(clone))
    _git(clone, "config", "user.email", "srv@t")
    _git(clone, "config", "user.name", "srv")
    return clone


class FakeHTTP:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, req):
        self.requests.append(req)
        status, body = self.responses.pop(0)
        return status, json.dumps(body).encode()


def _cfg(hub_root: Path, http) -> intake.IntakeConfig:
    return intake.IntakeConfig(
        hub_ref=str(hub_root),
        audience="https://kb.test",
        creds=ghapp.AppCreds(app_id="1", private_key_pem="unused-by-fake"),
        http=http,
        push_via_token_url=False,
    )


def _pr_http() -> FakeHTTP:
    """One successful publish's worth of GH App calls: installation lookup,
    token mint, PR create."""
    return FakeHTTP(
        [(200, {"id": 9}), (201, {"token": "t"}), (201, {"html_url": "u/pull/1"})]
    )


SHA_X = "e" * 64


def _archive_with_asset() -> bytes:
    return _tar_bytes(
        {
            "doc1/ch1-intro.md": b"text",
            f"doc1/assets/{SHA_X}.png": b"PNGBYTES",
        }
    )


def test_intake_diverts_assets_to_store(hub_root, monkeypatch):
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    cfg = _cfg(hub_root, _pr_http())
    store = assetstore.MemoryStore()
    intake.intake_publish(
        cfg, "child-a", "abc123", "org/child-a", [], _archive_with_asset(),
        store=store,
    )
    _git(hub_root, "checkout", "publish/child-a")
    dest = hub_root / "federation" / "child-a"
    assert store.get(f"{SHA_X}.png") == b"PNGBYTES"
    assert not (dest / "doc1" / "assets" / f"{SHA_X}.png").exists()
    assert (dest / "doc1" / "ch1-intro.md").exists()
    rec = models.load_yaml_model(dest / "_assets.yaml", models.AssetsRecord)
    assert rec.assets == [f"doc1/assets/{SHA_X}.png"]
    # the branch commit is text-only: no asset path is tracked
    tracked = gitio._run(hub_root, "ls-files", "--", "federation").stdout
    assert f"{SHA_X}.png" not in tracked
    _git(hub_root, "checkout", "main")


def test_intake_upload_failure_aborts_before_commit(hub_root, monkeypatch):
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    cfg = _cfg(hub_root, FakeHTTP([]))  # no HTTP call should happen before the abort

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


def test_intake_upload_failure_leaves_no_dirty_leftovers(hub_root, monkeypatch):
    """A failed divert must not leave uncommitted federation/ changes behind.

    Otherwise the next publish attempt for the same rid sees a dirty working
    tree: `dest.exists()` (a filesystem check) would be fooled into thinking
    the rid is already merged to main, and — worse — stray content from the
    aborted attempt could ride along uncommitted into a later, unrelated
    publish's commit.
    """
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")

    class _FailingStore(assetstore.MemoryStore):
        def put(self, name, data):
            raise assetstore.AssetStoreError("bucket down")

    archive1 = _tar_bytes(
        {
            "doc1/other.md": b"other",
            f"doc1/assets/{SHA_X}.png": b"PNGBYTES",
        }
    )
    with pytest.raises(intake.IntakeError):
        intake.intake_publish(
            _cfg(hub_root, FakeHTTP([])), "child-a", "abc123", "org/child-a",
            [], archive1, store=_FailingStore(),
        )
    status = gitio._run(
        hub_root, "status", "--porcelain", "--", "federation"
    ).stdout.strip()
    assert status == ""

    archive2 = _tar_bytes({"doc1/ch1-intro.md": b"text"})
    intake.intake_publish(
        _cfg(hub_root, _pr_http()), "child-a", "abc124", "org/child-a", [],
        archive2, store=assetstore.MemoryStore(),
    )
    _git(hub_root, "checkout", "publish/child-a")
    dest = hub_root / "federation" / "child-a"
    # not dragged along from the aborted attempt
    assert not (dest / "doc1" / "other.md").exists()
    assert (dest / "doc1" / "ch1-intro.md").exists()
    _git(hub_root, "checkout", "main")


def test_hub_manifest_synthesizes_assets_and_hides_record(hub_root, monkeypatch):
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    # hub_manifest() gates synthesis on the hub's own configured store (same
    # rule as publish._snapshot) -- the intake_publish call below bypasses
    # that via the store= test seam, but hub_manifest always reads
    # store_for_hub(handle), so the hub needs a real asset_store block for
    # the gated synthesis path to fire.
    (hub_root / ".kb" / "config.yaml").write_text(
        "asset_store:\n  mode: s3\n  bucket: kb-assets\n", encoding="utf-8"
    )
    intake.intake_publish(
        _cfg(hub_root, _pr_http()), "child-a", "abc123", "org/child-a", [],
        _archive_with_asset(), store=assetstore.MemoryStore(),
    )
    # hub_manifest reads main -- merge the publish branch in first
    _git(hub_root, "merge", "--no-ff", "--no-edit", "publish/child-a")
    man = intake.hub_manifest(str(hub_root), "child-a")
    assert man[f"doc1/assets/{SHA_X}.png"] == SHA_X
    assert "_assets.yaml" not in man
    assert "_meta.yaml" not in man


def test_intake_child_supplied_assets_record_is_ignored(hub_root, monkeypatch):
    """A malicious/stale tar can carry its own _assets.yaml at the rid root --
    it must never be synced verbatim into the hub-owned record. Only genuinely
    diverted assets (merged by divert_and_record) may end up in the record.
    """
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    bogus_record = models.AssetsRecord(assets=["doc1/assets/" + "e" * 64 + ".evil.png"])
    archive = _tar_bytes(
        {
            "doc1/ch1-intro.md": b"text",
            f"doc1/assets/{SHA_X}.png": b"PNGBYTES",
            assetstore.RECORD_NAME: (
                b"assets:\n- " + bogus_record.assets[0].encode() + b"\n"
            ),
        }
    )
    intake.intake_publish(
        _cfg(hub_root, _pr_http()), "child-a", "abc123", "org/child-a", [], archive,
        store=assetstore.MemoryStore(),
    )
    _git(hub_root, "checkout", "publish/child-a")
    dest = hub_root / "federation" / "child-a"
    rec = models.load_yaml_model(dest / assetstore.RECORD_NAME, models.AssetsRecord)
    assert bogus_record.assets[0] not in rec.assets
    assert rec.assets == [f"doc1/assets/{SHA_X}.png"]
    _git(hub_root, "checkout", "main")


def test_intake_deletes_cannot_touch_assets_record(hub_root, monkeypatch):
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    intake.intake_publish(
        _cfg(hub_root, _pr_http()), "child-a", "abc124", "org/child-a",
        ["_assets.yaml"], _archive_with_asset(), store=assetstore.MemoryStore(),
    )
    _git(hub_root, "checkout", "publish/child-a")
    assert (hub_root / "federation" / "child-a" / "_assets.yaml").exists()
    _git(hub_root, "checkout", "main")
