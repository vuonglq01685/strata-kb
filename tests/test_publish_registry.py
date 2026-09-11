"""Reviewer D's F-D1 repro: a hub with a registry must not accept a snapshot
published under someone else's repo-id."""
import pytest
import yaml

from center_kb import models, pubgate
from center_kb.publish import publish


@pytest.fixture
def governed_hub(hub_worktree, run_git):
    fed = hub_worktree / "federation"
    fed.mkdir(exist_ok=True)
    (fed / "registry.yaml").write_text(
        yaml.safe_dump({"repos": {"org/victim": "victim"}}),
        encoding="utf-8",
        newline="\n",
    )
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "hub: register org/victim")
    return hub_worktree


def _set_remote(run_git, root, url):
    run_git(root, "remote", "add", "origin", url)


def test_registered_publisher_may_publish_its_own_id(governed_hub, git_kb, run_git):
    _set_remote(run_git, git_kb["root"], "https://github.com/org/victim.git")
    report = publish(git_kb["kb"], str(governed_hub), repo_id=None, mode="direct")
    assert report.repo_id == "victim"
    assert (governed_hub / "federation" / "victim" / "index.yaml").exists()


def test_unregistered_publisher_cannot_publish_as_another_repo(
    governed_hub, git_kb, run_git
):
    # F-D1: the finding is that the attack REPLACES the victim's documents
    # (_snapshot replaces an entry wholesale -- see
    # test_republish_replaces_entry_wholesale), not merely that it creates a
    # fresh 'victim' entry. So publish as the real 'org/victim' first and
    # capture its bytes -- checking only for non-creation would pass
    # vacuously against a 'victim' entry that never existed.
    _set_remote(run_git, git_kb["root"], "https://github.com/org/victim.git")
    publish(git_kb["kb"], str(governed_hub), repo_id=None, mode="direct")
    index_path = governed_hub / "federation" / "victim" / "index.yaml"
    doc_path = governed_hub / "federation" / "victim" / "demo-doc" / "ch1-records.md"
    assert index_path.exists() and doc_path.exists()
    index_before = index_path.read_bytes()
    doc_before = doc_path.read_bytes()

    # Change the source between the legitimate publish and the attack. Without
    # this the attacker would snapshot byte-identical content, so "the victim's
    # bytes are unchanged" would hold even if the gate wrote first and refused
    # second -- the assertion would be measuring coincidence, not survival.
    doc_src = git_kb["kb"] / "demo-doc" / "ch1-records.md"
    doc_src.write_text(
        doc_src.read_text(encoding="utf-8") + "\n\nATTACKER CONTENT\n",
        encoding="utf-8",
    )
    run_git(git_kb["root"], "add", "-A")
    run_git(git_kb["root"], "commit", "-m", "attacker edit")
    run_git(
        git_kb["root"], "remote", "set-url", "origin",
        "https://github.com/org/attacker.git",
    )
    with pytest.raises(pubgate.GateError, match="is not registered on hub"):
        publish(git_kb["kb"], str(governed_hub), repo_id="victim", mode="direct")

    # non-creation: the attacker never gets a second entry of their own
    assert not (governed_hub / "federation" / "attacker").exists()
    # survival: the refused attack must not have touched the victim's files
    assert index_path.read_bytes() == index_before
    assert doc_path.read_bytes() == doc_before
    assert b"ATTACKER CONTENT" not in doc_path.read_bytes()


def test_registered_publisher_cannot_claim_a_different_repo_id(
    governed_hub, git_kb, run_git
):
    _set_remote(run_git, git_kb["root"], "https://github.com/org/victim.git")
    with pytest.raises(pubgate.GateError, match="not 'somebody-else'"):
        publish(git_kb["kb"], str(governed_hub), repo_id="somebody-else", mode="direct")


def test_governed_hub_with_remote_refuses_direct(
    governed_hub, git_kb, run_git, tmp_path
):
    # decide_mode's `governed and has_remote` refusal (pubgate.py:176-183) is
    # the actual enforcement for remote hubs -- every other governed-hub test
    # in this file uses hub_worktree, which has no remote, so that branch's
    # wiring into publish() was proved only by reading the line.
    origin = tmp_path / "hub-origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    run_git(governed_hub, "remote", "add", "origin", str(origin))
    run_git(governed_hub, "push", "-u", "origin", "HEAD")
    origin_head_before = run_git(origin, "rev-parse", "HEAD")

    _set_remote(run_git, git_kb["root"], "https://github.com/org/victim.git")
    with pytest.raises(pubgate.GateError, match="takes contributions by PR"):
        publish(git_kb["kb"], str(governed_hub), repo_id="victim", mode="direct")

    assert run_git(origin, "rev-parse", "HEAD") == origin_head_before


def test_ungoverned_hub_is_unaffected(hub_worktree, git_kb):
    report = publish(git_kb["kb"], str(hub_worktree), repo_id="anything", mode="direct")
    assert report.repo_id == "anything"


def test_empty_registry_counts_as_ungoverned(hub_worktree, git_kb, run_git):
    fed = hub_worktree / "federation"
    fed.mkdir(exist_ok=True)
    (fed / "registry.yaml").write_text("repos: {}\n", encoding="utf-8", newline="\n")
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "hub: empty registry")
    report = publish(git_kb["kb"], str(hub_worktree), repo_id="anything", mode="direct")
    assert report.repo_id == "anything"


def test_unreadable_registry_fails_closed(hub_worktree, git_kb, run_git):
    fed = hub_worktree / "federation"
    fed.mkdir(exist_ok=True)
    (fed / "registry.yaml").write_text("repos: [not, a, mapping\n", encoding="utf-8")
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "hub: broken registry")
    from center_kb.publish import PublishError

    with pytest.raises(PublishError, match="registry.yaml is invalid"):
        publish(git_kb["kb"], str(hub_worktree), repo_id="anything", mode="direct")


def test_case_folded_repo_id_cannot_clobber_a_sibling(hub_worktree, git_kb):
    publish(git_kb["kb"], str(hub_worktree), repo_id="victim", mode="direct")
    with pytest.raises(pubgate.GateError, match="collides with the existing entry"):
        publish(git_kb["kb"], str(hub_worktree), repo_id="VICTIM", mode="direct")
    assert (hub_worktree / "federation" / "victim" / "index.yaml").exists()


def test_reserved_device_name_is_refused_before_anything_is_written(
    hub_worktree, git_kb
):
    with pytest.raises(pubgate.GateError, match="reserved Windows device name"):
        publish(git_kb["kb"], str(hub_worktree), repo_id="CON", mode="direct")
    assert not (hub_worktree / "federation" / "CON").exists()


def test_registry_map_flattens_the_model():
    from center_kb import federation

    reg = models.Registry(repos={"org/repo": "rid"})
    assert federation.registry_map(reg) == {"org/repo": "rid"}
