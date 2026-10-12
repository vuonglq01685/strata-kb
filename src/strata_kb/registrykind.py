"""`kb init --kind hub` upgrade: record each registry entry's kind.

`propose` reads what the hub already holds under `federation/<repo_id>/`;
`apply` rewrites `registry.yaml` line-level so comments, ordering and quoting
survive (a YAML dump would drop them)."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import yaml
from pydantic import ValidationError
from yaml.nodes import MappingNode, ScalarNode

from strata_kb import kinds, models
from strata_kb.federation import (
    ENTRY_INDEX_NAME,
    ENTRY_META_NAME,
    iter_entry_dirs,
    load_registry,
    resolve_leaf_kind,
)


def _entry_kind(federation_dir: Path, repo_id: str) -> str:
    """Proposed kind for the published tree at federation/<repo_id>, or ""
    (ask) when there is nothing, or nothing unambiguous, to read."""
    rid = PurePosixPath(repo_id)
    if rid.is_absolute() or not rid.parts or ".." in rid.parts:
        return ""  # never read outside federation/, never federation/ itself
    entry_dir = federation_dir.joinpath(*rid.parts)
    if not entry_dir.is_dir():
        return ""
    if (entry_dir / ENTRY_META_NAME).exists() and (
        entry_dir / ENTRY_INDEX_NAME
    ).exists():
        return resolve_leaf_kind(entry_dir) or ""
    # A namespace holding any nested leaf is a child hub, registered as kb
    # (R10): any other pin is rejected by the kind check on its next publish.
    return kinds.KB if iter_entry_dirs(entry_dir) else ""


def propose(federation_dir: Path) -> dict[str, str]:
    """{registry key: proposed kind} for every entry without a kind.
    "" = no safe proposal, ask. Raises RegistryError on an unreadable file."""
    registry = load_registry(federation_dir)
    out: dict[str, str] = {}
    for key in registry.repos:
        entry = registry.resolve(key)
        if entry is not None and not entry.kind:
            out[key] = _entry_kind(federation_dir, entry.repo_id)
    return out


def _empty_kind_node(mapping: MappingNode) -> ScalarNode | None:
    """The value node of an explicit empty `kind:` key, which is replaced in
    place -- inserting a second `kind` key would be a duplicate."""
    for k, v in mapping.value:
        if (
            isinstance(k, ScalarNode)
            and k.value == "kind"
            and isinstance(v, ScalarNode)
        ):
            return v if not v.value else None
    return None


def _edits(text: str, kinds_by_key: dict[str, str]) -> list[tuple[int, int, str]]:
    """(start, end, replacement) character edits, one per key."""
    root = yaml.compose(text)
    repos = None
    if isinstance(root, MappingNode):
        repos = next(
            (
                v
                for k, v in root.value
                if isinstance(k, ScalarNode) and k.value == "repos"
            ),
            None,
        )
    if not isinstance(repos, MappingNode):
        raise ValueError("registry has no 'repos' mapping")
    line_starts = [0]
    for line in text.splitlines(keepends=True):
        line_starts.append(line_starts[-1] + len(line))
    nl = "\r\n" if "\r\n" in text else "\n"
    edits: list[tuple[int, int, str]] = []
    found: set[str] = set()
    for key_node, val in repos.value:
        key = key_node.value
        if key not in kinds_by_key:
            continue
        found.add(key)
        kind = kinds_by_key[key]
        if isinstance(val, ScalarNode):
            rid = text[val.start_mark.index : val.end_mark.index]
            edits.append(
                (
                    val.start_mark.index,
                    val.end_mark.index,
                    f"{{repo_id: {rid}, kind: {kind}}}",
                )
            )
        elif isinstance(val, MappingNode) and (node := _empty_kind_node(val)):
            start, end = node.start_mark.index, node.end_mark.index
            edits.append((start, end, kind if end > start else f" {kind}"))
        elif isinstance(val, MappingNode) and val.flow_style:
            at = val.end_mark.index - 1  # the closing brace
            edits.append((at, at, f", kind: {kind}"))
        elif isinstance(val, MappingNode) and val.value:
            last_line = val.value[-1][1].end_mark.line
            at = (
                line_starts[last_line + 1]
                if last_line + 1 < len(line_starts)
                else len(text)
            )
            indent = " " * val.value[0][0].start_mark.column
            lead = "" if at == 0 or text[at - 1] == "\n" else nl
            edits.append((at, at, f"{lead}{indent}kind: {kind}{nl}"))
        else:
            raise ValueError(f"registry entry '{key}' has an unexpected shape")
    if missing := sorted(set(kinds_by_key) - found):
        raise ValueError(f"registry has no entry {', '.join(missing)}")
    return edits


def apply(registry_text: str, kinds_by_key: dict[str, str]) -> str:
    """`registry_text` with `kind:` added to the named entries and every other
    byte untouched. Raises ValueError (nothing to write) if the result does
    not parse back to the same entries plus exactly those kinds."""
    out = registry_text
    for start, end, repl in sorted(_edits(registry_text, kinds_by_key), reverse=True):
        out = out[:start] + repl + out[end:]
    try:
        old = models.Registry.model_validate(yaml.safe_load(registry_text))
        new = models.Registry.model_validate(yaml.safe_load(out))
    except (yaml.YAMLError, ValidationError) as exc:
        raise ValueError(f"rewritten registry does not parse: {exc}") from exc
    for key in old.repos:
        before, after = old.resolve(key), new.resolve(key)
        if before is None or after is None:
            raise ValueError(f"rewritten registry lost entry '{key}'")
        want = before.model_copy(update={"kind": kinds_by_key.get(key, before.kind)})
        if after != want or new.repos.keys() != old.repos.keys():
            raise ValueError(f"rewritten registry changed entry '{key}' unexpectedly")
    return out
