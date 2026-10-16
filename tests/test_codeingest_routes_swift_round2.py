"""Swift fix round 2: scaling, wider known-middleware list, missing-token line."""

from __future__ import annotations

import pytest

pytest.importorskip("tree_sitter_language_pack")

from tests.swift_support import (
    ROUTES,
    pairs,
    run_routes,
    vapor_package,
    verdict,
    write,
)


def test_typical_sessions_and_auth_app_reaches_complete(tmp_path):
    vapor_package(tmp_path)
    write(
        tmp_path,
        "Sources/App/Auth.swift",
        """import Vapor
import Fluent
struct UserSessionAuthenticator: AsyncSessionAuthenticator {
    func authenticate(sessionID: UUID, for request: Request) async throws {}
}
""",
    )
    write(
        tmp_path,
        ROUTES,
        """import Vapor
func routes(_ app: Application) throws {
    app.middleware.use(app.sessions.middleware)
    let sessions = app.grouped(app.sessions.middleware)
    sessions.get("a") { r in 1 }
    let docs = app.routes.grouped([app.sessions.middleware, UserSessionAuthenticator(), User.guardMiddleware()])
    docs.get("b") { r in 1 }
    app.grouped(User.asyncSessionAuthenticator()).get("c") { r in 1 }
    app.grouped(User.asyncCredentialsAuthenticator()).post("login") { r in 1 }
    app.grouped(ResponseCompressionMiddleware(), TracingMiddleware(), MetricsMiddleware()).get("d") { r in 1 }
    app.grouped(app.sessions.middleware, User.asyncSessionAuthenticator(), User.redirectMiddleware(path: "/login")).get("e") { r in 1 }
}
""",
    )
    result = run_routes(tmp_path)
    assert {p for _m, p in pairs(result)} == {"/a", "/b", "/c", "/login", "/d", "/e"}
    assert verdict(result) == ("complete", "")


def test_other_members_named_middleware_are_not_assumed(tmp_path):
    vapor_package(tmp_path)
    write(
        tmp_path,
        ROUTES,
        """import Vapor
func routes(_ app: Application) throws {
    app.grouped(config.prefix.middleware).get("x") { r in 1 }
}
""",
    )
    assert verdict(run_routes(tmp_path))[0] == "partial"


def test_a_missing_token_names_its_own_line(tmp_path):
    vapor_package(tmp_path)
    write(
        tmp_path,
        "Sources/App/Bad.swift",
        "func f() async throws {\n"
        "  if let x = try await g() { print(x) }\n"
        "  let ok = 1\n"
        "  let = 3\n"
        "}\n",
    )
    assert verdict(run_routes(tmp_path)) == ("partial", "Sources/App/Bad.swift:4")
