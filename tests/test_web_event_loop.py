"""2026-10-10 review §6.2 F3: every Web/REST handler but /api/search ran its
sync work on the event loop -- one /ui render froze /api/health (and MCP)
for 9 s. A slow handler must now leave the loop free."""

from __future__ import annotations

import time

import anyio
import httpx
import pytest

from strata_kb.mcp import ServerConfig
from strata_kb.web import uidata
from strata_kb.web.app import create_app

TOKEN = "t" * 48
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _slow(real, seconds=1.0):
    def wrapped(*a, **k):
        time.sleep(seconds)
        return real(*a, **k)

    return wrapped


async def _health_while(app, path: str) -> float:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        slow_started = anyio.Event()
        health_ms: list[float] = []
        started_at: list[float] = []

        async def slow():
            started_at.append(time.perf_counter())
            slow_started.set()
            await c.get(path, headers=AUTH)

        async def probe():
            await slow_started.wait()
            await anyio.sleep(0.1)
            resp = await c.get("/api/health")
            # Measured from when the probe was due (0.1 s after the slow
            # request started), not from when its timer got to run: a
            # blocked loop delays the timer itself.
            due = started_at[0] + 0.1
            health_ms.append((time.perf_counter() - due) * 1000)
            assert resp.status_code == 200

        async with anyio.create_task_group() as tg:
            tg.start_soon(slow)
            tg.start_soon(probe)
    return health_ms[0]


@pytest.mark.parametrize(
    ("path", "target", "attr"),
    [
        ("/ui", uidata, "store_stats"),
        ("/ui/docs", "strata_kb.web.api", "list_docs"),
        ("/api/docs", "strata_kb.web.api", "list_docs"),
        ("/api/docs/arinc-424", "strata_kb.web.api", "load_manifest"),
        ("/api/docs/arinc-424/sections/5.3", "strata_kb.web.api", "get_section"),
    ],
)
def test_health_answers_while_a_slow_page_renders(
    fed_hub, monkeypatch, path, target, attr
):
    import importlib

    module = importlib.import_module(target) if isinstance(target, str) else target
    monkeypatch.setattr(module, attr, _slow(getattr(module, attr)))
    app = create_app(ServerConfig(kb_dir=fed_hub / ".kb", hub=str(fed_hub)), TOKEN)
    ms = anyio.run(_health_while, app, path)
    assert ms < 500, f"/api/health took {ms:.0f} ms while {path} rendered"


def test_health_answers_while_a_login_verifies_a_password(fed_hub, monkeypatch):
    """scrypt + sqlite in login_post run in a worker thread: a slow verify
    (stand-in for a held sqlite write lock) must not freeze the loop."""
    from strata_kb.serving.accounts import Accounts

    monkeypatch.setattr(Accounts, "verify", _slow(Accounts.verify))
    app = create_app(ServerConfig(kb_dir=fed_hub / ".kb", hub=str(fed_hub)), TOKEN)

    async def run() -> float:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            started = anyio.Event()
            out: list[float] = []
            started_at: list[float] = []

            async def login():
                started_at.append(time.perf_counter())
                started.set()
                await c.post("/ui/login", data={"username": "u", "password": "p"})

            async def probe():
                await started.wait()
                await anyio.sleep(0.1)
                # Measured from when the probe was due: a blocked loop delays
                # the timer itself, so "now" would hide the stall.
                due = started_at[0] + 0.1
                assert (await c.get("/api/health")).status_code == 200
                out.append((time.perf_counter() - due) * 1000)

            async with anyio.create_task_group() as tg:
                tg.start_soon(login)
                tg.start_soon(probe)
            return out[0]

    ms = anyio.run(run)
    assert ms < 500, f"/api/health took {ms:.0f} ms during a login verify"
