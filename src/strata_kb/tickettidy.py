"""`kb ticket tidy` — move flat `tickets/*.md` into `tickets/<mission-id>/`.

Spec 2026-09-29-ticket-status-decision-defaults-design §7. Idempotent: a
file already inside a folder is never touched; a destination that exists
is a conflict, never an overwrite. No git here — the BA commits and git
detects the rename.
"""

from __future__ import annotations

import re
from pathlib import Path

from strata_kb import mission, ticket

FOLDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def plan_moves(tickets_dir: Path) -> tuple[list[tuple[Path, Path]], list[Path], list[str]]:
    """(moves, unsorted, notes) for the flat `*.md` files directly under
    `tickets_dir`. A valid `> Parent mission: M-x` line sends the file to
    `tickets_dir/M-x/<name>`; no line, or a malformed id, is `unsorted`."""
    moves: list[tuple[Path, Path]] = []
    unsorted: list[Path] = []
    notes: list[str] = []
    for path in sorted(tickets_dir.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            notes.append(f"skipped {path}: {exc}")
            continue
        m = ticket.PARENT_MISSION_RE.search(text)
        if m is None or not mission.MISSION_ID_RE.match(m.group(1)):
            unsorted.append(path)
            continue
        moves.append((path, tickets_dir / m.group(1) / path.name))
    return moves, unsorted, notes


def into_moves(tickets_dir: Path, folder: str, files: list[Path]) -> list[tuple[Path, Path]]:
    return [(f, tickets_dir / folder / f.name) for f in files]


def apply_moves(moves: list[tuple[Path, Path]]) -> tuple[list[tuple[Path, Path]], list[str]]:
    """Rename each (src, dst), creating dst's folder. Returns (done,
    conflicts); an existing dst leaves src where it is."""
    done: list[tuple[Path, Path]] = []
    conflicts: list[str] = []
    for src, dst in moves:
        if dst.exists():
            conflicts.append(f"conflict: {dst} already exists — left {src} in place")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        done.append((src, dst))
    return done, conflicts
