"""Rust exported symbols, and the Rust job scheduler pattern."""

from __future__ import annotations

import pytest

pytest.importorskip("tree_sitter_language_pack")

from tests.rust_support import cargo, everything, run_symbols, sym_rows, write

LIB = """use std::fmt;

pub fn f() {}
pub(crate) fn hidden() {}
pub(super) fn hidden2() {}
pub(in crate::a) fn hidden3() {}
pub(self) fn hidden4() {}
fn private() {}
pub async fn af() {}
pub const fn cf() -> u8 { 0 }
pub unsafe extern "C" fn ef() {}
pub struct S { pub a: u8, b: u8 }
pub struct Unit;
pub struct Tup(pub u8);
pub struct Generic<T: Clone>(T);
struct PrivStruct;
pub(crate) struct CrateStruct;
pub enum E { A, B(u8), C { x: u8 }, D = 3 }
enum Priv { X }
pub(crate) enum PC { Y }
pub trait T { fn m(&self); const K: u8; }
pub type Alias = u8;
pub const MAX: usize = 10;
pub const TOKEN: &str = "sk_live_SECRETVALUE";
pub static GLOBAL: &str = "gh_secret_value";
pub static mut COUNTER: u32 = 0;
pub const _: () = ();
pub mod inner {
    pub fn nested() {}
    fn hidden() {}
    pub struct In;
    pub(crate) struct Mid;
    pub mod deeper { pub const DEEP: u8 = 1; }
}
mod private_mod { pub fn unreachable() {} }
pub use self::inner::In as Reexp;
pub use crate::inner::deeper::DEEP;
use crate::inner::In as NotExported;
impl S { pub fn method() {} }
impl fmt::Display for S { fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result { Ok(()) } }
pub union U { a: u8 }
#[cfg(test)]
pub mod tests { pub fn t() {} }
#[cfg(test)]
pub fn only_in_tests() {}
extern "C" { pub fn c_api(); fn c_private(); pub static C_VAR: u8; }
"""


def test_rust_symbols_pub_items_only(tmp_path):
    cargo(tmp_path)
    write(tmp_path, "src/lib.rs", LIB)
    result = run_symbols(tmp_path)
    f = "src/lib.rs"
    assert sym_rows(result) == sorted(
        [
            ("Alias", "type", f),
            ("COUNTER", "const", f),
            ("C_VAR", "const", f),
            ("DEEP", "const", f),
            ("E", "enum", f),
            ("E.A", "member", f),
            ("E.B", "member", f),
            ("E.C", "member", f),
            ("E.D", "member", f),
            ("GLOBAL", "const", f),
            ("Generic", "class", f),
            ("MAX", "const", f),
            ("Reexp", "class", f),
            ("S", "class", f),
            ("T", "interface", f),
            ("TOKEN", "const", f),
            ("Tup", "class", f),
            ("U", "class", f),
            ("Unit", "class", f),
            ("af", "function", f),
            ("c_api", "function", f),
            ("cf", "function", f),
            ("ef", "function", f),
            ("f", "function", f),
            ("inner", "const", f),
            ("inner::deeper", "const", f),
            ("inner::deeper::DEEP", "const", f),
            ("inner::In", "class", f),
            ("inner::nested", "function", f),
        ]
    )
    cov = [c for c in result.coverage if c.framework == "rust"]
    assert [(c.status, c.detail) for c in cov] == [("complete", "")]


def test_rust_symbols_never_emit_values(tmp_path):
    cargo(tmp_path)
    write(tmp_path, "src/lib.rs", LIB)
    result = run_symbols(tmp_path)
    blob = everything(result)
    assert "SECRETVALUE" not in blob
    assert "gh_secret_value" not in blob
    assert "TOKEN" in blob


def test_rust_symbols_skip_tests_benches_examples_and_generated_dirs(tmp_path):
    cargo(tmp_path)
    write(tmp_path, "src/lib.rs", "pub fn real() {}\n")
    for d in ("tests", "benches", "examples"):
        write(tmp_path, f"{d}/x.rs", f"pub fn from_{d}() {{}}\n")
    result = run_symbols(tmp_path)
    assert [r[0] for r in sym_rows(result)] == ["real"]


def test_rust_symbols_glob_reexport_and_syntax_error_are_sites(tmp_path):
    cargo(tmp_path)
    write(tmp_path, "src/lib.rs", "pub mod a;\npub use a::*;\npub fn k() {}\n")
    write(tmp_path, "src/b.rs", "pub fn broken( {\n")
    result = run_symbols(tmp_path)
    (cov,) = [c for c in result.coverage if c.framework == "rust"]
    assert cov.status == "partial"
    assert set(cov.detail.split("; ")) >= {"src/lib.rs:2", "src/b.rs:1"}


def test_rust_symbols_grouped_and_aliased_reexports(tmp_path):
    cargo(tmp_path)
    write(
        tmp_path,
        "src/lib.rs",
        "pub use crate::a::{Foo, bar, baz as qux};\npub use other::Thing;\n"
        "pub(crate) use crate::a::Hidden;\nuse crate::a::Private;\n",
    )
    result = run_symbols(tmp_path)
    assert sym_rows(result) == [
        ("Foo", "class", "src/lib.rs"),
        ("Thing", "class", "src/lib.rs"),
        ("bar", "function", "src/lib.rs"),
        ("qux", "function", "src/lib.rs"),
    ]


def test_language_without_rust_exporter_is_not_scanned(tmp_path, monkeypatch):
    from strata_kb.codeingest.extractors import symbols

    cargo(tmp_path)
    write(tmp_path, "src/lib.rs", "pub fn f() {}\n")
    monkeypatch.delitem(symbols.EXPORTERS, "rust")
    result = run_symbols(tmp_path)
    (cov,) = [c for c in result.coverage if c.framework == "rust"]
    assert cov.status == "not scanned"


def test_rust_tokio_cron_scheduler_jobs_pattern_is_covered(tmp_path):
    """Task 8 owns the pattern; this pins the `Job::new_async` / `_cron_job`
    spellings a typical tokio-cron-scheduler app uses."""
    from strata_kb.codeingest.extractors import jobs
    from tests.rust_support import opts

    cargo(tmp_path, "tokio-cron-scheduler")
    write(
        tmp_path,
        "src/main.rs",
        "use tokio_cron_scheduler::{Job, JobScheduler};\n"
        "async fn main() {\n"
        "    let sched = JobScheduler::new().await.unwrap();\n"
        '    sched.add(Job::new_async("0 0 * * * *", |_u, _l| Box::pin(async {})).unwrap()).await.unwrap();\n'
        '    sched.add(Job::new_cron_job("1/7 * * * * *", run)).await.unwrap();\n'
        "    sched.add(Job::new_one_shot(Duration::from_secs(5), run)).await.unwrap();\n"
        "}\n",
    )
    result = jobs.JobsExtractor().extract(tmp_path, opts(tmp_path))
    (sec,) = [s for s in result.sections if s.title == "src/main.rs"]
    assert "0 0 * * * *" in sec.l2_md
    assert "1/7 * * * * *" in sec.l2_md
