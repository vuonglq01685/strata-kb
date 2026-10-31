"""`.kb-work/<doc>/sections.json`: each unit's page span, saved at ingest.

The L3 fix reads it to know which PDF pages a section covers; the ingest-time
fallback ids are kept so the fix can tell which sections the sectioner flagged.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from strata_kb.l3check.detect import SectionInput

FILE_NAME = "sections.json"


class UnitSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    file: str
    chapter: str
    page: int | None
    end_page: int | None


class SpansFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str
    units: list[UnitSpan]
    fallback_units: list[str]


def save(work_dir: Path, doc_id: str, data: SpansFile) -> None:
    path = work_dir / doc_id / FILE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data.model_dump_json(indent=1), encoding="utf-8", newline="\n")


def load(work_dir: Path, doc_id: str) -> SpansFile | None:
    path = work_dir / doc_id / FILE_NAME
    if not path.is_file():
        return None
    return SpansFile.model_validate_json(path.read_text(encoding="utf-8"))


def section_input(span: UnitSpan, l3: str) -> SectionInput:
    return SectionInput(span.id, span.chapter, span.page, span.end_page, l3)
