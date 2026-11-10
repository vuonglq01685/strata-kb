"""Merge policy C: `kb auto run` may start only when GitHub would not let the
agent merge without the kind's required checks and a code-owner review, nor
bypass the protection. Every read failure is a refusal (fail closed)."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from strata_kb import ghrest, gitio, initcmd
from strata_kb.errors import KbError

REQUIRED_JOBS = {"dev": ("pr-lint",), "ba": ("lint",)}
KB_TEST_WORKFLOW = ".github/workflows/kb-test.yml"
_GUIDE = {"dev": "Dev", "ba": "BA"}
_READ_ERRORS = (KbError, OSError, ValueError, yaml.YAMLError)
_FAIL = object()  # a guarded read failed (its refusal is already recorded)


class _Guard:
    """Runs reads; a failure becomes a refusal, never a silent pass."""

    def __init__(self, kind: str) -> None:
        self.out: list[str] = []
        self.tail = f'see "Merge policy" in the {_GUIDE.get(kind, "Dev")} guide'

    def refuse(self, text: str) -> None:
        self.out.append(f"{text}; {self.tail}")

    def __call__(self, what: str, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except _READ_ERRORS as exc:
            self.refuse(f"could not read {what}: {exc}")
            return _FAIL


def _is_404(exc: Exception) -> bool:
    return "HTTP 404" in str(exc)


def _get(api: Callable, root: Path, path: str, *, none_on_404: bool = False) -> Any:
    try:
        return api(root, "GET", path)
    except KbError as exc:
        if none_on_404 and _is_404(exc):
            return None
        raise


def _file(api: Callable, root: Path, slug: str, path: str, branch: str) -> str | None:
    """Text of `path` on `branch`; None when it does not exist."""
    data = _get(
        api, root, f"repos/{slug}/contents/{path}?ref={branch}", none_on_404=True
    )
    if data is None:
        return None
    try:
        return base64.b64decode(data["content"]).decode("utf-8")
    except (KeyError, TypeError, binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError(f"unexpected contents of {path}: {exc}") from None


def _job_names(text: str) -> list[str]:
    jobs = (yaml.safe_load(text) or {}).get("jobs") or {}
    return [str((job or {}).get("name") or key) for key, job in jobs.items()]


def _is_required(job: str, contexts: set[str]) -> bool:
    # Matrix jobs report as "<name> (<matrix values>)".
    return any(c == job or c.startswith(f"{job} (") for c in contexts)


def _classic_contexts(rsc: dict) -> set[str]:
    found = set(rsc.get("contexts") or [])
    found.update(c["context"] for c in rsc.get("checks") or [] if c.get("context"))
    return found


def _ruleset_contexts(rules: list[dict]) -> set[str]:
    return {
        c["context"]
        for r in rules
        if r.get("type") == "required_status_checks"
        for c in (r.get("parameters") or {}).get("required_status_checks") or []
        if c.get("context")
    }


def _ruleset_code_owner(rules: list[dict]) -> bool:
    return any(
        r.get("type") == "pull_request"
        and (r.get("parameters") or {}).get("require_code_owner_review")
        for r in rules
    )


def _bypassable(api, root, slug, rules, classic) -> bool:
    """Admin identity only: can an admin bypass the protection?"""
    if (classic.get("enforce_admins") or {}).get("enabled"):
        return False
    ids = {
        (r["ruleset_id"], r.get("ruleset_source_type"), r.get("ruleset_source"))
        for r in rules
        if "ruleset_id" in r
    }
    if not ids:
        return True
    for rid, source_type, source in sorted(ids, key=str):
        base = f"orgs/{source}" if source_type == "Organization" else f"repos/{slug}"
        if (_get(api, root, f"{base}/rulesets/{rid}") or {}).get("bypass_actors") != []:
            return True
    return False


def refusals(root: Path, kind: str, api: Callable = ghrest.api) -> list[str]:
    """Why GitHub does not enforce policy C on the default branch; empty = it does."""
    g = _Guard(kind)
    where = g(
        "the origin repository",
        lambda: (ghrest.origin_slug(root)[1], gitio.default_branch(root)),
    )
    if where is _FAIL:
        return g.out
    slug, branch = where
    repo = g("the repository", lambda: _get(api, root, f"repos/{slug}"))
    if repo is _FAIL:
        return g.out
    perms = repo.get("permissions") if isinstance(repo, dict) else None
    if not isinstance(perms, dict):
        g.refuse("could not read token permissions")
    admin = bool(perms and perms.get("admin"))

    rules_path = f"repos/{slug}/rules/branches/{branch}"
    rules = g(
        f"the rules on {branch}",
        lambda: _get(api, root, rules_path, none_on_404=True) or [],
    )
    prot_path = f"repos/{slug}/branches/{branch}" + ("/protection" if admin else "")

    def read_classic() -> dict:
        data = _get(api, root, prot_path, none_on_404=True) or {}
        return data if admin else data.get("protection") or {}

    classic = g(f"the branch protection of {branch}", read_classic)
    if rules is not _FAIL and classic is not _FAIL:
        _check_protection(g, api, root, (slug, branch, kind, admin), rules, classic)
    _check_codeowners(g, api, root, slug, branch)
    return g.out


def _required_jobs(g, api, root, slug, branch, kind):
    jobs = list(REQUIRED_JOBS.get(kind, ()))
    if kind != "dev":
        return jobs
    read = lambda: _file(api, root, slug, KB_TEST_WORKFLOW, branch)  # noqa: E731
    text = g(KB_TEST_WORKFLOW, read)
    if text is _FAIL:
        return []
    if text is None:  # first task is dev-test-workflow: pr-lint alone suffices
        return jobs
    names = g(KB_TEST_WORKFLOW, lambda: _job_names(text))
    return [] if names is _FAIL else jobs + [n for n in names if n not in jobs]


def _check_protection(g, api, root, ctx, rules, classic) -> None:
    slug, branch, kind, admin = ctx
    contexts = _ruleset_contexts(rules) | _classic_contexts(
        classic.get("required_status_checks") or {}
    )
    for job in _required_jobs(g, api, root, slug, branch, kind):
        if not _is_required(job, contexts):
            g.refuse(f"required check '{job}' is not required on {branch}")
    reviews = classic.get("required_pull_request_reviews") or {}
    if not (_ruleset_code_owner(rules) or reviews.get("require_code_owner_reviews")):
        g.refuse(f"code-owner review is not required on {branch}")
    if admin:
        bypass = g("the rulesets", lambda: _bypassable(api, root, slug, rules, classic))
        if bypass is True:
            g.refuse(f"an admin can bypass the protection on {branch}")


def _check_codeowners(g, api, root, slug, branch) -> None:
    path = initcmd.CODEOWNERS_PATH
    text = g(path, lambda: _file(api, root, slug, path, branch))
    if text is _FAIL:
        return
    if text is None:
        g.refuse(f"{path} does not exist on {branch}")
        return
    lines = (ln.strip() for ln in text.splitlines())
    if any(
        initcmd.CODEOWNERS_PLACEHOLDER in ln for ln in lines if not ln.startswith("#")
    ):
        g.refuse(f"{path} still has the {initcmd.CODEOWNERS_PLACEHOLDER} placeholder")
