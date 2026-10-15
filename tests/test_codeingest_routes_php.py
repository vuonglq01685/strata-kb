"""PHP: Laravel and Symfony route adapters and the php exported symbols."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("tree_sitter_language_pack")

from strata_kb.codeingest.extractors import routes, symbols
from strata_kb.codeingest.types import CodeIngestOptions

LARAVEL = "laravel/framework"
SYMFONY = "symfony/framework-bundle"


def write(root: Path, rel: str, text: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def composer(root: Path, package: str, app: str = ".") -> None:
    write(root, f"{app}/composer.json", f'{{"require": {{"{package}": "^11.0"}}}}\n')


def opts(root: Path) -> CodeIngestOptions:
    return CodeIngestOptions(
        repo_root=root, kb_dir=root / ".kb", doc_id="d", repo_id="r"
    )


def run_routes(root: Path):
    return routes.RoutesExtractor().extract(root, opts(root))


def run_symbols(root: Path):
    return symbols.SymbolsExtractor().extract(root, opts(root))


def cells(l2: str) -> list[list[str]]:
    """Data rows of an L2 table; `table_rows` splits on an escaped `\\|` too."""
    rows = []
    for line in l2.splitlines()[2:]:
        parts = re.split(r"(?<!\\)\|", line.strip()[1:-1])
        rows.append([p.strip().replace("\\|", "|") for p in parts])
    return rows


def section(result, file: str):
    (found,) = [s for s in result.sections if s.title == file]
    return found


def rows_of(result, file: str) -> list[list[str]]:
    return cells(section(result, file).l2_md)


def row(result, scope: str = "."):
    (found,) = [r for r in result.coverage if r.scope == scope]
    return found


def pairs(result) -> list[tuple[str, str]]:
    return sorted((r[0], r[1]) for s in result.sections for r in cells(s.l2_md))


def triples(result) -> list[tuple[str, str, str]]:
    return sorted((r[0], r[1], r[2]) for s in result.sections for r in cells(s.l2_md))


def at(text: str, needle: str) -> int:
    """1-based line of the first line holding `needle`."""
    return next(n for n, ln in enumerate(text.splitlines(), 1) if needle in ln)


def everything(result) -> str:
    return "\n".join(
        s.l2_md + s.l3_md + s.summary for s in result.sections
    ) + "\n".join(r.detail for r in result.coverage)


# --- Laravel ------------------------------------------------------------------

WEB = "routes/web.php"


def laravel(root: Path, web: str, rel: str = WEB) -> None:
    composer(root, LARAVEL)
    write(root, rel, web)


def test_laravel_verbs_and_handler_forms(tmp_path):
    laravel(
        tmp_path,
        """<?php
use App\\Http\\Controllers\\PostController;
use App\\Http\\Controllers\\HealthController;
use Illuminate\\Support\\Facades\\Route;

Route::get('/', fn () => view('welcome'));
Route::get('/posts/{post}', [PostController::class, 'show'])->name('posts.show');
Route::post('/posts', 'PostController@store');
Route::delete('/posts/{post}', PostController::class);
Route::match(['put', 'patch'], '/posts/{post}', [\\App\\Http\\Controllers\\PostController::class, 'update']);
Route::any('/hook', HealthController::class);
Route::options('/o', function () { return 1; });
""",
    )
    result = run_routes(tmp_path)
    assert rows_of(result, WEB) == [
        ["GET", "/", "(inline)", WEB, ""],
        ["ANY", "/hook", "HealthController", WEB, ""],
        ["OPTIONS", "/o", "(inline)", WEB, ""],
        ["POST", "/posts", "PostController@store", WEB, ""],
        ["DELETE", "/posts/{post}", "PostController", WEB, ""],
        ["GET", "/posts/{post}", "PostController@show", WEB, ""],
        ["PATCH", "/posts/{post}", "PostController@update", WEB, ""],
        ["PUT", "/posts/{post}", "PostController@update", WEB, ""],
    ]
    assert (row(result).status, row(result).detail) == ("complete", "")


def test_laravel_groups_prefixes_and_controller(tmp_path):
    laravel(
        tmp_path,
        """<?php
use Illuminate\\Support\\Facades\\Route;

Route::prefix('api')->middleware(['auth:sanctum'])->name('api.')->group(function () {
    Route::get('/users/{user}', [UserController::class, 'show']);
    Route::prefix('v2')->group(function () {
        Route::controller(OrderController::class)->group(function () {
            Route::get('/orders/{id}', 'show');
            Route::post('/orders', 'store')->name('orders.store');
        });
    });
});
Route::group(['prefix' => 'admin', 'middleware' => 'auth'], function () {
    Route::get('dash', [AdminController::class, 'dash']);
});
Route::middleware('auth')->domain('{tenant}.example.com')->group(function () {
    Route::get('/me', fn () => 1);
});
""",
    )
    result = run_routes(tmp_path)
    assert triples(result) == sorted(
        [
            ("GET", "/admin/dash", "AdminController@dash"),
            ("GET", "/api/users/{user}", "UserController@show"),
            ("GET", "/api/v2/orders/{id}", "OrderController@show"),
            ("POST", "/api/v2/orders", "OrderController@store"),
            ("GET", "/me", "(inline)"),
        ]
    )
    assert row(result).status == "complete"


def test_laravel_resource_expansion_only_except_nested(tmp_path):
    laravel(
        tmp_path,
        """<?php
Route::resource('photos', PhotoController::class);
Route::apiResource('posts', PostController::class)->only(['index', 'show']);
Route::apiResource('tags', TagController::class)->except(['destroy']);
Route::resource('photos.comments', CommentController::class)->only('index');
Route::resource('user-profiles', ProfileController::class)->only(['show']);
""",
    )
    result = run_routes(tmp_path)
    got = triples(result)
    photo = "PhotoController@"
    assert [
        t for t in got if t[1].startswith("/photos") and "comments" not in t[1]
    ] == sorted(
        [
            ("GET", "/photos", photo + "index"),
            ("POST", "/photos", photo + "store"),
            ("GET", "/photos/create", photo + "create"),
            ("DELETE", "/photos/{photo}", photo + "destroy"),
            ("GET", "/photos/{photo}", photo + "show"),
            ("PATCH", "/photos/{photo}", photo + "update"),
            ("PUT", "/photos/{photo}", photo + "update"),
            ("GET", "/photos/{photo}/edit", photo + "edit"),
        ]
    )
    assert ("GET", "/photos/{photo}/comments", "CommentController@index") in got
    assert ("GET", "/posts", "PostController@index") in got
    assert ("GET", "/posts/{post}", "PostController@show") in got
    assert not [t for t in got if t[1].startswith("/posts") and t[0] != "GET"]
    tags = [t for t in got if t[1].startswith("/tags")]
    assert sorted(tags) == sorted(
        [
            ("GET", "/tags", "TagController@index"),
            ("POST", "/tags", "TagController@store"),
            ("GET", "/tags/{tag}", "TagController@show"),
            ("PATCH", "/tags/{tag}", "TagController@update"),
            ("PUT", "/tags/{tag}", "TagController@update"),
        ]
    )
    assert ("GET", "/user-profiles/{user_profile}", "ProfileController@show") in got
    assert row(result).status == "complete"


def test_laravel_resource_full_set_is_eight_rows_with_put_and_patch(tmp_path):
    laravel(tmp_path, "<?php\nRoute::resource('photos', PhotoController::class);\n")
    assert len(triples(run_routes(tmp_path))) == 8


def test_laravel_dynamic_forms_are_sites(tmp_path):
    text = """<?php
Route::get($path, [X::class, 'a']);
Route::get('/a/' . $suffix, [X::class, 'b']);
Route::match($verbs, '/m', [X::class, 'c']);
Route::resource($name, X::class);
Route::resource('items', X::class)->only($only);
Route::prefix($p)->group(function () {
    Route::get('/in', [X::class, 'd']);
});
Route::localized('/x', [X::class, 'e']);
Route::get('/ok', [X::class, 'f']);
Route::get("/interp/{$id}", [X::class, 'g']);
"""
    laravel(tmp_path, text)
    result = run_routes(tmp_path)
    expected = [
        at(text, needle)
        for needle in (
            "$path",
            "'/a/'",
            "$verbs",
            "$name",
            "->only($only)",
            "Route::prefix($p)",
            "localized",
            "interp",
        )
    ]
    assert row(result).status == "partial"
    assert row(result).detail == "; ".join(sorted(f"{WEB}:{n}" for n in expected))
    got = pairs(result)
    assert ("GET", "/ok") in got and ("GET", "/in") in got


def test_laravel_redirect_view_fallback(tmp_path):
    laravel(
        tmp_path,
        """<?php
Route::redirect('/old', '/new');
Route::view('/about', 'about');
Route::fallback(fn () => abort(404));
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [
        ("ANY", "/old"),
        ("GET", "/about"),
        ("GET", "/{fallbackPlaceholder}"),
    ]
    assert row(result).status == "complete"


def test_laravel_aliased_facade_and_foreign_route_class(tmp_path):
    laravel(
        tmp_path,
        """<?php
use Illuminate\\Support\\Facades\\Route as R;
R::get('/aliased', fn () => 1);
\\Illuminate\\Support\\Facades\\Route::get('/qualified', fn () => 2);
\\Route::get('/global', fn () => 3);
""",
    )
    write(
        tmp_path,
        "src/Other.php",
        """<?php
use Symfony\\Component\\Routing\\Route;
$r = Route::get('/not-laravel', fn () => 1);
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [
        ("GET", "/aliased"),
        ("GET", "/global"),
        ("GET", "/qualified"),
    ]
    assert row(result).status == "complete"


def test_laravel_legacy_router_variable_and_group_array(tmp_path):
    laravel(
        tmp_path,
        """<?php
$router->get('/legacy', 'LegacyController@index');
$router->group(['prefix' => 'v1'], function ($router) {
    $router->post('/items', 'ItemController@store');
});
""",
    )
    result = run_routes(tmp_path)
    assert triples(result) == [
        ("GET", "/legacy", "LegacyController@index"),
        ("POST", "/v1/items", "ItemController@store"),
    ]


def test_laravel_layout_proof_chains(tmp_path):
    text = """<?php
Route
    ::
    get(
        '/a', // the path
        [X::class, 'a']
    )
    ->name('a');
Route::prefix  ( 'p' )
  /* wrapped */ ->middleware('auth')
  ->group (
     function () {
        Route::get('/b', 'X@b');
        Route::get(
          '/c',
          /* c */ 'X@c'
        );
     }
  );
"""
    laravel(tmp_path, text)
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/a"), ("GET", "/p/b"), ("GET", "/p/c")]
    assert row(result).status == "complete"


# --- Laravel route-file prefixes ----------------------------------------------

PROVIDER = """<?php
namespace App\\Providers;

use Illuminate\\Support\\Facades\\Route;
use Illuminate\\Foundation\\Support\\Providers\\RouteServiceProvider as ServiceProvider;

class RouteServiceProvider extends ServiceProvider
{
    public function boot(): void
    {
        $this->routes(function () {
            Route::middleware('api')->prefix(%s)->group(base_path('routes/api.php'));
            Route::middleware('web')->group(base_path('routes/web.php'));
        });
    }
}
"""


def test_laravel_route_service_provider_prefix(tmp_path):
    composer(tmp_path, LARAVEL)
    write(tmp_path, "app/Providers/RouteServiceProvider.php", PROVIDER % "'api/v1'")
    write(tmp_path, "routes/api.php", "<?php\nRoute::get('/ping', fn () => 1);\n")
    write(tmp_path, WEB, "<?php\nRoute::get('/home', fn () => 1);\n")
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/api/v1/ping"), ("GET", "/home")]
    assert row(result).status == "complete"


def test_laravel_unresolvable_route_file_prefix_is_a_site(tmp_path):
    composer(tmp_path, LARAVEL)
    provider = PROVIDER % "config('app.api_prefix')"
    write(tmp_path, "app/Providers/RouteServiceProvider.php", provider)
    write(tmp_path, "routes/api.php", "<?php\nRoute::get('/ping', fn () => 1);\n")
    write(tmp_path, WEB, "<?php\nRoute::get('/home', fn () => 1);\n")
    result = run_routes(tmp_path)
    assert row(result).status == "partial"
    assert row(result).detail == (
        f"app/Providers/RouteServiceProvider.php:{at(provider, 'prefix(config')}"
    )


def test_laravel_bootstrap_with_routing_api_prefix(tmp_path):
    composer(tmp_path, LARAVEL)
    write(
        tmp_path,
        "bootstrap/app.php",
        """<?php
use Illuminate\\Foundation\\Application;

return Application::configure(basePath: dirname(__DIR__))
    ->withRouting(
        web: __DIR__.'/../routes/web.php',
        api: __DIR__.'/../routes/api.php',
        commands: __DIR__.'/../routes/console.php',
        health: '/up',
        apiPrefix: 'v2',
    )
    ->withMiddleware(function ($middleware) {
        $middleware->alias(['admin' => AdminOnly::class]);
    })
    ->create();
""",
    )
    write(tmp_path, "routes/api.php", "<?php\nRoute::get('/ping', fn () => 1);\n")
    write(tmp_path, WEB, "<?php\nRoute::get('/home', fn () => 1);\n")
    write(tmp_path, "routes/console.php", "<?php\nArtisan::command('x', fn () => 1);\n")
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/home"), ("GET", "/up"), ("GET", "/v2/ping")]
    assert row(result).status == "complete"


def test_laravel_bootstrap_default_api_prefix_and_dynamic_prefix(tmp_path):
    composer(tmp_path, LARAVEL)
    body = """<?php
return Application::configure(basePath: dirname(__DIR__))
    ->withRouting(
        api: __DIR__.'/../routes/api.php',
        apiPrefix: %s,
    )->create();
"""
    write(tmp_path, "bootstrap/app.php", body % "'api'")
    write(tmp_path, "routes/api.php", "<?php\nRoute::get('/ping', fn () => 1);\n")
    assert pairs(run_routes(tmp_path)) == [("GET", "/api/ping")]
    dynamic = body % "env('API_PREFIX')"
    write(tmp_path, "bootstrap/app.php", dynamic)
    result = run_routes(tmp_path)
    assert row(result).detail == f"bootstrap/app.php:{at(dynamic, 'apiPrefix')}"


def test_laravel_conventional_prefixes_and_unregistered_route_file(tmp_path):
    laravel(tmp_path, "<?php\nRoute::get('/home', fn () => 1);\n")
    write(tmp_path, "routes/api.php", "<?php\nRoute::get('/ping', fn () => 1);\n")
    write(tmp_path, "routes/admin.php", "<?php\nRoute::get('/panel', fn () => 1);\n")
    result = run_routes(tmp_path)
    assert row(result).status == "partial"
    assert row(result).detail == "routes/admin.php:1"
    assert ("GET", "/api/ping") in pairs(result)
    assert ("GET", "/home") in pairs(result)


def test_laravel_require_inherits_prefix_and_is_order_independent(tmp_path):
    composer(tmp_path, LARAVEL)
    # routes/auth.php sorts before routes/web.php; it is only ever included
    write(tmp_path, "routes/auth.php", "<?php\nRoute::get('/login', fn () => 1);\n")
    write(
        tmp_path,
        WEB,
        """<?php
Route::get('/', fn () => 1);
Route::prefix('account')->group(function () {
    require __DIR__.'/auth.php';
});
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/"), ("GET", "/account/login")]
    assert row(result).status == "complete"


@pytest.mark.parametrize("provider_dir", ["aaa", "zzz"])
def test_laravel_registering_file_before_or_after_defining_file(tmp_path, provider_dir):
    composer(tmp_path, LARAVEL)
    write(
        tmp_path,
        f"{provider_dir}/Provider.php",
        "<?php\nclass P { function boot() {\n"
        "Route::prefix('x')->group(base_path('routes/shop.php'));\n} }\n",
    )
    write(tmp_path, "routes/shop.php", "<?php\nRoute::get('/cart', fn () => 1);\n")
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/x/cart")]
    assert row(result).status == "complete"


def test_laravel_unresolvable_require_is_a_site(tmp_path):
    text = "<?php\nrequire $dir.'/extra.php';\nRoute::get('/a', fn () => 1);\n"
    laravel(tmp_path, text)
    result = run_routes(tmp_path)
    assert row(result).detail == f"{WEB}:2"


# --- Laravel: same-named non-route APIs ---------------------------------------


def test_laravel_collection_and_http_client_get_are_not_routes(tmp_path):
    laravel(tmp_path, "<?php\nRoute::get('/a', [ReportController::class, 'index']);\n")
    write(
        tmp_path,
        "app/Http/Controllers/ReportController.php",
        """<?php
namespace App\\Http\\Controllers;

use Illuminate\\Support\\Facades\\Cache;
use Illuminate\\Support\\Facades\\Http;
use Illuminate\\Support\\Facades\\Route;

class ReportController extends Controller
{
    public function index(Request $request, Client $client)
    {
        $page = $request->get('page', 1);
        $items = collect($data)->get('items');
        $res = Http::get('https://example.com/api/x');
        $cached = Cache::get('k', fn () => 1);
        $r = $client->get('/users', ['query' => ['a' => 1]]);
        $s = $this->app->get('service');
        $name = Route::currentRouteName();
        $on = Route::is('reports.*');
        $post = $bag->post('/x');
        $c = $container->get(Foo::class);
    }
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/a")]
    assert row(result).status == "complete"


def test_laravel_route_shaped_call_on_unresolved_receiver_is_a_site(tmp_path):
    laravel(tmp_path, "<?php\nRoute::get('/a', fn () => 1);\n")
    text = """<?php
$app->get('/health', fn () => 'ok');
$mux->post('/x', [X::class, 'y']);
$r->put('/y', 'Z@w');
"""
    write(tmp_path, "src/micro.php", text)
    result = run_routes(tmp_path)
    assert row(result).detail == "; ".join(f"src/micro.php:{n}" for n in (2, 3, 4))


def test_laravel_test_directories_are_not_product_routes(tmp_path):
    laravel(tmp_path, "<?php\nRoute::get('/a', fn () => 1);\n")
    write(
        tmp_path,
        "tests/Feature/RouteTest.php",
        "<?php\nRoute::get($dyn, fn () => 1);\nRoute::get('/only-in-test', fn () => 1);\n",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/a")]
    assert row(result).status == "complete"


# --- Laravel: hostile input, values ---------------------------------------------


def test_laravel_unparsable_file_is_a_site(tmp_path):
    laravel(tmp_path, "<?php\nRoute::get('/a', fn () => 1);\nRoute::get('/b'\n")
    result = run_routes(tmp_path)
    assert row(result).status == "partial"
    assert row(result).detail.startswith(f"{WEB}:")


def test_laravel_deeply_nested_groups_do_not_crash(tmp_path):
    depth = 1500
    text = (
        "<?php\n"
        + "Route::prefix('a')->group(function () {\n" * depth
        + "Route::get('/leaf', fn () => 1);\n"
        + "});\n" * depth
    )
    laravel(tmp_path, text)
    result = run_routes(tmp_path)
    assert row(result).status in {"complete", "partial"}
    assert not [w for w in result.warnings if "adapter failed" in w]


def test_laravel_long_method_chain_does_not_crash(tmp_path):
    text = "<?php\nRoute::get('/a', fn () => 1)" + "->name('x')" * 4000 + ";\n"
    laravel(tmp_path, text)
    result = run_routes(tmp_path)
    assert not [w for w in result.warnings if "adapter failed" in w]


def test_laravel_string_handler_never_leaks_a_literal(tmp_path):
    laravel(
        tmp_path,
        """<?php
Route::get('/a', 'sk_live_SECRETVALUE');
Route::get('/b', ['uses' => 'ghp_SECRETTOKEN', 'as' => 'x']);
Route::get('/c', make_handler('AKIASECRET123'));
Route::get('/d', [X::class, 'method']);
""",
    )
    result = run_routes(tmp_path)
    blob = everything(result)
    for secret in ("SECRETVALUE", "SECRETTOKEN", "AKIASECRET123"):
        assert secret not in blob
    assert triples(result) == [
        ("GET", "/a", "(inline)"),
        ("GET", "/b", "(inline)"),
        ("GET", "/c", "(inline)"),
        ("GET", "/d", "X@method"),
    ]


def test_typical_laravel_app_reaches_complete(tmp_path):
    composer(tmp_path, LARAVEL)
    write(
        tmp_path,
        "bootstrap/app.php",
        """<?php

use Illuminate\\Foundation\\Application;
use Illuminate\\Foundation\\Configuration\\Exceptions;
use Illuminate\\Foundation\\Configuration\\Middleware;

return Application::configure(basePath: dirname(__DIR__))
    ->withRouting(
        web: __DIR__.'/../routes/web.php',
        api: __DIR__.'/../routes/api.php',
        commands: __DIR__.'/../routes/console.php',
        health: '/up',
    )
    ->withMiddleware(function (Middleware $middleware) {
        $middleware->alias(['verified' => \\App\\Http\\Middleware\\EnsureVerified::class]);
    })
    ->withExceptions(function (Exceptions $exceptions) {
        //
    })->create();
""",
    )
    write(
        tmp_path,
        WEB,
        """<?php

use App\\Http\\Controllers\\Admin\\UserController;
use App\\Http\\Controllers\\PostController;
use App\\Http\\Controllers\\ProfileController;
use Illuminate\\Support\\Facades\\Route;

Route::get('/', function () {
    return view('welcome');
});

Route::get('/dashboard', function () {
    return view('dashboard');
})->middleware(['auth', 'verified'])->name('dashboard');

Route::middleware('auth')->group(function () {
    Route::get('/profile', [ProfileController::class, 'edit'])->name('profile.edit');
    Route::patch('/profile', [ProfileController::class, 'update'])->name('profile.update');
    Route::delete('/profile', [ProfileController::class, 'destroy'])->name('profile.destroy');
});

Route::resource('posts', PostController::class)->middleware('auth')->except(['show']);
Route::get('/posts/{post}', [PostController::class, 'show'])
    ->whereNumber('post')
    ->can('view', 'post')
    ->name('posts.show');

Route::prefix('admin')->name('admin.')->middleware(['auth', 'can:admin'])->group(function () {
    Route::get('/users/{user}', [UserController::class, 'show'])->withTrashed();
    Route::resource('users', UserController::class)->only(['index']);
});

require __DIR__.'/auth.php';
""",
    )
    write(
        tmp_path,
        "routes/auth.php",
        """<?php

use App\\Http\\Controllers\\Auth\\AuthenticatedSessionController;
use Illuminate\\Support\\Facades\\Route;

Route::middleware('guest')->group(function () {
    Route::get('login', [AuthenticatedSessionController::class, 'create'])->name('login');
    Route::post('login', [AuthenticatedSessionController::class, 'store']);
});

Route::middleware('auth')->group(function () {
    Route::post('logout', [AuthenticatedSessionController::class, 'destroy'])->name('logout');
});
""",
    )
    write(
        tmp_path,
        "routes/api.php",
        """<?php

use Illuminate\\Http\\Request;
use Illuminate\\Support\\Facades\\Route;

Route::middleware('auth:sanctum')->get('/user', function (Request $request) {
    return $request->user();
});

Route::middleware('auth:sanctum')->apiResource('posts', PostController::class);
""",
    )
    write(
        tmp_path,
        "routes/console.php",
        "<?php\nuse Illuminate\\Support\\Facades\\Artisan;\n"
        "Artisan::command('inspire', function () { $this->comment('x'); });\n",
    )
    write(
        tmp_path,
        "routes/channels.php",
        "<?php\nBroadcast::channel('App.Models.User.{id}', fn ($user, $id) => 1);\n",
    )
    write(
        tmp_path,
        "app/Http/Middleware/Track.php",
        "<?php\nclass Track { function handle($request) {"
        " $n = Route::currentRouteName(); $a = $request->get('a');"
        " return collect($x)->get('y'); } }\n",
    )
    result = run_routes(tmp_path)
    assert row(result).status == "complete"
    assert row(result).detail == ""
    got = pairs(result)
    assert ("GET", "/up") in got
    assert ("GET", "/api/user") in got
    assert ("GET", "/api/posts/{post}") in got
    assert ("GET", "/admin/users/{user}") in got
    assert ("GET", "/login") in got and ("POST", "/logout") in got
    assert ("GET", "/posts/{post}") in got
    assert ("GET", "/posts") in got and ("GET", "/admin/users") in got
    assert ("DELETE", "/posts/{post}") in got


def test_laravel_resource_options_and_package_macros(tmp_path):
    text = """<?php
Route::resource('photos', 'PhotoController');
Route::resource('s', 'sk_live_SECRET');
Route::resource('p', C::class, ['only' => ['index']]);
Route::resource('q', C::class, ['parameters' => ['q' => 'x']]);
Route::resource('r', C::class, ['names' => ['index' => 'r.list']]);
Route::inertia('/about', 'About');
Route::livewire('/lw', Comp::class);
"""
    laravel(tmp_path, text)
    result = run_routes(tmp_path)
    got = triples(result)
    # a legacy string controller counts; any other literal stays out of the column
    assert ("GET", "/photos", "PhotoController@index") in got
    assert ("GET", "/s", "(inline)") in got
    assert "sk_live_SECRET" not in everything(result)
    assert [t for t in got if t[1] == "/p"] == [("GET", "/p", "C@index")]
    assert ("GET", "/r", "C@index") in got and ("GET", "/q", "C@index") in got
    assert ("GET", "/about", "(inline)") in got and ("GET", "/lw", "Comp") in got
    assert row(result).detail == f"{WEB}:{at(text, 'parameters')}"


def test_laravel_package_route_registrations(tmp_path):
    composer(tmp_path, LARAVEL)
    text = """<?php
class Providers
{
    public function boot()
    {
        Broadcast::routes();
        Passport::routes();
        Auth::routes();
    }
}
"""
    write(tmp_path, "app/Providers/Providers.php", text)
    result = run_routes(tmp_path)
    assert pairs(result) == [
        ("GET", "/broadcasting/auth"),
        ("POST", "/broadcasting/auth"),
    ]
    assert row(result).detail == "; ".join(
        f"app/Providers/Providers.php:{at(text, n)}" for n in ("Passport", "Auth::")
    )
    write(
        tmp_path,
        "app/Providers/Providers.php",
        "<?php\nclass P { function boot() { Broadcast::routes(['middleware' => ['auth']]); } }\n",
    )
    assert row(run_routes(tmp_path)).detail == "app/Providers/Providers.php:2"


def test_laravel_ambiguous_module_route_file_is_a_site(tmp_path):
    composer(tmp_path, LARAVEL)
    for module in ("A", "B"):
        write(
            tmp_path,
            f"Modules/{module}/Routes/web.php",
            f"<?php\nRoute::get('/{module.lower()}', fn () => 1);\n",
        )
    write(
        tmp_path,
        "Modules/A/Providers/R.php",
        "<?php\nclass R { function map() {\n"
        "Route::prefix('a')->group(module_path('A', '/Routes/web.php'));\n} }\n",
    )
    result = run_routes(tmp_path)
    assert row(result).status == "partial"
    assert "Modules/A/Providers/R.php:3" in row(result).detail


def test_laravel_include_cycle_is_a_site(tmp_path):
    composer(tmp_path, LARAVEL)
    write(
        tmp_path,
        WEB,
        "<?php\nRoute::get('/w', fn () => 1);\nrequire __DIR__.'/auth.php';\n",
    )
    write(
        tmp_path,
        "routes/auth.php",
        "<?php\nRoute::get('/a', fn () => 1);\nrequire __DIR__.'/web.php';\n",
    )
    result = run_routes(tmp_path)
    assert row(result).status == "partial"


def test_laravel_nested_route_files_and_load_routes_from(tmp_path):
    composer(tmp_path, LARAVEL)
    write(
        tmp_path,
        "routes/api.php",
        "<?php\nRoute::prefix('v1')->group(base_path('routes/api/v1.php'));\n",
    )
    write(tmp_path, "routes/api/v1.php", "<?php\nRoute::get('/u', fn () => 1);\n")
    write(
        tmp_path,
        "app/Providers/P.php",
        "<?php\nclass P { function boot() {\n"
        "$this->loadRoutesFrom(__DIR__.'/../../routes/pkg.php');\n} }\n",
    )
    write(tmp_path, "routes/pkg.php", "<?php\nRoute::get('/pkg', fn () => 1);\n")
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/api/v1/u"), ("GET", "/pkg")]
    assert row(result).status == "complete"


def test_laravel_variable_held_group_and_loops_are_sites(tmp_path):
    text = """<?php
$api = Route::prefix('api');
$api->group(function () { Route::get('/x', fn () => 1); });
foreach ($locales as $l) {
    Route::prefix($l)->group(fn () => Route::get('/z', fn () => 1));
}
if (app()->isLocal()) {
    Route::get('/debug', fn () => 1);
}
"""
    laravel(tmp_path, text)
    result = run_routes(tmp_path)
    assert row(result).detail == "; ".join(
        sorted(f"{WEB}:{at(text, n)}" for n in ("$api = ", "Route::prefix($l)"))
    )
    assert ("GET", "/debug") in pairs(result)


def test_laravel_long_concatenated_include_path_does_not_crash(tmp_path):
    text = (
        "<?php\nRoute::prefix('a')->group(base_path("
        + "'a'." * 4000
        + "'b'));\nRoute::get('/ok', fn () => 1);\n"
    )
    laravel(tmp_path, text)
    result = run_routes(tmp_path)
    assert ("GET", "/ok") in pairs(result)
    assert row(result).status == "partial"
    assert not [w for w in result.warnings if "adapter failed" in w]


def test_laravel_scopes_do_not_share_route_files(tmp_path):
    composer(tmp_path, LARAVEL, "apps/one")
    composer(tmp_path, LARAVEL, "apps/two")
    for app in ("one", "two"):
        write(
            tmp_path,
            f"apps/{app}/routes/web.php",
            f"<?php\nRoute::get('/{app}', fn () => 1);\n",
        )
    result = run_routes(tmp_path)
    assert rows_of(result, "apps/one/routes/web.php") == [
        ["GET", "/one", "(inline)", "apps/one/routes/web.php", ""]
    ]
    assert row(result, "apps/one").status == "complete"
    assert row(result, "apps/two").status == "complete"


# --- Symfony ------------------------------------------------------------------

BLOG = "src/Controller/BlogController.php"


def symfony(root: Path, rel: str, text: str) -> None:
    composer(root, SYMFONY)
    write(root, rel, text)


def test_symfony_class_prefix_methods_and_named_path(tmp_path):
    symfony(
        tmp_path,
        BLOG,
        """<?php
namespace App\\Controller;

use Symfony\\Bundle\\FrameworkBundle\\Controller\\AbstractController;
use Symfony\\Component\\Routing\\Attribute\\Route;

#[Route('/blog', name: 'blog_')]
class BlogController extends AbstractController
{
    #[Route('/', name: 'index', methods: ['GET'])]
    public function index(): Response {}

    #[Route(path: '/posts/{slug}', name: 'post', methods: ['GET', 'HEAD'])]
    public function show(string $slug): Response {}

    #[Route('/comment/{id<\\d+>}/new', methods: 'POST')]
    public function commentNew(): Response {}

    #[Route('/any')]
    public function any(): Response {}

    #[Route('/multi', name: 'a'), Route('/multi2', name: 'b')]
    public function multi(): Response {}

    public function helper(): void {}
}
""",
    )
    result = run_routes(tmp_path)
    assert rows_of(result, BLOG) == [
        ["GET", "/blog", "BlogController.index", BLOG, ""],
        ["ANY", "/blog/any", "BlogController.any", BLOG, ""],
        ["POST", "/blog/comment/{id}/new", "BlogController.commentNew", BLOG, ""],
        ["ANY", "/blog/multi", "BlogController.multi", BLOG, ""],
        ["ANY", "/blog/multi2", "BlogController.multi", BLOG, ""],
        ["GET", "/blog/posts/{slug}", "BlogController.show", BLOG, ""],
        ["HEAD", "/blog/posts/{slug}", "BlogController.show", BLOG, ""],
    ]
    assert (row(result).status, row(result).detail) == ("complete", "")


def test_symfony_invokable_controller_and_unrouted_class(tmp_path):
    symfony(
        tmp_path,
        "src/Controller/PingController.php",
        """<?php
use Symfony\\Component\\Routing\\Attribute\\Route;

#[Route('/ping', methods: ['GET'])]
final class PingController
{
    public function __invoke(): Response {}
}
""",
    )
    write(
        tmp_path,
        "src/Service/Mailer.php",
        "<?php\nclass Mailer { public function send() {} }\n",
    )
    result = run_routes(tmp_path)
    assert triples(result) == [("GET", "/ping", "PingController")]
    assert row(result).status == "complete"


def test_symfony_alias_and_qualified_attribute_names(tmp_path):
    symfony(
        tmp_path,
        "src/Controller/AController.php",
        """<?php
use Symfony\\Component\\Routing\\Attribute\\Route as R;
use Symfony\\Component\\Routing\\Annotation;

class AController
{
    #[R('/aliased')]
    public function a() {}

    #[\\Symfony\\Component\\Routing\\Annotation\\Route('/qualified')]
    public function b() {}

    #[Annotation\\Route('/namespaced')]
    public function c() {}
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [
        ("ANY", "/aliased"),
        ("ANY", "/namespaced"),
        ("ANY", "/qualified"),
    ]


def test_symfony_dynamic_path_methods_and_localised_are_sites(tmp_path):
    text = """<?php
use Symfony\\Component\\Routing\\Attribute\\Route;

class DController
{
    #[Route(self::BASE . '/x')]
    public function a() {}

    #[Route('/b', methods: self::VERBS)]
    public function b() {}

    #[Route(['en' => '/about', 'fr' => '/a-propos'])]
    public function c() {}

    #[Route(path: Paths::LOGIN)]
    public function d() {}

    #[Route('/ok', methods: ['GET'])]
    public function e() {}
}
"""
    symfony(tmp_path, "src/Controller/DController.php", text)
    result = run_routes(tmp_path)
    expected = [at(text, n) for n in ("self::BASE", "self::VERBS", "'en'", "Paths::")]
    assert row(result).status == "partial"
    assert row(result).detail == "; ".join(
        sorted(f"src/Controller/DController.php:{n}" for n in expected)
    )
    assert pairs(result) == [("GET", "/ok")]


def test_symfony_dynamic_class_prefix_is_a_site(tmp_path):
    text = """<?php
use Symfony\\Component\\Routing\\Attribute\\Route;

#[Route(Prefix::BLOG)]
class EController
{
    #[Route('/x')]
    public function a() {}
}
"""
    symfony(tmp_path, "src/Controller/EController.php", text)
    result = run_routes(tmp_path)
    assert (
        row(result).detail == f"src/Controller/EController.php:{at(text, 'Prefix::')}"
    )


def test_symfony_docblock_annotations(tmp_path):
    symfony(
        tmp_path,
        "src/Controller/LegacyController.php",
        """<?php
use Symfony\\Component\\Routing\\Annotation\\Route;

/**
 * @Route("/legacy", name="legacy_")
 */
class LegacyController
{
    /**
     * @Route("/list/{page}", name="list", methods={"GET", "POST"})
     */
    public function list() {}

    /**
     * Shows one.
     *
     * @Route(path="/one", methods="GET")
     */
    public function one() {}
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [
        ("GET", "/legacy/list/{page}"),
        ("GET", "/legacy/one"),
        ("POST", "/legacy/list/{page}"),
    ]
    assert row(result).status == "complete"


def test_symfony_docblock_above_a_line_comment_is_still_read(tmp_path):
    symfony(
        tmp_path,
        "src/Controller/CController.php",
        """<?php
class CController
{
    /**
     * @Route("/c", methods={"PUT"})
     */
    // phpcs:ignore
    public function c() {}
}
""",
    )
    assert pairs(run_routes(tmp_path)) == [("PUT", "/c")]


def test_symfony_older_skeleton_imports_are_followed(tmp_path):
    composer(tmp_path, SYMFONY)
    write(
        tmp_path,
        "config/routes.yaml",
        """controllers:
    resource:
        path: ../src/Controller/
        namespace: App\\Controller
    type: attribute

kernel:
    resource: App\\Kernel
    type: attribute
""",
    )
    write(tmp_path, "src/Kernel.php", "<?php\nnamespace App;\nclass Kernel {}\n")
    write(
        tmp_path,
        "src/Controller/HomeController.php",
        "<?php\nuse Symfony\\Component\\Routing\\Attribute\\Route;\n"
        "class HomeController { #[Route('/', name: 'home')] public function a() {} }\n",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("ANY", "/")]
    assert row(result).status == "complete"


def test_symfony_routing_controllers_import_keeps_its_prefix(tmp_path):
    composer(tmp_path, SYMFONY)
    write(
        tmp_path,
        "config/routes.yaml",
        "controllers:\n    resource: routing.controllers\n    prefix: /{_locale}\n"
        "    defaults:\n        _locale: '%app.locale%'\n",
    )
    write(
        tmp_path,
        "src/Controller/BlogController.php",
        "<?php\nuse Symfony\\Component\\Routing\\Attribute\\Route;\n"
        "class BlogController { #[Route('/blog/{page<\\d+>?1}')] public function a() {} }\n",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("ANY", "/{_locale}/blog/{page}")]
    assert row(result).status == "complete"


def test_symfony_other_service_route_loaders_are_sites(tmp_path):
    composer(tmp_path, SYMFONY)
    yaml = """_security_logout:
    resource: security.route_loader.logout
    type: service
custom:
    resource: app.route_loader
    type: service
"""
    write(tmp_path, "config/routes/security.yaml", yaml)
    result = run_routes(tmp_path)
    assert row(result).detail == f"config/routes/security.yaml:{at(yaml, 'custom:')}"


def test_symfony_inline_requirements_and_defaults_are_not_in_the_path(tmp_path):
    symfony(
        tmp_path,
        "src/Controller/LocController.php",
        r"""<?php
use Symfony\Component\Routing\Attribute\Route;

#[Route('/{_locale<en|fr>?en}')]
class LocController
{
    #[Route('/page/{page<\d{1,3}>?1}/{slug:post}/{opt?}', methods: ['GET'])]
    public function a() {}

    #[Route('/{x<a|b>}/{y<[^/]+>}')]
    public function b() {}
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [
        ("ANY", "/{_locale}/{x}/{y}"),
        ("GET", "/{_locale}/page/{page}/{slug:post}/{opt}"),
    ]


def test_symfony_foreign_namespace_route_and_verb_attributes_are_routes(tmp_path):
    symfony(
        tmp_path,
        "src/Controller/UserController.php",
        """<?php
use FOS\\RestBundle\\Controller\\Annotations as Rest;

class UserController
{
    #[Rest\\Get('/users/{id}')]
    public function a() {}

    #[
        Rest\\Post(
            path: '/users', // create
        )
    ]
    public function b() {}
}
""",
    )
    write(
        tmp_path,
        "src/Controller/OrderController.php",
        """<?php
use FOS\\RestBundle\\Controller\\Annotations\\Route;

#[Route('/orders')]
class OrderController
{
    #[Route('/{id}', methods: ['GET'])]
    public function show() {}
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [
        ("GET", "/orders/{id}"),
        ("GET", "/users/{id}"),
        ("POST", "/users"),
    ]
    assert row(result).status == "complete"


def test_symfony_unreadable_or_unknown_verb_attributes_are_sites(tmp_path):
    text = """<?php
use App\\Attr\\Get;
use FOS\\RestBundle\\Controller\\Annotations as Rest;

class XController
{
    #[Rest\\Get]
    public function a() {}

    #[Get('/b')]
    public function b() {}

    #[Rest\\Delete(self::PATH)]
    public function c() {}

    #[Rest\\Prefix('/api')]
    public function d() {}
}
"""
    symfony(tmp_path, "src/Controller/XController.php", text)
    result = run_routes(tmp_path)
    assert pairs(result) == []
    assert row(result).detail == "; ".join(
        sorted(
            f"src/Controller/XController.php:{at(text, n)}"
            for n in ("#[Rest\\Get]", "#[Get(", "self::PATH", "Prefix")
        )
    )


def test_symfony_documentation_attributes_named_like_verbs_are_not_routes(tmp_path):
    symfony(
        tmp_path,
        "src/Controller/DocController.php",
        """<?php
use OpenApi\\Attributes as OA;
use Symfony\\Component\\Routing\\Attribute\\Route;

class DocController
{
    #[Route('/docs/x', methods: ['GET'])]
    #[OA\\Get(path: '/docs/x', summary: 'Get x')]
    #[OA\\Response(response: 200, description: 'ok')]
    public function a() {}
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/docs/x")]
    assert row(result).status == "complete"


def test_symfony_docblock_verb_annotations_and_sensio_method(tmp_path):
    symfony(
        tmp_path,
        "src/Controller/OldController.php",
        """<?php
use FOS\\RestBundle\\Controller\\Annotations as Rest;
use OpenApi\\Annotations as OA;
use Sensio\\Bundle\\FrameworkExtraBundle\\Configuration\\Method;
use Symfony\\Component\\Routing\\Annotation\\Route;

class OldController
{
    /**
     * @Rest\\Get("/rest/{id}")
     * @OA\\Get(path="/rest/{id}")
     */
    public function a() {}

    /**
     * @Route("/legacy/{id}", name="show")
     * @Method({"POST", "PUT"})
     */
    public function b() {}

    /**
     * @Route("/one")
     * @Method("DELETE")
     */
    public function c() {}
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [
        ("DELETE", "/one"),
        ("GET", "/rest/{id}"),
        ("POST", "/legacy/{id}"),
        ("PUT", "/legacy/{id}"),
    ]
    assert row(result).status == "complete"


def test_singular_test_directory_is_product_code_plural_tests_is_not(tmp_path):
    composer(tmp_path, LARAVEL)
    write(
        tmp_path,
        "Modules/Test/routes/web.php",
        "<?php\nRoute::get('/module-test', fn () => 1);\n",
    )
    write(
        tmp_path,
        "tests/Feature/RoutesTest.php",
        "<?php\nRoute::get($dyn, fn () => 1);\n",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/module-test")]
    assert row(result).detail == ""


def test_laravel_literal_include_never_binds_to_an_unrelated_suffix_match(tmp_path):
    composer(tmp_path, LARAVEL)
    text = "<?php\nRoute::prefix('x')->group('api.php');\n"
    write(tmp_path, WEB, text)
    write(
        tmp_path,
        "vendor_like/elsewhere/api.php",
        "<?php\nRoute::get('/far', fn () => 1);\n",
    )
    result = run_routes(tmp_path)
    assert ("GET", "/x/far") not in pairs(result)
    assert f"{WEB}:2" in row(result).detail.split("; ")


def test_symfony_docblock_with_unreadable_arguments_is_a_site(tmp_path):
    text = """<?php
class LegacyController
{
    /**
     * @Route(PATH_CONST, name="x")
     */
    public function list() {}
}
"""
    symfony(tmp_path, "src/Controller/LegacyController.php", text)
    result = run_routes(tmp_path)
    assert row(result).detail == (
        f"src/Controller/LegacyController.php:{at(text, '@Route')}"
    )


@pytest.mark.parametrize("bare", ["@Route", "@Rest\\Get", "@Route ", "@Post"])
def test_symfony_bare_docblock_annotation_is_a_site(tmp_path, bare):
    text = f"""<?php
class LegacyController
{{
    /**
     * {bare}
     */
    public function list() {{}}
}}
"""
    symfony(tmp_path, "src/Controller/LegacyController.php", text)
    result = run_routes(tmp_path)
    assert row(result).detail == (
        f"src/Controller/LegacyController.php:{at(text, bare.strip())}"
    )


def test_symfony_docblock_words_that_merely_start_like_an_annotation_are_prose(
    tmp_path,
):
    text = """<?php
class QuietController
{
    /**
     * @Getter @Gets @Routes are not route annotations.
     */
    public function list() {}
}
"""
    symfony(tmp_path, "src/Controller/QuietController.php", text)
    assert row(run_routes(tmp_path)).status == "complete"


def test_symfony_inherited_routes_are_sites(tmp_path):
    base = """<?php
use Symfony\\Component\\Routing\\Attribute\\Route;

abstract class CrudController
{
    #[Route('/', methods: ['GET'])]
    public function index() {}
}
"""
    sub = """<?php
use Symfony\\Component\\Routing\\Attribute\\Route;

#[Route('/users')]
class UserCrudController extends CrudController
{
}
"""
    symfony(tmp_path, "src/Controller/CrudController.php", base)
    write(tmp_path, "src/Controller/Admin/UserCrudController.php", sub)
    result = run_routes(tmp_path)
    assert row(result).status == "partial"
    assert row(result).detail == "; ".join(
        [
            f"src/Controller/Admin/UserCrudController.php:{at(sub, 'class UserCrud')}",
            f"src/Controller/CrudController.php:{at(base, '#[Route')}",
        ]
    )


def test_symfony_yaml_attribute_resource_prefix(tmp_path):
    composer(tmp_path, SYMFONY)
    write(
        tmp_path,
        "config/routes.yaml",
        """controllers:
    resource:
        path: ../src/Controller/Web/
        namespace: App\\Controller\\Web
    type: attribute

api:
    resource: ../src/Controller/Api/
    type: attribute
    prefix: /api/v1
""",
    )
    ctrl = (
        "<?php\nuse Symfony\\Component\\Routing\\Attribute\\Route;\n"
        "class C { #[Route('/%s')] public function a() {} }\n"
    )
    write(tmp_path, "src/Controller/Web/HomeController.php", ctrl % "home")
    write(tmp_path, "src/Controller/Api/UserController.php", ctrl % "users")
    result = run_routes(tmp_path)
    assert pairs(result) == [("ANY", "/api/v1/users"), ("ANY", "/home")]
    assert row(result).status == "complete"


def test_symfony_yaml_explicit_route_xml_and_php_config_are_sites(tmp_path):
    composer(tmp_path, SYMFONY)
    yaml = """controllers:
    resource: ../src/Controller/
    type: attribute

health:
    path: /health
    controller: App\\Controller\\HealthController::check
"""
    write(tmp_path, "config/routes.yaml", yaml)
    write(tmp_path, "config/routes/extra.xml", "<routes/>\n")
    php = """<?php
use Symfony\\Component\\Routing\\Loader\\Configurator\\RoutingConfigurator;

return static function (RoutingConfigurator $routes): void {
    $routes->add('home', '/')->controller([HomeController::class, 'index']);
    $routes->import('../src/Legacy/', 'attribute');
};
"""
    write(tmp_path, "config/routes/legacy.php", php)
    write(
        tmp_path,
        "src/Controller/HomeController.php",
        "<?php\nuse Symfony\\Component\\Routing\\Attribute\\Route;\n"
        "class HomeController { #[Route('/h')] public function a() {} }\n",
    )
    result = run_routes(tmp_path)
    assert row(result).status == "partial"
    assert row(result).detail == "; ".join(
        [
            f"config/routes.yaml:{at(yaml, 'health:')}",
            "config/routes/extra.xml:1",
            f"config/routes/legacy.php:{at(php, '->add(')}",
            f"config/routes/legacy.php:{at(php, '->import(')}",
        ]
    )
    assert pairs(result) == [("ANY", "/h")]


def test_symfony_controller_outside_any_resource_is_a_site(tmp_path):
    composer(tmp_path, SYMFONY)
    write(
        tmp_path,
        "config/routes.yaml",
        "controllers:\n    resource: ../src/Controller/\n    type: attribute\n",
    )
    write(
        tmp_path,
        "src/Other/OddController.php",
        "<?php\nuse Symfony\\Component\\Routing\\Attribute\\Route;\n"
        "class OddController { #[Route('/odd')] public function a() {} }\n",
    )
    result = run_routes(tmp_path)
    assert row(result).detail == "src/Other/OddController.php:3"
    assert pairs(result) == [("ANY", "/odd")]


def test_symfony_file_order_independence(tmp_path):
    composer(tmp_path, SYMFONY)
    # the subclass sorts before the base class that holds the routes
    write(
        tmp_path,
        "src/Controller/AaaController.php",
        "<?php\nclass AaaController extends ZzzBase {}\n",
    )
    write(
        tmp_path,
        "src/Controller/ZzzBase.php",
        "<?php\nuse Symfony\\Component\\Routing\\Attribute\\Route;\n"
        "class ZzzBase { #[Route('/z')] public function a() {} }\n",
    )
    result = run_routes(tmp_path)
    assert row(result).status == "partial"
    assert "src/Controller/AaaController.php:2" in row(result).detail


def test_symfony_non_route_get_calls_are_ignored(tmp_path):
    symfony(
        tmp_path,
        "src/Controller/MiscController.php",
        """<?php
use Symfony\\Component\\Routing\\Attribute\\Route;

class MiscController extends AbstractController
{
    #[Route('/m', methods: ['GET'])]
    public function m(Request $request)
    {
        $a = $request->get('page');
        $b = $this->get('app.service');
        $c = $this->container->get(Foo::class);
        $d = $client->get('/api/users', ['headers' => []]);
        $e = $collection->get('x');
        return $this->generateUrl('m');
    }
}
""",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == [("GET", "/m")]
    assert row(result).status == "complete"


def test_symfony_hostile_files_do_not_crash(tmp_path):
    symfony(
        tmp_path,
        "src/Controller/BrokenController.php",
        "<?php\nclass BrokenController { #[Route('/a'\n public function x( {\n",
    )
    nest = "<?php\n" + "if (true) {\n" * 3000 + "}\n" * 3000
    write(tmp_path, "src/Controller/DeepController.php", nest + "\n// Route\n")
    result = run_routes(tmp_path)
    assert row(result).status == "partial"
    assert not [w for w in result.warnings if "adapter failed" in w]


def test_typical_symfony_app_reaches_complete(tmp_path):
    composer(tmp_path, SYMFONY)
    write(
        tmp_path,
        "config/routes.yaml",
        "controllers:\n    resource: routing.controllers\n",
    )
    write(
        tmp_path,
        "config/routes/security.yaml",
        "_security_logout:\n    resource: security.route_loader.logout\n    type: service\n",
    )
    write(
        tmp_path,
        "config/routes/framework.yaml",
        "when@dev:\n    _errors:\n"
        "        resource: '@FrameworkBundle/Resources/config/routing/errors.xml'\n"
        "        prefix: /_error\n",
    )
    write(
        tmp_path,
        "config/routes/web_profiler.yaml",
        "when@dev:\n    web_profiler_wdt:\n"
        "        resource: '@WebProfilerBundle/Resources/config/routing/wdt.xml'\n"
        "        prefix: /_wdt\n"
        "    web_profiler_profiler:\n"
        "        resource: '@WebProfilerBundle/Resources/config/routing/profiler.xml'\n"
        "        prefix: /_profiler\n",
    )
    write(
        tmp_path,
        "src/Kernel.php",
        "<?php\nnamespace App;\nuse Symfony\\Bundle\\FrameworkBundle\\Kernel\\MicroKernelTrait;\n"
        "class Kernel extends BaseKernel { use MicroKernelTrait; }\n",
    )
    write(
        tmp_path,
        BLOG,
        r"""<?php
namespace App\Controller;

use App\Entity\Post;
use Symfony\Bridge\Doctrine\Attribute\MapEntity;
use Symfony\Bundle\FrameworkBundle\Controller\AbstractController;
use Symfony\Component\HttpKernel\Attribute\Cache;
use Symfony\Component\Routing\Attribute\Route;
use Symfony\Component\Security\Http\Attribute\IsGranted;

#[Route('/{_locale<en|fr>}/blog', name: 'blog_')]
class BlogController extends AbstractController
{
    #[Route('/', name: 'index', defaults: ['page' => '1'], methods: ['GET'])]
    #[Route('/page/{page<[1-9]\d*>}', name: 'index_paginated', methods: ['GET'])]
    #[Cache(smaxage: 10)]
    public function index(Request $request, int $page): Response
    {
        $tag = $request->query->get('tag');
        return $this->render('blog/index.html.twig');
    }

    #[Route('/posts/{slug}', name: 'post', methods: ['GET'])]
    public function postShow(Post $post): Response
    {
        return $this->render('blog/post_show.html.twig');
    }

    #[Route('/comment/{postSlug}/new', name: 'comment_new', methods: ['POST'])]
    #[IsGranted('IS_AUTHENTICATED')]
    public function commentNew(
        Request $request,
        #[MapEntity(mapping: ['postSlug' => 'slug'])] Post $post,
    ): Response {
        return $this->redirectToRoute('blog_post', ['slug' => $post->getSlug()]);
    }
}
""",
    )
    write(
        tmp_path,
        "src/Controller/Admin/PostController.php",
        r"""<?php
namespace App\Controller\Admin;

use Symfony\Component\Routing\Attribute\Route;
use Symfony\Component\Security\Http\Attribute\IsGranted;

#[Route('/admin/post')]
#[IsGranted('ROLE_ADMIN')]
final class PostController extends AbstractController
{
    #[Route('/', name: 'admin_post_index', methods: ['GET'])]
    public function index(): Response {}

    #[Route('/new', name: 'admin_post_new', methods: ['GET', 'POST'])]
    public function new(Request $request): Response {}

    #[Route('/{id<\d+>}', name: 'admin_post_show', methods: ['GET'])]
    public function show(Post $post): Response {}

    #[Route('/{id<\d+>}/delete', name: 'admin_post_delete', methods: ['POST'])]
    #[IsGranted('POST_DELETE', subject: 'post')]
    public function delete(Post $post): Response {}
}
""",
    )
    write(
        tmp_path,
        "src/Controller/SecurityController.php",
        r"""<?php
namespace App\Controller;

use Symfony\Component\Routing\Attribute\Route;

class SecurityController extends AbstractController
{
    #[Route('/login', name: 'app_login')]
    public function login(AuthenticationUtils $authenticationUtils): Response {}

    #[Route('/logout', name: 'app_logout', methods: ['GET'])]
    public function logout(): void {}
}
""",
    )
    write(
        tmp_path,
        "src/Service/Notifier.php",
        "<?php\nclass Notifier { function n($m) { return $m->get('x'); } }\n",
    )
    result = run_routes(tmp_path)
    assert row(result).status == "complete"
    assert row(result).detail == ""
    assert pairs(result) == sorted(
        [
            ("GET", "/{_locale}/blog"),
            ("GET", "/{_locale}/blog/page/{page}"),
            ("GET", "/{_locale}/blog/posts/{slug}"),
            ("POST", "/{_locale}/blog/comment/{postSlug}/new"),
            ("GET", "/admin/post"),
            ("GET", "/admin/post/new"),
            ("POST", "/admin/post/new"),
            ("GET", "/admin/post/{id}"),
            ("POST", "/admin/post/{id}/delete"),
            ("ANY", "/login"),
            ("GET", "/logout"),
        ]
    )


def test_symfony_foreign_routes_traits_and_custom_attributes_are_sites(tmp_path):
    symfony(
        tmp_path,
        "src/Entity/Book.php",
        "<?php\nuse ApiPlatform\\Metadata\\ApiResource;\n#[ApiResource]\nclass Book {}\n",
    )
    write(
        tmp_path,
        "src/Controller/Shared.php",
        "<?php\nuse Symfony\\Component\\Routing\\Attribute\\Route;\n"
        "trait Shared { #[Route('/t')] public function t() {} }\n",
    )
    # the attribute usage sorts before the class that defines it and never
    # mentions `Route` itself
    write(
        tmp_path,
        "src/Controller/AdminController.php",
        "<?php\nclass AdminController { #[AdminRoute('/x')] public function t() {} }\n",
    )
    write(
        tmp_path,
        "src/Attr/AdminRoute.php",
        "<?php\nuse Symfony\\Component\\Routing\\Attribute\\Route;\n"
        "#[\\Attribute]\nclass AdminRoute extends Route {}\n",
    )
    result = run_routes(tmp_path)
    assert pairs(result) == []
    assert row(result).detail == "; ".join(
        [
            "src/Controller/AdminController.php:2",
            "src/Controller/Shared.php:3",
            "src/Entity/Book.php:3",
        ]
    )


def test_symfony_unreadable_and_hostile_yaml_are_sites(tmp_path):
    composer(tmp_path, SYMFONY)
    write(tmp_path, "config/routes.yaml", "a: [\n")
    write(tmp_path, "config/routes/deep.yaml", "a: " + "[" * 5000 + "]" * 5000 + "\n")
    write(
        tmp_path,
        "config/routes/anchors.yaml",
        "x: &a\n  resource: ../../src/C/\n  type: attribute\ny: *a\n",
    )
    result = run_routes(tmp_path)
    assert row(result).detail == "config/routes.yaml:1; config/routes/deep.yaml:1"
    assert not [w for w in result.warnings if "adapter failed" in w]


def test_symfony_import_of_a_bundle_or_other_type_is_a_site(tmp_path):
    composer(tmp_path, SYMFONY)
    yaml = """api_platform:
    resource: .
    type: api_platform
    prefix: /api
sonata:
    resource: '@SonataAdminBundle/Resources/config/routing/sonata_admin.xml'
    prefix: /admin
filtered:
    resource: ../src/Controller/
    type: attribute
    exclude: ['../src/Controller/Legacy']
"""
    write(tmp_path, "config/routes.yaml", yaml)
    result = run_routes(tmp_path)
    assert row(result).detail == "; ".join(
        f"config/routes.yaml:{at(yaml, n)}"
        for n in ("api_platform:", "sonata:", "filtered:")
    )


# --- Symbols ------------------------------------------------------------------


def sym_rows(result) -> list[tuple[str, str, str]]:
    return sorted((r[0], r[1], r[2]) for s in result.sections for r in cells(s.l2_md))


def php_row(result, scope: str = "."):
    (found,) = [r for r in result.coverage if r.scope == scope and r.framework == "php"]
    return found


def test_php_symbols_types_cases_and_constants(tmp_path):
    composer(tmp_path, LARAVEL)
    write(
        tmp_path,
        "app/Models.php",
        r"""<?php
namespace App;

interface HasName
{
    const PREFIX = 'x';
    public function name(): string;
}

trait Loggable
{
    public const CHANNEL = 'app';
    private const HIDDEN = 1;
}

abstract class Base
{
    const A = 1;
    public const B = 2, C = 3;
    protected const D = 4;
    private const E = 5;
    final public const F = 6;
    public static $notAConst = 7;
}

final class User extends Base implements HasName
{
    use Loggable;
    public function name(): string { return 'u'; }
}

enum Suit: string
{
    case Hearts = 'H';
    case Spades = 'S';
    const Wild = self::Spades;
    private const Secret = 'x';
}

enum Status
{
    case Active;
    case Inactive;
}

function helper() {}
$anonymous = new class { const NOPE = 1; };
""",
    )
    result = run_symbols(tmp_path)
    f = "app/Models.php"
    assert sym_rows(result) == sorted(
        [
            ("Base", "class", f),
            ("Base::A", "member", f),
            ("Base::B", "member", f),
            ("Base::C", "member", f),
            ("Base::F", "member", f),
            ("HasName", "interface", f),
            ("HasName::PREFIX", "member", f),
            ("Loggable", "class", f),
            ("Loggable::CHANNEL", "member", f),
            ("Status", "enum", f),
            ("Status.Active", "member", f),
            ("Status.Inactive", "member", f),
            ("Suit", "enum", f),
            ("Suit.Hearts", "member", f),
            ("Suit.Spades", "member", f),
            ("Suit::Wild", "member", f),
            ("User", "class", f),
        ]
    )
    assert php_row(result).status == "complete"


def test_php_symbols_braced_namespaces_and_conditional_declarations(tmp_path):
    composer(tmp_path, SYMFONY)
    write(
        tmp_path,
        "src/legacy.php",
        """<?php
namespace One {
    class A {}
}
namespace Two {
    interface B {}
}
if (!class_exists('Shim')) {
    class Shim {}
}
function wrapper() { class InsideFunction {} }
""",
    )
    result = run_symbols(tmp_path)
    f = "src/legacy.php"
    assert sym_rows(result) == [
        ("A", "class", f),
        ("B", "interface", f),
        ("Shim", "class", f),
    ]


def test_php_symbols_never_emit_values(tmp_path):
    composer(tmp_path, LARAVEL)
    write(
        tmp_path,
        "app/Secrets.php",
        """<?php
class Config
{
    const API_KEY = 'sk_live_CONSTSECRET123';
    public const TOKEN = "ghp_CONSTTOKEN" . self::API_KEY;
}

enum Credential: string
{
    case Prod = 'sk_live_ENUMSECRET456';
    const DEFAULT = 'ghp_ENUMCONST789';
}
""",
    )
    result = run_symbols(tmp_path)
    assert ("Config::API_KEY", "member", "app/Secrets.php") in sym_rows(result)
    assert ("Credential.Prod", "member", "app/Secrets.php") in sym_rows(result)
    blob = everything(result)
    for secret in ("CONSTSECRET123", "CONSTTOKEN", "ENUMSECRET456", "ENUMCONST789"):
        assert secret not in blob


def test_php_symbols_syntax_error_is_a_site(tmp_path):
    composer(tmp_path, LARAVEL)
    write(tmp_path, "app/Broken.php", "<?php\nclass Broken {\n  public function (\n")
    result = run_symbols(tmp_path)
    assert php_row(result).status == "partial"
    assert php_row(result).detail.startswith("app/Broken.php:")


def test_php_symbols_deeply_nested_blocks_do_not_crash(tmp_path):
    composer(tmp_path, LARAVEL)
    depth = 3000
    write(
        tmp_path,
        "app/Deep.php",
        "<?php\n" + "if (true) {\n" * depth + "class Deep {}\n" + "}\n" * depth,
    )
    result = run_symbols(tmp_path)
    assert not [w for w in result.warnings if "could not be read" in w]
