# Kind-aware `kb docker-setup` + symbol-only heading filter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `kb docker-setup` finishes the job on both repo kinds (hub: `.env` + token + `docker compose up -d`; child: Docker check + `docker compose pull`, no `.env`), and ingest stops turning PDF rule lines (`_____`) into fallback sections.

**Architecture:** Kind dispatch lives in the CLI (`cli.py`); pure logic and subprocess helpers live in `dockersetup.py` so tests monkeypatch the helpers, never real Docker. The four `kb-docker-setup` wrapper templates become kind-neutral and move to `COMMON_TEMPLATES`. The sectioner drops headings with no alphanumeric characters before they can open nodes.

**Tech Stack:** Python 3.12, Typer CLI, pytest + `typer.testing.CliRunner`, `subprocess` for Docker.

**Spec:** `docs/superpowers/specs/2026-07-15-kind-aware-docker-setup-design.md`

## Global Constraints

- The HTTP token must NEVER appear on stdout/stderr — existing tests assert this; keep it true in every new code path.
- `run_setup` keeps its hub-only guard (`DockerSetupError` on child/kind-less) — direct callers stay safe; existing unit tests must keep passing unchanged.
- CLI tests must never invoke real Docker: monkeypatch `center_kb.dockersetup.docker_ready` / `compose_up` / `compose_pull` in every CLI test (the machine running tests may or may not have Docker — both must pass).
- Windows dev box: files written with `newline="\n"`, tests run via `uv run pytest`.
- Conventional commits, no attribution footer (disabled globally).
- Follow repo lint: `uv run ruff check src tests` and `uv run black --check src tests` must pass before each commit.

---

### Task 1: Sectioner drops symbol-only headings

**Files:**
- Modify: `src/center_kb/ingest/sectioner.py` (inside `_build_tree`, right after `normalized = " ".join(item.text.split())`, before the `endswith(":")` check)
- Test: `tests/test_sectioner.py`

**Interfaces:**
- Consumes: `DocItem`, `build_units` (existing).
- Produces: no API change — behavior only (symbol-only headings vanish).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sectioner.py` (module level, near the other `build_units` tests; note `DocItem` positional args are `(kind, text, level)`):

```python
def test_symbol_only_heading_is_dropped():
    # A PDF horizontal-rule/footnote line ("_____") that docling misreads as
    # a heading must not open a fallback node (no "-x1" ids) nor leak into
    # the body text.
    items = [
        DocItem("heading", "8.0 INSTRUMENTS", 1),
        DocItem("text", "Chapter body text. " * 60),
        DocItem("heading", "_____________", 2),
        DocItem("heading", "8.4 Navigation lights", 2),
        DocItem("text", "Lights body text. " * 70),
    ]
    units = build_units(items)
    ids = [u.id for u in units]
    assert ids == ["8", "8.4"]
    assert all("x1" not in i for i in ids)
    assert "___" not in units[0].body_md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sectioner.py::test_symbol_only_heading_is_dropped -v`
Expected: FAIL — `ids` contains `"8-x1"` (or `"___" in body`), because the underscore heading currently becomes a fallback node.

- [ ] **Step 3: Implement the filter**

In `src/center_kb/ingest/sectioner.py`, in `_build_tree`, the heading branch currently starts:

```python
        if item.kind == "heading":
            normalized = " ".join(item.text.split())
            if normalized.endswith(":"):
```

Insert the skip between those two statements:

```python
        if item.kind == "heading":
            normalized = " ".join(item.text.split())
            if not any(ch.isalnum() for ch in normalized):
                # Horizontal-rule / footnote-separator artifact ("_____",
                # "---"): pure graphics, no content -- skip entirely so it
                # never opens a fallback node.
                continue
            if normalized.endswith(":"):
```

- [ ] **Step 4: Run the full sectioner suite**

Run: `uv run pytest tests/test_sectioner.py -v`
Expected: ALL PASS (new test + no regressions).

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/ingest/sectioner.py tests/test_sectioner.py
git commit -m "fix: drop symbol-only headings (PDF rule lines) at ingest"
```

---

### Task 2: Docker helpers in `dockersetup.py`

**Files:**
- Modify: `src/center_kb/dockersetup.py`
- Test: `tests/test_dockersetup.py`

**Interfaces:**
- Consumes: `load_config` (existing), `subprocess`.
- Produces (Task 3 relies on these exact signatures):
  - `repo_kind(repo_root: Path) -> str` — returns `"hub"` or `"child"`; raises `DockerSetupError` when kind unset.
  - `docker_ready() -> bool` — `docker info` answers within 30 s.
  - `compose_up(repo_root: Path) -> int` — exit code of `docker compose up -d` (output streams).
  - `compose_pull(repo_root: Path) -> int` — exit code of `docker compose pull` (output streams).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dockersetup.py`:

```python
def test_repo_kind_reads_config(tmp_path: Path):
    import pytest

    from center_kb.dockersetup import DockerSetupError, repo_kind

    hub = tmp_path / "h"
    hub.mkdir()
    init_repo(hub, "hub")
    assert repo_kind(hub) == "hub"

    child = tmp_path / "c"
    child.mkdir()
    init_repo(child, "child")
    assert repo_kind(child) == "child"

    bare = tmp_path / "bare"
    bare.mkdir()
    with pytest.raises(DockerSetupError, match="kb init"):
        repo_kind(bare)


def test_docker_ready_false_when_cli_missing(monkeypatch):
    import subprocess

    from center_kb import dockersetup

    def boom(*args, **kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(subprocess, "run", boom)
    assert dockersetup.docker_ready() is False


def test_docker_ready_true_on_zero_exit(monkeypatch):
    import subprocess

    from center_kb import dockersetup

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)

        class R:
            returncode = 0

        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert dockersetup.docker_ready() is True
    assert calls == [["docker", "info"]]


def test_compose_helpers_run_in_repo_root(tmp_path: Path, monkeypatch):
    import subprocess

    from center_kb import dockersetup

    seen = []

    def fake_run(cmd, **kwargs):
        seen.append((cmd, kwargs.get("cwd")))

        class R:
            returncode = 0

        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert dockersetup.compose_up(tmp_path) == 0
    assert dockersetup.compose_pull(tmp_path) == 0
    assert seen == [
        (["docker", "compose", "up", "-d"], tmp_path),
        (["docker", "compose", "pull"], tmp_path),
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_dockersetup.py -v -k "repo_kind or docker_ready or compose_helpers"`
Expected: FAIL with `ImportError`/`AttributeError` — `repo_kind`, `docker_ready`, `compose_up`, `compose_pull` don't exist yet.

- [ ] **Step 3: Implement the helpers**

In `src/center_kb/dockersetup.py`:

Add `import subprocess` to the imports block.

Add after the `SetupReport` dataclass:

```python
def repo_kind(repo_root: Path) -> str:
    """Return the recorded repo kind ('hub' | 'child'); raise when unset."""
    kind = load_config(repo_root / ".kb").kind
    if kind not in ("hub", "child"):
        raise DockerSetupError(
            "repo kind is not recorded — run `kb init` first "
            "(it records kind: hub|child in .kb/config.yaml)"
        )
    return kind


def docker_ready() -> bool:
    """True when the Docker CLI exists and the daemon answers `docker info`."""
    try:
        return (
            subprocess.run(["docker", "info"], capture_output=True, timeout=30)
            .returncode
            == 0
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def compose_up(repo_root: Path) -> int:
    """`docker compose up -d` in the repo root; output streams to the console."""
    return subprocess.run(["docker", "compose", "up", "-d"], cwd=repo_root).returncode


def compose_pull(repo_root: Path) -> int:
    """`docker compose pull` in the repo root; output streams to the console."""
    return subprocess.run(["docker", "compose", "pull"], cwd=repo_root).returncode
```

Then refactor `_require_hub_kind` to reuse `repo_kind` (message for child unchanged):

```python
def _require_hub_kind(repo_root: Path) -> None:
    if repo_kind(repo_root) == "child":
        raise DockerSetupError(
            "this repo is a child — kb docker-setup prepares the MAIN hub "
            "(the repo that hosts federation/ and the shared MCP/Web service)"
        )
```

(`docker_ready` calls `subprocess.run` with the module-level import — the monkeypatched `subprocess.run` in the tests intercepts it because the tests patch the `subprocess` module attribute, which the function resolves at call time.)

- [ ] **Step 4: Run the full dockersetup suite**

Run: `uv run pytest tests/test_dockersetup.py -v`
Expected: ALL PASS — new helper tests plus every pre-existing `run_setup`/CLI test (the guard refactor must not change messages).

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/dockersetup.py tests/test_dockersetup.py
git commit -m "feat: docker helpers (repo_kind, docker_ready, compose up/pull) in dockersetup"
```

---

### Task 3: Kind-aware `kb docker-setup` CLI

**Files:**
- Modify: `src/center_kb/cli.py` (the `docker_setup` command, currently ~lines 157–197, plus two new module-level helpers `_docker_setup_hub` / `_docker_setup_child`)
- Test: `tests/test_dockersetup.py`

**Interfaces:**
- Consumes (from Task 2): `dockersetup.repo_kind(path)`, `dockersetup.docker_ready()`, `dockersetup.compose_up(path) -> int`, `dockersetup.compose_pull(path) -> int`; existing `dockersetup.run_setup`, `EnvExistsError`, `DockerSetupError`, `TOKEN_VAR`, `_stdin_isatty`.
- Produces: CLI behavior only. Output strings other tasks/docs rely on: hub fallback block still contains `docker compose up -d`, `http://localhost:8321/ui`, `Bearer <token>`; child block contains `docker compose run --rm hub kb ingest`.

- [ ] **Step 1: Update the existing CLI tests to mock Docker, and add the new cases**

In `tests/test_dockersetup.py`:

**(a)** Add a helper near the top (after `TOKEN_RE`):

```python
def _mock_docker(monkeypatch, ready: bool, up_rc: int = 0, pull_rc: int = 0):
    """Neutralize real Docker in CLI tests; record compose calls."""
    from center_kb import dockersetup

    calls: list[str] = []
    monkeypatch.setattr(dockersetup, "docker_ready", lambda: ready)

    def fake_up(path):
        calls.append("up")
        return up_rc

    def fake_pull(path):
        calls.append("pull")
        return pull_rc

    monkeypatch.setattr(dockersetup, "compose_up", fake_up)
    monkeypatch.setattr(dockersetup, "compose_pull", fake_pull)
    return calls
```

**(b)** Update the four existing CLI tests to take `monkeypatch` and call `_mock_docker` so they never touch real Docker:

- `test_cli_docker_setup_happy_path_never_prints_token(tmp_path, monkeypatch)` — add `_mock_docker(monkeypatch, ready=False)` as the first line (Docker absent → fallback path keeps every string the test already asserts: `docker compose up -d`, the UI URL, `Bearer <token>`). Keep all existing assertions.
- `test_cli_docker_setup_existing_env_needs_force(tmp_path, monkeypatch)` — add `_mock_docker(monkeypatch, ready=False)`.
- `test_cli_docker_setup_tty_confirm_regenerates(tmp_path, monkeypatch)` — already takes `monkeypatch`; add `_mock_docker(monkeypatch, ready=False)`.
- **Replace** `test_cli_docker_setup_refuses_child` with the child happy path (the CLI no longer refuses; the function-level refusal is still covered by `test_run_setup_refuses_child_and_kindless`):

```python
def test_cli_docker_setup_child_pulls_image_no_env(tmp_path: Path, monkeypatch):
    calls = _mock_docker(monkeypatch, ready=True)
    init_repo(tmp_path, "child")
    result = runner.invoke(app, ["docker-setup", str(tmp_path)])
    assert result.exit_code == 0
    assert calls == ["pull"]
    assert not (tmp_path / ".env").exists()
    assert "docker compose run --rm hub kb ingest" in result.output
```

**(c)** Add the new cases:

```python
def test_cli_docker_setup_hub_runs_compose_up(tmp_path: Path, monkeypatch):
    calls = _mock_docker(monkeypatch, ready=True)
    init_repo(tmp_path, "hub")
    result = runner.invoke(app, ["docker-setup", str(tmp_path)])
    assert result.exit_code == 0
    assert calls == ["up"]
    assert "http://localhost:8321/ui" in result.output
    token = TOKEN_RE.search((tmp_path / ".env").read_text(encoding="utf-8")).group(1)
    assert token not in result.output


def test_cli_docker_setup_hub_compose_failure_exits_nonzero(
    tmp_path: Path, monkeypatch
):
    _mock_docker(monkeypatch, ready=True, up_rc=1)
    init_repo(tmp_path, "hub")
    result = runner.invoke(app, ["docker-setup", str(tmp_path)])
    assert result.exit_code == 1
    assert "docker compose up failed" in result.output
    # .env was still written before compose ran
    assert TOKEN_RE.search((tmp_path / ".env").read_text(encoding="utf-8"))


def test_cli_docker_setup_hub_no_docker_flag_skips_compose(
    tmp_path: Path, monkeypatch
):
    calls = _mock_docker(monkeypatch, ready=True)
    init_repo(tmp_path, "hub")
    result = runner.invoke(app, ["docker-setup", str(tmp_path), "--no-docker"])
    assert result.exit_code == 0
    assert calls == []
    assert "docker compose up -d" in result.output  # manual next steps


def test_cli_docker_setup_child_without_docker_fails(tmp_path: Path, monkeypatch):
    _mock_docker(monkeypatch, ready=False)
    init_repo(tmp_path, "child")
    result = runner.invoke(app, ["docker-setup", str(tmp_path)])
    assert result.exit_code == 1
    assert "Docker not detected" in result.output


def test_cli_docker_setup_child_pull_failure_exits_nonzero(
    tmp_path: Path, monkeypatch
):
    _mock_docker(monkeypatch, ready=True, pull_rc=1)
    init_repo(tmp_path, "child")
    result = runner.invoke(app, ["docker-setup", str(tmp_path)])
    assert result.exit_code == 1
    assert "docker compose pull failed" in result.output


def test_cli_docker_setup_child_no_docker_flag_skips_pull(
    tmp_path: Path, monkeypatch
):
    calls = _mock_docker(monkeypatch, ready=False)
    init_repo(tmp_path, "child")
    result = runner.invoke(app, ["docker-setup", str(tmp_path), "--no-docker"])
    assert result.exit_code == 0
    assert calls == []
    assert "docker compose run --rm hub kb ingest" in result.output


def test_cli_docker_setup_kindless_fails(tmp_path: Path, monkeypatch):
    _mock_docker(monkeypatch, ready=True)
    result = runner.invoke(app, ["docker-setup", str(tmp_path)])
    assert result.exit_code == 1
    assert "kb init" in result.output
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `uv run pytest tests/test_dockersetup.py -v`
Expected: new CLI tests FAIL (child path exits 1 with the old refusal; `--no-docker` unknown option); pre-existing tests still pass.

- [ ] **Step 3: Rework the CLI command**

In `src/center_kb/cli.py`, replace the entire `docker_setup` command (keep the `@app.command("docker-setup")` decorator position) with:

```python
@app.command("docker-setup")
def docker_setup(
    path: Path = typer.Argument(Path("."), help="Repo root (default: current)"),
    force: bool = typer.Option(
        False, "--force", help="Hub: regenerate the token inside an existing .env"
    ),
    no_docker: bool = typer.Option(
        False, "--no-docker", help="Prepare files only; skip docker commands"
    ),
) -> None:
    """Prepare this repo for Docker — hub: .env + token + start the service; child: pull the ingest image."""
    from center_kb import dockersetup

    try:
        kind = dockersetup.repo_kind(path)
    except dockersetup.DockerSetupError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    if kind == "hub":
        _docker_setup_hub(path, force, no_docker)
    else:
        _docker_setup_child(path, no_docker)


def _docker_setup_hub(path: Path, force: bool, no_docker: bool) -> None:
    from center_kb import dockersetup

    try:
        try:
            report = dockersetup.run_setup(path, regenerate=force)
        except dockersetup.EnvExistsError:
            if _stdin_isatty() and typer.confirm(
                f"Found existing .env — regenerate {dockersetup.TOKEN_VAR}?"
            ):
                report = dockersetup.run_setup(path, regenerate=True)
            else:
                raise
    except dockersetup.DockerSetupError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    action = "created" if report.env_created else "updated"
    typer.echo(
        f".env {action} — {dockersetup.TOKEN_VAR} written (token not shown; see .env)."
    )
    if report.gitignore_updated:
        typer.echo(".gitignore updated: added .env")
    typer.secho(
        "This token was auto-generated for convenience — replace it with your "
        "own secret for real deployments, and store it in a secret manager.",
        fg=typer.colors.YELLOW,
    )
    if not no_docker and dockersetup.docker_ready():
        typer.echo("Starting the hub: docker compose up -d")
        if dockersetup.compose_up(path) != 0:
            typer.secho(
                "docker compose up failed — see output above.", fg=typer.colors.RED
            )
            raise typer.Exit(1)
        typer.echo(
            "Hub running — Web UI: http://localhost:8321/ui "
            "(sign in with the token from .env)"
        )
    else:
        if not no_docker:
            typer.secho(
                "Docker not detected — start Docker Desktop, then run the steps "
                "below yourself.",
                fg=typer.colors.YELLOW,
            )
        typer.echo("Next steps:")
        typer.echo("  1. docker compose up -d")
        typer.echo(
            "  2. Open http://localhost:8321/ui (sign in with the token from .env)"
        )
    typer.echo("Point remote MCP clients at the hub:")
    typer.echo('  { "mcpServers": { "center-kb": { "type": "http",')
    typer.echo('    "url": "http://<host>:8321/mcp",')
    typer.echo('    "headers": { "Authorization": "Bearer <token>" } } } }')


def _docker_setup_child(path: Path, no_docker: bool) -> None:
    from center_kb import dockersetup

    typer.echo(
        "Child repo: Docker runs one-shot ingest (the image bundles the full "
        "docling stack — no local Python needed)."
    )
    if not no_docker:
        if not dockersetup.docker_ready():
            typer.secho(
                "Docker not detected — install/start Docker Desktop, then re-run "
                "kb docker-setup.",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)
        typer.echo("Pulling the ingest image: docker compose pull")
        if dockersetup.compose_pull(path) != 0:
            typer.secho(
                "docker compose pull failed — see output above.",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)
    typer.echo("Ingest a document:")
    typer.echo(
        "  docker compose run --rm hub kb ingest source/<file>.pdf "
        "--id <doc-id> --no-summarize"
    )
    typer.echo(
        "Note: the first ingest downloads layout/table models into the "
        "kb-model-cache volume (one-time wait)."
    )
    typer.echo("(The shared MCP server + Web UI run on the MAIN hub, not here.)")
```

- [ ] **Step 4: Run the full dockersetup suite**

Run: `uv run pytest tests/test_dockersetup.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check src tests && uv run black --check src tests
git add src/center_kb/cli.py tests/test_dockersetup.py
git commit -m "feat: kind-aware kb docker-setup — hub runs compose up, child pulls ingest image"
```

---

### Task 4: Wrappers become common + init next-steps

**Files:**
- Modify: `src/center_kb/initcmd.py` (move 4 entries `HUB_TEMPLATES` → `COMMON_TEMPLATES`)
- Modify: `src/center_kb/cli.py` (init "Next steps" block, ~lines 140–154)
- Modify: `src/center_kb/templates/init/claude-skill-kb-docker-setup.md`
- Modify: `src/center_kb/templates/init/claude-command-kb-docker-setup.md`
- Modify: `src/center_kb/templates/init/copilot-kb-docker-setup.prompt.md`
- Modify: `src/center_kb/templates/init/cursor-kb-docker-setup.md`
- Test: `tests/test_init.py`

**Interfaces:**
- Consumes: CLI behavior from Task 3 (kind-aware `kb docker-setup`, `--force` hub-only semantics).
- Produces: both kinds scaffold `.claude/skills/kb-docker-setup/SKILL.md`, `.claude/commands/kb-docker-setup.md`, `.github/prompts/kb-docker-setup.prompt.md`, `.cursor/commands/kb-docker-setup.md`. Task 5's QUICKSTART text references `/kb-docker-setup` on both kinds.

- [ ] **Step 1: Update the failing tests first**

In `tests/test_init.py`:

**(a)** Rename `test_init_scaffolds_kb_docker_setup_hub_only` → `test_init_scaffolds_kb_docker_setup_both_kinds` and make it assert presence for BOTH kinds:

```python
def test_init_scaffolds_kb_docker_setup_both_kinds(tmp_path: Path):
    for kind in ("hub", "child"):
        repo = tmp_path / kind
        repo.mkdir()
        init_repo(repo, kind)
        skill = repo / ".claude" / "skills" / "kb-docker-setup" / "SKILL.md"
        command = repo / ".claude" / "commands" / "kb-docker-setup.md"
        prompt = repo / ".github" / "prompts" / "kb-docker-setup.prompt.md"
        assert skill.exists() and command.exists() and prompt.exists(), kind
        skill_text = skill.read_text(encoding="utf-8")
        assert "name: kb-docker-setup" in skill_text
        for text in (skill_text, prompt.read_text(encoding="utf-8")):
            assert "kb docker-setup" in text  # wraps the CLI
            assert "NEVER print" in text      # secret-hygiene rule
        command_text = command.read_text(encoding="utf-8")
        assert "kb-docker-setup" in command_text  # invokes the skill by name
```

(Keep the same helper/import style the current test uses — adjust names only.)

**(b)** `test_cursor_docker_setup_command_hub_only` → rename to `test_cursor_docker_setup_command_both_kinds`; assert `.cursor/commands/kb-docker-setup.md` exists for both kinds and drop the child-absence assertion.

**(c)** In the assistant-parity test (~line 430–440): change

```python
    for kind, names in (("hub", common + ["kb-docker-setup"]), ("child", common)):
```

to

```python
    common = common + ["kb-docker-setup"]
    for kind, names in (("hub", common), ("child", common)):
```

(match the actual local variable names in that test when editing) and delete any now-dead special-casing of `kb-docker-setup` (e.g. the `if n in ("kb-summarize", "kb-docker-setup")` filter at ~line 430 may need its comment/logic revisited — keep behavior: those two have no Cursor *rules* file; the filter itself stays).

**(d)** QUICKSTART assertions (~lines 326–328): keep `assert "kb docker-setup" in hub_q`; flip the child one to `assert "kb docker-setup" in child_q` (Task 5 updates the QUICKSTART text; this test goes red until then if edited now — so ONLY make change (d) in Task 5, not here. In this task leave lines 326–328 untouched.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_init.py -v -k "docker_setup or parity"`
Expected: FAIL — child repos lack the wrapper files.

- [ ] **Step 3: Move the template entries**

In `src/center_kb/initcmd.py`, cut these four lines from `HUB_TEMPLATES` and paste them into `COMMON_TEMPLATES` (keep dict style):

```python
    ".claude/skills/kb-docker-setup/SKILL.md": "claude-skill-kb-docker-setup.md",
    ".claude/commands/kb-docker-setup.md": "claude-command-kb-docker-setup.md",
    ".github/prompts/kb-docker-setup.prompt.md": "copilot-kb-docker-setup.prompt.md",
    ".cursor/commands/kb-docker-setup.md": "cursor-kb-docker-setup.md",
```

- [ ] **Step 4: Rewrite the four wrapper templates kind-neutral**

Replace `src/center_kb/templates/init/claude-skill-kb-docker-setup.md` with:

```markdown
---
name: kb-docker-setup
description: Prepare this repo for Docker — MAIN hub: create .env, generate the HTTP token, start the service; child repo: pull the ingest image. Kind-aware; run after kb init.
---

# kb-docker-setup — prepare this repo for Docker

Thin wrapper around the `kb docker-setup` CLI. Your job: run the command,
relay its output, keep any secret out of the chat.

The CLI reads `kind:` from `.kb/config.yaml` and adapts:
- **hub** — creates `.env` with a fresh `CENTER_KB_HTTP_TOKEN`, then runs
  `docker compose up -d`. When Docker is not available it prints the manual
  next steps instead (still exit 0 — the token was written).
- **child** — no `.env`/token (nothing to secure); requires Docker, runs
  `docker compose pull` so the first ingest doesn't wait for the image,
  then prints the one-shot ingest command.

Hard rules:
- NEVER print the contents of `.env` (or the token) into the chat. The CLI
  deliberately does not echo the token; do not read the file to "show" it.
- Non-zero exit → show the error verbatim and stop. Do not retry with
  guessed fixes, do not create `.env` manually, do not run docker commands
  the CLI refused to run.

## Workflow

1. Run `kb docker-setup`.
   - Hub, "found existing .env" → ask the user whether to regenerate the
     token, and only then re-run with `--force`.
2. Relay the output. Hub: `.env` written, the auto-generated-token warning
   (replace with your own secret for real deployments; store it in a secret
   manager), the Web UI URL (http://localhost:8321/ui) and the client MCP
   config snippet. Child: image pulled and the
   `docker compose run --rm hub kb ingest ...` command.
```

Replace `src/center_kb/templates/init/claude-command-kb-docker-setup.md` with:

```markdown
---
description: Prepare this repo for Docker — hub: .env + HTTP token + start the service; child: pull the ingest image
---

Invoke the `kb-docker-setup` skill with the Skill tool and follow its
workflow exactly.
```

Replace `src/center_kb/templates/init/copilot-kb-docker-setup.prompt.md` with:

```markdown
---
mode: agent
description: Prepare this repo for Docker — hub: create .env + HTTP token + start the service; child: pull the ingest image. Kind-aware.
---

# /kb-docker-setup — prepare this repo for Docker

Thin wrapper around the `kb docker-setup` CLI. Run the command, relay its
output, keep any secret out of the chat.

The CLI reads `kind:` from `.kb/config.yaml` and adapts:
- **hub** — creates `.env` with a fresh `CENTER_KB_HTTP_TOKEN`, then runs
  `docker compose up -d` (manual next steps are printed when Docker is not
  available).
- **child** — no `.env`/token; requires Docker, runs `docker compose pull`,
  then prints the one-shot ingest command.

Hard rules:
- NEVER print the contents of `.env` (or the token) into the chat. The CLI
  deliberately does not echo the token; do not read the file to "show" it.
- Non-zero exit → show the error verbatim and stop. Do not retry with
  guessed fixes, do not create `.env` manually.

## Workflow

1. Run `kb docker-setup`.
   - Hub, "found existing .env" → ask the user whether to regenerate the
     token, and only then re-run with `--force`.
2. Relay the output (hub: .env written + warning + UI URL + MCP snippet;
   child: image pulled + ingest command).
```

Replace `src/center_kb/templates/init/cursor-kb-docker-setup.md` with the same body as the Copilot prompt but with Cursor frontmatter:

```markdown
---
name: kb-docker-setup
description: Prepare this repo for Docker — hub: create .env + HTTP token + start the service; child: pull the ingest image. Kind-aware.
---

# /kb-docker-setup — prepare this repo for Docker

Thin wrapper around the `kb docker-setup` CLI. Run the command, relay its
output, keep any secret out of the chat.

The CLI reads `kind:` from `.kb/config.yaml` and adapts:
- **hub** — creates `.env` with a fresh `CENTER_KB_HTTP_TOKEN`, then runs
  `docker compose up -d` (manual next steps are printed when Docker is not
  available).
- **child** — no `.env`/token; requires Docker, runs `docker compose pull`,
  then prints the one-shot ingest command.

Hard rules:
- NEVER print the contents of `.env` (or the token) into the chat. The CLI
  deliberately does not echo the token; do not read the file to "show" it.
- Non-zero exit → show the error verbatim and stop. Do not retry with
  guessed fixes, do not create `.env` manually.

## Workflow

1. Run `kb docker-setup`.
   - Hub, "found existing .env" → ask the user whether to regenerate the
     token, and only then re-run with `--force`.
2. Relay the output (hub: .env written + warning + UI URL + MCP snippet;
   child: image pulled + ingest command).
```

- [ ] **Step 5: Update the init "Next steps" block**

In `src/center_kb/cli.py` (init command, currently ~lines 140–154), replace the hub/child next-steps with:

```python
    typer.echo("Next steps:")
    if resolved == "hub":
        typer.echo(
            "  1. kb docker-setup   (or /kb-docker-setup in your AI assistant)"
            "  # .env + HTTP token + docker compose up -d"
        )
        typer.echo(
            "  2. Open http://localhost:8321/ui    # Web UI (MCP HTTP on the same port)"
        )
        typer.echo("  3. kb ingest source/<file>.pdf --id <doc-id>")
    else:
        typer.echo("  1. Fill hub: in .kb/config.yaml with the main hub URL/path")
        typer.echo(
            "  2. kb docker-setup   (or /kb-docker-setup)"
            "  # optional: pull the Docker ingest image"
        )
        typer.echo("  3. kb ingest source/<file>.pdf --id <doc-id>    (or /kb-ingest)")
        typer.echo("  4. kb publish    (or /kb-publish)")
    typer.echo("  (details: QUICKSTART.md)")
```

Note: `tests/test_init.py:109` asserts `"kb docker-setup" in result.output` for hub init — still true. If a sibling test asserts the child next-steps do NOT mention docker-setup, update it to expect the new line.

- [ ] **Step 6: Run the init + dockersetup suites**

Run: `uv run pytest tests/test_init.py tests/test_dockersetup.py tests/test_templates.py -v`
Expected: ALL PASS (template-resource existence checks pick up the moved entries via the merged maps automatically).

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check src tests && uv run black --check src tests
git add src/center_kb/initcmd.py src/center_kb/cli.py src/center_kb/templates/init tests/test_init.py
git commit -m "feat: scaffold /kb-docker-setup on child repos; kind-neutral wrapper templates"
```

---

### Task 5: QUICKSTART + README documentation

**Files:**
- Modify: `src/center_kb/templates/init/QUICKSTART-hub.md`
- Modify: `src/center_kb/templates/init/QUICKSTART-child.md`
- Modify: `README.md` (~lines 210–221 and 238–243)
- Test: `tests/test_init.py` (QUICKSTART assertions ~lines 326–328)

**Interfaces:**
- Consumes: CLI behavior from Tasks 3–4 (hub auto-`compose up`; child pull; wrappers on both kinds).
- Produces: docs only.

- [ ] **Step 1: Update the QUICKSTART test expectations**

In `tests/test_init.py` (~lines 326–328): keep `assert "kb docker-setup" in hub_q`; change `assert "kb docker-setup" not in child_q` to `assert "kb docker-setup" in child_q`.

Run: `uv run pytest tests/test_init.py -v -k quickstart`
Expected: FAIL (child QUICKSTART doesn't mention it yet).

- [ ] **Step 2: Rewrite QUICKSTART-hub step 1–2**

In `src/center_kb/templates/init/QUICKSTART-hub.md`, replace steps 1 and 2 with a single step (renumber the remaining steps 2–4):

```markdown
1. **Set up Docker serving** — run `kb docker-setup` (in Claude Code /
   Copilot Chat / Cursor: `/kb-docker-setup`). It creates `.env`, generates
   `CENTER_KB_HTTP_TOKEN`, and starts the service (`docker compose up -d`) —
   web UI at http://localhost:8321/ui (sign in with the token). The token is
   auto-generated for convenience — replace it with your own secret for real
   deployments. Manual fallback: `cp .env.example .env`, edit the token,
   then `docker compose up -d`. Without Docker:
   `python -m center_kb.mcp --hub . --transport http`
   (requires the `CENTER_KB_HTTP_TOKEN` env var).
```

Update the CLI reference line:

```markdown
- `kb docker-setup` — prepare Docker: hub creates `.env` + the HTTP token and
  starts the service; child repos pull the ingest image
  (in your assistant: `/kb-docker-setup`)
```

- [ ] **Step 3: Add the pull step to QUICKSTART-child**

In `src/center_kb/templates/init/QUICKSTART-child.md`, insert a new step 2 after "Point at the main hub" (renumber the following steps — currently 2–5 become 3–6):

```markdown
2. **Pull the ingest image (optional but recommended)** — run
   `kb docker-setup` (in your assistant: `/kb-docker-setup`). It checks
   Docker and pulls the CENTER-KB image so ingest runs fully inside Docker —
   no local Python needed. Skip it if you install the ingest extra locally
   instead (`pip install "center-kb[ingest]"`).
```

Add to the CLI reference list (after the `kb init` line):

```markdown
- `kb docker-setup` — child: check Docker + pull the ingest image; on the
  hub it also creates `.env` + token and starts the service
  (in your assistant: `/kb-docker-setup`)
```

- [ ] **Step 4: Update README**

In `README.md` ~lines 214–218, replace:

```markdown
`.kb/config.yaml`, and re-runs reuse it. Hub repos then run `kb docker-setup`
(or the `/kb-docker-setup` slash command) to create `.env` and generate the
HTTP token. Slash commands (`/kb-ingest`, `/kb-summarize`, `/kb-publish`,
and on the hub `/kb-docker-setup`) are scaffolded for **Claude Code, GitHub
Copilot, and Cursor**; MCP client wiring ships as `.mcp.json` (Claude Code)
```

with:

```markdown
`.kb/config.yaml`, and re-runs reuse it. Then run `kb docker-setup` (or the
`/kb-docker-setup` slash command): on the hub it creates `.env`, generates
the HTTP token, and starts the service (`docker compose up -d`); on a child
it pulls the ingest image for one-shot Docker ingest. Slash commands
(`/kb-ingest`, `/kb-summarize`, `/kb-publish`, `/kb-docker-setup`) are
scaffolded for **Claude Code, GitHub Copilot, and Cursor**; MCP client
wiring ships as `.mcp.json` (Claude Code)
```

In `README.md` ~lines 241–243, replace:

```markdown
First-time hub setup: `kb docker-setup` creates `.env` and generates
`CENTER_KB_HTTP_TOKEN` (auto-generated for convenience — replace it with your
own secret for real deployments).
```

with:

```markdown
First-time setup: `kb docker-setup` — on the hub it creates `.env`, generates
`CENTER_KB_HTTP_TOKEN` (auto-generated for convenience — replace it with your
own secret for real deployments) and runs `docker compose up -d`; on a child
it pulls the image so ingest needs no local Python.
```

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest`
Expected: ALL PASS.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check src tests && uv run black --check src tests
git add src/center_kb/templates/init/QUICKSTART-hub.md src/center_kb/templates/init/QUICKSTART-child.md README.md tests/test_init.py
git commit -m "docs: QUICKSTART + README for kind-aware kb docker-setup"
```
