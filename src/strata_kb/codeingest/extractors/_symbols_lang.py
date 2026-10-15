"""Per-language exported-name readers behind the `symbols` extractor.

`EXPORTERS` maps a `_ts` language id to `exporter(tree, source) ->
[(name, kind)]`: the names the file exports itself, nothing from the rest
of the repo. Later language tasks add one entry each. Names only -- an
enum or object member is `X.KEY`, its value is never read into the result.

Three optional companions keep the exporter signature small:

- `EXTRAS[lang](tree, source)` returns what only the repo can answer
  (`export ... from` re-exports, resolved by `symbols.py`) and the lines
  whose exports this module could not read exactly (each becomes a
  partial-coverage site).
- `HINTS[lang]` is a cheap byte pattern; a file without a match exports
  nothing and is never parsed.
- `LENIENT` names languages whose grammar is too weak for a syntax error
  to mean anything (SCSS interpolation breaks it); their errors are not
  sites.

CommonJS (`module.exports`, `exports.x =`) is read only in files with no
ESM `import`/`export` statement; in an ES module those are ordinary names.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors import (
    _symbols_csharp,
    _symbols_dart,
    _symbols_go,
    _symbols_jvm,
    _symbols_php,
    _symbols_python,
    _symbols_rust,
    _symbols_swift,
    _ts,
)
from strata_kb.codeingest.extractors._symbols_css import (
    DYNAMIC_PROP,
    PROPERTY_AT_RULE,
    clean_style,
    declarations,
)

# the CSS scanners live in `_symbols_css`; the old private names stay for tests
_clean_style, _declarations = clean_style, declarations

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

__all__ = [
    "DEFAULT_NAME",
    "EXPORTERS",
    "EXTRAS",
    "HINTS",
    "LENIENT",
    "Extras",
    "Reexport",
]

Exporter = Callable[["Tree", bytes], list[tuple[str, str]]]

# Name an anonymous `export default` carries until `symbols.py` swaps in the
# file stem (the exporter has no file name).
DEFAULT_NAME = "default"

_FUNCTION_VALUES = frozenset(
    {"arrow_function", "function_expression", "function", "generator_function"}
)
_WRAPPERS = frozenset(
    {
        "as_expression",
        "satisfies_expression",
        "parenthesized_expression",
        "non_null_expression",
        "type_assertion",
    }
)
_DECL_KIND = {
    "function_declaration": "function",
    "generator_function_declaration": "function",
    "function_signature": "function",
    "class_declaration": "class",
    "abstract_class_declaration": "class",
    "interface_declaration": "interface",
    "type_alias_declaration": "type",
    "enum_declaration": "enum",
    "internal_module": "const",
    "module": "const",
}
_VARIABLE_DECLS = frozenset({"lexical_declaration", "variable_declaration"})
_JS_LANGS = ("typescript", "tsx", "javascript")


@dataclass(frozen=True)
class Reexport:
    kind: str  # star | named | ns
    spec: str
    names: tuple[tuple[str, str], ...]  # (imported, exported); ns: ("*", name)
    line: int


@dataclass(frozen=True)
class Extras:
    reexports: tuple[Reexport, ...]
    unreadable: tuple[int, ...]  # lines whose exports are not fully known
    # name the file's `export default` was listed under (`export *` skips it)
    default: str | None = None


# (name, kind, member source) per name a declaration binds.
_Binding = tuple[str, str, "Node | None"]


# -- JS / TS -----------------------------------------------------------------


def _unwrap(node: Node | None) -> Node | None:
    while node is not None:
        if node.type in _WRAPPERS:
            named = node.named_children
            node = named[-1 if node.type == "type_assertion" else 0] if named else None
        elif (
            node.type == "call_expression"
            and _ts.node_text(node.child_by_field_name("function") or node)
            == "Object.freeze"
        ):
            args = node.child_by_field_name("arguments")
            named = args.named_children if args is not None else []
            node = named[0] if len(named) == 1 else None
            if node is None:
                return None
        else:
            return node
    return None


def _prop_name(node: Node | None) -> str | None:
    """Key of an object/enum member, or None when it is computed."""
    if node is None:
        return None
    if node.type == "string":
        return _ts.string_literal(node)
    if node.type == "computed_property_name":
        named = node.named_children
        return (
            _prop_name(named[0])
            if len(named) == 1 and named[0].type == "string"
            else None
        )
    if node.type in (
        "property_identifier",
        "identifier",
        "number",
        "private_property_identifier",
    ):
        return _ts.node_text(node)
    return None


def _members(source: Node) -> tuple[list[str], list[int]]:
    """Keys of an enum body or object literal, plus the lines of members
    whose key is not a plain name (spread, computed): the list is then
    incomplete."""
    keys: list[str] = []
    bad: list[int] = []
    if source.type == "enum_declaration":
        body = source.child_by_field_name("body")
        children = body.named_children if body is not None else []
        pairs = [
            (c.child_by_field_name("name") if c.type == "enum_assignment" else c, c)
            for c in children
            if c.type != "comment"
        ]
    else:
        pairs = []
        for child in source.named_children:
            if child.type == "comment":
                continue
            if child.type in ("pair", "method_definition"):
                key = child.child_by_field_name(
                    "key" if child.type == "pair" else "name"
                )
                pairs.append((key, child))
            elif child.type == "shorthand_property_identifier":
                pairs.append((child, child))
            else:  # spread_element, anything unknown
                pairs.append((None, child))
    for key, child in pairs:
        name = _prop_name(key)
        if name is None:
            bad.append(_ts.line_of(child))
        else:
            keys.append(name)
    return keys, bad


def _pattern_names(node: Node | None) -> list[str]:
    if node is None:
        return []
    if node.type in ("identifier", "shorthand_property_identifier_pattern"):
        return [_ts.node_text(node)]
    if node.type == "pair_pattern":
        return _pattern_names(node.child_by_field_name("value"))
    if node.type in ("assignment_pattern", "object_assignment_pattern"):
        return _pattern_names(node.child_by_field_name("left"))
    if node.type in ("object_pattern", "array_pattern", "rest_pattern"):
        return [n for c in node.named_children for n in _pattern_names(c)]
    return []


def _variable_bindings(decl: Node) -> list[_Binding]:
    is_const = any(c.type == "const" for c in decl.children)
    out: list[_Binding] = []
    for declarator in decl.named_children:
        if declarator.type != "variable_declarator":
            continue
        target = declarator.child_by_field_name("name")
        if target is not None and target.type == "identifier":
            value = _unwrap(declarator.child_by_field_name("value"))
            kind = "const"
            if value is not None and value.type in _FUNCTION_VALUES:
                kind = "function"
            elif value is not None and value.type == "class":
                kind = "class"
            source = (
                value
                if is_const and value is not None and value.type == "object"
                else None
            )
            out.append((_ts.node_text(target), kind, source))
        else:
            out += [(n, "const", None) for n in _pattern_names(target)]
    return out


def _bindings(decl: Node) -> list[_Binding] | None:
    """What a declaration binds; None for a shape this reader does not know."""
    if decl.type == "ambient_declaration":
        inner = [c for c in decl.named_children if c.type != "comment"]
        return _bindings(inner[0]) if inner else None
    if decl.type in _VARIABLE_DECLS:
        return _variable_bindings(decl)
    if decl.type == "import_alias":
        first = decl.named_children[0] if decl.named_children else None
        return [(_ts.node_text(first), "const", None)] if first is not None else None
    kind = _DECL_KIND.get(decl.type)
    name = decl.child_by_field_name("name")
    if kind is None or name is None or name.type == "string":
        return None
    return [(_ts.node_text(name).split(".")[0], kind, decl if kind == "enum" else None)]


def _locals(root: Node) -> dict[str, tuple[str, Node | None]]:
    table: dict[str, tuple[str, Node | None]] = {}
    for stmt in root.named_children:
        decl = (
            stmt.child_by_field_name("declaration")
            if stmt.type == "export_statement"
            else stmt
        )
        for name, kind, source in (_bindings(decl) or []) if decl is not None else []:
            table.setdefault(name, (kind, source))
    return table


def _imports(root: Node) -> dict[str, tuple[str, str]]:
    """local name -> (module specifier, imported name; `*` for a namespace)."""
    table: dict[str, tuple[str, str]] = {}
    for stmt in root.named_children:
        if stmt.type != "import_statement":
            continue
        spec = _ts.string_literal(stmt.child_by_field_name("source") or stmt)
        clause = next(
            (c for c in stmt.named_children if c.type == "import_clause"), None
        )
        if spec is None or clause is None:
            continue
        for part in clause.named_children:
            if part.type == "identifier":
                table[_ts.node_text(part)] = (spec, DEFAULT_NAME)
            elif part.type == "namespace_import" and part.named_children:
                table[_ts.node_text(part.named_children[-1])] = (spec, "*")
            elif part.type == "named_imports":
                for item in part.named_children:
                    name = _export_name(item.child_by_field_name("name"))
                    alias = item.child_by_field_name("alias")
                    local = _export_name(alias) if alias is not None else name
                    if name is not None and local is not None:
                        table[local] = (spec, name)
    return table


def _is_module_exports(node: Node | None, shadow: frozenset[str] = frozenset()) -> bool:
    return (
        "module" not in shadow
        and node is not None
        and node.type == "member_expression"
        and _ts.node_text(node.child_by_field_name("object") or node) == "module"
        and _ts.node_text(node.child_by_field_name("property") or node) == "exports"
    )


def _cjs_slot(
    left: Node | None, shadow: frozenset[str]
) -> tuple[str, str | None] | None:
    """("whole", None) for `module.exports =`, ("prop", name|None) for
    `exports.x =` / `module.exports.x =` (None: computed name), else None."""
    if left is None:
        return None
    if _is_module_exports(left, shadow):
        return "whole", None
    if left.type not in ("member_expression", "subscript_expression"):
        return None
    target = left.child_by_field_name("object")
    if not (
        target is not None
        and (
            (
                target.type == "identifier"
                and _ts.node_text(target) == "exports"
                and "exports" not in shadow
            )
            or _is_module_exports(target, shadow)
        )
    ):
        return None
    if left.type == "member_expression":
        return "prop", _ts.node_text(left.child_by_field_name("property") or left)
    index = left.child_by_field_name("index")
    return "prop", _ts.string_literal(index) if index is not None else None


_FUNCTION_NODES = frozenset(
    {
        "function_declaration",
        "generator_function_declaration",
        "function_expression",
        "function",
        "generator_function",
        "arrow_function",
        "method_definition",
    }
)


def _bound_names(fn: Node) -> frozenset[str]:
    """`exports` / `module` when a parameter, a `var` anywhere in the body
    (hoisted) or a top-level `let`/`const` of `fn` rebinds them."""
    params = fn.child_by_field_name("parameters") or fn.child_by_field_name("parameter")
    bound: list[str] = []
    if params is not None and params.type == "identifier":
        bound.append(_ts.node_text(params))
    elif params is not None:
        for param in params.named_children:
            bound += _pattern_names(param.child_by_field_name("pattern") or param)
    body = fn.child_by_field_name("body")
    stack = [body] if body is not None else []
    while stack:
        node = stack.pop()
        if node.type == "variable_declaration" or (
            node.type == "lexical_declaration"
            and node.parent is not None
            and body is not None
            and node.parent.id == body.id
        ):
            for declarator in node.named_children:
                bound += _pattern_names(declarator.child_by_field_name("name"))
        if (
            body is not None and node.id == body.id
        ) or node.type not in _FUNCTION_NODES:
            stack.extend(node.children)
    return frozenset(bound) & {"exports", "module"}


def _binds_module(root: Node) -> bool:
    """True when the file declares a `module` of its own anywhere: a
    declarator, loop binding, parameter, catch parameter, function/class name
    or import. A bare `module` argument is then not CommonJS's."""
    stack = [root]
    while stack:
        node = stack.pop()
        stack.extend(node.children)
        found: list[str] = []
        if node.type == "variable_declarator":
            found = _pattern_names(node.child_by_field_name("name"))
        elif node.type == "for_in_statement":
            found = _pattern_names(node.child_by_field_name("left"))
        elif node.type == "catch_clause":
            found = _pattern_names(node.child_by_field_name("parameter"))
        elif node.type in (
            "formal_parameters",
            "required_parameter",
            "optional_parameter",
        ):
            params = node.named_children if node.type == "formal_parameters" else [node]
            found = [
                n
                for p in params
                for n in _pattern_names(p.child_by_field_name("pattern") or p)
            ]
        elif node.type == "arrow_function":
            found = _pattern_names(node.child_by_field_name("parameter"))
        elif node.type in ("import_specifier", "namespace_import", "import_clause"):
            found = [
                _ts.node_text(c) for c in node.named_children if c.type == "identifier"
            ]
        elif node.type in ("function_declaration", "class_declaration"):
            found = _pattern_names(node.child_by_field_name("name"))
        if "module" in found:
            return True
    return False


def _passes_exports(
    call: Node, shadow: frozenset[str], bare_module: bool = True
) -> bool:
    """`f(module.exports, ..)`, `f(exports, ..)` or `f(module)` can add names
    this reader cannot list; `Object.defineProperty(exports, '__esModule',
    ..)` cannot. `bare_module=False`: `module` is a binding of the file."""
    args = call.child_by_field_name("arguments")
    given = args.named_children if args is not None else []

    def is_module(a: Node) -> bool:
        bare = a.type == "identifier" and _ts.node_text(a) in ("exports", "module")
        return _is_module_exports(a, shadow) or (
            bare
            and _ts.node_text(a) not in shadow
            and (bare_module or _ts.node_text(a) != "module")
        )

    if not any(is_module(a) for a in given):
        return False
    fn = call.child_by_field_name("function")
    marker = (
        fn is not None
        and _ts.node_text(fn) == "Object.defineProperty"
        and len(given) > 1
        and _ts.string_literal(given[1]) == "__esModule"
    )
    return not marker


def _value_kind(value: Node | None) -> str:
    if value is not None and value.type in _FUNCTION_VALUES:
        return "function"
    if value is not None and value.type == "class":
        return "class"
    return "const"


class _Reader:
    def __init__(self, root: Node):
        self.locals = _locals(root)
        self.imports = _imports(root)
        self.imported: list[Reexport] = []
        self.out: list[tuple[str, str]] = []
        self.unreadable: list[int] = []
        self.default_name: str | None = None

    def emit(self, name: str, kind: str, source: Node | None) -> None:
        self.out.append((name, kind))
        if source is not None:
            keys, bad = _members(source)
            self.out += [(f"{name}.{k}", "member") for k in keys]
            self.unreadable += bad

    def local(self, local: str, exported: str, fallback: str) -> None:
        kind, source = self.locals.get(local, (fallback, None))
        self.emit(exported, kind, source)

    def import_reexport(self, local: str, exported: str, at: Node) -> bool:
        """Record `exported` as a re-export when `local` is an import (not
        shadowed by a declaration); the repo resolves what it is."""
        if local in self.locals or local not in self.imports:
            return False
        spec, imported = self.imports[local]
        kind = "ns" if imported == "*" else "named"
        pair = ("*" if kind == "ns" else imported, exported)
        self.imported.append(Reexport(kind, spec, (pair,), _ts.line_of(at)))
        return True

    def default(self, stmt: Node) -> None:
        node = stmt.child_by_field_name("declaration")
        if node is not None:
            name = node.child_by_field_name("name")
            kind = _DECL_KIND.get(node.type, "const")
            self.default_name = (
                _ts.node_text(name) if name is not None else DEFAULT_NAME
            )
            self.emit(self.default_name, kind, None)
            return
        value = _unwrap(stmt.child_by_field_name("value"))
        if value is not None and value.type == "identifier":
            name = _ts.node_text(value)
            if not self.import_reexport(name, DEFAULT_NAME, value):
                self.default_name = name
                self.local(name, name, "const")
        else:
            self.default_name = DEFAULT_NAME
            kind = "const"
            if value is not None and value.type in _FUNCTION_VALUES:
                kind = "function"
            elif value is not None and value.type == "class":
                kind = "class"
            self.emit(DEFAULT_NAME, kind, None)

    def clause(self, clause: Node, type_only: bool) -> None:
        for spec_node in clause.named_children:
            if spec_node.type != "export_specifier":
                continue
            name = spec_node.child_by_field_name("name")
            alias = spec_node.child_by_field_name("alias")
            local = _export_name(name)
            exported = _export_name(alias) if alias is not None else local
            if local is None or exported is None:
                self.unreadable.append(_ts.line_of(spec_node))
                continue
            if self.import_reexport(local, exported, spec_node):
                continue
            if (
                exported == DEFAULT_NAME
            ):  # named after the local, like `export default Q`
                exported = self.default_name = local
            typed = type_only or any(c.type == "type" for c in spec_node.children)
            self.local(local, exported, "type" if typed else "const")

    def cjs(self, root: Node) -> None:
        bare_module = not _binds_module(root)
        stack = [(root, frozenset[str]())]
        while stack:
            node, shadow = stack.pop()
            if node.type in _FUNCTION_NODES:
                shadow = shadow | _bound_names(node)
            stack.extend((c, shadow) for c in reversed(node.children))
            if node.type == "call_expression":
                if _passes_exports(node, shadow, bare_module):
                    self.unreadable.append(_ts.line_of(node))
                continue
            if node.type != "assignment_expression":
                continue
            slot = _cjs_slot(node.child_by_field_name("left"), shadow)
            if slot is None:
                continue
            value = _unwrap(node.child_by_field_name("right"))
            if slot[0] == "prop":
                if slot[1] is None:
                    self.unreadable.append(_ts.line_of(node))
                elif value is not None and value.type == "identifier":
                    self.local(_ts.node_text(value), slot[1], "const")
                else:
                    object_ = (
                        value if value is not None and value.type == "object" else None
                    )
                    self.emit(slot[1], _value_kind(value), object_)
            else:
                self.module_exports(node, value)

    def module_exports(self, node: Node, value: Node | None) -> None:
        if value is not None and value.type == "identifier":
            name = _ts.node_text(value)
            self.local(name, name, "const")
        elif value is not None and value.type == "object":
            for child in value.named_children:
                self.cjs_member(child)
        elif (
            value is not None
            and value.type in ("function_expression", "class", "generator_function")
            and value.child_by_field_name("name") is not None
        ):
            self.emit(
                _ts.node_text(value.child_by_field_name("name") or value),
                _value_kind(value),
                None,
            )
        else:  # require(..), a call, an anonymous function/class, a chain
            self.unreadable.append(_ts.line_of(node))

    def cjs_member(self, child: Node) -> None:
        if child.type == "comment":
            return
        if child.type == "shorthand_property_identifier":
            name = _ts.node_text(child)
            self.emit(name, self.locals.get(name, ("const", None))[0], None)
        elif child.type in ("pair", "method_definition"):
            is_pair = child.type == "pair"
            name = _prop_name(child.child_by_field_name("key" if is_pair else "name"))
            value = _unwrap(child.child_by_field_name("value")) if is_pair else None
            if name is None:
                self.unreadable.append(_ts.line_of(child))
            elif not is_pair:
                self.emit(name, "function", None)
            elif value is not None and value.type == "identifier":
                self.emit(
                    name,
                    self.locals.get(_ts.node_text(value), ("const", None))[0],
                    None,
                )
            else:
                self.emit(name, _value_kind(value), None)
        else:  # spread_element, anything unknown
            self.unreadable.append(_ts.line_of(child))

    def statement(self, stmt: Node) -> None:
        kinds = {c.type for c in stmt.children}
        if stmt.child_by_field_name("source") is not None:
            return  # re-export: resolved in symbols.py
        if "default" in kinds or "=" in kinds:
            if "=" in kinds:  # `export = x`
                ident = next(
                    (c for c in stmt.named_children if c.type == "identifier"), None
                )
                if ident is not None:
                    self.local(_ts.node_text(ident), _ts.node_text(ident), "const")
                else:
                    self.unreadable.append(_ts.line_of(stmt))
            else:
                self.default(stmt)
            return
        clause = next(
            (c for c in stmt.named_children if c.type == "export_clause"), None
        )
        if clause is not None:
            self.clause(clause, "type" in kinds)
            return
        decl = stmt.child_by_field_name("declaration")
        if decl is not None:
            bound = _bindings(decl)
            if bound is None:
                self.unreadable.append(_ts.line_of(stmt))
            for name, kind, source in bound or []:
                self.emit(name, kind, source)
            return
        if "namespace" not in kinds:  # `export as namespace X` exports nothing
            self.unreadable.append(_ts.line_of(stmt))


def _export_name(node: Node | None) -> str | None:
    if node is None:
        return None
    return _ts.string_literal(node) if node.type == "string" else _ts.node_text(node)


def _js_read(tree: Tree, source: bytes) -> _Reader:
    reader = _Reader(tree.root_node)
    for stmt in tree.root_node.named_children:
        if stmt.type == "export_statement":
            reader.statement(stmt)
    # CommonJS forms only mean something in a file with no ESM syntax: in an
    # ES module `module` / `exports` are ordinary names.
    esm = any(
        c.type in ("import_statement", "export_statement")
        for c in tree.root_node.named_children
    )
    if not esm and (b"exports" in source or b"module" in source):
        reader.cjs(tree.root_node)
    return reader


def _js_exports(tree: Tree, source: bytes) -> list[tuple[str, str]]:
    return _js_read(tree, source).out


def _js_extras(tree: Tree, source: bytes) -> Extras:
    reader = _js_read(tree, source)
    reexports: list[Reexport] = list(reader.imported)
    unreadable = list(reader.unreadable)
    for stmt in tree.root_node.named_children:
        from_node = (
            stmt.child_by_field_name("source")
            if stmt.type == "export_statement"
            else None
        )
        if from_node is None:
            continue
        spec = _ts.string_literal(from_node)
        line = _ts.line_of(stmt)
        if spec is None:
            unreadable.append(line)
            continue
        ns = next(
            (c for c in stmt.named_children if c.type == "namespace_export"), None
        )
        clause = next(
            (c for c in stmt.named_children if c.type == "export_clause"), None
        )
        if ns is not None:
            names = [_ts.node_text(c) for c in ns.named_children]
            reexports.append(
                Reexport("ns", spec, (("*", names[0]),) if names else (), line)
            )
        elif clause is not None:
            pairs = []
            for item in clause.named_children:
                if item.type != "export_specifier":
                    continue
                name = _export_name(item.child_by_field_name("name"))
                alias = item.child_by_field_name("alias")
                exported = _export_name(alias) if alias is not None else name
                if name is None or exported is None:
                    unreadable.append(_ts.line_of(item))
                else:
                    pairs.append((name, exported))
            reexports.append(Reexport("named", spec, tuple(pairs), line))
        else:
            reexports.append(Reexport("star", spec, (), line))
    return Extras(tuple(reexports), tuple(sorted(set(unreadable))), reader.default_name)


# -- CSS / SCSS --------------------------------------------------------------


def _css_reader(scss: bool) -> Exporter:
    def exports(_tree: Tree, source: bytes) -> list[tuple[str, str]]:
        # shortcut: regex, not the tree -- the SCSS grammar loses every
        # declaration after `--x: #{$v}`.
        text = clean_style(source, scss)
        names = set(declarations(text))
        names |= {m.group(1) for m in PROPERTY_AT_RULE.finditer(text)}
        return sorted((n.decode("utf-8", "replace"), "css-var") for n in names)

    return exports


def _css_extras(scss: bool) -> Callable[[Tree, bytes], Extras]:
    def extras(_tree: Tree, source: bytes) -> Extras:
        # a custom property named by interpolation (`--#{$k}: v`) has no static name
        text = clean_style(source, scss)
        lines = {
            text.count(b"\n", 0, m.start()) + 1 for m in DYNAMIC_PROP.finditer(text)
        }
        return Extras((), tuple(sorted(lines)))

    return extras


EXPORTERS: dict[str, Exporter] = {
    **dict.fromkeys(_JS_LANGS, _js_exports),
    "css": _css_reader(False),
    "scss": _css_reader(True),
    **_symbols_jvm.EXPORTERS,
    **_symbols_csharp.EXPORTERS,
    **_symbols_dart.EXPORTERS,
    **_symbols_go.EXPORTERS,
    **_symbols_php.EXPORTERS,
    **_symbols_python.EXPORTERS,
    **_symbols_rust.EXPORTERS,
    **_symbols_swift.EXPORTERS,
}
EXTRAS: dict[str, Callable[[Tree, bytes], Extras]] = {
    **dict.fromkeys(_JS_LANGS, _js_extras),
    "css": _css_extras(False),
    "scss": _css_extras(True),
    "python": lambda tree, _src: Extras((), _symbols_python.unreadable_lines(tree)),
    "rust": lambda tree, _src: Extras((), _symbols_rust.unreadable_lines(tree)),
}
HINTS: dict[str, re.Pattern[bytes]] = {
    **dict.fromkeys(_JS_LANGS, re.compile(rb"\b(?:exports?|module)\b")),
    "css": re.compile(rb"--"),
    "scss": re.compile(rb"--"),
    "java": re.compile(rb"\bpublic\b"),  # nothing else is exported
    "csharp": re.compile(rb"\bpublic\b"),
    **_symbols_swift.HINTS,
    "php": re.compile(
        rb"\b(?:class|interface|trait|enum)\b", re.IGNORECASE
    ),  # nothing else is exported
}
LENIENT: frozenset[str] = frozenset({"css", "scss"})
