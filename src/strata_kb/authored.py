"""authored — tag marking a hub doc whose markdown is the master copy.

An `authored` doc is hand-written (or hand-maintained) markdown; `kb ingest`
would overwrite it from a PDF, so ingest refuses it. Summarize is unaffected.
The tag lives in `.kb/index.yaml` next to `generated`.
"""

from __future__ import annotations

from pathlib import Path

from strata_kb import models

AUTHORED_TAG = "authored"
SKIP_TAG = "code-sync-skip"


def refusal_message(doc_id: str) -> str:
    return (
        f"'{doc_id}' is tagged authored: its markdown is the master and "
        "re-ingest would overwrite it — run "
        f"`kb authored {doc_id} --off` first if you really mean to replace it"
    )


def is_authored(kb_dir: Path, doc_id: str) -> bool:
    path = kb_dir / "index.yaml"
    if not path.exists():  # first ingest into a fresh KB
        return False
    index = models.load_yaml_model(path, models.KBIndex)
    return any(e.id == doc_id and AUTHORED_TAG in e.tags for e in index.docs)


def set_authored(kb_dir: Path, doc_id: str, on: bool) -> bool:
    """Add/remove the tag; True when index.yaml changed."""
    path = kb_dir / "index.yaml"
    index = models.load_yaml_model(path, models.KBIndex)
    entry = next((e for e in index.docs if e.id == doc_id), None)
    if entry is None:
        raise ValueError(f"'{doc_id}' is not in {path}")
    if (AUTHORED_TAG in entry.tags) == on:
        return False
    entry.tags = (
        [*entry.tags, AUTHORED_TAG]
        if on
        else [t for t in entry.tags if t != AUTHORED_TAG]
    )
    models.save_yaml_model(path, index)
    return True
