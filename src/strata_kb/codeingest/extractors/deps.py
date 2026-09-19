"""deps extractor — dependency manifests across nine ecosystems, with a
shared framework-detection table.

Each per-ecosystem reader below degrades rather than raises: a malformed
manifest becomes a warning naming the file (via `tree.relposix`), never a
crash, and the readers for every other ecosystem still run. A manifest that
exists but yields no dependencies is likewise a warning, not silence, so a
typo'd `pyproject.toml` doesn't just quietly disappear from the output.
That "yields nothing" warning is scored per *ecosystem*, deliberately, not
per manifest file: a repo commonly carries a `setup.cfg` used only for
tool config (flake8/mypy, no `install_requires`) right beside a real
`pyproject.toml` that does declare dependencies, and warning about the
former every run — once the ecosystem as a whole has evidence — would be
noise, not signal.

`detect_frameworks()` is the one function this module exposes beyond
`DepsExtractor` itself — Task B4 reuses it, unmodified, to label a
service's `technology` from the same dependency names.

`DepsExtractor.detect()` cannot see `opts.kb_dir`: `Extractor.detect(self,
root)` is a frozen protocol method that is never passed `opts`, so its one
tree walk always runs unpruned-by-kb_dir. Consequence: if `--kb-dir` points
somewhere *inside* the repo that happens to contain a file matching one of
this module's multi-file patterns (`package.json`, `requirements*.txt`,
`*.csproj`, `build.gradle*`, `Cargo.toml`, `Package.swift`,
`pubspec.yaml`) — most plausibly the KB's own previously
generated output sitting next to a real manifest — `detect()` can still
report `True` from evidence elsewhere in the tree (so `core.run()`'s
zero-detection guard correctly isn't tripped), while `extract()` — which
does have `opts.kb_dir` and prunes it via every reader's
`walk_tree(root, opts.kb_dir)` call — finds nothing there and contributes
zero sections. This is accepted, not routed around: widening
`Extractor.detect()`'s signature is out of scope, and the failure mode is
silent-but-safe (a quieter `deps` group), never a wrong one.
"""
from __future__ import annotations

import configparser
import fnmatch
import json
import re
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from pathlib import Path

import yaml

from center_kb.codeingest.core import CodeIngestOptions, CodeSection, ExtractResult
from center_kb.codeingest.extractors._envkeys import redact_userinfo
from center_kb.codeingest.extractors._mdcells import escape_cell
from center_kb.codeingest.extractors.tree import relposix, walk_tree

# ---------------------------------------------------------------------------
# framework detection — published interface, reused by Task B4.
# ---------------------------------------------------------------------------

FRAMEWORKS: tuple[tuple[str, str], ...] = (
    ("spring-boot", "Spring Boot"),
    ("quarkus", "Quarkus"),
    ("micronaut", "Micronaut"),
    ("microsoft.aspnetcore", "ASP.NET Core"),
    ("microsoft.entityframeworkcore", "Entity Framework Core"),
    ("fastapi", "FastAPI"),
    ("django", "Django"),
    ("flask", "Flask"),
    ("sqlalchemy", "SQLAlchemy"),
    ("celery", "Celery"),
    ("@angular/core", "Angular"),
    ("@nestjs/core", "NestJS"),
    ("next", "Next.js"),
    ("nuxt", "Nuxt"),
    ("react", "React"),
    ("vue", "Vue"),
    ("svelte", "Svelte"),
    ("express", "Express"),
    ("github.com/gin-gonic/gin", "Gin"),
    ("laravel/framework", "Laravel"),
    ("symfony/framework-bundle", "Symfony"),
    ("@playwright/test", "Playwright"),
    ("actix-web", "Actix Web"),
    ("axum", "Axum"),
    ("rocket", "Rocket"),
    ("vapor", "Vapor"),
    ("flutter", "Flutter"),
)


_NAME_SEPARATORS = frozenset("-./_")


def detect_frameworks(names: Iterable[str]) -> list[str]:
    """Deterministic: sorted, de-duplicated labels.

    Each name is matched case-insensitively against every `FRAMEWORKS`
    prefix; when more than one prefix matches the same name, the longest
    prefix wins so a broader entry (e.g. a hypothetical `"spring"`) could
    never shadow a more specific one (`"spring-boot"`). A prefix only
    counts as a match at a name boundary — either the whole name, or the
    character right after the prefix is a non-alphanumeric separator — so
    `"react"` cannot match `"reactive-streams"` (a real Maven artifactId,
    unrelated to the JS framework), nor `"express"` match `"expressive"`,
    `"next"` match `"nextcloud-client"`, etc.
    """
    labels: set[str] = set()
    for name in names:
        lname = name.lower()
        best_len = -1
        best_label = ""
        for prefix, label in FRAMEWORKS:
            lprefix = prefix.lower()
            if not lname.startswith(lprefix):
                continue
            at_boundary = (
                len(lname) == len(lprefix)
                or lname[len(lprefix)] in _NAME_SEPARATORS
            )
            if at_boundary and len(lprefix) > best_len:
                best_len = len(lprefix)
                best_label = label
        if best_label:
            labels.add(best_label)
    return sorted(labels)


# ---------------------------------------------------------------------------
# shared reader helpers
# ---------------------------------------------------------------------------

# Groups map a scope name to its (name, constraint) pairs. Every ecosystem
# uses "direct"; node and php add "dev"; python adds "extra:<name>" per
# `[project.optional-dependencies]` table and one group per non-root
# `requirements*.txt`, named by that file's repo-relative path. Every group
# is rendered (reviewer G-5) — names in L2, constraints in L3.
Groups = dict[str, list[tuple[str, str]]]

_NODE_MAX_DEPTH = 2  # package.json is only searched at depth <= 2
_PEP508_SPLIT_RE = re.compile(r"[><=!~\[;]")
_OPERATOR_LEAD_CHARS = "<>=!~^["
_GRADLE_DEP_RE = re.compile(
    r"""(?:implementation|api|compileOnly|testImplementation)\s*[('"]+([^'")]+)"""
)
_GO_REQUIRE_LINE_RE = re.compile(r"^require\s+(\S+)\s+(\S+)")


def _split_pep508(spec: str) -> tuple[str, str]:
    """Split a PEP 508 requirement string at its first version/extras/
    marker operator: `"fastapi>=0.110"` -> `("fastapi", ">=0.110")`."""
    spec = spec.strip()
    match = _PEP508_SPLIT_RE.search(spec)
    if match is None:
        return spec, ""
    idx = match.start()
    return spec[:idx].strip(), spec[idx:].strip()


def _split_gradle_coordinate(raw: str) -> tuple[str, str]:
    """Gradle's short-form coordinate is `group:artifact[:version]`. Keep
    the artifact id as the dependency name — matching Maven's bare
    `artifactId`, so the same library is recognised as the same dependency
    (and the same framework) whether the project builds with Maven or
    Gradle — and the version, when present, as the constraint. Falls back
    to the raw, unsplit string when it isn't 2-3 colon-separated parts
    (e.g. a project/version-catalog reference like `libs.spring.boot`)."""
    parts = raw.split(":")
    if len(parts) == 2:
        return parts[1], ""
    if len(parts) == 3:
        return parts[1], parts[2]
    return raw, ""


def _fmt_dep(name: str, constraint: str) -> str:
    """Render one L3 dependency line. A constraint that already starts
    with a version operator (PEP 508's `>=`, npm's `^`/`~`, ...) reads
    naturally concatenated (`fastapi>=0.110`); a bare version number gets a
    separating space (`spring-boot-starter-web 3.2.0`). Both `name` and
    `constraint` are run through `redact_userinfo` first (task review,
    Important 2) -- a PEP 508 direct-URL requirement or an npm
    `git+https://token@...` dependency is the normal way a private
    package is declared, and either can carry a `user:pass@`/`token@`
    credential the source repo already committed in plaintext; `.kb/`
    republishes it to the federation hub, an audience wider than that
    repo."""
    name = redact_userinfo(name)
    constraint = redact_userinfo(constraint)
    if not constraint:
        return name
    if constraint[0] in _OPERATOR_LEAD_CHARS:
        return f"{name}{constraint}"
    return f"{name} {constraint}"


def _dedupe_sorted(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    # The key must be *total* (never tie) or `sorted()`'s stability just
    # preserves `set(pairs)`'s iteration order for ties — and `str` hashing
    # is randomized per process, so two case-colliding names (`"Flask"` and
    # `"flask"` from two different manifests) would swap places from run to
    # run. Comparing the raw (case-sensitive) name after the lowercase key
    # breaks every tie deterministically.
    return sorted(set(pairs), key=lambda p: (p[0].lower(), p[0], p[1]))


def _merge(groups: Groups, group: str, pairs: list[tuple[str, str]]) -> None:
    if not pairs:
        return
    groups.setdefault(group, []).extend(pairs)


def _finish(groups: Groups, warnings: list[str], existing: list[str]) -> tuple[Groups, list[str]]:
    """Sort every group by name; if manifests were found but none produced
    a dependency and nothing more specific already explains why, warn once
    naming the manifest(s) considered."""
    for group in groups:
        groups[group] = _dedupe_sorted(groups[group])
    total = sum(len(v) for v in groups.values())
    if total == 0 and existing and not warnings:
        warnings.append(f"no dependencies found in {', '.join(sorted(existing))}")
    return groups, warnings


# ---------------------------------------------------------------------------
# python — pyproject.toml, setup.cfg, requirements*.txt
# ---------------------------------------------------------------------------


def _read_python(root: Path, opts: CodeIngestOptions) -> tuple[Groups, list[str]]:
    groups: Groups = {}
    warnings: list[str] = []
    existing: list[str] = []

    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        rel = relposix(root, pyproject)
        existing.append(rel)
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError) as exc:
            warnings.append(f"could not parse {rel}: {exc}")
        else:
            # `tomllib.loads` always returns a dict at the top level, but
            # `project` (and `dependencies` under it) are just keys — a
            # pyproject.toml with a scalar `project = "..."` would otherwise
            # crash `.get("dependencies")` on a str and take the whole
            # ecosystem down with it (every reader here must degrade a
            # wrong-shaped manifest, not just a malformed one).
            if not isinstance(data, dict):
                warnings.append(f"could not parse {rel}: top-level is not a table")
            else:
                project = data.get("project", {})
                if not isinstance(project, dict):
                    warnings.append(f"could not parse {rel}: 'project' is not a table")
                else:
                    deps = project.get("dependencies", [])
                    if isinstance(deps, list):
                        _merge(groups, "direct", [
                            _split_pep508(d) for d in deps if isinstance(d, str)
                        ])
                    elif deps:
                        warnings.append(
                            f"could not parse {rel}: 'project.dependencies' is not a list"
                        )

                    extras = project.get("optional-dependencies", {})
                    if isinstance(extras, dict):
                        for extra in sorted(extras, key=str):
                            specs = extras[extra]
                            if isinstance(specs, list):
                                _merge(groups, f"extra:{extra}", [
                                    _split_pep508(d) for d in specs if isinstance(d, str)
                                ])
                            else:
                                warnings.append(
                                    f"could not parse {rel}: optional-dependencies "
                                    f"{extra!r} is not a list"
                                )
                    elif extras:
                        warnings.append(
                            f"could not parse {rel}: 'project.optional-dependencies' is not a table"
                        )

    setup_cfg = root / "setup.cfg"
    if setup_cfg.is_file():
        rel = relposix(root, setup_cfg)
        existing.append(rel)
        parser = configparser.ConfigParser()
        try:
            parser.read_string(setup_cfg.read_text(encoding="utf-8"))
            raw = parser.get("options", "install_requires", fallback="")
        except (configparser.Error, OSError, UnicodeDecodeError) as exc:
            warnings.append(f"could not parse {rel}: {exc}")
        else:
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            _merge(groups, "direct", [_split_pep508(ln) for ln in lines])

    for _depth, reldir, filenames in walk_tree(root, opts.kb_dir):
        for name in filenames:
            if not fnmatch.fnmatch(name, "requirements*.txt"):
                continue
            path = root / reldir / name
            rel = relposix(root, path)
            existing.append(rel)
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                warnings.append(f"could not parse {rel}: {exc}")
                continue
            pairs = []
            for line in text.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                # Any pip option line (`-r other.txt`, `-e .`,
                # `--extra-index-url ...`, `--index-url ...`, ...) starts
                # with `-`, not a package name — and a trailing `# comment`
                # on an otherwise-real line must not leak into the
                # constraint (`fastapi>=0.110  # web` is a dependency plus
                # a comment, not a dependency whose constraint is
                # `>=0.110  # web`).
                if stripped.startswith("-"):
                    continue
                code_part = stripped.split("#", 1)[0].strip()
                if not code_part:
                    continue
                pairs.append(_split_pep508(code_part))
            # Only the root requirements.txt is the runtime set; every other
            # requirements file (a CI runner venv, a docs build) is its own
            # group so nothing is duplicated or misattributed (reviewer G-5).
            _merge(groups, "direct" if rel == "requirements.txt" else rel, pairs)

    return _finish(groups, warnings, existing)


# ---------------------------------------------------------------------------
# node — every package.json at depth <= 2
# ---------------------------------------------------------------------------


def _read_node(root: Path, opts: CodeIngestOptions) -> tuple[Groups, list[str]]:
    groups: Groups = {}
    warnings: list[str] = []
    existing: list[str] = []

    for depth, reldir, filenames in walk_tree(root, opts.kb_dir):
        if depth > _NODE_MAX_DEPTH or "package.json" not in filenames:
            continue
        path = root / reldir / "package.json"
        rel = relposix(root, path)
        existing.append(rel)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            warnings.append(f"could not parse {rel}: {exc}")
            continue
        # JSON, unlike TOML, can legally have any type at the top level —
        # a package.json that is `[]` or a bare string parses without
        # error but has no `.get()`; guard it the same way a malformed
        # file is guarded, and keep processing every other package.json
        # this reader finds.
        if not isinstance(data, dict):
            warnings.append(f"could not parse {rel}: top-level is not an object")
            continue
        direct = data.get("dependencies", {})
        dev = data.get("devDependencies", {})
        if isinstance(direct, dict):
            _merge(groups, "direct", [(k, str(v)) for k, v in direct.items()])
        if isinstance(dev, dict):
            _merge(groups, "dev", [(k, str(v)) for k, v in dev.items()])

    return _finish(groups, warnings, existing)


# ---------------------------------------------------------------------------
# java — pom.xml + build.gradle(.kts)
# ---------------------------------------------------------------------------


def _read_java(root: Path, opts: CodeIngestOptions) -> tuple[Groups, list[str]]:
    groups: Groups = {}
    warnings: list[str] = []
    existing: list[str] = []

    pom = root / "pom.xml"
    if pom.is_file():
        rel = relposix(root, pom)
        existing.append(rel)
        try:
            xml_tree = ET.parse(pom)  # noqa: S314 -- ET resolves no external entities (no XXE); expat's amplification limit refuses billion-laughs/quadratic blowup as ET.ParseError, already handled below
        except (ET.ParseError, OSError, UnicodeDecodeError) as exc:
            warnings.append(f"could not parse {rel}: {exc}")
        else:
            pairs = []
            for elem in xml_tree.getroot().iter():
                if not elem.tag.endswith("dependency"):
                    continue
                artifact = ""
                version = ""
                for child in elem:
                    tag = child.tag.rsplit("}", 1)[-1]
                    if tag == "artifactId" and child.text:
                        artifact = child.text.strip()
                    elif tag == "version" and child.text:
                        version = child.text.strip()
                if artifact:
                    pairs.append((artifact, version))
            _merge(groups, "direct", pairs)

    for _depth, reldir, filenames in walk_tree(root, opts.kb_dir):
        for name in filenames:
            if name not in ("build.gradle", "build.gradle.kts"):
                continue
            path = root / reldir / name
            rel = relposix(root, path)
            existing.append(rel)
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                warnings.append(f"could not parse {rel}: {exc}")
                continue
            matches = _GRADLE_DEP_RE.findall(text)
            _merge(groups, "direct", [_split_gradle_coordinate(m.strip()) for m in matches])

    return _finish(groups, warnings, existing)


# ---------------------------------------------------------------------------
# dotnet — *.csproj
# ---------------------------------------------------------------------------


def _read_dotnet(root: Path, opts: CodeIngestOptions) -> tuple[Groups, list[str]]:
    groups: Groups = {}
    warnings: list[str] = []
    existing: list[str] = []

    for _depth, reldir, filenames in walk_tree(root, opts.kb_dir):
        for name in filenames:
            if not name.endswith(".csproj"):
                continue
            path = root / reldir / name
            rel = relposix(root, path)
            existing.append(rel)
            try:
                xml_tree = ET.parse(path)  # noqa: S314 -- ET resolves no external entities (no XXE); expat's amplification limit refuses billion-laughs/quadratic blowup as ET.ParseError, already handled below
            except (ET.ParseError, OSError, UnicodeDecodeError) as exc:
                warnings.append(f"could not parse {rel}: {exc}")
                continue
            pairs = []
            for elem in xml_tree.getroot().iter():
                if not elem.tag.endswith("PackageReference"):
                    continue
                pkg_name = elem.get("Include", "")
                version = elem.get("Version", "")
                if not version:
                    for child in elem:
                        tag = child.tag.rsplit("}", 1)[-1]
                        if tag == "Version" and child.text:
                            version = child.text.strip()
                if pkg_name:
                    pairs.append((pkg_name, version))
            _merge(groups, "direct", pairs)

    return _finish(groups, warnings, existing)


# ---------------------------------------------------------------------------
# go — go.mod
# ---------------------------------------------------------------------------


def _read_go(root: Path, opts: CodeIngestOptions) -> tuple[Groups, list[str]]:
    groups: Groups = {}
    warnings: list[str] = []
    existing: list[str] = []

    go_mod = root / "go.mod"
    if go_mod.is_file():
        rel = relposix(root, go_mod)
        existing.append(rel)
        try:
            text = go_mod.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            warnings.append(f"could not parse {rel}: {exc}")
        else:
            pairs = []
            in_block = False
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("require") and stripped.endswith("("):
                    in_block = True
                    continue
                if in_block:
                    if stripped == ")":
                        in_block = False
                        continue
                    if not stripped or stripped.startswith("//"):
                        continue
                    parts = stripped.split()
                    if len(parts) >= 2:
                        pairs.append((parts[0], parts[1]))
                    continue
                if not stripped or stripped.startswith("//"):
                    continue
                match = _GO_REQUIRE_LINE_RE.match(stripped)
                if match:
                    pairs.append((match.group(1), match.group(2)))
            _merge(groups, "direct", pairs)

    return _finish(groups, warnings, existing)


# ---------------------------------------------------------------------------
# php — composer.json
# ---------------------------------------------------------------------------


def _read_php(root: Path, opts: CodeIngestOptions) -> tuple[Groups, list[str]]:
    groups: Groups = {}
    warnings: list[str] = []
    existing: list[str] = []

    composer = root / "composer.json"
    if composer.is_file():
        rel = relposix(root, composer)
        existing.append(rel)
        try:
            data = json.loads(composer.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            warnings.append(f"could not parse {rel}: {exc}")
        else:
            if not isinstance(data, dict):
                warnings.append(f"could not parse {rel}: top-level is not an object")
            else:
                direct = data.get("require", {})
                dev = data.get("require-dev", {})
                if isinstance(direct, dict):
                    _merge(groups, "direct", [(k, str(v)) for k, v in direct.items()])
                if isinstance(dev, dict):
                    _merge(groups, "dev", [(k, str(v)) for k, v in dev.items()])

    return _finish(groups, warnings, existing)


# ---------------------------------------------------------------------------
# rust — every Cargo.toml in the tree (workspace members included)
# ---------------------------------------------------------------------------


def _cargo_constraint(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        version = value.get("version", "")
        return version if isinstance(version, str) else ""
    return ""


def _inherits_workspace(value: object) -> bool:
    """`serde = { workspace = true }` / `serde.workspace = true` — the
    member declares the dependency but delegates its version to the
    workspace root's `[workspace.dependencies]`. Both spellings parse to
    the same table, so one check covers them."""
    return isinstance(value, dict) and value.get("workspace") is True


# (manifest table, group name) — `build-dependencies` (build scripts:
# tonic-build, cc, bindgen) is a real, separately-installed set, so it
# gets its own group rather than being folded into `direct` or dropped.
_CARGO_TABLES: tuple[tuple[str, str], ...] = (
    ("dependencies", "direct"),
    ("dev-dependencies", "dev"),
    ("build-dependencies", "build"),
)


def _read_rust(root: Path, opts: CodeIngestOptions) -> tuple[Groups, list[str]]:
    """Every `Cargo.toml` in the tree, in two passes.

    The first pass parses each manifest and collects the workspace
    root's `[workspace.dependencies]` into a version catalogue; the
    second resolves each member's `workspace = true` entries against it.
    Two passes because a workspace root need not be walked before its
    members, and no reader may depend on `walk_tree`'s order for
    correctness.

    That catalogue is a **lookup table only** — its entries are never
    themselves reported as dependencies. `[workspace.dependencies]`
    declares available versions, not use: a root listing thirty of them
    for members that pull five would otherwise report thirty, which is
    exactly the kind of claim the `-code` document must not make. And a
    member that overrides an entry (`serde = { git = ... }`, no
    `workspace = true`) keeps its own constraint, never the catalogue's.
    """
    groups: Groups = {}
    warnings: list[str] = []
    existing: list[str] = []
    manifests: list[dict] = []
    workspace_versions: dict[str, str] = {}

    for _depth, reldir, filenames in walk_tree(root, opts.kb_dir):
        if "Cargo.toml" not in filenames:
            continue
        path = root / reldir / "Cargo.toml"
        rel = relposix(root, path)
        existing.append(rel)
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError) as exc:
            warnings.append(f"could not parse {rel}: {exc}")
            continue
        if not isinstance(data, dict):
            warnings.append(f"could not parse {rel}: top-level is not a table")
            continue
        manifests.append(data)
        workspace = data.get("workspace")
        catalogue = workspace.get("dependencies") if isinstance(workspace, dict) else None
        if isinstance(catalogue, dict):
            for name, value in catalogue.items():
                constraint = _cargo_constraint(value)
                if constraint:
                    workspace_versions.setdefault(name, constraint)

    for data in manifests:
        for table, group in _CARGO_TABLES:
            section = data.get(table, {})
            if not isinstance(section, dict):
                continue
            _merge(groups, group, [
                (
                    name,
                    workspace_versions.get(name, "")
                    if _inherits_workspace(value)
                    else _cargo_constraint(value),
                )
                for name, value in section.items()
            ])

    return _finish(groups, warnings, existing)


# ---------------------------------------------------------------------------
# swift — every Package.swift in the tree (multi-module layouts), each a
# best-effort text scan (it is Swift source, not data: SwiftPM has no
# data-only manifest format)
# ---------------------------------------------------------------------------

_SWIFT_PACKAGE_CALL_RE = re.compile(r"\.package\(")
_SWIFT_URL_RE = re.compile(r'url:\s*"([^"]+)"')
_SWIFT_NAME_RE = re.compile(r'name:\s*"([^"]+)"')
_SWIFT_PATH_RE = re.compile(r'path:\s*"([^"]+)"')
_SWIFT_VERSION_RE = re.compile(r'(?:from|exact)\s*:\s*"([^"]+)"')


def _strip_swift_comments(text: str) -> str:
    """Blank out `//` line comments and `/* */` block comments (Swift's
    nest, unlike C's), leaving string literals intact.

    A dependency that has been commented out while the repo migrates off
    it is not a dependency, and reporting one is exactly the claim the
    `-code` document must not make -- but the strip has to be
    string-aware to find that out: every `.package(url: ...)` carries a
    `https://` whose `//` a naive line-comment strip would read as the
    start of a comment, deleting the URL, the version and the closing
    paren of a live dependency. Swift's raw strings (`#"..."#`) are not
    modelled: one holding a `//` or `/*` is conceivable but has no reason
    to appear in a manifest, and the failure would be a dropped
    dependency, not a crash."""
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text.startswith('"""', i):
            end = text.find('"""', i + 3)
            stop = n if end < 0 else end + 3
            out.append(text[i:stop])
            i = stop
        elif text[i] == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            stop = min(j + 1, n)
            out.append(text[i:stop])
            i = stop
        elif text.startswith("//", i):
            end = text.find("\n", i)
            # Stop *at* the newline, never past it: it still separates
            # this line from the next for anything scanning afterwards.
            i = n if end < 0 else end
        elif text.startswith("/*", i):
            depth = 1
            j = i + 2
            while j < n and depth:
                if text.startswith("/*", j):
                    depth += 1
                    j += 2
                elif text.startswith("*/", j):
                    depth -= 1
                    j += 2
                else:
                    j += 1
            i = j
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _iter_swift_package_calls(text: str) -> Iterable[str]:
    """Yield each `.package(...)` call's argument text, delimited by
    counting parens from the `.package(` that opens it -- a plain regex
    can't stop at the right `)` when the call nests one of its own
    (`.upToNextMajor(from: "1.2.3")`).

    Scanning resumes *after* the call just consumed, never from the next
    `.package(` inside it. With `re.finditer` an unterminated call (one
    stray `(`, or a truncated manifest) made every later match re-scan to
    EOF, which is quadratic in the file size -- measured 2.1s at 18 KB,
    10.2s at 36 KB, 28.3s at 72 KB, so ~90 minutes for a ~1 MB file. A
    hang is the one failure `DepsExtractor.extract`'s blanket
    `except Exception` cannot degrade into a warning."""
    pos = 0
    n = len(text)
    while (match := _SWIFT_PACKAGE_CALL_RE.search(text, pos)) is not None:
        start = match.end()
        depth = 1
        i = start
        while i < n and depth > 0:
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
            i += 1
        yield text[start : i - 1] if depth == 0 else text[start:i]
        pos = i


def _swift_dep_name(locator: str) -> str:
    name = locator.rstrip("/").rsplit("/", 1)[-1]
    return name[: -len(".git")] if name.endswith(".git") else name


def _read_swift(root: Path, opts: CodeIngestOptions) -> tuple[Groups, list[str]]:
    groups: Groups = {}
    warnings: list[str] = []
    existing: list[str] = []

    for _depth, reldir, filenames in walk_tree(root, opts.kb_dir):
        if "Package.swift" not in filenames:
            continue
        manifest = root / reldir / "Package.swift"
        rel = relposix(root, manifest)
        existing.append(rel)
        try:
            text = manifest.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            warnings.append(f"could not parse {rel}: {exc}")
            continue
        pairs = []
        for call in _iter_swift_package_calls(_strip_swift_comments(text)):
            url_match = _SWIFT_URL_RE.search(call)
            if url_match:
                name = _swift_dep_name(url_match.group(1))
            else:
                name_match = _SWIFT_NAME_RE.search(call)
                path_match = _SWIFT_PATH_RE.search(call)
                if name_match:
                    name = name_match.group(1)
                elif path_match:
                    name = _swift_dep_name(path_match.group(1))
                else:
                    continue
            version_match = _SWIFT_VERSION_RE.search(call)
            pairs.append((name, version_match.group(1) if version_match else ""))
        _merge(groups, "direct", pairs)

    return _finish(groups, warnings, existing)


# ---------------------------------------------------------------------------
# dart — every pubspec.yaml in the tree (melos/monorepo packages)
# ---------------------------------------------------------------------------


def _dart_constraint(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        version = value.get("version", "")
        return version if isinstance(version, str) else ""
    return ""


def _read_dart(root: Path, opts: CodeIngestOptions) -> tuple[Groups, list[str]]:
    groups: Groups = {}
    warnings: list[str] = []
    existing: list[str] = []

    for _depth, reldir, filenames in walk_tree(root, opts.kb_dir):
        if "pubspec.yaml" not in filenames:
            continue
        pubspec = root / reldir / "pubspec.yaml"
        rel = relposix(root, pubspec)
        existing.append(rel)
        try:
            data = yaml.safe_load(pubspec.read_text(encoding="utf-8"))
        except (yaml.YAMLError, UnicodeDecodeError, OSError) as exc:
            warnings.append(f"could not parse {rel}: {exc}")
            continue
        if not isinstance(data, dict):
            warnings.append(f"could not parse {rel}: top-level is not a mapping")
            continue
        direct = data.get("dependencies", {})
        dev = data.get("dev_dependencies", {})
        # `str(k)` for the same reason `_read_node` wraps its constraint:
        # a YAML mapping key is not necessarily a string (`1.5:` parses to
        # a float, and YAML 1.1 reads a bare `no:`/`on:` as a bool), while
        # every shared helper downstream -- `_dedupe_sorted`'s
        # `p[0].lower()` first -- assumes a `str` name. Without the cast
        # that AttributeError unwinds past this reader's per-file `try`
        # to `extract()`'s blanket handler and drops every other
        # pubspec.yaml in the repo with it, naming no file.
        if isinstance(direct, dict):
            _merge(groups, "direct", [(str(k), _dart_constraint(v)) for k, v in direct.items()])
        if isinstance(dev, dict):
            _merge(groups, "dev", [(str(k), _dart_constraint(v)) for k, v in dev.items()])

    return _finish(groups, warnings, existing)


# ---------------------------------------------------------------------------
# section rendering + extractor
# ---------------------------------------------------------------------------

# (section id, human label, reader key) — the first six match the brief's
# Step 4 ecosystem list (python, node, java, dotnet, go, php); rust/swift/
# dart were appended later, not alphabetical by id either way.
# core.run() re-sorts every extractor's sections by (group, id) before
# writing them out, so this order has no effect on the emitted files — it
# only affects which warning appears first when more than one ecosystem's
# manifest fails to parse in the same run.
_ECOSYSTEMS: tuple[tuple[str, str, str], ...] = (
    ("dep.python", "Python", "python"),
    ("dep.node", "Node", "node"),
    ("dep.java", "Java", "java"),
    ("dep.dotnet", ".NET", "dotnet"),
    ("dep.go", "Go", "go"),
    ("dep.php", "PHP", "php"),
    ("dep.rust", "Rust", "rust"),
    ("dep.swift", "Swift", "swift"),
    ("dep.dart", "Dart", "dart"),
)

_READERS = {
    "python": _read_python,
    "node": _read_node,
    "java": _read_java,
    "dotnet": _read_dotnet,
    "go": _read_go,
    "php": _read_php,
    "rust": _read_rust,
    "swift": _read_swift,
    "dart": _read_dart,
}


def _render_section(section_id: str, label: str, groups: Groups) -> CodeSection:
    direct = groups.get("direct", [])
    others = [(g, groups[g]) for g in sorted(groups) if g != "direct" and groups[g]]
    all_names = (name for deps in groups.values() for name, _constraint in deps)
    labels = detect_frameworks(all_names)

    l2_lines = [
        f"**Frameworks detected:** {', '.join(labels) if labels else 'none'}",
        "",
        "| Package | Constraint |",
        "| --- | --- |",
    ]
    l2_lines.extend(
        f"| {escape_cell(redact_userinfo(name))} | {escape_cell(redact_userinfo(constraint))} |"
        for name, constraint in direct
    )
    if others:
        # Names only — constraints are in L3 — so the L2 stays the condensed layer.
        l2_lines += ["", "| Group | Packages |", "| --- | --- |"]
        l2_lines.extend(
            f"| {escape_cell(group)} | "
            f"{escape_cell(', '.join(redact_userinfo(name) for name, _c in deps))} |"
            for group, deps in others
        )
    l2_md = "\n".join(l2_lines) + "\n"

    l3_blocks = []
    for group_name, deps in [("direct", direct), *others]:
        if not deps:
            continue
        body = "\n".join(_fmt_dep(name, constraint) for name, constraint in deps)
        l3_blocks.append(f"```\n# {group_name}\n{body}\n```")
    l3_md = "\n\n".join(l3_blocks) + "\n"

    # Count only names not already listed under `direct` — a non-root
    # requirements file that repeats a direct dependency (pinned to a
    # different constraint for that file) must not be claimed as "more"
    # when it isn't (reviewer finding: extra_count over-counted overlap).
    direct_names = {name for name, _constraint in direct}
    extra_count = sum(
        1 for _g, deps in others for name, _c in deps if name not in direct_names
    )
    summary = f"{len(direct)} direct {label} dependencies"
    if others:
        group_word = "group" if len(others) == 1 else "groups"
        summary += (
            f"; {extra_count} more in {len(others)} {group_word} "
            f"({', '.join(group for group, _d in others)})"
        )
    summary += f"; frameworks: {', '.join(labels)}." if labels else "."

    return CodeSection(
        id=section_id,
        title=f"{label} dependencies",
        summary=summary,
        group="deps",
        l2_md=l2_md,
        l3_md=l3_md,
    )


class DepsExtractor:
    name = "deps"

    def detect(self, root: Path) -> bool:
        if any(
            (root / name).is_file()
            for name in (
                "pyproject.toml", "setup.cfg", "pom.xml", "go.mod", "composer.json",
            )
        ):
            return True
        # No `opts` is available at detect() time (the Extractor protocol
        # is frozen and doesn't pass one), so `kb_dir` genuinely can't be
        # threaded through here — this is the one walk in this module that
        # legitimately calls walk_tree() without it.
        for depth, _reldir, filenames in walk_tree(root):
            for fname in filenames:
                if fname == "package.json" and depth <= _NODE_MAX_DEPTH:
                    return True
                if fnmatch.fnmatch(fname, "requirements*.txt"):
                    return True
                if fname.endswith(".csproj"):
                    return True
                if fname in ("build.gradle", "build.gradle.kts"):
                    return True
                if fname in ("Cargo.toml", "Package.swift", "pubspec.yaml"):
                    return True
        return False

    def extract(self, root: Path, opts: CodeIngestOptions) -> ExtractResult:
        sections: list[CodeSection] = []
        warnings: list[str] = []

        for section_id, label, key in _ECOSYSTEMS:
            reader = _READERS[key]
            try:
                groups, warns = reader(root, opts)
            except Exception as exc:  # noqa: BLE001 -- defense in depth: readers must never crash extract()
                groups, warns = {}, [f"could not read {label} manifests: {exc}"]
            warnings.extend(warns)
            if sum(len(v) for v in groups.values()) == 0:
                continue
            sections.append(_render_section(section_id, label, groups))

        return ExtractResult(sections=sections, warnings=warnings)
