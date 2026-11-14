"""testdeploy — is a story's published code on the test environment, and which
files did it change. GitHub REST only (compare, search, PR files); no clone."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from strata_kb import ghapp, ghrest, planparents, testenv, ticket, ticketfetch
from strata_kb.errors import KbError
from strata_kb.federation import load_federation
from strata_kb.hub import HubHandle
from strata_kb.testenv import TestEnv

_DEPLOYED = {"identical", "ahead"}
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
    out: dict[str, list[str]] = {}
    for row in rows:
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
    checked = {a.repo for a in env.apps if a.version_check}
    running = testenv.app_commits(env) if checked & repos.keys() else {}
    reasons: list[str] = []
    for repo in repos:
        meta = published.get(repo)
        if repo not in running:
            reasons.append(f"{repo}: no version_check")
        elif not (meta and meta.source_commit and meta.source_url):
            reasons.append(f"{repo}: not published")
        else:
            reasons += _compare(api, root, repo, meta, running[repo])
    return reasons


def _compare(api: Api, root: Path, repo: str, meta: Any, env_commit: str) -> list[str]:
    try:
        slug = ghapp.repo_full_from_url(meta.source_url)
        status = api(
            root, "GET", f"repos/{slug}/compare/{meta.source_commit}...{env_commit}"
        ).get("status")
    except KbError as exc:
        return [f"{repo}: cannot compare commits ({exc})"]
    if status in _DEPLOYED:
        return []
    return [
        f"{repo}: env at {env_commit}, publish at {meta.source_commit} not deployed yet"
    ]


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
            found = api(
                root,
                "GET",
                f'search/issues?q=repo:{slug}+is:pr+is:merged+"{child}"',
            )
            files: list[str] = []
            for item in found.get("items", []):
                for f in api(root, "GET", f"repos/{slug}/pulls/{item['number']}/files"):
                    if f["filename"] not in files:
                        files.append(f["filename"])
            out[child] = files
    return out
