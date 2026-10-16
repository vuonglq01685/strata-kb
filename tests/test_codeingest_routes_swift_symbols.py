"""Swift exported symbols: `public` / `open` declarations, names only."""

from __future__ import annotations

import pytest

pytest.importorskip("tree_sitter_language_pack")

from tests.swift_support import (
    everything,
    run_symbols,
    sym_rows,
    vapor_package,
    write,
)

LIB = """import Foundation

public class Open1 {}
open class Open2 {}
class Internal {}
internal class Internal2 {}
private class Priv {}
fileprivate class FPriv {}
package class Pkg {}
public final class Final {}
public struct S { public var a: Int; var b: Int; public func m() {}; func hidden() {} }
public actor A {}
public enum Color: String {
    case red = "r", green
    case blue
    indirect case tree(Int)
    public func name() -> String { "x" }
    static let k = 1
}
enum Hidden { case x }
public protocol P { associatedtype T; var p: Int { get }; func f() }
public typealias Alias = [String]
typealias Local = Int
public func free<T>(_ a: T) {}
func hiddenFn() {}
public var counter = 0
public let (x, y) = (1, 2)
public let a1 = 1, a2 = 2
public var computed: Int { 1 }
public private(set) var readOnly = 3
private(set) public static var shared = 4
private(set) var internalGet = 5
let implicitInternal = 6
"""


def test_swift_symbols_public_and_open_only(tmp_path):
    vapor_package(tmp_path)
    write(tmp_path, "Sources/Lib/Lib.swift", LIB)
    result = run_symbols(tmp_path)
    f = "Sources/Lib/Lib.swift"
    assert sym_rows(result) == sorted(
        [
            ("A", "class", f),
            ("Alias", "type", f),
            ("Color", "enum", f),
            ("Color.blue", "member", f),
            ("Color.green", "member", f),
            ("Color.name", "function", f),
            ("Color.red", "member", f),
            ("Color.tree", "member", f),
            ("Final", "class", f),
            ("Open1", "class", f),
            ("Open2", "class", f),
            ("P", "interface", f),
            ("P.T", "type", f),
            ("P.f", "function", f),
            ("P.p", "const", f),
            ("S", "class", f),
            ("S.a", "const", f),
            ("S.m", "function", f),
            ("a1", "const", f),
            ("a2", "const", f),
            ("computed", "const", f),
            ("counter", "const", f),
            ("free", "function", f),
            ("readOnly", "const", f),
            ("shared", "const", f),
            ("x", "const", f),
            ("y", "const", f),
        ]
    )
    (cov,) = [r for r in result.coverage if r.framework == "swift"]
    assert (cov.status, cov.detail) == ("complete", "")


def test_swift_nested_types_and_non_public_containers(tmp_path):
    vapor_package(tmp_path)
    write(
        tmp_path,
        "Sources/Lib/Nested.swift",
        """public struct Outer {
    public struct Inner { public static let id = 1 }
    struct Hidden { public var leaked = 1 }
    public enum Kind { case a, b }
    public typealias Id = Int
}
struct Internal {
    public struct NotReachable {}
    public func notExported() {}
}
""",
    )
    got = {(n, k) for n, k, _ in sym_rows(run_symbols(tmp_path))}
    assert got == {
        ("Outer", "class"),
        ("Outer.Inner", "class"),
        ("Outer.Inner.id", "const"),
        ("Outer.Kind", "enum"),
        ("Outer.Kind.a", "member"),
        ("Outer.Kind.b", "member"),
        ("Outer.Id", "type"),
    }


def test_swift_extension_members(tmp_path):
    vapor_package(tmp_path)
    write(
        tmp_path,
        "Sources/Lib/Ext.swift",
        """public extension Array where Element == Int {
    func sum() -> Int { 0 }
    var total: Int { 0 }
    private func hidden() {}
    internal func internalOne() {}
    typealias Pair = (Int, Int)
}
extension String {
    public func slug() -> String { self }
    func internalSlug() -> String { self }
    public static let empty = ""
}
extension Foo.Bar: Codable {
    public var id: Int { 1 }
}
private extension Int {
    public func neverVisible() {}
}
public extension Dictionary<String, Int> {
    func total() -> Int { 0 }
}
""",
    )
    got = {(n, k) for n, k, _ in sym_rows(run_symbols(tmp_path))}
    assert got == {
        ("Array.sum", "function"),
        ("Array.total", "const"),
        ("Array.Pair", "type"),
        ("String.slug", "function"),
        ("String.empty", "const"),
        ("Foo.Bar.id", "const"),
        ("Dictionary.total", "function"),
    }


def test_swift_symbols_never_leak_values(tmp_path):
    vapor_package(tmp_path)
    write(
        tmp_path,
        "Sources/Lib/Secrets.swift",
        """public let apiKey = "sk_live_SECRETVALUE123"
public var token: String = "ghp_TOPSECRETTOKEN"
public enum Env: String {
    case prod = "prod-password-hunter2"
    case dev = "dev-password-hunter3"
}
public struct Config {
    public static let dsn = "postgres://user:SECRETPW@host/db"
    public static let limit = 99_887_766
}
public let flags = ["xoxb-SLACKSECRET"]
""",
    )
    result = run_symbols(tmp_path)
    blob = everything(result)
    for secret in (
        "SECRETVALUE123",
        "TOPSECRETTOKEN",
        "hunter2",
        "hunter3",
        "SECRETPW",
        "99_887_766",
        "SLACKSECRET",
    ):
        assert secret not in blob
    names = {n for n, _k, _f in sym_rows(result)}
    assert {"apiKey", "token", "Env.prod", "Env.dev", "Config.dsn", "flags"} <= names


def test_swift_symbols_skip_tests_and_syntax_error_is_partial(tmp_path):
    vapor_package(tmp_path)
    write(tmp_path, "Tests/AppTests/AppTests.swift", "public struct InTests {}\n")
    write(tmp_path, "Sources/Lib/Good.swift", "public struct Good {}\n")
    write(tmp_path, "Sources/Lib/Bad.swift", "public struct Bad {\n  func ((( \n")
    result = run_symbols(tmp_path)
    assert {n for n, _k, _f in sym_rows(result)} >= {"Good"}
    assert "InTests" not in everything(result)
    (cov,) = [r for r in result.coverage if r.framework == "swift"]
    assert cov.status == "partial"
    assert "Sources/Lib/Bad.swift:" in cov.detail
    assert "skipped 1 test" in cov.detail


def test_swift_package_manifest_exports_nothing(tmp_path):
    vapor_package(tmp_path)
    result = run_symbols(tmp_path)
    assert sym_rows(result) == []


def test_swift_hostile_nesting_does_not_crash(tmp_path):
    vapor_package(tmp_path)
    depth = 400
    src = "".join(f"public struct S{i} {{\n" for i in range(depth)) + "}\n" * depth
    write(tmp_path, "Sources/Lib/Deep.swift", src)
    result = run_symbols(tmp_path)
    assert result is not None
    (cov,) = [r for r in result.coverage if r.framework == "swift"]
    assert cov.status in ("complete", "partial")


def test_swift_conditional_compilation_attributes_and_backticks(tmp_path):
    vapor_package(tmp_path)
    write(
        tmp_path,
        "Sources/Lib/Mixed.swift",
        """#if os(macOS)
public struct Mac {}
#else
public struct Linux {}
#endif
@available(*, deprecated) public func old() {}
@MainActor public final class VM { public static let `default` = VM() }
open class Base {
    open func over() {}
    public final func fin() {}
    func hidden() {}
}
public func + (lhs: Mac, rhs: Mac) -> Mac { lhs }
""",
    )
    got = {(n, k) for n, k, _ in sym_rows(run_symbols(tmp_path))}
    assert got == {
        ("Mac", "class"),
        ("Linux", "class"),
        ("old", "function"),
        ("VM", "class"),
        ("VM.default", "const"),
        ("Base", "class"),
        ("Base.over", "function"),
        ("Base.fin", "function"),
    }
