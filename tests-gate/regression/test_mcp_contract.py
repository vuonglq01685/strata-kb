"""tools/list is a HARD contract with every agent plugged into strata-kb.

WHAT RED MEANS: you just changed the MCP surface. If that was deliberate, re-run
with UPDATE_GOLDEN=1 and commit the new golden file — it will show up plainly in
the PR diff, and that is exactly the point: a change that breaks agents must be a
DELIBERATE, visible act, not a silent side effect.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

GOLDEN = Path(__file__).parent.parent / "golden" / "mcp_tools.json"


async def _list_tools(params):
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.list_tools()


def _snapshot(tools) -> dict:
    # Dump EVERY field of Tool (a Pydantic model), rather than listing fields by
    # hand — if the SDK later adds outputSchema/title/annotations/icons/meta, the
    # snapshot catches the change automatically instead of silently ignoring it.
    # by_alias=True keeps the on-the-wire names (camelCase: inputSchema,
    # outputSchema...) — exactly what the agent actually sees, not the internal
    # Python field names. exclude_none=True keeps the current golden compact
    # (every unused field is None), but any field that gets SET later will show
    # up in the snapshot.
    #
    # Normalizing "description" here is no longer needed: src/strata_kb/mcp.py now
    # cleandoc()s the docstring itself at tool-registration time (see
    # _canonical_docstring in create_server), so the on-the-wire description is
    # already stable across Python versions AT THE SOURCE — the golden compares
    # every field VERBATIM, description included, with no loophole left to dodge.
    return {
        t.name: t.model_dump(exclude={"name"}, exclude_none=True, by_alias=True)
        for t in sorted(tools.tools, key=lambda t: t.name)
    }


def test_mcp_tool_contract_is_unchanged(published_kb_mcp_params):
    snapshot = _snapshot(asyncio.run(_list_tools(published_kb_mcp_params)))

    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(
            json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))

    assert snapshot == expected
