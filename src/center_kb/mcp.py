from __future__ import annotations

import argparse
import inspect
import logging
import os
from dataclasses import dataclass
from pathlib import Path

# Contingency (see task-9-brief.md Step 1): mcp>=2.0 has no released build on
# PyPI for this environment (only 2.0.0a1..2.0.0b1) — pin mcp>=1.2 and use
# FastMCP (the SDK v1 high-level API) as MCPServer.
from mcp.server.fastmcp import FastMCP as MCPServer

from center_kb import gitio, kbcontext
from center_kb.query import get_section, search
from center_kb.resolve import render_resolved, resolve_refs
from center_kb.web.auth import TokenAuthMiddleware as BearerAuthMiddleware  # noqa: F401 — re-export


# Below this relative score gap between the top 2 kb_search results, both
# are surfaced with a note instead of letting the top hit look unambiguous.
AMBIGUOUS_SCORE_GAP = 0.20


@dataclass
class ServerConfig:
    kb_dir: Path
    hub: str
    transport: str = "stdio"
    host: str = "127.0.0.1"
    port: int = 8321


def _known_docs(hub) -> str:
    from center_kb.federation import load_federation

    return ", ".join(
        f"{r.meta.repo_id}:{d.id}"
        for r in load_federation(hub.federation_dir)
        for d in r.index.docs
    )


HUB_DOWN = (
    "hub unreachable and no local cache — queries need the hub federation; "
    "check the network or the hub path, then try again"
)


def _canonical_docstring(fn):
    """Normalize `fn.__doc__` with `inspect.cleandoc` before FastMCP reads it
    as the MCP `description` (`Tool.from_function` uses `fn.__doc__` verbatim
    — see mcp.server.fastmcp.tools.base). This is not test scaffolding: the
    wheel ships `.py` sources, not `.pyc`, so each tool's docstring is
    compiled by whichever CPython the *user* runs the server under, not by
    the interpreter that built the wheel. CPython 3.13+ auto-dedents
    multi-line docstrings at compile time (gh-81283); 3.11/3.12 keep the
    source's leading whitespace as-is. Left alone, the exact same wheel would
    hand different agents different `description` strings depending only on
    their local Python — a real inconsistency in the MCP wire contract.
    Canonicalizing here, at registration time, makes the emitted description
    identical on every supported interpreter."""
    fn.__doc__ = inspect.cleandoc(fn.__doc__ or "")
    return fn


def create_server(config: ServerConfig) -> MCPServer:
    mcp = MCPServer("center-kb")

    def _hub():
        from center_kb.hub import resolve_hub

        return resolve_hub(config.hub)

    def _stale_note(hub) -> str:
        if hub is not None and hub.stale:
            age = f"~{hub.age_seconds:.0f}s" if hub.age_seconds else "unknown age"
            return f"[warn] hub cache is stale ({age}) — results may lag the hub\n\n"
        return ""

    @mcp.tool()
    @_canonical_docstring
    def kb_search(
        query: str, tags: list[str] | None = None, budget: int = 2000
    ) -> str:
        """Find sections by tag match + BM25 (falls back to semantic search);
        return L2 content within the token budget, with citations. Returns
        every relevant section found, not just the best match — when using
        this to draft a User Story, show ALL returned sections (with their
        citations) to the user and confirm which ones actually apply before
        writing story content from them. Citing more than one section for a
        single story is normal. Once confirmed, call kb_context_new with the
        confirmed refs to pin them for the ticket. Results come from the hub
        federation — unpublished local content never appears."""
        hub = _hub()
        if hub is None:
            return HUB_DOWN
        results = search(hub, query, tags=tags, budget=budget)
        if not results:
            return "No matching section found — try dropping tags or changing keywords."
        note = _stale_note(hub)
        if len(results) >= 2 and results[0].score > 0:
            gap = (results[0].score - results[1].score) / results[0].score
            if gap < AMBIGUOUS_SCORE_GAP:
                note += (
                    f"Note: [{results[0].citation}] and [{results[1].citation}] "
                    "score closely — both may be relevant to your question; "
                    "review each before citing.\n\n"
                )
        return note + "\n\n".join(
            f"--- [{r.citation}] score={r.score:.2f} ~{r.tokens}tk\n{r.content}"
            for r in results
        )

    @mcp.tool()
    @_canonical_docstring
    def kb_get_section(
        doc: str, section: str, level: str = "l2", repo: str = ""
    ) -> str:
        """Fetch exactly one section: level 'l2' (condensed) or 'l3' (verbatim).
        `doc` accepts 'repo:doc' form; pass `repo` when the doc id alone is
        ambiguous across federation repos."""
        if level not in ("l2", "l3"):
            return f"level '{level}' is invalid — use 'l2' or 'l3'."
        hub = _hub()
        if hub is None:
            return HUB_DOWN
        from center_kb.query import AmbiguousDocError

        try:
            result = get_section(hub, doc, section, level=level, repo=repo or None)
        except AmbiguousDocError as exc:
            return str(exc)
        if result is None:
            known = _known_docs(hub)
            hint = f" Available docs: {known}." if known else ""
            return f"Not found: {doc} §{section}.{hint}"
        return (
            _stale_note(hub)
            + f"--- [{result.citation}] ~{result.tokens}tk\n{result.content}"
        )

    @mcp.tool()
    @_canonical_docstring
    def kb_context_new(refs: list[str], tags: list[str] | None = None) -> str:
        """Pin a kb-context citation block at the current KB commit, from 1+
        refs like 'arinc-424 §5.129'. Call this only after the user has
        confirmed which section(s) — out of everything kb_search returned —
        actually belong in the story; paste the returned block into the
        ticket. Citing 2-3 sections for one story is normal — pass every
        confirmed ref in one call."""
        hub = _hub()
        if hub is None:
            return HUB_DOWN
        try:
            block, warning = kbcontext.build_context_block(hub, refs, tags=tags)
        except kbcontext.KBRefNotFoundError as exc:
            known = _known_docs(hub)
            hint = f" Available docs: {known}." if known else ""
            return f"{exc}{hint}"
        except kbcontext.KBContextError as exc:
            return str(exc)
        except gitio.GitError as exc:
            return str(exc)
        if warning:
            return f"{warning}\n\n{block}"
        return block

    @mcp.tool()
    @_canonical_docstring
    def kb_resolve(kb_context: str) -> str:
        """Accept a kb-context block (or the raw ticket text containing one); return the cited sections at their pinned version + freshness ok/stale/broken."""
        hub = _hub()
        if hub is None:
            return HUB_DOWN
        try:
            ctx = kbcontext.parse(kb_context)
        except kbcontext.KBContextError as exc:
            return f"kb-context error: {exc}"
        try:
            results = resolve_refs(hub, ctx)
        except gitio.GitError as exc:
            return f"git error: {exc}"
        return _stale_note(hub) + render_resolved(results)

    return mcp


def create_http_app(config: ServerConfig, token: str):
    """One ASGI app: MCP (streamable HTTP) + REST /api + HTML /ui, token-guarded."""
    from center_kb.web.app import create_app

    return create_app(config, token, mcp_server=create_server(config))


def parse_args(argv: list[str] | None = None) -> ServerConfig:
    ap = argparse.ArgumentParser(
        prog="python -m center_kb.mcp", description="CENTER-KB MCP server"
    )
    ap.add_argument("--kb", type=Path, default=Path(".kb"),
                    help="KB directory (chỉ để tìm .kb/config.yaml)")
    ap.add_argument("--hub", default=None,
                    help="kb-hub URL/path (default: env CENTER_KB_HUB, rồi .kb/config.yaml)")
    ap.add_argument("--transport", choices=("stdio", "http"), default="stdio",
                    help="stdio (default) or http (requires CENTER_KB_HTTP_TOKEN)")
    ap.add_argument("--host", default="127.0.0.1", help="Host to bind when --transport http")
    ap.add_argument("--port", type=int, default=8321, help="Port when --transport http")
    args = ap.parse_args(argv)
    from center_kb.config import HubConfigError, require_hub

    try:
        hub = require_hub(
            args.hub or os.environ.get("CENTER_KB_HUB", ""), args.kb
        )
    except HubConfigError as exc:
        raise SystemExit(str(exc))
    return ServerConfig(
        kb_dir=args.kb, hub=hub, transport=args.transport,
        host=args.host, port=args.port,
    )


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO)
    config = parse_args(argv)
    if config.transport == "http":
        token = os.environ.get("CENTER_KB_HTTP_TOKEN", "")
        if not token:
            raise SystemExit(
                "missing env CENTER_KB_HTTP_TOKEN — required for http transport "
                "(the documents are copyrighted; do not run HTTP without auth)"
            )
        import uvicorn

        uvicorn.run(create_http_app(config, token), host=config.host, port=config.port)
        return
    create_server(config).run()


if __name__ == "__main__":
    main()
