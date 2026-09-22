"""Conventions pack — language detection + scaffold step for `kb init` (kind dev).

Spec: docs/superpowers/specs/2026-08-24-d-conventions-pack-design.md.

Deliberately standalone: `codeingest.extractors.deps` parses manifest
*contents* (it needs dependency names); this module needs only manifest
*presence*, and must not pull codeingest machinery into the init path.
"""
from __future__ import annotations

from collections.abc import Iterable
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # runtime import would be circular: initcmd imports us
    from strata_kb.initcmd import InitReport

LANG_MANIFESTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("dotnet", ("*.csproj",)),
    ("go", ("go.mod",)),
    ("java", ("pom.xml", "build.gradle", "build.gradle.kts")),
    ("php", ("composer.json",)),
    ("python", ("pyproject.toml", "setup.cfg", "requirements*.txt")),
    ("ts", ("package.json",)),
    ("rust", ("Cargo.toml",)),
    ("swift", ("Package.swift",)),
    ("dart", ("pubspec.yaml",)),
    (
        "e2e-playwright",
        (
            "playwright.config.ts",
            "playwright.config.js",
            "playwright.config.mjs",
            "playwright.config.cts",
            "playwright.config.mts",
        ),
    ),
)

LANG_IDS: tuple[str, ...] = tuple(lang for lang, _ in LANG_MANIFESTS)

# Directories whose contents are someone else's code or generated output —
# a manifest inside them says nothing about what THIS repo is written in.
_SKIP_DIRS = frozenset({".git", ".kb", "docs", "node_modules", "vendor"})


def detect_langs(root: Path) -> list[str]:
    """Language ids whose manifest exists at root or up to three levels below.

    Root is depth 0 (`web/package.json` is depth 1) — the depth the
    codeingest node reader searches. Defensive: unreadable directories are
    skipped, never raised, so a permission error cannot fail `kb init`.
    """
    found: set[str] = set()
    for lang, patterns in LANG_MANIFESTS:
        for pattern in patterns:
            for prefix in ("", "*/", "*/*/", "*/*/*/"):
                try:
                    hits = list(root.glob(prefix + pattern))
                except OSError:
                    continue
                for hit in hits:
                    parents = hit.relative_to(root).parts[:-1]
                    if any(part in _SKIP_DIRS for part in parents):
                        continue
                    try:
                        is_file = hit.is_file()
                    except OSError:
                        continue
                    if is_file:
                        found.add(lang)
                        break
    return sorted(found)


# file-extension globs per language id, used in the pointer wrappers'
# frontmatter (`globs:` for Cursor, `applyTo:` for Copilot).
LANG_GLOBS: dict[str, str] = {
    "dotnet": "**/*.cs",
    "go": "**/*.go",
    "java": "**/*.java",
    "php": "**/*.php",
    "python": "**/*.py",
    "ts": "**/*.ts,**/*.tsx,**/*.js,**/*.jsx",
    "rust": "**/*.rs",
    "swift": "**/*.swift",
    "dart": "**/*.dart",
    "e2e-playwright": "**/*.spec.ts,**/*.spec.js,**/e2e/**/*.ts,**/e2e/**/*.js",
}


# The five topics of a conventions pack. One `docs/conventions/common/<part>.md`
# per repo plus one `docs/conventions/<lang>/<part>.md` per scaffolded
# language; the language file extends the common one, and
# `docs/conventions/<lang>.md` is the entry file that links both.
CONVENTION_PARTS: tuple[str, ...] = (
    "coding-style",
    "patterns",
    "security",
    "testing",
    "hooks",
)


def _template_text(name: str) -> str:
    return (
        resources.files("strata_kb")
        .joinpath(f"templates/init/{name}")
        .read_text(encoding="utf-8")
    )


def _write(dest: Path, text: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8", newline="\n")


def _render_pointer(text: str, lang: str) -> str:
    # plain substring replace, same rationale as initcmd._render: template
    # text may legitimately contain other `{`/`}` characters.
    return text.replace("{lang}", lang).replace("{globs}", LANG_GLOBS[lang])


def _sync(target: Path, rel: str, text: str, report: InitReport) -> None:
    """Create-or-refresh with the same semantics as init_repo's main loop."""
    dest = target / rel
    if dest.exists():
        if dest.read_text(encoding="utf-8") == text:
            return
        dest.write_text(text, encoding="utf-8", newline="\n")
        report.updated.append(rel)
        return
    _write(dest, text)
    report.created.append(rel)


def scaffold_conventions(
    target: Path, report: InitReport, forced: Iterable[str] = ()
) -> list[str]:
    """Scaffold conventions files for every detected-or-forced language.

    Also writes the language-agnostic half of the conventions pack,
    `docs/conventions/common/<part>.md`, once per repo.

    Base + pointer files are package-owned (create-or-refresh); the
    `.local.md` stub is user data — created once, then never compared,
    never rewritten, not even with ``--force`` (its path is dynamic, so it
    cannot sit in PROTECTED_FILES; this function enforces the skip
    itself). Returns the scaffolded language ids: detected ∪ forced.
    """
    langs = sorted(set(detect_langs(target)) | set(forced))
    if not langs:
        report.notes.append(
            "no language manifests detected — conventions skipped; re-run "
            "kb init after adding code, or pass --lang <id> (one of "
            f"{', '.join(LANG_IDS)})"
        )
        return []
    stub = _template_text("conventions-local-stub.md")
    mdc = _template_text("conventions-pointer.mdc")
    instr = _template_text("conventions-pointer.instructions.md")
    # Language-agnostic half of the pack: one copy per repo, not per
    # language. Written after the no-language early return above, so a repo
    # with nothing detected still gets no docs/conventions/ directory.
    for part in CONVENTION_PARTS:
        _sync(
            target,
            f"docs/conventions/common/{part}.md",
            _template_text(f"conventions-common-{part}.md"),
            report,
        )
    for lang in langs:
        _sync(
            target,
            f"docs/conventions/{lang}.md",
            _template_text(f"conventions-{lang}.md"),
            report,
        )
        local_rel = f"docs/conventions/{lang}.local.md"
        local = target / "docs" / "conventions" / f"{lang}.local.md"
        if local.exists():
            report.skipped.append(
                f"docs/conventions/{lang}.local.md (local overrides — never refreshed)"
            )
        else:
            _write(local, stub)
            report.created.append(local_rel)
        _sync(
            target,
            f".cursor/rules/coding-{lang}.mdc",
            _render_pointer(mdc, lang),
            report,
        )
        _sync(
            target,
            f".github/instructions/coding-{lang}.instructions.md",
            _render_pointer(instr, lang),
            report,
        )
    return langs


CLAUDE_MARKER = "<!-- kb:conventions -->"

# Generic on purpose: it points at docs/conventions/ as a directory
# convention rather than naming languages, so detecting a new language
# later never requires editing an already-appended block.
_CLAUDE_BLOCK = (
    f"{CLAUDE_MARKER}\n"
    "**Coding conventions.**\n"
    "For each language you touch, read `docs/conventions/<lang>.md` and the\n"
    "five pack files it links under `docs/conventions/<lang>/` and\n"
    "`docs/conventions/common/`; if `docs/conventions/<lang>.local.md`\n"
    "exists it overrides them all. Where any of them conflicts with the\n"
    "repo's existing dominant style, the\n"
    "repo wins locally — record the conflict as a finding in the PR.\n"
)


def ensure_claude_block(target: Path, report: InitReport) -> None:
    """Append-only marker block, modelled on initcmd._record_kind.

    Missing file → create with the block; present without the marker →
    append, preserving existing bytes exactly; marker present → do
    nothing. User content is never rewritten.

    Reads with ``newline=""`` (universal-newline translation disabled) so
    pre-existing CRLF line endings survive unchanged in the string; the
    write below uses ``newline="\\n"``, which performs no translation
    either, so those bytes pass straight through and only the appended
    block is LF. ``Path.read_text`` gained a ``newline`` parameter only in
    3.13, so this project (>=3.11) goes through ``Path.open`` instead.
    """
    dest = target / "CLAUDE.md"
    if not dest.exists():
        _write(dest, _CLAUDE_BLOCK)
        report.created.append("CLAUDE.md")
        return
    with dest.open(encoding="utf-8", newline="") as f:
        text = f.read()
    if CLAUDE_MARKER in text:
        return
    if text and not text.endswith("\n"):
        text += "\n"
    dest.write_text(
        text + "\n" + _CLAUDE_BLOCK, encoding="utf-8", newline="\n"
    )
    report.updated.append("CLAUDE.md (conventions block appended)")
