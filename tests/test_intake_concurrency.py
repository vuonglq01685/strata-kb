"""Reviewer D's F-D4: two intake publishes for different repo-ids shared one
working tree, so beta's PR was based on publish/alpha and carried alpha's
unreviewed content -- and the clone stayed on publish/alpha for good."""
import threading
import time

import pytest

from center_kb import gitio, intake


def test_two_repo_ids_publishing_together_do_not_cross_contaminate(
    intake_cfg, hub_worktree, make_upload
):
    calls = []
    calls_lock = threading.Lock()

    def slow_create_pr(hub_full, token, branch, title, body, base, http=None):
        time.sleep(0.5)
        with calls_lock:
            calls.append({"branch": branch, "base": base, "title": title})
        return f"https://github.com/{hub_full}/pull/1"

    intake_cfg.pr_hook = slow_create_pr
    results = {}

    def run(rid):
        results[rid] = intake.intake_publish(
            intake_cfg, rid, f"c{rid}", f"org/{rid}", [], make_upload(rid)
        )

    t1 = threading.Thread(target=run, args=("alpha",))
    t2 = threading.Thread(target=run, args=("beta",))
    t1.start()
    time.sleep(0.3)
    t2.start()
    t1.join()
    t2.join()

    bases = {c["branch"]: c["base"] for c in calls}
    default = gitio.default_branch(hub_worktree)
    assert bases["publish/alpha"] == default
    assert bases["publish/beta"] == default

    beta_tree = gitio._run(
        hub_worktree, "ls-tree", "-r", "--name-only", "publish/beta"
    ).stdout
    assert "federation/beta/" in beta_tree
    assert "federation/alpha/" not in beta_tree

    assert gitio.current_branch(hub_worktree) == default


@pytest.mark.parametrize("scenario", ["success", "refusal"])
def test_no_worktree_is_left_behind(
    intake_cfg, hub_worktree, make_upload, monkeypatch, scenario
):
    """I-4: 'removed on every path' was only ever exercised by a
    SUCCESSFUL publish -- rewriting the finally-block cleanup to run only
    on success (leaking the worktree on every refusal/exception instead)
    left this test, and 106 others, fully green. The refusal branch here
    forces hashsync.apply_sync to raise, the same shape a real bad upload
    produces (see test_intake_upload_failure_leaves_no_dirty_leftovers in
    test_intake_core.py), and asserts the SAME clean worktree listing."""
    if scenario == "refusal":
        def boom(*a, **k):
            raise intake.hashsync.HashSyncError("boom")

        monkeypatch.setattr(intake.hashsync, "apply_sync", boom)
        with pytest.raises(intake.IntakeError):
            intake.intake_publish(
                intake_cfg, "alpha", "c1", "org/alpha", [], make_upload("alpha")
            )
    else:
        intake.intake_publish(
            intake_cfg, "alpha", "c1", "org/alpha", [], make_upload("alpha")
        )
    listing = gitio._run(hub_worktree, "worktree", "list").stdout
    assert listing.strip().count("\n") == 0  # only the main worktree


def test_hub_write_lock_serializes_worktree_add(
    intake_cfg, hub_worktree, make_upload, monkeypatch
):
    """I-6: deleting both `with _hub_write_lock:` statements left the whole
    suite green, because the two publishes in
    test_two_repo_ids_publishing_together_do_not_cross_contaminate never
    actually overlap at worktree_add (a 0.3s stagger against a 0.5s sleep
    inside THAT test's own pr_hook, not this call). This starts both
    threads together (a plain start_barrier, not synchronized while
    holding any lock -- see the deadlock note below) and watches
    worktree_add itself, the call the lock wraps, directly."""
    start_barrier = threading.Barrier(2)
    concurrent = {"count": 0, "max": 0}
    guard = threading.Lock()
    orig = gitio.worktree_add

    def watched(root, path, branch, base, reset):
        with guard:
            concurrent["count"] += 1
            concurrent["max"] = max(concurrent["max"], concurrent["count"])
        try:
            # No internal `assert ... locked()` here on purpose: an assertion
            # raised inside a background thread does not fail the test (it
            # only surfaces as a PytestUnhandledThreadExceptionWarning) and,
            # worse, it fires before the sleep below -- so the very first
            # racing thread aborts instantly instead of holding the window
            # open, and true overlap never gets a chance to happen. The
            # overlap counter below is the only signal this test needs.
            time.sleep(0.05)  # widen the window a concurrent call would land in
            return orig(root, path, branch, base, reset)
        finally:
            with guard:
                concurrent["count"] -= 1

    monkeypatch.setattr(intake.gitio, "worktree_add", watched)

    def run(rid):
        start_barrier.wait(timeout=5)
        intake.intake_publish(
            intake_cfg, rid, f"c{rid}", f"org/{rid}", [], make_upload(rid)
        )

    t1 = threading.Thread(target=run, args=("alpha",))
    t2 = threading.Thread(target=run, args=("beta",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert concurrent["max"] == 1
