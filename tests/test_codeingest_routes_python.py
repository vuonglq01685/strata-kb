"""Python: FastAPI / Flask / Django route adapters, the Pydantic request-type
field reader, and the python exported symbols."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("tree_sitter_language_pack")

from strata_kb.codeingest.extractors import routes, symbols
from strata_kb.codeingest.types import CodeIngestOptions
from strata_kb.lintcore import table_rows


def write(root: Path, rel: str, text: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def fastapi(root: Path, app: str = ".") -> None:
    write(root, f"{app}/requirements.txt", "fastapi==0.110\nuvicorn\npydantic\n")


def flask(root: Path, app: str = ".") -> None:
    write(root, f"{app}/requirements.txt", "Flask==3.0\ngunicorn\n")


def django(root: Path, app: str = ".") -> None:
    write(root, f"{app}/requirements.txt", "Django==5.0\ndjangorestframework\n")


def opts(root: Path) -> CodeIngestOptions:
    return CodeIngestOptions(
        repo_root=root, kb_dir=root / ".kb", doc_id="d", repo_id="r"
    )


def run_routes(root: Path):
    return routes.RoutesExtractor().extract(root, opts(root))


def run_symbols(root: Path):
    return symbols.SymbolsExtractor().extract(root, opts(root))


def section(result, file: str):
    (found,) = [s for s in result.sections if s.title == file]
    return found


def rows_of(result, file: str) -> list[list[str]]:
    return table_rows(section(result, file).l2_md)[1:]


def row(result, scope: str = ".", framework: str | None = None):
    (found,) = [
        r
        for r in result.coverage
        if r.scope == scope and (framework is None or r.framework == framework)
    ]
    return found


def all_routes(result) -> list[tuple[str, str]]:
    return sorted(
        (r[0], r[1]) for s in result.sections for r in table_rows(s.l2_md)[1:]
    )


def test_fastapi_router_prefix_path_param_and_request_fields(tmp_path):
    fastapi(tmp_path)
    write(
        tmp_path,
        "app/main.py",
        """from fastapi import FastAPI
from app.routers import users

app = FastAPI()
app.include_router(users.router, prefix="/api")
""",
    )
    write(tmp_path, "app/routers/__init__.py", "")
    write(
        tmp_path,
        "app/routers/users.py",
        """from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/users", tags=["users"])


class UserCreate(BaseModel):
    name: str
    email: str = Field(...)
    age: Optional[int] = None
    nick: str | None = None
    role: str = "member"


@router.get("/{user_id}", response_model=dict)
async def read_user(user_id: int):
    return {}


@router.post("/", status_code=201)
def create_user(body: UserCreate):
    return body
""",
    )
    result = run_routes(tmp_path)
    file = "app/routers/users.py"
    assert rows_of(result, file) == [
        ["POST", "/api/users", "create_user", file, "UserCreate"],
        ["GET", "/api/users/{user_id}", "read_user", file, ""],
    ]
    l3 = section(result, file).l3_md
    assert "| name | str | yes |" in l3
    assert "| email | str | yes |" in l3
    assert "| age | Optional[int] | no |" in l3
    assert "| nick | str | None | no |" in l3 or "| nick | str \\| None | no |" in l3
    assert "| role | str | no |" in l3
    assert (row(result).status, row(result).detail) == ("complete", "")
    assert row(result).framework == "FastAPI"


def test_fastapi_dynamic_path_partial(tmp_path):
    fastapi(tmp_path)
    write(
        tmp_path,
        "main.py",
        """from fastapi import FastAPI
app = FastAPI()
BASE = "/x"

@app.get(BASE + "/a")
def a():
    return 1

@app.get("/ok")
def ok():
    return 1
""",
    )
    result = run_routes(tmp_path)
    assert all_routes(result) == [("GET", "/ok")]
    assert (row(result).status, row(result).detail) == ("partial", "main.py:5")


def test_flask_register_prefix_overrides_blueprint_prefix_default_get(tmp_path):
    flask(tmp_path)
    write(
        tmp_path,
        "app/__init__.py",
        """from flask import Flask


def create_app():
    app = Flask(__name__)
    from .users import bp as users_bp
    app.register_blueprint(users_bp, url_prefix="/v1")
    return app
""",
    )
    write(
        tmp_path,
        "app/users.py",
        """from flask import Blueprint

bp = Blueprint("users", __name__, url_prefix="/users")


@bp.route("/<int:uid>")
def show(uid):
    return ""


@bp.route("/", methods=["GET", "POST"])
def index():
    return ""
""",
    )
    result = run_routes(tmp_path)
    file = "app/users.py"
    assert rows_of(result, file) == [
        ["GET", "/v1", "index", file, ""],
        ["POST", "/v1", "index", file, ""],
        ["GET", "/v1/<int:uid>", "show", file, ""],
    ]
    assert (row(result).status, row(result).detail) == ("complete", "")


def test_flask_dynamic_path_partial(tmp_path):
    flask(tmp_path)
    write(
        tmp_path,
        "app.py",
        """from flask import Flask
app = Flask(__name__)
P = "/x"

@app.route(P)
def a():
    return ""
""",
    )
    result = run_routes(tmp_path)
    assert all_routes(result) == []
    assert (row(result).status, row(result).detail) == ("partial", "app.py:5")


def test_django_include_prefix_and_path_param(tmp_path):
    django(tmp_path)
    write(tmp_path, "proj/settings.py", 'ROOT_URLCONF = "proj.urls"\n')
    write(
        tmp_path,
        "proj/urls.py",
        """from django.urls import include, path

urlpatterns = [
    path("api/", include("shop.urls")),
]
""",
    )
    write(
        tmp_path,
        "shop/urls.py",
        """from django.urls import path
from . import views

urlpatterns = [
    path("items/<int:pk>/", views.item_detail, name="item"),
]
""",
    )
    result = run_routes(tmp_path)
    assert rows_of(result, "shop/urls.py") == [
        ["ANY", "/api/items/<int:pk>", "views.item_detail", "shop/urls.py", ""]
    ]
    assert (row(result).status, row(result).detail) == ("complete", "")


def test_python_symbols_all_literal_and_public_names(tmp_path):
    write(
        tmp_path,
        "pkg/__init__.py",
        '__all__ = ["a", "B"]\n\ndef a(): ...\nclass B: ...\nclass C: ...\n',
    )
    write(tmp_path, "pkg/mod.py", "def f(): ...\ndef _g(): ...\nX = 1\n_Y = 2\n")
    write(tmp_path, "requirements.txt", "flask\n")
    result = run_symbols(tmp_path)
    got = sorted(
        (r[0], r[1], r[2]) for s in result.sections for r in table_rows(s.l2_md)[1:]
    )
    assert got == [
        ("B", "class", "pkg/__init__.py"),
        ("X", "const", "pkg/mod.py"),
        ("a", "function", "pkg/__init__.py"),
        ("f", "function", "pkg/mod.py"),
    ]


def sites_of(result, scope: str = ".", framework: str | None = None) -> list[str]:
    detail = row(result, scope, framework).detail
    return detail.split("; ") if detail else []


# --- FastAPI ----------------------------------------------------------------


def test_fastapi_typical_app_reaches_complete(tmp_path):
    fastapi(tmp_path)
    write(
        tmp_path,
        "app/main.py",
        """from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routers import items, users
from .deps import get_current_user


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="Shop", version="1.0", lifespan=lifespan, docs_url="/docs")
app.add_middleware(CORSMiddleware, allow_origins=["*"])
app.include_router(users.router, prefix="/api/v1", tags=["users"])
app.include_router(items.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
async def startup():
    pass


@app.exception_handler(HTTPException)
async def handler(request, exc):
    return None


@app.get("/health", include_in_schema=False)
async def health():
    return {"ok": True}
""",
    )
    write(tmp_path, "app/routers/__init__.py", "")
    write(tmp_path, "app/deps.py", "def get_current_user():\n    return 1\n")
    write(
        tmp_path,
        "app/routers/users.py",
        """from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel

router = APIRouter(prefix="/users", tags=["users"], responses={404: {"d": "x"}})


class UserIn(BaseModel):
    name: str


@router.get("/", response_model=list[UserIn])
async def list_users(skip: int = 0, limit: int = Query(10, le=100)):
    return []


@router.get("/{user_id}", status_code=status.HTTP_200_OK)
async def get_user(user_id: int):
    return {}


@router.post("/", status_code=201)
async def create(user: UserIn):
    return user


@router.delete("/{user_id}", status_code=204)
async def delete(user_id: int):
    return None
""",
    )
    write(
        tmp_path,
        "app/routers/items.py",
        """from fastapi import APIRouter

router = APIRouter(prefix="/items")


@router.put("/{item_id}")
def put_item(item_id: int):
    return {}


@router.api_route("/bulk", methods=["POST", "PATCH"])
def bulk():
    return {}
""",
    )
    result = run_routes(tmp_path)
    assert (row(result).status, row(result).detail) == ("complete", "")
    assert all_routes(result) == [
        ("DELETE", "/api/v1/users/{user_id}"),
        ("GET", "/api/v1/users"),
        ("GET", "/api/v1/users/{user_id}"),
        ("GET", "/health"),
        ("PATCH", "/api/v1/items/bulk"),
        ("POST", "/api/v1/items/bulk"),
        ("POST", "/api/v1/users"),
        ("PUT", "/api/v1/items/{item_id}"),
    ]


def test_fastapi_nested_include_and_import_forms(tmp_path):
    fastapi(tmp_path)
    write(
        tmp_path,
        "src/app/main.py",
        """from fastapi import FastAPI
from app.api import api_router

app = FastAPI()
app.include_router(api_router, prefix="/v1")
""",
    )
    write(
        tmp_path,
        "src/app/api/__init__.py",
        """from fastapi import APIRouter
from .endpoints.users import router as users_router
from . import orders

api_router = APIRouter(prefix="/api")
api_router.include_router(users_router, prefix="/users")
api_router.include_router(orders.router)
""",
    )
    write(tmp_path, "src/app/api/endpoints/__init__.py", "")
    write(
        tmp_path,
        "src/app/api/endpoints/users.py",
        """from fastapi import APIRouter
router = APIRouter()

@router.get("/me")
def me():
    return 1
""",
    )
    write(
        tmp_path,
        "src/app/api/orders.py",
        """import fastapi
router = fastapi.APIRouter(prefix="/orders")

@router.get("/{oid}")
def one(oid: int):
    return 1
""",
    )
    result = run_routes(tmp_path)
    assert (row(result).status, row(result).detail) == ("complete", "")
    assert all_routes(result) == [
        ("GET", "/v1/api/orders/{oid}"),
        ("GET", "/v1/api/users/me"),
    ]


def test_fastapi_root_path_and_mount_sites(tmp_path):
    fastapi(tmp_path)
    write(
        tmp_path,
        "main.py",
        """from fastapi import FastAPI
from flask import Flask
from fastapi.middleware.wsgi import WSGIMiddleware

flask_app = Flask(__name__)
app = FastAPI(root_path="/proxy")
app.mount("/legacy", WSGIMiddleware(flask_app))

@app.get("/ok")
def ok():
    return 1
""",
    )
    result = run_routes(tmp_path)
    detail = sites_of(result)
    assert detail == ["main.py:6", "main.py:7"]
    assert row(result).status == "partial"


def test_fastapi_mount_sub_app_is_followed(tmp_path):
    fastapi(tmp_path)
    write(
        tmp_path,
        "main.py",
        """from fastapi import FastAPI
sub = FastAPI()
app = FastAPI()
app.mount("/sub", sub)

@sub.get("/x")
def x():
    return 1

@app.get("/y")
def y():
    return 1
""",
    )
    result = run_routes(tmp_path)
    assert all_routes(result) == [("GET", "/sub/x"), ("GET", "/y")]
    assert row(result).status == "complete"


def test_fastapi_add_api_route_and_prefix_dynamic(tmp_path):
    fastapi(tmp_path)
    write(
        tmp_path,
        "main.py",
        """from fastapi import FastAPI, APIRouter
from settings import settings

app = FastAPI()
router = APIRouter(prefix="/r")
router.add_api_route("/ping", lambda: 1, methods=["GET", "HEAD"])
app.include_router(router, prefix=settings.API_PREFIX)
""",
    )
    result = run_routes(tmp_path)
    assert all_routes(result) == [("GET", "/r/ping"), ("HEAD", "/r/ping")]
    assert sites_of(result) == ["main.py:7"]


def test_fastapi_unresolved_router_and_orphan_router_are_sites(tmp_path):
    fastapi(tmp_path)
    write(
        tmp_path,
        "main.py",
        """from fastapi import FastAPI
from lib import make_router

app = FastAPI()
app.include_router(make_router())
""",
    )
    write(
        tmp_path,
        "orphan.py",
        """from fastapi import APIRouter
router = APIRouter(prefix="/lost")

@router.get("/a")
def a():
    return 1
""",
    )
    result = run_routes(tmp_path)
    assert all_routes(result) == [("GET", "/lost/a")]
    assert sites_of(result) == ["main.py:5", "orphan.py:2"]


def test_fastapi_receiver_that_is_a_parameter_is_a_site(tmp_path):
    fastapi(tmp_path)
    write(
        tmp_path,
        "main.py",
        """from fastapi import FastAPI

def create_app() -> FastAPI:
    return FastAPI()

def register(app: FastAPI):
    @app.get("/x")
    def x():
        return 1

app = create_app()
register(app)
""",
    )
    result = run_routes(tmp_path)
    assert all_routes(result) == []
    # the unbound `FastAPI()` (line 4) and the route on the parameter (line 7)
    assert sites_of(result) == ["main.py:4", "main.py:7"]


def test_fastapi_websocket_and_syntax_error_are_sites(tmp_path):
    fastapi(tmp_path)
    write(
        tmp_path,
        "main.py",
        """from fastapi import FastAPI, WebSocket
app = FastAPI()

@app.websocket("/ws")
async def ws(socket: WebSocket):
    pass
""",
    )
    write(
        tmp_path,
        "broken.py",
        "from fastapi import APIRouter\nrouter = APIRouter()\n@router.get('/x'\ndef f(:\n",
    )
    result = run_routes(tmp_path)
    assert all_routes(result) == []
    assert row(result).status == "partial"
    assert "main.py:4" in sites_of(result)
    assert any(s.startswith("broken.py:") for s in sites_of(result))


def test_fastapi_web_module_with_no_routes_is_a_site_at_the_dependency(tmp_path):
    fastapi(tmp_path)
    write(
        tmp_path,
        "main.py",
        "from fastapi import FastAPI\napp = FastAPI()\napp.include_router(build())\n",
    )
    write(tmp_path, "only_lib/util.py", "x = 1\n")
    result = run_routes(tmp_path)
    assert row(result).status == "partial"

    lib = tmp_path / "lib"
    write(lib, "requirements.txt", "# libs\nfastapi\n")
    write(lib, "models.py", "class A:\n    pass\n")
    # fastapi is a dependency but nothing imports it: not a web module
    result = run_routes(tmp_path)
    assert row(result, "lib").status == "complete"

    write(lib, "views.py", "from fastapi import HTTPException\n")
    result = run_routes(tmp_path)
    assert (row(result, "lib").status, row(result, "lib").detail) == (
        "partial",
        "lib/requirements.txt:2",
    )


def test_python_test_detection_uses_pytest_names_not_substrings(tmp_path):
    fastapi(tmp_path)
    write(
        tmp_path,
        "app.py",
        "from fastapi import FastAPI\napp = FastAPI()\n",
    )
    for rel in (
        "contest.py",
        "latest_routes.py",
        "app_testing.py",
        "api/test.py",
        "attestation/views.py",
    ):
        write(
            tmp_path,
            rel,
            "from app import app\n\n"
            f"@app.get('/{rel.replace('.py', '').replace('/', '-')}')\n"
            "def h():\n    return 1\n",
        )
    for rel in (
        "tests/test_x.py",
        "test_y.py",
        "z_test.py",
        "conftest.py",
        "pkg/tests/h.py",
    ):
        write(
            tmp_path,
            rel,
            "from app import app\n\n@app.get('/skipped')\ndef h():\n    return 1\n",
        )
    result = run_routes(tmp_path)
    assert row(result).status == "complete"
    got = [p for _m, p in all_routes(result)]
    assert "/skipped" not in got
    assert sorted(got) == [
        "/api-test",
        "/app_testing",
        "/attestation-views",
        "/contest",
        "/latest_routes",
    ]


def test_fastapi_request_type_rules(tmp_path):
    fastapi(tmp_path)
    write(
        tmp_path,
        "main.py",
        """from typing import Annotated, Optional
from fastapi import Body, Depends, FastAPI, Query
from models import Filters, Item, Child, Foreign
from external import Outside

app = FastAPI()


@app.post("/a")
def a(item: Annotated[Item, Body()], q: str = ""):
    return 1


@app.post("/b")
def b(filters: Annotated[Filters, Query()], dep=Depends(lambda: 1)):
    return 1


@app.post("/c")
def c(items: list[Child]):
    return 1


@app.post("/d")
def d(x: Outside = Body(...)):
    return 1


@app.put("/e")
def e(item: Optional[Item] = None):
    return 1


@app.put("/f")
def f(item: Foreign):
    return 1
""",
    )
    write(
        tmp_path,
        "models.py",
        """from typing import ClassVar, Optional
from pydantic import BaseModel, Field


class Base(BaseModel):
    id: int
    _hidden: int = 0
    registry: ClassVar[int] = 0


class Item(Base):
    title: str = Field(..., alias="name")
    note: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    price: float = Field(gt=0)


class Child(BaseModel):
    ok: bool


class Filters(BaseModel):
    page: int = 1


class Foreign(SomethingExternal):
    z: int
""",
    )
    result = run_routes(tmp_path)
    got = {r[1]: r[4] for r in rows_of(result, "main.py")}
    assert got == {
        "/a": "Item",
        "/b": "",
        "/c": "list[Child]",
        "/d": "Outside",
        "/e": "Item",
        "/f": "",
    }
    l3 = section(result, "main.py").l3_md
    assert "| id | int | yes |" in l3
    assert "| name | str | yes |" in l3
    assert "| note | Optional[str] | no |" in l3
    assert "| tags | list[str] | no |" in l3
    assert "| price | float | yes |" in l3
    assert "_hidden" not in l3 and "registry" not in l3
    assert "| ok | bool | yes |" in l3
    assert "Outside: request type declared outside the repo" in l3


def test_python_request_readers_are_guarded_by_language(tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies": {"express": "4"}}')
    write(
        tmp_path,
        "server.js",
        "const express = require('express');\nconst app = express();\n"
        "app.post('/x', (req, res) => res.end());\n",
    )
    write(
        tmp_path,
        "models.py",
        "from pydantic import BaseModel\nclass Item(BaseModel):\n    a: int\n",
    )
    assert routes._fields_block(
        tmp_path, ["models.py", "server.js"], "Item", "server.js"
    ) == ["Item: request type declared outside the repo"]
    assert routes._fields_block(tmp_path, ["a.ts", "models.py"], "Item", "a.ts") == [
        "Item: request type declared outside the repo"
    ]


def test_hostile_python_files_never_crash(tmp_path):
    fastapi(tmp_path)
    write(tmp_path, "main.py", "from fastapi import FastAPI\napp = FastAPI()\n")
    write(
        tmp_path,
        "deep.py",
        "from main import app\n@app.get('/d')\ndef f():\n    return "
        + "(" * 3000
        + "1"
        + ")" * 3000
        + "\n",
    )
    write(tmp_path, "bin.py", "\x00\x01\x02 router = (((\n")
    result = run_routes(tmp_path)
    assert row(result).status in ("complete", "partial")
    run_symbols(tmp_path)


# --- Flask ------------------------------------------------------------------


def test_flask_typical_app_reaches_complete(tmp_path):
    flask(tmp_path)
    write(
        tmp_path,
        "app/__init__.py",
        """from flask import Flask
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
login = LoginManager()


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config)
    db.init_app(app)
    login.init_app(app)

    from app.auth import bp as auth_bp
    from app.main import bp as main_bp
    from app import api

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(main_bp)
    app.register_blueprint(api.bp, url_prefix="/api/v1")

    @app.errorhandler(404)
    def not_found(e):
        return "", 404

    @app.before_request
    def before():
        pass

    @app.route("/health")
    def health():
        return "ok"

    return app
""",
    )
    write(
        tmp_path,
        "app/auth.py",
        """from flask import Blueprint, request
from flask_login import login_required
bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    return ""


@bp.route("/logout")
@login_required
def logout():
    return ""
""",
    )
    write(
        tmp_path,
        "app/main.py",
        """from flask import Blueprint
bp = Blueprint("main", __name__, template_folder="templates")


@bp.get("/")
def index():
    return ""


@bp.post("/posts/<int:post_id>/edit")
def edit(post_id):
    return ""
""",
    )
    write(
        tmp_path,
        "app/api.py",
        """from flask import Blueprint, jsonify
bp = Blueprint("api", __name__)

@bp.route("/users/<name>", methods=("GET",))
def user(name):
    return jsonify({})
""",
    )
    result = run_routes(tmp_path)
    assert (row(result).status, row(result).detail) == ("complete", "")
    assert all_routes(result) == [
        ("GET", "/"),
        ("GET", "/api/v1/users/<name>"),
        ("GET", "/auth/login"),
        ("GET", "/auth/logout"),
        ("GET", "/health"),
        ("POST", "/auth/login"),
        ("POST", "/posts/<int:post_id>/edit"),
    ]


def test_flask_nested_blueprint_prefix_concatenates(tmp_path):
    flask(tmp_path)
    write(
        tmp_path,
        "app.py",
        """from flask import Flask, Blueprint
app = Flask(__name__)
parent = Blueprint("parent", __name__, url_prefix="/parent")
child = Blueprint("child", __name__, url_prefix="/child")
parent.register_blueprint(child)
app.register_blueprint(parent)

@child.route("/x")
def x():
    return ""
""",
    )
    result = run_routes(tmp_path)
    assert all_routes(result) == [("GET", "/parent/child/x")]
    assert row(result).status == "complete"


def test_flask_method_view_and_add_url_rule(tmp_path):
    flask(tmp_path)
    write(
        tmp_path,
        "app.py",
        """from flask import Flask, Blueprint
from flask.views import MethodView, View

app = Flask(__name__)
bp = Blueprint("bp", __name__, url_prefix="/bp")


class UserAPI(MethodView):
    def get(self, user_id):
        return ""

    def post(self):
        return ""

    def _helper(self):
        return 1


class Plain(View):
    methods = ["GET", "POST"]

    def dispatch_request(self):
        return ""


def about():
    return ""


app.add_url_rule("/users/", view_func=UserAPI.as_view("users"))
bp.add_url_rule("/plain", view_func=Plain.as_view("plain"))
app.add_url_rule("/about", "about", about, methods=["GET", "PUT"])
app.register_blueprint(bp)


@app.route("/cls")
class Decorated(MethodView):
    def delete(self):
        return ""
""",
    )
    result = run_routes(tmp_path)
    assert (row(result).status, row(result).detail) == ("complete", "")
    assert all_routes(result) == [
        ("DELETE", "/cls"),
        ("GET", "/about"),
        ("GET", "/bp/plain"),
        ("GET", "/users"),
        ("POST", "/bp/plain"),
        ("POST", "/users"),
        ("PUT", "/about"),
    ]


def test_flask_sites_application_root_extensions_and_loops(tmp_path):
    flask(tmp_path)
    write(
        tmp_path,
        "app.py",
        """from flask import Flask
from flask_restx import Api, Resource

app = Flask(__name__)
app.config["APPLICATION_ROOT"] = "/svc"
api = Api(app)


class Hello(Resource):
    def get(self):
        return {}


api.add_resource(Hello, "/hello")
""",
    )
    write(
        tmp_path,
        "loop.py",
        """from flask import Flask
from views import all_blueprints
app = Flask(__name__)
for bp in all_blueprints:
    app.register_blueprint(bp)
""",
    )
    result = run_routes(tmp_path)
    got = sites_of(result)
    assert "app.py:2" in got  # flask_restx import
    assert "app.py:5" in got  # APPLICATION_ROOT
    assert "app.py:14" in got  # add_resource
    assert "loop.py:5" in got  # register_blueprint of a loop variable
    assert row(result).status == "partial"


def test_flask_orphan_blueprint_listed_without_prefix_and_site(tmp_path):
    flask(tmp_path)
    write(tmp_path, "app.py", "from flask import Flask\napp = Flask(__name__)\n")
    write(
        tmp_path,
        "lost.py",
        """from flask import Blueprint
bp = Blueprint("lost", __name__, url_prefix="/lost")

@bp.route("/a")
def a():
    return ""
""",
    )
    result = run_routes(tmp_path)
    assert all_routes(result) == [("GET", "/lost/a")]
    assert sites_of(result) == ["lost.py:2"]


def test_flask_unknown_receiver_and_computed_methods_are_sites(tmp_path):
    flask(tmp_path)
    write(
        tmp_path,
        "app.py",
        """from flask import Flask
from ext import make_app
app = make_app()
real = Flask(__name__)
M = ["GET"]

@app.route("/a")
def a():
    return ""

@real.route("/b", methods=M)
def b():
    return ""

@real.route("/c")
def c():
    return ""
""",
    )
    result = run_routes(tmp_path)
    assert all_routes(result) == [("GET", "/c")]
    assert sorted(sites_of(result)) == ["app.py:11", "app.py:7"]


def test_flask_scope_with_two_frameworks_keeps_rows_separate(tmp_path):
    write(tmp_path, "requirements.txt", "flask\nfastapi\n")
    write(
        tmp_path,
        "f.py",
        "from flask import Flask\napp = Flask(__name__)\n@app.route('/f')\ndef f():\n    return ''\n",
    )
    write(
        tmp_path,
        "g.py",
        "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/g')\ndef g():\n    return 1\n",
    )
    result = run_routes(tmp_path)
    assert all_routes(result) == [("GET", "/f"), ("GET", "/g")]
    assert row(result, framework="Flask").status == "complete"
    assert row(result, framework="FastAPI").status == "complete"


# --- Django -----------------------------------------------------------------


def test_django_typical_app_reaches_complete(tmp_path):
    django(tmp_path)
    write(tmp_path, "manage.py", "import os\n")
    write(
        tmp_path,
        "config/settings.py",
        'INSTALLED_APPS = ["django.contrib.admin"]\nROOT_URLCONF = "config.urls"\n',
    )
    write(
        tmp_path,
        "config/urls.py",
        """from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", TemplateView.as_view(template_name="home.html"), name="home"),
    path("blog/", include("blog.urls", namespace="blog")),
    path("shop/", include(("shop.urls", "shop"))),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
""",
    )
    write(
        tmp_path,
        "blog/urls.py",
        """from django.urls import path
from . import views

app_name = "blog"
urlpatterns = [
    path("", views.PostList.as_view(), name="list"),
    path("<slug:slug>/", views.detail, name="detail"),
    path("<int:year>/<int:month>/", views.archive),
]
""",
    )
    write(
        tmp_path,
        "shop/urls.py",
        """from django.urls import path
from .views import cart, checkout

urlpatterns = [
    path("cart/", cart),
    path("checkout/", checkout, {"mode": "x"}, name="checkout"),
]
""",
    )
    result = run_routes(tmp_path)
    assert (row(result).status, row(result).detail) == ("complete", "")
    assert all_routes(result) == [
        ("ANY", "/"),
        ("ANY", "/admin"),
        ("ANY", "/blog"),
        ("ANY", "/blog/<int:year>/<int:month>"),
        ("ANY", "/blog/<slug:slug>"),
        ("ANY", "/shop/cart"),
        ("ANY", "/shop/checkout"),
    ]


def test_django_re_path_regex_is_kept_verbatim(tmp_path):
    django(tmp_path)
    write(
        tmp_path,
        "urls.py",
        """from django.urls import include, re_path, path
from django.conf.urls import url
from . import views

urlpatterns = [
    re_path(r"^articles/(?P<year>[0-9]{4})/$", views.year_archive),
    url(r"^old/(\\d+)/$", views.old),
    path("api/", include([re_path(r"^v(?P<v>\\d)/ping$", views.ping)])),
]
""",
    )
    result = run_routes(tmp_path)
    got = sorted(p for _m, p in all_routes(result))
    assert got == [
        "/^articles/(?P<year>[0-9]{4})/$",
        "/^old/(\\d+)/$",
        "/api/^v(?P<v>\\d)/ping$",
    ]
    assert row(result).status == "complete"


def test_django_drf_router_expands_viewsets_and_actions(tmp_path):
    django(tmp_path)
    write(tmp_path, "settings.py", 'ROOT_URLCONF = "urls"\n')
    write(
        tmp_path,
        "urls.py",
        """from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework.decorators import api_view
from . import views

router = DefaultRouter()
router.register(r"users", views.UserViewSet, basename="user")
router.register("reports", views.ReportViewSet)

urlpatterns = [
    path("api/", include(router.urls)),
    path("ping/", views.ping),
]
""",
    )
    write(
        tmp_path,
        "views.py",
        """from rest_framework import mixins, viewsets
from rest_framework.decorators import action, api_view


class UserViewSet(viewsets.ModelViewSet):
    lookup_field = "username"

    @action(detail=True, methods=["post"], url_path="reset")
    def reset(self, request, username=None):
        pass

    @action(detail=False)
    def recent(self, request):
        pass


class ReportViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    pass


@api_view(["GET", "POST"])
def ping(request):
    pass
""",
    )
    result = run_routes(tmp_path)
    assert (row(result).status, row(result).detail) == ("complete", "")
    assert all_routes(result) == [
        ("DELETE", "/api/users/{username}"),
        ("GET", "/api"),
        ("GET", "/api/reports"),
        ("GET", "/api/reports/{pk}"),
        ("GET", "/api/users"),
        ("GET", "/api/users/recent"),
        ("GET", "/api/users/{username}"),
        ("GET", "/ping"),
        ("PATCH", "/api/users/{username}"),
        ("POST", "/api/users"),
        ("POST", "/api/users/{username}/reset"),
        ("POST", "/ping"),
        ("PUT", "/api/users/{username}"),
    ]


def test_django_sites_for_unfollowable_forms(tmp_path):
    django(tmp_path)
    write(tmp_path, "settings.py", 'ROOT_URLCONF = "urls"\n')
    write(
        tmp_path,
        "urls.py",
        """from django.conf.urls.i18n import i18n_patterns
from django.urls import include, path
from . import views

PREFIX = "x/"

urlpatterns = [
    path(PREFIX, views.a),
    path("auth/", include("allauth.urls")),
    path("ok/", views.ok),
]
urlpatterns += i18n_patterns(path("loc/", views.loc))
urlpatterns += [path(f"{n}/", views.n) for n in range(3)]
""",
    )
    result = run_routes(tmp_path)
    assert sorted(p for _m, p in all_routes(result)) == ["/loc", "/ok"]
    # PREFIX, allauth include, i18n_patterns, comprehension
    assert sorted(sites_of(result)) == [
        "urls.py:12",
        "urls.py:13",
        "urls.py:8",
        "urls.py:9",
    ]


def test_django_without_root_urlconf_reads_unincluded_urls_modules(tmp_path):
    django(tmp_path)
    write(
        tmp_path,
        "proj/urls.py",
        "from django.urls import include, path\nurlpatterns = [path('a/', include('app.urls'))]\n",
    )
    write(
        tmp_path,
        "app/urls.py",
        "from django.urls import path\nurlpatterns = [path('b/', lambda r: None)]\n",
    )
    result = run_routes(tmp_path)
    assert all_routes(result) == [("ANY", "/a/b")]
    assert row(result).status == "complete"


def test_django_unreached_urlconf_and_stray_path_are_sites(tmp_path):
    django(tmp_path)
    write(tmp_path, "settings.py", 'ROOT_URLCONF = "main_urls"\n')
    write(
        tmp_path,
        "main_urls.py",
        "from django.urls import path\nurlpatterns = [path('m/', lambda r: None)]\n",
    )
    write(
        tmp_path,
        "other/urls.py",
        "from django.urls import path\nurlpatterns = [path('o/', lambda r: None)]\n",
    )
    write(
        tmp_path,
        "other/helpers.py",
        "from django.urls import path\nextra = [path('stray/', lambda r: None)]\n",
    )
    result = run_routes(tmp_path)
    assert ("ANY", "/o") in all_routes(result)
    assert ("ANY", "/m") in all_routes(result)
    assert sorted(sites_of(result)) == ["other/helpers.py:2", "other/urls.py:1"]


def test_django_root_urlconf_not_literal_or_unresolved_is_a_site(tmp_path):
    django(tmp_path)
    write(tmp_path, "settings.py", 'import os\nROOT_URLCONF = os.environ["URLS"]\n')
    write(
        tmp_path,
        "urls.py",
        "from django.urls import path\nurlpatterns = [path('a/', lambda r: 1)]\n",
    )
    result = run_routes(tmp_path)
    assert ("ANY", "/a") in all_routes(result)
    assert "settings.py:2" in sites_of(result)


def test_django_web_module_without_routes_is_a_site(tmp_path):
    django(tmp_path)
    write(tmp_path, "shop/views.py", "from django.http import HttpResponse\n")
    result = run_routes(tmp_path)
    assert (row(result).status, row(result).detail) == ("partial", "requirements.txt:1")
    plain = tmp_path / "plain"
    write(plain, "requirements.txt", "django\n")
    write(plain, "models.py", "from django.db import models\n")
    result = run_routes(tmp_path)
    assert row(result, "plain").status == "complete"


def test_django_function_view_http_method_decorators(tmp_path):
    django(tmp_path)
    write(
        tmp_path,
        "urls.py",
        """from django.urls import path
from django.views.decorators.http import require_http_methods, require_POST
from django.contrib.auth.decorators import login_required


@require_http_methods(["GET", "PUT"])
def one(request):
    pass


@require_POST
def two(request):
    pass


@login_required
def three(request):
    pass


urlpatterns = [path("one/", one), path("two/", two), path("three/", login_required(three))]
""",
    )
    result = run_routes(tmp_path)
    assert all_routes(result) == [
        ("ANY", "/three"),
        ("GET", "/one"),
        ("POST", "/two"),
        ("PUT", "/one"),
    ]


def test_django_long_sum_of_patterns_is_not_dropped(tmp_path):
    django(tmp_path)
    terms = " + ".join(f"[path('p{i}/', lambda r: 1)]" for i in range(200))
    write(tmp_path, "urls.py", f"from django.urls import path\nurlpatterns = {terms}\n")
    result = run_routes(tmp_path)
    shown = [p for _m, p in all_routes(result)]
    # either all followed, or the cut-off is a site; never silently complete
    assert len(shown) == 200 or row(result).status == "partial"


def test_flask_and_fastapi_foreign_routing_forms_are_sites(tmp_path):
    write(tmp_path, "requirements.txt", "flask\nfastapi\n")
    write(
        tmp_path,
        "a.py",
        """from flask import Flask
from werkzeug.routing import Rule
from werkzeug.middleware.dispatcher import DispatcherMiddleware
app = Flask(__name__)
app.url_map.add(Rule("/r", endpoint="r"))
""",
    )
    write(
        tmp_path,
        "b.py",
        """from fastapi import FastAPI
from starlette.routing import Route, Mount
app = FastAPI(routes=[Route("/s", lambda r: None)])
extra = Mount("/m", app=None)
""",
    )
    result = run_routes(tmp_path)
    assert {"a.py:3", "a.py:5"} <= set(sites_of(result, framework="Flask"))
    assert {"b.py:3", "b.py:4"} <= set(sites_of(result, framework="FastAPI"))


def test_deep_attribute_chain_does_not_crash(tmp_path):
    fastapi(tmp_path)
    chain = ".".join(["a"] * 4000)
    write(
        tmp_path,
        "main.py",
        f"from fastapi import FastAPI\napp = FastAPI()\n@{chain}.get('/x')\ndef f():\n    return 1\n",
    )
    result = run_routes(tmp_path)
    assert row(result).status == "partial"


# --- symbols ----------------------------------------------------------------


def sym_rows(result) -> list[tuple[str, str, str]]:
    return sorted(
        (r[0], r[1], r[2]) for s in result.sections for r in table_rows(s.l2_md)[1:]
    )


def py_row(result, scope: str = "."):
    (found,) = [
        r for r in result.coverage if r.scope == scope and r.framework == "python"
    ]
    return found


def test_python_symbols_without_all_public_names_and_enum_members(tmp_path):
    write(tmp_path, "requirements.txt", "flask\n")
    write(
        tmp_path,
        "pkg/models.py",
        """import os
from enum import Enum, IntEnum
from typing import TypeAlias

API_URL = "https://x"
_PRIVATE = 1
a, b = 1, 2
Handler: TypeAlias = int


def public():
    pass


async def apublic():
    pass


def _hidden():
    pass


@decorator
def decorated():
    pass


class Role(Enum):
    ADMIN = "sk-live-abc123secret"
    USER = "user"
    _ignore_ = ["x"]

    def label(self):
        return 1


class Level(IntEnum):
    LOW = 1


class SubLevel(Level):
    HIGH = 2


class Plain:
    KEY = "not-listed"


if __name__ == "__main__":
    SCRIPT_ONLY = 1

try:
    import ujson
except ImportError:
    FALLBACK = True
""",
    )
    result = run_symbols(tmp_path)
    f = "pkg/models.py"
    assert sym_rows(result) == [
        ("API_URL", "const", f),
        ("FALLBACK", "const", f),
        ("Handler", "type", f),
        ("Level", "enum", f),
        ("Level.LOW", "member", f),
        ("Plain", "class", f),
        ("Role", "enum", f),
        ("Role.ADMIN", "member", f),
        ("Role.USER", "member", f),
        ("SubLevel", "enum", f),
        ("SubLevel.HIGH", "member", f),
        ("a", "const", f),
        ("apublic", "function", f),
        ("b", "const", f),
        ("decorated", "function", f),
        ("public", "function", f),
    ]
    blob = "\n".join(
        s.l2_md + s.l3_md + s.summary for s in result.sections
    ) + "\n".join(f"{r.detail}" for r in result.coverage)
    assert "sk-live-abc123secret" not in blob and "https://x" not in blob
    assert py_row(result).status == "complete"


def test_python_symbols_all_forms_and_computed_all_is_a_site(tmp_path):
    write(tmp_path, "requirements.txt", "flask\n")
    write(
        tmp_path,
        "pkg/__init__.py",
        """from .a import Thing, helper, CONSTANT
from . import sub

__all__ = ["Thing", "helper", "CONSTANT", "sub"]
__all__ += ["extra"]
__all__.extend(["more"])
__all__.append("last")


def extra():
    pass


def more():
    pass


def last():
    pass


def not_listed():
    pass
""",
    )
    write(
        tmp_path,
        "pkg/computed.py",
        """from .a import __all__ as a_all

__all__ = list(a_all) + ["z"]


def z():
    pass


def y():
    pass
""",
    )
    write(
        tmp_path,
        "pkg/star.py",
        "from .a import *\n\n\ndef own():\n    pass\n",
    )
    result = run_symbols(tmp_path)
    got = sym_rows(result)
    init = [(n, k) for n, k, f in got if f == "pkg/__init__.py"]
    assert init == [
        ("CONSTANT", "const"),
        ("Thing", "class"),
        ("extra", "function"),
        ("helper", "function"),
        ("last", "function"),
        ("more", "function"),
        ("sub", "function"),
    ]
    assert ("not_listed", "function", "pkg/__init__.py") not in got
    # computed / star: best-effort names + a site
    assert ("z", "function", "pkg/computed.py") in got
    assert ("own", "function", "pkg/star.py") in got
    assert py_row(result).status == "partial"
    assert set(py_row(result).detail.split("; ")) == {
        "pkg/computed.py:3",
        "pkg/star.py:1",
    }


def test_python_symbols_skip_test_files_by_name_not_substring(tmp_path):
    write(tmp_path, "requirements.txt", "flask\n")
    for rel in ("contest.py", "latest.py", "api/test.py", "testing/helpers.py"):
        write(tmp_path, rel, "def product():\n    pass\n")
    for rel in ("test_a.py", "b_test.py", "conftest.py", "tests/c.py", "pkg/test/d.py"):
        write(tmp_path, rel, "def hidden():\n    pass\n")
    result = run_symbols(tmp_path)
    files = sorted({f for _n, _k, f in sym_rows(result)})
    assert files == ["api/test.py", "contest.py", "latest.py", "testing/helpers.py"]
    assert "5 test" in py_row(result).detail


def test_python_symbols_syntax_error_is_a_site(tmp_path):
    write(tmp_path, "requirements.txt", "flask\n")
    write(tmp_path, "bad.py", "def f(:\n    pass\n")
    write(tmp_path, "good.py", "def g():\n    pass\n")
    result = run_symbols(tmp_path)
    assert ("g", "function", "good.py") in sym_rows(result)
    assert py_row(result).status == "partial"
    assert py_row(result).detail.startswith("bad.py:")


def test_flask_web_module_with_no_routes_is_a_site_at_the_dependency(tmp_path):
    write(tmp_path, "svc/requirements.txt", "# pins\nflask==3.0\n")
    write(
        tmp_path,
        "svc/helpers.py",
        "from flask import jsonify\n\ndef ok():\n    return jsonify({})\n",
    )
    write(tmp_path, "tools/requirements.txt", "flask\n")
    write(tmp_path, "tools/cli.py", "import click\n")
    result = run_routes(tmp_path)
    assert (row(result, "svc").status, row(result, "svc").detail) == (
        "partial",
        "svc/requirements.txt:2",
    )
    assert row(result, "tools").status == "complete"  # flask never imported


def test_route_list_edits_on_a_holder_are_sites(tmp_path):
    fastapi(tmp_path)
    write(
        tmp_path,
        "main.py",
        "from fastapi import FastAPI\napp = FastAPI()\napp.routes.append(make())\n",
    )
    result = run_routes(tmp_path)
    assert sites_of(result) == ["main.py:3"]


def test_python_routes_are_deterministic(tmp_path):
    write(tmp_path, "requirements.txt", "flask\nfastapi\ndjango\n")
    write(
        tmp_path,
        "a.py",
        "from flask import Flask\napp = Flask(__name__)\n@app.route('/b')\ndef b():\n    return ''\n"
        "@app.route('/a', methods=['POST', 'GET'])\ndef a():\n    return ''\n",
    )
    write(
        tmp_path,
        "urls.py",
        "from django.urls import path\nurlpatterns = [path('z/', lambda r: 1), path('y/', lambda r: 1)]\n",
    )
    first = run_routes(tmp_path)
    second = run_routes(tmp_path)
    dump = lambda r: ([(s.id, s.l2_md, s.l3_md) for s in r.sections], r.coverage)  # noqa: E731
    assert dump(first) == dump(second)
    assert [m for m, p in all_routes(first) if p == "/a"] == ["GET", "POST"]


# --- review round 1 ---------------------------------------------------------


def test_drf_register_in_file_sorted_before_router_constructor(tmp_path):
    django(tmp_path)
    write(tmp_path, "config/settings.py", 'ROOT_URLCONF = "config.routing"\n')
    write(
        tmp_path,
        "config/routing.py",
        "from django.urls import include, path\n"
        "from rest_framework.routers import DefaultRouter\n"
        "router = DefaultRouter()\n"
        "import blog.api\n"
        "urlpatterns = [path('api/', include(router.urls))]\n",
    )
    write(
        tmp_path,
        "blog/api.py",
        "from rest_framework import viewsets\n"
        "from config.routing import router\n\n"
        "class PostViewSet(viewsets.ReadOnlyModelViewSet):\n    pass\n\n"
        "router.register('posts', PostViewSet)\n",
    )
    result = run_routes(tmp_path)
    assert ("GET", "/api/posts") in all_routes(result)
    assert row(result).status == "complete"


def test_drf_register_on_unresolved_router_is_a_site(tmp_path):
    django(tmp_path)
    write(
        tmp_path,
        "urls.py",
        "from django.urls import path\nurlpatterns = [path('a/', lambda r: 1)]\n",
    )
    write(
        tmp_path,
        "api.py",
        "from rest_framework import viewsets\nfrom lib import router\n"
        "class V(viewsets.ModelViewSet):\n    pass\n\n"
        "router.register('v', V)\n"
        "admin.site.register(Model, ModelAdmin)\n",
    )
    result = run_routes(tmp_path)
    assert sites_of(result) == ["api.py:6"]


def test_decorator_on_computed_receiver_is_a_site(tmp_path):
    fastapi(tmp_path)
    write(
        tmp_path,
        "hidden.py",
        "from lib import get_router, ROUTERS\n\n"
        "@get_router().get('/hidden')\ndef a():\n    return 1\n\n"
        "@ROUTERS['v1'].post('/hidden2')\ndef b():\n    return 1\n",
    )
    result = run_routes(tmp_path)
    assert sites_of(result) == ["hidden.py:3", "hidden.py:7"]


def test_handler_column_never_prints_call_arguments(tmp_path):
    django(tmp_path)
    write(
        tmp_path,
        "urls.py",
        "from django.urls import path\nfrom . import views\n"
        "urlpatterns = [\n"
        "    path('a/', make_view('sk_live_abc123')),\n"
        "    path('b/', build(token='ghp_secret')),\n"
        "    path('c/', Factory('sk_live_xyz').as_view()),\n"
        "    path('d/', views.ok),\n"
        "    path('e/', lambda r: 'sk_live_l'),\n"
        "]\n",
    )
    flask(tmp_path, "f")
    write(
        tmp_path,
        "f/app.py",
        "from flask import Flask\napp = Flask(__name__)\n"
        "app.add_url_rule('/g', view_func=make('ghp_flask'))\n",
    )
    fastapi(tmp_path, "g")
    write(
        tmp_path,
        "g/main.py",
        "from fastapi import FastAPI\napp = FastAPI()\n"
        "app.add_api_route('/h', make('sk_live_fast'))\n",
    )
    result = run_routes(tmp_path)
    blob = "\n".join(s.l2_md + s.l3_md for s in result.sections)
    for secret in ("sk_live", "ghp_"):
        assert secret not in blob
    handlers = sorted(r[2] for s in result.sections for r in table_rows(s.l2_md)[1:])
    assert "views.ok" in handlers and "lambda" in handlers
    # a call as a Flask view_func is a site, not a route
    assert handlers.count("(inline)") == 3 and "build" in handlers


def test_annotated_field_default_and_no_literal_in_type(tmp_path):
    fastapi(tmp_path)
    write(
        tmp_path,
        "main.py",
        "from typing import Annotated, Literal\nfrom fastapi import FastAPI\n"
        "from pydantic import BaseModel, Field\napp = FastAPI()\n\n"
        "class M(BaseModel):\n"
        "    token: Annotated[str, Field(examples=['sk_live_abc'], default='sk_live_def')]\n"
        "    need: Annotated[int, Field(gt=0, alias='n')]\n"
        "    kind: Literal['sk_live_x', 'b'] = 'b'\n"
        "    maybe: Annotated[str | None, Field(default=None)]\n\n"
        "@app.post('/m')\ndef m(body: M):\n    return 1\n",
    )
    result = run_routes(tmp_path)
    l3 = section(result, "main.py").l3_md
    assert "sk_live" not in l3
    assert "| token | str | no |" in l3
    assert "| n | int | yes |" in l3
    assert "| kind | Literal | no |" in l3
    assert "| maybe | str | None | no |" in l3 or "| maybe | str \\| None | no |" in l3


def test_flask_register_helper_taking_the_app_is_followed(tmp_path):
    flask(tmp_path)
    write(
        tmp_path,
        "my_app/app.py",
        "from flask import Flask\nfrom my_app import user\n\n"
        "def create_app():\n    app = Flask(__name__)\n    register_blueprints(app)\n    return app\n\n"
        "def register_blueprints(app):\n    app.register_blueprint(user.blueprint)\n",
    )
    write(
        tmp_path,
        "my_app/user.py",
        "from flask import Blueprint\nblueprint = Blueprint('u', __name__, url_prefix='/users')\n"
        "@blueprint.route('/')\ndef members():\n    return ''\n",
    )
    result = run_routes(tmp_path)
    assert all_routes(result) == [("GET", "/users")]
    assert row(result).status == "complete"
    # a second caller passing something else makes it unknowable
    write(
        tmp_path,
        "other.py",
        "from my_app.app import register_blueprints\nregister_blueprints(make())\n",
    )
    result = run_routes(tmp_path)
    assert row(result).status == "partial"


def test_root_path_site_only_for_server_settings(tmp_path):
    fastapi(tmp_path)
    write(
        tmp_path,
        "main.py",
        "from pathlib import Path\nfrom fastapi import FastAPI\napp = FastAPI()\n"
        "root_path = Path(__file__).parent\nif root_path == 1:\n    pass\n"
        "@app.get('/x')\ndef x():\n    return 1\n",
    )
    assert row(run_routes(tmp_path)).status == "complete"
    write(
        tmp_path, "run.py", "import uvicorn\nuvicorn.run('main:app', root_path='/p')\n"
    )
    write(tmp_path, "assign.py", "from main import app\napp.root_path = '/q'\n")
    result = run_routes(tmp_path)
    assert sites_of(result) == ["assign.py:2", "run.py:2"]


# --- review round 2 ---------------------------------------------------------


def test_wrapped_multiline_decorator_receiver_is_a_site(tmp_path):
    fastapi(tmp_path)
    write(tmp_path, "main.py", "from fastapi import FastAPI\napp = FastAPI()\n")
    write(
        tmp_path,
        "other.py",
        "from lib import registry\n\n@registry.router_for(\n    'some-long-name',\n"
        "    version=2,\n).get('/y')\ndef y():\n    return 1\n\n"
        "@ROUTERS[\n    'v1'\n].post('/z')\ndef z():\n    return 1\n\n"
        "@mk() . get('/w')\ndef w():\n    return 1\n",
    )
    result = run_routes(tmp_path)
    assert row(result).status == "partial"
    assert sorted(sites_of(result)) == ["other.py:10", "other.py:16", "other.py:3"]


def test_param_helper_also_used_as_a_value_is_not_bound(tmp_path):
    flask(tmp_path)
    write(
        tmp_path,
        "app.py",
        "from flask import Flask, Blueprint\napp = Flask(__name__)\n"
        "bp = Blueprint('b', __name__, url_prefix='/b')\n"
        "def reg(t):\n    @t.route('/cb')\n    def cb():\n        return ''\n"
        "reg(app)\nfor h in [reg]:\n    h(bp)\napp.register_blueprint(bp)\n",
    )
    result = run_routes(tmp_path)
    assert row(result).status == "partial"
    assert "app.py:5" in sites_of(result)


def test_drf_unresolved_router_variable_or_concatenated_prefix_is_a_site(tmp_path):
    django(tmp_path)
    write(
        tmp_path,
        "urls.py",
        "from django.urls import path\nurlpatterns = [path('a/', lambda r: 1)]\n",
    )
    write(
        tmp_path,
        "api.py",
        "from rest_framework import viewsets\nfrom lib import router\nPREFIX = 'x'\n"
        "class V(viewsets.ModelViewSet):\n    pass\n\n"
        "router.register(PREFIX, V)\n"
        "router.register('a' 'b', V)\n"
        "router.register(PREFIX, V, basename='v')\n"
        "admin.site.register(Model, ModelAdmin)\n",
    )
    result = run_routes(tmp_path)
    assert sorted(sites_of(result)) == ["api.py:7", "api.py:8", "api.py:9"]


def test_nested_annotated_and_string_never_leak_into_field_types(tmp_path):
    fastapi(tmp_path)
    write(
        tmp_path,
        "main.py",
        "from typing import Annotated, Literal, Optional\nfrom fastapi import Body, FastAPI\n"
        "from pydantic import BaseModel\napp = FastAPI()\n\n"
        "class M(BaseModel):\n"
        "    a: Optional[Annotated[str, 'ghp_TOKEN']] = None\n"
        "    b: list['sk_live_fwd'] = []\n\n"
        "@app.post('/m')\ndef m(body: M):\n    return 1\n\n"
        "@app.post('/p')\ndef p(payload: Annotated[Literal['sk_live_X'], Body()]):\n    return 1\n",
    )
    result = run_routes(tmp_path)
    blob = "\n".join(s.l2_md + s.l3_md for s in result.sections)
    assert "ghp_" not in blob and "sk_live" not in blob
    assert "| a | Optional[str] | no |" in section(result, "main.py").l3_md
    assert "Literal" in blob
