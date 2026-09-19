"""Reviewer D's F-D3: while a publish was in flight, the read side served the
unmerged publish/<rid> branch."""
import threading
import time

from strata_kb import gitio, intake


def test_the_serving_tree_never_shows_unmerged_content(
    intake_cfg, hub_worktree, make_upload
):
    seen = []

    def slow_create_pr(hub_full, token, branch, title, body, base, http=None):
        for _ in range(5):
            entry = hub_worktree / "federation" / "alpha"
            seen.append(entry.exists())
            seen.append(gitio.current_branch(hub_worktree))
            time.sleep(0.1)
        return f"https://github.com/{hub_full}/pull/1"

    intake_cfg.pr_hook = slow_create_pr
    default = gitio.default_branch(hub_worktree)
    t = threading.Thread(
        target=intake.intake_publish,
        args=(intake_cfg, "alpha", "c1", "org/alpha", [], make_upload("alpha")),
    )
    t.start()
    t.join()

    # A non-empty `seen` proves slow_create_pr actually ran mid-publish (the
    # pr_hook seam works) -- without this, a swallowed thread exception could
    # leave `seen` empty and the assertions below would pass vacuously.
    assert seen
    assert all(b == default for b in seen if isinstance(b, str))
    assert not any(b for b in seen if isinstance(b, bool))
