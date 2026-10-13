"""planingest — `kb plan-ingest`: the `<repo_id>-plan` hub document.

The `ba` twin of `kb code-ingest`. It turns the missions that lint clean offline
and the tickets a BA has finished (lint-clean offline, Definition of Ready
ticked, not demoted by a newer mission revision) into `.kb/<repo_id>-plan/`: one group file per mission
(the mission plus its tickets) and one `tickets` group for the rest. No LLM,
no hub, and no clock: the output is a pure function of the working tree.
"""

from __future__ import annotations

import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from strata_kb import (
    kinds,
    lintcore,
    missionlint,
    missionnext,
    models,
    planrev,
    ticketlint,
)
from strata_kb.codeingest import core
from strata_kb.codeingest.types import CodeSection
from strata_kb.errors import KbError
from strata_kb.mdutils import _FENCE_RE, extract_tables

TITLE_SUFFIX = kinds.PLAN_TITLE_SUFFIX
TICKETS_GROUP = "tickets"
HUB_UNREACHABLE = "hub-unreachable"
# Prose the L2 keeps; every table is kept regardless (build._check_tables).
_MISSION_PROSE = ("Summary", "Business goal")
_TICKET_PROSE = ("User Story", "Acceptance Criteria")
_DROPPED_SECTIONS = ("## Review record", "## Definition of Ready")
_ATX_RE = re.compile(r"^(#{1,6})(?=[ \t]|$)")
_SENTENCE_RE = re.compile(r"^(.+?[.!?])(?:\s|$)")


class PlanIngestError(KbError):
    """Unreadable input, a bad directory, an unusable repo id, or a
    destination `kb plan-ingest` did not generate."""


@dataclass
class PlanIngestReport:
    doc_id: str
    published: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    files_written: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Item:
    id: str
    file: str
    text: str
    is_mission: bool
    group: str = ""


def _fenced(lines: list[str]) -> list[bool]:
    """True for each line inside a fence or opening/closing one — the same
    rule as `mdutils._unfenced_lines`."""
    flags: list[bool] = []
    fence = ""
    for line in lines:
        m = _FENCE_RE.match(line.strip())
        if m is None:
            flags.append(bool(fence))
            continue
        marker = m.group(1)
        if not fence:
            fence = marker
        elif marker[0] == fence[0] and len(marker) >= len(fence):
            fence = ""
        flags.append(True)
    return flags


def demote_headings(markdown: str) -> str:
    """Every ATX heading one level deeper (`##` -> `###`); fenced lines are
    left alone. Level 6 stays 6, which has no deeper level."""
    lines = markdown.split("\n")
    out = []
    for line, fenced in zip(lines, _fenced(lines), strict=True):
        m = None if fenced else _ATX_RE.match(line)
        out.append("#" + line if m and len(m.group(1)) < 6 else line)
    return "\n".join(out)


def promote_headings(markdown: str) -> str:
    """Inverse of `demote_headings`: every ATX heading deeper than `##` one
    level up (`###` -> `##`); fenced lines and `#`/`##` lines stay."""
    lines = markdown.split("\n")
    out = []
    for line, fenced in zip(lines, _fenced(lines), strict=True):
        m = None if fenced else _ATX_RE.match(line)
        out.append(line[1:] if m and len(m.group(1)) > 2 else line)
    return "\n".join(out)


def _normalize(text: str) -> str:
    """LF and NFC, so a CRLF or NFD twin renders the same sections."""
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))


def _title(text: str) -> str:
    lines = text.split("\n")
    for line, fenced in zip(lines, _fenced(lines), strict=True):
        if not fenced and line.startswith("# "):
            return line[2:].strip()
    return ""


def _l3_body(text: str) -> str:
    """The source minus its H1, Review record and Definition of Ready, with
    every heading demoted one level. A second H1 would become a `## `
    heading and open a section of its own, so it is pushed down first."""
    lines = text.split("\n")
    kept: list[str] = []
    title_seen = False
    dropping = False
    for line, fenced in zip(lines, _fenced(lines), strict=True):
        m = None if fenced else _ATX_RE.match(line)
        if m:
            level = len(m.group(1))
            dropping = line.strip() in _DROPPED_SECTIONS or (dropping and level > 2)
            if level == 1:
                if not title_seen:
                    title_seen = True
                    continue
                line = "#" + line
        if not dropping:
            kept.append(line)
    return demote_headings("\n".join(kept)).strip("\n")


def _prose(l3_body: str, headings: tuple[str, ...]) -> list[str]:
    """`### <heading>` plus its prose for each named section, in L3 order.
    Tables stay out (they follow separately) and so do fenced blocks."""
    lines = l3_body.split("\n")
    out: list[str] = []
    current: list[str] | None = None
    for line, fenced in zip(lines, _fenced(lines), strict=True):
        m = None if fenced else _ATX_RE.match(line)
        if m and len(m.group(1)) <= 3:
            name = line[len(m.group(1)) :].strip()
            current = [] if m.group(1) == "###" and name in headings else None
            if current is not None:
                out.append(line)
                out.append("")
        elif current is not None and not fenced:
            if not line.lstrip().startswith("|"):
                out.append(line)
    text = lintcore.HTML_COMMENT_RE.sub("", "\n".join(out))
    blocks = re.split(r"\n(?=### )", text)
    return [re.sub(r"\n{3,}", "\n\n", b).strip() for b in blocks if "\n" in b.strip()]


def _l2_body(l3_body: str, is_mission: bool) -> str:
    parts = _prose(l3_body, _MISSION_PROSE if is_mission else _TICKET_PROSE)
    parts += extract_tables(l3_body)
    return "\n\n".join(parts)


def _summary(text: str, title: str) -> str:
    body = lintcore.section_body(text, "## Summary") or ""
    para = " ".join(lintcore.HTML_COMMENT_RE.sub("", body).split())
    m = _SENTENCE_RE.match(para)
    return (m.group(1) if m else para) or title


def _section(item: _Item) -> CodeSection | None:
    title = _title(item.text)
    if not title:
        return None
    l3 = _l3_body(item.text)
    return CodeSection(
        id=item.id,
        title=title,
        summary=_summary(item.text, title),
        group=item.group,
        l2_md=_l2_body(l3, item.is_mission),
        l3_md=l3,
    )


def _offline_errors(report) -> list[str]:
    return [
        i.message
        for i in report.issues
        if i.level == "error" and i.code != HUB_UNREACHABLE
    ]


def _dor_reason(text: str) -> str | None:
    ticked, total = missionnext.dor_counts(text)
    if total > 0 and ticked == total:
        return None
    return f"Definition of Ready not fully ticked ({ticked}/{total})"


def _read(path: Path) -> str:
    try:
        return _normalize(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise PlanIngestError(f"cannot read {path}: {exc}") from exc


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _fence_reason(text: str) -> str | None:
    """`mdutils.section_map` splits on every line starting with `## `, fenced
    or not, so such a line inside a fence would cut the section for readers."""
    lines = text.split("\n")
    if any(
        f and line.startswith("## ")
        for line, f in zip(lines, _fenced(lines), strict=True)
    ):
        return "fenced line starting with '## ' would split the section — indent it inside the fence"
    return None


def _lint_reason(report) -> str | None:
    errors = _offline_errors(report)
    if not errors:
        return None
    more = f" (+{len(errors) - 1} more)" if len(errors) > 1 else ""
    return f"lint error: {errors[0]}{more}"


def _select(
    repo_root: Path, missions_dir: Path, tickets_dir: Path, report: PlanIngestReport
) -> list[_Item]:
    root = repo_root.resolve()
    mission_texts: dict[str, str] = {}
    published: list[_Item] = []
    for path in sorted(missions_dir.glob("*.md")):
        text = _read(path)
        mission_texts[path.stem] = text
        file = _rel(path, root)
        # No DoR gate for a mission: it ships as soon as it lints, and every
        # amend republishes it. Its tickets keep theirs (published = ready).
        reason = _lint_reason(missionlint.lint(text, None, path=path)) or _fence_reason(
            text
        )
        if reason:
            report.skipped.append((file, reason))
        else:
            published.append(_Item(path.stem, file, text, True, path.stem))

    ticket_texts: dict[str, str] = {}
    ticket_files: dict[str, Path] = {}
    for path in sorted(tickets_dir.rglob("*.md")):
        if path.stem in ticket_files or path.stem in mission_texts:
            report.skipped.append(
                (_rel(path, root), f"duplicate id {path.stem}; kept the first")
            )
            continue
        ticket_files[path.stem] = path
        ticket_texts[path.stem] = _read(path)
    demoted = planrev.demotions(mission_texts, ticket_texts)

    live = {m.id for m in published}
    for us_id, path in ticket_files.items():
        text = ticket_texts[us_id]
        file = _rel(path, root)
        reason = (
            "id contains whitespace" if re.search(r"\s", us_id) else None
        ) or _lint_reason(
            ticketlint.lint(text, None, path=path, missions_dir=missions_dir)
        )
        reason = (
            reason or _fence_reason(text) or _dor_reason(text) or demoted.get(us_id)
        )
        if reason:
            report.skipped.append((file, reason))
            continue
        pin = planrev.parent_pin(text)
        group = pin[0] if pin and pin[0] in live else TICKETS_GROUP
        published.append(_Item(us_id, file, text, False, group))
    return published


def _natural(value: str) -> list:
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", value)]


def _check_owned(doc_dir: Path) -> None:
    """Refuse to overwrite or delete a document this command did not write."""
    manifest_path = doc_dir / "_manifest.yaml"
    if not (manifest_path.is_file() or any(doc_dir.glob("*.md"))):
        return
    try:
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
    except (yaml.YAMLError, OSError, UnicodeDecodeError, ValidationError) as exc:
        raise PlanIngestError(
            f"{doc_dir} holds content with no readable _manifest.yaml ({exc}); "
            "move it away — nothing was written"
        ) from exc
    if not manifest.title.endswith(TITLE_SUFFIX):
        raise PlanIngestError(
            f"{doc_dir} holds a document kb plan-ingest did not generate "
            f"(title: {manifest.title!r}); nothing was written"
        )


def _drop_index_entry(kb_dir: Path, doc_id: str) -> None:
    index_path = kb_dir / "index.yaml"
    if not index_path.exists():
        return
    try:
        index = models.load_yaml_model(index_path, models.KBIndex)
        index.docs = [d for d in index.docs if d.id != doc_id]
        models.save_yaml_model(index_path, index)
    except (yaml.YAMLError, OSError, UnicodeDecodeError, ValidationError) as exc:
        raise PlanIngestError(f"cannot update {index_path}: {exc}") from exc


def run(
    repo_root: Path,
    kb_dir: Path,
    repo_id: str,
    missions_dir: Path,
    tickets_dir: Path,
) -> PlanIngestReport:
    doc_id = f"{repo_id}-plan"
    if not models.DOC_ID_RE.match(doc_id):
        raise PlanIngestError(
            f"repo id {repo_id!r} makes the invalid document id {doc_id!r}; "
            "pass --repo-id with letters, digits, '.', '_' or '-'"
        )
    for flag, d in (("--missions-dir", missions_dir), ("--tickets-dir", tickets_dir)):
        if not d.is_dir():
            raise PlanIngestError(f"{flag} '{d}' does not exist or is not a directory")

    report = PlanIngestReport(doc_id=doc_id)
    items = _select(repo_root, missions_dir, tickets_dir, report)
    items.sort(key=lambda i: (i.group, not i.is_mission, _natural(i.id)))
    sections: list[CodeSection] = []
    for item in items:
        section = _section(item)
        if section is None:
            report.skipped.append((item.file, "no '# ' title line"))
            continue
        sections.append(section)
        report.published.append(item.id)

    doc_dir = kb_dir / doc_id
    _check_owned(doc_dir)
    if not sections:
        try:
            shutil.rmtree(doc_dir, ignore_errors=not doc_dir.exists())
        except OSError as exc:
            raise PlanIngestError(f"could not remove {doc_dir} ({exc})") from exc
        _drop_index_entry(kb_dir, doc_id)
        return report

    short = core._head_commit(repo_root)[:7]
    banner = (
        f"> Generated by kb plan-ingest at {short or 'unknown-commit'} — "
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
                report.files_written.append(name)
        for stale in doc_dir.glob("*.md"):
            if stale.name not in written:
                stale.unlink()
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
        report.files_written.append("_manifest.yaml")
    except OSError as exc:
        raise PlanIngestError(f"could not write {doc_dir} ({exc})") from exc

    # `-plan` is gitignored, `index.yaml` is not: no revision in the index.
    index_report = core.CodeIngestReport(doc_id=doc_id)
    core._upsert_index_entry(
        kb_dir,
        doc_id,
        title,
        "",
        f"Published plan (missions and tickets) for the {repo_id} repository.",
        ["plan", "generated"],
        (),
        index_report,
    )
    if index_report.warnings:
        raise PlanIngestError("; ".join(index_report.warnings))
    return report
