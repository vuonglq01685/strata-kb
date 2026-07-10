from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from aero_kb import models


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
