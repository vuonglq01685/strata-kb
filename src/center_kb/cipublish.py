# src/center_kb/cipublish.py
"""kb ci-publish — runs inside the child's GitHub Actions job.

OIDC JWT ← ACTIONS_ID_TOKEN_REQUEST_URL/TOKEN; manifest diff against the hub
(via the intake service); uploads only changed files + a delete list.
No static secret anywhere in the child repo.
"""
from __future__ import annotations

import io
import json
import os
import tarfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from center_kb import gitio, hashsync
from center_kb import publish as publish_mod


class CIPublishError(RuntimeError):
    """ci-publish failed — the Actions job should go red."""


def _decode(raw) -> str:
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw)


def _default_http(method: str, url: str, headers: dict, body: bytes | None):
    req = urllib.request.Request(url, method=method, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, OSError) as exc:
        # Connection-level failure (DNS, refused, timeout): status 0 so the
        # manifest GET can fall back to a full upload, while POST/token paths
        # turn it into a loud CIPublishError with this text as the detail.
        return 0, str(exc).encode("utf-8")


def _request_oidc_token(audience: str, http) -> str:
    req_url = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL", "")
    req_tok = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "")
    if not req_url or not req_tok:
        raise CIPublishError(
            "not inside GitHub Actions (ACTIONS_ID_TOKEN_REQUEST_* missing) — "
            "ci-publish only runs in the child's workflow; use `kb publish` locally"
        )
    url = f"{req_url}&audience={urllib.parse.quote(audience, safe='')}"
    status, raw = http("GET", url, {"Authorization": f"Bearer {req_tok}"}, None)
    if status == 0:
        raise CIPublishError(f"OIDC token endpoint unreachable: {_decode(raw)}")
    if status != 200:
        raise CIPublishError(f"OIDC token request failed: HTTP {status}")
    return json.loads(raw)["value"]


def _fetch_remote_manifest(
    intake_url: str, rid: str, token: str, http
) -> dict[str, str]:
    url = (
        f"{intake_url.rstrip('/')}/intake/manifest?"
        + urllib.parse.urlencode({"repo_id": rid})
    )
    # The manifest endpoint is OIDC-gated (same audience as publish) so one
    # child can never diff another child's tree.
    status, raw = http("GET", url, {"Authorization": f"Bearer {token}"}, None)
    if status != 200:
        print(f"[warn] manifest endpoint returned {status} — falling back to full upload")
        return {}
    return json.loads(raw).get("files", {})


def _build_archive(kb_abs: Path, changed: list[str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for rel in changed:
            tf.add(kb_abs / rel, arcname=rel, recursive=False)
    return buf.getvalue()


def _multipart(meta: dict, archive: bytes) -> tuple[bytes, str]:
    boundary = f"kb-{uuid.uuid4().hex}"
    meta_json = json.dumps(meta).encode("utf-8")
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="meta"\r\n\r\n',
            meta_json, b"\r\n",
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="archive"; filename="kb.tar.gz"\r\n',
            b"Content-Type: application/gzip\r\n\r\n",
            archive, b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return body, f"multipart/form-data; boundary={boundary}"


def _check_unreviewed_gate(kb_dir: Path, require_reviewed: bool) -> None:
    """Warn/refuse on sections published without SME review (R18) — the
    same helper `kb publish` calls, run here before any upload."""
    gate = publish_mod.unreviewed_gate(kb_dir, require_reviewed)
    if gate.line is not None:
        print(gate.line)
        if gate.blocked:
            raise CIPublishError(gate.line)


def run(
    kb_dir: Path,
    intake_url: str,
    repo_id: str | None,
    require_reviewed: bool = False,
    http=None,
    token_requester=None,
) -> str:
    """Diff -> upload -> return PR URL; "" when there is nothing to publish."""
    _check_unreviewed_gate(kb_dir, require_reviewed)
    http = http or _default_http
    kb_abs = kb_dir.resolve()
    root = gitio.git_root(kb_abs)
    rid = repo_id or root.name
    commit = gitio.head_commit(root)

    # Token first: the manifest diff GET below authenticates with the same
    # OIDC JWT as the publish POST.
    audience = intake_url.rstrip("/")
    token = (token_requester or _request_oidc_token)(audience, http)

    remote_man = _fetch_remote_manifest(intake_url, rid, token, http)
    local_man = hashsync.build_manifest(kb_abs)
    changed, deleted = hashsync.diff_manifests(local_man, remote_man)
    if not changed and not deleted:
        print("nothing to publish — hub snapshot already matches .kb/")
        return ""
    print(f"publishing {len(changed)} changed file(s), {len(deleted)} deletion(s)")

    archive = _build_archive(kb_abs, changed)
    body, content_type = _multipart(
        {"source_commit": commit, "deletes": deleted}, archive
    )
    status, raw = http(
        "POST",
        f"{intake_url.rstrip('/')}/intake/publish",
        {"Authorization": f"Bearer {token}", "Content-Type": content_type},
        body,
    )
    if status == 0:
        raise CIPublishError(f"intake unreachable: {_decode(raw)}")
    if status != 200:
        try:
            detail = json.loads(raw).get("detail", "")
        except (json.JSONDecodeError, AttributeError):
            detail = _decode(raw[:200] if isinstance(raw, bytes) else raw)
        raise CIPublishError(f"intake rejected the publish (HTTP {status}): {detail}")
    pr_url = json.loads(raw).get("pr_url", "")
    print(f"PR: {pr_url}" if pr_url else "published (no content change on the hub)")
    return pr_url
