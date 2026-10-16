"""Rust: Rocket routes -- attribute macros, mount, routes![], fairings."""

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

ROCKET = "rocket"

# --- typical app --------------------------------------------------------------

TYPICAL_MAIN = """#[macro_use]
extern crate rocket;

use rocket::fs::{relative, FileServer};
use rocket::serde::json::Json;
use rocket::{Build, Rocket, State};
use rocket_dyn_templates::Template;

mod auth;
mod models;
mod posts;
mod users;

#[get("/")]
fn index() -> &'static str {
    "hi"
}

#[get("/hello/<name>?<greeting>")]
fn hello(name: &str, greeting: Option<&str>) -> String {
    format!("{greeting:?} {name}")
}

#[post("/echo", data = "<body>", format = "json", rank = 2)]
fn echo(body: Json<models::Echo>, _guard: auth::ApiKey) -> Json<models::Echo> {
    body
}

#[catch(404)]
fn not_found() -> &'static str {
    "nope"
}

#[launch]
fn rocket() -> _ {
    let secret = std::env::var("SECRET_KEY").unwrap_or_default();
    rocket::build()
        .attach(Template::fairing())
        .attach(auth::stage())
        .manage(models::Db::default())
        .register("/", catchers![not_found])
        .mount("/", routes![index, hello, echo])
        .mount("/users", users::routes())
        .mount("/static", FileServer::from(relative!("static")))
        .mount("/posts", routes![posts::list, posts::show, posts::create])
}
"""

TYPICAL_USERS = """use rocket::Route;

#[get("/")]
pub fn list() -> &'static str { "" }

#[get("/<id>")]
pub fn show(id: u32) -> String { id.to_string() }

#[put("/<id>", data = "<form>")]
pub fn update(id: u32, form: rocket::form::Form<Edit>) {}

pub fn routes() -> Vec<Route> {
    routes![list, show, update]
}
"""

TYPICAL_POSTS = """#[get("/")]
pub fn list() {}
#[get("/<id>")]
pub fn show(id: usize) {}
#[post("/", data = "<post>")]
pub fn create(post: Json<Post>) {}
"""

TYPICAL_AUTH = """use rocket::fairing::AdHoc;

pub struct ApiKey;

pub fn stage() -> AdHoc {
    AdHoc::on_ignite("Auth", |rocket| async {
        rocket.mount("/auth", routes![login, logout])
    })
}

#[post("/login")]
fn login() {}
#[delete("/logout")]
fn logout() {}
"""


def test_typical_rocket_app_reaches_complete(tmp_path):
    app(tmp_path, ROCKET, TYPICAL_MAIN)
    write(tmp_path, "src/users.rs", TYPICAL_USERS)
    write(tmp_path, "src/posts.rs", TYPICAL_POSTS)
    write(tmp_path, "src/auth.rs", TYPICAL_AUTH)
    write(tmp_path, "src/models.rs", "pub struct Echo; pub struct Db;\n")
    result = run_routes(tmp_path)
    assert verdict(result) == ("complete", "")
    assert triples(result) == [
        ("GET", "/", "index"),
        ("POST", "/auth/login", "login"),
        ("DELETE", "/auth/logout", "logout"),
        ("POST", "/echo", "echo"),
        ("GET", "/hello/<name>", "hello"),
        ("GET", "/posts", "posts::list"),
        ("POST", "/posts", "posts::create"),
        ("GET", "/posts/<id>", "posts::show"),
        ("GET", "/users", "list"),
        ("GET", "/users/<id>", "show"),
        ("PUT", "/users/<id>", "update"),
    ]
    assert "SECRET_KEY" not in everything(result)


def test_rocket_prefix_and_path_param_table_rows(tmp_path):
    app(
        tmp_path,
        ROCKET,
        """use rocket::{get, routes};

#[get("/<id>/items/<rest..>")]
fn items(id: u32, rest: std::path::PathBuf) {}

fn build() -> rocket::Rocket<rocket::Build> {
    rocket::build().mount("/shops", routes![items])
}
""",
    )
    result = run_routes(tmp_path)
    assert rows_of(result, MAIN) == [
        ["GET", "/shops/<id>/items/<rest..>", "items", MAIN, ""]
    ]
    assert verdict(result) == ("complete", "")


def test_rocket_attribute_forms_and_launch_variants(tmp_path):
    app(
        tmp_path,
        ROCKET,
        """use rocket::{delete, get, head, options, patch, post, put, route, routes};

#[get("/g")] fn g() {}
#[post("/p")] fn p() {}
#[put("/u")] fn u() {}
#[delete("/d")] fn d() {}
#[patch("/pa")] fn pa() {}
#[head("/h")] fn h() {}
#[options("/o")] fn o() {}
#[route(GET, uri = "/r")] fn r() {}
#[rocket::get("/q")] async fn q() {}
#[get(path = "/kw")] fn kw() {}

#[rocket::main]
async fn main() -> Result<(), rocket::Error> {
    let _r = rocket::build()
        .mount("/", routes![g, p, u, d, pa, h, o, r, q, kw])
        .launch()
        .await?;
    Ok(())
}
""",
    )
    result = run_routes(tmp_path)
    assert verdict(result) == ("complete", "")
    assert triples(result) == [
        ("DELETE", "/d", "d"),
        ("GET", "/g", "g"),
        ("HEAD", "/h", "h"),
        ("GET", "/kw", "kw"),
        ("OPTIONS", "/o", "o"),
        ("POST", "/p", "p"),
        ("PATCH", "/pa", "pa"),
        ("GET", "/q", "q"),
        ("GET", "/r", "r"),
        ("PUT", "/u", "u"),
    ]


def test_rocket_ignite_custom_and_multiple_mounts(tmp_path):
    app(
        tmp_path,
        ROCKET,
        """#[macro_use] extern crate rocket;

#[get("/a")] fn a() {}
#[get("/b")] fn b() {}

fn old() -> rocket::Rocket {
    rocket::ignite().mount("/one", routes![a]).mount("/two", routes![a, b])
}
fn cfg() -> rocket::Rocket<rocket::Build> {
    rocket::custom(rocket::Config::default()).mount("/c", routes![b])
}
""",
    )
    result = run_routes(tmp_path)
    assert verdict(result) == ("complete", "")
    assert pairs(result) == [
        ("GET", "/c/b"),
        ("GET", "/one/a"),
        ("GET", "/two/a"),
        ("GET", "/two/b"),
    ]


def test_rocket_const_base(tmp_path):
    app(
        tmp_path,
        ROCKET,
        """#[macro_use] extern crate rocket;
const BASE: &str = "/api";
#[get("/x")] fn x() {}
#[launch]
fn rocket() -> _ { rocket::build().mount(BASE, routes![x]) }
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/api/x")]
    assert verdict(result) == ("complete", "")


# --- partial / sites ----------------------------------------------------------


def test_rocket_dynamic_path_partial(tmp_path):
    src = """#[macro_use] extern crate rocket;

#[get("/x")] fn x() {}
#[get("/y")] fn y() {}
#[get("/z")] fn z() {}

#[launch]
fn rocket(base: &str) -> _ {
    rocket::build()
        .mount(base, routes![x])
        .mount(format!("/f{}", 1), routes![y])
        .mount("/ok", routes![z])
}
"""
    app(tmp_path, ROCKET, src)
    result = run_routes(tmp_path)
    status, detail = verdict(result)
    assert status == "partial"
    assert set(detail.split("; ")) == {
        f"{MAIN}:{at(src, '.mount(base')}",
        f"{MAIN}:{at(src, 'format!')}",
    }
    assert pairs(result) == [("GET", "/ok/z")]  # never under a wrong prefix


def test_rocket_dynamic_attribute_path_is_a_site(tmp_path):
    src = """#[macro_use] extern crate rocket;

#[get(concat!("/a", "/b"))] fn a() {}
#[get("/ok")] fn ok() {}

#[launch]
fn rocket() -> _ { rocket::build().mount("/", routes![a, ok]) }
"""
    app(tmp_path, ROCKET, src)
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/ok")]
    assert verdict(result) == ("partial", f"{MAIN}:{at(src, 'concat!')}")


def test_rocket_unmounted_handler_is_a_site_not_a_route(tmp_path):
    src = """#[macro_use] extern crate rocket;

#[get("/live")] fn live() {}
#[get("/dead")] fn dead() {}

#[launch]
fn rocket() -> _ { rocket::build().mount("/", routes![live]) }
"""
    app(tmp_path, ROCKET, src)
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/live")]
    dead = '#[get("/dead")]'
    assert verdict(result) == ("partial", f"{MAIN}:{at(src, dead)}")


def test_rocket_unknown_mount_arguments_are_sites(tmp_path):
    src = """#[macro_use] extern crate rocket;

#[launch]
fn rocket() -> _ {
    rocket::build()
        .mount("/docs", rocket_okapi::swagger_ui::make_swagger_ui(&cfg()))
        .mount("/ext", other_crate::routes())
        .mount("/ok", routes![])
}
"""
    app(tmp_path, ROCKET, src)
    result = run_routes(tmp_path)
    status, detail = verdict(result)
    assert status == "partial"
    assert set(detail.split("; ")) == {
        f"{MAIN}:{at(src, 'make_swagger_ui')}",
        f"{MAIN}:{at(src, 'other_crate::routes')}",
    }


def test_rocket_mount_on_unresolved_receiver_is_a_site_and_others_ignored(tmp_path):
    src = """#[macro_use] extern crate rocket;

#[get("/x")] fn x() {}

fn add(thing: crate::Opaque) {
    thing.mount("/hidden", routes![x]);
}

fn fs(m: &mut std::collections::HashMap<u8, u8>) {
    let _ = std::fs::read("a");
    let _ = m.get(&1);
    let _ = reqwest::get("https://example.com");
    let _ = reqwest::Client::new().get("https://example.com/x");
    let _ = nix::mount::mount(Some("/a"), "/b", None::<&str>, 0, None::<&str>);
}
"""
    app(tmp_path, ROCKET, src)
    result = run_routes(tmp_path)
    assert pairs(result) == []
    status, detail = verdict(result)
    assert status == "partial"
    assert f"{MAIN}:{at(src, 'thing.mount')}" in detail.split("; ")
    unmounted = '#[get("/x")]'
    assert f"{MAIN}:{at(src, unmounted)}" in detail.split("; ")
    assert len(detail.split("; ")) == 2


# --- ordering, modules --------------------------------------------------------


@pytest.mark.parametrize(
    ("first", "second"), [("a_app", "z_routes"), ("z_app", "a_routes")]
)
def test_rocket_registering_file_before_or_after_defining_file(tmp_path, first, second):
    cargo(tmp_path, ROCKET)
    write(tmp_path, "src/main.rs", f"mod {first};\nmod {second};\nfn main() {{}}\n")
    write(
        tmp_path,
        f"src/{first}.rs",
        f"""use rocket::routes;
pub fn build() -> rocket::Rocket<rocket::Build> {{
    rocket::build().mount("/m", routes![crate::{second}::items])
}}
""",
    )
    write(
        tmp_path,
        f"src/{second}.rs",
        'use rocket::get;\n#[get("/items")]\npub fn items() {}\n',
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/m/items")]
    assert verdict(result) == ("complete", "")
    assert rows_of(result, f"src/{second}.rs") == [
        ["GET", "/m/items", f"crate::{second}::items", f"src/{second}.rs", ""]
    ]


def test_rocket_attribute_of_another_framework_is_not_claimed(tmp_path):
    cargo(tmp_path, ROCKET, "actix-web")
    write(
        tmp_path,
        MAIN,
        """use rocket::{get, routes};
mod other;
#[get("/r")] fn r() {}
fn build() -> rocket::Rocket<rocket::Build> { rocket::build().mount("/", routes![r]) }
""",
    )
    write(
        tmp_path, "src/other.rs", 'use actix_web::get;\n#[get("/a")] async fn a() {}\n'
    )
    result = run_routes(tmp_path)
    rocket = [c for c in result.coverage if c.framework == "Rocket"]
    assert [(c.status, c.detail) for c in rocket] == [("complete", "")]
    assert ("GET", "/r") in pairs(result)


def test_rocket_hostile_input_does_not_crash(tmp_path):
    depth = 2500
    chain = "".join(f'.mount("/m{i}", routes![x])' for i in range(depth))
    junk = "w(" * 3000 + "x" + ")" * 3000
    cargo(tmp_path, ROCKET)
    write(
        tmp_path,
        MAIN,
        f"""#[macro_use] extern crate rocket;
#[get("/x")] fn x() {{}}
fn long() -> rocket::Rocket<rocket::Build> {{ rocket::build(){chain} }}
fn deep() -> rocket::Rocket<rocket::Build> {{ rocket::build().mount("/j", {junk}) }}
""",
    )
    result = run_routes(tmp_path)
    assert len(pairs(result)) == depth
    assert verdict(result)[0] == "partial"


def test_rocket_tests_and_cfg_test_are_skipped(tmp_path):
    cargo(tmp_path, ROCKET)
    write(
        tmp_path,
        MAIN,
        """#[macro_use] extern crate rocket;
#[get("/real")] fn real() {}
#[launch]
fn rocket() -> _ { rocket::build().mount("/", routes![real]) }

#[cfg(test)]
mod tests {
    use super::*;
    use rocket::local::blocking::Client;
    #[get("/only-test")] fn only() {}
    #[test]
    fn t() {
        let client = Client::tracked(rocket::build().mount("/", routes![only])).unwrap();
        client.get("/real").dispatch();
    }
}
""",
    )
    write(
        tmp_path,
        "tests/it.rs",
        '#[macro_use] extern crate rocket;\n#[get("/it")] fn it() {}\nfn f() { rocket::build().mount("/i", routes![it]); }\n',
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/real")]
    assert verdict(result) == ("complete", "")


def test_rocket_declaration_shape_fuzz_never_crashes(tmp_path):
    cargo(tmp_path, ROCKET)
    write(
        tmp_path,
        MAIN,
        """#[macro_use] extern crate rocket;
use std::{fmt, io::{self, Read}};
pub(crate) use crate::x::{self, y as _, z::*};

macro_rules! m { ($($t:tt)*) => {}; }
m!(a, b, c);
struct S<T: Clone = u8>(T) where T: Send;
#[get("/z")] fn z() {}

fn generic<'a, T: Into<String> + 'a, const N: usize>(x: &'a [T; N], (a, b): (u8, u8), _: ()) -> impl Fn() -> T + 'a { move || todo!() }

#[launch]
fn rocket() -> _ {
    let (a, b) = (1, 2);
    let [c, _] = [1, 2];
    let S(d) = S(1u8);
    let (x, y, q) = f();
    let Some(e) = None::<u8> else { return rocket::build() };
    let _: () = if true { () } else { loop {} };
    match 3 { 1 | 2 => {} n if n > 2 => {} _ => {} }
    let cl = |a: u8, (b, c): (u8, u8)| a + b + c;
    unsafe { let _ = 1; }
    'l: loop { break 'l; }
    rocket::build().mount("/ok", routes![z])
}
""",
    )
    result = run_routes(tmp_path)
    assert result.warnings == []
    assert row(result).status in ("complete", "partial")
    assert ("GET", "/ok/z") in pairs(result)
