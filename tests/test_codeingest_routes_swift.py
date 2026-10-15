"""Swift: Vapor routes -- verbs, path components, groups, collections, helpers."""

from __future__ import annotations

import pytest

pytest.importorskip("tree_sitter_language_pack")

from tests.swift_support import (
    ROUTES,
    at,
    pairs,
    rows_of,
    run_routes,
    triples,
    vapor_app,
    vapor_package,
    verdict,
    write,
)


def by_path(found):
    return sorted(found, key=lambda p: (p[1], p[0]))


# --- verbs, path components, handlers ---------------------------------------


def test_vapor_verbs_path_components_and_handler_forms(tmp_path):
    vapor_app(
        tmp_path,
        """import Vapor

func routes(_ app: Application) throws {
    app.get { req in "root" }
    app.get("hello", ":name") { req -> String in "hi" }
    app.post("users", use: createUser)
    app.put("users", ":id", use: UserController.update)
    app.patch("users", ":id") { req in req }
    app.delete("users", ":id", use: { req in req })
    app.get("files", "*") { req in req }
    app.get("assets", "**") { req in req }
    app.get(.constant("c"), .parameter("p"), .anything) { req in req }
    app.get(PathComponent.constant("d"), PathComponent.parameter("q")) { req in req }
    app.get("a/b", "c") { req in req }
    app.get(["arr", ":x"]) { req in req }
    app.post("upload", body: .collect(maxSize: "10mb")) { req in req }
    app.get(#"raw"#) { req in req }
}
""",
    )
    result = run_routes(tmp_path)
    assert rows_of(result, ROUTES) == [
        ["GET", "/", "(inline)", ROUTES, ""],
        ["GET", "/a/b/c", "(inline)", ROUTES, ""],
        ["GET", "/arr/:x", "(inline)", ROUTES, ""],
        ["GET", "/assets/**", "(inline)", ROUTES, ""],
        ["GET", "/c/:p/*", "(inline)", ROUTES, ""],
        ["GET", "/d/:q", "(inline)", ROUTES, ""],
        ["GET", "/files/*", "(inline)", ROUTES, ""],
        ["GET", "/hello/:name", "(inline)", ROUTES, ""],
        ["GET", "/raw", "(inline)", ROUTES, ""],
        ["POST", "/upload", "(inline)", ROUTES, ""],
        ["POST", "/users", "createUser", ROUTES, ""],
        ["DELETE", "/users/:id", "(inline)", ROUTES, ""],
        ["PATCH", "/users/:id", "(inline)", ROUTES, ""],
        ["PUT", "/users/:id", "UserController.update", ROUTES, ""],
    ]
    assert verdict(result) == ("complete", "")


def test_vapor_on_and_websocket(tmp_path):
    src = """import Vapor

func routes(_ app: Application) throws {
    app.on(.GET, "a") { req in "x" }
    app.on(.POST, "b", ":id", use: handle)
    app.on(HTTPMethod.PUT, "c", body: .collect) { req in "x" }
    app.webSocket("ws", "echo") { req, ws in }
    app.on(.init(rawValue: "PURGE"), "d") { req in "x" }
    app.on(method, "e") { req in "x" }
}
"""
    vapor_app(tmp_path, src)
    result = run_routes(tmp_path)
    assert pairs(result) == by_path(
        [("GET", "/a"), ("POST", "/b/:id"), ("PUT", "/c"), ("GET", "/ws/echo")]
    )
    purge, dynamic = at(src, "PURGE"), at(src, "on(method")
    assert verdict(result) == (
        "partial",
        "; ".join(sorted([f"{ROUTES}:{purge}", f"{ROUTES}:{dynamic}"])),
    )


# --- groups ---------------------------------------------------------------------


def test_vapor_grouped_chains_group_closures_and_middleware(tmp_path):
    vapor_app(
        tmp_path,
        """import Vapor

func routes(_ app: Application) throws {
    let api = app.grouped("api", "v1")
    api.get("ping") { req in "pong" }
    let protected = api.grouped(User.authenticator(), User.guardMiddleware())
    protected.get("me") { req in req }
    protected.grouped("admin").grouped(AdminOnly()).post("users", ":id") { req in req }
    app.grouped(.constant("x")).get("y") { req in req }
    app.group("g") { g in
        g.get("one") { req in req }
        g.group(":id", "items") { item in
            item.delete { req in req }
        }
    }
    app.group(RateLimit()) { g in
        g.get("limited") { req in req }
    }
    app.routes.get("viaRoutes") { req in req }
    app.group("short") { $0.get("dollar") { req in req } }
    app
        .grouped("multi")  // a comment in the chain
        .grouped(
            "line"
        )
        .get(
            "ok"
        ) { req in req }
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == by_path(
        [
            ("GET", "/api/v1/me"),
            ("POST", "/api/v1/admin/users/:id"),
            ("GET", "/api/v1/ping"),
            ("GET", "/g/one"),
            ("DELETE", "/g/:id/items"),
            ("GET", "/limited"),
            ("GET", "/multi/line/ok"),
            ("GET", "/short/dollar"),
            ("GET", "/viaRoutes"),
            ("GET", "/x/y"),
        ]
    )
    assert verdict(result) == ("complete", "")


# --- route collections -------------------------------------------------------------


COLLECTION = """import Vapor

struct TodoController: RouteCollection {
    func boot(routes: RoutesBuilder) throws {
        let todos = routes.grouped("todos")
        todos.get(use: self.index)
        todos.post(use: create)
        todos.group(":todoID") { todo in
            todo.get(use: self.show)
            todo.delete(use: self.delete)
        }
    }
    func index(req: Request) async throws -> String { "" }
    func create(req: Request) async throws -> String { "" }
    func show(req: Request) async throws -> String { "" }
    func delete(req: Request) async throws -> String { "" }
}
"""
CTRL = "Sources/App/Controllers/TodoController.swift"


def test_vapor_route_collection_table_rows(tmp_path):
    vapor_app(tmp_path, COLLECTION, CTRL)
    write(
        tmp_path,
        ROUTES,
        "import Vapor\nfunc routes(_ app: Application) throws {\n"
        "    try app.register(collection: TodoController())\n}\n",
    )
    result = run_routes(tmp_path)
    assert rows_of(result, CTRL) == sorted(
        [
            ["POST", "/todos", "TodoController.create", CTRL, ""],
            ["GET", "/todos", "TodoController.index", CTRL, ""],
            ["GET", "/todos/:todoID", "TodoController.show", CTRL, ""],
            ["DELETE", "/todos/:todoID", "TodoController.delete", CTRL, ""],
        ],
        key=lambda r: (r[1], r[0]),
    )
    assert verdict(result) == ("complete", "")


@pytest.mark.parametrize(
    ("registering", "defining"),
    [("A_routes.swift", "Z_Todo.swift"), ("Z_routes.swift", "A_Todo.swift")],
)
def test_vapor_collection_resolves_across_files_in_either_order(
    tmp_path, registering, defining
):
    vapor_package(tmp_path)
    write(
        tmp_path,
        f"Sources/App/{registering}",
        "import Vapor\nfunc routes(_ app: Application) throws {\n"
        '    try app.grouped("api").register(collection: TodoController())\n}\n',
    )
    write(tmp_path, f"Sources/App/{defining}", COLLECTION)
    result = run_routes(tmp_path)
    assert ("GET", "/api/todos/:todoID") in pairs(result)
    assert len(pairs(result)) == 4
    assert verdict(result) == ("complete", "")


def test_vapor_nested_collections_boot_in_extension_and_inherited_boot(tmp_path):
    vapor_package(tmp_path)
    write(
        tmp_path,
        "Sources/App/Api.swift",
        """import Vapor

struct ApiController: RouteCollection {
    func boot(routes: RoutesBuilder) throws {
        let v1 = routes.grouped("v1")
        try v1.register(collection: UserController())
        try v1.register(collection: PostController())
    }
}
struct UserController {}
extension UserController: RouteCollection {
    func boot(routes: RoutesBuilder) throws {
        routes.get("users") { req in "u" }
    }
}
class BaseController: RouteCollection {
    func boot(routes: RoutesBuilder) throws {
        routes.get(self.path) { req in "p" }
    }
    var path: PathComponent { "posts" }
}
final class PostController: BaseController {
    func extra() {}
}
""",
    )
    write(
        tmp_path,
        ROUTES,
        "import Vapor\nfunc routes(_ app: Application) throws {\n"
        '    try app.grouped("api").register(collection: ApiController())\n}\n',
    )
    result = run_routes(tmp_path)
    got = pairs(result)
    assert ("GET", "/api/v1/users") in got
    # the inherited boot reads a computed property: a site, not a made-up path
    status, detail = verdict(result)
    assert status == "partial"
    assert "Sources/App/Api.swift:" in detail
    assert len(got) == 1


def test_vapor_unregistered_external_and_ambiguous_collections_are_sites(tmp_path):
    vapor_package(tmp_path)
    write(
        tmp_path,
        "Sources/App/Colls.swift",
        """import Vapor

struct Lonely: RouteCollection {
    func boot(routes: RoutesBuilder) throws { routes.get("lonely") { req in "x" } }
}
""",
    )
    write(
        tmp_path,
        "Sources/App/A/Dup.swift",
        "import Vapor\nstruct Dup: RouteCollection {\n"
        '  func boot(routes: RoutesBuilder) throws { routes.get("a") { r in "x" } }\n}\n',
    )
    write(
        tmp_path,
        "Sources/App/B/Dup.swift",
        "import Vapor\nstruct Dup: RouteCollection {\n"
        '  func boot(routes: RoutesBuilder) throws { routes.get("b") { r in "x" } }\n}\n',
    )
    src = (
        "import Vapor\nimport Library\nfunc routes(_ app: Application) throws {\n"
        "    try app.register(collection: Dup())\n"
        "    try app.register(collection: ExternalController())\n"
        "    for c in loadControllers() { try app.register(collection: c) }\n}\n"
    )
    write(tmp_path, ROUTES, src)
    result = run_routes(tmp_path)
    status, detail = verdict(result)
    assert status == "partial"
    sites = detail.split("; ")
    assert "Sources/App/Colls.swift:3" in sites  # Lonely, never registered
    assert f"{ROUTES}:{at(src, 'Dup()')}" in sites
    assert f"{ROUTES}:{at(src, 'External')}" in sites
    assert f"{ROUTES}:{at(src, 'loadControllers')}" in sites


def test_vapor_controllers_array_loop_registers_each(tmp_path):
    vapor_package(tmp_path)
    write(
        tmp_path,
        "Sources/App/Ctl.swift",
        """import Vapor
struct A: RouteCollection {
    func boot(routes: RoutesBuilder) throws { routes.get("a") { r in "x" } }
}
struct B: RouteCollection {
    func boot(routes: RoutesBuilder) throws { routes.get("b") { r in "x" } }
}
""",
    )
    write(
        tmp_path,
        ROUTES,
        """import Vapor
func routes(_ app: Application) throws {
    let controllers: [RouteCollection] = [A(), B()]
    for controller in controllers {
        try app.register(collection: controller)
    }
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/a"), ("GET", "/b")]
    assert verdict(result) == ("complete", "")


# --- helpers, the application as a property -------------------------------------


def test_vapor_helpers_receive_the_callers_prefix(tmp_path):
    src = """import Vapor

func routes(_ app: Application) throws {
    let api = app.grouped("api")
    addUsers(api)
    try registerPosts(on: api.grouped("blog"))
    add(genericOn: app.grouped("gen"))
}
func addUsers(_ r: RoutesBuilder) {
    r.get("users") { req in "u" }
}
func registerPosts(on router: any RoutesBuilder) throws {
    router.get("posts") { req in "p" }
    addUsers(router)
}
func add<R: RoutesBuilder>(genericOn r: R) {
    r.get("g") { req in "g" }
}
"""
    vapor_app(tmp_path, src)
    result = run_routes(tmp_path)
    assert pairs(result) == by_path(
        [
            ("GET", "/api/users"),
            ("GET", "/api/blog/posts"),
            ("GET", "/api/blog/users"),
            ("GET", "/gen/g"),
        ]
    )
    assert verdict(result) == ("complete", "")


def test_vapor_helper_never_called_and_unfollowable_calls_are_sites(tmp_path):
    src = """import Vapor
import OtherLib

func routes(_ app: Application) throws {
    OtherLib.install(app)
    mystery(app)
    ambiguous(app)
}
func unused(_ r: RoutesBuilder) {
    r.get("unused") { req in "x" }
}
func ambiguous(_ a: Application) {}
func ambiguous(_ b: Application, extra: Int = 0) {}
"""
    vapor_app(tmp_path, src)
    result = run_routes(tmp_path)
    assert pairs(result) == []
    status, detail = verdict(result)
    assert status == "partial"
    sites = detail.split("; ")
    assert f"{ROUTES}:{at(src, 'OtherLib.install')}" in sites
    assert f"{ROUTES}:{at(src, 'mystery')}" in sites
    assert f"{ROUTES}:{at(src, 'ambiguous(app)')}" in sites
    unused = at(src, 'r.get("unused")')
    assert f"{ROUTES}:{unused}" in sites


def test_vapor_application_property_and_top_level_script(tmp_path):
    vapor_package(tmp_path)
    write(
        tmp_path,
        "Sources/App/Server.swift",
        """import Vapor
final class Server {
    let app: Application
    init(app: Application) { self.app = app }
    func setup() {
        app.get("prop") { req in "p" }
        self.app.grouped("g").get("self") { req in "s" }
    }
}
""",
    )
    write(
        tmp_path,
        "Sources/Run/main.swift",
        """import Vapor
var env = try Environment.detect()
let app = try await Application.make(env)
defer { app.shutdown() }
app.get("script") { req in "x" }
try app.run()
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == by_path(
        [("GET", "/g/self"), ("GET", "/prop"), ("GET", "/script")]
    )
    assert verdict(result) == ("complete", "")


# --- partial: dynamic paths --------------------------------------------------------


def test_vapor_dynamic_path_partial(tmp_path):
    src = """import Vapor

let apiPrefix: PathComponent = "api"

func routes(_ app: Application) throws {
    let version = Environment.get("API_VERSION") ?? "v1"
    app.get("static") { req in "x" }
    app.get("dyn\\(version)") { req in "x" }
    app.get("a" + version) { req in "x" }
    app.get(apiPrefix) { req in "x" }
    app.grouped(apiPrefix).get("g") { req in "x" }
    app.grouped("p\\(version)").get("h") { req in "x" }
    app.get(PathComponent(stringLiteral: version)) { req in "x" }
    app.get("nohandler")
}
"""
    vapor_app(tmp_path, src)
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/static")]
    status, detail = verdict(result)
    assert status == "partial"
    assert sorted(detail.split("; ")) == sorted(
        f"{ROUTES}:{at(src, needle)}"
        for needle in (
            "dyn\\(",
            '"a" + version',
            "get(apiPrefix)",
            "grouped(apiPrefix)",
            'grouped("p',
            "stringLiteral",
            "nohandler",
        )
    )


def test_vapor_local_string_constants_resolve(tmp_path):
    vapor_app(
        tmp_path,
        """import Vapor
func routes(_ app: Application) throws {
    let base: PathComponent = "base"
    let parts = ["x", ":y"]
    app.grouped(base).get(parts) { req in "x" }
    var mutable = "m"
    mutable = "n"
    app.get(mutable) { req in "x" }
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/base/x/:y")]
    assert verdict(result)[0] == "partial"


# --- typical apps (README / template) reach complete ----------------------------------


def test_typical_vapor_template_app_reaches_complete(tmp_path):
    vapor_package(tmp_path)
    write(
        tmp_path,
        "Sources/App/entrypoint.swift",
        """import Vapor
import Logging
import NIOCore
import NIOPosix

@main
enum Entrypoint {
    static func main() async throws {
        var env = try Environment.detect()
        try LoggingSystem.bootstrap(from: &env)

        let app = try await Application.make(env)

        // let executorTakeoverSuccess = NIOSingletons.unsafeTryInstallSingletonPosixEventLoopGroupAsConcurrencyGlobalExecutor()
        do {
            try await configure(app)
            try await app.execute()
        } catch {
            app.logger.report(error: error)
            try? await app.asyncShutdown()
            throw error
        }
        try await app.asyncShutdown()
    }
}
""",
    )
    write(
        tmp_path,
        "Sources/App/configure.swift",
        """import NIOSSL
import Fluent
import FluentSQLiteDriver
import Leaf
import Vapor

// configures your application
public func configure(_ app: Application) async throws {
    // uncomment to serve files from /Public folder
    // app.middleware.use(FileMiddleware(publicDirectory: app.directory.publicDirectory))
    app.middleware.use(CORSMiddleware(configuration: .init(
        allowedOrigin: .all, allowedMethods: [.GET, .POST, .PUT, .OPTIONS, .DELETE, .PATCH],
        allowedHeaders: [.accept, .authorization, .contentType])))
    app.middleware.use(ErrorMiddleware.default(environment: app.environment))
    app.databases.use(DatabaseConfigurationFactory.sqlite(.file("db.sqlite")), as: .sqlite)
    app.migrations.add(CreateTodo())
    app.views.use(.leaf)
    app.jwt.signers.use(.hs256(key: Environment.get("JWT_SECRET") ?? "dev-secret-do-not-ship"))
    app.http.server.configuration.port = Int(Environment.get("PORT") ?? "8080") ?? 8080
    app.routes.defaultMaxBodySize = "10mb"
    app.queues.use(.redis(url: Environment.get("REDIS_URL") ?? "redis://localhost"))
    app.lifecycle.use(Warmup())

    // register routes
    try routes(app)
}
""",
    )
    write(
        tmp_path,
        ROUTES,
        """import Fluent
import Vapor

func routes(_ app: Application) throws {
    app.get { req async in
        try await req.view.render("index", ["title": "Hello Vapor!"])
    }

    app.get("hello") { req async -> String in
        "Hello, world!"
    }

    app.get("health") { req async throws -> HTTPStatus in
        _ = try await req.client.get("https://upstream.example/ping")
        let res = try await req.client.post("https://upstream.example/hook") { out in
            try out.content.encode(["ok": true])
        }
        return res.status
    }

    let protected = app.grouped(UserAuthenticator()).grouped(User.guardMiddleware())
    protected.get("me") { req async throws -> User in try req.auth.require(User.self) }

    try app.register(collection: TodoController())
    try app.grouped("api").register(collection: AccountController())
}
""",
    )
    write(
        tmp_path,
        "Sources/App/Controllers/TodoController.swift",
        """import Fluent
import Vapor

struct TodoController: RouteCollection {
    func boot(routes: any RoutesBuilder) throws {
        let todos = routes.grouped("todos")

        todos.get(use: self.index)
        todos.post(use: self.create)
        todos.group(":todoID") { todo in
            todo.delete(use: self.delete)
        }
    }

    @Sendable
    func index(req: Request) async throws -> [TodoDTO] {
        try await Todo.query(on: req.db).group(.or) { group in
            group.filter(\\.$title == "a").filter(\\.$title == "b")
        }.all().map { $0.toDTO() }
    }

    @Sendable
    func create(req: Request) async throws -> TodoDTO {
        let todo = try req.content.decode(TodoDTO.self).toModel()

        try await todo.save(on: req.db)
        return todo.toDTO()
    }

    @Sendable
    func delete(req: Request) async throws -> HTTPStatus {
        guard let todo = try await Todo.find(req.parameters.get("todoID"), on: req.db) else {
            throw Abort(.notFound)
        }

        try await todo.delete(on: req.db)
        return .noContent
    }
}
""",
    )
    write(
        tmp_path,
        "Sources/App/Controllers/AccountController.swift",
        """import Vapor

struct AccountController: RouteCollection {
    func boot(routes: RoutesBuilder) throws {
        let accounts = routes.grouped("accounts")
        accounts.post("login", use: login)
        let secured = accounts.grouped(JWTMiddleware())
        secured.get(":id", use: show)
        secured.put(":id", use: update)
    }
    func login(req: Request) async throws -> String {
        let cache = req.application.cache
        _ = try await cache.get("k", as: String.self)
        return try await req.redis.get("k", as: String.self) ?? ""
    }
    func show(req: Request) async throws -> String { "" }
    func update(req: Request) async throws -> String { "" }
}
""",
    )
    write(
        tmp_path,
        "Sources/App/Middleware/UserAuthenticator.swift",
        """import Vapor

struct UserAuthenticator: AsyncBearerAuthenticator {
    func authenticate(bearer: BearerAuthorization, for request: Request) async throws {
        if bearer.token == "x" { request.auth.login(User()) }
    }
}
""",
    )
    write(
        tmp_path,
        "Sources/App/Models/Todo.swift",
        """import Fluent
import Vapor

final class Todo: Model, @unchecked Sendable {
    static let schema = "todos"
    @ID(key: .id) var id: UUID?
    @Field(key: "title") var title: String
    init() {}
}
""",
    )
    write(
        tmp_path,
        "Sources/App/Migrations/CreateTodo.swift",
        """import Fluent

struct CreateTodo: AsyncMigration {
    func prepare(on database: Database) async throws {
        try await database.schema("todos").id().field("title", .string, .required).create()
    }
    func revert(on database: Database) async throws {
        try await database.schema("todos").delete()
    }
}
""",
    )
    result = run_routes(tmp_path)
    assert triples(result) == [
        ("GET", "/", "(inline)"),
        ("GET", "/api/accounts/:id", "AccountController.show"),
        ("PUT", "/api/accounts/:id", "AccountController.update"),
        ("POST", "/api/accounts/login", "AccountController.login"),
        ("GET", "/health", "(inline)"),
        ("GET", "/hello", "(inline)"),
        ("GET", "/me", "(inline)"),
        ("GET", "/todos", "TodoController.index"),
        ("POST", "/todos", "TodoController.create"),
        ("DELETE", "/todos/:todoID", "TodoController.delete"),
    ]
    assert verdict(result) == ("complete", "")
