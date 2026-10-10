"""2026-10-10 review §6.2 F2: `slice_section` re-split the whole file per
section -- O(sections × bytes). `section_map` splits once; `slice_section`
must return byte-for-byte what the old per-call scan returned."""

from __future__ import annotations

import random
import time

import pytest

from strata_kb import mdutils
from strata_kb.mdutils import HEADING_RE, section_map, slice_section


def _old_slice(md: str, section_id: str, occurrence: int = 0) -> str | None:
    """The pre-1.13 implementation, kept here as the reference."""
    lines = md.splitlines()
    seen = -1
    start = None
    for i, line in enumerate(lines):
        m = HEADING_RE.match(line)
        if m and m.group("sid") == section_id:
            seen += 1
            if seen == occurrence:
                start = i
                break
    if start is None:
        return None
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            return "\n".join(lines[start:j]).strip()
    return "\n".join(lines[start:]).strip()


EDGE = "\n".join(
    [
        "preamble text",
        "## 1 One",
        "body one",
        "### 1.1 child",
        "child body",
        "##notaheading",
        "## ",  # a boundary that is not a heading
        "after empty heading",
        "## 2 Two",
        "",
        "| a | b |",
        "## 1 Repeated id",
        "second one",
        "## 3",
        "## 4 Last\t ",
        "tail",
        "",
    ]
)


@pytest.mark.parametrize("sid", ["1", "1.1", "2", "3", "4", "missing", ""])
@pytest.mark.parametrize("occ", [0, 1, 2, -1])
def test_edge_cases_match_the_old_scan(sid, occ):
    assert slice_section(EDGE, sid, occ) == _old_slice(EDGE, sid, occ)


def test_random_documents_match_the_old_scan():
    rng = random.Random(7)  # noqa: S311 -- a seeded fuzz input, not crypto
    for _ in range(200):
        lines = []
        for _ in range(rng.randint(0, 40)):
            kind = rng.random()
            if kind < 0.3:
                sid = rng.choice(["1", "2", "2.1", "x", "é"])
                suffix = rng.choice(["", " Title", "\tT", " "])
                lines.append("## " + sid + suffix)
            elif kind < 0.35:
                lines.append(rng.choice(["## ", "##x", "### 2 sub", "  ## 1 indented"]))
            else:
                lines.append(rng.choice(["text", "", "| a |", "```", "~~~"]))
        md = "\n".join(lines) + rng.choice(["", "\n", "\r\n"])
        for sid in ("1", "2", "2.1", "x", "é", "none"):
            for occ in range(3):
                assert slice_section(md, sid, occ) == _old_slice(md, sid, occ), (
                    md,
                    sid,
                    occ,
                )


def test_section_map_lists_repeated_ids_in_file_order():
    m = section_map(EDGE)
    assert [b.splitlines()[0] for b in m["1"]] == ["## 1 One", "## 1 Repeated id"]
    assert "3" in m and m["3"] == ("## 3",)


def test_slicing_every_section_of_a_big_file_is_linear():
    n = 500
    md = "\n".join(f"## {i} Title {i}\n\n" + "body text line\n" * 40 for i in range(n))
    mdutils.section_map.cache_clear()
    t0 = time.perf_counter()
    for i in range(n):
        assert slice_section(md, str(i)) is not None
    elapsed = time.perf_counter() - t0
    # The old scan took ~1.6 ms per call on a 1 MB file (0.8 s for 500);
    # one split plus 500 dict lookups is a small fraction of that.
    assert elapsed < 0.25, elapsed


def test_searchdb_reads_each_file_once_per_document(tmp_path, monkeypatch):
    from pathlib import Path

    from strata_kb import models, searchdb

    doc = tmp_path / "d"
    doc.mkdir()
    secs = [
        models.SectionEntry(id=str(i), title=f"T{i}", file="ch1") for i in range(50)
    ]
    text = "\n".join(f"## {i} T{i}\n\nbody {i}\n" for i in range(50))
    (doc / "ch1.md").write_text(text, encoding="utf-8")
    (doc / "ch1.raw.md").write_text(text, encoding="utf-8")
    reads: list[str] = []
    real = Path.read_text

    def counting(self, *a, **k):
        reads.append(self.name)
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", counting)
    texts: dict = {}
    parts = [searchdb._section_parts(tmp_path, "d", s, texts) for s in secs]
    assert sorted(reads) == ["ch1.md", "ch1.raw.md"]
    assert parts[7][2].startswith("## 7 T7")
