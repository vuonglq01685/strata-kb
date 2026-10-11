"""Checks on kb-context citations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from strata_kb import gitio, kbcontext
from strata_kb.doctor.issues import Issue
from strata_kb.resolve import ResolvedRef, resolve_refs

if TYPE_CHECKING:
    from strata_kb.hub import HubHandle


def check_context(
    text: str,
    hub: HubHandle,
    *,
    stale_level: Literal["error", "warning"] = "warning",
) -> tuple[list[Issue], list[ResolvedRef]]:
    try:
        ctx = kbcontext.parse(text)
    except kbcontext.KBContextError as exc:
        return [Issue("error", str(exc))], []
    try:
        results = resolve_refs(hub, ctx)
    except gitio.GitError as exc:
        return [Issue("error", str(exc))], []

    issues: list[Issue] = []
    for r in results:
        if r.status == "broken":
            issues.append(Issue("error", f"{r.ref}: {r.reason}"))
        elif r.status == "stale":
            # Unconditional — applies whether `stale_level` promoted this to
            # an error or left it a warning, so both phrasings name the same
            # fix. Mirrors `render_resolved`'s own remedy (resolve.py), which
            # names the same `kb diff` command; re-pinning is offered first
            # since it is the fix the BA usually wants once amendment is
            # confirmed, not just a way to inspect it.
            remedy = (
                "re-pin with the current hub commit, or run `kb diff "
                f"{r.ref.doc_id} --against {r.pinned_rev}` to review the "
                "amendment first"
            )
            issues.append(
                Issue(stale_level, f"{r.ref}: {r.reason} — {remedy}", "stale-ref")
            )
    return issues, results
