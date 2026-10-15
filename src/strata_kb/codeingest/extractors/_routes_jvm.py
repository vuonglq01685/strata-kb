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
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors import _jvm_ast as ast
from strata_kb.codeingest.extractors._jvm_config import (
    MICRONAUT_KEYS,
    QUARKUS_KEYS,
    SPRING_KEYS,
    config_sites,
)
from strata_kb.codeingest.extractors._routes_jsutil import (
    _error_line,
    _parse,
    _read,
    _walk,
)
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

    @property
    def carriers(self) -> frozenset[str]:
        return self.handlers | self.stereotypes

    @property
    def hint(self) -> re.Pattern[bytes]:
        names = self.carriers | self.clients | self.app_path
        return re.compile(
            rb"\b(?:"
            + "|".join(sorted(names)).encode()
            + rb")\b|"
            + self.unfollowed.pattern.encode()
        )


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


def _spring_prefix(anns: list[ast.Ann]) -> _Prefix:
    mapping = next((a for a in anns if a.name == "RequestMapping"), None)
    if mapping is None:
        return [""], 0
    if mapping.arg("method") is not None:  # a verb filter on the class
        return None, mapping.line
    return _paths(mapping.arg("value", "path", "")), mapping.line


def _spring_routes(anns: list[ast.Ann]) -> _Found:
    out: _Found = []
    for ann in anns:
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
    ),
}


def _composed(parsed: list[tuple[str, Tree]], fw: _Fw) -> frozenset[str]:
    """Names of repo-defined annotations that themselves carry a routing
    annotation (`@ApiV1` = `@RestController @RequestMapping("/v1")`)."""
    found: set[str] = set()
    for _rel, tree in parsed:
        for node in _walk(tree.root_node):
            if (
                node.type in ("annotation_type_declaration", "class_declaration")
                and ast.is_annotation_type(node)
                and any(a.name in fw.carriers for a in ast.annotations_of(node))
            ):
                found.add(ast.class_name(node))
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
    result.dynamic_sites += [
        f"{rel}:{a.line}"
        for a in [*anns, *(a for _m, found in members for a in found)]
        if a.name in composed
    ]
    mapped = [
        (m, next(a for a in found if a.name in fw.handlers), found)
        for m, found in members
        if any(a.name in fw.handlers for a in found)
    ]
    names = {a.name for a in anns}
    if not mapped or names & fw.clients:
        return []
    if not names & fw.stereotypes:
        result.dynamic_sites.append(f"{rel}:{mapped[0][1].line}")
        return []
    prefixes, line = fw.prefix(anns)
    if prefixes is None:
        result.dynamic_sites.append(f"{rel}:{line}")
        return []
    handler_class = ast.class_name(cls)
    out: list[Route] = []
    for method, first, found in mapped:
        read = fw.routes(found)
        if read is None:
            result.dynamic_sites.append(f"{rel}:{first.line}")
            continue
        handler = f"{handler_class}.{_method_name(method)}"
        body = _request_type(method, fw)
        out += [
            Route(verb, join_path(prefix, path), handler, rel, first.line, body)
            for verb, paths in read
            for prefix in prefixes
            for path in paths
        ]
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


def _adapter(
    label: str,
) -> Callable[[Path, Scope, list[str], list[str]], AdapterResult]:
    fw = _FRAMEWORKS[label]

    def adapter(
        root: Path, scope: Scope, files: list[str], repo_files: list[str]
    ) -> AdapterResult:
        result = AdapterResult()
        parsed: list[tuple[str, Tree]] = []
        sources: dict[str, bytes] = {}
        for rel in ast.jvm_files(files):
            data = _read(root, rel)
            if data is None:
                result.dynamic_sites.append(f"{rel}:1")
                continue
            if not (fw.hint.search(data) or _META.search(data)):
                continue
            tree = _parse(rel, data)
            line = _error_line(tree)
            if line is not None:
                result.dynamic_sites.append(f"{rel}:{line}")
            parsed.append((rel, tree))
            sources[rel] = data
        composed = _composed(parsed, fw)
        routes: list[Route] = []
        app_paths: list[tuple[str, ast.Ann]] = []
        for rel, tree in parsed:
            result.dynamic_sites += _unfollowed_sites(rel, sources[rel], fw)
            for cls in ast.classes(tree.root_node):
                app_paths += [
                    (rel, a) for a in ast.annotations_of(cls) if a.name in fw.app_path
                ]
                routes += _scan_class(rel, cls, fw, composed, result)
        if fw.app_path:
            base = _application_prefix(app_paths, result)
            routes = [replace(r, path=join_path(base, r.path)) for r in routes]
        result.routes = routes
        result.dynamic_sites += config_sites(root, scope, repo_files, fw.keys)
        return result

    return adapter


ADAPTERS = {label: _adapter(label) for label in _FRAMEWORKS}
