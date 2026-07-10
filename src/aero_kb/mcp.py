from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

# Contingency (xem task-9-brief.md Step 1): mcp>=2.0 chưa có bản release trên
# PyPI của môi trường này (chỉ có 2.0.0a1..2.0.0b1) — pin mcp>=1.2 và dùng
# FastMCP (API cao cấp của SDK v1) làm MCPServer.
from mcp.server.fastmcp import FastMCP as MCPServer

from aero_kb import gitio, kbcontext, models
from aero_kb.query import get_section, search
from aero_kb.resolve import render_resolved, resolve_refs

logger = logging.getLogger("aero_kb.mcp")


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
        """Tìm section theo tag match + BM25; trả nội dung L2 trong token budget, kèm citation."""
        results = search(config.kb_dir, query, tags=tags, budget=budget, hub=_hub())
        if not results:
            return "Không tìm thấy section phù hợp — thử bỏ tags hoặc đổi từ khóa."
        return "\n\n".join(
            f"--- [{r.citation}] score={r.score:.2f} ~{r.tokens}tk\n{r.content}"
            for r in results
        )

    @mcp.tool()
    def kb_get_section(doc: str, section: str, level: str = "l2") -> str:
        """Lấy chính xác một section: level 'l2' (cô đọng) hoặc 'l3' (nguyên văn)."""
        if level not in ("l2", "l3"):
            return f"level '{level}' không hợp lệ — dùng 'l2' hoặc 'l3'."
        result = get_section(config.kb_dir, doc, section, level=level, hub=_hub())
        if result is None:
            known = _known_docs(config.kb_dir)
            hint = f" Các doc hiện có: {known}." if known else ""
            return f"Không thấy {doc} §{section}.{hint}"
        return f"--- [{result.citation}] ~{result.tokens}tk\n{result.content}"

    @mcp.tool()
    def kb_resolve(kb_context: str) -> str:
        """Nhận block kb-context (hoặc nguyên văn ticket chứa block); trả các section đã cite đúng version pin + freshness ok/stale/broken."""
        try:
            ctx = kbcontext.parse(kb_context)
        except kbcontext.KBContextError as exc:
            return f"kb-context lỗi: {exc}"
        try:
            results = resolve_refs(config.kb_dir, ctx, hub=_hub())
        except gitio.GitError as exc:
            return f"git lỗi: {exc}"
        return render_resolved(results)

    return mcp


class BearerAuthMiddleware:
    """Chặn mọi HTTP request thiếu/sai 'Authorization: Bearer <token>' → 401."""

    def __init__(self, app, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            if headers.get("authorization") != f"Bearer {self.token}":
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": b'{"error": "unauthorized"}',
                    }
                )
                return
        await self.app(scope, receive, send)


def create_http_app(config: ServerConfig, token: str):
    """Starlette app streamable HTTP của FastMCP, bọc bearer auth."""
    server = create_server(config)
    return BearerAuthMiddleware(server.streamable_http_app(), token)


def parse_args(argv: list[str] | None = None) -> ServerConfig:
    ap = argparse.ArgumentParser(
        prog="python -m aero_kb.mcp", description="AERO-KB MCP server"
    )
    ap.add_argument("--kb", type=Path, default=Path(".kb"), help="Thư mục KB")
    ap.add_argument("--hub", default=None, help="URL/path kb-hub (Phase 3)")
    ap.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default="stdio",
        help="stdio (mặc định) hoặc http (streamable HTTP, cần AERO_KB_HTTP_TOKEN)",
    )
    ap.add_argument("--host", default="127.0.0.1", help="Host bind khi --transport http")
    ap.add_argument("--port", type=int, default=8321, help="Port khi --transport http")
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
                "thiếu env AERO_KB_HTTP_TOKEN — bắt buộc cho transport http "
                "(tài liệu có bản quyền, không chạy HTTP không auth)"
            )
        import uvicorn

        uvicorn.run(create_http_app(config, token), host=config.host, port=config.port)
        return
    create_server(config).run()


if __name__ == "__main__":
    main()
