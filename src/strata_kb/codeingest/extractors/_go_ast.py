"""Go source index shared by the Gin route adapter (`_routes_gin`).

`Index` parses every non-test `.go` file of a scope once and collects, per
package (= directory), the function and method declarations, the type
declarations (struct fields, embedded types) and the package-level `var` /
`const` declarations, so a definition in any file is visible from any other
file of its package regardless of file order. It also resolves import paths
to in-repo directories (through the `go.mod` module path) and classifies a
type node into a `Value` the interpreter binds to names:

- `Router(prefix)`: a `gin.Engine` (prefix `""`) or a group; `prefix` is None
  when it is not a literal (a `gin.RouterGroup` parameter, a computed group).
- `Str(text)`: a constant string, `Pkg(path)`: an imported package,
  `Other(path)`: a value of a non-gin package (HTTP client, `*gin.Context`,
  another router), `Typed(dir, name)`: an in-repo type, `UNKNOWN`: bound but
  not resolvable.

Every walk here is iterative: a hostile file cannot raise `RecursionError`
from this layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors import _ts
from strata_kb.codeingest.extractors._routes_jsutil import _error_line, _read, _text
from strata_kb.codeingest.extractors._scopes import Scope

if TYPE_CHECKING:
    from tree_sitter import Node

__all__ = [
    "GIN",
    "UNKNOWN",
    "Func",
    "GoFile",
    "Index",
    "Other",
    "Param",
    "Pkg",
    "Router",
    "Str",
    "Typed",
    "dotted",
    "params",
    "group_like",
]

GIN = "github.com/gin-gonic/gin"
# Routers other than gin: a call on one inside a gin scope is a site.
_ROUTER_PKGS = (
    "net/http",
    "github.com/go-chi/chi",
    "github.com/gorilla/mux",
    "github.com/gorilla/pat",
    "github.com/labstack/echo",
    "github.com/gofiber/fiber",
    "github.com/julienschmidt/httprouter",
    "github.com/dimfeld/httptreemux",
    "github.com/beego/beego",
    "github.com/astaxie/beego",
    "github.com/kataras/iris",
    "github.com/emicklei/go-restful",
    "github.com/go-martini/martini",
    "github.com/zeromicro/go-zero",
    "github.com/uptrace/bunrouter",
    "github.com/revel/revel",
)
_MODULE = re.compile(r"^\s*module\s+(\S+)", re.MULTILINE)
_VERSION = re.compile(r"^v\d+$")
_ENGINE = frozenset({"Engine"})
_GROUPS = frozenset({"RouterGroup", "IRouter", "IRoutes"})


@dataclass(frozen=True)
class Router:
    prefix: str | None  # "" for the engine; None: not a literal


@dataclass(frozen=True)
class Str:
    text: str


@dataclass(frozen=True)
class Pkg:
    path: str


@dataclass(frozen=True)
class Other:
    path: str


@dataclass(frozen=True)
class Typed:
    dir: str
    name: str


@dataclass(frozen=True)
class Unknown:
    pass


UNKNOWN = Unknown()
Value = Router | Str | Pkg | Other | Typed | Unknown


@dataclass
class GoFile:
    rel: str
    dir: str
    root: Node
    pkg: str
    imports: dict[str, str] = field(default_factory=dict)  # alias -> import path
    gin: bool = False  # imports gin
    other_router: bool = False  # imports another router package


@dataclass
class Param:
    name: str | None
    type: Node | None
    variadic: bool = False


@dataclass
class Func:
    name: str
    file: GoFile
    node: Node
    params: list[Param]
    result: Node | None
    recv_name: str | None = None  # receiver variable
    recv_type: str | None = None  # receiver type name, without `*`

    @property
    def line(self) -> int:
        return _ts.line_of(self.node)


@dataclass
class TypeInfo:
    kind: str  # struct | interface | other
    file: GoFile
    fields: dict[str, Node] = field(default_factory=dict)
    embeds: list[Node] = field(default_factory=list)


@dataclass
class PkgInfo:
    dir: str
    name: str = ""
    files: list[GoFile] = field(default_factory=list)
    funcs: dict[str, list[Func]] = field(default_factory=dict)
    methods: dict[str, list[Func]] = field(default_factory=dict)
    types: dict[str, TypeInfo] = field(default_factory=dict)
    decls: list[tuple[GoFile, Node]] = field(default_factory=list)  # var / const


def dotted(node: Node | None) -> str | None:
    """`a.b.c` for a chain of plain selectors, else None."""
    parts: list[str] = []
    while node is not None:
        if node.type in ("identifier", "field_identifier", "package_identifier"):
            parts.append(_text(node))
            return ".".join(reversed(parts))
        if node.type != "selector_expression":
            return None
        parts.append(_text(node.child_by_field_name("field")))
        node = node.child_by_field_name("operand")
    return None


def group_like(value: Value | None) -> bool:
    return isinstance(value, Router) and value.prefix is None


def _type_ref(node: Node | None) -> tuple[str | None, str] | None:
    """(package alias, type name) of a named type, looking through `*`,
    parentheses and generic instantiation; None for anything else."""
    while node is not None:
        if node.type in ("pointer_type", "parenthesized_type"):
            node = node.named_children[0] if node.named_children else None
        elif node.type == "generic_type":
            node = node.child_by_field_name("type")
        elif node.type == "qualified_type":
            alias = _text(node.child_by_field_name("package"))
            return alias, _text(node.child_by_field_name("name"))
        elif node.type == "type_identifier":
            return None, _text(node)
        else:
            return None
    return None


def params(plist: Node | None) -> list[Param]:
    out: list[Param] = []
    for child in plist.named_children if plist is not None else []:
        if child.type not in (
            "parameter_declaration",
            "variadic_parameter_declaration",
        ):
            continue
        type_node = child.child_by_field_name("type")
        variadic = child.type == "variadic_parameter_declaration"
        names = [_text(n) for n in child.children_by_field_name("name")]
        out += [Param(n, type_node, variadic) for n in names or [None]]
    return out


def _alias_of(path: str) -> str:
    parts = path.split("/")
    seg = parts[-1]
    if _VERSION.match(seg) and len(parts) > 1:
        seg = parts[-2]
    seg = re.sub(r"\.v\d+$", "", seg)
    seg = seg.removeprefix("go-").removesuffix("-go").removesuffix(".go")
    return seg.replace("-", "_")


class Index:
    def __init__(self, root: Path, scope: Scope, files: list[str]) -> None:
        self.scope = scope
        self.module = ""
        self.sites: list[str] = []
        self.pkgs: dict[str, PkgInfo] = {}
        manifest = root / scope.path / "go.mod"
        try:
            found = _MODULE.search(
                manifest.read_text(encoding="utf-8", errors="replace")
            )
        except OSError:
            found = None
        if found:
            self.module = found.group(1).strip('"`')
        for rel in files:
            self._load(root, rel)
        for pkg in self.pkgs.values():
            for gofile in pkg.files:
                self._imports(gofile)

    # --- loading ------------------------------------------------------------

    def _load(self, root: Path, rel: str) -> None:
        data = _read(root, rel)
        if data is None:
            self.sites.append(f"{rel}:1")
            return
        tree = _ts.parse("go", data)
        line = _error_line(tree)
        if line is not None:
            self.sites.append(f"{rel}:{line}")
        directory = rel.rpartition("/")[0] or "."
        clause = next(
            (c for c in tree.root_node.named_children if c.type == "package_clause"),
            None,
        )
        name = (
            _text(clause.named_children[0]) if clause and clause.named_children else ""
        )
        gofile = GoFile(rel, directory, tree.root_node, name)
        pkg = self.pkgs.setdefault(directory, PkgInfo(directory))
        pkg.name = pkg.name or name
        pkg.files.append(gofile)
        for node in tree.root_node.named_children:
            self._declare(pkg, gofile, node)

    def _declare(self, pkg: PkgInfo, gofile: GoFile, node: Node) -> None:
        if node.type in ("var_declaration", "const_declaration"):
            pkg.decls.append((gofile, node))
        elif node.type == "function_declaration":
            name = _text(node.child_by_field_name("name"))
            pkg.funcs.setdefault(name, []).append(self._func(gofile, node, name))
        elif node.type == "method_declaration":
            name = _text(node.child_by_field_name("name"))
            pkg.methods.setdefault(name, []).append(self._func(gofile, node, name))
        elif node.type == "type_declaration":
            for spec in node.named_children:
                if spec.type in ("type_spec", "type_alias"):
                    self._type(pkg, gofile, spec)

    def _func(self, gofile: GoFile, node: Node, name: str) -> Func:
        func = Func(
            name,
            gofile,
            node,
            params(node.child_by_field_name("parameters")),
            node.child_by_field_name("result"),
        )
        recv = params(node.child_by_field_name("receiver"))
        if recv:
            ref = _type_ref(recv[0].type)
            func.recv_name = recv[0].name
            func.recv_type = ref[1] if ref else None
        return func

    def _type(self, pkg: PkgInfo, gofile: GoFile, spec: Node) -> None:
        name = _text(spec.child_by_field_name("name"))
        body = spec.child_by_field_name("type")
        kind = {"struct_type": "struct", "interface_type": "interface"}.get(
            body.type if body is not None else "", "other"
        )
        info = TypeInfo(kind, gofile)
        if body is not None and kind == "struct":
            for member in (
                m for lst in body.named_children for m in lst.named_children
            ):
                if member.type != "field_declaration":
                    continue
                type_node = member.child_by_field_name("type")
                names = member.children_by_field_name("name")
                if not names and type_node is not None:
                    info.embeds.append(type_node)
                for n in names:
                    if type_node is not None:
                        info.fields[_text(n)] = type_node
        pkg.types[name] = info

    def _imports(self, gofile: GoFile) -> None:
        for decl in gofile.root.named_children:
            if decl.type != "import_declaration":
                continue
            specs = [
                s
                for c in decl.named_children
                for s in (c.named_children if c.type == "import_spec_list" else [c])
                if s.type == "import_spec"
            ]
            for spec in specs:
                path_node = spec.child_by_field_name("path")
                path = _ts.string_literal(path_node) if path_node is not None else None
                if not path:
                    continue
                name = spec.child_by_field_name("name")
                alias = _text(name) if name is not None else self._default_alias(path)
                if path == GIN:
                    gofile.gin = True
                if self.is_router_pkg(path):
                    gofile.other_router = True
                if alias not in ("_", "."):
                    gofile.imports[alias] = path

    def _default_alias(self, path: str) -> str:
        target = self.import_dir(path)
        if target is not None and self.pkgs[target].name:
            return self.pkgs[target].name
        return _alias_of(path)

    # --- resolution ---------------------------------------------------------

    @staticmethod
    def is_router_pkg(path: str) -> bool:
        return any(path == p or path.startswith(p + "/") for p in _ROUTER_PKGS)

    def import_dir(self, path: str) -> str | None:
        """The in-repo directory an import path names, via the module path."""
        if not self.module or not (
            path == self.module or path.startswith(self.module + "/")
        ):
            return None
        sub = path[len(self.module) :].strip("/")
        base = self.scope.path
        target = sub if base == "." else f"{base}/{sub}".rstrip("/")
        target = target or "."
        return target if target in self.pkgs else None

    def classify(self, gofile: GoFile, type_node: Node | None) -> Value | None:
        ref = _type_ref(type_node)
        if ref is None:
            return None
        alias, name = ref
        if alias is None:
            pkg = self.pkgs.get(gofile.dir)
            return Typed(gofile.dir, name) if pkg and name in pkg.types else None
        path = gofile.imports.get(alias)
        if path is None:
            return None
        if path == GIN:
            if name in _ENGINE:
                return Router("")
            return Router(None) if name in _GROUPS else Other(GIN)
        target = self.import_dir(path)
        if target is not None and name in self.pkgs[target].types:
            return Typed(target, name)
        return Other(path)

    def func(self, directory: str, name: str) -> Func | None:
        found = (
            self.pkgs[directory].funcs.get(name, []) if directory in self.pkgs else []
        )
        return found[0] if len(found) == 1 else None

    def method(self, directory: str, type_name: str, name: str) -> Func | None:
        pkg = self.pkgs.get(directory)
        found = [
            f
            for f in (pkg.methods.get(name, []) if pkg else [])
            if f.recv_type == type_name
        ]
        return found[0] if len(found) == 1 else None

    def info(self, typed: Typed) -> TypeInfo | None:
        pkg = self.pkgs.get(typed.dir)
        return pkg.types.get(typed.name) if pkg else None

    def methods_and_funcs(self) -> list[Func]:
        """Every function and method, in (file, line) order."""
        out = [
            f
            for pkg in self.pkgs.values()
            for group in (pkg.funcs, pkg.methods)
            for funcs in group.values()
            for f in funcs
        ]
        return sorted(out, key=lambda f: (f.file.rel, f.line))
