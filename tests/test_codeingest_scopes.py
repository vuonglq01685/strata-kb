"""Stable slugs, per-manifest dependency names and package scopes."""

from __future__ import annotations

from pathlib import Path

import pytest

from strata_kb.codeingest.extractors import _scopes, _slugs, deps


def write(root: Path, rel: str, text: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def git_init_add(run_git):
    def _go(root: Path) -> None:
        run_git(root, "init")
        run_git(root, "add", "-A")

    return _go


def test_find_scopes_monorepo(tmp_path, git_init_add):
    write(tmp_path, "package.json", '{"workspaces":["apps/*"]}')
    write(tmp_path, "apps/api/package.json", '{"dependencies":{"@nestjs/core":"^10"}}')
    write(
        tmp_path,
        "apps/web/package.json",
        '{"dependencies":{"next":"14","react":"18"}}',
    )
    git_init_add(tmp_path)
    scopes = _scopes.find_scopes(tmp_path, tmp_path / ".kb")
    assert [(s.path, s.frameworks) for s in scopes] == [
        (".", ()),
        ("apps/api", ("NestJS",)),
        ("apps/web", ("Next.js", "React")),
    ]
    assert _scopes.scope_of(scopes, "apps/api/src/a.ts").path == "apps/api"
    assert _scopes.scope_of(scopes, "tools/x.ts").path == "."


def test_find_scopes_without_git_prunes_ignored_dirs(tmp_path):
    write(tmp_path, "go.mod", "module x\n\nrequire github.com/gin-gonic/gin v1.9.0\n")
    write(tmp_path, "node_modules/dep/package.json", "{}")
    write(tmp_path, "svc/package.json", '{"dependencies":{"express":"4"}}')
    write(tmp_path, "svc/pom.xml", "<project/>")
    scopes = _scopes.find_scopes(tmp_path, tmp_path / ".kb")
    assert [(s.path, s.manifest, s.frameworks) for s in scopes] == [
        (".", "go.mod", ("Gin",)),
        ("svc", "package.json", ("Express",)),
    ]


def test_scope_of_without_root_scope_and_longest_prefix():
    scopes = [
        _scopes.Scope("apps", "package.json", ()),
        _scopes.Scope("apps/api", "package.json", ()),
    ]
    assert _scopes.scope_of(scopes, "apps/api/x.ts").path == "apps/api"
    assert _scopes.scope_of(scopes, "apps/apiary/x.ts").path == "apps"
    assert _scopes.scope_of(scopes, "libs/x.ts") is None


def test_slugs_stable_when_sibling_removed():
    a = _slugs.assign_slugs(
        [
            "apps/api/src/admin/admin.controller",
            "apps/admin/src/admin/admin.controller",
        ]
    )
    b = _slugs.assign_slugs(["apps/api/src/admin/admin.controller"])
    assert a[0] == b[0] and len(set(a)) == 2


def test_slugs_over_cap_names_get_own_suffix():
    long_a = "a" * 45 + "x"
    long_b = "a" * 45 + "y"
    a = _slugs.assign_slugs([long_a, long_b])
    assert len(set(a)) == 2
    assert _slugs.assign_slugs([long_b]) == [a[1]]


@pytest.mark.parametrize(
    ("name", "text", "expected"),
    [
        (
            "package.json",
            '{"dependencies":{"b":"1"},"devDependencies":{"a":"2"}}',
            ["a", "b"],
        ),
        ("pyproject.toml", '[project]\ndependencies=["fastapi>=0.1"]\n', ["fastapi"]),
        ("requirements-dev.txt", "# c\n-r x.txt\nflask>=2  # web\n", ["flask"]),
        (
            "pom.xml",
            "<project><dependencies><dependency><artifactId>spring-boot-starter</artifactId></dependency></dependencies></project>",
            ["spring-boot-starter"],
        ),
        (
            "build.gradle.kts",
            'implementation("org.x:quarkus-core:1")',
            ["quarkus-core"],
        ),
        (
            "a.csproj",
            '<Project><ItemGroup><PackageReference Include="Foo" Version="1"/></ItemGroup></Project>',
            ["Foo"],
        ),
        ("go.mod", "module m\nrequire (\n\tgithub.com/a/b v1\n)\n", ["github.com/a/b"]),
        (
            "composer.json",
            '{"require":{"laravel/framework":"^10"}}',
            ["laravel/framework"],
        ),
        (
            "Cargo.toml",
            '[dependencies]\naxum = { workspace = true }\n[dev-dependencies]\nrstest = "1"\n',
            ["axum", "rstest"],
        ),
        (
            "Package.swift",
            'let p = [.package(url: "https://x/y/vapor.git", from: "4.0.0")]',
            ["vapor"],
        ),
        ("pubspec.yaml", "dependencies:\n  flutter:\n    sdk: flutter\n", ["flutter"]),
    ],
)
def test_manifest_dep_names(tmp_path, name, text, expected):
    write(tmp_path, name, text)
    assert sorted(deps.manifest_dep_names(tmp_path / name)) == expected


def test_manifest_dep_names_degrades_on_garbage(tmp_path):
    write(tmp_path, "package.json", "{not json")
    assert deps.manifest_dep_names(tmp_path / "package.json") == []
    assert deps.manifest_dep_names(tmp_path / "missing.json") == []
    assert deps.manifest_dep_names(tmp_path / "README.md") == []
