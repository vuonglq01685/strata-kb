"""One auto-mode task = one fresh headless `claude -p` process.

`run_task` pipes the prompt on stdin (like `llm.Runner`), logs the exchange and
reads the closing `AUTO-RESULT:` line. The command never skips permissions:
`acceptEdits` lets the skill edit files, nothing else is pre-approved.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from strata_kb.llm import RunnerError, _extract_reply

Kind = Literal["done", "blocked-qa", "failed", "usage-limit"]

RESULT_PREFIX = "AUTO-RESULT: "
DEFAULT_TIMEOUT = 4 * 3600
MAX_REASON = 500
MAX_SLUG = 60


@dataclass(frozen=True)
class TaskResult:
    kind: Kind
    ids: tuple[int, ...] = ()
    reason: str = ""


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
    return TaskResult("failed", (), f"bad result line: {lines[-1][:200]}")


def prompt_for(skill: str, arg: str, kind: str) -> str:
    return (
        f"/{skill} {arg}".strip()
        + f"""

Auto mode is ON for this {kind} repo. Follow the "Auto mode" section of the \
skill. Never ask the human anything; a question for the human goes into the \
hub's Q&A instead.

End your reply with exactly one line, and make it the last line, in one of \
these three forms:
AUTO-RESULT: done
AUTO-RESULT: blocked-qa Q<id>[,Q<id>...]
AUTO-RESULT: failed <reason>
"""
    )


def _slug(prompt: str) -> str:
    first = prompt.strip().splitlines()[0] if prompt.strip() else ""
    return re.sub(r"[^A-Za-z0-9_-]", "-", first)[:MAX_SLUG].strip("-") or "task"


def _write_log(
    log_dir: Path, prompt: str, stdout: str, stderr: str, code: int | str, secs: float
) -> None:
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


# Narrow on purpose: "context limit" or "file size limit" is a hard failure,
# and calling it usage-limit would make the loop back off and retry forever.
_USAGE_LIMIT = re.compile(
    r"usage limit|rate limit|limit (reached|exceeded)|resets? at|try again (at|in)",
    re.I,
)


def _error(message: str) -> TaskResult:
    kind: Kind = "usage-limit" if _USAGE_LIMIT.search(message) else "failed"
    return TaskResult(kind, (), message[:MAX_REASON])


def run_task(
    root: Path,
    prompt: str,
    *,
    log_dir: Path,
    executable: str = "claude",
    timeout: int = DEFAULT_TIMEOUT,
) -> TaskResult:
    cmd = [
        shutil.which(executable) or executable,
        "-p",
        "--output-format",
        "json",
        "--permission-mode",
        "acceptEdits",
    ]
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
        )
    except subprocess.TimeoutExpired:
        _write_log(log_dir, prompt, "", "", "timeout", time.monotonic() - start)
        return TaskResult("failed", (), f"timed out after {timeout}s")
    except OSError as exc:
        _write_log(log_dir, prompt, "", str(exc), "oserror", time.monotonic() - start)
        return TaskResult("failed", (), f"cannot run {executable}: {exc}"[:MAX_REASON])
    _write_log(
        log_dir,
        prompt,
        proc.stdout,
        proc.stderr,
        proc.returncode,
        time.monotonic() - start,
    )
    try:
        reply, problem = _extract_reply("claude", proc.stdout), ""
    except RunnerError as exc:
        reply, problem = "", str(exc)
    if proc.returncode != 0:
        problem = (
            f"{problem} {proc.stderr.strip()}".strip() or f"exit {proc.returncode}"
        )
    if problem:
        return _error(problem)
    return parse_result(reply)
