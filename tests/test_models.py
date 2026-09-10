from datetime import date
from pathlib import Path

import pytest
import yaml
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


def test_section_entry_new_fields_default_absent_and_roundtrip(tmp_path: Path):
    sec = models.SectionEntry(id="1", title="T", file="f")
    assert sec.l3_sha256 is None and sec.provenance is None and sec.reviewed is None
    sec.provenance = models.Provenance(runner="claude", model="sonnet-5", effort="high",
                                       prompt_sha="abc123abc123", at="2026-09-09T10:00:00Z")
    sec.reviewed = models.ReviewRecord(by="d <d@x>", at="2026-09-09T11:00:00Z", l2_sha256="ff" * 32)
    sec.l3_sha256 = "aa" * 32
    m = models.Manifest(id="d", title="D", sections=[sec])
    path = tmp_path / "_manifest.yaml"
    models.save_yaml_model(path, m)
    loaded = models.load_yaml_model(path, models.Manifest)
    assert loaded == m
    assert loaded.sections[0].reviewed.by == "d <d@x>"


def test_save_omits_none_fields(tmp_path: Path):
    m = models.Manifest(id="d", title="D",
                        sections=[models.SectionEntry(id="1", title="T", file="f")])
    path = tmp_path / "_manifest.yaml"
    models.save_yaml_model(path, m)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "provenance" not in data["sections"][0]
    assert "reviewed" not in data["sections"][0]
    assert "l3_sha256" not in data["sections"][0]
    assert "ingested" not in data          # was already None → now omitted


def test_old_manifest_without_new_fields_loads(tmp_path: Path):
    path = tmp_path / "_manifest.yaml"
    path.write_text(
        "id: d\ntitle: D\nsections:\n- {id: '1', title: T, file: f, status: summarized, summary: s}\n",
        encoding="utf-8",
    )
    m = models.load_yaml_model(path, models.Manifest)
    assert m.sections[0].provenance is None and m.sections[0].l3_sha256 is None


def test_llm_effort_typo_is_rejected():
    with pytest.raises(ValidationError):
        models.LLMConfig(effort="hgih")
    assert models.LLMConfig(effort="medium").effort == "medium"


def test_bundled_manifests_roundtrip_byte_identical(tmp_path: Path):
    """exclude_none must not change how the shipped manifests serialise.

    Goes through models.save_yaml_model itself (the same path kb build uses,
    build.py:77), not a hand-rolled yaml.safe_dump — otherwise this test
    would not exercise (or protect) the code it claims to pin.
    """
    root = Path(__file__).resolve().parents[1]
    mans = sorted((root / ".kb").glob("*/_manifest.yaml"))
    assert mans, "no bundled .kb/*/_manifest.yaml found — glob root is wrong"
    for man in mans:
        text = man.read_text(encoding="utf-8")
        obj = models.load_yaml_model(man, models.Manifest)
        out = tmp_path / man.name
        models.save_yaml_model(out, obj)
        assert out.read_text(encoding="utf-8") == text, f"{man} would change on save"
