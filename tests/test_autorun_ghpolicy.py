"""Merge policy C check: a fake `api` keyed by path stands in for `gh api`."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from strata_kb import ghrest, gitio
from strata_kb.autorun import ghpolicy
from strata_kb.ghio import GHError

pytestmark = pytest.mark.real_ghpolicy

SLUG = "o/r"
B = "main"
CODEOWNERS = "# owners\n/.github/ @alice\n"


def _file(text: str) -> dict:
    return {"content": base64.b64encode(text.encode()).decode(), "encoding": "base64"}


def _rules(contexts=("lint",), owner=True, ruleset_id=7) -> list[dict]:
    return [
        {
            "type": "required_status_checks",
            "ruleset_id": ruleset_id,
            "parameters": {
                "required_status_checks": [{"context": c} for c in contexts]
            },
        },
        {
            "type": "pull_request",
            "ruleset_id": ruleset_id,
            "parameters": {"require_code_owner_review": owner},
        },
    ]


def _routes(admin=False, rules=None, protection=None, **extra) -> dict:
    r = {
        f"repos/{SLUG}": {"permissions": {"admin": admin, "push": True}},
        f"repos/{SLUG}/rules/branches/{B}": _rules() if rules is None else rules,
        f"repos/{SLUG}/contents/.github/CODEOWNERS?ref={B}": _file(CODEOWNERS),
        f"repos/{SLUG}/rulesets/7": {"bypass_actors": []},
    }
    if protection is not None:
        key = f"repos/{SLUG}/branches/{B}" + ("/protection" if admin else "")
        r[key] = protection
    r.update(extra)
    return r


@pytest.fixture(autouse=True)
def _origin(monkeypatch):
    monkeypatch.setattr(ghrest, "origin_slug", lambda root: ("github.com", SLUG))
    monkeypatch.setattr(gitio, "default_branch", lambda root: B)


def _run(routes: dict, kind="ba") -> list[str]:
    def api(root, method, path, body=None):
        v = routes.get(path)
        if isinstance(v, Exception):
            raise v
        if v is None:
            raise GHError("gh api failed: gh: Not Found (HTTP 404)")
        return v

    return ghpolicy.refusals(Path("."), kind, api=api)


def test_policy_ok_nonadmin_ruleset():
    assert _run(_routes()) == []


def test_policy_ok_admin_no_bypass():
    assert _run(_routes(admin=True)) == []


def test_policy_ok_classic_enforce_admins():
    prot = {
        "required_status_checks": {"contexts": ["lint"]},
        "required_pull_request_reviews": {"require_code_owner_reviews": True},
        "enforce_admins": {"enabled": True},
    }
    assert _run(_routes(admin=True, rules=[], protection=prot)) == []


def test_admin_with_bypass_actor_refused():
    routes = _routes(
        admin=True, **{f"repos/{SLUG}/rulesets/7": {"bypass_actors": [{"actor_id": 5}]}}
    )
    (msg,) = _run(routes)
    assert "an admin can bypass the protection on main" in msg
    assert 'see "Merge policy" in the BA guide' in msg


def test_missing_required_job_refused():
    (msg,) = _run(_routes(rules=_rules(contexts=("other",))), kind="dev")
    assert "'pr-lint'" in msg and "in the Dev guide" in msg


def test_kb_test_jobs_required_once_present():
    wf = "jobs:\n  unit:\n    runs-on: x\n  lint-all:\n    name: Lint all\n"
    path = f"repos/{SLUG}/contents/.github/workflows/kb-test.yml?ref={B}"
    ctx = ("pr-lint", "unit (3.12)")  # matrix suffix still counts
    routes = _routes(rules=_rules(contexts=ctx), **{path: _file(wf)})
    (msg,) = _run(routes, kind="dev")
    assert "'Lint all'" in msg
    ok = _routes(rules=_rules(contexts=(*ctx, "Lint all")), **{path: _file(wf)})
    assert _run(ok, kind="dev") == []


def test_codeowners_missing_refused():
    routes = _routes()
    del routes[f"repos/{SLUG}/contents/.github/CODEOWNERS?ref={B}"]
    (msg,) = _run(routes)
    assert "CODEOWNERS does not exist" in msg


def test_codeowners_placeholder_refused():
    path = f"repos/{SLUG}/contents/.github/CODEOWNERS?ref={B}"
    (msg,) = _run(_routes(**{path: _file("/x @OWNER\n")}))
    assert "@OWNER" in msg
    # a comment that mentions the placeholder is not a placeholder line
    assert _run(_routes(**{path: _file("# set @OWNER\n/x @alice\n")})) == []


def test_code_owner_review_off_refused():
    (msg,) = _run(_routes(rules=_rules(owner=False)))
    assert "code-owner review is not required" in msg


def test_api_error_fails_closed():
    routes = _routes(**{f"repos/{SLUG}/rules/branches/{B}": GHError("boom")})
    out = _run(routes)
    assert len(out) == 1 and "could not read the rules on main: boom" in out[0]
    assert _run({f"repos/{SLUG}": GHError("gh not found")})[0].startswith(
        "could not read the repository"
    )


def test_no_permissions_block_refused():
    routes = _routes(**{f"repos/{SLUG}": {"name": "r"}})
    assert any("could not read token permissions" in m for m in _run(routes))


def test_refusal_lists_every_missing_piece():
    prot = {"required_status_checks": {"contexts": []}}
    routes = _routes(rules=[], protection=prot)
    del routes[f"repos/{SLUG}/contents/.github/CODEOWNERS?ref={B}"]
    out = _run(routes)
    assert len(set(out)) >= 3
