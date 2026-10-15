"""symbols extractor: exported names of JS/TS and CSS/SCSS custom properties,
one `sym.<package>` section per package scope, plus the `symbols` coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from strata_kb.codeingest.extractors import _coverage, _symbols_lang, _ts, symbols
from strata_kb.codeingest.types import CodeIngestOptions
from strata_kb.lintcore import table_rows

needs_ts = pytest.mark.skipif(not _ts.available(), reason="code extra not installed")


def write(root: Path, rel: str, text: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def package(root: Path, directory: str, name: str = "pkg") -> None:
    rel = f"{directory}/package.json" if directory != "." else "package.json"
    write(root, rel, json.dumps({"name": name}))


def run_symbols(root: Path):
    opts = CodeIngestOptions(
        repo_root=root, kb_dir=root / ".kb", doc_id="d", repo_id="repo"
    )
    return symbols.SymbolsExtractor().extract(root, opts)


def section(result, slug: str):
    (found,) = [s for s in result.sections if s.id == slug]
    return found


def rows(result, slug: str) -> list[list[str]]:
    return table_rows(section(result, slug).l2_md)[1:]


def names(result, slug: str = "sym.root") -> list[str]:
    return [r[0] for r in rows(result, slug)]


def cover(result, scope: str, language: str):
    (found,) = [
        r for r in result.coverage if r.scope == scope and r.framework == language
    ]
    return found


def solo(tmp_path: Path, text: str, rel: str = "src/a.ts"):
    package(tmp_path, ".")
    write(tmp_path, rel, text)
    return run_symbols(tmp_path)


# --- structure -------------------------------------------------------------


def test_extractor_name_and_registered():
    from strata_kb.codeingest.extractors import ALL_EXTRACTORS

    assert symbols.SymbolsExtractor().name == "symbols"
    assert any(e.name == "symbols" for e in ALL_EXTRACTORS)


def test_symbol_is_a_frozen_name_kind_file_triple():
    sym = symbols.Symbol("A", "class", "a.ts")
    assert (sym.name, sym.kind, sym.file) == ("A", "class", "a.ts")
    with pytest.raises(AttributeError):
        sym.name = "B"  # type: ignore[misc]


def test_exporters_keyed_by_language_id():
    assert {"typescript", "tsx", "javascript", "css", "scss"} <= set(
        _symbols_lang.EXPORTERS
    )


# --- JS / TS ---------------------------------------------------------------


@needs_ts
def test_error_code_object_members_listed(tmp_path):
    package(tmp_path, "packages/shared")
    write(
        tmp_path,
        "packages/shared/src/error-codes.ts",
        'export const ErrorCodes = { ASSET_NOT_READY: "E1", NOT_FOUND: "E2" } as const;',
    )
    result = run_symbols(tmp_path)
    got = rows(result, "sym.packages-shared")
    file = "packages/shared/src/error-codes.ts"
    assert ["ErrorCodes.ASSET_NOT_READY", "member", file] in got
    assert ["ErrorCodes.NOT_FOUND", "member", file] in got
    assert ["ErrorCodes", "const", file] in got
    assert not any("E1" in c for r in got for c in r)  # names only, never values
    assert cover(result, "packages/shared", "typescript").status == "complete"


@needs_ts
def test_secret_shaped_values_appear_nowhere(tmp_path):
    result = solo(
        tmp_path,
        'export const Cfg = { API_KEY: "sk-live-4f9a1c0de", URL: `https://u:p@h/${x}` };\n'
        'export enum Role { Admin = "ghp_SECRETTOKEN123", User = 2 }\n'
        'export const TOKEN = "AKIAIOSFODNN7EXAMPLE";\n',
    )
    everything = "\n".join(
        [
            *(s.l2_md + s.l3_md + s.summary + s.title + s.id for s in result.sections),
            *(f"{r.detail} {r.framework} {r.scope}" for r in result.coverage),
            *result.warnings,
        ]
    )
    for secret in ("sk-live", "ghp_", "AKIA", "u:p@h"):
        assert secret not in everything
    assert "Cfg.API_KEY" in names(result)
    assert "Role.Admin" in names(result)


@needs_ts
def test_enum_members_and_kinds(tmp_path):
    result = solo(
        tmp_path,
        "export enum Color { Red, Green = 'g', 'Dark-Blue' = 3 }\n"
        "export const enum Flag { On }\n"
        "export declare enum Ambient { X }\n"
        "export interface I {}\n"
        "export type T = string;\n"
        "export abstract class AC {}\n"
        "export function* gen() {}\n"
        "export async function af() {}\n"
        "export declare function sig(): void;\n"
        "export let counter = 0;\n"
        "export var legacy = 1;\n"
        "export namespace NS { export const hidden = 1 }\n",
    )
    got = {r[0]: r[1] for r in rows(result, "sym.root")}
    assert got == {
        "Color": "enum",
        "Color.Red": "member",
        "Color.Green": "member",
        "Color.Dark-Blue": "member",
        "Flag": "enum",
        "Flag.On": "member",
        "Ambient": "enum",
        "Ambient.X": "member",
        "I": "interface",
        "T": "type",
        "AC": "class",
        "gen": "function",
        "af": "function",
        "sig": "function",
        "counter": "const",
        "legacy": "const",
        "NS": "const",
    }


@needs_ts
def test_function_valued_const_is_a_function(tmp_path):
    result = solo(
        tmp_path,
        "export const Public = () => SetMetadata(IS_PUBLIC, true);\n"
        "export const handler = async function () {};\n"
        "export const Klass = class {};\n"
        "export const { a, b: [c, d], ...rest } = obj;\n",
    )
    got = {r[0]: r[1] for r in rows(result, "sym.root")}
    assert got["Public"] == "function"
    assert got["handler"] == "function"
    assert got["Klass"] == "class"
    assert {got[n] for n in ("a", "c", "d", "rest")} == {"const"}


@needs_ts
def test_export_list_and_default(tmp_path):
    package(tmp_path, ".")
    write(
        tmp_path,
        "src/list.ts",
        "const a = 1;\nfunction b() {}\nclass K {}\ninterface Shape {}\n"
        "const Codes = { X: 1, Y: 2 };\n"
        "export { a, b as c, K, Shape, Codes as Errs };\n"
        "export type { Shape as Alias };\n",
    )
    write(tmp_path, "src/anon.ts", "export default function () {}\n")
    write(tmp_path, "src/named.ts", "export default class Widget {}\n")
    write(tmp_path, "src/obj.ts", "export default { a: 1 };\n")
    write(tmp_path, "src/id.ts", "const Local = () => 1;\nexport default Local;\n")
    got = {(r[2], r[0]): r[1] for r in rows(run_symbols(tmp_path), "sym.root")}
    assert got[("src/list.ts", "a")] == "const"
    assert got[("src/list.ts", "c")] == "function"  # exported name, local kind
    assert ("src/list.ts", "b") not in got
    assert got[("src/list.ts", "K")] == "class"
    assert got[("src/list.ts", "Shape")] == "interface"
    assert got[("src/list.ts", "Alias")] == "interface"
    assert got[("src/list.ts", "Errs")] == "const"
    assert got[("src/list.ts", "Errs.X")] == "member"  # members follow the alias
    assert got[("src/anon.ts", "anon")] == "function"  # file stem
    assert got[("src/named.ts", "Widget")] == "class"  # declared name
    assert got[("src/obj.ts", "obj")] == "const"
    assert got[("src/id.ts", "Local")] == "function"


@needs_ts
def test_reexport_star_followed_once(tmp_path):
    package(tmp_path, "apps/api", "api")
    d = "apps/api/src/common/decorators"
    write(
        tmp_path,
        f"{d}/public.decorator.ts",
        "export const Public = () => SetMetadata('p', true);\n"
        "export default function hidden() {}\n",
    )
    write(tmp_path, f"{d}/roles.decorator.ts", "export function Roles() {}\n")
    write(
        tmp_path,
        f"{d}/index.ts",
        "export * from './public.decorator';\nexport * from './roles.decorator';\n",
    )
    result = run_symbols(tmp_path)
    got = {(r[2], r[0]): r[1] for r in rows(result, "sym.apps-api")}
    assert got[(f"{d}/index.ts", "Public")] == "function"
    assert got[(f"{d}/index.ts", "Roles")] == "function"
    assert (f"{d}/index.ts", "hidden") not in got  # `export *` skips default
    assert got[(f"{d}/public.decorator.ts", "Public")] == "function"
    assert cover(result, "apps/api", "typescript").status == "complete"


@needs_ts
def test_reexport_barrel_chain_alias_and_cycle(tmp_path):
    package(tmp_path, ".")
    write(tmp_path, "src/deep.ts", "export class Deep {}\nexport * from './index';\n")
    write(tmp_path, "src/mid.ts", "export * from './deep';\nexport const Mid = 1;\n")
    write(
        tmp_path,
        "src/index.ts",
        "export * from './mid';\n"
        "export { Deep as Renamed } from './deep';\n"
        "export * as ns from './mid';\n",
    )
    result = run_symbols(tmp_path)
    got = {(r[2], r[0]): r[1] for r in rows(result, "sym.root")}
    assert got[("src/index.ts", "Deep")] == "class"  # two hops, cycle terminates
    assert got[("src/index.ts", "Mid")] == "const"
    assert got[("src/index.ts", "Renamed")] == "class"  # kind from the target
    assert got[("src/index.ts", "ns")] == "const"
    assert cover(result, ".", "typescript").status == "complete"


@needs_ts
def test_reexport_tsconfig_alias_and_workspace_package(tmp_path):
    package(tmp_path, ".")
    package(tmp_path, "packages/shared", "@acme/shared")
    write(
        tmp_path,
        "tsconfig.json",
        '{"compilerOptions": {"paths": {"@lib/*": ["lib/*"]}}}',
    )
    write(tmp_path, "lib/util.ts", "export const util = 1;\n")
    write(tmp_path, "packages/shared/src/index.ts", "export const shared = 1;\n")
    write(
        tmp_path,
        "src/index.ts",
        "export * from '@lib/util';\nexport * from '@acme/shared';\n",
    )
    result = run_symbols(tmp_path)
    got = {(r[2], r[0]) for r in rows(result, "sym.root")}
    assert ("src/index.ts", "util") in got
    assert ("src/index.ts", "shared") in got
    assert cover(result, ".", "typescript").status == "complete"


@needs_ts
def test_reexport_star_unresolved_is_a_site(tmp_path):
    result = solo(
        tmp_path,
        "export const kept = 1;\nexport * from './missing';\n",
        "src/a.ts",
    )
    assert "kept" in names(result)
    row = cover(result, ".", "typescript")
    assert row.status == "partial"
    assert "src/a.ts:2" in row.detail


@needs_ts
def test_reexport_star_from_registry_package_is_a_site(tmp_path):
    result = solo(tmp_path, "export * from 'lodash';\n")
    row = cover(result, ".", "typescript")
    assert row.status == "partial"
    assert "src/a.ts:1" in row.detail


@needs_ts
def test_named_reexport_from_registry_package_lists_names(tmp_path):
    result = solo(
        tmp_path,
        "export { debounce, throttle as slow } from 'lodash';\n"
        "export * as _ from 'lodash';\n",
    )
    got = {r[0]: r[1] for r in rows(result, "sym.root")}
    assert got == {"debounce": "const", "slow": "const", "_": "const"}
    assert cover(result, ".", "typescript").status == "complete"


@needs_ts
def test_named_reexport_unresolved_relative_is_a_site(tmp_path):
    result = solo(tmp_path, "export { gone } from './gone';\n")
    assert "gone" in names(result)
    assert cover(result, ".", "typescript").status == "partial"


@needs_ts
def test_spread_or_computed_member_is_a_site(tmp_path):
    result = solo(
        tmp_path,
        "export const Codes = { ...Base, A: 1 };\n"
        "export const Other = { [dyn()]: 1, B: 2 };\n",
    )
    assert {"Codes.A", "Other.B"} <= set(names(result))
    row = cover(result, ".", "typescript")
    assert row.status == "partial"
    assert "src/a.ts:1" in row.detail
    assert "src/a.ts:2" in row.detail


@needs_ts
def test_syntax_error_is_a_site_and_names_survive(tmp_path):
    result = solo(tmp_path, "export const ok = 1;\nexport const = ;\n")
    assert "ok" in names(result)
    row = cover(result, ".", "typescript")
    assert row.status == "partial"
    assert "src/a.ts:" in row.detail


@needs_ts
def test_tsx_and_javascript_get_their_own_rows(tmp_path):
    package(tmp_path, ".")
    write(tmp_path, "ui/Button.tsx", "export const Button = () => <b />;\n")
    write(tmp_path, "lib/x.js", "export function x() {}\nexport default 1;\n")
    write(tmp_path, "lib/y.mjs", "export const y = 1;\n")
    result = run_symbols(tmp_path)
    assert {"Button", "x", "y"} <= set(names(result))
    assert ["x", "function", "lib/x.js"] in rows(result, "sym.root")
    assert cover(result, ".", "tsx").status == "complete"
    assert cover(result, ".", "javascript").status == "complete"


@needs_ts
def test_commonjs_only_file_has_no_symbols_and_stays_complete(tmp_path):
    result = solo(tmp_path, "module.exports = { a: 1 };\n", "jest.config.js")
    assert not result.sections
    assert cover(result, ".", "javascript").status == "complete"


# --- CSS / SCSS ------------------------------------------------------------


@needs_ts
def test_css_custom_properties(tmp_path):
    package(tmp_path, "apps/web", "web")
    write(
        tmp_path,
        "apps/web/src/tokens.css",
        ":root { --admin-danger: #ff0001; --admin-danger: #0000fe; }\n"
        "@media (min-width: 1px) { .a { --in-media: 1px; color: var(--used-only); } }\n"
        "@property --registered { syntax: '<color>'; inherits: false; }\n"
        "/* --commented: gone */\n",
    )
    write(tmp_path, "apps/web/src/other.css", ":root { --admin-danger: green; }\n")
    result = run_symbols(tmp_path)
    got = rows(result, "sym.apps-web")
    assert ["--admin-danger", "css-var", "apps/web/src/tokens.css"] in got
    assert ["--admin-danger", "css-var", "apps/web/src/other.css"] in got
    assert (
        sum(r[0] == "--admin-danger" and r[2].endswith("tokens.css") for r in got) == 1
    )
    flat = {r[0] for r in got}
    assert {"--in-media", "--registered"} <= flat
    assert not flat & {"--used-only", "--commented"}
    assert not any("ff0001" in c or "0000fe" in c for r in got for c in r)
    assert cover(result, "apps/web", "css").status == "complete"


@needs_ts
def test_scss_vars_excluded_and_interpolated_values_read(tmp_path):
    package(tmp_path, ".")
    write(
        tmp_path,
        "styles/_tokens.scss",
        "$brand: #fff;\n// --line-comment: 1\n"
        ":root {\n  --a: #{$brand};\n  --b: calc(1px + #{$x});\n  --c: 3\n}\n"
        "@mixin m { --in-mixin: 1 }\n",
    )
    result = run_symbols(tmp_path)
    assert sorted(names(result)) == ["--a", "--b", "--c", "--in-mixin"]
    assert cover(result, ".", "scss").status == "complete"


@needs_ts
def test_scss_interpolated_property_name_is_a_site(tmp_path):
    package(tmp_path, ".")
    write(tmp_path, "s.scss", ":root { --static: 1; --#{$k}: 2; }\n")
    result = run_symbols(tmp_path)
    assert "--static" in names(result)
    row = cover(result, ".", "scss")
    assert row.status == "partial"
    assert "s.scss:1" in row.detail


# --- skips -----------------------------------------------------------------


@needs_ts
def test_generated_and_test_files_skipped(tmp_path):
    package(tmp_path, ".")
    write(tmp_path, "src/keep.ts", "export const keep = 1;\n")
    write(tmp_path, "src/types.d.ts", "export const decl = 1;\n")
    write(tmp_path, "src/api.generated.ts", "export const gen1 = 1;\n")
    write(tmp_path, "src/__generated__/g.ts", "export const gen2 = 1;\n")
    write(tmp_path, "src/a.test.ts", "export const t1 = 1;\n")
    write(tmp_path, "src/a.spec.tsx", "export const t2 = 1;\n")
    write(tmp_path, "src/__tests__/b.ts", "export const t3 = 1;\n")
    write(tmp_path, "test/c.ts", "export const t4 = 1;\n")
    write(tmp_path, "tests/d.ts", "export const t5 = 1;\n")
    write(tmp_path, "node_modules/x/index.ts", "export const nm = 1;\n")
    write(tmp_path, "dist/o.js", "export const out = 1;\n")
    result = run_symbols(tmp_path)
    assert names(result) == ["keep"]
    detail = cover(result, ".", "typescript").detail
    assert detail.startswith("skipped ")
    assert "1 *.d.ts" in detail
    assert "2 generated" in detail
    assert "4 test" in detail  # a.test.ts, __tests__/b.ts, test/c.ts, tests/d.ts
    assert cover(result, ".", "typescript").status == "complete"
    assert cover(result, ".", "tsx").detail == "skipped 1 test"


def test_skip_detail_is_classified_as_prose():
    rows_ = [
        _coverage.CoverageRow(
            "symbols", ".", "typescript", "partial", "skipped 2 test; a.ts:1"
        )
    ]
    assert _coverage.merge_rows(rows_)[0].detail == "skipped 2 test; a.ts:1"
    assert not _coverage._is_site("skipped 2 test")
    assert not _coverage._is_site("no exporter for go yet")


# --- degrade ---------------------------------------------------------------


@needs_ts
def test_language_without_exporter_not_scanned(tmp_path, monkeypatch):
    package(tmp_path, ".")
    write(tmp_path, "a.ts", "export const a = 1;\n")
    write(tmp_path, "s.css", ":root { --x: 1; }\n")
    write(tmp_path, "main.go", "package main\nfunc Main() {}\n")
    monkeypatch.delitem(symbols.EXPORTERS, "css")
    result = run_symbols(tmp_path)
    css = cover(result, ".", "css")
    assert (css.status, css.detail) == ("not scanned", "no exporter for css yet")
    assert cover(result, ".", "go").status == "not scanned"
    assert names(result) == ["a"]  # the language that has one still lists
    assert cover(result, ".", "typescript").status == "complete"


def test_without_tree_sitter_not_scanned_and_no_sections(tmp_path, monkeypatch):
    package(tmp_path, "apps/api")
    write(tmp_path, "apps/api/a.ts", "export const a = 1;\n")
    write(tmp_path, "apps/api/s.css", ":root { --x: 1; }\n")
    monkeypatch.setattr(_ts, "available", lambda: False)
    result = run_symbols(tmp_path)
    assert result.sections == []
    got = {(r.scope, r.framework, r.status, r.detail) for r in result.coverage}
    assert got == {
        ("apps/api", "typescript", "not scanned", _coverage.NOT_INSTALLED),
        ("apps/api", "css", "not scanned", _coverage.NOT_INSTALLED),
    }
    assert len(result.warnings) == 1
    assert "install strata-kb[code]" in result.warnings[0]


@needs_ts
def test_exporter_crash_degrades_to_a_site(tmp_path, monkeypatch):
    def boom(_tree, _source):
        raise RuntimeError("boom")

    package(tmp_path, ".")
    write(tmp_path, "a.ts", "export const a = 1;\n")
    monkeypatch.setitem(symbols.EXPORTERS, "typescript", boom)
    result = run_symbols(tmp_path)
    row = cover(result, ".", "typescript")
    assert (row.status, row.detail) == ("partial", "a.ts:1")
    assert any("boom" in w for w in result.warnings)


# --- sections --------------------------------------------------------------


@needs_ts
def test_section_shape_sorted_never_truncated(tmp_path):
    package(tmp_path, "packages/big", "big")
    body = "".join(f"export const n{i:04d} = {i};\n" for i in range(600))
    write(tmp_path, "packages/big/src/z.ts", body)
    write(
        tmp_path,
        "packages/big/src/a.ts",
        "export const zz = 1;\nexport const aa = 2;\n",
    )
    result = run_symbols(tmp_path)
    sec = section(result, "sym.packages-big")
    assert (sec.group, sec.title) == ("symbols", "Symbols: packages/big")
    assert sec.summary
    assert sec.l2_md.splitlines()[0] == "| Name | Kind | File |"
    got = rows(result, "sym.packages-big")
    assert len(got) == 602
    assert got[:2] == [
        ["aa", "const", "packages/big/src/a.ts"],
        ["zz", "const", "packages/big/src/a.ts"],
    ]
    assert got == sorted(got, key=lambda r: (r[2], r[0]))
    assert sec.l3_md.startswith("```\n") and sec.l3_md.count("\n") >= 602


@needs_ts
def test_root_scope_is_sym_root_and_nested_scope_is_separate(tmp_path):
    package(tmp_path, ".")
    package(tmp_path, "apps/api")
    write(tmp_path, "src/r.ts", "export const rootOnly = 1;\n")
    write(tmp_path, "apps/api/src/x.ts", "export const apiOnly = 1;\n")
    result = run_symbols(tmp_path)
    assert sorted(s.id for s in result.sections) == ["sym.apps-api", "sym.root"]
    assert names(result) == ["rootOnly"]
    assert names(result, "sym.apps-api") == ["apiOnly"]
    assert section(result, "sym.root").title == "Symbols: repo"


@needs_ts
def test_files_without_a_package_group_by_top_directory(tmp_path):
    write(tmp_path, "src/a.ts", "export const a = 1;\n")
    write(tmp_path, "lib/b.ts", "export const b = 1;\n")
    write(tmp_path, "top.ts", "export const top = 1;\n")
    result = run_symbols(tmp_path)
    assert sorted(s.id for s in result.sections) == ["sym.lib", "sym.root", "sym.src"]
    assert cover(result, "src", "typescript").status == "complete"
    assert cover(result, ".", "typescript").status == "complete"


@needs_ts
def test_scope_without_symbols_has_a_row_but_no_section(tmp_path):
    result = solo(tmp_path, "const hidden = 1;\n")
    assert result.sections == []
    assert cover(result, ".", "typescript").status == "complete"


@needs_ts
def test_output_is_deterministic(tmp_path):
    package(tmp_path, ".")
    write(
        tmp_path, "src/a.ts", "export const a = {X: 1, Y: 2};\nexport * from './b';\n"
    )
    write(tmp_path, "src/b.ts", "export class B {}\n")
    first, second = run_symbols(tmp_path), run_symbols(tmp_path)
    assert first == second


def test_detect(tmp_path):
    ext = symbols.SymbolsExtractor()
    write(tmp_path, "README.md", "x")
    assert not ext.detect(tmp_path)
    write(tmp_path, "a.ts", "export const a = 1;\n")
    assert ext.detect(tmp_path)
