"""kb_search over real stdio must answer.

Reviewer C F-C1: `searchdb._load_vec` imported `sqlite_vec` — and transitively
numpy's native `_multiarray_umath` — at request time, and FastMCP runs a sync
tool inline on the asyncio event-loop thread, where that native import
deadlocks on Windows. The server stayed alive and never replied: 120 s, no
response, ever. Every `[embed]` install, every `[dev]` install and this repo's
own `.venv` pull in `sqlite_vec`, so all of them hit this deadlock.

This test proves only the first of F-C1's two layers: the sqlite_vec/numpy
import is off the event-loop thread (`searchdb.warm_vec()`, called from
`create_server` before any loop starts). It does not by itself close F-C1 for
an `[embed]` install: `kb_search` also reaches `query.search() ->
embed_mod.default_embedder()`, whose first call does `from fastembed import
TextEmbedding` plus ONNX model construction — the same failure class, on the
same thread. `fastembed` is not installed in this repo's `.venv`, so this
test's server takes the ImportError-degrade path and never exercises that
import. The second layer — running each tool body via
`anyio.to_thread.run_sync` so the whole call, imports included, is off the
loop — is what covers that remaining case.

The reader runs on its own thread so that a hang fails this test instead of
hanging it.
"""
import json
import queue
import subprocess
import sys
import threading
import time

import pytest

pytest.importorskip("sqlite_vec")  # the deadlock only exists when it is importable

TIMEOUT_S = 30


def _reader(pipe, q: "queue.Queue") -> None:
    for line in pipe:
        q.put(line)
    q.put(None)


def _send(proc, payload: dict) -> None:
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()


def test_kb_search_over_stdio_answers(fed_hub):
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "strata_kb.mcp",
            "--kb", str(fed_hub / ".kb"),
            "--hub", str(fed_hub),
            "--transport", "stdio",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    q: "queue.Queue" = queue.Queue()
    threading.Thread(target=_reader, args=(proc.stdout, q), daemon=True).start()
    try:
        _send(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "stdio-test", "version": "0"},
            },
        })
        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        _send(proc, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "kb_search", "arguments": {"query": "airspace"}},
        })
        deadline = time.monotonic() + TIMEOUT_S
        while True:
            remaining = deadline - time.monotonic()
            assert remaining > 0, (
                f"kb_search did not answer within {TIMEOUT_S}s over stdio "
                "(F-C1: native import deadlocked on the event-loop thread)"
            )
            try:
                line = q.get(timeout=remaining)
            except queue.Empty:
                raise AssertionError(
                    f"kb_search did not answer within {TIMEOUT_S}s over stdio "
                    "(F-C1: native import deadlocked on the event-loop thread)"
                )
            assert line is not None, "server closed stdout before answering"
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == 2:
                assert "result" in msg, msg
                return
    finally:
        proc.kill()
        proc.wait(timeout=10)
