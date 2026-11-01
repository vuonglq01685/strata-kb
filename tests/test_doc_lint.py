"""Doc lint: guides, quickstarts and README name only real commands, with no stale facts."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src/strata_kb"
DOCS_SRC = REPO_ROOT / "docs/src"
DOCS: list[Path] = [
    REPO_ROOT / "README.md",
    *sorted(DOCS_SRC.glob("*.md")),
    *sorted((SRC / "templates/init").glob("QUICKSTART-*.md")),
]

# Cleared by the guides rewrite: the last task touching the offending files removes the mark.
REWRITE_PENDING = pytest.mark.xfail(strict=True, reason="cleared by the guides rewrite")

# `kb <name>[ <sub>]` where the backtick opens the span, so prose like "`kb` itself" is skipped.
KB_COMMAND = re.compile(r"`kb ([a-z][a-z0-9-]*)(?: ([a-z][a-z0-9-]*))?")
SLASH_COMMAND = re.compile(r"`/((?:kb|ba|dev|sa)-[a-z0-9-]+)")
VERSION = re.compile(r"\bv?1\.\d{1,2}\.\d{1,2}\b")
MD_LINK = re.compile(r"\]\(([^)\s]+)\)")
HEADING = re.compile(r"^(#{1,3}) ", re.MULTILINE)
FENCE = re.compile(r"^(```|~~~).*?^\1", re.MULTILINE | re.DOTALL)
FENCE_BODY = re.compile(
    r"^(?:```|~~~)[^\n]*\n(.*?)^(?:```|~~~)", re.MULTILINE | re.DOTALL
)
# Inside a fence there is no opening backtick, so `kb ...` must start a line or follow whitespace.
FENCED_KB_COMMAND = re.compile(
    r"(?:^|\s)kb ([a-z][a-z0-9-]*)(?: ([a-z][a-z0-9-]*))?", re.MULTILINE
)
# A link written inside a code span is a literal, not a link.
INLINE_CODE = re.compile(r"`[^`\n]*`")


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _cmd_name(c) -> str:
    return c.name or c.callback.__name__.replace("_", "-")


def _real_commands() -> tuple[set[str], dict[str, set[str]]]:
    from strata_kb.cli import app

    top = {_cmd_name(c) for c in app.registered_commands if not c.hidden}
    groups = {
        g.name: {_cmd_name(c) for c in g.typer_instance.registered_commands}
        | {
            sg.name for sg in g.typer_instance.registered_groups
        }  # nested group, e.g. `kb l3 fix`
        for g in app.registered_groups
        if not g.hidden
    }
    return top | set(groups), groups


def test_docs_name_only_real_kb_commands():
    names, groups = _real_commands()
    bad = []
    for doc in DOCS:
        text = _text(doc)
        refs = KB_COMMAND.findall(text)
        for body in FENCE_BODY.findall(text):
            refs += FENCED_KB_COMMAND.findall(body)
        for name, sub in refs:
            if name not in names or (
                name in groups and sub and sub not in groups[name]
            ):
                bad.append((_rel(doc), f"kb {name} {sub}".strip()))
    assert not bad, sorted(set(bad))


def test_docs_name_only_real_slash_commands():
    real = {
        re.sub(r"^claude-(skill|command)-|\.md$", "", p.name)
        for p in (SRC / "templates/init").glob("claude-*.md")
    }
    bad = sorted(
        {
            (_rel(doc), f"/{name}")
            for doc in DOCS
            for name in SLASH_COMMAND.findall(_text(doc))
            if name not in real
        }
    )
    assert not bad, bad


@REWRITE_PENDING
def test_guides_and_quickstarts_carry_no_version_numbers():
    files = [
        *DOCS_SRC.glob("guide-*.md"),
        *DOCS_SRC.glob("architecture.*.md"),
        *(SRC / "templates/init").glob("QUICKSTART-*.md"),
    ]
    bad = sorted({(_rel(p), m) for p in files for m in VERSION.findall(_text(p))})
    assert not bad, bad


def _heading_levels(path: Path) -> list[int]:
    return [len(h) for h in HEADING.findall(FENCE.sub("", _text(path)))]


def test_vi_guides_mirror_en_headings():
    problems = []
    for en in sorted(DOCS_SRC.glob("*.en.md")):
        vi = en.with_name(en.name.replace(".en.md", ".vi.md"))
        if not vi.exists():
            problems.append((_rel(en), "missing vi"))
            continue
        en_levels, vi_levels = _heading_levels(en), _heading_levels(vi)
        if en_levels != vi_levels:
            first = next(
                (
                    i
                    for i, (a, b) in enumerate(zip(en_levels, vi_levels, strict=False))
                    if a != b
                ),
                min(len(en_levels), len(vi_levels)),
            )
            problems.append(
                (
                    _rel(en),
                    f"{len(en_levels)} EN vs {len(vi_levels)} VI headings, "
                    f"first difference at index {first}",
                )
            )
    assert not problems, problems


def test_pdf_titles_match_sources():
    pytest.importorskip("xhtml2pdf")
    pytest.importorskip("markdown")
    spec = importlib.util.spec_from_file_location(
        "build_pdf", DOCS_SRC / "build_pdf.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert set(module.TITLES) == {p.stem for p in DOCS_SRC.glob("*.md")}


def _slug(heading: str) -> str:
    heading = re.sub(r"[`*]", "", heading.strip().lower())
    return re.sub(r"[^\w\- ]", "", heading).replace(" ", "-")


def _anchors(path: Path) -> set[str]:
    body = FENCE.sub("", _text(path))
    return {_slug(m) for m in re.findall(r"^#{1,6} (.+?)\s*#*$", body, re.MULTILINE)}


def test_doc_links_resolve():
    bad = []
    for doc in DOCS:
        for link in MD_LINK.findall(INLINE_CODE.sub("", FENCE.sub("", _text(doc)))):
            if re.match(r"[a-z][a-z0-9+.-]*:", link):
                continue  # external URL or mailto
            target, _, anchor = link.partition("#")
            path = (doc.parent / target).resolve() if target else doc
            if not path.is_file():
                bad.append((_rel(doc), link, "missing file"))
            elif (
                anchor and path.suffix == ".md" and anchor.lower() not in _anchors(path)
            ):
                bad.append((_rel(doc), link, "missing anchor"))
    assert not bad, bad
