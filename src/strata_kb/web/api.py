"""api — the read-only JSON routes under `/api/*`.

`build_routes` returns the Starlette routes (health, doc list, manifest,
section, search, questions, plan/next, registry/entry, resolve); `hub_handle`, `list_docs` and `load_manifest` are shared
with the web UI. Every read goes through the federation hub cache, and a hub
that cannot be resolved is reported as a 503 rather than an unhandled 500.
All routes but `health` are plain `def` so Starlette runs them off the event
loop.
"""

from __future__ import annotations

import dataclasses
import logging
import sqlite3

import yaml
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from strata_kb import gitio, models, searchdb
from strata_kb.kinds import UnknownKindError
from strata_kb.query import (
    AmbiguousDocError,
    InvalidLevelError,
    doc_dir,
    get_section,
    normalize_level,
    search,
    stale_hub_note,
)
from strata_kb.serving.config import ServerConfig, hub_serves_own_checkout
from strata_kb.web import bodycap

logger = logging.getLogger("strata_kb.web.api")

MAX_BUDGET = 20000

QA_NEEDS_HUB_DETAIL = "Q&A needs the shared hub server"

# A kb-context block is a few KB; this bounds what POST /api/resolve buffers.
MAX_RESOLVE_BODY = 64 * 1024

HUB_DOWN_DETAIL = "hub unreachable — the federation is the only read source"


def hub_handle(config: ServerConfig):
    from strata_kb.hub import resolve_hub

    # resolve_hub can raise gitio.GitError (hub.py's _discard_cache) when a
    # stale cache cannot be removed -- e.g. Windows holding a lock on
    # <cache>/.kb-work/search.sqlite3, and a serving web process is exactly
    # the kind of process that would be holding it open. Every call site
    # below already treats None as "hub unreachable" (HUB_DOWN); folding the
    # exception into that same None reuses the guard every route already
    # has, instead of letting it crash the request as an unhandled 500.
    # Same shape as mcp._hub.
    #
    # Log before returning None: a bare `except ... return None` would
    # discard the ONLY diagnostic -- a locked-cache request sweep at DEBUG
    # across all loggers would produce zero strata_kb.* records. In that
    # exact condition "no local cache" would be false on both halves (the
    # hub can be perfectly reachable, and the whole reason this raised is
    # that a cache DOES exist -- it is merely locked), which is why
    # HUB_DOWN_DETAIL does not assert it. resolve_hub's own clone/pull
    # failures already log at warning (see hub.py); this matches that shape,
    # as mcp._hub does.
    try:
        return resolve_hub(config.hub)
    except gitio.GitError as exc:
        logger.warning("hub cache unusable — serving as hub-unreachable: %s", exc)
        return None


def _error(status: int, error: str, detail: str = "") -> JSONResponse:
    return JSONResponse({"error": error, "detail": detail}, status_code=status)


def list_docs(config: ServerConfig) -> list[dict] | None:
    """None = hub unreachable (the caller returns 503)."""
    from strata_kb.federation import load_federation

    hub = hub_handle(config)
    if hub is None:
        return None
    return [
        {**d.model_dump(), "repo": repo.meta.repo_id, "kind": repo.kind}
        for repo in load_federation(hub.federation_dir)
        for d in repo.index.docs
    ]


def known_doc_ids(config: ServerConfig) -> list[str]:
    docs = list_docs(config) or []
    return [f"{d['repo']}:{d['id']}" for d in docs]


class SnapshotCorruptError(Exception):
    """A published snapshot's _manifest.yaml does not parse or validate.

    uidata._iter_manifests survives this (the doc simply does not list), so
    /ui keeps working. The doc routes raise it so app.py's handler can answer
    with a 503 (JSON or an error page) instead of a bare 500 with no shell.
    """

    def __init__(self, doc_id: str = "", detail: str = "") -> None:
        super().__init__(f"{doc_id}: {detail}")
        self.doc_id = doc_id
        self.detail = detail


def load_manifest(
    config: ServerConfig, doc_id: str, repo: str | None = None
) -> tuple[models.Manifest, str] | None:
    """Find a manifest in federation; raise AmbiguousDocError on doc-id collision."""
    from strata_kb.federation import load_federation

    hub = hub_handle(config)
    if hub is None or not models.DOC_ID_RE.match(doc_id):
        return None
    holders = [
        (r, folder)
        for r in load_federation(hub.federation_dir)
        if (repo is None or r.meta.repo_id == repo)
        and (folder := doc_dir(r.kb_dir, doc_id)) is not None
        and (folder / "_manifest.yaml").exists()
    ]
    if not holders:
        return None
    if len(holders) > 1:
        raise AmbiguousDocError(doc_id, [r.meta.repo_id for r, _ in holders])
    r, folder = holders[0]
    try:
        manifest = models.load_yaml_model(folder / "_manifest.yaml", models.Manifest)
    except (yaml.YAMLError, ValidationError, ValueError) as exc:
        raise SnapshotCorruptError(doc_id, " ".join(str(exc).split())) from exc
    return manifest, r.meta.repo_id


def build_routes(config: ServerConfig) -> list[Route]:
    # Every route but `health` is a plain `def`: Starlette runs it in its
    # threadpool. As `async def` they ran manifest parsing, hub resolution
    # (a git subprocess, a pull when the TTL expired) and file reads on the
    # event loop -- one slow page froze MCP and REST for every agent
    # (/api/health took 9 s while /ui rendered).
    async def health(request: Request) -> JSONResponse:
        # This route is auth-exempt (EXEMPT_PATHS, auth.py) so
        # TokenAuthMiddleware never calls the limiter for it -- an
        # auth-varying body here would let a caller compare guesses against
        # the token at full, unmetered speed (measured: 20/20 wrong guesses
        # -> 200, limiter never touched). So the route does not vary by auth
        # at all; unauthenticated liveness is satisfied by returning liveness
        # to everyone. hub_configured/hub_reachable stay available through
        # the authenticated /ui and `kb doctor`.
        return JSONResponse({"status": "ok"})

    def docs(request: Request) -> JSONResponse:
        listed = list_docs(config)
        if listed is None:
            return _error(503, "hub_unreachable", HUB_DOWN_DETAIL)
        return JSONResponse({"docs": listed})

    def doc_detail(request: Request) -> JSONResponse:
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
            return _error(
                404, "doc_not_found", f"unknown doc '{doc_id}'; known docs: {known}"
            )
        manifest, rid = found
        return JSONResponse(
            {
                "id": manifest.id,
                "title": manifest.title,
                "revision": manifest.revision,
                "repo": rid,
                "sections": [
                    {
                        "id": s.id,
                        "title": s.title,
                        "summary": s.summary,
                        "status": s.status,
                    }
                    for s in manifest.sections
                ],
            }
        )

    def section(request: Request) -> JSONResponse:
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
        except (yaml.YAMLError, ValidationError, ValueError) as exc:
            raise SnapshotCorruptError(doc_id, " ".join(str(exc).split())) from exc
        if result is None:
            known = ", ".join(known_doc_ids(config))
            return _error(
                404,
                "section_not_found",
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

    def api_search(request: Request) -> JSONResponse:
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
            results = search(
                hub,
                q,
                tags=tags,
                budget=budget,
                kinds=request.query_params.getlist("kind") or None,
            )
        except searchdb.TooManyTagsError as exc:
            return _error(400, "too_many_tags", str(exc))
        except UnknownKindError as exc:
            return _error(400, "unknown_kind", str(exc))
        except searchdb.IndexBusyError as exc:
            return _error(503, "index_busy", str(exc))
        except (yaml.YAMLError, ValidationError, ValueError) as exc:
            # No single doc_id here -- search() syncs every federated repo's
            # manifest before it ever searches (searchdb._sync_repo), so a
            # corrupt manifest anywhere in the federation surfaces here with
            # no way to know which one without re-walking it (not worth it).
            raise SnapshotCorruptError("", " ".join(str(exc).split())) from exc
        body = {
            "query": q,
            "results": [
                {
                    "doc_id": r.doc_id,
                    "section_id": r.section_id,
                    "title": r.title,
                    "score": r.score,
                    "citation": r.citation,
                    # content_tokens, not tokens: this response carries only
                    # r.content, never r.snippet -- reporting the budget-spend
                    # figure (tokens) here would describe text the caller
                    # never received.
                    "tokens": r.content_tokens,
                    "content": r.content,
                    "source": r.source,
                    "kind": r.kind,
                }
                for r in results
            ],
        }
        note = stale_hub_note(hub)
        if note:
            body["notes"] = [note]
        return JSONResponse(body)

    def questions(request: Request) -> JSONResponse:
        # Read-only like the Q&A UI pages: a missing qa.db is an empty list,
        # not a reason to create the store from a GET.
        from strata_kb import ticketqa
        from strata_kb.errors import KbError

        if not hub_serves_own_checkout(config):
            return _error(503, "qa_needs_hub_server", QA_NEEDS_HUB_DETAIL)
        hub = hub_handle(config)
        if hub is None:
            return _error(503, "hub_unreachable", HUB_DOWN_DETAIL)
        params = request.query_params
        status = params.get("status", "open")
        if status not in ticketqa.STATUSES:
            return _error(
                400,
                "bad_status",
                f"status must be one of {', '.join(ticketqa.STATUSES)}, not {status!r}",
            )
        db = ticketqa.qa_db_path(hub.root)
        try:
            if db.exists():
                rows = ticketqa.list_questions(
                    hub,
                    ticketqa.QaStore(db),
                    ticket_ref=params.get("ticket", ""),
                    repo=params.get("repo", ""),
                    status=status,
                )
            else:
                rows = []
        except KbError as exc:  # bad status (QaError) or a malformed ticket ref
            return _error(400, "bad_request", str(exc))
        except (sqlite3.Error, OSError):
            logger.exception("Q&A store error")
            return _error(500, "qa_store_error", "see hub log")
        return JSONResponse(
            {
                "questions": [
                    {
                        "id": q.id,
                        "repo": q.repo,
                        "ticket": q.ticket,
                        "state": state,
                        "question": q.question,
                        "asked_by": q.asked_by,
                        "asked_at": q.asked_at,
                        "blocks": q.blocks,
                        "answer": q.answer,
                        "answer_rev": q.answer_rev,
                    }
                    for q, state, _rev in rows
                ]
            }
        )

    def plan_next(request: Request) -> JSONResponse:
        from strata_kb import planstatus

        hub = hub_handle(config)
        if hub is None:
            return _error(503, "hub_unreachable", HUB_DOWN_DETAIL)
        stories, unparented, notes = planstatus.next_from_hub(
            hub, request.query_params.get("repo") or None
        )
        return JSONResponse(
            {
                "stories": [dataclasses.asdict(s) for s in stories],
                "unparented": [dataclasses.asdict(s) for s in unparented],
                "notes": notes,
            }
        )

    def registry_entry(request: Request) -> JSONResponse:
        # One repo's facts only: never the workflow pins or the whole registry.
        from strata_kb import federation

        repo_id = request.query_params.get("repo_id", "").strip()
        if not repo_id:
            return _error(
                400, "missing_repo_id", "query parameter 'repo_id' is required"
            )
        hub = hub_handle(config)
        if hub is None:
            return _error(503, "hub_unreachable", HUB_DOWN_DETAIL)
        try:
            registry = federation.load_registry(hub.federation_dir)
        except federation.RegistryError as exc:
            return _error(503, "registry_invalid", str(exc))
        entries = [e for k in registry.repos if (e := registry.resolve(k))]
        found = next((e for e in entries if e.repo_id == repo_id), None)
        if found is None:
            return _error(
                404, "repo_not_registered", f"'{repo_id}' is not in the hub registry"
            )
        return JSONResponse(
            {
                "repo_id": found.repo_id,
                "kind": found.kind,
                "auto_merge": found.auto_merge,
                "dev_repos": sum(1 for e in entries if e.kind == "dev"),
            }
        )

    def resolve_body(text: str) -> JSONResponse:
        from strata_kb import kbcontext, resolve

        hub = hub_handle(config)
        if hub is None:
            return _error(503, "hub_unreachable", HUB_DOWN_DETAIL)
        try:
            ctx = kbcontext.parse(text)
        except kbcontext.KBContextError as exc:
            return _error(400, "kb_context_error", str(exc))
        return JSONResponse(
            {
                "version": ctx.version,
                "results": [
                    {
                        "ref": str(r.ref),
                        "status": r.status,
                        "citation": r.citation,
                        "content": r.content,
                        "tokens": r.tokens,
                        "reason": r.reason,
                        "pinned_rev": r.pinned_rev,
                    }
                    for r in resolve.resolve_refs(hub, ctx)
                ],
            }
        )

    async def api_resolve(request: Request) -> JSONResponse:
        # async only to read the body; the parse and the git reads run in the
        # threadpool like every other route.
        too_big = _error(413, "body_too_large", f"max {MAX_RESOLVE_BODY} bytes")
        if int(request.headers.get("content-length") or 0) > MAX_RESOLVE_BODY:
            return too_big
        capped = Request(
            request.scope,
            bodycap.capped_receive(
                request, MAX_RESOLVE_BODY, lambda: OverflowError("body too large")
            ),
        )
        try:
            raw = await capped.body()
        except OverflowError:
            return too_big
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return _error(400, "bad_encoding", "body must be UTF-8 text")
        return await run_in_threadpool(resolve_body, text)

    return [
        Route("/api/health", health, methods=["GET"]),
        Route("/api/docs", docs, methods=["GET"]),
        Route("/api/docs/{doc}", doc_detail, methods=["GET"]),
        Route("/api/docs/{doc}/sections/{section}", section, methods=["GET"]),
        Route("/api/search", api_search, methods=["GET"]),
        Route("/api/questions", questions, methods=["GET"]),
        Route("/api/plan/next", plan_next, methods=["GET"]),
        Route("/api/registry/entry", registry_entry, methods=["GET"]),
        Route("/api/resolve", api_resolve, methods=["POST"]),
    ]
