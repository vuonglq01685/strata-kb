"""Which C# projects are test projects, told from MSBuild files only.

A project is a test project when it references a test framework
(`Microsoft.NET.Test.Sdk`, `xunit*`, `NUnit*`, `MSTest*`) or sets
`<IsTestProject>true`, in its own `.csproj` or in the nearest
`Directory.Build.props` / `Directory.Packages.props` above it (MSBuild
imports the nearest one; an `Import` of the next one up is followed one hop).
Names of folders and files never decide: `Features/Tests/` is product code.

Conditions in a props file are evaluated against the project, in the simple
forms only: none (always), `$(MSBuildProjectName).EndsWith|StartsWith|Contains
('x')` (also `$(MSBuildProjectName.EndsWith('x'))`), `'$(MSBuildProjectName)'
== 'x'`, and `'$(IsTestProject)' == 'true'` (true only when the `.csproj`
itself sets `IsTestProject`). Any other condition is not evaluated and counts
as false. A `.csproj`'s own references count whatever their condition.
"""

from __future__ import annotations

import posixpath
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from xml.etree.ElementTree import Element

_FRAMEWORK = re.compile(
    r"(?:Microsoft\.NET\.Test\.Sdk|xunit|NUnit|MSTest)", re.IGNORECASE
)
_TEXT_FALLBACK = re.compile(
    r"<(?:Global)?PackageReference\s[^>]*?Include\s*=\s*\"(?:Microsoft\.NET\.Test\.Sdk"
    r"|xunit|NUnit|MSTest)[^\"]*\"|<IsTestProject>\s*true",
    re.IGNORECASE,
)
_NAME_METHOD = re.compile(
    r"^\$\(MSBuildProjectName(?:\)\.|\.)(EndsWith|StartsWith|Contains)\('([^']*)'\)\)?$"
)
_NAME_EQUALS = re.compile(r"^'\$\(MSBuildProjectName\)'\s*(==|!=)\s*'([^']*)'$")
_IS_TEST = re.compile(r"^'\$\(IsTestProject\)'\s*==\s*'true'$", re.IGNORECASE)
_ABOVE = re.compile(r"GetPathOfFileAbove\(\s*'([^']+)'")
PROPS = ("Directory.Build.props", "Directory.Packages.props")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _condition(text: str | None, name: str, is_test: bool) -> bool | None:
    """True/False when evaluable, None when the form is not one we evaluate."""
    if text is None or not text.strip():
        return True
    text = text.strip()
    found = _NAME_METHOD.match(text)
    if found:
        method, arg = found.group(1), found.group(2).lower()
        lowered = name.lower()
        return {
            "EndsWith": lowered.endswith,
            "StartsWith": lowered.startswith,
            "Contains": lambda a: a in lowered,
        }[method](arg)
    found = _NAME_EQUALS.match(text)
    if found:
        same = name.lower() == found.group(2).lower()
        return same if found.group(1) == "==" else not same
    if _IS_TEST.match(text):
        return is_test
    return None


def _sets_test_property(root: Element) -> bool:
    return any(
        _local(el.tag) == "IsTestProject" and (el.text or "").strip().lower() == "true"
        for el in root.iter()
    )


def _live_children(el: Element, name: str, is_test: bool, evaluate: bool):
    """The children of `el` that apply to the project. In a `<Choose>` the
    first true `<When>` wins; `<Otherwise>` applies only when every `<When>`
    was evaluated false (one we cannot evaluate leaves it unknown)."""
    if not evaluate:
        return list(el)
    if _local(el.tag) == "Choose":
        unknown = False
        for branch in el:
            if _local(branch.tag) == "Otherwise":
                return [] if unknown else [branch]
            verdict = _condition(branch.get("Condition"), name, is_test)
            if verdict:
                return [branch]
            unknown = unknown or verdict is None
        return []
    return [c for c in el if _condition(c.get("Condition"), name, is_test)]


def _marks_test(root: Element, name: str, is_test: bool, evaluate: bool) -> bool:
    # explicit stack: a hostile file nested thousands deep must not recurse
    stack = [root]
    while stack:
        for child in _live_children(stack.pop(), name, is_test, evaluate):
            tag = _local(child.tag)
            if tag in (
                "PackageReference",
                "GlobalPackageReference",
            ) and _FRAMEWORK.match(child.get("Include") or ""):
                return True
            if tag == "IsTestProject" and (child.text or "").strip().lower() == "true":
                return True
            stack.append(child)
    return False


def _parse(text: str) -> Element | None:
    try:
        return ET.fromstring(text.lstrip("﻿"))  # noqa: S314 -- local file, entities are not fetched
    except ET.ParseError:
        return None


def _nearest(here: str, by_dir: dict[str, str]) -> str | None:
    """The props file in `here` or the closest directory above it."""
    while True:
        if here in by_dir:
            return by_dir[here]
        if not here:
            return None
        here = here.rpartition("/")[0]


def _parent_hop(
    props: str, root: Element | None, index: dict[str, dict[str, str]]
) -> str | None:
    """The props file `props` imports from above (one hop), if it does."""
    if root is None:
        return None
    base = props.rpartition("/")[0]
    for el in root.iter():
        if _local(el.tag) != "Import":
            continue
        target = el.get("Project") or ""
        if "GetPathOfFileAbove" in target:
            named = _ABOVE.search(target)
            if not base or named is None or named.group(1) not in index:
                continue
            return _nearest(base.rpartition("/")[0], index[named.group(1)])
        if "$(" in target.replace("$(MSBuildThisFileDirectory)", ""):
            continue
        cleaned = target.replace("$(MSBuildThisFileDirectory)", "").replace("\\", "/")
        resolved = posixpath.normpath(posixpath.join(base, cleaned))
        if resolved == ".." or resolved.startswith("../"):
            continue  # points outside the repo
        if any(resolved in by_dir.values() for by_dir in index.values()):
            return resolved
    return None


def find(
    files: list[str],
    text: Callable[[str], str],
    warn: Callable[[str], None] = lambda _msg: None,
) -> frozenset[str]:
    """Directories ("" is the repo root) of the test projects among `files`.

    A project whose files cannot be evaluated is not a test project; `warn`
    says so (degrade, never abort the ingest)."""
    index: dict[str, dict[str, str]] = {n: {} for n in PROPS}
    for rel in files:
        name = rel.rpartition("/")[2]
        if name in index:
            index[name][rel.rpartition("/")[0]] = rel
    parsed: dict[str, Element | None] = {}

    def props_root(rel: str) -> Element | None:
        if rel not in parsed:
            parsed[rel] = _parse(text(rel))
        return parsed[rel]

    def is_test_project(rel: str) -> bool:
        name = rel.rpartition("/")[2].removesuffix(".csproj")
        own_text = text(rel)
        own = _parse(own_text)
        if own is None:
            return bool(_TEXT_FALLBACK.search(own_text))
        if _marks_test(own, name, True, evaluate=False):
            return True
        is_test = _sets_test_property(own)
        here = rel.rpartition("/")[0]
        for kind in PROPS:
            props = _nearest(here, index[kind])
            for rel_props in (
                props,
                _parent_hop(props, props_root(props), index) if props else None,
            ):
                root = props_root(rel_props) if rel_props else None
                if root is not None and _marks_test(root, name, is_test, evaluate=True):
                    return True
        return False

    found = set()
    for rel in files:
        if not rel.endswith(".csproj"):
            continue
        try:
            if is_test_project(rel):
                found.add(rel.rpartition("/")[0])
        except Exception as exc:  # noqa: BLE001 -- one hostile file must not abort the run
            warn(f"symbols: {rel} could not be evaluated as a test project: {exc!r}")
    return frozenset(found)
