from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal, TypeVar

import yaml
from pydantic import BaseModel, Field

T = TypeVar("T", bound=BaseModel)


class SectionTokens(BaseModel):
    l2: int = 0
    l3: int = 0


class SectionEntry(BaseModel):
    id: str
    title: str
    summary: str = ""
    status: Literal["pending", "summarized", "reviewed"] = "pending"
    file: str
    tokens: SectionTokens = Field(default_factory=SectionTokens)


class IngestConfig(BaseModel):
    chapter_pattern: str
    appendix_pattern: str


class Manifest(BaseModel):
    id: str
    title: str
    revision: str = ""
    ingested: date | None = None
    source_sha256: str = ""
    sections: list[SectionEntry] = Field(default_factory=list)
    ingest: IngestConfig | None = None


class IndexEntry(BaseModel):
    id: str
    title: str
    revision: str = ""
    tags: list[str] = Field(default_factory=list)
    summary: str = ""


class KBIndex(BaseModel):
    docs: list[IndexEntry] = Field(default_factory=list)


def load_yaml_model(path: Path, model: type[T]) -> T:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return model.model_validate(data)


def save_yaml_model(path: Path, obj: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(
        obj.model_dump(mode="json"), allow_unicode=True, sort_keys=False
    )
    path.write_text(text, encoding="utf-8")
