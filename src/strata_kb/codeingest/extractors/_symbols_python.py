"""Python exported-name reader for `_symbols_lang.EXPORTERS`.

A module's public surface is `__all__` when that is a literal list or tuple
of strings (also `+=`, `.extend([...])`, `.append("x")` and `[...] + [...]`),
else its module-level `def`, `class` and assignment names that do not start
with `_` (also those under `if` / `try` / `with` at the top level, not those
under `if __name__ == "__main__":`). `Enum` subclasses (`Enum`, `IntEnum`,
`StrEnum`, `Flag`, `IntFlag`, or a subclass of one declared in the same file)
are kind `enum`, and their members `Cls.MEMBER` kind `member`. Names only: an
assigned value or an enum value is never read.

Shortcuts: a name listed in `__all__` that this file does not define (a
re-export or a submodule) has its kind guessed from its spelling (`CamelCase`
class, `UPPER` const, else function); `__all__` computed any other way, and
`from x import *` without an `__all__`, are reported as unreadable lines (a
partial-coverage site) and the module-level names are listed as a best effort.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors import _py_ast as ast
from strata_kb.codeingest.extractors import _ts

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

__all__ = ["EXPORTERS", "unreadable_lines"]

_Name = tuple[str, str]

_ENUM_BASES = frozenset({"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag", "ReprEnum"})
_BLOCKS = frozenset(
    {
        "if_statement", "elif_clause", "else_clause", "try_statement", "except_clause",
        "except_group_clause", "finally_clause", "with_statement", "block",
    }
)  # fmt: skip


def _statements(root: Node) -> list[Node]:
    """Top-level statements, looking inside `if`/`try`/`with` bodies."""
    out: list[Node] = []
    stack = list(reversed(root.named_children))
    while stack:
        node = stack.pop()
        if node.type == "if_statement" and "__name__" in ast.text(
            node.child_by_field_name("condition")
        ):
            continue
        if node.type in _BLOCKS:
            stack.extend(reversed(node.named_children))
        else:
            out.append(node)
    return out


def _class_bases(cls: Node) -> list[str]:
    bases = cls.child_by_field_name("superclasses")
    names = []
    for base in bases.named_children if bases is not None else []:
        parts = ast.dotted(base)
        if parts:
            names.append(parts[-1])
    return names


def _member_names(cls: Node) -> list[str]:
    body = cls.child_by_field_name("body")
    out: list[str] = []
    for stmt in body.named_children if body is not None else []:
        if stmt.type != "assignment":
            continue
        left = stmt.child_by_field_name("left")
        if left is not None and left.type == "identifier":
            name = ast.text(left)
            if (
                not name.startswith("_")
                and stmt.child_by_field_name("right") is not None
            ):
                out.append(name)
    return out


def _guess(name: str) -> str:
    if name.isupper():
        return "const"
    if name[:1].isupper():
        return "class"
    return "function"


class _Surface:
    def __init__(self, root: Node):
        self.defined: dict[str, str] = {}  # name -> kind
        self.members: dict[str, list[str]] = {}  # enum -> member names
        self.all_names: list[str] | None = None
        self.unreadable: list[int] = []
        self._star: list[int] = []
        statements = _statements(root)
        enums = self._enums(statements)
        for stmt in statements:
            self._statement(stmt, enums)
        if self.all_names is None:
            self.unreadable += self._star

    @staticmethod
    def _enums(statements: list[Node]) -> set[str]:
        classes = {}
        for stmt in statements:
            node = (
                stmt.child_by_field_name("definition")
                if stmt.type == "decorated_definition"
                else stmt
            )
            if node is not None and node.type == "class_definition":
                classes[ast.text(node.child_by_field_name("name"))] = _class_bases(node)
        found: set[str] = set()
        changed = True
        while changed:
            changed = False
            for name, bases in classes.items():
                if name not in found and any(
                    b in _ENUM_BASES or b in found for b in bases
                ):
                    found.add(name)
                    changed = True
        return found

    def _statement(self, stmt: Node, enums: set[str]) -> None:
        node = stmt
        if stmt.type == "decorated_definition":
            node = stmt.child_by_field_name("definition") or stmt
        kind = node.type
        if kind == "function_definition":
            self.defined[ast.func_name(node)] = "function"
        elif kind == "class_definition":
            name = ast.text(node.child_by_field_name("name"))
            self.defined[name] = "enum" if name in enums else "class"
            if name in enums:
                self.members[name] = _member_names(node)
        elif kind == "type_alias_statement":
            alias = node.named_children[0] if node.named_children else None
            self.defined[ast.text(alias)] = "type"
        elif kind == "assignment":
            self._assignment(node)
        elif kind == "augmented_assignment":
            if ast.text(node.child_by_field_name("left")) == "__all__":
                self._all(node, node.child_by_field_name("right"), extend=True)
        elif kind == "call":
            self._all_call(node)
        elif kind == "import_from_statement" and any(
            c.type == "wildcard_import" for c in node.children
        ):
            self._star.append(_ts.line_of(node))

    def _assignment(self, node: Node) -> None:
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None:
            return
        if ast.text(left) == "__all__":
            if right is not None:
                self._all(node, right, extend=False)
            return
        ann = node.child_by_field_name("type")
        kind = (
            "type"
            if ann is not None and ast.text(ann).endswith("TypeAlias")
            else "const"
        )
        if left.type == "identifier" and right is not None:
            self.defined[ast.text(left)] = kind
        elif left.type != "identifier":
            for name in ast.targets(left):
                self.defined[name] = "const"

    def _all_call(self, call: Node) -> None:
        fn = ast.callee(call)
        if (
            fn is None
            or fn.type != "attribute"
            or ast.text(fn.child_by_field_name("object")) != "__all__"
        ):
            return
        method = ast.text(fn.child_by_field_name("attribute"))
        args = ast.call_args(call).pos
        if method == "append" and args and ast.lit(args[0]) is not None:
            self._add([ast.lit(args[0]) or ""])
        elif method == "extend" and args:
            self._all(call, args[0], extend=True)
        else:
            self.unreadable.append(_ts.line_of(call))

    def _literal(self, node: Node | None) -> list[str] | None:
        node = ast.unwrap(node)
        if node is None:
            return None
        if (
            node.type == "binary_operator"
            and ast.text(node.child_by_field_name("operator")) == "+"
        ):
            left = self._literal(node.child_by_field_name("left"))
            right = self._literal(node.child_by_field_name("right"))
            return None if left is None or right is None else left + right
        return ast.literal_strings(node)

    def _all(self, at: Node, value: Node | None, extend: bool) -> None:
        names = self._literal(value)
        if names is None:
            self.unreadable.append(_ts.line_of(at))
        elif extend and self.all_names is not None:
            self.all_names += names
        else:
            self.all_names = list(names)

    def _add(self, names: list[str]) -> None:
        self.all_names = [*(self.all_names or []), *names]

    def exports(self) -> list[_Name]:
        if self.all_names is not None and not self.unreadable:
            listed = list(dict.fromkeys(self.all_names))
        else:
            listed = [n for n in self.defined if not n.startswith("_")]
            if self.all_names is not None:
                listed = list(dict.fromkeys([*listed, *self.all_names]))
        out: list[_Name] = []
        for name in listed:
            kind = self.defined.get(name) or _guess(name)
            out.append((name, kind))
            out += [(f"{name}.{m}", "member") for m in self.members.get(name, [])]
        return list(dict.fromkeys(out))


def _python(tree: Tree, _source: bytes) -> list[_Name]:
    return _Surface(tree.root_node).exports()


def unreadable_lines(tree: Tree) -> tuple[int, ...]:
    """Lines whose exports this reader could not enumerate."""
    return tuple(sorted(set(_Surface(tree.root_node).unreadable)))


EXPORTERS = {ast.LANG: _python}
