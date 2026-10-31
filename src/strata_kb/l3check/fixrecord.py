"""`.kb/<doc>/_l3fix.yaml`: the L3 AI structure fix's baseline and fix entries,
and the gate on edits of L3 made outside `kb l3 fix apply`.

Local only (never published). The gate reads this file, not the switch.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from strata_kb import models
from strata_kb.l3check import slices

FILE_NAME = "_l3fix.yaml"

AWAITING = "ai-fix awaiting review"
EDITED = "edited outside kb l3 fix apply"
REMOVED = "removed outside kb l3 fix apply"


class BaselineUnit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str
    l3_sha256: str


class FixEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    file: str
    was: str = ""
    l3_sha256: str
    verified: bool = True
    by: str
    at: str
    changes: list[str] = Field(default_factory=list)
    confirmed: slices.Confirmation | None = None


class L3Fix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline: dict[str, BaselineUnit] = Field(default_factory=dict)
    sections: list[FixEntry] = Field(default_factory=list)


def load(doc_dir: Path) -> L3Fix | None:
    path = doc_dir / FILE_NAME
    return models.load_yaml_model(path, L3Fix) if path.exists() else None


def save(doc_dir: Path, rec: L3Fix, keep_empty: bool = False) -> None:
    """Nothing tracked means no file: its presence is what gates. `keep_empty`
    writes it anyway (confirm: deleting it would unblock untracked edits)."""
    path = doc_dir / FILE_NAME
    if rec.baseline or rec.sections or keep_empty:
        models.save_yaml_model(path, rec)
    else:
        path.unlink(missing_ok=True)


def reset_on_ingest(
    doc_dir: Path,
    stems: set[str],
    units: dict[str, BaselineUnit],
    switch_on: bool,
) -> None:
    """Re-ingest rewrote the files in `stems`: forget what was tracked for them
    (and for files gone from disk). `units` is every unit of the doc now.

    No record yet: with the switch on, baseline every unit of the doc; off,
    write nothing. Record exists (whatever the switch): baseline only the units
    of `stems`, whose L3 was just rewritten from the PDF. Never baseline a unit
    outside `stems`, or a hand edit there would clear the gate unreviewed.
    Nothing tracked afterwards: delete the file (an existing record keeps
    gating the doc, so only an empty one goes)."""
    rec = load(doc_dir)

    def gone(file: str) -> bool:
        return file in stems or not (doc_dir / f"{file}.raw.md").exists()

    kept = rec or L3Fix()
    baseline = {k: v for k, v in kept.baseline.items() if not gone(v.file)}
    sections = [e for e in kept.sections if not gone(e.file)]
    if switch_on or rec is not None:
        baseline.update(
            {k: v for k, v in units.items() if rec is None or v.file in stems}
        )
    save(doc_dir, L3Fix(baseline=baseline, sections=sections))


def blocked(rec: L3Fix, digests: dict[str, str]) -> list[tuple[str, str]]:
    """(section id, reason) for every tracked id whose L3 is not as recorded,
    then every id in `digests` that nothing tracks (a unit added by direct edit)."""
    newest = {e.id: e for e in rec.sections}  # later entry overwrites earlier
    out: list[tuple[str, str]] = []
    for sid in dict.fromkeys([*rec.baseline, *newest]):
        digest = digests.get(sid)
        entry = newest.get(sid)
        base = rec.baseline.get(sid)
        if digest is None:
            out.append((sid, REMOVED))
        elif entry is not None and entry.l3_sha256 == digest:
            if entry.confirmed is None or entry.confirmed.l3_sha256 != digest:
                out.append((sid, AWAITING))
        elif base is None or base.l3_sha256 != digest:
            out.append((sid, EDITED))
    tracked = set(rec.baseline) | set(newest)
    out += [(sid, EDITED) for sid in digests if sid not in tracked]
    return out


def blocked_ids(kb_dir: Path, doc_id: str) -> list[tuple[str, str]]:
    rec = load(kb_dir / doc_id)
    if rec is None:
        return []
    return blocked(rec, slices.current_digests(kb_dir, doc_id))


def unit_files(doc_dir: Path) -> dict[str, str]:
    """Section id -> chapter file, from the manifest (first row of a repeated id)."""
    path = doc_dir / "_manifest.yaml"
    if not path.exists():
        return {}
    manifest = models.load_yaml_model(path, models.Manifest)
    files: dict[str, str] = {}
    for sec in manifest.sections:
        files.setdefault(sec.id, sec.file)
    return files


def confirm(
    doc_dir: Path, ids: list[str], by: str, at: str, digests: dict[str, str]
) -> None:
    """A human accepts `ids` as they are now. An AI fix gets its newest entry
    confirmed; an outside edit gets a new human entry holding the current
    digest; an outside removal drops the id from baseline and entries. Ids
    that nothing blocks are left alone."""
    rec = load(doc_dir)
    if rec is None:
        return
    reasons = dict(blocked(rec, digests))
    files = unit_files(doc_dir)
    baseline = dict(rec.baseline)
    sections = list(rec.sections)
    for sid in ids:
        reason = reasons.get(sid)
        if reason == REMOVED:
            baseline.pop(sid, None)
            sections = [e for e in sections if e.id != sid]
            continue
        if reason not in (AWAITING, EDITED):
            continue
        digest = digests[sid]
        proof = slices.Confirmation(by=by, at=at, l3_sha256=digest)
        if reason == AWAITING:
            at_last = max(i for i, e in enumerate(sections) if e.id == sid)
            sections[at_last] = sections[at_last].model_copy(
                update={"confirmed": proof}
            )
            continue
        newest = next((e for e in reversed(sections) if e.id == sid), None)
        known = newest or baseline.get(sid)
        sections.append(
            FixEntry(
                id=sid,
                file=known.file if known else files.get(sid, ""),
                l3_sha256=digest,
                by="human",
                at=at,
                confirmed=proof,
            )
        )
    save(doc_dir, L3Fix(baseline=baseline, sections=sections), keep_empty=True)
