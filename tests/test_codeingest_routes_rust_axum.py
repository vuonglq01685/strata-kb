"""Rust: Axum routes -- Router::route, nest, merge, modules, with_state."""

from __future__ import annotations

import pytest

pytest.importorskip("tree_sitter_language_pack")

from tests.rust_support import (
    MAIN,
    app,
    at,
    cargo,
    everything,
    pairs,
    row,
    rows_of,
    run_routes,
    triples,
    verdict,
    write,
)

AXUM = "axum"

# --- typical app --------------------------------------------------------------

TYPICAL_MAIN = """use std::{net::SocketAddr, sync::Arc};

use axum::{extract::State, middleware, routing::get, Router};
use tower_http::{cors::CorsLayer, services::ServeDir, trace::TraceLayer};

mod api;
mod error;
mod state;
mod web;

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt::init();
    let secret = std::env::var("JWT_SECRET").expect("secret");
    let state = Arc::new(state::AppState::new(secret).await);

    let app = Router::new()
        .route("/", get(web::index))
        .route("/health", get(|| async { "ok" }))
        .nest("/api", api::routes(state.clone()))
        .merge(web::pages())
        .nest_service("/assets", ServeDir::new("assets"))
        .layer(TraceLayer::new_for_http())
        .layer(CorsLayer::permissive())
        .layer(middleware::from_fn(web::request_id))
        .fallback(web::not_found)
        .with_state(state);

    let addr = SocketAddr::from(([0, 0, 0, 0], 3000));
    let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
    axum::serve(listener, app).with_graceful_shutdown(shutdown()).await.unwrap();
}

async fn shutdown() {
    tokio::signal::ctrl_c().await.ok();
}
"""

TYPICAL_API = """use std::sync::Arc;

use axum::{
    middleware,
    routing::{delete, get, post},
    Router,
};

use crate::state::AppState;

mod items;
mod users;

pub fn routes(state: Arc<AppState>) -> Router<Arc<AppState>> {
    Router::new()
        .nest("/users", users::routes())
        .route(
            "/items/:id",
            get(items::show).put(items::update).delete(items::remove),
        )
        .route_layer(middleware::from_fn_with_state(state, crate::web::auth))
}
"""

TYPICAL_USERS = """use axum::{
    extract::{Path, State},
    routing::{get, post},
    Json, Router,
};

use crate::state::AppState;

pub fn routes() -> Router<std::sync::Arc<AppState>> {
    Router::new()
        .route("/", get(list).post(create))
        .route("/:id", get(show))
}

async fn list(State(s): State<std::sync::Arc<AppState>>) -> Json<Vec<u8>> { Json(vec![]) }
async fn create(Json(body): Json<NewUser>) {}
async fn show(Path(id): Path<u32>) {}
"""

TYPICAL_ITEMS = """pub async fn show() {}
pub async fn update() {}
pub async fn remove() {}
"""

TYPICAL_WEB = """use axum::{routing::get, Router};

pub async fn index() {}
pub async fn about() {}
pub async fn not_found() {}
pub async fn request_id() {}
pub async fn auth() {}

pub fn pages() -> Router<std::sync::Arc<crate::state::AppState>> {
    Router::new().route("/about", get(about))
}
"""


def test_typical_axum_app_reaches_complete(tmp_path):
    app(tmp_path, AXUM, TYPICAL_MAIN)
    write(tmp_path, "src/api/mod.rs", TYPICAL_API)
    write(tmp_path, "src/api/users.rs", TYPICAL_USERS)
    write(tmp_path, "src/api/items.rs", TYPICAL_ITEMS)
    write(tmp_path, "src/web.rs", TYPICAL_WEB)
    write(tmp_path, "src/state.rs", "pub struct AppState;\n")
    write(tmp_path, "src/error.rs", "pub enum Error { A }\n")
    result = run_routes(tmp_path)
    assert verdict(result) == ("complete", "")
    assert triples(result) == [
        ("GET", "/", "web::index"),
        ("GET", "/about", "about"),
        ("DELETE", "/api/items/:id", "items::remove"),
        ("GET", "/api/items/:id", "items::show"),
        ("PUT", "/api/items/:id", "items::update"),
        ("GET", "/api/users", "list"),
        ("POST", "/api/users", "create"),
        ("GET", "/api/users/:id", "show"),
        ("GET", "/health", "(inline)"),
    ]
    assert "JWT_SECRET" not in everything(result)


def test_axum_prefix_and_path_param_table_rows_both_param_syntaxes(tmp_path):
    app(
        tmp_path,
        AXUM,
        """use axum::{routing::get, Router};

async fn show() {}
async fn wild() {}

pub fn router() -> Router {
    Router::new().nest(
        "/orders",
        Router::new()
            .route("/:id", get(show))
            .route("/v8/{id}", get(show))
            .route("/files/*rest", get(wild))
            .route("/files8/{*rest}", get(wild)),
    )
}
fn main() { let _ = router(); }
""",
    )
    result = run_routes(tmp_path)
    assert rows_of(result, MAIN) == [
        ["GET", "/orders/:id", "show", MAIN, ""],
        ["GET", "/orders/files/*rest", "wild", MAIN, ""],
        ["GET", "/orders/files8/{*rest}", "wild", MAIN, ""],
        ["GET", "/orders/v8/{id}", "show", MAIN, ""],
    ]
    assert verdict(result) == ("complete", "")


def test_axum_method_router_forms(tmp_path):
    app(
        tmp_path,
        AXUM,
        """use axum::{
    routing::{any, get, on, post, MethodFilter, get_service},
    Router,
};
use axum::routing;
use tower_http::services::{ServeDir, ServeFile};

async fn a() {}
async fn b() {}
async fn c() {}

fn r() -> Router {
    let shared = get(a).post(b);
    Router::new()
        .route("/chain", get(a).post(b).delete(c).patch(c).head(c).options(c))
        .route("/any", any(a))
        .route("/on", on(MethodFilter::GET.or(MethodFilter::POST), a))
        .route("/qual", routing::put(a))
        .route("/full", axum::routing::delete(a))
        .route("/var", shared)
        .route("/new", axum::routing::MethodRouter::new().get(a))
        .route("/svc", get_service(ServeFile::new("index.html")))
        .route_service("/dir", ServeDir::new("x"))
        .route("/layer", get(a).layer(tower::limit::ConcurrencyLimitLayer::new(1)))
        .route("/closure", post(|| async {}))
}
fn main() { let _ = r(); }
""",
    )
    result = run_routes(tmp_path)
    assert verdict(result) == ("complete", "")
    assert triples(result) == [
        ("ANY", "/any", "a"),
        ("DELETE", "/chain", "c"),
        ("GET", "/chain", "a"),
        ("HEAD", "/chain", "c"),
        ("OPTIONS", "/chain", "c"),
        ("PATCH", "/chain", "c"),
        ("POST", "/chain", "b"),
        ("POST", "/closure", "(inline)"),
        ("DELETE", "/full", "a"),
        ("GET", "/layer", "a"),
        ("GET", "/new", "a"),
        ("GET", "/on", "a"),
        ("POST", "/on", "a"),
        ("PUT", "/qual", "a"),
        ("GET", "/var", "a"),
        ("POST", "/var", "b"),
    ]


def test_axum_nest_merge_across_modules_use_paths_and_super(tmp_path):
    cargo(tmp_path, AXUM)
    write(
        tmp_path,
        "src/main.rs",
        """use axum::Router;
mod routes;
use crate::routes::{admin, public as pub_routes};

fn app() -> Router {
    Router::new()
        .merge(pub_routes::router())
        .nest("/admin", admin::router())
        .nest("/v2", routes::v2::router())
}
fn main() { let _ = app(); }
""",
    )
    write(
        tmp_path,
        "src/routes/mod.rs",
        "pub mod admin;\npub mod public;\npub mod v2;\n",
    )
    write(
        tmp_path,
        "src/routes/public.rs",
        """use axum::{routing::get, Router};
pub fn router() -> Router { Router::new().route("/pub", get(super::admin::ping)) }
""",
    )
    write(
        tmp_path,
        "src/routes/admin.rs",
        """use axum::{routing::get, Router};
pub async fn ping() {}
pub fn router() -> Router { Router::new().route("/ping", get(ping)) }
""",
    )
    write(
        tmp_path,
        "src/routes/v2.rs",
        """use axum::{routing::post, Router};
use super::admin::router as admin_router;
pub fn router() -> Router {
    Router::new().route("/make", post(make)).nest("/inner", admin_router())
}
async fn make() {}
""",
    )
    result = run_routes(tmp_path)
    assert verdict(result) == ("complete", "")
    assert triples(result) == [
        ("GET", "/admin/ping", "ping"),
        ("GET", "/pub", "super::admin::ping"),
        ("GET", "/v2/inner/ping", "ping"),
        ("POST", "/v2/make", "make"),
    ]
    # one section per declaring file; the nested route lives where it is declared
    assert rows_of(result, "src/routes/admin.rs") == [
        ["GET", "/admin/ping", "ping", "src/routes/admin.rs", ""],
        ["GET", "/v2/inner/ping", "ping", "src/routes/admin.rs", ""],
    ]


def test_axum_sub_router_is_not_listed_bare_and_methods_on_impl_types(tmp_path):
    app(
        tmp_path,
        AXUM,
        """use axum::{routing::get, Router};

pub struct Api;
impl Api {
    pub fn router() -> Router { Router::new().route("/inside", get(h)) }
}
async fn h() {}

fn app() -> Router { Router::new().nest("/api", Api::router()) }
fn main() { let _ = app(); }
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/api/inside")]
    assert verdict(result) == ("complete", "")


def test_axum_helper_taking_and_returning_a_router(tmp_path):
    app(
        tmp_path,
        AXUM,
        """use axum::{routing::get, Router};

fn with_health(r: Router) -> Router { r.route("/health", get(h)) }
async fn h() {}

fn app() -> Router { with_health(Router::new().route("/a", get(h))) }
fn main() { let _ = app(); }
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/a"), ("GET", "/health")]
    assert verdict(result) == ("complete", "")


def test_axum_mutable_router_and_conditionals(tmp_path):
    app(
        tmp_path,
        AXUM,
        """use axum::{routing::get, Router};

async fn h() {}

fn app(debug: bool) -> Router {
    let mut app = Router::new().route("/a", get(h));
    if debug {
        app = app.route("/debug", get(h));
    }
    for _ in 0..2 {
        app = app.nest("/n", Router::new().route("/x", get(h)));
    }
    app
}
fn main() { let _ = app(true); }
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/a"), ("GET", "/debug"), ("GET", "/n/x")]
    assert verdict(result) == ("complete", "")


def test_axum_const_path(tmp_path):
    app(
        tmp_path,
        AXUM,
        """use axum::{routing::get, Router};
const BASE: &str = "/base";
mod paths { pub const USERS: &str = "/users"; }
async fn h() {}
fn app() -> Router {
    Router::new().nest(BASE, Router::new().route(paths::USERS, get(h)))
}
fn main() { let _ = app(); }
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/base/users")]
    assert verdict(result) == ("complete", "")


# --- partial / sites ----------------------------------------------------------


def test_axum_dynamic_path_partial(tmp_path):
    src = """use axum::{routing::get, Router};

async fn h() {}

fn app(prefix: &str) -> Router {
    Router::new()
        .route(&format!("/{}/x", prefix), get(h))
        .nest(prefix, Router::new().route("/lost", get(h)))
        .route(concat!("/a", "/b"), get(h))
        .route("/ok", get(h))
}
fn main() { let _ = app(&std::env::var("P").unwrap()); }
"""
    app(tmp_path, AXUM, src)
    result = run_routes(tmp_path)
    status, detail = verdict(result)
    assert status == "partial"
    assert set(detail.split("; ")) == {
        f"{MAIN}:{at(src, 'format!')}",
        f"{MAIN}:{at(src, '.nest(prefix')}",
        f"{MAIN}:{at(src, 'concat!')}",
    }
    assert pairs(result) == [("GET", "/ok")]  # never listed under a wrong prefix


def test_axum_unknown_methods_and_foreign_routers_are_sites(tmp_path):
    src = """use axum::{routing::get, Router};

async fn h() {}

fn app() -> Router {
    Router::new()
        .route("/a", get(h))
        .typed_get(h)
        .nest("/x", shared_api::routes())
        .merge(plugin::router())
        .routes(utoipa_axum::routes!(h))
}
fn main() { let _ = app(); }
"""
    app(tmp_path, AXUM, src)
    result = run_routes(tmp_path)
    status, detail = verdict(result)
    assert status == "partial"
    assert set(detail.split("; ")) == {
        f"{MAIN}:{at(src, 'typed_get')}",
        f"{MAIN}:{at(src, 'shared_api')}",
        f"{MAIN}:{at(src, 'plugin::router')}",
        f"{MAIN}:{at(src, '.routes(')}",
    }
    assert pairs(result) == [("GET", "/a")]


def test_axum_router_from_sibling_workspace_crate_is_unknown(tmp_path):
    cargo(tmp_path, AXUM, app="svc", name="svc")
    cargo(tmp_path, AXUM, app="shared", name="shared")
    src = """use axum::Router;
use shared::build_router;

#[tokio::main]
async fn main() {
    let app = build_router();
    let listener = tokio::net::TcpListener::bind("0.0.0.0:3000").await.unwrap();
    axum::serve(listener, app).await.unwrap();
}
"""
    write(tmp_path, "svc/src/main.rs", src)
    write(
        tmp_path,
        "shared/src/lib.rs",
        'use axum::{routing::get, Router};\npub fn build_router() -> Router { Router::new().route("/s", get(h)) }\nasync fn h() {}\n',
    )
    result = run_routes(tmp_path)
    assert verdict(result, "svc")[0] == "partial"
    assert verdict(result, "svc")[1].startswith("svc/src/main.rs:")
    # the sibling crate's own router fn is only reachable from outside the
    # package: its mount prefix is unknown, so it is a site, not a bare route
    assert verdict(result, "shared") == ("partial", "shared/src/lib.rs:2")
    assert pairs(result) == []


def test_axum_serving_an_unresolved_call_result_is_a_site(tmp_path):
    src = """#[tokio::main]
async fn main() {
    let listener = tokio::net::TcpListener::bind("0.0.0.0:3000").await.unwrap();
    axum::serve(listener, other_crate::app()).await.unwrap();
}
"""
    app(tmp_path, AXUM, src)
    result = run_routes(tmp_path)
    assert verdict(result) == ("partial", f"{MAIN}:{at(src, 'axum::serve')}")


def test_axum_router_fn_only_reachable_through_a_cycle_is_a_site(tmp_path):
    src = """use axum::{routing::get, Router};
async fn h() {}
fn a() -> Router { Router::new().route("/a", get(h)).merge(b()) }
fn b() -> Router { Router::new().route("/b", get(h)).merge(a()) }
"""
    app(tmp_path, AXUM, src)
    result = run_routes(tmp_path)
    status, detail = verdict(result)
    assert status == "partial"
    assert detail != ""


def test_axum_uncalled_helper_with_router_param_is_a_site(tmp_path):
    src = """use axum::{routing::get, Router};
async fn h() {}
pub fn add(r: Router) -> Router { r.route("/x", get(h)) }
"""
    app(tmp_path, AXUM, src, "src/lib.rs")
    result = run_routes(tmp_path)
    assert pairs(result) == []
    assert verdict(result) == ("partial", f"src/lib.rs:{at(src, 'pub fn add')}")


# --- ordering, collisions -----------------------------------------------------


@pytest.mark.parametrize(
    ("first", "second"), [("a_main", "z_users"), ("z_main", "a_users")]
)
def test_axum_registering_file_before_or_after_defining_file(tmp_path, first, second):
    cargo(tmp_path, AXUM)
    write(
        tmp_path,
        "src/main.rs",
        f"mod {first};\nmod {second};\nfn main() {{ {first}::start(); }}\n",
    )
    write(
        tmp_path,
        f"src/{first}.rs",
        f"""use axum::Router;
pub fn app() -> Router {{ Router::new().nest("/u", crate::{second}::routes()) }}
pub fn start() {{ let _ = app(); }}
""",
    )
    write(
        tmp_path,
        f"src/{second}.rs",
        """use axum::{routing::get, Router};
pub fn routes() -> Router { Router::new().route("/me", get(me)) }
async fn me() {}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/u/me")]
    assert verdict(result) == ("complete", "")


def test_axum_get_without_axum_import_is_not_a_route(tmp_path):
    app(
        tmp_path,
        AXUM,
        """use axum::{routing::get as aget, Router};
use std::collections::HashMap;

fn get(x: u8) -> u8 { x }
async fn h() {}

async fn client(c: &reqwest::Client, m: &HashMap<u8, u8>) {
    let _ = reqwest::get("https://example.com").await;
    let _ = c.get("https://example.com/b").send().await;
    let _ = m.get(&1);
    let _ = HashMap::<u8, u8>::new().get(&2);
    let _ = get(3);
    let r = Router::new().route("/ok", aget(h));
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/ok")]
    assert verdict(result) == ("complete", "")


def test_axum_route_on_non_router_types_is_ignored(tmp_path):
    app(
        tmp_path,
        AXUM,
        """use axum::{routing::get, Router};

struct Table;
impl Table { fn route(&self, a: &str, b: u8) -> u8 { b } }
async fn h() {}

struct Query;
impl Query {
    fn new() -> Self { Query }
    fn route(self, a: &str, b: u8) -> Self { self }
}

fn f(t: Table) {
    let _ = t.route("/x", 3);
    let _ = Table.route("a", 1);
    let _ = Query::new().route("/internal", 3);
    let r = Router::new().route("/real", get(h));
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/real")]
    assert verdict(result) == ("complete", "")


def test_axum_route_shaped_call_on_unresolved_receiver_is_a_site(tmp_path):
    src = """use axum::routing::get;

async fn h() {}

fn add(thing: crate::Opaque) {
    thing.route("/hidden", get(h));
}
"""
    app(tmp_path, AXUM, src)
    result = run_routes(tmp_path)
    assert pairs(result) == []
    assert verdict(result) == ("partial", f"{MAIN}:{at(src, 'thing.route')}")


def test_axum_router_from_unknown_crate_type_is_not_assumed_axum(tmp_path):
    src = """use matchit::Router;

fn f() {
    let mut r = Router::new();
    r.insert("/x", 1).unwrap();
}
"""
    app(tmp_path, AXUM, src)
    result = run_routes(tmp_path)
    assert verdict(result) == ("complete", "")


# --- hostile input ------------------------------------------------------------


def test_axum_hostile_chain_and_nesting_do_not_crash(tmp_path):
    depth = 3000
    chain = "".join(f'.route("/r{i}", get(h))' for i in range(depth))
    nest = 'Router::new().route("/inner", get(h))'
    for i in range(40):
        nest = f'Router::new().nest("/n{i}", {nest})'
    junk = "w(" * 3000 + "h" + ")" * 3000
    cargo(tmp_path, AXUM)
    write(
        tmp_path,
        MAIN,
        f"""use axum::{{routing::get, Router}};
async fn h() {{}}
fn long() -> Router {{ Router::new(){chain} }}
fn nested() -> Router {{ {nest} }}
fn junk() -> Router {{ Router::new().merge({junk}) }}
fn main() {{ let _ = (long(), nested(), junk()); }}
""",
    )
    result = run_routes(tmp_path)
    found = pairs(result)
    assert len(found) == depth + 1
    assert any(p.endswith("/inner") and p.count("/") == 41 for _m, p in found)
    status, _detail = verdict(result)
    assert status == "partial"  # the junk merge is a site


def test_axum_unparsable_file_is_a_site_not_a_crash(tmp_path):
    cargo(tmp_path, AXUM)
    write(tmp_path, MAIN, "mod broken;\nfn main() {}\n")
    write(tmp_path, "src/broken.rs", "use axum::{\nfn (((( ;;; }}}}\n")
    result = run_routes(tmp_path)
    status, detail = verdict(result)
    assert status == "partial"
    assert detail.startswith("src/broken.rs:")


def test_axum_missing_module_file_is_a_site(tmp_path):
    src = "mod ghost;\nfn main() {}\n"
    app(tmp_path, AXUM, src)
    result = run_routes(tmp_path)
    assert verdict(result) == ("partial", f"{MAIN}:1")


def test_axum_tests_benches_examples_and_cfg_test_are_skipped(tmp_path):
    cargo(tmp_path, AXUM)
    write(
        tmp_path,
        MAIN,
        """use axum::{routing::get, Router};
async fn h() {}
fn app() -> Router { Router::new().route("/real", get(h)) }
fn main() { let _ = app(); }

#[cfg(test)]
mod tests {
    use super::*;
    fn only_in_tests() -> Router { Router::new().route("/only-test", get(h)) }
    #[tokio::test]
    async fn t() { let _ = Router::new().route("/t2", get(h)); }
}
""",
    )
    for d in ("tests", "benches", "examples"):
        write(
            tmp_path,
            f"{d}/x.rs",
            f'use axum::{{routing::get, Router}};\nfn f() -> Router {{ Router::new().route("/{d}", get(h)) }}\n',
        )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/real")]
    assert verdict(result) == ("complete", "")


def test_axum_declaration_shape_fuzz_never_crashes(tmp_path):
    cargo(tmp_path, AXUM)
    write(
        tmp_path,
        MAIN,
        """use axum::{routing::{get, post}, Router};
use std::{fmt, io::{self, Read}};
pub(crate) use crate::x::{self, y as _, z::*};
use axum::*;

macro_rules! m { ($($t:tt)*) => {}; }
m!(a, b, c);
struct S<T: Clone = u8>(T) where T: Send;
trait Tr { const C: usize = 1; fn f(&self); }
impl<T> Tr for S<T> where T: Clone + Send { fn f(&self) {} }
async fn h() {}

fn generic<'a, T: Into<String> + 'a, const N: usize>(x: &'a [T; N], (a, b): (u8, u8), [c, ..]: [u8; 2], _: ()) -> impl Fn() -> T + 'a { move || todo!() }

fn app() -> Router {
    let (a, b) = (Router::new(), Router::new());
    let [c, _] = [1, 2];
    let S(d) = S(1u8);
    let _ = (c, d);
    let (x, y, z) = f();
    let Some(e) = None::<u8> else { return Router::new() };
    let _: () = if true { () } else { loop {} };
    match 3 { 1 | 2 => {} n if n > 2 => {} _ => {} }
    let cl = |a: u8, (b, c): (u8, u8)| a + b + c;
    unsafe { let _ = 1; }
    'l: loop { break 'l; }
    let r: Router = a.merge(b);
    r.route("/ok", get(h))
}
fn main() { let _ = app(); }
""",
    )
    result = run_routes(tmp_path)
    assert result.warnings == []
    assert row(result).status in ("complete", "partial")
    assert ("GET", "/ok") in pairs(result)
