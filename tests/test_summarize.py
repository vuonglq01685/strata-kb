import json as _json
from pathlib import Path

import pytest

from center_kb import models, summarize
from center_kb.llm import RunnerError
from center_kb.summarize import collect_pending, strip_tables


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


class FakeRunner:
    """Duck-typed stand-in for llm.Runner. Scripted replies per call order."""
    name = "fake"

    def __init__(self, reply=None, fail_ids=(), fail_times=2):
        self._reply = reply
        self._fail_ids = set(fail_ids)
        self._fail_times = fail_times
        self._fail_count: dict[str, int] = {}
        self.calls: list[str] = []

    def run(self, prompt: str) -> str:
        self.calls.append(prompt)
        for sid in self._fail_ids:
            if f"Section {sid} " in prompt:
                n = self._fail_count.get(sid, 0)
                if n < self._fail_times:
                    self._fail_count[sid] = n + 1
                    raise RunnerError("boom")
        if "one-line summaries" in prompt:  # doc-summary call
            return _json.dumps({"summary": "Doc-level summary."})
        return self._reply or _json.dumps(
            {"l2_summary": "Condensed text.", "l1_summary": "One line."}
        )


def test_summarize_kb_fills_l2_manifest_and_doc_summary(tmp_path):
    kb = make_kb(tmp_path, {})
    report = summarize.summarize_kb(kb, FakeRunner(), max_workers=2)
    assert sorted(report.summarized) == ["d1/1.1", "d1/1.2"]
    assert report.failed == [] and report.ok
    l2 = (kb / "d1" / "ch1.md").read_text(encoding="utf-8")
    assert "TODO:summarize" not in l2
    assert "Condensed text." in l2
    assert "| P | Prohibited |" in l2  # table survived
    manifest = models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest)
    assert all(s.status == "summarized" for s in manifest.sections)
    assert all(s.summary == "One line." for s in manifest.sections)
    index = models.load_yaml_model(kb / "index.yaml", models.KBIndex)
    assert index.docs[0].summary == "Doc-level summary."


def test_summarize_kb_failed_section_stays_pending(tmp_path):
    kb = make_kb(tmp_path, {})
    report = summarize.summarize_kb(kb, FakeRunner(fail_ids={"1.2"}), max_workers=2)
    assert report.summarized == ["d1/1.1"]
    assert report.failed == ["d1/1.2"] and not report.ok
    manifest = models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest)
    by_id = {s.id: s for s in manifest.sections}
    assert by_id["1.1"].status == "summarized"
    assert by_id["1.2"].status == "pending"
    l2 = (kb / "d1" / "ch1.md").read_text(encoding="utf-8")
    assert "<!-- TODO:summarize 1.2 -->" in l2
    index = models.load_yaml_model(kb / "index.yaml", models.KBIndex)
    assert index.docs[0].summary == ""  # doc not complete → no doc summary


def test_summarize_kb_retries_once_then_succeeds(tmp_path):
    kb = make_kb(tmp_path, {})
    runner = FakeRunner(fail_ids={"1.1"}, fail_times=1)  # fails once, retry OK
    report = summarize.summarize_kb(kb, runner, max_workers=1)
    assert report.ok and sorted(report.summarized) == ["d1/1.1", "d1/1.2"]


def test_summarize_kb_no_pending_is_noop(tmp_path):
    kb = make_kb(tmp_path, {"1.1": "summarized", "1.2": "reviewed"})
    runner = FakeRunner()
    report = summarize.summarize_kb(kb, runner)
    assert report.summarized == [] and report.failed == []
    assert runner.calls == []


class OSErrorOnceRunner:
    """Raises a bare OSError (e.g. E2BIG from subprocess.run) for one section
    only; other sections succeed normally. Simulates argv-too-large or
    executable-vanished failures that llm.Runner.run can let escape
    uncaught — these must not abort the whole batch."""

    name = "fake"

    def __init__(self, fail_id: str):
        self._fail_id = fail_id

    def run(self, prompt: str) -> str:
        if f"Section {self._fail_id} " in prompt:
            raise OSError("E2BIG")
        if "one-line summaries" in prompt:  # doc-summary call
            return _json.dumps({"summary": "Doc-level summary."})
        return _json.dumps(
            {"l2_summary": "Condensed text.", "l1_summary": "One line."}
        )


def test_summarize_kb_survives_bare_oserror_from_one_section(tmp_path):
    """A raw OSError (ARG_MAX overflow, vanished executable, etc.) from one
    section's runner.run must not propagate out of summarize_kb and discard
    the other section's successful result."""
    kb = make_kb(tmp_path, {})
    report = summarize.summarize_kb(kb, OSErrorOnceRunner(fail_id="1.2"), max_workers=2)
    assert report.summarized == ["d1/1.1"]
    assert report.failed == ["d1/1.2"] and not report.ok
    manifest = models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest)
    by_id = {s.id: s for s in manifest.sections}
    assert by_id["1.1"].status == "summarized"
    assert by_id["1.2"].status == "pending"


def test_strip_tables_replaces_block_with_placeholder():
    text = "intro line\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\noutro line"
    out = strip_tables(text)
    assert "| a | b |" not in out
    assert out.count("[table omitted]") == 1
    assert "intro line" in out and "outro line" in out


def test_strip_tables_multiple_blocks_and_edges():
    text = "| t1 |\n| x |\nprose between\n| t2 |\n| y |"
    out = strip_tables(text)
    assert out.count("[table omitted]") == 2
    assert "prose between" in out
    assert "| t1 |" not in out and "| y |" not in out


def test_strip_tables_no_tables_is_identity_modulo_whitespace():
    text = "just prose\n\nmore prose"
    assert strip_tables(text) == text


def test_collect_pending_strips_tables_and_flags_table_only(tmp_path):
    kb = tmp_path / ".kb"
    (kb / "doc1").mkdir(parents=True)
    (kb / "index.yaml").write_text(
        "docs:\n- id: doc1\n  title: Doc One\n", encoding="utf-8"
    )
    raw = (
        "## 1 Prose Section\n\nSome prose here.\n\n| h |\n|---|\n| v |\n\n"
        "## 2 Table Only\n\n| h2 |\n|----|\n| v2 |\n"
    )
    (kb / "doc1" / "f1.raw.md").write_text(raw, encoding="utf-8")
    (kb / "doc1" / "_manifest.yaml").write_text(
        "id: doc1\ntitle: Doc One\nrevision: ''\n"
        "ingested: 2026-07-11\nsource_sha256: ''\n"
        "ingest: {chapter_pattern: x, appendix_pattern: y}\n"
        "sections:\n"
        "- {id: '1', title: Prose Section, file: f1, status: pending}\n"
        "- {id: '2', title: Table Only, file: f1, status: pending}\n",
        encoding="utf-8",
    )
    pending = collect_pending(kb)
    by_id = {p.section_id: p for p in pending}
    assert "| h |" not in by_id["1"].l3_body
    assert "[table omitted]" in by_id["1"].l3_body
    assert "Some prose here." in by_id["1"].l3_body
    assert by_id["1"].table_only is False
    assert by_id["2"].table_only is True
