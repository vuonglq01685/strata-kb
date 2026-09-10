from __future__ import annotations

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from center_kb import models, searchdb
from center_kb.mcp import ServerConfig
from center_kb.query import (
    AmbiguousDocError,
    InvalidLevelError,
    get_section,
    normalize_level,
    search,
)

MAX_BUDGET = 20000

HUB_DOWN_DETAIL = (
    "hub unreachable and no local cache — the federation is the only read source"
)


def hub_handle(config: ServerConfig):
    from center_kb.hub import resolve_hub

    return resolve_hub(config.hub)


def _error(status: int, error: str, detail: str = "") -> JSONResponse:
    return JSONResponse({"error": error, "detail": detail}, status_code=status)


def list_docs(config: ServerConfig) -> list[dict] | None:
    """None = hub unreachable (the caller returns 503)."""
    from center_kb.federation import load_federation

    hub = hub_handle(config)
    if hub is None:
        return None
    return [
        {**d.model_dump(), "repo": repo.meta.repo_id}
        for repo in load_federation(hub.federation_dir)
        for d in repo.index.docs
    ]


def known_doc_ids(config: ServerConfig) -> list[str]:
    docs = list_docs(config) or []
    return [f"{d['repo']}:{d['id']}" for d in docs]


def load_manifest(
    config: ServerConfig, doc_id: str, repo: str | None = None
) -> tuple[models.Manifest, str] | None:
    """Find a manifest in federation; raise AmbiguousDocError on doc-id collision."""
    from center_kb.federation import load_federation

    hub = hub_handle(config)
    if hub is None:
        return None
    holders = [
        r for r in load_federation(hub.federation_dir)
        if (repo is None or r.meta.repo_id == repo)
        and (r.kb_dir / doc_id / "_manifest.yaml").exists()
    ]
    if not holders:
        return None
    if len(holders) > 1:
        raise AmbiguousDocError(doc_id, [r.meta.repo_id for r in holders])
    r = holders[0]
    manifest = models.load_yaml_model(
        r.kb_dir / doc_id / "_manifest.yaml", models.Manifest
    )
    return manifest, r.meta.repo_id


def build_routes(config: ServerConfig) -> list[Route]:
    async def health(request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "hub_configured": bool(config.hub),
                "hub_reachable": hub_handle(config) is not None,
            }
        )

    async def docs(request: Request) -> JSONResponse:
        listed = list_docs(config)
        if listed is None:
            return _error(503, "hub_unreachable", HUB_DOWN_DETAIL)
        return JSONResponse({"docs": listed})

    async def doc_detail(request: Request) -> JSONResponse:
        doc_id = request.path_params["doc"]
        repo = request.query_params.get("repo") or None
        if hub_handle(config) is None:
            return _error(503, "hub_unreachable", HUB_DOWN_DETAIL)
        try:
            found = load_manifest(config, doc_id, repo=repo)
        except AmbiguousDocError as exc:
            return _error(400, "ambiguous_doc", str(exc))
        if found is None:
            known = ", ".join(known_doc_ids(config))
            return _error(404, "doc_not_found", f"unknown doc '{doc_id}'; known docs: {known}")
        manifest, rid = found
        return JSONResponse(
            {
                "id": manifest.id,
                "title": manifest.title,
                "revision": manifest.revision,
                "repo": rid,
                "sections": [
                    {"id": s.id, "title": s.title, "summary": s.summary, "status": s.status}
                    for s in manifest.sections
                ],
            }
        )

    async def section(request: Request) -> JSONResponse:
        doc_id = request.path_params["doc"]
        section_id = request.path_params["section"]
        repo = request.query_params.get("repo") or None
        level = request.query_params.get("level", "l2")
        try:
            level = normalize_level(level)
        except InvalidLevelError as exc:
            return _error(400, "bad_level", str(exc))
        hub = hub_handle(config)
        if hub is None:
            return _error(503, "hub_unreachable", HUB_DOWN_DETAIL)
        try:
            result = get_section(hub, doc_id, section_id, level=level, repo=repo)
        except AmbiguousDocError as exc:
            return _error(400, "ambiguous_doc", str(exc))
        if result is None:
            known = ", ".join(known_doc_ids(config))
            return _error(
                404, "section_not_found",
                f"{doc_id} §{section_id} not found; known docs: {known}",
            )
        return JSONResponse(
            {
                "doc_id": result.doc_id,
                "section_id": result.section_id,
                "title": result.title,
                "citation": result.citation,
                "tokens": result.tokens,
                "level": level,
                "content": result.content,
                "source": result.source,
            }
        )

    async def api_search(request: Request) -> JSONResponse:
        q = request.query_params.get("q", "").strip()
        if not q:
            return _error(400, "missing_query", "query parameter 'q' is required")
        raw_tags = request.query_params.get("tags", "")
        tags = [t.strip() for t in raw_tags.split(",") if t.strip()] or None
        try:
            budget = int(request.query_params.get("budget", "2000"))
        except ValueError:
            return _error(400, "bad_budget", "'budget' must be an integer")
        budget = max(1, min(budget, MAX_BUDGET))
        hub = hub_handle(config)
        if hub is None:
            return _error(503, "hub_unreachable", HUB_DOWN_DETAIL)
        try:
            results = await run_in_threadpool(
                search, hub, q, tags=tags, budget=budget
            )
        except searchdb.TooManyTagsError as exc:
            return _error(400, "too_many_tags", str(exc))
        except searchdb.IndexBusyError as exc:
            return _error(503, "index_busy", str(exc))
        return JSONResponse(
            {
                "query": q,
                "results": [
                    {
                        "doc_id": r.doc_id,
                        "section_id": r.section_id,
                        "title": r.title,
                        "score": r.score,
                        "citation": r.citation,
                        "tokens": r.tokens,
                        "content": r.content,
                        "source": r.source,
                    }
                    for r in results
                ],
            }
        )

    return [
        Route("/api/health", health, methods=["GET"]),
        Route("/api/docs", docs, methods=["GET"]),
        Route("/api/docs/{doc}", doc_detail, methods=["GET"]),
        Route("/api/docs/{doc}/sections/{section}", section, methods=["GET"]),
        Route("/api/search", api_search, methods=["GET"]),
    ]
