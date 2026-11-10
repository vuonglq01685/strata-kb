"""One auto-mode task = one fresh headless `claude -p` process.

`run_task` pipes the prompt on stdin (like `llm.Runner`), logs the exchange and
reads the closing `AUTO-RESULT:` line. The command never skips permissions:
`acceptEdits` lets the skill edit files, nothing else is pre-approved.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Literal

from strata_kb.llm import AUTO_TASK_ENV, RunnerError, _extract_reply, envelope_meta

Kind = Literal[
    "done", "blocked-qa", "blocked-split", "blocked-review", "failed", "usage-limit"
]

RESULT_PREFIX = "AUTO-RESULT: "
# the line templates prompt_for prints; the Stop-hook guard reuses them
RESULT_FORMS = (
    "AUTO-RESULT: done",
    "AUTO-RESULT: blocked-qa Q<id>[,Q<id>...]",
    "AUTO-RESULT: blocked-split <bug-id>",
    "AUTO-RESULT: blocked-review <pr-url>",
    "AUTO-RESULT: failed <reason>",
)
_PR_URL = re.compile(r"https://\S+/pull/\d+")
DEFAULT_TIMEOUT = 4 * 3600
MAX_REASON = 500
MAX_SLUG = 60
# BUG-<n>, or a child bug BUG-<n>.<repo-id>[.<k>] (ticket.CHILD_ID_RE's shape)
_SPLIT_BUG = r"BUG-\d+(?:\.[A-Za-z0-9][A-Za-z0-9_-]*(?:\.(?:[2-9]|[1-9]\d+))?)?"


@dataclass(frozen=True)
class TaskResult:
    kind: Kind
    # blocked-qa: question ids (int); blocked-split: the bug id ("BUG-7", or a
    # child bug "BUG-7.web" proposing a sibling child on its parent)
    ids: tuple[int | str, ...] = ()
    reason: str = ""
    # run facts for runs.jsonl; out of ==/hash so a result still compares by verdict
    meta: Mapping[str, object] = field(default_factory=dict, compare=False, hash=False)


def parse_result(reply: str) -> TaskResult:
    """The reply's last non-empty line must be the `AUTO-RESULT:` line."""
    lines = [line.strip() for line in reply.splitlines() if line.strip()]
    if not lines or not lines[-1].startswith(RESULT_PREFIX):
        return TaskResult("failed", (), "no result line")
    verdict = lines[-1][len(RESULT_PREFIX) :]
    word, _, rest = verdict.partition(" ")
    rest = rest.strip()
    if word == "done" and not rest:
        return TaskResult("done")
    if word == "failed":
        return TaskResult("failed", (), rest or "no reason given")
    if word == "blocked-qa":
        parts = [p.strip() for p in rest.split(",")]
        if parts and all(re.fullmatch(r"Q\d+", p) for p in parts):
            return TaskResult("blocked-qa", tuple(int(p[1:]) for p in parts))
    if word == "blocked-split" and re.fullmatch(_SPLIT_BUG, rest):
        return TaskResult("blocked-split", (rest,))
    if word == "blocked-review" and _PR_URL.fullmatch(rest):
        return TaskResult("blocked-review", (rest,))
    return TaskResult("failed", (), f"bad result line: {lines[-1][:200]}")


def prompt_for(skill: str, arg: str, kind: str) -> str:
    return (
        f"/{skill} {arg}".strip()
        + f"""

Auto mode is ON for this {kind} repo. Follow the "Auto mode" section of the \
skill. Never ask the human anything; a question for the human goes into the \
hub's Q&A instead.

Run git from the working directory; never use `git -C`. When a rule of this \
repo (`CLAUDE.md`, `AGENTS.md`, ...) needs a command you are not allowed to \
run, skip that step and name it in the PR's notes; do not stop or fail for it.

A `kb` command that has a `strata-kb` MCP tool counts as no CLI when it \
cannot run here (`kb` is missing, the permission system denies it, it refuses \
in this environment, or it cannot reach the hub): use its MCP tool instead. A \
blocked CLI is not a reason to fail while the MCP tool works.

End your reply with exactly one line, and make it the last line, in one of \
these five forms:
{chr(10).join(RESULT_FORMS)}
"""
    )


def _slug(prompt: str) -> str:
    first = prompt.strip().splitlines()[0] if prompt.strip() else ""
    return re.sub(r"[^A-Za-z0-9_-]", "-", first)[:MAX_SLUG].strip("-") or "task"


def _write_log(
    log_dir: Path, prompt: str, stdout: str, stderr: str, code: int | str, secs: float
) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{datetime.now():%Y%m%d-%H%M%S}-{_slug(prompt)}"
    path = log_dir / f"{stem}.log"
    n = 1
    while path.exists():  # same prompt twice within a second: keep both logs
        n += 1
        path = log_dir / f"{stem}-{n}.log"
    body = (
        f"=== PROMPT ===\n{prompt}\n=== STDOUT ===\n{stdout}\n"
        f"=== STDERR ===\n{stderr}\nexit={code} duration={secs:.1f}s\n"
    )
    path.write_text(body, encoding="utf-8", newline="\n")
    return path


# Narrow on purpose: "context limit" or "file size limit" is a hard failure,
# and calling it usage-limit would make the loop back off and retry forever.
_USAGE_LIMIT = re.compile(
    r"(usage|rate|5-hour|weekly|session) limit|hit your limit|limit reached.*reset",
    re.I,
)


def _error(message: str, meta: Mapping[str, object]) -> TaskResult:
    kind: Kind = "usage-limit" if _USAGE_LIMIT.search(message) else "failed"
    return TaskResult(kind, (), message[:MAX_REASON], meta)


def _meta(stdout: str, log: Path) -> dict[str, object]:
    return {**envelope_meta(stdout), "log": str(log)}


def run_task(
    root: Path,
    prompt: str,
    *,
    log_dir: Path,
    executable: str = "claude",
    timeout: int = DEFAULT_TIMEOUT,
    model: str = "",
    effort: str = "",
) -> TaskResult:
    cmd = [
        shutil.which(executable) or executable,
        "-p",
        "--output-format",
        "json",
        "--permission-mode",
        "acceptEdits",
    ]
    if model:
        cmd += ["--model", model]
    if effort:
        cmd += ["--effort", effort]
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=root,
            # Marks a task process: `kb auto on|off|run` refuse under it, so a
            # task can never flip the switch or start a second loop.
            env={**os.environ, AUTO_TASK_ENV: "1"},
        )
    except subprocess.TimeoutExpired:
        log = _write_log(log_dir, prompt, "", "", "timeout", time.monotonic() - start)
        return TaskResult("failed", (), f"timed out after {timeout}s", _meta("", log))
    except OSError as exc:
        log = _write_log(
            log_dir, prompt, "", str(exc), "oserror", time.monotonic() - start
        )
        return TaskResult(
            "failed",
            (),
            f"cannot run {executable}: {exc}"[:MAX_REASON],
            _meta("", log),
        )
    log = _write_log(
        log_dir,
        prompt,
        proc.stdout,
        proc.stderr,
        proc.returncode,
        time.monotonic() - start,
    )
    meta = _meta(proc.stdout, log)
    try:
        reply, problem = _extract_reply("claude", proc.stdout), ""
    except RunnerError as exc:
        reply, problem = "", str(exc)
    if proc.returncode != 0:
        problem = (
            f"{problem} {proc.stderr.strip()}".strip() or f"exit {proc.returncode}"
        )
    if problem:
        return _error(problem, meta)
    return replace(parse_result(reply), meta=meta)
