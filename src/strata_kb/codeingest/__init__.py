"""`kb code-ingest` — deterministic, LLM-free codebase-to-KB extraction."""
from __future__ import annotations

from strata_kb.codeingest.core import (
    CodeIngestError,
    CodeIngestOptions,
    CodeIngestReport,
    run,
)

__all__ = ["CodeIngestError", "CodeIngestOptions", "CodeIngestReport", "run"]
