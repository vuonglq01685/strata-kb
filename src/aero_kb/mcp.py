from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

# Contingency (see task-9-brief.md Step 1): mcp>=2.0 has no released build on
# PyPI for this environment (only 2.0.0a1..2.0.0b1) — pin mcp>=1.2 and use
# FastMCP (the SDK v1 high-level API) as MCPServer.
from mcp.server.fastmcp import FastMCP as MCPServer

from aero_kb import gitio, kbcontext, models
from aero_kb.query import get_section, search
from aero_kb.resolve import render_resolved, resolve_refs
from aero_kb.web.auth import TokenAuthMiddleware as BearerAuthMiddleware  # noqa: F401 — re-export


@dataclass
class ServerConfig:
    kb_dir: Path
    hub: str | None = None
    transport: str = "stdio"
    host: str = "127.0.0.1"
    port: int = 8321


def _known_docs(kb_dir: Path) -> str:
    index_path = kb_dir / "index.yaml"
    if not index_path.exists():
        return ""
    index = models.load_yaml_model(index_path, models.KBIndex)
    return ", ".join(d.id for d in index.docs)


def create_server(config: ServerConfig) -> MCPServer:
    mcp = MCPServer("aero-kb")

    def _hub():
        if not config.hub:
            return None
        from aero_kb.hub import resolve_hub

        return resolve_hub(config.hub)

    @mcp.tool()
    def kb_search(
        query: str, tags: list[str] | None = None, budget: int = 2000
    ) -> str:
        """Find sections by tag match + BM25; return L2 content within the token budget, with citations."""
        results = search(config.kb_dir, query, tags=tags, budget=budget, hub=_hub())
        if not results:
            return "No matching section found — try dropping tags or changing keywords."
        return "\n\n".join(
            f"--- [{r.citation}] score={r.score:.2f} ~{r.tokens}tk\n{r.content}"
            for r in results
        )

    @mcp.tool()
    def kb_get_section(doc: str, section: str, level: str = "l2") -> str:
        """Fetch exactly one section: level 'l2' (condensed) or 'l3' (verbatim)."""
        if level not in ("l2", "l3"):
            return f"level '{level}' is invalid — use 'l2' or 'l3'."
        result = get_section(config.kb_dir, doc, section, level=level, hub=_hub())
        if result is None:
            known = _known_docs(config.kb_dir)
            hint = f" Available docs: {known}." if known else ""
            return f"Not found: {doc} §{section}.{hint}"
        return f"--- [{result.citation}] ~{result.tokens}tk\n{result.content}"

    @mcp.tool()
    def kb_resolve(kb_context: str) -> str:
        """Accept a kb-context block (or the raw ticket text containing one); return the cited sections at their pinned version + freshness ok/stale/broken."""
        try:
            ctx = kbcontext.parse(kb_context)
        except kbcontext.KBContextError as exc:
            return f"kb-context error: {exc}"
        try:
            results = resolve_refs(config.kb_dir, ctx, hub=_hub())
        except gitio.GitError as exc:
            return f"git error: {exc}"
        return render_resolved(results)

    return mcp


def create_http_app(config: ServerConfig, token: str):
    """FastMCP's streamable HTTP Starlette app, wrapped with bearer auth."""
    server = create_server(config)
    return BearerAuthMiddleware(server.streamable_http_app(), token)


def parse_args(argv: list[str] | None = None) -> ServerConfig:
    ap = argparse.ArgumentParser(
        prog="python -m aero_kb.mcp", description="AERO-KB MCP server"
    )
    ap.add_argument("--kb", type=Path, default=Path(".kb"), help="KB directory")
    ap.add_argument("--hub", default=None, help="kb-hub URL/path (Phase 3)")
    ap.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default="stdio",
        help="stdio (default) or http (streamable HTTP, requires AERO_KB_HTTP_TOKEN)",
    )
    ap.add_argument("--host", default="127.0.0.1", help="Host to bind when --transport http")
    ap.add_argument("--port", type=int, default=8321, help="Port when --transport http")
    args = ap.parse_args(argv)
    return ServerConfig(
        kb_dir=args.kb,
        hub=args.hub,
        transport=args.transport,
        host=args.host,
        port=args.port,
    )


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO)
    config = parse_args(argv)
    if config.transport == "http":
        import os

        token = os.environ.get("AERO_KB_HTTP_TOKEN", "")
        if not token:
            raise SystemExit(
                "missing env AERO_KB_HTTP_TOKEN — required for http transport "
                "(the documents are copyrighted; do not run HTTP without auth)"
            )
        import uvicorn

        uvicorn.run(create_http_app(config, token), host=config.host, port=config.port)
        return
    create_server(config).run()


if __name__ == "__main__":
    main()
