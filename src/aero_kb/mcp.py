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
    hub: str | None = None  # Phase 3 — đọc sẵn, chưa kích hoạt


def _known_docs(kb_dir: Path) -> str:
    index_path = kb_dir / "index.yaml"
    if not index_path.exists():
        return ""
    index = models.load_yaml_model(index_path, models.KBIndex)
    return ", ".join(d.id for d in index.docs)


def create_server(config: ServerConfig) -> MCPServer:
    mcp = MCPServer("aero-kb")

    @mcp.tool()
    def kb_search(
        query: str, tags: list[str] | None = None, budget: int = 2000
    ) -> str:
        """Tìm section theo tag match + BM25; trả nội dung L2 trong token budget, kèm citation."""
        results = search(config.kb_dir, query, tags=tags, budget=budget)
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
        result = get_section(config.kb_dir, doc, section, level=level)
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
            results = resolve_refs(config.kb_dir, ctx)
        except gitio.GitError as exc:
            return f"git lỗi: {exc}"
        return render_resolved(results, ctx.version)

    return mcp


def parse_args(argv: list[str] | None = None) -> ServerConfig:
    ap = argparse.ArgumentParser(
        prog="python -m aero_kb.mcp", description="AERO-KB MCP server (stdio)"
    )
    ap.add_argument("--kb", type=Path, default=Path(".kb"), help="Thư mục KB")
    ap.add_argument(
        "--hub", default=None, help="URL kb-hub (Phase 3 — nhận nhưng chưa kích hoạt)"
    )
    args = ap.parse_args(argv)
    return ServerConfig(kb_dir=args.kb, hub=args.hub)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO)
    config = parse_args(argv)
    if config.hub:
        logger.warning(
            "hub '%s' được cấu hình nhưng chưa kích hoạt trước Phase 3", config.hub
        )
    create_server(config).run()


if __name__ == "__main__":
    main()
