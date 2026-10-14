"""Accounts store: scrypt hashes, SQLite users table, session key, env bootstrap."""

from __future__ import annotations

import sys

import pytest

from strata_kb.serving.accounts import (
    AccountError,
    Accounts,
    bootstrap_from_env,
    check_password,
    ensure_git_exclude,
    hash_password,
    load_or_create_session_key,
    password_version,
)


def test_hash_round_trip_and_format():
    h = hash_password("pw-1")
    assert h.startswith("scrypt$n=16384,r=8,p=1$")
    assert check_password("pw-1", h) and not check_password("pw-2", h)
    assert hash_password("pw-1") != h  # fresh salt


def test_check_password_rejects_malformed_hash():
    assert check_password("x", "not-a-hash") is False


def test_add_get_is_case_insensitive(tmp_path):
    a = Accounts(tmp_path / "users.db")
    a.add("vuonglq01685", "pw", "admin")
    assert a.get("VuongLQ01685").username == "vuonglq01685"
    assert a.verify("VUONGLQ01685", "pw").role == "admin"
    assert a.verify("vuonglq01685", "bad") is None
    assert a.verify("nobody", "pw") is None


def test_add_rejects_bad_role_and_duplicate(tmp_path):
    a = Accounts(tmp_path / "users.db")
    with pytest.raises(AccountError):
        a.add("u", "pw", "root")
    a.add("u", "pw", "dev")
    with pytest.raises(AccountError):
        a.add("U", "pw", "dev")


def test_last_admin_cannot_be_removed_or_demoted(tmp_path):
    a = Accounts(tmp_path / "users.db")
    a.add("boss", "pw", "admin")
    with pytest.raises(AccountError):
        a.remove("boss")
    with pytest.raises(AccountError):
        a.set_role("boss", "dev")


def test_second_admin_allows_remove_and_demote(tmp_path):
    a = Accounts(tmp_path / "users.db")
    a.add("boss", "pw", "admin")
    a.add("deputy", "pw", "admin")
    a.set_role("deputy", "ba")
    a.add("deputy2", "pw", "admin")
    a.remove("deputy2")
    assert [u.username for u in a.list()] == ["boss", "deputy"]


def test_unknown_user_mutations_raise(tmp_path):
    a = Accounts(tmp_path / "users.db")
    for call in (
        lambda: a.set_password("ghost", "pw"),
        lambda: a.set_role("ghost", "dev"),
        lambda: a.remove("ghost"),
    ):
        with pytest.raises(AccountError):
            call()
    a.add("u", "pw", "dev")
    with pytest.raises(AccountError):
        a.set_role("u", "root")


def test_set_password_changes_version(tmp_path):
    a = Accounts(tmp_path / "users.db")
    a.add("u", "pw", "dev")
    before = password_version(a.get("u").password_hash)
    assert len(before) == 16
    a.set_password("u", "pw2")
    assert password_version(a.get("u").password_hash) != before
    assert a.verify("u", "pw2") is not None and a.verify("u", "pw") is None


def test_add_hashed_rejects_non_hash(tmp_path):
    a = Accounts(tmp_path / "users.db")
    with pytest.raises(AccountError):
        a.add_hashed("u", "plain", "dev")
    a.add_hashed("u", hash_password("pw"), "dev")
    assert a.verify("u", "pw").role == "dev"


def test_empty_username_or_password_rejected(tmp_path):
    a = Accounts(tmp_path / "users.db")
    with pytest.raises(AccountError):
        a.add(" ", "pw", "dev")
    with pytest.raises(AccountError):
        a.add("u", "", "dev")


def test_session_key_is_stable_and_private(tmp_path):
    k1 = load_or_create_session_key(tmp_path / ".kb-auth")
    assert len(k1) == 32 and load_or_create_session_key(tmp_path / ".kb-auth") == k1
    if sys.platform != "win32":
        mode = (tmp_path / ".kb-auth" / "session.key").stat().st_mode & 0o777
        assert oct(mode) == "0o600"


def test_auth_dir_for_is_sibling_of_kb_dir(tmp_path):
    from strata_kb.serving.accounts import auth_dir_for

    assert auth_dir_for(tmp_path / "hub" / ".kb") == tmp_path / "hub" / ".kb-auth"


def test_bootstrap_creates_admin_only_when_empty(tmp_path):
    a = Accounts(tmp_path / "users.db")
    env = {
        "STRATA_KB_BOOTSTRAP_ADMIN": "boss",
        "STRATA_KB_BOOTSTRAP_PASSWORD_HASH": hash_password("pw"),
    }
    assert "created" in bootstrap_from_env(a, env)
    assert a.verify("boss", "pw").role == "admin"
    assert "ignored" in bootstrap_from_env(a, env)  # restart: no duplicate, no raise
    assert a.count() == 1


def test_bootstrap_without_env_is_silent(tmp_path):
    a = Accounts(tmp_path / "users.db")
    assert bootstrap_from_env(a, {}) == ""


def test_bootstrap_with_one_var_creates_nothing(tmp_path):
    a = Accounts(tmp_path / "users.db")
    msg = bootstrap_from_env(a, {"STRATA_KB_BOOTSTRAP_ADMIN": "boss"})
    assert "STRATA_KB_BOOTSTRAP_PASSWORD_HASH" in msg and a.count() == 0


def test_bootstrap_rejects_plaintext_in_hash_var(tmp_path):
    a = Accounts(tmp_path / "users.db")
    msg = bootstrap_from_env(
        a,
        {
            "STRATA_KB_BOOTSTRAP_ADMIN": "boss",
            "STRATA_KB_BOOTSTRAP_PASSWORD_HASH": "plain-password",
        },
    )
    assert a.count() == 0 and "kb user hash" in msg
    assert "plain-password" not in msg


def test_ensure_git_exclude_is_idempotent(tmp_path, run_git):
    run_git(tmp_path, "init")
    assert ensure_git_exclude(tmp_path) is True
    assert ensure_git_exclude(tmp_path) is False
    assert (tmp_path / ".git/info/exclude").read_text().count(".kb-auth/") == 1


def test_ensure_git_exclude_outside_git_is_noop(tmp_path):
    assert ensure_git_exclude(tmp_path) is False
