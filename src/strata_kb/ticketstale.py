"""Scan every ticket and mission for citations the hub has moved since they
were pinned.

`kb ticket lint` checks citations when a PR touches a ticket. A ticket that
merged last month is never looked at again, though the hub keeps
publishing. `kb ticket stale` walks them all, and `kb-doctor.yml` runs it on
a schedule and keeps one issue up to date.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import ValidationError

from strata_kb import gitio, kbcontext, missionnext, models
from strata_kb.resolve import ResolvedRef, resolve_refs

# `_parse_section` / `_id_lines` are private to ticketcheck: reusing them keeps
# the id-reading rules in one place instead of copying the skip rules here.
from strata_kb.ticketcheck import (
    HEADING,
    NEW_RE,
    SERVICES_HEADING,
    DocLoadError,
    _id_lines,
    _parse_section,
    grounded_entries,
    load_from_hub,
)

if TYPE_CHECKING:
    from strata_kb.hub import HubHandle

DEFAULT_DIRS = ("tickets", "missions")

KB_CONTEXT = "kb-context"
ARCHITECTURE = "architecture"
BASELINE_MISSING = "baseline not on hub"
# Narrower than ticketcheck.ID_RE: only the ids a `-code` section can carry.
_ARCH_ID_RE = re.compile(r"\b(?:svc|db|api|int|cmd)\.[A-Za-z0-9._-]+")
_MIN_REV_LEN = 7


@dataclass
class StaleRef:
    citation: str
    status: str  # "stale" | "broken"
    reason: str
    kind: str = KB_CONTEXT  # "kb-context" | "architecture"


@dataclass
class StaleFile:
    path: str
    refs: list[StaleRef] = field(default_factory=list)


def _files(paths: Iterable[Path]) -> list[Path]:
    found: set[Path] = set()
    for path in paths:
        if path.is_dir():
            found.update(p for p in path.rglob("*.md") if p.is_file())
        elif path.is_file():
            found.add(path)
    return sorted(found)


def _kb_context_refs(text: str, hub: HubHandle) -> list[StaleRef]:
    """Stale or broken refs of the file's kb-context block. A file without a
    block, or whose block does not parse, yields nothing: `kb ticket lint` is
    the gate that reports those, and a scheduled sweep that failed on a
    half-written draft would hide every real finding."""
    try:
        ctx = kbcontext.parse(text)
    except kbcontext.KBContextError:
        return []
    try:
        results = resolve_refs(hub, ctx)
    except gitio.GitError as exc:
        return [StaleRef(ctx.version, "broken", str(exc))]
    return [
        StaleRef(r.citation, r.status, r.reason)
        for r in results
        if r.status in ("stale", "broken")
    ]


def scan(paths: Iterable[Path], hub: HubHandle) -> list[StaleFile]:
    """Files whose kb-context block cites something stale or broken, or whose
    cited architecture sections moved since the `-code` baseline. The two
    checks are independent: a file with no kb-context block still gets the
    architecture check."""
    findings: list[StaleFile] = []
    for path in _files(paths):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        refs = _kb_context_refs(text, hub) + architecture_refs(path, text, hub)
        if refs:
            findings.append(StaleFile(path.as_posix(), refs))
    return findings


def _grounded_code_entry(text: str) -> tuple[str | None, str, str] | None:
    """`(repo, doc, rev)` of the first parseable `- Grounded on:` line, its
    `-code` entry preferred (the way `missionnext.grounded_doc` picks it)."""
    for line in text.splitlines():
        entries = grounded_entries(line)
        if entries:
            return next((e for e in entries if e[1].endswith("-code")), entries[0])
    return None


def cited_ids(text: str) -> list[str]:
    """Architecture section ids the file cites, in order, once each. A
    mission cites `svc.*` in `## Services & order`; a ticket cites every kind
    in `## Technical grounding`. Lines are read the way `kb ticket check`
    reads them (`_id_lines` skips `Files:` / `Grounded on:` and blanks
    healthcheck values); a `db.<table>.<column>` cites the `db.<table>`
    section. A line carrying `[NEW]` / `[NEW: …]` proposes the id, so it has
    nothing to drift from."""
    mission_section = _parse_section(text, SERVICES_HEADING)
    section = mission_section or _parse_section(text, HEADING)
    ids: dict[str, None] = {}
    if section is None:
        return []
    for _, line in _id_lines(section):
        if NEW_RE.search(line):
            continue
        for raw in _ARCH_ID_RE.findall(line):
            sid = raw.rstrip(".")
            if sid.startswith("db.") and sid.count(".") >= 2:
                sid = sid.rsplit(".", 1)[0]
            if mission_section is None or sid.startswith("svc."):
                ids[sid] = None
    return list(ids)


def _same_revision(pinned: str, published: str) -> bool:
    # Prefix match in either direction, but only when both are long enough to
    # mean a commit; anything shorter must match exactly.
    a, b = pinned.lower(), published.lower()
    if len(a) >= _MIN_REV_LEN and len(b) >= _MIN_REV_LEN:
        return a.startswith(b) or b.startswith(a)
    return a == b


def _holder(hub: HubHandle, repo: str | None, doc: str) -> str | None:
    """The repo publishing `doc`, resolved as `ticketcheck.load_from_hub`
    does: the qualifier when given, else the unique holder (None if none or
    several)."""
    from strata_kb.federation import load_federation

    if repo is not None:
        return repo
    holders = [
        r.meta.repo_id
        for r in load_federation(hub.federation_dir)
        if (r.kb_dir / doc / "_manifest.yaml").exists()
    ]
    return holders[0] if len(holders) == 1 else None


def _baseline_commit(git_root: Path, manifest_path: Path, rev: str) -> str | None:
    """Newest hub commit whose `manifest_path` carries `revision: rev`. The
    hub may sit in a subdirectory of its git repo, so the path is made
    relative to the git root, as `resolve` does."""
    rel = manifest_path.resolve().relative_to(git_root).as_posix()
    for commit in gitio.log_commits(git_root, rel):
        text = gitio.read_at(git_root, commit, manifest_path)
        try:
            manifest = models.Manifest.model_validate(yaml.safe_load(text or "") or {})
        except (yaml.YAMLError, ValidationError):
            continue
        if manifest.revision and _same_revision(rev, manifest.revision):
            return commit
    return None


def _delivered(
    path: Path, text: str, hub: HubHandle, repo: str | None, doc: str
) -> bool:
    """True when the story (a ticket) or every story of the backlog (a
    mission) is done in the Dev repo's `-svc` history. Delivering a story
    changes the `-code` sections it cites, so drift there is expected, not a
    finding. No `-svc` on the hub (or no unique holder): nothing is known, so
    nothing is skipped."""
    try:
        svc = load_from_hub(hub.federation_dir, repo, missionnext.svc_doc_id(doc))
    except DocLoadError:
        return False
    if svc is None:
        return False
    done = missionnext.done_ids_from_history(svc.read_group("history"))
    if _parse_section(text, SERVICES_HEADING) is None:
        return path.stem in done
    backlog = {s.us_id for s in missionnext.parse_mission(text)[1]}
    return bool(backlog) and backlog <= done


def drift_refs(
    hub: HubHandle, repo: str | None, doc: str, rev: str, ids: list[str]
) -> list[ResolvedRef] | None:
    """The cited sections of `doc` as they stood at the hub commit that
    published revision `rev`, every status included (`ok` too). None when the
    doc has no unique holder or no hub commit carries `rev`. `gitio.GitError`
    propagates."""
    holder = _holder(hub, repo, doc)
    if holder is None:
        return None
    commit = _baseline_commit(
        gitio.git_root(hub.root),
        hub.federation_dir / holder / doc / "_manifest.yaml",
        rev,
    )
    if commit is None:
        return None
    ctx = kbcontext.KBContext(
        version=commit,
        refs=[
            kbcontext.KBRef(repo_id=holder, doc_id=doc, section_id=id_) for id_ in ids
        ],
    )
    return resolve_refs(hub, ctx)


def architecture_refs(path: Path, text: str, hub: HubHandle) -> list[StaleRef]:
    """Cited architecture sections that changed (`stale`) or vanished
    (`broken`) in the `-code` document since the revision the file is
    grounded on. Only cited sections are compared, so a dev merge touching
    nothing the file used yields nothing. `path` is unused today; it keeps the
    signature parallel to the other per-file checks."""
    entry = _grounded_code_entry(text)
    ids = cited_ids(text) if entry else []
    if entry is None or not ids:
        return []
    repo, doc, rev = entry
    if _delivered(path, text, hub, repo, doc):
        return []
    citation = f"{doc} @ {rev}"

    def finding(status: str, reason: str) -> list[StaleRef]:
        return [StaleRef(citation, status, reason, kind=ARCHITECTURE)]

    try:
        holder = _holder(hub, repo, doc)
        if holder is None:
            return finding(
                "broken",
                f"{doc} has no unique holder in the federation — qualify it: "
                f"`Grounded on: <repo-id>:{doc} @ {rev}`",
            )
        hub_root = gitio.git_root(hub.root)
        commit = _baseline_commit(
            hub_root, hub.federation_dir / holder / doc / "_manifest.yaml", rev
        )
        if commit is None:
            return finding("stale", BASELINE_MISSING)
        ctx = kbcontext.KBContext(
            version=commit,
            refs=[
                kbcontext.KBRef(repo_id=holder, doc_id=doc, section_id=id_)
                for id_ in ids
            ],
        )
        return [
            StaleRef(r.citation, r.status, r.reason, kind=ARCHITECTURE)
            for r in resolve_refs(hub, ctx)
            if r.status in ("stale", "broken")
        ]
    except gitio.GitError as exc:
        return finding("broken", str(exc))


def exit_code(findings: list[StaleFile]) -> int:
    """0 when everything is current, 2 when only staleness was found (as
    `kb resolve` does), 1 when any citation is broken."""
    statuses = {ref.status for f in findings for ref in f.refs}
    if "broken" in statuses:
        return 1
    return 2 if statuses else 0


def render_markdown(findings: list[StaleFile]) -> str:
    """The issue body `kb-doctor.yml` keeps up to date."""
    if not findings:
        return "Every ticket and mission cites current hub content.\n"
    total = sum(len(f.refs) for f in findings)
    lines = [
        f"{total} citation(s) in {len(findings)} file(s) no longer match the hub.",
        "",
        "A **stale** citation still resolves, but the cited content changed after "
        "it was pinned: review the amendment (`kb diff <doc> --against <pin>`), "
        "then re-pin with `kb context new`. A **broken** one no longer resolves. "
        "An **architecture** finding means a service, table, route or command "
        "the file cites changed in the `-code` document after the revision it "
        "is grounded on: re-ground it with `sa-ticket-ground`. Architecture "
        "drift on a mission under delivery is expected when its own stories change "
        "the cited services: re-ground it when the change was not planned.",
        "",
        "| File | Kind | Citation | Status | Reason |",
        "| --- | --- | --- | --- | --- |",
    ]
    for f in findings:
        for ref in f.refs:
            reason = ref.reason.replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| `{f.path}` | {ref.kind} | {ref.citation} | {ref.status} | {reason} |"
            )
    return "\n".join(lines) + "\n"


def to_json(findings: list[StaleFile]) -> list[dict]:
    return [{"path": f.path, "refs": [vars(ref) for ref in f.refs]} for f in findings]
