"""`kb report fetch` engine — a Dev or BA reads a tester's published test report
(`<story>.R<n>` section of a `<repo>-test` document) from the hub, restored to
report shape with one provenance line under the H1."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from strata_kb import gitio, kinds, models, query, testflow, ticketcheck
from strata_kb.errors import KbError
from strata_kb.federation import load_federation
from strata_kb.hub import HubHandle
from strata_kb.planingest import ASSET_REF_RE, ASSETS_DIR
from strata_kb.planstatus import safe_name


class ReportFetchError(KbError):
    """No such report on the hub, or an unsafe story id."""


def _check_story(story: str) -> None:
    if not safe_name(story):
        raise ReportFetchError(
            f"'{story}' is not a story id — use letters, digits, '.', '_' or '-'"
        )


def _round_re(story: str) -> re.Pattern[str]:
    return re.compile(rf"{re.escape(story)}\.R([1-9]\d*)")


@dataclass(frozen=True)
class _Holder:
    repo: str
    doc_id: str
    folder: Path
    doc: ticketcheck.LoadedDoc
    sec: models.SectionEntry


def _holders(hub: HubHandle, story: str) -> dict[int, _Holder]:
    """Round -> the `-test` doc entry publishing it (first one wins)."""
    pat = _round_re(story)
    out: dict[int, _Holder] = {}
    for fed in load_federation(hub.federation_dir):
        for entry in sorted(fed.index.docs, key=lambda d: d.id):
            if not kinds.is_test_doc(entry.title, entry.tags):
                continue
            folder = query.doc_dir(fed.kb_dir, entry.id)
            if folder is None:
                continue
            try:
                doc = ticketcheck.load_doc_dir(folder, entry.id)
            except ticketcheck.DocLoadError:
                continue
            for sec in doc.manifest.sections:
                if m := pat.fullmatch(sec.id):
                    out.setdefault(
                        int(m[1]), _Holder(fed.meta.repo_id, entry.id, folder, doc, sec)
                    )
    return out


def rounds(hub: HubHandle, story: str) -> list[int]:
    """Published rounds of `story`, ascending."""
    _check_story(story)
    return sorted(_holders(hub, story))


def _pick(hub: HubHandle, story: str, round_: int | None) -> tuple[int, _Holder]:
    """`(round, holder)` of the wanted round (the latest by default)."""
    _check_story(story)
    held = _holders(hub, story)
    if not held:
        raise ReportFetchError(
            f"no test report for {story} on the hub — ask the Tester to run kb publish"
        )
    n = max(held) if round_ is None else round_
    if n not in held:
        names = ", ".join(f"R{r}" for r in sorted(held))
        raise ReportFetchError(
            f"R{n} is not published for {story} — published rounds: {names}"
        )
    return n, held[n]


def _render(story: str, n: int, h: _Holder, hub: HubHandle) -> str:
    text = testflow._section_text(h.doc, h.sec)
    if text is None:
        raise ReportFetchError(
            f"{h.doc_id} lists {story}.R{n} but its text cannot be read"
        )
    try:
        rev = gitio.head_commit(hub.root)[:7]
    except gitio.GitError as exc:
        raise ReportFetchError(str(exc)) from exc
    heading, _, body = text.partition("\n")
    provenance = (
        f"> Fetched from hub: {h.repo}:{h.doc_id} §{story}.R{n} @ {rev} — do not edit."
    )
    return f"{heading}\n\n{provenance}\n\n{body.strip(chr(10))}\n"


def render(hub: HubHandle, story: str, round_: int | None = None) -> tuple[int, str]:
    """`(round, markdown)`: the report as the Tester wrote it, with a
    `> Fetched from hub:` line under the H1."""
    n, h = _pick(hub, story, round_)
    return n, _render(story, n, h, hub)


def assets_of(hub: HubHandle, story: str, round_: int) -> tuple[list[Path], list[str]]:
    """`(found, missing)` for the assets the report references: files under
    the `-test` doc's `assets/`, and the names of those not on disk (diverted
    to the object store) or symlinked. A symlinked `assets/`, or one resolving
    outside the hub, holds nothing."""
    n, h = _pick(hub, story, round_)
    names = dict.fromkeys(ASSET_REF_RE.findall(_render(story, n, h, hub)))
    folder = h.folder / ASSETS_DIR
    if folder.is_symlink() or not folder.resolve().is_relative_to(hub.root.resolve()):
        return [], list(names)
    found = [
        folder / n
        for n in names
        if (folder / n).is_file() and not (folder / n).is_symlink()
    ]
    return found, [n for n in names if folder / n not in found]
