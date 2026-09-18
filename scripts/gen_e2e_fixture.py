"""Generate tests-gate/fixtures/pending-kb/ using scaffold_doc() ITSELF.

This fixture is the "seam" of the e2e journey: it stands in for `kb ingest`,
which cannot run inside the release gate. Generating it with the real code
(instead of hand-typing it) is the first half of the anti-drift scheme; the
second half is tests/test_ingest_seam.py (Task 4), which re-runs this generator
and compares against the committed tree.

Run: python scripts/gen_e2e_fixture.py [dest]
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
            "type codes. Each designation ties to a boundary definition that "
            "governs entry and exit procedures for aircraft operating within "
            "the airspace."
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
    # index.yaml must exist first: scaffold_doc reads-then-writes it.
    (kb_dir / "index.yaml").write_text("docs: []\n", encoding="utf-8", newline="\n")
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
