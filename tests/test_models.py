from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from center_kb import models


def test_manifest_yaml_roundtrip(tmp_path: Path):
    manifest = models.Manifest(
        id="arinc-424",
        title="ARINC 424",
        revision="Supplement 22",
        ingested=date(2026, 7, 10),
        sections=[
            models.SectionEntry(
                id="5.3",
                title="Restrictive Airspace",
                summary="UR/PR record structure.",
                status="summarized",
                file="ch5-navigation-data",
                tokens=models.SectionTokens(l2=810, l3=2900),
            )
        ],
    )
    path = tmp_path / "_manifest.yaml"
    models.save_yaml_model(path, manifest)
    loaded = models.load_yaml_model(path, models.Manifest)
    assert loaded == manifest


def test_section_entry_defaults_pending():
    sec = models.SectionEntry(id="1.1", title="General", file="ch1-general")
    assert sec.status == "pending"
    assert sec.summary == ""
    assert sec.tokens.l2 == 0


def test_invalid_status_rejected():
    with pytest.raises(ValidationError):
        models.SectionEntry(id="1.1", title="x", file="f", status="done")


def test_index_yaml_roundtrip(tmp_path: Path):
    index = models.KBIndex(
        docs=[
            models.IndexEntry(
                id="arinc-424",
                title="ARINC 424",
                tags=["arinc424", "navdata"],
                summary="Navigation data spec.",
            )
        ]
    )
    path = tmp_path / "index.yaml"
    models.save_yaml_model(path, index)
    loaded = models.load_yaml_model(path, models.KBIndex)
    assert loaded == index
    assert "arinc424" in path.read_text()


def test_kbindex_without_llm_block_gets_defaults(tmp_path):
    p = tmp_path / "index.yaml"
    p.write_text("docs: []\n", encoding="utf-8")
    index = models.load_yaml_model(p, models.KBIndex)
    assert index.llm.runner == "auto"
    assert index.llm.model == "sonnet-5"
    assert index.llm.effort == "high"
    assert index.llm.max_workers == 5
    assert index.llm.timeout == 300


def test_kbindex_llm_block_roundtrip(tmp_path):
    p = tmp_path / "index.yaml"
    p.write_text(
        "docs: []\nllm:\n  runner: copilot\n  model: gpt-5\n  max_workers: 2\n",
        encoding="utf-8",
    )
    index = models.load_yaml_model(p, models.KBIndex)
    assert index.llm.runner == "copilot"
    assert index.llm.model == "gpt-5"
    assert index.llm.max_workers == 2
    models.save_yaml_model(p, index)
    assert "runner: copilot" in p.read_text(encoding="utf-8")


def test_federation_index_roundtrip(tmp_path):
    from center_kb.models import (
        FederationIndex,
        FedIndexEntry,
        load_yaml_model,
        save_yaml_model,
    )

    idx = FederationIndex(
        docs=[
            FedIndexEntry(
                repo_id="arinc-kb",
                doc_id="arinc-424",
                title="ARINC 424",
                revision="Supplement 22",
                tags=["arinc424"],
                summary="Nav DB spec.",
                source_commit="abc1234",
                published_at="2026-07-13T00:00:00+00:00",
            )
        ]
    )
    path = tmp_path / "index.yaml"
    save_yaml_model(path, idx)
    loaded = load_yaml_model(path, FederationIndex)
    assert loaded == idx


def test_federation_index_defaults():
    from center_kb.models import FederationIndex, FedIndexEntry

    e = FedIndexEntry(repo_id="r", doc_id="d")
    assert e.tags == [] and e.revision == "" and e.published_at == ""
    assert FederationIndex().docs == []


def test_section_status_still_parses_reviewed():
    from center_kb.models import SectionEntry

    sec = SectionEntry(id="1.1", title="T", file="ch1", status="reviewed")
    assert sec.status == "reviewed"
