"""Keeping `<repo_id>-code` in step (spec 2026-09-25): one ingest
configuration shared by local runs and CI, and the CI version pin that
tells whether a local run can match what CI publishes."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from strata_kb import config as config_mod
from strata_kb import models
from strata_kb.codeingest import core

KB_CODE_WORKFLOW = Path(".github") / "workflows" / "kb-code.yml"
_PIN_RE = re.compile(r"strata-kb==([^\s\"']+)")


def ci_pin(repo_root: Path) -> str | None:
    """The `strata-kb==<version>` pin in kb-code.yml, or None when the file
    or the pin is absent."""
    try:
        text = (repo_root / KB_CODE_WORKFLOW).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    m = _PIN_RE.search(text)
    return m.group(1) if m else None


def version_note(repo_root: Path) -> str | None:
    """One line when the installed package differs from CI's pin — different
    extractors, so local -code may differ from what CI publishes."""
    import strata_kb

    pin = ci_pin(repo_root)
    if pin is None or pin == strata_kb.__version__:
        return None
    return (
        f"strata-kb {strata_kb.__version__} is installed but kb-code.yml pins "
        f"{pin} — local -code may differ from what CI publishes"
    )


def options_from_config(
    repo_root: Path,
    kb_dir: Path,
    repo_id: str,
    *,
    doc_id: str = "",
    db: Sequence[Path] = (),
    tags: Sequence[str] = (),
    scaffold_svc: bool = False,
) -> core.CodeIngestOptions:
    """Ingest options from `code_ingest:` in .kb/config.yaml. A non-empty
    `db` or `tags` argument (a CLI flag) replaces that config list for
    this run — it never merges."""
    cfg = config_mod.load_config(kb_dir).code_ingest
    return core.CodeIngestOptions(
        repo_root=repo_root,
        kb_dir=kb_dir,
        doc_id=doc_id or f"{repo_id}-code",
        repo_id=repo_id,
        db_paths=tuple(db) if db else tuple(Path(p) for p in cfg.db),
        tags=tuple(tags) if tags else tuple(cfg.tags),
        scaffold_svc=scaffold_svc,
    )


@dataclass
class FreshResult:
    regenerated: bool
    reason: str = ""
    report: core.CodeIngestReport | None = None
    notes: list[str] = field(default_factory=list)


def has_code_doc(kb_dir: Path, repo_id: str) -> bool:
    """This repo already has a `-code` document: its directory, or its
    `index.yaml` entry (a fresh clone of a migrated repo has only that)."""
    doc_id = f"{repo_id}-code"
    if (kb_dir / doc_id).is_dir():
        return True
    try:
        index = models.load_yaml_model(kb_dir / "index.yaml", models.KBIndex)
    except (OSError, yaml.YAMLError, ValidationError, UnicodeDecodeError):
        return False
    return any(d.id == doc_id for d in index.docs)


def _stale_reason(repo_root: Path, kb_dir: Path, doc_id: str) -> str:
    """Why `-code` must be regenerated, or "" when it matches the tree."""
    manifest_path = kb_dir / doc_id / "_manifest.yaml"
    if not manifest_path.exists():
        return "missing"
    head = core._head_commit(repo_root)
    if not head:
        return "no git"
    try:
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
    except (OSError, yaml.YAMLError, ValidationError, UnicodeDecodeError):
        return "unreadable manifest"
    if manifest.revision != head[:7]:
        return "revision"
    # Tracked changes only (an untracked file is invisible to the tree
    # extractor's `git ls-files`), and never under .kb/: edits there do not
    # change -code, and a still-tracked -code in an unmigrated repo would
    # otherwise re-trigger itself on every call.
    args = ["status", "--porcelain", "--untracked-files=no", "--", "."]
    try:
        args.append(f":(exclude){kb_dir.relative_to(repo_root).as_posix()}")
    except ValueError:
        pass  # .kb outside the repo: nothing to exclude
    proc = core._git(repo_root, *args)
    if proc.returncode != 0 or proc.stdout.strip():
        return "dirty"
    return ""


def ensure_code_fresh(
    kb_dir: Path, repo_id: str, repo_root: Path | None = None
) -> FreshResult:
    """Regenerate `<repo_id>-code` when it is missing, older than HEAD, or
    the tracked tree has changes outside .kb/ (spec 2026-09-25 §4.1).
    Never scaffolds -svc. Raises core.CodeIngestError when the ingest
    refuses; callers print it."""
    kb_abs = kb_dir.resolve()
    root = (repo_root or kb_abs.parent).resolve()
    opts = options_from_config(root, kb_abs, repo_id)
    reason = _stale_reason(root, kb_abs, opts.doc_id)
    if not reason:
        return FreshResult(regenerated=False)
    report = core.run(opts)
    notes = [f"refreshed {opts.doc_id} from the working tree ({reason})"]
    # This refresh is now the main local producer of `-code` (spec
    # 2026-09-25 §4.1) -- an extractor warning (e.g. "could not parse …")
    # must reach the caller the same way `kb code-ingest` prints it, not be
    # discarded because callers here only read `.notes`.
    notes.extend(f"[warn] {warning}" for warning in report.warnings)
    pin_note = version_note(root)
    if pin_note:
        notes.append(pin_note)
    return FreshResult(regenerated=True, reason=reason, report=report, notes=notes)
