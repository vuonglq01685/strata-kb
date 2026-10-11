"""app — assembles the one ASGI app the shared HTTP server runs.

`create_app` (called by `mcp.create_http_app`) builds the route table (`/`
redirect, `/api/*`, `/ui/*`, the optional `/intake/*`, and FastMCP mounted
last at `/mcp`), installs the corrupt-snapshot error handler, and wraps
everything in token auth and then security headers. The headers middleware
sits outside auth so the auth layer's own redirects and 401/429 responses
carry the headers too.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Mount, Route

from strata_kb.serving.auth import TokenAuthMiddleware
from strata_kb.serving.config import ServerConfig
from strata_kb.web import api, planui, ui
from strata_kb.web.headers import SecurityHeadersMiddleware

logger = logging.getLogger("strata_kb.web.app")


def create_app(config: ServerConfig, token: str, mcp_server=None, intake_cfg=None):
    """One ASGI app: / → /ui redirect, /api/*, /ui/*, /intake/* (optional), and
    /mcp (mounted FastMCP).

    mcp_server=None (unit tests): no /mcp branch, no lifespan requirement.
    intake_cfg=None (default): no /intake/* routes — publish intake disabled.
    """
    from strata_kb import searchdb
    from strata_kb.serving.ratelimit import (
        LOGIN_MAX_ATTEMPTS,
        LOGIN_WINDOW_SECONDS,
        SlidingWindowLimiter,
        trusted_proxies_from_env,
    )

    # Import sqlite_vec/numpy now, off the event loop: doing it inside a request
    # handler that runs on the loop thread deadlocks (see searchdb.warm_vec).
    # NOT in `lifespan`: `lifespan` stays None when mcp_server is None, so the
    # API-only app would skip it.
    searchdb.warm_vec()

    # One bucket for "a failed attempt at the shared secret", wherever it
    # arrives. Read once here rather than inside build_routes, so the
    # middleware and the login form cannot disagree about the proxy count.
    trusted_proxies = trusted_proxies_from_env()
    auth_limiter = SlidingWindowLimiter(LOGIN_MAX_ATTEMPTS, LOGIN_WINDOW_SECONDS)

    async def root(request: Request) -> RedirectResponse:
        return RedirectResponse("/ui", status_code=302)

    routes: list = [Route("/", root, methods=["GET"])]
    routes += api.build_routes(config)
    routes += ui.build_routes(
        config, token, login_limiter=auth_limiter, trusted_proxies=trusted_proxies
    )
    # planui builds on ui's page helpers, so it is wired here, not inside ui.
    routes += planui.plan_routes(config)
    if intake_cfg is not None:
        from strata_kb import gitio
        from strata_kb import hub as hub_mod
        from strata_kb import intake as intake_mod
        from strata_kb.web import intake_routes

        # resolve_hub can raise gitio.GitError (a stale/locked hub cache it
        # cannot clean up itself). Unguarded, that would crash create_app
        # itself, so the SERVER WOULD FAIL TO BOOT over an intake-only cache
        # problem, taking /api, /ui and /mcp down with it even though none of
        # them touch this cache. Start degraded, not refuse to start -- the
        # routes built below already guard every per-request resolve_hub call
        # of their own (_load_registry, intake_publish, both via
        # intake._resolve_hub_or_503) into a clean 503, so this one-time
        # boot-time diagnostic has nothing a live request cannot recover on
        # its own; refusing to start would make the outage strictly worse
        # by also taking down the unrelated /api, /ui and /mcp routes.
        try:
            handle = hub_mod.resolve_hub(intake_cfg.hub_ref)
        except gitio.GitError as exc:
            logger.warning(
                "intake hub cache unusable at startup (%s) -- /intake/* "
                "will serve 503 until it recovers; /api, /ui and /mcp are "
                "unaffected",
                exc,
            )
            handle = None
        if handle is not None:
            for line in intake_mod.check_serving_clone(handle):
                logger.warning("%s", line)

        store = intake_mod.StatusStore(intake_cfg.status_path)
        routes += intake_routes.build_intake_routes(intake_cfg, store)

    lifespan: Callable[[Starlette], AbstractAsyncContextManager[None]] | None = None
    if mcp_server is not None:
        mcp_app = mcp_server.streamable_http_app()

        @contextlib.asynccontextmanager
        async def mcp_lifespan(app: Starlette) -> AsyncIterator[None]:
            # FastMCP's session manager must run for the app's lifetime,
            # but Starlette does not run a mounted sub-app's lifespan —
            # so the parent enters it explicitly.
            async with mcp_server.session_manager.run():
                yield

        lifespan = mcp_lifespan

        # Mounted last: /mcp requests fall through to the FastMCP app,
        # which serves them at its internal /mcp path.
        routes.append(Mount("/", app=mcp_app))

    async def snapshot_corrupt(request: Request, exc: Exception):
        # Registered for api.SnapshotCorruptError only; Starlette types every
        # handler as taking any Exception.
        doc_id = exc.doc_id if isinstance(exc, api.SnapshotCorruptError) else None
        logger.warning("corrupt published snapshot: %s", exc)
        if request.url.path.startswith("/api"):
            json_detail = (
                f"published snapshot for '{doc_id}' is corrupt"
                if doc_id
                else "a published snapshot is corrupt"
            )
            return JSONResponse(
                {"error": "snapshot_corrupt", "detail": json_detail},
                status_code=503,
            )
        html_detail = (
            f"The published snapshot for '{doc_id}' is corrupt. "
            "Re-publish it from the owning repo."
            if doc_id
            else "A published snapshot is corrupt. Re-publish it from the owning repo."
        )
        return ui.render_error_page(
            config,
            status=503,
            title="Document unavailable",
            detail=html_detail,
        )

    app = Starlette(
        routes=routes,
        lifespan=lifespan,
        exception_handlers={api.SnapshotCorruptError: snapshot_corrupt},
    )
    return SecurityHeadersMiddleware(
        TokenAuthMiddleware(
            app, token, limiter=auth_limiter, trusted_proxies=trusted_proxies
        )
    )
