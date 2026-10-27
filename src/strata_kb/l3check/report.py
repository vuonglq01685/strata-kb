"""`.kb/<doc>/_l3check.yaml`: the L3 check's findings, and the gate on them.

summarize/build/publish refuse a doc while a flagged section is unconfirmed
(`blocked_docs`). A confirmation is bound to the section's L3 digest, so any
later edit of the section re-blocks it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from strata_kb import models, quality
from strata_kb.mdutils import heading_occurrences, slice_section
from strata_kb.review import _now

FILE_NAME = "_l3check.yaml"
FindingKind = Literal["fallback", "order", "content", "break", "unverifiable"]


class AgentVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["spurious", "intentional", "unsure"]
    reason: str


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: FindingKind
    page: int | None = None
    # keys used: l3, next, pdf, heading, other
    evidence: dict[str, str] = Field(default_factory=dict)
    agent: AgentVerdict | None = None


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by: str
    at: str
    l3_sha256: str


class SectionCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    l3_sha256: str
    findings: list[Finding]
    confirmed: Confirmation | None = None


class L3Check(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checked_at: str
    source_sha256: str = ""
    sections: list[SectionCheck] = Field(default_factory=list)


def load(doc_dir: Path) -> L3Check | None:
    path = doc_dir / FILE_NAME
    return models.load_yaml_model(path, L3Check) if path.exists() else None


def save(doc_dir: Path, check: L3Check) -> None:
    """No flagged sections left means no file: its presence is what gates."""
    path = doc_dir / FILE_NAME
    if check.sections:
        models.save_yaml_model(path, check)
    else:
        path.unlink(missing_ok=True)


def l3_slices(kb_dir: Path, doc_id: str) -> dict[str, list[str | None]]:
    """Section id -> its L3 slice per manifest row, in manifest order (an id may
    repeat). None where the `.raw.md` file or the slice is missing."""
    manifest_path = kb_dir / doc_id / "_manifest.yaml"
    if not manifest_path.exists():
        return {}
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    raws: dict[str, str] = {}
    out: dict[str, list[str | None]] = {}
    for sec, occ in zip(
        manifest.sections, heading_occurrences(manifest.sections), strict=True
    ):
        if sec.file not in raws:
            raw = kb_dir / doc_id / f"{sec.file}.raw.md"
            raws[sec.file] = raw.read_text(encoding="utf-8") if raw.exists() else ""
        out.setdefault(sec.id, []).append(
            slice_section(raws[sec.file], sec.id, occurrence=occ)
        )
    return out


def digest_slices(slices: dict[str, list[str | None]]) -> dict[str, str]:
    """An id repeated in the manifest digests all its slices joined, so an edit
    of any occurrence changes it. An id with a missing slice is left out."""
    return {
        sid: quality.digest("\n\n".join(p for p in pieces if p is not None))
        for sid, pieces in slices.items()
        if None not in pieces
    }


def current_digests(kb_dir: Path, doc_id: str) -> dict[str, str]:
    """Section id -> digest of its L3 slice now (what `build` compares
    `l3_sha256` against)."""
    return digest_slices(l3_slices(kb_dir, doc_id))


def unconfirmed(check: L3Check, digests: dict[str, str]) -> list[SectionCheck]:
    return [
        s
        for s in check.sections
        if s.confirmed is None or s.confirmed.l3_sha256 != digests.get(s.id)
    ]


def blocked_docs(kb_dir: Path) -> list[tuple[str, list[str]]]:
    index = models.load_yaml_model(kb_dir / "index.yaml", models.KBIndex)
    out: list[tuple[str, list[str]]] = []
    for entry in index.docs:
        check = load(kb_dir / entry.id)
        if check is None:
            continue
        pending = unconfirmed(check, current_digests(kb_dir, entry.id))
        if pending:
            out.append((entry.id, [s.id for s in pending]))
    return out


def _bare(findings: list[Finding]) -> list[Finding]:
    return [f.model_copy(update={"agent": None}) for f in findings]


def merge(previous: L3Check | None, fresh: L3Check, rechecked: set[str]) -> L3Check:
    """Previous entries outside `rechecked` stay; each fresh entry inherits the
    old confirmation and agent verdicts if nothing but the verdicts changed.
    Dropping ids gone from the manifest is the caller's job."""
    if previous is None:
        return fresh
    old = {s.id: s for s in previous.sections}
    merged: list[SectionCheck] = [s for s in previous.sections if s.id not in rechecked]
    for sec in fresh.sections:
        prev = old.get(sec.id)
        if (
            prev is not None
            and prev.l3_sha256 == sec.l3_sha256
            and _bare(prev.findings) == _bare(sec.findings)
        ):
            # fresh check output never carries agent verdicts, so keep the previous
            findings = [
                f.model_copy(update={"agent": p.agent or f.agent})
                for p, f in zip(prev.findings, sec.findings, strict=True)
            ]
            sec = sec.model_copy(
                update={"findings": findings, "confirmed": prev.confirmed}
            )
        merged.append(sec)
    return fresh.model_copy(update={"sections": merged})


def confirm(
    kb_dir: Path, doc_id: str, section_ids: list[str] | None, by: str
) -> list[str]:
    """Bind a confirmation to each section's current L3 digest. `None` = all."""
    check = load(kb_dir / doc_id)
    if check is None:
        raise ValueError(f"{doc_id}: no {FILE_NAME} to confirm")
    valid = [s.id for s in check.sections]
    wanted = valid if section_ids is None else section_ids
    unknown = [i for i in wanted if i not in valid]
    if unknown:
        raise ValueError(
            f"{doc_id}: no flagged section {', '.join(unknown)} "
            f"(flagged: {', '.join(valid)})"
        )
    digests = current_digests(kb_dir, doc_id)
    for sid in wanted:
        if sid not in digests:
            raise ValueError(f"§{sid}: section not found in L3 — re-ingest {doc_id}")
    at = _now()
    sections = [
        s.model_copy(
            update={"confirmed": Confirmation(by=by, at=at, l3_sha256=digests[s.id])}
        )
        if s.id in wanted
        else s
        for s in check.sections
    ]
    save(kb_dir / doc_id, check.model_copy(update={"sections": sections}))
    return [i for i in valid if i in wanted]
