"""integrations extractor -- `int.<name>` sections naming which external
systems a repo talks to, from environment-variable *key names* alone.

**Never a secret channel (spec §3.11) -- the constraint this module is
built around.** Every code path below that can contribute a string to the
rendered output is enumerated here:

  1. `.env.example` / `.env.sample` / `.env.template` file text --
     `_ENV_KEY_RE` captures only the key directly (its regex has no group
     around the `=value` part at all, so a value literally cannot be
     captured, and the capture group's own charset -- `[A-Z][A-Z0-9_]*`
     -- already constrains it to a bare identifier). This path does not
     need the shared sanitiser below; there is nothing left for it to
     strip.
  2. Compose `environment:` as a top-level mapping (`{KEY: value}`) --
     `_envkeys.env_keys_from()`'s dict branch iterates the mapping's own
     *keys*, never touching `mapping[key]`.
  3. Compose `environment:` as a list of plain strings (`["KEY=value"]`)
     -- `env_keys_from()`'s list-of-str branch.
  4. Compose `environment:` as a list containing a *single-pair mapping*
     -- the YAML-parsing artifact behind Task B4's Critical secret leak:
     an unquoted list entry whose text contains ": " (e.g.
     `- KAFKA_BROKER_URL=kafka: 9092`) is parsed by PyYAML as a one-entry
     mapping (`{"KAFKA_BROKER_URL=kafka": 9092}`), not a string.
     `env_keys_from()`'s list-of-dict branch iterates that inner
     mapping's *keys* only -- the value (`9092` above) is never read at
     all, so it cannot leak by construction, not by having been
     remembered to be excluded.

  Paths 2-4 all route through `_envkeys.sanitize_env_key` -- the one
  place this whole rule is stated (Ruling R40). That module's docstring
  has the full account of why: this exact rule caused a Critical secret
  leak *twice* -- once in `services.py` (Task B4, three review rounds)
  and once in this module (Task B7), because this module's first version
  copied `services.py`'s already-hardened function verbatim instead of
  importing it, and inherited a bug the round-3 fix never had to close
  (a `:`-delimited value with no `=` at all was published whole). Both
  modules now import the same function from `_envkeys.py` so the rule
  cannot drift out of sync between them again.

  A fifth candidate path -- an OpenAPI/Swagger document's `servers[*].url`
  -- is read only far enough to decide `detect()` (was a committed
  contract with a non-empty `servers` list found at all); no server URL
  is ever added to an integration's key list or rendered here (Ruling
  R39 -- the controller confirmed this reading is correct, not merely
  unfalsified: `_classify()` is the only route into an `int.*` section
  and matches uppercase prefixes or `_URL`/`_ENDPOINT`/`_HOST`/`_URI`
  suffixes, which no realistic server URL or hostname satisfies, so
  folding servers in would produce no observable output difference; the
  brief's own summary format string counts "environment keys", which a
  URL is not). A server URL describes where *this* repo's own API is
  hosted, not an external system it depends on -- `api.py`'s own
  `ApiExtractor` already renders every `servers[*].url` verbatim in its
  `**Servers:**` line, which is the one place in this task's two
  extractors the security note's "servers[*].url may be emitted as a
  URL" exception is exercised.

Both env-file and compose discovery walk the *entire* pruned tree, not
just the repository root (Ruling R7: "your compose/env discovery is the
same shape" as `api.API_GLOBS`'s `**/`-rooted pattern) -- via
`walk_tree`, never `rglob`/`glob`/`os.walk`.

**Determinism.** Every key -> integration-name classification is a pure
function of the key text; two keys are compared as ordinary Python
strings, which is already a *total* order (no two distinct strings ever
tie), so sorting the keys within one integration, and sorting integration
names against each other, can never depend on `dict`/`set` iteration
order the way an earlier task's untotaled sort key once did.
"""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path

import yaml

from center_kb.codeingest.core import CodeIngestOptions, CodeSection, ExtractResult
from center_kb.codeingest.extractors._envkeys import env_keys_from
from center_kb.codeingest.extractors._mdcells import escape_cell
from center_kb.codeingest.extractors.api import find_openapi_files
from center_kb.codeingest.extractors.tree import relposix, walk_tree

# spec §3.11 -- never a secret channel: read only these three committed,
# template-style filenames. NEVER a real `.env`, which holds live values.
ENV_FILES = (".env.example", ".env.sample", ".env.template")

# The value is never captured -- there is no group around "=..." at all --
# so it cannot leak regardless of what a matched line's right-hand side
# contains.
_ENV_KEY_RE = re.compile(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=", re.M)

INTEGRATION_PREFIXES: tuple[tuple[str, str], ...] = (
    ("KAFKA", "kafka"), ("RABBIT", "rabbitmq"), ("REDIS", "redis"),
    ("S3", "s3"), ("MINIO", "s3"), ("AWS", "aws"), ("AZURE", "azure"),
    ("GCP", "gcp"), ("SMTP", "smtp"), ("MAIL", "smtp"),
    ("ELASTIC", "elasticsearch"), ("OPENSEARCH", "elasticsearch"),
    ("KEYCLOAK", "keycloak"), ("OIDC", "oidc"), ("OAUTH", "oauth"),
    ("STRIPE", "stripe"), ("TWILIO", "twilio"),
)

_GENERIC_SUFFIXES = ("_URL", "_ENDPOINT", "_HOST", "_URI")

# Recursive (Ruling R7), unlike services.py's root-only `_COMPOSE_GLOBS` --
# that module predates this ruling and covers a different facet (running
# containers) of the same files.
_COMPOSE_GLOBS = ("compose*.y*ml", "docker-compose*.y*ml")


def _classify(key: str) -> str | None:
    """First prefix in `INTEGRATION_PREFIXES` to match wins; a key
    matching no prefix but ending in one of the four generic suffixes
    falls into `"other"`; anything else -- a plain `SECRET_KEY`, say -- is
    not evidence of an external integration and is dropped, never
    published (spec §3.11)."""
    for prefix, name in INTEGRATION_PREFIXES:
        if key.startswith(prefix):
            return name
    if key.endswith(_GENERIC_SUFFIXES):
        return "other"
    return None


# ---------------------------------------------------------------------------
# readers -- degrade, never crash; a malformed file warns naming itself
# while every other file/reader still runs.
# ---------------------------------------------------------------------------


def _read_env_files(root: Path, kb_dir: Path | None) -> tuple[dict[str, set[str]], list[str]]:
    """key -> set of contributing file relpaths, from every `ENV_FILES`
    name found anywhere in the pruned tree (Ruling R7)."""
    sources: dict[str, set[str]] = {}
    warnings: list[str] = []
    for _depth, reldir, filenames in walk_tree(root, kb_dir):
        for name in filenames:
            if name not in ENV_FILES:
                continue
            path = root / reldir / name
            rel = relposix(root, path)
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                warnings.append(f"could not parse {rel}: {exc}")
                continue
            for m in _ENV_KEY_RE.finditer(text):
                sources.setdefault(m.group(1), set()).add(rel)
    return sources, warnings


def _read_compose_env(root: Path, kb_dir: Path | None) -> tuple[dict[str, set[str]], list[str]]:
    """key -> set of contributing file relpaths, from every compose
    file's every service's `environment:` block, found anywhere in the
    pruned tree (Ruling R7). A malformed file, or a wrong-shaped
    top-level/`services`/service/`environment` entry, warns naming the
    file and contributes nothing for it; every other compose file (and
    every other service in the same file) still runs."""
    sources: dict[str, set[str]] = {}
    warnings: list[str] = []
    for _depth, reldir, filenames in walk_tree(root, kb_dir):
        for name in filenames:
            if not any(fnmatch.fnmatch(name, pat) for pat in _COMPOSE_GLOBS):
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
            services = data.get("services", {})
            if not isinstance(services, dict):
                warnings.append(f"could not parse {rel}: 'services' is not a mapping")
                continue
            for svc_name, spec in services.items():
                if not isinstance(spec, dict):
                    warnings.append(
                        f"could not parse {rel}: service {svc_name!r} is not a mapping"
                    )
                    continue
                if "environment" not in spec:
                    continue
                environment = spec["environment"]
                if environment is None:
                    # A real-world shape, not malformed: every entry
                    # under `environment:` commented out (or the key
                    # written with no value at all) parses as `None`.
                    # The Compose schema itself rejects a null
                    # `environment:`, so this is no more "wrong" than
                    # the equally-empty `{}`/`[]` forms, which also stay
                    # silent -- warning here would be a new false
                    # positive on a real shape, not a caught defect.
                    continue
                if not isinstance(environment, (dict, list)):
                    # Minor review finding: every other wrong shape in
                    # this reader warns naming the file -- a scalar
                    # `environment:` (e.g. `environment: KEY=value`, a
                    # plain string) must not be the one silent exception.
                    warnings.append(
                        f"could not parse {rel}: service {svc_name!r} "
                        "'environment' is not a mapping or list"
                    )
                    continue
                for key in env_keys_from(environment):
                    sources.setdefault(key, set()).add(rel)
    return sources, warnings


def _openapi_has_servers(path: Path) -> bool:
    """Used only by `detect()` (see module docstring for why no server
    URL is ever added to the rendered key lists). Never raises: any
    read/parse failure, or a wrong-shaped document, is simply "no
    evidence here" -- `ApiExtractor`'s own reader is the one that warns
    about a malformed OpenAPI file."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return False
    if not isinstance(data, dict):
        return False
    servers = data.get("servers")
    return isinstance(servers, list) and len(servers) > 0


# ---------------------------------------------------------------------------
# section rendering
# ---------------------------------------------------------------------------


def _render_section(name: str, keys: dict[str, set[str]]) -> CodeSection:
    sorted_keys = sorted(keys)  # total order: plain string comparison, no ties possible

    l2_lines = ["| Env key | Source |", "| --- | --- |"]
    l2_lines.extend(
        f"| {escape_cell(key)} | {escape_cell(', '.join(sorted(keys[key])))} |"
        for key in sorted_keys
    )
    l2_md = "\n".join(l2_lines) + "\n"

    l3_md = "```\n" + "\n".join(sorted_keys) + "\n```\n"

    summary = (
        f"External integration {name}: configured through {len(sorted_keys)} "
        f"environment keys ({', '.join(sorted_keys)})."
    )

    return CodeSection(
        id=f"int.{name}",
        title=name,
        summary=summary,
        group="integrations",
        l2_md=l2_md,
        l3_md=l3_md,
    )


class IntegrationsExtractor:
    name = "integrations"

    def detect(self, root: Path) -> bool:
        # No `opts` at detect() time -- same structural exception
        # documented in deps.py/commands.py/schema.py/api.py.
        for _depth, _reldir, filenames in walk_tree(root):
            if any(name in ENV_FILES for name in filenames):
                return True
            if any(
                fnmatch.fnmatch(name, pat) for name in filenames for pat in _COMPOSE_GLOBS
            ):
                return True
        return any(_openapi_has_servers(path) for path in find_openapi_files(root, None))

    def extract(self, root: Path, opts: CodeIngestOptions) -> ExtractResult:
        warnings: list[str] = []
        merged: dict[str, set[str]] = {}

        try:
            env_sources, env_warnings = _read_env_files(root, opts.kb_dir)
        except Exception as exc:  # defense in depth: readers must never crash extract()
            env_sources, env_warnings = {}, [f"could not read env files: {exc}"]
        warnings.extend(env_warnings)
        for key, sources in env_sources.items():
            merged.setdefault(key, set()).update(sources)

        try:
            compose_sources, compose_warnings = _read_compose_env(root, opts.kb_dir)
        except Exception as exc:
            compose_sources, compose_warnings = {}, [f"could not read compose manifests: {exc}"]
        warnings.extend(compose_warnings)
        for key, sources in compose_sources.items():
            merged.setdefault(key, set()).update(sources)

        groups: dict[str, dict[str, set[str]]] = {}
        for key, sources in merged.items():
            name = _classify(key)
            if name is None:
                continue
            groups.setdefault(name, {})[key] = sources

        sections = [_render_section(name, groups[name]) for name in sorted(groups)]
        return ExtractResult(sections=sections, warnings=warnings)
