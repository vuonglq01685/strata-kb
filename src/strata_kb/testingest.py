"""testingest — `kb report-ingest`: the `<repo_id>-test` hub document.

The `tester` twin of `kb plan-ingest`. It turns each story's lint-clean test
case spec (`tests/<story>/test-cases.md`) and lint-clean reports
(`reports/<story>/R<n>.md`) into `.kb/<repo_id>-test/`: one group per story,
the cases first, then the rounds. No LLM, no hub, no clock: the output is a
pure function of the working tree.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from strata_kb import (
    kinds,
    models,
    planingest,
    planstatus,
    testcases,
    testreport,
)
from strata_kb.codeingest import core
from strata_kb.codeingest.types import CodeSection
from strata_kb.errors import KbError
from strata_kb.mdmask import visible_body
from strata_kb.mdutils import extract_tables

TITLE_SUFFIX = kinds.TEST_TITLE_SUFFIX
ASSETS_DIR = planingest.ASSETS_DIR
CASES_FILE = "test-cases.md"
_ROUND_RE = re.compile(r"R([1-9]\d*)\.md")


class TestIngestError(KbError):
    """Unreadable input, a bad directory, an unusable repo id, or a
    destination `kb report-ingest` did not generate."""

    __test__ = False  # not a pytest class


@dataclass
class TestIngestReport:
    __test__ = False  # not a pytest class
    doc_id: str
    published: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    files_written: list[str] = field(default_factory=list)


def _read(path: Path) -> str:
    try:
        return planingest.normalize_text(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise TestIngestError(f"cannot read {path}: {exc}") from exc


def _section(sid: str, group: str, text: str, summary: str) -> CodeSection | None:
    title = planingest.section_title(text)
    if not title:
        return None
    l3 = planingest.l3_body(text)
    return CodeSection(
        id=sid,
        title=title,
        summary=summary,
        group=group,
        l2_md="\n\n".join(extract_tables(l3)),
        l3_md=l3,
    )


def _ship_report(
    story: str,
    n: int,
    path: Path,
    kids: tuple[str, ...],
    root: Path,
) -> tuple[CodeSection, dict[str, bytes]] | str:
    """The section and image assets of one report, or why it cannot ship."""
    text = _read(path)
    rep = testreport.parse(text)
    if rep.round != n:
        return f"header Round {rep.round} does not match file name R{n}"
    if reason := planingest.lint_reason(
        testreport.lint(
            text, report_dir=path.parent, story_children=kids, repo_root=root
        )
    ) or planingest.fence_reason(text):
        return reason
    attached = planingest.attach_images(
        text,
        testreport._IMAGE_RE.findall(visible_body(text)),
        ASSETS_DIR,
        path.parent,
        "report",
    )
    if isinstance(attached, str):
        return attached
    text, files = attached
    passed = sum(1 for _, _, r in rep.results if r == "PASS")
    summary = f"R{n} {rep.verdict} — {passed}/{len(rep.results)}"
    sec = _section(f"{story}.R{n}", story, text, summary)
    return (sec, dict(files)) if sec else "no '# ' title line"


def _ship_story(
    story: str,
    spec_path: Path,
    root: Path,
    reports_dir: Path,
    children_of: Callable[[str], tuple[str, ...]],
    out: TestIngestReport,
    assets: dict[str, bytes],
) -> list[CodeSection]:
    spec_text = _read(spec_path)
    ticket_path = spec_path.parent / "ticket.md"
    ticket_text = _read(ticket_path) if ticket_path.is_file() else None
    spec = testcases.parse(spec_text)
    spec_file = planingest.rel_path(spec_path, root)
    reason = planingest.lint_reason(
        testcases.lint(spec_text, ticket_text, spec_dir=spec_path.parent)
    ) or planingest.fence_reason(spec_text)
    cases = (
        None
        if reason
        else _section(
            f"{story}.cases", story, spec_text, f"{len(spec.cases)} test cases"
        )
    )
    if cases is None:
        out.skipped.append((spec_file, reason or "no '# ' title line"))
    sections = [cases] if cases else []

    story_reports = reports_dir / story
    kids = spec.children or children_of(story)
    for path in sorted(story_reports.glob("*.md"), key=lambda p: (len(p.name), p.name)):
        file = planingest.rel_path(path, root)
        m = _ROUND_RE.fullmatch(path.name)
        if m is None:
            out.skipped.append(
                (file, "file name is not R<n>.md (n from 1, no leading zero)")
            )
        elif cases is None:
            out.skipped.append((file, f"test cases of {story} are not shippable"))
        elif isinstance(
            shipped := _ship_report(story, int(m.group(1)), path, kids, root), str
        ):
            out.skipped.append((file, shipped))
        else:
            sections.append(shipped[0])
            assets.update(shipped[1])
    return sections


def run(
    repo_root: Path,
    kb_dir: Path,
    repo_id: str,
    tests_dir: Path,
    reports_dir: Path,
    children_of: Callable[[str], tuple[str, ...]],
) -> TestIngestReport:
    doc_id = f"{repo_id}-test"
    if not models.DOC_ID_RE.match(doc_id):
        raise TestIngestError(
            f"repo id {repo_id!r} makes the invalid document id {doc_id!r}; "
            "pass --repo-id with letters, digits, '.', '_' or '-'"
        )
    if not tests_dir.is_dir():
        raise TestIngestError(
            f"--tests-dir '{tests_dir}' does not exist or is not a directory"
        )
    root = repo_root.resolve()
    out = TestIngestReport(doc_id=doc_id)
    sections: list[CodeSection] = []
    assets: dict[str, bytes] = {}
    for story_dir in sorted(p for p in tests_dir.iterdir() if p.is_dir()):
        spec_path = story_dir / CASES_FILE
        if not spec_path.is_file():
            continue
        if not planstatus.safe_name(story_dir.name):
            out.skipped.append(
                (planingest.rel_path(spec_path, root), "unsafe story folder name")
            )
            continue
        sections += _ship_story(
            story_dir.name, spec_path, root, reports_dir, children_of, out, assets
        )
    out.published = [s.id for s in sections]

    doc_dir = kb_dir / doc_id
    planingest.check_owned(doc_dir, TITLE_SUFFIX, "kb report-ingest", TestIngestError)
    if not sections:
        try:
            shutil.rmtree(doc_dir, ignore_errors=not doc_dir.exists())
        except OSError as exc:
            raise TestIngestError(f"could not remove {doc_dir} ({exc})") from exc
        planingest.drop_index_entry(kb_dir, doc_id, TestIngestError)
        return out

    short = core._head_commit(repo_root)[:7]
    banner = (
        f"> Generated by kb report-ingest at {short or 'unknown-commit'} — "
        "do not edit by hand."
    )
    groups: dict[str, list[CodeSection]] = {}
    for sec in sections:
        groups.setdefault(sec.group, []).append(sec)
    title = f"{repo_id} {TITLE_SUFFIX}"
    try:
        doc_dir.mkdir(parents=True, exist_ok=True)
        written: set[str] = set()
        for group, secs in groups.items():
            for level, name in (("l2", f"{group}.md"), ("l3", f"{group}.raw.md")):
                core._write_group(
                    doc_dir / name, core._render_group(secs, level, banner, doc_id)
                )
                written.add(name)
                out.files_written.append(name)
        for stale in doc_dir.glob("*.md"):
            if stale.name not in written:
                stale.unlink()
        planingest.sync_assets(doc_dir, assets)
        manifest = models.Manifest(
            id=doc_id,
            title=title,
            revision=short,
            source_sha256="",
            ingested=core._head_date(repo_root),
            sections=[
                models.SectionEntry(
                    id=s.id,
                    title=s.title,
                    summary=s.summary,
                    status="summarized",
                    file=s.group,
                )
                for s in sections
            ],
        )
        models.save_yaml_model(doc_dir / "_manifest.yaml", manifest)
        out.files_written.append("_manifest.yaml")
    except OSError as exc:
        raise TestIngestError(f"could not write {doc_dir} ({exc})") from exc

    index_report = core.CodeIngestReport(doc_id=doc_id)
    core._upsert_index_entry(
        kb_dir,
        doc_id,
        title,
        "",
        f"Test cases and reports for the {repo_id} repository.",
        ["test", "generated"],
        (),
        index_report,
    )
    if index_report.warnings:
        raise TestIngestError("; ".join(index_report.warnings))
    return out
