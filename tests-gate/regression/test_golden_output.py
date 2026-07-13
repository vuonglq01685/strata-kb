"""Đóng băng OUTPUT trên một KB cố định (v0.9.0 từ git history).

Hợp đồng MÁY của center-kb nằm ở chuỗi trả về của MCP tool (kb_search,
kb_get_section, kb_resolve đều -> str) — CLI chưa có --json, nên stdout của nó
là hợp đồng NGƯỜI và chỉ được so ở dạng đã chuẩn hoá.

ĐỎ NGHĨA LÀ GÌ: hành vi đã đổi. Thường là do nâng cấp dependency (rank-bm25 đổi
công thức ranking là ca kinh điển). Điều tra TRƯỚC, chỉ chạy UPDATE_GOLDEN=1
sau khi đã hiểu tại sao nó đổi và xác nhận là mong muốn.

PHẠM VI BẢO VỆ — đọc kỹ trước khi tin golden này:
  - CÓ bảo vệ: thứ tự kết quả trả về, và toàn bộ NỘI DUNG (citation, text L2,
    số token) của từng kết quả. Một nâng cấp rank-bm25 đổi công thức ranking
    đủ để đảo thứ tự hai hit gần điểm nhau sẽ làm golden đỏ ngay cả khi mọi
    unit test khác vẫn xanh.
  - KHÔNG bảo vệ: giá trị số của `score=`. Pattern NOISE thay `score=<số>`
    bằng `score=<N>` trước khi so — nghĩa là nếu rank-bm25 đổi công thức
    nhưng thứ tự + nội dung kết quả tình cờ giữ nguyên (điểm số đổi mà
    ranking tương đối không đổi), golden này sẽ KHÔNG bắt được. Đánh đổi có
    chủ ý: định dạng float (`:.2f`) không đổi giữa các nền tảng cho một giá
    trị cố định, nhưng đóng băng đúng giá trị float sẽ làm golden vỡ vụn vì
    lý do trình bày (rounding, platform libm) chứ không phải vì hành vi đổi
    — tín hiệu thật ta cần là ORDER + CONTENT, không phải trị số điểm.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

GOLDEN = Path(__file__).parent.parent / "golden"

# Phần biến động giữa các lần chạy — không phải tín hiệu hành vi.
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
    assert actual == path.read_text(encoding="utf-8"), f"{name} đã đổi"


async def _call_mcp(params, tool: str, args: dict) -> str:
    """params: StdioServerParameters — dựng sẵn bởi fixture
    published_kb_mcp_params (tests-gate/conftest.py, Task 9) qua helper dùng
    chung _mcp_stdio_params. Không tự dựng lại StdioServerParameters ở đây."""
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


def test_golden_kb_get_section(published_kb_mcp_params):
    out = asyncio.run(
        _call_mcp(
            published_kb_mcp_params, "kb_search", {"query": "restrictive airspace"}
        )
    )

    assert_golden("mcp_outputs/kb_search_restrictive.txt", out)


def test_golden_cli_query(published_kb, kb_run):
    out = kb_run("query", "airspace", "--hub", str(published_kb["hub"]),
                 "--kb-dir", str(published_kb["kb"]),
                 cwd=published_kb["repo"]).stdout

    assert_golden("cli_outputs/query_airspace.txt", out)
