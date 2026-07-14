from __future__ import annotations

import io
import json
import logging
import tarfile
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from center_kb import federation, ghapp, gitio, hashsync, models
from center_kb import hub as hub_mod

logger = logging.getLogger("center_kb.intake")

GITHUB_ISSUER = "https://token.actions.githubusercontent.com"
JWKS_URL = GITHUB_ISSUER + "/.well-known/jwks"
TAG_REF_PREFIX = "refs/tags/kb-publish/"
DEFAULT_MAX_TAR = 50 * 1024 * 1024


class IntakeError(RuntimeError):
    """Publish intake rejected the request; maps to an HTTP status."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


_jwks_client = None
_jwks_lock = threading.Lock()


def _default_key_resolver(token: str):
    """PyJWKClient resolves + caches GitHub's signing keys by `kid`."""
    global _jwks_client
    import jwt

    with _jwks_lock:
        if _jwks_client is None:
            _jwks_client = jwt.PyJWKClient(JWKS_URL, cache_keys=True)
    return _jwks_client.get_signing_key_from_jwt(token).key


def verify_oidc(token: str, audience: str, key_resolver=None) -> dict:
    import jwt

    resolver = key_resolver or _default_key_resolver
    try:
        key = resolver(token)
        return jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=audience,
            issuer=GITHUB_ISSUER,
        )
    except jwt.PyJWTError as exc:
        raise IntakeError(401, f"OIDC token rejected: {exc}") from exc


def authorize(claims: dict, registry: models.Registry) -> str:
    """claims -> repo_id. The registry -- never the payload -- decides the write path."""
    from center_kb.publish import _REPO_ID_RE

    ref = claims.get("ref", "")
    if not ref.startswith(TAG_REF_PREFIX):
        raise IntakeError(
            403, f"ref '{ref}' is not a {TAG_REF_PREFIX}* tag -- run `kb publish`"
        )
    repo = claims.get("repository", "")
    rid = registry.repos.get(repo, "")
    if not rid:
        raise IntakeError(
            403,
            f"repo '{repo}' is not registered -- open a PR on the hub adding "
            f"`{repo}: <repo-id>` under `repos:` in federation/registry.yaml",
        )
    if not _REPO_ID_RE.fullmatch(rid) or rid in {".", ".."}:
        raise IntakeError(500, f"registry maps '{repo}' to invalid repo-id '{rid}'")
    return rid


def safe_extract(data: bytes, dest: Path, max_bytes: int = DEFAULT_MAX_TAR) -> None:
    if len(data) > max_bytes:
        raise IntakeError(413, f"archive exceeds {max_bytes} bytes")
    try:
        tf = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")
    except tarfile.TarError as exc:
        raise IntakeError(400, f"archive is not a valid tar.gz: {exc}") from exc
    dest_resolved = dest.resolve()
    with tf:
        total = 0
        # Lazy iteration: `for member in tf` reads one header at a time, so the
        # cumulative cap below aborts after ~max_bytes decompressed. getmembers()
        # would walk (decompress) the ENTIRE archive up front just to list
        # headers -- a crafted tar bomb could force tens of GB of decompression
        # before the cap ever ran.
        for member in tf:
            if not member.isreg():
                raise IntakeError(
                    400, f"tar member '{member.name}' is not a regular file"
                )
            rel = Path(member.name)
            if rel.is_absolute() or ".." in rel.parts:
                raise IntakeError(400, f"tar member '{member.name}' escapes dest")
            total += member.size
            if total > max_bytes:
                raise IntakeError(413, f"archive content exceeds {max_bytes} bytes")
            target = (dest / rel).resolve()
            if not target.is_relative_to(dest_resolved):
                raise IntakeError(400, f"tar member '{member.name}' escapes dest")
            target.parent.mkdir(parents=True, exist_ok=True)
            src = tf.extractfile(member)
            assert src is not None  # isreg() checked above
            target.write_bytes(src.read())


class StatusStore:
    """(repo_id, commit) -> {state, pr_url, detail}; thread-safe; optional JSON persistence."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {}
        if path is not None and path.exists():
            try:
                self._data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                logger.warning("intake status file unreadable -- starting empty")

    @staticmethod
    def _key(repo_id: str, commit: str) -> str:
        return f"{repo_id}@{commit}"

    def set(
        self, repo_id: str, commit: str, state: str, pr_url: str = "", detail: str = ""
    ) -> None:
        with self._lock:
            self._data[self._key(repo_id, commit)] = {
                "state": state, "pr_url": pr_url, "detail": detail,
            }
            if self._path is not None:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._path.write_text(json.dumps(self._data), encoding="utf-8")

    def get(self, repo_id: str, commit: str) -> dict | None:
        with self._lock:
            return self._data.get(self._key(repo_id, commit))


_repo_locks: dict[str, threading.Lock] = {}
_repo_locks_guard = threading.Lock()


def repo_lock(repo_id: str) -> threading.Lock:
    with _repo_locks_guard:
        return _repo_locks.setdefault(repo_id, threading.Lock())


@dataclass
class IntakeConfig:
    hub_ref: str
    audience: str
    creds: ghapp.AppCreds
    status_path: Path | None = None
    max_tar_bytes: int = DEFAULT_MAX_TAR
    key_resolver: object = None  # test seam -- None = real PyJWKClient
    http: object = None  # test seam -- None = real urllib
    push_via_token_url: bool = True  # False in tests: push plain origin, no token URL


def _resolve_hub_or_503(hub_ref: str) -> hub_mod.HubHandle:
    handle = hub_mod.resolve_hub(hub_ref)
    if handle is None:
        raise IntakeError(503, "hub unreachable from the intake server")
    return handle


def _dest_for_rid(federation_dir: Path, rid: str) -> Path:
    """Validate `rid` before treating it as a federation/ subpath.

    authorize() already validates rid via the registry in the normal intake
    flow, but intake_publish/hub_manifest are callable directly (tests,
    tooling) -- re-validate rather than trust the caller.
    """
    from center_kb.publish import _REPO_ID_RE

    if not _REPO_ID_RE.fullmatch(rid) or rid in {".", ".."}:
        raise IntakeError(400, f"repo-id '{rid}' is invalid")
    dest = federation_dir / rid
    if not dest.resolve().is_relative_to(federation_dir.resolve()):
        raise IntakeError(400, f"repo-id '{rid}' escapes the federation/ directory")
    return dest


def _neutralize_line_endings(root: Path) -> None:
    """federation/ snapshot fidelity is checked with raw-byte hashes
    (hashsync hashes bytes as extracted from the upload archive, no git
    filtering) -- the operator machine's global core.autocrlf must not be
    allowed to rewrite LF -> CRLF when the hub branch is checked out again
    (e.g. reusing an unmerged publish/<rid> branch across successive
    publishes), which would make byte-identical re-publishes look changed
    forever. Set locally (repo-scoped, does not touch the user's global
    gitconfig) -- best-effort, publish still proceeds if this fails.
    """
    import subprocess

    for key, value in (("core.autocrlf", "false"), ("core.eol", "lf")):
        subprocess.run(
            ["git", "config", key, value],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )


def hub_manifest(hub_ref: str, rid: str) -> dict[str, str]:
    handle = _resolve_hub_or_503(hub_ref)
    dest = _dest_for_rid(handle.federation_dir, rid)
    return hashsync.build_manifest(dest, exclude=("_meta.yaml",))


def intake_publish(
    cfg: IntakeConfig,
    rid: str,
    source_commit: str,
    source_repo_full: str,
    deletes: list[str],
    archive: bytes,
) -> str:
    """Apply an uploaded snapshot on branch publish/<rid> and open the hub PR.

    Returns the PR URL, or "" when the snapshot changes nothing.
    """
    from center_kb import publish as publish_mod

    http = cfg.http or ghapp._default_http
    deletes = [d for d in deletes if d != "_meta.yaml"]
    with repo_lock(rid):
        handle = _resolve_hub_or_503(cfg.hub_ref)
        dest = _dest_for_rid(handle.federation_dir, rid)
        publish_mod._neutralize_excludes(handle.root)
        _neutralize_line_endings(handle.root)
        try:
            gitio.pull(handle.root)  # base the PR on the freshest main when possible
        except gitio.GitError:
            logger.warning("hub pull failed -- publishing against cached main")
        original = gitio.current_branch(handle.root)
        branch = f"publish/{rid}"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_kb = Path(tmp) / "kb"
            tmp_kb.mkdir()
            safe_extract(archive, tmp_kb, cfg.max_tar_bytes)
            try:
                # Reuse the branch across successive publishes of the same
                # rid so an unmerged PR accumulates snapshots (and a second,
                # identical publish diffs against its own prior write and
                # is a true no-op) instead of getting reset to `original`
                # (main) -- which would always look "changed" because
                # federation/<rid> does not exist on main until merged.
                if gitio.rev_exists(handle.root, branch):
                    gitio.checkout(handle.root, branch)
                else:
                    gitio.checkout_branch(handle.root, branch, original)
                # upload is incremental -- every file in the archive counts as changed
                local_man = hashsync.build_manifest(tmp_kb)
                hashsync.apply_sync(tmp_kb, dest, sorted(local_man), deletes)
                dirty = gitio._run(
                    handle.root, "status", "--porcelain", "--", "federation"
                ).stdout.strip()
                if not dirty:
                    return ""  # nothing changed -- finally still checks out `original`
                meta = federation.FederationMeta(
                    repo_id=rid,
                    source_url=f"https://github.com/{source_repo_full}",
                    source_commit=source_commit,
                    published_at=datetime.now(timezone.utc).isoformat(
                        timespec="seconds"
                    ),
                )
                models.save_yaml_model(dest / "_meta.yaml", meta)
                federation.write_federation_index(handle.federation_dir)
                gitio.commit_paths(
                    handle.root, f"publish: {rid} @ {source_commit}", ["federation"]
                )
                hub_url = gitio.remote_url(handle.root)
                hub_full = ghapp.repo_full_from_url(hub_url)
                token = ghapp.mint_installation_token(cfg.creds, hub_full, http=http)
                if cfg.push_via_token_url:
                    push_url = f"https://x-access-token:{token}@github.com/{hub_full}.git"
                    gitio.push_branch_url(handle.root, push_url, branch)
                else:
                    gitio.push_branch(handle.root, branch)
                return ghapp.create_or_get_pr(
                    hub_full,
                    token,
                    branch,
                    title=f"publish: {rid} @ {source_commit}",
                    body=publish_mod.PR_BODY_TEMPLATE.format(
                        rid=rid, commit=source_commit
                    ),
                    base=original,
                    http=http,
                )
            finally:
                gitio.checkout(handle.root, original)
