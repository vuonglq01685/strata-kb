"""Go: Gin routes -- verbs, groups, paths, helpers and file order."""

from __future__ import annotations

import pytest

pytest.importorskip("tree_sitter_language_pack")

from tests.go_support import (
    MAIN,
    at,
    gin_app,
    gomod,
    pairs,
    row,
    rows_of,
    run_routes,
    triples,
    verdict,
    write,
)

# --- verbs, handlers ---------------------------------------------------------


def test_gin_verbs_and_handler_forms(tmp_path):
    gin_app(
        tmp_path,
        """package main

import (
	"github.com/gin-gonic/gin"
	"example.com/app/controllers"
)

func main() {
	r := gin.Default()
	h := &Handler{}
	r.GET("/", func(c *gin.Context) { c.String(200, "ok") })
	r.POST("/users", h.Create)
	r.PUT("/users/:id", authRequired(), h.Update)
	r.PATCH("/users/:id", h.Patch)
	r.DELETE("/users/:id", controllers.Delete)
	r.HEAD("/ping", h.Ping)
	r.OPTIONS("/ping", h.Ping)
	r.Any("/any", h.Any)
	r.Handle("GET", "/handled", h.Handled)
	r.GET("/wrapped", wrap(h.Wrapped))
	r.GET(`/raw`, h.Raw)
	r.Run(":8080")
}
""",
    )
    result = run_routes(tmp_path)
    assert rows_of(result, MAIN) == [
        ["GET", "/", "(inline)", MAIN, ""],
        ["ANY", "/any", "h.Any", MAIN, ""],
        ["GET", "/handled", "h.Handled", MAIN, ""],
        ["HEAD", "/ping", "h.Ping", MAIN, ""],
        ["OPTIONS", "/ping", "h.Ping", MAIN, ""],
        ["GET", "/raw", "h.Raw", MAIN, ""],
        ["POST", "/users", "h.Create", MAIN, ""],
        ["DELETE", "/users/:id", "controllers.Delete", MAIN, ""],
        ["PATCH", "/users/:id", "h.Patch", MAIN, ""],
        ["PUT", "/users/:id", "h.Update", MAIN, ""],
        ["GET", "/wrapped", "(inline)", MAIN, ""],
    ]
    assert verdict(result) == ("complete", "")


def test_gin_match_expands_and_bad_handle_method_is_a_site(tmp_path):
    src = """package main

import "github.com/gin-gonic/gin"

func main() {
	r := gin.New()
	r.Match([]string{"GET", "POST"}, "/m", h)
	r.Handle(method, "/dyn", h)
	r.Match(methods, "/dyn2", h)
}
"""
    gin_app(tmp_path, src)
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/m"), ("POST", "/m")]
    assert verdict(result) == (
        "partial",
        f"{MAIN}:{at(src, '/dyn')}; {MAIN}:{at(src, '/dyn2')}",
    )


# --- groups, params ----------------------------------------------------------


def test_gin_group_prefix_and_path_param_table_rows(tmp_path):
    gin_app(
        tmp_path,
        """package main

import "github.com/gin-gonic/gin"

func main() {
	r := gin.Default()
	api := r.Group("/api")
	v1 := api.Group("/v1")
	{
		v1.GET("/users/:id", getUser)
		v1.GET("/files/*path", files)
		users := v1.Group("/users", auth())
		users.POST("", createUser)
		users.GET("/:id/orders/:orderId", orders)
	}
	r.Group("/chained").Group("/deep").GET("/x", deep)
	r.Group("/").GET("/root", rootHandler)
}
""",
    )
    result = run_routes(tmp_path)
    assert rows_of(result, MAIN) == [
        ["GET", "/api/v1/files/*path", "files", MAIN, ""],
        ["POST", "/api/v1/users", "createUser", MAIN, ""],
        ["GET", "/api/v1/users/:id", "getUser", MAIN, ""],
        ["GET", "/api/v1/users/:id/orders/:orderId", "orders", MAIN, ""],
        ["GET", "/chained/deep/x", "deep", MAIN, ""],
        ["GET", "/root", "rootHandler", MAIN, ""],
    ]
    assert verdict(result) == ("complete", "")


def test_gin_group_scopes_and_shadowing(tmp_path):
    gin_app(
        tmp_path,
        """package main

import "github.com/gin-gonic/gin"

func main() {
	r := gin.Default()
	g := r.Group("/a")
	{
		g := r.Group("/b")
		g.GET("/inner", h1)
	}
	g.GET("/outer", h2)
	g = r.Group("/c")
	g.GET("/reassigned", h3)
	authed := r.Group("/d").Use(authRequired())
	authed.GET("/after-use", h4)
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [
        ("GET", "/a/outer"),
        ("GET", "/b/inner"),
        ("GET", "/c/reassigned"),
        ("GET", "/d/after-use"),
    ]
    assert verdict(result) == ("complete", "")


def test_gin_package_const_paths_are_resolved(tmp_path):
    gomod(tmp_path)
    write(
        tmp_path,
        "main.go",
        """package main

import (
	"github.com/gin-gonic/gin"
	"example.com/app/config"
)

func main() {
	r := gin.Default()
	api := r.Group(config.APIPrefix)
	api.GET(usersPath, list)
	api.GET(usersPath+"/:id", get)
	r.GET(Version, ver)
}
""",
    )
    write(
        tmp_path,
        "paths.go",
        "package main\n\n"
        'const usersPath = "/users"\nconst Version string = "/version"\n'
        'const (\n\tbase = "/base"\n\tderived = base + "/derived"\n)\n',
    )
    write(
        tmp_path,
        "derived.go",
        'package main\n\nimport "github.com/gin-gonic/gin"\n\n'
        "func init() { gin.New().GET(derived, d) }\n",
    )
    write(
        tmp_path,
        "config/config.go",
        'package config\n\nconst APIPrefix = "/api/v2"\n',
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [
        ("GET", "/api/v2/users"),
        ("GET", "/api/v2/users/:id"),
        ("GET", "/base/derived"),
        ("GET", "/version"),
    ]
    assert verdict(result) == ("complete", "")


# --- dynamic paths -----------------------------------------------------------


def test_gin_dynamic_path_partial(tmp_path):
    src = """package main

import (
	"fmt"
	"github.com/gin-gonic/gin"
)

var prefix = os.Getenv("PREFIX")

func main() {
	r := gin.Default()
	r.GET("/ok", ok)
	r.GET(fmt.Sprintf("/v%d/x", 2), a)
	r.GET(prefix+"/y", b)
	r.GET(somePath, c)
	g := r.Group(prefix)
	g.GET("/under-dynamic", d)
}
"""
    gin_app(tmp_path, src)
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/ok")]
    expected = sorted(
        f"{MAIN}:{at(src, needle)}"
        for needle in ("Sprintf", "prefix+", "somePath", "Group(prefix)", "under-dyn")
    )
    assert verdict(result) == ("partial", "; ".join(expected))


def test_gin_static_noroute_and_use_are_not_routes_or_sites(tmp_path):
    gin_app(
        tmp_path,
        """package main

import "github.com/gin-gonic/gin"

func main() {
	r := gin.Default()
	r.Use(gin.Logger(), gin.Recovery())
	r.Static("/assets", "./assets")
	r.StaticFS("/more", http.Dir("x"))
	r.StaticFile("/favicon.ico", "./favicon.ico")
	r.LoadHTMLGlob("templates/*")
	r.NoRoute(notFound)
	r.NoMethod(notAllowed)
	r.SetTrustedProxies(nil)
	r.GET("/ping", ping)
	http.ListenAndServe(":8080", r)
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/ping")]
    assert verdict(result) == ("complete", "")


# --- helpers, cross file -----------------------------------------------------


def test_gin_group_passed_to_helper_in_other_file_and_package(tmp_path):
    gomod(tmp_path)
    write(
        tmp_path,
        "main.go",
        """package main

import (
	"github.com/gin-gonic/gin"
	"example.com/app/handlers"
)

func main() {
	r := gin.Default()
	api := r.Group("/api")
	registerUser(api.Group("/users"))
	registerUser(api.Group("/admins"))
	handlers.RegisterOrders(api.Group("/orders"))
	handlers.Setup(r)
}
""",
    )
    write(
        tmp_path,
        "users.go",
        """package main

import "github.com/gin-gonic/gin"

func registerUser(rg *gin.RouterGroup) {
	rg.GET("/:id", getUser)
	rg.POST("", createUser)
}
""",
    )
    write(
        tmp_path,
        "handlers/orders.go",
        """package handlers

import "github.com/gin-gonic/gin"

func RegisterOrders(rg *gin.RouterGroup) {
	rg.GET("/:id", getOrder)
}

func Setup(r *gin.Engine) {
	r.GET("/health", health)
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [
        ("POST", "/api/admins"),
        ("GET", "/api/admins/:id"),
        ("GET", "/api/orders/:id"),
        ("POST", "/api/users"),
        ("GET", "/api/users/:id"),
        ("GET", "/health"),
    ]
    assert verdict(result) == ("complete", "")
    assert {s.title for s in result.sections} == {"users.go", "handlers/orders.go"}


@pytest.mark.parametrize(
    ("registering", "defining"),
    [("a_main.go", "z_users.go"), ("z_main.go", "a_users.go")],
)
def test_gin_registering_file_before_or_after_defining_file(
    tmp_path, registering, defining
):
    gomod(tmp_path)
    write(
        tmp_path,
        registering,
        """package main

import "github.com/gin-gonic/gin"

func main() {
	r := gin.Default()
	register(r.Group("/late"))
	r.GET("/early", early)
}
""",
    )
    write(
        tmp_path,
        defining,
        """package main

import "github.com/gin-gonic/gin"

func register(rg *gin.RouterGroup) {
	rg.GET("/x", x)
}

const unused = "/z"
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/early"), ("GET", "/late/x")]
    assert verdict(result) == ("complete", "")


def test_gin_package_level_router_and_const_in_later_file(tmp_path):
    gomod(tmp_path)
    write(
        tmp_path,
        "a.go",
        """package main

import "github.com/gin-gonic/gin"

var api = router.Group(base)

func init() {
	api.GET("/ping", ping)
}
""",
    )
    write(
        tmp_path,
        "z.go",
        """package main

import "github.com/gin-gonic/gin"

const base = "/svc"

var router = gin.New()
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/svc/ping")]
    assert verdict(result) == ("complete", "")


def test_gin_unresolvable_helper_arguments_are_sites(tmp_path):
    gomod(tmp_path)
    src = """package main

import (
	"github.com/gin-gonic/gin"
	"github.com/gin-contrib/pprof"
)

func main() {
	r := gin.Default()
	pprof.Register(r)
	mystery(r.Group("/m"))
	dup(r.Group("/d"))
	for _, reg := range registrars {
		reg(r.Group("/loop"))
	}
	r.GET("/ok", ok)
}
"""
    write(tmp_path, "main.go", src)
    write(
        tmp_path,
        "a.go",
        'package main\n\nimport "github.com/gin-gonic/gin"\n\n'
        'func dup(rg *gin.RouterGroup) { rg.GET("/a", a) }\n',
    )
    write(
        tmp_path,
        "b.go",
        'package main\n\nimport "github.com/gin-gonic/gin"\n\n'
        'func dup(rg *gin.RouterGroup) { rg.GET("/b", b) }\n',
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/ok")]
    status, detail = verdict(result)
    assert status == "partial"
    sites = set(detail.split("; "))
    for needle in ("pprof.Register", "mystery", "dup(", "reg(r.Group"):
        assert f"{MAIN}:{at(src, needle)}" in sites


def test_gin_helper_never_called_is_a_site_at_its_declaration(tmp_path):
    gomod(tmp_path)
    src = """package main

import "github.com/gin-gonic/gin"

func main() {
	r := gin.Default()
	r.GET("/ok", ok)
}

func orphan(rg *gin.RouterGroup) {
	rg.GET("/lost", lost)
}

func harmless(rg *gin.RouterGroup) {
	rg.Use(mw)
}
"""
    write(tmp_path, "main.go", src)
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/ok")]
    assert verdict(result) == ("partial", f"{MAIN}:{at(src, 'func orphan')}")


def test_gin_recursive_helper_does_not_loop(tmp_path):
    gin_app(
        tmp_path,
        """package main

import "github.com/gin-gonic/gin"

func main() {
	r := gin.Default()
	nest(r.Group("/n"))
}

func nest(rg *gin.RouterGroup) {
	rg.GET("/leaf", leaf)
	nest(rg.Group("/n"))
}
""",
    )
    result = run_routes(tmp_path)
    assert ("GET", "/n/leaf") in pairs(result)
    assert row(result).status == "partial"


def test_gin_struct_field_router_and_constructor(tmp_path):
    gomod(tmp_path)
    write(
        tmp_path,
        "server.go",
        """package main

import "github.com/gin-gonic/gin"

type Server struct {
	router *gin.Engine
	users  *UserHandler
}

func NewServer() *Server {
	s := &Server{router: gin.New(), users: &UserHandler{}}
	s.routes()
	return s
}

func (s *Server) routes() {
	s.router.GET("/healthz", s.health)
	api := s.router.Group("/api")
	api.GET("/users/:id", s.users.Get)
}
""",
    )
    result = run_routes(tmp_path)
    assert triples(result) == [
        ("GET", "/api/users/:id", "s.users.Get"),
        ("GET", "/healthz", "s.health"),
    ]
    assert verdict(result) == ("complete", "")


def test_gin_function_returning_engine_is_a_root(tmp_path):
    gin_app(
        tmp_path,
        """package main

import "github.com/gin-gonic/gin"

func SetupRouter() *gin.Engine {
	r := gin.Default()
	r.GET("/a", a)
	return r
}

func main() {
	r := SetupRouter()
	r.GET("/b", b)
	r.Run()
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/a"), ("GET", "/b")]
    assert verdict(result) == ("complete", "")


def test_gin_aliased_import_and_layout_proof_chains(tmp_path):
    gin_app(
        tmp_path,
        """package main

import g "github.com/gin-gonic/gin"

func main() {
	r := g.Default()
	r.
		Group("/wrapped").
		// comment between
		Use(mw()).
		GET("/chain",
			mw2(),
			handler,
		)
	r .   POST  ( "/spaced" , handler )
	r.GET(
		"/multi",
		h,
	)
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [
        ("GET", "/multi"),
        ("POST", "/spaced"),
        ("GET", "/wrapped/chain"),
    ]
    assert verdict(result) == ("complete", "")


def test_gin_methods_on_handler_types_aliased_import_and_subdir_module(tmp_path):
    gomod(tmp_path, "apps/api", "example.com/api")
    main_src = """package main

import (
	"github.com/gin-gonic/gin"
	hd "example.com/api/handlers_v2"
)

func main() {
	r := gin.Default()
	users := hd.NewUserHandler()
	orders := hd.NewOrderHandler()
	api := r.Group("/api")
	users.Register(api.Group("/users"))
	orders.Register(api.Group("/orders"))
	var reg Registrar = users
	reg.Register(api.Group("/dynamic"))
}

type Registrar interface{ Register(rg *gin.RouterGroup) }
"""
    write(tmp_path, "apps/api/main.go", main_src)
    write(
        tmp_path,
        "apps/api/handlers_v2/handlers.go",
        """package handlers

import "github.com/gin-gonic/gin"

type UserHandler struct{}

func NewUserHandler() *UserHandler { return &UserHandler{} }

func (h *UserHandler) Register(rg *gin.RouterGroup) { rg.GET("/:id", h.Get) }

type OrderHandler struct{}

func NewOrderHandler() *OrderHandler { return &OrderHandler{} }

func (h *OrderHandler) Register(rg *gin.RouterGroup) { rg.POST("", h.Create) }
""",
    )
    result = run_routes(tmp_path)
    assert triples(result) == [
        ("POST", "/api/orders", "h.Create"),
        ("GET", "/api/users/:id", "h.Get"),
    ]
    # the interface-typed call cannot be followed: it is a site, not silent
    assert verdict(result, "apps/api") == (
        "partial",
        f"apps/api/main.go:{at(main_src, 'reg.Register')}",
    )


def test_gin_embedded_engine_and_group_field_used_in_another_method(tmp_path):
    gin_app(
        tmp_path,
        """package main

import "github.com/gin-gonic/gin"

type App struct {
	*gin.Engine
	api *gin.RouterGroup
}

func New() *App {
	a := &App{Engine: gin.New()}
	a.api = a.Group("/api")
	a.api.GET("/same-function", sameFunction)
	return a
}

func (a *App) routes() {
	a.GET("/embedded", embedded)
	a.api.GET("/other-function", otherFunction)
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/api/same-function"), ("GET", "/embedded")]
    # `a.api` is only known inside New(): the other method's route is a site
    assert verdict(result) == ("partial", f"{MAIN}:19")


def test_gin_net_http_method_constants_in_handle_and_match(tmp_path):
    gin_app(
        tmp_path,
        """package main

import (
	"net/http"
	"github.com/gin-gonic/gin"
)

func main() {
	r := gin.New()
	r.Handle(http.MethodPost, "/h", h)
	r.Match([]string{http.MethodGet, http.MethodHead}, "/m", h)
	r.Handle(http.MethodNope, "/bad", h)
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("POST", "/h"), ("GET", "/m"), ("HEAD", "/m")]
    assert verdict(result) == ("partial", f"{MAIN}:12")


def test_gin_dot_import_and_unimported_gin_never_drop_routes_silently(tmp_path):
    gin_app(
        tmp_path,
        """package main

import . "github.com/gin-gonic/gin"

func main() {
	r := Default()
	r.GET("/dot", h)
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == []
    assert verdict(result) == ("partial", f"{MAIN}:7")


def test_gin_group_without_leading_slash_and_repeated_registration(tmp_path):
    gin_app(
        tmp_path,
        """package main

import "github.com/gin-gonic/gin"

func main() {
	r := gin.Default()
	v1 := r.Group("v1")
	v1.GET("users/:id", get)
	both(v1)
	both(v1)
}

func both(rg *gin.RouterGroup) { rg.GET("both", b) }
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/v1/both"), ("GET", "/v1/users/:id")]
    assert verdict(result) == ("complete", "")


def test_gin_router_variable_of_another_package(tmp_path):
    gomod(tmp_path)
    write(
        tmp_path,
        "app/app.go",
        """package app

import "github.com/gin-gonic/gin"

const Prefix = "/svc"

var Router = gin.New()
var Api = Router.Group(Prefix)
""",
    )
    write(
        tmp_path,
        "main.go",
        """package main

import "example.com/app/app"

func main() {
	app.Router.GET("/root", root)
	app.Api.GET("/inner", inner)
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/root"), ("GET", "/svc/inner")]
    assert verdict(result) == ("complete", "")
