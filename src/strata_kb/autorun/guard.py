"""Stop-hook guard: a headless `kb auto run` task may not end without its
`AUTO-RESULT:` line."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from strata_kb.autorun import claude
from strata_kb.usage.transcript import _rows


def _last_assistant_text(payload: dict) -> str:
    message = payload.get("last_assistant_message")
    if isinstance(message, str):
        return message
    path = payload.get("transcript_path")
    if not isinstance(path, str) or not path:
        return ""
    for row in reversed(_rows(Path(path))):
        if row.get("type") != "assistant":
            continue
        content = (row.get("message") or {}).get("content")
        if not isinstance(content, list):
            return ""
        return "\n".join(
            b["text"]
            for b in content
            if isinstance(b, dict)
            and b.get("type") == "text"
            and isinstance(b.get("text"), str)
        )
    return ""


def stop_decision(payload: dict, env: Mapping[str, str]) -> dict | None:
    """`None` = let the session end; else the Stop-hook block decision."""
    if env.get(claude.AUTO_TASK_ENV) != "1" or payload.get("stop_hook_active") is True:
        return None
    failure = claude.parse_result(_last_assistant_text(payload))
    if failure.kind != "failed" or not (
        failure.reason == "no result line"
        or failure.reason.startswith("bad result line")
    ):
        return None
    forms = "\n".join(claude.RESULT_FORMS)
    return {
        "decision": "block",
        "reason": (
            "Your last message must end with exactly one AUTO-RESULT line, "
            f"in one of these forms:\n{forms}"
        ),
    }
