"""Shared helpers of the Swift (Vapor) and Dart codeingest tests."""

from __future__ import annotations

from pathlib import Path

from strata_kb.lintcore import table_rows
from tests.go_support import (
    at,
    everything,
    opts,
    pairs,
    row,
    rows_of,
    run_routes,
    run_symbols,
    section,
    triples,
    verdict,
    write,
)

__all__ = [
    "at",
    "everything",
    "opts",
    "pairs",
    "pubspec",
    "row",
    "rows_of",
    "run_routes",
    "run_symbols",
    "section",
    "sym_rows",
    "triples",
    "vapor_app",
    "vapor_package",
    "verdict",
    "write",
]

ROUTES = "Sources/App/routes.swift"

_PACKAGE = """// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "app",
    platforms: [.macOS(.v13)],
    dependencies: [
        .package(url: "https://github.com/vapor/vapor.git", from: "4.89.0"),
    ],
    targets: [
        .executableTarget(
            name: "App",
            dependencies: [.product(name: "Vapor", package: "vapor")]
        ),
        .testTarget(name: "AppTests", dependencies: [.target(name: "App")]),
    ]
)
"""


def vapor_package(root: Path, app: str = ".") -> None:
    base = "" if app == "." else f"{app}/"
    write(root, f"{base}Package.swift", _PACKAGE)


def vapor_app(root: Path, text: str, rel: str = ROUTES) -> None:
    vapor_package(root)
    write(root, rel, text)


def pubspec(root: Path, *deps: str, app: str = ".") -> None:
    base = "" if app == "." else f"{app}/"
    lines = "".join(f"  {dep}:\n    sdk: flutter\n" for dep in deps)
    write(
        root,
        f"{base}pubspec.yaml",
        f"name: app\nenvironment:\n  sdk: '>=3.0.0 <4.0.0'\ndependencies:\n{lines}",
    )


def sym_rows(result) -> list[tuple[str, str, str]]:
    return sorted(
        (r[0], r[1], r[2]) for s in result.sections for r in table_rows(s.l2_md)[1:]
    )
