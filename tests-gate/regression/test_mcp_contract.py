"""tools/list là hợp đồng CỨNG với mọi agent đang cắm vào center-kb.

ĐỎ NGHĨA LÀ GÌ: bạn vừa đổi bề mặt MCP. Nếu là cố ý, chạy lại với
UPDATE_GOLDEN=1 và commit file golden mới — nó sẽ hiện rõ trong diff PR, và
đó chính là mục đích: một thay đổi phá agent phải là một hành động CỐ Ý, nhìn
thấy được, không phải một tác dụng phụ im lặng.
"""

from __future__ import annotations

import asyncio
import inspect
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


def _normalize_description(description: str | None) -> str | None:
    """Xóa lệch indentation do PHIÊN BẢN COMPILER gây ra, KHÔNG phải do nội
    dung đổi.

    CPython 3.13+ tự động dedent docstring nhiều dòng ngay lúc compile
    (PEP xem CPython gh-81283); 3.11 và 3.12 thì giữ nguyên whitespace đầu
    dòng y hệt trong source. FastMCP lấy `description` thẳng từ `__doc__`
    (xem src/center_kb/mcp.py) — nên MỘT docstring y hệt cho ra hai chuỗi
    khác nhau chỉ vì con wheel được build bằng CPython nào. Phần agent thực
    sự đọc — câu chữ — không đổi; chỉ khoảng trắng đầu dòng đổi, và đó là
    artifact của compiler chứ không phải một phần hợp đồng đáng đóng băng.

    inspect.cleandoc() là chính hàm CPython dùng nội bộ để dedent docstring
    — đã verify thực nghiệm (không chỉ giả định): dựng cùng một docstring
    nhiều dòng trên 3.11, 3.12 và 3.13, chạy cleandoc() trên cả 3, so sánh
    SHA256 → giống hệt nhau trên cả 3 phiên bản.

    CHỈ áp dụng cho description — inputSchema/outputSchema là hợp đồng máy
    đọc, không có vấn đề whitespace theo phiên bản, phải so khớp NGUYÊN VĂN.
    """
    if description is None:
        return None
    return inspect.cleandoc(description)


def _normalize_tool_dump(dumped: dict) -> dict:
    """Chuẩn hóa MỘT field (description) của bản dump; mọi field khác (kể cả
    inputSchema/outputSchema) đi qua nguyên vẹn, không rờ tới."""
    if "description" not in dumped:
        return dumped
    return {**dumped, "description": _normalize_description(dumped["description"])}


def _snapshot(tools) -> dict:
    # Dump TOÀN BỘ field của Tool (Pydantic model), không liệt kê tay từng
    # field — nếu SDK thêm outputSchema/title/annotations/icons/meta sau này,
    # snapshot tự động bắt được thay đổi thay vì im lặng bỏ qua. by_alias=True
    # để giữ tên trên wire (camelCase: inputSchema, outputSchema...) — đúng
    # cái agent thực sự thấy, không phải tên field Python nội bộ.
    # exclude_none=True giữ golden hiện tại gọn (mọi field chưa dùng đều None)
    # nhưng bất kỳ field nào được SET sau này sẽ hiện ra trong snapshot.
    #
    # _normalize_tool_dump chỉ đụng vào "description" (xem docstring của nó
    # để biết lý do) — mọi field khác, gồm cả inputSchema/outputSchema, giữ
    # nguyên xi từ model_dump, so khớp CHÍNH XÁC như cũ.
    return {
        t.name: _normalize_tool_dump(
            t.model_dump(exclude={"name"}, exclude_none=True, by_alias=True)
        )
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
