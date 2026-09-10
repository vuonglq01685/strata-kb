from __future__ import annotations

import contextlib

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.routing import Mount, Route

from center_kb.mcp import ServerConfig
from center_kb.web import api, ui
from center_kb.web.auth import TokenAuthMiddleware


def create_app(config: ServerConfig, token: str, mcp_server=None, intake_cfg=None):
    """One ASGI app: / → /ui redirect, /api/*, /ui/*, /intake/* (optional), and
    /mcp (mounted FastMCP).

    mcp_server=None (unit tests): no /mcp branch, no lifespan requirement.
    intake_cfg=None (default): no /intake/* routes — publish intake disabled.
    """
    from center_kb import searchdb

    # F-C1, same reason as mcp.create_server. NOT in `lifespan`: line 36 leaves
    # lifespan None when mcp_server is None, so the API-only app would skip it.
    searchdb.warm_vec()

    async def root(request: Request) -> RedirectResponse:
        return RedirectResponse("/ui", status_code=302)

    routes: list = [Route("/", root, methods=["GET"])]
    routes += api.build_routes(config)
    routes += ui.build_routes(config, token)
    if intake_cfg is not None:
        from center_kb import intake as intake_mod
        from center_kb.web import intake_routes

        store = intake_mod.StatusStore(intake_cfg.status_path)
        routes += intake_routes.build_intake_routes(intake_cfg, store)

    lifespan = None
    if mcp_server is not None:
        mcp_app = mcp_server.streamable_http_app()

        @contextlib.asynccontextmanager
        async def lifespan(app):
            # FastMCP's session manager must run for the app's lifetime,
            # but Starlette does not run a mounted sub-app's lifespan —
            # so the parent enters it explicitly.
            async with mcp_server.session_manager.run():
                yield

        # Mounted last: /mcp requests fall through to the FastMCP app,
        # which serves them at its internal /mcp path.
        routes.append(Mount("/", app=mcp_app))

    app = Starlette(routes=routes, lifespan=lifespan)
    return TokenAuthMiddleware(app, token)
