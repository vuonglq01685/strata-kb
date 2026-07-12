from __future__ import annotations

from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from center_kb import models
from center_kb.mcp import ServerConfig
from center_kb.query import get_section, search

MAX_BUDGET = 20000


def hub_handle(config: ServerConfig):
    """'' / None → None; otherwise resolve (None again if unreachable)."""
    if not config.hub:
        return None
    from center_kb.hub import resolve_hub

    return resolve_hub(config.hub)


def _error(status: int, error: str, detail: str = "") -> JSONResponse:
    return JSONResponse({"error": error, "detail": detail}, status_code=status)


def _index_docs(kb_dir: Path) -> list[models.IndexEntry]:
    index_path = kb_dir / "index.yaml"
    if not index_path.exists():
        return []
    return models.load_yaml_model(index_path, models.KBIndex).docs


def known_doc_ids(config: ServerConfig) -> list[str]:
    ids = [d.id for d in _index_docs(config.kb_dir)]
    hub = hub_handle(config)
    if hub is not None:
        seen = set(ids)
        ids += [d.id for d in _index_docs(hub.kb_dir) if d.id not in seen]
        seen.update(ids)
        from center_kb.federation import load_federation

        for repo in load_federation(hub.federation_dir):
            ids += [d.id for d in repo.index.docs if d.id not in seen]
            seen.update(d.id for d in repo.index.docs)
    return ids


def list_docs(config: ServerConfig, include_local: bool = True) -> list[dict]:
    """L0 across local + hub + federation, local wins on id collision.

    include_local=False → published sources only (hub + federation).
    """
    out = (
        [{**d.model_dump(), "source": "local"} for d in _index_docs(config.kb_dir)]
        if include_local
        else []
    )
    hub = hub_handle(config)
    if hub is None:
        return out
    seen = {d["id"] for d in out}
    for d in _index_docs(hub.kb_dir):
        if d.id not in seen:
            out.append({**d.model_dump(), "source": "hub"})
            seen.add(d.id)
    from center_kb.federation import load_federation

    for repo in load_federation(hub.federation_dir):
        rid = repo.meta.repo_id
        for d in repo.index.docs:
            out.append({**d.model_dump(), "source": f"remote:{rid}"})
    return out


def load_manifest(config: ServerConfig, doc_id: str) -> tuple[models.Manifest, str] | None:
    """Find a manifest for doc_id: local → hub → federation. Returns (manifest, repo)."""
    candidates: list[Path] = [config.kb_dir]
    hub = hub_handle(config)
    if hub is not None:
        candidates.append(hub.kb_dir)
    for base in candidates:
        mp = base / doc_id / "_manifest.yaml"
        if mp.exists():
            return models.load_yaml_model(mp, models.Manifest), ""
    if hub is not None:
        from center_kb.federation import load_federation

        for repo in load_federation(hub.federation_dir):
            m = repo.manifests.get(doc_id)
            if m is not None:
                return m, repo.meta.repo_id
    return None


def build_routes(config: ServerConfig) -> list[Route]:
    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "hub_configured": bool(config.hub)})

    async def docs(request: Request) -> JSONResponse:
        return JSONResponse({"docs": list_docs(config)})

    async def doc_detail(request: Request) -> JSONResponse:
        doc_id = request.path_params["doc"]
        found = load_manifest(config, doc_id)
        if found is None:
            known = ", ".join(known_doc_ids(config))
            return _error(404, "doc_not_found", f"unknown doc '{doc_id}'; known docs: {known}")
        manifest, repo = found
        return JSONResponse(
            {
                "id": manifest.id,
                "title": manifest.title,
                "revision": manifest.revision,
                "repo": repo,
                "sections": [
                    {"id": s.id, "title": s.title, "summary": s.summary, "status": s.status}
                    for s in manifest.sections
                ],
            }
        )

    async def section(request: Request) -> JSONResponse:
        doc_id = request.path_params["doc"]
        section_id = request.path_params["section"]
        level = request.query_params.get("level", "l2")
        if level not in ("l2", "l3"):
            return _error(400, "bad_level", f"level '{level}' is invalid — use 'l2' or 'l3'")
        result = get_section(config.kb_dir, doc_id, section_id, level=level, hub=hub_handle(config))
        if result is None:
            known = ", ".join(known_doc_ids(config))
            return _error(
                404, "section_not_found", f"{doc_id} §{section_id} not found; known docs: {known}"
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
        results = search(config.kb_dir, q, tags=tags, budget=budget, hub=hub_handle(config))
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
