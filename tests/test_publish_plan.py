"""publish.plan(): the `kb publish` route, decided as a library call (1.15.0).
Each case is called directly; the CLI behaviour on top of it is pinned by
the existing publish CLI tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from strata_kb import publish
from strata_kb.publish import PublishError


def _kb(root: Path, config: str) -> Path:
    kb_dir = root / ".kb"
    kb_dir.mkdir(parents=True)
    (kb_dir / "config.yaml").write_text(config, encoding="utf-8")
    return kb_dir


def _git(run_git, root: Path) -> None:
    run_git(root, "init")


@pytest.mark.parametrize(
    ("pr", "direct", "mode"),
    [(False, False, "auto"), (True, False, "pr"), (False, True, "direct")],
)
def test_child_publishes_a_snapshot(tmp_path, pr, direct, mode):
    kb_dir = _kb(tmp_path, "kind: child\nhub: ../hub\n")
    plan = publish.plan(kb_dir, "", pr=pr, direct=direct)
    assert plan.route == "snapshot"
    assert plan.mode == mode
    # resolved later, after the unreviewed gate, as before
    assert plan.hub_ref is None
    assert not plan.self_publish and not plan.refresh_code


def test_dev_refreshes_its_code_doc(tmp_path):
    kb_dir = _kb(tmp_path, "kind: dev\nhub: ../hub\n")
    plan = publish.plan(kb_dir, "", pr=False, direct=False)
    assert plan.route == "snapshot" and plan.refresh_code


def test_intake_is_the_route_unless_a_mode_is_forced(tmp_path):
    kb_dir = _kb(tmp_path, "kind: child\nintake: https://hub.example\n")
    plan = publish.plan(kb_dir, "", pr=False, direct=False)
    assert plan.route == "intake"
    assert plan.intake_url == "https://hub.example"
    assert publish.plan(kb_dir, "", pr=False, direct=True).route == "snapshot"


def test_pr_and_direct_are_refused(tmp_path):
    kb_dir = _kb(tmp_path, "kind: child\n")
    with pytest.raises(PublishError, match="mutually exclusive"):
        publish.plan(kb_dir, "", pr=True, direct=True)


def test_an_unreadable_config_is_refused_with_the_fix(tmp_path):
    kb_dir = _kb(tmp_path, "kind: [not, a, kind\n")
    with pytest.raises(PublishError, match="(?s)is unreadable .* fix the file"):
        publish.plan(kb_dir, "", pr=False, direct=False)


def test_a_root_hub_has_nothing_to_publish(tmp_path, monkeypatch):
    monkeypatch.delenv("STRATA_KB_HUB", raising=False)
    kb_dir = _kb(tmp_path, "kind: hub\n")
    with pytest.raises(PublishError, match="this is a root hub"):
        publish.plan(kb_dir, "", pr=False, direct=False)


def test_a_hub_pointing_at_itself_self_publishes_from_its_root(
    tmp_path, run_git, monkeypatch
):
    root = tmp_path / "hub"
    kb_dir = _kb(root, "kind: hub\nhub: .\n")
    _git(run_git, root)
    # from anywhere: `hub: .` anchors to the repo root, not the cwd
    monkeypatch.chdir(tmp_path)
    plan = publish.plan(kb_dir, "", pr=False, direct=False)
    assert plan.route == "snapshot" and plan.self_publish
    assert Path(plan.hub_ref or "").resolve() == root.resolve()


def test_a_self_publishing_hub_may_use_intake(tmp_path, run_git):
    root = tmp_path / "hub"
    kb_dir = _kb(root, "kind: hub\nhub: .\nintake: https://hub.example\n")
    _git(run_git, root)
    plan = publish.plan(kb_dir, "", pr=False, direct=False)
    assert plan.route == "intake" and plan.self_publish


def test_hub_to_hub_publishes_its_federation(tmp_path, run_git):
    upper = tmp_path / "upper"
    upper.mkdir()
    root = tmp_path / "mid"
    kb_dir = _kb(root, f"kind: hub\nhub: {upper}\n")
    _git(run_git, root)
    plan = publish.plan(kb_dir, "", pr=False, direct=False)
    assert plan.route == "federation"
    assert plan.hub_ref == str(upper)
    assert not plan.self_publish


def test_hub_to_hub_refuses_intake(tmp_path, run_git):
    upper = tmp_path / "upper"
    upper.mkdir()
    root = tmp_path / "mid"
    kb_dir = _kb(root, f"kind: hub\nhub: {upper}\nintake: https://x.example\n")
    _git(run_git, root)
    with pytest.raises(PublishError, match="not supported for hub-to-hub"):
        publish.plan(kb_dir, "", pr=False, direct=False)
    assert publish.plan(kb_dir, "", pr=False, direct=True).route == "federation"


def test_the_hub_flag_beats_the_config(tmp_path, run_git):
    upper = tmp_path / "upper"
    upper.mkdir()
    root = tmp_path / "mid"
    kb_dir = _kb(root, "kind: hub\nhub: .\n")
    _git(run_git, root)
    plan = publish.plan(kb_dir, str(upper), pr=False, direct=False)
    assert plan.route == "federation" and plan.hub_ref == str(upper)


def test_ba_refreshes_its_plan_doc(tmp_path):
    kb_dir = _kb(tmp_path, "kind: ba\nrepo_id: acme\nintake: https://hub.example\n")
    plan = publish.plan(kb_dir, "", pr=False, direct=False)
    assert plan.route == "intake" and plan.refresh_plan and not plan.refresh_code


def test_dev_does_not_refresh_a_plan_doc(tmp_path):
    kb_dir = _kb(tmp_path, "kind: dev\nhub: ../hub\n")
    assert not publish.plan(kb_dir, "", pr=False, direct=False).refresh_plan
