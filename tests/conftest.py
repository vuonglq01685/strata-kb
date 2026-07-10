from pathlib import Path

import pytest

from aero_kb import models

TABLE = "| Code | Meaning |\n|---|---|\n| P | Prohibited |\n| R | Restricted |"

L2_CONTENT = f"""## 1.1 Airspace Records

Condensed: airspace record structure with designation and type fields.

{TABLE}

## 1.2 Airway Records

Condensed: airway record structure, route identifiers.
"""

L3_CONTENT = f"""## 1.1 Airspace Records

Full raw text about airspace records. Designation, type, multiple code, level.

{TABLE}

## 1.2 Airway Records

Full raw text about airway records and route identifiers.
"""


@pytest.fixture
def fixture_kb(tmp_path: Path) -> Path:
    kb = tmp_path / ".kb"
    doc_dir = kb / "demo-doc"
    doc_dir.mkdir(parents=True)
    (doc_dir / "ch1-records.md").write_text(L2_CONTENT, encoding="utf-8")
    (doc_dir / "ch1-records.raw.md").write_text(L3_CONTENT, encoding="utf-8")
    manifest = models.Manifest(
        id="demo-doc",
        title="Demo Document",
        revision="Rev 1",
        sections=[
            models.SectionEntry(
                id="1.1",
                title="Airspace Records",
                summary="Airspace record structure: designation, type, level.",
                status="summarized",
                file="ch1-records",
            ),
            models.SectionEntry(
                id="1.2",
                title="Airway Records",
                summary="Airway record structure and route identifiers.",
                status="summarized",
                file="ch1-records",
            ),
        ],
    )
    models.save_yaml_model(doc_dir / "_manifest.yaml", manifest)
    index = models.KBIndex(
        docs=[
            models.IndexEntry(
                id="demo-doc",
                title="Demo Document",
                revision="Rev 1",
                tags=["demo", "airspace"],
                summary="Demo aviation data spec.",
            )
        ]
    )
    models.save_yaml_model(kb / "index.yaml", index)
    return kb
