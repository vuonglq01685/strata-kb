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

A subagent writes its own transcript (`subagent_transcripts`). It starts from
the parent's cursors at the subagent's first timestamp (`parent_cursor`, the
same rules walked over the main transcript) and then walks its own file
exactly as above.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from strata_kb.usage.ledger import UsageRow, is_safe_stem

# A ticket file mention. The separator class allows one or more of `/` and `\`
# because a Windows path inside the JSONL is backslash-escaped
# (`docs\\impl\\x\\plan.md`), so a single-character class would match the first
# backslash and then fail on the second.
_SEP = r"[/\\]+"
# `tickets/<stem>.md` or `tickets/<folder>/<stem>.md` (one folder, the
# mission id, since 1.6.0); missions stay flat. The folder class excludes
# whitespace so prose like `tickets/ and docs/x.md` cannot set the cursor.
TICKET_PATH_RE = re.compile(
    rf"(?:tickets{_SEP}(?:[^/\\\"\s]+?{_SEP})?|missions{_SEP})(?P<stem>[^/\\\"]+?)\.md"
    rf"|docs{_SEP}impl{_SEP}(?P<impl>[^/\\\"\s]+?){_SEP}(?:design|plan)\.md"
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


def _str(usage: dict, key: str) -> str:
    value = usage.get(key)
    return value if isinstance(value, str) else ""


def _rows(path: Path) -> list[dict]:
    """Every parseable JSON object in the transcript, in file order."""
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            # One truncated line (a transcript being written while we read it)
            # must not cost the rest of the file.
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


SUBAGENTS_DIR = "subagents"


def subagent_transcripts(main: Path) -> list[Path]:
    """Every subagent transcript of the session whose main transcript is `main`.

    Claude Code writes each subagent to `<session-id>/subagents/agent-<id>.jsonl`
    beside `<session-id>.jsonl`. The format is documented as internal and
    version-dependent; this module is the one place that knows the layout. A
    hook payload's `agent_transcript_path` is used whenever there is one.
    """
    return sorted((main.with_suffix("") / SUBAGENTS_DIR).glob("agent-*.jsonl"))


def is_subagent_transcript(path: Path) -> bool:
    return path.parent.name == SUBAGENTS_DIR and path.name.startswith("agent-")


def parent_of(subagent: Path) -> Path:
    """The main transcript a subagent transcript belongs to."""
    return subagent.parent.parent.with_suffix(".jsonl")


@dataclass(frozen=True)
class ParentCursor:
    """The parent session's (ticket, phase) at each change, in file order.

    Timestamps compare as strings: Claude Code writes every one in the same
    ISO-8601 `YYYY-MM-DDTHH:MM:SS.mmmZ` form, so lexical order is time order.
    """

    points: tuple[tuple[str, str | None, str], ...] = ()

    def at(self, ts: str) -> tuple[str | None, str]:
        """The parent's (ticket, phase) as of `ts`, a change AT `ts` included."""
        ticket: str | None = None
        phase = UNKNOWN_PHASE
        for point_ts, point_ticket, point_phase in self.points:
            if point_ts > ts:
                break
            ticket, phase = point_ticket, point_phase
        return ticket, phase


def parent_cursor(path: Path) -> ParentCursor:
    """Walk a main transcript with the same cursor rules as
    `rows_from_transcript` (`_ticket_in(_ticket_blob(row))`, `_phase_in(row)`)
    and keep each change point.

    A change on a row without a timestamp is not lost: the state accumulates,
    so the next timestamped change point carries it.
    """
    points: list[tuple[str, str | None, str]] = []
    ticket: str | None = None
    phase = UNKNOWN_PHASE
    for row in _rows(path):
        found = _ticket_in(_ticket_blob(row))
        switched = _phase_in(row)
        if found is None and switched is None:
            continue
        ticket = found if found is not None else ticket
        phase = switched if switched is not None else phase
        ts = row.get("timestamp")
        if isinstance(ts, str) and ts:
            points.append((ts, ticket, phase))
    return ParentCursor(tuple(points))


@dataclass
class _Call:
    """One API call while the scan is still collecting its rows."""

    first: dict  # the call's first transcript row: uuid, ts, session, branch, model
    usage: dict  # the usage block of the row with the largest output_tokens
    ticket: str | None  # the ticket cursor at the first row
    phase: str  # the phase cursor at the first row


def _usage_counts(usage: dict) -> dict:
    """The numbers of ONE usage block, copied (I3) — never mixed across rows."""
    creation = usage.get("cache_creation")
    if isinstance(creation, dict):
        w5 = _int(creation, "ephemeral_5m_input_tokens")
        w1 = _int(creation, "ephemeral_1h_input_tokens")
    else:
        # An older or foreign producer writes only the total; the cheaper
        # 5m rate is the conservative reading.
        w5, w1 = _int(usage, "cache_creation_input_tokens"), 0
    server = usage.get("server_tool_use")
    return dict(
        tokens_in=_int(usage, "input_tokens"),
        tokens_out=_int(usage, "output_tokens"),
        cache_read=_int(usage, "cache_read_input_tokens"),
        cache_write_5m=w5,
        cache_write_1h=w1,
        inference_geo=_str(usage, "inference_geo"),
        speed=_str(usage, "speed"),
        service_tier=_str(usage, "service_tier"),
        web_searches=_int(server, "web_search_requests") if isinstance(server, dict) else 0,
    )


def _to_row(
    call: _Call,
    request: str,
    *,
    actor: str,
    session_fallback: str,
    forced_ticket: str | None,
    subagent: bool,
) -> UsageRow:
    first = call.first
    branch = first.get("gitBranch")
    return UsageRow(
        uuid=first["uuid"],
        request=request,
        ts=str(first.get("timestamp") or ""),
        session=str(first.get("sessionId") or session_fallback),
        actor=actor,
        phase=call.phase,
        ticket=forced_ticket if forced_ticket is not None else call.ticket,
        model=str(first["message"].get("model") or ""),
        # The file's location, not the row flag, makes a subagent's row
        # sidechain.
        sidechain=subagent or bool(first.get("isSidechain")),
        # 'HEAD' is what a non-git directory reports for every row; it is not
        # a branch, so it is not recorded as one.
        branch=branch if isinstance(branch, str) and branch != "HEAD" else None,
        assistant="claude-code",
        est=False,
        **_usage_counts(call.usage),
    )


def rows_from_transcript(
    path: Path,
    *,
    actor: str,
    session_fallback: str = "",
    forced_ticket: str | None = None,
    subagent: bool = False,
    parent: ParentCursor | None = None,
    hold_back_last: bool = False,
) -> list[UsageRow]:
    """Every API call in this transcript, attributed.

    One API CALL yields one row, not one transcript row: Claude Code splits an
    assistant message across several rows (text, then each tool_use) and repeats
    the `usage` block on every one of them, so a row is finer than a call.
    Measured across six live transcripts: 516 usage rows for 239 real calls, so
    keying on the row would overstate cost by 55.8%.

    The copies are not always identical: a streamed call writes a row per
    content block, and the first one (a thinking block, say) can carry a
    partial output count — 5 against the last row's 329, measured 2026-10-10.
    So every call is collected over the whole scan and emitted at the end, in
    first-seen order. The emitted row keeps the FIRST row's identity (uuid,
    timestamp, session, branch, model) and attribution; every count, modifiers
    included, comes from the single row with the largest `output_tokens` —
    one usage block copied whole, never a mix of rows (I3). The later copies
    refine the call's output count; they are never emitted.

    They are still part of the SCAN — a ticket path named inside a later copy
    has to attribute every later call.

    `hold_back_last` leaves out the last call in first-seen order: the caller
    knows it may still be streaming, and a stored row never changes (I1).

    `subagent` marks a subagent's own transcript: every row is sidechain,
    whatever its `isSidechain` flag says — the file's location decides. With
    `parent` (the main transcript's `parent_cursor`), a subagent starts from
    the parent's (ticket, phase) at the subagent's first timestamp; its own
    cursors then move as usual, and its own ticket wins once it has named one.

    `forced_ticket` overrides every cursor, inherited ones included — the
    escape hatch for a session the cursor read wrongly.
    """
    rows = _rows(path)
    inherited_ticket: str | None = None
    phase = UNKNOWN_PHASE
    if parent is not None:
        first_ts = next(
            (
                ts
                for ts in (row.get("timestamp") for row in rows)
                if isinstance(ts, str) and ts
            ),
            "",
        )
        inherited_ticket, phase = parent.at(first_ts)
    calls: dict[str, _Call] = {}
    ticket: str | None = None
    for row in rows:
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
        call = calls.get(request)
        if call is None:
            calls[request] = _Call(
                first=row,
                usage=usage,
                ticket=ticket if ticket is not None else inherited_ticket,
                phase=phase,
            )
        elif _int(usage, "output_tokens") > _int(call.usage, "output_tokens"):
            # A streamed call writes a row per content block; the first one
            # can carry a partial output count (5 vs 329 measured). Keep the
            # whole usage block of the largest, never a mix of rows. Either
            # way the cursors above have already consumed this row, which is
            # the point.
            call.usage = usage

    keys = list(calls)  # dict order = first-seen order
    if hold_back_last and keys:
        # The last call may still be streaming (a Stop hook can fire while a
        # background subagent is mid-call). A stored row never changes (I1),
        # so storing it now would freeze a partial output count forever.
        keys = keys[:-1]
    return [
        _to_row(
            calls[k],
            k,
            actor=actor,
            session_fallback=session_fallback,
            forced_ticket=forced_ticket,
            subagent=subagent,
        )
        for k in keys
    ]
