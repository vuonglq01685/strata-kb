"""Index freshness.

Reviewer C F-C3: `_repo_fingerprint` hashed only `_meta.yaml` and `index.yaml`,
and `_meta.yaml` is rewritten only when a CHILD publishes. So a fix made
directly in `federation/` on the hub — README §7.9 calls that "the single
review gate" — never invalidated the index. `kb query` and `kb get`
disagreed about the same section forever, and neither `kb reindex` nor
`kb doctor` repaired it; only `rm hub/.kb-work/search.db` did.
"""
import hashlib
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

pytest.importorskip("sqlite_vec")

from center_kb import searchdb
from center_kb.cli import app
from center_kb.hub import HubHandle
from center_kb.query import get_section, search

MARKER = "ZZHUBFIXMARKERZZ"


def test_hub_side_edit_is_visible_to_the_next_query(fed_hub, run_git):
    hub = HubHandle(root=fed_hub)
    assert search(hub, MARKER) == []          # builds the index

    l2 = fed_hub / "federation" / "arinc-kb" / "arinc-424" / "ch1.md"
    l2.write_text(
        l2.read_text(encoding="utf-8") + f"\n{MARKER} typo fixed on the hub.\n",
        encoding="utf-8",
    )
    run_git(fed_hub, "add", "-A")
    run_git(fed_hub, "commit", "-m", "reviewer fixes a typo directly on the hub")

    results = search(hub, MARKER)
    assert results, "a hub-side edit is invisible to search"
    assert results[0].section_id == "5.3"
    # and the two read paths agree
    assert MARKER in get_section(hub, "arinc-kb:arinc-424", "5.3").content


def test_reindex_force_rebuilds_from_scratch(fed_hub):
    hub = HubHandle(root=fed_hub)
    searchdb.sync(hub, None)
    conn = searchdb.open_db(hub)
    try:
        conn.execute("DELETE FROM sections")
        conn.execute("DELETE FROM fts")
        conn.commit()
    finally:
        conn.close()

    # the fingerprints still match, so an ordinary sync sees nothing to do
    searchdb.sync(hub, None)
    assert search(hub, "restrictive airspace") == []

    result = CliRunner().invoke(
        app,
        ["reindex", "--force", "--hub", str(fed_hub),
         "--kb-dir", str(fed_hub / ".kb")],
    )
    assert result.exit_code == 0, result.output
    assert search(hub, "restrictive airspace")


# --- Review round 2 (F-C3 findings 1+2): the os.scandir rewrite ------------
#
# Finding 1: Path.rglob + Path.stat crossed the 20ms per-query gate around
# ~465 files (reviewer-measured). Rewritten on os.scandir + DirEntry.stat,
# which reuses the stat data the directory enumeration already returned.
# Finding 2: Path.stat() was unguarded, so a file vanishing between being
# listed and being stat'd (a concurrent git pull/publish on the hub, which
# is also the query source) put a raw traceback in front of the caller.


def _reference_fingerprint(repo_dir: Path) -> str:
    """The pre-round-2 implementation (Path.rglob + Path.stat) — kept here
    only to prove the os.scandir rewrite hashes to an identical digest on a
    real tree, not to be reused anywhere."""
    h = hashlib.sha256()
    if not repo_dir.is_dir():
        return h.hexdigest()
    for p in sorted(repo_dir.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        st = p.stat()
        rel = p.relative_to(repo_dir).as_posix()
        h.update(f"{rel}\0{st.st_size}\0{st.st_mtime_ns}\0".encode("utf-8"))
    return h.hexdigest()


def test_fingerprint_matches_the_pre_rewrite_digest_on_a_real_tree(fed_hub):
    """The os.scandir rewrite must be a pure performance change: same digest
    for the same tree. `federation/arinc-kb` is a realistic multi-level,
    multi-file federation entry (a doc subdirectory holding L2/L3/manifest,
    plus index.yaml/_meta.yaml at the entry root)."""
    entry_dir = fed_hub / "federation" / "arinc-kb"
    assert searchdb._repo_fingerprint(entry_dir) == _reference_fingerprint(entry_dir)


def test_fingerprint_missing_dir_returns_empty_digest():
    digest = searchdb._repo_fingerprint(Path("no-such-federation-entry-dir"))
    assert digest == hashlib.sha256().hexdigest()


def test_fingerprint_skips_a_file_that_vanishes_mid_walk(fed_hub, monkeypatch):
    """F-C3 finding 2: DirEntry.stat() raising OSError for a file that
    vanished between being listed and being stat'd must be swallowed, not
    raised — and the resulting digest must be exactly the digest of the
    tree with that file genuinely absent (not merely "didn't crash")."""
    entry_dir = fed_hub / "federation" / "arinc-kb"
    victim = entry_dir / "arinc-424" / "ch1.md"
    assert victim.exists()

    # reference: the digest of the tree as if the victim had never existed.
    # A rename (even to a throwaway name in the same dir) would still leave
    # a file at that relpath for the walk to pick up — an actual removal is
    # the only way to get "genuinely absent"; restore the content after.
    original_bytes = victim.read_bytes()
    victim.unlink()
    digest_without_file = searchdb._repo_fingerprint(entry_dir)
    victim.write_bytes(original_bytes)

    real_scandir = os.scandir

    class _VanishingEntry:
        """Wraps a real DirEntry so .stat() raises, simulating the file
        disappearing between os.scandir() listing it and it being stat'd."""

        def __init__(self, real):
            self._real = real

        @property
        def name(self):
            return self._real.name

        @property
        def path(self):
            return self._real.path

        def is_dir(self, follow_symlinks=True):
            return self._real.is_dir(follow_symlinks=follow_symlinks)

        def is_file(self, follow_symlinks=True):
            return self._real.is_file(follow_symlinks=follow_symlinks)

        def stat(self, follow_symlinks=True):
            raise FileNotFoundError(f"vanished mid-walk: {self._real.name}")

    def flaky_scandir(path):
        for e in real_scandir(path):
            yield _VanishingEntry(e) if e.path == str(victim) else e

    monkeypatch.setattr(searchdb.os, "scandir", flaky_scandir)
    digest_with_vanish = searchdb._repo_fingerprint(entry_dir)  # must not raise

    assert digest_with_vanish == digest_without_file


def test_fingerprint_skips_symlinked_entries_without_descending(fed_hub, monkeypatch):
    """F-C3: symlinked files and symlinked directories are skipped, and a
    symlinked directory is never descended into.

    Creating a real symlink needs elevated privilege on this Windows sandbox
    (verified separately: os.symlink raises WinError 1314 for both a file
    and a directory target without it), so this fakes the os.scandir
    DirEntry shape a symlink presents instead: is_dir(follow_symlinks=False)
    and is_file(follow_symlinks=False) both report False for a symlink
    entry, whatever it points to — that's the exact property
    _repo_fingerprint relies on to skip one without stat'ing or descending
    into it."""
    entry_dir = fed_hub / "federation" / "arinc-kb"
    real_scandir = os.scandir
    scanned_paths: list[str] = []
    symlinked_dir = str(entry_dir / "evil-link-dir")

    class _SymlinkEntry:
        def __init__(self, name, path):
            self.name, self.path = name, path

        def is_dir(self, follow_symlinks=True):
            return False

        def is_file(self, follow_symlinks=True):
            return False

        def stat(self, follow_symlinks=True):
            raise AssertionError(
                f"stat() must not be called on a symlink entry: {self.name}"
            )

    def scandir_with_symlinks(path):
        # a generator (not `iter(a_list)`) so it has `.close()`, like the
        # real os.scandir() iterator _repo_fingerprint relies on
        scanned_paths.append(str(path))
        yield from real_scandir(path)
        if str(path) == str(entry_dir):
            yield _SymlinkEntry("evil-link.md", str(entry_dir / "evil-link.md"))
            yield _SymlinkEntry("evil-link-dir", symlinked_dir)

    monkeypatch.setattr(searchdb.os, "scandir", scandir_with_symlinks)
    digest_with_symlinks = searchdb._repo_fingerprint(entry_dir)

    assert symlinked_dir not in scanned_paths  # never descended into

    monkeypatch.setattr(searchdb.os, "scandir", real_scandir)
    digest_without_symlinks = searchdb._repo_fingerprint(entry_dir)
    assert digest_with_symlinks == digest_without_symlinks
