"""`pick_tester`: resume, strategy amend, next story, cooling."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from strata_kb.autorun.picker import Task, pick_tester
from strata_kb.claimclient import LocalClaims
from strata_kb.errors import KbError
from tests.test_strategyhub import MISSION_ID, US1, _doc
from tests.test_test_next import _two_done

US3 = f"{MISSION_ID}-US3"
HEADER = "| Rank | Target | Pin | Risk | Why | Types |\n|---|---|---|---|---|---|\n"
CLEAN = _doc(HEADER + f"| 1 | {MISSION_ID} | rev 1 | High | core | API |\n")
GOOD_ROWS = HEADER + f"| 1 | {US1} | rev 1 | High | core | API |\n"


class Claims:
    def __init__(self, claims=(), error: Exception | None = None):
        self.claims, self.error = list(claims), error

    def held(self, repo="", ticket="", role=""):
        assert role == "tester"
        if self.error:
            raise self.error
        return self.claims


def _fake_run(*codes):
    calls: list[list[str]] = []
    it = iter(codes)

    def run(argv, **kw):
        calls.append(argv)
        return SimpleNamespace(returncode=next(it), stdout="", stderr="boom")

    run.calls = calls  # type: ignore[attr-defined]
    return run


@pytest.fixture
def env(tmp_path):
    root, kb = tmp_path / "repo", tmp_path / ".kb"
    (root / "docs").mkdir(parents=True)
    kb.mkdir()
    return root, kb


def _strategy(root, text):
    (root / "docs" / "test-strategy.md").write_text(text, encoding="utf-8")


def _pick(env, plan_hub, claims=None, run=None, **kw):
    root, kb = env
    return pick_tester(
        root,
        kb,
        plan_hub,
        claims_client=claims or Claims(),
        run=run or _fake_run(0, 0, 0),
        **kw,
    )


def _claim(ticket, cid=1, **kw):
    return {"id": cid, "ticket": ticket, "role": "tester", **kw}


def test_pick_tester_resumes_own_working_claim(env, plan_hub):
    LocalClaims(env[1]).put(US1, 7, "tok")
    pick = _pick(env, plan_hub, Claims([_claim(US1, 7, phase="working")]))
    assert pick.task == Task("tester-test-story", US1) and pick.cause == "task"


@pytest.mark.parametrize(
    "kw",
    [
        {"phase": "publishing", "pr": "u"},
        {"phase": "review", "pr": "u"},
        {"state": "stopped"},
    ],
)
def test_pick_tester_does_not_resume_parked_claim(env, plan_hub, kw):
    LocalClaims(env[1]).put(US1, 7, "tok")
    run = _fake_run(4)
    pick = _pick(env, plan_hub, Claims([_claim(US1, 7, **kw)]), run=run)
    # review/publishing stay held (no duplicate round); stopped is freed
    if kw.get("state") == "stopped":
        assert pick.task is None and run.calls and pick.cause == "waiting"
    else:
        assert (pick.task, pick.cause) == (None, "waiting") and not run.calls


@pytest.mark.parametrize("phase", ["review", "publishing"])
def test_pick_tester_resumes_review_phase_claim_without_pr(env, plan_hub, phase):
    """Q1 sets `review` before any PR exists; only a claim with a PR is parked."""
    LocalClaims(env[1]).put(US1, 7, "tok")
    pick = _pick(env, plan_hub, Claims([_claim(US1, 7, phase=phase)]))
    assert pick.task == Task("tester-test-story", US1)


@pytest.mark.parametrize(
    "kw", [{"skip": {f"tester-test-story:{US1}"}}, {"waiting": frozenset({US1})}]
)
def test_pick_tester_resume_honours_skip_and_waiting(env, plan_hub, kw):
    LocalClaims(env[1]).put(US1, 7, "tok")
    pick = _pick(env, plan_hub, Claims([_claim(US1, 7, phase="working")]), **kw)
    assert pick.task != Task("tester-test-story", US1)


def test_pick_tester_amend_on_coverage_finding(env, plan_hub):
    _strategy(env[0], _doc(GOOD_ROWS.replace(US1, "M-nope-US1")))
    assert _pick(env, plan_hub).task == Task("tester-strategy", "--amend")


def test_pick_tester_no_amend_for_tc_revision_only(env, plan_hub):
    _strategy(env[0], CLEAN)
    pick = _pick(env, plan_hub)
    assert pick.task == Task("tester-test-story", US1)


def test_pick_tester_amend_skipped_key_falls_to_story(env, plan_hub):
    _strategy(env[0], _doc(GOOD_ROWS.replace(US1, "M-nope-US1")))
    pick = _pick(env, plan_hub, skip={"tester-strategy:--amend"})
    assert pick.task == Task("tester-test-story", US1)


def test_pick_tester_skips_story_held_by_other_tester(env, plan_hub):
    _two_done(plan_hub)
    pick = _pick(env, plan_hub, Claims([_claim(US1, 9)]))
    assert pick.task == Task("tester-test-story", US3)


def test_pick_tester_not_deployed_story_is_cooled_next_tried(env, plan_hub):
    _two_done(plan_hub)
    run = _fake_run(4, 0)
    pick = _pick(env, plan_hub, run=run)
    assert pick.task == Task("tester-test-story", US3)
    assert pick.cooled == (US1,)
    assert run.calls[0] == ["kb", "test-env", "deployed", US1]


def test_pick_tester_other_deploy_exit_raises(env, plan_hub):
    with pytest.raises(KbError):
        _pick(env, plan_hub, run=_fake_run(1))


def test_pick_tester_nothing_testable_is_nothing(env, plan_hub):
    # US1 is testable on the plan hub; park the whole plan via an empty hub view
    plan_hub.federation_dir.joinpath("dev-one/dev-svc/history.md").write_text(
        "", encoding="utf-8"
    )
    pick = _pick(env, plan_hub)
    assert (pick.task, pick.cause) == (None, "nothing")


def test_pick_tester_all_held_is_waiting(env, plan_hub):
    pick = _pick(env, plan_hub, Claims([_claim(US1, 9)]))
    assert (pick.task, pick.cause) == (None, "waiting")


def test_pick_tester_waiting_and_skip_are_passed_over(env, plan_hub):
    assert _pick(env, plan_hub, waiting=frozenset({US1})).cause == "waiting"
    assert _pick(env, plan_hub, skip={f"tester-test-story:{US1}"}).cause == "skipped"


def test_pick_tester_claim_read_error_raises(env, plan_hub):
    with pytest.raises(KbError):
        _pick(env, plan_hub, Claims(error=KbError("hub down")))


def test_pick_tester_bad_strategy_no_amend(env, plan_hub, monkeypatch):
    from strata_kb.autorun import picker

    def boom(text):
        raise ValueError("bad table")

    monkeypatch.setattr(picker.teststrategy, "parse", boom)
    _strategy(env[0], CLEAN)
    assert _pick(env, plan_hub).task == Task("tester-test-story", US1)


def test_pick_tester_plan_not_on_hub_no_crash(env, plan_hub):
    _strategy(env[0], _doc(GOOD_ROWS).replace("ba-one", "ba-gone"))
    pick = _pick(env, plan_hub, skip={"tester-strategy:--amend"})
    assert (pick.task, pick.cause) == (None, "skipped")  # amend due but skipped


def test_pick_tester_unsafe_story_id_is_skipped(env, plan_hub, monkeypatch):
    from strata_kb.autorun import picker

    # only the picker's view: hub reading needs the real safe_name
    monkeypatch.setattr(
        picker, "planstatus", SimpleNamespace(safe_name=lambda s: False)
    )
    run = _fake_run()
    assert _pick(env, plan_hub, run=run).cause == "waiting" and not run.calls


def test_pick_tester_reads_default_branch_when_remote(env, plan_hub, tmp_path):
    root, _ = env
    git = lambda *a, cwd=root: subprocess.run(  # noqa: E731
        ["git", *a], cwd=cwd, check=True, capture_output=True
    )
    bare = tmp_path / "origin.git"
    git("init", "--bare", "-b", "main", str(bare), cwd=tmp_path)
    git("init", "-b", "main")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    _strategy(root, _doc(GOOD_ROWS.replace(US1, "M-nope-US1")))
    git("add", ".")
    git("commit", "-m", "s")
    git("remote", "add", "origin", str(bare))
    git("push", "-u", "origin", "main")
    git("remote", "set-head", "origin", "main")
    _strategy(root, CLEAN)  # working tree differs: the remote copy wins
    assert _pick(env, plan_hub).task == Task("tester-strategy", "--amend")


def test_pick_tester_one_skipped_one_held_is_waiting(env, plan_hub):
    _two_done(plan_hub)
    pick = _pick(
        env,
        plan_hub,
        Claims([_claim(US3, 9)]),
        skip={f"tester-test-story:{US1}"},
    )
    assert (pick.task, pick.cause) == (None, "waiting")


def test_pick_tester_unsafe_claim_ticket_not_resumed(env, plan_hub):
    bad = "../x"
    LocalClaims(env[1]).put(bad, 7, "tok")
    pick = _pick(env, plan_hub, Claims([_claim(bad, 7)]))
    assert pick.task != Task("tester-test-story", bad)
