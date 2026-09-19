"""transcript — turn a Claude Code transcript into ledger rows.

A transcript lives at `~/.claude/projects/<slug>/<session-id>.jsonl`. Every row
whose `message` carries a `usage` block is one API call, and that block is the
assistant's own accounting — not an estimate — so the numbers here are copied,
never computed (invariant I3).

Attribution is two cursors walked in file order. Both depend only on rows
BEFORE the current one, which is what makes re-ingestion of a growing
transcript stable: the `Stop` hook re-reads the same file every turn, and rows
already stored must never change (invariant I1). Both cursors are read from
the current row before that row is itself attributed, so a row that both
carries a `usage` block and triggers a switch (a `Skill` call, a command
marker, a ticket `file_path`) is attributed to what it switches to, not to
what was active before it ran — deliberate, since at most one row per
transition is affected and "the transition row gets the phase/ticket it
starts" is the simpler rule to keep consistent between the two cursors.

A cursor advances on what the session did or said, never on what it merely
read: a `tool_result` block is file content, a directory listing, or command
output echoed back verbatim, and scanning it would let any file the session
reads plant a ticket or reset a phase it never actually touched.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from center_kb.usage.ledger import UsageRow, is_safe_stem

# A ticket file mention. The separator class allows one or more of `/` and `\`
# because a Windows path inside the JSONL is backslash-escaped
# (`docs\\impl\\x-plan.md`), so a single-character class would match the first
# backslash and then fail on the second.
_SEP = r"[/\\]+"
TICKET_PATH_RE = re.compile(
    rf"(?:tickets|missions){_SEP}(?P<stem>[^/\\\"]+?)\.md"
    rf"|docs{_SEP}impl{_SEP}(?P<impl>[^/\\\"]+?)-(?:design|plan)\.md"
)

# The only two phase signals. A slash command's marker is injected into the
# user message; a Skill tool call names the skill in its input.
COMMAND_RE = re.compile(r"<command-name>([^<]{1,80})</command-name>")
PHASE_RE = re.compile(r"^(?:ba|dev|kb)-[a-z0-9-]+$")

SYNTHETIC_MODEL = "<synthetic>"
UNKNOWN_PHASE = "unknown"
_NOT_A_TICKET = {"TEMPLATE"}

# These two tools' inputs carry proposals and plans, not actions taken:
# AskUserQuestion's `options` are choices offered (including ones the human
# rejects), and TodoWrite's `todos` are a plan of what might be done next.
# The cursor rule is that it follows what the session DID or SAID, never what
# it merely contemplates — measured on real KS-BA transcripts, a rejected
# ticket-naming proposal inside an AskUserQuestion option list captured the
# cursor and held it for 14 rows (2.8%), fabricating a ticket that never
# existed. Every other tool's input stays trusted, `Bash.command` included —
# it is the dominant real ticket signal on BA data, and excluding path-shaped
# keys instead (an earlier proposal) was measured to trade those 14 corrected
# rows for 38 newly-unattributed ones.
_PROPOSAL_ONLY_TOOLS = {"AskUserQuestion", "TodoWrite"}


def _ticket_blob(row: dict) -> str:
    """The parts of one row that reflect something the session said or did —
    never something it merely read or merely considered.

    A `tool_result` block is file content, a directory listing, or command
    output echoed back exactly as read; it contributes nothing, on either a
    user or an assistant row (in practice a `tool_result` only appears on a
    user row, but the exclusion is type-based, not role-based, so it holds
    either way). A `tool_use` block's `input` IS included: a `file_path`
    argument to Read/Write/Edit is the strongest ticket signal there is —
    except for `_PROPOSAL_ONLY_TOOLS`, whose input is what the session is
    weighing, not what it did. Text blocks are what the session actually
    wrote or was told.
    """
    message = row.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
        elif block_type == "tool_use":
            if block.get("name") in _PROPOSAL_ONLY_TOOLS:
                continue
            parts.append(json.dumps(block.get("input") or {}, ensure_ascii=False))
        # tool_result (and anything else) is excluded: it is what the
        # session read, not what it said or did.
    return "\n".join(parts)


def _command_text(row: dict) -> str:
    """Text a slash-command marker can legitimately appear in: a user row's
    own text content, and nothing else.

    Claude Code injects a slash command's expansion as user-message content,
    so restricting the scan to a user row's text closes the `tool_result`
    channel completely — reading a doc that happens to contain the literal
    marker can no longer reset the phase — without touching the one case that
    is real.
    """
    if row.get("type") != "user":
        return ""
    message = row.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(
        block["text"]
        for block in content
        if isinstance(block, dict)
        and block.get("type") == "text"
        and isinstance(block.get("text"), str)
    )


def _ticket_in(blob: str) -> str | None:
    """The last ticket stem mentioned in one row's trusted text, or None.

    Last, not first: a row that mentions two files (two `file_path` inputs in
    the same turn, say) leaves the cursor on whichever came latest, matching
    how the cursor behaves across rows.
    """
    found: str | None = None
    for match in TICKET_PATH_RE.finditer(blob):
        stem = match.group("stem") or match.group("impl") or ""
        if stem in _NOT_A_TICKET or not is_safe_stem(stem):
            # A traversal attempt, a template, or anything else that cannot be
            # a ticket file name is treated as no mention at all — never
            # rewritten into something that looks safe.
            continue
        found = stem
    return found


def _phase_in(row: dict) -> str | None:
    """The phase this row switches to, `UNKNOWN_PHASE` for a reset, or None
    for "leave the cursor alone".

    Deliberately NOT derived from skill names appearing in content: a session
    that edits the dev skills mentions `dev-handover` hundreds of times while
    running something else entirely, and counting mentions produced a phase
    breakdown that was wrong and looked right.
    """
    names: list[str] = [m.strip() for m in COMMAND_RE.findall(_command_text(row))]
    message = row.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "tool_use"
                    and block.get("name") == "Skill"
                ):
                    skill = (block.get("input") or {}).get("skill")
                    if isinstance(skill, str):
                        names.append(skill)
    result: str | None = None
    for raw in names:
        name = raw.lstrip("/").strip()
        if name == "clear":
            # /clear wipes the context the phase was running in, so the phase
            # is over — not merely unchanged.
            result = UNKNOWN_PHASE
        elif PHASE_RE.fullmatch(name):
            result = name
    return result


def _int(usage: dict, key: str) -> int:
    value = usage.get(key)
    return int(value) if isinstance(value, (int, float)) else 0


def rows_from_transcript(
    path: Path,
    *,
    actor: str,
    session_fallback: str = "",
    forced_ticket: str | None = None,
) -> list[UsageRow]:
    """Every API call in this transcript, attributed.

    One API CALL yields one row, not one transcript row: Claude Code splits an
    assistant message across several rows (text, then each tool_use) and repeats
    the identical `usage` block on every one of them, so a row is finer than a
    call. Measured across six live transcripts: 516 usage rows for 239 real
    calls, every multi-row group carrying byte-identical usage (179 of 179), so
    keying on the row would overstate cost by 55.8%.

    The later copies are dropped from the OUTPUT, never from the scan — a ticket
    path named inside a dropped row still has to attribute every later call.

    `forced_ticket` overrides the cursor entirely — the escape hatch for a
    session the cursor read wrongly.
    """
    rows: list[UsageRow] = []
    seen_calls: set[str] = set()
    ticket: str | None = None
    phase = UNKNOWN_PHASE
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            # One truncated line (a transcript being written while we read it)
            # must not cost the rest of the file.
            continue
        if not isinstance(row, dict):
            continue
        found = _ticket_in(_ticket_blob(row))
        if found is not None:
            ticket = found
        switched = _phase_in(row)
        if switched is not None:
            phase = switched

        message = row.get("message")
        usage = message.get("usage") if isinstance(message, dict) else None
        if not isinstance(usage, dict):
            continue
        model = message.get("model") or ""
        uuid = row.get("uuid")
        if model == SYNTHETIC_MODEL or not isinstance(uuid, str) or not uuid:
            continue
        # The call's own identity, coarsest first: `requestId` is the API
        # request, `message.id` the assistant message it produced, and the row
        # uuid only as a last resort — without either id there is nothing finer
        # than the row, so two rows are two calls, as before this fix.
        request = str(row.get("requestId") or message.get("id") or uuid)
        if request in seen_calls:
            # A later copy of a call already recorded. The cursors above have
            # already consumed this row, which is the point.
            continue
        seen_calls.add(request)
        creation = usage.get("cache_creation") or {}
        branch = row.get("gitBranch")
        rows.append(
            UsageRow(
                uuid=uuid,
                request=request,
                ts=str(row.get("timestamp") or ""),
                session=str(row.get("sessionId") or session_fallback),
                actor=actor,
                phase=phase,
                ticket=forced_ticket if forced_ticket is not None else ticket,
                model=str(model),
                tokens_in=_int(usage, "input_tokens"),
                tokens_out=_int(usage, "output_tokens"),
                cache_read=_int(usage, "cache_read_input_tokens"),
                cache_write_5m=_int(creation, "ephemeral_5m_input_tokens"),
                cache_write_1h=_int(creation, "ephemeral_1h_input_tokens"),
                sidechain=bool(row.get("isSidechain")),
                # 'HEAD' is what a non-git directory reports for every row; it
                # is not a branch, so it is not recorded as one.
                branch=branch if isinstance(branch, str) and branch != "HEAD" else None,
                assistant="claude-code",
                est=False,
            )
        )
    return rows
