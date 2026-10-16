"""Rust: module resolution, current skeletons and cross-framework edges.

Shared by the Actix Web / Axum / Rocket adapters (`_rs_index`, `_rs_interp`).
"""

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
    rows_of,
    run_routes,
    triples,
    verdict,
    write,
)

# --- current skeletons (ruling 17) -----------------------------------------------


def test_actix_readme_hello_world_is_complete(tmp_path):
    app(
        tmp_path,
        "actix-web",
        """use actix_web::{get, post, web, App, HttpResponse, HttpServer, Responder};

#[get("/")]
async fn hello() -> impl Responder {
    HttpResponse::Ok().body("Hello world!")
}

#[post("/echo")]
async fn echo(req_body: String) -> impl Responder {
    HttpResponse::Ok().body(req_body)
}

async fn manual_hello() -> impl Responder {
    HttpResponse::Ok().body("Hey there!")
}

#[actix_web::main]
async fn main() -> std::io::Result<()> {
    HttpServer::new(|| {
        App::new()
            .service(hello)
            .service(echo)
            .route("/hey", web::get().to(manual_hello))
    })
    .bind(("127.0.0.1", 8080))?
    .run()
    .await
}
""",
    )
    result = run_routes(tmp_path)
    assert verdict(result) == ("complete", "")
    assert triples(result) == [
        ("GET", "/", "hello"),
        ("POST", "/echo", "echo"),
        ("GET", "/hey", "manual_hello"),
    ]


def test_axum_readme_hello_world_is_complete(tmp_path):
    app(
        tmp_path,
        "axum",
        """use axum::{routing::get, Router};

#[tokio::main]
async fn main() {
    // build our application with a single route
    let app = Router::new().route("/", get(|| async { "Hello, World!" }));

    // run our app with hyper, listening globally on port 3000
    let listener = tokio::net::TcpListener::bind("0.0.0.0:3000").await.unwrap();
    axum::serve(listener, app).await.unwrap();
}
""",
    )
    result = run_routes(tmp_path)
    assert verdict(result) == ("complete", "")
    assert triples(result) == [("GET", "/", "(inline)")]


def test_rocket_readme_hello_world_is_complete(tmp_path):
    app(
        tmp_path,
        "rocket",
        """#[macro_use] extern crate rocket;

#[get("/")]
fn index() -> &'static str {
    "Hello, world!"
}

#[launch]
fn rocket() -> _ {
    rocket::build().mount("/", routes![index])
}
""",
    )
    result = run_routes(tmp_path)
    assert verdict(result) == ("complete", "")
    assert triples(result) == [("GET", "/", "index")]


# --- module resolution --------------------------------------------------------------


def test_lib_and_bin_of_one_package_resolve_through_the_package_name(tmp_path):
    cargo(tmp_path, "axum", name="my-app")
    write(
        tmp_path,
        "src/lib.rs",
        """use axum::{routing::get, Router};
pub fn app() -> Router { Router::new().route("/lib", get(h)) }
async fn h() {}
""",
    )
    write(
        tmp_path,
        MAIN,
        """use my_app::app;
#[tokio::main]
async fn main() { axum::serve(l, app()).await.unwrap(); }
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/lib")]
    assert verdict(result) == ("complete", "")


def test_path_attribute_pub_use_aliases_and_globs(tmp_path):
    cargo(tmp_path, "axum")
    write(
        tmp_path,
        MAIN,
        """use axum::Router;
#[path = "routes/api_v1.rs"]
mod api;
mod prelude;
use prelude::*;
fn app() -> Router { Router::new().nest("/v1", renamed()).nest("/g", glob_routes()) }
fn main() { let _ = app(); }
""",
    )
    write(
        tmp_path,
        "src/routes/api_v1.rs",
        """use axum::{routing::get, Router};
pub fn routes() -> Router { Router::new().route("/ping", get(ping)) }
pub fn more() -> Router { Router::new().route("/more", get(ping)) }
async fn ping() {}
""",
    )
    write(
        tmp_path,
        "src/prelude.rs",
        "pub use crate::api::routes as renamed;\npub use crate::api::more as glob_routes;\n",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/g/more"), ("GET", "/v1/ping")]
    assert verdict(result) == ("complete", "")


def test_inline_modules_self_super_and_orphan_files(tmp_path):
    cargo(tmp_path, "axum")
    write(
        tmp_path,
        MAIN,
        """use axum::{routing::get, Router};
mod outer {
    pub mod inner {
        use axum::{routing::get, Router};
        pub fn r() -> Router { Router::new().route("/inner", get(super::sibling)).nest("/s", self::deeper::r()) }
        mod deeper { use axum::{routing::get, Router};
            pub fn r() -> Router { Router::new().route("/deep", get(crate::top)) } }
    }
    pub async fn sibling() {}
}
async fn top() {}
fn app() -> Router { Router::new().nest("/o", outer::inner::r()).nest("/x", orphan::r()) }
fn main() { let _ = app(); }
""",
    )
    # nothing declares `mod orphan;`: the file is read as its own root
    write(
        tmp_path,
        "src/orphan.rs",
        'use axum::{routing::get, Router};\npub fn r() -> Router { Router::new().route("/o", get(h)) }\nasync fn h() {}\n',
    )
    result = run_routes(tmp_path)
    status, detail = verdict(result)
    assert pairs(result) == [("GET", "/o/inner"), ("GET", "/o/s/deep")]
    # `orphan::r()` is not resolvable from main: a site, never a wrong route
    assert status == "partial"
    main_text = (tmp_path / MAIN).read_text()
    assert f"{MAIN}:{at(main_text, 'orphan::r()')}" in detail.split("; ")


def test_cfg_test_module_file_is_not_an_orphan_root(tmp_path):
    cargo(tmp_path, "axum")
    write(
        tmp_path,
        MAIN,
        """use axum::{routing::get, Router};
async fn h() {}
fn app() -> Router { Router::new().route("/real", get(h)) }
fn main() { let _ = app(); }
#[cfg(test)] mod tests;
""",
    )
    write(
        tmp_path,
        "src/tests.rs",
        'use axum::{routing::get, Router};\nfn t() { let _ = Router::new().route("/in-test-file", get(h)); }\nmod helpers;\n',
    )
    write(
        tmp_path,
        "src/tests/helpers.rs",
        'use axum::{routing::get, Router};\nfn t() { let _ = Router::new().route("/helper", get(h)); }\n',
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/real")]
    assert verdict(result) == ("complete", "")


def test_cargo_bin_paths_and_src_bin_are_crate_roots(tmp_path):
    cargo(tmp_path, "axum")
    (tmp_path / "Cargo.toml").write_text(
        (tmp_path / "Cargo.toml").read_text()
        + '\n[[bin]]\nname = "srv"\npath = "server/main.rs"\n'
    )
    write(
        tmp_path,
        "server/main.rs",
        """use axum::{routing::get, Router};
mod api;
async fn h() {}
fn main() { let _ = Router::new().route("/srv", get(h)).nest("/a", api::r()); }
""",
    )
    write(
        tmp_path,
        "server/api.rs",
        'use axum::{routing::get, Router};\npub fn r() -> Router { Router::new().route("/x", get(h)) }\nasync fn h() {}\n',
    )
    write(
        tmp_path,
        "src/bin/tool.rs",
        'use axum::{routing::get, Router};\nasync fn h() {}\nfn main() { let _ = Router::new().route("/tool", get(h)); }\n',
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/a/x"), ("GET", "/srv"), ("GET", "/tool")]
    assert verdict(result) == ("complete", "")


def test_local_use_in_function_body_and_fn_named_like_the_macro(tmp_path):
    app(
        tmp_path,
        "actix-web",
        """use actix_web::{get, post, web, App};

#[get("/a")] async fn get() {}
#[post("/b")] async fn post() {}
fn build() -> App<()> {
    use actix_web::web::scope;
    App::new().service(scope("/s").service(get).service(post))
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/s/a"), ("POST", "/s/b")]
    assert verdict(result) == ("complete", "")


def test_rocket_handlers_named_like_attributes_with_glob_imports(tmp_path):
    app(
        tmp_path,
        "rocket",
        """#[macro_use] extern crate rocket;
use diesel::prelude::*;

#[delete("/<id>")] fn delete(id: i64) {}
#[get("/")] fn get() {}

#[launch]
fn rocket() -> _ { rocket::build().mount("/db", routes![get, delete]) }
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/db"), ("DELETE", "/db/<id>")]
    assert verdict(result) == ("complete", "")


def test_rocket_local_handler_fn_and_fairing_struct_hook(tmp_path):
    app(
        tmp_path,
        "rocket",
        """#[macro_use] extern crate rocket;
use rocket::fairing::{Fairing, Info, Kind};
use rocket::{Build, Rocket};

#[derive(Default, Clone)]
struct Counter;

#[rocket::async_trait]
impl Fairing for Counter {
    fn info(&self) -> Info { Info { name: "c", kind: Kind::Ignite } }

    async fn on_ignite(&self, rocket: Rocket<Build>) -> rocket::fairing::Result {
        #[get("/counts")]
        fn counts() -> String { String::new() }

        Ok(rocket.manage(self.clone()).mount("/", routes![counts]))
    }
}

#[launch]
fn rocket() -> _ { rocket::build().attach(Counter::default()) }
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/counts")]
    assert verdict(result) == ("complete", "")


def test_rocket_route_attribute_without_method_takes_every_method(tmp_path):
    app(
        tmp_path,
        "rocket",
        """#[macro_use] extern crate rocket;
#[route("/<_..>")] fn all() {}
#[launch]
fn rocket() -> _ { rocket::build().mount("/", routes![all]).ignite().await.unwrap() }
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("ANY", "/<_..>")]
    assert verdict(result) == ("complete", "")


def test_actix_redirect_service_and_axum_join_macro_arguments(tmp_path):
    app(
        tmp_path,
        "actix-web",
        """use actix_web::{web, App};
async fn index() {}
fn build() -> App<()> {
    App::new().service(web::resource("/index.html").to(index)).service(web::redirect("/", "/index.html"))
}
""",
    )
    assert pairs(run_routes(tmp_path)) == [("ANY", "/"), ("ANY", "/index.html")]
    other = tmp_path / "ax"
    app(
        other,
        "axum",
        """use axum::{routing::get, Router};
async fn h() {}
fn one() -> Router { Router::new().route("/one", get(h)) }
fn two() -> Router { Router::new().route("/two", get(h)) }
async fn serve(app: Router, port: u16) { axum::serve(l, app.layer(x)).await; }
#[tokio::main]
async fn main() {
    tokio::join!(
        serve(one(), 3001),
        serve(two(), 3002),
    );
}
""",
    )
    result = run_routes(other)
    assert pairs(result) == [("GET", "/one"), ("GET", "/two")]
    assert verdict(result) == ("complete", "")


def test_axum_static_router_item_and_result_adaptors(tmp_path):
    src = """use axum::{routing::get, Router};
use std::sync::LazyLock;
async fn h() {}
static APP: LazyLock<Router> = LazyLock::new(|| Router::new().route("/s", get(h)));
async fn build() -> Result<Router, ()> { Ok(Router::new().route("/b", get(h))) }
#[tokio::main]
async fn main() { let app = build().await.unwrap(); axum::serve(l, app).await.unwrap(); }
"""
    app(tmp_path, "axum", src)
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/b")]
    assert verdict(result) == ("partial", f"{MAIN}:{at(src, 'static APP')}")


def test_axum_nest_service_with_a_method_router_and_service_calls(tmp_path):
    app(
        tmp_path,
        "axum",
        """use axum::{routing::get, Router};
use tower::ServiceExt;
async fn h() {}
async fn probe() {
    let router = Router::new().route("/probe", get(h));
    let _ = router.clone().oneshot(req).await.unwrap();
}
fn app() -> Router { Router::new().nest_service("/svc", get(h)) }
fn main() { let _ = app(); }
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/probe"), ("GET", "/svc")]
    assert verdict(result) == ("complete", "")


# --- several frameworks in one package ---------------------------------------------


def test_actix_and_rocket_in_one_package_claim_only_their_own_attributes(tmp_path):
    cargo(tmp_path, "actix-web", "rocket")
    write(
        tmp_path,
        MAIN,
        """mod web_a;
mod web_r;
fn main() {}
""",
    )
    write(
        tmp_path,
        "src/web_a.rs",
        """use actix_web::{get, App};
#[get("/actix")] async fn a() {}
pub fn build() -> App<()> { App::new().service(a) }
""",
    )
    write(
        tmp_path,
        "src/web_r.rs",
        """use rocket::{get, routes};
#[get("/rocket")] fn r() {}
pub fn build() -> rocket::Rocket<rocket::Build> { rocket::build().mount("/", routes![r]) }
""",
    )
    result = run_routes(tmp_path)
    cov = {c.framework: (c.status, c.detail) for c in result.coverage}
    assert cov == {"Actix Web": ("complete", ""), "Rocket": ("complete", "")}
    assert pairs(result) == [("GET", "/actix"), ("GET", "/rocket")]


def test_output_is_deterministic_and_l3_lists_file_and_line(tmp_path):
    src = """use axum::{routing::get, Router};
async fn h() {}
fn app() -> Router {
    Router::new()
        .route("/b", get(h))
        .route("/a", get(h))
}
fn main() { let _ = app(); }
"""
    app(tmp_path, "axum", src)
    first = run_routes(tmp_path)
    second = run_routes(tmp_path)
    assert [(s.id, s.l2_md, s.l3_md) for s in first.sections] == [
        (s.id, s.l2_md, s.l3_md) for s in second.sections
    ]
    (sec,) = first.sections
    assert f"GET /a  h  {MAIN}:{at(src, '/a')}" in sec.l3_md
    assert f"GET /b  h  {MAIN}:{at(src, '/b')}" in sec.l3_md
    assert rows_of(first, MAIN)[0][:2] == ["GET", "/a"]
    assert str(tmp_path) not in everything(first)


# --- wrappers, macros, layout, provenance --------------------------------------


def test_framework_reexported_by_a_wrapper_crate_and_shuttle_config_closure(tmp_path):
    app(
        tmp_path,
        "axum",
        """use shuttle_axum::axum::{routing::get, Router};
async fn h() {}
#[shuttle_runtime::main]
async fn main() -> shuttle_axum::ShuttleAxum {
    let router = Router::new().route("/health", get(h));
    Ok(router.into())
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/health")]
    assert verdict(result) == ("complete", "")
    other = tmp_path / "act"
    app(
        other,
        "actix-web",
        """use actix_web::{get, web::ServiceConfig};
use shuttle_actix_web::ShuttleActixWeb;

#[get("/")]
async fn hello_world() -> &'static str { "Hello World!" }

#[shuttle_runtime::main]
async fn main() -> ShuttleActixWeb<impl FnOnce(&mut ServiceConfig) + Send + Clone + 'static> {
    let config = move |cfg: &mut ServiceConfig| {
        cfg.service(hello_world);
    };
    Ok(config.into())
}
""",
    )
    result = run_routes(other)
    assert pairs(result) == [("GET", "/")]
    assert verdict(result) == ("complete", "")


def test_route_building_macro_rules_are_sites_and_data_macros_are_not(tmp_path):
    src = """use axum::{routing::get, Router};
async fn h() {}

macro_rules! add { ($r:expr, $p:literal) => { $r.route($p, get(h)) }; }
macro_rules! label { ($x:expr) => { format!("{}", $x) }; }

fn app() -> Router {
    let name = label!(1);
    let r = Router::new().route("/a", get(h));
    add!(r, "/b")
}
fn main() { let _ = app(); }
"""
    app(tmp_path, "axum", src)
    result = run_routes(tmp_path)
    status, detail = verdict(result)
    # the macro call, and `app()` whose router could not be built
    assert (status, set(detail.split("; "))) == (
        "partial",
        {f"{MAIN}:{at(src, 'add!(r')}", f"{MAIN}:{at(src, 'fn main')}"},
    )


def test_unknown_prelude_router_and_verbs_are_routing_shaped_sites(tmp_path):
    src = """use shared::prelude::*;
fn app() {
    let r = Router::new().route("/x", get(h));
}
"""
    app(tmp_path, "axum", src)
    result = run_routes(tmp_path)
    assert pairs(result) == []
    assert verdict(result) == ("partial", f"{MAIN}:{at(src, '.route(')}")


def test_actix_resource_guard_picks_the_method(tmp_path):
    app(
        tmp_path,
        "actix-web",
        """use actix_web::{guard, web, App};
async fn h() {}
fn build() -> App<()> {
    App::new()
        .service(web::resource("/g").guard(guard::Get()).to(h))
        .service(web::resource("/any").guard(guard::Header("a", "b")).to(h))
}
""",
    )
    result = run_routes(tmp_path)
    assert triples(result) == [("ANY", "/any", "h"), ("GET", "/g", "h")]


def test_attribute_and_chain_layout_does_not_matter(tmp_path):
    app(
        tmp_path,
        "actix-web",
        """use actix_web::{get, post, web, App};

#[ get (
    // the path
    "/spaced" , /* trailing */
)]
async fn spaced() {}

# [ actix_web :: post ( "/qualified" ) ]
async fn qualified() {}

fn build() -> App<()> {
    App
        ::
        new()
        // comment between calls
        .service( spaced )
        . service(
            web :: scope ( "/s" )
                /* c */ . service ( qualified )
        )
}
""",
    )
    result = run_routes(tmp_path)
    assert triples(result) == [
        ("POST", "/s/qualified", "qualified"),
        ("GET", "/spaced", "spaced"),
    ]
    assert verdict(result) == ("complete", "")


def test_rocket_read_only_rocket_references_are_neither_roots_nor_sites(tmp_path):
    app(
        tmp_path,
        "rocket",
        """#[macro_use] extern crate rocket;
use rocket::{Build, Orbit, Rocket};

#[get("/a")] fn a() {}

fn probe(rocket: &Rocket<Orbit>) -> usize { rocket.routes().count() }

#[launch]
fn rocket() -> _ {
    let r = rocket::build().mount("/", routes![a]);
    let n = external::count(&r);
    r
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/a")]
    assert verdict(result) == ("complete", "")


def test_nested_scopes_and_resources_join_without_doubled_slashes(tmp_path):
    app(
        tmp_path,
        "actix-web",
        """use actix_web::{web, App};
async fn h() {}
fn build() -> App<()> {
    App::new().service(
        web::scope("/api/")
            .service(web::scope("//v1").service(web::resource("/x/").to(h)))
            .service(web::scope("").route("", web::get().to(h))),
    )
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/api"), ("ANY", "/api/v1/x")]


def test_trait_default_methods_and_include_are_not_silently_skipped(tmp_path):
    src = """use axum::{routing::get, Router};
async fn h() {}
trait Plugin {
    fn routes(&self) -> Router { Router::new().route("/p", get(h)) }
}
include!(concat!(env!("OUT_DIR"), "/generated_routes.rs"));
fn main() {}
"""
    app(tmp_path, "axum", src)
    result = run_routes(tmp_path)
    status, detail = verdict(result)
    assert pairs(result) == []
    assert status == "partial"
    # the default method (nobody calls it) and the unseen generated source
    assert set(detail.split("; ")) == {
        f"{MAIN}:{at(src, 'fn routes')}",
        f"{MAIN}:{at(src, 'include!')}",
    }


def test_verb_attribute_of_an_unreadable_crate_is_a_site(tmp_path):
    src = """use actix_web::App;
use ntex::web::get;

#[get("/ntex")]
async fn h() {}

fn build() -> App<()> { App::new() }
"""
    app(tmp_path, "actix-web", src)
    result = run_routes(tmp_path)
    assert pairs(result) == []
    assert verdict(result) == ("partial", f"{MAIN}:{at(src, '#[get')}")


@pytest.mark.parametrize("path", ['""', '"relative"', '"/abs"', "dynamic_path"])
def test_routing_call_on_unknown_receiver_is_a_site_whatever_its_path(tmp_path, path):
    src = f"""use axum::routing::get;
async fn h() {{}}
fn add(thing: crate::Opaque, dynamic_path: &str) {{
    thing.route({path}, get(h));
}}
"""
    app(tmp_path, "axum", src)
    result = run_routes(tmp_path)
    assert verdict(result) == ("partial", f"{MAIN}:{at(src, 'thing.route')}")
