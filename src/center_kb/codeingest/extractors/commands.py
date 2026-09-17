"""commands extractor — cmd.build / cmd.test / cmd.lint / cmd.run.

These are the sections `dev-execute` and `dev-handover` read to satisfy the
evidence rule (spec §3.14) — this is the task that makes Stage A's
verification gate executable: until these sections exist, a Dev agent has
no machine-readable answer to "how do I test this repo?".

Five readers surface command evidence from five sources — CI workflows, npm
scripts, a Makefile, tox/pytest config, and presence-based defaults for
Maven/Gradle/.NET/Go — each returning `list[Candidate]` (a `(purpose,
command, source)` triple) plus warnings, never raising. For each of the
four purposes in `PURPOSES`, the primary command is the first CI-sourced
candidate; failing that, the first local candidate in reader order (npm,
make, python, presence-based). Every other candidate for that purpose is
kept as an alternative — never silently dropped — because CI evidence is
what *actually* runs in the pipeline, while a local script only *could*
run something similar.

Classification (`_classify()`) is a single keyword lookup against
`PURPOSE_KEYWORDS`, checked in the dict's own declaration order — `test`
before `lint` before `build` before `run` — so `pytest` (whose last four
letters spell "test") is never miscounted as a generic `build`. The npm
reader folds its `npm run <name>` / `npm test` invocation into the same
string it classifies and displays (Ruling R2): a script's raw body is
still what's shown and matched primarily, but the invocation travels
alongside it rather than replacing it, which also lets a reserved script
name (`start`) pull in the `run` purpose's `"start"` keyword even when the
body itself (`vite`) carries no keyword of its own. The `make` reader
differs deliberately: its command is `make <target>` — the recipe body is
never shown or classified, only the target name embedded in that string.

Every reader degrades rather than raises: a malformed or wrong-shaped file
(a `package.json` that's a list, a `jobs:` that's a list, ...) becomes a
warning naming the file, and every other reader still runs — the same
discipline `deps.py` and `services.py` use.
"""
from __future__ import annotations

import configparser
import fnmatch
import json
import re
import tomllib
from collections.abc import Callable
from pathlib import Path

import yaml

from center_kb.codeingest.core import CodeIngestOptions, CodeSection, ExtractResult
from center_kb.codeingest.extractors._envkeys import redact_userinfo
from center_kb.codeingest.extractors._mdcells import escape_cell
from center_kb.codeingest.extractors.tree import relposix, walk_tree

PURPOSES = ("build", "test", "lint", "run")

PURPOSE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "test": ("pytest", "vitest", "jest", "mocha", "go test", "dotnet test",
             "mvn test", "gradle test", "phpunit", "test"),
    "lint": ("ruff", "eslint", "flake8", "mypy", "golangci-lint",
             "dotnet format", "checkstyle", "lint", "format"),
    "build": ("build", "compile", "tsc", "vite build", "mvn package",
              "gradle build", "dotnet build", "pip install", "go build"),
    "run": ("start", "serve", "uvicorn", "gunicorn", "dotnet run",
            "go run", "dev"),
}

# (purpose, command, source) — the uniform shape every reader below returns.
Candidate = tuple[str, str, str]

_WORKFLOWS_DIR = Path(".github") / "workflows"
_NODE_MAX_DEPTH = 2  # package.json is only searched at depth <= 2 (matches deps.py)
_MAKE_TARGET_RE = re.compile(r"^([a-zA-Z0-9_.-]+):(?!=)", re.M)
_CD_LINE_RE = re.compile(r"^cd\s+(\S+)$")


def _step_dir_label(step: dict, lines: list[str]) -> str | None:
    """The directory a step's `run:` block actually executes in, when
    that isn't the repo root — from `working-directory:` if the step
    sets it, else a leading, standalone `cd <dir>` line in the block
    itself (checked only on the first non-blank line: a `cd` buried
    mid-block doesn't apply to the earlier commands). Used only to
    annotate the source label (`... (in web/)`) — the command text
    itself is never rewritten into `cd web && ...`; rewriting invites
    its own errors, and the label alone is enough to stop a
    subdirectory-only command from being read as root-runnable
    (task review round 1, Finding 1 / controller ruling R33).

    R34(a): a block with *more than one* standalone `cd <dir>` line
    (`cd web` ... `cd ../api` ...) can't be resolved without tracking the
    shell's cwd across the whole block, which is out of scope — the label
    is advisory, never a rewritten command. Returning the first `cd`'s
    target anyway would claim a directory that's flatly wrong for a later
    command in the same block — worse than the pre-fix silence this
    mechanism exists to improve on — so more than one match means `None`,
    deliberately, rather than a guess."""
    working_dir = step.get("working-directory")
    if isinstance(working_dir, str) and working_dir.strip():
        return working_dir.strip().rstrip("/")

    cd_matches = [
        m for m in (_CD_LINE_RE.match(line.strip()) for line in lines if line.strip())
        if m is not None
    ]
    if len(cd_matches) > 1:
        return None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        match = _CD_LINE_RE.match(stripped)
        return match.group(1).rstrip("/") if match else None
    return None


def _defaults_working_directory(
    container: object, rel: str, scope_desc: str, warnings: list[str]
) -> str | None:
    """`container["defaults"]["run"]["working-directory"]` — `container`
    is either a job mapping or the top-level workflow document (Ruling
    R34: the same fallback GitHub Actions itself applies, extended to
    every level a Dev agent could encounter it at). Every level's type is
    guarded — `defaults`, `defaults.run`, or the value itself may be a
    non-mapping / non-string in a malformed workflow — and a wrong shape
    warns naming the file and the scope (`"workflow"` or `"job 'test'"`),
    the same discipline every other structural guard in this reader uses.
    A key that is simply *absent* — the overwhelmingly common case, since
    most workflows never set `defaults:` at all — is not a defect and
    never warns."""
    if not isinstance(container, dict) or "defaults" not in container:
        return None
    defaults = container["defaults"]
    if not isinstance(defaults, dict):
        warnings.append(f"could not parse {rel}: {scope_desc} 'defaults' is not a mapping")
        return None
    if "run" not in defaults:
        return None
    run_defaults = defaults["run"]
    if not isinstance(run_defaults, dict):
        warnings.append(f"could not parse {rel}: {scope_desc} 'defaults.run' is not a mapping")
        return None
    if "working-directory" not in run_defaults:
        return None
    value = run_defaults["working-directory"]
    if not isinstance(value, str):
        warnings.append(
            f"could not parse {rel}: {scope_desc} 'defaults.run.working-directory' is not a string"
        )
        return None
    stripped = value.strip()
    return stripped.rstrip("/") if stripped else None


def _classify(text: str) -> str | None:
    """First purpose in `PURPOSE_KEYWORDS`' own declaration order whose
    keyword appears in `text` (case-insensitive substring match) — `test`
    is checked before `build` so `pytest` is never mistaken for a generic
    build command."""
    lowered = text.lower()
    for purpose, keywords in PURPOSE_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return purpose
    return None


# ---------------------------------------------------------------------------
# reader: ci — .github/workflows/*.y*ml
# ---------------------------------------------------------------------------


def _read_ci(root: Path, opts: CodeIngestOptions) -> tuple[list[Candidate], list[str]]:
    """Every `run:` step across every workflow file, in file order (via
    `walk_tree`, Ruling R7) then job order (`sorted` job names, matching
    `services.py`'s convention of sorting a parsed mapping's keys) then
    step order (a step list's position is meaningful — the file's own
    execution order — so it is never re-sorted). A multi-line `run:`
    block is split on newlines into one candidate per line. Source label
    is `f"CI: {file}#{job}"` so every candidate from the same job shares
    one traceable label — with a `" (in <dir>/)"` suffix when the command
    doesn't actually run at the repo root; without that, a
    subdirectory-only command reads as root-runnable, which is worse than
    not having it at all. The directory is resolved with GitHub Actions'
    own precedence (Ruling R34): the step's own `working-directory:` or a
    leading `cd <dir>` in its block (`_step_dir_label`), else the job's
    `defaults.run.working-directory`, else the workflow's
    (`_defaults_working_directory`, checked at both scopes)."""
    candidates: list[Candidate] = []
    warnings: list[str] = []

    for _depth, reldir, filenames in walk_tree(root, opts.kb_dir):
        if reldir != _WORKFLOWS_DIR:
            continue
        for name in filenames:
            if not fnmatch.fnmatch(name, "*.y*ml"):
                continue
            path = root / reldir / name
            rel = relposix(root, path)
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                warnings.append(f"could not parse {rel}: {exc}")
                continue
            try:
                data = yaml.safe_load(text)
            except yaml.YAMLError as exc:
                warnings.append(f"could not parse {rel}: {exc}")
                continue
            if not isinstance(data, dict):
                warnings.append(f"could not parse {rel}: top-level is not a mapping")
                continue
            jobs = data.get("jobs", {})
            if not isinstance(jobs, dict):
                warnings.append(f"could not parse {rel}: 'jobs' is not a mapping")
                continue
            workflow_default_dir = _defaults_working_directory(data, rel, "workflow", warnings)
            for job_name in sorted(jobs):
                job = jobs[job_name]
                if not isinstance(job, dict):
                    warnings.append(
                        f"could not parse {rel}: job {job_name!r} is not a mapping"
                    )
                    continue
                steps = job.get("steps", [])
                if not isinstance(steps, list):
                    warnings.append(
                        f"could not parse {rel}: job {job_name!r} 'steps' is not a list"
                    )
                    continue
                job_default_dir = _defaults_working_directory(
                    job, rel, f"job {job_name!r}", warnings
                )
                source_base = f"CI: {rel}#{job_name}"
                for step in steps:
                    if not isinstance(step, dict):
                        warnings.append(
                            f"could not parse {rel}: job {job_name!r} has a non-mapping step"
                        )
                        continue
                    if "run" not in step:
                        continue  # e.g. a `uses:` step -- not a command, not a defect
                    run = step["run"]
                    if not isinstance(run, str):
                        warnings.append(
                            f"could not parse {rel}: job {job_name!r} step 'run' is not a string"
                        )
                        continue
                    lines = run.splitlines()
                    # Ruling R34: step's own directory beats the job's
                    # `defaults.run.working-directory`, which beats the
                    # workflow's -- GitHub Actions' own precedence.
                    dir_label = (
                        _step_dir_label(step, lines) or job_default_dir or workflow_default_dir
                    )
                    source = f"{source_base} (in {dir_label}/)" if dir_label else source_base
                    for line in lines:
                        stripped = line.strip()
                        if not stripped:
                            continue
                        purpose = _classify(stripped)
                        if purpose is not None:
                            candidates.append((purpose, stripped, source))

    return candidates, warnings


# ---------------------------------------------------------------------------
# reader: npm — every package.json at depth <= 2
# ---------------------------------------------------------------------------


def _read_npm(root: Path, opts: CodeIngestOptions) -> tuple[list[Candidate], list[str]]:
    """Every `scripts` entry of every `package.json` at depth <= 2.
    Ruling R2: the command is the raw script body, with the `npm run
    <name>` / `npm test` invocation folded in alongside it (never
    replacing it) so both forms are visible and both are available to
    `_classify()` — the invocation is what lets the reserved `"start"`
    script pull in the `run` purpose even when its body (`"vite"`) alone
    carries no keyword."""
    candidates: list[Candidate] = []
    warnings: list[str] = []

    for depth, reldir, filenames in walk_tree(root, opts.kb_dir):
        if depth > _NODE_MAX_DEPTH or "package.json" not in filenames:
            continue
        path = root / reldir / "package.json"
        rel = relposix(root, path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            warnings.append(f"could not parse {rel}: {exc}")
            continue
        if not isinstance(data, dict):
            warnings.append(f"could not parse {rel}: top-level is not an object")
            continue
        scripts = data.get("scripts", {})
        if not isinstance(scripts, dict):
            warnings.append(f"could not parse {rel}: 'scripts' is not an object")
            continue
        for name in sorted(scripts):
            body = scripts[name]
            if not isinstance(body, str):
                warnings.append(f"could not parse {rel}: script {name!r} is not a string")
                continue
            invocation = "npm test" if name == "test" else f"npm run {name}"
            command = f"{body} ({invocation})"
            purpose = _classify(command)
            if purpose is not None:
                candidates.append((purpose, command, rel))

    return candidates, warnings


# ---------------------------------------------------------------------------
# reader: make — a root Makefile
# ---------------------------------------------------------------------------


def _read_make(root: Path) -> tuple[list[Candidate], list[str]]:
    """A root `Makefile`'s target names. Unlike every other reader, the
    displayed and classified command is `make <target>` — never the
    recipe body — per Ruling R2's carve-out for this reader."""
    path = root / "Makefile"
    if not path.is_file():
        return [], []
    rel = relposix(root, path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [], [f"could not parse {rel}: {exc}"]

    candidates: list[Candidate] = []
    for match in _MAKE_TARGET_RE.finditer(text):
        command = f"make {match.group(1)}"
        purpose = _classify(command)
        if purpose is not None:
            candidates.append((purpose, command, rel))
    return candidates, []


# ---------------------------------------------------------------------------
# reader: python — tox.ini env names, pyproject.toml pytest config presence
# ---------------------------------------------------------------------------


def _tox_env_names(text: str) -> set[str]:
    """Env names from `[tox] envlist` and any `[testenv:<name>]` section.
    `interpolation=None` avoids configparser's default `%`-interpolation
    crashing on a tox.ini value that legitimately contains a bare `%`."""
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(text)
    names: set[str] = set()
    if parser.has_section("tox"):
        raw = parser.get("tox", "envlist", fallback="")
        names.update(part.strip() for part in raw.replace("\n", ",").split(",") if part.strip())
    for section in parser.sections():
        if section.startswith("testenv:"):
            names.add(section.split(":", 1)[1].strip())
    return names


def _read_python(root: Path) -> tuple[list[Candidate], list[str]]:
    candidates: list[Candidate] = []
    warnings: list[str] = []

    tox_path = root / "tox.ini"
    if tox_path.is_file():
        rel = relposix(root, tox_path)
        try:
            text = tox_path.read_text(encoding="utf-8")
            names = _tox_env_names(text)
        except (OSError, UnicodeDecodeError, configparser.Error) as exc:
            warnings.append(f"could not parse {rel}: {exc}")
        else:
            for name in sorted(names):
                command = f"tox -e {name}"
                purpose = _classify(command)
                if purpose is not None:
                    candidates.append((purpose, command, rel))

    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        rel = relposix(root, pyproject)
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError) as exc:
            warnings.append(f"could not parse {rel}: {exc}")
        else:
            tool = data.get("tool", {})
            pytest_cfg = tool.get("pytest", {}) if isinstance(tool, dict) else {}
            ini_options = pytest_cfg.get("ini_options") if isinstance(pytest_cfg, dict) else None
            if isinstance(ini_options, dict):
                candidates.append(("test", "pytest", rel))

    return candidates, warnings


# ---------------------------------------------------------------------------
# reader: presence-based defaults — maven / gradle / dotnet / go
# ---------------------------------------------------------------------------


def _first_matching_file(
    root: Path, opts: CodeIngestOptions, predicate: Callable[[str], bool]
) -> str | None:
    """The first (deterministic, `walk_tree`-ordered) file whose name
    satisfies `predicate`, or `None`. Shared by the gradle and dotnet
    lookups below so the same pruned-walk-plus-first-match rule lives in
    exactly one place rather than being copied per ecosystem."""
    for _depth, reldir, filenames in walk_tree(root, opts.kb_dir):
        for name in filenames:
            if predicate(name):
                return relposix(root, root / reldir / name)
    return None


def _read_presence(root: Path, opts: CodeIngestOptions) -> tuple[list[Candidate], list[str]]:
    """No file content is read here — presence alone is the evidence, and
    the purpose of each canonical command is known statically, so these
    candidates bypass `_classify()` entirely (unlike every other reader).
    Maven and Gradle each contribute one default `build` command; .NET
    and Go each contribute both a `build` and a `test` default, per the
    brief's table."""
    candidates: list[Candidate] = []

    if (root / "pom.xml").is_file():
        candidates.append(("build", "mvn -B verify", "pom.xml"))

    gradle_file = _first_matching_file(
        root, opts, lambda n: n in ("build.gradle", "build.gradle.kts")
    )
    if gradle_file is not None:
        candidates.append(("build", "./gradlew build", gradle_file))

    dotnet_file = _first_matching_file(root, opts, lambda n: n.endswith((".csproj", ".sln")))
    if dotnet_file is not None:
        candidates.append(("build", "dotnet build", dotnet_file))
        candidates.append(("test", "dotnet test", dotnet_file))

    if (root / "go.mod").is_file():
        candidates.append(("build", "go build ./...", "go.mod"))
        candidates.append(("test", "go test ./...", "go.mod"))

    return candidates, []


# ---------------------------------------------------------------------------
# priority merge + section rendering
# ---------------------------------------------------------------------------


def _select(all_candidates: list[Candidate], purpose: str) -> tuple[Candidate, list[Candidate]] | None:
    """`all_candidates` is already CI-first, then local readers in the
    brief's fixed order (npm, make, python, presence-based) — so the
    first match for a purpose is, by construction, the first CI-sourced
    candidate if one exists, else the first local one. Everything else
    for that purpose is an alternative, never dropped."""
    matches = [c for c in all_candidates if c[0] == purpose]
    if not matches:
        return None
    return matches[0], matches[1:]


def _render_section(purpose: str, primary: Candidate, alternatives: list[Candidate]) -> CodeSection:
    # A captured command can itself be (or embed) a URL a Dev committed
    # with a plaintext credential in it -- `curl https://admin:pw@host/x`,
    # a `git+https://token@...` clone step, ... -- so every command text
    # is run through `redact_userinfo` before it reaches l2_md, l3_md, or
    # `summary` below (task review, Important 2; `.kb/` republishes this
    # to the federation hub, an audience wider than the source repo).
    _, raw_command, source = primary
    command = redact_userinfo(raw_command)
    alternatives = [
        (alt_purpose, redact_userinfo(alt_cmd), alt_src)
        for alt_purpose, alt_cmd, alt_src in alternatives
    ]

    l2_lines = [f"**Primary:** `{command}`", "", f"_Source: {source}_"]
    if alternatives:
        l2_lines += ["", "| Command | Source |", "| --- | --- |"]
        l2_lines += [
            f"| {escape_cell(alt_cmd)} | {escape_cell(alt_src)} |"
            for _, alt_cmd, alt_src in alternatives
        ]
    l2_md = "\n".join(l2_lines) + "\n"

    l3_blocks = [f"```bash\n{command}\n```"]
    if alternatives:
        alt_body = "\n".join(f"# {alt_src}\n{alt_cmd}" for _, alt_cmd, alt_src in alternatives)
        l3_blocks.append(f"```\n{alt_body}\n```")
    l3_md = "\n\n".join(l3_blocks) + "\n"

    summary = f"How to {purpose} this repository: {command} (source: {source})."

    return CodeSection(
        id=f"cmd.{purpose}",
        title=f"{purpose.capitalize()} command",
        summary=summary,
        group="commands",
        l2_md=l2_md,
        l3_md=l3_md,
    )


class CommandsExtractor:
    name = "commands"

    def detect(self, root: Path) -> bool:
        # No `opts` at detect() time (the Extractor protocol never passes
        # one) — same accepted limitation `DepsExtractor.detect()`
        # documents: this walk can't be pruned by a non-default
        # `--kb-dir`, but `extract()`'s walks all are.
        if any(
            (root / name).is_file()
            for name in ("Makefile", "tox.ini", "pyproject.toml", "pom.xml", "go.mod")
        ):
            return True
        for depth, reldir, filenames in walk_tree(root):
            if reldir == _WORKFLOWS_DIR and any(
                fnmatch.fnmatch(f, "*.y*ml") for f in filenames
            ):
                return True
            for name in filenames:
                if name == "package.json" and depth <= _NODE_MAX_DEPTH:
                    return True
                if name in ("build.gradle", "build.gradle.kts"):
                    return True
                if name.endswith((".csproj", ".sln")):
                    return True
        return False

    def extract(self, root: Path, opts: CodeIngestOptions) -> ExtractResult:
        warnings: list[str] = []

        def _run(
            reader: Callable[..., tuple[list[Candidate], list[str]]],
            label: str,
            *args: object,
        ) -> list[Candidate]:
            try:
                found, warns = reader(*args)
            except Exception as exc:  # noqa: BLE001 -- defense in depth, mirrors DepsExtractor
                # A human label, not `reader.__name__` (Finding 2, task
                # review round 1): a private function name leaking into a
                # user-visible KB warning is both unhelpful and, per
                # defect #3's signature, a whole reader's output silently
                # gone with no file named.
                found, warns = [], [f"could not read {label}: {exc}"]
            warnings.extend(warns)
            return found

        # CI first, then every local reader in the brief's fixed order —
        # this list's order IS the priority rule (see `_select`).
        all_candidates: list[Candidate] = (
            _run(_read_ci, "CI workflow", root, opts)
            + _run(_read_npm, "npm scripts", root, opts)
            + _run(_read_make, "Makefile", root)
            + _run(_read_python, "Python tooling (tox/pytest)", root)
            + _run(_read_presence, "presence-based defaults", root, opts)
        )

        sections: list[CodeSection] = []
        for purpose in PURPOSES:
            picked = _select(all_candidates, purpose)
            if picked is None:
                continue
            primary, alternatives = picked
            sections.append(_render_section(purpose, primary, alternatives))

        return ExtractResult(sections=sections, warnings=warnings)
