import ast
import inspect
import subprocess
import sys
from pathlib import Path

import anyio
import pytest

from strata_kb import gitio


def test_git_root_finds_repo_from_kb_dir(git_kb):
    assert gitio.git_root(git_kb["kb"]) == git_kb["root"]


def test_git_root_raises_outside_repo(tmp_path: Path):
    with pytest.raises(gitio.GitError):
        gitio.git_root(tmp_path)


def test_head_commit_returns_short_hash(git_kb):
    assert gitio.head_commit(git_kb["root"]) == git_kb["rev2"]


def test_rev_exists(git_kb):
    assert gitio.rev_exists(git_kb["root"], git_kb["rev1"])
    assert not gitio.rev_exists(git_kb["root"], "deadbeef")


def test_read_at_returns_old_content(git_kb):
    path = git_kb["kb"] / "demo-doc" / "ch1-records.md"
    old = gitio.read_at(git_kb["root"], git_kb["rev1"], path)
    assert "designation and type fields" in old
    new = gitio.read_at(git_kb["root"], git_kb["rev2"], path)
    assert "amended multiple code field" in new


def test_read_at_missing_file_returns_none(git_kb):
    path = git_kb["kb"] / "demo-doc" / "does-not-exist.md"
    assert gitio.read_at(git_kb["root"], git_kb["rev1"], path) is None


def test_read_at_bad_rev_raises(git_kb):
    path = git_kb["kb"] / "index.yaml"
    with pytest.raises(gitio.GitError):
        gitio.read_at(git_kb["root"], "deadbeef", path)


def test_read_at_path_outside_repo_raises(git_kb, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "x.md"
    with pytest.raises(gitio.GitError):
        gitio.read_at(git_kb["root"], git_kb["rev1"], outside)


def test_neutralize_line_endings_logs_on_config_failure(tmp_path, caplog):
    """M6: `git config` is best-effort here, but a silent failure inside
    clone() would re-open F-D10 for every later checkout in that clone with
    no signal at all -- at minimum it must log."""
    import logging

    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()
    with caplog.at_level(logging.DEBUG, logger="strata_kb.gitio"):
        gitio.neutralize_line_endings(not_a_repo)  # must not raise
    assert "core.autocrlf" in caplog.text


def test_is_dirty(git_kb):
    assert not gitio.is_dirty(git_kb["root"], git_kb["kb"])
    (git_kb["kb"] / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    assert gitio.is_dirty(git_kb["root"], git_kb["kb"])


# --- Phase 3: clone/pull/commit/push ---


@pytest.fixture
def bare_origin(tmp_path, run_git):
    """Bare repo used as origin + a 'seed' clone that has committed 1 file."""
    bare = tmp_path / "origin.git"
    bare.mkdir()
    run_git(bare, "init", "--bare")
    seed = tmp_path / "seed"
    run_git(tmp_path, "clone", str(bare), "seed")
    (seed / "a.txt").write_text("v1", encoding="utf-8")
    run_git(seed, "add", "-A")
    run_git(seed, "commit", "-m", "v1")
    run_git(seed, "push", "origin", "HEAD")
    return {"bare": bare, "seed": seed}


def test_clone_and_pull_roundtrip(tmp_path, run_git, bare_origin):
    dest = tmp_path / "clone2"
    gitio.clone(str(bare_origin["bare"]), dest)
    assert (dest / "a.txt").read_text(encoding="utf-8") == "v1"
    # origin has a new commit → pull picks it up
    seed = bare_origin["seed"]
    (seed / "a.txt").write_text("v2", encoding="utf-8")
    run_git(seed, "add", "-A")
    run_git(seed, "commit", "-m", "v2")
    run_git(seed, "push", "origin", "HEAD")
    gitio.pull(dest)
    assert (dest / "a.txt").read_text(encoding="utf-8") == "v2"


def test_clone_bad_url_raises(tmp_path):
    with pytest.raises(gitio.GitError):
        gitio.clone(str(tmp_path / "does-not-exist"), tmp_path / "dest")


def test_commit_all_returns_false_when_clean(bare_origin, run_git):
    seed = bare_origin["seed"]
    run_git(seed, "config", "user.name", "test")
    run_git(seed, "config", "user.email", "test@test.local")
    assert gitio.commit_all(seed, "no-op") is False


def test_commit_all_and_push(bare_origin, run_git, tmp_path):
    seed = bare_origin["seed"]
    run_git(seed, "config", "user.name", "test")
    run_git(seed, "config", "user.email", "test@test.local")
    (seed / "b.txt").write_text("new", encoding="utf-8")
    assert gitio.commit_all(seed, "add b") is True
    gitio.push(seed)
    check = tmp_path / "check"
    gitio.clone(str(bare_origin["bare"]), check)
    assert (check / "b.txt").exists()


def test_push_rejected_then_pull_rebase_recovers(tmp_path, run_git, bare_origin):
    # clone2 lags behind origin → push fails → pull_rebase → push OK
    dest = tmp_path / "clone2"
    gitio.clone(str(bare_origin["bare"]), dest)
    run_git(dest, "config", "user.name", "test")
    run_git(dest, "config", "user.email", "test@test.local")
    seed = bare_origin["seed"]
    (seed / "a.txt").write_text("upstream", encoding="utf-8")
    run_git(seed, "add", "-A")
    run_git(seed, "commit", "-m", "upstream")
    run_git(seed, "push", "origin", "HEAD")
    (dest / "c.txt").write_text("local", encoding="utf-8")
    gitio.commit_all(dest, "add c")
    with pytest.raises(gitio.GitError):
        gitio.push(dest)
    gitio.pull_rebase(dest)
    gitio.push(dest)


def test_commit_paths_excludes_files_outside_paths(bare_origin, run_git):
    seed = bare_origin["seed"]
    run_git(seed, "config", "user.name", "test")
    run_git(seed, "config", "user.email", "test@test.local")
    (seed / "federation").mkdir()
    (seed / "federation" / "f.txt").write_text("in", encoding="utf-8")
    (seed / "outside.txt").write_text("out", encoding="utf-8")
    assert gitio.commit_paths(seed, "add federation", ["federation"]) is True
    status = run_git(seed, "status", "--porcelain")
    assert "outside.txt" in status  # still untracked, not committed by mistake
    assert "federation" not in status  # committed, clean


def test_commit_paths_returns_false_when_clean(bare_origin, run_git):
    seed = bare_origin["seed"]
    run_git(seed, "config", "user.name", "test")
    run_git(seed, "config", "user.email", "test@test.local")
    # a.txt is already committed (bare_origin fixture) → nothing changed in scope
    assert gitio.commit_paths(seed, "no-op", ["a.txt"]) is False


def test_has_remote_and_remote_url(bare_origin, fixture_kb, run_git):
    assert gitio.has_remote(bare_origin["seed"]) is True
    assert gitio.remote_url(bare_origin["seed"]).endswith("origin.git")
    root = fixture_kb.parent
    run_git(root, "init")
    assert gitio.has_remote(root) is False
    assert gitio.remote_url(root) == ""


def test_branch_helpers_roundtrip(tmp_path, run_git):
    from strata_kb import gitio

    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.txt").write_text("v1", encoding="utf-8")
    run_git(root, "init")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "v1")
    main = gitio.current_branch(root)

    gitio.checkout_branch(root, "publish/demo", main)
    assert gitio.current_branch(root) == "publish/demo"
    (root / "a.txt").write_text("v2", encoding="utf-8")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "v2")

    gitio.checkout(root, main)
    assert gitio.current_branch(root) == main
    assert (root / "a.txt").read_text(encoding="utf-8") == "v1"

    # a second checkout -B resets the branch back to start_point
    gitio.checkout_branch(root, "publish/demo", main)
    assert (root / "a.txt").read_text(encoding="utf-8") == "v1"
    gitio.checkout(root, main)


def test_push_branch_to_local_bare_origin(tmp_path, run_git):
    from strata_kb import gitio

    origin = tmp_path / "origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    root = tmp_path / "repo"
    run_git(tmp_path, "clone", str(origin), str(root))
    run_git(root, "config", "user.name", "t")
    run_git(root, "config", "user.email", "t@t")
    (root / "a.txt").write_text("v1", encoding="utf-8")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "v1")
    gitio.push_branch(root, gitio.current_branch(root))
    gitio.checkout_branch(root, "publish/demo", "HEAD")
    gitio.push_branch(root, "publish/demo")
    out = run_git(origin, "branch")
    assert "publish/demo" in out


def test_worktree_add_and_remove_leave_the_main_tree_on_its_branch(tmp_path, run_git):
    from strata_kb import gitio

    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(tmp_path, "init", str(repo))
    (repo / "f.txt").write_text("v1\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-m", "v1")
    base = gitio.current_branch(repo)

    wt = tmp_path / "wt"
    gitio.worktree_add(repo, wt, "publish/alpha", base, reset=True)
    assert (wt / "f.txt").is_file()
    assert gitio.current_branch(wt) == "publish/alpha"
    assert gitio.current_branch(repo) == base

    (wt / "f.txt").write_text("v2\n", encoding="utf-8")
    run_git(wt, "add", "-A")
    run_git(wt, "commit", "-m", "v2")
    assert (repo / "f.txt").read_text(encoding="utf-8") == "v1\n"

    gitio.worktree_remove(repo, wt)
    assert not wt.exists()
    assert gitio.rev_exists(repo, "publish/alpha")


def test_worktree_add_can_reuse_an_existing_branch(tmp_path, run_git):
    from strata_kb import gitio

    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(tmp_path, "init", str(repo))
    (repo / "f.txt").write_text("v1\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-m", "v1")
    base = gitio.current_branch(repo)
    run_git(repo, "branch", "publish/alpha")

    # advance publish/alpha ahead of base -- reset=False must preserve this
    # commit; an implementation that always used `-B branch path base`
    # would destroy it and still pass a check that only looks at the
    # branch name.
    run_git(repo, "checkout", "publish/alpha")
    (repo / "f.txt").write_text("v2\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-m", "v2 on alpha")
    alpha_tip = gitio.head_commit(repo)
    run_git(repo, "checkout", base)

    wt = tmp_path / "wt"
    gitio.worktree_add(repo, wt, "publish/alpha", base, reset=False)
    assert gitio.current_branch(wt) == "publish/alpha"
    assert gitio.head_commit(wt) == alpha_tip
    assert (wt / "f.txt").read_text(encoding="utf-8") == "v2\n"
    gitio.worktree_remove(repo, wt)


def test_worktree_prune_forgets_a_deleted_worktree(tmp_path, run_git):
    import shutil

    from strata_kb import gitio

    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(tmp_path, "init", str(repo))
    (repo / "f.txt").write_text("v1\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-m", "v1")
    wt = tmp_path / "wt"
    gitio.worktree_add(repo, wt, "publish/alpha", gitio.current_branch(repo), reset=True)
    shutil.rmtree(wt)  # simulate a crashed publish
    gitio.worktree_prune(repo)
    assert "wt" not in run_git(repo, "worktree", "list")


def test_default_branch_and_path_exists_at(tmp_path, run_git):
    from strata_kb import gitio

    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(tmp_path, "init", str(repo))
    (repo / "federation").mkdir()
    (repo / "federation" / "alpha.txt").write_text("x\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-m", "v1")
    branch = gitio.default_branch(repo)
    assert branch == gitio.current_branch(repo)
    assert gitio.path_exists_at(repo, branch, "federation/alpha.txt") is True
    assert gitio.path_exists_at(repo, branch, "federation/beta.txt") is False


def test_default_branch_reads_origin_head_and_strips_the_origin_prefix(tmp_path, run_git):
    from strata_kb import gitio

    origin = tmp_path / "origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    root = tmp_path / "repo"
    run_git(tmp_path, "clone", str(origin), str(root))
    run_git(root, "config", "user.name", "t")
    run_git(root, "config", "user.email", "t@t")
    (root / "a.txt").write_text("v1", encoding="utf-8")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "v1")
    branch = gitio.current_branch(root)
    gitio.push_branch(root, branch)
    run_git(root, "fetch", "origin")
    run_git(root, "symbolic-ref", "refs/remotes/origin/HEAD", f"refs/remotes/origin/{branch}")

    assert gitio.default_branch(root) == branch


def test_path_exists_at_normalises_windows_separators(tmp_path, run_git):
    from strata_kb import gitio

    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(tmp_path, "init", str(repo))
    (repo / "federation").mkdir()
    (repo / "federation" / "alpha.txt").write_text("x\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-m", "v1")
    branch = gitio.current_branch(repo)

    assert gitio.path_exists_at(repo, branch, "federation\\alpha.txt") is True


def test_path_exists_at_raises_on_unresolvable_rev(tmp_path, run_git):
    from strata_kb import gitio

    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(tmp_path, "init", str(repo))
    (repo / "federation").mkdir()
    (repo / "federation" / "alpha.txt").write_text("x\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-m", "v1")
    branch = gitio.current_branch(repo)

    with pytest.raises(gitio.GitError):
        gitio.path_exists_at(repo, "publish/does-not-exist", "federation/alpha.txt")

    # a resolvable rev with a missing path still returns a plain False
    assert gitio.path_exists_at(repo, branch, "federation/missing.txt") is False


# --- P55/P57: no subprocess.run that can reach git may inherit the ---
# --- caller's stdin, however the call is spelled ---------------------
#
# gitio is called from the CLI, the MCP stdio server, the HTTP server and
# the intake worker -- it cannot assume a console. When the caller is an
# MCP stdio server, its stdin *is* the JSON-RPC channel: a git child that
# inherits it can block reading it forever (Wave J Critical -- the MCP
# server's first git call, hub._cache_needs_reclone's
# gitio.config_value(..., local=True), hung every `kb_search` call on this
# branch). The fix is stdin=subprocess.DEVNULL on every subprocess.run in
# this module.
#
# Round 2 (P57): the round-1 checker only asked "is a `stdin=` keyword
# present" -- and three ordinary-looking rewrites slip past that question:
# an aliased module import (`import subprocess as sp; sp.run(...)`), an
# aliased `from subprocess import run as _x; _x(...)`, and `stdin=None`,
# which is syntactically an explicit stdin= and semantically identical to
# inheriting the parent's -- the exact hazard P55 forbids. The checker
# below resolves import aliases (module-level or local) and dynamic
# dispatch (`getattr(subprocess, "run")`), and accepts `stdin=` only when
# it can prove the value is `subprocess.DEVNULL`; everything it cannot
# prove -- missing entirely, `stdin=None`, folded into `**kwargs`, or bound
# to a name/expression it cannot resolve -- is reported as an offender.
# Fail closed, not open.


def _resolve_subprocess_run_aliases(tree: ast.AST) -> tuple[set[str], set[str]]:
    """Local names that resolve to the `subprocess` module itself (for
    `<name>.run(...)` / `getattr(<name>, "run")(...)`), and local names
    that resolve directly to `subprocess.run` (for a bare `<name>(...)`
    call) -- walked over the whole tree, not just the module body, so a
    local `import subprocess as sp` inside a function is resolved too."""
    module_names: set[str] = set()
    run_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess":
                    module_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            for alias in node.names:
                if alias.name == "run":
                    run_names.add(alias.asname or alias.name)
    return module_names, run_names


def _is_subprocess_run_call(
    call: ast.Call, module_names: set[str], run_names: set[str]
) -> bool:
    func = call.func
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "run"
        and isinstance(func.value, ast.Name)
        and func.value.id in module_names
    ):
        return True  # subprocess.run(...) / sp.run(...)
    if isinstance(func, ast.Name) and func.id in run_names:
        return True  # run(...) / _sprun(...) via `from subprocess import run as X`
    if (
        isinstance(func, ast.Call)
        and isinstance(func.func, ast.Name)
        and func.func.id == "getattr"
        and len(func.args) >= 2
        and isinstance(func.args[0], ast.Name)
        and func.args[0].id in module_names
        and isinstance(func.args[1], ast.Constant)
        and func.args[1].value == "run"
    ):
        return True  # getattr(subprocess, "run")(...)
    return False


def _stdin_offenders_in_source(
    source: str, filename: str = "<source>"
) -> list[tuple[int, str]]:
    """P57: every call resolved as `subprocess.run` (see above) must carry
    a `stdin=` the checker can *prove* is `subprocess.DEVNULL` -- a literal
    `<subprocess-name>.DEVNULL` attribute access. Anything else -- missing
    entirely, `stdin=None`, stdin only inside `**kwargs`, or a value that
    is some other name/expression the checker has no way to evaluate --
    fails closed and is reported as an offender, naming the line."""
    tree = ast.parse(source, filename=filename)
    module_names, run_names = _resolve_subprocess_run_aliases(tree)
    offenders: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _is_subprocess_run_call(node, module_names, run_names):
            continue
        stdin_kw = None
        has_star_kwargs = False
        for kw in node.keywords:
            if kw.arg == "stdin":
                stdin_kw = kw
            elif kw.arg is None:
                has_star_kwargs = True
        if stdin_kw is None:
            reason = (
                "stdin= arrives only via **kwargs -- cannot verify statically, failing closed"
                if has_star_kwargs
                else "missing an explicit stdin="
            )
            offenders.append((node.lineno, reason))
            continue
        value = stdin_kw.value
        if isinstance(value, ast.Constant) and value.value is None:
            offenders.append((
                node.lineno,
                "stdin=None inherits the parent's stdin -- the exact hazard this check forbids",
            ))
            continue
        if (
            isinstance(value, ast.Attribute)
            and value.attr == "DEVNULL"
            and isinstance(value.value, ast.Name)
            and value.value.id in module_names
        ):
            continue  # proven safe
        offenders.append((
            node.lineno,
            "stdin= is not a literal subprocess.DEVNULL -- cannot verify statically, failing closed",
        ))
    return offenders


def _stdin_offenders_in_module(module) -> list[tuple[int, str]]:
    return _stdin_offenders_in_source(
        inspect.getsource(module), filename=str(module.__file__)
    )


def test_every_subprocess_run_call_in_gitio_has_a_verifiably_safe_stdin():
    """Structural check (P57): replaces round 1's "a stdin= keyword is
    present" question with "the value is provably subprocess.DEVNULL",
    resolved through whatever aliasing the call is spelled with. Weaker
    than the behavioural tests below (it can prove the shape of the call,
    not runtime correctness) -- kept in addition to them, not instead of
    them, per the ruling that no call site may be missing one, checked
    ones included."""
    offenders = _stdin_offenders_in_module(gitio)
    assert offenders == [], (
        f"subprocess.run() in gitio.py has an unsafe or unverifiable stdin= at: {offenders}"
    )


# --- P57 evasions: test cases against the checker itself (review-waveJ- ---
# --- verdict.md J-1) -- each below was confirmed to leave the round-1 ---
# --- checker green (`offenders == []`) before this round's fix landed. ---


def test_checker_catches_module_alias_evasion():
    """Evasion 1 (named in the review): `import subprocess as sp` then
    `sp.run(...)` with no stdin= -- an ordinary tidy-up alias the round-1
    checker's literal `node.func.value.id == "subprocess"` never saw."""
    offenders = _stdin_offenders_in_source(
        "import subprocess as sp\n"
        "def f(args):\n"
        "    return sp.run(['git', *args], capture_output=True)\n"
    )
    assert offenders, "checker must catch `sp.run(...)` (aliased module import) with no stdin="


def test_checker_catches_from_import_alias_evasion():
    """Evasion 2 (named in the review): `from subprocess import run as
    _sprun` then a bare `_sprun(...)` call -- not a `subprocess.run(...)`
    shape at all, so the round-1 checker's `ast.Attribute` pattern never
    matched it."""
    offenders = _stdin_offenders_in_source(
        "from subprocess import run as _sprun\n"
        "def f(args):\n"
        "    return _sprun(['git', *args], capture_output=True)\n"
    )
    assert offenders, (
        "checker must catch `_sprun(...)` (aliased `from subprocess import run`) with no stdin="
    )


def test_checker_catches_stdin_none_evasion():
    """Evasion 3 (named in the review, and the one that stings): `stdin=None`
    is syntactically an explicit stdin= -- the round-1 checker's
    `any(kw.arg == "stdin" ...)` accepted it -- and semantically identical
    to inheriting the parent's, the exact hazard P55 forbids."""
    offenders = _stdin_offenders_in_source(
        "import subprocess\n"
        "def f(args):\n"
        "    return subprocess.run(['git', *args], capture_output=True, stdin=None)\n"
    )
    assert offenders, (
        "checker must catch stdin=None -- it IS the inherited-stdin hazard, not a safe explicit value"
    )


def test_checker_catches_getattr_dynamic_dispatch_evasion():
    """Evasion 4 (mine): `getattr(subprocess, "run")(...)` is still
    subprocess.run, just spelled so its callee is a `Call` node rather
    than an `Attribute` node -- a checker that only pattern-matches
    `<name>.run(...)` does not merely fail to verify this call, it never
    sees it at all."""
    offenders = _stdin_offenders_in_source(
        "import subprocess\n"
        "def f(args):\n"
        "    return getattr(subprocess, 'run')(['git', *args], capture_output=True)\n"
    )
    assert offenders, (
        "checker must catch getattr(subprocess, 'run')(...) -- dynamic dispatch is still subprocess.run"
    )


def test_checker_fails_closed_on_an_unverifiable_stdin_value():
    """Not one of the four evasions above -- documents the fail-closed
    contract itself. A `stdin=` the checker cannot prove is
    `subprocess.DEVNULL` (here, a plain parameter) must be treated as an
    offender, not given the benefit of the doubt."""
    offenders = _stdin_offenders_in_source(
        "import subprocess\n"
        "def f(args, maybe_devnull):\n"
        "    return subprocess.run(['git', *args], capture_output=True, stdin=maybe_devnull)\n"
    )
    assert offenders, "an unresolvable stdin= value must fail closed, not pass by default"


def test_checker_fails_closed_when_stdin_could_be_hiding_in_kwargs():
    """Same fail-closed contract, a different unverifiable shape: stdin=
    potentially folded into a **kwargs dict the checker cannot expand
    statically."""
    offenders = _stdin_offenders_in_source(
        "import subprocess\n"
        "def f(args, opts):\n"
        "    return subprocess.run(['git', *args], capture_output=True, **opts)\n"
    )
    assert offenders, "stdin= potentially hidden inside **kwargs must fail closed too"


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="reproduces a Windows-specific overlapped-named-pipe stdio hazard "
    "(CREATE_NO_WINDOW / anyio.open_process); a plain subprocess.PIPE does "
    "not reproduce it, and this is the shape that does",
)
def test_config_value_completes_when_parent_holds_an_unwritten_stdin_pipe_open(
    tmp_path, run_git
):
    """Behavioural: reproduces the real hang, reduced to gitio.

    The reported topology: a child process's stdio is wired through a
    genuine Windows OVERLAPPED named pipe -- anyio.open_process with
    CREATE_NO_WINDOW is the exact path mcp.os.win32.create_windows_process
    takes to launch the MCP server (a plain synchronous subprocess.PIPE does
    NOT reproduce this hang; verified separately). The parent (this test)
    holds that pipe's write end open and never writes to it, exactly like
    an MCP client between sending a request and reading its response. The
    child concurrently runs its own blocking stdin read in a worker thread
    -- mirroring mcp.server.stdio.stdio_server()'s
    `async for line in TextIOWrapper(sys.stdin.buffer)` loop, which anyio
    backs with a blocking readline() in a thread pool -- and calls
    gitio.config_value(..., local=True) via anyio.to_thread.run_sync,
    exactly like a FastMCP tool body.

    Before the fix, git inherits that pipe as its own stdin and its read on
    it never resolves: this test hangs and is killed by the 15s deadline
    below. After the fix (stdin=DEVNULL on every subprocess.run in gitio),
    it returns in well under a second.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init")
    run_git(repo, "config", "core.autocrlf", "false")

    child_script = f"""
import functools, sys
from io import TextIOWrapper
import anyio
import anyio.to_thread
from strata_kb import gitio

async def main():
    stdin = anyio.wrap_file(
        TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    )

    async def reader():
        async for _line in stdin:
            pass  # never happens: nothing is ever written to this pipe

    async with anyio.create_task_group() as tg:
        tg.start_soon(reader)
        await anyio.sleep(0.2)
        result = await anyio.to_thread.run_sync(
            functools.partial(
                gitio.config_value, {str(repo)!r}, "core.autocrlf", local=True
            )
        )
        print("CHILD-RESULT:", repr(result), flush=True)
        tg.cancel_scope.cancel()

anyio.run(main)
"""

    async def _drive() -> bytes:
        process = await anyio.open_process(
            [sys.executable, "-c", child_script],
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            with anyio.fail_after(15):
                out = b""
                async for chunk in process.stdout:
                    out += chunk
                    if b"CHILD-RESULT" in out:
                        break
            return out
        finally:
            process.kill()
            with anyio.CancelScope(shield=True):
                await process.aclose()

    out = anyio.run(_drive)
    assert b"CHILD-RESULT: 'false'" in out


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="reproduces a Windows-specific overlapped-named-pipe stdio hazard "
    "(CREATE_NO_WINDOW / anyio.open_process); a plain subprocess.PIPE does "
    "not reproduce it, and this is the shape that does",
)
def test_pull_completes_when_parent_holds_an_unwritten_stdin_pipe_open(
    tmp_path, run_git, bare_origin
):
    """Behavioural (P57 item 2): the test above only exercises `_run` --
    `config_value` is a `_run` caller. `clone`/`pull`/`pull_rebase`/`push*`
    go through `_run_env` instead, and it had zero behavioural coverage:
    reverting `_run_env` alone left the test above green (measured
    `1 failed, 1 passed ... in 0.90s`, the one failure being the structural
    test) -- so an aliased-or-None regression in `_run_env`, the
    credential/network path, was caught by nothing, on any platform.

    `gitio.pull(root, url=...)` with an explicit `url` never calls
    `remote_url` (`url or remote_url(root)` short-circuits), so it never
    touches `_run` at all -- a single, clean `_run_env` call, independent
    of the `_run` coverage above (unlike `clone`, which also runs
    `neutralize_line_endings` -> `_run` afterwards and so would not
    isolate the two). Same topology as the test above: the parent holds
    the child's stdin pipe open and unwritten while the child races a
    blocking stdin reader against `gitio.pull` on a worker thread. The
    assertion is on completion and on the pulled file's content, not on
    timing -- the 15s deadline is only the failure mechanism.
    """
    seed = bare_origin["seed"]
    dest = tmp_path / "pull-dest"
    run_git(tmp_path, "clone", str(bare_origin["bare"]), "pull-dest")

    # give the clone something real to pull
    (seed / "a.txt").write_text("v2", encoding="utf-8")
    run_git(seed, "add", "-A")
    run_git(seed, "commit", "-m", "v2")
    run_git(seed, "push", "origin", "HEAD")

    child_script = f"""
import functools, sys
from io import TextIOWrapper
import anyio
import anyio.to_thread
from strata_kb import gitio

async def main():
    stdin = anyio.wrap_file(
        TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    )

    async def reader():
        async for _line in stdin:
            pass  # never happens: nothing is ever written to this pipe

    async with anyio.create_task_group() as tg:
        tg.start_soon(reader)
        await anyio.sleep(0.2)
        await anyio.to_thread.run_sync(
            functools.partial(
                gitio.pull, {str(dest)!r}, {str(bare_origin["bare"])!r}
            )
        )
        print("CHILD-RESULT: pulled", flush=True)
        tg.cancel_scope.cancel()

anyio.run(main)
"""

    async def _drive() -> bytes:
        process = await anyio.open_process(
            [sys.executable, "-c", child_script],
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            with anyio.fail_after(15):
                out = b""
                async for chunk in process.stdout:
                    out += chunk
                    if b"CHILD-RESULT" in out:
                        break
            return out
        finally:
            process.kill()
            with anyio.CancelScope(shield=True):
                await process.aclose()

    out = anyio.run(_drive)
    assert b"CHILD-RESULT: pulled" in out
    assert (dest / "a.txt").read_text(encoding="utf-8") == "v2"
