"""Java / Kotlin syntax-tree helpers shared by the JVM route adapters,
the request-type field reader and the symbol exporters.

The two grammars disagree on almost everything (annotation nodes, class
names, parameter lists), so the differences are absorbed here: callers see
`Ann` (an annotation with its arguments), `Param`, class-like declarations
and their methods, and string-array values, whatever the language.
Internal to the `_routes_jvm` / `_jvm_*` / `_symbols_jvm` modules.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors import _ts
from strata_kb.codeingest.extractors._routes_jsutil import _text, _walk

if TYPE_CHECKING:
    from tree_sitter import Node

JVM_LANGS = frozenset({"java", "kotlin"})
CLASS_TYPES = frozenset(
    {
        "class_declaration",
        "interface_declaration",
        "record_declaration",
        "enum_declaration",
        "object_declaration",
    }
)
_ARRAY_TYPES = frozenset({"element_value_array_initializer", "collection_literal"})
_ARRAY_CALLS = frozenset({"arrayOf", "listOf", "setOf"})
_TEST_DIR = re.compile(
    r"(?:^|/)src/(?:test|integrationTest|testFixtures|functionalTest)/"
)
# `FooTest.java` is a test only outside `src/main`: `ABTest` can be a product class
_TEST_NAME = re.compile(r"(?:Tests?|IT|Spec)\.(?:java|kt|kts)$")
_MAIN = re.compile(r"(?:^|/)src/main/")


def _is_test(rel: str) -> bool:
    if _TEST_DIR.search(rel):
        return True
    return not _MAIN.search(rel) and bool(_TEST_NAME.search(rel))


def jvm_files(files: list[str]) -> list[str]:
    """Java/Kotlin product sources of a scope (test source sets skipped)."""
    return [f for f in files if _ts.language_for(f) in JVM_LANGS and not _is_test(f)]


def flatten(node: Node | None) -> list[Node]:
    """Children of a body, with the members of an ERROR wrapper spliced in."""
    out: list[Node] = []
    for child in node.children if node is not None else []:
        if child.type == "ERROR":
            out += flatten(child)
        else:
            out.append(child)
    return out


@dataclass
class Ann:
    name: str  # last segment (`org.x.GetMapping` -> `GetMapping`)
    line: int
    args: list[tuple[str | None, Node]]  # (keyword or None, value)

    def arg(self, *keys: str) -> Node | None:
        """The value given for the first of `keys`; with `""` among them,
        the positional (unnamed) argument too."""
        for key, value in self.args:
            if (key or "") in keys:
                return value
        return None


@dataclass
class Param:
    type: str
    anns: list[Ann]


def _last(name: str) -> str:
    return name.rsplit(".", 1)[-1]


def _kotlin_annotations(node: Node) -> list[Ann]:
    out: list[Ann] = []
    for part in node.named_children:
        head = part
        if part.type == "constructor_invocation":
            head = next((c for c in part.named_children if c.type == "user_type"), part)
        elif part.type != "user_type":
            continue
        args: list[tuple[str | None, Node]] = []
        for group in part.named_children if part is not head else []:
            if group.type != "value_arguments":
                continue
            for arg in group.named_children:
                if arg.type != "value_argument":
                    continue
                kids = arg.named_children
                named = any(c.type == "=" for c in arg.children)
                if named and len(kids) >= 2:
                    args.append((_text(kids[0]), kids[-1]))
                elif kids:
                    args.append((None, kids[-1]))
        out.append(Ann(_last(_text(head)), _ts.line_of(node), args))
    return out


def _java_annotation(node: Node) -> Ann:
    args: list[tuple[str | None, Node]] = []
    listing = node.child_by_field_name("arguments")
    for arg in listing.named_children if listing is not None else []:
        if arg.type == "element_value_pair":
            key, value = (
                arg.child_by_field_name("key"),
                arg.child_by_field_name("value"),
            )
            if key is not None and value is not None:
                args.append((_text(key), value))
        elif arg.type not in ("comment", "line_comment", "block_comment"):
            args.append((None, arg))
    name = _last(_text(node.child_by_field_name("name")))
    return Ann(name, _ts.line_of(node), args)


def _from_modifiers(mods: Node) -> list[Ann]:
    out: list[Ann] = []
    for child in mods.children:
        # both grammars call it `annotation`; only Java's has a `name` field
        if child.type == "marker_annotation" or (
            child.type == "annotation" and child.child_by_field_name("name")
        ):
            out.append(_java_annotation(child))
        elif child.type == "annotation":
            out.extend(_kotlin_annotations(child))
    return out


def annotations_of(decl: Node) -> list[Ann]:
    """Annotations in the `modifiers` of a class, method, field or
    parameter declaration."""
    return [
        a for c in decl.children if c.type == "modifiers" for a in _from_modifiers(c)
    ]


def class_name(cls: Node) -> str:
    named = cls.child_by_field_name("name")
    if named is not None:
        return _text(named)
    return _text(next((c for c in cls.children if c.type == "type_identifier"), None))


def classes(root: Node) -> Iterator[Node]:
    """Every class-like declaration, nested ones included, in source order."""
    for node in _walk(root):
        if node.type in CLASS_TYPES:
            yield node


def is_annotation_type(decl: Node) -> bool:
    """`@interface X` (Java) or `annotation class X` (Kotlin)."""
    if decl.type == "annotation_type_declaration":
        return True
    return any(
        _text(m) == "annotation"
        for mods in decl.children
        if mods.type == "modifiers"
        for m in mods.named_children
        if m.type == "class_modifier"
    )


def _body(cls: Node) -> Node | None:
    body = cls.child_by_field_name("body")
    if body is not None:
        return body
    return next((c for c in cls.children if c.type == "class_body"), None)


def methods(cls: Node) -> list[Node]:
    return [
        m
        for m in flatten(_body(cls))
        if m.type in ("method_declaration", "function_declaration")
    ]


def name_line(decl: Node) -> int:
    """Line of a class or method name (its annotations may start the node
    on an earlier line)."""
    named = decl.child_by_field_name("name") or next(
        (
            c
            for c in decl.children
            if c.type in ("type_identifier", "simple_identifier")
        ),
        decl,
    )
    return _ts.line_of(named)


def is_interface(decl: Node) -> bool:
    return decl.type == "interface_declaration" or any(
        c.type == "interface" for c in decl.children
    )


def header_text(decl: Node) -> str:
    """The declaration up to its body: name, type parameters, supertypes."""
    body = _body(decl)
    end = body.start_byte if body is not None else decl.end_byte
    return (decl.text or b"")[: end - decl.start_byte].decode("utf-8", "replace")


def is_override(method: Node) -> bool:
    """`@Override` (Java) or the `override` modifier (Kotlin)."""
    return any(a.name == "Override" for a in annotations_of(method)) or any(
        _text(c) == "override"
        for mods in method.children
        if mods.type == "modifiers"
        for c in mods.children
    )


def params(method: Node) -> list[Param]:
    out: list[Param] = []
    listing = method.child_by_field_name("parameters") or next(
        (c for c in method.children if c.type == "function_value_parameters"), None
    )
    if listing is None:
        return out
    pending: list[Ann] = []
    for child in listing.children:
        if child.type == "parameter_modifiers":
            pending += _from_modifiers(child)
        elif child.type == "formal_parameter" or child.type == "spread_parameter":
            typ = child.child_by_field_name("type") or next(
                (c for c in child.named_children if c.type.endswith("type")), None
            )
            out.append(Param(_text(typ), annotations_of(child)))
        elif child.type == "parameter":
            kids = child.named_children
            typ = next((k for k in kids[1:] if k.type != "comment"), None)
            out.append(Param(_text(typ), pending))
            pending = []
    return out


def elements(node: Node) -> list[Node] | None:
    """Items of an array value (`{a, b}`, `[a, b]`, `arrayOf(a, b)`); a
    single value is its own one item. None when the form is not readable."""
    if node.type in _ARRAY_TYPES:
        return [c for c in node.named_children if "comment" not in c.type]
    if node.type == "call_expression":
        callee = node.named_children[0] if node.named_children else None
        if _text(callee) not in _ARRAY_CALLS:
            return None
        return [
            a.named_children[-1]
            for suffix in node.named_children[1:]
            for group in suffix.named_children
            if group.type == "value_arguments"
            for a in group.named_children
            if a.type == "value_argument" and a.named_children
        ]
    return [node]


def strings(node: Node | None) -> list[str] | None:
    """Plain string literals of an annotation value (one or an array); None
    when any item is computed (a constant, a concatenation, a template)."""
    items = elements(node) if node is not None else None
    if items is None:
        return None
    out: list[str] = []
    for item in items:
        value = _ts.string_literal(item)
        # `${...}` is a property placeholder resolved at runtime
        if value is None or "${" in value:
            return None
        out.append(re.sub(r'\\(["\\])', r"\1", value))
    return out


def enum_names(node: Node | None) -> list[str] | None:
    """Last segment of each enum-constant reference (`RequestMethod.GET`,
    `GET`); None when an item is not a plain reference."""
    items = elements(node) if node is not None else None
    if items is None:
        return None
    names = [re.fullmatch(r"(?:\w+\.)*(\w+)", _text(i)) for i in items]
    if any(n is None for n in names):
        return None
    return [n.group(1) for n in names if n]
