from __future__ import annotations

import io
import tarfile
import time

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from center_kb import intake, models

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
