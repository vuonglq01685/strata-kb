"""Go: Gin routes -- provenance of values, unresolved receivers, package
variables and method values (never a silent drop)."""

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
    run_routes,
    verdict,
    write,
)


def test_gin_value_from_an_external_package_is_unknown_never_a_non_gin_type(tmp_path):
    src = """package main

import (
	"github.com/gin-gonic/gin"
	"github.com/acme/platform/httpserver"
)

func main() {
	r := httpserver.NewGinEngine("svc")
	r.GET("/users/:id", getUser)
	api := r.Group("/api")
	api.POST("/orders", createOrder)
	srv := httpserver.New()
	srv.Router().POST("/users", create)
	_ = gin.H{}
}
"""
    gin_app(tmp_path, src)
    result = run_routes(tmp_path)
    assert pairs(result) == []
    wanted = [at(src, n) for n in ("r.GET", "r.Group", "api.POST", "srv.Router")]
    assert verdict(result) == (
        "partial",
        "; ".join(f"{MAIN}:{n}" for n in sorted(wanted)),
    )


@pytest.mark.parametrize("shared_first", [True, False])
def test_gin_engine_factory_in_a_go_work_sibling_module_is_a_site(
    tmp_path, shared_first
):
    shared, svc = ("a-shared", "z-svc") if shared_first else ("z-shared", "a-svc")
    gomod(tmp_path, shared, "example.com/shared")
    gomod(tmp_path, svc, "example.com/svc")
    write(tmp_path, "go.work", f"go 1.22\n\nuse (\n\t./{shared}\n\t./{svc}\n)\n")
    write(
        tmp_path,
        f"{shared}/server/server.go",
        'package server\n\nimport "github.com/gin-gonic/gin"\n\n'
        "func NewEngine() *gin.Engine { return gin.New() }\n\n"
        'func RegisterCommon(rg *gin.RouterGroup) { rg.GET("/healthz", health) }\n',
    )
    src = """package main

import "example.com/shared/server"

func main() {
	r := server.NewEngine()
	r.GET("/orders", list)
	server.RegisterCommon(r.Group("/api"))
}
"""
    write(tmp_path, f"{svc}/main.go", src)
    result = run_routes(tmp_path)
    assert verdict(result, svc) == (
        "partial",
        f"{svc}/main.go:{at(src, 'r.GET')}; {svc}/main.go:{at(src, 'r.Group')}",
    )


@pytest.mark.parametrize(
    "body",
    [
        'r := Default()\n\tr.GET("", h)\n\tr.GET("users", h)',
        'groups := map[string]*gin.RouterGroup{}\n\tgroups["v1"].GET("", list)',
        'var g Unknown\n\tg.POST("users", create)',
    ],
)
def test_gin_empty_or_relative_path_on_an_unresolved_receiver_is_a_site(tmp_path, body):
    gin_app(
        tmp_path,
        'package main\n\nimport . "github.com/gin-gonic/gin"\n\n'
        "func main() {\n\t" + body + "\n}\n",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == []
    assert row(result).status == "partial"


def test_gin_empty_path_joins_the_group_prefix_and_type_alias_groups_resolve(tmp_path):
    gin_app(
        tmp_path,
        """package main

import "github.com/gin-gonic/gin"

type RG = *gin.RouterGroup

func register(g RG) {
	g.GET("", list)
	g.GET("x", one)
}

func main() {
	r := gin.Default()
	users := r.Group("/users")
	users.GET("", all)
	register(r.Group("/api"))
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [
        ("GET", "/api"),
        ("GET", "/api/x"),
        ("GET", "/users"),
    ]
    assert verdict(result) == ("complete", "")


@pytest.mark.parametrize(
    "param",
    ["x any", "g Router"],
)
def test_gin_router_passed_into_an_unrecognised_param_type_is_a_site(tmp_path, param):
    src = f"""package main

import "github.com/gin-gonic/gin"

type Router interface {{
	GET(string, ...gin.HandlerFunc) gin.IRoutes
}}

func register({param}) {{}}

func main() {{
	r := gin.Default()
	register(r.Group("/api"))
}}
"""
    gin_app(tmp_path, src)
    result = run_routes(tmp_path)
    assert verdict(result) == ("partial", f"{MAIN}:{at(src, 'register(r.Group')}")


@pytest.mark.parametrize("order", [("a.go", "b.go"), ("b.go", "a.go")])
def test_gin_package_var_written_in_a_function_is_file_order_independent(
    tmp_path, order
):
    init, use = order
    gomod(tmp_path)
    write(
        tmp_path,
        init,
        'package main\n\nimport "github.com/gin-gonic/gin"\n\n'
        'var api *gin.RouterGroup\n\nfunc init() { api = gin.New().Group("/v1") }\n',
    )
    write(
        tmp_path,
        use,
        'package main\n\nfunc routes() { api.GET("/users", list) }\n',
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/v1/users")]
    assert verdict(result) == ("complete", "")


@pytest.mark.parametrize("order", [("a.go", "b.go"), ("b.go", "a.go")])
def test_gin_package_var_with_conflicting_writes_is_a_site_in_both_orders(
    tmp_path, order
):
    first, second = order
    gomod(tmp_path)
    write(
        tmp_path,
        first,
        'package main\n\nimport "github.com/gin-gonic/gin"\n\n'
        'var api = gin.New().Group("/old")\n\nfunc setup() { api = gin.New().Group("/new") }\n',
    )
    write(
        tmp_path,
        second,
        'package main\n\nfunc routes() { api.GET("/users", list) }\n',
    )
    result = run_routes(tmp_path)
    assert pairs(result) == []
    assert verdict(result) == ("partial", f"{second}:3")


def test_gin_local_assignment_never_leaks_into_the_package_var(tmp_path):
    gin_app(
        tmp_path,
        """package main

import "github.com/gin-gonic/gin"

var api = gin.New().Group("/pkg")

func other() {
	api := gin.New().Group("/local")
	api.GET("/l", l)
}

func main() { api.GET("/p", p) }
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/local/l"), ("GET", "/pkg/p")]
    assert verdict(result) == ("complete", "")


def test_gin_router_method_taken_as_a_value_is_a_site(tmp_path):
    src = """package main

import "github.com/gin-gonic/gin"

func add(f func(string, ...gin.HandlerFunc) gin.IRoutes, p string, h gin.HandlerFunc) { f(p, h) }

func main() {
	r := gin.Default()
	get := r.GET
	get("/via-value", h)
	add(r.POST, "/via-helper", h)
	r.GET("/ok", ok)
}
"""
    gin_app(tmp_path, src)
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/ok")]
    assert verdict(result) == (
        "partial",
        "; ".join(
            sorted(f"{MAIN}:{at(src, n)}" for n in ("get := r.GET", "add(r.POST"))
        ),
    )


def test_gin_package_var_chain_deeper_than_four_resolves_in_reverse_file_order(
    tmp_path,
):
    gomod(tmp_path)
    write(
        tmp_path,
        "a.go",
        'package main\n\nfunc init() { v9.GET("/deep", h) }\n',
    )
    chain = "".join(
        f'var v{i} = v{i - 1}.Group("/{i}")\n' for i in range(9, 0, -1) if i > 1
    )
    write(
        tmp_path,
        "z.go",
        'package main\n\nimport "github.com/gin-gonic/gin"\n\nvar v1 = gin.New()\n'
        + chain,
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/2/3/4/5/6/7/8/9/deep")]
    assert verdict(result) == ("complete", "")
