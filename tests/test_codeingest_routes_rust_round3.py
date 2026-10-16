"""Rust fix round 3: unknown and diverging arms/returns in joins, equal
static services, rocket builders from two branches."""

from __future__ import annotations

import pytest

pytest.importorskip("tree_sitter_language_pack")

from tests.rust_support import MAIN, app, at, pairs, run_routes, verdict

AX = "use axum::{routing::get, Router};\nasync fn h() {}\n"

# --- 1. an unknown arm / return is not dropped ----------------------------------


def test_axum_if_with_an_unknown_arm_is_a_site(tmp_path):
    src = (
        AX
        + """fn app(f: bool) -> Router {
    let docs: Router = if f { shared::SwaggerUi::new("/docs").into() } else { Router::new() };
    Router::new().route("/a", get(h)).merge(docs)
}
fn main() { let _ = app(true); }
"""
    )
    app(tmp_path, "axum", src)
    result = run_routes(tmp_path)
    # the unknown `docs` router is merged somewhere: never a silent complete
    assert verdict(result)[0] == "partial"


def test_axum_router_arm_vs_external_router_arm_is_a_site(tmp_path):
    src = (
        AX
        + """fn sub(f: bool) -> Router {
    if f { Router::new().route("/a", get(h)) } else { other::router() }
}
fn app() -> Router { Router::new().nest("/x", sub(true)) }
fn main() { let _ = app(); }
"""
    )
    app(tmp_path, "axum", src)
    result = run_routes(tmp_path)
    assert verdict(result)[0] == "partial"
    assert ("GET", "/x/a") not in pairs(result)


def test_axum_early_return_with_unknown_tail_is_a_site(tmp_path):
    src = (
        AX
        + """fn sub(f: bool) -> Router {
    if f { return Router::new().route("/a", get(h)); }
    other::router()
}
fn app() -> Router { Router::new().nest("/x", sub(true)) }
fn main() { let _ = app(); }
"""
    )
    app(tmp_path, "axum", src)
    result = run_routes(tmp_path)
    assert verdict(result)[0] == "partial"
    assert ("GET", "/x/a") not in pairs(result)


def test_closure_returning_a_path_with_an_unknown_tail_is_a_site(tmp_path):
    src = (
        AX
        + """fn main() {
    let pre = |c: bool| { if c { return "/a"; } other::path() };
    let _ = Router::new().nest(pre(true), Router::new().route("/x", get(h)));
}
"""
    )
    app(tmp_path, "axum", src)
    result = run_routes(tmp_path)
    assert verdict(result) == ("partial", f"{MAIN}:{at(src, '.nest(pre')}")


def test_actix_scope_arm_unknown_is_a_site(tmp_path):
    src = """use actix_web::{web, App};
async fn h() {}
fn build(f: bool) -> App<()> {
    App::new().service(if f { web::scope("/x").route("/a", web::get().to(h)) } else { other::scope() })
}
"""
    app(tmp_path, "actix-web", src)
    result = run_routes(tmp_path)
    assert verdict(result)[0] == "partial"
    assert pairs(result) == []


def test_rocket_routes_arm_unknown_is_a_site(tmp_path):
    src = """#[macro_use] extern crate rocket;
#[get("/r")] fn r() {}
#[launch]
fn rocket() -> _ {
    let l = if cfg!(debug_assertions) { routes![r] } else { other::routes() };
    rocket::build().mount("/", l)
}
"""
    app(tmp_path, "rocket", src)
    result = run_routes(tmp_path)
    assert verdict(result)[0] == "partial"
    assert pairs(result) == []


# --- diverging arms are ignored ---------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        'panic!("no")',
        "unreachable!()",
        "todo!()",
        "unimplemented!()",
        "return Router::new()",
    ],
)
def test_diverging_arms_do_not_spoil_a_router_or_a_string(tmp_path, bad):
    src = (
        AX
        + f"""fn app(n: u8) -> Router {{
    let pre = match n {{ 1 => "/one", _ => {bad} }};
    let r = match n {{ 1 => Router::new().route("/a", get(h)), _ => {bad} }};
    Router::new().nest(pre, r)
}}
fn main() {{ let _ = app(1); }}
"""
    )
    app(tmp_path, "axum", src)
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/one/a")]
    assert verdict(result) == ("complete", "")


def test_loop_break_and_continue_arms_do_not_spoil_a_string(tmp_path):
    app(
        tmp_path,
        "axum",
        AX
        + """fn main() {
    for n in 0..3 {
        let pre = match n { 0 => "/z", 1 => continue, _ => break };
        let _ = Router::new().nest(pre, Router::new().route("/a", get(h)));
    }
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/z/a")]
    assert verdict(result) == ("complete", "")


def test_return_then_known_tail_in_a_fn_and_closure_stays_known(tmp_path):
    app(
        tmp_path,
        "axum",
        AX
        + """fn sub(f: bool) -> Router {
    if f { return Router::new().route("/a", get(h)); }
    Router::new().route("/b", get(h))
}
fn main() {
    let pre = |c: bool| { if c { return "/p"; } "/p" };
    let p = pre(true);
    let _ = Router::new().nest(p, sub(true));
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/p/a"), ("GET", "/p/b")]
    assert verdict(result) == ("complete", "")


# --- 2. equal static services -----------------------------------------------------


def test_axum_equal_static_services_from_two_branches(tmp_path):
    app(
        tmp_path,
        "axum",
        AX
        + """use tower_http::services::ServeDir;
fn main() {
    let svc = if std::env::var("A").is_ok() { ServeDir::new("a") } else { ServeDir::new("b") };
    let _ = Router::new().route("/x", get(h)).nest_service("/s", svc);
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/x")]
    assert verdict(result) == ("complete", "")


def test_actix_equal_static_services_from_two_branches(tmp_path):
    app(
        tmp_path,
        "actix-web",
        """use actix_files::Files;
use actix_web::App;
fn build(f: bool) -> App<()> {
    App::new().service(if f { Files::new("/a", "x") } else { Files::new("/b", "y") })
}
""",
    )
    assert verdict(run_routes(tmp_path)) == ("complete", "")


# --- 3. two rocket builders ---------------------------------------------------------


def test_rocket_builders_from_two_branches_are_unioned(tmp_path):
    app(
        tmp_path,
        "rocket",
        """#[macro_use] extern crate rocket;
#[get("/r")] fn r() {}
#[get("/s")] fn s() {}
#[get("/t")] fn t() {}
#[launch]
fn rocket() -> _ {
    let b = if cfg!(debug_assertions) { rocket::build().mount("/a", routes![r]) } else { rocket::build().mount("/b", routes![s]) };
    b.mount("/c", routes![t])
}
""",
    )
    result = run_routes(tmp_path)
    assert ("GET", "/c/t") in pairs(result)
    assert ("GET", "/a/r") in pairs(result)
    assert ("GET", "/b/s") in pairs(result)
    assert verdict(result) == ("complete", "")
