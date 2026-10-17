"""`kb ticket fetch` engine — a Dev given only a ticket id reads the ticket
from the hub. The hub holds it as a section of a published `*-plan` document
(see `planingest`); this finds that section and restores the ticket's source
shape: H1, one provenance line, the L3 body with its headings promoted back."""

from __future__ import annotations

from pathlib import Path

from strata_kb import gitio, query
from strata_kb.errors import KbError
from strata_kb.hub import HubHandle
from strata_kb.mdutils import slice_section
from strata_kb.planingest import ASSET_REF_RE, ASSETS_DIR, promote_headings
from strata_kb.planstatus import plan_docs, safe_name


class TicketFetchError(KbError):
    """The ticket is not on the hub, or several repos publish the same id."""


class TicketNotOnHub(TicketFetchError):
    """No published `*-plan` document lists the ticket (the one case a caller
    may treat as "gone"; every other `TicketFetchError` is a real problem)."""


def split_ref(ticket_ref: str) -> tuple[str | None, str]:
    """`<repo>:<id>` -> (repo, id); a bare `<id>` -> (None, id). An id that
    is not a plain name (path separators, `..`, empty) is refused."""
    repo, sep, ticket_id = ticket_ref.strip().rpartition(":")
    if not sep:
        repo, ticket_id = "", ticket_ref.strip()
    if not safe_name(ticket_id):
        raise TicketFetchError(
            f"'{ticket_id}' is not a ticket id — use letters, digits, '.', '_' or '-'"
        )
    return repo or None, ticket_id


def find(hub: HubHandle, ticket_ref: str) -> tuple[str, str, Path]:
    """`(repo_id, doc_id, l3_file)` of the one `*-plan` document that lists
    section `<id>`."""

    repo, ticket_id = split_ref(ticket_ref)
    holders: list[tuple[str, str, Path]] = []
    # plan_docs skips unreadable documents and symlinked folders.
    for fed, manifest in plan_docs(hub, repo):
        section = next((s for s in manifest.sections if s.id == ticket_id), None)
        folder = query.doc_dir(fed.kb_dir, manifest.id)
        if section is not None and folder is not None:
            if not safe_name(section.file):
                raise TicketFetchError(
                    f"{manifest.id} on the hub lists {ticket_id} in file "
                    f"'{section.file}', which is not a plain file name — refusing to read it"
                )
            holders.append(
                (fed.meta.repo_id, manifest.id, folder / f"{section.file}.raw.md")
            )
    if not holders:
        raise TicketNotOnHub(
            f"{ticket_id} is not on the hub — ask the BA to run kb publish, "
            "or pass the ticket file / paste it"
        )
    if len(holders) > 1:
        names = ", ".join(sorted(f"{r}:{d}" for r, d, _ in holders))
        raise TicketFetchError(
            f"{ticket_id} is published by several repos ({names}) — "
            f"qualify it as <repo>:{ticket_id}"
        )
    return holders[0]


def read_section(l3: Path, doc: str, ticket_id: str) -> str:
    """The `## <id> <title>` slice of the ticket's L3 group file."""
    try:
        section = slice_section(l3.read_text(encoding="utf-8"), ticket_id)
    except (OSError, UnicodeDecodeError) as exc:
        # Name the file, not its path: an MCP client must not see the hub's disk layout.
        # OSError's str() repeats the path, its strerror does not.
        detail = exc.strerror if isinstance(exc, OSError) and exc.strerror else exc
        raise TicketFetchError(f"could not read {doc}/{l3.name} ({detail})") from exc
    if section is None:
        raise TicketFetchError(
            f"{doc} lists {ticket_id} but {l3.name} has no such section"
        )
    return section


def render(hub: HubHandle, ticket_ref: str) -> str:
    """The ticket as the BA wrote it, minus `## Definition of Ready` and
    `## Review record` (plan-ingest drops them: being on the hub means DoR
    passed)."""
    repo, doc, l3 = find(hub, ticket_ref)
    _, ticket_id = split_ref(ticket_ref)
    section = read_section(l3, doc, ticket_id)
    heading, _, body = section.partition("\n")
    title = heading.removeprefix(f"## {ticket_id}").strip()
    try:
        rev = gitio.head_commit(hub.root)
    except gitio.GitError as exc:
        raise TicketFetchError(str(exc)) from exc
    provenance = (
        f"> Fetched from hub: {repo}:{doc} §{ticket_id} @ {rev} "
        "— do not edit; amend in the BA repo."
    )
    return f"# {title}\n\n{provenance}\n\n{promote_headings(body.strip(chr(10)))}\n"


def missions(hub: HubHandle) -> dict[str, str]:
    """Every mission the hub's plans publish, by id, as `render` restores it.
    A mission that cannot be read is left out: callers use this for advice
    (`kb ticket check`'s related-rows warning), never for a verdict."""
    from strata_kb.mission import MISSION_ID_RE

    out: dict[str, str] = {}
    for fed, manifest in plan_docs(hub, None):
        for section in manifest.sections:
            if section.id in out or not MISSION_ID_RE.match(section.id):
                continue
            try:
                out[section.id] = render(hub, f"{fed.meta.repo_id}:{section.id}")
            except TicketFetchError:
                continue
    return out


def split_assets(hub: HubHandle, ticket_ref: str) -> tuple[list[Path], list[str]]:
    """`(found, missing)` for the assets the fetched text references: files
    under the plan document's `assets/`, and the names of those not on disk
    (diverted to the object store) or that are symlinks. A symlinked
    `assets/` folder, or one resolving outside the hub, holds nothing."""
    folder = find(hub, ticket_ref)[2].parent / ASSETS_DIR
    names = dict.fromkeys(ASSET_REF_RE.findall(render(hub, ticket_ref)))
    if folder.is_symlink() or not folder.resolve().is_relative_to(hub.root.resolve()):
        return [], list(names)
    found = [
        folder / n
        for n in names
        if (folder / n).is_file() and not (folder / n).is_symlink()
    ]
    return found, [n for n in names if folder / n not in found]


def assets_of(hub: HubHandle, ticket_ref: str) -> list[Path]:
    """The files under the plan document's `assets/` that the fetched text
    references (see `split_assets`)."""
    return split_assets(hub, ticket_ref)[0]
