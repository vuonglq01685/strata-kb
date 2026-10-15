"""Rust: Actix Web routes -- attribute macros, scopes, resources, configure."""

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

ACTIX = "actix-web"

# --- typical app --------------------------------------------------------------

TYPICAL_MAIN = """use actix_web::{middleware::Logger, web, App, HttpServer};

mod auth;
mod handlers;
mod routes;

#[actix_web::main]
async fn main() -> std::io::Result<()> {
    env_logger::init_from_env(env_logger::Env::new().default_filter_or("info"));
    let pool = db::connect().await.expect("db");
    let secret = std::env::var("JWT_SECRET").unwrap_or_default();
    HttpServer::new(move || {
        App::new()
            .wrap(Logger::default())
            .wrap(actix_cors::Cors::permissive())
            .app_data(web::Data::new(pool.clone()))
            .app_data(web::JsonConfig::default().limit(4096))
            .configure(routes::config)
            .service(handlers::health)
            .service(actix_files::Files::new("/static", "./static").show_files_listing())
            .default_service(web::route().to(handlers::not_found))
    })
    .bind(("127.0.0.1", 8080))?
    .workers(4)
    .run()
    .await
}
"""

TYPICAL_ROUTES = """use actix_web::{guard, web};

use crate::auth::Auth;
use crate::handlers;

pub fn config(cfg: &mut web::ServiceConfig) {
    cfg.service(
        web::scope("/api/v1")
            .wrap(Auth)
            .service(
                web::scope("/users")
                    .service(handlers::list_users)
                    .service(handlers::get_user)
                    .service(handlers::create_user),
            )
            .service(
                web::resource("/items/{id}")
                    .route(web::get().to(handlers::get_item))
                    .route(web::delete().guard(guard::Header("x-admin", "1")).to(handlers::del_item)),
            )
            .route("/ping", web::get().to(|| async { "pong" })),
    );
}
"""

TYPICAL_HANDLERS = """use actix_web::{delete, get, post, web, HttpResponse, Responder};
use serde::Deserialize;

use crate::models::NewUser;

#[get("/health")]
pub async fn health() -> impl Responder {
    HttpResponse::Ok().finish()
}

#[utoipa::path(get, path = "/api/v1/users")]
#[get("")]
pub async fn list_users(pool: web::Data<Pool>, q: web::Query<Page>) -> impl Responder {
    HttpResponse::Ok().json(vec![1])
}

#[get("/{id}")]
pub async fn get_user(path: web::Path<u32>) -> impl Responder {
    HttpResponse::Ok().finish()
}

#[post("")]
pub async fn create_user(body: web::Json<NewUser>) -> impl Responder {
    HttpResponse::Created().finish()
}

pub async fn get_item(id: web::Path<u32>) -> impl Responder {
    HttpResponse::Ok().finish()
}

pub async fn del_item(id: web::Path<u32>) -> impl Responder {
    HttpResponse::NoContent().finish()
}

pub async fn not_found() -> impl Responder {
    HttpResponse::NotFound().finish()
}
"""


def test_typical_actix_app_reaches_complete(tmp_path):
    app(tmp_path, ACTIX, TYPICAL_MAIN)
    write(tmp_path, "src/routes.rs", TYPICAL_ROUTES)
    write(tmp_path, "src/handlers.rs", TYPICAL_HANDLERS)
    write(tmp_path, "src/auth.rs", "pub struct Auth;\n")
    result = run_routes(tmp_path)
    assert verdict(result) == ("complete", "")
    assert triples(result) == [
        ("DELETE", "/api/v1/items/{id}", "handlers::del_item"),
        ("GET", "/api/v1/items/{id}", "handlers::get_item"),
        ("GET", "/api/v1/ping", "(inline)"),
        ("GET", "/api/v1/users", "handlers::list_users"),
        ("POST", "/api/v1/users", "handlers::create_user"),
        ("GET", "/api/v1/users/{id}", "handlers::get_user"),
        ("GET", "/health", "handlers::health"),
    ]
    assert not any("sk_" in r.detail for r in result.coverage)


def test_actix_scope_prefix_and_path_param_table_rows(tmp_path):
    app(
        tmp_path,
        ACTIX,
        """use actix_web::{get, web, App, HttpServer};

#[get("/{id}")]
async fn show(id: web::Path<u32>) -> String { id.to_string() }

fn build() -> App<()> {
    App::new().service(web::scope("/orders").service(show))
}
""",
    )
    result = run_routes(tmp_path)
    assert rows_of(result, MAIN) == [["GET", "/orders/{id}", "show", MAIN, ""]]
    assert verdict(result) == ("complete", "")


# --- attribute forms ----------------------------------------------------------


def test_actix_every_verb_attribute_and_route_macro(tmp_path):
    app(
        tmp_path,
        ACTIX,
        """use actix_web::{connect, delete, get, head, options, patch, post, put, route, trace, App};

#[get("/g")] async fn g() {}
#[post("/p")] async fn p() {}
#[put("/u")] async fn u() {}
#[delete("/d")] async fn d() {}
#[patch("/pa")] async fn pa() {}
#[head("/h")] async fn h() {}
#[options("/o")] async fn o() {}
#[trace("/t")] async fn t() {}
#[connect("/c")] async fn c() {}
#[route("/multi", method = "GET", method = "POST")]
async fn multi() {}
#[actix_web::get("/qualified", guard = "x")]
async fn qualified() {}
#[get("/one")]
#[get("/two")]
async fn stacked() {}

fn app() -> App<()> {
    App::new()
        .service(g).service(p).service(u).service(d).service(pa).service(h)
        .service(o).service(t).service(c).service(multi).service(qualified).service(stacked)
}
""",
    )
    result = run_routes(tmp_path)
    assert verdict(result) == ("complete", "")
    assert triples(result) == [
        ("CONNECT", "/c", "c"),
        ("DELETE", "/d", "d"),
        ("GET", "/g", "g"),
        ("HEAD", "/h", "h"),
        ("GET", "/multi", "multi"),
        ("POST", "/multi", "multi"),
        ("OPTIONS", "/o", "o"),
        ("GET", "/one", "stacked"),
        ("POST", "/p", "p"),
        ("PATCH", "/pa", "pa"),
        ("GET", "/qualified", "qualified"),
        ("TRACE", "/t", "t"),
        ("GET", "/two", "stacked"),
        ("PUT", "/u", "u"),
    ]


def test_actix_builder_forms(tmp_path):
    app(
        tmp_path,
        ACTIX,
        """use actix_web::{web, App, http::Method};

async fn index() {}
async fn create() {}
async fn any_h() {}
async fn custom() {}

fn app() -> App<()> {
    App::new()
        .route("/", web::get().to(index))
        .route("/things", web::post().to(create))
        .service(web::resource("/res").route(web::get().to(index)).route(web::post().to(create)))
        .service(web::resource("/all").to(any_h))
        .service(web::resource(["/a", "/b"]).route(web::put().to(index)))
        .service(web::resource("/m").route(web::method(Method::PATCH).to(custom)))
        .service(web::scope("/s").route("", web::get().to(index)).route("/x", web::route().to(any_h)))
}
""",
    )
    result = run_routes(tmp_path)
    assert verdict(result) == ("complete", "")
    assert triples(result) == [
        ("GET", "/", "index"),
        ("PUT", "/a", "index"),
        ("ANY", "/all", "any_h"),
        ("PUT", "/b", "index"),
        ("PATCH", "/m", "custom"),
        ("GET", "/res", "index"),
        ("POST", "/res", "create"),
        ("GET", "/s", "index"),
        ("ANY", "/s/x", "any_h"),
        ("POST", "/things", "create"),
    ]


def test_actix_scope_value_helpers_and_local_variables(tmp_path):
    app(
        tmp_path,
        ACTIX,
        """use actix_web::{get, web, App, Scope};

#[get("/me")]
async fn me() {}

fn users() -> Scope {
    web::scope("/users").service(me)
}

fn app() -> App<()> {
    let admin = web::scope("/admin").route("/stats", web::get().to(stats));
    let app = App::new();
    let app = app.service(users());
    app.service(admin)
}
async fn stats() {}
""",
    )
    result = run_routes(tmp_path)
    assert verdict(result) == ("complete", "")
    assert triples(result) == [
        ("GET", "/admin/stats", "stats"),
        ("GET", "/users/me", "me"),
    ]


def test_actix_configure_closure_and_nested_configure(tmp_path):
    app(
        tmp_path,
        ACTIX,
        """use actix_web::{get, web, App};

#[get("/a")] async fn a() {}
#[get("/b")] async fn b() {}

fn inner(cfg: &mut web::ServiceConfig) {
    cfg.service(b);
}

fn app() -> App<()> {
    App::new()
        .configure(|cfg| { cfg.service(a); })
        .service(web::scope("/in").configure(inner))
}
""",
    )
    result = run_routes(tmp_path)
    assert verdict(result) == ("complete", "")
    assert pairs(result) == [("GET", "/a"), ("GET", "/in/b")]


def test_actix_const_path_resolves_and_secret_const_never_leaks(tmp_path):
    app(
        tmp_path,
        ACTIX,
        """use actix_web::{web, App};

const PREFIX: &str = "/api";
pub const API_KEY: &str = "sk_live_SUPERSECRET";
async fn h() {}

fn app() -> App<()> {
    App::new().service(web::scope(PREFIX).route("/k", web::get().to(h)))
}
""",
    )
    result = run_routes(tmp_path)
    assert verdict(result) == ("complete", "")
    assert pairs(result) == [("GET", "/api/k")]
    assert "SUPERSECRET" not in everything(result)


# --- partial / sites ----------------------------------------------------------


def test_actix_dynamic_path_partial(tmp_path):
    src = """use actix_web::{web, App};

async fn h() {}

fn app(prefix: String) -> App<()> {
    App::new()
        .service(web::scope(&prefix).route("/lost", web::get().to(h)))
        .service(web::resource(format!("/f/{}", 1)).to(h))
        .service(web::scope(concat!("/a", "/b")).to(h))
        .route("/ok", web::get().to(h))
}
"""
    app(tmp_path, ACTIX, src)
    result = run_routes(tmp_path)
    status, detail = verdict(result)
    assert status == "partial"
    assert set(detail.split("; ")) == {
        f"{MAIN}:{at(src, 'web::scope(&prefix)')}",
        f"{MAIN}:{at(src, 'format!')}",
        f"{MAIN}:{at(src, 'concat!')}",
    }
    assert pairs(result) == [("GET", "/ok")]  # never listed under a wrong prefix


def test_actix_unregistered_attribute_handler_is_a_site_not_a_route(tmp_path):
    src = """use actix_web::{get, web, App};

#[get("/live")]
async fn live() {}

#[get("/dead")]
async fn dead() {}

fn app() -> App<()> { App::new().service(live) }
"""
    app(tmp_path, ACTIX, src)
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/live")]
    dead = '#[get("/dead")]'
    assert verdict(result) == ("partial", f"{MAIN}:{at(src, dead)}")


def test_actix_handler_registered_under_two_scopes_lists_both(tmp_path):
    app(
        tmp_path,
        ACTIX,
        """use actix_web::{get, web, App};

#[get("/ping")]
async fn ping() {}

fn app() -> App<()> {
    App::new()
        .service(web::scope("/v1").service(ping))
        .service(web::scope("/v2").service(ping))
}
""",
    )
    result = run_routes(tmp_path)
    assert verdict(result) == ("complete", "")
    assert pairs(result) == [("GET", "/v1/ping"), ("GET", "/v2/ping")]


def test_actix_unknown_services_are_sites(tmp_path):
    src = """use actix_web::{web, App};

fn app() -> App<()> {
    App::new()
        .service(utoipa_swagger_ui::SwaggerUi::new("/docs/{_:.*}"))
        .configure(shared_api::config)
        .service(plugin::routes())
}
"""
    app(tmp_path, ACTIX, src)
    result = run_routes(tmp_path)
    status, detail = verdict(result)
    assert status == "partial"
    assert set(detail.split("; ")) == {
        f"{MAIN}:{at(src, 'SwaggerUi')}",
        f"{MAIN}:{at(src, 'shared_api')}",
        f"{MAIN}:{at(src, 'plugin::routes')}",
    }


def test_actix_uncalled_config_fn_is_a_site(tmp_path):
    src = """use actix_web::{get, web};

#[get("/lib")]
async fn lib_route() {}

pub fn config(cfg: &mut web::ServiceConfig) {
    cfg.service(lib_route);
}
"""
    app(tmp_path, ACTIX, src, "src/lib.rs")
    result = run_routes(tmp_path)
    assert pairs(result) == []
    status, detail = verdict(result)
    assert status == "partial"
    assert f"src/lib.rs:{at(src, 'pub fn config')}" in detail.split("; ")


# --- ordering, modules --------------------------------------------------------


@pytest.mark.parametrize(
    ("first", "second"), [("a_app", "z_routes"), ("z_app", "a_routes")]
)
def test_actix_registering_file_before_or_after_defining_file(tmp_path, first, second):
    cargo(tmp_path, ACTIX)
    write(
        tmp_path,
        "src/main.rs",
        f"mod {first};\nmod {second};\nfn main() {{}}\n",
    )
    reg, dfn = (first, second)
    write(
        tmp_path,
        f"src/{reg}.rs",
        f"""use actix_web::{{web, App}};
pub fn build() -> App<()> {{
    App::new().service(web::scope("/o").service(crate::{dfn}::items))
}}
""",
    )
    write(
        tmp_path,
        f"src/{dfn}.rs",
        """use actix_web::get;
#[get("/items")]
pub async fn items() {}
""",
    )
    result = run_routes(tmp_path)
    assert verdict(result) == ("complete", "")
    assert pairs(result) == [("GET", "/o/items")]
    assert rows_of(result, f"src/{dfn}.rs") == [
        ["GET", "/o/items", f"crate::{dfn}::items", f"src/{dfn}.rs", ""]
    ]


def test_actix_module_dir_mod_rs_and_super_paths(tmp_path):
    cargo(tmp_path, ACTIX)
    write(tmp_path, "src/main.rs", "mod api;\nfn main() {}\n")
    write(
        tmp_path,
        "src/api/mod.rs",
        """use actix_web::{web, App};
mod users;
pub fn app() -> App<()> {
    App::new().service(web::scope("/api").configure(users::config))
}
""",
    )
    write(
        tmp_path,
        "src/api/users.rs",
        """use actix_web::{get, web};
use super::helpers::auth_note;

#[get("/users/{id}")]
async fn show(id: web::Path<u32>) {}

pub fn config(cfg: &mut web::ServiceConfig) {
    cfg.service(show);
}
""",
    )
    write(tmp_path, "src/api/helpers.rs", "pub fn auth_note() {}\n")
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/api/users/{id}")]
    assert verdict(result) == ("complete", "")


# --- collisions (ruling 12) ---------------------------------------------------


def test_actix_non_route_calls_are_ignored_and_app_stays_complete(tmp_path):
    app(
        tmp_path,
        ACTIX,
        """use actix_web::{get, web, App, HttpServer};
use std::collections::HashMap;

#[get("/x")]
async fn x() {}

async fn fetch(client: &reqwest::Client, m: &HashMap<String, String>) {
    let _ = reqwest::get("https://example.com/a").await;
    let _ = client.get("https://example.com/b").send().await;
    let _ = m.get("k");
    let _ = tokio::spawn(async {}).route("/not", 1);
    let r = Registry::new().route("/a", handler);
    let _ = get(handler);
}

fn app() -> App<()> { App::new().service(x) }
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/x")]
    assert verdict(result) == ("complete", "")


def test_actix_route_shaped_call_on_unresolved_receiver_is_a_site(tmp_path):
    src = """use actix_web::{web, App};

async fn h() {}

fn add(app: crate::Wrapper) {
    app.route("/hidden", web::get().to(h));
}
"""
    app(tmp_path, ACTIX, src)
    result = run_routes(tmp_path)
    assert pairs(result) == []
    assert verdict(result) == ("partial", f"{MAIN}:{at(src, 'app.route')}")


def test_actix_attribute_handler_of_another_framework_is_not_claimed(tmp_path):
    cargo(tmp_path, ACTIX, "rocket")
    write(
        tmp_path,
        MAIN,
        """use actix_web::{get, App};
mod other;
#[get("/a")] async fn a() {}
fn app() -> App<()> { App::new().service(a) }
""",
    )
    write(tmp_path, "src/other.rs", 'use rocket::get;\n#[get("/r")] fn r() {}\n')
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/a")]
    actix = [c for c in result.coverage if c.framework == "Actix Web"]
    assert [(c.status, c.detail) for c in actix] == [("complete", "")]


# --- hostile input ------------------------------------------------------------


def test_actix_hostile_nesting_and_chains_do_not_crash(tmp_path):
    depth = 3000
    chain = "".join(f'.service(web::resource("/r{i}").to(h))' for i in range(depth))
    nested = "w(" * 2000 + "h" + ")" * 2000
    cargo(tmp_path, ACTIX)
    write(
        tmp_path,
        MAIN,
        f"""use actix_web::{{web, App}};
async fn h() {{}}
fn long() -> App<()> {{ App::new(){chain} }}
fn deep() -> App<()> {{ App::new().service({nested}) }}
fn ok() -> App<()> {{ App::new().route("/deep", web::get().to(h)) }}
""",
    )
    result = run_routes(tmp_path)
    assert ("GET", "/deep") in pairs(result)
    assert len(pairs(result)) == depth + 1
    status, detail = verdict(result)
    assert status == "partial"  # the 2000-deep nest is a site
    assert detail.count(";") == 0


def test_actix_unparsable_file_is_a_site_not_a_crash(tmp_path):
    cargo(tmp_path, ACTIX)
    write(tmp_path, MAIN, "mod broken;\nfn main() {}\n")
    write(tmp_path, "src/broken.rs", "use actix_web::{\nfn (((( ;;; }}}}\n")
    result = run_routes(tmp_path)
    status, detail = verdict(result)
    assert status == "partial"
    assert detail.startswith("src/broken.rs:")


def test_actix_tests_benches_examples_and_cfg_test_are_skipped(tmp_path):
    cargo(tmp_path, ACTIX)
    write(
        tmp_path,
        MAIN,
        """use actix_web::{get, web, App};
#[get("/real")] async fn real() {}
fn app() -> App<()> { App::new().service(real) }

#[cfg(test)]
mod tests {
    use super::*;
    use actix_web::test;
    #[actix_web::test]
    async fn t() {
        let app = test::init_service(App::new().route("/only-test", web::get().to(real))).await;
    }
}
""",
    )
    for d in ("tests", "benches", "examples"):
        write(
            tmp_path,
            f"{d}/x.rs",
            f'use actix_web::{{web, App}};\nfn f() {{ App::new().route("/{d}", web::get().to(h)); }}\n',
        )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/real")]
    assert verdict(result) == ("complete", "")


def test_actix_declaration_shape_fuzz_never_crashes(tmp_path):
    cargo(tmp_path, ACTIX)
    write(
        tmp_path,
        MAIN,
        """use actix_web::{web, App};
use actix_web::web::{scope as sc, *};
use std::{fmt, io::{self, Read}};
pub(crate) use crate::x::{self, y as _, z::*};

macro_rules! m { ($($t:tt)*) => {}; }
m!(a, b, c);

struct S<T: Clone = u8>(T) where T: Send;
trait Tr { const C: usize = 1; fn f(&self); }
impl<T> Tr for S<T> where T: Clone + Send { fn f(&self) {} }

fn generic<'a, T: Into<String> + 'a, const N: usize>(x: &'a [T; N], (a, b): (u8, u8), [c, ..]: [u8; 2], _: ()) -> impl Fn() -> T + 'a { move || todo!() }

async fn h() {}

fn app() -> App<()> {
    let (a, b) = (web::scope("/a"), web::scope("/b"));
    let [c, _] = [1, 2];
    let S(d) = S(1u8);
    let _ = (a, b, c, d);
    let (x, y, z) = f();
    let e @ Some(_) = None::<u8> else { return App::new() };
    let _: () = if true { () } else { loop {} };
    match 3 { 1 | 2 => {} n if n > 2 => {} _ => {} }
    let cl = |a: u8, (b, c): (u8, u8)| a + b + c;
    unsafe { let _ = 1; }
    'l: loop { break 'l; }
    App::new().service(sc("/ok").route("/z", get().to(h)))
}
""",
    )
    result = run_routes(tmp_path)
    assert result.warnings == []
    assert row(result).status in ("complete", "partial")
    assert ("GET", "/ok/z") in pairs(result)
