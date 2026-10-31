"""L3 slices of a document and their digests: what `_l3check.yaml` and
`_l3fix.yaml` both compare against. Kept apart so neither imports the other's
module."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from strata_kb import models, quality
from strata_kb.mdutils import heading_occurrences, slice_section


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by: str
    at: str
    l3_sha256: str


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
