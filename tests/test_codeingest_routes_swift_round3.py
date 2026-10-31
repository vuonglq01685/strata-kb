"""Swift fix round 3: `sessions.middleware` needs the Application as base,
in-repo declarations shadow the known middleware names, scale ratio."""

from __future__ import annotations

import time

import pytest

pytest.importorskip("tree_sitter_language_pack")

from tests.swift_support import (
    ROUTES,
    pairs,
    run_routes,
    vapor_app,
    vapor_package,
    verdict,
    write,
)

HEAD = "import Vapor\n"


def routes_src(body: str, extra: str = "") -> str:
    return HEAD + extra + "func routes(_ app: Application) throws {\n" + body + "\n}\n"


SESSIONS_NOT_THE_APP = {
    "unknown_base": routes_src(
        '    app.grouped(config.sessions.middleware).get("x") { r in 1 }'
    ),
    "in_repo_string_chain": routes_src(
        '    let cfg = Paths()\n    app.grouped(cfg.sessions.middleware).get("x") { r in 1 }',
        'struct S { let middleware: String = "v1" }\n'
        "struct Paths { let sessions: S = S() }\n",
    ),
    "static_enum_string": routes_src(
        '    app.grouped(Env.sessions.middleware).get("x") { r in 1 }',
        'enum Env { enum sessions { static let middleware = "v1" } }\n',
    ),
    "call_base": routes_src(
        '    app.grouped(foo().sessions.middleware).get("x") { r in 1 }'
    ),
    "other_router_member": routes_src(
        '    app.grouped(app.http.sessions.middleware).get("x") { r in 1 }'
    ),
}


@pytest.mark.parametrize("name", sorted(SESSIONS_NOT_THE_APP))
def test_sessions_middleware_of_a_non_application_is_a_site(tmp_path, name):
    vapor_app(tmp_path, SESSIONS_NOT_THE_APP[name])
    result = run_routes(tmp_path)
    assert ("GET", "/x") not in pairs(result)
    assert verdict(result)[0] == "partial"


def test_self_sessions_middleware_in_a_collection_is_a_site(tmp_path):
    vapor_package(tmp_path)
    write(
        tmp_path,
        ROUTES,
        HEAD
        + """func routes(_ app: Application) throws { try app.register(collection: C()) }
struct C: RouteCollection {
    let sessions = S()
    func boot(routes: RoutesBuilder) throws {
        routes.grouped(self.sessions.middleware).get("x") { r in 1 }
    }
}
struct S { let middleware = "v1" }
""",
    )
    result = run_routes(tmp_path)
    assert ("GET", "/x") not in pairs(result)
    assert verdict(result)[0] == "partial"


def test_sessions_middleware_of_the_application_stays_middleware(tmp_path):
    vapor_app(
        tmp_path,
        routes_src(
            """    app.grouped(app.sessions.middleware).get("a") { r in 1 }
    app.grouped([app.sessions.middleware, User.guardMiddleware()]).get("b") { r in 1 }
    app.get("c") { req async throws -> String in
        req.application.grouped(req.application.sessions.middleware).get("d") { r in 1 }
        return ""
    }"""
        ),
    )
    result = run_routes(tmp_path)
    assert {p for _m, p in pairs(result)} == {"/a", "/b", "/c", "/d"}
    assert verdict(result) == ("complete", "")


# --- in-repo declarations shadow the known names ----------------------------------

SHADOWED = {
    "middleware_factory_string": routes_src(
        '    app.grouped(Paths.middleware()).get("x") { r in 1 }',
        'enum Paths { static func middleware() -> String { "v1" } }\n',
    ),
    "async_factory_string": routes_src(
        '    app.grouped(Paths.asyncSessionAuthenticator()).get("x") { r in 1 }',
        'enum Paths { static func asyncSessionAuthenticator() -> String { "v1" } }\n',
    ),
    "type_not_a_middleware": routes_src(
        '    app.grouped(TracingMiddleware()).get("x") { r in 1 }',
        'struct TracingMiddleware { func callAsFunction() -> String { "v1" } }\n',
    ),
    "factory_without_return_type": routes_src(
        '    app.grouped(Paths.guardMiddleware()).get("x") { r in 1 }',
        "enum Paths { static func guardMiddleware() {} }\n",
    ),
}


@pytest.mark.parametrize("name", sorted(SHADOWED))
def test_in_repo_non_middleware_declaration_shadows_the_known_name(tmp_path, name):
    vapor_app(tmp_path, SHADOWED[name])
    result = run_routes(tmp_path)
    assert ("GET", "/x") not in pairs(result)
    assert verdict(result)[0] == "partial"


def test_in_repo_declarations_that_are_middleware_still_count(tmp_path):
    vapor_app(
        tmp_path,
        routes_src(
            """    app.grouped(Paths.middleware()).get("a") { r in 1 }
    app.grouped(Paths.guardMiddleware()).get("b") { r in 1 }
    app.grouped(TracingMiddleware()).get("c") { r in 1 }""",
            """struct TracingMiddleware: AsyncMiddleware {}
struct Built: AsyncMiddleware {}
enum Paths {
    static func middleware() -> Built { Built() }
    static func guardMiddleware() -> some Middleware { Built() }
}
""",
        ),
    )
    result = run_routes(tmp_path)
    assert {p for _m, p in pairs(result)} == {"/a", "/b", "/c"}
    assert verdict(result) == ("complete", "")


# --- scaling ---------------------------------------------------------------------------


def _scope_with(root, files: int):
    vapor_package(root)
    write(root, ROUTES, routes_src('    app.get("x") { r in 1 }'))
    for i in range(files):
        props = "\n".join(f"    let p{j}: Int = {j}" for j in range(10))
        fns = "\n".join(f"    func f{j}() {{ }}" for j in range(10))
        write(
            root,
            f"Sources/App/M{i}.swift",
            f"import Vapor\nstruct T{i} {{\n{props}\n{fns}\n}}\n",
        )


def test_app_owners_are_scanned_once_whatever_the_file_count(tmp_path, monkeypatch):
    """The scale guard, without a clock: a per-call owner rescan (the bug the
    timing test below was written for) shows up as many scans."""
    from strata_kb.codeingest.extractors import _routes_swift

    calls = []
    real = _routes_swift.Vapor._scan_app_owners

    def counting(self):
        calls.append(1)
        return real(self)

    monkeypatch.setattr(_routes_swift.Vapor, "_scan_app_owners", counting)
    for files in (20, 200):
        calls.clear()
        root = tmp_path / str(files)
        _scope_with(root, files)
        assert verdict(run_routes(root)) == ("complete", "")
        assert len(calls) <= 1, files


def test_time_grows_roughly_linearly_with_the_file_count(tmp_path):
    timings = {}
    for files in (200, 800):
        root = tmp_path / str(files)
        _scope_with(root, files)
        runs = []
        # best of 3: noise on a shared CI runner only adds time
        for _ in range(3):
            start = time.perf_counter()
            assert verdict(run_routes(root)) == ("complete", "")
            runs.append(time.perf_counter() - start)
        timings[files] = min(runs)
    # 4x the files: linear is ~4x locally, but 9-11x on loaded CI runners
    # (xdist workers share the machine), which failed the 1.32.0 release gate
    # at the old limit of 9. A per-call owner rescan is ~16x locally and far
    # more on CI; the exact guard is the scan-count test above.
    assert timings[800] / max(timings[200], 0.05) < 16
