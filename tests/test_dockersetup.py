import re
from pathlib import Path

from typer.testing import CliRunner

from center_kb.cli import app
from center_kb.initcmd import init_repo

runner = CliRunner()

TOKEN_RE = re.compile(r"^CENTER_KB_HTTP_TOKEN=([0-9a-f]{48})$", re.MULTILINE)


def test_run_setup_creates_env_with_token(tmp_path: Path):
    from center_kb.dockersetup import run_setup

    init_repo(tmp_path, "hub")
    report = run_setup(tmp_path)
    assert report.env_created
    env = (tmp_path / ".env").read_text(encoding="utf-8")
    match = TOKEN_RE.search(env)
    assert match, env
    assert match.group(1) != "change-me"


def test_run_setup_synthesizes_env_without_example(tmp_path: Path):
    from center_kb.dockersetup import run_setup

    init_repo(tmp_path, "hub")
    (tmp_path / ".env.example").unlink()
    run_setup(tmp_path)
    assert TOKEN_RE.search((tmp_path / ".env").read_text(encoding="utf-8"))


def test_run_setup_refuses_existing_env_without_regenerate(tmp_path: Path):
    import pytest

    from center_kb.dockersetup import EnvExistsError, run_setup

    init_repo(tmp_path, "hub")
    (tmp_path / ".env").write_text("CENTER_KB_HTTP_TOKEN=mine\n", encoding="utf-8")
    with pytest.raises(EnvExistsError):
        run_setup(tmp_path)
    assert "mine" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_run_setup_regenerates_with_flag(tmp_path: Path):
    from center_kb.dockersetup import run_setup

    init_repo(tmp_path, "hub")
    (tmp_path / ".env").write_text(
        "OTHER=keep\nCENTER_KB_HTTP_TOKEN=mine\n", encoding="utf-8"
    )
    report = run_setup(tmp_path, regenerate=True)
    assert not report.env_created
    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "OTHER=keep" in env
    assert "mine" not in env
    assert TOKEN_RE.search(env)


def test_run_setup_refuses_child_and_kindless(tmp_path: Path):
    import pytest

    from center_kb.dockersetup import DockerSetupError, run_setup

    child = tmp_path / "c"
    child.mkdir()
    init_repo(child, "child")
    with pytest.raises(DockerSetupError, match="child"):
        run_setup(child)

    bare = tmp_path / "bare"
    bare.mkdir()
    with pytest.raises(DockerSetupError, match="kb init"):
        run_setup(bare)


def test_run_setup_adds_env_to_gitignore(tmp_path: Path):
    from center_kb.dockersetup import run_setup

    init_repo(tmp_path, "hub")
    report = run_setup(tmp_path)
    assert report.gitignore_updated
    assert ".env" in (tmp_path / ".gitignore").read_text(encoding="utf-8").split()
    # second run with regenerate: already ignored, no duplicate
    report2 = run_setup(tmp_path, regenerate=True)
    assert not report2.gitignore_updated


def test_cli_docker_setup_happy_path_never_prints_token(tmp_path: Path):
    init_repo(tmp_path, "hub")
    result = runner.invoke(app, ["docker-setup", str(tmp_path)])
    assert result.exit_code == 0
    token = TOKEN_RE.search((tmp_path / ".env").read_text(encoding="utf-8")).group(1)
    assert token not in result.output
    assert "auto-generated" in result.output
    assert "secret manager" in result.output
    assert "docker compose up -d" in result.output
    assert "http://localhost:8321/ui" in result.output
    assert "Bearer <token>" in result.output


def test_cli_docker_setup_refuses_child(tmp_path: Path):
    init_repo(tmp_path, "child")
    result = runner.invoke(app, ["docker-setup", str(tmp_path)])
    assert result.exit_code == 1
    assert "child" in result.output
    assert not (tmp_path / ".env").exists()


def test_cli_docker_setup_existing_env_needs_force(tmp_path: Path):
    init_repo(tmp_path, "hub")
    (tmp_path / ".env").write_text("CENTER_KB_HTTP_TOKEN=mine\n", encoding="utf-8")
    result = runner.invoke(app, ["docker-setup", str(tmp_path)])
    assert result.exit_code == 1
    assert "--force" in result.output
    assert "mine" in (tmp_path / ".env").read_text(encoding="utf-8")
    result2 = runner.invoke(app, ["docker-setup", str(tmp_path), "--force"])
    assert result2.exit_code == 0
    assert "mine" not in (tmp_path / ".env").read_text(encoding="utf-8")


def test_cli_docker_setup_tty_confirm_regenerates(tmp_path: Path, monkeypatch):
    from center_kb import cli

    monkeypatch.setattr(cli, "_stdin_isatty", lambda: True)
    init_repo(tmp_path, "hub")
    (tmp_path / ".env").write_text("CENTER_KB_HTTP_TOKEN=mine\n", encoding="utf-8")
    result = runner.invoke(app, ["docker-setup", str(tmp_path)], input="y\n")
    assert result.exit_code == 0
    assert "mine" not in (tmp_path / ".env").read_text(encoding="utf-8")


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
