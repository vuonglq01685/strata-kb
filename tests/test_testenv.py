from pathlib import Path

import pytest
import yaml

from strata_kb import testenv
from strata_kb.testenv import TestEnvError, load

EXAMPLE = Path(testenv.__file__).parent / "templates/init/test-env.example.yaml"


def _write(root: Path, data) -> None:
    (root / ".kb").mkdir(exist_ok=True)
    (root / ".kb/test-env.yaml").write_text(yaml.safe_dump(data))


def _base() -> dict:
    return yaml.safe_load(EXAMPLE.read_text())


def test_load_valid_env(tmp_path):
    (tmp_path / ".kb").mkdir()
    (tmp_path / ".kb/test-env.yaml").write_text(EXAMPLE.read_text())
    env = load(tmp_path)
    assert env.retries == 3
    assert env.apps[0].repo == "shop-fe"
    assert env.accounts["buyer"].user_env == "TEST_BUYER_USER"


def test_refuses_credential_url_and_names_field(tmp_path):
    data = _base()
    data["apps"][0]["url"] = "postgres://u:p@h/db"
    _write(tmp_path, data)
    with pytest.raises(TestEnvError, match=r"apps\[0\]\.url") as e:
        load(tmp_path)
    assert "u:p" not in str(e.value)


def test_refuses_long_token_in_any_field(tmp_path):
    data = _base()
    data["name"] = "A1b2" * 10
    _write(tmp_path, data)
    with pytest.raises(TestEnvError, match="name") as e:
        load(tmp_path)
    assert "A1b2A1b2" not in str(e.value)


def test_env_var_names_must_be_upper_snake(tmp_path):
    data = _base()
    data["db"]["url_env"] = "test_db"
    _write(tmp_path, data)
    with pytest.raises(TestEnvError, match=r"db\.url_env"):
        load(tmp_path)


@pytest.mark.parametrize("bad", ["../x.sh", "/abs.sh"])
def test_script_paths_must_stay_in_repo(tmp_path, bad):
    data = _base()
    data["db"]["reset"] = bad
    _write(tmp_path, data)
    with pytest.raises(TestEnvError, match=r"db\.reset"):
        load(tmp_path)


def test_missing_file_says_run_tester_env_setup(tmp_path):
    with pytest.raises(TestEnvError, match="tester-env-setup"):
        load(tmp_path)


def test_check_prints_ok_and_problem(tmp_path, capsys):
    (tmp_path / ".kb").mkdir()
    (tmp_path / ".kb/test-env.yaml").write_text(EXAMPLE.read_text())
    assert testenv.check(tmp_path) == 0
    assert "test-env: OK" in capsys.readouterr().out
    (tmp_path / ".kb/test-env.yaml").unlink()
    assert testenv.check(tmp_path) == 1
    assert "tester-env-setup" in capsys.readouterr().err


def test_secret_like():
    assert testenv.secret_like("https://u:p@h/db")
    assert testenv.secret_like("x" * 32)
    assert not testenv.secret_like("https://staging.example.test/version")
