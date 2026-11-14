import json
import subprocess
from pathlib import Path

import pytest
import yaml

from strata_kb import testenv
from strata_kb.testenv import TestEnvError

EXAMPLE = Path(testenv.__file__).parent / "templates/init/test-env.example.yaml"
SECRET = "postgres-host-unique-value"


def _env(**over) -> testenv.TestEnv:
    data = yaml.safe_load(EXAMPLE.read_text()) | over
    return testenv.TestEnv.model_validate(data)


def _http(bodies: dict[str, tuple[int, bytes]]):
    def http(method, url, headers, body=None, timeout=60):
        return bodies.get(url, (200, b"{}"))

    return http


def _run(calls: list, code: int = 0):
    def run(cmd, **kw):
        calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, code)

    return run


def test_app_commits_reads_the_field():
    http = _http(
        {
            "https://staging.example.test/version": (200, b'{"commit":"abc"}'),
            "https://api.staging.example.test/health": (200, b'{"git_sha":"d1"}'),
        }
    )
    assert testenv.app_commits(_env(), http) == {"shop-fe": "abc", "shop-api": "d1"}


def test_app_commits_dotted_path():
    env = _env()
    env.apps[0].version_check.field = "build.git_sha"
    http = _http({env.apps[0].version_check.url: (200, b'{"build":{"git_sha":"x9"}}')})
    env.apps = env.apps[:1]
    assert testenv.app_commits(env, http) == {"shop-fe": "x9"}


def test_version_check_missing_field_names_repo():
    http = _http({"https://staging.example.test/version": (200, b'{"other":1}')})
    with pytest.raises(TestEnvError, match="shop-fe"):
        testenv.app_commits(_env(), http)


def test_version_check_http_failure_names_repo():
    http = _http({"https://staging.example.test/version": (0, b"refused")})
    with pytest.raises(TestEnvError, match="shop-fe"):
        testenv.app_commits(_env(), http)


def test_run_script_refuses_production(tmp_path):
    with pytest.raises(TestEnvError, match="production"):
        testenv.run_script(tmp_path, _env(name="Production"), "x.sh", _run([]))


def test_run_script_refuses_protected_url(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_DB_URL", SECRET)
    env = _env(protected_urls=[SECRET])
    with pytest.raises(TestEnvError) as ei:
        testenv.run_script(tmp_path, env, "x.sh", _run([]))
    assert SECRET not in str(ei.value)
    assert "TEST_DB_URL" in str(ei.value)


def test_run_script_missing_url_env(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_DB_URL", raising=False)
    with pytest.raises(TestEnvError, match="TEST_DB_URL is not set"):
        testenv.run_script(tmp_path, _env(), "x.sh", _run([]))


def test_run_script_passes_only_url_env_from_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_DB_URL", raising=False)
    (tmp_path / ".env").write_text(f"TEST_DB_URL={SECRET}\nTEST_BUYER_USER=bob\n")
    calls: list = []
    assert testenv.run_script(tmp_path, _env(), "s.sh", _run(calls, 3)) == 3
    cmd, kw = calls[0]
    assert cmd == ["bash", "s.sh"]
    assert kw["cwd"] == tmp_path and kw["timeout"] == testenv.SCRIPT_TIMEOUT
    assert kw["env"]["TEST_DB_URL"] == SECRET
    assert "TEST_BUYER_USER" not in kw["env"]


def test_run_script_timeout_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_DB_URL", SECRET)

    def run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)

    with pytest.raises(TestEnvError, match="timed out"):
        testenv.run_script(tmp_path, _env(), "s.sh", run)


def _root(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("TEST_DB_URL", SECRET)
    (tmp_path / ".kb").mkdir()
    (tmp_path / ".kb/test-env.yaml").write_text(EXAMPLE.read_text())
    return tmp_path


def test_verify_prints_each_item_and_exits_1_on_any_fail(tmp_path, monkeypatch, capsys):
    root = _root(tmp_path, monkeypatch)
    http = _http(
        {
            "https://staging.example.test": (200, b""),
            "https://api.staging.example.test": (503, b""),
            "https://staging.example.test/version": (200, b'{"commit":"abc"}'),
            "https://api.staging.example.test/health": (200, b'{"git_sha":"d1"}'),
        }
    )
    assert testenv.verify(root, http, _run([])) == 1
    out = capsys.readouterr().out.splitlines()
    assert "ok shop-fe url: 200" in out
    assert any(ln.startswith("FAIL shop-api api_base") for ln in out)
    assert any(ln.startswith("ok db.check") for ln in out)
    assert any(ln.startswith("ok db.seeds.checkout-basic") for ln in out)
    assert any(ln.startswith("ok shop-fe version: abc") for ln in out)
    assert SECRET not in "\n".join(out)


def test_verify_all_ok_exits_0(tmp_path, monkeypatch):
    assert (
        testenv.verify(_root(tmp_path, monkeypatch), _http({}), _run([])) == 1
    )  # no commit in "{}"
    http = _http(
        {
            "https://staging.example.test/version": (
                200,
                json.dumps({"commit": "a"}).encode(),
            ),
            "https://api.staging.example.test/health": (
                200,
                json.dumps({"git_sha": "b"}).encode(),
            ),
        }
    )
    assert testenv.verify(tmp_path, http, _run([])) == 0


def test_verify_failing_script_is_fail(tmp_path, monkeypatch, capsys):
    root = _root(tmp_path, monkeypatch)
    assert testenv.verify(root, _http({}), _run([], 2)) == 1
    assert "FAIL db.check: exit 2" in capsys.readouterr().out


def test_run_script_refuses_protected_url_with_userinfo(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_DB_URL", "postgres://u:p@prod/db/")
    env = _env(protected_urls=["postgres://prod/db"])
    calls: list = []
    with pytest.raises(TestEnvError, match="protected") as ei:
        testenv.run_script(tmp_path, env, "x.sh", _run(calls))
    assert calls == [] and "u:p" not in str(ei.value)


def test_run_script_oserror_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_DB_URL", SECRET)

    def run(cmd, **kw):
        raise FileNotFoundError("bash")

    with pytest.raises(TestEnvError, match="s.sh could not run"):
        testenv.run_script(tmp_path, _env(), "s.sh", run)
