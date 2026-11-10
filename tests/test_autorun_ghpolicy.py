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
    if not admin:  # the real body: 200 for every branch, `protection` always there
        body = {
            "enabled": False,
            "required_status_checks": {"contexts": [], "checks": []},
        }
        if protection is not None:
            body = {"enabled": True, **protection}
        r[f"repos/{SLUG}/branches/{B}"] = {"name": B, "protection": body}
    elif protection is not None:
        r[f"repos/{SLUG}/branches/{B}/protection"] = protection
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
    out = _run(routes)
    assert any("ruleset 7: bypass_actors is not empty" in m for m in out)
    assert all('see "Merge policy" in the BA guide' in m for m in out)


def test_case_a_empty_bypass_ruleset_without_checks_refused():
    # checks + review sit in classic protection without enforce_admins
    prot = {
        "required_status_checks": {"contexts": ["lint"]},
        "required_pull_request_reviews": {"require_code_owner_reviews": True},
        "enforce_admins": {"enabled": False},
    }
    rules = [{"type": "deletion", "ruleset_id": 7}]
    out = _run(_routes(admin=True, rules=rules, protection=prot))
    assert any("enforce_admins is off" in m for m in out)
    assert any("'lint' is not required" in m for m in out)
    assert any("code-owner review is not required" in m for m in out)


def test_case_b_enforce_admins_only_with_bypassable_ruleset_refused():
    prot = {"enforce_admins": {"enabled": True}}
    routes = _routes(
        admin=True,
        protection=prot,
        **{
            f"repos/{SLUG}/rulesets/7": {
                "bypass_actors": [{"actor_type": "RepositoryRole", "actor_id": 5}]
            }
        },
    )
    out = _run(routes)
    assert any("bypass_actors is not empty" in m for m in out)
    assert any("'lint' is not required" in m for m in out)
    assert any("code-owner review is not required" in m for m in out)


def test_nonadmin_bypassable_ruleset_refused():
    routes = _routes(
        **{
            f"repos/{SLUG}/rulesets/7": {
                "name": "p",
                "current_user_can_bypass": "always",
            }
        }
    )
    out = _run(routes)
    assert any("(ruleset p: current_user_can_bypass=always)" in m for m in out)
    assert any("'lint' is not required" in m for m in out)


def test_can_bypass_never_beats_bypass_actors():
    detail = {"current_user_can_bypass": "never", "bypass_actors": [{"actor_id": 1}]}
    assert _run(_routes(**{f"repos/{SLUG}/rulesets/7": detail})) == []


def test_ruleset_404_counts_for_nothing():
    routes = _routes()
    del routes[f"repos/{SLUG}/rulesets/7"]
    out = _run(routes)
    assert any("not readable, 404" in m for m in out)
    assert any("'lint' is not required" in m for m in out)


def test_admin_classic_review_bypass_allowance_refused():
    prot = {
        "required_status_checks": {"contexts": ["lint"]},
        "required_pull_request_reviews": {
            "require_code_owner_reviews": True,
            "bypass_pull_request_allowances": {"users": [{"login": "x"}]},
        },
        "enforce_admins": {"enabled": True},
    }
    out = _run(_routes(admin=True, rules=[], protection=prot))
    assert any("bypass_pull_request_allowances" in m for m in out)


def test_nonadmin_classic_only_says_use_a_ruleset():
    prot = {"required_status_checks": {"contexts": ["lint"]}}
    out = _run(_routes(rules=[], protection=prot))
    assert any(
        "classic protection: cannot be verified without a ruleset" in m for m in out
    )


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


def test_repo_404_is_a_refusal():
    (msg,) = _run({})
    assert msg.startswith("could not read the repository")


def test_contents_decode_error_is_a_refusal():
    path = f"repos/{SLUG}/contents/.github/CODEOWNERS?ref={B}"
    (msg,) = _run(_routes(**{path: {"content": "!!!notbase64", "encoding": "base64"}}))
    assert "could not read .github/CODEOWNERS" in msg


@pytest.mark.parametrize("body", ["", "# only a comment\n\n"])
def test_codeowners_without_a_rule_refused(body):
    path = f"repos/{SLUG}/contents/.github/CODEOWNERS?ref={B}"
    (msg,) = _run(_routes(**{path: _file(body)}))
    assert "has no owner rule" in msg


KB_TEST = f"repos/{SLUG}/contents/.github/workflows/kb-test.yml?ref={B}"


@pytest.mark.parametrize(
    ("overrides", "kind", "needle"),
    [
        ({f"repos/{SLUG}/rules/branches/{B}": {"message": "x"}}, "ba", "the rulesets"),
        ({f"repos/{SLUG}/rules/branches/{B}": ["x"]}, "ba", "the rulesets"),
        ({f"repos/{SLUG}/rulesets/7": ["x"]}, "ba", "ruleset 7"),
        ({KB_TEST: _file("- a\n- b\n")}, "dev", "kb-test.yml"),
        ({KB_TEST: _file("jobs: [a, b]\n")}, "dev", "kb-test.yml"),
        ({KB_TEST: _file("just text\n")}, "dev", "kb-test.yml"),
        ({f"repos/{SLUG}": ["x"]}, "ba", "token permissions"),
    ],
)
def test_unexpected_shapes_are_refusals_not_crashes(overrides, kind, needle):
    routes = _routes(rules=_rules(contexts=("lint", "pr-lint")), **overrides)
    out = _run(routes, kind=kind)
    assert out and any(needle in m for m in out)


def test_nonadmin_ruleset_with_unprotected_branch_body_ok():
    routes = _routes()
    assert routes[f"repos/{SLUG}/branches/{B}"]["protection"]["enabled"] is False
    assert _run(routes) == []


def test_admin_full_classic_plus_deletion_only_bypassable_ruleset_ok():
    prot = {
        "required_status_checks": {"contexts": ["lint"]},
        "required_pull_request_reviews": {"require_code_owner_reviews": True},
        "enforce_admins": {"enabled": True},
    }
    routes = _routes(
        admin=True,
        rules=[{"type": "deletion", "ruleset_id": 7}],
        protection=prot,
        **{f"repos/{SLUG}/rulesets/7": {"bypass_actors": [{"actor_id": 5}]}},
    )
    assert _run(routes) == []


def test_missing_piece_names_the_non_counted_sources():
    prot = {
        "required_status_checks": {"contexts": ["lint"]},
        "enforce_admins": {"enabled": False},
    }
    routes = _routes(
        admin=True,
        protection=prot,
        **{f"repos/{SLUG}/rulesets/7": {"name": "p", "bypass_actors": [{"id": 1}]}},
    )
    lint = next(m for m in _run(routes) if "'lint'" in m)
    assert "ruleset p: bypass_actors is not empty" in lint
    assert "classic protection: enforce_admins is off" in lint
    assert lint.endswith('see "Merge policy" in the BA guide')


@pytest.mark.parametrize(
    "prot",
    [
        {"enforce_admins": True},
        {
            "enforce_admins": {"enabled": True},
            "required_status_checks": {"checks": ["x"]},
        },
        {"required_pull_request_reviews": ["x"]},
    ],
)
def test_odd_classic_shapes_are_refusals_not_crashes(prot):
    out = _run(_routes(admin=True, protection=prot))
    assert any("could not read the branch protection of main" in m for m in out)
