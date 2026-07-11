from pathlib import Path

import pytest

from center_kb import models, summarize


def make_kb(tmp_path: Path, statuses: dict[str, str]) -> Path:
    """One doc 'd1', sections 1.1/1.2 in file ch1, with given statuses."""
    kb = tmp_path / ".kb"
    doc = kb / "d1"
    doc.mkdir(parents=True)
    (doc / "ch1.raw.md").write_text(
        "## 1.1 Alpha\n\nAlpha body text §2.3 code P.\n\n"
        "## 1.2 Beta\n\nBeta body text.\n",
        encoding="utf-8",
    )
    (doc / "ch1.md").write_text(
        "## 1.1 Alpha\n\n<!-- TODO:summarize 1.1 -->\n\n"
        "| Code | Meaning |\n|---|---|\n| P | Prohibited |\n\n"
        "## 1.2 Beta\n\n<!-- TODO:summarize 1.2 -->\n",
        encoding="utf-8",
    )
    manifest = models.Manifest(
        id="d1", title="Doc One",
        sections=[
            models.SectionEntry(id="1.1", title="Alpha", file="ch1",
                                status=statuses.get("1.1", "pending")),
            models.SectionEntry(id="1.2", title="Beta", file="ch1",
                                status=statuses.get("1.2", "pending")),
        ],
    )
    models.save_yaml_model(doc / "_manifest.yaml", manifest)
    index = models.KBIndex(docs=[models.IndexEntry(id="d1", title="Doc One")])
    models.save_yaml_model(kb / "index.yaml", index)
    return kb


def test_collect_pending_returns_only_pending_with_l3_body(tmp_path):
    kb = make_kb(tmp_path, {"1.2": "summarized"})
    pending = summarize.collect_pending(kb)
    assert [p.section_id for p in pending] == ["1.1"]
    assert pending[0].doc_id == "d1"
    assert pending[0].file == "ch1"
    assert "Alpha body text" in pending[0].l3_body


def test_collect_pending_filters_by_doc_id(tmp_path):
    kb = make_kb(tmp_path, {})
    assert summarize.collect_pending(kb, doc_id="other") == []
    assert len(summarize.collect_pending(kb, doc_id="d1")) == 2


def test_section_prompt_contains_body_rules_and_json_contract(tmp_path):
    kb = make_kb(tmp_path, {})
    section = summarize.collect_pending(kb)[0]
    prompt = summarize.build_section_prompt(section)
    assert "Alpha body text" in prompt
    assert "l2_summary" in prompt and "l1_summary" in prompt
    assert "20" in prompt and "30%" in prompt  # length target
    assert "25 words" in prompt
    assert "VERBATIM" in prompt


def test_parse_json_reply_accepts_clean_and_fenced_json():
    good = '{"l2_summary": "long text", "l1_summary": "short"}'
    keys = ("l2_summary", "l1_summary")
    assert summarize.parse_json_reply(good, keys)["l1_summary"] == "short"
    fenced = f"Here you go:\n```json\n{good}\n```\nDone."
    assert summarize.parse_json_reply(fenced, keys)["l2_summary"] == "long text"


@pytest.mark.parametrize("bad", [
    "no json at all",
    '{"l2_summary": "only one key"}',
    '{"l2_summary": "", "l1_summary": "x"}',
    '{"l2_summary": 5, "l1_summary": "x"}',
])
def test_parse_json_reply_rejects_bad_replies(bad):
    with pytest.raises(ValueError):
        summarize.parse_json_reply(bad, ("l2_summary", "l1_summary"))


def test_replace_marker_replaces_only_target_and_keeps_tables(tmp_path):
    kb = make_kb(tmp_path, {})
    l2 = (kb / "d1" / "ch1.md").read_text(encoding="utf-8")
    out = summarize.replace_marker(l2, "1.1", "Condensed alpha.")
    assert "Condensed alpha." in out
    assert "<!-- TODO:summarize 1.1 -->" not in out
    assert "<!-- TODO:summarize 1.2 -->" in out          # untouched
    assert "| P | Prohibited |" in out                   # table intact


def test_replace_marker_raises_when_marker_missing():
    with pytest.raises(ValueError):
        summarize.replace_marker("## 1.1 Alpha\n\ntext\n", "1.1", "s")
