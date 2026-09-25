"""Keeping `<repo_id>-code` in step (spec 2026-09-25): one ingest
configuration shared by local runs and CI, and the CI version pin that
tells whether a local run can match what CI publishes."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from strata_kb import config as config_mod
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
