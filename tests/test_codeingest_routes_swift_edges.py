"""Swift: Vapor collisions, provenance, rebinding, hostile input, hygiene."""

from __future__ import annotations

import pytest

pytest.importorskip("tree_sitter_language_pack")

from tests.swift_support import (
    ROUTES,
    at,
    everything,
    pairs,
    run_routes,
    vapor_app,
    vapor_package,
    verdict,
    write,
)

HEAD = "import Vapor\n\nfunc routes(_ app: Application) throws {\n"


def routes_of(tmp_path, body: str, head: str = HEAD):
    src = head + body + "}\n"
    vapor_app(tmp_path, src)
    return src, run_routes(tmp_path)


# --- same-named non-route APIs: ignored, and the app stays complete -----------------


def test_non_route_verb_calls_are_not_routes_and_stay_complete(tmp_path):
    _, result = routes_of(
        tmp_path,
        """    app.get("real") { req in "x" }
    app.get("client") { req async throws -> String in
        _ = try await req.client.get("https://example.com/a")
        _ = try await req.client.get(URI(string: "https://example.com")) { out in
            out.headers.add(name: .authorization, value: "x")
        }
        _ = try await req.application.client.post("https://example.com") { out in
            try out.content.encode(["a": 1])
        }
        let client = req.client
        _ = try await client.delete("https://example.com/x") { out in out.headers.add(name: "a", value: "b") }
        let id = req.parameters.get("id")
        let q = try req.query.get(String.self, at: "q")
        let h = req.headers.first(name: .host)
        let env = Environment.get("HOME")
        _ = try await URLSession.shared.data(from: URL(string: "https://e.com")!)
        var dict = Dictionary<String, Int>()
        dict["a"] = 1
        let cached = try await req.cache.get("key", as: String.self)
        let v = req.session.data["k"]
        try await todo.delete(on: req.db)
        try await Todo.query(on: req.db).group(.or) { g in g.filter(\\.$a == 1) }.all()
        return "ok"
    }
    app.client.get("https://example.com") { out in out.headers.add(name: "a", value: "b") }
""",
    )
    assert pairs(result) == [("GET", "/client"), ("GET", "/real")]
    assert verdict(result) == ("complete", "")


def test_route_shaped_call_on_unknown_receiver_is_a_site(tmp_path):
    src, result = routes_of(
        tmp_path,
        """    cache.get("k") { value in value }
    thing.post("p", use: handle)
    api.grouped("v2").get("x") { req in "x" }
    router.on(.GET, "e") { req in "x" }
    router.webSocket("ws") { req, ws in }
    helper().get("") { req in "x" }
    router.get("") { req in "x" }
    router.get("/abs") { req in "x" }
    x.group("g") { y in }
    tryCollection.register(collection: Foo())
""",
    )
    assert pairs(result) == []
    status, detail = verdict(result)
    assert status == "partial"
    for needle in (
        'cache.get("k")',
        'thing.post("p"',
        'api.grouped("v2")',
        "router.on",
        "router.webSocket",
        "helper().get",
        'router.get("")',
        'router.get("/abs")',
        'x.group("g")',
        "tryCollection.register",
    ):
        assert f"{ROUTES}:{at(src, needle)}" in detail.split("; "), needle


def test_unknown_receiver_without_the_route_shape_is_ignored(tmp_path):
    _, result = routes_of(
        tmp_path,
        """    get("id")
    thing.get("a")
    thing.post(payload)
    thing.get(5) { v in v }
    thing.get(String.self, at: "k")
    thing.delete(on: db)
    items.grouped(by: \\.name)
    q.group(.and) { g in g }
    q.group(\\.$name)
""",
    )
    assert verdict(result) == ("complete", "")


def test_method_taken_as_a_value_and_add_route_are_sites(tmp_path):
    vapor_package(tmp_path)
    src = """import Vapor

func routes(_ app: Application) throws {
    let getter = app.get
    app.routes.add(Route(method: .GET, path: ["a"], responder: responder))
    controllers.forEach(app.register)
}
"""
    write(tmp_path, ROUTES, src)
    result = run_routes(tmp_path)
    assert pairs(result) == []
    sites = verdict(result)[1].split("; ")
    for needle in ("app.get\n", "Route(method", "app.register)"):
        assert f"{ROUTES}:{at(src, needle.strip())}" in sites, needle


def test_unresolvable_helper_on_the_router_types_is_a_site(tmp_path):
    vapor_package(tmp_path)
    src = """import Vapor

extension RoutesBuilder {
    func crud(_ path: PathComponent, name: String) {
        self.get(path) { req in "x" }
    }
}
func routes(_ app: Application) throws {
    app.crud("things")
    app.crud("two", name: "n", extra: 1)
}
"""
    write(tmp_path, ROUTES, src)
    result = run_routes(tmp_path)
    status, detail = verdict(result)
    assert status == "partial"
    two = at(src, 'app.crud("two"')
    assert f"{ROUTES}:{two}" in detail.split("; ")


# --- rebinding, shadowing, conditional compilation ---------------------------------------


def test_reassigned_shadowed_and_redeclared_routers_are_not_trusted(tmp_path):
    src, result = routes_of(
        tmp_path,
        """    var g = app.grouped("old")
    g = app.grouped("new")
    g.get("reassigned") { req in "x" }
    let api = app.grouped("api")
    if let api = maybeRouter() {
        api.get("shadow") { req in "x" }
    }
    api.get("after") { req in "x" }
    #if DEBUG
    let dbg = app.grouped("debug")
    #else
    let dbg = app.grouped("release")
    #endif
    dbg.get("conditional") { req in "x" }
    let ok = app.grouped("fine")
    ok.get("good") { req in "x" }
""",
    )
    assert pairs(result) == [("GET", "/fine/good")]
    sites = verdict(result)[1].split("; ")
    for needle in ('"reassigned"', '"shadow"', '"after"', '"conditional"'):
        assert f"{ROUTES}:{at(src, needle)}" in sites, needle


def test_conditional_compilation_keeps_both_branches_of_routes(tmp_path):
    _, result = routes_of(
        tmp_path,
        """    #if DEBUG
    app.get("debug") { req in "x" }
    #else
    app.get("release") { req in "x" }
    #endif
    app.get("always") { req in "x" }
""",
    )
    assert pairs(result) == [("GET", "/always"), ("GET", "/debug"), ("GET", "/release")]
    assert verdict(result) == ("complete", "")


def test_a_group_closure_parameter_shadows_the_outer_name(tmp_path):
    src, result = routes_of(
        tmp_path,
        """    let r = app.grouped("outer")
    app.group("inner") { r in
        r.get("a") { req in "x" }
    }
    r.get("b") { req in "x" }
""",
    )
    assert pairs(result) == [("GET", "/inner/a"), ("GET", "/outer/b")]
    assert verdict(result) == ("complete", "")


# --- file-order and helper-order independence ---------------------------------------------


@pytest.mark.parametrize("registering_first", [True, False])
def test_helper_reached_with_a_prefix_is_not_also_a_site(tmp_path, registering_first):
    vapor_package(tmp_path)
    a, b = ("A_routes.swift", "Z_helpers.swift")
    if not registering_first:
        a, b = "Z_routes.swift", "A_helpers.swift"
    write(
        tmp_path,
        f"Sources/App/{a}",
        "import Vapor\nfunc routes(_ app: Application) {\n"
        '    addUsers(app.grouped("api"))\n}\n',
    )
    write(
        tmp_path,
        f"Sources/App/{b}",
        "import Vapor\nfunc addUsers(_ r: RoutesBuilder) {\n"
        '    r.get("users") { req in "u" }\n}\n',
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/api/users")]
    assert verdict(result) == ("complete", "")


def test_helper_chain_reached_from_a_property_owner_is_not_order_dependent(tmp_path):
    vapor_package(tmp_path)
    write(
        tmp_path,
        "Sources/App/Z.swift",
        """import Vapor
final class Server {
    let app: Application
    init(app: Application) { self.app = app }
    func setup() { addAll(app.grouped("v1")) }
}
""",
    )
    write(
        tmp_path,
        "Sources/App/A.swift",
        """import Vapor
func addAll(_ r: RoutesBuilder) { r.get("all") { req in "x" } }
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/v1/all")]
    assert verdict(result) == ("complete", "")


def test_recursive_helpers_and_deep_helper_chains_are_sites_not_hangs(tmp_path):
    levels = "\n".join(
        f'func h{i}(_ r: RoutesBuilder) {{ h{i + 1}(r.grouped("l{i}")) }}'
        for i in range(12)
    )
    src = (
        "import Vapor\n"
        "func routes(_ app: Application) { h0(app); loop(app) }\n"
        "func loop(_ r: RoutesBuilder) { loop(r) }\n"
        + levels
        + '\nfunc h12(_ r: RoutesBuilder) { r.get("end") { req in "x" } }\n'
    )
    vapor_app(tmp_path, src)
    result = run_routes(tmp_path)
    assert verdict(result)[0] == "partial"


# --- hostile input ---------------------------------------------------------------------


def test_syntax_error_and_unreadable_shapes_are_sites_not_crashes(tmp_path):
    vapor_package(tmp_path)
    write(tmp_path, ROUTES, HEAD + '    app.get("ok") { req in "x" }\n}\n')
    write(tmp_path, "Sources/App/Bad.swift", "func broken( {{{ \n app.get(\n")
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/ok")]
    status, detail = verdict(result)
    assert status == "partial"
    assert "Sources/App/Bad.swift:" in detail


def test_deeply_nested_input_does_not_crash(tmp_path):
    chain = "app" + '.grouped("a")' * 3000
    nest = "(" * 2500 + 'app.get("n") { req in "x" }' + ")" * 2500
    closures = "".join('app.group("g") { g in\n' for _ in range(400)) + "}\n" * 400
    src = (
        HEAD
        + f'    {chain}.get("deep") {{ req in "x" }}\n'
        + f"    {nest}\n"
        + "    "
        + closures
        + '    app.get("after") { req in "x" }\n}\n'
    )
    vapor_app(tmp_path, src)
    result = run_routes(tmp_path)
    got = {p for _m, p in pairs(result)}
    assert "/after" in got
    assert "/" + "/".join(["a"] * 3000) + "/deep" in got
    assert verdict(result)[0] in ("complete", "partial")


def test_declaration_shapes_do_not_crash_the_resolver(tmp_path):
    vapor_package(tmp_path)
    write(
        tmp_path,
        "Sources/App/Shapes.swift",
        """import Vapor
let (a, b) = (1, 2)
let (c, _) = pair()
var _ = 3
let [first, second] = list()
struct Gen<T: RoutesBuilder, U>: RouteCollection where U: Sendable {
    typealias Alias = Application
    func boot(routes: RoutesBuilder, extra: Int = 0, _ more: String...) throws {}
    subscript(i: Int) -> Int { get { i } set { } }
    deinit {}
    init?(coder: Int) { return nil }
    var computed: Application { fatalError() }
    static func make<R>(_ r: R) -> R where R: RoutesBuilder { r }
}
enum E: String, CaseIterable { case a = "A", b = "B"; static let all = [E.a] }
protocol P: RouteCollection { func configure(app: Application) async throws }
actor Act { func run(_ app: Application) async { await helper(app) } }
func helper(_ app: Application) async {}
func labels(a b: Application, _ c: Application, d: inout Int, e: @escaping () -> Void) {}
func tuple(_ t: (Application, Int)) {}
func opt(_ o: Application?, _ p: (any RoutesBuilder)?, _ q: [Application]) {}
func top(app: Application) throws {
    let (x, y) = (app.grouped("x"), app.grouped("y"))
    x.get("t") { r in r }
    for (i, v) in [1, 2].enumerated() { _ = (i, v) }
    switch app.environment { case .production: break; default: break }
    do { try await helper(app) } catch let e { _ = e }
    guard case .some(let z) = Optional(app) else { return }
    z.get("z") { r in r }
    labels(a: app, app, d: &n, e: {})
    tuple((app, 1))
    opt(app, app, [app])
    let closure = { (r: RoutesBuilder) in r.get("c") { _ in 1 } }
    closure(app)
    _ = try? await Application.make(.testing)
    app.get(.constant("k"), .parameter("p"), .catchall) { _ in 1 }
    app.group("g", "h") { g in g.get(":i") { _ in 1 } }
    Task { try await helper(app) }
    func local(_ r: RoutesBuilder) { r.get("loc") { _ in 1 } }
    local(app)
}
""",
    )
    result = run_routes(tmp_path)
    assert ("GET", "/k/:p/**") in pairs(result)
    assert ("GET", "/g/h/:i") in pairs(result)
    assert verdict(result)[0] == "partial"


# --- hygiene -------------------------------------------------------------------------------


def test_swift_route_output_never_carries_values(tmp_path):
    _, result = routes_of(
        tmp_path,
        """    let secret = "sk_live_ROUTESECRET"
    app.jwt.signers.use(.hs256(key: "JWTSECRETKEY"))
    app.get("ok") { req async throws -> String in
        let token = "ghp_HANDLERSECRET"
        return Environment.get("DB_PASSWORD") ?? "hunter2-fallback"
    }
    app.get("users", use: handler)
""",
    )
    blob = everything(result)
    for leak in (
        "ROUTESECRET",
        "JWTSECRETKEY",
        "HANDLERSECRET",
        "hunter2",
        "DB_PASSWORD",
    ):
        assert leak not in blob
    assert pairs(result) == [("GET", "/ok"), ("GET", "/users")]


def test_tests_directory_and_package_manifest_are_not_read(tmp_path):
    vapor_app(tmp_path, HEAD + '    app.get("real") { req in "x" }\n}\n')
    write(
        tmp_path,
        "Tests/AppTests/AppTests.swift",
        'import XCTVapor\nfunc t(_ app: Application) { app.get("only-in-tests") { r in "x" } }\n',
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/real")]
    assert verdict(result) == ("complete", "")


def test_two_vapor_packages_are_separate_scopes(tmp_path):
    vapor_package(tmp_path, "svc-a")
    vapor_package(tmp_path, "svc-b")
    write(
        tmp_path,
        "svc-a/Sources/App/r.swift",
        HEAD + '    app.get("a") { req in "x" }\n}\n',
    )
    write(
        tmp_path,
        "svc-b/Sources/App/r.swift",
        HEAD + '    app.get("b") { req in "x" }\n    mystery(app)\n}\n',
    )
    result = run_routes(tmp_path)
    by_scope = {r.scope: r for r in result.coverage if r.area == "routes"}
    assert by_scope["svc-a"].status == "complete"
    assert by_scope["svc-b"].status == "partial"
    assert pairs(result) == [("GET", "/a"), ("GET", "/b")]


def test_in_repo_types_named_like_vapor_ones_are_not_routers(tmp_path):
    vapor_package(tmp_path)
    write(
        tmp_path,
        "Sources/App/Nav.swift",
        """import Vapor
final class Router {
    func get(_ name: String, handler: () -> Void) {}
}
func navigate(_ r: Router) {
    r.get("home") { }
}
func routes(_ app: Application) {
    app.get("real") { req in "x" }
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/real")]
    assert verdict(result) == ("complete", "")


def test_extensions_of_the_application_register_on_self(tmp_path):
    vapor_package(tmp_path)
    write(
        tmp_path,
        "Sources/App/Ext.swift",
        """import Vapor
extension Application {
    func registerRoutes() throws {
        get("implicit") { req in "x" }
        self.grouped("api").get("explicit") { req in "x" }
        try register(collection: Todos())
    }
}
extension RoutesBuilder {
    func crud(_ name: PathComponent) {
        self.get(name) { req in "x" }
    }
}
struct Todos: RouteCollection {
    func boot(routes: RoutesBuilder) throws { routes.get("todos") { r in "x" } }
}
func routes(_ app: Application) throws {
    try app.registerRoutes()
    app.grouped("x").crud("things")
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [
        ("GET", "/api/explicit"),
        ("GET", "/implicit"),
        ("GET", "/todos"),
        ("GET", "/x/things"),
    ]
    assert verdict(result) == ("complete", "")


# --- grammar limits --------------------------------------------------------------


def test_try_await_in_a_condition_does_not_make_the_scope_partial(tmp_path):
    vapor_package(tmp_path)
    write(
        tmp_path,
        "Sources/App/Ctl.swift",
        """import Vapor
struct Ctl: RouteCollection {
    func boot(routes: RoutesBuilder) throws {
        routes.get("a", use: self.a)
        routes.post("b", use: self.b)
    }
    func a(req: Request) async throws -> String {
        if let user = try await User.find(req.parameters.get("id"), on: req.db) {
            return user.name
        } else if let other = try? await other(req) {
            return other
        }
        while let next = try await queue.pop() {
            print(next)
        }
        switch try await state(req) {
        case .ready: break
        default: break
        }
        return ""
    }
    func b(req: Request) async throws -> String { "" }
}
func routes(_ app: Application) throws { try app.register(collection: Ctl()) }
""",
    )
    write(
        tmp_path,
        "Sources/App/Lib.swift",
        "public struct Lib {\n  public func f() async throws {\n"
        "    if let x = try await g() { print(x) }\n  }\n}\n",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/a"), ("POST", "/b")]
    assert verdict(result) == ("complete", "")
    from tests.swift_support import run_symbols

    (cov,) = [r for r in run_symbols(tmp_path).coverage if r.framework == "swift"]
    assert (cov.status, cov.detail) == ("complete", "")


def test_a_real_syntax_error_is_still_a_site_after_the_await_repair(tmp_path):
    vapor_package(tmp_path)
    write(
        tmp_path,
        "Sources/App/Bad.swift",
        "func f() async throws {\n  if let x = try await g() { print(x) }\n  let = = 1\n}\n",
    )
    status, detail = verdict(run_routes(tmp_path))
    assert status == "partial"
    assert "Sources/App/Bad.swift:" in detail


def test_ambiguous_aliases_and_properties_are_not_guessed(tmp_path):
    vapor_package(tmp_path)
    write(
        tmp_path,
        "Sources/App/A/Alias.swift",
        "import Vapor\ntypealias Web = Application\n"
        "struct Server { let handle: Application\n"
        '  func setup() { handle.get("one") { r in "x" } } }\n',
    )
    write(
        tmp_path,
        "Sources/App/B/Alias.swift",
        "import Vapor\ntypealias Web = Client\n"
        "struct Server { let handle: Client\n"
        '  func setup() { handle.get("two") { r in "x" } } }\n'
        'func viaAlias(_ w: Web) { w.get("three") { r in "x" } }\n',
    )
    result = run_routes(tmp_path)
    # `handle` is an Application in one `Server` and a Client in the other, `Web`
    # is both: nothing is guessed, every route-shaped call is a site
    assert pairs(result) == []
    sites = verdict(result)[1].split("; ")
    assert "Sources/App/A/Alias.swift:4" in sites
    assert "Sources/App/B/Alias.swift:4" in sites
    assert "Sources/App/B/Alias.swift:5" in sites
