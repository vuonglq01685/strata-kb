# tests/test_hashsync.py
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from center_kb import hashsync


def _write(root: Path, rel: str, content: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


class TestBuildManifest:
    def test_maps_relpath_to_sha256_sorted(self, tmp_path):
        _write(tmp_path, "b/two.md", "two")
        _write(tmp_path, "a/one.md", "one")
        man = hashsync.build_manifest(tmp_path)
        assert list(man) == ["a/one.md", "b/two.md"]
        # sha256("one") — giá trị cố định, manifest phải deterministic
        assert man["a/one.md"] == (
            "7692c3ad3540bb803c020b3aee66cd8887123234ea0c6e7143c0add73ff431ed"
        )

    def test_missing_root_returns_empty(self, tmp_path):
        assert hashsync.build_manifest(tmp_path / "nope") == {}

    def test_exclude_skips_exact_relpath(self, tmp_path):
        _write(tmp_path, "_meta.yaml", "x")
        _write(tmp_path, "doc/index.yaml", "y")
        man = hashsync.build_manifest(tmp_path, exclude=("_meta.yaml",))
        assert "_meta.yaml" not in man
        assert "doc/index.yaml" in man

    def test_hash_is_bytes_exact_crlf_differs(self, tmp_path):
        (tmp_path / "f.md").write_bytes(b"line\r\n")
        man1 = hashsync.build_manifest(tmp_path)
        (tmp_path / "f.md").write_bytes(b"line\n")
        man2 = hashsync.build_manifest(tmp_path)
        assert man1["f.md"] != man2["f.md"]


class TestDiffManifests:
    def test_changed_new_deleted_and_empty(self):
        local = {"a": "1", "b": "2-new", "c": "3"}
        remote = {"a": "1", "b": "2-old", "d": "4"}
        changed, deleted = hashsync.diff_manifests(local, remote)
        assert changed == ["b", "c"]
        assert deleted == ["d"]
        assert hashsync.diff_manifests({"a": "1"}, {"a": "1"}) == ([], [])


class TestApplySync:
    def test_copies_deletes_and_prunes_empty_dirs(self, tmp_path):
        src, dest = tmp_path / "src", tmp_path / "dest"
        _write(src, "keep/new.md", "new")
        _write(dest, "old/gone.md", "bye")
        hashsync.apply_sync(src, dest, ["keep/new.md"], ["old/gone.md"])
        assert (dest / "keep/new.md").read_text(encoding="utf-8") == "new"
        assert not (dest / "old/gone.md").exists()
        assert not (dest / "old").exists()  # pruned

    def test_deletes_readonly_file(self, tmp_path):
        src, dest = tmp_path / "src", tmp_path / "dest"
        src.mkdir()
        target = _write(dest, "ro.md", "x")
        os.chmod(target, stat.S_IREAD)
        hashsync.apply_sync(src, dest, [], ["ro.md"])
        assert not target.exists()

    @pytest.mark.parametrize("bad", ["../escape.md", "a/../../up.md"])
    def test_path_escape_raises(self, tmp_path, bad):
        src, dest = tmp_path / "src", tmp_path / "dest"
        src.mkdir(), dest.mkdir()
        with pytest.raises(hashsync.HashSyncError):
            hashsync.apply_sync(src, dest, [], [bad])
        with pytest.raises(hashsync.HashSyncError):
            hashsync.apply_sync(src, dest, [bad], [])
