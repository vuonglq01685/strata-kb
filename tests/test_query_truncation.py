"""Leg-cap truncation.

Reviewer C F-C7: `K_LEG = 50` caps each leg before RRF and nothing told the
caller. `record` matched 154 sections in FTS and returned 50; `runway` matched
63 and returned 50 — under a docstring that tells agents kb_search "Returns
every relevant section found". For a broad BA query that is a false assurance.
"""
import pytest

pytest.importorskip("sqlite_vec")

from center_kb import searchdb
from center_kb.federation import write_federation_index
from center_kb.hub import HubHandle
from center_kb.query import search_detailed


def _wide_hub(tmp_path, n_sections: int) -> HubHandle:
    """One doc whose N sections all contain the term 'record'."""
    from center_kb import models
    from center_kb.federation import FederationMeta

    fed = tmp_path / "hub" / "federation"
    entry = fed / "wide-kb" / "wide-doc"
    entry.mkdir(parents=True)
    (tmp_path / "hub" / ".kb").mkdir(parents=True)
    body = "".join(
        f"## {i}.0 Record {i}\n\nThis section describes record {i} in detail.\n\n"
        for i in range(1, n_sections + 1)
    )
    (entry / "ch1.md").write_text(body, encoding="utf-8")
    (entry / "ch1.raw.md").write_text(body, encoding="utf-8")
    models.save_yaml_model(
        entry / "_manifest.yaml",
        models.Manifest(
            id="wide-doc", title="Wide Doc",
            sections=[
                models.SectionEntry(
                    id=f"{i}.0", title=f"Record {i}",
                    summary=f"Record {i}.", status="summarized", file="ch1",
                )
                for i in range(1, n_sections + 1)
            ],
        ),
    )
    models.save_yaml_model(
        fed / "wide-kb" / "index.yaml",
        models.KBIndex(docs=[models.IndexEntry(
            id="wide-doc", title="Wide Doc", tags=["wide"], summary="Wide."
        )]),
    )
    models.save_yaml_model(
        fed / "wide-kb" / "_meta.yaml",
        FederationMeta(
            repo_id="wide-kb", source_commit="abc1234",
            published_at="2026-07-13T00:00:00+00:00",
        ),
    )
    write_federation_index(fed)
    return HubHandle(root=tmp_path / "hub")


def test_note_when_the_leg_cap_truncated(tmp_path):
    hub = _wide_hub(tmp_path, searchdb.K_LEG + 20)
    outcome = search_detailed(hub, "record", budget=10_000_000)
    assert any("more sections matched" in n for n in outcome.notes)


def test_no_note_when_everything_fit(tmp_path):
    hub = _wide_hub(tmp_path, searchdb.K_LEG - 10)
    outcome = search_detailed(hub, "record", budget=10_000_000)
    assert not any("more sections matched" in n for n in outcome.notes)
