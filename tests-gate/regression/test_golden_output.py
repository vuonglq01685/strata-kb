"""Freeze the OUTPUT against a fixed KB (v0.9.0 from git history).

WHAT RED MEANS: behavior changed. Usually because of a dependency upgrade
(rank-bm25 changing its ranking formula is the classic case). Investigate FIRST,
and only run UPDATE_GOLDEN=1 once you understand why it changed and have
confirmed the change is wanted.

TWO COMPARISON MODES IN THIS FILE — do not mix up which applies to which test:
  - `assert_golden()` (kb_search — both the MCP and the CLI surface): compares
    AFTER normalize() — the NOISE patterns replace `score=<number>` with
    `score=<N>` before comparing. kb_search embeds the raw BM25 float
    (`score=12.34`) on BOTH surfaces; the goldens were generated on macOS while
    CI runs ubuntu, rank-bm25 computes through numpy, and numpy's reduction
    order can differ between architectures — freezing the exact float value
    would break the goldens for presentational reasons (rounding, platform
    libm), not because behavior changed. A gate that goes red at random is a
    gate that will get switched off, and a gate that is switched off protects
    nothing.
  - `assert_golden_exact()` (kb_get_section): compares EXACTLY — only `.strip()`,
    NO normalize(). kb_get_section returns exactly ONE section and has NO BM25
    score in its output — there is nothing volatile to mask, so this is the real
    "MACHINE contract" golden: the MCP tool's returned string compared
    byte-for-byte.

WHAT assert_golden() ACTUALLY PROTECTS (kb_search, MCP and CLI alike) — read
this carefully before trusting these goldens:
  - IS protected:
    (a) the order of the returned results + the entire content (citation, L2
        text, token count) of each result — a rank-bm25 upgrade that changes
        the formula enough to swap the order of two closely scored hits, or to
        change which results fit into the budget, will turn the golden red even
        when every other unit test stays green.
    (b) the "score closely — both may be relevant..." note, which
        `src/center_kb/mcp.py::kb_search` only emits when the RELATIVE gap
        between the top two results' scores is smaller than
        `AMBIGUOUS_SCORE_GAP` (0.20) — concretely: `gap = (results[0].score -
        results[1].score) / results[0].score`, and the note appears when
        `gap < 0.20`. A changed ranking formula that pushes `gap` across that
        threshold will make this note appear, disappear, or change its citation
        — golden red even when the result order did not change.
  - NOT protected: the ABSOLUTE numeric value of `score=`. A rank-bm25 upgrade
    that changes the formula but happens to preserve BOTH the result order AND
    the "score closely" classification (changing only the absolute magnitude,
    not the order nor the relative ratio between the top-2) will NOT be caught
    by these goldens. That is the remaining blind spot — stated outright so that
    a later reader knows exactly what this net does and does not catch.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

GOLDEN = Path(__file__).parent.parent / "golden"

# The parts that vary between runs — not a behavioral signal.
NOISE = [
    (re.compile(r"/tmp/[^\s\"']+"), "<TMP>"),
    (re.compile(r"\b[0-9a-f]{7,40}\b"), "<SHA>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}T[\d:.+]+"), "<TS>"),
    (re.compile(r"score=\d+\.\d+"), "score=<N>"),
]


def normalize(text: str) -> str:
    for pattern, repl in NOISE:
        text = pattern.sub(repl, text)
    return text.strip() + "\n"


def assert_golden(name: str, actual: str) -> None:
    path = GOLDEN / name
    actual = normalize(actual)
    if os.environ.get("UPDATE_GOLDEN") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8")
    assert actual == path.read_text(encoding="utf-8"), f"{name} changed"


def assert_golden_exact(name: str, actual: str) -> None:
    """Compare EXACTLY — only `.strip()`, never going through normalize()/NOISE.

    Reserved for kb_get_section: its output embeds no BM25 score nor any other
    volatile value, so there is nothing to mask before comparing — this is the
    genuine "MACHINE contract" golden (byte-for-byte), unlike assert_golden()
    above, which has to normalize() first because kb_search embeds the raw
    score."""
    path = GOLDEN / name
    actual = actual.strip() + "\n"
    if os.environ.get("UPDATE_GOLDEN") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8")
    assert actual == path.read_text(encoding="utf-8"), f"{name} changed"


async def _call_mcp(params, tool: str, args: dict) -> str:
    """params: StdioServerParameters — prebuilt by the published_kb_mcp_params
    fixture (tests-gate/conftest.py, Task 9) via the shared _mcp_stdio_params
    helper. Do not rebuild StdioServerParameters here."""
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, args)
            return "".join(c.text for c in result.content if c.type == "text")


def test_golden_kb_search(published_kb_mcp_params):
    out = asyncio.run(
        _call_mcp(published_kb_mcp_params, "kb_search", {"query": "airspace"})
    )

    assert_golden("mcp_outputs/kb_search_airspace.txt", out)


def test_golden_kb_search_restrictive(published_kb_mcp_params):
    out = asyncio.run(
        _call_mcp(
            published_kb_mcp_params, "kb_search", {"query": "restrictive airspace"}
        )
    )

    assert_golden("mcp_outputs/kb_search_restrictive.txt", out)


def test_golden_kb_get_section(published_kb_mcp_params):
    """The real kb_get_section — no BM25 score in its output, so compare EXACTLY
    (assert_golden_exact, no normalize()). §5.129 (Restrictive Airspace
    Designation) is a section that genuinely exists in the frozen v0.9.0 KB —
    confirmed via the kb_search goldens above and via git show directly against
    v0.9.0:.kb/arinc-424/ch5-navigation-data-field-definitions{,.raw}.md. Both
    l2 (condensed) and l3 (verbatim, copyrighted) are tested, to prove the L2/L3
    split still works end to end all the way out to the MCP surface."""
    for level, golden_name in (
        ("l2", "mcp_outputs/kb_get_section_5129_l2.txt"),
        ("l3", "mcp_outputs/kb_get_section_5129_l3.txt"),
    ):
        out = asyncio.run(
            _call_mcp(
                published_kb_mcp_params,
                "kb_get_section",
                {"doc": "arinc-424", "section": "5.129", "level": level},
            )
        )
        assert_golden_exact(golden_name, out)


def test_golden_cli_query(published_kb, kb_run):
    out = kb_run("query", "airspace", "--hub", str(published_kb["hub"]),
                 "--kb-dir", str(published_kb["kb"]),
                 cwd=published_kb["repo"]).stdout

    assert_golden("cli_outputs/query_airspace.txt", out)
