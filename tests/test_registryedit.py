import subprocess
from pathlib import Path

import pytest
import yaml

from strata_kb import gitio
from strata_kb.errors import KbError
from strata_kb.models import Registry
from strata_kb.registryedit import (
    add_entry,
    commit_registry,
    dump_registry,
    remove_entry,
    set_auto_merge,
)


def test_add_entry_validates_repo_id_and_uniqueness():
    reg = Registry(repos={"a/b": "rb"})
    with pytest.raises(KbError):
        add_entry(reg, "A/B", "x")  # case-colliding key
    with pytest.raises(KbError):
        add_entry(reg, "e/f", "rb")  # repo-id claimed
    with pytest.raises(KbError):
        add_entry(reg, "e/f", "../evil")  # normalize_repo_id
    with pytest.raises(KbError):
        add_entry(reg, "e/f", "ok", kind="nope")
    added = add_entry(reg, "e/f", "rf", kind="dev", auto_merge=True).resolve("e/f")
    assert added is not None and added.auto_merge


def test_add_entry_rejects_repo_id_claimed_by_mapping_entry():
    reg = Registry(repos={"a/b": {"repo_id": "rb", "workflow": "w"}})
    with pytest.raises(KbError):
        add_entry(reg, "e/f", "rb")


def test_add_entry_rejects_blank_repo_key():
    with pytest.raises(KbError):
        add_entry(Registry(), " ", "rb")


def test_remove_and_toggle_unknown_key_raise():
    with pytest.raises(KbError):
        remove_entry(Registry(), "x/y")
    with pytest.raises(KbError):
        set_auto_merge(Registry(), "x/y", True)


def test_remove_and_toggle_work_and_keep_other_fields():
    reg = Registry(
        repos={"a/b": {"repo_id": "rb", "workflow": "w", "kind": "dev"}, "c/d": "rd"}
    )
    toggled = set_auto_merge(reg, "a/b", True).resolve("a/b")
    assert toggled is not None
    assert (toggled.auto_merge, toggled.workflow, toggled.kind) == (True, "w", "dev")
    assert list(remove_entry(reg, "a/b").repos) == ["c/d"]


def test_inputs_are_not_mutated():
    reg = Registry(repos={"a/b": "rb"})
    set_auto_merge(reg, "a/b", True)
    add_entry(reg, "c/d", "rd")
    remove_entry(reg, "a/b")
    assert reg.repos == {"a/b": "rb"}


def test_dump_round_trips_and_keeps_order():
    reg = Registry(repos={"z/z": "rz", "a/a": {"repo_id": "ra", "auto_merge": True}})
    text = dump_registry(reg)
    assert text.index("z/z") < text.index("a/a") and "rz" in text
    assert Registry.model_validate(yaml.safe_load(text)) == reg


def test_dump_plain_string_when_only_repo_id_and_only_non_defaults_otherwise():
    reg = Registry(
        repos={"a/b": "rb", "c/d": {"repo_id": "rd", "kind": "dev", "workflow": ""}}
    )
    assert yaml.safe_load(dump_registry(reg)) == {
        "repos": {"a/b": "rb", "c/d": {"repo_id": "rd", "kind": "dev"}}
    }


def test_dump_empty_registry_is_valid():
    text = dump_registry(Registry())
    assert Registry.model_validate(yaml.safe_load(text)) == Registry()


@pytest.fixture
def git_identity(monkeypatch):
    for who in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{who}_NAME", "test")
        monkeypatch.setenv(f"GIT_{who}_EMAIL", "test@test.local")


def test_commit_registry_lands_on_default_branch(fed_hub, run_git, git_identity):
    pushed = []
    commit_registry(
        fed_hub,
        "repos: {}\n",
        "registry: test (by admin)",
        lambda wt, br: pushed.append((wt, br)),
    )
    assert [br for _, br in pushed] == [gitio.default_branch(fed_hub)]
    # worktree removed, hub checkout untouched
    assert not pushed[0][0].exists()
    assert gitio.is_dirty(fed_hub, fed_hub / "federation") is False
    assert not (fed_hub / "federation" / "registry.yaml").exists()


def test_commit_registry_commits_only_the_registry(fed_hub, run_git, git_identity):
    seen = {}

    def push(wt: Path, br: str) -> None:
        (wt / ".kb-auth").mkdir(exist_ok=True)
        seen["subject"] = run_git(wt, "log", "-1", "--format=%s")
        seen["files"] = run_git(wt, "show", "--name-only", "--format=", "HEAD")

    commit_registry(fed_hub, "repos: {}\n", "registry: add x (by admin)", push)
    assert seen["subject"] == "registry: add x (by admin)"
    assert seen["files"] == "federation/registry.yaml"


def test_commit_registry_rejects_invalid_text_without_pushing(fed_hub):
    pushed = []
    with pytest.raises(KbError):
        commit_registry(
            fed_hub, "repos: {a/b: [}", "m", lambda wt, br: pushed.append(br)
        )
    with pytest.raises(KbError):
        commit_registry(
            fed_hub, "repos: {x: 1, y: 2, z: 3}\nbogus: 1\n", "m", lambda w, b: None
        )
    assert pushed == []


def test_commit_registry_removes_worktree_when_push_raises(fed_hub, git_identity):
    seen = []

    def push(wt: Path, br: str) -> None:
        seen.append(wt)
        raise gitio.GitError("rejected")

    with pytest.raises(gitio.GitError):
        commit_registry(fed_hub, "repos: {}\n", "m", push)
    assert not seen[0].exists()


def test_push_head_with_token_refuses_non_fast_forward(tmp_path, run_git):
    origin = tmp_path / "origin.git"
    run_git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    a, b = tmp_path / "a", tmp_path / "b"
    run_git(tmp_path, "clone", str(origin), str(a))
    run_git(a, "checkout", "-b", "main")
    (a / "f").write_text("1", encoding="utf-8", newline="\n")
    run_git(a, "add", "f")
    run_git(a, "commit", "-m", "one")
    gitio.push_head_with_token(a, str(origin), "", "main")
    run_git(tmp_path, "clone", str(origin), str(b))
    (b / "f").write_text("remote", encoding="utf-8", newline="\n")
    run_git(b, "commit", "-am", "remote")
    gitio.push_head_with_token(b, str(origin), "", "main")
    (a / "f").write_text("diverged", encoding="utf-8", newline="\n")
    run_git(a, "commit", "-am", "diverged")
    with pytest.raises(gitio.GitError):
        gitio.push_head_with_token(a, str(origin), "", "main")
    tip = subprocess.run(
        ["git", "log", "-1", "--format=%s", "main"],
        cwd=origin,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert tip == "remote"


def test_push_head_with_token_fast_forwards(tmp_path, run_git):
    origin = tmp_path / "origin.git"
    run_git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    a = tmp_path / "a"
    run_git(tmp_path, "clone", str(origin), str(a))
    run_git(a, "checkout", "-b", "main")
    (a / "f").write_text("1", encoding="utf-8", newline="\n")
    run_git(a, "add", "f")
    run_git(a, "commit", "-m", "one")
    gitio.push_head_with_token(a, str(origin), "", "main")
    assert run_git(origin, "log", "-1", "--format=%s", "main") == "one"
