"""Python tree-sitter layer shared by the Python route adapters
(`_routes_python.py`, `_routes_django.py`) and the request-type reader
(`_py_fields.py`): file classification, call-argument access, per-scope name
bindings and a small project model that follows imports across the repo.

A `Project` answers "what does this name mean here?" -- a holder object, a
module, a class, a function, or something outside the repo. It never executes
code: a name bound twice, a parameter, a loop variable or an import it cannot
place is `unknown`, and callers turn that into a coverage site.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors import _ts
from strata_kb.codeingest.extractors._routes_jsutil import _error_line, _read, _walk

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

LANG = "python"

# pytest / unittest conventions only: a file or directory *named* like a test.
# `contest.py`, `latest.py`, `testing/` and `app/test.py` are product code.
_TEST_FILE = re.compile(r"(?:^|/)(?:test_[^/]*|[^/]*_test|conftest)\.py$")
_TEST_DIR = re.compile(r"(?:^|/)tests?/")
_MAX_DEPTH = 12  # import chains followed (re-export of a re-export of ...)
_FUNC = "function_definition"
_ISOLATED = frozenset(
    {
        "function_definition",
        "class_definition",
        "lambda",
        "list_comprehension",
        "set_comprehension",
        "dictionary_comprehension",
        "generator_expression",
    }
)


def is_test(rel: str) -> bool:
    return bool(_TEST_FILE.search(rel) or _TEST_DIR.search(rel))


def product_files(files: list[str]) -> list[str]:
    """`.py` files that are not test code."""
    return [f for f in files if f.endswith(".py") and not is_test(f)]


# -- node helpers -----------------------------------------------------------


def text(node: Node | None) -> str:
    return " ".join(_ts.node_text(node).split()) if node is not None else ""


def lit(node: Node | None) -> str | None:
    """Plain string literal content, else None (f-string fields, implicit
    concatenation, identifiers)."""
    return _ts.string_literal(node) if node is not None else None


def unwrap(node: Node | None) -> Node | None:
    """Drop parentheses and the `type` wrapper of an annotation."""
    while node is not None and node.type in ("parenthesized_expression", "type"):
        inner = [c for c in node.named_children if c.type != "comment"]
        if len(inner) != 1:
            return node
        node = inner[0]
    return node


@dataclass
class Args:
    pos: list[Node] = field(default_factory=list)
    kw: dict[str, Node] = field(default_factory=dict)
    splat: bool = False  # `*a` / `**k`: arguments this reader cannot see


def call_args(call: Node | None) -> Args:
    out = Args()
    args = call.child_by_field_name("arguments") if call is not None else None
    if args is None or args.type != "argument_list":
        return out
    for child in args.named_children:
        if child.type == "comment":
            continue
        if child.type == "keyword_argument":
            name = text(child.child_by_field_name("name"))
            value = child.child_by_field_name("value")
            if value is not None:
                out.kw[name] = value
        elif child.type in ("list_splat", "dictionary_splat"):
            out.splat = True
        else:
            out.pos.append(child)
    return out


def dotted(node: Node | None) -> list[str] | None:
    """`a.b.c` -> ["a", "b", "c"]; None for any other expression."""
    parts: list[str] = []
    while node is not None and node.type == "attribute":
        parts.append(text(node.child_by_field_name("attribute")))
        node = node.child_by_field_name("object")
    if node is None or node.type != "identifier":
        return None
    parts.append(text(node))
    return parts[::-1]


def callee(call: Node) -> Node | None:
    return call.child_by_field_name("function")


def literal_strings(node: Node | None) -> list[str] | None:
    """Items of a list/tuple/set of plain strings, else None."""
    node = unwrap(node)
    if node is None or node.type not in ("list", "tuple", "set"):
        return None
    out: list[str] = []
    for item in node.named_children:
        if item.type == "comment":
            continue
        value = lit(item)
        if value is None:
            return None
        out.append(value)
    return out


def enclosing_functions(node: Node) -> list[Node]:
    """Function definitions around `node`, innermost first."""
    out = []
    parent = node.parent
    while parent is not None:
        if parent.type == _FUNC:
            out.append(parent)
        parent = parent.parent
    return out


def enclosing_class(node: Node) -> Node | None:
    parent = node.parent
    while parent is not None and parent.type != _FUNC:
        if parent.type == "class_definition":
            return parent
        parent = parent.parent
    return None


def decorated(call: Node) -> Node | None:
    """The function/class a decorator call decorates."""
    deco = call.parent
    if deco is None or deco.type != "decorator" or deco.parent is None:
        return None
    return deco.parent.child_by_field_name("definition")


def decorator_calls(defn: Node) -> list[tuple[Node, Node]]:
    """(decorator expression, its call or itself) of a definition."""
    wrapper = defn.parent
    if wrapper is None or wrapper.type != "decorated_definition":
        return []
    out = []
    for deco in wrapper.children:
        if deco.type == "decorator":
            expr = next((c for c in deco.named_children if c.type != "comment"), None)
            if expr is not None:
                out.append((expr, expr))
    return out


def func_name(defn: Node) -> str:
    return text(defn.child_by_field_name("name"))


# -- scopes -----------------------------------------------------------------


@dataclass(frozen=True)
class Import:
    module: str  # dotted, leading dots when relative; "" for `from . import`
    name: str | None  # None: a module import
    line: int


@dataclass(frozen=True)
class Binding:
    kind: str  # assign|import|def|class|param|other|multi|global
    node: Node | None = None  # assigned value / definition
    imp: Import | None = None
    line: int = 0


def targets(node: Node | None) -> list[str]:
    if node is None:
        return []
    if node.type == "identifier":
        return [text(node)]
    if node.type in ("pattern_list", "tuple_pattern", "list_pattern", "tuple"):
        return [n for c in node.named_children for n in targets(c)]
    if node.type in (
        "list_splat_pattern",
        "parenthesized_expression",
        "as_pattern_target",
    ):
        return [n for c in node.named_children for n in targets(c)]
    return []


def _param_names(params: Node | None) -> list[str]:
    out: list[str] = []
    for child in params.named_children if params is not None else []:
        if child.type == "identifier":
            out.append(text(child))
        elif child.type in (
            "typed_parameter",
            "default_parameter",
            "typed_default_parameter",
            "list_splat_pattern",
            "dictionary_splat_pattern",
        ):
            ident = child.child_by_field_name("name") or next(
                (c for c in child.named_children if c.type == "identifier"), None
            )
            if ident is not None:
                out.append(text(ident))
    return out


def _import_bindings(node: Node) -> tuple[list[tuple[str, Import]], list[Import]]:
    """(local name, Import) pairs and star imports of one import statement."""
    named: list[tuple[str, Import]] = []
    stars: list[Import] = []
    line = _ts.line_of(node)
    if node.type == "import_statement":
        for child in node.children_by_field_name("name"):
            if child.type == "aliased_import":
                module = text(child.child_by_field_name("name"))
                alias = text(child.child_by_field_name("alias"))
                named.append((alias, Import(module, None, line)))
            else:
                module = text(child)
                named.append(
                    (module.split(".")[0], Import(module.split(".")[0], None, line))
                )
        return named, stars
    module_node = node.child_by_field_name("module_name")
    module = text(module_node)
    if any(c.type == "wildcard_import" for c in node.children):
        return named, [Import(module, "*", line)]
    for child in node.children_by_field_name("name"):
        if child.type == "aliased_import":
            name = text(child.child_by_field_name("name"))
            alias = text(child.child_by_field_name("alias"))
        else:
            name = alias = text(child)
        named.append((alias, Import(module, name, line)))
    return named, stars


def scope_bindings(scope: Node) -> tuple[dict[str, Binding], list[Import]]:
    """Names bound directly in a module or function body (nested function,
    class and comprehension bodies are their own scopes)."""
    found: dict[str, Binding] = {}
    stars: list[Import] = []

    def bind(name: str, binding: Binding) -> None:
        found[name] = Binding("multi", line=binding.line) if name in found else binding

    if scope.type == _FUNC:
        for name in _param_names(scope.child_by_field_name("parameters")):
            bind(name, Binding("param"))
        start = [scope.child_by_field_name("body")]
    else:
        start = [scope]
    stack = [n for n in start if n is not None]
    while stack:
        node = stack.pop()
        for child in reversed(node.children):
            kind = child.type
            line = _ts.line_of(child)
            if kind in ("function_definition", "class_definition"):
                bind(
                    text(child.child_by_field_name("name")),
                    Binding("def" if kind == _FUNC else "class", child, line=line),
                )
                continue
            if kind in _ISOLATED:
                continue
            if kind in ("import_statement", "import_from_statement"):
                named, more = _import_bindings(child)
                for name, imp in named:
                    bind(name, Binding("import", imp=imp, line=line))
                stars += more
                continue
            if kind == "assignment":
                left = child.child_by_field_name("left")
                right = child.child_by_field_name("right")
                while right is not None and right.type == "assignment":
                    right = right.child_by_field_name("right")  # a = b = X
                if left is not None and left.type == "identifier":
                    if right is not None:  # `x: int` alone binds nothing
                        bind(text(left), Binding("assign", right, line=line))
                else:
                    for name in targets(left):
                        bind(name, Binding("other", line=line))
            elif kind == "for_statement":
                for name in targets(child.child_by_field_name("left")):
                    bind(name, Binding("other", line=line))
            elif kind == "as_pattern":
                for name in targets(child.child_by_field_name("alias")):
                    bind(name, Binding("other", line=line))
            elif kind == "named_expression":
                for name in targets(child.child_by_field_name("name")):
                    bind(name, Binding("other", line=line))
            elif kind == "global_statement":
                for ident in child.named_children:
                    found[text(ident)] = Binding("global", line=line)
            stack.append(child)
    return found, stars


# -- project ----------------------------------------------------------------


@dataclass(frozen=True)
class Mod:
    key: str  # repo path without `.py` / `/__init__.py`; "" for the repo root
    file: str | None  # the module's source file; None for a bare directory


@dataclass(frozen=True)
class Ref:
    """What a name or dotted expression resolves to."""

    kind: str  # assign|func|class|mod|external|attr|unknown
    file: str = ""
    node: Node | None = None
    mod: Mod | None = None
    base: Ref | None = None  # kind attr: the object the attribute belongs to
    name: str = ""  # external: imported name; attr: attribute name; assign: bound name
    module: str = ""  # external: dotted module


UNKNOWN = Ref("unknown")


class FileInfo:
    def __init__(self, rel: str, data: bytes, tree: Tree):
        self.rel = rel
        self.data = data
        self.tree = tree
        self.error_line = _error_line(tree)
        self._scopes: dict[int, tuple[dict[str, Binding], list[Import]]] = {}

    def scope(self, node: Node) -> dict[str, Binding]:
        return self.scope_full(node)[0]

    def scope_full(self, node: Node) -> tuple[dict[str, Binding], list[Import]]:
        if node.id not in self._scopes:
            self._scopes[node.id] = scope_bindings(node)
        return self._scopes[node.id]

    @property
    def module(self) -> dict[str, Binding]:
        return self.scope(self.tree.root_node)

    @property
    def stars(self) -> list[Import]:
        return self.scope_full(self.tree.root_node)[1]


class Project:
    """Parsed files of one repo (read-only, cached for one adapter run)."""

    def __init__(self, root: Path, files: list[str]):
        self.root = root
        self.files = frozenset(files)
        self._dirs: set[str] = set()
        for rel in files:
            parent = PurePosixPath(rel).parent
            while str(parent) not in ("", "."):
                self._dirs.add(parent.as_posix())
                parent = parent.parent
        self._infos: dict[str, FileInfo | None] = {}
        self._keys: dict[str, list[str]] | None = None

    # -- files
    def info(self, rel: str) -> FileInfo | None:
        if rel not in self._infos:
            data = _read(self.root, rel)
            self._infos[rel] = (
                None if data is None else FileInfo(rel, data, _ts.parse(LANG, data))
            )
        return self._infos[rel]

    # -- modules
    def _mod_at(self, key: str) -> Mod | None:
        if key + ".py" in self.files:
            return Mod(key, key + ".py")
        init = f"{key}/__init__.py" if key else "__init__.py"
        if init in self.files:
            return Mod(key, init)
        if key == "" or key in self._dirs:
            return Mod(key, None)
        return None

    def _candidates(self, dotted_name: str) -> list[str]:
        if self._keys is None:
            keys: dict[str, set[str]] = {}
            paths = {f[:-3] for f in self.files}
            paths = {p[:-9] if p.endswith("/__init__") else p for p in paths}
            for path in paths | self._dirs:
                parts = path.split("/")
                for i in range(len(parts)):
                    keys.setdefault(".".join(parts[i:]), set()).add(path)
            self._keys = {k: sorted(v) for k, v in keys.items()}
        return self._keys.get(dotted_name, [])

    def resolve_module(self, name: str, from_file: str) -> Mod | None:
        """The module a dotted name (leading dots = relative) imports from
        `from_file`, or None when it is outside the repo or ambiguous."""
        here = PurePosixPath(from_file).parent
        if name.startswith("."):
            level = len(name) - len(name.lstrip("."))
            base = here
            for _ in range(level - 1):
                base = base.parent
            parts = [p for p in name.lstrip(".").split(".") if p]
            key = "/".join([p for p in (base.as_posix(), *parts) if p != "."])
            return self._mod_at(key)
        found = self._candidates(name)
        if not found:
            return None

        def rank(path: str) -> tuple[int, int, str]:
            shared = len(
                [1 for a, b in zip(path.split("/"), here.parts, strict=False) if a == b]
            )
            return (-shared, path.count("/"), path)

        ordered = sorted(found, key=rank)
        if len(ordered) > 1 and rank(ordered[0])[:2] == rank(ordered[1])[:2]:
            return None
        return self._mod_at(ordered[0])

    def _submodule(self, mod: Mod, name: str) -> Mod | None:
        return self._mod_at(f"{mod.key}/{name}" if mod.key else name)

    # -- names
    def lookup(self, rel: str, node: Node, name: str) -> Ref:
        """Meaning of the bare `name` as written at `node`."""
        info = self.info(rel)
        if info is None:
            return UNKNOWN
        for fn in enclosing_functions(node):
            binding = info.scope(fn).get(name)
            if binding is not None and binding.kind != "global":
                return self._binding_ref(rel, name, binding, 0)
            if binding is not None:
                break
        return self.module_name(rel, name, 0) or UNKNOWN

    def module_name(self, rel: str, name: str, depth: int) -> Ref | None:
        """Meaning of `name` at the top level of `rel`; None if unbound there."""
        info = self.info(rel)
        if info is None or depth > _MAX_DEPTH:
            return None
        binding = info.module.get(name)
        if binding is not None:
            return self._binding_ref(rel, name, binding, depth)
        for star in info.stars:
            mod = self.resolve_module(star.module, rel)
            if mod is not None and mod.file is not None:
                found = self.module_name(mod.file, name, depth + 1)
                if found is not None:
                    return found
        return None

    def _binding_ref(self, rel: str, name: str, binding: Binding, depth: int) -> Ref:
        kind = binding.kind
        if kind == "assign" and binding.node is not None:
            return Ref("assign", rel, binding.node, name=name)
        if kind == "def":
            return Ref("func", rel, binding.node, name=name)
        if kind == "class":
            return Ref("class", rel, binding.node, name=name)
        if kind == "import" and binding.imp is not None:
            return self._import_ref(rel, binding.imp, depth + 1)
        return UNKNOWN

    def _import_ref(self, rel: str, imp: Import, depth: int) -> Ref:
        if depth > _MAX_DEPTH:
            return UNKNOWN
        mod = self.resolve_module(imp.module, rel)
        if imp.name is None:
            if mod is None:
                return Ref("external", module=imp.module)
            return Ref("mod", mod.file or "", mod=mod)
        if mod is None:
            return Ref("external", module=imp.module, name=imp.name)
        found = None
        if mod.file is not None and mod.file != rel:  # not the file itself
            found = self.module_name(mod.file, imp.name, depth)
            if found is not None and found.kind != "unknown":
                return found
        sub = self._submodule(mod, imp.name)  # `from pkg import submodule`
        if sub is not None:
            return Ref("mod", sub.file or "", mod=sub)
        return found or UNKNOWN

    def attr(self, base: Ref, name: str) -> Ref:
        if base.kind == "mod" and base.mod is not None:
            if base.mod.file is not None:
                found = self.module_name(base.mod.file, name, 0)
                if found is not None:
                    return found
            sub = self._submodule(base.mod, name)
            if sub is not None:
                return Ref("mod", sub.file or "", mod=sub)
            return UNKNOWN
        if base.kind == "external":
            return Ref("external", module=base.module, name=name)
        if base.kind == "unknown":
            return UNKNOWN
        return Ref("attr", base=base, name=name)

    def chain(self, rel: str, node: Node | None) -> Ref:
        """Resolve a name or dotted attribute expression."""
        node = unwrap(node)
        if node is None:
            return UNKNOWN
        if node.type == "identifier":
            return self.lookup(rel, node, text(node))
        if node.type == "attribute":
            base = self.chain(rel, node.child_by_field_name("object"))
            return self.attr(base, text(node.child_by_field_name("attribute")))
        return UNKNOWN

    def imported_name(self, rel: str, node: Node) -> str:
        """Original name of an identifier imported under an alias
        (`from flask import Flask as F` -> "Flask"), else its own text."""
        name = text(node)
        info = self.info(rel)
        if info is None:
            return name
        for fn in enclosing_functions(node):
            b = info.scope(fn).get(name)
            if b is not None:
                return b.imp.name or name if b.kind == "import" and b.imp else name
        b = info.module.get(name)
        if b is not None and b.kind == "import" and b.imp and b.imp.name:
            return b.imp.name
        return name

    def import_module_of(self, rel: str, node: Node) -> str:
        """Module an identifier was imported from ("" if it was not)."""
        info = self.info(rel)
        if info is None:
            return ""
        name = text(node)
        for fn in enclosing_functions(node):
            b = info.scope(fn).get(name)
            if b is not None:
                return b.imp.module if b.kind == "import" and b.imp else ""
        b = info.module.get(name)
        return b.imp.module if b is not None and b.kind == "import" and b.imp else ""


def all_calls(tree: Tree) -> list[Node]:
    return [n for n in _walk(tree.root_node) if n.type == "call"]
