"""JVM route adapters for `routes.py`: Spring Boot, Quarkus (JAX-RS) and
Micronaut, for Java and Kotlin sources alike (`_jvm_ast` hides the grammar
differences).

One scanner serves the three frameworks; each contributes a `_Fw` table:
which annotation makes a class a server controller, which makes a method a
handler, how a class prefix and a method's (verb, paths) read, and which
constructs it recognises but never follows.

**Default to a site, never drop.** Anything recognised as routing that does
not become a `Route` is a `file:line` site: a path or prefix that is not a
string literal (a constant, a concatenation), a computed `method=`, a
handler annotation in a class that is not a controller (a base class or
interface whose methods other classes inherit), a use of a repo-defined
annotation that itself carries a routing annotation, a JAX-RS
sub-resource locator, functional routers (`RouterFunctions`, `coRouter`),
programmatic route builders, and the config options that prefix every
served path (`_jvm_config`). Outbound clients (`@FeignClient`,
`@RegisterRestClient`, `@Client`) declare the same annotations but serve
nothing, so they are skipped. Test source sets are not product routes.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors import _jvm_ast as ast
from strata_kb.codeingest.extractors import _kotlin_parse, _ts
from strata_kb.codeingest.extractors._jvm_config import (
    MICRONAUT_KEYS,
    QUARKUS_KEYS,
    SPRING_KEYS,
    config_sites,
)
from strata_kb.codeingest.extractors._routes_jsutil import _read, _walk
from strata_kb.codeingest.extractors._routes_model import (
    AdapterResult,
    Route,
    join_path,
)
from strata_kb.codeingest.extractors._scopes import Scope

if TYPE_CHECKING:
    from tree_sitter import Node, Tree

__all__ = ["ADAPTERS"]

_HTTP_VERBS = frozenset(
    {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"}
)
_META = re.compile(rb"@interface\b|\bannotation\s+class\b")
_QUERY_TEMPLATE = re.compile(r"\{[?&][^}]*\}")
# the generator itself, not `org.openapitools:jackson-databind-nullable` (client side)
_GENERATOR = re.compile(r"openapi[-._]?generator|swagger[-._]?codegen", re.IGNORECASE)
_MANIFESTS = frozenset({"pom.xml", "build.gradle", "build.gradle.kts"})
_COMMENT = re.compile(r"^\s*(?://|/\*|\*)")

# (verb, relative paths) per handler annotation set; None = not readable
_Found = list[tuple[str, list[str]]] | None
_Prefix = tuple[list[str] | None, int]


@dataclass(frozen=True)
class _Fw:
    handlers: frozenset[str]
    stereotypes: frozenset[str]
    clients: frozenset[str]
    body: frozenset[str]
    keys: frozenset[str]
    unfollowed: re.Pattern[str]  # constructs on one line that declare routes
    prefix: Callable[[list[ast.Ann]], _Prefix]
    routes: Callable[[list[ast.Ann]], _Found]
    app_path: frozenset[str] = frozenset()
    # routing annotations that only count on a stereotype class (an
    # interface that carries them is an HTTP client, not a server)
    exchange: frozenset[str] = frozenset()
    # class annotations of another framework's server: not followed here
    foreign: frozenset[str] = frozenset()
    # manifest text that turns every repository interface into an endpoint
    data_rest: re.Pattern[str] | None = None
    # the manifest line of a server artifact: only a module that has one is a
    # web module, so only there does "no route read" mean something is missed
    dependency: re.Pattern[str] = re.compile(r"$^")
    # annotation whose interfaces classes elsewhere implement (JAX-RS `@Path`)
    shared: str = ""

    @property
    def carriers(self) -> frozenset[str]:
        return self.handlers | self.stereotypes

    def hint(
        self, extra: Iterable[str] = (), repositories: bool = False
    ) -> re.Pattern[bytes]:
        """Cheap prefilter: a file with none of these is never parsed."""
        names = (
            self.carriers
            | self.clients
            | self.app_path
            | self.exchange
            | self.foreign
            | frozenset(extra)
        )
        alternatives = "|".join(map(re.escape, sorted(names))).encode()
        pattern = rb"(?<![\w$])(?:" + alternatives + rb")(?![\w$])|"
        pattern += self.unfollowed.pattern.encode()
        return re.compile(pattern + (rb"|Repository\b" if repositories else b""))


def _source(root: Path, rel: str) -> bytes | None:
    """File bytes, read once per run (scopes and the repo-wide scans share)."""
    return ast.run_cached(("source", root, rel), lambda: _read(root, rel))


def _paths(node: Node | None) -> list[str] | None:
    """Literal paths of an annotation value; absent or empty means `""`."""
    if node is None:
        return [""]
    found = ast.strings(node)
    return found or [""] if found is not None else None


# --- Spring -----------------------------------------------------------------

_SPRING_VERBS = {
    "GetMapping": "GET",
    "PostMapping": "POST",
    "PutMapping": "PUT",
    "PatchMapping": "PATCH",
    "DeleteMapping": "DELETE",
}


_EXCHANGE_VERBS = {
    "GetExchange": "GET",
    "PostExchange": "POST",
    "PutExchange": "PUT",
    "PatchExchange": "PATCH",
    "DeleteExchange": "DELETE",
}


def _spring_prefix(anns: list[ast.Ann]) -> _Prefix:
    exchange = next((a for a in anns if a.name == "HttpExchange"), None)
    mapping = next((a for a in anns if a.name == "RequestMapping"), None)
    if mapping is not None and exchange is not None:  # which one wins is not ours
        return None, exchange.line
    if mapping is None and exchange is not None:
        return _paths(exchange.arg("value", "url", "")), exchange.line
    if mapping is None:
        return [""], 0
    if mapping.arg("method") is not None:  # a verb filter on the class
        return None, mapping.line
    return _paths(mapping.arg("value", "path", "")), mapping.line


def _spring_routes(anns: list[ast.Ann]) -> _Found:
    out: _Found = []
    for ann in anns:
        if ann.name in _EXCHANGE_VERBS or ann.name == "HttpExchange":
            given = ann.arg("method") if ann.name == "HttpExchange" else None
            verbs = [_EXCHANGE_VERBS.get(ann.name, "ANY")]
            if given is not None:
                named = ast.strings(given)
                verbs = [v.upper() for v in named or []]
                if not verbs or any(v not in _HTTP_VERBS for v in verbs):
                    return None
            paths = _paths(ann.arg("value", "url", ""))
            if paths is None:
                return None
            out += [(v, paths) for v in verbs]
            continue
        if ann.name in _SPRING_VERBS:
            verbs = [_SPRING_VERBS[ann.name]]
        elif ann.name == "RequestMapping":
            given = ann.arg("method")
            verbs = ["ANY"] if given is None else ast.enum_names(given) or []
            if given is not None and (
                not verbs or any(v not in _HTTP_VERBS for v in verbs)
            ):
                return None
        else:
            continue
        paths = _paths(ann.arg("value", "path", ""))
        if paths is None:
            return None
        out += [(v, paths) for v in verbs]
    return out


# --- Quarkus (JAX-RS) -------------------------------------------------------

_JAXRS_VERBS = frozenset(_HTTP_VERBS)


def _quarkus_prefix(anns: list[ast.Ann]) -> _Prefix:
    ann = next(a for a in anns if a.name == "Path")
    return _paths(ann.arg("value", "")), ann.line


def _quarkus_routes(anns: list[ast.Ann]) -> _Found:
    names = {a.name for a in anns}
    verbs = sorted(names & _JAXRS_VERBS)
    # a custom `@HttpMethod`, or `@Path` alone (a sub-resource locator)
    if not verbs or "HttpMethod" in names:
        return None
    path = next((a for a in anns if a.name == "Path"), None)
    paths = _paths(path.arg("value", "")) if path is not None else [""]
    return None if paths is None else [(v, paths) for v in verbs]


# --- Micronaut --------------------------------------------------------------

_MICRONAUT_VERBS = {
    "Get": "GET",
    "Post": "POST",
    "Put": "PUT",
    "Patch": "PATCH",
    "Delete": "DELETE",
    "Head": "HEAD",
    "Options": "OPTIONS",
    "Trace": "TRACE",
}


def _micronaut_prefix(anns: list[ast.Ann]) -> _Prefix:
    ann = next(a for a in anns if a.name == "Controller")
    return _paths(ann.arg("value", "uri", "")), ann.line


def _micronaut_routes(anns: list[ast.Ann]) -> _Found:
    out: _Found = []
    for ann in anns:
        if ann.name == "CustomHttpMethod":
            return None
        if ann.name not in _MICRONAUT_VERBS:
            continue
        paths = _paths(ann.arg("value", "uri", "uris", ""))
        if paths is None:
            return None
        # RFC 6570 query templates (`{?max,offset}`, `{&x}`) are not path
        paths = [_QUERY_TEMPLATE.sub("", p) for p in paths]
        out.append((_MICRONAUT_VERBS[ann.name], paths))
    return out


_FRAMEWORKS: dict[str, _Fw] = {
    "Spring Boot": _Fw(
        handlers=frozenset({*_SPRING_VERBS, "RequestMapping"}),
        stereotypes=frozenset({"RestController", "Controller"}),
        clients=frozenset({"FeignClient", "ReactiveFeignClient"}),
        body=frozenset({"RequestBody"}),
        keys=SPRING_KEYS,
        unfollowed=re.compile(
            r"\b(?:RouterFunctions?|coRouter|RouteLocator(?:Builder)?|addPathPrefix"
            r"|addViewController|addRedirectViewController|SimpleUrlHandlerMapping"
            r"|ServletRegistrationBean|RepositoryRestResource)\b|@WebServlet"
            r"|\brouter\s*\{"
        ),
        prefix=_spring_prefix,
        routes=_spring_routes,
        exchange=frozenset({*_EXCHANGE_VERBS, "HttpExchange"}),
        foreign=frozenset({"Path"}),  # Jersey under Spring Boot
        data_rest=re.compile(r"data-rest"),
        dependency=re.compile(
            r"spring-boot-starter-(?:web|webflux|jersey)\b|spring-web(?:mvc|flux)?\b"
        ),
    ),
    "Quarkus": _Fw(
        handlers=frozenset({*_JAXRS_VERBS, "Path", "HttpMethod"}),
        stereotypes=frozenset({"Path"}),
        clients=frozenset({"RegisterRestClient"}),
        body=frozenset(),
        keys=QUARKUS_KEYS,
        unfollowed=re.compile(
            r"@Route(?:Base)?\b|@Observes\s+(?:\w+\.)*Router\b|@WebServlet"
        ),
        prefix=_quarkus_prefix,
        routes=_quarkus_routes,
        app_path=frozenset({"ApplicationPath"}),
        foreign=frozenset({"RestController", "RequestMapping"}),  # quarkus-spring-web
        dependency=re.compile(
            r"quarkus-(?:rest|resteasy|vertx-http|reactive-routes|spring-web)"
        ),
        shared="Path",
    ),
    "Micronaut": _Fw(
        handlers=frozenset({*_MICRONAUT_VERBS, "CustomHttpMethod"}),
        stereotypes=frozenset({"Controller"}),
        clients=frozenset({"Client"}),
        body=frozenset({"Body"}),
        keys=MICRONAUT_KEYS,
        unfollowed=re.compile(r"\bRouteBuilder\b"),
        prefix=_micronaut_prefix,
        routes=_micronaut_routes,
        dependency=re.compile(r"micronaut-http-server"),
    ),
}


def _composed(trees: dict[str, Tree], fw: _Fw) -> frozenset[str]:
    """Names of repo-defined annotations that themselves carry a routing
    annotation, directly or through another such annotation (`@ApiV1` =
    `@RestController @RequestMapping("/v1")`)."""
    found: set[str] = set()
    grew = True
    while grew:
        grew = False
        for tree in trees.values():
            for node in _walk(tree.root_node):
                if (
                    node.type in ("annotation_type_declaration", "class_declaration")
                    and ast.is_annotation_type(node)
                    and ast.class_name(node) not in found
                    and any(
                        a.name in fw.carriers | found for a in ast.annotations_of(node)
                    )
                ):
                    found.add(ast.class_name(node))
                    grew = True
    return frozenset(found)


def _request_type(method: Node, fw: _Fw) -> str:
    for param in ast.params(method):
        if any(a.name in fw.body for a in param.anns):
            return param.type
    return ""


def _scan_class(
    rel: str, cls: Node, fw: _Fw, composed: frozenset[str], result: AdapterResult
) -> list[Route]:
    anns = ast.annotations_of(cls)
    members = [(m, ast.annotations_of(m)) for m in ast.methods(cls)]
    sites = result.dynamic_sites
    start = len(sites)
    sites += [
        f"{rel}:{a.line}"
        for a in [*anns, *(a for _m, found in members for a in found)]
        if a.name in composed
    ]
    sites += [f"{rel}:{a.line}" for a in anns if a.name in fw.foreign]
    names = {a.name for a in anns}
    if names & fw.clients:
        return []
    if not names & fw.stereotypes:
        # a handler annotation on an interface or base class: the classes
        # that inherit it serve routes this scan cannot attach a path to
        sites += [f"{rel}:{a.line}" for a in anns if a.name in fw.handlers]
        for _m, found in members:
            first = next((a for a in found if a.name in fw.handlers), None)
            if first is not None:
                sites.append(f"{rel}:{first.line}")
        return []
    routing = fw.handlers | fw.exchange
    mapped = [
        (m, next(a for a in found if a.name in routing), found)
        for m, found in members
        if any(a.name in routing for a in found)
    ]
    # an override serves whatever the supertype mapped; invisible from here
    sites += [
        f"{rel}:{ast.name_line(m)}"
        for m, found in members
        if ast.is_override(m) and not any(a.name in routing for a in found)
    ]
    out: list[Route] = []
    prefixes, line = fw.prefix(anns)
    if prefixes is None:
        sites.append(f"{rel}:{line}")
    else:
        handler_class = ast.class_name(cls)
        for method, first, found in mapped:
            read = fw.routes(found)
            if read is None:
                sites.append(f"{rel}:{first.line}")
                continue
            handler = f"{handler_class}.{_method_name(method)}"
            body = _request_type(method, fw)
            out += [
                Route(verb, join_path(prefix, path), handler, rel, first.line, body)
                for verb, paths in read
                for prefix in prefixes
                for path in paths
            ]
    if not out and len(sites) == start:  # a controller that yields nothing
        sites.append(f"{rel}:{ast.name_line(cls)}")
    return out


def _method_name(method: Node) -> str:
    named = method.child_by_field_name("name")
    if named is None:  # Kotlin: the first simple_identifier is the name
        named = next(
            (c for c in method.children if c.type == "simple_identifier"), None
        )
    return " ".join((named.text or b"").decode().split()) if named else ""


def _unfollowed_sites(rel: str, data: bytes, fw: _Fw) -> list[str]:
    return [
        f"{rel}:{number}"
        for number, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1)
        if fw.unfollowed.search(line)
        and not _COMMENT.match(line)
        and not line.lstrip().startswith(("import ", "package "))
    ]


def _application_prefix(found: list[tuple[str, ast.Ann]], result: AdapterResult) -> str:
    """`@ApplicationPath` prefixes every JAX-RS route; one literal is
    applied, anything else (none readable, several) is a site."""
    values = [(rel, ann, ast.strings(ann.arg("value", ""))) for rel, ann in found]
    if len(values) == 1 and values[0][2] is not None and len(values[0][2]) == 1:
        return values[0][2][0]
    result.dynamic_sites += [f"{rel}:{ann.line}" for rel, ann, _v in values]
    return ""


def _manifests(
    root: Path, repo_files: list[str], only: str | None = None
) -> list[tuple[str, str]]:
    """(path, text) of the build files in directory `only`, or everywhere
    (read once per run)."""

    def read_all() -> list[tuple[str, str]]:
        out = []
        for rel in repo_files:
            if rel.rpartition("/")[2] in _MANIFESTS:
                data = _read(root, rel)
                if data is not None:
                    out.append((rel, data.decode("utf-8", "replace")))
        return out

    everything = ast.run_cached(("manifests", root), read_all)
    if only is None:
        return everything
    return [
        (rel, t) for rel, t in everything if (rel.rpartition("/")[0] or ".") == only
    ]


def _generator_sites(manifests: list[tuple[str, str]]) -> list[str]:
    """Generated server stubs (OpenAPI Generator, swagger-codegen) come from
    a build step, often in a sibling module or the parent build: their
    interfaces are not in this tree, whichever module runs the generator."""
    return [
        f"{rel}:{number}"
        for rel, text in manifests
        for number, line in enumerate(text.splitlines(), start=1)
        if _GENERATOR.search(line)
    ]


def _dependency_site(fw: _Fw, manifests: list[tuple[str, str]]) -> str | None:
    for rel, text in manifests:
        for number, line in enumerate(text.splitlines(), start=1):
            if fw.dependency.search(line):
                return f"{rel}:{number}"
    return None


def _path_interfaces(
    root: Path, repo_files: list[str], fw: _Fw
) -> list[tuple[str, str]]:
    """(name, file) of each repo interface annotated `@<fw.shared>`, in any
    module: a class elsewhere that implements one serves its routes. A list,
    so two interfaces with one simple name in different modules both count."""
    if not fw.shared:
        return []

    def scan() -> list[tuple[str, str]]:
        found = []
        marker = re.compile(rb"\b" + re.escape(fw.shared.encode()) + rb"\b")
        for rel in ast.jvm_files(repo_files):
            data = _source(root, rel)
            if data is None or not marker.search(data) or b"interface" not in data:
                continue
            for cls in ast.classes(_kotlin_parse.parse(rel, data).root_node):
                names = {a.name for a in ast.annotations_of(cls)}
                if (
                    ast.is_interface(cls)
                    and fw.shared in names
                    and not names & fw.clients
                ):
                    found.append((ast.class_name(cls), rel))
        return found

    return ast.run_cached(("interfaces", root, fw.shared), scan)


def _repository_sites(rel: str, tree: Tree) -> list[str]:
    """Spring Data REST exports every repository interface as endpoints."""
    sites = []
    for decl in ast.classes(tree.root_node):
        header = ast.header_text(decl)
        supertypes = header.split(ast.class_name(decl), 1)[-1]
        if ast.is_interface(decl) and re.search(r"\w*Repository\b", supertypes):
            sites.append(f"{rel}:{ast.name_line(decl)}")
    return sites


def _implements(cls: Node, names: set[str]) -> bool:
    """Whether the class header's supertypes name one of `names`."""
    supertypes = ast.header_text(cls).split(ast.class_name(cls), 1)[-1]
    alternatives = "|".join(map(re.escape, sorted(names)))
    return re.search(rf"(?<![\w$])(?:{alternatives})(?![\w$])", supertypes) is not None


def _adapter(
    label: str,
) -> Callable[[Path, Scope, list[str], list[str]], AdapterResult]:
    fw = _FRAMEWORKS[label]

    def adapter(
        root: Path, scope: Scope, files: list[str], repo_files: list[str]
    ) -> AdapterResult:
        result = AdapterResult()
        sources: dict[str, bytes] = {}
        for rel in ast.jvm_files(files):
            data = _source(root, rel)
            if data is None:
                result.dynamic_sites.append(f"{rel}:1")
            else:
                sources[rel] = data
        trees: dict[str, Tree] = {}

        def tree_of(rel: str) -> None:
            if rel not in trees:
                trees[rel] = _kotlin_parse.parse(rel, sources[rel])
                lang = _ts.language_for(rel) or ""
                line = _kotlin_parse.error_line(trees[rel], lang)
                if line is not None:
                    result.dynamic_sites.append(f"{rel}:{line}")

        manifests = _manifests(root, repo_files, scope.path)
        result.dynamic_sites += _generator_sites(_manifests(root, repo_files))
        data_rest = fw.data_rest is not None and any(
            fw.data_rest.search(text) for _rel, text in manifests
        )
        # annotation declarations first: a file that only uses `@ApiV1` has
        # none of the routing words, so the prefilter needs their names
        for rel in sorted(sources):
            if _META.search(sources[rel]):
                tree_of(rel)
        composed = _composed(trees, fw)
        in_scope = set(sources)
        external = {
            name
            for name, rel in _path_interfaces(root, repo_files, fw)
            if rel not in in_scope
        }
        hint = fw.hint(composed | external, data_rest)
        for rel in sorted(sources):
            if hint.search(sources[rel]):
                tree_of(rel)
        routes: list[Route] = []
        app_paths: list[tuple[str, ast.Ann]] = []
        for rel in sorted(trees):
            tree = trees[rel]
            result.dynamic_sites += _unfollowed_sites(rel, sources[rel], fw)
            if data_rest:
                result.dynamic_sites += _repository_sites(rel, tree)
            for cls in ast.classes(tree.root_node):
                if external and _implements(cls, external):
                    result.dynamic_sites.append(f"{rel}:{ast.name_line(cls)}")
                app_paths += [
                    (rel, a) for a in ast.annotations_of(cls) if a.name in fw.app_path
                ]
                routes += _scan_class(rel, cls, fw, composed, result)
        if fw.app_path:
            base = _application_prefix(app_paths, result)
            routes = [replace(r, path=join_path(base, r.path)) for r in routes]
        result.routes = routes
        if not routes and not result.dynamic_sites:  # a web module that read nothing
            net = _dependency_site(fw, manifests)
            if net is not None:
                result.dynamic_sites.append(net)
        result.dynamic_sites += config_sites(root, scope, repo_files, fw.keys)
        return result

    return adapter


ADAPTERS = {label: _adapter(label) for label in _FRAMEWORKS}
