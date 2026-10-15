"""Swift fix round 1: provable middleware, unknown supertypes, structural roots,
the await-repair shim, backticked `default`."""

from __future__ import annotations

import time

import pytest

pytest.importorskip("tree_sitter_language_pack")

from strata_kb.codeingest.extractors import _ts
from tests.swift_support import (
    ROUTES,
    at,
    pairs,
    run_routes,
    run_symbols,
    sym_rows,
    vapor_app,
    vapor_package,
    verdict,
    write,
)

# --- 1. a prefix is dropped only when it is provably middleware -------------------

UNPROVEN_PREFIXES = {
    "string_param": """import Vapor
func routes(_ app: Application) { api(app, prefix: "v1") }
func api(_ app: Application, prefix: String) {
    app.grouped(prefix).get("users") { r in 1 }
}
""",
    "string_ctor_let": """import Vapor
func routes(_ app: Application) {
    let version = String(Environment.get("V") ?? "v1")
    app.grouped(version).get("users") { r in 1 }
}
""",
    "typed_string_let": """import Vapor
func routes(_ app: Application) {
    let version: String = Environment.get("V")!
    app.grouped(version).get("users") { r in 1 }
}
""",
    "path_component_array_param": """import Vapor
func routes(_ app: Application) { api(app) }
func api(_ app: Application, base: [PathComponent] = []) {
    app.grouped(base).get("users") { r in 1 }
}
""",
    "unknown_call_inline": """import Vapor
func routes(_ app: Application) {
    app.grouped(makePrefix()).get("users") { r in 1 }
    app.group(apiVersion()) { g in g.get("items") { r in 1 } }
}
""",
    "unknown_call_let": """import Vapor
func routes(_ app: Application) {
    let p = makePrefix()
    app.grouped(p).get("users") { r in 1 }
}
""",
    "string_literal_ctor": """import Vapor
func routes(_ app: Application) {
    app.grouped(PathComponent(stringLiteral: "x")).get("users") { r in 1 }
}
""",
}


@pytest.mark.parametrize("name", sorted(UNPROVEN_PREFIXES))
def test_unproven_prefix_is_a_site_not_dropped(tmp_path, name):
    src = UNPROVEN_PREFIXES[name]
    vapor_app(tmp_path, src)
    result = run_routes(tmp_path)
    got = {p for _m, p in pairs(result)}
    assert "/users" not in got
    assert "/items" not in got
    status, detail = verdict(result)
    assert status == "partial"
    assert detail


def test_provable_middleware_adds_no_path_and_stays_complete(tmp_path):
    vapor_package(tmp_path)
    write(
        tmp_path,
        "Sources/App/Mw.swift",
        """import Vapor
struct AuthMiddleware: AsyncMiddleware {
    func respond(to request: Request, chainingTo next: AsyncResponder) async throws -> Response {
        try await next.respond(to: request)
    }
}
struct UserAuthenticator: AsyncBearerAuthenticator {
    func authenticate(bearer: BearerAuthorization, for request: Request) async throws {}
}
final class ChildMiddleware: AuthMiddleware {}
""",
    )
    write(
        tmp_path,
        ROUTES,
        """import Vapor
func routes(_ app: Application) throws {
    let auth = AuthMiddleware()
    let tokenAuth = UserToken.authenticator()
    app.grouped(UserAuthenticator()).get("a") { r in 1 }
    app.grouped(User.authenticator(), User.guardMiddleware()).get("b") { r in 1 }
    app.grouped(auth).get("c") { r in 1 }
    app.grouped(tokenAuth).get("d") { r in 1 }
    app.grouped(FileMiddleware(publicDirectory: "x")).get("e") { r in 1 }
    app.grouped(CORSMiddleware(), ErrorMiddleware.default(environment: app.environment)).get("f") { r in 1 }
    app.grouped([AuthMiddleware(), ChildMiddleware()]).get("g") { r in 1 }
    app.grouped(ChildMiddleware()).grouped("h").get("i") { r in 1 }
    app.group(AuthMiddleware()) { g in g.get("j") { r in 1 } }
    app.grouped(User.sessionAuthenticator(), User.redirectMiddleware(path: "/login")).get("k") { r in 1 }
}
""",
    )
    result = run_routes(tmp_path)
    assert {p for _m, p in pairs(result)} == {f"/{c}" for c in "abcdefgj"} | {
        "/h/i",
        "/k",
    }
    assert verdict(result) == ("complete", "")


# --- 2. in-repo types with an external supertype are unknown -----------------------


def test_in_repo_type_with_external_supertype_is_unknown(tmp_path):
    vapor_package(tmp_path)
    src = """import Vapor
import Other
final class Api: HBRouterBuilder {}
struct Wrap { let r: Api }
func routes(_ app: Application) {
    let api = Api()
    api.get("x", use: h)
    let w = Wrap(r: api)
    w.r.post("y", use: h)
}
"""
    write(tmp_path, ROUTES, src)
    result = run_routes(tmp_path)
    status, detail = verdict(result)
    assert status == "partial"
    sites = detail.split("; ")
    assert f"{ROUTES}:{at(src, 'api.get')}" in sites
    assert f"{ROUTES}:{at(src, 'w.r.post')}" in sites


def test_in_repo_plain_types_with_known_supertypes_stay_ignored(tmp_path):
    vapor_package(tmp_path)
    write(
        tmp_path,
        ROUTES,
        """import Vapor
final class Todo: Model, Content, @unchecked Sendable {
    static func get(_ id: Int, _ f: () -> Void) {}
}
struct Cache { func get(_ k: String, use: () -> Void) {} }
func routes(_ app: Application) {
    let c = Cache()
    c.get("k", use: {})
    app.get("real") { r in 1 }
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/real")]
    assert verdict(result) == ("complete", "")


# --- 3. roots are structural, not textual -----------------------------------------


def test_collection_with_application_property_and_mentions_stays_complete(tmp_path):
    vapor_package(tmp_path)
    write(
        tmp_path,
        "Sources/App/Auth.swift",
        """import Vapor
struct AuthController: RouteCollection {
    let app: Application
    func boot(routes: RoutesBuilder) throws {
        let auth = routes.grouped("auth")
        auth.get("me") { req async throws -> String in
            let key = req.application.storage[Application.Key.self]
            return key ?? ""
        }
        auth.post("login", use: login)
    }
    func login(req: Request) async throws -> String { "" }
}
struct Plain: RouteCollection {
    func boot(routes: RoutesBuilder) throws {
        routes.get("plain") { req in req.application.storage[Application.Key.self] }
    }
}
""",
    )
    write(
        tmp_path,
        ROUTES,
        """import Vapor
func routes(_ app: Application) throws {
    try app.register(collection: AuthController(app: app))
    try app.grouped("p").register(collection: Plain())
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [
        ("POST", "/auth/login"),
        ("GET", "/auth/me"),
        ("GET", "/p/plain"),
    ]
    assert verdict(result) == ("complete", "")


def test_methods_of_application_owners_and_app_makers_are_still_roots(tmp_path):
    vapor_package(tmp_path)
    write(
        tmp_path,
        "Sources/App/S.swift",
        """import Vapor
final class Server {
    let app: Application
    init(app: Application) { self.app = app }
    func setup() { addAll(app.grouped("v1")) }
}
func addAll(_ r: RoutesBuilder) { r.get("all") { req in "x" } }
func standalone() throws {
    let app = try Application(.testing)
    app.get("made") { req in "x" }
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/made"), ("GET", "/v1/all")]
    assert verdict(result) == ("complete", "")


# --- 4. the await-repair shim --------------------------------------------------------


def test_await_repair_is_linear_on_a_huge_line():
    # the rewrite alone (tree-sitter's own recovery on such a line is not ours)
    line = b"if " + b"try await x " * 16000 + b"\n"
    source = (b"func f() async throws {\n" + line) * 5 + b"}\n"
    start = time.perf_counter()
    assert _ts._swift_parenthesised(source) == source
    assert time.perf_counter() - start < 2


def test_real_error_line_wins_over_the_repaired_misparse(tmp_path):
    vapor_package(tmp_path)
    write(
        tmp_path,
        "Sources/App/Bad.swift",
        "func f() async throws {\n"
        "  if let x = try await g() { print(x) }\n"
        "  let ok = 1\n"
        "  let = = 3\n"
        "}\n",
    )
    status, detail = verdict(run_routes(tmp_path))
    assert status == "partial"
    assert detail == "Sources/App/Bad.swift:4"


# --- 5. a Swift / Python name `default` is not the JS default-export sentinel ---------


def test_backticked_default_keeps_its_name(tmp_path):
    vapor_package(tmp_path)
    write(
        tmp_path,
        "Sources/Lib/Secrets.swift",
        "public func `default`() {}\npublic let other = 1\n",
    )
    write(tmp_path, "tools/helpers.py", "def default():\n    pass\n")
    names = {(n, f) for n, _k, f in sym_rows(run_symbols(tmp_path))}
    assert ("default", "Sources/Lib/Secrets.swift") in names
    assert ("default", "tools/helpers.py") in names
