import re
from pathlib import Path

from typer.testing import CliRunner

from strata_kb.cli import app
from strata_kb.initcmd import init_repo

runner = CliRunner()

TOKEN_RE = re.compile(r"^STRATA_KB_HTTP_TOKEN=([0-9a-f]{48})$", re.MULTILINE)


def _mock_docker(monkeypatch, ready: bool, up_rc: int = 0, pull_rc: int = 0):
    """Neutralize real Docker in CLI tests; record compose calls."""
    from strata_kb import dockersetup

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


def test_run_setup_creates_env_with_token(tmp_path: Path):
    from strata_kb.dockersetup import run_setup

    init_repo(tmp_path, "hub")
    report = run_setup(tmp_path)
    assert report.env_created
    env = (tmp_path / ".env").read_text(encoding="utf-8")
    match = TOKEN_RE.search(env)
    assert match, env
    assert match.group(1) != "change-me"


def test_run_setup_synthesizes_env_without_example(tmp_path: Path):
    from strata_kb.dockersetup import run_setup

    init_repo(tmp_path, "hub")
    (tmp_path / ".env.example").unlink()
    run_setup(tmp_path)
    assert TOKEN_RE.search((tmp_path / ".env").read_text(encoding="utf-8"))


def test_run_setup_refuses_existing_env_without_regenerate(tmp_path: Path):
    import pytest

    from strata_kb.dockersetup import EnvExistsError, run_setup

    init_repo(tmp_path, "hub")
    (tmp_path / ".env").write_text("STRATA_KB_HTTP_TOKEN=mine\n", encoding="utf-8")
    with pytest.raises(EnvExistsError):
        run_setup(tmp_path)
    assert "mine" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_run_setup_regenerates_with_flag(tmp_path: Path):
    from strata_kb.dockersetup import run_setup

    init_repo(tmp_path, "hub")
    (tmp_path / ".env").write_text(
        "OTHER=keep\nSTRATA_KB_HTTP_TOKEN=mine\n", encoding="utf-8"
    )
    report = run_setup(tmp_path, regenerate=True)
    assert not report.env_created
    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "OTHER=keep" in env
    assert "mine" not in env
    assert TOKEN_RE.search(env)


def test_run_setup_refuses_child_and_kindless(tmp_path: Path):
    import pytest

    from strata_kb.dockersetup import DockerSetupError, run_setup

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
    from strata_kb.dockersetup import run_setup

    init_repo(tmp_path, "hub")
    report = run_setup(tmp_path)
    assert report.gitignore_updated
    assert ".env" in (tmp_path / ".gitignore").read_text(encoding="utf-8").split()
    # second run with regenerate: already ignored, no duplicate
    report2 = run_setup(tmp_path, regenerate=True)
    assert not report2.gitignore_updated


def test_cli_docker_setup_happy_path_never_prints_token(tmp_path: Path, monkeypatch):
    _mock_docker(monkeypatch, ready=False)
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


def test_cli_docker_setup_child_pulls_image_no_env(tmp_path: Path, monkeypatch):
    calls = _mock_docker(monkeypatch, ready=True)
    init_repo(tmp_path, "child")
    result = runner.invoke(app, ["docker-setup", str(tmp_path)])
    assert result.exit_code == 0
    assert calls == ["pull"]
    assert not (tmp_path / ".env").exists()
    assert "docker compose run --rm hub kb ingest" in result.output


def test_cli_docker_setup_existing_env_needs_force(tmp_path: Path, monkeypatch):
    _mock_docker(monkeypatch, ready=False)
    init_repo(tmp_path, "hub")
    (tmp_path / ".env").write_text("STRATA_KB_HTTP_TOKEN=mine\n", encoding="utf-8")
    result = runner.invoke(app, ["docker-setup", str(tmp_path)])
    assert result.exit_code == 1
    assert "--force" in result.output
    assert "mine" in (tmp_path / ".env").read_text(encoding="utf-8")
    result2 = runner.invoke(app, ["docker-setup", str(tmp_path), "--force"])
    assert result2.exit_code == 0
    assert "mine" not in (tmp_path / ".env").read_text(encoding="utf-8")


def test_cli_docker_setup_tty_confirm_regenerates(tmp_path: Path, monkeypatch):
    from strata_kb import cli

    _mock_docker(monkeypatch, ready=False)
    monkeypatch.setattr(cli, "_stdin_isatty", lambda: True)
    init_repo(tmp_path, "hub")
    (tmp_path / ".env").write_text("STRATA_KB_HTTP_TOKEN=mine\n", encoding="utf-8")
    result = runner.invoke(app, ["docker-setup", str(tmp_path)], input="y\n")
    assert result.exit_code == 0
    assert "mine" not in (tmp_path / ".env").read_text(encoding="utf-8")


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


def test_repo_kind_reads_config(tmp_path: Path):
    import pytest

    from strata_kb.dockersetup import DockerSetupError, repo_kind

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

    from strata_kb import dockersetup

    def boom(*args, **kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(subprocess, "run", boom)
    assert dockersetup.docker_ready() is False


def test_docker_ready_true_on_zero_exit(monkeypatch):
    import subprocess

    from strata_kb import dockersetup

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

    from strata_kb import dockersetup

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


def test_repo_kind_returns_ba_and_dev_instead_of_raising(tmp_path: Path):
    from strata_kb.dockersetup import repo_kind

    for kind in ("ba", "dev"):
        repo = tmp_path / kind
        repo.mkdir()
        init_repo(repo, kind)
        assert repo_kind(repo) == kind


def test_repo_kind_still_raises_when_kind_is_unset(tmp_path: Path):
    import pytest

    from strata_kb.dockersetup import DockerSetupError, repo_kind

    # A bare directory: load_config returns its defaults, so kind is "".
    # Same construction test_run_setup_refuses_child_and_kindless uses.
    bare = tmp_path / "bare"
    bare.mkdir()
    with pytest.raises(DockerSetupError, match="kb init"):
        repo_kind(bare)


def test_require_hub_kind_rejects_every_non_hub_kind(tmp_path: Path):
    import pytest

    from strata_kb.dockersetup import DockerSetupError, _require_hub_kind

    for kind in ("child", "ba", "dev"):
        repo = tmp_path / kind
        repo.mkdir()
        init_repo(repo, kind)
        with pytest.raises(DockerSetupError):
            _require_hub_kind(repo)


def test_set_env_line_appends_when_absent():
    from strata_kb.dockersetup import set_env_line

    assert set_env_line("", "A", "1") == "A=1\n"
    assert set_env_line("B=2\n", "A", "1") == "B=2\nA=1\n"
    assert set_env_line("B=2", "A", "1") == "B=2\nA=1\n"


def test_set_env_line_replaces_in_place_and_keeps_other_lines():
    from strata_kb.dockersetup import set_env_line

    out = set_env_line("B=2\nA=old\nC=3\n", "A", "new")
    assert out == "B=2\nA=new\nC=3\n"


def test_set_env_line_treats_the_value_literally():
    from strata_kb.dockersetup import set_env_line

    # A backslash in the value must not be read as a regex escape.
    assert set_env_line("A=old\n", "A", r"c:\x") == "A=c:\\x\n"


def test_ensure_gitignored_creates_the_file_when_absent(tmp_path: Path):
    from strata_kb.dockersetup import ensure_gitignored

    assert ensure_gitignored(tmp_path) is True
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == ".env\n"
    assert ensure_gitignored(tmp_path) is False


def test_cli_docker_setup_rejects_ba_and_dev_by_name(tmp_path: Path):
    for kind in ("ba", "dev"):
        repo = tmp_path / kind
        repo.mkdir()
        init_repo(repo, kind)
        result = runner.invoke(app, ["docker-setup", str(repo)])
        assert result.exit_code == 1
        assert f"kind: {kind}" in result.output
        assert "hub" in result.output and "child" in result.output
