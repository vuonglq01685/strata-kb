from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger("strata_kb.gitio")

# `user:pass@` / `x-access-token:<token>@` in any URL — CI templates pass
# credential-bearing hub URLs, and git echoes the remote URL in its stderr.
_URL_CRED_RE = re.compile(r"(\w+://)[^@/\s]+@")

_URL_CRED_SPLIT_RE = re.compile(r"^(?P<scheme>\w+://)(?P<cred>[^@/\s]+)@(?P<rest>.*)$")


class GitError(RuntimeError):
    """Error calling git: not a repo, rev doesn't exist, path outside the repo.

    Deliberately stays out of the KbError family (Wave G fix round 2, item
    7): its handling is site-specific by design -- swallowed in
    hub.resolve_hub and publish._publish_direct, re-wrapped into a different
    message in cli.reindex -- so a blanket "catch KbError, print str(exc)"
    guard would be wrong at some of its call sites.
    """


def redact_url(text: str) -> str:
    """Strip embedded credentials from every URL in `text`.

    Must be applied to anything that can reach a log, exception message, or
    CLI output and may contain a remote URL (the URL itself or git stderr,
    which echoes it) — tokens must never land in CI logs.
    """
    return _URL_CRED_RE.sub(r"\1<redacted>@", text)


def split_credentials(url: str) -> tuple[str, str | None]:
    """(url without credentials, token) -- (url, None) when there are none.

    The CI templates hand us https://x-access-token:<token>@host/org/repo.git.
    Cloning that verbatim writes the token into <clone>/.git/config at mode
    0644, where it outlives the process and every token rotation.
    """
    m = _URL_CRED_SPLIT_RE.match(url or "")
    if not m:
        return url, None
    cred = m.group("cred")
    token = cred.split(":", 1)[1] if ":" in cred else cred
    return f"{m.group('scheme')}{m.group('rest')}", token or None


def credential_env(url: str, token: str | None) -> dict[str, str]:
    """Environment that hands git a credential without putting it in argv.

    /proc/<pid>/cmdline is world-readable; /proc/<pid>/environ is readable
    only by the same uid. GIT_CONFIG_COUNT/KEY/VALUE needs git >= 2.31.
    """
    if not token:
        return {}
    import base64

    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": f"http.{url}.extraheader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}",
    }


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    # P55: gitio is called from the CLI, the MCP stdio server, the HTTP
    # server and the intake worker -- it cannot assume a console. An
    # inherited stdin can be a protocol stream (the MCP server's stdin *is*
    # the JSON-RPC channel); a git child that inherits it can block reading
    # it forever (Wave J Critical). No call here writes to git's stdin, so
    # DEVNULL is correct, not just convenient.
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True,
        encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
    )


def _run_env(
    root: Path | None, env_extra: dict[str, str], *args: str
) -> subprocess.CompletedProcess[str]:
    import os

    env = {**os.environ, **env_extra} if env_extra else None
    # P55 -- see _run above.
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env, stdin=subprocess.DEVNULL,
    )


def git_root(start: Path) -> Path:
    cwd = start if start.is_dir() else start.parent
    proc = _run(cwd, "rev-parse", "--show-toplevel")
    if proc.returncode != 0:
        raise GitError(
            f"'{start}' is not inside a git repo — resolve/diff/doctor --context need a KB versioned with Git"
        )
    return Path(proc.stdout.strip()).resolve()


def head_commit(root: Path) -> str:
    proc = _run(root, "rev-parse", "--short", "HEAD")
    if proc.returncode != 0:
        raise GitError(f"could not get HEAD: {proc.stderr.strip()}")
    return proc.stdout.strip()


def rev_exists(root: Path, rev: str) -> bool:
    proc = _run(root, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    return proc.returncode == 0


def is_tracked(root: Path, relpath: str) -> bool:
    """True when `relpath` is tracked by git under `root`.

    False, never raised, when `root` isn't a git repo or git isn't on
    PATH -- callers use this to decide whether to refuse writing a secret
    into a file, and "can't tell" must not crash that decision.
    """
    try:
        proc = _run(root, "ls-files", "--error-unmatch", "--", relpath)
    except FileNotFoundError:
        return False
    return proc.returncode == 0


def _relpath(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise GitError(f"'{path}' is outside git repo '{root}'") from exc


def read_at(root: Path, rev: str, path: Path) -> str | None:
    """File content at a given rev; None if the file doesn't exist at that rev.

    Raises GitError if the rev doesn't exist (distinguishes it from a missing
    file — git show returns the same exit code for both).
    """
    rel = _relpath(root, path)
    if not rev_exists(root, rev):
        raise GitError(f"rev '{rev}' does not exist in the repo (force-push or shallow clone?)")
    proc = _run(root, "show", f"{rev}:{rel}")
    if proc.returncode != 0:
        return None
    return proc.stdout


def is_dirty(root: Path, subpath: Path) -> bool:
    rel = _relpath(root, subpath)
    proc = _run(root, "status", "--porcelain", "--", rel)
    return bool(proc.stdout.strip())


def config_value(root: Path, key: str, *, local: bool = False) -> str:
    """`git config --get <key>` or "" when unset.

    `local=True` scopes the read to `root`'s own `.git/config` (`--local`),
    ignoring anything set in the operator's global/system gitconfig --
    without it, a value set globally is indistinguishable from one written
    into this clone's own config (the exact gap Important 2 found in
    hub.py's `_cache_needs_reclone`, and the reason `doctor.py`'s credential
    sweep already scopes its own read this way).
    """
    args = ["config", "--local", "--get", key] if local else ["config", "--get", key]
    proc = _run(root, *args)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def clone(url: str, dest: Path) -> None:
    """Clone `url` into `dest` with no credential and no CRLF rewriting.

    core.autocrlf=false / core.eol=lf are set on the command AND written into
    the clone's local config: with Git for Windows' default autocrlf=true a
    fresh checkout writes CRLF, hashsync hashes raw bytes, and the next
    publish looks like a whole-tree change (F-D10).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    stripped, token = split_credentials(url)
    proc = _run_env(
        None,
        credential_env(stripped, token),
        "-c", "core.autocrlf=false", "-c", "core.eol=lf",
        "clone", stripped, str(dest),
    )
    if proc.returncode != 0:
        raise GitError(redact_url(f"clone '{stripped}' failed: {proc.stderr.strip()}"))
    neutralize_line_endings(dest)


def pull(root: Path, url: str | None = None, token: str | None = None) -> None:
    """`token` is an explicit credential (e.g. HubHandle.token) to use when
    `url` is omitted -- remote_url(root) is the clone's own origin, which is
    already stripped of any credential (strip_remote_credentials), so a
    caller with no credential-bearing `url` handy must pass `token`
    separately or authentication silently has nothing to offer git."""
    stripped, embedded = split_credentials(url or remote_url(root))
    proc = _run_env(root, credential_env(stripped, token or embedded), "pull", "--ff-only")
    if proc.returncode != 0:
        raise GitError(redact_url(f"pull failed: {proc.stderr.strip()}"))


def pull_rebase(root: Path, token: str | None = None) -> None:
    stripped, embedded = split_credentials(remote_url(root))
    proc = _run_env(
        root, credential_env(stripped, token or embedded), "pull", "--rebase"
    )
    if proc.returncode != 0:
        raise GitError(redact_url(f"pull --rebase failed: {proc.stderr.strip()}"))


def commit_all(root: Path, message: str) -> bool:
    """`git add -A` + commit; False if the working tree is clean (nothing to commit)."""
    _run(root, "add", "-A")
    if not _run(root, "status", "--porcelain").stdout.strip():
        return False
    proc = _run(root, "commit", "-m", message)
    if proc.returncode != 0:
        raise GitError(f"commit failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return True


def commit_paths(root: Path, message: str, paths: list[str]) -> bool:
    """`git add -- <paths>` + commit limited to those paths (other paths untouched).

    False if the working tree is clean within the `paths` scope (nothing to commit).
    Use when only a subdirectory (e.g. federation/) should be staged, to avoid
    accidentally committing stray files outside that scope (e.g. the .kb-work/
    cache in a hub clone).
    """
    _run(root, "add", "--", *paths)
    if not _run(root, "status", "--porcelain", "--", *paths).stdout.strip():
        return False
    proc = _run(root, "commit", "-m", message, "--", *paths)
    if proc.returncode != 0:
        raise GitError(f"commit failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return True


def push(root: Path, token: str | None = None) -> None:
    stripped, embedded = split_credentials(remote_url(root))
    proc = _run_env(
        root, credential_env(stripped, token or embedded), "push", "origin", "HEAD"
    )
    if proc.returncode != 0:
        raise GitError(redact_url(f"push failed: {proc.stderr.strip()}"))


def has_remote(root: Path) -> bool:
    return _run(root, "remote", "get-url", "origin").returncode == 0


def remote_url(root: Path) -> str:
    proc = _run(root, "remote", "get-url", "origin")
    return proc.stdout.strip() if proc.returncode == 0 else ""


def current_branch(root: Path) -> str:
    proc = _run(root, "rev-parse", "--abbrev-ref", "HEAD")
    if proc.returncode != 0:
        raise GitError(f"could not get current branch: {proc.stderr.strip()}")
    return proc.stdout.strip()


def checkout_branch(root: Path, name: str, start_point: str) -> None:
    """Create/reset branch `name` at `start_point`, then switch to it (checkout -B)."""
    proc = _run(root, "checkout", "-B", name, start_point)
    if proc.returncode != 0:
        raise GitError(f"checkout -B {name} failed: {proc.stderr.strip()}")


def checkout(root: Path, name: str) -> None:
    proc = _run(root, "checkout", name)
    if proc.returncode != 0:
        raise GitError(f"checkout {name} failed: {proc.stderr.strip()}")


def push_branch(root: Path, branch: str, token: str | None = None) -> None:
    """Force-push the working branch (publish/<rid> is owned by the publisher)."""
    stripped, embedded = split_credentials(remote_url(root))
    proc = _run_env(
        root, credential_env(stripped, token or embedded),
        "push", "--force", "origin", branch,
    )
    if proc.returncode != 0:
        raise GitError(redact_url(f"push branch '{branch}' failed: {proc.stderr.strip()}"))


def tag(root: Path, name: str) -> None:
    proc = _run(root, "tag", name)
    if proc.returncode != 0:
        raise GitError(f"tag '{name}' failed: {proc.stderr.strip()}")


def push_tag(root: Path, name: str) -> None:
    proc = _run(root, "push", "origin", f"refs/tags/{name}")
    if proc.returncode != 0:
        raise GitError(redact_url(f"push tag '{name}' failed: {proc.stderr.strip()}"))


def push_branch_with_token(root: Path, url: str, token: str, branch: str) -> None:
    """Force-push `branch` to `url` with the token passed through the env.

    Replaces building https://x-access-token:<token>@... and handing it to
    git as an argv, where any local user could read it from
    /proc/<pid>/cmdline.
    """
    stripped, embedded = split_credentials(url)
    proc = _run_env(
        root,
        credential_env(stripped, token or embedded),
        "push", "--force", stripped, f"{branch}:{branch}",
    )
    if proc.returncode != 0:
        detail = redact_url(proc.stderr.strip().replace(stripped, "<hub-url>"))
        raise GitError(f"push branch '{branch}' failed: {detail}")


def worktree_add(
    root: Path, path: Path, branch: str, base: str, reset: bool
) -> None:
    """Check `branch` out into its own working tree at `path`.

    reset=True recreates the branch at `base` (`-B`); reset=False attaches to
    the branch as it stands. Either way the repo's own working tree keeps its
    branch and its files -- which is the point: the intake server serves from
    that tree while a publish writes here.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    args = ["worktree", "add"]
    args += ["-B", branch, str(path), base] if reset else [str(path), branch]
    proc = _run(root, *args)
    if proc.returncode != 0:
        raise GitError(f"worktree add '{branch}' failed: {proc.stderr.strip()}")


def worktree_remove(root: Path, path: Path) -> None:
    """Remove a worktree; best-effort, so a cleanup failure never masks the
    real error a caller is already unwinding from."""
    proc = _run(root, "worktree", "remove", "--force", str(path))
    if proc.returncode != 0:
        import shutil

        shutil.rmtree(path, ignore_errors=True)
        _run(root, "worktree", "prune")


def worktree_prune(root: Path) -> None:
    """Forget worktrees whose directories are gone (crash cleanup)."""
    _run(root, "worktree", "prune")


def default_branch(root: Path) -> str:
    """origin/HEAD's branch when there is a remote, else the current branch."""
    proc = _run(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip().split("/", 1)[-1]
    return current_branch(root)


def path_exists_at(root: Path, rev: str, relpath: str) -> bool:
    """Does `relpath` exist in the tree at `rev`?

    `relpath` is repo-relative, separators normalised to POSIX -- git only
    resolves `rev:path` with forward slashes, so a raw Windows path would
    silently read as "missing" instead of failing loudly.

    Asks git rather than the working tree, so the answer does not depend on
    which branch some other publish left checked out.

    Raises GitError if `rev` itself doesn't exist (distinguishes an
    unresolvable rev from a resolvable rev with a missing path -- same
    split as `read_at`, and for the same reason: a typo'd or unfetched rev
    must be loud, not silently answered False).
    """
    if not rev_exists(root, rev):
        raise GitError(f"rev '{rev}' does not exist in the repo (force-push or shallow clone?)")
    posix_relpath = relpath.replace("\\", "/")
    return _run(root, "cat-file", "-e", f"{rev}:{posix_relpath}").returncode == 0


def neutralize_line_endings(root: Path) -> None:
    """federation/ snapshot fidelity is checked with raw-byte hashes
    (hashsync hashes bytes as extracted from the upload archive, no git
    filtering) -- the operator machine's global core.autocrlf must not be
    allowed to rewrite LF -> CRLF when the hub branch is checked out again
    (e.g. reusing an unmerged publish/<rid> branch across successive
    publishes), which would make byte-identical re-publishes look changed
    forever. Set locally (repo-scoped, does not touch the user's global
    gitconfig) -- best-effort, publish still proceeds if this fails.
    """
    for key, value in (("core.autocrlf", "false"), ("core.eol", "lf")):
        proc = _run(root, "config", key, value)
        if proc.returncode != 0:
            logger.debug(
                "git config %s %s failed in %s (rc=%s): %s",
                key, value, root, proc.returncode, proc.stderr.strip(),
            )
