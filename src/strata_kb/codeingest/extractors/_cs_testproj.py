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
PROPS = ("Directory.Build.props", "Directory.Packages.props")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _condition(text: str | None, name: str, is_test: bool) -> bool:
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
    return False


def _sets_test_property(root: Element) -> bool:
    return any(
        _local(el.tag) == "IsTestProject" and (el.text or "").strip().lower() == "true"
        for el in root.iter()
    )


def _marks_test(el: Element, name: str, is_test: bool, evaluate: bool) -> bool:
    for child in el:
        if evaluate and not _condition(child.get("Condition"), name, is_test):
            continue
        tag = _local(child.tag)
        if tag in ("PackageReference", "GlobalPackageReference") and _FRAMEWORK.match(
            child.get("Include") or ""
        ):
            return True
        if tag == "IsTestProject" and (child.text or "").strip().lower() == "true":
            return True
        if _marks_test(child, name, is_test, evaluate):
            return True
    return False


def _parse(text: str) -> Element | None:
    try:
        return ET.fromstring(text.lstrip("﻿"))  # noqa: S314 -- see import
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
    props: str, root: Element | None, name: str, index: dict[str, dict[str, str]]
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
            if not base:
                return None
            return _nearest(base.rpartition("/")[0], index[name])
        if "$(" in target.replace("$(MSBuildThisFileDirectory)", ""):
            continue
        cleaned = target.replace("$(MSBuildThisFileDirectory)", "").replace("\\", "/")
        resolved = posixpath.normpath(posixpath.join(base, cleaned)).lstrip("./")
        if resolved in index[name].values():
            return resolved
    return None


def find(files: list[str], text: Callable[[str], str]) -> frozenset[str]:
    """Directories ("" is the repo root) of the test projects among `files`."""
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

    found = set()
    for rel in files:
        if not rel.endswith(".csproj"):
            continue
        here = rel.rpartition("/")[0]
        name = rel.rpartition("/")[2].removesuffix(".csproj")
        own_text = text(rel)
        own = _parse(own_text)
        if own is None:
            if _TEXT_FALLBACK.search(own_text):
                found.add(here)
            continue
        if _marks_test(own, name, True, evaluate=False):
            found.add(here)
            continue
        is_test = _sets_test_property(own)
        for kind in PROPS:
            props = _nearest(here, index[kind])
            for rel_props in (
                props,
                _parent_hop(props, props_root(props), kind, index) if props else None,
            ):
                root = props_root(rel_props) if rel_props else None
                if root is not None and _marks_test(root, name, is_test, evaluate=True):
                    found.add(here)
    return frozenset(found)
