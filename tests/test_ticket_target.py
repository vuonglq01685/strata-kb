from __future__ import annotations

from strata_kb import ticket

GROUND = "- Grounded on: payments-api:payments-api-code @ c12b24f"


def _t(header: str = "", body: str = "") -> str:
    return f"# T-1 — x\n> Revision: 1\n{header}\n## Summary\n{body}\n"


def test_header_wins_over_grounded_on():
    text = _t("> Target repo: web-app", GROUND)
    assert ticket.target_repo(text) == "web-app"


def test_qualified_grounded_on_gives_repo():
    assert ticket.target_repo(_t(body=GROUND)) == "payments-api"


def test_unqualified_grounded_on_resolved_by_unique_holder():
    text = _t(body="- Grounded on: payments-api-code @ c12b24f")
    assert ticket.target_repo(text, lambda d: ["payments-api"]) == "payments-api"
    assert ticket.target_repo(text, lambda d: ["a", "b"]) is None
    assert ticket.target_repo(text) is None


def test_svc_entry_skipped_for_code_entry():
    text = _t(body="- Grounded on: a:a-svc @ c12b24f, b:b-code @ c12b24f")
    assert ticket.target_repo(text) == "b"


def test_target_header_only_in_header_block():
    fenced = _t("```\n> Target repo: x\n```")
    below = _t(body="> Target repo: x")
    assert ticket.target_header(fenced) is None
    assert ticket.target_header(below) is None
    assert ticket.target_header(_t("> Target repo: x")) == "x"


def test_no_target_information():
    assert ticket.target_repo(_t()) is None
