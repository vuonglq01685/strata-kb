import json as _json
from pathlib import Path

import pytest

from strata_kb import models, summarize
from strata_kb.llm import RunnerError
from strata_kb.summarize import (
    RedoItem,
    RedoPlan,
    collect_pending,
    plan_redo,
    rebuild_l2_scaffold,
    redo_reset,
    reset_section_prose,
    strip_tables,
)


@pytest.fixture(autouse=True)
def _no_retry_pause(monkeypatch):
    monkeypatch.setattr(summarize, "RETRY_PAUSE_SECONDS", 0.0)


def make_kb(tmp_path: Path, statuses: dict[str, str], short: bool = False) -> Path:
    """One doc 'd1', sections 1.1/1.2 in file ch1, with given statuses.

    By default the L3 bodies are long prose (> 200 chars) so every section
    is an `llm` section and needs the runner. With `short=True` the bodies
    are short one-liners (brief sections, no LLM call) — used only by the
    provenance test that wants runner "none".
    """
    kb = tmp_path / ".kb"
    doc = kb / "d1"
    doc.mkdir(parents=True)
    if short:
        alpha_body = "Alpha body text §2.3 code P."
        beta_body = "Beta body text."
    else:
        alpha_body = "Alpha body text §2.3 code P. " * 12
        beta_body = "Beta body text. " * 20
    (doc / "ch1.raw.md").write_text(
        f"## 1.1 Alpha\n\n{alpha_body}\n\n"
        f"## 1.2 Beta\n\n{beta_body}\n",
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


def test_replace_marker_occurrence_targets_the_nth_marker_for_that_id():
    text = "<!-- TODO:summarize 1.1 -->\n\n<!-- TODO:summarize 1.1 -->\n"
    out = summarize.replace_marker(text, "1.1", "SUM-B", occurrence=1)
    assert out == "<!-- TODO:summarize 1.1 -->\n\nSUM-B\n"


def test_replace_marker_occurrence_out_of_range_raises():
    text = "<!-- TODO:summarize 1.1 -->\n"
    with pytest.raises(ValueError):
        summarize.replace_marker(text, "1.1", "s", occurrence=1)


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


OBJ = '{"l2_summary": "long text", "l1_summary": "short"}'


@pytest.mark.parametrize("reply", [
    f"```json\n{OBJ}\n```",
    f"Sure! Here is the JSON:\n{OBJ}",
    f"{OBJ}\nHope that helps!",
    f"{OBJ}\nNote: use {{curly}} braces carefully.",
    f"Analysis {{of the section}}\n{OBJ}",
    f"{OBJ}\n{OBJ}",
    '{"l2_summary": "has {5.3} inside", "l1_summary": "esc \\"q\\""}',
    f"[{OBJ}]",
])
def test_parse_json_reply_survives_realistic_wrappers(reply):
    out = summarize.parse_json_reply(reply, ("l2_summary", "l1_summary"))
    assert (out["l1_summary"], out["l2_summary"]) in (
        ("short", "long text"),
        ('esc "q"', "has {5.3} inside"),
    )


def test_parse_json_reply_prefers_fenced_object_over_an_earlier_bare_one():
    fenced_obj = '{"l2_summary": "fenced wins", "l1_summary": "fenced"}'
    bare_obj = '{"l2_summary": "bare loses", "l1_summary": "bare"}'
    # The bare object comes FIRST in the text — if `_candidates` did not
    # give fenced blocks precedence over `_balanced_spans`'s left-to-right
    # scan, this earlier bare object would win instead.
    text = f"Draft: {bare_obj}\n```json\n{fenced_obj}\n```"
    out = summarize.parse_json_reply(text, ("l2_summary", "l1_summary"))
    assert out == {"l2_summary": "fenced wins", "l1_summary": "fenced"}


@pytest.mark.parametrize("bad", [
    '{"l2_summary": "x", "l1_summary": "y",}',            # trailing comma
    "{'l2_summary': 'x', 'l1_summary': 'y'}",             # single quotes
])
def test_parse_json_reply_still_rejects_invalid_json(bad):
    with pytest.raises(ValueError, match="no JSON object"):
        summarize.parse_json_reply(bad, ("l2_summary", "l1_summary"))


def _give_sections_real_summaries(kb: Path, doc_id: str = "d1") -> None:
    """Set a non-empty per-section `summary` on every section of `doc_id`'s
    manifest — the realistic state of a doc whose sections are all done,
    as opposed to a manifest whose rows are non-pending but never got a
    real summary written (e.g. a hand-built fixture, or a zero-section
    manifest)."""
    mpath = kb / doc_id / "_manifest.yaml"
    manifest = models.load_yaml_model(mpath, models.Manifest)
    for sec in manifest.sections:
        sec.summary = f"{sec.title} done."
    models.save_yaml_model(mpath, manifest)


def test_no_pending_but_empty_l0_refreshes_doc_summary(tmp_path):
    kb = make_kb(tmp_path, {"1.1": "summarized", "1.2": "reviewed"})
    _give_sections_real_summaries(kb)
    runner = FakeRunner()
    report = summarize.summarize_kb(kb, runner)
    assert report.ok and report.summarized == []
    assert len(runner.calls) == 1 and "one-line summaries" in runner.calls[0]
    index = models.load_yaml_model(kb / "index.yaml", models.KBIndex)
    assert index.docs[0].summary == "Doc-level summary."


def test_no_pending_and_l0_present_is_noop(tmp_path):
    kb = make_kb(tmp_path, {"1.1": "summarized", "1.2": "reviewed"})
    _give_sections_real_summaries(kb)  # otherwise the blank-section guard
    # alone would skip the doc, leaving entry.summary.strip() unexercised.
    ipath = kb / "index.yaml"
    idx = models.load_yaml_model(ipath, models.KBIndex)
    idx.docs[0].summary = "Already there."
    models.save_yaml_model(ipath, idx)
    runner = FakeRunner()
    summarize.summarize_kb(kb, runner)
    assert runner.calls == []


def test_l0_refresh_skipped_when_no_section_has_a_summary(tmp_path):
    """Sections are all non-pending (status-wise "done") but none of them
    ever got a real `summary` written — a zero-section manifest is the
    same case in spirit. Must not call the runner nor fabricate an L0
    sentence from an empty/blank bullet list."""
    kb = make_kb(tmp_path, {"1.1": "summarized", "1.2": "reviewed"})
    runner = FakeRunner()
    report = summarize.summarize_kb(kb, runner)
    assert report.ok
    assert runner.calls == []
    index = models.load_yaml_model(kb / "index.yaml", models.KBIndex)
    assert index.docs[0].summary == ""


def test_doc_summary_failure_is_counted(tmp_path):
    kb = make_kb(tmp_path, {})

    class DocFails(FakeRunner):
        def run(self, prompt):
            if "one-line summaries" in prompt:
                raise RunnerError("529")
            return super().run(prompt)

    report = summarize.summarize_kb(kb, DocFails(), max_workers=1)
    assert report.failed == ["d1/<doc-summary>"] and not report.ok


def test_doc_summary_bad_json_reply_is_counted_as_failure(tmp_path):
    """Covers the ValueError leg of `except (RunnerError, ValueError)` in
    _fill_doc_summaries — as opposed to test_doc_summary_failure_is_counted,
    which covers the RunnerError leg."""
    kb = make_kb(tmp_path, {"1.1": "summarized", "1.2": "reviewed"})
    _give_sections_real_summaries(kb)

    class GarbageDocReply(FakeRunner):
        def run(self, prompt):
            if "one-line summaries" in prompt:
                return "not json"
            return super().run(prompt)

    report = summarize.summarize_kb(kb, GarbageDocReply())
    assert report.failed == ["d1/<doc-summary>"] and not report.ok
    index = models.load_yaml_model(kb / "index.yaml", models.KBIndex)
    assert index.docs[0].summary == ""


def _add_second_doc(kb: Path, section_summary: str = "Gamma done.") -> None:
    """Add doc 'd2': one non-pending section with a real summary, but an
    empty L0 `summary` of its own — for cross-doc scoping tests."""
    doc = kb / "d2"
    doc.mkdir(parents=True)
    (doc / "ch1.raw.md").write_text("## 2.1 Gamma\n\nGamma body.\n", encoding="utf-8")
    (doc / "ch1.md").write_text("## 2.1 Gamma\n\nGamma done.\n", encoding="utf-8")
    manifest = models.Manifest(
        id="d2", title="Doc Two",
        sections=[models.SectionEntry(id="2.1", title="Gamma", file="ch1",
                                       status="summarized", summary=section_summary)],
    )
    models.save_yaml_model(doc / "_manifest.yaml", manifest)
    index_path = kb / "index.yaml"
    index = models.load_yaml_model(index_path, models.KBIndex)
    index.docs.append(models.IndexEntry(id="d2", title="Doc Two"))
    models.save_yaml_model(index_path, index)


def test_summarize_kb_refreshes_l0_for_every_in_scope_doc_when_nothing_pending(tmp_path):
    kb = make_kb(tmp_path, {"1.1": "summarized", "1.2": "reviewed"})
    _give_sections_real_summaries(kb)
    _add_second_doc(kb)
    report = summarize.summarize_kb(kb, FakeRunner())
    assert report.ok
    index = models.load_yaml_model(kb / "index.yaml", models.KBIndex)
    by_id = {e.id: e for e in index.docs}
    assert by_id["d1"].summary == "Doc-level summary."
    assert by_id["d2"].summary == "Doc-level summary."


def test_summarize_kb_doc_id_scopes_l0_refresh_to_that_doc_only(tmp_path):
    kb = make_kb(tmp_path, {"1.1": "summarized", "1.2": "reviewed"})
    _give_sections_real_summaries(kb)
    _add_second_doc(kb)
    report = summarize.summarize_kb(kb, FakeRunner(), doc_id="d1")
    assert report.ok
    index = models.load_yaml_model(kb / "index.yaml", models.KBIndex)
    by_id = {e.id: e for e in index.docs}
    assert by_id["d1"].summary == "Doc-level summary."
    assert by_id["d2"].summary == ""  # out of scope — untouched
    manifest2 = models.load_yaml_model(kb / "d2" / "_manifest.yaml", models.Manifest)
    assert manifest2.sections[0].summary == "Gamma done."  # untouched


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
    assert by_id["1"].kind == "brief" and by_id["1"].table_only is False
    assert by_id["2"].kind == "table_only" and by_id["2"].table_only is True
    assert by_id["1"].row == 0 and by_id["2"].row == 1
    assert len(by_id["1"].l3_sha256) == 64


from strata_kb.summarize import PendingSection, _summarize_one


class _ExplodingRunner:
    name = "exploding"

    def run(self, prompt: str) -> str:  # pragma: no cover - must not be called
        raise AssertionError("runner.run must not be called for table-only sections")


def test_table_only_section_skips_llm():
    sec = PendingSection("doc1", "2", "Table Only", "f1", "## 2 Table Only\n\n[table omitted]")
    result = _summarize_one(_ExplodingRunner(), sec)
    assert result == {"l2_summary": "", "l1_summary": "Table-only section: Table Only."}


def test_brief_section_copies_prose_verbatim_without_llm():
    body = "## 5.320 HAL\n\nUsed On: PA\nLength: 3\n\n[table omitted]"
    sec = PendingSection("doc1", "5.320", "HAL", "f1", body)
    assert sec.kind == "brief"
    result = _summarize_one(_ExplodingRunner(), sec)
    assert result == {"l2_summary": "Used On: PA\nLength: 3", "l1_summary": "Brief section: HAL."}


import json

from strata_kb.summarize import build_section_prompt


def _prose_section(prose: str) -> PendingSection:
    return PendingSection("doc1", "1", "Prose", "f1", prose)


def test_budget_is_measured_on_prose_not_on_headings_or_placeholders():
    body = "## 1 Prose\n\n[table omitted]\n\n" + "p" * 2000 + "\n\n[table omitted]"
    sec = _prose_section(body)
    assert sec.prose_chars == 2000
    prompt = build_section_prompt(sec)
    assert "at most 700 characters" in prompt
    assert "[table omitted]" in prompt           # rule mentions the marker
    assert "Never describe, list, or reconstruct table contents" in prompt


class _ScriptedRunner:
    """Returns queued replies; records prompts."""

    name = "scripted"

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def run(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.replies.pop(0)


def _reply(l2: str) -> str:
    return json.dumps({"l2_summary": l2, "l1_summary": "One line."})


def test_length_guard_passes_short_reply():
    runner = _ScriptedRunner([_reply("short summary")])
    result = _summarize_one(runner, _prose_section("p" * 2000))
    assert result["l2_summary"] == "short summary"
    assert len(runner.prompts) == 1


def test_length_guard_retries_then_accepts():
    runner = _ScriptedRunner([_reply("x" * 800), _reply("y" * 100)])
    result = _summarize_one(runner, _prose_section("p" * 2000))  # limit 700
    assert result["l2_summary"] == "y" * 100
    assert len(runner.prompts) == 2
    assert "over the 700-character hard limit" in runner.prompts[1]


def test_length_guard_fails_after_two_long_replies():
    runner = _ScriptedRunner([_reply("x" * 800), _reply("z" * 800)])
    with pytest.raises(RunnerError, match="too long"):
        _summarize_one(runner, _prose_section("p" * 2000))


L2_WITH_SUMMARIES = (
    "## 1 Prose Section\n\nAn old summary paragraph.\nSecond line of it.\n\n"
    "| h |\n|---|\n| v |\n\n"
    "## 2 Table Only\n\n| h2 |\n|----|\n| v2 |\n"
)


def test_rebuild_l2_scaffold_restores_markers_keeps_tables():
    out = rebuild_l2_scaffold(L2_WITH_SUMMARIES)
    assert "<!-- TODO:summarize 1 -->" in out
    assert "<!-- TODO:summarize 2 -->" in out
    assert "An old summary paragraph." not in out
    assert "| h |" in out and "| v2 |" in out
    # headings preserved
    assert "## 1 Prose Section" in out and "## 2 Table Only" in out


def test_rebuild_l2_scaffold_is_idempotent():
    once = rebuild_l2_scaffold(L2_WITH_SUMMARIES)
    assert rebuild_l2_scaffold(once) == once


L2_WITH_FIGURE = (
    "## 1 Prose Section\n\nAn old summary paragraph.\n\n"
    "| h |\n|---|\n| v |\n\nFigure: Holding pattern entry sectors\n\n"
    "## 2 Table Only\n\n| h2 |\n|----|\n| v2 |\n"
)
SCAFFOLD_WITH_FIGURE = (
    "## 1 Prose Section\n\n<!-- TODO:summarize 1 -->\n\n"
    "| h |\n|---|\n| v |\n\nFigure: Holding pattern entry sectors\n\n"
    "## 2 Table Only\n\n<!-- TODO:summarize 2 -->\n\n| h2 |\n|----|\n| v2 |\n"
)


def test_rebuild_l2_scaffold_keeps_figure_lines_round_trip():
    assert rebuild_l2_scaffold(L2_WITH_FIGURE).rstrip("\n") == SCAFFOLD_WITH_FIGURE.rstrip("\n")
    assert rebuild_l2_scaffold(SCAFFOLD_WITH_FIGURE).rstrip("\n") == SCAFFOLD_WITH_FIGURE.rstrip("\n")


def test_reset_section_prose_touches_only_that_section():
    out = reset_section_prose(L2_WITH_FIGURE, "1")
    assert "<!-- TODO:summarize 1 -->" in out
    assert "An old summary paragraph." not in out
    assert "Figure: Holding pattern entry sectors" in out
    assert out.endswith("## 2 Table Only\n\n| h2 |\n|----|\n| v2 |")   # §2 untouched
    assert "<!-- TODO:summarize 2 -->" not in out


def _redo_kb(tmp_path):
    kb = tmp_path / ".kb"
    (kb / "doc1").mkdir(parents=True)
    (kb / "index.yaml").write_text("docs:\n- id: doc1\n  title: Doc One\n", encoding="utf-8")
    (kb / "doc1" / "f1.md").write_text(L2_WITH_SUMMARIES, encoding="utf-8")
    (kb / "doc1" / "_manifest.yaml").write_text(
        "id: doc1\ntitle: Doc One\nsections:\n"
        "- {id: '1', title: Prose Section, file: f1, status: summarized, summary: old}\n"
        "- {id: '2', title: Table Only, file: f1, status: reviewed, summary: old2,\n"
        "   reviewed: {by: sme, at: '2026-09-01T00:00:00Z', l2_sha256: abc}}\n",
        encoding="utf-8",
    )
    return kb


def test_plan_redo_skips_reviewed_by_default(tmp_path):
    plan = plan_redo(_redo_kb(tmp_path), "doc1")
    assert [i.section_id for i in plan.items] == ["1"]
    assert [i.section_id for i in plan.skipped_reviewed] == ["2"]
    assert plan.reviewed_items == []


def test_plan_redo_include_reviewed_lists_the_record(tmp_path):
    plan = plan_redo(_redo_kb(tmp_path), "doc1", include_reviewed=True)
    assert [i.section_id for i in plan.items] == ["1", "2"]
    assert plan.reviewed_items[0].reviewed.by == "sme"


def test_plan_redo_section_filter_and_unknown_ids(tmp_path):
    kb = _redo_kb(tmp_path)
    plan = plan_redo(kb, "doc1", section_ids=["1"])
    assert [i.section_id for i in plan.items] == ["1"]
    with pytest.raises(ValueError, match="9"):
        plan_redo(kb, "doc1", section_ids=["9"])
    with pytest.raises(ValueError, match="nope"):
        plan_redo(kb, "nope")


def test_plan_redo_writes_nothing(tmp_path):
    kb = _redo_kb(tmp_path)
    before = (kb / "doc1" / "_manifest.yaml").read_text(encoding="utf-8")
    plan_redo(kb, "doc1", include_reviewed=True)
    assert (kb / "doc1" / "_manifest.yaml").read_text(encoding="utf-8") == before


def test_redo_reset_applies_the_plan_only(tmp_path):
    kb = _redo_kb(tmp_path)
    report = redo_reset(kb, plan_redo(kb, "doc1"))
    assert report.reset == ["doc1/1"] and report.reviewed_reset == 0
    m = models.load_yaml_model(kb / "doc1" / "_manifest.yaml", models.Manifest)
    assert m.sections[0].status == "pending" and m.sections[0].summary == ""
    assert m.sections[0].provenance is None and m.sections[0].l3_sha256 is None
    assert m.sections[1].status == "reviewed" and m.sections[1].reviewed.by == "sme"
    l2 = (kb / "doc1" / "f1.md").read_text(encoding="utf-8")
    assert "<!-- TODO:summarize 1 -->" in l2 and "<!-- TODO:summarize 2 -->" not in l2


def test_redo_reset_include_reviewed_clears_the_record(tmp_path):
    kb = _redo_kb(tmp_path)
    report = redo_reset(kb, plan_redo(kb, "doc1", include_reviewed=True))
    assert sorted(report.reset) == ["doc1/1", "doc1/2"] and report.reviewed_reset == 1
    m = models.load_yaml_model(kb / "doc1" / "_manifest.yaml", models.Manifest)
    assert all(s.status == "pending" and s.reviewed is None for s in m.sections)


L2_DUP_ID = (
    "## 1 First\n\nFirst old summary.\n\n"
    "## 1 Second\n\nSecond old summary.\n"
)


def test_reset_section_prose_occurrence_targets_second_heading():
    out = reset_section_prose(L2_DUP_ID, "1", occurrence=1)
    assert "First old summary." in out  # first occurrence untouched
    assert "Second old summary." not in out
    assert out.count("<!-- TODO:summarize 1 -->") == 1


def _dup_id_kb(tmp_path):
    kb = tmp_path / ".kb"
    (kb / "doc1").mkdir(parents=True)
    (kb / "index.yaml").write_text("docs:\n- id: doc1\n  title: Doc One\n", encoding="utf-8")
    (kb / "doc1" / "f1.md").write_text(L2_DUP_ID, encoding="utf-8")
    (kb / "doc1" / "_manifest.yaml").write_text(
        "id: doc1\ntitle: Doc One\nsections:\n"
        "- {id: '1', title: First, file: f1, status: summarized, summary: old-first}\n"
        "- {id: '1', title: Second, file: f1, status: summarized, summary: old-second}\n",
        encoding="utf-8",
    )
    return kb


def test_redo_reset_targets_the_planned_row_not_the_first_matching_id(tmp_path):
    kb = _dup_id_kb(tmp_path)
    plan = RedoPlan(items=[RedoItem("doc1", 1, "1", "summarized", None)])
    report = redo_reset(kb, plan)
    assert report.reset == ["doc1/1"] and report.failed == []
    m = models.load_yaml_model(kb / "doc1" / "_manifest.yaml", models.Manifest)
    assert m.sections[0].status == "summarized" and m.sections[0].summary == "old-first"
    assert m.sections[1].status == "pending" and m.sections[1].summary == ""
    l2 = (kb / "doc1" / "f1.md").read_text(encoding="utf-8")
    assert "First old summary." in l2
    assert "Second old summary." not in l2


def test_redo_reset_records_failure_for_stale_row_without_aborting(tmp_path):
    kb = _redo_kb(tmp_path)  # row 0 id='1', row 1 id='2' (see _redo_kb above)
    stale_plan = RedoPlan(items=[RedoItem("doc1", 0, "9", "summarized", None)])
    report = redo_reset(kb, stale_plan)
    assert report.reset == [] and report.reviewed_reset == 0
    assert report.failed == ["doc1/9: heading not found in f1 (occurrence 0)"]
    m = models.load_yaml_model(kb / "doc1" / "_manifest.yaml", models.Manifest)
    assert m.sections[0].status == "summarized" and m.sections[0].summary == "old"


def test_redo_reset_records_failure_for_missing_heading_without_aborting(tmp_path):
    kb = _dup_id_kb(tmp_path)
    # Row 1 is the second occurrence of id '1', but the L2 file only has
    # ONE '## 1' heading in this scenario — simulate drift by pointing at
    # a row whose occurrence the L2 file can't satisfy.
    (kb / "doc1" / "f1.md").write_text(
        "## 1 First\n\nFirst old summary.\n", encoding="utf-8"
    )
    plan = RedoPlan(items=[RedoItem("doc1", 1, "1", "summarized", None)])
    report = redo_reset(kb, plan)
    assert report.reset == []
    assert report.failed == ["doc1/1: heading not found in f1 (occurrence 1)"]
    m = models.load_yaml_model(kb / "doc1" / "_manifest.yaml", models.Manifest)
    assert m.sections[1].status == "summarized" and m.sections[1].summary == "old-second"


def test_redo_reset_records_failure_for_row_past_end_of_manifest(tmp_path):
    """B3: a stale plan row whose `row` index no longer exists at all in the
    manifest (not merely a different id at a valid row) must go to
    `report.failed`, not raise IndexError."""
    kb = _redo_kb(tmp_path)  # doc1 has exactly 2 sections (rows 0, 1)
    plan = RedoPlan(items=[RedoItem("doc1", 5, "9", "summarized", None)])
    report = redo_reset(kb, plan)
    assert report.reset == [] and report.reviewed_reset == 0
    assert report.failed == ["doc1/9: manifest row 5 no longer exists"]
    m = models.load_yaml_model(kb / "doc1" / "_manifest.yaml", models.Manifest)
    assert m.sections[0].status == "summarized" and m.sections[0].summary == "old"


def test_redo_reset_skips_l2_write_when_nothing_changed_for_the_doc(tmp_path, monkeypatch):
    """B3: L2 is written only `if changed`. Row 1 targets a second '## 1'
    occurrence that the (single-heading) L2 file doesn't have, so the row
    fails inside reset_section_prose — but only AFTER the file was already
    read into l2_cache, so the pre-fix code still (harmlessly, but
    needlessly) rewrites the file even though nothing actually changed."""
    kb = _dup_id_kb(tmp_path)
    (kb / "doc1" / "f1.md").write_text(
        "## 1 First\n\nFirst old summary.\n", encoding="utf-8"
    )
    plan = RedoPlan(items=[RedoItem("doc1", 1, "1", "summarized", None)])
    write_calls = []
    original_write_text = Path.write_text

    def spy_write_text(self, *args, **kwargs):
        write_calls.append(self)
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", spy_write_text)
    report = redo_reset(kb, plan)
    assert report.failed  # sanity: the row really did fail
    assert write_calls == []


def test_redo_reset_continues_past_a_failing_row_in_the_same_plan(tmp_path):
    kb = _dup_id_kb(tmp_path)
    (kb / "doc1" / "f1.md").write_text(
        "## 1 First\n\nFirst old summary.\n", encoding="utf-8"
    )
    plan = RedoPlan(
        items=[
            RedoItem("doc1", 0, "1", "summarized", None),  # occurrence 0: present
            RedoItem("doc1", 1, "1", "summarized", None),  # occurrence 1: missing
        ]
    )
    report = redo_reset(kb, plan)
    assert report.reset == ["doc1/1"]
    assert report.failed == ["doc1/1: heading not found in f1 (occurrence 1)"]
    m = models.load_yaml_model(kb / "doc1" / "_manifest.yaml", models.Manifest)
    assert m.sections[0].status == "pending"
    assert m.sections[1].status == "summarized" and m.sections[1].summary == "old-second"


def test_retry_pauses_before_second_attempt(monkeypatch):
    monkeypatch.setattr(summarize, "RETRY_PAUSE_SECONDS", 1.0)
    slept: list[float] = []
    monkeypatch.setattr(summarize.time, "sleep", lambda s: slept.append(s))

    class Boom:
        name = "boom"

        def __init__(self):
            self.n = 0

        def run(self, prompt):
            self.n += 1
            if self.n == 1:
                raise RunnerError("529 overloaded")
            return _reply("fine")

    result = _summarize_one(Boom(), _prose_section("p" * 2000))
    assert result["l2_summary"] == "fine"
    assert len(slept) == 1 and 1.0 <= slept[0] <= 1.5


def test_length_guard_retry_does_not_pause(monkeypatch):
    monkeypatch.setattr(summarize, "RETRY_PAUSE_SECONDS", 1.0)
    slept: list[float] = []
    monkeypatch.setattr(summarize.time, "sleep", lambda s: slept.append(s))
    runner = _ScriptedRunner([_reply("x" * 800), _reply("y" * 100)])
    _summarize_one(runner, _prose_section("p" * 2000))
    assert slept == []


def test_duplicate_ids_each_get_their_own_summary(tmp_path):
    kb = tmp_path / ".kb"
    (kb / "d").mkdir(parents=True)
    (kb / "index.yaml").write_text("docs:\n- id: d\n  title: D\n  summary: s\n", encoding="utf-8")
    long_a = "AAAA " * 60
    long_b = "BBBB " * 60
    (kb / "d" / "f.raw.md").write_text(
        f"## 1.1 Part A\n\n{long_a}\n\n## 1.1 Part B\n\n{long_b}\n", encoding="utf-8")
    (kb / "d" / "f.md").write_text(
        "## 1.1 Part A\n\n<!-- TODO:summarize 1.1 -->\n\n## 1.1 Part B\n\n<!-- TODO:summarize 1.1 -->\n",
        encoding="utf-8")
    (kb / "d" / "_manifest.yaml").write_text(
        "id: d\ntitle: D\nsections:\n"
        "- {id: '1.1', title: Part A, file: f, status: pending}\n"
        "- {id: '1.1', title: Part B, file: f, status: pending}\n", encoding="utf-8")

    class Echo:
        name = "echo"

        def run(self, prompt):
            if "one-line summaries" in prompt:
                return _json.dumps({"summary": "doc"})
            tag = "A" if "AAAA" in prompt else "B"
            return _json.dumps({"l2_summary": f"SUM-{tag}", "l1_summary": f"L1-{tag}"})

    report = summarize.summarize_kb(kb, Echo(), max_workers=2)
    assert report.ok
    l2 = (kb / "d" / "f.md").read_text(encoding="utf-8")
    assert l2.index("SUM-A") < l2.index("SUM-B")
    m = models.load_yaml_model(kb / "d" / "_manifest.yaml", models.Manifest)
    assert [s.summary for s in m.sections] == ["L1-A", "L1-B"]


def test_apply_results_records_provenance_and_l3_hash(tmp_path):
    kb = make_kb(tmp_path, {}, short=True)   # ~30-char bodies → brief → no LLM call
    fake = FakeRunner()
    fake.model, fake.effort = "sonnet-5", "high"
    summarize.summarize_kb(kb, fake, max_workers=1)
    m = models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest)
    for sec in m.sections:
        assert len(sec.l3_sha256) == 64
        assert sec.provenance is not None
        assert sec.provenance.prompt_sha == summarize.PROMPT_SHA
        assert sec.provenance.at.endswith("Z")
    # make_kb's sections are brief (< 200 chars of prose) → no LLM call → runner "none"
    assert {s.provenance.runner for s in m.sections} == {"none"}
    assert all(s.provenance.model == "" for s in m.sections)


def test_llm_section_provenance_names_the_runner(tmp_path):
    kb = make_kb(tmp_path, {})               # long bodies → llm kind
    fake = FakeRunner()
    fake.model, fake.effort = "sonnet-5", "high"
    summarize.summarize_kb(kb, fake, max_workers=1)
    m = models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest)
    assert m.sections[0].provenance.runner == "fake"
    assert m.sections[0].provenance.model == "sonnet-5"


def test_duplicate_ids_partial_failure_keeps_correct_marker_and_row_status(tmp_path):
    """Row 0 (Part A) fails at the runner; row 1 (Part B) succeeds. The write
    side must target the SECOND marker occurrence for row 1, leaving row 0's
    marker untouched — a first-match writer would desync the manifest by
    writing row 1's summary under row 0's heading."""
    kb = tmp_path / ".kb"
    (kb / "d").mkdir(parents=True)
    (kb / "index.yaml").write_text("docs:\n- id: d\n  title: D\n", encoding="utf-8")
    long_a = "AAAA " * 60
    long_b = "BBBB " * 60
    (kb / "d" / "f.raw.md").write_text(
        f"## 1.1 Part A\n\n{long_a}\n\n## 1.1 Part B\n\n{long_b}\n", encoding="utf-8")
    (kb / "d" / "f.md").write_text(
        "## 1.1 Part A\n\n<!-- TODO:summarize 1.1 -->\n\n## 1.1 Part B\n\n<!-- TODO:summarize 1.1 -->\n",
        encoding="utf-8")
    (kb / "d" / "_manifest.yaml").write_text(
        "id: d\ntitle: D\nsections:\n"
        "- {id: '1.1', title: Part A, file: f, status: pending}\n"
        "- {id: '1.1', title: Part B, file: f, status: pending}\n", encoding="utf-8")

    class FlakyEcho:
        name = "flaky"

        def run(self, prompt):
            if "AAAA" in prompt:
                raise RunnerError("boom")
            return _json.dumps({"l2_summary": "SUM-B", "l1_summary": "L1-B"})

    report = summarize.summarize_kb(kb, FlakyEcho(), max_workers=1)
    assert report.failed == ["d/1.1"]
    assert report.summarized == ["d/1.1"]
    l2 = (kb / "d" / "f.md").read_text(encoding="utf-8")
    assert "<!-- TODO:summarize 1.1 -->" in l2   # row 0's marker survives
    assert "SUM-B" in l2
    assert l2.index("<!-- TODO:summarize 1.1 -->") < l2.index("SUM-B")
    m = models.load_yaml_model(kb / "d" / "_manifest.yaml", models.Manifest)
    assert m.sections[0].status == "pending"
    assert m.sections[1].status == "summarized"


def _kb_with_missing_heading(tmp_path):
    kb = tmp_path / ".kb"
    (kb / "d").mkdir(parents=True)
    (kb / "index.yaml").write_text("docs:\n- id: d\n  title: D\n", encoding="utf-8")
    (kb / "d" / "f.raw.md").write_text(
        "## X Only One\n\n" + "Some prose text here that is fairly long. " * 6 + "\n",
        encoding="utf-8")
    (kb / "d" / "f.md").write_text(
        "## X Only One\n\n<!-- TODO:summarize X -->\n\n"
        "## X Only One\n\n<!-- TODO:summarize X -->\n",
        encoding="utf-8")
    (kb / "d" / "_manifest.yaml").write_text(
        "id: d\ntitle: D\nsections:\n"
        "- {id: 'X', title: Only One, file: f, status: pending}\n"
        "- {id: 'X', title: Only One, file: f, status: pending}\n", encoding="utf-8")
    return kb


def test_collect_pending_skips_missing_heading_and_reports_via_callback(tmp_path):
    kb = _kb_with_missing_heading(tmp_path)
    pending = summarize.collect_pending(kb)
    assert [p.row for p in pending] == [0]  # row 1's heading doesn't exist in the raw file

    messages: list[str] = []
    pending2 = summarize.collect_pending(kb, on_missing=messages.append)
    assert [p.row for p in pending2] == [0]
    assert messages == ["d/X: heading not found in f (occurrence 1)"]


def test_missing_heading_fails_that_row_without_fabricating_table_only(tmp_path):
    kb = _kb_with_missing_heading(tmp_path)
    report = summarize.summarize_kb(kb, FakeRunner(), max_workers=1)
    assert "d/X: heading not found in f (occurrence 1)" in report.failed
    m = models.load_yaml_model(kb / "d" / "_manifest.yaml", models.Manifest)
    assert m.sections[0].status == "summarized"
    assert m.sections[1].status == "pending"
    assert m.sections[1].l3_sha256 in (None, "")
    l2 = (kb / "d" / "f.md").read_text(encoding="utf-8")
    assert l2.count("<!-- TODO:summarize X -->") == 1  # row 1's marker untouched


def test_replace_marker_negative_occurrence_raises():
    with pytest.raises(ValueError):
        summarize.replace_marker("<!-- TODO:summarize 1.1 -->\n", "1.1", "s", occurrence=-1)


def test_duplicate_id_row_already_summarized_leaves_marker_index_correct_for_pending_row(
    tmp_path,
):
    """Row 0 (Part A) was already summarized in a PREVIOUS run — its marker
    is gone from the L2 file, only row 1 (Part B)'s marker remains. The
    marker occurrence for row 1 must be derived from how many *pending*
    same-id rows precede it (0, since row 0 no longer holds a marker), not
    from its heading index (1) — heading_occurrences counts every row
    regardless of status, which would ask replace_marker for a second
    marker that no longer exists."""
    kb = tmp_path / ".kb"
    (kb / "d").mkdir(parents=True)
    (kb / "index.yaml").write_text("docs:\n- id: d\n  title: D\n", encoding="utf-8")
    long_a = "AAAA " * 60
    long_b = "BBBB " * 60
    (kb / "d" / "f.raw.md").write_text(
        f"## 1.1 Part A\n\n{long_a}\n\n## 1.1 Part B\n\n{long_b}\n", encoding="utf-8")
    (kb / "d" / "f.md").write_text(
        "## 1.1 Part A\n\nOld summary A.\n\n## 1.1 Part B\n\n<!-- TODO:summarize 1.1 -->\n",
        encoding="utf-8")
    (kb / "d" / "_manifest.yaml").write_text(
        "id: d\ntitle: D\nsections:\n"
        "- {id: '1.1', title: Part A, file: f, status: summarized, summary: Old summary A.}\n"
        "- {id: '1.1', title: Part B, file: f, status: pending}\n", encoding="utf-8")

    class Echo:
        name = "echo"

        def run(self, prompt):
            if "one-line summaries" in prompt:  # doc-summary call
                return _json.dumps({"summary": "doc"})
            assert "BBBB" in prompt  # row 0 is not pending — must not be re-summarized
            return _json.dumps({"l2_summary": "SUM-B", "l1_summary": "L1-B"})

    report = summarize.summarize_kb(kb, Echo(), max_workers=1)
    assert report.ok and report.failed == []
    assert report.summarized == ["d/1.1"]
    l2 = (kb / "d" / "f.md").read_text(encoding="utf-8")
    assert "Old summary A." in l2
    assert "SUM-B" in l2
    assert "<!-- TODO:summarize 1.1 -->" not in l2
    m = models.load_yaml_model(kb / "d" / "_manifest.yaml", models.Manifest)
    assert m.sections[0].status == "summarized" and m.sections[0].summary == "Old summary A."
    assert m.sections[1].status == "summarized" and m.sections[1].summary == "L1-B"


def test_duplicate_id_rerun_after_partial_failure_resolves_marker_by_remaining_pending_order(
    tmp_path,
):
    """Row 0 succeeds and consumes its marker in the first run; row 1 raises
    and stays pending. A second run, with a working runner, must still land
    row 1's summary under Part B's marker (the only one left), not fail with
    a stale marker index computed from the pristine heading order."""
    kb = tmp_path / ".kb"
    (kb / "d").mkdir(parents=True)
    (kb / "index.yaml").write_text("docs:\n- id: d\n  title: D\n", encoding="utf-8")
    long_a = "AAAA " * 60
    long_b = "BBBB " * 60
    (kb / "d" / "f.raw.md").write_text(
        f"## 1.1 Part A\n\n{long_a}\n\n## 1.1 Part B\n\n{long_b}\n", encoding="utf-8")
    (kb / "d" / "f.md").write_text(
        "## 1.1 Part A\n\n<!-- TODO:summarize 1.1 -->\n\n## 1.1 Part B\n\n<!-- TODO:summarize 1.1 -->\n",
        encoding="utf-8")
    (kb / "d" / "_manifest.yaml").write_text(
        "id: d\ntitle: D\nsections:\n"
        "- {id: '1.1', title: Part A, file: f, status: pending}\n"
        "- {id: '1.1', title: Part B, file: f, status: pending}\n", encoding="utf-8")

    class FlakyEcho:
        name = "flaky"

        def run(self, prompt):
            if "BBBB" in prompt:
                raise RunnerError("boom")
            return _json.dumps({"l2_summary": "SUM-A", "l1_summary": "L1-A"})

    report1 = summarize.summarize_kb(kb, FlakyEcho(), max_workers=1)
    assert report1.summarized == ["d/1.1"] and report1.failed == ["d/1.1"]
    m1 = models.load_yaml_model(kb / "d" / "_manifest.yaml", models.Manifest)
    assert m1.sections[0].status == "summarized"
    assert m1.sections[1].status == "pending"

    class WorkingEcho:
        name = "working"

        def run(self, prompt):
            if "one-line summaries" in prompt:  # doc-summary call
                return _json.dumps({"summary": "doc"})
            assert "BBBB" in prompt
            return _json.dumps({"l2_summary": "SUM-B", "l1_summary": "L1-B"})

    report2 = summarize.summarize_kb(kb, WorkingEcho(), max_workers=1)
    assert report2.ok and report2.failed == []
    assert report2.summarized == ["d/1.1"]
    l2 = (kb / "d" / "f.md").read_text(encoding="utf-8")
    assert "SUM-A" in l2 and "SUM-B" in l2
    assert "<!-- TODO:summarize 1.1 -->" not in l2
    m2 = models.load_yaml_model(kb / "d" / "_manifest.yaml", models.Manifest)
    assert m2.sections[0].status == "summarized" and m2.sections[0].summary == "L1-A"
    assert m2.sections[1].status == "summarized" and m2.sections[1].summary == "L1-B"
