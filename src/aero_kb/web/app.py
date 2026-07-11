from __future__ import annotations

import contextlib

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.routing import Mount, Route

from aero_kb.mcp import ServerConfig
from aero_kb.web import api, ui
from aero_kb.web.auth import TokenAuthMiddleware


def create_app(config: ServerConfig, token: str, mcp_server=None):
    """One ASGI app: / → /ui redirect, /api/*, /ui/*, and /mcp (mounted FastMCP).

    mcp_server=None (unit tests): no /mcp branch, no lifespan requirement.
    """

    async def root(request: Request) -> RedirectResponse:
        return RedirectResponse("/ui")

    routes: list = [Route("/", root, methods=["GET"])]
    routes += api.build_routes(config)
    routes += ui.build_routes(config, token)

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
