"""Django REST framework routers for the Django route adapter.

`router = DefaultRouter()` / `SimpleRouter()` with `router.register("p",
ViewSet)` expands to the standard routes the ViewSet provides:

- bases: `ModelViewSet` (all six actions), `ReadOnlyModelViewSet` (list,
  retrieve), the `*ModelMixin`s, `GenericViewSet` / `ViewSet` (none);
  repo-declared bases are followed;
- methods the class defines named `list`, `create`, `retrieve`, `update`,
  `partial_update`, `destroy`;
- `@action(detail=, methods=[...], url_path=)` routes;
- the lookup segment is `{pk}`, or `lookup_url_kwarg` / `lookup_field` when
  that is a string literal.

A ViewSet with a base this reader does not know, a non-literal prefix, a
non-literal `@action` argument or an unresolvable viewset is a site. A
`DefaultRouter` also lists its `APIRootView` at the router's own prefix; the
`.json` format-suffix variants it adds are not listed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors import _py_ast as ast

if TYPE_CHECKING:
    from tree_sitter import Node

__all__ = ["Router", "Routers", "Rt"]

_ROUTERS = {"DefaultRouter": True, "SimpleRouter": False}
_ACTIONS = {
    "list": ("GET", False),
    "create": ("POST", False),
    "retrieve": ("GET", True),
    "update": ("PUT", True),
    "partial_update": ("PATCH", True),
    "destroy": ("DELETE", True),
}
_VIEWSET_BASES: dict[str, frozenset[str]] = {
    "ModelViewSet": frozenset(_ACTIONS),
    "ReadOnlyModelViewSet": frozenset({"list", "retrieve"}),
    "GenericViewSet": frozenset(),
    "ViewSet": frozenset(),
    "ViewSetMixin": frozenset(),
    "GenericAPIView": frozenset(),
    "ListModelMixin": frozenset({"list"}),
    "CreateModelMixin": frozenset({"create"}),
    "RetrieveModelMixin": frozenset({"retrieve"}),
    "UpdateModelMixin": frozenset({"update", "partial_update"}),
    "DestroyModelMixin": frozenset({"destroy"}),
    "object": frozenset(),
}
_MAX_CLASSES = 12  # a viewset's own class plus the bases followed

_Extra = tuple[str, bool, list[str], str]  # name, detail, methods, url_path


@dataclass
class Rt:
    """One route of a URLconf: a path piece joined onto its parents'."""

    piece: str
    regex: bool
    view: str
    methods: tuple[str, ...]
    file: str
    line: int


@dataclass
class Router:
    default: bool
    file: str
    line: int
    regs: list[tuple[Node, Node | None, str, int]] = field(default_factory=list)
    expanded: bool = False


@dataclass
class _ViewSet:
    actions: set[str] = field(default_factory=set)
    extras: list[_Extra] = field(default_factory=list)
    lookup_field: str = ""
    lookup_kwarg: str = ""

    @property
    def lookup(self) -> str:
        return self.lookup_kwarg or self.lookup_field or "pk"


def _line(node: Node) -> int:
    return node.start_point[0] + 1


class Routers:
    """The DRF routers of a scope and their registrations."""

    def __init__(
        self,
        proj: ast.Project,
        mine: list[str],
        site: Callable[[str, Node | int], None],
    ):
        self.proj = proj
        self.mine = mine
        self.site = site
        self.routers: dict[tuple[str, int], Router] = {}

    def index(self) -> None:
        for rel in self.mine:
            info = self.proj.info(rel)
            if info is None or not (
                b".register(" in info.data or b"Router(" in info.data
            ):
                continue
            calls = ast.all_calls(info.tree)
            for call in calls:
                self._ctor(rel, call)
            for call in calls:
                self._register(rel, call)

    def _ctor(self, rel: str, call: Node) -> None:
        parts = ast.dotted(ast.callee(call)) or []
        parent = call.parent
        if (
            parts
            and parts[-1] in _ROUTERS
            and parent is not None
            and parent.type == "assignment"
        ):
            self.routers[(rel, call.id)] = Router(_ROUTERS[parts[-1]], rel, _line(call))

    def of(self, rel: str, node: Node | None) -> Router | None:
        """The router a name or attribute chain refers to."""
        ref = self.proj.chain(rel, node)
        if ref.kind != "assign" or ref.node is None:
            return None
        return self.routers.get((ref.file, ref.node.id))

    def _register(self, rel: str, call: Node) -> None:
        fn = ast.callee(call)
        if fn is None or fn.type != "attribute":
            return
        if ast.text(fn.child_by_field_name("attribute")) != "register":
            return
        router = self.of(rel, fn.child_by_field_name("object"))
        if router is None:  # `admin.site.register(Model)` and friends
            return
        args = ast.call_args(call)
        prefix = args.pos[0] if args.pos else args.kw.get("prefix")
        view = args.pos[1] if len(args.pos) > 1 else args.kw.get("viewset")
        if prefix is None or view is None or args.splat:
            self.site(rel, call)
            return
        router.regs.append((prefix, view, rel, _line(call)))

    def unexpanded(self) -> list[Router]:
        return [r for r in self.routers.values() if r.regs and not r.expanded]

    def urls(self, router: Router) -> list[Rt]:
        router.expanded = True
        out: list[Rt] = []
        if router.default:
            out.append(Rt("", False, "APIRootView", ("GET",), router.file, router.line))
        for prefix_node, view_node, rel, line in router.regs:
            prefix = ast.lit(prefix_node)
            ref = self.proj.chain(rel, view_node)
            info = self._viewset(ref) if ref.kind == "class" else None
            if prefix is None or info is None or ref.node is None:
                self.site(rel, line)
                continue
            cls = ast.text(ref.node.child_by_field_name("name"))
            out += self._routes(prefix.strip("/"), cls, info, rel, line)
        return out

    def _viewset(self, ref: ast.Ref) -> _ViewSet | None:
        found = _ViewSet()
        stack = [(ref.file, ref.node)]
        seen: set[int] = set()
        while stack:
            file, cls = stack.pop(0)
            if cls is None or cls.id in seen or len(seen) > _MAX_CLASSES:
                return None
            seen.add(cls.id)
            if not self._body(cls, found):
                return None
            bases = cls.child_by_field_name("superclasses")
            for base in bases.named_children if bases is not None else []:
                if base.type == "keyword_argument":
                    continue
                parts = ast.dotted(base)
                if not parts:
                    return None
                known = _VIEWSET_BASES.get(parts[-1])
                if known is not None:
                    found.actions |= known
                    continue
                sub = self.proj.chain(file, base)
                if sub.kind != "class":
                    return None  # a base from a package
                stack.append((sub.file, sub.node))
        return found

    def _body(self, cls: Node, found: _ViewSet) -> bool:
        """Read one class body into `found`; False when it is not readable."""
        body = cls.child_by_field_name("body")
        for stmt in body.named_children if body is not None else []:
            inner = stmt
            if stmt.type == "decorated_definition":
                inner = stmt.child_by_field_name("definition") or stmt
            if inner.type == "function_definition":
                name = ast.func_name(inner)
                if name in _ACTIONS:
                    found.actions.add(name)
                extra = _extra_action(inner)
                if extra is False:
                    return False
                if isinstance(extra, tuple):
                    found.extras.append(extra)
            elif inner.type == "assignment":
                key = ast.text(inner.child_by_field_name("left"))
                if key not in ("lookup_url_kwarg", "lookup_field"):
                    continue
                value = ast.lit(inner.child_by_field_name("right"))
                if value is None:
                    return False
                if key == "lookup_url_kwarg":
                    found.lookup_kwarg = found.lookup_kwarg or value
                else:
                    found.lookup_field = found.lookup_field or value
        return True

    @staticmethod
    def _routes(prefix: str, cls: str, info: _ViewSet, rel: str, line: int) -> list[Rt]:
        out: list[Rt] = []
        detail_head = f"{prefix}/{{{info.lookup}}}"
        for name in sorted(info.actions):
            method, detail = _ACTIONS[name]
            out.append(
                Rt(
                    detail_head if detail else prefix,
                    False,
                    f"{cls}.{name}",
                    (method,),
                    rel,
                    line,
                )
            )
        for name, detail, methods, url_path in info.extras:
            head = detail_head if detail else prefix
            out.append(
                Rt(
                    f"{head}/{url_path}",
                    False,
                    f"{cls}.{name}",
                    tuple(methods),
                    rel,
                    line,
                )
            )
        return out


def _extra_action(func: Node) -> _Extra | None | bool:
    """The `@action` of a method: the route, None when it has none, False
    when its arguments are not literals."""
    for expr, _ in ast.decorator_calls(func):
        if expr.type != "call":
            continue
        parts = ast.dotted(ast.callee(expr)) or []
        if not parts or parts[-1] != "action":
            continue
        args = ast.call_args(expr)
        detail = args.kw.get("detail") or (args.pos[0] if args.pos else None)
        methods = (
            ast.literal_strings(args.kw["methods"]) if "methods" in args.kw else ["get"]
        )
        url_path = (
            ast.lit(args.kw["url_path"])
            if "url_path" in args.kw
            else ast.func_name(func)
        )
        if (
            detail is None
            or detail.type not in ("true", "false")
            or not methods
            or url_path is None
            or args.splat
        ):
            return False
        return (
            ast.func_name(func),
            detail.type == "true",
            [m.upper() for m in methods],
            url_path,
        )
    return None
