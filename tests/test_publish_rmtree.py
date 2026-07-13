"""Windows sets PermissionError on rmtree of read-only files — publish
re-snapshots over an existing mirror and must not die on them."""
import os
import stat
from pathlib import Path

from center_kb import publish


def test_rmtree_force_removes_readonly_file(tmp_path: Path):
    tree = tmp_path / "mirror"
    (tree / "doc").mkdir(parents=True)
    victim = tree / "doc" / "ro.md"
    victim.write_text("x", encoding="utf-8")
    os.chmod(victim, stat.S_IREAD)

    publish._rmtree_force(tree)

    assert not tree.exists()
