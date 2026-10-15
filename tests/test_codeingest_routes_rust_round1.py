"""Rust fix round 1: cfg predicates, rewritten strings, unknown receivers,
type aliases, `#[path]` anchoring."""

from __future__ import annotations

import pytest

pytest.importorskip("tree_sitter_language_pack")

from tests.rust_support import (
    MAIN,
    app,
    at,
    cargo,
    pairs,
    run_routes,
    run_symbols,
    sym_rows,
    verdict,
    write,
)

# --- 1. cfg predicates --------------------------------------------------------

_SERVE = """use axum::{{routing::get, Router}};
async fn h() {{}}
#[cfg({pred})]
fn main() {{
    let app = Router::new().route("/x", get(h));
    axum::serve(l, app);
}}
"""


@pytest.mark.parametrize(
    "pred",
    [
        'not(any(test, feature = "mock"))',
        'not(feature = "test-utils")',
        'feature = "test-utils"',
        "all(not(test), unix)",
        'any(test, feature = "x")',
        "not(test)",
        "unix",
    ],
)
def test_cfg_that_can_hold_outside_tests_is_product_code(tmp_path, pred):
    app(tmp_path, "axum", _SERVE.format(pred=pred))
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/x")]
    assert verdict(result) == ("complete", "")


@pytest.mark.parametrize("pred", ["test", "all(test, unix)", "all(unix, test)"])
def test_cfg_that_only_holds_under_test_is_skipped(tmp_path, pred):
    app(tmp_path, "axum", _SERVE.format(pred=pred))
    assert pairs(run_routes(tmp_path)) == []


def test_cfg_gated_symbols_follow_the_same_rule(tmp_path):
    cargo(tmp_path)
    write(
        tmp_path,
        "src/lib.rs",
        '#[cfg(not(any(test, feature = "mock")))]\npub fn prod() {}\n'
        "#[cfg(all(test, unix))]\npub fn only_test() {}\n",
    )
    assert [r[0] for r in sym_rows(run_symbols(tmp_path))] == ["prod"]


# --- 2. strings written more than once ----------------------------------------


def test_reassigned_path_string_is_a_site_not_the_last_value(tmp_path):
    src = """use axum::{routing::get, Router};
async fn h() {}
fn app(flag: bool) -> Router {
    let mut base = "/v1";
    if flag { base = "/v2"; }
    Router::new().route(base, get(h))
}
fn main() { let _ = app(true); }
"""
    app(tmp_path, "axum", src)
    result = run_routes(tmp_path)
    assert pairs(result) == []
    assert verdict(result) == ("partial", f"{MAIN}:{at(src, 'route(base')}")


def test_rocket_mount_base_rewritten_in_a_loop_is_a_site(tmp_path):
    src = """#[macro_use] extern crate rocket;
#[get("/r")] fn r() {}
#[launch]
fn rocket() -> _ {
    let mut base = "/a";
    for _ in 0..2 { base = "/b"; }
    rocket::build().mount(base, routes![r])
}
"""
    app(tmp_path, "rocket", src)
    result = run_routes(tmp_path)
    assert pairs(result) == []
    assert verdict(result) == ("partial", f"{MAIN}:{at(src, '.mount(base')}")


def test_immutable_and_shadowed_strings_still_resolve(tmp_path):
    app(
        tmp_path,
        "axum",
        """use axum::{routing::get, Router};
async fn h() {}
fn main() {
    let base = "/v1";
    let base = "/v2";
    let _ = Router::new().route(base, get(h));
}
""",
    )
    assert pairs(run_routes(tmp_path)) == [("GET", "/v2")]


def test_const_declared_twice_with_different_values_is_a_site(tmp_path):
    src = """use axum::{routing::get, Router};
async fn h() {}
#[cfg(feature = "a")] const P: &str = "/a";
#[cfg(not(feature = "a"))] const P: &str = "/b";
fn main() { let _ = Router::new().route(P, get(h)); }
"""
    app(tmp_path, "axum", src)
    result = run_routes(tmp_path)
    assert pairs(result) == []
    assert verdict(result) == ("partial", f"{MAIN}:{at(src, 'route(P')}")


def test_use_alias_bound_twice_to_different_paths_is_unresolved(tmp_path):
    src = """#[cfg(feature = "a")] use axum::routing::get;
#[cfg(not(feature = "a"))] use other::get;
use axum::Router;
async fn h() {}
fn main() { let _ = Router::new().route("/x", get(h)); }
"""
    app(tmp_path, "axum", src)
    result = run_routes(tmp_path)
    assert pairs(result) == []
    assert verdict(result)[0] == "partial"


# --- 3. unknown receivers (rulings 12, 14) ------------------------------------


def test_actix_unknown_receiver_chain_is_a_site(tmp_path):
    src = """use actix_web::{App, HttpServer};
fn main() {
    HttpServer::new(|| shared::app().route("/x", shared::get_route()).service(shared::svc()));
}
"""
    app(tmp_path, "actix-web", src)
    result = run_routes(tmp_path)
    assert pairs(result) == []
    assert verdict(result) == ("partial", f"{MAIN}:{at(src, 'HttpServer::new')}")


@pytest.mark.parametrize("path", ['""', '"relative"', '"/abs"'])
def test_actix_and_rocket_unknown_receiver_whatever_the_path(tmp_path, path):
    src = f"""use actix_web::web;
fn add(thing: crate::Opaque) {{
    thing.route({path}, unknown::route());
}}
"""
    app(tmp_path, "actix-web", src)
    assert verdict(run_routes(tmp_path)) == (
        "partial",
        f"{MAIN}:{at(src, 'thing.route')}",
    )
    other = tmp_path / "rk"
    src = f"""#[macro_use] extern crate rocket;
fn add(thing: crate::Opaque) {{
    thing.mount({path}, unknown::routes());
}}
"""
    app(other, "rocket", src)
    assert verdict(run_routes(other)) == ("partial", f"{MAIN}:{at(src, 'thing.mount')}")


# --- 4. aliases and #[path] ---------------------------------------------------


def test_type_alias_of_a_router_is_still_a_router(tmp_path):
    app(
        tmp_path,
        "axum",
        """use axum::{routing::get, Router};
type Api = Router<()>;
async fn h() {}
fn app() -> Api { Api::new().route("/a", get(h)) }
fn main() { let _ = app(); }
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/a")]
    assert verdict(result) == ("complete", "")


def test_type_alias_of_an_external_type_is_not_provably_non_router(tmp_path):
    src = """use axum::routing::get;
type Reg = shared::Registry;
async fn h() {}
fn f(r: Reg) { r.route("/x", get(h)); }
"""
    app(tmp_path, "axum", src)
    assert verdict(run_routes(tmp_path)) == ("partial", f"{MAIN}:{at(src, 'r.route')}")


def test_path_attribute_in_a_non_mod_rs_file_is_relative_to_that_file_dir(tmp_path):
    cargo(tmp_path, "axum")
    write(tmp_path, MAIN, "mod web;\nfn main() { let _ = web::r(); }\n")
    write(
        tmp_path,
        "src/web.rs",
        '#[path = "extra/x.rs"]\nmod x;\npub fn r() -> axum::Router { x::r() }\n',
    )
    write(
        tmp_path,
        "src/extra/x.rs",
        "use axum::{routing::get, Router};\nasync fn h() {}\n"
        'pub fn r() -> Router { Router::new().route("/w/x", get(h)) }\n',
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/w/x")]
    assert verdict(result) == ("complete", "")


def test_cfg_test_enum_variant_is_not_exported(tmp_path):
    cargo(tmp_path)
    write(tmp_path, "src/lib.rs", "pub enum C { A, #[cfg(test)] T }\n")
    assert [r[0] for r in sym_rows(run_symbols(tmp_path))] == ["C", "C.A"]
