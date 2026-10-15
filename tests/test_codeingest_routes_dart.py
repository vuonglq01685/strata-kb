"""Dart: top-level exported names and enum values; Flutter has no HTTP routes
(its page routes are the `pages` extractor's, test_codeingest_pages.py)."""

from __future__ import annotations

import pytest

pytest.importorskip("tree_sitter_language_pack")

from tests.swift_support import (
    everything,
    pubspec,
    run_routes,
    run_symbols,
    sym_rows,
    write,
)

LIB = """library app;

import 'package:flutter/material.dart';

class Public {
  int field = 1;
  void method() {}
  static const kInner = 'inner-secret';
}
abstract class Abstract {}
sealed class Sealed {}
base class Base {}
final class Fin {}
interface class Iface {}
mixin class MixClass {}
mixin Mixin on Public {}
class Applied = Public with Mixin;
class _Private {}
mixin _PrivateMixin {}
enum Color { red, green('x'), blue, _hidden;
  const Color([this.v]);
  final v = 1;
}
enum _Secret { a }
extension Named on String { int get n => 1; }
extension on int { int get twice => this * 2; }
extension _PrivExt on String {}
extension type Meters(int value) {}
typedef Callback = void Function(int);
typedef void OldStyle(int a);
typedef _PrivDef = int;
void topFunction() {}
Future<int> asyncFn() async => 1;
int _hidden() => 1;
int get topGetter => 1;
set topSetter(int v) {}
const kVersion = '1.0.0';
final shared = Object(), other = 2;
var mutable = 3, _w = 4;
String? nullable;
late int late1;
int _private1 = 1;
void main() {}
"""


def test_dart_symbols_top_level_names_and_enum_values(tmp_path):
    pubspec(tmp_path, "flutter")
    write(tmp_path, "lib/app.dart", LIB)
    result = run_symbols(tmp_path)
    f = "lib/app.dart"
    assert sym_rows(result) == sorted(
        [
            ("Abstract", "class", f),
            ("Applied", "class", f),
            ("Base", "class", f),
            ("Callback", "type", f),
            ("Color", "enum", f),
            ("Color.blue", "member", f),
            ("Color.green", "member", f),
            ("Color.red", "member", f),
            ("Fin", "class", f),
            ("Iface", "class", f),
            ("Meters", "class", f),
            ("MixClass", "class", f),
            ("Mixin", "class", f),
            ("Named", "class", f),
            ("OldStyle", "type", f),
            ("Public", "class", f),
            ("Sealed", "class", f),
            ("asyncFn", "function", f),
            ("kVersion", "const", f),
            ("late1", "const", f),
            ("main", "function", f),
            ("mutable", "const", f),
            ("nullable", "const", f),
            ("other", "const", f),
            ("shared", "const", f),
            ("topFunction", "function", f),
            ("topGetter", "function", f),
            ("topSetter", "function", f),
        ]
    )
    (cov,) = [r for r in result.coverage if r.framework == "dart"]
    assert (cov.status, cov.detail) == ("complete", "")


def test_dart_part_of_files_are_read_and_generated_parts_are_skipped(tmp_path):
    pubspec(tmp_path, "flutter")
    write(tmp_path, "lib/model.dart", "part 'model.g.dart';\nclass Model {}\n")
    write(
        tmp_path,
        "lib/model_part.dart",
        "part of 'model.dart';\nclass PartClass {}\nvoid partFn() {}\n",
    )
    write(
        tmp_path,
        "lib/model.g.dart",
        "part of 'model.dart';\nModel _$ModelFromJson() => Model();\nclass GeneratedPublic {}\n",
    )
    write(tmp_path, "lib/model.freezed.dart", "class FrozenPublic {}\n")
    write(tmp_path, "test/model_test.dart", "void testHelper() {}\n")
    write(tmp_path, "lib/widget_test.dart", "void alsoTest() {}\n")
    result = run_symbols(tmp_path)
    assert {n for n, _k, _f in sym_rows(result)} == {"Model", "PartClass", "partFn"}
    (cov,) = [r for r in result.coverage if r.framework == "dart"]
    assert cov.status == "complete"
    assert cov.detail == "skipped 2 generated, 2 test"


def test_dart_symbols_never_leak_values(tmp_path):
    pubspec(tmp_path, "flutter")
    write(
        tmp_path,
        "lib/secrets.dart",
        """const apiKey = 'sk_live_SECRETVALUE123';
final dsn = 'postgres://user:SECRETPW@host/db';
var token = "ghp_TOPSECRETTOKEN", limit = 99887766;
enum Env { prod('prod-password-hunter2'), dev('dev-password-hunter3');
  const Env(this.password);
  final String password;
}
class Config { static const secret = 'CLASSSECRET'; }
""",
    )
    result = run_symbols(tmp_path)
    blob = everything(result)
    for secret in (
        "SECRETVALUE123",
        "SECRETPW",
        "TOPSECRETTOKEN",
        "99887766",
        "hunter2",
        "hunter3",
        "CLASSSECRET",
    ):
        assert secret not in blob
    names = {n for n, _k, _f in sym_rows(result)}
    assert {"apiKey", "dsn", "token", "limit", "Env.prod", "Env.dev"} <= names
    assert "Config.secret" not in names


def test_dart_syntax_error_is_partial_not_a_crash(tmp_path):
    pubspec(tmp_path, "flutter")
    write(tmp_path, "lib/good.dart", "class Good {}\n")
    write(tmp_path, "lib/bad.dart", "class Bad { void f( {\n")
    result = run_symbols(tmp_path)
    assert "Good" in {n for n, _k, _f in sym_rows(result)}
    (cov,) = [r for r in result.coverage if r.framework == "dart"]
    assert cov.status == "partial"
    assert "lib/bad.dart:" in cov.detail


def test_flutter_scope_has_no_http_route_rows(tmp_path):
    pubspec(tmp_path, "flutter")
    write(
        tmp_path,
        "lib/main.dart",
        "import 'package:flutter/material.dart';\n"
        "void main() { runApp(MaterialApp(routes: {'/home': (c) => Home()})); }\n",
    )
    result = run_routes(tmp_path)
    assert result.sections == []
    assert [r for r in result.coverage if r.area == "routes"] == []
