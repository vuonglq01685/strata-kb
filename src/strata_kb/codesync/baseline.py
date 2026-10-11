"""The code-sync baseline: one hub commit sha in `kb-code-sync.yaml` at the
hub repo root (spec §5.1), and the scan sha it is compared against."""

from __future__ import annotations

import re
from pathlib import Path

from strata_kb import gitio

BASELINE_FILE = "kb-code-sync.yaml"
BOT_BRANCH = "kb-bot/code-sync"
_BOT_REF = f"refs/remotes/origin/{BOT_BRANCH}"

_SHA_RE = re.compile(r"[0-9a-fA-F]{7,40}")
# Line-based, not YAML: an all-digit sha would load as an int.
_KEY_RE = re.compile(
    r"^baseline:[ \t]*(?P<value>[^#\n]*?)[ \t]*(?:#.*)?$", re.MULTILINE
)


def check_sha(value: str) -> str:
    """`value` unchanged if it is a 7-40 char hex sha, else ValueError: the
    only gate between an operator-edited file or flag and `git`."""
    if _SHA_RE.fullmatch(value) is None:
        raise ValueError(f"'{value}' is not a commit sha (7-40 hex characters)")
    return value


def parse(text: str) -> str | None:
    """The `baseline:` value of the file's text; None when the key is missing."""
    m = _KEY_RE.search(text)
    if m is None:
        return None
    return check_sha(m["value"].strip("'\""))


def read_at(root: Path, rev: str) -> str | None:
    """`parse` of the baseline file at `rev`; None when the file is absent.
    GitError if `rev` does not exist."""
    text = gitio.read_at(root, rev, root / BASELINE_FILE)
    return None if text is None else parse(text)


def write(root: Path, sha: str) -> None:
    (root / BASELINE_FILE).write_text(
        f"baseline: {sha}\n", encoding="utf-8", newline="\n"
    )


def scan_ref(root: Path) -> str:
    """Full sha the scan reads: the default branch's tip (`origin/HEAD`).
    `HEAD` only for a repo with no remote; a remote with no `origin/HEAD`
    raises GitError rather than guessing."""
    if not gitio.has_remote(root):
        return gitio.resolve_commit(root, "HEAD")
    return gitio.resolve_commit(root, gitio.origin_head_ref(root))


def resolve(
    root: Path, scan_sha: str, *, bot_ref: bool = True
) -> tuple[str | None, str]:
    """`(baseline sha, source)`: the rolling PR branch's file when that
    remote-tracking ref holds one, else the file at `scan_sha`. `bot_ref`
    False never reads the local tracking ref: it can outlive a closed PR."""
    if bot_ref and gitio.rev_exists(root, _BOT_REF):
        sha = read_at(root, _BOT_REF)
        if sha is not None:
            return sha, "bot-branch"
    return read_at(root, scan_sha), "default-branch"
