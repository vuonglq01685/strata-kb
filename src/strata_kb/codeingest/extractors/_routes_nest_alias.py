"""NestJS decorator-name resolution for `_routes_js.nest`.

A verb decorator reaches a controller under another name in three ways, all
resolved here per file before the class walk:

- `import { Get as X } from '@nestjs/common'`
- `export { Get as X } [from '@nestjs/common']` in a same-repo file that the
  controller imports from (`import { X } from './lib'`), through barrels
  (`export *`, `export { X } from`), default exports and `import * as ns`
  namespaces, at most `_MAX_HOPS` files deep
- `const|let|var X = Get` (or `= common.Get`)

A name imported from a relative file whose export chain could not be followed
(missing file, hop cap, cycle) is a *suspect*: it may be a verb, so using it
as a decorator is a site. Custom decorators the repo defines itself
(`SetMetadata`, no verb inside) resolve to a plain declaration and are not
suspects.

shortcut: CommonJS `require` bindings, destructured aliases and renames made
by a barrel file that never mentions `@nestjs/common` are not followed.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors._routes_jsutil import (
    _EXTS,
    _SCRIPT_EXT_RE,
    _last_name,
    _lit,
    _parse,
    _read,
    _source_files,
    _text,
    _walk,
)

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

NEST_PKG = "@nestjs/common"
_MAX_HOPS = 5
NEST_VERBS = {
    "Get": "GET",
    "Post": "POST",
    "Put": "PUT",
    "Patch": "PATCH",
    "Delete": "DELETE",
    "Options": "OPTIONS",
    "Head": "HEAD",
    "All": "ANY",
    "Sse": "GET",
}
# real names whose aliases matter to the class walk
_TRACKED = frozenset({*NEST_VERBS, "Controller", "Version"})
_DECL_TYPES = (
    "function_declaration",
    "generator_function_declaration",
    "class_declaration",
    "abstract_class_declaration",
)


@dataclass
class Names:
    """What a file's decorator names mean. `aliases` maps a local name (or
    `ns.Name`) to its real `@nestjs/common` name, or to itself for a plain
    declaration."""

    aliases: dict[str, str] = field(default_factory=dict)
    suspects: set[str] = field(default_factory=set)
    opaque_ns: set[str] = field(default_factory=set)

    def suspect(self, callee: str) -> bool:
        ns, dot, _member = callee.partition(".")
        return callee in self.suspects or (
            bool(dot) and ns in self.opaque_ns and callee not in self.aliases
        )


@dataclass
class _Exports:
    names: dict[str, str] = field(default_factory=dict)
    opaque: bool = False


class AliasResolver:
    def __init__(self, root: Path, files: list[str], trees: dict[str, Tree]) -> None:
        self._root = root
        self._files = frozenset(_source_files(files))
        self._trees = trees  # shared with the caller; read lazily otherwise
        self._exports_cache: dict[str, _Exports] = {}

    def names(self, rel: str, tree: Tree) -> Names:
        return self._bind(rel, tree, (rel,))

    def exported_aliases(self, rel: str) -> set[str]:
        """Names `rel` exports under a different name than the one it got."""
        exports = self._exports(rel, ())
        return {k for k, v in exports.names.items() if k != v and v in _TRACKED}

    # -- file graph ----------------------------------------------------------

    def _resolve(self, rel: str, spec: str | None) -> str | None:
        if spec is None or not spec.startswith("."):
            return None
        base = posixpath.normpath(posixpath.join(posixpath.dirname(rel), spec))
        stem = _SCRIPT_EXT_RE.sub("", base)
        candidates = [base]
        candidates += [stem + ext for ext in _EXTS]
        candidates += [f"{base}/index{ext}" for ext in _EXTS]
        return next((c for c in candidates if c in self._files), None)

    def _tree(self, rel: str) -> Tree | None:
        if rel not in self._trees:
            data = _read(self._root, rel)
            if data is None:
                return None
            self._trees[rel] = _parse(rel, data)
        return self._trees[rel]

    # -- bindings of one file ------------------------------------------------

    def _bind(self, rel: str, tree: Tree, stack: tuple[str, ...]) -> Names:
        names = Names()
        for node in tree.root_node.named_children:
            if node.type == "import_statement":
                self._bind_import(rel, node, stack, names)
        self._bind_consts(tree, names)
        return names

    def _bind_import(
        self, rel: str, node: Node, stack: tuple[str, ...], names: Names
    ) -> None:
        source = _lit(node.child_by_field_name("source"))
        if source is None:
            return
        target = self._resolve(rel, source)
        if source != NEST_PKG and target is None:
            return
        exports = self._exports(target, stack) if target else None
        for part in _walk(node):
            if part.type == "import_specifier":
                name = _text(part.child_by_field_name("name"))
                local = _text(part.child_by_field_name("alias")) or name
                self._bind_name(names, local, name, exports)
            elif part.type == "namespace_import" and exports is not None:
                local = _text(part.named_children[0]) if part.named_children else ""
                for key, real in exports.names.items():
                    names.aliases[f"{local}.{key}"] = real
                if exports.opaque:
                    names.opaque_ns.add(local)
            elif (
                part.type == "identifier"
                and part.parent is not None
                and part.parent.type == "import_clause"
            ):
                self._bind_name(names, _text(part), "default", exports)

    @staticmethod
    def _bind_name(
        names: Names, local: str, name: str, exports: _Exports | None
    ) -> None:
        if exports is None:  # from '@nestjs/common'
            names.aliases[local] = name
        elif name in exports.names:
            names.aliases[local] = exports.names[name]
        elif exports.opaque:
            names.suspects.add(local)

    @staticmethod
    def _bind_consts(tree: Tree, names: Names) -> None:
        decls = [
            (_text(n.child_by_field_name("name")), n.child_by_field_name("value"))
            for n in _walk(tree.root_node)
            if n.type == "variable_declarator"
            and (ident := n.child_by_field_name("name")) is not None
            and ident.type == "identifier"
        ]
        for _ in range(_MAX_HOPS):  # `const H = G; const G = Get` settles
            changed = False
            for name, value in decls:
                real = _alias_of(value, names)
                if real is not None and names.aliases.get(name) != real:
                    names.aliases[name] = real
                    changed = True
            if not changed:
                break

    # -- exports of one file -------------------------------------------------

    def _exports(self, rel: str | None, stack: tuple[str, ...]) -> _Exports:
        if rel is None or rel in stack or len(stack) >= _MAX_HOPS:
            return _Exports(opaque=True)
        if rel in self._exports_cache:
            return self._exports_cache[rel]
        tree = self._tree(rel)
        if tree is None:
            return _Exports(opaque=True)
        inner = (*stack, rel)
        names = self._bind(rel, tree, inner)
        out = _Exports()
        for stmt in tree.root_node.named_children:
            if stmt.type == "export_statement":
                self._export(rel, stmt, names, inner, out)
        self._exports_cache[rel] = out
        return out

    def _export(
        self,
        rel: str,
        stmt: Node,
        names: Names,
        stack: tuple[str, ...],
        out: _Exports,
    ) -> None:
        source = _lit(stmt.child_by_field_name("source"))
        decl = stmt.child_by_field_name("declaration")
        clause = next((c for c in stmt.children if c.type == "export_clause"), None)
        if clause is not None:
            for spec in clause.named_children:
                name = _text(spec.child_by_field_name("name"))
                alias = _text(spec.child_by_field_name("alias")) or name
                if source is None:
                    out.names[alias] = names.aliases.get(name, name)
                elif source == NEST_PKG:
                    out.names[alias] = name
                elif source.startswith("."):
                    sub = self._exports(self._resolve(rel, source), stack)
                    if name in sub.names:
                        out.names[alias] = sub.names[name]
                    else:
                        out.opaque = out.opaque or sub.opaque or not sub.names
        elif decl is not None:
            for declared in _declared_names(decl):
                out.names[declared] = names.aliases.get(declared, declared)
        elif source is not None and any(c.type == "*" for c in stmt.children):
            if source == NEST_PKG:
                for real in _TRACKED:
                    out.names.setdefault(real, real)
            elif source.startswith("."):
                sub = self._exports(self._resolve(rel, source), stack)
                for key, real in sub.names.items():
                    out.names.setdefault(key, real)
                out.opaque = out.opaque or sub.opaque
        else:
            value = stmt.child_by_field_name("value")
            if value is not None:  # `export default X`
                out.names["default"] = _alias_of(value, names) or "default"
            for child in stmt.named_children:
                if child.type == "identifier":  # older grammars: no value field
                    out.names["default"] = names.aliases.get(_text(child), "default")


def _declared_names(decl: Node) -> list[str]:
    if decl.type in _DECL_TYPES:
        return [_text(decl.child_by_field_name("name"))]
    out = []
    for item in decl.named_children:
        name = item.child_by_field_name("name")
        if item.type == "variable_declarator" and name and name.type == "identifier":
            out.append(_text(name))
    return out


def _alias_of(value: Node | None, names: Names) -> str | None:
    """Real name the expression `value` stands for, if it is a bound name."""
    if value is None:
        return None
    if value.type == "identifier":
        text = _text(value)
        return names.aliases.get(text, text if text in _TRACKED else None)
    if value.type == "member_expression":
        qualified = _text(value)
        prop = _last_name(value)
        return names.aliases.get(qualified, prop if prop in _TRACKED else None)
    return None
