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


def save(doc_dir: Path, rec: L3Fix) -> None:
    """Nothing tracked means no file: its presence is what gates."""
    path = doc_dir / FILE_NAME
    if rec.baseline or rec.sections:
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
    (and for files gone from disk); with the switch on, track `units` afresh."""
    rec = load(doc_dir) or L3Fix()

    def gone(file: str) -> bool:
        return file in stems or not (doc_dir / f"{file}.raw.md").exists()

    baseline = {k: v for k, v in rec.baseline.items() if not gone(v.file)}
    sections = [e for e in rec.sections if not gone(e.file)]
    if switch_on:
        baseline.update(units)
    save(doc_dir, L3Fix(baseline=baseline, sections=sections))


def blocked(rec: L3Fix, digests: dict[str, str]) -> list[tuple[str, str]]:
    """(section id, reason) for every tracked id whose L3 is not as recorded."""
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
    return out


def blocked_ids(kb_dir: Path, doc_id: str) -> list[tuple[str, str]]:
    rec = load(kb_dir / doc_id)
    if rec is None:
        return []
    return blocked(rec, slices.current_digests(kb_dir, doc_id))
