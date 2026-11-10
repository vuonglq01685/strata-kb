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
_SHAPE_ERRORS = (AttributeError, TypeError, KeyError)  # an unexpected response shape
_Counted = tuple[set[str], bool]  # (required contexts, code-owner review on)
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
        except _SHAPE_ERRORS:
            self.refuse(f"could not read {what}: unexpected response")
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
    doc = yaml.safe_load(text)
    jobs = doc.get("jobs") if isinstance(doc, dict) else None
    if not isinstance(jobs, dict):
        raise ValueError("unexpected response: no `jobs` mapping")
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


def _bypass_why(detail: Any) -> str | None:
    """Why this identity can bypass the ruleset; None = it cannot."""
    if detail is None:
        return "not readable, 404"
    if not isinstance(detail, dict):
        raise ValueError("unexpected response")
    can = detail.get("current_user_can_bypass")
    if can is not None:
        return None if can == "never" else f"current_user_can_bypass={can}"
    actors = detail.get("bypass_actors")
    if not isinstance(actors, list):
        return "cannot tell who can bypass"
    return "bypass_actors is not empty" if actors else None


def _count_rulesets(
    g: _Guard, api: Callable, root: Path, slug: str, rules: Any, notes: list[str]
) -> _Counted:
    """Contexts and code-owner review from rulesets this identity cannot bypass."""
    if not isinstance(rules, list):
        raise ValueError("unexpected response")
    by_id: dict[Any, list[dict]] = {}
    for rule in rules:
        by_id.setdefault(rule.get("ruleset_id"), []).append(rule)
    contexts: set[str] = set()
    owner = False
    for rid, group in by_id.items():
        path = f"repos/{slug}/rulesets/{rid}"
        detail = g(
            f"ruleset {rid}", lambda p=path: _get(api, root, p, none_on_404=True)
        )
        if detail is _FAIL:
            continue
        why = g(f"ruleset {rid}", lambda d=detail: _bypass_why(d))
        if why is _FAIL:
            continue
        if why:
            name = detail.get("name", rid) if isinstance(detail, dict) else rid
            notes.append(f"ruleset {name}: {why}")
            continue
        contexts |= _ruleset_contexts(group)
        owner = owner or _ruleset_code_owner(group)
    return contexts, owner


def _count_classic(classic: dict, admin: bool, notes: list[str]) -> _Counted:
    """Classic protection counts only for an admin with enforce_admins on and
    no review-bypass allowance; a non-admin cannot read the review settings."""
    if not admin:
        # shortcut: a non-admin sees `protection.enabled`; any enabled classic
        # protection is unverifiable, so it counts for nothing.
        if classic.get("enabled"):
            notes.append("classic protection: cannot be verified without a ruleset")
        return set(), False
    if not classic:
        return set(), False
    reviews = classic.get("required_pull_request_reviews") or {}
    allow = reviews.get("bypass_pull_request_allowances") or {}
    if not (classic.get("enforce_admins") or {}).get("enabled"):
        notes.append("classic protection: enforce_admins is off")
    elif any(allow.get(k) for k in ("users", "teams", "apps")):
        notes.append("classic protection: bypass_pull_request_allowances is not empty")
    else:
        contexts = _classic_contexts(classic.get("required_status_checks") or {})
        return contexts, bool(reviews.get("require_code_owner_reviews"))
    return set(), False


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
        if not isinstance(data, dict):
            raise ValueError("unexpected response")
        return data if admin else data.get("protection") or {}

    classic = g(f"the branch protection of {branch}", read_classic)
    if rules is not _FAIL and classic is not _FAIL:
        notes: list[str] = []
        counted = g(
            f"the rulesets of {branch}",
            lambda: _count_rulesets(g, api, root, slug, rules, notes),
        )
        by_classic = g(
            f"the branch protection of {branch}",
            lambda: _count_classic(classic, admin, notes),
        )
        if counted is not _FAIL and by_classic is not _FAIL:
            contexts = counted[0] | by_classic[0]
            owner = counted[1] or by_classic[1]
            where = (slug, branch, kind)
            _check_protection(g, api, root, where, contexts, owner, notes)
    _check_codeowners(g, api, root, slug, branch)
    return g.out


def _required_jobs(
    g: _Guard, api: Callable, root: Path, slug: str, branch: str, kind: str
) -> list[str]:
    jobs = list(REQUIRED_JOBS.get(kind, ()))
    if kind != "dev":
        return jobs
    text = g(KB_TEST_WORKFLOW, lambda: _file(api, root, slug, KB_TEST_WORKFLOW, branch))
    if text is _FAIL:
        return []
    if text is None:  # first task is dev-test-workflow: pr-lint alone suffices
        return jobs
    names = g(KB_TEST_WORKFLOW, lambda: _job_names(text))
    return [] if names is _FAIL else jobs + [n for n in names if n not in jobs]


def _check_protection(
    g: _Guard,
    api: Callable,
    root: Path,
    where: tuple[str, str, str],
    contexts: set[str],
    owner: bool,
    notes: list[str],
) -> None:
    slug, branch, kind = where
    # What did not count and why, so the owner sees the real cause.
    why = (
        f" in protection this identity cannot bypass ({'; '.join(notes)})"
        if notes
        else ""
    )
    for job in _required_jobs(g, api, root, slug, branch, kind):
        if not _is_required(job, contexts):
            g.refuse(f"required check '{job}' is not required on {branch}{why}")
    if not owner:
        g.refuse(f"code-owner review is not required on {branch}{why}")


def _check_codeowners(
    g: _Guard, api: Callable, root: Path, slug: str, branch: str
) -> None:
    path = initcmd.CODEOWNERS_PATH
    text = g(path, lambda: _file(api, root, slug, path, branch))
    if text is _FAIL:
        return
    if text is None:
        g.refuse(f"{path} does not exist on {branch}")
        return
    lines = [ln for ln in (x.strip() for x in text.splitlines()) if ln]
    rules = [ln for ln in lines if not ln.startswith("#")]
    if not rules:
        g.refuse(f"{path} has no owner rule on {branch}")
    elif any(initcmd.CODEOWNERS_PLACEHOLDER in ln for ln in rules):
        g.refuse(f"{path} still has the {initcmd.CODEOWNERS_PLACEHOLDER} placeholder")
