"""Config options that move every served JVM route (servlet context path,
Quarkus `root-path`, Micronaut `context-path`).

The scanner lists paths as the annotations spell them, so a prefix set in
`application.properties` / `application.yml` makes each listed path wrong.
Every line that sets one is a `file:line` site (never applied, never
dropped). A value of `/` or empty changes nothing and is not a site.
"""

from __future__ import annotations

import re
from pathlib import Path

from strata_kb.codeingest.extractors._routes_jsutil import _read
from strata_kb.codeingest.extractors._scopes import Scope

_CONFIG_FILE = re.compile(
    r"(?:application|bootstrap)(?:[-_.][\w.-]+)?\.(?:properties|ya?ml)$"
)
_TEST_DIR = re.compile(r"(?:^|/)src/(?:test|integrationTest)/")
_PROPERTY = re.compile(r"^\s*([^\s#!=:][^\s=:]*)\s*[=:]\s*(.*?)\s*$")
_YAML_KEY = re.compile(
    r"^(\s*)(?:\"([^\"]+)\"|'([^']+)'|([^\s#:\-][^:#]*?))\s*:(?:\s+(.*))?$"
)
_IDLE = frozenset({"", "/", '"/"', "'/'", '""', "''"})

# Keys are compared lower-case with `-` and `_` removed (relaxed binding).
SPRING_KEYS = frozenset(
    {
        "server.servlet.contextpath",
        "spring.mvc.servlet.path",
        "spring.webflux.basepath",
        "spring.jersey.applicationpath",
        "spring.data.rest.basepath",
    }
)
QUARKUS_KEYS = frozenset(
    {
        "quarkus.http.rootpath",
        "quarkus.rest.path",
        "quarkus.resteasy.path",
        "quarkus.resteasyreactive.path",
    }
)
MICRONAUT_KEYS = frozenset({"micronaut.server.contextpath"})


def _normal(key: str) -> str:
    key = re.sub(r"^%[\w-]+\.", "", key)  # Quarkus profile prefix
    return key.lower().replace("-", "").replace("_", "")


def _yaml_keys(text: str) -> list[tuple[int, str, str]]:
    """(line, dotted key, value) for every `key: value` line; a `---`
    document separator resets the nesting."""
    out: list[tuple[int, str, str]] = []
    stack: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if line.startswith("---"):
            stack = []
            continue
        found = _YAML_KEY.match(line)
        if not found or line.lstrip().startswith("#"):
            continue
        indent = len(found.group(1))
        key = found.group(2) or found.group(3) or found.group(4)
        value = (found.group(5) or "").split(" #")[0].strip()
        while stack and stack[-1][0] >= indent:
            stack.pop()
        stack.append((indent, key))
        # a profile level (`"%dev":`) is not part of the property name
        dotted = ".".join(k for _i, k in stack if not k.startswith("%"))
        out.append((number, dotted, value))
    return out


def config_sites(
    root: Path, scope: Scope, repo_files: list[str], keys: frozenset[str]
) -> list[str]:
    """`file:line` of each `keys` property the scope's config files set."""
    sites: list[str] = []
    prefix = "" if scope.path == "." else scope.path + "/"
    for rel in repo_files:
        name = rel.rsplit("/", 1)[-1]
        if (
            not rel.startswith(prefix)
            or not _CONFIG_FILE.fullmatch(name)
            or _TEST_DIR.search(rel)
        ):
            continue
        data = _read(root, rel)
        if data is None:
            continue
        text = data.decode("utf-8", errors="replace")
        if name.endswith(".properties"):
            found = [
                (n, m.group(1), m.group(2))
                for n, line in enumerate(text.splitlines(), start=1)
                if (m := _PROPERTY.match(line))
            ]
        else:
            found = _yaml_keys(text)
        sites += [
            f"{rel}:{n}"
            for n, key, value in found
            if _normal(key) in keys and value not in _IDLE
        ]
    return sites
