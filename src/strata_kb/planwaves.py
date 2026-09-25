"""`kb plan waves` engine — dependency waves of a dev plan.

A `docs/impl/<ticket-id>-plan.md` written by `dev-plan` carries, per
`### Task <n>` heading, a `Depends on:` line and a `**Files:**` list (spec
2026-09-24-mission-next-greenfield-design §5). Two tasks with no dependency
path between them must be file-disjoint — that is what lets `dev-execute`
run a wave in parallel worktree lanes and merge them back without conflict.
This module checks that and computes the waves. Text in, errors and waves
out; no filesystem, CLI or MCP imports.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

TASK_RE = re.compile(r"^#{2,4}\s+Task\s+(?P<n>\d+)\b")
DEPENDS_RE = re.compile(r"^\*{0,2}Depends on:?\*{0,2}\s*(?P<rest>.*?)\s*$", re.I)
SECTION_RE = re.compile(r"^\*\*(?P<name>Files|Interfaces|Steps):?\*\*:?\s*$")
FILE_LINE_RE = re.compile(r"^\s*-\s*(?:Create|Modify|Test|Delete)\s*:\s*(?P<rest>.+?)\s*$", re.I)
CODE_SPAN_RE = re.compile(r"`([^`]+)`")
LINE_SUFFIX_RE = re.compile(r":\d+(?:-\d+)?$")

_NONE_WORDS = frozenset({"", "none", "-", "n/a"})


@dataclass(frozen=True)
class Task:
    number: int
    depends_on: tuple[int, ...] | None   # None = no `Depends on:` line
    paths: tuple[str, ...]


def _path_of(rest: str) -> str | None:
    """The path on a `- Create: \\`src/x.py:10-20\\`` line: the first backtick
    span (else the first token), with a trailing `:<line>[-<line>]` dropped
    and a leading `./` stripped so `./x.py` and `x.py` collide as one path."""
    m = CODE_SPAN_RE.search(rest)
    token = m.group(1).strip() if m else (rest.split() or [""])[0]
    token = LINE_SUFFIX_RE.sub("", token).strip()
    if token.startswith("./"):
        token = token[2:]
    return token or None


def _deps_of(rest: str) -> tuple[int, ...] | None:
    """Dependency numbers parsed from a `Depends on:` remainder, or `None`
    when it is neither a none-word nor names any digit (`Depends on: TBD`)
    -- `parse_plan` leaves such a line unbound so `check` reports it the
    same as a missing line, instead of silently reading it as `none`."""
    stripped = rest.strip().lower()
    if stripped in _NONE_WORDS:
        return ()
    if not any(c.isdigit() for c in rest):
        return None
    return tuple(dict.fromkeys(int(n) for n in re.findall(r"\d+", rest)))


def _fence_marker(line: str) -> str:
    """The fence marker opening/closing on this line, or '' if none."""
    stripped = line.lstrip()
    for marker in ("```", "~~~"):
        if stripped.startswith(marker):
            return marker
    return ""


def parse_plan(text: str) -> list[Task]:
    """Tasks in file order. A `Depends on:` line binds to the task heading
    above it; `**Files:**` lines are read until the next bold section or
    task heading. A fenced code block (``` or ~~~, closed by the same
    marker) is skipped whole -- a plan quoting another plan or a test
    fixture as an example must not spawn phantom tasks."""
    text = text.lstrip("﻿")
    tasks: list[Task] = []
    number: int | None = None
    depends: tuple[int, ...] | None = None
    paths: list[str] = []
    in_files = False
    in_fence = ""

    def flush() -> None:
        if number is not None:
            tasks.append(Task(number, depends, tuple(dict.fromkeys(paths))))

    for raw in text.splitlines():
        line = raw.rstrip()
        marker = _fence_marker(line)
        if in_fence:
            if marker == in_fence:
                in_fence = ""
            continue
        if marker:
            in_fence = marker
            continue
        m = TASK_RE.match(line)
        if m:
            flush()
            number, depends, paths, in_files = int(m.group("n")), None, [], False
            continue
        if number is None:
            continue
        m = DEPENDS_RE.match(line.strip())
        if m and depends is None:
            depends = _deps_of(m.group("rest"))
            continue
        m = SECTION_RE.match(line.strip())
        if m:
            in_files = m.group("name") == "Files"
            continue
        if in_files:
            m = FILE_LINE_RE.match(line)
            if m:
                path = _path_of(m.group("rest"))
                if path:
                    paths.append(path)
    flush()
    return tasks


def unclosed_fence(text: str) -> bool:
    """True when `text` ends with a fenced code block (``` or ~~~) that was
    never closed -- `parse_plan` skips everything inside a fence, so an
    unclosed one may have silently swallowed the rest of the plan."""
    text = text.lstrip("﻿")
    in_fence = ""
    for raw in text.splitlines():
        marker = _fence_marker(raw.rstrip())
        if in_fence:
            if marker == in_fence:
                in_fence = ""
            continue
        if marker:
            in_fence = marker
    return bool(in_fence)


def _reachable(start: int, deps: dict[int, tuple[int, ...]]) -> set[int]:
    """Every task `start` depends on, transitively."""
    seen: set[int] = set()
    stack = list(deps.get(start, ()))
    while stack:
        n = stack.pop()
        if n in seen or n not in deps:
            continue
        seen.add(n)
        stack.extend(deps[n])
    return seen


def _find_cycle(deps: dict[int, tuple[int, ...]]) -> list[int] | None:
    # ponytail: recursive DFS, fine below ~1000 tasks; iterative if plans ever get that big
    state: dict[int, int] = {}
    path: list[int] = []

    def visit(n: int) -> list[int] | None:
        state[n] = 1
        path.append(n)
        for d in deps.get(n, ()):
            if d not in deps:
                continue
            if state.get(d) == 1:
                return path[path.index(d):] + [d]
            if state.get(d) is None:
                found = visit(d)
                if found:
                    return found
        path.pop()
        state[n] = 2
        return None

    for n in deps:
        if state.get(n) is None:
            found = visit(n)
            if found:
                return found
    return None


def check(
    tasks: list[Task], unclosed: bool = False
) -> tuple[list[str], list[list[int]]]:
    """(errors, waves). Waves are empty whenever an error is reported —
    a plan with a cycle or an undeclared shared file has no safe order.
    `unclosed` (from `unclosed_fence`) reports a fence the parser never
    saw close, which may have silently dropped the plan's tail."""
    if not tasks:
        return ["no `### Task <n>` headings found"], []
    errors: list[str] = []
    if unclosed:
        errors.append("unclosed code fence")
    seen: set[int] = {t.number for t in tasks}
    counts = Counter(t.number for t in tasks)
    for n in sorted(counts):
        if counts[n] > 1:
            errors.append(f"task {n} is defined twice")
    if all(t.depends_on is None for t in tasks):
        # Plan predates waves (no task carries a `Depends on:` line) -- report
        # only the missing-line defect, not the shared-path/cycle noise that
        # a legacy plan trips on every task pair. Errors already collected
        # (unclosed fence, duplicate task numbers) are kept, not dropped.
        return errors + [f"task {t.number} has no Depends on: line" for t in tasks], []
    deps: dict[int, tuple[int, ...]] = {}
    for t in tasks:
        if t.depends_on is None:
            errors.append(f"task {t.number} has no Depends on: line")
            deps[t.number] = ()
            continue
        deps[t.number] = t.depends_on
        for d in t.depends_on:
            if d not in seen:
                errors.append(f"task {t.number} depends on task {d} — no such task")
    for t in tasks:
        if not t.paths:
            errors.append(f"task {t.number} lists no paths under **Files**")

    cycle = _find_cycle(deps)
    if cycle:
        errors.append("dependency cycle: " + " → ".join(str(n) for n in cycle))

    # `_reachable` tolerates a cycle (its `seen` set stops the walk), so the
    # shared-path check runs even when a cycle was reported — a plan with
    # both defects reports both.
    reach = {n: _reachable(n, deps) for n in deps}
    by_number = {t.number: t for t in tasks}
    numbers = sorted(by_number)
    for i, a in enumerate(numbers):
        for b in numbers[i + 1:]:
            shared = sorted(set(by_number[a].paths) & set(by_number[b].paths))
            if shared and b not in reach[a] and a not in reach[b]:
                for p in shared:
                    errors.append(f"tasks {a} and {b} share {p} but neither depends on the other")

    if errors:
        return errors, []
    waves: list[list[int]] = []
    placed: set[int] = set()
    remaining = set(deps)
    while remaining:
        wave = sorted(n for n in remaining if all(d in placed for d in deps[n]))
        waves.append(wave)
        placed.update(wave)
        remaining -= set(wave)
    return [], waves


def render(waves: list[list[int]]) -> str:
    return "\n".join(
        f"wave {i}: " + ", ".join(f"task {n}" for n in wave)
        for i, wave in enumerate(waves, start=1)
    )


def to_json(errors: list[str], waves: list[list[int]]) -> dict:
    return {"errors": list(errors), "waves": [list(w) for w in waves]}
