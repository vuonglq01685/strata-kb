"""Cross-file index of one Rust package (a `Cargo.toml` scope) and the path
resolver the Actix / Axum / Rocket adapters share.

Every `.rs` file of the scope is parsed first; modules are linked the way
rustc finds them: crate roots (`src/lib.rs`, `src/main.rs`, `src/bin/*.rs`,
`src/bin/*/main.rs`, `[lib]`/`[[bin]]` paths), `mod x;` -> `x.rs` or
`x/mod.rs` next to the declaring file (a `#[path]` is followed), inline
`mod x { .. }`. A file no root reaches is its own root (best effort). Only
afterwards does anything resolve a name, so file order never matters.

`resolve(mod, segments)` follows `crate::`, `self::`, `super::`, `use`
aliases (also `as`, groups, `pub use` re-exports) and glob imports to an
item of the package: a function, module, const string or type; a path whose
first segment names nothing in the package is `Res.ext` (an external crate,
std, or a sibling workspace member -- all unproven, never "not a router").

Skipped: top-level `tests/`, `benches/`, `examples/` of the package,
`build.rs`, items under `#[cfg(test)]` / `#[test]`. A `mod x;` whose file is
missing, a syntax error, an unreadable file are `file:line` sites.
"""

from __future__ import annotations

import posixpath
import re
import tomllib
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors import _ts
from strata_kb.codeingest.extractors._routes_jsutil import _error_line, _read
from strata_kb.codeingest.extractors._rs_syntax import (
    Attr,
    attrs_before,
    is_cfg_test,
    line_of,
    segments,
    string_of,
    text,
)

if TYPE_CHECKING:
    from pathlib import Path

    from tree_sitter import Node

    from strata_kb.codeingest.extractors._scopes import Scope

__all__ = ["Fn", "Index", "Mod", "Res", "flatten_use", "scoped_mod"]

_SKIP = re.compile(r"(?:^|/)build\.rs$")
_PRODUCT_DIRS = ("tests/", "benches/", "examples/")
_ROUTER_WORD = re.compile(r"\bRouter\b")
# a macro whose body builds or registers routes
_ROUTING_BODY = re.compile(
    r"\b(?:route|nest|merge|service|mount|scope|resource|routes|Router|App|Rocket|build"
    r"|get|post|put|delete|patch)\b"
)
_MOD_RS = ("mod.rs", "lib.rs", "main.rs")
_ITEM_TYPES = frozenset({"struct_item", "enum_item", "union_item", "type_item"})
MAX_RESOLVE_DEPTH = 24


class Fn:
    """A function or method item. Identity-hashed."""

    __slots__ = (
        "attrs", "file", "has_self", "line", "mod", "name", "node", "owner", "params", "ret",
    )  # fmt: skip

    def __init__(self, mod: Mod, node: Node, attrs: list[Attr], owner: str | None):
        self.mod = mod
        self.file = mod.file
        self.node = node
        self.attrs = attrs
        self.owner = owner
        self.name = text(node.child_by_field_name("name"))
        self.line = line_of(node)
        self.ret = text(node.child_by_field_name("return_type"))
        self.params: list[tuple[str, str]] = []
        plist = node.child_by_field_name("parameters")
        self.has_self = False
        for param in plist.named_children if plist is not None else []:
            if param.type == "self_parameter":
                self.has_self = True
            if param.type != "parameter":
                continue
            pat = param.child_by_field_name("pattern")
            self.params.append(
                (
                    text(pat) if pat is not None and pat.type == "identifier" else "",
                    text(param.child_by_field_name("type")),
                )
            )

    @property
    def body(self) -> Node | None:
        return self.node.child_by_field_name("body")


class Mod:
    """A module: a file, or an inline `mod x { .. }` inside one."""

    def __init__(self, file: str, parent: Mod | None):
        self.file = file
        self.parent = parent
        self.root: Mod = parent.root if parent is not None else self
        self.uses: dict[str, tuple[str, ...]] = {}
        self.globs: list[tuple[str, ...]] = []
        self.fns: dict[str, list[Fn]] = defaultdict(list)
        self.mods: dict[str, Mod] = {}
        self.consts: dict[str, str | None] = {}
        self.types: set[str] = set()


@dataclass(frozen=True)
class Res:
    kind: str  # fn | amb | mod | const | type | ext
    fn: Fn | None = None
    mod: Mod | None = None
    value: str | None = None  # const string, None when not a plain literal
    segs: tuple[str, ...] = ()  # ext: the expanded path; type: (name,)
    alts: tuple[Fn, ...] = ()  # amb: the candidates


def flatten_use(
    node: Node,
) -> tuple[list[tuple[str, tuple[str, ...]]], list[tuple[str, ...]]]:
    """A `use` tree -> ([(alias, path)], [glob path])."""
    named: list[tuple[str, tuple[str, ...]]] = []
    globs: list[tuple[str, ...]] = []
    stack: list[tuple[tuple[str, ...], Node]] = [((), node)]
    while stack:
        prefix, cur = stack.pop()
        kind = cur.type
        if kind == "use_declaration":
            arg = cur.child_by_field_name("argument")
            if arg is not None:
                stack.append((prefix, arg))
        elif kind == "scoped_use_list":
            head = segments(cur.child_by_field_name("path")) or ()
            lst = cur.child_by_field_name("list")
            if lst is not None:
                stack.append((prefix + head, lst))
        elif kind == "use_list":
            stack.extend((prefix, c) for c in cur.named_children)
        elif kind == "use_wildcard":
            inner = next(iter(cur.named_children), None)
            globs.append(prefix + (segments(inner) or ()))
        elif kind == "use_as_clause":
            path = segments(cur.child_by_field_name("path"))
            alias = text(cur.child_by_field_name("alias"))
            if path and alias and alias != "_":
                named.append((alias, prefix + path))
        elif kind in ("identifier", "scoped_identifier", "self", "crate", "super"):
            path = segments(cur)
            if path is None:
                continue
            if path == ("self",) and prefix:
                named.append((prefix[-1], prefix))
            elif path != ("self",):
                named.append((path[-1], prefix + path))
    return named, globs


def scoped_mod(mod: Mod, use: Node) -> Mod:
    """`mod` plus the imports of a `use` inside a function body."""
    named, globs = flatten_use(use)
    inner = Mod(mod.file, mod.parent)
    inner.root = mod.root
    inner.uses = {**mod.uses, **dict(named)}
    inner.globs = [*mod.globs, *globs]
    inner.fns, inner.mods, inner.consts, inner.types = (
        mod.fns,
        mod.mods,
        mod.consts,
        mod.types,
    )
    return inner


class Index:
    def __init__(self, root: Path, scope: Scope, files: list[str]):
        self.root = root
        self.scope = scope
        self.base = "" if scope.path == "." else scope.path + "/"
        self.sites: list[str] = []
        # module-level `static` / `const` / macro items that hold a `Router`
        # (`LazyLock<Router>`, `lazy_static!`): never run, so a site
        self.router_items: list[str] = []
        # `macro_rules!` of this package -> does its body build routes; item-level calls
        self.macros: dict[str, bool] = {}
        self._macro_calls: list[tuple[str, str]] = []
        self.mods: list[Mod] = []
        self.fns: list[Fn] = []
        self.by_file: dict[str, Mod] = {}
        self.impls: dict[str, dict[str, list[Fn]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self.macro_use: set[str] = set()
        self.source: dict[str, bytes] = {}
        self._trees: dict[str, Node] = {}
        self._fileset: set[str] = set()
        self._test_files: set[str] = set()
        self._test_dirs: set[str] = set()
        self.pkg_name = ""
        self.extern_crates: set[str] = {"std", "core", "alloc"}
        self.lib_root: Mod | None = None
        self._lib_name = ""
        self._load_files(files)
        self._link()

    # -- loading ---------------------------------------------------------

    def _local(self, rel: str) -> str:
        return rel[len(self.base) :]

    def _load_files(self, files: list[str]) -> None:
        for rel in sorted(files):
            local = self._local(rel)
            if (
                not rel.endswith(".rs")
                or _SKIP.search(local)
                or local.startswith(_PRODUCT_DIRS)
            ):
                continue
            data = _read(self.root, rel)
            if data is None:
                self.sites.append(f"{rel}:1")
                continue
            tree = _ts.parse("rust", data)
            line = _error_line(tree)
            if line is not None:
                self.sites.append(f"{rel}:{line}")
            self.source[rel] = data
            self._trees[rel] = tree.root_node
            self._fileset.add(rel)

    def _cargo(self) -> dict:
        try:
            data = tomllib.loads(
                (self.root / f"{self.base}Cargo.toml").read_text(encoding="utf-8")
            )
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _dependency_names(cargo: dict) -> set[str]:
        """Crate names the code can write without a `use` (the extern
        prelude): every dependency key, `-` as `_`."""
        tables = [cargo]
        target = cargo.get("target")
        tables += (
            [t for t in target.values() if isinstance(t, dict)]
            if isinstance(target, dict)
            else []
        )
        names: set[str] = set()
        for table in tables:
            for key in ("dependencies", "dev-dependencies", "build-dependencies"):
                deps = table.get(key)
                names |= (
                    {str(k).replace("-", "_") for k in deps}
                    if isinstance(deps, dict)
                    else set()
                )
        return names

    def _roots(self) -> list[tuple[str, bool]]:
        """(file, is_lib) of the package's crate roots that exist."""
        cargo = self._cargo()
        package = cargo.get("package")
        self.pkg_name = (
            str(package.get("name", "")) if isinstance(package, dict) else ""
        )
        lib = cargo.get("lib")
        lib_path = lib.get("path") if isinstance(lib, dict) else None
        lib_name = lib.get("name") if isinstance(lib, dict) else None
        self._lib_name = str(lib_name or self.pkg_name).replace("-", "_")
        self.extern_crates = {"std", "core", "alloc", *self._dependency_names(cargo)}
        found: list[tuple[str, bool]] = [
            (
                f"{self.base}{lib_path if isinstance(lib_path, str) else 'src/lib.rs'}",
                True,
            ),
            (f"{self.base}src/main.rs", False),
        ]
        bins = cargo.get("bin")
        for entry in bins if isinstance(bins, list) else []:
            if isinstance(entry, dict) and isinstance(entry.get("path"), str):
                found.append((f"{self.base}{entry['path']}", False))
        prefix = f"{self.base}src/bin/"
        for rel in sorted(self._fileset):
            if rel.startswith(prefix):
                rest = rel[len(prefix) :]
                if "/" not in rest or (
                    rest.endswith("/main.rs") and rest.count("/") == 1
                ):
                    found.append((rel, False))
        seen: set[str] = set()
        return [
            (posixpath.normpath(f), lib)
            for f, lib in found
            if posixpath.normpath(f) in self._fileset
            and not (posixpath.normpath(f) in seen or seen.add(posixpath.normpath(f)))
        ]

    def _link(self) -> None:
        self._work: list[tuple[Mod, Node, str]] = []
        for rel, is_lib in self._roots():
            mod = self._new_mod(rel, None, True)
            if is_lib:
                self.lib_root = mod
            self._drain()
        for rel in sorted(self._fileset):
            if rel not in self.by_file and not self._in_test_code(rel):
                self._new_mod(rel, None, True)
                self._drain()

    def macro_sites(self) -> list[str]:
        """Item-level calls of this package's route-building `macro_rules!`
        (they expand to routes this adapter does not read)."""
        return [
            site
            for name, site in self._macro_calls
            if self.macros.get(name) or name == "include"  # `include!`: unseen code
        ]

    def _in_test_code(self, rel: str) -> bool:
        return rel in self._test_files or any(
            rel.startswith(d + "/") for d in self._test_dirs
        )

    def _children_dir(self, rel: str, is_root: bool) -> str:
        directory, name = posixpath.split(rel)
        if is_root or name in _MOD_RS:
            return directory
        return posixpath.join(directory, name[:-3])

    def _new_mod(self, rel: str, parent: Mod | None, is_root: bool) -> Mod:
        mod = Mod(rel, parent)
        self.by_file[rel] = mod
        self.mods.append(mod)
        self._work.append((mod, self._trees[rel], self._children_dir(rel, is_root)))
        return mod

    def _drain(self) -> None:
        while self._work:
            mod, node, base = self._work.pop()
            self._declare(mod, node, base)

    # -- declarations ----------------------------------------------------

    def _declare(self, mod: Mod, parent: Node, base: str) -> None:
        for attrs, item in attrs_before(parent):
            if item.type == "expression_statement":  # `include!(..);` at module level
                item = next(iter(item.named_children), item)
            kind = item.type
            if kind == "extern_crate_declaration" and any(
                a.name == "macro_use" for a in attrs
            ):
                self.macro_use.add(text(item.child_by_field_name("name")))
            elif is_cfg_test(attrs):
                if kind == "mod_item" and item.child_by_field_name("body") is None:
                    self._skip_test_mod(item, attrs, base)
            elif kind == "use_declaration":
                named, globs = flatten_use(item)
                for alias, path in named:
                    mod.uses.setdefault(alias, path)
                mod.globs.extend(globs)
            elif kind == "function_item":
                self._add_fn(mod, item, attrs, None)
            elif kind == "mod_item":
                self._declare_mod(mod, item, attrs, base)
            elif kind == "macro_definition":
                self.macros[text(item.child_by_field_name("name"))] = bool(
                    _ROUTING_BODY.search(text(item))
                )
            elif kind in ("const_item", "static_item", "macro_invocation"):
                if kind != "macro_invocation":
                    name = text(item.child_by_field_name("name"))
                    mutable = any(c.type == "mutable_specifier" for c in item.children)
                    value = item.child_by_field_name("value")
                    mod.consts[name] = None if mutable else string_of(value)
                if kind == "macro_invocation":
                    name = (segments(item.child_by_field_name("macro")) or ("",))[-1]
                    self._macro_calls.append((name, f"{mod.file}:{line_of(item)}"))
                if _ROUTER_WORD.search(text(item)):
                    self.router_items.append(f"{mod.file}:{line_of(item)}")
            elif kind in _ITEM_TYPES:
                mod.types.add(text(item.child_by_field_name("name")))
            elif kind in ("impl_item", "trait_item"):
                self._declare_impl(mod, item)
                if kind == "trait_item":
                    mod.types.add(text(item.child_by_field_name("name")))

    def _add_fn(self, mod: Mod, node: Node, attrs: list[Attr], owner: str | None) -> Fn:
        fn = Fn(mod, node, attrs, owner)
        self.fns.append(fn)
        if owner is None:
            mod.fns[fn.name].append(fn)
        else:
            self.impls[owner][fn.name].append(fn)
        return fn

    def _skip_test_mod(self, item: Node, attrs: list[Attr], base: str) -> None:
        """`#[cfg(test)] mod tests;`: its file (and what it declares) is test
        code, not an orphan root."""
        rel = self._mod_file(attrs, base, text(item.child_by_field_name("name")))
        if rel is not None:
            self._test_files.add(rel)
            self._test_dirs.add(self._children_dir(rel, False))

    def _declare_impl(self, mod: Mod, item: Node) -> None:
        """Methods of an `impl` block, or the default methods of a `trait`."""
        if item.type == "trait_item":
            owner = text(item.child_by_field_name("name"))
        else:
            owner = (segments(item.child_by_field_name("type")) or ("",))[-1]
        body = item.child_by_field_name("body")
        for attrs, member in attrs_before(body) if body is not None else []:
            if member.type == "function_item" and not is_cfg_test(attrs):
                self._add_fn(mod, member, attrs, owner or "?")

    def _declare_mod(self, mod: Mod, item: Node, attrs: list[Attr], base: str) -> None:
        name = text(item.child_by_field_name("name"))
        body = item.child_by_field_name("body")
        if body is not None:
            child = Mod(mod.file, mod)
            self.mods.append(child)
            mod.mods[name] = child
            self._work.append((child, body, posixpath.join(base, name)))
            return
        rel = self._mod_file(attrs, base, name)
        if rel is None:
            self.sites.append(f"{mod.file}:{line_of(item)}")
        elif rel in self.by_file:
            mod.mods[name] = self.by_file[rel]
        else:
            mod.mods[name] = self._new_mod(rel, mod, False)

    def _mod_file(self, attrs: list[Attr], base: str, name: str) -> str | None:
        explicit = next((a for a in attrs if a.name == "path"), None)
        if explicit is not None:
            lit = string_of(explicit.value)
            rel = posixpath.normpath(posixpath.join(base, lit)) if lit else None
            return rel if rel in self._fileset else None
        for cand in (f"{base}/{name}.rs", f"{base}/{name}/mod.rs"):
            cand = posixpath.normpath(cand)
            if cand in self._fileset:
                return cand
        return None

    # -- resolution ------------------------------------------------------

    def resolve(self, mod: Mod, segs: tuple[str, ...]) -> Res | None:
        return self._resolve(mod, segs, set(), 0)

    def _resolve(
        self, mod: Mod, segs: tuple[str, ...], seen: set[tuple], depth: int
    ) -> Res | None:
        if not segs or depth > MAX_RESOLVE_DEPTH:
            return None
        head, rest = segs[0], segs[1:]
        cur: Res | None
        if head == "crate":
            cur = Res("mod", mod=mod.root)
        elif head == "self":
            cur = Res("mod", mod=mod)
        elif head == "super":
            parent: Mod | None = mod
            while parent is not None and segs and segs[0] == "super":
                parent, segs = parent.parent, segs[1:]
            if parent is None:
                return None
            cur, rest = Res("mod", mod=parent), segs
        elif head == "Self":
            return None
        else:
            cur = self._lookup(mod, head, seen, depth, not rest, True)
            if cur is None:
                if (
                    self.lib_root is not None
                    and head == self._lib_name
                    and mod.root is not self.lib_root
                ):
                    cur = Res("mod", mod=self.lib_root)
                elif rest:
                    return Res("ext", segs=segs)
                else:
                    return None
        for i, seg in enumerate(rest):
            cur = self._step(cur, seg, seen, depth, i == len(rest) - 1)
            if cur is None:
                return None
        return cur

    def _step(
        self, cur: Res, seg: str, seen: set[tuple], depth: int, last: bool
    ) -> Res | None:
        if cur.kind == "mod" and cur.mod is not None:
            return self._lookup(cur.mod, seg, seen, depth, last)
        if cur.kind == "type":
            return self.method(cur.segs[0], seg)
        if cur.kind == "ext":
            return Res("ext", segs=(*cur.segs, seg))
        return None

    def method(self, owner: str, name: str) -> Res | None:
        found = self.impls.get(owner, {}).get(name)
        if not found:
            return None
        return (
            Res("fn", fn=found[0]) if len(found) == 1 else Res("amb", alts=tuple(found))
        )

    def _lookup(
        self,
        mod: Mod,
        name: str,
        seen: set[tuple],
        depth: int,
        value_ok: bool = True,
        head: bool = False,
    ) -> Res | None:
        """`value_ok`: the name may be a function or const. A name with more
        path after it (`rocket::build`) lives in the type namespace, so a
        function called `rocket` does not shadow the crate."""
        if value_ok and name in mod.fns:
            fns = mod.fns[name]
            return (
                Res("fn", fn=fns[0]) if len(fns) == 1 else Res("amb", alts=tuple(fns))
            )
        if name in mod.mods:
            return Res("mod", mod=mod.mods[name])
        if value_ok and name in mod.consts:
            return Res("const", value=mod.consts[name])
        if name in mod.types:
            return Res("type", segs=(name,))
        key = (id(mod), name)
        if key in seen:
            return None
        seen.add(key)
        try:
            if name in mod.uses:
                return self._resolve(mod, mod.uses[name], seen, depth + 1)
            if head and name in self.extern_crates:
                return Res("ext", segs=(name,))  # beats a glob import
            return self._via_globs(mod, name, seen, depth, value_ok)
        finally:
            seen.discard(key)

    def _via_globs(
        self, mod: Mod, name: str, seen: set[tuple], depth: int, value_ok: bool
    ) -> Res | None:
        hits: list[Res] = []
        exts: list[Res] = []
        for glob in mod.globs:
            target = self._resolve(mod, glob, seen, depth + 1)
            if target is None:
                if glob and glob[0] not in ("crate", "self", "super"):
                    exts.append(
                        Res("ext", segs=(*glob, name))
                    )  # an external crate's glob
            elif target.kind == "mod" and target.mod is not None:
                hit = self._lookup(target.mod, name, seen, depth + 1, value_ok)
                if hit is not None:
                    hits.append(hit)
            elif target.kind == "ext":
                exts.append(Res("ext", segs=(*target.segs, name)))
        # two different candidates: the name is not proven to be either
        pool = hits or exts
        return (
            pool[0]
            if len({(r.kind, r.segs, id(r.fn), id(r.mod)) for r in pool}) == 1
            else None
        )
