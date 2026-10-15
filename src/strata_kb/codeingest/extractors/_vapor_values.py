"""Values, scopes and syntax unrolling of the Vapor route evaluator
(`_routes_swift.Vapor`): what an expression can evaluate to (a router with a
known or unknown prefix, a provably non-router, a collection instance, a type,
a literal array or string), the lexical environment, the call-chain unroller
and the scan for names the evaluator must not trust."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from strata_kb.codeingest.extractors._routes_jsutil import _text
from strata_kb.codeingest.extractors._swift_ast import Call, call_of, kids

if TYPE_CHECKING:
    from tree_sitter import Node

VERBS = frozenset({"get", "post", "put", "patch", "delete"})
HTTP_METHODS = frozenset(
    {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE", "CONNECT"}
)
ROUTER_TYPES = frozenset({"Application", "RoutesBuilder", "Routes", "Router"})
# Types that are provably not routers: standard, Foundation and Vapor value
# types that share verb names (`Client.get`, `Parameters.get`, `Environment.get`).
PLAIN_TYPES = frozenset(
    {
        "URLSession", "URLRequest", "URL", "URI", "Data", "Dictionary", "Array", "Set",
        "String", "Int", "Bool", "Double", "Date", "JSONDecoder", "JSONEncoder",
        "FileManager", "UserDefaults", "ProcessInfo", "DispatchQueue", "NotificationCenter",
        "Logger", "NSCache", "Process", "Optional", "Request", "Response", "Client",
        "ClientRequest", "ClientResponse", "Environment", "Parameters", "HTTPHeaders",
        "Session", "Database", "WebSocket", "Task", "NIOThreadPool", "EventLoop",
    }
)  # fmt: skip
# `app.<name>` members that are services, not routers.
PLAIN_MEMBERS = frozenset(
    {
        "client", "http", "logger", "environment", "directory", "views", "middleware",
        "migrations", "databases", "queues", "sessions", "passwords", "caches", "cache",
        "storage", "lifecycle", "jwt", "fluent", "leaf", "redis", "console", "threadPool",
        "eventLoopGroup", "commands", "running", "locks", "fileio", "validators",
        "server", "servers", "responder", "migrator",
    }
)  # fmt: skip
LABELS = frozenset({"use", "body", "maxFrameSize", "shouldUpgrade", "onUpgrade"})
BENIGN_CALLS = frozenset(
    {
        "print", "debugPrint", "dump", "assert", "precondition", "fatalError", "run",
        "execute", "start", "startup", "shutdown", "asyncShutdown", "boot", "forEach",
        "map", "append", "insert", "contains", "isEmpty", "count", "min", "max",
    }
)  # fmt: skip
TRANSPARENT = frozenset({"try_expression", "await_expression"})
STRINGS = frozenset(
    {"line_string_literal", "multi_line_string_literal", "raw_string_literal"}
)
LITERALS = frozenset(
    {
        "integer_literal", "real_literal", "boolean_literal", "nil", "hex_literal",
        "oct_literal", "bin_literal", "key_path_expression", "regex_literal",
    }
)  # fmt: skip
METHOD = re.compile(r"^(?:HTTPMethod)?\.([A-Z]+)$")
HANDLER = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$")
UNSAFE_PATH = re.compile(r"[\s\x00-\x1f\\]")


@dataclass(frozen=True)
class Router:
    prefix: str | None  # None: a router whose prefix is not known


@dataclass(frozen=True)
class Plain:
    """Provably not a router (a `Request`, a client, a standard type)."""

    type: str = ""


@dataclass(frozen=True)
class Coll:
    name: str  # an instance of a RouteCollection type


@dataclass(frozen=True)
class TypeRef:
    name: str


@dataclass(frozen=True)
class Items:
    values: tuple


@dataclass(frozen=True)
class Text:
    value: str


class _Marker:
    def __init__(self, label: str):
        self.label = label


SELF = _Marker("self")
MADE = _Marker("made")  # the result of a call we do not model
MW = _Marker("middleware")  # a value that is provably middleware

Value = Router | Plain | Coll | TypeRef | Items | Text | _Marker | None


class Env:
    __slots__ = ("parent", "vars")

    def __init__(self, parent: Env | None = None):
        self.vars: dict[str, Value] = {}
        self.parent = parent

    def lookup(self, name: str) -> tuple[bool, Value]:
        env: Env | None = self
        while env is not None:
            if name in env.vars:
                return True, env.vars[name]
            env = env.parent
        return False, None

    def bind(self, name: str, value: Value) -> None:
        # declared twice in one scope (also across `#if` branches): disagreeing
        self.vars[name] = None if name in self.vars else value


@dataclass(frozen=True)
class Frame:
    file: str
    self_type: str
    env: Env
    unsafe: frozenset[str]
    depth: int
    stack: frozenset[int]
    me: Router | None = None  # `self` inside an extension of a router type


EMPTY_CALL = Call([], [])


@dataclass(frozen=True)
class Step:
    kind: str  # "m" member | "c" call
    name: str
    node: Node
    call: Call = EMPTY_CALL  # arguments of a call step


def line(node: Node) -> int:
    return node.start_point[0] + 1


def where(node: Node) -> int:
    """Line of the `.name` part of a member access, else of the node."""
    tail = node.child_by_field_name("suffix")
    return line(tail if tail is not None else node)


def unroll(node: Node) -> tuple[Node, list[Step]]:
    steps: list[Step] = []
    while True:
        kind = node.type
        if kind == "call_expression":
            parts = kids(node)
            suffix = next((c for c in parts if c.type == "call_suffix"), None)
            if suffix is None or len(parts) < 2:
                break
            steps.append(Step("c", "", node, call_of(suffix)))
            node = parts[0]
        elif kind == "navigation_expression":
            target = node.child_by_field_name("target")
            tail = node.child_by_field_name("suffix")
            word = tail.child_by_field_name("suffix") if tail is not None else None
            if target is None or word is None:
                break
            steps.append(Step("m", _text(word), node))
            node = target
        elif kind in TRANSPARENT:
            inner = node.child_by_field_name("expr")
            if inner is None:
                break
            node = inner
        elif kind == "postfix_expression":
            inner = node.child_by_field_name("target")
            if inner is None:
                break
            node = inner
        elif kind == "tuple_expression" and len(kids(node)) == 1:
            node = kids(node)[0]
        else:
            break
    steps.reverse()
    return node, steps


def unsafe_names(root: Node) -> set[str]:
    """Names this subtree rebinds or reassigns: `x = ..`, `&x`, and every
    pattern binder that is not a plain `let` / `var` (if-let, for, switch,
    catch). The evaluator knows nothing about such a name."""
    names: set[str] = set()
    stack = [root]
    while stack:
        node = stack.pop()
        kind = node.type
        if kind == "assignment":
            target = node.child_by_field_name("target")
            word = (
                next((c for c in kids(target) if c.type == "simple_identifier"), None)
                if target is not None
                else None
            )
            if word is not None:
                names.add(_text(word))
        elif kind == "prefix_expression":
            spelled = _text(node)
            if spelled.startswith("&"):
                names.add(spelled[1:].strip().split(".")[0])
        elif kind == "pattern":
            parent = node.parent
            # a `for` variable is scoped by `for_loop` itself
            if parent is None or parent.type not in (
                "property_declaration",
                "for_statement",
            ):
                inner = [node]
                while inner:
                    current = inner.pop()
                    if current.type == "simple_identifier":
                        names.add(_text(current))
                    inner.extend(current.children)
        else:
            names.update(
                _text(c) for c in node.children_by_field_name("bound_identifier")
            )
        stack.extend(node.children)
    return names


# Middleware is dropped from a `grouped(..)` argument list only when provable:
# an in-repo type conforming to one of these protocols, a Vapor-provided
# middleware type, or a call of a known factory (`User.authenticator()`).
MIDDLEWARE_PROTOCOLS = frozenset(
    {
        "Middleware", "AsyncMiddleware", "Authenticator", "AsyncAuthenticator",
        "BearerAuthenticator", "AsyncBearerAuthenticator", "BasicAuthenticator",
        "AsyncBasicAuthenticator", "CredentialsAuthenticator",
        "AsyncCredentialsAuthenticator", "SessionAuthenticator",
        "AsyncSessionAuthenticator", "RequestAuthenticator",
        "AsyncRequestAuthenticator", "ClientMiddleware",
    }
)  # fmt: skip
MIDDLEWARE_TYPES = frozenset(
    {
        "FileMiddleware", "CORSMiddleware", "ErrorMiddleware", "SessionsMiddleware",
        "RouteLoggingMiddleware", "DefaultHeadersMiddleware", "RateLimitMiddleware",
    }
)  # fmt: skip
MIDDLEWARE_FACTORIES = frozenset(
    {
        "authenticator", "credentialsAuthenticator", "sessionAuthenticator",
        "guardMiddleware", "redirectMiddleware", "asyncRedirectMiddleware",
        "middleware", "asyncMiddleware",
    }
)  # fmt: skip
# Supertypes that say nothing about routing; any other supertype that is not
# declared in the repo makes a type unknown (it may be a router builder).
KNOWN_SUPERTYPES = frozenset(
    {
        "Content", "Codable", "Decodable", "Encodable", "Model", "Fields", "Sendable",
        "Error", "AbortError", "DebuggableError", "Equatable", "Hashable", "Comparable",
        "Identifiable", "CustomStringConvertible", "CaseIterable", "RawRepresentable",
        "Migration", "AsyncMigration", "Command", "AsyncCommand", "LifecycleHandler",
        "AsyncLifecycleHandler", "StorageKey", "AnyObject", "Authenticatable",
        "ModelAuthenticatable", "ModelTokenAuthenticatable", "ModelSessionAuthenticatable",
        "ModelCredentialsAuthenticatable", "JWTPayload", "Validatable", "Job", "AsyncJob",
        "RouteCollection", "ResponseEncodable", "AsyncResponseEncodable",
        "RequestDecodable", "AsyncRequestDecodable", "String", "Int", "UInt8",
        "NSObject", "Reflectable", "Parameter", "Authorizable",
    }
)  # fmt: skip
