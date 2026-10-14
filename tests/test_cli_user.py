"""`kb user`: hub UI account management."""

from __future__ import annotations

from typer.testing import CliRunner

from strata_kb.cli import app
from strata_kb.serving.accounts import Accounts, check_password

runner = CliRunner()


def _kb(tmp_path):
    (tmp_path / ".kb").mkdir(exist_ok=True)
    return str(tmp_path / ".kb")


def _db(tmp_path) -> Accounts:
    return Accounts(tmp_path / ".kb-auth" / "users.db")


def _add(tmp_path, name="boss", role="admin", pw="pw-123"):
    return runner.invoke(
        app,
        ["user", "add", name, "--role", role, "--kb", _kb(tmp_path)],
        input=f"{pw}\n{pw}\n",
    )


def test_user_add_prompts_twice_and_stores(tmp_path):
    r = _add(tmp_path)
    assert r.exit_code == 0
    assert _db(tmp_path).verify("boss", "pw-123")


def test_user_add_mismatched_confirmation_fails(tmp_path):
    r = runner.invoke(
        app,
        ["user", "add", "boss", "--role", "admin", "--kb", _kb(tmp_path)],
        input="a\nb\n",
    )
    assert r.exit_code != 0
    assert _db(tmp_path).count() == 0


def test_user_add_bad_role_exits_1(tmp_path):
    r = _add(tmp_path, role="root")
    assert r.exit_code == 1
    assert _db(tmp_path).count() == 0


def test_user_add_duplicate_exits_1(tmp_path):
    assert _add(tmp_path).exit_code == 0
    assert _add(tmp_path).exit_code == 1


def test_user_passwd_changes_password(tmp_path):
    _add(tmp_path)
    r = runner.invoke(
        app, ["user", "passwd", "boss", "--kb", _kb(tmp_path)], input="new-pw\nnew-pw\n"
    )
    assert r.exit_code == 0
    assert _db(tmp_path).verify("boss", "new-pw")
    assert not _db(tmp_path).verify("boss", "pw-123")


def test_user_passwd_unknown_user_exits_1_on_stderr(tmp_path):
    r = runner.invoke(
        app, ["user", "passwd", "ghost", "--kb", _kb(tmp_path)], input="x\nx\n"
    )
    assert r.exit_code == 1
    assert "ghost" in r.stderr
    assert "Traceback" not in r.output


def test_user_role_changes_role(tmp_path):
    _add(tmp_path)
    _add(tmp_path, name="ann", role="dev", pw="p")
    r = runner.invoke(app, ["user", "role", "ann", "ba", "--kb", _kb(tmp_path)])
    assert r.exit_code == 0
    user = _db(tmp_path).get("ann")
    assert user is not None and user.role == "ba"


def test_user_role_demote_last_admin_exits_1_on_stderr(tmp_path):
    _add(tmp_path)
    r = runner.invoke(app, ["user", "role", "boss", "dev", "--kb", _kb(tmp_path)])
    assert r.exit_code == 1
    assert "last admin" in r.stderr
    assert "Traceback" not in r.output


def test_user_list_never_prints_hashes(tmp_path):
    _add(tmp_path)
    r = runner.invoke(app, ["user", "list", "--kb", _kb(tmp_path)])
    assert r.exit_code == 0
    assert "scrypt$" not in r.output
    assert "boss" in r.output and "admin" in r.output


def test_user_remove_deletes(tmp_path):
    _add(tmp_path)
    _add(tmp_path, name="ann", role="dev", pw="p")
    r = runner.invoke(app, ["user", "remove", "ann", "--kb", _kb(tmp_path)])
    assert r.exit_code == 0
    assert _db(tmp_path).get("ann") is None


def test_user_remove_last_admin_exits_1(tmp_path):
    _add(tmp_path)
    r = runner.invoke(app, ["user", "remove", "boss", "--kb", _kb(tmp_path)])
    assert r.exit_code == 1
    assert "last admin" in r.stderr
    assert _db(tmp_path).get("boss") is not None


def test_user_remove_unknown_exits_1(tmp_path):
    r = runner.invoke(app, ["user", "remove", "ghost", "--kb", _kb(tmp_path)])
    assert r.exit_code == 1
    assert "ghost" in r.stderr


def test_user_hash_prints_verifiable_hash():
    r = runner.invoke(app, ["user", "hash"], input="pw\npw\n")
    assert r.exit_code == 0
    line = r.stdout.strip().splitlines()[-1]
    assert check_password("pw", line)
    # stdout is the bare hash; stderr carries a quoted, compose-safe .env line.
    assert "STRATA_KB_BOOTSTRAP_PASSWORD_HASH" not in r.stdout
    assert f"STRATA_KB_BOOTSTRAP_PASSWORD_HASH='{line}'" in r.stderr


def test_user_add_before_first_server_start_excludes_auth_dir_from_git(tmp_path):
    (tmp_path / ".git").mkdir()
    assert _add(tmp_path).exit_code == 0
    exclude = (tmp_path / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert ".kb-auth/" in exclude.splitlines()


def test_user_commands_refuse_a_missing_kb_dir_and_create_nothing(tmp_path):
    kb = str(tmp_path / "typo" / ".kb")
    r = runner.invoke(
        app, ["user", "add", "boss", "--role", "admin", "--kb", kb], input="p\np\n"
    )
    assert r.exit_code == 1
    assert len(r.stderr.strip().splitlines()) == 1 and "typo" in r.stderr
    assert not (tmp_path / "typo").exists()
    assert runner.invoke(app, ["user", "list", "--kb", kb]).exit_code == 1
