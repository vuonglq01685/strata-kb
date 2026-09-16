"""commands extractor — cmd.build / cmd.test / cmd.lint / cmd.run.

These are the sections `dev-execute` and `dev-handover` read to satisfy the
evidence rule (spec §3.14) — this is the task that makes Stage A's
verification gate executable: until these sections exist, a Dev agent has
no machine-readable answer to "how do I test this repo?".

Six readers surface command evidence from six sources — CI workflows, npm
scripts, a Makefile, tox/pytest config, shell scripts at the root or under
`scripts/`, and presence-based defaults for Maven/Gradle/.NET/Go — each
returning `list[Candidate]` (a `(purpose, command, source)` triple) plus
warnings, never raising. For each of the four purposes in `PURPOSES`, the
primary command is the first CI-sourced candidate; failing that, the first
local candidate in reader order (npm, make, python, shell, presence-based).
Every other candidate for that purpose is kept as an alternative — never
silently dropped — because CI evidence is what *actually* runs in the
pipeline, while a local script only *could* run something similar.

Classification (`_classify()`) matches a keyword against a token when the
keyword equals the whole token, or is a prefix of the token cut off by a
`-` or `:` separator (`test-unit`, `lint:fix`) — never a bare substring:
`/dev/null` is not `dev`. A logical line is first split into segments on
unquoted `&&`/`;` (`_split_unquoted_segments`; a plain matching quote
pair is respected, nesting/escaping is not) — each segment's own tokens
checked independently against `PURPOSE_KEYWORDS` — and the line's
purpose is the first purpose in `PURPOSE_KEYWORDS`'s own declaration
order — `test` before `lint` before `build` before `run` — that is named
by *any* non-excluded segment, never whichever segment happens to come
first (R3-1, re-review round 3: position is not evidence of purpose —
the leftmost segment of a chained line is routinely `cd`, `rm`, `mkdir`
or an install step, none of which say anything about what the line is
*for*; `rm -rf build && pytest -q` is a `test` line even though its
first segment's own last token is literally `build`). This is also why
`pytest` (whose last four letters spell "test") is never miscounted as a
generic `build`: `test` is checked, across every segment, before `build`
ever is. The npm reader folds its `npm run <name>` / `npm test`
invocation into the same string it classifies and displays (Ruling R2):
a script's raw body is still what's shown and matched primarily, but the
invocation travels alongside it rather than replacing it, which also lets a
reserved script name (`start`) pull in the `run` purpose's `"start"` keyword
even when the body itself (`vite`) carries no keyword of its own. The `make`
reader differs deliberately: its command is `make <target>` — the recipe body
is never shown or classified, only the target name embedded in that string.

Before a segment's tokens are even checked against `PURPOSE_KEYWORDS`,
`_classify()` drops two shapes that are not commands at all (fix wave,
2026-09-16, findings C1/I5): a segment whose leading tokens are a
package-manager install verb (`pip install`, `npm ci`, `apt-get
install`, ...) — the *installed package name* can itself be a keyword
(`pip install build twine` classified as `build`), which whole-token
matching alone does not close, only narrows — and a `test`/`[`/`[[`
shell-conditional segment (`test "$code" = "401"`), which is an exact
match against the bare `"test"` keyword every Makefile/raw-`test`
invocation still needs. Excluding a segment removes only its own
contribution to the purposes considered above; it never demotes another
segment in the same line (R2-3: `npm ci && npm run build` classifies as
`build` from its second segment, not `None` from treating the whole
line as one excluded unit). See `_is_install_line`/`_is_shell_conditional`.

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
from center_kb.codeingest.extractors._lines import join_continuations
from center_kb.codeingest.extractors._mdcells import escape_cell
from center_kb.codeingest.extractors.tree import relposix, walk_tree

PURPOSES = ("build", "test", "lint", "run")

PURPOSE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "test": ("pytest", "vitest", "jest", "mocha", "go test", "dotnet test",
             "mvn test", "gradle test", "phpunit", "test"),
    "lint": ("ruff", "eslint", "flake8", "mypy", "golangci-lint",
             "dotnet format", "checkstyle", "lint", "format"),
    "build": ("build", "compile", "tsc", "vite build", "mvn package",
              "gradle build", "dotnet build", "go build"),
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
    sets it, else a standalone `cd <dir>` line at `lines[0]` (checked
    only there: a `cd` after an earlier command doesn't apply to that
    earlier command). `lines` has already been comment- and blank-
    dropped and continuation-joined by `join_continuations`, so a
    leading `# comment` no longer hides the `cd` right after it —
    `# set up` / `cd web` / `npm run build` now labels `web`, not
    `None`. Used only to annotate the source label (`... (in web/)`) — the
    command text itself is never rewritten into `cd web && ...`; rewriting
    invites its own errors, and the label alone is enough to stop a
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


_TOKEN_STRIP = "\"'();,"
_TOKEN_SEPARATORS = ("-", ":")

# Recognized file extensions, checked against a token's final dot-suffix.
# A frozen list, not a generic "has a dot" rule: `ruff>=0.15` and `v1.2`
# already fail the separator/position check on their own (no keyword
# prefix followed by `-`/`:`), so neither argues for a frozen set --
# and `lint:fix` / `build:prod` have no dot at all, so a dot-rule would
# ignore them by construction and never even reach this check either
# way. What does argue for a frozen set: `make test-3.11` -> `test` and
# `tox -e lint-3.12` -> `lint` (Python version matrices) are genuine
# separator-rule matches whose matched token carries a dot -- a generic
# "has a dot" rule would wrongly exclude both.
_FILENAME_EXTENSIONS = frozenset({
    "txt", "json", "yml", "yaml", "sh", "py", "js", "ts", "md",
    "cfg", "ini", "toml", "lock", "csv", "log", "sql", "xml",
    "in", "gz", "tgz", "zip", "tar", "bz2", "xz", "mjs", "cjs", "bash",
})


def _looks_like_filename(token: str) -> bool:
    """True when `token` ends in a recognized file extension. Case-
    sensitive: `token` must already be lowercased -- `_classify` does
    this before `token` ever reaches here, its only caller, so
    `_looks_like_filename("x.TXT")` returning `False` is unreached in
    practice."""
    _, dot, suffix = token.rpartition(".")
    return bool(dot) and suffix in _FILENAME_EXTENSIONS


def _token_matches_keyword(token: str, keyword: str) -> bool:
    """`keyword` matches `token` when they're equal, or when `keyword` is
    a prefix of `token` immediately followed by a separator in
    `_TOKEN_SEPARATORS` and `token` doesn't look like a filename -- so a
    Makefile target `test-unit` or an npm script `lint:fix` still
    classifies (user-approved widening: a whole-token-only rule left a
    repo whose Makefile has only `test-unit` with no `cmd.test` section
    at all), but a CI `run:` line's own install/copy/download step
    (`pip install -r dev-requirements.txt`, `cp test-fixtures/a.json
    /tmp`, `curl -o start-script.sh https://x`) doesn't reopen the
    false-positive class the separator rule was meant to close
    (user-approved containment). The keyword must still start at
    position 0 of the token: `devops.txt` (`dev` then `o`), `/dev/null`
    (`dev` isn't at position 0), `smoke-test-token` (`test` isn't at
    position 0) and `starting` (`start` then `i`) all stay unmatched."""
    if token == keyword:
        return True
    return (
        token.startswith(keyword)
        and token[len(keyword)] in _TOKEN_SEPARATORS
        and not _looks_like_filename(token)
    )


# C1 (final whole-branch review): a *whole-token* match still fires when
# the installed package name itself is a `PURPOSE_KEYWORDS` entry --
# `pip install build twine` classified as `build` (the package `build`),
# `pip install ruff` as `lint` (the package `ruff`) -- so an install step
# outranked the real command it precedes in every CI job that installs
# its own tooling before running it. Spec Decision 6 assumed whole-token
# matching alone closed this ("the install step ... no longer classifies
# at all"); it does not, whenever the package name coincides with a
# keyword, which is the common case. This is not solved by reinstating
# "last line wins" (ruled out by the plan's Task 12 Step 2 and by Decision
# 6 for other reasons) -- instead, a line whose leading tokens are a
# package-manager install verb is recognised as setup and dropped before
# classification ever runs, regardless of what package name follows.
_INSTALL_VERBS: tuple[tuple[str, ...], ...] = (
    ("pip", "install"), ("pip3", "install"), ("python", "-m", "pip", "install"),
    ("uv", "pip", "install"), ("uv", "add"), ("uv", "sync"),
    ("pipx", "install"),
    ("poetry", "install"), ("poetry", "add"),
    ("npm", "install"), ("npm", "i"), ("npm", "ci"), ("npm", "add"),
    ("yarn", "add"), ("yarn", "install"),
    ("pnpm", "install"), ("pnpm", "add"),
    ("apt-get", "install"), ("apt", "install"), ("apk", "add"),
    ("brew", "install"),
    ("go", "install"),
    ("cargo", "install"),
    ("gem", "install"),
    ("dotnet", "add"), ("dotnet", "restore"), ("dotnet", "tool", "install"),
)


def _is_install_line(tokens: list[str]) -> bool:
    """True when `tokens` (already lowercased/quote-stripped, exactly as
    `_classify` builds them) *start* with one of `_INSTALL_VERBS` --
    matched only at position 0, unlike `_classify`'s scan-anywhere keyword
    search, because this is asked about one already-split SEGMENT of a
    logical line (`_split_unquoted_segments`, R2-3), never the whole
    line: a `&&`/`;`-chained segment that follows an install step
    (`npm ci && npm run build`) very much does have something after it,
    and does contribute its own purpose to the line -- see `_classify`'s
    docstring (R2-3 originally, corrected by R3-1) for how the purposes
    of every non-excluded segment combine. This function's only job is
    whether ITS segment's purpose is "install a tool", which is setup,
    never a command a Dev agent should be told to run."""
    return any(tuple(tokens[:len(verb)]) == verb for verb in _INSTALL_VERBS)


# I5 (same review, same intake-filter surface as C1): the bare keyword
# `"test"` (needed so a Makefile `test:` target or a raw `test`
# invocation classifies at all) is also an exact token match against the
# shell builtin/`[`/`[[` conditional -- `release.yml#docker-verify`'s
# `test "$code" = "401"` surfaced as a `cmd.test` alternative. Rejecting
# the conditional *shape* (rather than removing the keyword) keeps
# legitimate commands that merely contain "test" classifying normally.
_CONDITIONAL_HEADS = ("test", "[", "[[")
_CONDITIONAL_OPERATORS = ("!=", "-eq", "-z", "-n", "=")


def _is_shell_conditional(tokens: list[str]) -> bool:
    """True when `tokens` has the shape of a shell conditional test --
    first token `test`, `[` or `[[`, with a later token carrying a
    comparison operator (`=`, `!=`, `-eq`, `-z`, `-n` -- checked by
    substring, which also catches `!=` via its trailing `=`) or the
    line's own last token ending in `]`/`]]`. `pytest -q`, `go test
    ./...`, `npm run test` and `dotnet test` don't start with a bare
    `test`/`[`/`[[` token, so none of them match."""
    if not tokens or tokens[0] not in _CONDITIONAL_HEADS:
        return False
    if tokens[-1].endswith("]"):
        return True
    return any(op in tok for tok in tokens[1:] for op in _CONDITIONAL_OPERATORS)


def _split_unquoted_segments(text: str) -> list[str]:
    """Split `text` on `&&`/`;` into logical segments, ignoring either
    operator when it appears inside a single- or double-quoted run
    (`echo "a && b"` is one segment, not two). R2-3 (re-review round 2):
    `_classify` used to treat a whole `&&`-chained line as one
    classification unit, so `_is_install_line`/`_is_shell_conditional`
    matching the *first* segment (`npm ci && npm run build`, `pip
    install -e .[dev] && pytest -q`) dropped the entire line to `None`,
    silencing the real command that follows -- a regression this fix
    wave itself introduced, in the exact accuracy class (G-2: name the
    command that actually runs) the whole batch exists to close.

    Only a plain matching quote pair is handled -- no backslash-escaping
    of a quote inside a quote, no nesting. Real CI/tox/shell `run:`
    lines don't need more than that; a line with escaped quotes around
    its own `&&`/`;` is not a shape this module's other readers or tests
    exercise, so building a full shell-quoting parser for it here would
    be disproportionate to what it buys."""
    segments: list[str] = []
    current: list[str] = []
    quote: str | None = None
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if quote is not None:
            current.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            current.append(ch)
            i += 1
            continue
        if text.startswith("&&", i):
            segments.append("".join(current))
            current = []
            i += 2
            continue
        if ch == ";":
            segments.append("".join(current))
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    segments.append("".join(current))
    return segments


def _keyword_purpose(tokens: list[str]) -> str | None:
    """First purpose in `PURPOSE_KEYWORDS`' own declaration order (`test`
    before `lint` before `build` before `run`) whose keyword matches a
    run of `tokens`: a one-word keyword must match one whitespace-
    delimited token (outer quotes and parens stripped, per
    `_token_matches_keyword`) already stripped by the caller, a
    multi-word keyword must match that many consecutive tokens the same
    way. A bare substring match classified `/dev/null` as `run` and
    `:latest` as `test` (reviewer G-2); this still can't -- only a whole
    token, or a keyword prefix cut by `-`/`:`, counts. Only ever called
    on ONE segment's tokens (see `_classify`) -- it has no notion of
    "the rest of the line" and returns as soon as any keyword in the
    highest-priority purpose that has one matches, never continuing on
    to see whether a lower-priority purpose's keyword also appears."""
    for purpose, keywords in PURPOSE_KEYWORDS.items():
        for keyword in keywords:
            kw_tokens = keyword.split()
            width = len(kw_tokens)
            if any(
                all(
                    _token_matches_keyword(tok, kw)
                    for tok, kw in zip(tokens[i:i + width], kw_tokens)
                )
                for i in range(len(tokens) - width + 1)
            ):
                return purpose
    return None


def _classify(text: str) -> str | None:
    """The first purpose in `PURPOSE_KEYWORDS`' own declaration order
    (`test` before `lint` before `build` before `run`) named by ANY
    segment of `text` (split on unquoted `&&`/`;` by
    `_split_unquoted_segments`) whose own tokens aren't excluded by one
    of the two guards below -- purpose priority across every segment,
    never "whichever segment comes first" (R3-1, re-review round 3,
    correcting R2-3's own fix): position in a `&&`/`;`-chained line is
    not evidence of purpose. `rm -rf build && pytest -q` and `cd build
    && make test` both classify as `test`, not `build`, even though
    each one's *first* segment's own last token happens to be `build` --
    `cd`/`rm`/`mkdir` are routinely a chained line's leading segment and
    say nothing about what the line is for, exactly as `_keyword_purpose`
    checking `test` before `build` already does *within* one segment (so
    `pytest`, whose last four letters spell "test", is never miscounted
    as a generic `build`); this makes the same guarantee hold *across*
    segments too.

    A single-segment `text` (no `&&`/`;` at all -- the overwhelmingly
    common case) is simply `_keyword_purpose` of that one segment,
    unchanged from before R2-3/R3-1 ever existed.

    Two guards run before a segment's tokens are even checked against
    `PURPOSE_KEYWORDS`, both added in the same fix wave (C1/I5) and both
    applied here -- the one function every reader that classifies a
    shell line (CI `run:`, `*.sh`, tox `commands =`) already shares, so a
    single check point covers all three rather than three copies of it.
    Placing the guards inside `_classify` itself (rather than only in
    those three readers' own call sites) is safe for its other callers
    too: the npm reader's command is `<script body> (npm run <name>)` (a
    script body starting with an install verb is exceedingly unlikely,
    and not a shape any existing test relies on), the make reader's is
    always exactly `make <target>` (never two install-verb tokens, since
    a Makefile target name has no spaces), and the presence-based reader
    bypasses `_classify` entirely -- none of them can spuriously trip
    either guard.
    - `_is_install_line`: a segment whose leading tokens are a package-
      manager install verb (`pip install`, `npm ci`, `apt-get install`,
      ...) is setup, never a command to run (C1) -- `pip install build
      twine` no longer classifies as `build` merely because `build`
      happens to be an installed package name -- but (R2-3) excluding a
      segment removes only ITS OWN contribution: `npm ci && npm run
      build` still classifies as `build`, from its second segment.
    - `_is_shell_conditional`: a `test`/`[`/`[[` shell conditional is not
      a test *command* (I5) -- `test "$code" = "401"` no longer
      classifies as `test`, and (R2-3) only its own segment is excluded
      when it's chained with `&&` (`[ "$OK" = 1 ] && make build` still
      classifies as `build`).
    """
    found_purposes: set[str] = set()
    for segment in _split_unquoted_segments(text):
        tokens = [tok.strip(_TOKEN_STRIP) for tok in segment.lower().split()]
        if _is_install_line(tokens) or _is_shell_conditional(tokens):
            continue
        purpose = _keyword_purpose(tokens)
        if purpose is not None:
            found_purposes.add(purpose)
    for purpose in PURPOSE_KEYWORDS:
        if purpose in found_purposes:
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
    block is split into logical lines by `join_continuations` (a `\\`
    continuation is one command) — one candidate per line. Source label
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
                    lines = join_continuations(run)
                    # Ruling R34: step's own directory beats the job's
                    # `defaults.run.working-directory`, which beats the
                    # workflow's -- GitHub Actions' own precedence.
                    dir_label = (
                        _step_dir_label(step, lines) or job_default_dir or workflow_default_dir
                    )
                    source = f"{source_base} (in {dir_label}/)" if dir_label else source_base
                    for line in lines:
                        purpose = _classify(line)
                        if purpose is not None:
                            candidates.append((purpose, line, source))

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


def _tox_commands(text: str) -> list[tuple[str, str]]:
    """`(invocation, logical command line)` for every `commands =` value
    of `[testenv]` (invocation `tox`) and `[testenv:<name>]` (`tox -e
    <name>`), continuations joined. Env names alone say nothing about
    what an env runs (reviewer G-2: `envlist = py311` + `commands =
    pytest -q` contributed nothing)."""
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(text)
    found: list[tuple[str, str]] = []
    for section in parser.sections():
        if section == "testenv":
            invocation = "tox"
        elif section.startswith("testenv:"):
            invocation = f"tox -e {section.split(':', 1)[1].strip()}"
        else:
            continue
        raw = parser.get(section, "commands", fallback="")
        found.extend((invocation, line) for line in join_continuations(raw))
    return found


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

            for invocation, line in _tox_commands(text):
                purpose = _classify(line)
                candidate = (purpose, invocation, rel)
                if purpose is not None and candidate not in candidates:
                    candidates.append(candidate)

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
# reader: shell — *.sh at the repo root and directly under scripts/
# ---------------------------------------------------------------------------

_SHELL_DIRS = (Path("."), Path("scripts"))


def _read_shell(root: Path, opts: CodeIngestOptions) -> tuple[list[Candidate], list[str]]:
    """Every `*.sh` at the repo root or directly under `scripts/`. The
    script's logical lines are classified; for each purpose that appears
    at least once the candidate is `bash <script>` with the script as
    source — a Dev agent is told to run the script, not one line torn out
    of it. `bash scripts/gate.sh` is aero's own documented release gate
    and was invisible before this reader (reviewer G-2)."""
    candidates: list[Candidate] = []
    warnings: list[str] = []
    for _depth, reldir, filenames in walk_tree(root, opts.kb_dir):
        if reldir not in _SHELL_DIRS:
            continue
        for name in filenames:
            if not name.endswith(".sh"):
                continue
            path = root / reldir / name
            rel = relposix(root, path)
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                warnings.append(f"could not parse {rel}: {exc}")
                continue
            purposes = {
                purpose
                for purpose in (_classify(line) for line in join_continuations(text))
                if purpose is not None
            }
            for purpose in PURPOSES:
                if purpose in purposes:
                    candidates.append((purpose, f"bash {rel}", rel))
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
    brief's fixed order (npm, make, python, shell, presence-based) — so the
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
            if reldir in _SHELL_DIRS and any(f.endswith(".sh") for f in filenames):
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
            except Exception as exc:  # defense in depth, mirrors DepsExtractor
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
            + _run(_read_shell, "shell scripts", root, opts)
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
