"""`kb report fetch` engine — a Dev or BA reads a tester's published test report
(`<story>.R<n>` section of a `<repo>-test` document) from the hub, restored to
report shape with one provenance line under the H1."""

from __future__ import annotations

import re
from pathlib import Path

from strata_kb import gitio, query, testflow
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


def _holders(hub: HubHandle, story: str) -> dict[int, str]:
    """Round -> id of the `-test` doc publishing it."""
    pat = _round_re(story)
    out: dict[int, str] = {}
    for doc_id, doc in testflow._test_docs(hub):
        for sec in doc.manifest.sections:
            if m := pat.fullmatch(sec.id):
                out.setdefault(int(m[1]), doc_id)
    return out


def rounds(hub: HubHandle, story: str) -> list[int]:
    """Published rounds of `story`, ascending."""
    _check_story(story)
    return sorted(_holders(hub, story))


def _pick(hub: HubHandle, story: str, round_: int | None) -> tuple[int, str]:
    """`(round, doc_id)` of the wanted round (the latest by default)."""
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


def render(hub: HubHandle, story: str, round_: int | None = None) -> tuple[int, str]:
    """`(round, markdown)`: the report as the Tester wrote it, with a
    `> Fetched from hub:` line under the H1."""
    n, doc = _pick(hub, story, round_)
    text = testflow.section_text(hub, f"{story}.R{n}")
    if text is None:
        raise ReportFetchError(f"{doc} lists {story}.R{n} but its text cannot be read")
    try:
        rev = gitio.head_commit(hub.root)[:7]
    except gitio.GitError as exc:
        raise ReportFetchError(str(exc)) from exc
    repo = doc.removesuffix("-test")
    heading, _, body = text.partition("\n")
    provenance = (
        f"> Fetched from hub: {repo}:{doc} §{story}.R{n} @ {rev} — do not edit."
    )
    return n, f"{heading}\n\n{provenance}\n\n{body.strip(chr(10))}\n"


def assets_of(hub: HubHandle, story: str, round_: int) -> list[Path]:
    """Files under the `-test` doc's `assets/` that the report references.
    A symlinked `assets/`, one resolving outside the hub, or a symlinked file
    holds nothing."""
    _, doc = _pick(hub, story, round_)
    names = dict.fromkeys(ASSET_REF_RE.findall(render(hub, story, round_)[1]))
    folder = next(
        (
            f / ASSETS_DIR
            for fed in load_federation(hub.federation_dir)
            if (f := query.doc_dir(fed.kb_dir, doc)) and f.is_dir()
        ),
        None,
    )
    if (
        folder is None
        or folder.is_symlink()
        or not folder.resolve().is_relative_to(hub.root.resolve())
    ):
        return []
    return [
        folder / n
        for n in names
        if (folder / n).is_file() and not (folder / n).is_symlink()
    ]
