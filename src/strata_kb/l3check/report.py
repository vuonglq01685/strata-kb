"""`.kb/<doc>/_l3check.yaml`: the L3 check's findings, and the gate on them.

summarize/build/publish refuse a doc while a flagged section is unconfirmed
(`blocked_docs`). A confirmation is bound to the section's L3 digest, so any
later edit of the section re-blocks it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from strata_kb import models
from strata_kb.l3check import fixrecord
from strata_kb.l3check.slices import (  # noqa: F401 (re-exported)
    Confirmation,
    current_digests,
    digest_slices,
    l3_slices,
)

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


def _now() -> str:
    # not review._now: review imports build, which imports this module
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def unconfirmed(check: L3Check, digests: dict[str, str]) -> list[SectionCheck]:
    return [
        s
        for s in check.sections
        if s.confirmed is None or s.confirmed.l3_sha256 != digests.get(s.id)
    ]


def blocked_docs(kb_dir: Path) -> list[tuple[str, list[str]]]:
    """Per doc, the ids that gate: unconfirmed `_l3check.yaml` sections, then ids
    that `_l3fix.yaml` blocks (an AI fix not yet confirmed, or L3 edited or
    removed outside `kb l3 fix apply`)."""
    index = models.load_yaml_model(kb_dir / "index.yaml", models.KBIndex)
    out: list[tuple[str, list[str]]] = []
    for entry in index.docs:
        ids: list[str] = []
        check = load(kb_dir / entry.id)
        if check is not None:
            ids = [s.id for s in unconfirmed(check, current_digests(kb_dir, entry.id))]
        ids += [
            sid for sid, _ in fixrecord.blocked_ids(kb_dir, entry.id) if sid not in ids
        ]
        if ids:
            out.append((entry.id, ids))
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


def confirmable(kb_dir: Path, doc_id: str) -> list[str] | None:
    """Ids a human may confirm: flagged in `_l3check.yaml`, then those that
    `_l3fix.yaml` blocks. None when neither file exists."""
    check = load(kb_dir / doc_id)
    if check is None and fixrecord.load(kb_dir / doc_id) is None:
        return None
    ids = [s.id for s in check.sections] if check is not None else []
    fix_ids = [sid for sid, _ in fixrecord.blocked_ids(kb_dir, doc_id)]
    return list(dict.fromkeys([*ids, *fix_ids]))


def confirm(
    kb_dir: Path, doc_id: str, section_ids: list[str] | None, by: str
) -> list[str]:
    """Bind a confirmation to each section's current L3 digest, in both files.
    `None` = all."""
    valid = confirmable(kb_dir, doc_id)
    if valid is None:
        raise ValueError(f"{doc_id}: no {FILE_NAME} to confirm")
    check = load(kb_dir / doc_id)
    flagged = {s.id for s in check.sections} if check is not None else set()
    wanted = valid if section_ids is None else section_ids
    unknown = [i for i in wanted if i not in valid]
    if unknown:
        raise ValueError(
            f"{doc_id}: no flagged section {', '.join(unknown)} "
            f"(flagged: {', '.join(valid)})"
        )
    digests = current_digests(kb_dir, doc_id)
    removed = {
        sid
        for sid, why in fixrecord.blocked_ids(kb_dir, doc_id)
        if why == fixrecord.REMOVED
    }
    for sid in wanted:
        # a flagged id removed outside kb l3 fix apply is dropped below, not confirmed
        if sid not in digests and sid in flagged and sid not in removed:
            raise ValueError(f"§{sid}: section not found in L3 — re-ingest {doc_id}")
    at = _now()
    if check is not None:
        sections = [
            s.model_copy(
                update={
                    "confirmed": Confirmation(by=by, at=at, l3_sha256=digests[s.id])
                }
            )
            if s.id in wanted and s.id not in removed
            else s
            for s in check.sections
            if not (s.id in wanted and s.id in removed)
        ]
        save(kb_dir / doc_id, check.model_copy(update={"sections": sections}))
    fixrecord.confirm(kb_dir / doc_id, wanted, by, at, digests)
    return [i for i in valid if i in wanted]
