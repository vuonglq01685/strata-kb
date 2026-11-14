"""testdeploy — is a story's published code on the test environment, and which
files did it change. GitHub REST only (compare, search, PR files); no clone."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote

from strata_kb import ghapp, ghrest, planparents, testenv, ticket, ticketfetch
from strata_kb.errors import KbError
from strata_kb.federation import load_federation
from strata_kb.hub import HubHandle
from strata_kb.testenv import TestEnv

_DEPLOYED = {"identical", "ahead"}
_PER_PAGE = 100
_MAX_PAGES = 10  # shortcut: GitHub search caps at 1000 hits; 10 pages of 100
Api = Callable[..., Any]


def story_repos(hub: HubHandle, story: str) -> dict[str, list[str]]:
    """Dev repo id -> ids of the child tickets it implements; an unsplit story
    maps its target repo to the story itself."""
    _, ticket_id = ticketfetch.split_ref(story)
    _, doc, l3 = ticketfetch.find(hub, story)
    text = ticketfetch.source_text(ticketfetch.read_section(l3, doc, ticket_id))
    rows = planparents.children(text, ticket_id) if planparents.is_parent(text) else []
    if not rows:
        repo = ticket.target_repo(text)
        if not repo:
            raise KbError(f"{ticket_id} names no target repo")
        return {repo: [ticket_id]}
    own = planparents._own_fix(text, ticket_id)  # a parent bug's own fix row
    out: dict[str, list[str]] = {}
    for row in [*([own] if own else []), *rows]:
        if not row.repo:
            raise KbError(f"{row.child} in the split of {ticket_id} names no repo")
        out.setdefault(row.repo, []).append(row.child)
    return out


def deployed(
    hub: HubHandle, env: TestEnv, story: str, *, api: Api = ghrest.api, root: Path
) -> list[str]:
    """Empty = every repo of the story runs a commit that has the published one;
    else one reason per repo."""
    repos = story_repos(hub, story)
    published = {r.meta.repo_id: r.meta for r in load_federation(hub.federation_dir)}
    declared = {a.repo for a in env.apps}
    checked = {a.repo for a in env.apps if a.version_check}
    running = testenv.app_commits(env) if checked & repos.keys() else {}
    reasons: list[str] = []
    for repo in repos:
        meta = published.get(repo)
        if repo not in declared:  # a different reason: a human cannot override it
            reasons.append(f"{repo}: not in test-env apps")
        elif repo not in running:
            reasons.append(f"{repo}: no version_check")
        elif not (meta and meta.source_commit and meta.source_url):
            reasons.append(f"{repo}: not published")
        else:
            reasons += _compare(api, root, repo, meta, running[repo])
    return reasons


def _compare(api: Api, root: Path, repo: str, meta: Any, env_commit: str) -> list[str]:
    slug = ghapp.repo_full_from_url(meta.source_url)
    path = f"repos/{slug}/compare/{meta.source_commit}...{env_commit}"
    status = _answer(api(root, "GET", path), path).get("status")
    if status in _DEPLOYED:
        return []
    return [
        f"{repo}: env at {env_commit}, publish at {meta.source_commit} not deployed yet"
    ]


def _answer(value: Any, path: str) -> Any:
    if value is None:
        raise KbError(f"GitHub returned nothing for GET {path}")
    return value


def _paged(api: Api, root: Path, path: str, key: str | None = None) -> list[Any]:
    """Every item of a paginated GET (`key` names the list inside the answer)."""
    sep = "&" if "?" in path else "?"
    items: list[Any] = []
    for page in range(1, _MAX_PAGES + 1):
        url = f"{path}{sep}per_page={_PER_PAGE}&page={page}"
        got = _answer(api(root, "GET", url), url)
        got = got[key] if key else got
        items += got
        if len(got) < _PER_PAGE:
            break
    return items


def changed_files(
    hub: HubHandle, story: str, *, api: Api = ghrest.api, root: Path
) -> dict[str, list[str]]:
    """Child id -> files of its merged PRs (found by the child id in the PR)."""
    published = {r.meta.repo_id: r.meta for r in load_federation(hub.federation_dir)}
    out: dict[str, list[str]] = {}
    for repo, children in story_repos(hub, story).items():
        meta = published.get(repo)
        if not (meta and meta.source_url):
            raise KbError(f"{repo}: not published")
        slug = ghapp.repo_full_from_url(meta.source_url)
        for child in children:
            query = quote(f'repo:{slug} is:pr is:merged "{child}"', safe="")
            files: list[str] = []
            for item in _paged(api, root, f"search/issues?q={query}", "items"):
                for f in _paged(
                    api, root, f"repos/{slug}/pulls/{item['number']}/files"
                ):
                    if f["filename"] not in files:
                        files.append(f["filename"])
            out[child] = files
    return out
