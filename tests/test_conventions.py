"""Conventions pack — detection + scaffold step (spec
docs/superpowers/specs/2026-08-24-d-conventions-pack-design.md)."""
from pathlib import Path

import pytest

from center_kb.conventions import (
    CLAUDE_MARKER,
    LANG_GLOBS,
    detect_langs,
    ensure_claude_block,
    scaffold_conventions,
)
from center_kb.initcmd import InitReport


def _touch(root: Path, rel: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x\n", encoding="utf-8")


@pytest.mark.parametrize(
    ("rel", "lang"),
    [
        ("pyproject.toml", "python"),
        ("setup.cfg", "python"),
        ("requirements-dev.txt", "python"),
        ("package.json", "ts"),
        ("pom.xml", "java"),
        ("build.gradle", "java"),
        ("build.gradle.kts", "java"),
        ("go.mod", "go"),
        ("composer.json", "php"),
        ("App.csproj", "dotnet"),
    ],
)
def test_detects_each_manifest_at_root(tmp_path: Path, rel: str, lang: str):
    _touch(tmp_path, rel)
    assert detect_langs(tmp_path) == [lang]


def test_detects_manifests_up_to_two_levels_below_root(tmp_path: Path):
    _touch(tmp_path, "web/package.json")        # depth 1
    _touch(tmp_path, "services/api/go.mod")     # depth 2
    assert detect_langs(tmp_path) == ["go", "ts"]


def test_ignores_manifests_below_depth_two(tmp_path: Path):
    _touch(tmp_path, "a/b/c/pyproject.toml")    # depth 3
    assert detect_langs(tmp_path) == []


def test_multi_language_repo_is_sorted_and_deduped(tmp_path: Path):
    _touch(tmp_path, "pyproject.toml")
    _touch(tmp_path, "requirements.txt")        # second python manifest: no dupe
    _touch(tmp_path, "web/package.json")
    assert detect_langs(tmp_path) == ["python", "ts"]


def test_skips_vendored_and_internal_directories(tmp_path: Path):
    _touch(tmp_path, "node_modules/left-pad/package.json")
    _touch(tmp_path, "vendor/acme/composer.json")
    _touch(tmp_path, ".kb/demo/go.mod")
    _touch(tmp_path, "docs/samples/pom.xml")
    _touch(tmp_path, ".git/pyproject.toml")
    assert detect_langs(tmp_path) == []


def test_empty_repo_detects_nothing(tmp_path: Path):
    assert detect_langs(tmp_path) == []


def test_directory_named_like_a_manifest_does_not_count(tmp_path: Path):
    (tmp_path / "go.mod").mkdir()
    assert detect_langs(tmp_path) == []


def test_skips_glob_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _touch(tmp_path, "pyproject.toml")

    def _raise_oserror(self: Path, pattern: str) -> list[Path]:
        raise OSError("glob denied")

    monkeypatch.setattr(Path, "glob", _raise_oserror)
    assert detect_langs(tmp_path) == []


def test_skips_is_file_permission_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _touch(tmp_path, "pyproject.toml")

    def _raise_permission_error(self: Path) -> bool:
        raise PermissionError("is_file denied")

    monkeypatch.setattr(Path, "is_file", _raise_permission_error)
    assert detect_langs(tmp_path) == []


def _scaffold(tmp_path: Path) -> InitReport:
    report = InitReport()
    scaffold_conventions(tmp_path, report)
    return report


def test_scaffold_creates_base_local_and_pointers_for_detected_lang(tmp_path: Path):
    _touch(tmp_path, "pyproject.toml")
    report = _scaffold(tmp_path)
    base = tmp_path / "docs" / "conventions" / "python.md"
    local = tmp_path / "docs" / "conventions" / "python.local.md"
    mdc = tmp_path / ".cursor" / "rules" / "coding-python.mdc"
    instr = tmp_path / ".github" / "instructions" / "coding-python.instructions.md"
    for f in (base, local, mdc, instr):
        assert f.is_file(), f
    assert "# Python coding conventions" in base.read_text(encoding="utf-8")
    assert "OVERRIDE" in local.read_text(encoding="utf-8")
    mdc_text = mdc.read_text(encoding="utf-8")
    assert "globs: **/*.py" in mdc_text            # {globs} substituted
    assert "docs/conventions/python.md" in mdc_text  # {lang} substituted
    assert "{lang}" not in mdc_text and "{globs}" not in mdc_text
    instr_text = instr.read_text(encoding="utf-8")
    assert 'applyTo: "**/*.py"' in instr_text
    assert "{lang}" not in instr_text and "{globs}" not in instr_text
    assert "docs/conventions/python.md" in report.created
    assert "docs/conventions/python.local.md" in report.created
    assert ".cursor/rules/coding-python.mdc" in report.created
    assert ".github/instructions/coding-python.instructions.md" in report.created
    # only the detected language
    assert not (tmp_path / "docs" / "conventions" / "ts.md").exists()


def test_scaffold_returns_detected_langs_and_covers_multi_lang(tmp_path: Path):
    _touch(tmp_path, "pyproject.toml")
    _touch(tmp_path, "web/package.json")
    report = InitReport()
    assert scaffold_conventions(tmp_path, report) == ["python", "ts"]
    assert (tmp_path / "docs" / "conventions" / "ts.md").is_file()
    assert (tmp_path / ".cursor" / "rules" / "coding-ts.mdc").is_file()


def test_scaffold_refreshes_stale_base_but_never_touches_local(tmp_path: Path):
    _touch(tmp_path, "pyproject.toml")
    _scaffold(tmp_path)
    base = tmp_path / "docs" / "conventions" / "python.md"
    local = tmp_path / "docs" / "conventions" / "python.local.md"
    base.write_text("stale\n", encoding="utf-8")
    local.write_text("my overrides\n", encoding="utf-8")
    report = _scaffold(tmp_path)
    assert "stale" not in base.read_text(encoding="utf-8")
    assert local.read_text(encoding="utf-8") == "my overrides\n"
    assert "docs/conventions/python.md" in report.updated
    assert (
        "docs/conventions/python.local.md (local overrides — never refreshed)"
        in report.skipped
    )


def test_scaffold_is_idempotent_when_current(tmp_path: Path):
    _touch(tmp_path, "pyproject.toml")
    _scaffold(tmp_path)
    report = _scaffold(tmp_path)
    assert report.created == []
    assert report.updated == []
    assert report.skipped == [
        "docs/conventions/python.local.md (local overrides — never refreshed)"
    ]


def test_scaffold_without_manifests_notes_and_writes_nothing(tmp_path: Path):
    report = InitReport()
    assert scaffold_conventions(tmp_path, report) == []
    assert not (tmp_path / "docs" / "conventions").exists()
    assert any("no language manifests detected" in n for n in report.notes)


def test_lang_globs_covers_every_manifest_lang():
    from center_kb.conventions import LANG_MANIFESTS

    assert sorted(LANG_GLOBS) == sorted(lang for lang, _ in LANG_MANIFESTS)


@pytest.mark.parametrize(
    ("rel", "lang"),
    [
        ("pyproject.toml", "python"),
        ("package.json", "ts"),
        ("pom.xml", "java"),
        ("go.mod", "go"),
        ("composer.json", "php"),
        ("App.csproj", "dotnet"),
    ],
)
def test_scaffold_produces_four_files_for_every_manifest_lang(
    tmp_path: Path, rel: str, lang: str
):
    # Every id in LANG_MANIFESTS must have a matching conventions-<lang>.md
    # template resource. python/ts are already covered elsewhere in detail;
    # this pins the other four ids too, so a missing template resource
    # raises FileNotFoundError here in the suite instead of at runtime.
    _touch(tmp_path, rel)
    _scaffold(tmp_path)
    base = tmp_path / "docs" / "conventions" / f"{lang}.md"
    local = tmp_path / "docs" / "conventions" / f"{lang}.local.md"
    mdc = tmp_path / ".cursor" / "rules" / f"coding-{lang}.mdc"
    instr = tmp_path / ".github" / "instructions" / f"coding-{lang}.instructions.md"
    for f in (base, local, mdc, instr):
        assert f.is_file(), f


def test_claude_block_created_when_file_missing(tmp_path: Path):
    report = InitReport()
    ensure_claude_block(tmp_path, report)
    text = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert text.startswith(CLAUDE_MARKER)
    assert "docs/conventions/<lang>.md" in text
    assert "docs/conventions/<lang>.local.md" in text
    # raw-text needle kept to one source line — the phrase wraps
    assert "repo wins locally" in text
    assert "CLAUDE.md" in report.created


def test_claude_block_appended_preserving_user_bytes(tmp_path: Path):
    user = "# My project notes\n\nno trailing newline here"
    (tmp_path / "CLAUDE.md").write_text(user, encoding="utf-8")
    report = InitReport()
    ensure_claude_block(tmp_path, report)
    text = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    # This round-trips through universal-newline translation on both the
    # write above and the read here, so it only proves the user's text is
    # an unmodified prefix once decoded — it cannot see whether the
    # on-disk line-ending bytes changed. See
    # test_claude_block_appended_preserves_existing_crlf_bytes below for
    # the actual byte-exactness assertion.
    assert text.startswith(user)
    assert CLAUDE_MARKER in text
    assert "CLAUDE.md (conventions block appended)" in report.updated


def test_claude_block_appended_preserves_existing_crlf_bytes(tmp_path: Path):
    # write_bytes bypasses text-mode newline translation entirely, so the
    # on-disk bytes are exactly this CRLF content — a stand-in for a
    # CLAUDE.md checked out with Windows line endings, which is entirely
    # plausible for `kb init` scaffolding into an arbitrary user repo.
    dest = tmp_path / "CLAUDE.md"
    user_bytes = b"# My project notes\r\n\r\nwindows line endings here\r\n"
    dest.write_bytes(user_bytes)
    report = InitReport()
    ensure_claude_block(tmp_path, report)
    # Byte-exact check, per the plan's "append preserving existing bytes"
    # rule: every pre-existing CRLF byte must survive untouched. Against
    # the pre-fix implementation (read via read_text's universal-newline
    # translation, then a whole-file rewrite with newline="\n"), the CRLF
    # bytes collapse to LF and this assertion fails.
    on_disk = dest.read_bytes()
    assert on_disk.startswith(user_bytes)
    assert CLAUDE_MARKER.encode("utf-8") in on_disk
    assert "CLAUDE.md (conventions block appended)" in report.updated


def test_claude_block_untouched_when_marker_present(tmp_path: Path):
    report = InitReport()
    ensure_claude_block(tmp_path, report)
    first = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    report2 = InitReport()
    ensure_claude_block(tmp_path, report2)
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == first
    assert report2.created == [] and report2.updated == []
    assert first.count(CLAUDE_MARKER) == 1
