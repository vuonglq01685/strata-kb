"""Request-type field reader for Java and Kotlin: the fields of a `@RequestBody`
/ `@Body` type when it is a plain class, record or Kotlin class declared in
the repo.

**Required.** Kotlin: a constructor property is required when its type is
non-null and it has no default. Java: a record component is required; a
class field only when it carries `@NotNull` / `@NotBlank` / `@NotEmpty` /
`@NonNull`. A class with a superclass, an interface, an enum or a Kotlin
class with body properties is not plain (its list would be incomplete), so
it reads as undeclared -- the same rule the TS reader follows.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors import _kotlin_parse, _ts
from strata_kb.codeingest.extractors._jvm_ast import (
    JVM_LANGS,
    Ann,
    annotations_of,
    class_name,
    classes,
    flatten,
)
from strata_kb.codeingest.extractors._routes_jsutil import (
    Field,
    _common_dirs,
    _lit,
    _read,
    _text,
)

if TYPE_CHECKING:
    from tree_sitter import Node

_REQUIRED = frozenset({"NotNull", "NotBlank", "NotEmpty", "NonNull", "Nonnull"})
_CONTAINERS = (
    r"List|Set|Collection|Iterable|Optional|Flux|Mono|Array|ArrayList|HashSet"
    r"|MutableList|MutableSet"
)
_WRAPPED = re.compile(rf"(?:\w+\.)*(?:{_CONTAINERS})<\s*(?:\?\s+extends\s+)?(.+)>")
_GENERIC = re.compile(r"^((?:\w+\.)*\w+)\s*<.*>$")


def element_type(name: str) -> str:
    """`List<Foo>` / `Foo[]` / `Foo?` / `a.b.Foo<T>` -> `Foo`."""
    name = name.strip()
    while True:
        wrapped = _WRAPPED.fullmatch(name)
        if wrapped:
            name = wrapped.group(1).strip()
        elif name.endswith(("[]", "?")):
            name = name[:-2] if name.endswith("[]") else name[:-1]
        else:
            break
    generic = _GENERIC.fullmatch(name)
    return (generic.group(1) if generic else name).rsplit(".", 1)[-1]


def _json_name(anns: list[Ann], default: str) -> str:
    for ann in anns:
        if ann.name == "JsonProperty":
            value = ann.arg("value", "")
            return (_lit(value) if value is not None else None) or default
    return default


def _java_fields(decl: Node) -> list[Field] | None:
    if decl.type == "record_declaration":
        listing = decl.child_by_field_name("parameters")
        out = []
        for comp in listing.named_children if listing is not None else []:
            name = _text(comp.child_by_field_name("name"))
            typ = _text(comp.child_by_field_name("type"))
            out.append((_json_name(annotations_of(comp), name), typ, True))
        return out
    if decl.type != "class_declaration" or decl.child_by_field_name("superclass"):
        return None
    body = decl.child_by_field_name("body")
    out = []
    for member in body.named_children if body is not None else []:
        if member.type != "field_declaration":
            continue
        mods = next((c for c in member.children if c.type == "modifiers"), None)
        if mods is not None and any(c.type == "static" for c in mods.children):
            continue
        anns = annotations_of(member)
        typ = _text(member.child_by_field_name("type"))
        required = any(a.name in _REQUIRED for a in anns)
        for declarator in member.children_by_field_name("declarator"):
            name = _text(declarator.child_by_field_name("name"))
            out.append((_json_name(anns, name), typ, required))
    return out


def _kotlin_fields(decl: Node) -> list[Field] | None:
    kids = decl.children
    if any(c.type in ("interface", "enum") for c in kids):
        return None
    if any(
        c.type == "delegation_specifier"
        and any(g.type == "constructor_invocation" for g in c.named_children)
        for c in kids
    ):
        return None
    ctor = next((c for c in kids if c.type == "primary_constructor"), None)
    body = next((c for c in kids if c.type == "class_body"), None)
    if ctor is None or any(c.type == "property_declaration" for c in flatten(body)):
        return None
    out = []
    for param in ctor.named_children:
        if param.type != "class_parameter" or not any(
            c.type == "binding_pattern_kind" for c in param.children
        ):
            continue
        parts = [c for c in param.named_children if c.type.endswith("type")]
        typ = _text(parts[-1] if parts else None) or "Any"
        default = any(c.type == "=" for c in param.children)
        name = _text(
            next(
                (c for c in param.named_children if c.type == "simple_identifier"), None
            )
        )
        out.append(
            (
                _json_name(annotations_of(param), name),
                typ,
                not typ.endswith("?") and not default,
            )
        )
    return out


# Source bytes read for the run in progress. `routes.py` passes the same
# `files` list to every call of a run, so list identity scopes the cache; a
# new run brings a new list and drops it.
_reads: tuple[list[str], dict[str, bytes | None]] | None = None


def _run_cache(files: list[str]) -> dict[str, bytes | None]:
    global _reads
    if _reads is None or _reads[0] is not files:
        _reads = (files, {})
    return _reads[1]


def declared_fields(
    root: Path, files: list[str], type_name: str, near: str
) -> list[Field] | None:
    """Fields of `type_name` when it is a plain class/record declared in the
    repo, else None. A declaration in `near` (the route's file) wins, then
    the closest directory (shortcut: imports are not followed -- upgrade if
    a repo hits two same-named types). Only a Java/Kotlin route reads
    Java/Kotlin types."""
    if _ts.language_for(near) not in JVM_LANGS:
        return None
    reads = _run_cache(files)

    def data_of(rel: str) -> bytes | None:
        if rel not in reads:
            reads[rel] = _read(root, rel)
        return reads[rel]

    type_name = element_type(type_name)
    pattern = re.compile(
        rb"\b(?:class|record|interface|enum)\s+"
        + re.escape(type_name.encode())
        + rb"\b"
    )
    candidates = []
    for rel in files:
        if _ts.language_for(rel) in JVM_LANGS:
            data = data_of(rel)
            if data is not None and pattern.search(data):
                candidates.append(rel)
    candidates.sort(key=lambda rel: (rel != near, -_common_dirs(rel, near), rel))
    for rel in candidates:
        data = data_of(rel)
        if data is None:
            continue
        for decl in classes(_kotlin_parse.parse(rel, data).root_node):
            if class_name(decl) == type_name:
                if _ts.language_for(rel) == "java":
                    return _java_fields(decl)
                return _kotlin_fields(decl)
    return None
