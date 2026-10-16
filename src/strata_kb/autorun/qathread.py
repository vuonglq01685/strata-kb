"""qathread -- the BA's Q&A answerer, a background job beside the main loop.

While the BA runner works a ticket, Dev may ask questions. This thread polls the
hub and, when any are open, answers them in a separate `claude -p` process in a
separate git worktree (`.kb/auto/worktrees/qa`, branch `auto/qa`), so it shares
neither context nor files with the main BA task.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from strata_kb import gitio
from strata_kb.autorun import claude
from strata_kb.autorun import state as autostate
from strata_kb.autorun.qa import QaClient
from strata_kb.errors import KbError

logger = logging.getLogger("strata_kb.autorun.qathread")

SKILL = "ba-answer-questions"
BRANCH = "auto/qa"


def open_question_count(qa: QaClient, repo: str) -> int:
    return len(qa.list("open", repo=repo))


class QaThread:
    def __init__(
        self,
        root: Path,
        kb_dir: Path,
        qa: QaClient,
        interval: int,
        repo: str,
        run_task=claude.run_task,
    ) -> None:
        self._root, self._kb_dir, self._qa = root, kb_dir, qa
        self._interval, self._repo, self._run_task = interval, repo, run_task
        self._stop = threading.Event()
        self._loop_thread: threading.Thread | None = None
        self._proc_thread: threading.Thread | None = None
        self._skip_ticks = 0  # set by a usage-limit result: wait one more interval

    @property
    def worktree(self) -> Path:
        return self._kb_dir / "auto" / "worktrees" / "qa"

    def start(self) -> None:
        self._loop_thread = threading.Thread(target=self._loop, daemon=True)
        self._loop_thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._loop_thread is not None:
            self._loop_thread.join()
        if self._proc_thread is not None and self._proc_thread.is_alive():
            logger.info("Q&A answer still running; it finishes on its own")

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(self._interval)

    def tick(self) -> bool:
        """One check; True when it launched an answering process."""
        if self._proc_thread is not None and self._proc_thread.is_alive():
            return False
        if self._skip_ticks:
            self._skip_ticks -= 1
            return False
        try:
            if not open_question_count(self._qa, self._repo):
                return False
            self._fresh_worktree()
        except KbError as exc:
            logger.warning("Q&A check skipped: %s", exc)
            return False
        self._proc_thread = threading.Thread(target=self._answer, daemon=True)
        self._proc_thread.start()
        return True

    def _fresh_worktree(self) -> None:
        """Recreate the worktree on `auto/qa` from the default branch."""
        gitio.worktree_remove(self._root, self.worktree)
        gitio.worktree_prune(self._root)
        gitio.worktree_add(
            self._root,
            self.worktree,
            BRANCH,
            gitio.default_branch(self._root),
            reset=True,
        )

    def _answer(self) -> None:
        try:
            result = self._run_task(
                self.worktree,
                claude.prompt_for(SKILL, "", "ba"),
                log_dir=autostate.log_dir(self._kb_dir),
            )
        except Exception as exc:  # noqa: BLE001 -- a dead answer must free the slot
            logger.warning("Q&A answer crashed: %s", exc)
            return
        if result.kind == "done":
            logger.info("Q&A answer done")
            return
        logger.warning("Q&A answer %s: %s", result.kind, result.reason)
        if result.kind == "usage-limit":
            self._skip_ticks = 1
