"""`kb code-sync scan`: which hub-owned documents name something that changed
in the code docs since the baseline (spec §5.3-§5.5).

A pure function of (hub git history, baseline sha, scan sha): everything is
read from git objects, never the worktree or the search index.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path

import yaml

from strata_kb import config, gitio, mdutils, models
from strata_kb.authored import AUTHORED_TAG, SKIP_TAG
from strata_kb.codesync import baseline as baseline_mod
from strata_kb.codesync.changes import ChangedItem, code_changes

GENERATED_TAG = "generated"

# Generic words never identify one thing, so they never match by name.
STOP_WORDS = frozenset(
    [
        "api",
        "app",
        "web",
        "db",
        "service",
        "server",
        "main",
        "core",
        "data",
        "common",
        "shared",
        "base",
        "default",
        "test",
        "build",
        "lint",
        "run",
    ]
)
MIN_TERM_LEN = 4

NO_BASELINE_NOTE = "no baseline — run kb code-sync baseline"

DIGEST_PREFIX = "<!-- kb-code-sync digest:"


@dataclass(frozen=True)
class Finding:
    doc_id: str
    section_id: str
    section_title: str
    term: str
    image: bool
    item: ChangedItem


@dataclass(frozen=True)
class ScanResult:
    scan_sha: str
    baseline_sha: str | None
    baseline_source: str
    findings: tuple[Finding, ...]
    notes: tuple[str, ...]
    hub_repo_id: str = ""  # outside the digest: names federation/<rid>/ for the skill


def _fact_terms(kind: str, value: str) -> list[str]:
    if kind == "text":
        return []
    if kind == "route":  # "GET /orders": prose names the path
        return [value, value.partition(" ")[2]]
    if kind == "column_type":  # "amount:TEXT": prose names the column
        return [value.partition(":")[0]]
    return [value]


def match_terms(item: ChangedItem) -> list[str]:
    """Literal names to look for in hub prose, most specific filtering
    applied: generic and short names are dropped (spec §5.3)."""
    sid = item.section_id
    facts = sorted(item.added | item.removed)
    if sid is None:
        raw = [item.repo_id]  # a whole repo came or went: its name is the term
    elif sid.startswith("cmd."):
        raw = [v for k, v in facts if k == "command"]
    else:
        raw = [item.title, sid.partition(".")[2]]
        raw += [t for k, v in facts for t in _fact_terms(k, v)]
    terms = {t.strip() for t in raw}
    return sorted(
        t for t in terms if len(t) >= MIN_TERM_LEN and t.lower() not in STOP_WORDS
    )


def _pattern(term: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w-]){re.escape(term)}(?![\w-])", re.IGNORECASE)


def _tags(
    reader: gitio.BatchReader, root: Path, sha: str, rid: str
) -> dict[str, list[str]] | None:
    """Tags per published hub doc; None when the hub has no index at `sha`."""
    text = reader.read_at(sha, root / "federation" / rid / "index.yaml")
    if text is None:
        return None
    index = models.KBIndex.model_validate(yaml.safe_load(text))
    return {e.id: e.tags for e in index.docs}


def _must_read(reader: gitio.BatchReader, sha: str, root: Path, path: Path) -> str:
    """A file a published hub doc lists must exist at `sha`; a half-published
    doc is an error (exit 1), not a silent gap."""
    text = reader.read_at(sha, path)
    if text is None:
        rel = path.relative_to(root).as_posix()
        raise gitio.GitError(f"{rel} is missing at {sha[:12]} (unreadable hub doc)")
    return text


def _hub_sections(
    reader: gitio.BatchReader, root: Path, sha: str, rid: str, doc_id: str
) -> list[tuple[str, str, str]]:
    """`(section id, title, L3 text)` of one hub doc at `sha`."""
    folder = root / "federation" / rid / doc_id
    text = _must_read(reader, sha, root, folder / "_manifest.yaml")
    manifest = models.Manifest.model_validate(yaml.safe_load(text))
    out: list[tuple[str, str, str]] = []
    for sec, occ in zip(
        manifest.sections, mdutils.heading_occurrences(manifest.sections), strict=True
    ):
        md = _must_read(reader, sha, root, folder / f"{sec.file}.raw.md")
        out.append((sec.id, sec.title, mdutils.slice_section(md, sec.id, occ) or ""))
    return out


def _first_hit(
    patterns: list[tuple[str, re.Pattern[str]]], l3: str
) -> tuple[str, bool] | None:
    """`(term, image)` of the first term found in prose; failing that, in an
    image description only (image=True)."""
    prose = mdutils._IMAGE_MD_RE.sub("", l3)
    image_term: str | None = None
    for term, pat in patterns:
        if pat.search(prose):
            return term, False
        if image_term is None and pat.search(l3):
            image_term = term
    return (image_term, True) if image_term is not None else None


def hub_repo_id(root: Path) -> str:
    return config.effective_repo_id("", root / ".kb") or root.name


def _findings(
    root: Path, scan_sha: str, items: list[ChangedItem]
) -> tuple[list[Finding], list[str]]:
    rid = hub_repo_id(root)
    patterns = [(item, [(t, _pattern(t)) for t in match_terms(item)]) for item in items]
    patterns = [(item, pats) for item, pats in patterns if pats]
    findings: list[Finding] = []
    notes: list[str] = []
    with gitio.BatchReader(root) as reader:
        docs = _tags(reader, root, scan_sha, rid)
        if docs is None:
            notes.append(
                f"no published hub documents under federation/{rid}/ — check repo_id"
            )
            return findings, notes
        for doc_id, tags in sorted(docs.items()):
            if GENERATED_TAG in tags or SKIP_TAG in tags:
                continue
            if AUTHORED_TAG not in tags:
                notes.append(f"{doc_id} is not tagged authored")
            for sid, title, l3 in _hub_sections(reader, root, scan_sha, rid, doc_id):
                for item, pats in patterns:
                    hit = _first_hit(pats, l3)
                    if hit is not None:
                        findings.append(Finding(doc_id, sid, title, *hit, item))
    return findings, notes


def _sort_key(f: Finding) -> tuple[str, ...]:
    i = f.item
    return (
        f.doc_id,
        f.section_id,
        str(f.image),
        i.repo_id,
        i.doc_id,
        i.section_id or "",
    )


def run_scan(
    root: Path,
    *,
    baseline_sha: str | None = None,
    baseline_source: str = "override",
    bot_ref: bool = True,
) -> ScanResult:
    """Findings between the baseline and the default branch's tip.

    `baseline_sha` overrides the baseline file (tests, recovery, the runner's
    REST read) and is labelled `baseline_source`. `bot_ref` False ignores the
    local bot-branch tracking ref (the runner has no PR-state check for it). GitError when a sha is not
    in the repo's history."""
    root = root.resolve()
    scan_sha = baseline_mod.scan_ref(root)
    if baseline_sha is not None:
        base: str | None = gitio.resolve_commit(
            root, baseline_mod.check_sha(baseline_sha)
        )
        source = baseline_source
    else:
        base, source = baseline_mod.resolve(root, scan_sha, bot_ref=bot_ref)
        if base is not None:
            base = gitio.resolve_commit(root, base)
    if base is None:
        return ScanResult(
            scan_sha, None, source, (), (NO_BASELINE_NOTE,), hub_repo_id(root)
        )
    findings, notes = _findings(root, scan_sha, code_changes(root, base, scan_sha))
    return ScanResult(
        scan_sha,
        base,
        source,
        tuple(sorted(findings, key=_sort_key)),
        tuple(notes),
        hub_repo_id(root),
    )


_FACT_LABELS = {
    "depends_on": "`Depends on`",
    "port": "port",
    "env_key": "env key",
    "technology": "technology",
    "column": "column",
    "column_type": "column type",
    "pk": "primary key",
    "route": "route",
    "command": "command",
    "framework": "framework",
}


def _fact_line(verb: str, kind: str, value: str, *, gone: bool) -> str:
    if kind == "depends_on":
        return f"`Depends on` {'no longer lists' if gone else 'now lists'} `{value}`"
    return f"{_FACT_LABELS.get(kind, kind)} `{value}` {verb}"


def describe(item: ChangedItem) -> str:
    """One line saying what changed in the code doc."""
    what = "document" if item.section_id is None else "section"
    if item.status != "changed":
        return f"{what} {item.status}"
    parts = [
        _fact_line("removed", k, v, gone=True)
        for k, v in sorted(item.removed)
        if k != "text"
    ] + [
        _fact_line("added", k, v, gone=False)
        for k, v in sorted(item.added)
        if k != "text"
    ]
    if any(k == "text" for k, _ in item.added | item.removed):
        parts.append("description changed")
    return "; ".join(parts)


def _source(item: ChangedItem) -> str:
    kind = item.doc_id.rsplit("-", 1)[-1]
    where = f"§{item.section_id}" if item.section_id else "whole document"
    return f"`-{kind} {where}` ({item.doc_id})"


def line(f: Finding) -> str:
    return f"{f.term} — {_source(f.item)}: {describe(f.item)}"


def to_json(r: ScanResult) -> dict:
    return {
        "scan_sha": r.scan_sha,
        "baseline_sha": r.baseline_sha,
        "baseline_source": r.baseline_source,
        "notes": list(r.notes),
        "hub_repo_id": r.hub_repo_id,
        "findings": [_finding_json(f) for f in r.findings],
    }


def _finding_json(f: Finding) -> dict:
    i = f.item
    return {
        "doc_id": f.doc_id,
        "section_id": f.section_id,
        "section_title": f.section_title,
        "term": f.term,
        "image": f.image,
        "repo_id": i.repo_id,
        "code_doc_id": i.doc_id,
        "code_section_id": i.section_id,
        "status": i.status,
        "added": sorted(i.added),
        "removed": sorted(i.removed),
    }


def digest(r: ScanResult) -> str:
    """sha256 of the canonical JSON of the findings only, so the header (shas,
    notes) can move without making the same work order look new."""
    canon = json.dumps(
        [_finding_json(f) for f in r.findings],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def exit_code(r: ScanResult) -> int:
    return 2 if r.findings else 0


def render_markdown(r: ScanResult) -> str:
    base = f"{r.baseline_sha[:12]} ({r.baseline_source})" if r.baseline_sha else "none"
    n = len(r.findings)
    lines = [f"Scan: {r.scan_sha[:12]} · Baseline: {base} · {n} finding(s)"]
    lines += [f"note: {note}" for note in r.notes]
    for (doc_id, sid, title, image), group in groupby(
        r.findings, key=lambda f: (f.doc_id, f.section_id, f.section_title, f.image)
    ):
        lines += ["", f"## {doc_id} §{sid} {title}" + ("  (image)" if image else "")]
        lines += [f"- {line(f)}" for f in group]
    lines += ["", f"{DIGEST_PREFIX}{digest(r)} -->"]
    return "\n".join(lines) + "\n"
