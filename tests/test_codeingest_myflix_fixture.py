"""End-to-end acceptance: a myflix-shaped repo run through `core.run`; every
question the structural-coverage spec set out to answer has a cited row."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("tree_sitter_language_pack")

from strata_kb.codeingest import core
from strata_kb.codeingest.extractors import _coverage
from strata_kb.lintcore import table_rows

FIXTURE = Path(__file__).parent / "fixtures" / "codeingest-myflix"
API = "apps/api/src"


@pytest.fixture(scope="module")
def run_result(tmp_path_factory):
    root = tmp_path_factory.mktemp("myflix")
    shutil.copytree(FIXTURE, root, dirs_exist_ok=True)
    for cmd in (["init", "-q"], ["add", "-A"]):
        subprocess.run(["git", *cmd], cwd=root, check=True)
    opts = core.CodeIngestOptions(
        repo_root=root, kb_dir=root / ".kb", doc_id="myflix", repo_id="myflix"
    )
    report = core.run(opts)
    return root / ".kb" / "myflix", report


def read(doc: Path, group: str, level: str = "") -> str:
    return (doc / f"{group}{level}.md").read_text(encoding="utf-8")


def block(text: str, heading_id: str) -> str:
    """Body of one `## <id> ...` section."""
    start = text.index(f"## {heading_id} ")
    nxt = text.find("\n## ", start + 1)
    return text[start : nxt if nxt != -1 else len(text)]


def rows(text: str) -> list[list[str]]:
    return table_rows(text)[1:]


def test_admin_stats_route_declared(run_result):
    doc, _ = run_result
    sec = next(
        s
        for s in read(doc, "routes").split("\n## ")
        if f"{API}/admin/admin.controller.ts" in s.split("\n")[0]
    )
    assert any(r[:2] == ["GET", "/api/admin/stats"] for r in rows(sec))


def test_playback_session_route_and_dto_fields(run_result):
    doc, _ = run_result
    l2 = read(doc, "routes")
    assert any(
        r[:2] == ["POST", "/api/playback/session"] and r[4] == "StartSessionDto"
        for r in rows(l2)
    )
    l3 = block(
        read(doc, "routes", ".raw"),
        "route.apps-api-src-playback-playback-controlle-730abe",
    )
    assert "| assetId | string | yes |" in l3
    assert "| position | number | no |" in l3


def test_playback_events_partition_pk_and_index(run_result):
    doc, _ = run_result
    sec = block(read(doc, "db"), "db.PlaybackEvent")
    assert 'Partition: RANGE ("created_at")' in sec
    assert "Primary key: id, createdAt" in sec
    assert "Indexes:" in sec
    assert sec.count("playback_events_created_at_idx") == 1
    assert "(unnamed)" not in sec


def test_pages_admin_group_and_viewer_watch(run_result):
    doc, _ = run_result
    got = {r[0]: r for r in rows(block(read(doc, "pages"), "page.apps-web"))}
    assert got["/admin"][1:] == ["apps/web/src/app/(admin)/admin/page.tsx", "(admin)"]
    assert got["/watch/[id]"][2] == "(viewer)"
    assert got["Middleware matcher: /admin/:path*"][1] == "apps/web/src/middleware.ts"


def test_partition_job_listed(run_result):
    doc, _ = run_result
    got = rows(read(doc, "jobs"))
    assert any(
        r[3] == f"{API}/maintenance/maintenance.service.ts"
        and r[2] == "MaintenanceService.createPartition"
        for r in got
    )


def test_symbols_public_error_code_and_css_token(run_result):
    doc, _ = run_result
    syms = read(doc, "symbols")
    assert ["Public", "function", f"{API}/common/decorators/index.ts"] in rows(
        block(syms, "sym.apps-api")
    )
    assert [
        "ErrorCodes.ASSET_NOT_READY",
        "member",
        "packages/shared/src/error-codes.ts",
    ] in rows(block(syms, "sym.packages-shared"))
    assert [
        "--admin-danger",
        "css-var",
        "apps/web/src/styles/tokens.css",
    ] in rows(block(syms, "sym.apps-web"))


def coverage_rows(doc: Path) -> list[list[str]]:
    return rows(block(read(doc, "structure"), "struct.coverage"))


def cover(doc: Path, area: str, scope: str) -> list[str]:
    found = [r for r in coverage_rows(doc) if r[0] == area and r[1] == scope]
    assert found, (area, scope, coverage_rows(doc))
    return found[0]


def cover_all(doc: Path, area: str, scope: str) -> list[list[str]]:
    return [r for r in coverage_rows(doc) if r[0] == area and r[1] == scope]


def test_coverage_complete_for_clean_scopes(run_result):
    doc, _ = run_result
    assert cover(doc, "routes", "apps/media")[3] == "complete"
    assert cover(doc, "pages", "apps/web")[3] == "complete"
    assert {r[3] for r in cover_all(doc, "symbols", "apps/web")} == {"complete"}
    assert cover(doc, "symbols", "apps/api")[3] == "complete"
    assert cover(doc, "symbols", "packages/shared")[3] == "complete"
    for scope in ("apps", "packages", "prisma"):
        assert cover(doc, "files", scope)[3] == "complete"
    assert {r[3] for r in cover_all(doc, "schema", ".")} == {"complete"}


def test_jobs_coverage_always_partial(run_result):
    doc, _ = run_result
    row = cover(doc, "jobs", "apps/api")
    assert row[3] == "partial" and row[4].startswith(_coverage.JOBS_DETAIL)


def test_dynamic_route_marks_api_routes_partial_and_names_site(run_result):
    doc, _ = run_result
    row = cover(doc, "routes", "apps/api")
    assert row[3] == "partial" and f"{API}/legacy.controller.ts" in row[4]


BAIT_VALUES = ("E1", "#c00", "isPublic", "v1")


def test_no_literal_values_leak_into_any_output(run_result):
    doc, _ = run_result
    for path in sorted(doc.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        for bait in BAIT_VALUES:
            assert bait not in text, (path.name, bait)
