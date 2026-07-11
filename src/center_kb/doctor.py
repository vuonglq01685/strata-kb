from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from center_kb import gitio, kbcontext, models
from center_kb.mdutils import slice_section
from center_kb.resolve import ResolvedRef, resolve_refs

if TYPE_CHECKING:
    from center_kb.hub import HubHandle


@dataclass
class Issue:
    level: Literal["error", "warning"]
    message: str


def _check_doc(kb_dir: Path, doc_id: str) -> list[Issue]:
    issues: list[Issue] = []
    doc_dir = kb_dir / doc_id
    manifest = models.load_yaml_model(doc_dir / "_manifest.yaml", models.Manifest)

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
    index = models.load_yaml_model(index_path, models.KBIndex)
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
    kb_dir: Path, text: str, hub: "HubHandle | None" = None
) -> tuple[list[Issue], list[ResolvedRef]]:
    try:
        ctx = kbcontext.parse(text)
    except kbcontext.KBContextError as exc:
        return [Issue("error", str(exc))], []
    try:
        results = resolve_refs(kb_dir, ctx, hub=hub)
    except gitio.GitError as exc:
        return [Issue("error", str(exc))], []

    issues: list[Issue] = []
    for r in results:
        if r.status == "broken":
            issues.append(Issue("error", f"{r.ref}: {r.reason}"))
        elif r.status == "stale":
            issues.append(Issue("warning", f"{r.ref}: {r.reason}"))
    return issues, results


_COLLISION_GUIDE = (
    "doc '{doc}' exists in both the local KB and the hub — local wins on query. "
    "Clean up: (1) delete the .kb/{doc}/ directory and the '{doc}' entry in .kb/index.yaml; "
    "(2) commit; pinned refs still resolve to the old version; "
    "(3) `kb context new` from then on will pin via hub_version automatically."
)


def check_hub(
    kb_dir: Path, handle: "HubHandle | None", repo_id: str | None = None
) -> tuple[list[Issue], bool]:
    """Check hub-related health. Returns (issues, hub_stale)."""
    from center_kb.federation import load_federation

    if handle is None:
        return (
            [Issue("warning", "could not reach hub — running with local KB")],
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

    local_ids: set[str] = set()
    index_path = kb_dir / "index.yaml"
    if index_path.exists():
        local_ids = {
            d.id for d in models.load_yaml_model(index_path, models.KBIndex).docs
        }
    hub_index_path = handle.kb_dir / "index.yaml"
    hub_ids: set[str] = set()
    if hub_index_path.exists():
        hub_ids = {
            d.id for d in models.load_yaml_model(hub_index_path, models.KBIndex).docs
        }
    for doc in sorted(local_ids & hub_ids):
        issues.append(Issue("error", _COLLISION_GUIDE.format(doc=doc)))

    repos = load_federation(handle.federation_dir)
    if repo_id:
        entry = next((r for r in repos if r.meta.repo_id == repo_id), None)
        if entry is None:
            issues.append(
                Issue("warning", f"repo '{repo_id}' has not published its index to the hub")
            )
        else:
            try:
                head = gitio.head_commit(gitio.git_root(kb_dir.resolve()))
            except gitio.GitError as exc:
                head = ""
                issues.append(Issue("warning", str(exc)))
            if head and entry.meta.source_commit != head:
                issues.append(
                    Issue(
                        "error",
                        f"hub index out of sync: federation/{repo_id} is pinned at "
                        f"{entry.meta.source_commit}, repo is now at {head} — "
                        "CI publish failed or hasn't run yet (run `kb publish` to sync)",
                    )
                )
    counts = Counter(d.id for r in repos for d in r.index.docs)
    for doc_id, n in sorted(counts.items()):
        if n > 1:
            issues.append(
                Issue(
                    "warning",
                    f"doc-id '{doc_id}' appears in {n} federation repos — "
                    "query still disambiguates by repo-id, but consider renaming",
                )
            )
    return issues, hub_stale
