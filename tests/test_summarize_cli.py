from pathlib import Path

from typer.testing import CliRunner

from strata_kb import models
from strata_kb.cli import app
from tests.test_summarize import FakeRunner, make_kb

runner = CliRunner()


def _patch_detect(monkeypatch, fake):
    import strata_kb.llm as llm_mod

    # cli._run_summarize looks detect_runner up on the module at call time,
    # so patching the module attribute is enough.
    monkeypatch.setattr(llm_mod, "detect_runner", lambda choice, cfg: fake)


def test_summarize_success_exit_0(tmp_path: Path, monkeypatch):
    kb = make_kb(tmp_path, {})
    _patch_detect(monkeypatch, FakeRunner())
    result = runner.invoke(app, ["summarize", "--kb-dir", str(kb)])
    assert result.exit_code == 0, result.output
    assert "2 summarized" in result.output
    manifest = models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest)
    assert all(s.status == "summarized" for s in manifest.sections)


def test_summarize_failed_section_exit_1(tmp_path: Path, monkeypatch):
    kb = make_kb(tmp_path, {})
    _patch_detect(monkeypatch, FakeRunner(fail_ids={"1.2"}))
    result = runner.invoke(app, ["summarize", "--kb-dir", str(kb)])
    assert result.exit_code == 1
    assert "1 failed" in result.output
    assert "kb summarize" in result.output  # re-run hint


def test_summarize_no_runner_exit_1(tmp_path: Path, monkeypatch):
    kb = make_kb(tmp_path, {})
    _patch_detect(monkeypatch, None)
    result = runner.invoke(app, ["summarize", "--kb-dir", str(kb)])
    assert result.exit_code == 1
    assert "claude" in result.output and "copilot" in result.output


def test_summarize_runner_none_exit_1(tmp_path: Path):
    kb = make_kb(tmp_path, {})
    result = runner.invoke(app, ["summarize", "--kb-dir", str(kb), "--llm", "none"])
    assert result.exit_code == 1
    assert "none" in result.output


def test_summarize_bad_llm_value_exit_1(tmp_path: Path):
    kb = make_kb(tmp_path, {})
    result = runner.invoke(app, ["summarize", "--kb-dir", str(kb), "--llm", "gemini"])
    assert result.exit_code == 1


def test_summarize_bad_effort_literal_is_a_clean_error_not_a_traceback(tmp_path: Path):
    """B4: a pydantic.ValidationError (subclass of ValueError) from a typo'd
    `llm.effort` in index.yaml must surface as `[error] <msg>` + exit 1, not
    an unhandled traceback."""
    kb = make_kb(tmp_path, {})
    index_path = kb / "index.yaml"
    index_path.write_text(
        index_path.read_text(encoding="utf-8").replace("effort: high", "effort: hgih"),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["summarize", "--kb-dir", str(kb)])
    assert result.exit_code == 1
    assert not isinstance(result.exception, ValueError), result.exception
    assert "[error]" in result.output


def test_summarize_nothing_pending_exit_0(tmp_path: Path, monkeypatch):
    kb = make_kb(tmp_path, {"1.1": "summarized", "1.2": "reviewed"})
    _patch_detect(monkeypatch, FakeRunner())
    result = runner.invoke(app, ["summarize", "--kb-dir", str(kb)])
    assert result.exit_code == 0
    assert "0" in result.output


def _reviewed_kb(tmp_path):
    return make_kb(tmp_path, {"1.1": "summarized", "1.2": "reviewed"})


def test_redo_without_doc_or_all_is_refused(tmp_path, monkeypatch):
    kb = _reviewed_kb(tmp_path)
    _patch_detect(monkeypatch, FakeRunner())
    result = runner.invoke(app, ["summarize", "--redo", "--kb-dir", str(kb)])
    assert result.exit_code == 1 and "--all" in result.output
    m = models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest)
    assert [s.status for s in m.sections] == ["summarized", "reviewed"]


def test_redo_doc_skips_reviewed_and_says_so(tmp_path, monkeypatch):
    kb = _reviewed_kb(tmp_path)
    _patch_detect(monkeypatch, FakeRunner())
    result = runner.invoke(app, ["summarize", "d1", "--redo", "--kb-dir", str(kb)])
    assert result.exit_code == 0, result.output
    assert "redo: 1 section(s) in d1 will be reset (1 reviewed skipped)" in result.output
    m = models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest)
    assert [s.status for s in m.sections] == ["summarized", "reviewed"]


def test_redo_include_reviewed_needs_yes_on_non_tty(tmp_path, monkeypatch):
    kb = _reviewed_kb(tmp_path)
    _patch_detect(monkeypatch, FakeRunner())
    result = runner.invoke(app, ["summarize", "d1", "--redo", "--include-reviewed", "--kb-dir", str(kb)])
    assert result.exit_code == 1
    assert "d1/1.2 reviewed by" in result.output
    m = models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest)
    assert m.sections[1].status == "reviewed"


def test_redo_include_reviewed_with_yes_resets_and_resummarizes(tmp_path, monkeypatch):
    kb = _reviewed_kb(tmp_path)
    _patch_detect(monkeypatch, FakeRunner())
    result = runner.invoke(app, ["summarize", "d1", "--redo", "--include-reviewed", "--yes", "--kb-dir", str(kb)])
    assert result.exit_code == 0, result.output
    assert "2 summarized, 0 failed." in result.output
    m = models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest)
    assert all(s.status == "summarized" and s.reviewed is None for s in m.sections)


def test_redo_dry_run_writes_nothing(tmp_path, monkeypatch):
    kb = _reviewed_kb(tmp_path)
    _patch_detect(monkeypatch, FakeRunner())
    before_manifest = (kb / "d1" / "_manifest.yaml").read_text(encoding="utf-8")
    before_l2 = (kb / "d1" / "ch1.md").read_text(encoding="utf-8")
    result = runner.invoke(app, ["summarize", "d1", "--redo", "--dry-run", "--kb-dir", str(kb)])
    assert result.exit_code == 0 and "will be reset" in result.output
    assert (kb / "d1" / "_manifest.yaml").read_text(encoding="utf-8") == before_manifest
    assert (kb / "d1" / "ch1.md").read_text(encoding="utf-8") == before_l2


def test_redo_all_with_doc_id_is_refused(tmp_path, monkeypatch):
    kb = _reviewed_kb(tmp_path)
    _patch_detect(monkeypatch, FakeRunner())
    result = runner.invoke(app, ["summarize", "d1", "--redo", "--all", "--kb-dir", str(kb)])
    assert result.exit_code == 1


def test_redo_no_runner_does_not_reset(tmp_path, monkeypatch):
    kb = make_kb(tmp_path, {"1.1": "summarized", "1.2": "summarized"})
    _patch_detect(monkeypatch, None)
    result = runner.invoke(app, ["summarize", "d1", "--redo", "--kb-dir", str(kb)])
    assert result.exit_code == 1 and "redo:" not in result.output
    m = models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest)
    assert all(s.status == "summarized" for s in m.sections)


def _two_doc_kb(tmp_path):
    kb = tmp_path / ".kb"
    body = "Alpha body text §2.3 code P. " * 12
    for doc_id in ("d1", "d2"):
        doc = kb / doc_id
        doc.mkdir(parents=True)
        (doc / "ch1.raw.md").write_text(f"## 1.1 Alpha\n\n{body}\n", encoding="utf-8")
        (doc / "ch1.md").write_text(
            "## 1.1 Alpha\n\n<!-- TODO:summarize 1.1 -->\n", encoding="utf-8"
        )
        manifest = models.Manifest(
            id=doc_id, title=f"Doc {doc_id}",
            sections=[
                models.SectionEntry(
                    id="1.1", title="Alpha", file="ch1",
                    status="summarized", summary=f"kept-{doc_id}",
                ),
            ],
        )
        models.save_yaml_model(doc / "_manifest.yaml", manifest)
    index = models.KBIndex(docs=[
        models.IndexEntry(id="d1", title="Doc d1"),
        models.IndexEntry(id="d2", title="Doc d2"),
    ])
    models.save_yaml_model(kb / "index.yaml", index)
    return kb


def test_redo_all_resets_and_resummarizes_every_doc(tmp_path, monkeypatch):
    kb = _two_doc_kb(tmp_path)
    _patch_detect(monkeypatch, FakeRunner())
    result = runner.invoke(app, ["summarize", "--redo", "--all", "--yes", "--kb-dir", str(kb)])
    assert result.exit_code == 0, result.output
    assert "redo: 2 section(s) in the whole KB will be reset (0 reviewed skipped)" in result.output
    assert "2 summarized, 0 failed." in result.output
    for doc_id in ("d1", "d2"):
        m = models.load_yaml_model(kb / doc_id / "_manifest.yaml", models.Manifest)
        # kept-<doc_id> would still be there if this doc had NOT been reset+redone
        assert m.sections[0].status == "summarized" and m.sections[0].summary == "One line."


def _section_scope_kb(tmp_path):
    kb = tmp_path / ".kb"
    doc = kb / "d1"
    doc.mkdir(parents=True)
    alpha_body = "Alpha body text §2.3 code P. " * 12
    beta_body = "Beta body text. " * 20
    (doc / "ch1.raw.md").write_text(
        f"## 1.1 Alpha\n\n{alpha_body}\n\n## 1.2 Beta\n\n{beta_body}\n", encoding="utf-8"
    )
    (doc / "ch1.md").write_text(
        "## 1.1 Alpha\n\n<!-- TODO:summarize 1.1 -->\n\n"
        "## 1.2 Beta\n\n<!-- TODO:summarize 1.2 -->\n",
        encoding="utf-8",
    )
    manifest = models.Manifest(
        id="d1", title="Doc One",
        sections=[
            models.SectionEntry(id="1.1", title="Alpha", file="ch1",
                                 status="summarized", summary="kept-1.1"),
            models.SectionEntry(id="1.2", title="Beta", file="ch1",
                                 status="summarized", summary="kept-1.2"),
        ],
    )
    models.save_yaml_model(doc / "_manifest.yaml", manifest)
    models.save_yaml_model(
        kb / "index.yaml", models.KBIndex(docs=[models.IndexEntry(id="d1", title="Doc One")])
    )
    return kb


def test_redo_section_flag_resets_only_the_named_section(tmp_path, monkeypatch):
    kb = _section_scope_kb(tmp_path)
    _patch_detect(monkeypatch, FakeRunner())
    result = runner.invoke(app, ["summarize", "d1", "--redo", "--section", "1.2", "--kb-dir", str(kb)])
    assert result.exit_code == 0, result.output
    assert "redo: 1 section(s) in d1 will be reset (0 reviewed skipped)" in result.output
    m = models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest)
    assert m.sections[0].status == "summarized" and m.sections[0].summary == "kept-1.1"
    assert m.sections[1].status == "summarized" and m.sections[1].summary == "One line."


def test_redo_all_with_section_requires_doc_id(tmp_path, monkeypatch):
    kb = _reviewed_kb(tmp_path)
    _patch_detect(monkeypatch, FakeRunner())
    result = runner.invoke(
        app, ["summarize", "--redo", "--all", "--section", "1.1", "--kb-dir", str(kb)]
    )
    assert result.exit_code == 1 and "--section requires a DOC_ID" in result.output


def test_redo_section_without_doc_id_requires_doc_id(tmp_path, monkeypatch):
    kb = _reviewed_kb(tmp_path)
    _patch_detect(monkeypatch, FakeRunner())
    result = runner.invoke(app, ["summarize", "--redo", "--section", "1.1", "--kb-dir", str(kb)])
    assert result.exit_code == 1 and "--section requires a DOC_ID" in result.output


def test_redo_only_flag_without_redo_is_refused(tmp_path, monkeypatch):
    kb = _reviewed_kb(tmp_path)
    _patch_detect(monkeypatch, FakeRunner())
    result = runner.invoke(app, ["summarize", "d1", "--dry-run", "--kb-dir", str(kb)])
    assert result.exit_code == 1 and "--dry-run requires --redo" in result.output
    m = models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest)
    assert [s.status for s in m.sections] == ["summarized", "reviewed"]


def test_redo_prints_fail_lines_and_exits_1_without_aborting_other_rows(tmp_path, monkeypatch):
    kb = tmp_path / ".kb"
    doc = kb / "d1"
    doc.mkdir(parents=True)
    (doc / "ch1.md").write_text("## 1 Alpha\n\n<!-- TODO:summarize 1 -->\n", encoding="utf-8")
    manifest = models.Manifest(
        id="d1", title="Doc One",
        sections=[
            models.SectionEntry(id="1", title="Alpha", file="ch1",
                                 status="summarized", summary="kept-0"),
            models.SectionEntry(id="1", title="Alpha 2", file="ch1",
                                 status="summarized", summary="kept-1"),
        ],
    )
    models.save_yaml_model(doc / "_manifest.yaml", manifest)
    models.save_yaml_model(
        kb / "index.yaml", models.KBIndex(docs=[models.IndexEntry(id="d1", title="Doc One")])
    )
    _patch_detect(monkeypatch, FakeRunner())
    result = runner.invoke(app, ["summarize", "d1", "--redo", "--section", "1", "--kb-dir", str(kb)])
    assert result.exit_code == 1
    assert "[fail] d1/1: heading not found in ch1 (occurrence 1)" in result.output
    m = models.load_yaml_model(doc / "_manifest.yaml", models.Manifest)
    assert m.sections[0].status == "pending"  # row 0 reset fine
    assert m.sections[1].status == "summarized" and m.sections[1].summary == "kept-1"  # untouched


from strata_kb.summarize import build_section_prompt, collect_pending


def test_print_prompt_emits_the_engine_prompt_verbatim(tmp_path):
    kb = make_kb(tmp_path, {})
    result = runner.invoke(app, ["summarize", "d1", "--print-prompt", "--kb-dir", str(kb)])
    assert result.exit_code == 0, result.output
    expected = {s.section_id: build_section_prompt(s) for s in collect_pending(kb, "d1")}
    for sid, prompt in expected.items():
        assert f"=== d1/{sid} ===" in result.output
        assert prompt in result.output


def test_print_prompt_marks_brief_and_table_only(tmp_path):
    kb = make_kb(tmp_path, {})
    raw = kb / "d1" / "ch1.raw.md"
    raw.write_text("## 1.1 Alpha\n\nShort.\n\n## 1.2 Beta\n\n| h |\n|---|\n| v |\n", encoding="utf-8")
    result = runner.invoke(app, ["summarize", "d1", "--print-prompt", "--kb-dir", str(kb)])
    assert "=== d1/1.1 === [no LLM needed: brief" in result.output
    assert "=== d1/1.2 === [no LLM needed: table-only" in result.output


def test_print_prompt_section_filter_and_nothing_pending(tmp_path):
    kb = make_kb(tmp_path, {"1.2": "summarized"})
    result = runner.invoke(app, ["summarize", "d1", "--print-prompt", "--section", "1.1", "--kb-dir", str(kb)])
    assert result.exit_code == 0 and "=== d1/1.1 ===" in result.output and "d1/1.2" not in result.output
    done = make_kb(tmp_path / "b", {"1.1": "summarized", "1.2": "summarized"})
    result = runner.invoke(app, ["summarize", "d1", "--print-prompt", "--kb-dir", str(done)])
    assert result.exit_code == 0 and "nothing pending" in result.output


def test_print_prompt_requires_doc_id_and_known_section(tmp_path):
    kb = make_kb(tmp_path, {})
    assert runner.invoke(app, ["summarize", "--print-prompt", "--kb-dir", str(kb)]).exit_code == 1
    bad = runner.invoke(app, ["summarize", "d1", "--print-prompt", "--section", "9.9", "--kb-dir", str(kb)])
    assert bad.exit_code == 1 and "9.9" in bad.output


def test_print_prompt_still_refuses_redo_only_flags(tmp_path):
    kb = make_kb(tmp_path, {})
    result = runner.invoke(
        app, ["summarize", "d1", "--print-prompt", "--dry-run", "--kb-dir", str(kb)]
    )
    assert result.exit_code == 1 and "--dry-run requires --redo" in result.output


def test_print_prompt_cannot_combine_with_redo(tmp_path):
    kb = make_kb(tmp_path, {})
    result = runner.invoke(
        app, ["summarize", "d1", "--print-prompt", "--redo", "--kb-dir", str(kb)]
    )
    assert (
        result.exit_code == 1
        and "--print-prompt cannot be combined with --redo" in result.output
    )


def test_print_prompt_reports_skipped_missing_heading(tmp_path):
    kb = tmp_path / ".kb"
    doc = kb / "d1"
    doc.mkdir(parents=True)
    (doc / "ch1.raw.md").write_text("## 1.2 Beta\n\nBeta body text.\n", encoding="utf-8")
    manifest = models.Manifest(
        id="d1", title="Doc One",
        sections=[
            models.SectionEntry(id="1.1", title="Alpha", file="ch1", status="pending"),
            models.SectionEntry(id="1.2", title="Beta", file="ch1", status="pending"),
        ],
    )
    models.save_yaml_model(doc / "_manifest.yaml", manifest)
    models.save_yaml_model(
        kb / "index.yaml", models.KBIndex(docs=[models.IndexEntry(id="d1", title="Doc One")])
    )
    result = runner.invoke(app, ["summarize", "d1", "--print-prompt", "--kb-dir", str(kb)])
    assert result.exit_code == 0, result.output
    assert "[skip] d1/1.1: heading not found in ch1" in result.output


def test_print_prompt_never_calls_runner_or_writes(tmp_path, monkeypatch):
    kb = make_kb(tmp_path, {})
    fake = FakeRunner()
    _patch_detect(monkeypatch, fake)
    result = runner.invoke(app, ["summarize", "d1", "--print-prompt", "--kb-dir", str(kb)])
    assert result.exit_code == 0, result.output
    assert fake.calls == []
    manifest = models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest)
    assert all(s.status == "pending" for s in manifest.sections)


def test_print_prompt_blank_line_separates_blocks(tmp_path):
    kb = make_kb(tmp_path, {})
    result = runner.invoke(app, ["summarize", "d1", "--print-prompt", "--kb-dir", str(kb)])
    assert result.exit_code == 0, result.output
    assert "\n\n=== d1/1.2 ===" in result.output
