"""Guards against Windows-breaking patterns (spec 2026-07-14-windows-support).

subprocess text=True without encoding decodes with the locale codepage
(cp1252) on Windows — UTF-8 output from git/claude gets mojibaked."""
import re
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "center_kb"


def _windows(text: str, needle: str, span: int = 300) -> list[str]:
    """A ±span-char window around each occurrence of needle."""
    return [
        text[max(0, m.start() - span): m.start() + span]
        for m in re.finditer(re.escape(needle), text)
    ]


def test_subprocess_text_true_always_sets_utf8():
    offenders = []
    for py in sorted(SRC.rglob("*.py")):
        text = py.read_text(encoding="utf-8")
        for window in _windows(text, "text=True"):
            if 'encoding="utf-8"' not in window:
                offenders.append(str(py.relative_to(SRC)))
    assert not offenders, (
        f"subprocess text=True without encoding=\"utf-8\" in: {offenders} — "
        "on Windows this decodes with cp1252 and mojibakes UTF-8 output"
    )


# Writers whose output is committed content (KB YAML, L2/L3 markdown,
# templates) — CRLF from a Windows machine would churn hub diffs and skew
# content hashes. hub.py (marker) and ingest/parser.py (cache) are local-only.
COMMITTED_WRITERS = [
    "models.py",
    "initcmd.py",
    "dockersetup.py",
    "summarize.py",
    "ingest/scaffold.py",
    "conventions.py",
]


def test_committed_writers_force_lf_newline():
    offenders = []
    for rel in COMMITTED_WRITERS:
        text = (SRC / rel).read_text(encoding="utf-8")
        for m in re.finditer(re.escape("write_text("), text):
            window = text[m.start(): m.start() + 300]
            if 'newline="\\n"' not in window:
                offenders.append(rel)
    assert not offenders, (
        f"write_text without newline=\"\\n\" in committed-content writers: {offenders}"
    )
