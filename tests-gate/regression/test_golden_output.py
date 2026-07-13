"""Đóng băng OUTPUT trên một KB cố định (v0.9.0 từ git history).

ĐỎ NGHĨA LÀ GÌ: hành vi đã đổi. Thường là do nâng cấp dependency (rank-bm25 đổi
công thức ranking là ca kinh điển). Điều tra TRƯỚC, chỉ chạy UPDATE_GOLDEN=1
sau khi đã hiểu tại sao nó đổi và xác nhận là mong muốn.

HAI CÁCH SO TRONG FILE NÀY — đừng nhầm cái nào áp dụng cho test nào:
  - `assert_golden()` (kb_search — cả bề mặt MCP lẫn CLI): so SAU khi
    normalize() — pattern NOISE thay `score=<số>` bằng `score=<N>` trước khi
    so. kb_search nhúng float BM25 thô (`score=12.34`) trên CẢ HAI bề mặt;
    golden được sinh trên macOS còn CI chạy ubuntu, rank-bm25 tính qua numpy,
    và thứ tự rút gọn (reduction order) của numpy có thể khác giữa các kiến
    trúc — đóng băng đúng giá trị float sẽ làm golden vỡ vì lý do trình bày
    (rounding, platform libm), không phải vì hành vi đổi. Một cửa đỏ ngẫu
    nhiên là một cửa sẽ bị tắt, và một cửa bị tắt thì không bảo vệ gì cả.
  - `assert_golden_exact()` (kb_get_section): so CHÍNH XÁC — chỉ `.strip()`,
    KHÔNG normalize(). kb_get_section trả về đúng MỘT section và KHÔNG có
    BM25 score trong output — không có gì biến động cần che, nên đây mới là
    golden "hợp đồng MÁY" đúng nghĩa: chuỗi trả về của MCP tool được so
    byte-for-byte.

PHẠM VI BẢO VỆ CỦA assert_golden() (kb_search, MCP lẫn CLI) — đọc kỹ trước
khi tin golden này:
  - CÓ bảo vệ:
    (a) thứ tự kết quả trả về + toàn bộ nội dung (citation, text L2, số
        token) của từng kết quả — một nâng cấp rank-bm25 đổi công thức đủ để
        đảo thứ tự hai hit gần điểm nhau, hoặc đổi tập kết quả lọt vào
        budget, sẽ làm golden đỏ ngay cả khi mọi unit test khác vẫn xanh.
    (b) note "score closely — both may be relevant..." mà
        `src/center_kb/mcp.py::kb_search` chỉ phát ra khi khoảng cách TƯƠNG
        ĐỐI giữa điểm hai kết quả đứng đầu nhỏ hơn `AMBIGUOUS_SCORE_GAP`
        (0.20) — cụ thể: `gap = (results[0].score - results[1].score) /
        results[0].score`, và note xuất hiện khi `gap < 0.20`. Một công thức
        ranking đổi làm `gap` vượt/lọt ngưỡng đó sẽ làm note này xuất hiện,
        biến mất, hoặc đổi citation — golden đỏ ngay cả khi thứ tự kết quả
        không đổi.
  - KHÔNG bảo vệ: giá trị số TUYỆT ĐỐI của `score=`. Một nâng cấp rank-bm25
    đổi công thức nhưng tình cờ giữ nguyên CẢ thứ tự kết quả LẪN cách phân
    loại "score closely" (chỉ đổi độ lớn tuyệt đối, không đổi thứ tự hay tỉ
    lệ tương đối giữa top-2) sẽ KHÔNG bị bắt bởi golden này. Đây là điểm mù
    còn lại — nói thẳng ra để người đọc sau biết chính xác lưới này bắt được
    gì và không bắt được gì.
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


def assert_golden_exact(name: str, actual: str) -> None:
    """So khớp CHÍNH XÁC — chỉ `.strip()`, không đi qua normalize()/NOISE.

    Dành riêng cho kb_get_section: output của nó không nhúng BM25 score hay
    bất kỳ giá trị biến động nào khác, nên không có gì cần che trước khi so —
    đây là golden "hợp đồng MÁY" thật sự (byte-for-byte), khác với
    assert_golden() ở trên vốn phải normalize() trước vì kb_search nhúng
    score thô."""
    path = GOLDEN / name
    actual = actual.strip() + "\n"
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


def test_golden_kb_search_restrictive(published_kb_mcp_params):
    out = asyncio.run(
        _call_mcp(
            published_kb_mcp_params, "kb_search", {"query": "restrictive airspace"}
        )
    )

    assert_golden("mcp_outputs/kb_search_restrictive.txt", out)


def test_golden_kb_get_section(published_kb_mcp_params):
    """kb_get_section thật sự — không có BM25 score trong output nên so
    CHÍNH XÁC (assert_golden_exact, không normalize()). §5.129 (Restrictive
    Airspace Designation) là section có thật trong KB v0.9.0 đóng băng — đã
    xác nhận qua các golden kb_search ở trên và qua git show trực tiếp lên
    v0.9.0:.kb/arinc-424/ch5-navigation-data-field-definitions{,.raw}.md.
    Test cả l2 (condensed) và l3 (verbatim, có bản quyền) để chứng minh việc
    tách L2/L3 vẫn hoạt động thông suốt tới tận bề mặt MCP."""
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
