"""Rust fix round 4: labeled blocks, `Err` / `None` returns, `return` in
async blocks, shadowed diverging macros, rocket diverging macro arms."""

from __future__ import annotations

import pytest

pytest.importorskip("tree_sitter_language_pack")

from tests.rust_support import app, pairs, run_routes, verdict

AX = "use axum::{routing::get, Router};\nasync fn h() {}\n"


def _axum(tmp_path, src):
    app(tmp_path, "axum", AX + src)
    return run_routes(tmp_path)


# --- 1. a labeled block is not diverging ------------------------------------------


def test_labeled_block_break_value_arm_is_not_dropped_for_a_string(tmp_path):
    result = _axum(
        tmp_path,
        """fn main() {
    let pre = match 1 { 1 => "/a", _ => 'b: { break 'b other::p(); } };
    let _ = Router::new().nest(pre, Router::new().route("/x", get(h)));
}
""",
    )
    assert verdict(result)[0] == "partial"
    assert ("GET", "/a/x") not in pairs(result)


def test_labeled_block_break_value_arm_is_not_dropped_for_a_router(tmp_path):
    result = _axum(
        tmp_path,
        """fn main() {
    let r = match 1 { 1 => Router::new().route("/a", get(h)), _ => 'b: { break 'b other::r(); } };
    let _ = Router::new().nest("/x", r);
}
""",
    )
    assert verdict(result)[0] == "partial"


def test_labeled_block_conditional_break_does_not_pick_the_tail(tmp_path):
    result = _axum(
        tmp_path,
        """fn main() {
    let c = std::env::var("A").is_ok();
    let pre = 'b: { if c { break 'b "/v2"; } "/v1" };
    let _ = Router::new().nest(pre, Router::new().route("/x", get(h)));
}
""",
    )
    assert verdict(result)[0] == "partial"
    assert ("GET", "/v1/x") not in pairs(result)


def test_labeled_block_break_router_and_tail_are_joined(tmp_path):
    result = _axum(
        tmp_path,
        """fn app() -> Router {
    let r = 'blk: { if true { break 'blk Router::new().route("/a", get(h)); } Router::new() };
    r
}
fn main() { let _ = Router::new().nest("/x", app()); }
""",
    )
    assert ("GET", "/x/a") in pairs(result)


def test_labeled_block_without_a_break_keeps_its_value(tmp_path):
    result = _axum(
        tmp_path,
        """fn main() {
    let pre = 'b: { "/v1" };
    let _ = Router::new().nest(pre, Router::new().route("/x", get(h)));
}
""",
    )
    assert pairs(result) == [("GET", "/v1/x")]
    assert verdict(result) == ("complete", "")


# --- 2a. `Err` / `None` returns make no router -----------------------------------


@pytest.mark.parametrize(
    "ret_ty, bail, wrap",
    [
        ("Result<Router, String>", 'return Err("bad".to_string());', "Ok({})"),
        ("Option<Router>", "return None;", "Some({})"),
        ("Result<Router, String>", 'Err("bad".to_string())?;', "Ok({})"),
    ],
)
def test_err_and_none_returns_are_ignored_in_the_join(tmp_path, ret_ty, bail, wrap):
    router = wrap.format('Router::new().route("/a", get(h))')
    result = _axum(
        tmp_path,
        f"""fn sub(ok: bool) -> {ret_ty} {{
    if !ok {{ {bail} }}
    {router}
}}
fn main() {{ let _ = Router::new().nest("/x", sub(true).unwrap()); }}
""",
    )
    assert pairs(result) == [("GET", "/x/a")]
    assert verdict(result) == ("complete", "")


def test_err_question_mark_arm_is_ignored_in_a_join(tmp_path):
    result = _axum(
        tmp_path,
        """fn sub(n: u8) -> Result<Router, String> {
    let r = match n { 1 => Router::new().route("/a", get(h)), _ => Err("bad".to_string())? };
    Ok(r)
}
fn main() { let _ = Router::new().nest("/x", sub(1).unwrap()); }
""",
    )
    assert pairs(result) == [("GET", "/x/a")]
    assert verdict(result) == ("complete", "")


def test_err_return_beside_an_unknown_tail_stays_a_site(tmp_path):
    result = _axum(
        tmp_path,
        """fn sub(ok: bool) -> Result<Router, String> {
    if !ok { return Err("bad".to_string()); }
    other::router()
}
fn main() { let _ = Router::new().nest("/x", sub(true).unwrap()); }
""",
    )
    assert verdict(result)[0] == "partial"


# --- 2b. `return` in an async block / closure is its own ------------------------


def test_return_in_an_async_block_does_not_leak_into_the_fn(tmp_path):
    result = _axum(
        tmp_path,
        """fn sub() -> Router {
    tokio::spawn(async move { return; });
    let _ = async { return 1; };
    Router::new().route("/a", get(h))
}
fn main() { let _ = Router::new().nest("/x", sub()); }
""",
    )
    assert pairs(result) == [("GET", "/x/a")]
    assert verdict(result) == ("complete", "")


def test_return_in_a_closure_does_not_leak_into_the_fn(tmp_path):
    result = _axum(
        tmp_path,
        """fn sub() -> Router {
    let _ = [1, 2].iter().map(|x| { if *x > 1 { return 0; } 1 });
    Router::new().route("/a", get(h))
}
fn main() { let _ = Router::new().nest("/x", sub()); }
""",
    )
    assert pairs(result) == [("GET", "/x/a")]
    assert verdict(result) == ("complete", "")


# --- 3. diverging macros: std paths without a shadowing macro_rules -----------------


def test_std_qualified_diverging_macro_arm_is_ignored(tmp_path):
    result = _axum(
        tmp_path,
        """fn main() {
    let pre = match 1 { 1 => "/a", _ => std::unreachable!() };
    let _ = Router::new().nest(pre, Router::new().route("/x", get(h)));
}
""",
    )
    assert pairs(result) == [("GET", "/a/x")]
    assert verdict(result) == ("complete", "")


def test_foreign_path_diverging_macro_arm_is_unknown(tmp_path):
    result = _axum(
        tmp_path,
        """fn main() {
    let pre = match 1 { 1 => "/a", _ => mymacros::todo!("/b") };
    let _ = Router::new().nest(pre, Router::new().route("/x", get(h)));
}
""",
    )
    assert verdict(result)[0] == "partial"
    assert ("GET", "/a/x") not in pairs(result)


def test_repo_macro_shadowing_a_diverging_macro_is_unknown(tmp_path):
    result = _axum(
        tmp_path,
        """macro_rules! todo { ($e:expr) => { $e } }
fn main() {
    let pre = match 1 { 1 => "/a", _ => todo!(other::p()) };
    let _ = Router::new().nest(pre, Router::new().route("/x", get(h)));
}
""",
    )
    assert verdict(result)[0] == "partial"
    assert ("GET", "/a/x") not in pairs(result)


# --- 4. rocket ignores diverging macro arms ---------------------------------------


@pytest.mark.parametrize("bad", ["unreachable!()", 'panic!("no")', "todo!()"])
def test_rocket_diverging_macro_arm_is_ignored(tmp_path, bad):
    app(
        tmp_path,
        "rocket",
        f"""#[macro_use] extern crate rocket;
#[get("/r")] fn r() {{}}
#[launch]
fn rocket() -> _ {{
    let base = match 1 {{ 1 => "/p", _ => {bad} }};
    rocket::build().mount(base, routes![r])
}}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/p/r")]
    assert verdict(result) == ("complete", "")
