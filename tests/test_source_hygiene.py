"""Source hygiene rules for src/strata_kb that ruff cannot express.

1. Every module opens with a docstring saying what it is for.
2. No comment or docstring points at an internal review artefact
   ("F-D9", "wave I-1 round 4", "fix round 1, Important 3", "spec
   2026-09-25 §4.1", ...). Those artefacts change or disappear, and the
   comment loses its meaning with them. Keep the rationale in the code,
   the history in CHANGELOG.md and git.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "strata_kb"
MODULES = sorted(SRC.rglob("*.py"))

_PROVENANCE_RE = re.compile(
    r"\bF-[A-Z]{1,2}\d+\b"  # review finding ids: F-D9, F-C10
    r"|\b[Ww]ave [A-Z]\d*(?:-\d+)?\b"  # Wave G, wave I-1, wave L1
    r"|\b[Ff]ix round\b"
    r"|\bround[- ]\d+\b"  # round 4, round-3
    r"|\bP[1-9]\d\b"  # brief rulings: P45, ruling P53
    r"|\bspec 20\d\d-\d\d-\d\d\b"
    r"|\b20\d\d-\d\d-\d\d review\b"
    r"|\breviewer [A-Z]\b"
    r"|\b(?:HIGH|MEDIUM|LOW)-\d+\b"
    r"|\b(?:Critical|Important|Minor) \d+\b"
    r"|\broadmap [A-Z]\d+\b"
)


def _rel(path: Path) -> str:
    return path.relative_to(SRC.parent).as_posix()


def test_modules_are_found() -> None:
    assert len(MODULES) > 100


@pytest.mark.parametrize("path", MODULES, ids=_rel)
def test_module_has_a_docstring(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    doc = ast.get_docstring(tree)
    assert doc and doc.strip(), f"{_rel(path)} has no module docstring"


def test_no_comment_points_at_an_internal_review() -> None:
    hits = [
        f"{_rel(path)}:{lineno}: {line.strip()}"
        for path in MODULES
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        )
        if _PROVENANCE_RE.search(line)
    ]
    assert not hits, "\n".join(hits)


@pytest.mark.parametrize(
    "line",
    [
        "# F-D9 finding 2: keep the order",
        "# (Wave G fix round 2, item 7)",
        "# wave I-1 round 4",
        "# ruling P53",
        "# spec 2026-09-25 §4.1",
        "# 2026-10-10 review B4",
        "# Fix round 1, Important 3",
        "# HIGH-2 round 2",
        "# (reviewer F L2)",
    ],
)
def test_the_pattern_catches_known_shapes(line: str) -> None:
    assert _PROVENANCE_RE.search(line)


@pytest.mark.parametrize(
    "line",
    [
        "# L2 summaries are written by summarize",
        "# wave n = tasks whose every Depends on: sits in an earlier wave",
        "# round-trip the YAML",
        "# at most 3 rounds",
        '"... run another review round"',
        '"fix them and re-review"',
        "# Python 3.11",
    ],
)
def test_the_pattern_leaves_ordinary_prose_alone(line: str) -> None:
    assert not _PROVENANCE_RE.search(line)
