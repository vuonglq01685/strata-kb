"""services extractor — one section per running container, cross-stack.

`svc.<name>` is **the join key** the whole Dev feature is built on: Stage
C's curated `-svc` document reuses these ids and `kb svc note` validates
ticket <-> service history against them, so a name emitted here becomes a
stable public identifier (spec §3.12 — key by container manifest kind,
never by language, which is why one extractor covers compose, Dockerfile,
k8s and sln). The section id is `svc.<slug>`, where `<slug>` is normally
`slugify_id(name)` but may carry a short deterministic suffix (a
truncation-collision disambiguator, Ruling R30) or be a name-hash fallback
(an all-punctuation/emoji/empty name that would otherwise slug to `""`,
Ruling R31) — see `_assign_slugs()`. `title`, the L2 description, and
`summary` all keep the real `name` verbatim regardless; only the id is
ever slugified, so the human-readable, grep-able name is never lost even
when the id had to be mangled or hashed (review findings 2-4).

Five readers below share a uniform return shape, `(list[ServiceRecord],
list[warning])`, and each degrades rather than raises: a malformed or
wrong-shaped manifest becomes a warning naming the file, never a crash,
and the other readers still run. `environment:` is read in both the
mapping and `KEY=value` list forms, but only the *key* ever survives into
a `ServiceRecord` — never the value (spec §3.11). The manifest kinds are
compose, Dockerfile, k8s, `.sln`, and a workspace `package.json`.

Ruling R1 (controller): the Dockerfile fallback fires whenever the
compose readers produced zero services — a parse failure counts as "no
services", exactly like no compose file being present at all — so
`extract()` decides the fallback from `_read_compose()`'s result, not
from a bare file-existence check.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import tomllib
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

from center_kb.codeingest.core import CodeIngestOptions, CodeSection, ExtractResult
from center_kb.codeingest.extractors._envkeys import env_keys_from, redact_userinfo
from center_kb.codeingest.extractors._lines import join_continuations
from center_kb.codeingest.extractors._mdcells import escape_cell
from center_kb.codeingest.extractors.deps import detect_frameworks
from center_kb.codeingest.extractors.tree import IGNORED_DIRS, relposix, walk_tree
from center_kb.mdutils import slugify_id

# Ruling R27: `compose.yaml` is the Compose Specification's preferred
# filename and what Docker Compose v2 scaffolds by default; `docker-
# compose.yml` is the legacy/v1 name. Both are globbed and merged into one
# sorted, de-duplicated listing so determinism never depends on which
# pattern matched (Important review finding 7).
_COMPOSE_GLOBS = ("compose*.y*ml", "docker-compose*.y*ml")
_K8S_KINDS = frozenset({"Deployment", "StatefulSet", "Service"})
# Visual Studio's well-known project-type GUID for a Solution Folder — an
# organisational grouping, never a buildable project. `_read_sln` skips it
# (Important review finding 6).
_SLN_FOLDER_TYPE_GUID = "{2150E333-8FDC-42A3-9474-1A3956D46DE4}"
_SLN_PROJECT_RE = re.compile(r'^Project\("(\{[0-9A-Fa-f-]+\})"\)\s*=\s*"([^"]+)"')
_PEP508_SPLIT_RE = re.compile(r"[><=!~\[;]")


@dataclass
class ServiceRecord:
    name: str
    image: str
    ports: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    env_keys: list[str] = field(default_factory=list)
    source: str = ""  # the file this record came from, e.g. "docker-compose.yml"
    directory: str = ""                 # the service's own code directory, when known
    command: str = ""                   # Dockerfile CMD/ENTRYPOINT as one shell line (Task 11)
    env_files: list[str] = field(default_factory=list)  # compose env_file *names*, never opened
    base_image: str = ""                # FROM of a built service (Task 11); feeds technology


# ---------------------------------------------------------------------------
# shared value coercion — never let a wrong-shaped YAML value crash a reader.
# ---------------------------------------------------------------------------


def _stringify_list(value: object) -> list[str]:
    """Coerce a compose list-or-mapping field (`ports`, `depends_on`) to a
    list of strings. Compose allows a bare scalar (`ports: 8080`), the
    short list form (`ports: ["8080:8080"]`), and a long-form mapping
    (`depends_on: {postgres: {condition: ...}}`) — the mapping's keys are
    sorted so output never depends on that dict's parse-time order."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, dict):
        return sorted(str(k) for k in value)
    if isinstance(value, (str, int)):
        return [str(value)]
    return []


def _env_keys_from(value: object) -> list[str]:
    """Extract only the *keys* of an `environment:` block, de-duplicated
    and sorted so the result never depends on the source mapping's
    iteration order. The extraction and sanitisation rule itself now
    lives in `_envkeys.env_keys_from` / `_envkeys.sanitize_env_key`
    (Ruling R40, Task B7) — this module and `integrations.py` both
    import from there rather than each keeping an independent copy.

    That rule has caused a Critical secret leak twice from two
    separately-maintained copies of it: once here (Task B4, three
    review rounds, each fixing one branch of a multi-branch function at
    a time), and once in `integrations.py` (Task B7), whose author
    copied this already-fixed function verbatim rather than importing
    it — and inherited a *different* bug the round-3 fix here never had
    to consider (a `:`-delimited value with no `=` at all was returned
    whole, credentials included, because the old rule only ever
    stripped text *after* an `=`). Both defects are now closed in the
    one place `_envkeys` lives, so this module has nothing left to fix
    by hand — see that module's docstring for the full account."""
    return sorted(set(env_keys_from(value)))


# ---------------------------------------------------------------------------
# reader: compose
# ---------------------------------------------------------------------------


def _resolve_build(compose_dir: Path, build: object) -> tuple[str, Path | None]:
    """`(context label, Dockerfile path)` for a compose `build:` value — a
    string context, or a mapping with `context` (default `.`) and
    `dockerfile` (default `Dockerfile`). `None` when the value has the
    wrong shape."""
    if isinstance(build, str):
        context, dockerfile = build, "Dockerfile"
    elif isinstance(build, dict):
        context = build.get("context", ".")
        dockerfile = build.get("dockerfile", "Dockerfile")
        if not isinstance(context, str) or not isinstance(dockerfile, str):
            return "", None
    else:
        return "", None
    return context, compose_dir / context / dockerfile


def _read_compose(root: Path) -> tuple[list[ServiceRecord], list[str]]:
    """Every `compose*.y*ml` or `docker-compose*.y*ml` directly at the
    repo root (overrides and profile files live there by convention,
    never nested — this is a plain directory listing, not a recursive
    walk, so R7 doesn't apply). A parse failure, or a wrong-shaped
    top-level document, warns naming the file and contributes zero
    services for it; per Ruling R1 the caller treats that the same as no
    compose file at all."""
    records: list[ServiceRecord] = []
    warnings: list[str] = []

    paths = sorted({p for pattern in _COMPOSE_GLOBS for p in root.glob(pattern) if p.is_file()})
    for path in paths:
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
        for name in sorted(services):
            spec = services[name]
            if not isinstance(spec, dict):
                warnings.append(f"could not parse {rel}: service {name!r} is not a mapping")
                continue
            image = spec.get("image", "")
            if not isinstance(image, str):
                image = str(image) if image is not None else ""
            ports = _stringify_list(spec.get("ports", []))
            source = rel
            command = ""
            base_image = ""
            build = spec.get("build")
            if not image and build is not None:
                # A `build:` service has no image name, but it has a
                # Dockerfile — and that Dockerfile's runtime stage, EXPOSE
                # and CMD are the knowledge a reader wants (reviewer G-8:
                # aero's own hub service rendered an empty image).
                context, dockerfile_path = _resolve_build(path.parent, build)
                if dockerfile_path is not None and dockerfile_path.is_file():
                    # normpath (not resolve) collapses `./` and `../` without
                    # following symlinks, so the label stays repo-relative.
                    normalised = Path(os.path.normpath(dockerfile_path))
                    try:
                        dockerfile_rel = relposix(root, normalised)
                    except ValueError:  # a build context outside the repo
                        dockerfile_rel = normalised.as_posix()
                    try:
                        base_image, exposed, command = _parse_dockerfile(
                            dockerfile_path.read_text(encoding="utf-8")
                        )
                    except (OSError, UnicodeDecodeError) as exc:
                        warnings.append(f"could not parse {dockerfile_rel}: {exc}")
                        exposed = []
                    image = f"build: {dockerfile_rel} (FROM {base_image or 'unknown'})"
                    if not ports:
                        ports = exposed
                    source = f"{rel}, {dockerfile_rel}"
                else:
                    image = f"build: {context or '.'} (Dockerfile not found)"
                    warnings.append(
                        f"service {name!r} in {rel}: build context {context or '.'!r} "
                        "has no Dockerfile"
                    )
            records.append(ServiceRecord(
                name=str(name),
                image=image,
                ports=ports,
                depends_on=_stringify_list(spec.get("depends_on", [])),
                env_keys=_env_keys_from(spec.get("environment", {})),
                source=source,
                command=command,
                env_files=_stringify_list(spec.get("env_file", [])),
                base_image=base_image,
            ))

    return records, warnings


# ---------------------------------------------------------------------------
# reader: dockerfile fallback
# ---------------------------------------------------------------------------


def _exec_form_to_shell(rest: str) -> str:
    """`["python", "-m", "x"]` -> `python -m x`; shell form is returned as is."""
    if rest.startswith("["):
        try:
            items = json.loads(rest)
        except json.JSONDecodeError:
            return rest
        if isinstance(items, list) and all(isinstance(i, str) for i in items):
            return " ".join(items)
    return rest


def _parse_dockerfile(text: str) -> tuple[str, list[str], str]:
    """`(image, ports, command)`: the image of the *last* `FROM` (the
    runtime stage of a multi-stage build — the first `FROM` is a build
    stage that never runs), every `EXPOSE` port, and the last
    `CMD`/`ENTRYPOINT` rendered as one shell line. Continuations joined.

    `FROM` and `CMD`/`ENTRYPOINT` are attacker-adjacent content — a
    registry reference or a command line can carry a `user:pass@` — so
    both are redacted here, once, at the single point every caller (the
    root-Dockerfile fallback and a compose `build:`'s Dockerfile) routes
    through, rather than at each render site individually."""
    image = ""
    ports: list[str] = []
    command = ""
    for line in join_continuations(text):
        parts = line.split()
        directive = parts[0].upper()
        if directive == "FROM" and len(parts) >= 2:
            image = parts[1]
        elif directive == "EXPOSE":
            for token in parts[1:]:
                port = token.split("/", 1)[0]  # "8080/tcp" -> "8080"
                if port:
                    ports.append(port)
        elif directive in ("CMD", "ENTRYPOINT") and len(parts) >= 2:
            command = _exec_form_to_shell(line.split(None, 1)[1].strip())
    return redact_userinfo(image), ports, redact_userinfo(command)


def _read_dockerfile(root: Path, repo_id: str) -> tuple[list[ServiceRecord], list[str]]:
    """A root `Dockerfile`, read only as the Ruling-R1 fallback (the
    caller only calls this when `_read_compose()` produced zero
    services). Yields one service named `repo_id`."""
    path = root / "Dockerfile"
    if not path.is_file():
        return [], []
    rel = relposix(root, path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [], [f"could not parse {rel}: {exc}"]
    image, ports, command = _parse_dockerfile(text)
    record = ServiceRecord(
        name=repo_id, image=image, ports=ports, source=rel, command=command, base_image=image,
    )
    return [record], []


# ---------------------------------------------------------------------------
# reader: k8s manifests
# ---------------------------------------------------------------------------


def _first_container(containers: object) -> tuple[str, list[str]]:
    if not isinstance(containers, list) or not containers:
        return "", []
    first = containers[0]
    if not isinstance(first, dict):
        return "", []
    image = first.get("image", "")
    if not isinstance(image, str):
        image = str(image) if image is not None else ""
    ports: list[str] = []
    raw_ports = first.get("ports", [])
    if isinstance(raw_ports, list):
        for p in raw_ports:
            if isinstance(p, dict) and "containerPort" in p:
                ports.append(str(p["containerPort"]))
            elif p is not None and not isinstance(p, dict):
                ports.append(str(p))
    return image, ports


def _read_k8s(root: Path, kb_dir: Path | None) -> tuple[list[ServiceRecord], list[str]]:
    """`*.y*ml` under any directory, pruned via `walk_tree` (Ruling R7 —
    a bare recursive glob would re-parse the KB's own generated output and
    vendored charts). Reads with `yaml.safe_load_all` since a manifest may
    hold more than one `---`-separated document; only documents whose
    `kind` is Deployment/StatefulSet/Service become a service, named from
    `metadata.name`, with image and `containerPort` from the first
    container (a bare `Service` has none — it degrades to an empty image
    and no ports, not a crash)."""
    records: list[ServiceRecord] = []
    warnings: list[str] = []

    for _depth, reldir, filenames in walk_tree(root, kb_dir):
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
                docs = list(yaml.safe_load_all(text))
            except yaml.YAMLError as exc:
                warnings.append(f"could not parse {rel}: {exc}")
                continue
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                if doc.get("kind") not in _K8S_KINDS:
                    continue
                metadata = doc.get("metadata", {})
                svc_name = metadata.get("name", "") if isinstance(metadata, dict) else ""
                if not svc_name or not isinstance(svc_name, str):
                    continue
                spec = doc.get("spec", {})
                template = spec.get("template", {}) if isinstance(spec, dict) else {}
                pod_spec = template.get("spec", {}) if isinstance(template, dict) else {}
                containers = pod_spec.get("containers", []) if isinstance(pod_spec, dict) else []
                image, ports = _first_container(containers)
                records.append(ServiceRecord(
                    name=svc_name, image=image, ports=ports, source=rel,
                ))

    return records, warnings


# ---------------------------------------------------------------------------
# reader: .sln
# ---------------------------------------------------------------------------


def _read_sln(root: Path) -> tuple[list[ServiceRecord], list[str]]:
    """A root `*.sln` — one candidate service per `Project(...)` line, the
    closest a solution file gets to compose's `services:` mapping. Skips
    Solution Folder entries (project-type GUID `_SLN_FOLDER_TYPE_GUID`) —
    a folder is an organisational grouping in Visual Studio, not a
    buildable project; without this filter every folder name (commonly
    `src`, or a literal `Solution Items`) becomes a permanent public
    `svc.<name>` join key (Important review finding 6). No image, ports,
    or depends_on are recoverable from a solution file alone; those
    fields stay empty rather than guessed."""
    records: list[ServiceRecord] = []
    warnings: list[str] = []

    for path in sorted(p for p in root.glob("*.sln") if p.is_file()):
        rel = relposix(root, path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            warnings.append(f"could not parse {rel}: {exc}")
            continue
        for line in text.splitlines():
            match = _SLN_PROJECT_RE.match(line.strip())
            if not match:
                continue
            project_type, proj_name = match.group(1), match.group(2)
            if project_type.upper() == _SLN_FOLDER_TYPE_GUID:
                continue
            records.append(ServiceRecord(name=proj_name, image="", source=rel))

    return records, warnings


# ---------------------------------------------------------------------------
# reader: workspace package.json (Node monorepos)
# ---------------------------------------------------------------------------


def _read_workspaces(root: Path) -> tuple[list[ServiceRecord], list[str]]:
    """The root `package.json`'s `workspaces` — a list of globs, or the
    `{"packages": [...]}` object form — each resolved to directories that
    hold their own `package.json`. One image-less record per package,
    named from that package's `name` (else the directory name), with
    `directory` set so the Technology column reads the package's own
    dependencies. Listed in the spec and README from the start, never
    implemented (reviewer G-6); without it a Node monorepo has no
    `svc.*` and no Stage-D join key."""
    path = root / "package.json"
    if not path.is_file():
        return [], []
    rel = relposix(root, path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [], [f"could not parse {rel}: {exc}"]
    if not isinstance(data, dict):
        return [], [f"could not parse {rel}: top-level is not an object"]
    workspaces = data.get("workspaces")
    if workspaces is None:
        return [], []
    if isinstance(workspaces, dict):
        workspaces = workspaces.get("packages")
    if not isinstance(workspaces, list):
        return [], [f"could not parse {rel}: 'workspaces' is not a list"]

    records: list[ServiceRecord] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for pattern in workspaces:
        if not isinstance(pattern, str):
            warnings.append(f"could not parse {rel}: workspace entry {pattern!r} is not a string")
            continue
        for match in sorted(root.glob(pattern)):
            if not match.is_dir():
                continue
            rel_dir = relposix(root, match)
            if any(part in IGNORED_DIRS for part in Path(rel_dir).parts):
                continue
            pkg = match / "package.json"
            if not pkg.is_file() or rel_dir in seen:
                continue
            seen.add(rel_dir)
            name = match.name
            try:
                pkg_data = json.loads(pkg.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                warnings.append(f"could not parse {rel_dir}/package.json: {exc}")
            else:
                pkg_name = pkg_data.get("name") if isinstance(pkg_data, dict) else None
                if isinstance(pkg_name, str) and pkg_name.strip():
                    name = pkg_name
            records.append(ServiceRecord(
                name=name, image="", source=f"{rel_dir}/package.json", directory=rel_dir,
            ))
    records.sort(key=lambda r: r.directory)
    return records, warnings


# ---------------------------------------------------------------------------
# de-duplication and id assignment (Rulings R30, R31)
# ---------------------------------------------------------------------------

_NAME_NORMALIZE_RE = re.compile(r"[\W_]+")


def _normalize_name(name: str) -> str:
    """The same normalization `mdutils.slugify_id` applies (NFKC,
    `[\\W_]+` -> `-`, strip, lower) but WITHOUT its 40-char cap. Used as
    the *dedupe* key (Ruling R30 part 1) so `api_gateway` and
    `api-gateway` (spelling drift — DNS-1123 forbids underscores in k8s
    names but compose allows them) still merge, exactly as before, while
    two distinct 40+ character names that only coincide *after*
    truncation are correctly treated as different services and are never
    silently merged (that used to delete one of them with zero
    warnings — Important review finding, round 2)."""
    text = unicodedata.normalize("NFKC", name)
    return _NAME_NORMALIZE_RE.sub("-", text).strip("-").lower()


def _dedupe_key(name: str) -> str:
    """`_normalize_name(name)`, except when that normalizes away to an
    empty string (a name made entirely of punctuation/emoji/underscores,
    or an empty raw name — Ruling R31) — then the raw name itself is the
    key, so two *different* degenerate names (`"+++"` vs `"..."`, both
    normalizing to `""`) are not forced to merge just because they share
    an empty normalized form."""
    normalized = _normalize_name(name)
    return normalized if normalized else name


def _safe_slug(name: str) -> str:
    """`slugify_id(name)`, guaranteed non-empty (Ruling R31). A name made
    entirely of punctuation/emoji/underscores (or an empty raw name, e.g.
    a compose `services: {"": {...}}` key) normalizes to `""` via
    `slugify_id`'s own regex, which would ship the degenerate public join
    key `id="svc."`. Falls back to a short, deterministic hash of the
    *raw* name — never a sibling-order index — so two different
    degenerate names still get different fallback ids."""
    slug = slugify_id(name)
    if slug:
        return slug
    return f"unnamed-{hashlib.sha256(name.encode('utf-8')).hexdigest()[:8]}"


def _stable_suffix(seed: str) -> str:
    """A short suffix derived only from `seed` (the record's own full
    normalized name) — never from sibling order or an index — so a
    truncation-collision disambiguation (Ruling R30 part 3) never shifts
    a service's id when an unrelated sibling service is added or
    removed. Stage C's `kb svc note` validates ticket <-> service history
    against this id, so its stability matters more than its brevity."""
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:6]


def _dedupe(records: list[ServiceRecord]) -> tuple[list[ServiceRecord], list[str]]:
    """De-duplicates on `_dedupe_key(rec.name)` — the *untruncated*
    normalized name, never the raw name and never the (possibly
    truncated) id slug (Important review finding 2 / Ruling R30).

    First occurrence wins, EXCEPT when the record kept so far has no
    image and a later record for the same key does: a bare k8s `Service`
    document commonly lists before its `Deployment` (a `01-service.yaml`
    / `02-deployment.yaml` layout), and letting an image-less `Service`
    permanently shadow the real image was a silent data-loss bug
    (Important review finding 5, round 1). The fix only *fills* the
    image field via `dataclasses.replace` — it does NOT swap in the
    later record wholesale, which would silently discard the kept
    record's `ports`/`depends_on`/`env_keys` and re-attribute its
    `source` (Important review finding, round 2): a compose service with
    neither `image:` nor `build:` has `image == ""` but real
    ports/depends_on/environment, and a later k8s record that only
    supplies the image must not erase them. (`build:` itself always
    yields a descriptive, non-empty image string as of Task 11/G-8 —
    see `_resolve_build`/`_parse_dockerfile` — so it no longer reaches
    this path, but the same fill-not-swap guarantee still matters for
    any other reader that legitimately produces an empty image.)

    `extract()` appends readers in priority order (compose, dockerfile,
    k8s, sln), so absent the image-fill override this still naturally
    prefers the compose record — the one closest to what actually runs.
    Warns on the image fill (so it's visible, not silent), on two
    non-empty images actually disagreeing, and — per Ruling R30 part 4 —
    on every merge where the raw names differ, so a same-normalized-but-
    differently-spelled merge (`api_gateway`/`api-gateway`) is always
    visible even when neither of the other two conditions applies."""
    kept: dict[str, ServiceRecord] = {}
    warnings: list[str] = []
    for rec in records:
        key = _dedupe_key(rec.name)
        prior = kept.get(key)
        if prior is None:
            kept[key] = rec
            continue
        merged = prior
        if not prior.image and rec.image:
            merged = replace(prior, image=rec.image)
            warnings.append(
                f"service {rec.name!r}: filled empty image from {rec.source} "
                f"onto the record kept from {prior.source}"
            )
        if not merged.directory and rec.directory:
            # Metadata, not evidence: a workspace record only tells a
            # compose-declared service where its code lives.
            merged = replace(merged, directory=rec.directory)
        if prior.name != rec.name:
            warnings.append(
                f"merged {rec.name!r} ({rec.source}) into {prior.name!r} "
                f"({prior.source}) — both normalize to {key!r}"
            )
        if prior.image and rec.image and prior.image != rec.image:
            warnings.append(
                f"service {rec.name!r}: kept image {prior.image!r} from "
                f"{prior.source}, discarded {rec.image!r} from {rec.source}"
            )
        kept[key] = merged
    return list(kept.values()), warnings


# Must match `mdutils.slugify_id`'s own truncation length exactly — this
# is what determines whether *this* record's name could possibly collide
# with another after `slugify_id` truncates it.
_ID_CAP = 40


def _assign_slugs(records: list[ServiceRecord]) -> tuple[list[str], list[str]]:
    """One safe, unique id slug per (already-deduped) record — parallel
    to `records`.

    Ruling R30 part 3 requires the disambiguation suffix to come only
    from a record's own full normalized name — "never from sibling order
    or an index" — specifically so a service's id never shifts merely
    because an unrelated sibling was added or removed in some run. An
    earlier version of this function only added a suffix when it
    detected an *actual* collision among the records passed in for that
    one call — which technically doesn't use sibling order or an index,
    but still means the presence of the suffix depends on which siblings
    happen to be present, which is exactly the instability R30 part 3
    rules out (caught by
    `test_truncation_collision_id_is_stable_when_a_sibling_is_removed`
    reverting to that approach).

    The per-record pass below fixes that: whether a record's id gets a
    suffix depends *only* on that record's own normalized name length
    relative to `_ID_CAP` — never on whether any other record happens to
    share the same truncated prefix in this particular run. Every name
    whose full normalized form exceeds `_ID_CAP` is unconditionally
    suffixed; every name at or under the cap never is. Two already-
    deduped records both at-or-under the cap can never collide *by
    length* (their `_safe_slug()` equals their full `_normalize_name()`
    unchanged, and `_dedupe`'s key is that same `_normalize_name()`, so
    two distinct post-dedupe records already have distinct short slugs);
    two both over the cap get distinct name-derived suffixes; one over
    and one under can only coincide if the short one is a
    truncation-length prefix of the long one, and the long one's
    mandatory suffix breaks that tie too.

    What the per-record pass does NOT cover — a prior version of this
    docstring overclaimed "collision-free by construction, no need to
    inspect siblings at all", which was wrong (review finding, round 3):
    `_safe_slug()`'s Ruling R31 hash fallback (`"unnamed-<sha256[:8]>"`,
    used when a name normalizes to `""`) shares its plain-string output
    format with ordinary slugs, so it can coincide with a REAL service
    that happens to be named exactly that fallback string (e.g. one
    service named `"+++"` and another literally named
    `"unnamed-29f5099b"` — verified to be `slugify_id("+++")`'s actual
    fallback value). That is a coincidence between two different records'
    outputs, not a property either record's own name-length check can
    see in isolation, so it genuinely does need a final cross-record
    pass. That pass never picks a "winner": every member of a still-
    colliding group gets a further name-derived suffix, so no record is
    silently left with the bare, ambiguous slug."""
    slugs: list[str] = []
    warnings: list[str] = []
    for rec in records:
        base = _safe_slug(rec.name)
        normalized = _normalize_name(rec.name)
        if len(normalized) > _ID_CAP:
            suffix = _stable_suffix(normalized)
            final = f"{base}-{suffix}"
            warnings.append(
                f"service {rec.name!r} ({rec.source}): name is longer than "
                f"the {_ID_CAP}-character id cap, disambiguated to {final!r}"
            )
        else:
            final = base
        slugs.append(final)

    # Final uniqueness pass: closes the R31-hash-fallback-namespace
    # collision above (and, incidentally, the residual birthday-paradox
    # risk of `_stable_suffix`'s 24-bit space) without ever choosing
    # which colliding record keeps the unsuffixed form.
    counts: dict[str, int] = {}
    for slug in slugs:
        counts[slug] = counts.get(slug, 0) + 1
    for i, rec in enumerate(records):
        if counts[slugs[i]] > 1:
            extra = _stable_suffix(rec.name)
            disambiguated = f"{slugs[i]}-{extra}"
            warnings.append(
                f"service {rec.name!r} ({rec.source}): id {slugs[i]!r} "
                f"collides with another service, disambiguated to "
                f"{disambiguated!r}"
            )
            slugs[i] = disambiguated
    return slugs, warnings


# ---------------------------------------------------------------------------
# Technology labelling — detect_frameworks() over a service's own code
# directory when it has one, else over its image name.
# ---------------------------------------------------------------------------


# Infrastructure images have no dependency manifest to read; label them by
# repository name (reviewer G-8: Technology was `none` on every service in
# every fixture). Matched on the image's base name, exactly.
_INFRA_IMAGES: dict[str, str] = {
    "postgres": "PostgreSQL", "postgresql": "PostgreSQL", "mysql": "MySQL",
    "mariadb": "MariaDB", "redis": "Redis", "nginx": "nginx", "mongo": "MongoDB",
    "rabbitmq": "RabbitMQ", "kafka": "Kafka", "cp-kafka": "Kafka",
    "elasticsearch": "Elasticsearch", "traefik": "Traefik", "minio": "MinIO",
    "memcached": "Memcached", "python": "Python", "node": "Node.js",
    "golang": "Go", "openjdk": "Java", "eclipse-temurin": "Java", "amazoncorretto": "Java",
}


def _image_base_name(image: str) -> str:
    """`registry.example.com/team/airspace:1.0` -> `airspace`: strip any
    registry/namespace path and the tag, leaving the bare repository name
    to feed `detect_frameworks()` (which matches dependency-name-shaped
    strings, not arbitrary image references)."""
    if not image:
        return ""
    last_segment = image.rsplit("/", 1)[-1]
    return last_segment.split(":", 1)[0]


def _dep_names_from_directory(directory: Path) -> list[str]:
    """Best-effort, top-level-only scan for dependency *names* (no
    constraints) inside `directory`, feeding the services table's
    Technology column. Deliberately narrower than `deps.DepsExtractor` —
    it only labels a service's stack, so a parse failure degrades to an
    empty list silently rather than a warning; the four readers above are
    the ones the brief holds to a warn-by-name contract."""
    names: list[str] = []

    package_json = directory / "package.json"
    if package_json.is_file():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            for key in ("dependencies", "devDependencies"):
                deps = data.get(key, {})
                if isinstance(deps, dict):
                    names.extend(str(k) for k in deps)

    pyproject = directory / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError):
            data = {}
        if isinstance(data, dict):
            project = data.get("project", {})
            if isinstance(project, dict):
                deps = project.get("dependencies", [])
                if isinstance(deps, list):
                    for d in deps:
                        if isinstance(d, str):
                            idx = _PEP508_SPLIT_RE.search(d)
                            names.append(d[:idx.start()].strip() if idx else d.strip())

    pom = directory / "pom.xml"
    if pom.is_file():
        try:
            xml_tree = ET.parse(pom)
        except (ET.ParseError, OSError, UnicodeDecodeError):
            xml_tree = None
        if xml_tree is not None:
            for elem in xml_tree.getroot().iter():
                if elem.tag.endswith("artifactId") and elem.text:
                    names.append(elem.text.strip())

    return names


def _technology_for(root: Path, record: ServiceRecord) -> str:
    directory = root / (record.directory or record.name)
    names = _dep_names_from_directory(directory) if directory.is_dir() else []
    labels = detect_frameworks(names)
    if labels:
        return ", ".join(labels)
    base = _image_base_name(record.base_image or record.image)
    if base in _INFRA_IMAGES:
        return _INFRA_IMAGES[base]
    labels = detect_frameworks([base]) if base else []
    return ", ".join(labels) if labels else "none"


# ---------------------------------------------------------------------------
# section rendering
# ---------------------------------------------------------------------------


def _lead_sentence(name: str, record: ServiceRecord) -> str:
    if record.base_image and record.image.startswith("build: "):
        dockerfile = record.image[len("build: "):].split(" (", 1)[0]
        return f"Container `{name}` — built from `{dockerfile}` (base `{record.base_image}`)."
    if not record.image and record.directory:
        return f"Workspace package `{name}` in `{record.directory}` — no container image."
    return f"Container `{name}` — image `{record.image}`."


def _render_section(root: Path, record: ServiceRecord, slug: str) -> CodeSection:
    # Important review findings 2-4: only the id is slugified
    # (`mdutils._HEADING_RE` requires the id token to be `\S+`, and
    # `slugify_id` — unlike `mdutils.slugify` — keeps non-ASCII scripts
    # intact instead of collapsing them to an empty string). `title`, the
    # L2 description, and `summary` all keep `record.name` verbatim, so
    # the real, grep-able name still appears somewhere in the emitted
    # document even when the id had to be mangled. `slug` is precomputed
    # by `_assign_slugs()` (Rulings R30/R31), not derived here, so a
    # truncation-collision disambiguation or an R31 empty-name fallback
    # is visible to the caller across the whole record set at once.
    name = record.name
    # New Important review finding (round 3): a raw name that is empty
    # or all-whitespace (e.g. a compose `services: {"": {...}}` key)
    # makes `_safe_slug()`'s hash fallback keep the *id* non-empty, but
    # `title` (kept verbatim from `name` for every other input, per
    # findings 2-4 above) would still be `""` — an unparseable
    # `"## svc.<hash> "` heading with no title token at all, which
    # `kb build` rejects even though the id itself now looks fine.
    # `title` falls back to the already-unique, already-non-empty `slug`
    # for exactly this one case; every other input keeps its real,
    # grep-able name as the title untouched.
    title = name if name.strip() else slug
    ports_str = ", ".join(record.ports)
    depends_str = ", ".join(record.depends_on)
    env_str = ", ".join(record.env_keys)
    technology = _technology_for(root, record)

    l2_lines = [
        _lead_sentence(name, record),
        "",
        "| Property | Value |",
        "| --- | --- |",
        f"| Image | {escape_cell(record.image)} |",
        f"| Ports | {escape_cell(ports_str) or 'none'} |",
        *([f"| Command | {escape_cell(redact_userinfo(record.command))} |"] if record.command else []),
        f"| Depends on | {escape_cell(depends_str) or 'nothing'} |",
        f"| Technology | {escape_cell(technology)} |",
        f"| Env keys | {escape_cell(env_str) or 'none'} |",
        *([f"| Env file | {escape_cell(redact_userinfo(', '.join(record.env_files)))} |"] if record.env_files else []),
        f"| Source | {escape_cell(record.source)} |",
    ]
    l2_md = "\n".join(l2_lines) + "\n"

    record_dict = {
        "name": name,
        "image": record.image,
        "ports": record.ports,
        "depends_on": record.depends_on,
        "env_keys": record.env_keys,
    }
    for key, value in (
        ("command", redact_userinfo(record.command)),
        ("env_files", [redact_userinfo(f) for f in record.env_files]),
        ("directory", record.directory),
    ):
        if value:
            record_dict[key] = value
    yaml_block = yaml.safe_dump(
        record_dict, allow_unicode=True, sort_keys=False
    ).rstrip("\n")
    l3_md = f"```yaml\n{yaml_block}\n```\n\n```\nsource: {record.source}\n```\n"

    summary = (
        f"Container {name} from {record.source}: image {record.image or 'none'}, "
        f"ports {ports_str or 'none'}, depends on {depends_str or 'nothing'}."
    )

    return CodeSection(
        id=f"svc.{slug}",
        title=title,
        summary=summary,
        group="services",
        l2_md=l2_md,
        l3_md=l3_md,
    )


# ---------------------------------------------------------------------------
# extractor
# ---------------------------------------------------------------------------


class ServicesExtractor:
    name = "services"

    def detect(self, root: Path) -> bool:
        # Minor review finding: without the `.is_file()` filter, a
        # *directory* named like a compose/sln file made `detect()` True
        # while `extract()` (which does filter) returned nothing.
        if any(p.is_file() for pattern in _COMPOSE_GLOBS for p in root.glob(pattern)):
            return True
        if (root / "Dockerfile").is_file():
            return True
        if any(p.is_file() for p in root.glob("*.sln")):
            return True
        pkg = root / "package.json"
        if pkg.is_file():
            try:
                data = json.loads(pkg.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                data = None
            if isinstance(data, dict) and "workspaces" in data:
                return True
        # No `opts` at detect() time (`Extractor.detect(self, root)` is a
        # frozen protocol method), so `kb_dir` can't be threaded through
        # here — the same accepted limitation documented on
        # DepsExtractor.detect() a few lines up in the registry.
        records, _warnings = _read_k8s(root, None)
        return bool(records)

    def extract(self, root: Path, opts: CodeIngestOptions) -> ExtractResult:
        warnings: list[str] = []

        try:
            compose_records, compose_warnings = _read_compose(root)
        except Exception as exc:  # defense in depth: readers must never crash extract()
            compose_records, compose_warnings = [], [f"could not read compose manifests: {exc}"]
        warnings.extend(compose_warnings)

        if compose_records:
            records = list(compose_records)
        else:
            # Ruling R1: compose producing zero services — whether from no
            # compose file, or a parse failure just warned about above —
            # is what triggers the Dockerfile fallback.
            try:
                dockerfile_records, dockerfile_warnings = _read_dockerfile(root, opts.repo_id)
            except Exception as exc:
                dockerfile_records, dockerfile_warnings = [], [f"could not read Dockerfile: {exc}"]
            records = list(dockerfile_records)
            warnings.extend(dockerfile_warnings)

        try:
            k8s_records, k8s_warnings = _read_k8s(root, opts.kb_dir)
        except Exception as exc:
            k8s_records, k8s_warnings = [], [f"could not read k8s manifests: {exc}"]
        records.extend(k8s_records)
        warnings.extend(k8s_warnings)

        try:
            sln_records, sln_warnings = _read_sln(root)
        except Exception as exc:
            sln_records, sln_warnings = [], [f"could not read .sln files: {exc}"]
        records.extend(sln_records)
        warnings.extend(sln_warnings)

        try:
            ws_records, ws_warnings = _read_workspaces(root)
        except Exception as exc:
            ws_records, ws_warnings = [], [f"could not read workspace package.json: {exc}"]
        records.extend(ws_records)
        warnings.extend(ws_warnings)

        merged, dedupe_warnings = _dedupe(records)
        warnings.extend(dedupe_warnings)

        # One safe, unique id slug per deduped record (Rulings R30/R31),
        # computed once over the whole set so a truncation collision
        # between two siblings can be detected and disambiguated.
        slugs, slug_warnings = _assign_slugs(merged)
        warnings.extend(slug_warnings)

        # Sort by the same slug that becomes the id (not the raw name) so
        # the emitted section order always matches ascending id order,
        # regardless of how a raw name's case or script compares to
        # others under plain string ordering.
        paired = sorted(zip(slugs, merged), key=lambda pair: pair[0])
        sections = [_render_section(root, rec, slug) for slug, rec in paired]
        return ExtractResult(sections=sections, warnings=warnings)
