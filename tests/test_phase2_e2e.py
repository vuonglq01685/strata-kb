"""Phase 2 acceptance E2E: full BA → Jira → Dev loop with an amendment.

Scenario = completion criteria 1 + 2 of the spec: BA pins at rev1 →
amendment (commit rev2) → Dev resolves to stale, diff shows only the
right section, doctor exits 2.
"""

import pytest

# Contingency (see task-9-brief.md Step 1 + src/aero_kb/mcp.py): SDK v2 (`mcp
# import Client`) has no released build on PyPI for this environment — use SDK v1
# (mcp>=1.2) with the in-memory client session `create_connected_server_and_client_session`
# instead of `mcp.Client`. Equivalent API: list_tools()/call_tool(name, args);
# read text via result.content[0].text (see tests/test_mcp.py).
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

    # 1. BA: generates a kb-context block (pinned at rev1) — pastes it into Jira
    result = runner.invoke(
        app,
        ["context", "new", "--refs", "demo-doc §1.1", "--tags", "demo",
         "--kb-dir", str(fixture_kb)],
    )
    assert result.exit_code == 0
    ticket = f"# TAL-1 Airspace popup\n\nAC: show the field per [demo-doc §1.1]\n\n{result.output}"

    # 2. Amendment after the BA wrote it: edits L2 + summary §1.1, commits rev2
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

    # 3. Dev: resolves via MCP → gets exactly what the BA saw + a stale warning
    server = create_server(ServerConfig(kb_dir=fixture_kb))
    async with connect_client(server, raise_exceptions=True) as client:
        resolved = await client.call_tool("kb_resolve", {"kb_context": ticket})
        text = resolved.content[0].text
    assert "status=stale" in text
    assert "designation and type fields" in text  # pinned version, not the new one

    # 4. kb diff points to exactly the changed section for SME/BA review
    rev1 = run_git(root, "rev-list", "--max-parents=0", "--abbrev-commit", "HEAD")
    result = runner.invoke(
        app, ["diff", "demo-doc", "--against", rev1, "--kb-dir", str(fixture_kb)]
    )
    assert result.exit_code == 0
    assert "~ §1.1" in result.output
    assert "§1.2" not in result.output

    # 5. kb doctor --context: CI can distinguish "needs BA re-confirmation" (exit 2)
    ticket_file = root / "ticket.md"
    ticket_file.write_text(ticket, encoding="utf-8")
    result = runner.invoke(
        app,
        ["doctor", "--context", str(ticket_file), "--kb-dir", str(fixture_kb)],
    )
    assert result.exit_code == 2
