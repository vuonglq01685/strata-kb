"""Symfony routing configuration read for the attribute loader.

`config/routes.yaml` and `config/routes/**/*.yaml` say which directories
and files are scanned for `#[Route]` attributes and under which `prefix`:

    controllers:
        resource: ../src/Controller/        # or {path:, namespace:}
        type: attribute                     # or annotation
        prefix: /api

Each such import is an `Import` (a directory, a file, a glob or a class).
Everything else the config can say is a site, never dropped: a route
declared in YAML (`path:`), an import of another type, a localised or
computed prefix, `exclude`/`methods` filters, a bundle import other than
the dev tooling of the framework skeleton, an unparsable file. XML route
files and PHP route configurators (`RoutingConfigurator`, `RouteCollection`)
are sites too.
"""

from __future__ import annotations

import fnmatch
import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from strata_kb.codeingest.extractors._routes_jsutil import _read
from strata_kb.codeingest.extractors._symfony_path import compiled

__all__ = ["Config", "Import", "read_config"]

_CONFIG_FILE = re.compile(r"^config/routes(?:\.(?:ya?ml|xml)|/.*\.(?:ya?ml|xml))$")
# dev tooling the framework skeleton imports; not the app's own routes
_TOOLING = frozenset(
    {"FrameworkBundle", "WebProfilerBundle", "TwigBundle", "DebugBundle", "MakerBundle"}
)
_CONTROLLERS_LOADER = "routing.controllers"
_LOGOUT_LOADER = "security.route_loader.logout"
_ATTRIBUTE_TYPES = frozenset({"attribute", "annotation"})
_FILTERS = ("exclude", "methods")
_CONFIGURATOR = re.compile(rb"RoutingConfigurator|RouteCollection")
_CONFIGURING = re.compile(
    rb"->\s*(?:add|import|collection)\s*\(|\bnew\s+Route\s*\(|\bnew\s+RouteCollection\b"
)
_COMMENT = re.compile(rb"^\s*(?://|#|/\*|\*)")
_MAX_NESTING = 8


@dataclass(frozen=True)
class Import:
    kind: str  # dir | file | glob | class | all
    target: str  # repo path, glob, or short class name
    prefix: str

    def covers(self, rel: str) -> bool:
        if self.kind == "all":
            return True
        if self.kind == "dir":
            return rel == self.target or rel.startswith(self.target + "/")
        if self.kind == "file":
            return rel == self.target
        if self.kind == "glob":
            return fnmatch.fnmatch(rel, self.target)
        return rel.rsplit("/", 1)[-1] == f"{self.target}.php"


@dataclass
class Config:
    imports: list[Import] = field(default_factory=list)
    sites: list[str] = field(default_factory=list)
    present: bool = False  # some routing config exists, whatever it holds

    def prefixes(self, rel: str) -> list[str]:
        return sorted({i.prefix for i in self.imports if i.covers(rel)})


def _scalar(node: yaml.Node | None) -> str | None:
    return node.value if isinstance(node, yaml.ScalarNode) else None


def _mapping(node: yaml.Node | None) -> dict[str, yaml.Node] | None:
    if not isinstance(node, yaml.MappingNode):
        return None
    out: dict[str, yaml.Node] = {}
    for key, value in node.value:
        name = _scalar(key)
        if name is not None:
            out[name] = value
    return out


def _entries(
    document: yaml.Node,
) -> list[tuple[yaml.Node, yaml.Node]]:
    """(key, value) entries of the file, looking inside `when@env` blocks."""
    out: list[tuple[yaml.Node, yaml.Node]] = []
    todo = [(document, 0)]
    while todo:
        node, depth = todo.pop()
        if not isinstance(node, yaml.MappingNode):
            continue
        for key, value in node.value:
            name = _scalar(key) or ""
            if name.startswith("when@") and depth < _MAX_NESTING:
                todo.append((value, depth + 1))
            else:
                out.append((key, value))
    return sorted(out, key=lambda kv: kv[0].start_mark.index)


def _resource(rel: str, fields: dict[str, yaml.Node]) -> tuple[str, str] | None:
    """(kind, target) of an attribute import's `resource`, None when it is
    not one this scan can place."""
    value = fields["resource"]
    text = _scalar(value)
    if text is None:
        text = _scalar((_mapping(value) or {}).get("path"))
    if text is None or text.startswith("@") or "vendor/" in text:
        return None
    if "\\" in text and "/" not in text:
        return "class", text.rsplit("\\", 1)[-1]
    base = posixpath.normpath(posixpath.join(posixpath.dirname(rel), text))
    if base.startswith(".."):
        return None
    if any(c in base for c in "*?["):
        return "glob", base
    return ("file" if base.endswith(".php") else "dir"), base


def _read_yaml(rel: str, text: str, config: Config) -> None:
    try:
        document = yaml.compose(text, Loader=yaml.SafeLoader)
    except (yaml.YAMLError, RecursionError, ValueError):
        config.sites.append(f"{rel}:1")
        return
    if document is None:
        return
    if not isinstance(document, yaml.MappingNode):
        config.sites.append(f"{rel}:1")
        return
    for key, value in _entries(document):
        line = f"{rel}:{key.start_mark.line + 1}"
        fields = _mapping(value)
        if fields is None or "resource" not in fields:
            config.sites.append(line)  # a route declared here (`path:`), or unknown
            continue
        text_resource = _scalar(fields["resource"]) or ""
        bundle = (
            text_resource[1:].split("/", 1)[0] if text_resource.startswith("@") else ""
        )
        if bundle in _TOOLING:
            continue
        kind = _scalar(fields.get("type"))
        prefix = _scalar(fields["prefix"]) if "prefix" in fields else ""
        if text_resource == _LOGOUT_LOADER and kind == "service":
            continue  # the security recipe's logout routes: no app route
        if text_resource == _CONTROLLERS_LOADER:
            # the Symfony 7.4+ skeleton: every controller of the app
            if prefix is None or any(name in fields for name in _FILTERS):
                config.sites.append(line)
            else:
                config.imports.append(Import("all", "", compiled(prefix)))
            continue
        placed = _resource(rel, fields)
        if (
            kind not in _ATTRIBUTE_TYPES
            or placed is None
            or prefix is None
            or any(name in fields for name in _FILTERS)
        ):
            config.sites.append(line)
            continue
        config.imports.append(Import(placed[0], placed[1], compiled(prefix)))


def configurator_sites(rel: str, data: bytes) -> list[str]:
    """Sites of a PHP route configurator: each `->add()` / `->import()` /
    `new Route()` line, else the line that names the configurator."""
    if not _CONFIGURATOR.search(data):
        return []
    lines = data.splitlines()
    found = {
        data.count(b"\n", 0, m.start()) + 1
        for m in _CONFIGURING.finditer(data)
        if not _COMMENT.match(lines[data.count(b"\n", 0, m.start())])
    }
    if not found:
        found = {
            n
            for n, line in enumerate(lines, 1)
            if _CONFIGURATOR.search(line)
            and not _COMMENT.match(line)
            and not line.lstrip().startswith(b"use ")
        }
    return [f"{rel}:{n}" for n in sorted(found)]


def read_config(root: Path, scope_path: str, repo_files: list[str]) -> Config:
    """Routing configuration of the Symfony app rooted at `scope_path`."""
    config = Config()
    prefix = "" if scope_path == "." else scope_path + "/"
    for rel in repo_files:
        if not rel.startswith(prefix) or not _CONFIG_FILE.match(rel[len(prefix) :]):
            continue
        config.present = True
        if rel.endswith(".xml"):
            config.sites.append(f"{rel}:1")
            continue
        data = _read(root, rel)
        if data is None:
            config.sites.append(f"{rel}:1")
        else:
            _read_yaml(rel, data.decode("utf-8", "replace"), config)
    return config
