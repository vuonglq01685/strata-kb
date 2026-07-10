"""E2E nghiệm thu Phase 2: vòng BA → Jira → Dev trọn vẹn với amendment.

Kịch bản = tiêu chí hoàn thành 1 + 2 của spec: BA pin tại rev1 → amendment
(commit rev2) → Dev resolve ra stale, diff chỉ đúng section, doctor exit 2.
"""

import pytest

# Contingency (xem task-9-brief.md Step 1 + src/aero_kb/mcp.py): SDK v2 (`mcp
# import Client`) chưa release trên PyPI của môi trường này — dùng SDK v1
# (mcp>=1.2) với client in-memory session `create_connected_server_and_client_session`
# thay cho `mcp.Client`. API tương đương: list_tools()/call_tool(name, args);
# đọc text qua result.content[0].text (xem tests/test_mcp.py).
from mcp.shared.memory import create_connected_server_and_client_session as connect_client
from typer.testing import CliRunner

from aero_kb import models
from aero_kb.cli import app
from aero_kb.mcp import ServerConfig, create_server

runner = CliRunner()


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_full_loop_ba_to_dev_with_amendment(fixture_kb, run_git):
    root = fixture_kb.parent
    run_git(root, "init")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "kb v1")

    # 1. BA: sinh block kb-context (pin tại rev1) — dán vào Jira
    result = runner.invoke(
        app,
        ["context", "new", "--refs", "demo-doc §1.1", "--tags", "demo",
         "--kb-dir", str(fixture_kb)],
    )
    assert result.exit_code == 0
    ticket = f"# TAL-1 Airspace popup\n\nAC: hiển thị field theo [demo-doc §1.1]\n\n{result.output}"

    # 2. Amendment sau khi BA viết: sửa L2 + summary §1.1, commit rev2
    l2 = fixture_kb / "demo-doc" / "ch1-records.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace(
            "airspace record structure with designation and type fields.",
            "airspace record structure with NEW multiple code field.",
        ),
        encoding="utf-8",
    )
    manifest_path = fixture_kb / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.sections[0].summary = "Airspace records: designation, type, multiple code."
    models.save_yaml_model(manifest_path, manifest)
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "amendment 1.1")

    # 3. Dev: resolve qua MCP → nhận đúng nội dung BA đã thấy + cảnh báo stale
    server = create_server(ServerConfig(kb_dir=fixture_kb))
    async with connect_client(server, raise_exceptions=True) as client:
        resolved = await client.call_tool("kb_resolve", {"kb_context": ticket})
        text = resolved.content[0].text
    assert "status=stale" in text
    assert "designation and type fields" in text  # bản pin, không phải bản mới

    # 4. kb diff chỉ ra đúng section thay đổi để SME/BA review
    rev1 = run_git(root, "rev-list", "--max-parents=0", "--abbrev-commit", "HEAD")
    result = runner.invoke(
        app, ["diff", "demo-doc", "--against", rev1, "--kb-dir", str(fixture_kb)]
    )
    assert result.exit_code == 0
    assert "~ §1.1" in result.output
    assert "§1.2" not in result.output

    # 5. kb doctor --context: CI phân biệt được "cần BA xác nhận lại" (exit 2)
    ticket_file = root / "ticket.md"
    ticket_file.write_text(ticket, encoding="utf-8")
    result = runner.invoke(
        app,
        ["doctor", "--context", str(ticket_file), "--kb-dir", str(fixture_kb)],
    )
    assert result.exit_code == 2
