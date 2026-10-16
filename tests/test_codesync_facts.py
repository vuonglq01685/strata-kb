from __future__ import annotations

from pathlib import Path

import pytest

from strata_kb.codeingest.hublag import BANNER_PREFIX
from strata_kb.codesync.facts import facts_for
from strata_kb.mdutils import slice_section


@pytest.fixture
def l2(code_doc: tuple[Path, str]):
    kb_dir, _ = code_doc

    def _l2(file: str, section_id: str) -> str:
        text = (kb_dir / "demo-code" / file).read_text(encoding="utf-8")
        body = slice_section(text, section_id)
        assert body is not None
        return body

    return _l2


def test_svc_facts_include_depends_on_ports_env_technology(l2):
    facts = facts_for(
        "svc.airspace-service",
        "code",
        l2("services.md", "svc.airspace-service"),
        "",
    )
    assert facts == {
        ("depends_on", "postgres"),
        ("port", "8080:8080"),
        ("env_key", "AIRSPACE_DB_URL"),
        ("env_key", "KAFKA_BROKER_URL"),
    }
    postgres = facts_for("svc.postgres", "code", l2("services.md", "svc.postgres"), "")
    assert postgres == {("port", "5432:5432"), ("technology", "PostgreSQL")}


def test_svc_facts_split_multi_value_and_strip_backticks():
    body = (
        "| Property | Value |\n| --- | --- |\n"
        "| Ports | `80:80`, 443:443 |\n"
        "| Depends on | `a`, b |\n"
        "| Technology | FastAPI, React |\n"
        "| Env keys | none |\n"
    )
    assert facts_for("svc.x", "code", body, "") == {
        ("port", "80:80"),
        ("port", "443:443"),
        ("depends_on", "a"),
        ("depends_on", "b"),
        ("technology", "FastAPI"),
        ("technology", "React"),
    }


def test_svc_facts_ignore_image_source_volumes_healthcheck(l2):
    base = l2("services.md", "svc.airspace-service")
    changed = (
        base.replace("airspace:1.0", "airspace:2.0")
        .replace("docker-compose.yml", "deploy/compose.yml")
        .replace("| Volumes | none |", "| Volumes | data |")
        .replace("curl -f http://localhost:8080/health", "wget -q localhost")
    )
    assert changed != base
    assert facts_for("svc.airspace-service", "code", changed, "") == facts_for(
        "svc.airspace-service", "code", base, ""
    )


def test_db_facts_columns_types_pk(l2):
    facts = facts_for(
        "db.restrictive_airspace", "code", l2("db.md", "db.restrictive_airspace"), ""
    )
    assert facts == {
        ("column", "id"),
        ("column", "designation"),
        ("column", "airspace_type"),
        ("column", "effective_date"),
        ("column_type", "id:BIGSERIAL PRIMARY KEY"),
        ("column_type", "designation:VARCHAR(20) NOT NULL"),
        ("column_type", "airspace_type:CHAR(1) NOT NULL"),
        ("column_type", "effective_date:DATE"),
        ("pk", "id"),
    }


def test_api_facts_routes(l2):
    facts = facts_for("api.airspace", "code", l2("api.md", "api.airspace"), "")
    assert facts == {("route", "GET /airspace"), ("route", "POST /airspace")}


def test_int_facts_env_keys(l2):
    facts = facts_for("int.kafka", "code", l2("integrations.md", "int.kafka"), "")
    assert facts == {("env_key", "KAFKA_BROKER_URL")}


def test_cmd_facts_primary_command_only(l2):
    base = l2("commands.md", "cmd.test")
    assert facts_for("cmd.test", "code", base, "") == {
        ("command", "pytest -q --cov=airspace")
    }
    other_alternatives = base.replace("pytest | pyproject.toml", "tox | tox.ini")
    assert facts_for("cmd.test", "code", other_alternatives, "") == facts_for(
        "cmd.test", "code", base, ""
    )


def test_dep_facts_frameworks_not_versions(l2):
    base = l2("deps.md", "dep.python")
    assert facts_for("dep.python", "code", base, "") == {("framework", "FastAPI")}
    bumped = base.replace(">=0.110", ">=0.115").replace("pydantic", "pydantic-core")
    assert facts_for("dep.python", "code", bumped, "") == {("framework", "FastAPI")}
    none = "**Frameworks detected:** none\n\n| Package | Constraint |\n"
    assert facts_for("dep.go", "code", none, "") == frozenset()


def test_svc_doc_text_fact_ignores_banner_and_whitespace():
    prose = "The payment   service\ncalls ledger.\n"
    bannered = f"{BANNER_PREFIX}abc123 — do not edit by hand.\n\n{prose}"
    reflowed = "The payment service calls ledger."
    ref = facts_for("svc.payment", "svc", "", prose)
    assert len(ref) == 1 and next(iter(ref))[0] == "text"
    assert facts_for("svc.payment", "svc", "", bannered) == ref
    assert facts_for("svc.payment", "svc", "", reflowed) == ref
    assert facts_for("svc.payment", "svc", "", prose + "It also calls X.") != ref
    assert facts_for("flow.checkout", "svc", "", prose) == facts_for(
        "flow.checkout", "svc", "", reflowed
    )


def test_struct_tree_and_hist_have_no_facts(l2):
    tree = l2("structure.md", "struct.tree")
    assert facts_for("struct.tree", "code", tree, "x") == frozenset()
    assert facts_for("hist.2024", "code", tree, "x") == frozenset()
    assert facts_for("hist.2024", "svc", tree, "x") == frozenset()
    assert facts_for("mystery.x", "code", tree, "x") == frozenset()
    assert facts_for("flow.x", "code", tree, "x") == frozenset()


def test_db_facts_keep_escaped_pipes_in_type_cell():
    body = (
        "| Column | Type | PK |\n| --- | --- | --- |\n"
        "| c | TEXT CHECK (a \\|\\| b) | yes |\n"
        "| d | INT |  |\n"
    )
    facts = facts_for("db.t", "code", body, "")
    assert ("column_type", "c:TEXT CHECK (a || b)") in facts
    assert ("pk", "c") in facts
    assert ("column_type", "d:INT") in facts
    changed = facts_for("db.t", "code", body.replace("a \\|\\| b", "a \\|\\| z"), "")
    assert changed != facts


def test_in_scope_lists_the_ids_whose_appearance_is_a_fact():
    from strata_kb.codesync.facts import in_scope

    for sid in ("svc.a", "db.a", "api.a", "int.a", "cmd.a", "dep.a"):
        assert in_scope(sid, "code")
    assert not any(in_scope(s, "code") for s in ("struct.tree", "hist.1", "flow.x"))
    assert in_scope("svc.a", "svc") and in_scope("flow.a", "svc")
    assert not any(in_scope(s, "svc") for s in ("db.a", "hist.1", "struct.tree"))


_ROUTE_L2 = (
    "| Method | Path | Handler | File | Request type |\n| --- | --- | --- | --- | --- |\n"
    "| get | /watch/{id} | M.watch | a.ts |  |\n"
    "| GET | /watch/:id/ | M.watch2 | a.ts |  |\n"
    "| POST | /media | M.up | a.ts |  |\n"
)
_PAGE_L2 = (
    "| Path | File | Layout/group |\n| --- | --- | --- |\n"
    "| /admin | a/page.tsx | (admin) |\n"
    "| /watch/[id] | b/page.tsx |  |\n"
    "| Middleware matcher: /admin/:path* | m.ts |  |\n"
)
_JOB_L2 = (
    "| Name | Schedule | Handler | File |\n| --- | --- | --- | --- |\n"
    "| nightly | 0 2 * * * | - | a.ts |\n"
    "| (anonymous) | 0 4 * * * | - | a.ts |\n"
    "| (dynamic) | 0 5 * * * | - | a.ts |\n"
)


def test_route_facts():
    facts = facts_for("route.x", "code", _ROUTE_L2, "")
    assert facts == {("route", "GET /watch/{}"), ("route", "POST /media")}
    changed = _ROUTE_L2.replace("/media", "/media2")
    assert facts_for("route.x", "code", changed, "") != facts


def test_page_facts():
    facts = facts_for("page.x", "code", _PAGE_L2, "")
    assert facts == {("page", "/admin"), ("page", "/watch/{}")}


def test_job_facts():
    facts = facts_for("job.x", "code", _JOB_L2, "")
    assert facts == {("job", "nightly @ 0 2 * * *")}
    moved = _JOB_L2.replace("0 2 * * *", "0 3 * * *")
    assert facts_for("job.x", "code", moved, "") != facts


def test_sym_and_files_not_in_codesync_scope():
    from strata_kb.codesync.facts import in_scope

    assert not in_scope("sym.x", "code")
    assert not in_scope("struct.files.x", "code")
    assert facts_for("sym.x", "code", _JOB_L2, "") == frozenset()
    for sid in ("route.x", "page.x", "job.x"):
        assert in_scope(sid, "code")
        assert not in_scope(sid, "svc")
