from pathlib import Path

import pytest
import yaml

from strata_kb import testenv
from strata_kb.testenv import TestEnvError, load

EXAMPLE = Path(testenv.__file__).parent / "templates/init/test-env.example.yaml"


def _write(root: Path, data) -> None:
    (root / ".kb").mkdir(exist_ok=True)
    (root / ".kb/test-env.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


def _base() -> dict:
    return yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))


def test_load_valid_env(tmp_path):
    (tmp_path / ".kb").mkdir()
    (tmp_path / ".kb/test-env.yaml").write_text(
        EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    env = load(tmp_path)
    assert env.retries == 3
    assert env.apps[0].repo == "shop-fe"
    assert env.accounts["buyer"].user_env == "TEST_BUYER_USER"


def test_retries_must_be_at_least_one(tmp_path):
    data = _base()
    data["retries"] = 0
    (tmp_path / ".kb").mkdir()
    (tmp_path / ".kb/test-env.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(testenv.TestEnvError, match="retries"):
        load(tmp_path)


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
    (tmp_path / ".kb/test-env.yaml").write_text(
        EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    assert testenv.check(tmp_path) == 0
    assert "test-env: OK" in capsys.readouterr().out
    (tmp_path / ".kb/test-env.yaml").unlink()
    assert testenv.check(tmp_path) == 1
    assert "tester-env-setup" in capsys.readouterr().err


def test_secret_like():
    assert testenv.secret_like("https://u:p@h/db")
    assert testenv.secret_like("x1" * 16)
    assert not testenv.secret_like("https://staging.example.test/version")


TOKEN = "ghp_" + "aB3x" * 9


def test_token_shaped_seed_key_refused_without_echo(tmp_path):
    data = _base()
    data["db"]["seeds"][TOKEN] = "tests/seeds/x.sh"
    _write(tmp_path, data)
    with pytest.raises(TestEnvError, match=r"db\.seeds \(key\)") as e:
        load(tmp_path)
    assert TOKEN not in str(e.value)


def test_token_shaped_top_level_key_refused_without_echo(tmp_path):
    data = _base()
    data[TOKEN] = 1
    _write(tmp_path, data)
    with pytest.raises(TestEnvError, match=r"top level \(key\)") as e:
        load(tmp_path)
    assert TOKEN not in "".join(e.value.problems)


def test_long_env_names_and_script_names_are_not_secrets(tmp_path):
    data = _base()
    data["db"]["url_env"] = "STAGING_PAYMENT_GATEWAY_DATABASE_URL"
    data["db"]["reset"] = "scripts/reset_staging_database_with_fixtures.sh"
    _write(tmp_path, data)
    assert load(tmp_path).db.url_env == "STAGING_PAYMENT_GATEWAY_DATABASE_URL"


def test_mixed_40_char_token_still_refused(tmp_path):
    data = _base()
    data["name"] = "a1" * 20
    _write(tmp_path, data)
    with pytest.raises(TestEnvError, match="name"):
        load(tmp_path)


def test_password_with_slash_refused_but_port_url_fine(tmp_path):
    assert testenv.secret_like("postgres://admin:ab/cd@h/db")
    assert not testenv.secret_like("https://host:8443/path")


def test_check_prints_one_line_per_problem(tmp_path, capsys):
    data = _base()
    data["db"]["url_env"] = "bad"
    data["db"]["reset"] = "/abs.sh"
    data["accounts"]["buyer"]["user_env"] = "bad"
    _write(tmp_path, data)
    assert testenv.check(tmp_path) == 1
    lines = capsys.readouterr().err.strip().splitlines()
    assert len(lines) == 3


def test_password_only_userinfo_is_secret_like():
    assert testenv.secret_like("redis://:hunter2@h:6379")


@pytest.mark.parametrize(
    "url", ["https://host:8443/x?email=a@b.test", "https://host:8443/api/@me"]
)
def test_port_then_later_at_sign_is_not_userinfo(url):
    assert not testenv.secret_like(url)


@pytest.mark.parametrize(
    ("url", "secret"),
    [
        ("postgres://u:1234/abc@h/db", True),
        ("redis://:hunter2@h:6379", True),
        ("https://host:8443/x?email=a@b.test", False),
        ("https://host:8443/api/@me", False),
    ],
)
def test_userinfo_edge_cases(url, secret):
    assert testenv.secret_like(url) is secret


@pytest.mark.parametrize("name", ["a/b", "a b"])
def test_env_name_with_slash_or_space_is_refused(tmp_path, name):
    data = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    data["name"] = name
    (tmp_path / ".kb").mkdir(exist_ok=True)
    (tmp_path / ".kb/test-env.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(TestEnvError, match="name"):
        load(tmp_path)
