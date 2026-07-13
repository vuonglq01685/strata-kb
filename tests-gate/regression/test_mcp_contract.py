"""tools/list là hợp đồng CỨNG với mọi agent đang cắm vào center-kb.

ĐỎ NGHĨA LÀ GÌ: bạn vừa đổi bề mặt MCP. Nếu là cố ý, chạy lại với
UPDATE_GOLDEN=1 và commit file golden mới — nó sẽ hiện rõ trong diff PR, và
đó chính là mục đích: một thay đổi phá agent phải là một hành động CỐ Ý, nhìn
thấy được, không phải một tác dụng phụ im lặng.
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
    return {
        t.name: {
            "description": (t.description or "").strip(),
            "inputSchema": t.inputSchema,
        }
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
