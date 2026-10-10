"""A receive channel that refuses a request body past a byte cap.

A `Content-Length` check alone does not bound a body: a chunked request
carries no `Content-Length`, and Starlette's own form limits are per field
(1 MiB × 1000 fields by default). Wrapping `receive` bounds the bytes taken
off the wire before any parser buffers them. Shared by the intake upload
(`web/intake_routes.py`) and `POST /ui/login` (2026-10-10 review §5.2 #2).
"""
from __future__ import annotations

from collections.abc import Callable

from starlette.requests import Request


def capped_receive(
    request: Request, max_bytes: int, overflow: Callable[[], Exception]
):
    """Wrap `request`'s ASGI receive channel. Past `max_bytes` of body,
    raise `overflow()`.

    The exception raised from inside `receive` propagates out of
    `await request.form()` intact. Neither formparsers.py's
    `except (MultiPartException, OSError)` nor requests.py's
    `except MultiPartException` catches it, so it must not subclass either.
    The caller catches its own exception type around `form()`.
    """
    seen = 0

    async def receive():
        nonlocal seen
        message = await request.receive()
        if message["type"] == "http.request":
            seen += len(message.get("body", b""))
            if seen > max_bytes:
                raise overflow()
        return message

    return receive
