"""`kb impl tidy` — move flat `docs/impl/<id>-*` into `docs/impl/<id>/`.

Spec 2026-10-06-impl-per-ticket-folder-design. `<id>-design.md`,
`<id>-plan.md`, `<id>-context.md` become `<id>/design.md` … and the
`<id>-review/` folder becomes `<id>/review/`. Idempotent; an existing
destination is a conflict, never an overwrite. No git — the Dev commits and
git detects the rename.
"""

from __future__ import annotations

import re
from pathlib import Path

from strata_kb.tickettidy import apply_moves

_FILE_RE = re.compile(r"^(?P<id>.+)-(?P<kind>design|plan|context)\.md$")
_REVIEW_RE = re.compile(r"^(?P<id>.+)-review$")


def plan_moves(impl_dir: Path) -> list[tuple[Path, Path]]:
    """(src, dst) for every flat ticket entry directly under `impl_dir`."""
    moves: list[tuple[Path, Path]] = []
    for path in sorted(impl_dir.iterdir()):
        if path.is_file() and (m := _FILE_RE.match(path.name)):
            moves.append((path, impl_dir / m["id"] / f"{m['kind']}.md"))
        elif path.is_dir() and (m := _REVIEW_RE.match(path.name)):
            moves.append((path, impl_dir / m["id"] / "review"))
    return moves


def tidy(impl_dir: Path) -> tuple[list[tuple[Path, Path]], list[str]]:
    """Apply `plan_moves`; (done, conflicts). No `impl_dir` → nothing to do."""
    if not impl_dir.is_dir():
        return [], []
    return apply_moves(plan_moves(impl_dir))
