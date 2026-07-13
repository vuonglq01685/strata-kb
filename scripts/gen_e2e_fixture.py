"""Sinh tests-gate/fixtures/pending-kb/ bằng CHÍNH scaffold_doc().

Fixture này là "vết nối" của hành trình e2e: nó thế chỗ cho `kb ingest`, thứ
không chạy được trong cửa release. Sinh nó bằng code thật (thay vì gõ tay) là
nửa đầu của cách chống trôi; nửa sau là tests/test_ingest_seam.py (Task 4),
chạy lại generator này và so với cây đã commit.

Chạy: python scripts/gen_e2e_fixture.py [dest]
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from center_kb.ingest.scaffold import scaffold_doc
from center_kb.ingest.sectioner import SectionUnit

TABLE = "| Code | Meaning |\n|---|---|\n| P | Prohibited |\n| R | Restricted |"

UNITS = [
    SectionUnit(
        id="1.1",
        title="Airspace Records",
        chapter="1",
        body_md=(
            "Airspace records carry a designation, a type, a multiple code and "
            "a level. Restrictive airspace uses the prohibited and restricted "
            "type codes."
        ),
        tables=[TABLE],
    ),
    SectionUnit(
        id="1.2",
        title="Airway Records",
        chapter="1",
        body_md=(
            "Airway records carry route identifiers, sequence numbers and the "
            "fixes that make up the route."
        ),
        tables=[],
    ),
]


def generate(kb_dir: Path) -> None:
    if kb_dir.exists():
        shutil.rmtree(kb_dir)
    kb_dir.mkdir(parents=True)
    # index.yaml phải tồn tại trước: scaffold_doc đọc-rồi-ghi nó.
    (kb_dir / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    scaffold_doc(
        UNITS,
        doc_id="demo-doc",
        title="Demo Document",
        tags=["demo", "airspace"],
        revision="Rev 1",
        source_path=None,
        kb_dir=kb_dir,
    )


if __name__ == "__main__":
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).parent.parent / "tests-gate" / "fixtures" / "pending-kb"
    )
    generate(dest)
    print(f"generated {dest}")
