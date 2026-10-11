"""Checks on usage recording (ba and dev repos)."""

from __future__ import annotations

import json
from pathlib import Path

from strata_kb.doctor.issues import Issue


def check_usage_log(kb_dir: Path) -> list[Issue]:
    """The Stop hook swallows every failure into ingest-errors.log; this is
    the one place a human hears about it."""
    from strata_kb.usage.ledger import hook_errors

    count, last = hook_errors(kb_dir)
    if not count:
        return []
    return [
        Issue(
            "warning",
            f"{count} hook ingest error(s) logged in {kb_dir / 'usage' / 'ingest-errors.log'} "
            f"— last: {last}; truncate the file once handled",
        )
    ]


_USAGE_HOOK = "kb usage ingest-transcript"


def _has_usage_hook(settings: dict, event: str) -> bool:
    hooks = settings.get("hooks")
    groups = (hooks if isinstance(hooks, dict) else {}).get(event) or []
    if not isinstance(groups, list):
        return False
    for g in groups:
        hooks_in_group = g.get("hooks") if isinstance(g, dict) else None
        if not isinstance(hooks_in_group, list):
            continue
        for h in hooks_in_group:
            if isinstance(h, dict) and _USAGE_HOOK in str(h.get("command", "")):
                return True
    return False


def check_usage_hooks(repo_root: Path) -> list[Issue]:
    """`kb init` never rewrites an existing .claude/settings.json, so a repo
    set up before 1.9.0 has the Stop hook and not SubagentStop. The Stop
    sweep still records its subagents, minus each one's in-flight last call."""
    path = repo_root / ".claude" / "settings.json"
    try:
        # utf-8-sig: Notepad saves JSON with a BOM, which json.loads rejects.
        settings = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    if not isinstance(settings, dict):
        return []
    if _has_usage_hook(settings, "Stop") and not _has_usage_hook(
        settings, "SubagentStop"
    ):
        return [
            Issue(
                "warning",
                f"{path} records usage on Stop but not on SubagentStop — add a "
                '"SubagentStop" entry with the same command '
                f"(`{_USAGE_HOOK} --hook-stdin`) so every subagent call is counted",
            )
        ]
    return []
