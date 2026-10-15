"""Go: Gin routes -- same-named APIs, other routers, hostile input and a
typical app."""

from __future__ import annotations

import pytest

pytest.importorskip("tree_sitter_language_pack")

from strata_kb.lintcore import table_rows
from tests.go_support import (
    MAIN,
    at,
    everything,
    gin_app,
    gomod,
    pairs,
    row,
    run_routes,
    verdict,
    write,
)

# --- collisions --------------------------------------------------------------


def test_gin_non_route_get_calls_are_ignored(tmp_path):
    gin_app(
        tmp_path,
        """package main

import (
	"net/http"
	"github.com/gin-gonic/gin"
	"github.com/go-resty/resty/v2"
)

type Client struct{ base string }

func (c *Client) GET(path string, out interface{}) error { return nil }

func fetch(c *Client, rc *resty.Client) {
	resp, _ := http.Get("https://example.com/health")
	_ = resp
	r := resty.New()
	r.R().Get("/orders")
	rc.R().SetBody(1).Post("/orders")
	c.GET("/api/users", nil)
	e := httpexpect.New(t, "http://x")
	e.GET("/users").Expect().Status(200)
	rc.GET("/legacy", cb)
}

func handler(c *gin.Context) {
	user, _ := c.Get("user")
	c.JSON(200, user)
	val := rdb.Get(ctx, "key")
	_ = val
	c.Request.Header.Get("X-Id")
}

func main() {
	app := gin.Default()
	app.GET("/ok", handler)
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/ok")]
    assert verdict(result) == ("complete", "")


def test_gin_route_shaped_call_on_unresolved_receiver_is_a_site(tmp_path):
    src = """package main

import "github.com/gin-gonic/gin"

func register(thing Thing) {
	thing.GET("/lost", lostHandler)
	thing.Group("/lost-group")
}

func main() {
	r := gin.Default()
	r.GET("/ok", ok)
}
"""
    gin_app(tmp_path, src)
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/ok")]
    assert verdict(result) == (
        "partial",
        f"{MAIN}:{at(src, 'thing.GET')}; {MAIN}:{at(src, 'thing.Group')}",
    )


def test_gin_other_routers_in_a_gin_scope_are_sites(tmp_path):
    src = """package main

import (
	"net/http"
	"github.com/gin-gonic/gin"
	"github.com/go-chi/chi/v5"
	"github.com/labstack/echo/v4"
	"github.com/gorilla/mux"
)

func main() {
	r := gin.Default()
	r.GET("/gin", ginH)

	http.HandleFunc("/std", stdH)
	m := http.NewServeMux()
	m.HandleFunc("GET /items/{id}", itemH)
	m.Handle("/metrics", promH)

	cr := chi.NewRouter()
	cr.Get("/chi", chiH)
	cr.Route("/api", func(r chi.Router) { r.Get("/x", x) })

	e := echo.New()
	e.GET("/echo", echoH)
	eg := e.Group("/eg")
	eg.POST("/y", y)

	gm := mux.NewRouter()
	gm.HandleFunc("/gorilla", gH).Methods("GET")
	gm.PathPrefix("/p").Handler(ph)
}
"""
    gin_app(tmp_path, src)
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/gin")]
    status, detail = verdict(result)
    assert status == "partial"
    sites = set(detail.split("; "))
    for needle in (
        'http.HandleFunc("/std"',
        "m.HandleFunc",
        "m.Handle(",
        "cr.Get",
        "cr.Route",
        "e.GET",
        "e.Group",
        "eg.POST",
        "gm.HandleFunc",
        "gm.PathPrefix",
    ):
        assert f"{MAIN}:{at(src, needle)}" in sites, needle


def test_gin_ordinary_http_server_calls_are_not_sites(tmp_path):
    gin_app(
        tmp_path,
        """package main

import (
	"net/http"
	"github.com/gin-gonic/gin"
)

func main() {
	r := gin.Default()
	r.GET("/ok", ok)
	srv := &http.Server{Addr: ":8080", Handler: r}
	go srv.ListenAndServe()
	http.ListenAndServe(":9090", r)
	log.Println(http.StatusOK)
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/ok")]
    assert verdict(result) == ("complete", "")


# --- files, hostile input ----------------------------------------------------


def test_gin_test_files_and_testdata_are_skipped(tmp_path):
    gin_app(
        tmp_path,
        'package main\n\nimport "github.com/gin-gonic/gin"\n\n'
        'func main() { r := gin.Default(); r.GET("/ok", ok) }\n',
    )
    write(
        tmp_path,
        "main_test.go",
        'package main\n\nfunc TestX() { r := gin.New(); r.GET("/test-only", h); thing.GET("/t", h) }\n',
    )
    write(
        tmp_path,
        "testdata/app.go",
        'package main\n\nfunc main() { r := gin.New(); r.GET("/fixture", h) }\n',
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/ok")]
    assert verdict(result) == ("complete", "")


def test_gin_unparsable_file_is_a_site(tmp_path):
    gin_app(tmp_path, "package main\n\nfunc main( {\n  r := gin.Default(\n")
    result = run_routes(tmp_path)
    assert row(result).status == "partial"
    assert row(result).detail.startswith(f"{MAIN}:")


def test_gin_hostile_nesting_does_not_crash(tmp_path):
    depth = 4000
    src = (
        'package main\n\nimport "github.com/gin-gonic/gin"\n\nfunc main() {\n'
        "\tr := gin.Default()\n"
        + "\tif x {\n" * depth
        + '\tr.GET("/deep", h)\n'
        + "\t}\n" * depth
        + "}\n"
    )
    gin_app(tmp_path, src)
    result = run_routes(tmp_path)
    assert not [w for w in result.warnings if "adapter failed" in w]
    assert pairs(result) == [("GET", "/deep")]
    assert verdict(result) == ("complete", "")


def test_gin_hostile_chain_and_concatenation_do_not_crash(tmp_path):
    chain = ".Use(mw)" * 3000
    concat = " + ".join(['"/a"'] * 3000)
    gin_app(
        tmp_path,
        'package main\n\nimport "github.com/gin-gonic/gin"\n\nfunc main() {\n'
        f'\tr := gin.Default()\n\tr{chain}.GET("/chain", h)\n'
        f"\tr.GET({concat}, h)\n}}\n",
    )
    result = run_routes(tmp_path)
    assert not [w for w in result.warnings if "adapter failed" in w]
    assert ("GET", "/chain") in pairs(result)


def test_gin_scopes_do_not_share_files(tmp_path):
    gomod(tmp_path, "svc-a", "example.com/a")
    gomod(tmp_path, "svc-b", "example.com/b")
    write(
        tmp_path,
        "svc-a/main.go",
        'package main\n\nimport "github.com/gin-gonic/gin"\n\n'
        'func main() { r := gin.Default(); r.GET("/a", h) }\n',
    )
    write(
        tmp_path,
        "svc-b/main.go",
        'package main\n\nimport "github.com/gin-gonic/gin"\n\n'
        'func main() { r := gin.Default(); r.GET("/b", h) }\n',
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/a"), ("GET", "/b")]
    assert row(result, "svc-a").status == "complete"
    assert row(result, "svc-b").status == "complete"


def test_gin_handler_column_never_carries_a_literal(tmp_path):
    gin_app(
        tmp_path,
        """package main

import "github.com/gin-gonic/gin"

func main() {
	r := gin.Default()
	r.GET("/a", build("sk_live_GINSECRET"))
	r.GET("/b", handlers["sk_live_INDEXED"])
	r.GET("/c", New("ghp_CALLRECV").Handle)
	r.GET("/d", h.WithKey("ghp_METHOD"))
}
""",
    )
    result = run_routes(tmp_path)
    assert {r[2] for s in result.sections for r in table_rows(s.l2_md)[1:]} == {
        "(inline)"
    }
    blob = everything(result)
    for secret in ("GINSECRET", "INDEXED", "CALLRECV", "METHOD"):
        assert secret not in blob


# --- typical app -------------------------------------------------------------


def test_typical_gin_app_reaches_complete(tmp_path):
    gomod(tmp_path)
    write(
        tmp_path,
        "cmd/server/main.go",
        """package main

import (
	"log"
	"net/http"

	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
	swaggerFiles "github.com/swaggo/files"
	ginSwagger "github.com/swaggo/gin-swagger"
	"go.uber.org/zap"

	"example.com/app/internal/handlers"
	"example.com/app/internal/middleware"
	"example.com/app/internal/store"
)

func main() {
	logger, _ := zap.NewProduction()
	db, err := store.Open("postgres://user:pass@localhost/db")
	if err != nil {
		log.Fatal(err)
	}

	r := gin.New()
	r.Use(gin.Logger(), gin.Recovery(), cors.Default(), middleware.RequestID())
	r.LoadHTMLGlob("web/templates/*")
	r.Static("/static", "./web/static")
	r.NoRoute(func(c *gin.Context) { c.JSON(http.StatusNotFound, gin.H{"error": "not found"}) })

	r.GET("/healthz", func(c *gin.Context) { c.Status(http.StatusOK) })
	r.GET("/swagger/*any", ginSwagger.WrapHandler(swaggerFiles.Handler))

	users := handlers.NewUserHandler(db, logger)
	auth := handlers.NewAuthHandler(db)

	public := r.Group("/api/v1")
	{
		public.POST("/login", auth.Login)
		public.POST("/register", auth.Register)
	}

	authed := r.Group("/api/v1", middleware.JWT(), middleware.RateLimit(100))
	{
		authed.GET("/me", users.Me)
		u := authed.Group("/users")
		u.GET("", users.List)
		u.GET("/:id", users.Get)
		u.PUT("/:id", users.Update)
		u.DELETE("/:id", users.Delete)
		u.GET("/:id/files/*path", users.File)
	}

	admin := authed.Group("/admin", middleware.RequireRole("admin"))
	handlers.RegisterAdmin(admin)

	srv := &http.Server{Addr: ":8080", Handler: r}
	if err := srv.ListenAndServe(); err != nil {
		log.Fatal(err)
	}
}
""",
    )
    write(
        tmp_path,
        "internal/handlers/admin.go",
        """package handlers

import "github.com/gin-gonic/gin"

func RegisterAdmin(rg *gin.RouterGroup) {
	rg.GET("/stats", Stats)
	rg.POST("/reindex", Reindex)
}
""",
    )
    write(
        tmp_path,
        "internal/handlers/users.go",
        """package handlers

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

type UserHandler struct{ db *Store }

func NewUserHandler(db *Store, l *zap.Logger) *UserHandler { return &UserHandler{db: db} }

func (h *UserHandler) Get(c *gin.Context) {
	id := c.Param("id")
	user, err := h.db.Get(id)
	if err != nil {
		c.AbortWithStatusJSON(http.StatusNotFound, gin.H{"error": err.Error()})
		return
	}
	if v, ok := c.Get("tenant"); ok {
		_ = v
	}
	c.JSON(http.StatusOK, user)
}

func (h *UserHandler) List(c *gin.Context) {
	var q struct{ Page int `form:"page"` }
	if err := c.ShouldBindQuery(&q); err != nil {
		c.JSON(400, err)
	}
}
""",
    )
    result = run_routes(tmp_path)
    assert verdict(result) == ("complete", "")
    assert pairs(result) == [
        ("POST", "/api/v1/admin/reindex"),
        ("GET", "/api/v1/admin/stats"),
        ("POST", "/api/v1/login"),
        ("GET", "/api/v1/me"),
        ("POST", "/api/v1/register"),
        ("GET", "/api/v1/users"),
        ("DELETE", "/api/v1/users/:id"),
        ("GET", "/api/v1/users/:id"),
        ("PUT", "/api/v1/users/:id"),
        ("GET", "/api/v1/users/:id/files/*path"),
        ("GET", "/healthz"),
        ("GET", "/swagger/*any"),
    ]
    blob = everything(result)
    assert "pass@localhost" not in blob


def test_gin_operator_expressions_are_not_paths_and_do_not_recurse(tmp_path):
    gin_app(
        tmp_path,
        """package main

import "github.com/gin-gonic/gin"

func main() {
	router := gin.Default()
	router.MaxMultipartMemory = 8 << 20
	limit := 1<<10 - 1
	router.GET("/a"+"/b", h)
	router.GET(limit*2, h)
	router.GET("/ok", h)
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/a/b"), ("GET", "/ok")]
    assert verdict(result) == ("partial", f"{MAIN}:10")


def test_gin_net_http_import_alone_does_not_make_x_get_or_x_handle_sites(tmp_path):
    gin_app(
        tmp_path,
        """package main

import (
	"net/http"
	"github.com/gin-gonic/gin"
)

type Cache interface{ Get(string) string }

func run(cache Cache, svc Service) {
	_ = cache.Get("/k")
	_ = http.StatusOK
	svc.Group("x")
}

func main() {
	r := gin.Default()
	r.GET("/ok", ok)
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/ok")]
    # only the route-shaped svc.Group (line 13); cache.Get is not a router call
    assert verdict(result) == ("partial", f"{MAIN}:13")
