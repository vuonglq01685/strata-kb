import hashlib
import time
from pathlib import Path

import pytest

from center_kb import gitio, hub as hub_mod


CRED = "https://x-access-token:ghs_SECRETTOKEN@github.com/org/kb-hub.git"
STRIPPED = "https://github.com/org/kb-hub.git"
TOKEN = "ghs_SECRETTOKEN"

# localhost:1 -- connection refused instantly, no network dependency. Used
# wherever a test actually has to invoke git against a "remote" (clone,
# push, pull) with a credential-bearing URL/token: the mechanism (argv/env)
# is what is under test, never the network outcome.
UNREACHABLE_CRED = f"https://x-access-token:{TOKEN}@localhost:1/hub.git"
UNREACHABLE_STRIPPED = "https://localhost:1/hub.git"


def _spy_git_calls(monkeypatch):
    """Wrap gitio.subprocess.run to record (argv, env) for every git call
    while still running real git -- the reviewer's own measurement method,
    and the batch's sanctioned technique ("no mocking library -- real git,
    real filesystem, pytest monkeypatch")."""
    calls: list[dict] = []
    real_run = gitio.subprocess.run

    def spy(cmd, **kwargs):
        calls.append({"argv": list(cmd), "env": kwargs.get("env")})
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(gitio.subprocess, "run", spy)
    return calls


def _matching(calls, needle):
    return [c for c in calls if needle in c["argv"]]


def _repo_with_unreachable_origin(tmp_path, run_git):
    root = tmp_path / "repo"
    root.mkdir()
    run_git(root, "init", "-b", "main")
    run_git(root, "config", "user.email", "t@t")
    run_git(root, "config", "user.name", "t")
    (root / "f.txt").write_text("x", encoding="utf-8")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "init")
    run_git(root, "remote", "add", "origin", UNREACHABLE_STRIPPED)
    return root


def test_split_credentials_separates_url_from_token():
    url, token = gitio.split_credentials(CRED)
    assert url == STRIPPED
    assert token == "ghs_SECRETTOKEN"


def test_split_credentials_leaves_a_plain_url_alone():
    assert gitio.split_credentials(STRIPPED) == (STRIPPED, None)


def test_split_credentials_leaves_ssh_and_local_paths_alone():
    assert gitio.split_credentials("git@github.com:org/repo.git")[1] is None
    assert gitio.split_credentials("/srv/kb-hub")[1] is None


def test_credential_env_carries_the_token_out_of_argv():
    env = gitio.credential_env(STRIPPED, "ghs_SECRETTOKEN")
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == f"http.{STRIPPED}.extraheader"
    assert env["GIT_CONFIG_VALUE_0"].startswith("Authorization: Basic ")
    assert "ghs_SECRETTOKEN" not in env["GIT_CONFIG_KEY_0"]


def test_credential_env_is_empty_without_a_token():
    assert gitio.credential_env(STRIPPED, None) == {}


def test_clone_sends_credential_via_env_and_scrubs_argv(tmp_path, monkeypatch):
    """I3: the old version of this test cloned a local path, where
    split_credentials always returns token=None -- clone's whole credential
    handling could be reverted (mutant A) with a green suite. Drive it
    through a credential-bearing URL shape instead, and assert on the
    command actually sent to git, not on an artefact afterward."""
    calls = _spy_git_calls(monkeypatch)
    dest = tmp_path / "dest"
    with pytest.raises(gitio.GitError) as exc:
        gitio.clone(UNREACHABLE_CRED, dest)
    assert TOKEN not in str(exc.value)

    clone_calls = _matching(calls, "clone")
    assert clone_calls, "clone never invoked git"
    argv, env = clone_calls[0]["argv"], clone_calls[0]["env"]
    assert not any(TOKEN in part for part in argv)
    assert UNREACHABLE_STRIPPED in argv
    assert env is not None
    assert env["GIT_CONFIG_KEY_0"] == f"http.{UNREACHABLE_STRIPPED}.extraheader"
    assert env["GIT_CONFIG_VALUE_0"].startswith("Authorization: Basic ")
    assert TOKEN not in env["GIT_CONFIG_VALUE_0"]


def test_push_sends_credential_via_env_not_argv(tmp_path, run_git, monkeypatch):
    """C1: gitio.push had no credential parameter at all -- every hub push
    after Task 11 stripped the token from origin went out unauthenticated."""
    root = _repo_with_unreachable_origin(tmp_path, run_git)
    calls = _spy_git_calls(monkeypatch)
    with pytest.raises(gitio.GitError) as exc:
        gitio.push(root, TOKEN)
    assert TOKEN not in str(exc.value)

    push_calls = _matching(calls, "push")
    assert push_calls
    argv, env = push_calls[0]["argv"], push_calls[0]["env"]
    assert not any(TOKEN in part for part in argv)
    assert env is not None
    assert env["GIT_CONFIG_VALUE_0"].startswith("Authorization: Basic ")
    assert TOKEN not in env["GIT_CONFIG_VALUE_0"]


def test_pull_rebase_sends_credential_via_env_not_argv(tmp_path, run_git, monkeypatch):
    """C1: gitio.pull_rebase (the direct-push retry path) was also left
    unauthenticated -- a rejected push's own recovery could never succeed
    against a credentialed hub."""
    root = _repo_with_unreachable_origin(tmp_path, run_git)
    calls = _spy_git_calls(monkeypatch)
    with pytest.raises(gitio.GitError) as exc:
        gitio.pull_rebase(root, TOKEN)
    assert TOKEN not in str(exc.value)

    pull_calls = _matching(calls, "pull")
    assert pull_calls
    argv, env = pull_calls[0]["argv"], pull_calls[0]["env"]
    assert not any(TOKEN in part for part in argv)
    assert env is not None
    assert env["GIT_CONFIG_VALUE_0"].startswith("Authorization: Basic ")


def test_push_branch_sends_credential_via_env_not_argv(tmp_path, run_git, monkeypatch):
    """C1: gitio.push_branch (the PR-mode publish path and intake's
    fallback push) was also left unauthenticated."""
    root = _repo_with_unreachable_origin(tmp_path, run_git)
    calls = _spy_git_calls(monkeypatch)
    with pytest.raises(gitio.GitError) as exc:
        gitio.push_branch(root, "publish/x", TOKEN)
    assert TOKEN not in str(exc.value)

    push_calls = _matching(calls, "publish/x")
    assert push_calls
    argv, env = push_calls[0]["argv"], push_calls[0]["env"]
    assert not any(TOKEN in part for part in argv)
    assert env is not None
    assert env["GIT_CONFIG_VALUE_0"].startswith("Authorization: Basic ")


def test_pull_with_explicit_token_and_no_url_sends_credential_via_env(
    tmp_path, run_git, monkeypatch
):
    """C1: intake.py:377's shape -- url=None (falls back to the ALREADY
    stripped remote_url), token supplied out-of-band from HubHandle.token.
    Before the fix this fell back to remote_url(root), silently offering no
    credential at all."""
    root = _repo_with_unreachable_origin(tmp_path, run_git)
    calls = _spy_git_calls(monkeypatch)
    with pytest.raises(gitio.GitError) as exc:
        gitio.pull(root, token=TOKEN)
    assert TOKEN not in str(exc.value)

    pull_calls = _matching(calls, "pull")
    assert pull_calls
    argv, env = pull_calls[0]["argv"], pull_calls[0]["env"]
    assert not any(TOKEN in part for part in argv)
    assert env is not None
    assert env["GIT_CONFIG_VALUE_0"].startswith("Authorization: Basic ")


def test_push_branch_with_token_sends_credential_via_env_not_argv(
    tmp_path, run_git, monkeypatch
):
    """I4: push_branch_with_token had no test at all -- reverting it to a
    token-in-argv push (rebuilding https://x-access-token:<token>@...) left
    125 tests green."""
    root = _repo_with_unreachable_origin(tmp_path, run_git)
    calls = _spy_git_calls(monkeypatch)
    with pytest.raises(gitio.GitError) as exc:
        gitio.push_branch_with_token(root, UNREACHABLE_STRIPPED, TOKEN, "publish/x")
    assert TOKEN not in str(exc.value)

    push_calls = _matching(calls, "publish/x:publish/x")
    assert push_calls
    argv, env = push_calls[0]["argv"], push_calls[0]["env"]
    assert not any(TOKEN in part for part in argv)
    assert env is not None
    assert env["GIT_CONFIG_VALUE_0"].startswith("Authorization: Basic ")


def test_push_branch_with_token_pushes_to_a_real_remote(tmp_path, run_git):
    """I4: no happy-path test existed either -- prove the refspec is right,
    not just that the token stays out of argv."""
    origin = tmp_path / "origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    root = tmp_path / "repo"
    run_git(tmp_path, "clone", str(origin), str(root))
    run_git(root, "config", "user.name", "t")
    run_git(root, "config", "user.email", "t@t")
    (root / "a.txt").write_text("v1", encoding="utf-8")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "v1")
    run_git(root, "checkout", "-b", "publish/demo")
    gitio.push_branch_with_token(root, str(origin), "", "publish/demo")
    out = run_git(origin, "branch")
    assert "publish/demo" in out


def test_cache_key_survives_a_token_rotation(tmp_path, monkeypatch):
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "cache"))
    key_a = hub_mod.cache_key(CRED)
    key_b = hub_mod.cache_key(
        "https://x-access-token:ghs_ROTATED@github.com/org/kb-hub.git"
    )
    assert key_a == key_b
    assert key_a == hashlib.sha1(STRIPPED.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]


@pytest.mark.skipif(
    not hasattr(__import__("os"), "geteuid"), reason="POSIX mode bits only"
)
def test_cache_directory_is_private(tmp_path, monkeypatch):
    import stat

    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "cache"))
    base = hub_mod.ensure_cache_base()
    assert stat.S_IMODE(base.stat().st_mode) == 0o700


def test_legacy_cache_with_a_credentialed_remote_is_rewritten(tmp_path, run_git):
    clone = tmp_path / "legacy"
    clone.mkdir()
    run_git(tmp_path, "init", str(clone))
    run_git(clone, "remote", "add", "origin", CRED)
    hub_mod.strip_remote_credentials(clone)
    assert gitio.remote_url(clone) == STRIPPED


def test_resolve_hub_uses_the_stripped_key_cache_and_rewrites_its_origin(
    tmp_path, monkeypatch, run_git
):
    """I5: mutant C+E (cache path reverted to sha1(hub)[:12] and both
    strip_remote_credentials calls deleted) left 60 tests passing -- nothing
    exercised resolve_hub's own use of the stripped cache_key together with
    the strip together. Pre-create the cache at the address a CORRECT
    implementation would compute (sha1 of the stripped URL, independent of
    hub_mod.cache_key so a reverted cache_key can't rubber-stamp itself);
    under the reverted code resolve_hub would look in the wrong place, find
    nothing, and try to clone the fake credentialed URL for real."""
    cache_base = tmp_path / "cache"
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(cache_base))
    bare = tmp_path / "bare.git"
    run_git(tmp_path, "init", "--bare", str(bare))

    key = hashlib.sha1(UNREACHABLE_STRIPPED.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
    cache = cache_base / key
    cache_base.mkdir(parents=True, exist_ok=True)
    run_git(tmp_path, "clone", str(bare), str(cache))
    run_git(cache, "remote", "set-url", "origin", UNREACHABLE_CRED)
    # Mark it as a "healthy" (post-Task-12) cache -- resolve_hub's OWN
    # legacy-cache heal (item 3 of this fix round) would otherwise discard
    # and try to re-clone this fixture from the unreachable URL, which is a
    # different regression than the one this test is about.
    run_git(cache, "config", "core.autocrlf", "false")
    (cache_base / f"{key}.last-pull").write_text(str(time.time()), encoding="utf-8")

    handle = hub_mod.resolve_hub(UNREACHABLE_CRED)
    assert handle is not None
    assert handle.root == cache
    assert gitio.remote_url(cache) == UNREACHABLE_STRIPPED
    assert handle.token == TOKEN


def test_doctor_reports_a_clone_whose_credential_could_not_be_stripped(
    hub_worktree, git_kb, run_git
):
    """The rewrite is best-effort -- a read-only .git/config, or a remote
    named something other than origin, leaves the token in place. An operator
    has to be told, because the file is the thing that needs rotating."""
    from center_kb.doctor import check_hub
    from center_kb.hub import HubHandle

    run_git(hub_worktree, "remote", "add", "upstream", CRED)
    issues, _ = check_hub(git_kb["kb"], HubHandle(root=hub_worktree))
    assert any(
        "credential" in i.message and i.level == "warning" for i in issues
    )
    assert not any("ghs_SECRETTOKEN" in i.message for i in issues)
    # Minor 3 (Wave G fix round 2): user-facing messages start lower-case --
    # this one used to start "{handle.root} still stores...", capitalised
    # because a path happened to start the sentence.
    credential_issue = next(i for i in issues if "credential" in i.message)
    assert credential_issue.message[0].islower()


# --- Wave G fix round 2, item 1: the repr=False guard the round 1 brief
# required a test for was never committed -- deleting it left both the
# targeted AND the full suite green.


def test_hubhandle_repr_and_str_omit_the_token():
    handle = hub_mod.HubHandle(root=Path("/tmp/hub"), token=TOKEN)
    assert TOKEN not in repr(handle)
    assert TOKEN not in str(handle)
    assert TOKEN not in "{}".format(handle)


def _seed_hub_with_bare_origin(tmp_path, run_git) -> Path:
    origin = tmp_path / "hub-origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    seed = tmp_path / "hub-seed"
    (seed / ".kb").mkdir(parents=True)
    (seed / "federation").mkdir()
    (seed / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8", newline="\n")
    (seed / "federation" / ".gitkeep").write_text("", encoding="utf-8")
    run_git(tmp_path, "init", str(seed))
    run_git(seed, "add", "-A")
    run_git(seed, "commit", "-m", "hub v0")
    run_git(seed, "remote", "add", "origin", str(origin))
    run_git(seed, "push", "-u", "origin", "HEAD")
    return origin


def _seed_credentialed_cache(tmp_path, origin, token: str, run_git, monkeypatch) -> Path:
    """Pre-seed a managed-cache clone at the address a credential-bearing
    fake hub_ref hashes to (cache_key hashes the STRIPPED url), with a real
    LOCAL origin -- so publish() actually authenticates/pushes for real,
    while the (never-dereferenced) fake host only needs to line up for the
    token extraction + cache-key match. Same trick
    test_publish.py's test_direct_publish_threads_the_hub_token_into_the_push
    uses for the one call site that IS already protected."""
    stripped = "https://example.invalid/hub.git"
    cache_base = tmp_path / "cache"
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(cache_base))
    key = hashlib.sha1(stripped.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
    cache = cache_base / key
    cache_base.mkdir(parents=True, exist_ok=True)
    # -c core.autocrlf=false at clone time (not just configured afterwards)
    # is load-bearing on a machine with global core.autocrlf=true (Git for
    # Windows' own installer default): checkout during the clone would
    # convert the LF blobs to CRLF in the working tree first, and setting
    # the local config a line later cannot retroactively re-normalise files
    # already on disk -- the cache would be born permanently "dirty" (git
    # status shows .kb/index.yaml modified forever), which is invisible to
    # every git command used here except `pull --rebase`, which refuses to
    # run against unstaged changes.
    run_git(tmp_path, "-c", "core.autocrlf=false", "clone", str(origin), str(cache))
    run_git(cache, "config", "core.autocrlf", "false")  # a "healthy" cache
    run_git(cache, "config", "user.name", "test")
    run_git(cache, "config", "user.email", "test@test.local")
    (cache_base / f"{key}.last-pull").write_text(str(time.time()), encoding="utf-8")
    return cache


def test_rebase_retry_threads_the_hub_token_into_pull_rebase(
    tmp_path, run_git, monkeypatch, git_kb
):
    """Important 1 (mutant MU3): publish._push_with_retry's rebase-retry
    call site (gitio.pull_rebase(handle.root, handle.token)) dropped the
    token with 87 tests still green -- the gitio-level pull_rebase test
    (above) supplies a token directly and cannot see this call site regress.
    Force a genuine push rejection (origin moves ahead between the cache's
    clone and its own push) so the retry path is actually exercised, not
    merely constructed."""
    from center_kb.publish import publish

    origin = _seed_hub_with_bare_origin(tmp_path, run_git)
    fake_hub_ref = "https://x-access-token:ghs_REBASETOKEN@example.invalid/hub.git"
    _seed_credentialed_cache(tmp_path, origin, "ghs_REBASETOKEN", run_git, monkeypatch)

    # Advance origin AFTER the cache was cloned from it -- the cache's own
    # first push attempt below is therefore rejected (non-fast-forward).
    seed = tmp_path / "hub-seed"
    (seed / "extra.txt").write_text("x", encoding="utf-8")
    run_git(seed, "add", "-A")
    run_git(seed, "commit", "-m", "concurrent publisher")
    run_git(seed, "push", "origin", "HEAD")

    calls: list[dict] = []
    real_run = gitio.subprocess.run

    def spy(cmd, **kwargs):
        calls.append({"argv": list(cmd), "env": kwargs.get("env")})
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(gitio.subprocess, "run", spy)

    report = publish(git_kb["kb"], fake_hub_ref, repo_id="child", mode="direct")

    rebase_calls = [
        c for c in calls
        if c["argv"][:2] == ["git", "pull"] and "--rebase" in c["argv"]
    ]
    assert rebase_calls, "publish() never retried with pull --rebase"
    env = rebase_calls[0]["env"]
    assert env is not None, "the rebase retry carried no credential env at all"
    assert env["GIT_CONFIG_VALUE_0"].startswith("Authorization: Basic ")
    assert "ghs_REBASETOKEN" not in rebase_calls[0]["argv"]
    assert report.pushed is True


def test_pr_path_threads_the_hub_token_into_the_branch_push(
    tmp_path, run_git, monkeypatch, git_kb
):
    """Important 1 (mutant MU1): publish._publish_pr's branch push
    (gitio.push_branch(handle.root, branch, handle.token)) dropped the token
    with 87 tests still green. Force PR mode via the ghio test seams
    test_publish.py's own PR-mode tests use."""
    from center_kb import ghio
    from center_kb.publish import publish

    origin = _seed_hub_with_bare_origin(tmp_path, run_git)
    fake_hub_ref = "https://x-access-token:ghs_PRTOKEN@example.invalid/hub.git"
    _seed_credentialed_cache(tmp_path, origin, "ghs_PRTOKEN", run_git, monkeypatch)

    monkeypatch.setattr(ghio, "can_open_pr", lambda root: True)
    monkeypatch.setattr(ghio, "pr_url_for_branch", lambda root, branch: "")
    monkeypatch.setattr(
        ghio, "create_pr",
        lambda root, branch, title, body: "https://github.com/org/hub/pull/1",
    )

    calls: list[dict] = []
    real_run = gitio.subprocess.run

    def spy(cmd, **kwargs):
        calls.append({"argv": list(cmd), "env": kwargs.get("env")})
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(gitio.subprocess, "run", spy)

    report = publish(git_kb["kb"], fake_hub_ref, repo_id="child", mode="pr")

    push_calls = [
        c for c in calls
        if c["argv"][:2] == ["git", "push"] and "publish/child" in c["argv"]
    ]
    assert push_calls, "publish() in PR mode never pushed the branch"
    env = push_calls[0]["env"]
    assert env is not None, "the branch push carried no credential env at all"
    assert env["GIT_CONFIG_VALUE_0"].startswith("Authorization: Basic ")
    assert "ghs_PRTOKEN" not in push_calls[0]["argv"]
    assert report.pr_url == "https://github.com/org/hub/pull/1"
