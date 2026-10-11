"""Checks on the local `.kb/` itself: documents, kind, tracked sources and
credentials in config."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from strata_kb import gitio, models
from strata_kb.doctor.issues import Issue, _flatten
from strata_kb.mdutils import (
    count_tokens,
    heading_occurrences,
    orphan_heading_ids,
    slice_section,
)


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
    occurrences = heading_occurrences(manifest.sections)
    for row, sec in enumerate(manifest.sections):
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
                continue
            sliced = slice_section(
                path.read_text(encoding="utf-8"), sec.id, occurrences[row]
            )
            if sliced is None:
                issues.append(
                    Issue(
                        "error",
                        f"{doc_id} §{sec.id}: could not slice section in '{name}'",
                    )
                )
                continue
            recount = count_tokens(sliced)
            stored = sec.tokens.l2 if suffix == ".md" else sec.tokens.l3
            field = "tokens.l2" if suffix == ".md" else "tokens.l3"
            if stored != recount:
                # Warning, not error: svc_note deliberately leaves stale counts
                # in place (svcnote.py) and code-ingest leaves every section
                # unbuilt -- both routine, both fixed by the next `kb build`.
                # Still reported (real drift looks the same), just not a red
                # doctor exit on a healthy day-to-day workflow.
                issues.append(
                    Issue(
                        "warning",
                        f"{doc_id} §{sec.id}: {field} is {stored}, recount is "
                        f"{recount} — run 'kb build'",
                    )
                )
    # Repeated ids are legal WITHIN one file -- heading_occurrences/
    # slice_section(occurrence=) exist for exactly that, spec-allowed "repeated
    # numbering" (mdutils.py). heading_occurrences scopes its count per (file,
    # id), so same id + different files each independently slice fine and "could
    # not slice" above never catches this. The only real ambiguity is a citation
    # `doc#<id>` that cannot say which FILE it meant -- so flag an id only when
    # its rows span more than one file.
    files_by_id: dict[str, set[str]] = {}
    for s in manifest.sections:
        files_by_id.setdefault(s.id, set()).add(s.file)
    for sid in sorted(sid for sid, files in files_by_id.items() if len(files) > 1):
        issues.append(
            Issue(
                "error",
                f"{doc_id} §{sid}: duplicate section id in _manifest.yaml — "
                "ids are the citation key and must be unique within a doc",
            )
        )

    # A within-file repeat IS legal
    # (heading_occurrences/slice_section(occurrence=) exist for exactly that,
    # spec-allowed "repeated numbering") and a citation `doc#<id>` truly cannot
    # name a FILE (the reason the check above stays scoped to cross-file) -- but
    # it cannot name an OCCURRENCE either, and nothing on the read path does
    # that job for it: query.py, resolve.py, searchdb.py, diff.py and svcnote.py
    # all resolve occurrence 0 only (`_get_section_in` picks the first matching
    # manifest row, then slices occurrence 0). So a within-file repeat's
    # 2nd-and-later rows build, publish, and are permanently unreachable by `kb
    # get`/`kb resolve`/the section API/any MCP tool -- not an error (the format
    # allows the repeat and four write modules rely on it), but not silently
    # doctor-green either.
    per_file_counts: dict[tuple[str, str], int] = {}
    for s in manifest.sections:
        per_file_counts[(s.file, s.id)] = per_file_counts.get((s.file, s.id), 0) + 1
    for (file, sid), count in sorted(per_file_counts.items()):
        if count > 1:
            issues.append(
                Issue(
                    "warning",
                    f"{doc_id} §{sid}: id repeated {count}x in '{file}' — the "
                    "2nd and later occurrences are unreachable by citation "
                    "(kb get/resolve, the section API and MCP tools all "
                    "resolve the first occurrence only)",
                )
            )

    # The manifest→file direction is checked above (missing file, unsliceable
    # section). This is the file→manifest direction for headings, the way the
    # orphan-file loop below is for files: a heading nothing lists is content no
    # citation can reach.
    listed = {s.id for s in manifest.sections}
    for suffix in (".md", ".raw.md"):
        for name in sorted({f"{s.file}{suffix}" for s in manifest.sections}):
            path = doc_dir / name
            if not path.exists():
                continue  # already reported above
            text = path.read_text(encoding="utf-8")
            for sid in orphan_heading_ids(text, suffix, listed):
                issues.append(
                    Issue(
                        "error",
                        f"{doc_id}: heading '{sid}' in '{name}' is not in "
                        "_manifest.yaml",
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
    from strata_kb.config import load_config

    try:
        kind = load_config(kb_dir).kind
    # OSError is a vanished or unreadable file -- doctor's job is to report
    # it, not die on it (check_kind runs before _hub_or_exit, so nothing
    # else catches this first); worded like cli.py's identical condition
    # rather than "invalid", which is only true of the branch below.
    except OSError as exc:
        return [Issue("error", f"could not read .kb/config.yaml: {_flatten(exc)}")]
    # ValidationError is a ValueError subclass (covers a bad literal like
    # kind: bogus); UnicodeDecodeError (a non-UTF-8 file) is also a
    # ValueError subclass.
    except (yaml.YAMLError, ValueError) as exc:
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


SOURCE_DIRS = ("source", "sources")


def check_source_dirs(repo_root: Path) -> list[Issue]:
    """Copyrighted source documents must never be in git. `kb init` ignores
    every file in both folders; a file tracked before that -- or force-added
    -- is still published with every push."""
    issues: list[Issue] = []
    for folder in SOURCE_DIRS:
        files = [
            f
            for f in gitio.tracked_files(repo_root, folder)
            if f != f"{folder}/.gitignore"
        ]
        if not files:
            continue
        shown = ", ".join(files[:5]) + (
            f" (+{len(files) - 5} more)" if len(files) > 5 else ""
        )
        issues.append(
            Issue(
                "warning",
                f"{folder}/ holds {len(files)} file(s) tracked by git: {shown} — source "
                "documents are often copyrighted; untrack them with "
                f"`git rm --cached <file>` and commit (`kb init` writes {folder}/.gitignore "
                "to keep them out)",
            )
        )
    return issues


def check_config_credentials(kb_dir: Path, repo_root: Path) -> list[Issue]:
    """A committed `.kb/config.yaml` whose `hub:` or `intake:` URL carries a
    token puts that token in every clone's history. The value is never
    printed."""
    config_path = kb_dir.resolve() / "config.yaml"
    try:
        relpath = config_path.relative_to(repo_root.resolve()).as_posix()
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError, yaml.YAMLError):
        return []
    if not isinstance(raw, dict) or not gitio.is_tracked(repo_root, relpath):
        return []
    keys = [
        key
        for key in ("hub", "intake")
        if isinstance(raw.get(key), str) and gitio.split_credentials(raw[key])[1]
    ]
    if not keys:
        return []
    return [
        Issue(
            "warning",
            f"{relpath} is tracked by git and its {' and '.join(f'`{k}:`' for k in keys)} "
            "URL carries a credential — rewrite it without one, pass the credentialed URL "
            "in the STRATA_KB_HUB environment variable instead, commit, and rotate the "
            "token: it is in this repo's history",
        )
    ]
