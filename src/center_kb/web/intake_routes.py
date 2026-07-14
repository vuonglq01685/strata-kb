from __future__ import annotations

import json

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from center_kb import federation, ghapp, gitio, intake
from center_kb import hub as hub_mod


def _err(exc: intake.IntakeError) -> JSONResponse:
    return JSONResponse(
        {"error": "intake_rejected", "detail": exc.detail}, status_code=exc.status
    )


def build_intake_routes(
    cfg: intake.IntakeConfig, store: intake.StatusStore
) -> list[Route]:
    async def manifest(request: Request) -> JSONResponse:
        rid = request.query_params.get("repo_id", "")
        if not rid:
            return JSONResponse(
                {"error": "missing_repo_id", "detail": "query param repo_id required"},
                status_code=400,
            )
        try:
            files = await run_in_threadpool(intake.hub_manifest, cfg.hub_ref, rid)
        except intake.IntakeError as exc:
            return _err(exc)
        return JSONResponse({"files": files})

    async def status(request: Request) -> JSONResponse:
        rid = request.query_params.get("repo_id", "")
        commit = request.query_params.get("commit", "")
        found = store.get(rid, commit)
        if found is None:
            return JSONResponse({"state": "unknown"}, status_code=404)
        return JSONResponse(found)

    async def publish(request: Request) -> JSONResponse:
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse(
                {"error": "missing_token", "detail": "Authorization: Bearer <OIDC JWT> required"},
                status_code=401,
            )
        token = auth.removeprefix("Bearer ")
        try:
            claims = await run_in_threadpool(
                intake.verify_oidc, token, cfg.audience, cfg.key_resolver
            )

            def _load_registry():
                handle = hub_mod.resolve_hub(cfg.hub_ref)
                if handle is None:
                    raise intake.IntakeError(503, "hub unreachable")
                return federation.load_registry(handle.federation_dir)

            try:
                registry = await run_in_threadpool(_load_registry)
            except federation.RegistryError as exc:
                raise intake.IntakeError(503, str(exc))
            rid = intake.authorize(claims, registry)
            form = await request.form()
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
            archive = await upload.read()
        except intake.IntakeError as exc:
            return _err(exc)

        store.set(rid, source_commit, "processing")
        try:
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
        store.set(rid, source_commit, "done", pr_url=pr_url)
        return JSONResponse({"repo_id": rid, "pr_url": pr_url})

    return [
        Route("/intake/manifest", manifest, methods=["GET"]),
        Route("/intake/status", status, methods=["GET"]),
        Route("/intake/publish", publish, methods=["POST"]),
    ]
