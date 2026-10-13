"""gitio — every git subprocess call strata-kb makes.

Small wrappers (rev-parse, show, status, clone, pull, commit, push, worktree,
tag) that raise GitError on failure, plus BatchReader for many `read_at`s
through one `git cat-file --batch`. Called from the CLI, the MCP stdio server,
the HTTP server and the intake worker, so no call may assume a console. Any
text that can carry a remote URL goes through `redact_url` before it is
logged or raised; tokens reach git through the environment, never argv.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from strata_kb.errors import KbError

logger = logging.getLogger("strata_kb.gitio")

# `user:pass@` / `x-access-token:<token>@` in any URL — CI templates pass
# credential-bearing hub URLs, and git echoes the remote URL in its stderr.
_URL_CRED_RE = re.compile(r"(\w+://)[^@/\s]+@")

_URL_CRED_SPLIT_RE = re.compile(r"^(?P<scheme>\w+://)(?P<cred>[^@/\s]+)@(?P<rest>.*)$")


class GitError(KbError):
    """Error calling git: not a repo, rev doesn't exist, path outside the repo.

    Sites with their own handling (swallowed in hub.resolve_hub and
    publish._publish_direct, re-worded in cli.reindex) catch it before it
    leaves them; one that escapes a CLI command reaches the root guard as a
    one-line error instead of a traceback (1.15.0).
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
    # gitio is called from the CLI, the MCP stdio server, the HTTP server
    # and the intake worker -- it cannot assume a console. An inherited
    # stdin can be a protocol stream (the MCP server's stdin *is* the
    # JSON-RPC channel); a git child that inherits it can block reading it
    # forever. No call here writes to git's stdin, so DEVNULL is correct,
    # not just convenient.
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
    )


def _run_env(
    root: Path | None,
    env_extra: dict[str, str],
    *args: str,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    import os

    env = {**os.environ, **env_extra} if env_extra else None
    # stdin=DEVNULL -- see _run above.
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        stdin=subprocess.DEVNULL,
        timeout=timeout,
    )


def _run_network(
    root: Path | None,
    env: dict[str, str],
    what: str,
    *args: str,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """A git call that talks to a remote. With `timeout` (unattended callers:
    the hub auto-pull thread, the intake worker) it also turns off git's tty
    and credential-manager prompts, which stdin=DEVNULL alone does not, so a
    missing credential fails instead of hanging -- and a hung remote cannot
    hold a publish lock forever. Without one
    (the CLI), a developer's interactive credential prompt is unchanged."""
    if timeout is not None:
        env = {**env, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
    try:
        return _run_env(root, env, *args, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"{what} timed out after {timeout}s") from exc


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


def head_summary(root: Path) -> tuple[str, str]:
    """(short sha, committer date as ISO 8601) of HEAD."""
    proc = _run(root, "log", "-1", "--format=%h %cI")
    if proc.returncode != 0 or " " not in proc.stdout.strip():
        raise GitError(f"could not read HEAD: {proc.stderr.strip()}")
    sha, date = proc.stdout.strip().split(" ", 1)
    return sha, date


def rev_exists(root: Path, rev: str) -> bool:
    proc = _run(root, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    return proc.returncode == 0


def log_commits(root: Path, relpath: str) -> list[str]:
    """Full hashes of the commits that touch `relpath`, newest first.

    `relpath` is repo-relative; separators are normalised to POSIX like
    `path_exists_at`. Raises GitError on a non-zero exit (not a repo, git
    failure); a path git has never seen is an empty list, not an error."""
    posix_relpath = relpath.replace("\\", "/")
    proc = _run(root, "log", "--format=%H", "--", posix_relpath)
    if proc.returncode != 0:
        raise GitError(f"git log failed for '{posix_relpath}': {proc.stderr.strip()}")
    return proc.stdout.split()


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


def tracked_files(root: Path, relpath: str) -> list[str]:
    """Paths git tracks under `relpath` (POSIX, relative to `root`).

    [] -- never raised -- when `root` isn't a git repo or git isn't on PATH,
    like `is_tracked`: doctor uses this to warn, and "can't tell" is silence.
    """
    try:
        proc = _run(root, "ls-files", "-z", "--", relpath)
    except FileNotFoundError:
        return []
    if proc.returncode != 0:
        return []
    return [f for f in proc.stdout.split("\0") if f]


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
        raise GitError(
            f"rev '{rev}' does not exist in the repo (force-push or shallow clone?)"
        )
    proc = _run(root, "show", f"{rev}:{rel}")
    if proc.returncode != 0:
        return None
    return proc.stdout


class BatchReader:
    """`read_at` for many (rev, path) pairs through ONE `git cat-file --batch`
    process, memoised. Plain `read_at` calls cost `kb resolve` four git
    processes per ref (`rev-parse` twice, `show` twice): 22 for five refs.

    Same contract as `read_at` for files: the text (newlines normalised as
    text-mode `git show` did), None when the path is absent at that rev,
    GitError when the rev does not exist. A directory reads as None (`git
    show` would print a tree listing; no caller reads one). Use as a context
    manager; `close()` ends the process.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self._proc: subprocess.Popen[bytes] | None = None
        self._revs: dict[str, bool] = {}
        self._blobs: dict[tuple[str, str], str | None] = {}

    def __enter__(self) -> BatchReader:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._proc is not None:
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
                self._proc.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                self._proc.kill()
            self._proc = None

    def _cat(self, spec: str) -> bytes | None:
        if self._proc is None:
            self._proc = subprocess.Popen(
                ["git", "cat-file", "--batch"],
                cwd=self.root,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        stdin, stdout = self._proc.stdin, self._proc.stdout
        if stdin is None or stdout is None:  # pragma: no cover - PIPE always sets both
            raise GitError("git cat-file --batch has no pipes")
        if "\n" in spec:
            return None  # cat-file reads one spec per line; git paths never hold one
        stdin.write(spec.encode("utf-8") + b"\n")
        stdin.flush()
        header = stdout.readline()
        if not header:
            raise GitError(f"git cat-file --batch ended reading '{spec}'")
        parts = header.split()
        if len(parts) != 3:  # "<spec> missing" / "ambiguous"
            return None
        size = int(parts[2])
        data = stdout.read(size)
        stdout.read(1)  # the LF after the content
        return data if parts[1] == b"blob" else None

    def mark_rev_exists(self, rev: str) -> None:
        """A caller that already ran `rev_exists(rev)` spares the repeat."""
        self._revs[rev] = True

    def rev_exists(self, rev: str) -> bool:
        if rev not in self._revs:
            self._revs[rev] = rev_exists(self.root, rev)
        return self._revs[rev]

    def read_at(self, rev: str, path: Path) -> str | None:
        rel = _relpath(self.root, path)
        key = (rev, rel)
        if key not in self._blobs:
            if not self.rev_exists(rev):
                raise GitError(
                    f"rev '{rev}' does not exist in the repo (force-push or shallow clone?)"
                )
            data = self._cat(f"{rev}:{rel}")
            self._blobs[key] = (
                None
                if data is None
                else data.decode("utf-8", errors="replace")
                .replace("\r\n", "\n")
                .replace("\r", "\n")
            )
        return self._blobs[key]


def is_dirty(root: Path, subpath: Path) -> bool:
    rel = _relpath(root, subpath)
    proc = _run(root, "status", "--porcelain", "--", rel)
    return bool(proc.stdout.strip())


def config_value(root: Path, key: str, *, local: bool = False) -> str:
    """`git config --get <key>` or "" when unset.

    `local=True` scopes the read to `root`'s own `.git/config` (`--local`),
    ignoring anything set in the operator's global/system gitconfig --
    without it, a value set globally is indistinguishable from one written
    into this clone's own config (the gap this closes in hub.py's
    `_cache_needs_reclone`, and the reason `doctor.py`'s credential sweep
    scopes its own read this way).
    """
    args = ["config", "--local", "--get", key] if local else ["config", "--get", key]
    proc = _run(root, *args)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def clone(url: str, dest: Path) -> None:
    """Clone `url` into `dest` with no credential and no CRLF rewriting.

    core.autocrlf=false / core.eol=lf are set on the command AND written into
    the clone's local config: with Git for Windows' default autocrlf=true a
    fresh checkout writes CRLF, hashsync hashes raw bytes, and the next
    publish looks like a whole-tree change.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    stripped, token = split_credentials(url)
    proc = _run_env(
        None,
        credential_env(stripped, token),
        "-c",
        "core.autocrlf=false",
        "-c",
        "core.eol=lf",
        "clone",
        stripped,
        str(dest),
    )
    if proc.returncode != 0:
        raise GitError(redact_url(f"clone '{stripped}' failed: {proc.stderr.strip()}"))
    neutralize_line_endings(dest)


def pull(
    root: Path,
    url: str | None = None,
    token: str | None = None,
    *,
    timeout: float | None = None,
) -> None:
    """`token` is an explicit credential (e.g. HubHandle.token) to use when
    `url` is omitted -- remote_url(root) is the clone's own origin, which is
    already stripped of any credential (strip_remote_credentials), so a
    caller with no credential-bearing `url` handy must pass `token`
    separately or authentication silently has nothing to offer git.

    `timeout` is for unattended callers: see `_run_network`."""
    stripped, embedded = split_credentials(url or remote_url(root))
    env = credential_env(stripped, token or embedded)
    proc = _run_network(root, env, "pull", "pull", "--ff-only", timeout=timeout)
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


def push_branch(
    root: Path,
    branch: str,
    token: str | None = None,
    *,
    timeout: float | None = None,
    force: bool = True,
) -> None:
    """Force-push the working branch (publish/<rid> is owned by the publisher);
    `force=False` for a branch with history to keep (`kb publish --branch`).
    `timeout`: see `_run_network`."""
    stripped, embedded = split_credentials(remote_url(root))
    proc = _run_network(
        root,
        credential_env(stripped, token or embedded),
        f"push branch '{branch}'",
        "push",
        *(["--force"] if force else []),
        "origin",
        branch,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise GitError(
            redact_url(f"push branch '{branch}' failed: {proc.stderr.strip()}")
        )


def remote_branch_exists(
    root: Path,
    branch: str,
    token: str | None = None,
    *,
    timeout: float | None = None,
) -> bool:
    """True when `origin` has branch `branch` (`git ls-remote --heads`).
    Same credential handling as `push_branch`. Raises GitError on a non-zero
    exit, so a network failure is never read as "branch is gone".
    `timeout`: see `_run_network`."""
    stripped, embedded = split_credentials(remote_url(root))
    ref = f"refs/heads/{branch}"
    proc = _run_network(
        root,
        credential_env(stripped, token or embedded),
        f"look up branch '{branch}'",
        "ls-remote",
        "--heads",
        "origin",
        ref,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise GitError(
            redact_url(f"look up branch '{branch}' failed: {proc.stderr.strip()}")
        )
    return any(line.split()[-1:] == [ref] for line in proc.stdout.splitlines())


def tag(root: Path, name: str) -> None:
    proc = _run(root, "tag", name)
    if proc.returncode != 0:
        raise GitError(f"tag '{name}' failed: {proc.stderr.strip()}")


def delete_tag(root: Path, name: str) -> None:
    proc = _run(root, "tag", "-d", name)
    if proc.returncode != 0:
        raise GitError(f"delete tag '{name}' failed: {proc.stderr.strip()}")


def push_tag(root: Path, name: str) -> None:
    proc = _run(root, "push", "origin", f"refs/tags/{name}")
    if proc.returncode != 0:
        raise GitError(redact_url(f"push tag '{name}' failed: {proc.stderr.strip()}"))


def push_branch_with_token(
    root: Path,
    url: str,
    token: str,
    branch: str,
    *,
    timeout: float | None = None,
) -> None:
    """Force-push `branch` to `url` with the token passed through the env.

    Replaces building https://x-access-token:<token>@... and handing it to
    git as an argv, where any local user could read it from
    /proc/<pid>/cmdline. `timeout`: see `_run_network`.
    """
    stripped, embedded = split_credentials(url)
    proc = _run_network(
        root,
        credential_env(stripped, token or embedded),
        f"push branch '{branch}'",
        "push",
        "--force",
        stripped,
        f"{branch}:{branch}",
        timeout=timeout,
    )
    if proc.returncode != 0:
        detail = redact_url(proc.stderr.strip().replace(stripped, "<hub-url>"))
        raise GitError(f"push branch '{branch}' failed: {detail}")


def worktree_add(root: Path, path: Path, branch: str, base: str, reset: bool) -> None:
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


def worktree_add_detached(root: Path, path: Path, rev: str) -> None:
    """Check `rev` out, detached, into its own working tree at `path` —
    read-only use; no branch is created or moved."""
    path.parent.mkdir(parents=True, exist_ok=True)
    proc = _run(root, "worktree", "add", "--detach", str(path), rev)
    if proc.returncode != 0:
        raise GitError(f"git worktree add --detach {rev} failed: {proc.stderr.strip()}")


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


def origin_head_ref(root: Path) -> str:
    """`origin/<branch>` resolved from `refs/remotes/origin/HEAD` only --
    never falling back to the checked-out branch the way `default_branch`
    does (that fallback exists for callers with no remote at all, and stays
    unchanged for them). `git remote add` + `push -u` does not itself set
    `origin/HEAD` -- only `git remote set-head origin --auto` (or an
    explicit branch) does -- so a caller that must compare against the
    repo's real default branch, not whatever happens to be checked out
    right now, needs this narrower behaviour and raises instead of
    silently guessing.
    """
    proc = _run(root, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    prefix = "refs/remotes/"
    ref = proc.stdout.strip()
    if proc.returncode != 0 or not ref.startswith(prefix):
        raise GitError(
            "origin/HEAD is not set — run `git remote set-head origin --auto`"
        )
    return ref[len(prefix) :]


def valid_branch_name(root: Path, name: str) -> bool:
    """True when `name` is a plain, well-formed branch name (not `HEAD`, not
    an `@{-1}`-style shorthand)."""
    if name == "HEAD":
        return False
    proc = _run(root, "check-ref-format", "--branch", name)
    return proc.returncode == 0 and proc.stdout.strip() == name


def commits_ahead(root: Path, base: str, head: str) -> int | None:
    """Commits in `head` not in `base`; None when `base` does not exist."""
    if _run(root, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}").returncode:
        return None
    proc = _run(root, "rev-list", "--count", f"{base}..{head}")
    if proc.returncode != 0:
        raise GitError(f"could not compare {base} and {head}: {proc.stderr.strip()}")
    return int(proc.stdout.strip())


def is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    """Is commit `ancestor` reachable from `descendant`? A missing rev is no."""
    proc = _run(root, "merge-base", "--is-ancestor", ancestor, descendant)
    if proc.returncode not in (0, 1, 128):
        raise GitError(
            f"could not compare {ancestor} and {descendant}: {proc.stderr.strip()}"
        )
    return proc.returncode == 0


def resolve_commit(root: Path, rev: str) -> str:
    """Full sha of `rev`; GitError if it does not name a commit."""
    proc = _run(root, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    if proc.returncode != 0:
        raise GitError(
            f"rev '{rev}' does not exist in the repo (force-push or shallow clone?)"
        )
    return proc.stdout.strip()


def ls_tree(root: Path, rev: str, relpath: str) -> list[str]:
    """POSIX paths of the blobs under `relpath` at `rev`, repo-relative.

    Empty when `relpath` is absent at `rev`; GitError when `rev` is missing
    (same split as `path_exists_at`)."""
    sha = resolve_commit(root, rev)
    posix_relpath = relpath.replace("\\", "/")
    proc = _run(root, "ls-tree", "-r", "-z", "--name-only", sha, "--", posix_relpath)
    if proc.returncode != 0:
        raise GitError(
            f"git ls-tree failed for '{posix_relpath}': {proc.stderr.strip()}"
        )
    return [p for p in proc.stdout.split("\0") if p]


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
        raise GitError(
            f"rev '{rev}' does not exist in the repo (force-push or shallow clone?)"
        )
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
                key,
                value,
                root,
                proc.returncode,
                proc.stderr.strip(),
            )
