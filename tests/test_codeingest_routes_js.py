"""routes extractor core + the NestJS / Express / Next.js / Nuxt adapters."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("tree_sitter_language_pack")

from strata_kb.codeingest.extractors import _coverage, _ts, routes
from strata_kb.codeingest.types import CodeIngestOptions
from strata_kb.lintcore import table_rows


def write(root: Path, rel: str, text: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def package(root: Path, app: str, *deps: str) -> None:
    manifest = {
        "name": app.replace("/", "-") or "app",
        "dependencies": dict.fromkeys(deps, "*"),
    }
    write(
        root,
        f"{app}/package.json" if app != "." else "package.json",
        json.dumps(manifest),
    )


def nest_app(root: Path, app: str, main: str = "", files: dict[str, str] | None = None):
    package(root, app, "@nestjs/core")
    write(root, f"{app}/src/main.ts", f"async function bootstrap() {{ {main} }}\n")
    for rel, text in (files or {}).items():
        write(root, f"{app}/{rel}", text)


def run_routes(root: Path):
    opts = CodeIngestOptions(
        repo_root=root, kb_dir=root / ".kb", doc_id="d", repo_id="r"
    )
    return routes.RoutesExtractor().extract(root, opts)


def section(result, file: str):
    (found,) = [s for s in result.sections if s.title == file]
    return found


def coverage(result, area: str, scope: str, framework: str | None = None) -> str:
    rows = [
        r
        for r in result.coverage
        if r.area == area and r.scope == scope and framework in (None, r.framework)
    ]
    assert len(rows) == 1, rows
    return rows[0].status


def detail(result, scope: str) -> str:
    (row,) = [r for r in result.coverage if r.scope == scope]
    return row.detail


def rows_of(result, file: str) -> list[list[str]]:
    return table_rows(section(result, file).l2_md)[1:]


# --- NestJS -----------------------------------------------------------------


def test_nest_controller_joins_global_and_class_prefix(tmp_path):
    nest_app(
        tmp_path,
        "apps/api",
        main='app.setGlobalPrefix("api")',
        files={
            "src/admin/admin.controller.ts": """
@Controller("admin") export class AdminController {
  @Get("stats") stats() {}
  @Post("users") create(@Body() dto: CreateUserDto) {}
}
export class CreateUserDto { name!: string; note?: string }"""
        },
    )
    result = run_routes(tmp_path)
    file = "apps/api/src/admin/admin.controller.ts"
    assert table_rows(section(result, file).l2_md) == [
        ["Method", "Path", "Handler", "File", "Request type"],
        ["GET", "/api/admin/stats", "AdminController.stats", file, ""],
        ["POST", "/api/admin/users", "AdminController.create", file, "CreateUserDto"],
    ]
    sec = section(result, file)
    assert "| name | string | yes |" in sec.l3_md
    assert "| note | string | no |" in sec.l3_md
    assert sec.id.startswith("route.") and sec.group == "routes" and sec.summary
    assert coverage(result, "routes", "apps/api") == "complete"


def test_nest_all_maps_to_any_and_object_controller_path(tmp_path):
    nest_app(
        tmp_path,
        "api",
        files={
            "src/x.controller.ts": """
@Controller({ path: 'x', host: 'h' })
export class X { @All(':id') any() {} @Get() list() {} }"""
        },
    )
    result = run_routes(tmp_path)
    assert [r[:3] for r in rows_of(result, "api/src/x.controller.ts")] == [
        ["GET", "/x", "X.list"],
        ["ANY", "/x/:id", "X.any"],
    ]


def test_dynamic_path_marks_scope_partial(tmp_path):
    nest_app(
        tmp_path,
        "apps/api",
        files={
            "src/x.controller.ts": """@Controller("x")
export class X {
  @Get(`${BASE}/x`) x() {}
  @Get("ok") ok() {}
}"""
        },
    )
    result = run_routes(tmp_path)
    assert coverage(result, "routes", "apps/api") == "partial"
    assert detail(result, "apps/api") == "apps/api/src/x.controller.ts:3"
    assert [r[:2] for r in rows_of(result, "apps/api/src/x.controller.ts")] == [
        ["GET", "/x/ok"]
    ]


def test_nest_unrecognised_forms_default_to_sites(tmp_path):
    nest_app(
        tmp_path,
        "api",
        main="app.setGlobalPrefix(PREFIX); app.enableVersioning();",
        files={
            "src/a.ts": """
class Loose { @Get("a") a() {} }
@Controller(P) class Dyn { @Post("b") b() {} }
@Controller("c") class Child extends Base { @Get() c() {} }
"""
        },
    )
    result = run_routes(tmp_path)
    assert coverage(result, "routes", "api") == "partial"
    sites = detail(result, "api").split("; ")
    assert "api/src/main.ts:1" in sites  # setGlobalPrefix(PREFIX) + enableVersioning
    assert "api/src/a.ts:2" in sites  # @Get outside any controller
    assert "api/src/a.ts:3" in sites  # dynamic @Controller path
    assert "api/src/a.ts:4" in sites  # controller with a base class
    assert result.sections == []  # unknown global prefix: no path is knowable


def test_two_apps_same_controller_name_distinct_ids(tmp_path):
    body = """@Controller("admin") export class AdminController { @Get() a() {} }"""
    for app in ("apps/a", "apps/b"):
        nest_app(tmp_path, app, files={"src/admin.controller.ts": body})
    first = run_routes(tmp_path)
    ids = {s.title: s.id for s in first.sections}
    assert len(set(ids.values())) == 2
    for p in (tmp_path / "apps/b").rglob("*"):
        if p.is_file():
            p.unlink()
    second = run_routes(tmp_path)
    assert {s.title: s.id for s in second.sections} == {
        "apps/a/src/admin.controller.ts": ids["apps/a/src/admin.controller.ts"]
    }


def test_request_type_interface_and_outside_repo(tmp_path):
    nest_app(
        tmp_path,
        "api",
        files={
            "src/u.controller.ts": """
import { External } from 'lib';
@Controller("u") export class U {
  @Post() a(@Body() dto: Local) {}
  @Put() b(@Body() dto: External) {}
  @Patch() c(@Body() dto: Derived, @Body("k") k: string) {}
}
export interface Local { id: number; tag?: string }
export class Derived extends Local { x: string }
"""
        },
    )
    sec = section(run_routes(tmp_path), "api/src/u.controller.ts")
    assert "| id | number | yes |" in sec.l3_md
    assert "| tag | string | no |" in sec.l3_md
    assert sec.l3_md.count("request type declared outside the repo") == 2
    assert [r[4] for r in table_rows(sec.l2_md)[1:]] == ["Derived", "Local", "External"]


# --- Express ----------------------------------------------------------------


def test_express_router_mount_prefix(tmp_path):
    package(tmp_path, ".", "express")
    write(
        tmp_path,
        "app.js",
        """const express = require("express");
const app = express();
app.use("/v1", require("./users"));
app.get("/health", (req, res) => res.send("ok"));
app.get("env");
""",
    )
    write(
        tmp_path,
        "users.js",
        """const router = require("express").Router();
router.get("/:id", getUser);
router.route("/bulk").post(bulk).delete(purge);
module.exports = router;
""",
    )
    result = run_routes(tmp_path)
    assert coverage(result, "routes", ".") == "complete"
    assert rows_of(result, "app.js") == [["GET", "/health", "(inline)", "app.js", ""]]
    assert [r[:3] for r in rows_of(result, "users.js")] == [
        ["GET", "/v1/:id", "getUser"],
        ["DELETE", "/v1/bulk", "purge"],
        ["POST", "/v1/bulk", "bulk"],
    ]


def test_express_esm_named_import_and_nested_mount(tmp_path):
    package(tmp_path, "svc", "express")
    write(
        tmp_path,
        "svc/src/server.ts",
        """import express from "express";
import { api } from "./api";
const app = express();
app.use("/api", api);
""",
    )
    write(
        tmp_path,
        "svc/src/api.ts",
        """import { Router } from "express";
import items from "./items";
export const api = Router();
api.use("/items", items);
""",
    )
    write(
        tmp_path,
        "svc/src/items.ts",
        """import { Router } from "express";
const r = Router();
r.get("/", list);
export default r;
""",
    )
    result = run_routes(tmp_path)
    assert coverage(result, "routes", "svc") == "complete"
    assert [r[:2] for r in rows_of(result, "svc/src/items.ts")] == [
        ["GET", "/api/items"]
    ]


def test_express_unfollowable_mount_and_dynamic_path_are_sites(tmp_path):
    package(tmp_path, ".", "express")
    write(
        tmp_path,
        "app.js",
        """const express = require("express");
const app = express();
app.use("/a", makeRouter());
app.use(PREFIX, require("./x"));
app.get(PATH, h);
function register(router) { router.get("/late", h2); }
app.use(cors());
""",
    )
    write(
        tmp_path,
        "x.js",
        'const r = require("express").Router(); r.get("/x", h); module.exports = r;\n',
    )
    result = run_routes(tmp_path)
    assert coverage(result, "routes", ".") == "partial"
    assert detail(result, ".").split("; ") == [
        "app.js:3",
        "app.js:4",
        "app.js:5",
        "app.js:6",
    ]
    # x.js is mounted under a dynamic prefix: its route is not listed
    assert [s.title for s in result.sections] == []


def test_express_unmounted_router_is_listed_and_partial(tmp_path):
    package(tmp_path, ".", "express")
    write(
        tmp_path,
        "lib.js",
        'const r = require("express").Router();\nr.get("/x", h);\nmodule.exports = r;\n',
    )
    result = run_routes(tmp_path)
    assert coverage(result, "routes", ".") == "partial"
    assert detail(result, ".") == "lib.js:1"
    assert rows_of(result, "lib.js")[0][:2] == ["GET", "/x"]


# --- Next.js / Nuxt ---------------------------------------------------------


def test_next_route_handlers_and_groups(tmp_path):
    package(tmp_path, "apps/web", "next", "react")
    write(
        tmp_path,
        "apps/web/app/(admin)/api/stats/route.ts",
        "export async function GET() {}\nexport const POST = async () => {};\nexport const dynamic = 'force-dynamic';\n",
    )
    write(
        tmp_path,
        "apps/web/src/app/users/[id]/route.js",
        "export { get as GET };\nexport function DELETE() {}\n",
    )
    write(
        tmp_path,
        "apps/web/pages/api/legacy/[slug].ts",
        "export default function h() {}\n",
    )
    write(tmp_path, "apps/web/pages/api/index.ts", "export default function h() {}\n")
    write(tmp_path, "apps/web/app/page.tsx", "export default function P() {}\n")
    result = run_routes(tmp_path)
    assert coverage(result, "routes", "apps/web") == "complete"
    assert [
        r[:3] for r in rows_of(result, "apps/web/app/(admin)/api/stats/route.ts")
    ] == [
        ["GET", "/api/stats", "GET"],
        ["POST", "/api/stats", "POST"],
    ]
    assert [r[:2] for r in rows_of(result, "apps/web/src/app/users/[id]/route.js")] == [
        ["DELETE", "/users/[id]"],
        ["GET", "/users/[id]"],
    ]
    assert rows_of(result, "apps/web/pages/api/legacy/[slug].ts")[0][:2] == [
        "ANY",
        "/api/legacy/[slug]",
    ]
    assert rows_of(result, "apps/web/pages/api/index.ts")[0][:2] == ["ANY", "/api"]


def test_next_unknown_exports_and_base_path_are_sites(tmp_path):
    package(tmp_path, ".", "next")
    write(tmp_path, "app/a/route.ts", "export * from './handlers';\n")
    write(tmp_path, "app/b/route.ts", "export default function x() {}\n")
    write(tmp_path, "next.config.js", "module.exports = {\n  basePath: '/docs',\n};\n")
    result = run_routes(tmp_path)
    assert coverage(result, "routes", ".") == "partial"
    assert detail(result, ".").split("; ") == [
        "app/a/route.ts:1",
        "app/b/route.ts:1",
        "next.config.js:2",
    ]


def test_nuxt_server_routes(tmp_path):
    package(tmp_path, ".", "nuxt")
    write(
        tmp_path,
        "server/api/users/[id].get.ts",
        "export default defineEventHandler(() => 1)\n",
    )
    write(
        tmp_path,
        "server/api/users/index.post.ts",
        "export default defineEventHandler(() => 1)\n",
    )
    write(
        tmp_path, "server/api/ping.ts", "export default defineEventHandler(() => 1)\n"
    )
    write(
        tmp_path,
        "server/routes/health.ts",
        "export default defineEventHandler(() => 1)\n",
    )
    write(
        tmp_path,
        "server/routes/sitemap.xml.ts",
        "export default defineEventHandler(() => 1)\n",
    )
    write(
        tmp_path,
        "server/middleware/log.ts",
        "export default defineEventHandler(() => 1)\n",
    )
    result = run_routes(tmp_path)
    assert coverage(result, "routes", ".") == "complete"
    got = sorted((r[0], r[1]) for s in result.sections for r in table_rows(s.l2_md)[1:])
    assert got == [
        ("ANY", "/api/ping"),
        ("ANY", "/health"),
        ("ANY", "/sitemap.xml"),
        ("GET", "/api/users/[id]"),
        ("POST", "/api/users"),
    ]


# --- core -------------------------------------------------------------------


def test_framework_without_adapter_is_not_scanned(tmp_path, monkeypatch):
    package(tmp_path, ".", "express")
    write(tmp_path, "app.js", "const app = require('express')();\napp.get('/x', h);\n")
    monkeypatch.setattr(
        routes, "ADAPTERS", {k: v for k, v in routes.ADAPTERS.items() if k != "Express"}
    )
    result = run_routes(tmp_path)
    assert result.sections == []
    (row,) = result.coverage
    assert (row.area, row.scope, row.framework, row.status, row.detail) == (
        "routes",
        ".",
        "Express",
        "not scanned",
        "no adapter for Express yet",
    )


def test_without_extra_rows_are_not_scanned(tmp_path, monkeypatch):
    package(tmp_path, "a", "express", "react")
    package(tmp_path, "b", "next")
    write(
        tmp_path, "a/app.js", "const app = require('express')();\napp.get('/x', h);\n"
    )
    monkeypatch.setattr(_ts, "available", lambda: False)
    result = run_routes(tmp_path)
    assert result.sections == []
    assert [
        (r.area, r.scope, r.framework, r.status, r.detail) for r in result.coverage
    ] == [
        ("routes", "a", "Express", "not scanned", _coverage.NOT_INSTALLED),
        ("routes", "b", "Next.js", "not scanned", _coverage.NOT_INSTALLED),
    ]
    assert len(result.warnings) == 1


def test_scope_without_route_framework_gets_no_row(tmp_path):
    package(tmp_path, ".", "react", "lodash")
    write(tmp_path, "src/a.ts", "export const a = 1;\n")
    result = run_routes(tmp_path)
    assert result.coverage == [] and result.sections == [] and result.warnings == []
    assert routes.RoutesExtractor().detect(tmp_path) is False


def test_output_is_deterministic(tmp_path):
    nest_app(
        tmp_path,
        "api",
        files={
            "src/a.controller.ts": '@Controller("a") class A { @Get("z") z() {} @Get("b") b() {} }'
        },
    )
    assert run_routes(tmp_path) == run_routes(tmp_path)


def test_route_frameworks_are_the_eighteen_spec_labels():
    assert len(routes.ROUTE_FRAMEWORKS) == 18
    assert {"NestJS", "Express", "Next.js", "Nuxt", "Spring Boot", "Vapor"} <= set(
        routes.ROUTE_FRAMEWORKS
    )
    assert {"NestJS", "Express", "Next.js", "Nuxt"} <= set(routes.ADAPTERS)


# --- more edge cases --------------------------------------------------------


def test_express_local_mount_class_field_and_syntax_error(tmp_path):
    package(tmp_path, ".", "express")
    write(
        tmp_path,
        "app.ts",
        """import express, { Router } from "express";
const app = express();
const api: Router = Router();
api.get("/a", h);
app.use("/api", api);
class Server {
  private app = express();
  init() { this.app.post("/s", h); }
}
""",
    )
    write(
        tmp_path,
        "broken.js",
        'const r = require("express").Router();\nr.get("/x", ;;\n',
    )
    result = run_routes(tmp_path)
    assert coverage(result, "routes", ".") == "partial"
    assert detail(result, ".").startswith("broken.js:")
    assert [r[:2] for r in rows_of(result, "app.ts")] == [
        ["GET", "/api/a"],
        ["POST", "/s"],
    ]


def test_express_test_files_are_not_routes(tmp_path):
    package(tmp_path, ".", "express")
    write(tmp_path, "app.js", 'const app = require("express")();\napp.get("/a", h);\n')
    write(
        tmp_path,
        "app.test.js",
        'const app = require("express")();\napp.get("/t", h);\n',
    )
    result = run_routes(tmp_path)
    assert [s.title for s in result.sections] == ["app.js"]
    assert coverage(result, "routes", ".") == "complete"


def test_nest_bare_controller_and_scope_file_attribution(tmp_path):
    nest_app(
        tmp_path,
        "api",
        files={
            "src/h.controller.ts": "@Controller() class H { @Get() h() {} @Head(':x') x() {} }"
        },
    )
    # nested package without a route framework: its files do not belong to api
    write(tmp_path, "api/tools/package.json", "{}")
    write(tmp_path, "api/tools/x.ts", "@Controller('t') class T { @Get() t() {} }")
    result = run_routes(tmp_path)
    assert [r[:2] for r in rows_of(result, "api/src/h.controller.ts")] == [
        ["GET", "/"],
        ["HEAD", "/:x"],
    ]
    assert coverage(result, "routes", "api") == "complete"


# --- review round 1: nothing recognised may vanish under `complete` ----------


def all_routes(result):
    return sorted(
        (r[0], r[1]) for s in result.sections for r in table_rows(s.l2_md)[1:]
    )


def test_dirs_named_test_are_not_skipped_but_suffixes_are(tmp_path):
    nest_app(
        tmp_path,
        "api",
        files={
            "src/test/test.controller.ts": '@Controller("t") class T { @Get() a() {} }',
            "src/e2e/e2e.controller.ts": '@Controller("e") class E { @Get() a() {} }',
            "src/x.spec.ts": '@Controller("s") class S { @Get() a() {} }',
            "src/__tests__/y.ts": '@Controller("y") class Y { @Get() a() {} }',
        },
    )
    package(tmp_path, "web", "next")
    write(tmp_path, "web/app/api/test/route.ts", "export function GET() {}\n")
    write(tmp_path, "web/pages/api/test/ping.ts", "export default function h() {}\n")
    package(tmp_path, "nx", "nuxt")
    write(tmp_path, "nx/server/api/tests/run.post.ts", "export default 1\n")
    result = run_routes(tmp_path)
    assert all_routes(result) == [
        ("ANY", "/api/test/ping"),
        ("GET", "/api/test"),
        ("GET", "/e"),
        ("GET", "/t"),
        ("POST", "/api/tests/run"),
    ]


def test_express_route_chain_on_untracked_receiver_is_a_site(tmp_path):
    package(tmp_path, ".", "express")
    write(
        tmp_path,
        "r.js",
        'module.exports = (router) => {\n  router.route("/users").get(list).post(create);\n};\n',
    )
    result = run_routes(tmp_path)
    assert coverage(result, "routes", ".") == "partial"
    assert "r.js:2" in detail(result, ".")


def test_express_new_router_is_tracked(tmp_path):
    package(tmp_path, ".", "express")
    write(
        tmp_path,
        "app.js",
        'const express = require("express");\nconst app = express();\n'
        'const r = new express.Router();\nr.get("/a", h);\napp.use("/p", r);\n'
        'const q = new Router();\nq.get("/b", h);\napp.use("/q", q);\n',
    )
    result = run_routes(tmp_path)
    assert coverage(result, "routes", ".") == "complete"
    assert all_routes(result) == [("GET", "/p/a"), ("GET", "/q/b")]


def test_express_unbound_verb_call_with_non_slash_literal_is_a_site(tmp_path):
    package(tmp_path, ".", "express")
    write(
        tmp_path,
        "a.js",
        "module.exports = (router) => {\n  router.get(':id', h);\n  router.all('*', h);\n};\n",
    )
    result = run_routes(tmp_path)
    assert detail(result, ".").split("; ") == ["a.js:2", "a.js:3"]


def test_express_computed_verb_on_tracked_receiver_is_a_site(tmp_path):
    package(tmp_path, ".", "express")
    write(
        tmp_path,
        "a.js",
        'const app = require("express")();\nconst m = "get";\napp[m]("/x", h);\n',
    )
    result = run_routes(tmp_path)
    assert detail(result, ".") == "a.js:3"


def test_nest_verb_calls_namespace_and_aliased_imports_are_sites(tmp_path):
    nest_app(
        tmp_path,
        "api",
        files={
            "src/a.ts": (
                "import { applyDecorators, Get } from '@nestjs/common';\n"
                "export const Auth = () => applyDecorators(Get('all'), HttpCode(200));\n"
            ),
            "src/b.ts": (
                "import * as common from '@nestjs/common';\n"
                "@common.Controller('b') class B {\n  @common.Get('x') x() {}\n}\n"
            ),
            "src/c.ts": (
                "import { Controller, Get as HttpGet } from '@nestjs/common';\n"
                "@Controller('c') class C {\n  @HttpGet('y') y() {}\n}\n"
            ),
        },
    )
    result = run_routes(tmp_path)
    assert detail(result, "api") == "api/src/a.ts:2"
    # namespace and aliased decorator imports resolve to real routes
    assert all_routes(result) == [("GET", "/b/x"), ("GET", "/c/y")]


def test_nest_router_module_for_routes_is_a_site(tmp_path):
    nest_app(
        tmp_path,
        "api",
        files={
            "src/m.ts": "RouterModule.forRoutes([{ path: 'a', module: A }]);\n"
            "RouterModule.register([{ path: 'b', module: B }]);\n"
        },
    )
    assert detail(run_routes(tmp_path), "api").split("; ") == [
        "api/src/m.ts:1",
        "api/src/m.ts:2",
    ]


def test_nuxt_config_options_that_move_routes_are_sites(tmp_path):
    package(tmp_path, ".", "nuxt")
    write(tmp_path, "server/api/a.ts", "export default 1\n")
    write(
        tmp_path,
        "nuxt.config.ts",
        "export default defineNuxtConfig({\n  srcDir: 'src/',\n  app: { baseURL: '/x' },\n  runtimeConfig: { public: { apiBaseURL: '/y' } },\n  serverHandlers: [],\n})\n",
    )
    assert detail(run_routes(tmp_path), ".").split("; ") == [
        "nuxt.config.ts:2",
        "nuxt.config.ts:3",
        "nuxt.config.ts:4",
        "nuxt.config.ts:5",
    ]


def test_request_type_wrappers_are_unwrapped_for_field_lookup(tmp_path):
    nest_app(
        tmp_path,
        "api",
        files={
            "src/d.controller.ts": (
                '@Controller("d") class D {\n  @Post() a(@Body() x: CreateDto[]) {}\n'
                "  @Put() b(@Body() x: Partial<CreateDto>) {}\n}\n"
                "class CreateDto { name!: string }\n"
            )
        },
    )
    sec = section(run_routes(tmp_path), "api/src/d.controller.ts")
    assert [r[4] for r in table_rows(sec.l2_md)[1:]] == [
        "CreateDto[]",
        "Partial<CreateDto>",
    ]
    assert sec.l3_md.count("| name | string | yes |") == 1  # CreateDto[]
    assert sec.l3_md.count("| name | string | no |") == 1  # Partial<...>
    assert "outside the repo" not in sec.l3_md


# --- review round 2 ---------------------------------------------------------


def test_express_untracked_call_and_array_args_are_sites(tmp_path):
    package(tmp_path, ".", "express")
    write(
        tmp_path,
        "a.js",
        "module.exports = (router) => {\n"
        '  router.get("/users", asyncHandler(list));\n'
        '  router.post("/login", passport.authenticate("local"), h);\n'
        '  router.put("/x", [auth], h);\n'
        '  router["get"]("/y", h);\n'
        '  cache.get("k", { ttl: 1 });\n'
        "};\n",
    )
    assert detail(run_routes(tmp_path), ".").split("; ") == [
        "a.js:2",
        "a.js:3",
        "a.js:4",
        "a.js:5",
    ]


def test_nuxt_skips_test_suffix_files_only(tmp_path):
    package(tmp_path, ".", "nuxt")
    write(tmp_path, "server/api/a.ts", "export default 1\n")
    write(tmp_path, "server/api/a.test.ts", "export default 1\n")
    write(tmp_path, "server/api/b.spec.ts", "export default 1\n")
    write(tmp_path, "server/api/tests/c.ts", "export default 1\n")
    assert all_routes(run_routes(tmp_path)) == [
        ("ANY", "/api/a"),
        ("ANY", "/api/tests/c"),
    ]


def test_outermost_type_wrapper_wins():
    from strata_kb.codeingest.extractors import _routes_jsutil as u

    assert u._unwrap_type("Required<Partial<X>>") == ("X", True)
    assert u._unwrap_type("Partial<Required<X>>") == ("X", False)
    assert u._unwrap_type("Partial<X>[]") == ("X", False)


# --- review round 3 ---------------------------------------------------------


def test_computed_verb_only_file_is_scanned(tmp_path):
    package(tmp_path, ".", "express")
    write(tmp_path, "a.js", 'module.exports = (r) => {\n  r["get"]("/x", h);\n};\n')
    write(
        tmp_path, "b.ts", "export default (r: any) => {\n  r[\"post\"]('/y', h);\n};\n"
    )
    write(tmp_path, "c.js", 'module.exports = (i18n) => i18n["t"]("a", b);\n')
    app = tmp_path / "d.js"
    app.write_text(
        'const app = require("express")();\nconst m = "get";\napp[m]("/z", h);\napp["get"]("/w", h);\n'
    )
    assert detail(run_routes(tmp_path), ".").split("; ") == [
        "a.js:2",
        "b.ts:2",
        "d.js:3",
        "d.js:4",
    ]


def test_nest_reexported_and_const_aliased_verbs_resolve_to_routes(tmp_path):
    nest_app(
        tmp_path,
        "api",
        files={
            "src/lib.ts": "export { Get as HttpGet } from '@nestjs/common';\n",
            "src/a.controller.ts": (
                "import { HttpGet } from './lib';\n"
                "import { Controller, Get, HttpCode, ApiTags } from '@nestjs/common';\n"
                "const G = Get;\n"
                "@Controller('a') class A {\n"
                "  @HttpGet('x') x() {}\n"
                "  @G('y') y() {}\n"
                "  @HttpGet() z() {}\n"
                "  @HttpCode(200) @ApiTags('t') @Get('ok') ok() {}\n"
                "}\n"
            ),
        },
    )
    result = run_routes(tmp_path)
    assert coverage(result, "routes", "api") == "complete"
    assert all_routes(result) == [
        ("GET", "/a"),
        ("GET", "/a/ok"),
        ("GET", "/a/x"),
        ("GET", "/a/y"),
    ]


def test_nest_custom_metadata_decorators_do_not_make_a_scope_partial(tmp_path):
    nest_app(
        tmp_path,
        "api",
        main="app.setGlobalPrefix('api');",
        files={
            "src/auth/public.decorator.ts": (
                "import { SetMetadata } from '@nestjs/common';\n"
                "export const Public = () => SetMetadata('isPublic', true);\n"
            ),
            "src/auth/roles.decorator.ts": (
                "import { SetMetadata } from '@nestjs/common';\n"
                "export const Roles = (...r: string[]) => SetMetadata('roles', r);\n"
            ),
            "src/auth/index.ts": (
                "export * from './public.decorator';\n"
                "export { Roles } from './roles.decorator';\n"
            ),
            "src/movies.controller.ts": (
                "import { Controller, Get, Post, HttpCode } from '@nestjs/common';\n"
                "import { Public, Roles } from './auth';\n"
                "@Controller('movies')\n"
                "export class MoviesController {\n"
                "  @Public() @Get() list() {}\n"
                "  @Roles('admin') @Post() create() {}\n"
                "  @Roles(Role.Admin) @HttpCode(204) @Post('x') x() {}\n"
                "  @ResponseMessage('ok') @Get('y') y() {}\n"
                "  @Auth() @Permissions('x') @Transactional() @Get('z') z() {}\n"
                "  @MessagePattern('m') @GrpcMethod('S', 'M') @Get('w') w() {}\n"
                "}\n"
            ),
        },
    )
    result = run_routes(tmp_path)
    assert coverage(result, "routes", "api") == "complete"
    assert len(all_routes(result)) == 6


def test_nest_alias_with_identifier_argument_is_a_site(tmp_path):
    nest_app(
        tmp_path,
        "api",
        files={
            "src/lib.ts": "export { Get as HttpGet } from '@nestjs/common';\n",
            "src/paths.ts": "export const P = 'x';\n",
            "src/a.controller.ts": (
                "import { HttpGet } from './lib';\n"
                "import { P } from './paths';\n"
                "import { Controller, Get } from '@nestjs/common';\n"
                "const G = Get;\n"
                "@Controller('a') class A {\n"
                "  @HttpGet(P) x() {}\n"
                "  @G(R.y) y() {}\n"
                "  @Get('ok') ok() {}\n"
                "}\n"
            ),
        },
    )
    result = run_routes(tmp_path)
    assert detail(result, "api").split("; ") == [
        "api/src/a.controller.ts:6",
        "api/src/a.controller.ts:7",
    ]
    assert all_routes(result) == [("GET", "/a/ok")]


def test_nest_alias_resolves_through_barrel_hops_namespace_and_default(tmp_path):
    nest_app(
        tmp_path,
        "api",
        files={
            "src/lib.ts": "export { Get as HttpGet, Post as HttpPost } from '@nestjs/common';\n",
            "src/mid.ts": "export * from './lib';\n",
            "src/top/index.ts": "export { HttpGet as Fetch } from '../mid';\n",
            "src/dflt.ts": "import { Delete } from '@nestjs/common';\nexport default Delete;\n",
            "src/a.controller.ts": (
                "import { Controller } from '@nestjs/common';\n"
                "import { Fetch } from './top';\n"
                "import { HttpPost } from './mid';\n"
                "import Remove from './dflt';\n"
                "import * as dec from './mid';\n"
                "@Controller('a') class A {\n"
                "  @Fetch('f') f() {}\n"
                "  @HttpPost('p') p() {}\n"
                "  @Remove('d') d() {}\n"
                "  @dec.HttpGet('n') n() {}\n"
                "}\n"
            ),
        },
    )
    result = run_routes(tmp_path)
    assert coverage(result, "routes", "api") == "complete"
    assert all_routes(result) == [
        ("DELETE", "/a/d"),
        ("GET", "/a/f"),
        ("GET", "/a/n"),
        ("POST", "/a/p"),
    ]


def test_nest_unresolvable_name_from_reexporting_file_is_a_site(tmp_path):
    nest_app(
        tmp_path,
        "api",
        files={
            "src/lib.ts": (
                "export * from '@nestjs/common';\nexport * from '../../elsewhere';\n"
            ),
            "src/a.controller.ts": (
                "import { Controller } from '@nestjs/common';\n"
                "import { Mystery } from './lib';\n"
                "@Controller('a') class A {\n  @Mystery('x') x() {}\n}\n"
            ),
        },
    )
    result = run_routes(tmp_path)
    assert coverage(result, "routes", "api") == "partial"
    assert detail(result, "api") == "api/src/a.controller.ts:4"


def test_nest_alias_chain_longer_than_cap_is_a_site(tmp_path):
    files = {"src/h0.ts": "export { Get as Deep } from '@nestjs/common';\n"}
    for i in range(1, 8):
        files[f"src/h{i}.ts"] = f"export * from './h{i - 1}';\n"
    files["src/a.controller.ts"] = (
        "import { Controller } from '@nestjs/common';\n"
        "import { Deep } from './h7';\n"
        "@Controller('a') class A {\n  @Deep('x') x() {}\n}\n"
    )
    nest_app(tmp_path, "api", files=files)
    result = run_routes(tmp_path)
    assert coverage(result, "routes", "api") == "partial"


def test_nest_alias_only_file_without_nest_mentions_is_still_scanned(tmp_path):
    nest_app(
        tmp_path,
        "api",
        files={
            "src/lib.ts": (
                "export { Get as HttpGet, Controller as Ctl } from '@nestjs/common';\n"
            ),
            "src/a.controller.ts": (
                "import { Ctl, HttpGet } from './lib';\n"
                "@Ctl('a') class A {\n  @HttpGet('x') x() {}\n}\n"
            ),
        },
    )
    result = run_routes(tmp_path)
    assert coverage(result, "routes", "api") == "complete"
    assert all_routes(result) == [("GET", "/a/x")]


def test_nuxt_skips_only_nitro_default_ignored_suffixes(tmp_path):
    package(tmp_path, ".", "nuxt")
    write(tmp_path, "server/api/a.test.ts", "export default 1\n")
    write(tmp_path, "server/api/b.spec.mts", "export default 1\n")
    write(tmp_path, "server/api/c.e2e-spec.ts", "export default 1\n")
    write(tmp_path, "server/api/d.test.mjs", "export default 1\n")
    assert all_routes(run_routes(tmp_path)) == [
        ("ANY", "/api/c.e2e-spec"),
        ("ANY", "/api/d.test"),
    ]
