"""Rust fix round 2: branch-joined paths, identifier paths on unknown
receivers, router type aliases as return types."""

from __future__ import annotations

import pytest

pytest.importorskip("tree_sitter_language_pack")

from tests.rust_support import MAIN, app, at, pairs, run_routes, verdict

# --- 1. a path chosen by `if` / `match` ------------------------------------------


def test_axum_nest_prefix_chosen_by_if_is_a_site(tmp_path):
    src = """use axum::{routing::get, Router};
async fn h() {}
fn app(flag: bool) -> Router {
    let pre = if flag { "/a" } else { "/b" };
    Router::new().nest(pre, Router::new().route("/x", get(h)))
}
fn main() { let _ = app(std::env::var("F").is_ok()); }
"""
    app(tmp_path, "axum", src)
    result = run_routes(tmp_path)
    assert pairs(result) == []
    assert verdict(result) == ("partial", f"{MAIN}:{at(src, '.nest(pre')}")


def test_actix_scope_prefix_chosen_by_match_is_a_site(tmp_path):
    src = """use actix_web::{web, App};
async fn h() {}
fn build(n: u8) -> App<()> {
    let pre = match n { 1 => "/one", _ => "/other" };
    App::new().service(web::scope(pre).route("/x", web::get().to(h)))
}
"""
    app(tmp_path, "actix-web", src)
    result = run_routes(tmp_path)
    assert pairs(result) == []
    assert verdict(result) == ("partial", f"{MAIN}:{at(src, 'web::scope(pre)')}")


def test_rocket_mount_base_chosen_by_match_is_a_site(tmp_path):
    src = """#[macro_use] extern crate rocket;
#[get("/r")] fn r() {}
#[launch]
fn rocket() -> _ {
    let base = match std::env::var("M") { Ok(_) => "/a", Err(_) => "/b" };
    rocket::build().mount(base, routes![r])
}
"""
    app(tmp_path, "rocket", src)
    result = run_routes(tmp_path)
    assert pairs(result) == []
    assert verdict(result) == ("partial", f"{MAIN}:{at(src, '.mount(base')}")


def test_branches_that_agree_or_build_routers_still_resolve(tmp_path):
    app(
        tmp_path,
        "axum",
        """use axum::{routing::get, Router};
async fn h() {}
fn app(flag: bool) -> Router {
    let pre = if flag { "/same" } else { "/same" };
    let r = if flag { Router::new().route("/a", get(h)) } else { Router::new().route("/b", get(h)) };
    Router::new().nest(pre, r)
}
fn main() { let _ = app(true); }
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/same/a"), ("GET", "/same/b")]
    assert verdict(result) == ("complete", "")


# --- 2. identifier paths on an unknown receiver --------------------------------


@pytest.mark.parametrize(
    "path", ["dynamic_path", "&dynamic_path", "crate::P", 'format!("/{}", 1)']
)
def test_identifier_path_on_unknown_receiver_is_a_site(tmp_path, path):
    src = f"""use actix_web::web;
fn add(thing: crate::Opaque, dynamic_path: &str) {{
    thing.route({path}, unknown::route());
}}
"""
    app(tmp_path, "actix-web", src)
    assert verdict(run_routes(tmp_path)) == (
        "partial",
        f"{MAIN}:{at(src, 'thing.route')}",
    )
    ax = tmp_path / "ax"
    src = f"""use axum::routing::get;
async fn h() {{}}
fn add(thing: crate::Opaque, dynamic_path: &str) {{
    thing.route({path}, get(h));
    thing.nest({path}, unknown::router());
}}
"""
    app(ax, "axum", src)
    assert verdict(run_routes(ax))[0] == "partial"
    rk = tmp_path / "rk"
    src = f"""#[macro_use] extern crate rocket;
fn add(thing: crate::Opaque, dynamic_path: &str) {{
    thing.mount({path}, unknown::routes());
}}
"""
    app(rk, "rocket", src)
    assert verdict(run_routes(rk)) == ("partial", f"{MAIN}:{at(src, 'thing.mount')}")


def test_numeric_first_argument_is_not_routing(tmp_path):
    app(
        tmp_path,
        "axum",
        """use axum::{routing::get, Router};
async fn h() {}
fn f(t: crate::Opaque) { let _ = t.route(1, 2); let _ = t.route(true, 2); }
fn main() { let _ = Router::new().route("/ok", get(h)); }
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/ok")]
    assert verdict(result) == ("complete", "")


# --- 3. a type alias as a router fn's return type ------------------------------


def test_router_alias_return_type_is_a_router_fn_not_a_bare_root(tmp_path):
    app(
        tmp_path,
        "axum",
        """use axum::{routing::get, Router};
type Api = Router<()>;
async fn h() {}
fn api() -> Api { Router::new().route("/s", get(h)) }
fn app() -> Router { Router::new().nest("/api", api()) }
fn main() { let _ = app(); }
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/api/s")]
    assert verdict(result) == ("complete", "")


def test_router_alias_param_is_not_a_root(tmp_path):
    src = """use axum::{routing::get, Router};
type Api = Router<()>;
async fn h() {}
pub fn add(r: Api) -> Api { r.route("/x", get(h)) }
"""
    app(tmp_path, "axum", src, "src/lib.rs")
    result = run_routes(tmp_path)
    assert pairs(result) == []
    assert verdict(result) == ("partial", f"src/lib.rs:{at(src, 'pub fn add')}")
