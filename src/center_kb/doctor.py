from __future__ import annotations

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
