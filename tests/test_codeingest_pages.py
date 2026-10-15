"""pages extractor: Next.js / Nuxt / SvelteKit file routers, Angular / Vue /
React router tables and Flutter go_router, plus the pages coverage rows."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("tree_sitter_language_pack")

from strata_kb.codeingest.extractors import _coverage, _ts, pages
from strata_kb.codeingest.types import CodeIngestOptions
from strata_kb.lintcore import table_rows


def write(root: Path, rel: str, text: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def package(root: Path, app: str, *deps: str) -> None:
    manifest = {
        "name": app.replace("/", "-") or "app",
        "dependencies": dict.fromkeys(deps, "*"),
    }
    write(
        root,
        f"{app}/package.json" if app != "." else "package.json",
        json.dumps(manifest),
    )


def pubspec(root: Path, app: str, *deps: str) -> None:
    body = "dependencies:\n  flutter:\n    sdk: flutter\n" + "".join(
        f"  {d}: ^1.0.0\n" for d in deps
    )
    write(root, f"{app}/pubspec.yaml" if app != "." else "pubspec.yaml", body)


def run_pages(root: Path, repo_id: str = "r"):
    opts = CodeIngestOptions(
        repo_root=root, kb_dir=root / ".kb", doc_id="d", repo_id=repo_id
    )
    return pages.PagesExtractor().extract(root, opts)


def section(result, slug: str):
    (found,) = [s for s in result.sections if s.id == f"page.{slug}"]
    return found


def rows_of(result, slug: str) -> list[list[str]]:
    return table_rows(section(result, slug).l2_md)[1:]


def paths_of(result, slug: str) -> list[str]:
    return [r[0] for r in rows_of(result, slug)]


def row(result, scope: str, framework: str):
    (found,) = [
        r for r in result.coverage if r.scope == scope and r.framework == framework
    ]
    return found


# --- Next.js ----------------------------------------------------------------


def test_next_app_router_groups_and_dynamic_segments(tmp_path):
    package(tmp_path, "apps/web", "next", "react")
    write(
        tmp_path,
        "apps/web/src/app/(admin)/admin/page.tsx",
        "export default function P() {}",
    )
    write(
        tmp_path,
        "apps/web/src/app/(viewer)/watch/[id]/page.tsx",
        "export default function P() {}",
    )
    write(tmp_path, "apps/web/src/app/page.tsx", "export default function P() {}")
    write(tmp_path, "apps/web/src/app/layout.tsx", "export default function L() {}")
    write(tmp_path, "apps/web/src/app/api/x/route.ts", "export function GET() {}")
    result = run_pages(tmp_path)
    sec = section(result, "apps-web")
    assert sec.group == "pages" and sec.title == "Pages: apps/web" and sec.summary
    assert table_rows(sec.l2_md) == [
        ["Path", "File", "Layout/group"],
        ["/", "apps/web/src/app/page.tsx", ""],
        ["/admin", "apps/web/src/app/(admin)/admin/page.tsx", "(admin)"],
        ["/watch/[id]", "apps/web/src/app/(viewer)/watch/[id]/page.tsx", "(viewer)"],
    ]
    assert row(result, "apps/web", "Next.js").status == "complete"
    assert not [r for r in result.coverage if r.framework == "React"]


def test_next_pages_router_skips_special_files_and_api(tmp_path):
    package(tmp_path, ".", "next")
    for rel in (
        "index",
        "about",
        "blog/[slug]",
        "blog/index",
        "_app",
        "_document",
        "api/hello",
        "404",
    ):
        write(tmp_path, f"pages/{rel}.tsx", "export default 1")
    result = run_pages(tmp_path, repo_id="web")
    assert paths_of(result, "web") == ["/", "/404", "/about", "/blog", "/blog/[slug]"]
    assert section(result, "web").title == "Pages: web"


def test_next_private_folder_slot_and_intercepting_route(tmp_path):
    package(tmp_path, ".", "next")
    write(tmp_path, "app/_components/page.tsx")
    write(tmp_path, "app/@modal/page.tsx")
    write(tmp_path, "app/feed/(..)photo/[id]/page.tsx")
    result = run_pages(tmp_path, "web")
    assert rows_of(result, "web") == [["/", "app/@modal/page.tsx", "@modal"]]
    r = row(result, ".", "Next.js")
    assert r.status == "partial" and r.detail == "app/feed/(..)photo/[id]/page.tsx:1"


def test_next_middleware_matcher_listed(tmp_path):
    package(tmp_path, ".", "next")
    write(tmp_path, "app/page.tsx")
    write(
        tmp_path,
        "middleware.ts",
        "export const config = { matcher: ['/admin/:path*', { source: '/api/(.*)' }] };",
    )
    result = run_pages(tmp_path, "web")
    assert rows_of(result, "web")[-1] == [
        "Middleware matcher: /admin/:path*, /api/(.*)",
        "middleware.ts",
        "",
    ]
    assert row(result, ".", "Next.js").status == "complete"


def test_next_middleware_nonliteral_matcher_is_site(tmp_path):
    package(tmp_path, ".", "next")
    write(tmp_path, "app/page.tsx")
    write(
        tmp_path,
        "middleware.ts",
        "const m = ['/a'];\nexport const config = { matcher: m };",
    )
    result = run_pages(tmp_path, "web")
    assert row(result, ".", "Next.js").detail == "middleware.ts:2"
    assert rows_of(result, "web") == [["/", "app/page.tsx", ""]]


def test_next_middleware_without_config_lists_nothing(tmp_path):
    package(tmp_path, ".", "next")
    write(tmp_path, "app/page.tsx")
    write(tmp_path, "src/middleware.ts", "export function middleware() {}")
    result = run_pages(tmp_path, "web")
    assert paths_of(result, "web") == ["/"]
    assert row(result, ".", "Next.js").status == "complete"


@pytest.mark.parametrize(
    "config",
    [
        "module.exports = { basePath: '/docs' }",
        "export default { pageExtensions: ['page.tsx'] }",
    ],
)
def test_next_config_that_moves_pages_is_site(tmp_path, config):
    package(tmp_path, ".", "next")
    write(tmp_path, "app/page.tsx")
    write(tmp_path, "next.config.js", config)
    r = row(run_pages(tmp_path, "web"), ".", "Next.js")
    assert r.status == "partial" and r.detail == "next.config.js:1"


# --- Nuxt -------------------------------------------------------------------


def test_nuxt_pages(tmp_path):
    package(tmp_path, "apps/site", "nuxt", "vue")
    for rel in ("index", "users/index", "users/[id]", "[...slug]", "(m)/about"):
        write(tmp_path, f"apps/site/pages/{rel}.vue", "<template/>")
    write(tmp_path, "apps/site/pages/ignored.spec.ts")
    write(tmp_path, "apps/site/server/api/x.ts")
    result = run_pages(tmp_path)
    assert rows_of(result, "apps-site") == [
        ["/", "apps/site/pages/index.vue", ""],
        ["/[...slug]", "apps/site/pages/[...slug].vue", ""],
        ["/about", "apps/site/pages/(m)/about.vue", "(m)"],
        ["/users", "apps/site/pages/users/index.vue", ""],
        ["/users/[id]", "apps/site/pages/users/[id].vue", ""],
    ]
    assert row(result, "apps/site", "Nuxt").status == "complete"
    assert not [r for r in result.coverage if r.framework == "Vue"]


def test_nuxt_srcdir_and_page_meta_path_are_sites(tmp_path):
    package(tmp_path, ".", "nuxt")
    write(
        tmp_path, "pages/a.vue", "<script setup>definePageMeta({ path: '/b' })</script>"
    )
    write(
        tmp_path,
        "nuxt.config.ts",
        "export default defineNuxtConfig({\n  srcDir: 'src/',\n})",
    )
    r = row(run_pages(tmp_path, "web"), ".", "Nuxt")
    assert r.status == "partial"
    assert r.detail == "nuxt.config.ts:2; pages/a.vue:1"


# --- SvelteKit --------------------------------------------------------------


def test_sveltekit_pages(tmp_path):
    package(tmp_path, "web", "svelte", "@sveltejs/kit")
    for rel in (
        "+page",
        "blog/[slug]/+page",
        "(app)/dash/+page",
        "x/+layout",
        "x/+server",
    ):
        suffix = "ts" if rel.endswith("+server") else "svelte"
        write(tmp_path, f"web/src/routes/{rel}.{suffix}")
    result = run_pages(tmp_path)
    assert rows_of(result, "web") == [
        ["/", "web/src/routes/+page.svelte", ""],
        ["/blog/[slug]", "web/src/routes/blog/[slug]/+page.svelte", ""],
        ["/dash", "web/src/routes/(app)/dash/+page.svelte", "(app)"],
    ]
    assert row(result, "web", "Svelte").status == "complete"


def test_sveltekit_custom_routes_dir_is_site(tmp_path):
    package(tmp_path, ".", "svelte", "@sveltejs/kit")
    write(tmp_path, "src/routes/+page.svelte")
    write(
        tmp_path,
        "svelte.config.js",
        "export default { kit: { files: { routes: 'src/r' } } };",
    )
    assert row(run_pages(tmp_path, "w"), ".", "Svelte").status == "partial"


def test_plain_svelte_without_kit_or_router_has_no_row(tmp_path):
    package(tmp_path, ".", "svelte")
    write(tmp_path, "src/App.svelte")
    result = run_pages(tmp_path, "w")
    assert result.coverage == [] and result.sections == []


def test_svelte_spa_router_is_unsupported(tmp_path):
    package(tmp_path, ".", "svelte", "svelte-spa-router")
    r = row(run_pages(tmp_path, "w"), ".", "Svelte")
    assert r.status == "not scanned" and "svelte-spa-router" in r.detail


# --- Angular ----------------------------------------------------------------


def test_angular_routes_array(tmp_path):
    package(tmp_path, "apps/ng", "@angular/core", "@angular/router")
    write(
        tmp_path,
        "apps/ng/src/app/app.routes.ts",
        """import { Routes } from '@angular/router';
export const routes: Routes = [
  { path: '', component: HomeComponent },
  { path: 'users/:id', loadComponent: () => import('./user').then(m => m.User) },
  { path: 'old', redirectTo: 'users/1', pathMatch: 'full' },
  { path: 'admin', component: Shell, children: [
    { path: 'stats', component: Stats },
  ] },
];
""",
    )
    write(
        tmp_path,
        "apps/ng/src/app/app.config.ts",
        "import { routes } from './app.routes';\nexport const c = [provideRouter(routes)];",
    )
    result = run_pages(tmp_path)
    assert rows_of(result, "apps-ng") == [
        ["/", "apps/ng/src/app/app.routes.ts", ""],
        ["/admin", "apps/ng/src/app/app.routes.ts", ""],
        ["/admin/stats", "apps/ng/src/app/app.routes.ts", "Shell"],
        ["/users/:id", "apps/ng/src/app/app.routes.ts", ""],
    ]
    assert row(result, "apps/ng", "Angular").status == "complete"


def test_angular_lazy_children_join_and_unresolved_is_site(tmp_path):
    package(tmp_path, ".", "@angular/core")
    write(
        tmp_path,
        "src/app.routes.ts",
        """export const routes: Routes = [
  { path: 'shop', loadChildren: () => import('./shop.routes').then(m => m.SHOP_ROUTES) },
  { path: 'legacy', loadChildren: () => import('./legacy.module').then(m => m.LegacyModule) },
  { path: 'ext', loadChildren: () => import('some-pkg').then(m => m.X) },
];""",
    )
    write(
        tmp_path,
        "src/shop.routes.ts",
        "export const SHOP_ROUTES: Routes = [{ path: 'cart', component: Cart }];",
    )
    write(
        tmp_path,
        "src/legacy.module.ts",
        "@NgModule({ imports: [RouterModule.forChild([{ path: 'old', component: Old }])] })\nexport class LegacyModule {}",
    )
    result = run_pages(tmp_path, "ng")
    assert paths_of(result, "ng") == ["/legacy/old", "/shop/cart"]
    r = row(result, ".", "Angular")
    assert r.status == "partial" and r.detail == "src/app.routes.ts:4"


def test_angular_dynamic_path_and_spread_are_sites(tmp_path):
    package(tmp_path, ".", "@angular/core")
    write(
        tmp_path,
        "src/r.ts",
        """import { more } from '@lib/more';
export const routes: Routes = [
  { path: PATH, component: A },
  ...more,
  { path: 'ok', component: B },
];""",
    )
    result = run_pages(tmp_path, "ng")
    assert paths_of(result, "ng") == ["/ok"]
    assert row(result, ".", "Angular").detail == "src/r.ts:3; src/r.ts:4"


# --- Vue --------------------------------------------------------------------


def test_vue_router_routes(tmp_path):
    package(tmp_path, "app", "vue", "vue-router")
    write(
        tmp_path,
        "app/src/router.ts",
        """import { createRouter, createWebHistory } from 'vue-router';
import { adminRoutes } from './admin';
export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: Home },
    { path: '/users/:id', component: () => import('./User.vue') },
    { path: '/old', redirect: '/' },
    ...adminRoutes,
  ],
});""",
    )
    write(
        tmp_path,
        "app/src/admin.ts",
        """export const adminRoutes = [
  { path: '/admin', component: Admin, children: [{ path: 'logs', component: Logs }, { path: '/abs', component: Abs }] },
];""",
    )
    result = run_pages(tmp_path)
    assert paths_of(result, "app") == [
        "/",
        "/abs",
        "/admin",
        "/admin/logs",
        "/users/:id",
    ]
    assert row(result, "app", "Vue").status == "complete"


def test_vue_without_router_lib_has_no_row_and_unplugin_is_unsupported(tmp_path):
    package(tmp_path, "a", "vue")
    package(tmp_path, "b", "vue", "unplugin-vue-router")
    result = run_pages(tmp_path)
    assert [r for r in result.coverage if r.scope == "a"] == []
    r = row(result, "b", "Vue")
    assert r.status == "not scanned" and "unplugin-vue-router" in r.detail


def test_vue_add_route_and_missing_routes_are_sites(tmp_path):
    package(tmp_path, ".", "vue", "vue-router")
    write(
        tmp_path,
        "r.ts",
        "import { createRouter } from 'vue-router';\nconst router = createRouter({ history });\nrouter.addRoute({ path: '/x', component: X });",
    )
    r = row(run_pages(tmp_path, "v"), ".", "Vue")
    assert r.status == "partial" and r.detail == "r.ts:2; r.ts:3"


# --- React ------------------------------------------------------------------


def test_react_router_nested_children(tmp_path):
    package(tmp_path, "web", "react", "react-router-dom")
    write(
        tmp_path,
        "web/src/App.tsx",
        """import { Routes, Route } from 'react-router-dom';
export const App = () => (
  <Routes>
    <Route path="/" element={<Layout />}>
      <Route index element={<Home />} />
      <Route path="users" element={<Users />}>
        <Route path=":id" element={<User />} />
      </Route>
    </Route>
    <Route path="*" element={<NotFound />} />
  </Routes>
);""",
    )
    write(
        tmp_path,
        "web/src/router.tsx",
        """import { createBrowserRouter } from 'react-router-dom';
export const router = createBrowserRouter([
  { path: '/docs', element: <Docs />, children: [{ path: ':slug', element: <Doc /> }] },
]);""",
    )
    result = run_pages(tmp_path)
    assert [(r[0], r[2]) for r in rows_of(result, "web")] == [
        ("/", ""),
        ("/", "Layout"),
        ("/*", ""),
        ("/docs", ""),
        ("/docs/:slug", "Docs"),
        ("/users", "Layout"),
        ("/users/:id", "Users"),
    ]
    assert row(result, "web", "React").status == "complete"


def test_react_descendant_splat_custom_route_and_condition_are_sites(tmp_path):
    package(tmp_path, ".", "react", "react-router-dom")
    write(
        tmp_path,
        "App.tsx",
        """import { Routes, Route } from 'react-router-dom';
export const A = () => (
  <Routes>
    <Route path="/app/*" element={<Sub />} />
    <PrivateRoute path="/p" component={P} />
    <Route path={dyn} element={<D />} />
    <Route path="/ok" element={<Ok />}>{flag && <Route path="x" element={<X />} />}</Route>
  </Routes>
);""",
    )
    result = run_pages(tmp_path, "w")
    assert paths_of(result, "w") == ["/app/*", "/ok"]
    assert (
        row(result, ".", "React").detail == "App.tsx:4; App.tsx:5; App.tsx:6; App.tsx:7"
    )


def test_react_unsupported_router_names_the_library(tmp_path):
    package(tmp_path, "a", "react", "@tanstack/react-router")
    package(tmp_path, "b", "react", "wouter")
    package(tmp_path, "c", "react")
    result = run_pages(tmp_path)
    assert "@tanstack/react-router" in row(result, "a", "React").detail
    assert row(result, "b", "React").status == "not scanned"
    assert [r for r in result.coverage if r.scope == "c"] == []


def test_react_object_routes_identifier_imported(tmp_path):
    package(tmp_path, ".", "react", "react-router")
    write(
        tmp_path,
        "src/routes.tsx",
        "export const routes = [{ path: '/a', element: <A /> }];",
    )
    write(
        tmp_path,
        "src/main.tsx",
        "import { createBrowserRouter } from 'react-router';\nimport { routes } from './routes';\nconst r = createBrowserRouter(routes);",
    )
    result = run_pages(tmp_path, "w")
    assert paths_of(result, "w") == ["/a"]
    assert row(result, ".", "React").status == "complete"


# --- Flutter ----------------------------------------------------------------


def test_flutter_go_router_nested(tmp_path):
    pubspec(tmp_path, "app", "go_router")
    write(
        tmp_path,
        "app/lib/router.dart",
        """final router = GoRouter(routes: [
  GoRoute(path: '/', builder: (c, s) => Home(), routes: [
    GoRoute(path: 'details/:id', builder: (c, s) => Details()),
    GoRoute(path: '/abs', builder: (c, s) => Abs()),
  ]),
  ShellRoute(builder: (c, s, w) => w, routes: [
    GoRoute(path: '/settings', builder: (c, s) => S()),
  ]),
]);
""",
    )
    result = run_pages(tmp_path)
    assert rows_of(result, "app") == [
        ["/", "app/lib/router.dart", ""],
        ["/abs", "app/lib/router.dart", ""],
        ["/details/:id", "app/lib/router.dart", ""],
        ["/settings", "app/lib/router.dart", "ShellRoute"],
    ]
    assert row(result, "app", "Flutter").status == "complete"


def test_flutter_material_app_routes_and_sites(tmp_path):
    pubspec(tmp_path, ".")
    write(
        tmp_path,
        "lib/main.dart",
        """void main() => runApp(MaterialApp(
  routes: {'/': (c) => Home(), '/about': (c) => About(), kPath: (c) => X()},
  onGenerateRoute: gen,
));
@TypedGoRoute<HomeRoute>(path: '/h')
class HomeRoute {}
""",
    )
    write(tmp_path, "lib/r.dart", "final x = GoRoute(path: base + '/y', builder: b);")
    result = run_pages(tmp_path, "app")
    assert paths_of(result, "app") == ["/", "/about"]
    r = row(result, ".", "Flutter")
    assert r.status == "partial"
    assert r.detail == "lib/main.dart:1; lib/main.dart:2; lib/main.dart:5; lib/r.dart:1"


def test_flutter_spread_of_same_file_list_keeps_prefix(tmp_path):
    pubspec(tmp_path, ".", "go_router")
    write(
        tmp_path,
        "lib/r.dart",
        """final subs = [GoRoute(path: 'b', builder: b)];
final r = GoRouter(routes: [GoRoute(path: '/a', builder: b, routes: subs)]);
""",
    )
    assert paths_of(run_pages(tmp_path, "app"), "app") == ["/a", "/a/b"]


def test_flutter_auto_route_is_unsupported(tmp_path):
    pubspec(tmp_path, ".", "auto_route")
    r = row(run_pages(tmp_path, "app"), ".", "Flutter")
    assert r.status == "not scanned" and "auto_route" in r.detail


# --- degrade ----------------------------------------------------------------


def test_backend_only_scope_has_no_pages_row(tmp_path):
    package(tmp_path, "api", "@nestjs/core", "express")
    write(tmp_path, "api/src/main.ts")
    result = run_pages(tmp_path)
    assert result.sections == [] and result.coverage == []
    assert pages.PagesExtractor().detect(tmp_path) is False


def test_nested_backend_scope_files_are_not_attributed_to_root_app(tmp_path):
    package(tmp_path, ".", "next")
    write(tmp_path, "app/page.tsx")
    package(tmp_path, "services/api", "express")
    write(tmp_path, "services/api/app/page.tsx")
    assert paths_of(run_pages(tmp_path, "web"), "web") == ["/"]


def test_without_tree_sitter_fs_routers_run_and_parsers_are_not_scanned(
    tmp_path, monkeypatch
):
    package(tmp_path, "web", "next")
    write(tmp_path, "web/app/page.tsx")
    write(tmp_path, "web/middleware.ts", "export const config = { matcher: ['/a'] };")
    package(tmp_path, "ng", "@angular/core")
    pubspec(tmp_path, "mobile", "go_router")
    monkeypatch.setattr(_ts, "available", lambda: False)
    result = run_pages(tmp_path)
    assert paths_of(result, "web") == ["/"]
    assert row(result, "web", "Next.js").status == "not scanned"
    assert row(result, "web", "Next.js").detail == _coverage.NOT_INSTALLED
    for scope, fw in (("ng", "Angular"), ("mobile", "Flutter")):
        assert (row(result, scope, fw).status, row(result, scope, fw).detail) == (
            "not scanned",
            _coverage.NOT_INSTALLED,
        )
    assert len(result.warnings) == 1 and "tree-sitter" in result.warnings[0]


def test_nuxt_without_tree_sitter_stays_complete(tmp_path, monkeypatch):
    package(tmp_path, ".", "nuxt")
    write(tmp_path, "pages/index.vue")
    monkeypatch.setattr(_ts, "available", lambda: False)
    result = run_pages(tmp_path, "w")
    assert (
        paths_of(result, "w") == ["/"] and row(result, ".", "Nuxt").status == "complete"
    )
    assert result.warnings == []


def test_syntax_error_in_router_file_is_site_and_adapter_crash_degrades(
    tmp_path, monkeypatch
):
    package(tmp_path, ".", "@angular/core")
    write(
        tmp_path,
        "r.ts",
        "export const routes: Routes = [{ path: 'a', component: A ,, ]\n",
    )
    r = row(run_pages(tmp_path, "w"), ".", "Angular")
    assert r.status == "partial" and r.detail.startswith("r.ts:")

    def boom(*_a):
        raise RuntimeError("x")

    monkeypatch.setattr(pages, "angular_pages", boom)
    result = run_pages(tmp_path, "w")
    assert row(result, ".", "Angular").detail == "package.json:1"
    assert "Angular adapter failed" in result.warnings[0]


def test_output_is_deterministic_and_root_scope_uses_repo_id(tmp_path):
    package(tmp_path, ".", "nuxt")
    write(tmp_path, "pages/b.vue")
    write(tmp_path, "pages/a.vue")
    first = run_pages(tmp_path, "my-repo")
    assert first == run_pages(tmp_path, "my-repo")
    assert first.sections[0].id == "page.my-repo"


def test_vue_shorthand_routes_default_import_and_alias_site(tmp_path):
    package(tmp_path, ".", "vue", "vue-router")
    write(
        tmp_path,
        "src/router.js",
        "import { createRouter } from 'vue-router'\nimport routes from './routes'\nexport default createRouter({ routes })\n",
    )
    write(
        tmp_path,
        "src/routes.js",
        "export default [{ path: '/', component: H }, { path: '/a', component: A, alias: '/b' }]\n",
    )
    result = run_pages(tmp_path, "v")
    assert paths_of(result, "v") == ["/", "/a"]
    assert row(result, ".", "Vue").detail == "src/routes.js:1"


def test_react_namespace_import_route_and_angular_type_assertion(tmp_path):
    package(tmp_path, "r", "react", "react-router-dom")
    write(
        tmp_path,
        "r/b.jsx",
        "import * as RR from 'react-router-dom'\nexport const X = <RR.Route path='/b' element={<B />} />\n",
    )
    package(tmp_path, "n", "@angular/core")
    write(
        tmp_path, "n/a.ts", "export const r = <Routes>[{ path: 'z', component: Z }];\n"
    )
    result = run_pages(tmp_path)
    assert paths_of(result, "r") == ["/b"] and paths_of(result, "n") == ["/z"]
    assert (
        row(result, "r", "React").status
        == row(result, "n", "Angular").status
        == "complete"
    )


# --- review fix round 1 -----------------------------------------------------


def test_nuxt_layers_extends_and_i18n_are_sites(tmp_path):
    package(tmp_path, ".", "nuxt")
    write(tmp_path, "pages/index.vue")
    write(
        tmp_path,
        "nuxt.config.ts",
        "export default defineNuxtConfig({\n  extends: ['../base'],\n  modules: ['@nuxtjs/i18n'],\n  i18n: {},\n})",
    )
    r = row(run_pages(tmp_path, "w"), ".", "Nuxt")
    assert (
        r.status == "partial"
        and r.detail == "nuxt.config.ts:2; nuxt.config.ts:3; nuxt.config.ts:4"
    )


def test_nuxt_local_layer_pages_are_listed(tmp_path):
    package(tmp_path, ".", "nuxt")
    write(tmp_path, "pages/index.vue")
    write(
        tmp_path, "layers/admin/nuxt.config.ts", "export default defineNuxtConfig({})"
    )
    write(tmp_path, "layers/admin/pages/admin/index.vue")
    result = run_pages(tmp_path, "w")
    assert rows_of(result, "w") == [
        ["/", "pages/index.vue", ""],
        ["/admin", "layers/admin/pages/admin/index.vue", ""],
    ]
    assert row(result, ".", "Nuxt").status == "complete"


def test_react_routes_reexported_through_a_barrel_are_found(tmp_path):
    package(tmp_path, ".", "react", "react-router-dom")
    write(
        tmp_path,
        "src/lib/router.ts",
        "export { Route, Routes } from 'react-router-dom'\n",
    )
    write(
        tmp_path,
        "src/AppRoutes.tsx",
        "import { Route, Routes } from './lib/router'\nexport const A = () => (<Routes><Route path='/a' element={<A />} /></Routes>)\n",
    )
    result = run_pages(tmp_path, "w")
    assert paths_of(result, "w") == ["/a"]
    assert row(result, ".", "React").status == "complete"


def test_vue_router_created_through_a_wrapper_is_found(tmp_path):
    package(tmp_path, ".", "vue", "vue-router")
    write(
        tmp_path,
        "src/router.ts",
        "import { createRouter } from './lib'\nexport default createRouter({ routes: [{ path: '/a', component: A }] })\n",
    )
    assert paths_of(run_pages(tmp_path, "w"), "w") == ["/a"]


@pytest.mark.parametrize(
    ("framework", "deps"),
    [("React", ("react", "react-router-dom")), ("Vue", ("vue", "vue-router"))],
)
def test_router_lib_with_no_pages_and_no_sites_is_a_site(tmp_path, framework, deps):
    package(tmp_path, "app", *deps)
    write(tmp_path, "app/src/main.ts", "export const x = 1\n")
    r = row(run_pages(tmp_path), "app", framework)
    assert r.status == "partial" and r.detail == "app/package.json:1"


def test_flutter_go_router_with_no_pages_is_a_site(tmp_path):
    pubspec(tmp_path, ".", "go_router")
    write(tmp_path, "lib/main.dart", "void main() {}\n")
    r = row(run_pages(tmp_path, "app"), ".", "Flutter")
    assert r.status == "partial" and r.detail == "pubspec.yaml:1"


def test_flutter_home_is_root_and_imperative_routes_are_sites(tmp_path):
    pubspec(tmp_path, ".")
    write(
        tmp_path,
        "lib/main.dart",
        "Widget build(c) {\n  return MaterialApp(home: const HomePage());\n}\n"
        "void go(c) => Navigator.push(c, MaterialPageRoute(builder: (_) => D()));\n",
    )
    result = run_pages(tmp_path, "app")
    assert rows_of(result, "app") == [["/", "lib/main.dart", ""]]
    r = row(result, ".", "Flutter")
    assert r.status == "partial" and r.detail == "lib/main.dart:4"


def test_angular_classic_lazy_module_follows_its_routing_module(tmp_path):
    package(tmp_path, ".", "@angular/core")
    write(
        tmp_path,
        "src/app-routing.module.ts",
        "const routes: Routes = [\n"
        "  { path: '', component: Home },\n"
        "  { path: 'customers', loadChildren: () => import('./customers/customers.module').then(m => m.CustomersModule) },\n"
        "];\n@NgModule({ imports: [RouterModule.forRoot(routes)] })\nexport class AppRoutingModule {}\n",
    )
    write(
        tmp_path,
        "src/customers/customers-routing.module.ts",
        "import { NgModule } from '@angular/core';\n"
        "const routes: Routes = [{ path: '', component: C }, { path: ':id', component: C }];\n"
        "@NgModule({ imports: [RouterModule.forChild(routes)] })\nexport class CustomersRoutingModule {}\n",
    )
    write(
        tmp_path,
        "src/customers/customers.module.ts",
        "import { CustomersRoutingModule } from './customers-routing.module';\n"
        "@NgModule({ imports: [CommonModule, CustomersRoutingModule] })\nexport class CustomersModule {}\n",
    )
    result = run_pages(tmp_path, "ng")
    assert paths_of(result, "ng") == ["/", "/customers", "/customers/:id"]
    assert row(result, ".", "Angular").status == "complete"


def test_next_markdown_pages_are_not_pages(tmp_path):
    package(tmp_path, ".", "next")
    write(tmp_path, "app/page.tsx")
    write(tmp_path, "app/docs/page.md")
    write(tmp_path, "pages/readme.md")
    assert paths_of(run_pages(tmp_path, "w"), "w") == ["/"]


def test_analog_router_is_unsupported_for_angular(tmp_path):
    package(tmp_path, ".", "@angular/core", "@analogjs/router")
    r = row(run_pages(tmp_path, "w"), ".", "Angular")
    assert r.status == "not scanned" and "@analogjs/router" in r.detail


def test_sveltekit_reroute_hook_is_site(tmp_path):
    package(tmp_path, ".", "svelte", "@sveltejs/kit")
    write(tmp_path, "src/routes/+page.svelte")
    write(
        tmp_path,
        "src/hooks.ts",
        "import x from 'y';\nexport const reroute = ({ url }) => url.pathname;\n",
    )
    r = row(run_pages(tmp_path, "w"), ".", "Svelte")
    assert r.status == "partial" and r.detail == "src/hooks.ts:2"


def test_next_matcher_with_has_or_missing_is_site(tmp_path):
    package(tmp_path, ".", "next")
    write(tmp_path, "app/page.tsx")
    write(
        tmp_path,
        "middleware.ts",
        "export const config = {\n  matcher: [{ source: '/a', has: [{ type: 'header', key: 'x' }] }],\n};\n",
    )
    result = run_pages(tmp_path, "w")
    assert row(result, ".", "Next.js").detail == "middleware.ts:2"
    assert rows_of(result, "w")[-1][0] == "Middleware matcher: /a"


def test_top_level_declaration_wins_over_nested_shadow(tmp_path):
    package(tmp_path, ".", "@angular/core")
    write(
        tmp_path,
        "src/r.ts",
        "function f() { const routes = [{ path: 'nested', component: N }]; return routes; }\n"
        "const routes = [{ path: 'real', component: R }];\n"
        "@NgModule({ imports: [RouterModule.forRoot(routes)] })\nexport class M {}\n",
    )
    assert paths_of(run_pages(tmp_path, "w"), "w") == ["/real"]
