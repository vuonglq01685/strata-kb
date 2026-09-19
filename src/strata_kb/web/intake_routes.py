from __future__ import annotations

import json
import logging

import anyio
from python_multipart.exceptions import FormParserError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from center_kb import federation, ghapp, gitio, intake
from center_kb.web.ratelimit import (
    INTAKE_MAX_ATTEMPTS,
    INTAKE_WINDOW_SECONDS,
    SlidingWindowLimiter,
    client_key,
)

logger = logging.getLogger("center_kb.web.intake")

_CHUNK = 64 * 1024
# F-D12 item 3: the receive-channel cap (_capped_receive, via
# _parse_capped_form) must bound the WHOLE multipart envelope -- boundaries,
# part headers, and the `meta` JSON field, not just the `archive` part -- so
# it needs headroom above max_tar_bytes rather than being set to it exactly.
# Measured worst case: 1000 `deletes` entries alone put `meta` at 43041
# bytes; 1 MiB is comfortably above that while still a tight bound on total
# bytes accepted off the wire. `read_capped` (below) is the archive-only cap
# and does NOT use this allowance.
_ENVELOPE_ALLOWANCE = 1024 * 1024

# HIGH-1 blast-radius containment (round 4): HIGH-1's own fix bounds a
# single publish's decoded-pax-header memory, but intake_publish as a whole
# still legitimately holds tens of MiB per call (a full DEFAULT_MAX_TAR
# member read into memory at once, worst measured case ~56 MiB above a bare
# process -- see the round-4 report's publish_mem_driver.py harness). This
# is NOT the HIGH-1 fix itself -- it is a cap on how many such calls may
# run at once, so N simultaneous publishes (legitimate concurrent CI runs,
# or an attacker opening several connections in parallel) cannot multiply
# that per-call cost into an unbounded total. 2: publish is already
# rate-limited per caller (SlidingWindowLimiter above) and is not a
# high-QPS path -- 2 gives a little real overlap for near-simultaneous
# legitimate CI publishes without letting the count grow with request
# volume. Sized together with the mem_limit added to docker-compose.yml /
# docker-compose-hub.yml this round -- see their comments for the number.
INTAKE_PUBLISH_MAX_CONCURRENCY = 2


def _err(exc: intake.IntakeError) -> JSONResponse:
    return JSONResponse(
        {"error": "intake_rejected", "detail": exc.detail}, status_code=exc.status
    )


async def read_capped(upload, max_bytes: int) -> bytes:
    """Read an upload in chunks, aborting at the cap.

    `await upload.read()` buffered the whole body first -- Starlette applies
    no size limit to a multipart file part -- so a 413 cost as much memory
    as the body an allowlisted child chose to send.
    """
    buf = bytearray()
    while True:
        chunk = await upload.read(_CHUNK)
        if not chunk:
            return bytes(buf)
        buf += chunk
        if len(buf) > max_bytes:
            raise intake.IntakeError(413, f"archive exceeds {max_bytes} bytes")


def _capped_receive(request: Request, max_body_bytes: int):
    """Wrap `request`'s ASGI receive channel so the BODY (the whole
    multipart envelope -- boundaries, part headers, and the `meta` JSON
    field, not just the `archive` part; see `_ENVELOPE_ALLOWANCE`) is
    refused past `max_body_bytes` before python_multipart ever spools it.

    Starlette's `max_part_size` bounds only the non-file branch of a
    multipart part (starlette/formparsers.py) -- a part is a "file" iff its
    Content-Disposition carries `filename=`, which the `archive` field
    always does -- so file-part bytes had no size check upstream of
    `read_capped`. This closes that gap one layer earlier: a
    `intake.IntakeError` raised from inside `receive` propagates out of
    `await form()` completely intact (neither formparsers.py's
    `except (MultiPartException, OSError)` nor requests.py's
    `except MultiPartException` catches a RuntimeError subclass), landing
    unchanged in the route's own `except intake.IntakeError` below --
    unlike a genuine parse failure, which `_parse_capped_form` has to
    translate back into an `IntakeError` itself (see there).
    """
    seen = 0

    async def receive():
        nonlocal seen
        message = await request.receive()
        if message["type"] == "http.request":
            seen += len(message.get("body", b""))
            if seen > max_body_bytes:
                raise intake.IntakeError(
                    413, f"request body exceeds {max_body_bytes} bytes"
                )
        return message

    return receive


async def _parse_capped_form(request: Request, max_body_bytes: int) -> Request:
    """Parse `request`'s multipart body through a receive channel capped at
    `max_body_bytes` (see `_capped_receive`) and return the capped `Request`
    (its `.form` is populated; caller reads fields/files from it and MUST
    `await capped.close()` once done -- see `publish`'s `finally`).

    A genuine parse failure (malformed multipart, an oversized part header,
    etc.) raises `starlette.formparsers.MultiPartException` from inside
    `form()` -- but under a real Starlette app (`web/app.py` always builds
    one via `Starlette(routes=...)`, so `"app"` is in `request.scope`),
    `starlette/requests.py` (around line 290) converts that to
    `starlette.exceptions.HTTPException(400)` before this function ever
    sees it. The `HTTPException` catch below is the one that actually fires
    in production; the bare `MultiPartException` catch is a fallback for a
    direct call against a scope with no `"app"` key (e.g. calling this
    function outside a mounted app), where Starlette leaves the exception
    unconverted.

    `python_multipart`'s `FormParserError` (base of `MultipartParseError`,
    e.g. an oversized part header such as a 100 KiB `filename`) is NOT
    intercepted by Starlette either way and is caught directly below --
    without this it surfaced as an uncaught 500.

    All three are translated to `IntakeError(...)` here so they render
    through `_err()` instead of Starlette's plain-text 400 or an uncaught
    500.
    """
    capped = Request(request.scope, _capped_receive(request, max_body_bytes))
    try:
        await capped.form()
    except HTTPException as exc:
        raise intake.IntakeError(exc.status_code, str(exc.detail)) from exc
    except (MultiPartException, FormParserError) as exc:
        raise intake.IntakeError(400, str(exc)) from exc
    return capped


def build_intake_routes(
    cfg: intake.IntakeConfig,
    store: intake.StatusStore,
    publish_limiter=None,
    publish_concurrency_limiter=None,
) -> list[Route]:
    limiter = publish_limiter or SlidingWindowLimiter(
        INTAKE_MAX_ATTEMPTS, INTAKE_WINDOW_SECONDS
    )
    # See INTAKE_PUBLISH_MAX_CONCURRENCY's comment above. Built fresh per
    # app instance (not module-level) for the same reason `limiter` is --
    # tests construct a new app per case and must not share state across
    # them; `publish_concurrency_limiter` is a test seam to shrink it to 1
    # for a deterministic "second publish blocks" pin.
    concurrency_limiter = publish_concurrency_limiter or anyio.CapacityLimiter(
        INTAKE_PUBLISH_MAX_CONCURRENCY
    )
    def _load_registry():
        # round-4 appended-section fix: this used to call hub_mod.resolve_hub
        # directly and only guard its `None` return -- resolve_hub can also
        # RAISE gitio.GitError (a stale/locked hub cache it cannot clean up
        # itself), which was previously unguarded here and reached
        # /intake/manifest and /intake/status as an uncaught 500. Reusing
        # intake._resolve_hub_or_503 (already the guard hub_manifest and
        # intake_publish use for the identical resolve_hub call) covers both
        # failure shapes with the one already-tested helper instead of a
        # second, drifting copy of the same guard.
        handle = intake._resolve_hub_or_503(cfg.hub_ref)
        try:
            return federation.load_registry(handle.federation_dir)
        except federation.RegistryError as exc:
            raise intake.IntakeError(503, str(exc))

    def _missing_token() -> JSONResponse:
        return JSONResponse(
            {"error": "missing_token", "detail": "Authorization: Bearer <OIDC JWT> required"},
            status_code=401,
        )

    async def _caller_rid(token: str) -> tuple[str, dict]:
        """OIDC claims -> the caller's registered repo-id (registry decides)."""
        claims = await run_in_threadpool(
            intake.verify_oidc, token, cfg.audience, cfg.key_resolver
        )
        registry = await run_in_threadpool(_load_registry)
        return intake.authorize(claims, registry), claims

    async def manifest(request: Request) -> JSONResponse:
        rid = request.query_params.get("repo_id", "")
        if not rid:
            return JSONResponse(
                {"error": "missing_repo_id", "detail": "query param repo_id required"},
                status_code=400,
            )
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return _missing_token()
        try:
            caller, _ = await _caller_rid(auth.removeprefix("Bearer "))
            if rid != caller:
                raise intake.IntakeError(
                    403,
                    f"repo_id '{rid}' does not match the caller's registered repo-id",
                )
            files = await run_in_threadpool(intake.hub_manifest, cfg.hub_ref, rid)
        except intake.IntakeError as exc:
            return _err(exc)
        return JSONResponse({"files": files})

    async def status(request: Request) -> JSONResponse:
        # LOW-1: this used to have no auth check at all -- repo_id and
        # commit are both public (repo_id lives in the hub's own
        # federation/registry.yaml; commit is a public git SHA), but
        # `detail` echoes internal text (e.g. raw `git` stderr from
        # gitio.GitError, including container filesystem paths and branch
        # names -- see the `except (gitio.GitError, ghapp.GHAppError)`
        # branch below) to ANY unauthenticated caller for ANY repo-id. This
        # is the authorization boundary `manifest` already enforces
        # (`_caller_rid` + `rid == caller`); status gets the same one.
        rid = request.query_params.get("repo_id", "")
        commit = request.query_params.get("commit", "")
        if not rid:
            return JSONResponse(
                {"error": "missing_repo_id", "detail": "query param repo_id required"},
                status_code=400,
            )
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return _missing_token()
        try:
            caller, _ = await _caller_rid(auth.removeprefix("Bearer "))
            if rid != caller:
                raise intake.IntakeError(
                    403,
                    f"repo_id '{rid}' does not match the caller's registered repo-id",
                )
        except intake.IntakeError as exc:
            return _err(exc)
        found = store.get(rid, commit)
        if found is None:
            return JSONResponse({"state": "unknown"}, status_code=404)
        return JSONResponse(found)

    async def publish(request: Request) -> JSONResponse:
        client_ip = client_key(request, cfg.trusted_proxies)
        if not limiter.allow(client_ip):
            logger.warning("intake publish rate-limited for %s", client_ip)
            return JSONResponse(
                {"error": "rate_limited", "detail": "too many publish attempts"},
                status_code=429,
            )
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            logger.warning("intake publish without token from %s", client_ip)
            return _missing_token()
        token = auth.removeprefix("Bearer ")
        capped = None
        # F-D12 item 3: the body cap bounds the WHOLE multipart envelope
        # (boundaries, part headers, the `meta` JSON field), not just the
        # archive -- it needs headroom above max_tar_bytes, or an archive of
        # exactly the documented limit no longer fits inside its own
        # envelope. read_capped (below) applies max_tar_bytes to the
        # archive part alone and is unaffected by this allowance.
        max_body_bytes = cfg.max_tar_bytes + _ENVELOPE_ALLOWANCE
        try:
            # Check the declared size before doing any auth/network work --
            # OIDC verification and multipart parsing are both wasted (and,
            # for parsing, unbounded -- see read_capped's docstring) if the
            # caller has already told us the body is oversized. Compared
            # against max_body_bytes (not max_tar_bytes): Content-Length
            # here is the declared size of the WHOLE request body, the same
            # quantity _capped_receive bounds below -- comparing it to the
            # archive-only cap would reject a legitimate request whose
            # declared body (archive + multipart overhead) exceeds
            # max_tar_bytes even though its archive does not.
            declared = request.headers.get("content-length", "")
            try:
                declared_len = int(declared) if declared else None
            except ValueError:
                # Not a base-10 integer per RFC 9110 -- e.g. a stray '+'/
                # whitespace, or a Unicode digit str.isdigit() would accept
                # but int() rejects. Skip the pre-check rather than 500;
                # read_capped and the capped receive below still bound the
                # actual body regardless of what Content-Length claimed.
                declared_len = None
            if declared_len is not None and declared_len > max_body_bytes:
                raise intake.IntakeError(
                    413, f"request body exceeds {max_body_bytes} bytes"
                )
            rid, claims = await _caller_rid(token)
            capped = await _parse_capped_form(request, max_body_bytes)
            form = await capped.form()
            try:
                meta = json.loads(form["meta"])
                source_commit = str(meta["source_commit"])
                deletes = [str(d) for d in meta.get("deletes", [])]
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                raise intake.IntakeError(
                    400, "field 'meta' must be JSON with source_commit (+ optional deletes)"
                )
            upload = form.get("archive")
            if upload is None:
                raise intake.IntakeError(400, "multipart field 'archive' required")
            if not hasattr(upload, "read"):
                # plain text form field, not an UploadFile
                raise intake.IntakeError(
                    400, "multipart field 'archive' must be a file upload"
                )
            archive = await read_capped(upload, cfg.max_tar_bytes)
        except intake.IntakeError as exc:
            if exc.status in (401, 403):
                logger.warning(
                    "intake publish rejected (%s) from %s: %s",
                    exc.status, client_ip, exc.detail,
                )
            return _err(exc)
        finally:
            # Deterministic cleanup of the capped request's spooled upload(s)
            # rather than waiting on GC. A no-op when `capped` was never
            # assigned (rejected before parsing) or its form never parsed
            # (the underlying SpooledTemporaryFile in that case belongs to a
            # now-unreachable MultiPartParser instance, outside what
            # Request.close() can reach either way).
            if capped is not None:
                await capped.close()

        store.set(rid, source_commit, "processing")
        try:
            try:
                # HIGH-1 blast-radius containment: brackets exactly the
                # memory-heavy phase (extraction, hashing, worktree write --
                # everything intake_publish itself does), not the multipart
                # read/parse above, which is already bounded per-request by
                # max_tar_bytes regardless of concurrency.
                async with concurrency_limiter:
                    pr_url = await run_in_threadpool(
                        intake.intake_publish,
                        cfg, rid, source_commit, claims["repository"], deletes, archive,
                    )
            except intake.IntakeError as exc:
                store.set(rid, source_commit, "error", detail=exc.detail)
                return _err(exc)
            except (gitio.GitError, ghapp.GHAppError) as exc:
                store.set(rid, source_commit, "error", detail=str(exc))
                return JSONResponse(
                    {"error": "publish_failed", "detail": str(exc)}, status_code=502
                )
            except Exception:
                # MEDIUM-2 backstop: intake_publish's own extraction step now
                # translates every OS/parse error it can see into IntakeError,
                # but this is the terminal-state guarantee itself, not a bet
                # that every future failure mode was anticipated -- an
                # unexpected crash here must never leave the job at
                # "processing" forever (no other code path ever moves it out
                # of that state), so this is a deliberately broad backstop.
                # The traceback is logged, never returned -- spec: no traceback
                # reaches a user.
                logger.exception(
                    "intake publish crashed unexpectedly for %s @ %s", rid, source_commit
                )
                store.set(
                    rid, source_commit, "error",
                    detail="internal error -- see server logs",
                )
                return JSONResponse(
                    {"error": "publish_failed", "detail": "internal error -- see server logs"},
                    status_code=500,
                )
            store.set(rid, source_commit, "done", pr_url=pr_url)
            return JSONResponse({"repo_id": rid, "pr_url": pr_url})
        finally:
            # N-6: `except Exception` above does not catch a BaseException
            # -- notably asyncio.CancelledError, raised into this coroutine
            # when the client disconnects mid-publish (Python 3.8+ makes it
            # a BaseException, not an Exception, precisely so `except
            # Exception` does not swallow cancellation). Such an exception
            # unwinds past every `except` clause above without ever
            # reaching a `store.set(..., "error"/"done", ...)` call, which
            # is MEDIUM-2's exact symptom -- /intake/status stuck at
            # "processing" forever -- by a different route than an
            # unanticipated extraction failure. This promotes any job this
            # coroutine leaves at "processing", however it exits, to
            # "error" -- and is a no-op on every path above, since each of
            # them already sets a terminal state before returning.
            current = store.get(rid, source_commit)
            if current is not None and current.get("state") == "processing":
                store.set(
                    rid, source_commit, "error",
                    detail="publish did not complete",
                )

    return [
        Route("/intake/manifest", manifest, methods=["GET"]),
        Route("/intake/status", status, methods=["GET"]),
        Route("/intake/publish", publish, methods=["POST"]),
    ]
