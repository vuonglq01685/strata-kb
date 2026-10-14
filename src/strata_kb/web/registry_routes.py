"""registry_routes -- the admin-only Registry page (`/ui/registry*`).

The registry (`federation/registry.yaml`) is the hub's publish allowlist. This
page edits it through a commit on the hub's default branch: every POST takes
`registry_lock`, pulls the hub checkout, reads the registry from it, applies
the one change (`registryedit`), commits in a throwaway worktree and pushes
non-forced. A push that loses a race is shown as "the hub moved, reload and
retry" -- never overwritten.

Authorization is checked here, on every route, server-side: anonymous browsers
are already redirected to the login by the auth middleware; a bearer request
(no account) or a non-admin cookie gets 403. Every POST also carries a CSRF
token derived from the session cookie.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from strata_kb import federation, ghapp, gitio, kinds, registryedit
from strata_kb import hub as hub_mod
from strata_kb.errors import KbError
from strata_kb.models import Registry
from strata_kb.serving.accounts import User
from strata_kb.serving.auth import COOKIE_NAME, SessionAuth, current_user
from strata_kb.serving.config import ServerConfig
from strata_kb.web import api, bodycap
from strata_kb.web.ui import NO_STORE, _render_page, render_error_page

if TYPE_CHECKING:
    # intake is a heavy module; only the real push needs it at run time.
    from strata_kb.intake import IntakeConfig

logger = logging.getLogger("strata_kb.web.registry")

# One admin edit at a time: the whole pull-read-modify-commit-push. Deliberately
# not intake's _hub_write_lock -- commit_registry takes that one itself for its
# worktree bookkeeping, and holding it here would deadlock.
registry_lock = threading.Lock()

REGISTRY_REL = f"federation/{federation.REGISTRY_NAME}"
HISTORY_LIMIT = 10
# Four short fields and a csrf token; 16 KiB is generous.
MAX_BODY = 16 * 1024
# git's wording when the remote tip moved under us (vs. a hook/branch-protection
# "remote rejected", which is a different problem).
_STALE_MARKERS = ("fetch first", "non-fast-forward", "stale info")
STALE_MESSAGE = "The hub moved while you were editing. Reload this page and retry."
NOTICES = {
    "added": "Repository added.",
    "removed": "Repository removed.",
    "auto-merge-on": "Auto-merge turned on.",
    "auto-merge-off": "Auto-merge turned off.",
    "nochange": "No change.",
}
# Suffix on a notice code: the push landed but the post-push pull failed.
STALE_SUFFIX = "-stale"
STALE_PULL_NOTICE = (
    "Pushed, but this hub's checkout did not refresh; "
    "intake uses the old registry until it does."
)


def csrf_token(key: bytes, cookie_value: str) -> str:
    """Per-session CSRF value: HMAC of the session cookie under the session
    key with a fixed label, so it dies with the session and cannot be
    computed from the cookie alone."""
    msg = b"csrf\0" + cookie_value.encode("utf-8", "surrogatepass")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def _csrf_ok(session: SessionAuth, request: Request, submitted: object) -> bool:
    expected = csrf_token(session.key, request.cookies.get(COOKIE_NAME, ""))
    return hmac.compare_digest(
        str(submitted).encode("utf-8", "surrogatepass"), expected.encode("ascii")
    )


class _Fail(KbError):
    """A refused edit: HTTP status and a user-facing message."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _first_line(text: str, limit: int = 300) -> str:
    # redact_url: a remote URL in the text may carry credentials.
    return (gitio.redact_url(text).strip().splitlines() or [""])[0][:limit]


def _read_only_reason(
    intake_cfg: IntakeConfig | None, hub_root: Path | None
) -> str | None:
    if hub_root is None:
        return "The hub checkout is not available, so nothing can be shown or edited."
    if intake_cfg is None:
        return (
            "Read-only: publish intake is not configured on this hub (set "
            "STRATA_KB_GH_APP_ID, STRATA_KB_GH_APP_KEY and "
            "STRATA_KB_INTAKE_AUDIENCE), so it has no GitHub App identity to "
            "push registry changes with."
        )
    if not gitio.has_remote(hub_root):
        return (
            "Read-only: the hub checkout has no GitHub remote ('origin'), so "
            "registry changes cannot be pushed."
        )
    return None


def _entries(reg: Registry) -> list[dict]:
    rows = []
    for key in reg.repos:
        entry = reg.resolve(key)
        if entry is not None:
            rows.append(
                {
                    "repo": key,
                    "repo_id": entry.repo_id,
                    "kind": entry.kind,
                    "workflow": entry.workflow,
                    "auto_merge": entry.auto_merge,
                }
            )
    return rows


def _history(hub_root: Path) -> list[dict]:
    try:
        branch = gitio.default_branch(hub_root)
    except gitio.GitError:
        return []
    proc = gitio._run(
        hub_root,
        "log",
        f"-{HISTORY_LIMIT}",
        "--format=%h%x1f%cs%x1f%s",
        branch,
        "--",
        REGISTRY_REL,
    )
    if proc.returncode != 0:
        return []
    rows = []
    for line in proc.stdout.splitlines():
        sha, date, subject = (line.split("\x1f") + ["", ""])[:3]
        rows.append({"sha": sha, "date": date, "subject": subject})
    return rows


def _pull_best_effort(hub: str) -> bool:
    """True when the pull ran; False (logged) when it failed."""
    try:
        hub_mod.pull_once(hub)
        return True
    except Exception:  # noqa: BLE001 -- pull_once can also raise sqlite3.Error; after a landed push that must not become a 500
        # Before an edit the push fails cleanly if the base is stale; after one
        # the change has already landed. Either way: log, never raise.
        logger.warning("registry: hub pull failed", exc_info=True)
        return False


def _federation_dirs(federation_dir: Path) -> list[str]:
    if not federation_dir.is_dir():
        return []
    return [p.name for p in federation_dir.iterdir() if p.is_dir()]


def _make_real_push(hub_root: Path, cfg: IntakeConfig) -> Callable[[Path, str], None]:
    def push(work: Path, branch: str) -> None:
        from strata_kb.intake import INTAKE_GIT_TIMEOUT_SECONDS

        full = ghapp.repo_full_from_url(gitio.remote_url(hub_root))
        token = ghapp.mint_installation_token(
            cfg.creds, full, http=cfg.http or ghapp._default_http
        )
        url = (
            f"https://github.com/{full}.git"
            if cfg.push_via_token_url
            else gitio.remote_url(hub_root)
        )
        gitio.push_head_with_token(
            work, url, token, branch, timeout=INTAKE_GIT_TIMEOUT_SECONDS
        )

    return push


def build_registry_routes(
    config: ServerConfig,
    intake_cfg: IntakeConfig | None,
    session: SessionAuth,
    push: Callable[[Path, str], None] | None = None,
) -> list[Route]:
    def admin_or_403(request: Request) -> User | Response:
        user = current_user(request)
        if user is not None and user.role == "admin":
            return user
        resp = render_error_page(
            config,
            status=403,
            title="Forbidden",
            detail="The registry is for hub administrators.",
        )
        resp.headers.update(NO_STORE)
        return resp

    def page(request: Request, status: int = 200, **ctx) -> Response:
        """Render the registry page. `ctx` may carry error/notice/form/confirm."""
        hub = api.hub_handle(config)
        if hub is None:
            resp = render_error_page(
                config,
                status=503,
                title="Hub unreachable",
                detail="The hub checkout is not available.",
            )
            resp.headers.update(NO_STORE)
            return resp
        reason = _read_only_reason(intake_cfg, hub.root)
        error = ctx.pop("error", "")
        for name, default in (("notice", ""), ("confirm", ""), ("form", {})):
            ctx.setdefault(name, default)
        try:
            rows = _entries(registryedit.read_registry(hub.root))
        except (KbError, gitio.GitError) as exc:
            rows, reason = [], reason or "Read-only: the registry cannot be read."
            error = error or _first_line(str(exc))
        resp = _render_page(
            "registry.html",
            config,
            screen="registry",
            status=status,
            title="Registry",
            rows=rows,
            history=_history(hub.root),
            read_only=reason,
            error=error,
            csrf=csrf_token(session.key, request.cookies.get(COOKIE_NAME, "")),
            kinds=kinds.HUB_KINDS,
            **ctx,
        )
        resp.headers.update(NO_STORE)
        return resp

    def registry_get(request: Request) -> Response:
        if isinstance(who := admin_or_403(request), Response):
            return who
        done = request.query_params.get("done", "")
        notice = NOTICES.get(done.removesuffix(STALE_SUFFIX), "")
        if notice and done.endswith(STALE_SUFFIX):
            notice = f"{notice} {STALE_PULL_NOTICE}"
        return page(request, notice=notice)

    def apply(action: str, form: FormData, username: str) -> str:
        """Run one edit under the lock; the notice code on success."""
        repo = str(form.get("repo", "")).strip()
        label, code = _labels(action, form)
        with registry_lock:
            _pull_best_effort(config.hub)
            hub = api.hub_handle(config)
            if hub is None:
                raise _Fail(503, "The hub checkout is not available.")
            reason = _read_only_reason(intake_cfg, hub.root)
            if reason or intake_cfg is None:
                raise _Fail(409, reason or "Read-only.")
            message = f"registry: {label} {repo} (by {username})"
            do_push = push or _make_real_push(hub.root, intake_cfg)
            try:
                # Read and commit share one base: the default branch's own
                # worktree, never the (possibly off-branch or dirty) checkout.
                changed = registryedit.edit_registry(
                    hub.root,
                    lambda reg, fed_dir: _edit(action, reg, form, repo, fed_dir),
                    message,
                    do_push,
                )
            except _Fail:
                raise
            except gitio.GitError as exc:
                _pull_best_effort(config.hub)
                if any(m in str(exc) for m in _STALE_MARKERS):
                    raise _Fail(409, STALE_MESSAGE) from exc
                logger.warning("registry push failed: %s", gitio.redact_url(str(exc)))
                raise _Fail(
                    502, f"The hub rejected the push: {_first_line(str(exc))}"
                ) from exc
            except ghapp.GHAppError as exc:
                logger.warning(
                    "registry token mint failed: %s", gitio.redact_url(str(exc))
                )
                raise _Fail(
                    502,
                    f"GitHub App token could not be minted: {_first_line(str(exc))}",
                ) from exc
            except KbError as exc:  # the registry on the branch is unreadable
                raise _Fail(500, _first_line(str(exc))) from exc
            if not changed:
                return "nochange"
            return code if _pull_best_effort(config.hub) else code + STALE_SUFFIX

    def _labels(action: str, form: FormData) -> tuple[str, str]:
        """(commit-message action, notice code)."""
        if action == "add":
            return "add", "added"
        if action == "remove":
            return "remove", "removed"
        on = form.get("on") == "1"
        return (
            ("auto-merge on", "auto-merge-on")
            if on
            else (
                "auto-merge off",
                "auto-merge-off",
            )
        )

    def _edit(
        action: str, reg: Registry, form: FormData, repo: str, fed_dir: Path
    ) -> Registry:
        try:
            if action == "add":
                return registryedit.add_entry(
                    reg,
                    repo,
                    str(form.get("repo_id", "")).strip(),
                    kind=str(form.get("kind", "")).strip(),
                    workflow=str(form.get("workflow", "")),
                    auto_merge=form.get("auto_merge") == "on",
                    existing_dirs=_federation_dirs(fed_dir),
                )
            if action == "remove":
                return registryedit.remove_entry(reg, repo)
            return registryedit.set_auto_merge(reg, repo, form.get("on") == "1")
        except KbError as exc:
            # remove/toggle of a key that is gone = a stale tab, not bad input.
            raise _Fail(400 if action == "add" else 409, str(exc)) from exc

    def handle_post(
        request: Request, user: User, action: str, form: FormData
    ) -> Response:
        repo = str(form.get("repo", "")).strip()
        if action == "remove" and form.get("confirm") != "yes":
            known = {r["repo"] for r in _entries_safe()}
            if repo not in known:
                return page(
                    request,
                    status=409,
                    error=f"Repository '{repo}' is not in the registry.",
                )
            return page(request, confirm=repo)
        try:
            code = apply(action, form, user.username)
        except _Fail as fail:
            return page(
                request,
                status=fail.status,
                error=fail.message,
                form=dict(form) if action == "add" else {},
            )
        except Exception:
            logger.exception("registry %s failed", action)
            return page(
                request,
                status=500,
                error="Unexpected error; see the hub log.",
            )
        return RedirectResponse(
            f"/ui/registry?done={quote(code)}", status_code=303, headers=NO_STORE
        )

    def _entries_safe() -> list[dict]:
        hub = api.hub_handle(config)
        if hub is None:
            return []
        try:
            return _entries(registryedit.read_registry(hub.root))
        except (KbError, gitio.GitError):
            return []

    def read_only_now() -> str | None:
        hub = api.hub_handle(config)
        return _read_only_reason(intake_cfg, hub.root if hub else None)

    def post_route(action: str):
        async def handler(request: Request) -> Response:
            user = admin_or_403(request)
            if isinstance(user, Response):
                return user
            # Before the body and the CSRF check: a read-only hub changes
            # nothing, and its page renders no forms to carry a token.
            if reason := await run_in_threadpool(read_only_now):
                return await run_in_threadpool(page, request, 409, error=reason)
            if int(request.headers.get("content-length") or 0) > MAX_BODY:
                return Response("body too large", status_code=413, headers=NO_STORE)
            capped = Request(
                request.scope,
                bodycap.capped_receive(
                    request, MAX_BODY, lambda: OverflowError("body too large")
                ),
            )
            try:
                form = await capped.form(max_files=0, max_fields=12)
            except OverflowError:
                return Response("body too large", status_code=413, headers=NO_STORE)
            await capped.close()
            if not _csrf_ok(session, request, form.get("csrf", "")):
                return await run_in_threadpool(
                    page, request, 403, error="Form expired. Reload and try again."
                )
            return await run_in_threadpool(handle_post, request, user, action, form)

        return handler

    return [
        Route("/ui/registry", registry_get, methods=["GET"]),
        Route("/ui/registry/add", post_route("add"), methods=["POST"]),
        Route("/ui/registry/remove", post_route("remove"), methods=["POST"]),
        Route("/ui/registry/auto-merge", post_route("auto-merge"), methods=["POST"]),
    ]
