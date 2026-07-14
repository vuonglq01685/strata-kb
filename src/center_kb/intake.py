from __future__ import annotations

import io
import json
import logging
import tarfile
import threading
from pathlib import Path

from center_kb import models

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
