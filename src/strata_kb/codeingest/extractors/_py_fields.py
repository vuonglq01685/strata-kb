"""Request-type reader for Python: which parameter of a FastAPI handler is
the request body, and the fields of a Pydantic (or SQLModel) class declared
in the repo.

**Body parameter.** The first parameter whose annotation (after `Annotated`,
`Optional`, `| None`) names a model class declared in the repo and that is not
marked as another source (`Query`, `Header`, `Cookie`, `Path`, `Form`, `File`,
`Depends`, `Security`). A parameter marked `Body(...)` with a type outside the
repo is reported by its annotation text (its fields read as outside the repo).

**Fields.** Annotated class attributes, bases included. Required = no default
(`= ...` and a bare `Field(...)`/`Field(min_length=1)` have none). A name
starting with `_`, `ClassVar`, `model_config`, `Relationship(...)` and
`PrivateAttr(...)` are not fields. `Field(alias="x")` renames. A base that is
neither `BaseModel`/`SQLModel` nor a model class in the repo (a mixin from a
package, a `TypedDict`, a dataclass) makes the list incomplete, so the type
reads as declared outside the repo -- the rule the other readers follow.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors import _py_ast as ast
from strata_kb.codeingest.extractors import _ts
from strata_kb.codeingest.extractors._routes_jsutil import (
    Field,
    _common_dirs,
    _read,
    _walk,
)

if TYPE_CHECKING:
    from tree_sitter import Node

_ROOTS = frozenset({"BaseModel", "SQLModel"})
_IGNORED_BASES = frozenset({"Generic", "ABC", "object", "Protocol"})
_NON_BODY = frozenset(
    {"Query", "Header", "Cookie", "Path", "Form", "File", "Depends", "Security"}
)
_WRAPPERS = frozenset(
    {
        "List", "list", "Sequence", "Set", "set", "FrozenSet", "frozenset",
        "Iterable", "Tuple", "tuple", "Union", "Optional", "Annotated",
    }
)  # fmt: skip
_CLASS = re.compile(rb"^[ \t]*class[ \t]+(\w+)", re.MULTILINE)
_MAX_BASES = 8

# (root, rel) -> {class name: node}, parsed on demand for one routes run;
# `routes.py` clears it when the run ends.
_CLASSES: dict[tuple[str, str], dict[str, Node]] = {}
_INDEX: dict[tuple[str, int], dict[str, list[str]]] = {}


def clear_cache() -> None:
    _CLASSES.clear()
    _INDEX.clear()


def _index(root: Path, files: list[str]) -> dict[str, list[str]]:
    key = (str(root), id(files))
    if key not in _INDEX:
        found: dict[str, list[str]] = {}
        for rel in ast.product_files(files):
            data = _read(root, rel)
            if data is None:
                continue
            for match in _CLASS.finditer(data):
                found.setdefault(match.group(1).decode(), []).append(rel)
        _INDEX[key] = found
    return _INDEX[key]


def _classes(root: Path, rel: str) -> dict[str, Node]:
    key = (str(root), rel)
    if key not in _CLASSES:
        data = _read(root, rel)
        out: dict[str, Node] = {}
        if data is not None:
            for node in _walk(_ts.parse(ast.LANG, data).root_node):
                if node.type == "class_definition":
                    out.setdefault(ast.text(node.child_by_field_name("name")), node)
        _CLASSES[key] = out
    return _CLASSES[key]


def _find(
    root: Path, files: list[str], name: str, near: str
) -> tuple[str, Node] | None:
    ordered = sorted(
        _index(root, files).get(name, []),
        key=lambda rel: (rel != near, -_common_dirs(rel, near), rel),
    )
    for rel in ordered:
        node = _classes(root, rel).get(name)
        if node is not None:
            return rel, node
    return None


# -- annotations --------------------------------------------------------------


def _generic(node: Node) -> tuple[str, list[Node]] | None:
    """`Name[a, b]` as (Name, [a, b]) in annotation or expression position."""
    if node.type == "generic_type":
        head = node.named_children[0] if node.named_children else None
        params = next((c for c in node.children if c.type == "type_parameter"), None)
        args = list(params.named_children) if params is not None else []
    elif node.type == "subscript":
        head = node.child_by_field_name("value")
        args = node.children_by_field_name("subscript")
    else:
        return None
    parts = ast.dotted(head)
    return (parts[-1], args) if parts else None


def _is_none(node: Node | None) -> bool:
    node = ast.unwrap(node)
    return node is not None and node.type == "none"


def _peel(node: Node | None) -> Node | None:
    """Strip `Annotated[...]`, `Optional[...]`, `X | None`, `Union[X, None]`."""
    node = ast.unwrap(node)
    while node is not None:
        generic = _generic(node)
        if generic is not None and generic[0] == "Annotated" and generic[1]:
            node = ast.unwrap(generic[1][0])
        elif generic is not None and generic[0] in ("Optional", "Union"):
            rest = [a for a in generic[1] if not _is_none(a)]
            if len(rest) != 1:
                return node
            node = ast.unwrap(rest[0])
        elif (
            node.type == "binary_operator"
            and ast.text(node.child_by_field_name("operator")) == "|"
        ):
            sides = [
                node.child_by_field_name("left"),
                node.child_by_field_name("right"),
            ]
            rest = [s for s in sides if not _is_none(s)]
            if len(rest) != 1:
                return node
            node = ast.unwrap(rest[0])
        else:
            return node
    return node


def _element(node: Node | None) -> str:
    """Class name an annotation boils down to (`List[Foo]` -> Foo)."""
    node = _peel(node)
    while node is not None:
        generic = _generic(node)
        if generic is None or generic[0] not in _WRAPPERS or not generic[1]:
            break
        node = _peel(generic[1][0])
    if node is None:
        return ""
    if node.type == "string":
        return (ast.lit(node) or "").split(".")[-1].strip()
    parts = ast.dotted(node)
    return parts[-1] if parts else ""


# -- fields -------------------------------------------------------------------


def _field_call(value: Node | None) -> Node | None:
    if value is not None and value.type == "call":
        parts = ast.dotted(ast.callee(value))
        if parts and parts[-1] == "Field":
            return value
    return None


def _own_fields(cls: Node) -> list[Field]:
    body = cls.child_by_field_name("body")
    out: list[Field] = []
    for stmt in body.named_children if body is not None else []:
        if stmt.type != "assignment":
            continue
        left = stmt.child_by_field_name("left")
        ann = stmt.child_by_field_name("type")
        value = stmt.child_by_field_name("right")
        if left is None or left.type != "identifier" or ann is None:
            continue
        name = ast.text(left)
        kind = ast.text(ann)
        if (
            name.startswith("_")
            or name == "model_config"
            or kind.startswith(("ClassVar", "typing.ClassVar"))
        ):
            continue
        if value is not None and value.type == "call":
            callee = (ast.dotted(ast.callee(value)) or [""])[-1]
            if callee in ("Relationship", "PrivateAttr"):
                continue
        required = value is None
        field_call = _field_call(value)
        if field_call is not None:
            args = ast.call_args(field_call)
            first = args.pos[0] if args.pos else None
            has_default = (
                (first is not None and first.type != "ellipsis")
                or "default" in args.kw
                or "default_factory" in args.kw
            )
            required = not has_default
            alias = ast.lit(args.kw.get("alias") or args.kw.get("validation_alias"))
            name = alias or name
        out.append((name, kind, required))
    return out


def _model_fields(
    root: Path, files: list[str], rel: str, cls: Node, seen: frozenset[int], depth: int
) -> list[Field] | None:
    if depth > _MAX_BASES or cls.id in seen:
        return None
    bases = cls.child_by_field_name("superclasses")
    inherited: list[Field] = []
    is_model = False
    for base in bases.named_children if bases is not None else []:
        if base.type == "keyword_argument":
            continue  # `table=True`, `metaclass=...`
        generic = _generic(base)
        parts = ast.dotted(base) or ([generic[0]] if generic else [])
        name = parts[-1] if parts else ""
        if name in _ROOTS:
            is_model = True
        elif name in _IGNORED_BASES:
            continue
        else:
            found = _find(root, files, name, rel) if name else None
            if found is None:
                return None  # a base from a package: fields unknown
            more = _model_fields(
                root, files, found[0], found[1], seen | {cls.id}, depth + 1
            )
            if more is None:
                return None
            inherited += more
            is_model = True
    if not is_model:
        return None
    merged: dict[str, Field] = {f[0]: f for f in inherited}
    for own in _own_fields(cls):
        merged[own[0]] = own
    return list(merged.values())


def _plain_name(type_name: str) -> str:
    """`List[a.Foo]` / `Optional["Foo"]` / `Foo` -> `Foo`."""
    idents = re.findall(r"[A-Za-z_][\w.]*", type_name)
    keep = [i for i in idents if i not in _WRAPPERS and i != "None"]
    return keep[0].split(".")[-1] if keep else ""


def declared_fields(
    root: Path, files: list[str], type_name: str, near: str
) -> list[Field] | None:
    """Fields of a Pydantic/SQLModel class declared in the repo, else None.
    A declaration in `near` wins, then the closest directory (shortcut:
    imports are not followed -- upgrade if a repo has two same-named
    models). Only a Python route reads Python types."""
    if not near.endswith(".py"):
        return None
    name = _plain_name(type_name)
    found = _find(root, files, name, near)
    if found is None:
        return None
    return _model_fields(root, files, found[0], found[1], frozenset(), 0)


def is_model(root: Path, files: list[str], name: str, near: str) -> bool:
    return bool(name) and declared_fields(root, files, name, near) is not None


# -- request parameter ----------------------------------------------------------


def _marker(node: Node | None) -> str:
    """Last name of a call (`Depends(...)` -> Depends), else ""."""
    node = ast.unwrap(node)
    if node is not None and node.type == "call":
        parts = ast.dotted(ast.callee(node))
        return parts[-1] if parts else ""
    return ""


def _annotated_markers(ann: Node | None) -> set[str]:
    node = ast.unwrap(ann)
    found: set[str] = set()
    while node is not None:
        generic = _generic(node)
        if generic is None:
            break
        if generic[0] == "Annotated":
            found |= {_marker(a) for a in generic[1][1:]}
        nxt = generic[1][0] if generic[1] else None
        node = ast.unwrap(nxt)
    return found


def body_type(root: Path, files: list[str], func: Node, near: str) -> str:
    """Request-body type name of a FastAPI handler, or ""."""
    params = func.child_by_field_name("parameters")
    for param in params.named_children if params is not None else []:
        if param.type not in ("typed_parameter", "typed_default_parameter"):
            continue
        ann = param.child_by_field_name("type")
        markers = _annotated_markers(ann) | {
            _marker(param.child_by_field_name("value"))
        }
        if markers & _NON_BODY:
            continue
        peeled = _peel(ann)
        name = _element(ann)
        if is_model(root, files, name, near):
            return ast.text(peeled)
        if "Body" in markers and peeled is not None:
            return ast.text(peeled)
    return ""
