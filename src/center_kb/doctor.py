from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import yaml
from pydantic import ValidationError

from center_kb import gitio, kbcontext, models
from center_kb.mdutils import slice_section
from center_kb.resolve import ResolvedRef, resolve_refs

if TYPE_CHECKING:
    from center_kb.hub import HubHandle


@dataclass
class Issue:
    level: Literal["error", "warning"]
    message: str


def _flatten(exc: Exception) -> str:
    """Collapse a (possibly multi-line) exception message to one scannable line."""
    return " ".join(str(exc).split())


def _check_doc(kb_dir: Path, doc_id: str) -> list[Issue]:
    doc_dir = kb_dir / doc_id
    try:
        manifest = models.load_yaml_model(doc_dir / "_manifest.yaml", models.Manifest)
    except (yaml.YAMLError, ValidationError) as exc:
        return [
            Issue(
                "error",
                f"{doc_id}: _manifest.yaml is corrupt — fix or regenerate it: "
                f"{_flatten(exc)}",
            )
        ]

    issues: list[Issue] = []
    pending = 0
    referenced: set[str] = {"_manifest.yaml"}
    for sec in manifest.sections:
        if sec.status == "pending":
            pending += 1
        for suffix, layer in ((".md", "L2"), (".raw.md", "L3")):
            name = f"{sec.file}{suffix}"
            referenced.add(name)
            path = doc_dir / name
            if not path.exists():
                issues.append(
                    Issue("error", f"{doc_id} §{sec.id}: missing {layer} file '{name}'")
                )
            elif slice_section(path.read_text(encoding="utf-8"), sec.id) is None:
                issues.append(
                    Issue(
                        "error",
                        f"{doc_id} §{sec.id}: could not slice section in '{name}'",
                    )
                )
    if pending:
        issues.append(Issue("warning", f"{doc_id}: {pending} section pending"))
    for f in sorted(doc_dir.glob("*.md")):
        if f.name not in referenced:
            issues.append(
                Issue("warning", f"{doc_id}: orphan file '{f.name}' not in manifest")
            )
    return issues


def check_kb(kb_dir: Path) -> list[Issue]:
    index_path = kb_dir / "index.yaml"
    if not index_path.exists():
        return [Issue("error", f"no index.yaml in '{kb_dir}'")]
    try:
        index = models.load_yaml_model(index_path, models.KBIndex)
    except (yaml.YAMLError, ValidationError) as exc:
        return [
            Issue(
                "error",
                f"index.yaml in '{kb_dir}' is corrupt — fix or regenerate it: "
                f"{_flatten(exc)}",
            )
        ]
    index_ids = {d.id for d in index.docs}

    issues: list[Issue] = []
    for entry in index.docs:
        if not (kb_dir / entry.id / "_manifest.yaml").exists():
            issues.append(
                Issue(
                    "error",
                    f"doc '{entry.id}' is in the index but missing _manifest.yaml",
                )
            )
            continue
        issues += _check_doc(kb_dir, entry.id)

    for child in sorted(p for p in kb_dir.iterdir() if p.is_dir()):
        if (child / "_manifest.yaml").exists() and child.name not in index_ids:
            issues.append(
                Issue(
                    "error",
                    f"doc '{child.name}' has a manifest but is not in index.yaml",
                )
            )
    return issues


def check_kind(kb_dir: Path) -> list[Issue]:
    """Warn when the repo's hub|child kind is not recorded in config.yaml."""
    from center_kb.config import load_config

    try:
        kind = load_config(kb_dir).kind
    except (yaml.YAMLError, ValidationError) as exc:
        return [Issue("error", f"config.yaml is invalid: {_flatten(exc)}")]
    if not kind:
        return [
            Issue(
                "warning",
                "repo kind is not recorded in .kb/config.yaml — run `kb init` "
                "to record kind: hub|child",
            )
        ]
    return []


ASSET_SIZE_WARN_BYTES = 100 * 1024 * 1024


def check_asset_store(kb_dir: Path, handle, store=None) -> list[Issue]:
    """Storage health per asset_store mode; [] when the block is absent."""
    from center_kb import assetstore
    from center_kb.config import load_config

    try:
        cfg = load_config(kb_dir).asset_store
    except Exception:  # noqa: BLE001 — check_kind already reports invalid config
        return []
    if cfg.mode == "none":
        total = 0
        roots = [kb_dir]
        if handle is not None:
            roots.append(handle.federation_dir)
        for root in roots:
            if not root.is_dir():
                continue
            total += sum(
                p.stat().st_size for p in root.glob("**/assets/*") if p.is_file()
            )
        if total > ASSET_SIZE_WARN_BYTES:
            return [
                Issue(
                    "warning",
                    f"in-git assets total {total // (1024 * 1024)} MB — consider "
                    "asset_store mode: s3 (kb assets migrate) or git-LFS",
                )
            ]
        return []
    if store is None:
        try:
            store = assetstore.from_config(cfg)
        except assetstore.AssetStoreError as exc:
            return [Issue("error", f"asset_store: {_flatten(exc)}")]
    try:
        store.exists(assetstore.PROBE_NAME)
    except assetstore.AssetStoreError as exc:
        return [Issue("error", f"asset store unreachable: {_flatten(exc)}")]
    return []


def check_context(
    text: str, hub: "HubHandle"
) -> tuple[list[Issue], list[ResolvedRef]]:
    try:
        ctx = kbcontext.parse(text)
    except kbcontext.KBContextError as exc:
        return [Issue("error", str(exc))], []
    try:
        results = resolve_refs(hub, ctx)
    except gitio.GitError as exc:
        return [Issue("error", str(exc))], []

    issues: list[Issue] = []
    for r in results:
        if r.status == "broken":
            issues.append(Issue("error", f"{r.ref}: {r.reason}"))
        elif r.status == "stale":
            issues.append(Issue("warning", f"{r.ref}: {r.reason}"))
    return issues, results


def _kb_tree_digest(root: Path) -> str:
    """Deterministic digest of a .kb tree (excludes _meta.yaml — snapshot-only)."""
    import hashlib

    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "_meta.yaml":
            continue
        h.update(path.relative_to(root).as_posix().encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def check_hub(
    kb_dir: Path, handle: "HubHandle | None", repo_id: str | None = None
) -> tuple[list[Issue], bool]:
    """Hub-first health. Returns (issues, hub_stale)."""
    from center_kb.federation import build_federation_index, load_federation

    if handle is None:
        return (
            [
                Issue(
                    "error",
                    "could not reach hub — the federation is the only read "
                    "source; check the network or the hub path",
                )
            ],
            False,
        )
    issues: list[Issue] = []
    hub_stale = False
    if handle.stale:
        age = f"~{handle.age_seconds:.0f}s" if handle.age_seconds else "unknown"
        issues.append(
            Issue("warning", f"hub cache is stale (pull failed, age {age})")
        )
        hub_stale = True

    fed = handle.federation_dir
    if fed.is_dir():
        for child in sorted(p for p in fed.iterdir() if p.is_dir()):
            if (child / "manifests").is_dir():
                issues.append(
                    Issue(
                        "warning",
                        f"federation/{child.name} uses the old slim layout — "
                        "run `kb publish` from that repo to upgrade it",
                    )
                )

    index_path = fed / "index.yaml"
    if not index_path.exists():
        issues.append(
            Issue("error", "federation/index.yaml is missing — run `kb reindex`")
        )
    else:
        try:
            stored = models.load_yaml_model(index_path, models.FederationIndex)
        except (yaml.YAMLError, ValidationError) as exc:
            issues.append(
                Issue(
                    "error",
                    f"federation/index.yaml is corrupt — run `kb reindex`: "
                    f"{_flatten(exc)}",
                )
            )
        else:
            if stored != build_federation_index(fed):
                issues.append(
                    Issue(
                        "error",
                        "federation/index.yaml is out of sync with the snapshots — "
                        "run `kb reindex`",
                    )
                )

    if repo_id:
        entry = fed / repo_id
        if not entry.is_dir():
            issues.append(
                Issue(
                    "warning",
                    f"repo '{repo_id}' has not published to the hub yet — run `kb publish`",
                )
            )
        elif _kb_tree_digest(kb_dir.resolve()) != _kb_tree_digest(entry):
            issues.append(
                Issue(
                    "warning",
                    f"local .kb differs from the published snapshot "
                    f"federation/{repo_id} — run `kb publish`",
                )
            )

    counts = Counter(
        d.id for r in load_federation(fed) for d in r.index.docs
    )
    for doc_id, n in sorted(counts.items()):
        if n > 1:
            issues.append(
                Issue(
                    "warning",
                    f"doc-id '{doc_id}' appears in {n} federation repos — "
                    "refs must be repo-qualified (repo:doc)",
                )
            )
    return issues, hub_stale


_ENTRY_SEGMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_FED_TOP_SKIP = {"index.yaml", "registry.yaml", ".gitkeep"}


def _fed_tree_digest(root: Path) -> str:
    """Digest deterministic của một cây federation — bỏ file tầng đỉnh mà
    publish không mirror (index/registry/.gitkeep) và mọi _meta.yaml
    (giống _kb_tree_digest: snapshot-only, hai phía đều bỏ nên so sánh vẫn đúng)."""
    import hashlib

    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "_meta.yaml":
            continue
        rel = path.relative_to(root).as_posix()
        if rel in _FED_TOP_SKIP:
            continue
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def check_federation_publish(
    source_root: Path, handle: "HubHandle | None", repo_id: str | None
) -> list[Issue]:
    """Health hub phân tầng: id entry hợp lệ, cảnh báo cycle, trạng thái đã
    publish lên upstream. handle = hub CẤP TRÊN (None khi root hub / offline)."""
    from center_kb.federation import find_cycle_segment, iter_entry_dirs

    fed_src = source_root / "federation"
    issues: list[Issue] = []
    for path_id, _ in iter_entry_dirs(fed_src):
        if not all(_ENTRY_SEGMENT_RE.fullmatch(s) for s in path_id.split("/")):
            issues.append(
                Issue(
                    "error",
                    f"federation entry '{path_id}' has an invalid path segment — "
                    "only letters/digits/._- per segment",
                )
            )
    if repo_id:
        hit = find_cycle_segment(fed_src, {repo_id}, exempt_exact={repo_id})
        if hit is not None:
            issues.append(
                Issue(
                    "warning",
                    f"own repo id '{repo_id}' appears inside federation entry "
                    f"'{hit}' — this is a cycle: content has looped back; "
                    "`kb publish` will refuse",
                )
            )
    if handle is not None and repo_id:
        dest = handle.federation_dir / repo_id
        if not dest.is_dir():
            issues.append(
                Issue(
                    "warning",
                    f"hub '{repo_id}' has not published to the upstream hub yet — "
                    "run `kb publish`",
                )
            )
        elif _fed_tree_digest(fed_src) != _fed_tree_digest(dest):
            issues.append(
                Issue(
                    "warning",
                    f"local federation/ differs from the published snapshot "
                    f"federation/{repo_id} on the upstream hub — run `kb publish`",
                )
            )
    return issues
