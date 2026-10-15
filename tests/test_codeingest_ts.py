"""Tree-sitter layer (codeingest.extractors._ts): suffix map, string literals."""

from __future__ import annotations

import sys

import pytest

pytest.importorskip("tree_sitter_language_pack")
from strata_kb.codeingest.extractors import _ts


def test_language_for_maps_suffixes():
    assert _ts.language_for("apps/api/src/a.controller.ts") == "typescript"
    assert _ts.language_for("x/page.tsx") == "tsx"
    assert _ts.language_for("x/y.MJS") == "javascript"
    assert _ts.language_for("README.md") is None
    assert _ts.language_for("Makefile") is None


def test_string_literal_plain_vs_dynamic():
    t = _ts.parse("typescript", b'f("a/b"); f(`x${y}`); f("a" + b); f(`plain`)')
    calls = [
        m["arg"][0]
        for m in _ts.matches(
            "typescript",
            "(call_expression arguments: (arguments . (_) @arg))",
            t.root_node,
        )
    ]
    assert [_ts.string_literal(n) for n in calls] == ["a/b", None, None, "plain"]


def test_string_literal_python_fstring_is_dynamic():
    t = _ts.parse("python", b'f("a")\nf(f"{x}/b")\n')
    args = [
        m["a"][0]
        for m in _ts.matches(
            "python", "(call arguments: (argument_list . (_) @a))", t.root_node
        )
    ]
    assert [_ts.string_literal(n) for n in args] == ["a", None]


def test_available_false_when_pack_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "tree_sitter_language_pack", None)
    assert _ts.available() is False


def test_available_true_with_pack():
    assert _ts.available() is True


def test_node_text_and_line_of():
    t = _ts.parse("python", b"x = 1\nf('\xff')\n")
    call = t.root_node.children[1]
    assert _ts.line_of(call) == 2
    assert "�" in _ts.node_text(call)


def test_matches_returns_capture_lists_and_caches_query():
    t = _ts.parse("python", b"def a(): pass\ndef b(): pass\n")
    q = "(function_definition name: (identifier) @n)"
    got = _ts.matches("python", q, t.root_node)
    assert [_ts.node_text(m["n"][0]) for m in got] == ["a", "b"]
    assert _ts.matches(
        "python", q, t.root_node
    )  # second call reuses the compiled query


# (lang, source, call-query, expected string_literal of each first argument)
_CASES = {
    "java": (
        b'class A { void m() { f("a/b"); f("a" + b); } }',
        "(method_invocation arguments: (argument_list . (_) @a))",
        ["a/b", None],
    ),
    "kotlin": (
        b'fun m() { f("a/b"); f("x$y"); f("x${y}") }',
        "(call_expression (call_suffix (value_arguments (value_argument . (_) @a))))",
        ["a/b", None, None],
    ),
    "csharp": (
        b'class A { void M() { F("a/b"); F($"x{y}"); F(@"v/w"); } }',
        "(invocation_expression arguments: (argument_list (argument . (_) @a)))",
        ["a/b", None, "v/w"],
    ),
    "go": (
        b'package p\nfunc m() { f("a/b"); f(`raw/p`); f("a" + b) }',
        "(call_expression arguments: (argument_list . (_) @a))",
        ["a/b", "raw/p", None],
    ),
    "rust": (
        b'fn m() { f("a/b"); f(r"raw/p"); f(r#"hash/p"#); f(x) }',
        "(call_expression arguments: (arguments . (_) @a))",
        ["a/b", "raw/p", "hash/p", None],
    ),
    "php": (
        b'<?php f(\'a/b\'); f("c/d"); f("$x"); f("{$x}/b");',
        "(function_call_expression arguments: (arguments (argument . (_) @a)))",
        ["a/b", "c/d", None, None],
    ),
    "swift": (
        b'f("a/b"); f("\\(x)")',
        "(call_expression (call_suffix (value_arguments (value_argument . (_) @a))))",
        ["a/b", None],
    ),
    "dart": (
        b"void m() { f('a/b'); f(\"c/d\"); f('$x'); f('${x}'); f('a' 'b'); }",
        "(argument_part (arguments (argument . (_) @a)))",
        ["a/b", "c/d", None, None, None],
    ),
    "javascript": (
        b"f('a'); f(`p`); f(`x${y}`)",
        "(call_expression arguments: (arguments . (_) @a))",
        ["a", "p", None],
    ),
}


@pytest.mark.parametrize("lang", sorted(_CASES))
def test_string_literal_per_language(lang):
    src, query, expected = _CASES[lang]
    root = _ts.parse(lang, src).root_node
    args = [m["a"][0] for m in _ts.matches(lang, query, root)]
    assert [_ts.string_literal(n) for n in args] == expected
