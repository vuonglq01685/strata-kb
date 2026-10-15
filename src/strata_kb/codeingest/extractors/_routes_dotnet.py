"""ASP.NET Core route adapter for `routes.py`: attribute-routed controllers
here, minimal APIs (`MapGet`, `MapGroup`, ...) in `_routes_dotnet_minimal`.

**Controllers.** A public, non-abstract, non-generic class whose name ends in
`Controller` (or that carries `[Controller]`) is discovered by MVC; each
public method is an action. The class `[Route]` template(s) are the prefix;
the action's `[HttpGet("t")]` ... `[Route("t")]` ... `[AcceptVerbs]`
attributes become selectors the way MVC builds them (a `[Route]` absorbs the
bare verb attributes beside it, otherwise they make one prefix-only
selector). Templates are combined, then `[controller]` (class name without
`Controller`, **lower-cased**, as the plan specifies), `[action]` (method
name, or `[ActionName]`, as written) and `[area]` (the `[Area]` literal) are
replaced; `[[` / `]]` are literal brackets. `/` or `~/` at the start of an
action template ignores the prefix. A `[Route]` on a repo base controller is
inherited when the derived class has none.

**Default to a site, never drop.** Anything recognised as routing that does
not become a `Route` is a `file:line` site: a template that is not a literal
(constant, interpolation, concatenation) or keeps an unknown `[token]`; an
`[Area]` together with `{area}`; a conventional (non-attribute) action;
handler attributes on a base class, interface or abstract class; a base
class the repo does not declare; a base `[Route]` combined with the class's
own; a repo attribute derived from a routing attribute; conventional
routing (`MapControllerRoute`, `UseMvc`), route conventions, `UsePathBase`,
application parts, OpenAPI/NSwag server generation in the build; a
controller that yields nothing; a web project that yields no route at all.
Test projects are not product routes.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors import _cs_ast as ast
from strata_kb.codeingest.extractors import _routes_dotnet_minimal as minimal
from strata_kb.codeingest.extractors._jvm_ast import run_cached
from strata_kb.codeingest.extractors._routes_jsutil import _error_line
from strata_kb.codeingest.extractors._routes_model import (
    AdapterResult,
    Route,
    join_path,
)
from strata_kb.codeingest.extractors._scopes import Scope

if TYPE_CHECKING:
    from tree_sitter import Node

__all__ = ["ADAPTERS"]

_VERBS = {
    "HttpGet": "GET",
    "HttpPost": "POST",
    "HttpPut": "PUT",
    "HttpDelete": "DELETE",
    "HttpPatch": "PATCH",
    "HttpHead": "HEAD",
    "HttpOptions": "OPTIONS",
}
_ROUTING = frozenset({*_VERBS, "Route", "AcceptVerbs"})
# what a repo attribute derives from to become a routing attribute itself
_ROUTING_BASES = _ROUTING | {
    "HttpMethod",
    "IRouteTemplateProvider",
    "IActionHttpMethodProvider",
}
_FRAMEWORK_BASES = frozenset({"ControllerBase", "Controller", "object"})
_INTERFACE = re.compile(r"I[A-Z]\w*")
_TOKEN = re.compile(r"\[\[|\]\]|\[([^\[\]]*)\]")
_AREA_PARAM = re.compile(r"\{area\b", re.IGNORECASE)
_ATTRIBUTE_CLASS = re.compile(rb"\bclass\s+(\w+)\s*(?:<[^>]*>)?\s*:\s*([^{;]*)")
_UNFOLLOWED = re.compile(
    rb"\bUsePathBase\b|\bPathBase\s*=|\.Conventions\.Add\s*\(|\bI(?:Application|Controller|Action)ModelConvention\b"
    rb"|\bUseMvc\w*|\bAddApplicationPart\b|\bApplicationPartManager\b|\bControllerFeatureProvider\b"
    rb"|\bMapODataRoute\b|\bUseFastEndpoints\b|\bI?CarterModule\b"
    rb"|:\s*(?:Endpoint(?:Without(?:Request|Response)|WithMapper)?\b|Ep\.)"
    rb"|\[\s*RoutePrefix\b"
)
_COMMENT = re.compile(rb"^\s*(?://|/\*|\*)")
_FIRST_BASE = re.compile(rb"\bclass\s+\w+\s*(?:<[^>]*>)?(?:\([^)]*\))?\s*:\s*([\w.]+)")
_PAGE = re.compile(rb"^\s*@page\b", re.MULTILINE)
_PAGE_FILES = (".cshtml", ".razor")
# NSwag / OpenAPI Generator emit server stubs from the build, not into the tree
_GENERATOR = re.compile(
    r"NSwag\.MSBuild|openapi[-._]?generator|swagger[-._]?codegen", re.I
)
_BUILD_FILES = (".csproj", ".props", ".targets")
_WEB_LINE = re.compile(
    r"""Sdk\s*=\s*"Microsoft\.NET\.Sdk\.Web\b|<Sdk\s+Name\s*=\s*"Microsoft\.NET\.Sdk\.Web\b"""
    r"""|<FrameworkReference\s+Include\s*=\s*"Microsoft\.AspNetCore\.App\b"""
    # a package that serves routes; not test hosts, Blazor WebAssembly clients,
    # or libraries of auth / HttpContext helpers
    r"""|Include\s*=\s*"Microsoft\.AspNetCore\.(?:App|All|Mvc(?!\.Testing\b)|Routing|OpenApi"""
    r"""|Razor|Server\.|SpaServices|OData)"""
)
_WEB_USING = re.compile(
    r"^\s*(?:global\s+)?using\s+(?:static\s+)?Microsoft\.AspNetCore\.(?:Mvc|Builder|Routing)\b"
)


@dataclass
class _View:
    """One type, or the parts of a `partial` one spread over files."""

    name: str
    kind: str  # the declaration node type
    parts: list[tuple[str, Node]]

    @property
    def attrs(self) -> list[tuple[str, ast.Attr]]:
        return [(rel, a) for rel, n in self.parts for a in ast.attrs_of(n)]

    @property
    def rel(self) -> str:
        return self.parts[0][0]

    @property
    def line(self) -> int:
        return ast.name_line(self.parts[0][1])

    @property
    def modifiers(self) -> set[str]:
        return {m for _r, n in self.parts for m in ast.modifiers(n)}

    @property
    def methods(self) -> list[tuple[str, Node]]:
        return [(rel, m) for rel, n in self.parts for m in ast.methods(n)]

    @property
    def bases(self) -> list[str]:
        return [b for _r, n in self.parts for b in ast.base_names(n)]

    def named(self, name: str) -> list[tuple[str, ast.Attr]]:
        return [(rel, a) for rel, a in self.attrs if a.name == name]


def _views(trees: dict[str, Node]) -> list[_View]:
    """Every type declaration of the given trees; `partial` parts merge."""
    by_name: dict[str, _View] = {}
    out: list[_View] = []
    for rel in sorted(trees):
        for decl in ast.type_decls(trees[rel]):
            name = ast.decl_name(decl)
            if "partial" in ast.modifiers(decl) and name in by_name:
                by_name[name].parts.append((rel, decl))
                continue
            view = _View(name, decl.type, [(rel, decl)])
            out.append(view)
            if "partial" in ast.modifiers(decl):
                by_name[name] = view
    return out


def _site(rel: str, line: int) -> str:
    return f"{rel}:{line}"


def _composed_names(root: Path, repo_files: list[str]) -> frozenset[str]:
    """Repo attribute classes derived (directly or through another) from a
    routing attribute: `[ApiGet("x")]` is a route this scan cannot read."""

    def scan() -> frozenset[str]:
        declared: dict[str, set[str]] = {}
        for rel in ast.cs_files(root, repo_files, repo_files):
            data = ast.source(root, rel)
            for name, bases in _ATTRIBUTE_CLASS.findall(data or b""):
                declared.setdefault(name.decode(), set()).update(
                    re.sub(r"Attribute$", "", ast.simple_name(b.strip()))
                    for b in bases.decode("utf-8", "replace").split(",")
                )
        found: set[str] = set()
        grew = True
        while grew:
            grew = False
            for name, bases in declared.items():
                plain = re.sub(r"Attribute$", "", name)
                if plain not in found and bases & (_ROUTING_BASES | found):
                    found.add(plain)
                    grew = True
        return frozenset(found)

    return run_cached(("cs-composed", root), scan)


def _base_classes(root: Path, repo_files: list[str]) -> frozenset[str]:
    """Simple names that some repo class names as its base class."""

    def scan() -> frozenset[str]:
        found: set[str] = set()
        for rel in ast.cs_files(root, repo_files, repo_files):
            data = ast.source(root, rel)
            found.update(
                ast.simple_name(m.decode()) for m in _FIRST_BASE.findall(data or b"")
            )
        return frozenset(found)

    return run_cached(("cs-bases", root), scan)


def _has_pages(root: Path, scope: Scope, repo_files: list[str]) -> bool:
    """Razor Pages / Blazor `@page` files: pages, which this table skips."""
    inside = "" if scope.path == "." else scope.path + "/"
    for rel in repo_files:
        if rel.endswith(_PAGE_FILES) and rel.startswith(inside):
            data = ast.source(root, rel)
            if data is not None and _PAGE.search(data):
                return True
    return False


def _hint(composed: frozenset[str], helpers: frozenset[str]) -> re.Pattern[bytes]:
    """Cheap prefilter: a file with none of these is never parsed. A helper's
    name counts: the file that calls `ConfigurePipeline()` has no route word."""
    names = sorted(
        {
            *_ROUTING,
            "HttpMethod",
            "Map[A-Z]\\w*",
            *map(re.escape, composed | helpers),
        }
    )
    # `Controller` anywhere: `HomeController : BaseController` has no other word
    return re.compile(
        rb"(?<![\w$])(?:"
        + "|".join(names).encode()
        + rb")|Controller|"
        + _UNFOLLOWED.pattern
    )


# --- selectors --------------------------------------------------------------


@dataclass
class _Sel:
    verbs: tuple[str, ...]
    template: str | None  # None: the class prefix alone
    line: int


def _selectors(rel: str, found: list[ast.Attr], sites: list[str]) -> list[_Sel] | None:
    """MVC's selector rules for the routing attributes of one action; None
    (with a site) when one cannot be read."""
    absorbing: list[_Sel] = []  # defined by a plain `[Route]`
    own: list[_Sel] = []  # `[HttpGet("t")]`: one selector of its own
    silent: list[ast.Attr] = []
    silent_verbs: set[str] = set()
    for attr in found:
        verbs: tuple[str, ...] = (_VERBS[attr.name],) if attr.name in _VERBS else ()
        if attr.name == "AcceptVerbs":
            listed = [ast.literal(n) for n in attr.positional()]
            if not listed or None in listed:
                sites.append(_site(rel, attr.line))
                return None
            verbs = tuple(str(v).upper() for v in listed)
            node = attr.arg("Route")
        else:
            node = attr.arg("", "template", "Template")
        if attr.name == "Route" and node is None:
            sites.append(_site(rel, attr.line))
            return None
        template = ast.literal(node) if node is not None else None
        if node is not None and template is None:
            sites.append(_site(rel, attr.line))
            return None
        named = attr.arg("Name", "Order") is not None
        if template is None and not named:
            silent.append(attr)
            silent_verbs.update(verbs)
        elif attr.name == "Route":
            absorbing.append(_Sel((), template, attr.line))
        else:
            own.append(_Sel(verbs, template, attr.line))
    if not found:
        return [_Sel(("ANY",), None, 0)]
    sels = [
        _Sel(tuple(sorted(silent_verbs)) or ("ANY",), s.template, s.line)
        for s in absorbing
    ]
    sels += own
    if silent and not absorbing:
        sels.append(_Sel(tuple(sorted(silent_verbs)) or ("ANY",), None, silent[0].line))
    return sels


def _expand(template: str, values: dict[str, str | None]) -> str | None:
    """Replace `[controller]` / `[action]` / `[area]`; None when a token is
    unknown or has no value."""
    bad = False

    def replace(match: re.Match[str]) -> str:
        nonlocal bad
        if match.group(0) in ("[[", "]]"):
            return match.group(0)[0]
        value = values.get(match.group(1))
        if value is None:
            bad = True
            return match.group(0)
        return value

    out = _TOKEN.sub(replace, template)
    return None if bad else out


# --- controllers ------------------------------------------------------------


class _Index:
    """Repo-wide type lookup for base classes (any module, parsed on demand)."""

    def __init__(self, root: Path, repo_files: list[str]):
        self._root = root
        self._names = ast.declared_names(root, repo_files)

    def lookup(self, name: str) -> list[_View]:
        trees: dict[str, Node] = {}
        for rel in self._names.get(name, []):
            data = ast.source(self._root, rel)
            if data is not None:
                trees[rel] = ast.tree(self._root, rel, data).root_node
        return [v for v in _views(trees) if v.name == name]


def _class_base(bases: list[str], index: _Index) -> tuple[str | None, list[_View]]:
    """The base class among a type's bases and the repo types of that name.
    An `I...` name is an interface unless the repo declares a class by it."""
    for name in bases:
        if name in _FRAMEWORK_BASES:
            return name, []
        found = index.lookup(name)
        if found:
            if all(v.kind == "interface_declaration" for v in found):
                continue
            return name, found
        if not _INTERFACE.fullmatch(name):
            return name, []  # a class declared outside the repo
    return None, []


def _ancestors(view: _View, index: _Index, sites: list[str]) -> list[_View]:
    """Repo base classes of `view`, nearest first. A base the repo does not
    declare (a package, another solution) is a site: it may carry routes."""
    chain: list[_View] = []
    seen = {view.name}
    current, found = _class_base(view.bases, index)
    while current and current not in _FRAMEWORK_BASES and current not in seen:
        seen.add(current)
        if len(found) != 1:  # undeclared here, or two types of one name
            sites.append(_site(view.rel, view.line))
            break
        chain.append(found[0])
        current, found = _class_base(found[0].bases, index)
    return chain


def _method_routing(method: Node) -> list[ast.Attr]:
    return [a for a in ast.attrs_of(method) if a.name in _ROUTING]


def _is_controller(view: _View) -> bool:
    mods = view.modifiers
    return (
        view.kind == "class_declaration"
        and "public" in mods
        and "abstract" not in mods
        and not any(ast.has_type_parameters(n) for _r, n in view.parts)
        and (view.name.lower().endswith("controller") or bool(view.named("Controller")))
    )


def _is_action(method: Node) -> bool:
    mods = ast.modifiers(method)
    if "public" not in mods or mods & {"static", "abstract"}:
        return False
    if any(c.type == "type_parameter_list" for c in method.children):
        return False
    if method.child_by_field_name("name") is None or ast.decl_name(method) == "Dispose":
        return False
    return not any(a.name == "NonAction" for a in ast.attrs_of(method))


def _prefixes(
    view: _View, chain: list[_View], sites: list[str]
) -> tuple[list[str] | None, str | None, bool]:
    """(class templates, area, area given). Templates None: unreadable."""
    own = view.named("Route")
    inherited = next((v.named("Route") for v in chain if v.named("Route")), [])
    if own and inherited:  # how MVC merges the two is not followed
        sites.append(_site(*_at(own[0])))
    given = own or inherited
    templates: list[str] | None = []
    for rel, attr in given:
        text = ast.literal(attr.arg("", "template", "Template"))
        if text is None:
            sites.append(_site(rel, attr.line))
            templates = None
        elif templates is not None:
            templates.append(text.removeprefix("~/"))
    area_attrs = view.named("Area") or next(
        (v.named("Area") for v in chain if v.named("Area")), []
    )
    area: str | None = None
    if area_attrs:
        area = ast.literal(area_attrs[0][1].arg("", "areaName", "AreaName"))
        if area is None:
            sites.append(_site(area_attrs[0][0], area_attrs[0][1].line))
    return templates, area, bool(area_attrs)


def _at(found: tuple[str, ast.Attr]) -> tuple[str, int]:
    return found[0], found[1].line


def _request_type(method: Node) -> str:
    for param in ast.params(method):
        if any(a.name == "FromBody" for a in param.attrs):
            return param.type.rstrip("?").strip()
    return ""


def _scan_controller(
    view: _View,
    index: _Index,
    composed: frozenset[str],
    bases: frozenset[str],
    result: AdapterResult,
) -> list[Route]:
    sites = result.dynamic_sites
    start = len(sites)
    chain = _ancestors(view, index, sites)
    # handler attributes on a repo base class are served by this class too
    for base in chain:
        for rel, method in base.methods:
            attrs = _method_routing(method)
            if attrs:
                sites.append(_site(rel, attrs[0].line))
    templates, area, has_area = _prefixes(view, chain, sites)
    if templates is None:
        return []
    out: list[Route] = []
    controller = view.name.removesuffix("Controller")
    for rel, method in view.methods:
        if not _is_action(method):
            continue
        attrs = ast.attrs_of(method)
        used = [a for a in attrs if a.name in composed]
        sites += [_site(rel, a.line) for a in used]
        routing = [a for a in attrs if a.name in _ROUTING]
        if ast.modifiers(method) & {"override"} and not routing:
            continue  # an override serves what its base declared: seen above
        # MVC drops the `Async` suffix from action names
        action = re.sub(r"(?<=\w)Async$", "", ast.decl_name(method))
        renamed = [a for a in attrs if a.name == "ActionName"]
        if renamed:
            action = ast.literal(renamed[0].arg("", "name", "Name")) or ""
            if not action:
                sites.append(_site(rel, renamed[0].line))
                continue
        selectors = _selectors(rel, routing, sites)
        if selectors is None:
            continue
        values: dict[str, str | None] = {
            "controller": controller.lower(),
            "action": action,
            "area": area,
        }
        body = _request_type(method)
        for sel in selectors:
            line = sel.line or ast.name_line(method)
            if sel.template is None and not templates:
                sites.append(_site(rel, line))  # conventional routing
                continue
            absolute = sel.template is not None and sel.template.startswith(("/", "~/"))
            own = (sel.template or "").removeprefix("~/")
            for prefix in templates if (templates and not absolute) else [""]:
                path = join_path(prefix, own)
                if has_area and _AREA_PARAM.search(path):
                    sites.append(_site(rel, line))
                    continue
                final = _expand(path, values)
                if final is None:
                    sites.append(_site(rel, line))
                    continue
                out += [
                    Route(
                        verb,
                        final,
                        f"{view.name}.{ast.decl_name(method)}",
                        rel,
                        line,
                        body,
                    )
                    for verb in sel.verbs
                ]
    # a controller that yields nothing, unless other controllers build on it
    if not out and len(sites) == start and view.name not in bases:
        sites.append(_site(view.rel, view.line))
    return out


def _conditional_sites(view: _View) -> list[str]:
    """Attributes under `#if`: the active alternative is unknown, so the
    routes they declare are a guess."""
    found = [(rel, a) for rel, a in view.attrs]
    for rel, method in view.methods:
        found += [(rel, a) for a in ast.attrs_of(method)]
    return [_site(rel, a.line) for rel, a in found if a.conditional]


def _stray_handlers(view: _View, composed: frozenset[str], sites: list[str]) -> None:
    """Handler attributes in a type MVC does not serve as a controller (an
    abstract or generic base, an interface, a plain class) or composed
    attributes anywhere: the classes inheriting them are invisible here."""
    for rel, method in view.methods:
        attrs = ast.attrs_of(method)
        first = next(
            (a for a in attrs if a.name in _ROUTING or a.name in composed), None
        )
        if first is not None:
            sites.append(_site(rel, first.line))


# --- the scope --------------------------------------------------------------


def _line_sites(rel: str, data: bytes, pattern: re.Pattern[bytes]) -> list[str]:
    return [
        _site(rel, number)
        for number, line in enumerate(data.splitlines(), 1)
        if pattern.search(line) and not _COMMENT.match(line)
    ]


def _build_files(root: Path, repo_files: list[str]) -> list[tuple[str, str]]:
    def read() -> list[tuple[str, str]]:
        out = []
        for rel in repo_files:
            if rel.endswith(_BUILD_FILES):
                data = ast.source(root, rel)
                if data is not None:
                    out.append((rel, data.decode("utf-8", "replace")))
        return out

    return run_cached(("cs-build", root), read)


def _generator_sites(root: Path, repo_files: list[str]) -> list[str]:
    sites = [
        _site(rel, number)
        for rel, text in _build_files(root, repo_files)
        for number, line in enumerate(text.splitlines(), 1)
        if _GENERATOR.search(line)
    ]
    return sites + [_site(rel, 1) for rel in repo_files if rel.endswith(".nswag")]


def _web_site(
    scope: Scope, builds: list[tuple[str, str]], sources: dict[str, bytes]
) -> str | None:
    """Where a web module announces itself: its project file, else the first
    `using` of an ASP.NET Core namespace."""
    for rel, text in builds:
        if rel.endswith(".csproj") and (rel.rpartition("/")[0] or ".") == scope.path:
            for number, line in enumerate(text.splitlines(), 1):
                if _WEB_LINE.search(line):
                    return _site(rel, number)
    for rel in sorted(sources):
        for number, line in enumerate(
            sources[rel].decode("utf-8", "replace").splitlines(), 1
        ):
            if _WEB_USING.match(line):
                return _site(rel, number)
    return None


def adapter(
    root: Path, scope: Scope, files: list[str], repo_files: list[str]
) -> AdapterResult:
    result = AdapterResult()
    sites = result.dynamic_sites
    sources: dict[str, bytes] = {}
    for rel in ast.cs_files(root, files, repo_files):
        data = ast.source(root, rel)
        if data is None:
            sites.append(_site(rel, 1))
        else:
            sources[rel] = data
    composed = _composed_names(root, repo_files)
    hint = _hint(composed, minimal.helper_names(root, repo_files))
    trees: dict[str, Node] = {}
    for rel in sorted(sources):
        if not hint.search(sources[rel]):
            continue
        parsed = ast.tree(root, rel, sources[rel])
        line = _error_line(parsed)
        if line is not None:
            sites.append(_site(rel, line))
        trees[rel] = parsed.root_node
        sites += _line_sites(rel, sources[rel], _UNFOLLOWED)
    sites += _generator_sites(root, repo_files)
    index = _Index(root, repo_files)
    bases = _base_classes(root, repo_files)
    routes: list[Route] = []
    for view in _views(trees):
        if view.named("NonController"):
            continue
        sites += _conditional_sites(view)
        if _is_controller(view):
            routes += _scan_controller(view, index, composed, bases, result)
            sites += [_site(rel, a.line) for rel, a in view.attrs if a.name in composed]
        else:
            _stray_handlers(view, composed, sites)
            sites += [_site(rel, a.line) for rel, a in view.attrs if a.name in composed]
    found, delegated = minimal.scan(root, trees, repo_files, result)
    routes += found
    result.routes = routes
    builds = _build_files(root, repo_files)
    if not (routes or sites or delegated or _has_pages(root, scope, repo_files)):
        # a web module that yields no route at all (pages are not routes)
        net = _web_site(scope, builds, sources)
        if net is not None:
            sites.append(net)
    return result


ADAPTERS: dict[str, Callable[[Path, Scope, list[str], list[str]], AdapterResult]] = {
    "ASP.NET Core": adapter
}
