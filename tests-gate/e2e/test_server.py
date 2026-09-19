"""HTTP + MCP against the installed artifact.

There is no `kb serve` command — the server runs via `python -m strata_kb.mcp`,
exactly as the Dockerfile's CMD does. So we invoke the python OF THE ARTIFACT
VENV, not the runner's python.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
import urllib.error
import urllib.request

import pytest

TOKEN = "e2e-token"


def _get(url: str, token: str | None = None) -> tuple[int, str]:
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


@pytest.fixture
def http_server(artifact, published_repo, free_port):
    proc = subprocess.Popen(
        [
            str(artifact.python), "-m", "strata_kb.mcp",
            "--kb", str(published_repo["kb"]),
            "--hub", str(published_repo["hub"]),
            "--transport", "http",
            "--host", "127.0.0.1",
            "--port", str(free_port),
        ],
        cwd=published_repo["repo"],
        env={**os.environ, "STRATA_KB_HTTP_TOKEN": TOKEN},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base = f"http://127.0.0.1:{free_port}"
    deadline = time.monotonic() + 60
    try:
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                pytest.fail(f"server died during startup:\n{proc.stdout.read()}")
            try:
                if _get(f"{base}/api/health")[0] == 200:
                    break
            except OSError:
                time.sleep(0.3)
        else:
            pytest.fail("server did not answer /api/health within 60s")

        yield base
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_health_is_open(http_server):
    status, _ = _get(f"{http_server}/api/health")

    assert status == 200


def test_docs_require_a_token(http_server):
    # The documents are copyrighted — HTTP without a token MUST be blocked.
    status, _ = _get(f"{http_server}/api/docs")

    assert status == 401


def test_docs_with_a_token_return_the_published_doc(http_server):
    status, body = _get(f"{http_server}/api/docs", token=TOKEN)

    assert status == 200
    assert "demo-doc" in body


def test_search_api_finds_the_seeded_section(http_server):
    # The query parameter was double-checked against the real code: api_search()
    # (web/api.py) reads request.query_params.get("q", ...) — matching the
    # brief's guess.
    status, body = _get(f"{http_server}/api/search?q=airspace", token=TOKEN)

    assert status == 200
    assert "Condensed via stub." in body


EXPECTED_TOOLS = {
    "kb_search",
    "kb_get_section",
    "kb_context_new",
    "kb_resolve",
    "kb_ticket_lint",
}


async def _handshake(params):
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            hit = await session.call_tool("kb_search", {"query": "airspace"})
            return tools, hit


def test_mcp_stdio_exposes_exactly_the_five_tools(mcp_stdio_params):
    tools, hit = asyncio.run(_handshake(mcp_stdio_params))

    assert {t.name for t in tools.tools} == EXPECTED_TOOLS

    text = "".join(c.text for c in hit.content if c.type == "text")
    assert "Condensed via stub." in text
