"""mcp — the Strata MCP server (`python -m strata_kb.mcp`).

`create_server()` registers the kb_search, kb_get_section, kb_context_new,
kb_resolve, kb_ticket_lint, kb_ticket_check and kb_mission_next tools over
the hub federation; every tool body
runs on a worker thread and resolves the hub under one lock. `main()` serves
stdio by default; `--transport http` mounts the same server inside the
token-guarded `web.app` and refuses a weak STRATA_KB_HTTP_TOKEN.
"""

from __future__ import annotations

import argparse
import inspect
import json
import logging
import os
import re
import threading
from pathlib import Path

import anyio.to_thread

# mcp>=2.0 has no released build on PyPI for this environment (only
# 2.0.0a1..2.0.0b1) — pin mcp>=1.2 and use FastMCP (the SDK v1 high-level API)
# as MCPServer.
from mcp.server.fastmcp import FastMCP as MCPServer

from strata_kb import gitio, kbcontext
from strata_kb.kinds import UnknownKindError
from strata_kb.query import get_section, search_detailed, stale_hub_note
from strata_kb.resolve import render_resolved, resolve_refs
from strata_kb.serving.auth import (
    TokenAuthMiddleware as BearerAuthMiddleware,  # noqa: F401 — re-export
)
from strata_kb.serving.config import ServerConfig
from strata_kb.ticketlint import lint as lint_ticket

logger = logging.getLogger("strata_kb.mcp")

_AMBIGUOUS_MIN_RATIO = 0.8  # top-2 are "close" when the 2nd score >= 80% of the 1st


def _ambiguity_note(results) -> str:
    """Prompt a review of both top results when they are genuinely hard to separate.

    RRF scores carry no magnitude the way BM25 does: adjacent ranks within one
    leg always sit ~1.6% apart in relative terms (1/61 vs 1/62), so a
    relative-gap comparison would fire the note on almost every query. Truly
    ambiguous means both results are confirmed by both legs (hybrid) AND the
    scores are genuinely close, or the scores are exactly equal (tie)."""
    if len(results) < 2:
        return ""
    top, second = results[0], results[1]
    both_hybrid = top.match_mode == "hybrid" and second.match_mode == "hybrid"
    close = second.score >= _AMBIGUOUS_MIN_RATIO * top.score
    if not (both_hybrid and close) and top.score != second.score:
        return ""
    return (
        f"Note: [{top.citation}] and [{second.citation}] "
        "score closely — both may be relevant to your question; "
        "review each before citing.\n\n"
    )


def _known_docs(hub) -> str:
    from strata_kb.federation import load_federation

    return ", ".join(
        f"{r.meta.repo_id}:{d.id}"
        for r in load_federation(hub.federation_dir)
        for d in r.index.docs
    )


def _mission_loader(hub, mission_markdown: str | None):
    """Mission text by id for the ticket tools: the client's
    `mission_markdown` when its `> Mission:` line names that id, else the
    mission's section of the hub's plan, else None."""
    from strata_kb import mission, ticketfetch

    def load(mission_id: str) -> str | None:
        if mission_markdown:
            m = mission.MISSION_LINE_RE.search(mission_markdown)
            if m is not None and m.group(1) == mission_id:
                return mission_markdown
        try:
            return ticketfetch.render(hub, mission_id)
        except ticketfetch.TicketFetchError:
            return None

    return load


HUB_DOWN = (
    "hub unreachable — queries need the hub federation; check the network "
    "or the hub path, then try again"
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
    import sqlite3

    from strata_kb import searchdb

    # Never import sqlite_vec/numpy from inside a tool call — FastMCP runs sync
    # tools on the event-loop thread and the native import deadlocks there.
    searchdb.warm_vec()
    mcp = MCPServer("strata-kb")
    # Each tool body runs on its own worker thread (anyio.to_thread.run_sync),
    # off the loop thread, so concurrent calls genuinely race rather than being
    # serialized by the single event loop. resolve_hub() clones/pulls into a
    # cache shared by every call; without a lock, two concurrent URL-hub
    # resolutions can run `git clone`/`git pull` against the same directory
    # at once. One lock, held only around resolve_hub() itself, keeps hub
    # resolution serialized while leaving the actual tool work (search, etc.)
    # to run concurrently on its own thread.
    _hub_lock = threading.Lock()

    def _hub():
        from strata_kb.hub import resolve_hub

        with _hub_lock:
            # resolve_hub can raise gitio.GitError (hub.py's _discard_cache)
            # when a stale cache cannot be removed -- e.g. Windows holding a lock
            # on <cache>/.kb-work/search.sqlite3, and a serving MCP process
            # is exactly the kind of process that would be holding it open.
            # Every call site below already treats None as "hub
            # unreachable" (HUB_DOWN); folding the exception into that same
            # None reuses the guard every tool call already has, instead of
            # letting it crash the tool call as an unhandled exception. Same
            # shape as intake._resolve_hub_or_503 minus the 503 wrapping --
            # there is no HTTP status here to carry it.
            #
            # Log it: a bare `except ... return None` here would discard the
            # ONLY diagnostic -- a full locked-cache sweep at DEBUG would
            # produce zero strata_kb.* log records. In this exact condition a
            # "no local cache" claim would be false on both halves (the hub
            # can be perfectly reachable, and the whole reason this raised is
            # that a cache DOES exist -- it is merely locked), which is why
            # HUB_DOWN does not assert it. resolve_hub's own clone/pull
            # failures already log at warning (see hub.py) -- match that
            # shape instead of being the one silent guard.
            try:
                return resolve_hub(config.hub)
            except gitio.GitError as exc:
                logger.warning(
                    "hub cache unusable — serving as hub-unreachable: %s", exc
                )
                return None

    @mcp.tool()
    @_canonical_docstring
    async def kb_search(
        query: str,
        tags: list[str] | None = None,
        budget: int = 2000,
        kinds: list[str] | None = None,
    ) -> str:
        """Find sections by hybrid search (FTS5 keyword + semantic KNN, RRF-fused);
        return L2 content within the token budget, with citations. Returns the
        top-ranked sections, not just the best match — each leg is capped at 50
        results before fusion, and a note says so when matches were dropped.
        When using this to draft a User Story, show ALL returned sections (with
        their citations) to the user and confirm which ones actually apply
        before writing story content from them. Citing more than one section
        for a single story is normal. Once confirmed, call kb_context_new with
        the confirmed refs to pin them for the ticket. Results come from the
        hub federation — unpublished local content never appears. `kinds`
        limits results to `kb` (Document), `ba` (Ticket) or `dev` (Code); omit
        for all."""

        def _run() -> str:
            hub = _hub()
            if hub is None:
                return HUB_DOWN
            try:
                outcome = search_detailed(
                    hub, query, tags=tags, budget=budget, kinds=kinds
                )
            except searchdb.IndexBusyError as exc:
                return str(exc)
            except sqlite3.DatabaseError as exc:
                if searchdb.classify_db_error(exc) != "client":
                    raise
                return f"search index rejected the query: {exc}"
            except (searchdb.TooManyTagsError, UnknownKindError) as exc:
                return str(exc)
            notes = "".join(outcome.notes)
            if not outcome.results:
                return notes + (
                    "No matching section found — try dropping tags or changing keywords."
                )
            note = stale_hub_note(hub) + notes + _ambiguity_note(outcome.results)
            return note + "\n\n".join(
                f"--- [{r.citation}] match={r.match_mode} ~{r.tokens}tk\n{r.content}"
                + (f"\nraw match: {r.snippet}" if r.snippet else "")
                for r in outcome.results
            )

        return await anyio.to_thread.run_sync(_run)

    @mcp.tool()
    @_canonical_docstring
    async def kb_get_section(
        doc: str, section: str, level: str = "l2", repo: str = ""
    ) -> str:
        """Fetch exactly one section: level 'l2' (condensed) or 'l3' (verbatim).
        `doc` accepts 'repo:doc' form; pass `repo` when the doc id alone is
        ambiguous across federation repos."""

        def _run() -> str:
            hub = _hub()
            if hub is None:
                return HUB_DOWN
            from strata_kb.query import AmbiguousDocError, InvalidLevelError

            try:
                result = get_section(hub, doc, section, level=level, repo=repo or None)
            except InvalidLevelError as exc:
                return str(exc)
            except AmbiguousDocError as exc:
                return str(exc)
            if result is None:
                known = _known_docs(hub)
                hint = f" Available docs: {known}." if known else ""
                return f"Not found: {doc} §{section}.{hint}"
            return (
                stale_hub_note(hub)
                + f"--- [{result.citation}] ~{result.tokens}tk\n{result.content}"
            )

        return await anyio.to_thread.run_sync(_run)

    @mcp.tool()
    @_canonical_docstring
    async def kb_context_new(refs: list[str], tags: list[str] | None = None) -> str:
        """Pin a kb-context citation block at the current KB commit, from 1+
        refs like 'hr-handbook §4.12'. Call this only after the user has
        confirmed which section(s) — out of everything kb_search returned —
        actually belong in the story; paste the returned block into the
        ticket. Citing 2-3 sections for one story is normal — pass every
        confirmed ref in one call."""

        def _run() -> str:
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

        return await anyio.to_thread.run_sync(_run)

    @mcp.tool()
    @_canonical_docstring
    async def kb_resolve(kb_context: str) -> str:
        """Accept a kb-context block (or the raw ticket text containing one); return the cited sections at their pinned version + freshness ok/stale/broken."""

        def _run() -> str:
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
            return stale_hub_note(hub) + render_resolved(results)

        return await anyio.to_thread.run_sync(_run)

    @mcp.tool()
    @_canonical_docstring
    async def kb_ticket_lint(
        ticket_markdown: str,
        ticket_id: str | None = None,
        mission_markdown: str | None = None,
    ) -> str:
        """Lint a draft ticket against the Definition of Ready: required
        structure, story format, ACs, Mermaid diagrams, kb-context refs
        resolving at their pinned version, and the optional
        '> Parent mission:' back-link. For the back-link's existence and
        backlog-membership checks pass `ticket_id` (the ticket file name
        without .md, e.g. M-checkout-US1) and, whenever the mission file
        exists locally, `mission_markdown` (its text; it wins over the hub's
        plan). Without `ticket_id` they are skipped with a note; with it, a
        mission neither passed nor on the hub is an error. Run this before handing the ticket to
        the BA; fix errors and re-run until PASS."""

        def _run() -> str:
            hub = _hub()
            if hub is None:
                return HUB_DOWN
            report = lint_ticket(
                ticket_markdown,
                hub,
                ticket_id=ticket_id or None,
                load_mission=_mission_loader(hub, mission_markdown),
            )
            return stale_hub_note(hub) + report.render()

        return await anyio.to_thread.run_sync(_run)

    @mcp.tool()
    @_canonical_docstring
    async def kb_ticket_check(
        ticket_markdown: str,
        mission_markdown: str | None = None,
        heading: str = "## Technical grounding",
    ) -> str:
        """SA grounding gate, the `kb ticket check` report: every id in
        '## Technical grounding' exists in the hub's -code document,
        columns/routes/commands/files match it, a moved `Grounded on:`
        revision is judged by its cited facts, `[NEW: D<n>]` points at a
        DECIDED row of the parent mission's Technology decisions, and Open
        decisions is empty. The mission is `mission_markdown` (pass the
        mission file's text whenever it exists locally — it wins over the
        hub), else the hub's plan. `heading="## Services & order"` checks a mission plan instead
        (decisions read from the same text). The -code document is read
        from the hub only — no local fallback."""

        def _run() -> str:
            from strata_kb import ticketcheck, ticketstale

            hub = _hub()
            if hub is None:
                return HUB_DOWN
            load_mission = _mission_loader(hub, mission_markdown)

            def load_doc(repo, doc):
                return ticketcheck.load_from_hub(hub.federation_dir, repo, doc)

            def load_drift(repo, doc, rev):
                ids = ticketstale.cited_ids(ticket_markdown)
                return ticketstale.drift_refs(hub, repo, doc, rev, ids) if ids else []

            def load_decisions(mission_id):
                text = load_mission(mission_id)
                if text is None:
                    return None
                return ticketcheck.parse_decisions(text, f"mission {mission_id}")

            report = ticketcheck.check(
                ticket_markdown,
                load_doc=load_doc,
                heading=heading,
                load_decisions=load_decisions,
                load_drift=load_drift,
            )
            return stale_hub_note(hub) + report.render("Grounding")

        return await anyio.to_thread.run_sync(_run)

    @mcp.tool()
    @_canonical_docstring
    async def kb_mission_next(repo: str | None = None) -> str:
        """Which story next, from the plans BA repos published to the hub
        (`<ba-repo>-plan`): every backlog story as done / ready / not ready
        (no published ticket) / blocked, then the next one to take. Done comes
        from the product repo's -svc history; a story with a published ticket
        is ready. `repo` limits it to one BA repo's plan. Same report as `kb
        mission next --from-hub`; a BA's unpublished missions/ and tickets/
        drafts need the CLI (`kb mission next` in the BA repo)."""

        def _run() -> str:
            from strata_kb import missionnext, planstatus

            hub = _hub()
            if hub is None:
                return HUB_DOWN
            results, notes = planstatus.next_from_hub(hub, repo or None)
            return stale_hub_note(hub) + missionnext.render(
                results, notes, planstatus.FROM_HUB_LABELS
            )

        return await anyio.to_thread.run_sync(_run)

    @mcp.tool()
    @_canonical_docstring
    async def kb_doctor_hub(
        kind: str,
        repo_id: str,
        remote_url: str = "",
        dir_name: str = "",
        kb_context: str | None = None,
    ) -> str:
        """For `kb doctor` in a child, ba or dev repo, which reaches the hub
        over MCP: the hub's side of the checks as JSON -- its strata-kb
        version (every repo on the hub must run the same), whether
        federation/<repo_id> is published and its content digest, the hub's
        `<repo_id>-code` section digests (dev), the registry's kind pin for
        this repo (`remote_url` and `dir_name` identify it as `kb publish`
        would), and the citation checks of `kb_context`. The CLI calls this;
        an agent wanting a health check runs `kb doctor` instead."""

        def _run() -> str:
            from strata_kb.doctor import remote

            hub = _hub()
            if hub is None:
                return json.dumps({"error": HUB_DOWN})
            return json.dumps(
                remote.hub_facts(
                    hub,
                    kind=kind,
                    repo_id=repo_id,
                    remote_url=remote_url,
                    dir_name=dir_name,
                    kb_context=kb_context,
                )
            )

        return await anyio.to_thread.run_sync(_run)

    return mcp


_LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")
_HOST_NAME_RE = re.compile(r"^[A-Za-z0-9.-]+$")


def transport_security_from_env():
    """FastMCP's DNS-rebinding check, its localhost allowlist plus each name in
    STRATA_KB_ALLOWED_HOSTS. Without it, /mcp behind a reverse proxy at a real
    name answers 421 Invalid Host header (#101)."""
    from mcp.server.transport_security import TransportSecuritySettings

    raw = os.environ.get("STRATA_KB_ALLOWED_HOSTS", "")
    names = [n.strip() for n in raw.split(",") if n.strip()]
    for name in names:
        if not _HOST_NAME_RE.fullmatch(name):
            raise SystemExit(
                f"STRATA_KB_ALLOWED_HOSTS entry '{name}' is not a host name — "
                "list bare names separated by commas, e.g. kb.example.com "
                "(no scheme, port or path)"
            )
    hosts = [f"{h}:*" for h in _LOCAL_HOSTS]
    origins = [f"http://{h}:*" for h in _LOCAL_HOSTS]
    for name in names:
        hosts += [name, f"{name}:*"]
        origins += [f"{s}://{name}{p}" for s in ("https", "http") for p in ("", ":*")]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


def create_http_app(config: ServerConfig, token: str):
    """One ASGI app: MCP (streamable HTTP) + REST /api + HTML /ui + /intake, token-guarded."""
    from strata_kb.intake import intake_config_from_env
    from strata_kb.web.app import create_app

    server = create_server(config)
    server.settings.transport_security = transport_security_from_env()
    return create_app(
        config,
        token,
        mcp_server=server,
        intake_cfg=intake_config_from_env(config.hub),
    )


def parse_args(argv: list[str] | None = None) -> ServerConfig:
    ap = argparse.ArgumentParser(
        prog="python -m strata_kb.mcp", description="Strata MCP server"
    )
    ap.add_argument(
        "--kb",
        type=Path,
        default=Path(".kb"),
        help="KB directory (only to find .kb/config.yaml)",
    )
    ap.add_argument(
        "--hub",
        default=None,
        help="kb-hub URL/path (default: env STRATA_KB_HUB, then .kb/config.yaml)",
    )
    ap.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default="stdio",
        help="stdio (default) or http (requires STRATA_KB_HTTP_TOKEN)",
    )
    ap.add_argument(
        "--host", default="127.0.0.1", help="Host to bind when --transport http"
    )
    ap.add_argument("--port", type=int, default=8321, help="Port when --transport http")
    args = ap.parse_args(argv)
    from strata_kb.config import HubConfigError, require_hub

    try:
        hub = require_hub(args.hub or os.environ.get("STRATA_KB_HUB", ""), args.kb)
    except HubConfigError as exc:
        raise SystemExit(str(exc)) from None
    return ServerConfig(
        kb_dir=args.kb,
        hub=hub,
        transport=args.transport,
        host=args.host,
        port=args.port,
    )


HTTP_TOKEN_MIN_LENGTH = 32
_PLACEHOLDER_TOKENS = frozenset({"change-me"})


def check_http_token(token: str) -> None:
    """Refuse an http-transport token the server cannot defend: the shipped
    `change-me` placeholder, anything shorter than 32 characters, and anything that is not printable ASCII -- a header
    token is compared as `str` and cannot carry non-ASCII reliably. The
    session cookie is `HMAC(token, issued)`, so a weak token is also
    brute-forceable offline from any copied cookie. No override: the server
    serves copyrighted documents."""
    how = (
        "run `kb docker-setup --force` to regenerate .env, or set "
        "STRATA_KB_HTTP_TOKEN to the output of "
        '`python -c "import secrets; print(secrets.token_hex(24))"`'
    )
    if token in _PLACEHOLDER_TOKENS:
        raise SystemExit(f"STRATA_KB_HTTP_TOKEN is the placeholder '{token}' — {how}")
    if len(token) < HTTP_TOKEN_MIN_LENGTH:
        raise SystemExit(
            f"STRATA_KB_HTTP_TOKEN is {len(token)} characters; at least "
            f"{HTTP_TOKEN_MIN_LENGTH} are required — {how}"
        )
    if not (token.isascii() and token.isprintable()) or " " in token:
        raise SystemExit(
            f"STRATA_KB_HTTP_TOKEN must be printable ASCII with no spaces — {how}"
        )


def main(argv: list[str] | None = None) -> None:
    from strata_kb.utf8io import force_utf8_streams

    force_utf8_streams()
    logging.basicConfig(level=logging.INFO)
    config = parse_args(argv)
    if config.transport == "http":
        token = os.environ.get("STRATA_KB_HTTP_TOKEN", "")
        if not token:
            raise SystemExit(
                "missing env STRATA_KB_HTTP_TOKEN — required for http transport "
                "(the documents are copyrighted; do not run HTTP without auth)"
            )
        check_http_token(token)
        import uvicorn

        from strata_kb.hub import start_auto_pull

        start_auto_pull(config.hub)
        uvicorn.run(
            create_http_app(config, token),
            host=config.host,
            port=config.port,
            # proxy_headers=False: uvicorn's own ProxyHeadersMiddleware sits
            # BELOW Starlette and would rewrite scope["client"] from
            # X-Forwarded-For using its own trust model (forwarded_allow_ips),
            # independent of STRATA_KB_TRUSTED_PROXIES and
            # serving.ratelimit.client_key. Two independent, differently-trusted
            # XFF implementations is the hazard -- client_key must stay the
            # single authority on X-Forwarded-For. Do not re-enable this.
            proxy_headers=False,
        )
        return
    create_server(config).run()


if __name__ == "__main__":
    main()
