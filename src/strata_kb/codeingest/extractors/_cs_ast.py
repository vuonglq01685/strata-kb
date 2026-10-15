"""C# syntax-tree helpers shared by the .NET route adapters
(`_routes_dotnet`, `_routes_dotnet_minimal`), the request-type field reader
and the csharp symbol exporter.

Callers see `Attr` (an attribute with its arguments), `Param`, type
declarations and their members, and string / string-array values. Parsed
trees and source bytes are read once per routes run (`_jvm_ast.run_cached`,
opened by `RoutesExtractor.extract`). Internal to the `_routes_dotnet*` /
`_dotnet_*` / `_symbols_csharp` modules.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors import _ts
from strata_kb.codeingest.extractors._jvm_ast import run_cached
from strata_kb.codeingest.extractors._routes_jsutil import _read, _text, _walk

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

LANG = "csharp"
TYPE_NODES = frozenset(
    {
        "class_declaration",
        "interface_declaration",
        "struct_declaration",
        "record_declaration",
        "enum_declaration",
    }
)
# a directory or file that only holds tests (`tests/`, `Api.Tests/`,
# `ApiIntegrationTests/`, `FooTests.cs`); case-sensitive on purpose, so
# `Contest.cs` or `Latest/` stay product code
_TEST_PATH = re.compile(
    r"(?:^|/)(?:tests?|Tests?|[^/]*\.Tests?|[^/]*Tests)/|(?:Tests?)\.cs$"
)
_TYPE_DECL = re.compile(
    rb"\b(?:class|interface|struct|enum|record(?:\s+(?:class|struct))?)\s+(\w+)"
)
_OTHER_TARGETS = ("return", "assembly", "module")
_CONDITIONAL = frozenset({"preproc_if", "preproc_elif", "preproc_else"})
_ATTRIBUTE_ALTERNATIVES = frozenset(
    {
        "preproc_if_in_attribute_list",
        "preproc_elif_in_attribute_list",
        "preproc_else_in_attribute_list",
    }
)
_GENERIC_ARGS = re.compile(r"<.*>", re.DOTALL)


def is_test(rel: str) -> bool:
    return bool(_TEST_PATH.search(rel))


def cs_files(files: list[str]) -> list[str]:
    """C# product sources of a scope (test projects skipped)."""
    return [f for f in files if _ts.language_for(f) == LANG and not is_test(f)]


def source(root: Path, rel: str) -> bytes | None:
    """File bytes, read once per run (scopes and the repo-wide scans share)."""
    return run_cached(("cs-source", root, rel), lambda: _read(root, rel))


def tree(root: Path, rel: str, data: bytes) -> Tree:
    return run_cached(("cs-tree", root, rel), lambda: _ts.parse(LANG, data))


def declared_names(root: Path, repo_files: list[str]) -> dict[str, list[str]]:
    """Simple type name -> the repo files that declare a type of that name."""

    def scan() -> dict[str, list[str]]:
        found: dict[str, list[str]] = {}
        for rel in cs_files(repo_files):
            data = source(root, rel)
            if data is None:
                continue
            for name in sorted({m.decode() for m in _TYPE_DECL.findall(data)}):
                found.setdefault(name, []).append(rel)
        return found

    return run_cached(("cs-names", root), scan)


@dataclass
class Attr:
    name: str  # last segment, without `Attribute` (`Mvc.HttpGetAttribute` -> `HttpGet`)
    line: int
    args: list[tuple[str | None, Node]]  # (keyword or None, value)
    # inside `#if` / `#else`: which alternative is compiled is not known here
    conditional: bool = False

    def arg(self, *keys: str) -> Node | None:
        """The value given for the first of `keys`; with `""` among them,
        the positional (unnamed) argument too."""
        for key, value in self.args:
            if (key or "") in keys:
                return value
        return None

    def positional(self) -> list[Node]:
        return [v for k, v in self.args if k is None]


@dataclass
class Param:
    name: str
    type: str
    attrs: list[Attr]
    default: bool
    this: bool = False


def simple_name(node: Node | str | None) -> str:
    """`a.b.Foo<T>` -> `Foo`."""
    text = node if isinstance(node, str) else _text(node)
    return _GENERIC_ARGS.sub("", text).rsplit(".", 1)[-1].strip()


def _attr(node: Node) -> Attr:
    name = simple_name(node.child_by_field_name("name"))
    if name.endswith("Attribute") and len(name) > len("Attribute"):
        name = name[: -len("Attribute")]
    args: list[tuple[str | None, Node]] = []
    listing = next(
        (c for c in node.children if c.type == "attribute_argument_list"), None
    )
    for arg in listing.named_children if listing is not None else []:
        kids = [c for c in arg.named_children if "comment" not in c.type]
        key = arg.child_by_field_name("name")
        if key is not None and len(kids) >= 2:
            args.append((_text(key), kids[-1]))
        elif kids:
            args.append((None, kids[-1]))
    return Attr(name, _ts.line_of(node), args)


def _lists(node: Node, conditional: bool = False) -> Iterator[tuple[Node, bool]]:
    for child in node.children:
        if child.type == "attribute_list":
            yield child, conditional
        elif child.type in _ATTRIBUTE_ALTERNATIVES or (
            conditional and child.type in _CONDITIONAL
        ):
            yield from _lists(child, True)


def attrs_of(decl: Node) -> list[Attr]:
    """Attributes in the `attribute_list`s of a declaration or parameter,
    those under `#if` / `#else` included (marked `conditional`);
    `[return: ...]`, `[assembly: ...]` and `[module: ...]` are not the
    declaration's own."""
    out: list[Attr] = []
    for lst, conditional in _lists(decl):
        spec = next(
            (c for c in lst.children if c.type == "attribute_target_specifier"), None
        )
        if spec is not None and _text(spec).startswith(_OTHER_TARGETS):
            continue
        for node in lst.named_children:
            if node.type == "attribute":
                attr = _attr(node)
                attr.conditional = conditional
                out.append(attr)
    return out


def modifiers(decl: Node) -> set[str]:
    return {_text(c) for c in decl.children if c.type == "modifier"}


def decl_name(decl: Node) -> str:
    return _text(decl.child_by_field_name("name"))


def name_line(decl: Node) -> int:
    named = decl.child_by_field_name("name")
    return _ts.line_of(named if named is not None else decl)


def type_decls(root: Node) -> Iterator[Node]:
    """Every class / interface / struct / record / enum declaration, nested
    ones included, in source order."""
    for node in _walk(root):
        if node.type in TYPE_NODES:
            yield node


def members_of(node: Node) -> list[Node]:
    """Named children, with the members of `#if` / `#else` branches spliced
    in (every branch counts: which one is compiled is not known here)."""
    out: list[Node] = []
    for child in node.named_children:
        if child.type in _CONDITIONAL:
            out += members_of(child)
        else:
            out.append(child)
    return out


def body_members(decl: Node) -> list[Node]:
    body = decl.child_by_field_name("body")
    return members_of(body) if body is not None else []


def methods(decl: Node) -> list[Node]:
    return [m for m in body_members(decl) if m.type == "method_declaration"]


def base_names(decl: Node) -> list[str]:
    """Simple names of the base class and interfaces, in source order."""
    out: list[str] = []
    for lst in decl.children:
        if lst.type != "base_list":
            continue
        for item in lst.named_children:
            if item.type == "primary_constructor_base_type" and item.named_children:
                item = item.named_children[0]
            out.append(simple_name(item))
    return out


def has_type_parameters(decl: Node) -> bool:
    return any(c.type == "type_parameter_list" for c in decl.children)


def params(method: Node) -> list[Param]:
    listing = method.child_by_field_name("parameters")
    if listing is None:
        listing = next((c for c in method.children if c.type == "parameter_list"), None)
    out: list[Param] = []
    for p in listing.named_children if listing is not None else []:
        if p.type != "parameter":
            continue
        out.append(
            Param(
                _text(p.child_by_field_name("name")),
                _text(p.child_by_field_name("type")),
                attrs_of(p),
                any(c.type == "=" for c in p.children),
                any(c.type == "modifier" and _text(c) == "this" for c in p.children),
            )
        )
    return out


def literal(node: Node | None) -> str | None:
    """Content of a plain string literal (escapes `\\"` and `\\\\` decoded),
    else None: an interpolation, a concatenation, a constant."""
    value = _ts.string_literal(node) if node is not None else None
    return re.sub(r'\\(["\\])', r"\1", value) if value is not None else None


def strings(node: Node | None) -> list[str] | None:
    """Plain string literals of a value (`"a"`, `new[] {"a"}`, `["a"]`);
    None when any item is computed."""
    if node is None:
        return None
    items: list[Node]
    if node.type in ("array_creation_expression", "implicit_array_creation_expression"):
        init = next(
            (c for c in node.children if c.type == "initializer_expression"), None
        )
        if init is None:
            return None
        items = list(init.named_children)
    elif node.type == "initializer_expression":
        items = list(node.named_children)
    elif node.type == "collection_expression":
        items = []
        for element in node.named_children:
            if element.type != "collection_element" or not element.named_children:
                return None
            inner = element.named_children[0]
            if inner.type != "expression_element" or not inner.named_children:
                return None
            items.append(inner.named_children[0])
    else:
        items = [node]
    out = [literal(i) for i in items]
    return None if any(v is None for v in out) else [v for v in out if v is not None]
