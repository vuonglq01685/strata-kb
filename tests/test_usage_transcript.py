import json
from pathlib import Path

from center_kb.usage import transcript


def usage_row(uuid: str, *, model: str = "claude-sonnet-5", out: int = 100, **kw):
    """An assistant row shaped like Claude Code writes it."""
    row = {
        "type": "assistant",
        "uuid": uuid,
        "sessionId": "sess-1",
        "timestamp": "2026-08-23T09:59:22.432Z",
        "gitBranch": "feat/x",
        "isSidechain": False,
        "message": {
            "model": model,
            "usage": {
                "input_tokens": 7,
                "output_tokens": out,
                "cache_read_input_tokens": 1000,
                "cache_creation_input_tokens": 300,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 0,
                    "ephemeral_1h_input_tokens": 300,
                },
            },
        },
    }
    row.update(kw)
    return row


def user_row(text: str, **kw):
    row = {
        "type": "user",
        "uuid": f"u-{abs(hash(text)) % 10**8}",
        "sessionId": "sess-1",
        "timestamp": "2026-08-23T09:59:00.000Z",
        "message": {"role": "user", "content": text},
    }
    row.update(kw)
    return row


def skill_call_row(skill: str):
    return {
        "type": "assistant",
        "uuid": f"s-{skill}",
        "sessionId": "sess-1",
        "timestamp": "2026-08-23T09:58:00.000Z",
        "message": {
            "model": "claude-sonnet-5",
            "content": [
                {"type": "tool_use", "name": "Skill", "input": {"skill": skill}}
            ],
        },
    }


def tool_result_row(text: str, **kw):
    """A user row carrying a tool_result block: file content, a directory
    listing, or command output the session merely read — never something it
    said or did."""
    row = {
        "type": "user",
        "uuid": f"tr-{abs(hash(text)) % 10**8}",
        "sessionId": "sess-1",
        "timestamp": "2026-08-23T09:59:10.000Z",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": text}
            ],
        },
    }
    row.update(kw)
    return row


def write_transcript(tmp_path: Path, rows: list[dict], name: str = "t.jsonl") -> Path:
    path = tmp_path / name
    path.write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8", newline="\n"
    )
    return path


def test_a_usage_row_becomes_a_ledger_row_with_the_numbers_copied(tmp_path: Path):
    path = write_transcript(tmp_path, [usage_row("a1")])

    (row,) = transcript.rows_from_transcript(path, actor="ba")

    assert (row.uuid, row.model, row.actor) == ("a1", "claude-sonnet-5", "ba")
    assert (row.tokens_in, row.tokens_out) == (7, 100)
    assert (row.cache_read, row.cache_write_5m, row.cache_write_1h) == (1000, 0, 300)
    assert row.assistant == "claude-code"
    assert row.est is False  # invariant I3


def test_rows_without_a_usage_block_are_ignored(tmp_path: Path):
    path = write_transcript(tmp_path, [user_row("hello"), usage_row("a1")])

    assert [r.uuid for r in transcript.rows_from_transcript(path, actor="ba")] == ["a1"]


def test_a_synthetic_model_row_is_skipped(tmp_path: Path):
    # Claude Code writes an all-zero '<synthetic>' row for an API error; it is
    # not an API call and must not appear as one.
    path = write_transcript(tmp_path, [usage_row("a1", model="<synthetic>")])

    assert transcript.rows_from_transcript(path, actor="ba") == []


def test_a_row_without_a_uuid_is_skipped(tmp_path: Path):
    # Without a uuid the row cannot be de-duplicated, so ingesting it twice
    # would double-count. Dropping it is the safe failure.
    row = usage_row("a1")
    del row["uuid"]
    path = write_transcript(tmp_path, [row])

    assert transcript.rows_from_transcript(path, actor="ba") == []


def test_the_ticket_cursor_is_set_by_a_tickets_path(tmp_path: Path):
    path = write_transcript(
        tmp_path,
        [user_row("please read tickets/open-new-flight.md"), usage_row("a1")],
    )

    (row,) = transcript.rows_from_transcript(path, actor="ba")

    assert row.ticket == "open-new-flight"


def test_the_ticket_cursor_reads_a_windows_path_too(tmp_path: Path):
    # Inside the JSONL a Windows path is backslash-escaped: docs\\impl\\x-plan.md
    path = write_transcript(
        tmp_path,
        [user_row("see docs\\impl\\ATM-7-plan.md"), usage_row("a1")],
    )

    (row,) = transcript.rows_from_transcript(path, actor="dev")

    assert row.ticket == "ATM-7"


def test_the_ticket_cursor_follows_missions_and_docs_impl(tmp_path: Path):
    path = write_transcript(
        tmp_path,
        [
            user_row("open missions/M-stock.md"),
            usage_row("a1"),
            user_row("now docs/impl/M-stock-US2-design.md"),
            usage_row("a2"),
        ],
    )

    rows = transcript.rows_from_transcript(path, actor="dev")

    assert [r.ticket for r in rows] == ["M-stock", "M-stock-US2"]


def test_rows_before_any_ticket_mention_have_no_ticket(tmp_path: Path):
    path = write_transcript(
        tmp_path,
        [usage_row("a1"), user_row("tickets/open-new-flight.md"), usage_row("a2")],
    )

    rows = transcript.rows_from_transcript(path, actor="ba")

    assert [(r.uuid, r.ticket) for r in rows] == [
        ("a1", None),
        ("a2", "open-new-flight"),
    ]


def test_the_template_file_is_not_a_ticket(tmp_path: Path):
    path = write_transcript(
        tmp_path, [user_row("read docs/tickets/TEMPLATE.md"), usage_row("a1")]
    )

    (row,) = transcript.rows_from_transcript(path, actor="ba")

    assert row.ticket is None


def test_a_traversal_stem_is_treated_as_no_mention(tmp_path: Path):
    path = write_transcript(
        tmp_path, [user_row("tickets/../../etc/passwd.md"), usage_row("a1")]
    )

    (row,) = transcript.rows_from_transcript(path, actor="ba")

    assert row.ticket is None


def test_the_last_mention_wins_and_mission_does_not_stack_with_ticket(tmp_path: Path):
    path = write_transcript(
        tmp_path,
        [
            user_row("missions/M-stock.md"),
            user_row("tickets/open-new-flight.md"),
            usage_row("a1"),
        ],
    )

    (row,) = transcript.rows_from_transcript(path, actor="ba")

    assert row.ticket == "open-new-flight"


def test_forced_ticket_overrides_every_cursor_result(tmp_path: Path):
    path = write_transcript(
        tmp_path, [user_row("tickets/open-new-flight.md"), usage_row("a1")]
    )

    (row,) = transcript.rows_from_transcript(
        path, actor="ba", forced_ticket="remove-witness-crew-stock-transfer"
    )

    assert row.ticket == "remove-witness-crew-stock-transfer"


def test_the_phase_cursor_is_set_by_a_command_marker(tmp_path: Path):
    path = write_transcript(
        tmp_path,
        [user_row("<command-name>/ba-ticket-author</command-name>"), usage_row("a1")],
    )

    (row,) = transcript.rows_from_transcript(path, actor="ba")

    assert row.phase == "ba-ticket-author"


def test_the_phase_cursor_is_set_by_a_skill_tool_call(tmp_path: Path):
    path = write_transcript(tmp_path, [skill_call_row("dev-execute"), usage_row("a1")])

    (row,) = transcript.rows_from_transcript(path, actor="dev")

    assert row.phase == "dev-execute"


def test_phase_is_unknown_before_any_command(tmp_path: Path):
    path = write_transcript(tmp_path, [usage_row("a1")])

    (row,) = transcript.rows_from_transcript(path, actor="ba")

    assert row.phase == "unknown"


def test_clear_resets_the_phase(tmp_path: Path):
    path = write_transcript(
        tmp_path,
        [
            user_row("<command-name>/ba-ticket-author</command-name>"),
            usage_row("a1"),
            user_row("<command-name>/clear</command-name>"),
            usage_row("a2"),
        ],
    )

    rows = transcript.rows_from_transcript(path, actor="ba")

    assert [r.phase for r in rows] == ["ba-ticket-author", "unknown"]


def test_an_unrelated_command_leaves_the_phase_alone(tmp_path: Path):
    path = write_transcript(
        tmp_path,
        [
            user_row("<command-name>/ba-ticket-author</command-name>"),
            user_row("<command-name>/model</command-name>"),
            usage_row("a1"),
        ],
    )

    (row,) = transcript.rows_from_transcript(path, actor="ba")

    assert row.phase == "ba-ticket-author"


def test_a_non_workflow_skill_is_not_a_phase(tmp_path: Path):
    path = write_transcript(
        tmp_path, [skill_call_row("superpowers:writing-plans"), usage_row("a1")]
    )

    (row,) = transcript.rows_from_transcript(path, actor="dev")

    assert row.phase == "unknown"


def test_a_skill_name_mentioned_in_content_is_not_a_phase(tmp_path: Path):
    # THE anti-test. A session that edits the dev skills mentions
    # 'dev-handover' hundreds of times while running something else; counting
    # mentions produced a phase breakdown that was wrong and looked right.
    path = write_transcript(
        tmp_path,
        [
            user_row("edit claude-skill-dev-handover.md — dev-handover, dev-handover"),
            usage_row("a1"),
        ],
    )

    (row,) = transcript.rows_from_transcript(path, actor="dev")

    assert row.phase == "unknown"


def test_sidechain_and_branch_are_carried_through(tmp_path: Path):
    path = write_transcript(tmp_path, [usage_row("a1", isSidechain=True)])

    (row,) = transcript.rows_from_transcript(path, actor="dev")

    assert row.sidechain is True
    assert row.branch == "feat/x"


def test_a_head_branch_is_recorded_as_none(tmp_path: Path):
    # A repo that is not a git repository reports 'HEAD' for every row; that is
    # not a branch and must not be shown as one.
    path = write_transcript(tmp_path, [usage_row("a1", gitBranch="HEAD")])

    (row,) = transcript.rows_from_transcript(path, actor="ba")

    assert row.branch is None


def test_reingesting_a_longer_transcript_reproduces_the_earlier_rows(tmp_path: Path):
    # Invariant I1: both cursors depend only on PRECEDING rows, so a prefix and
    # the full file must agree on every row the prefix contained.
    prefix = [user_row("tickets/open-new-flight.md"), usage_row("a1")]
    full = prefix + [user_row("<command-name>/clear</command-name>"), usage_row("a2")]

    short = transcript.rows_from_transcript(
        write_transcript(tmp_path, prefix, "short.jsonl"), actor="ba"
    )
    long = transcript.rows_from_transcript(
        write_transcript(tmp_path, full, "long.jsonl"), actor="ba"
    )

    assert [r.model_dump() for r in short] == [r.model_dump() for r in long[:1]]


def test_a_malformed_line_does_not_lose_the_rest_of_the_file(tmp_path: Path):
    path = tmp_path / "t.jsonl"
    path.write_text(
        json.dumps(usage_row("a1")) + "\n{ not json\n" + json.dumps(usage_row("a2"))
        + "\n",
        encoding="utf-8",
    )

    assert [r.uuid for r in transcript.rows_from_transcript(path, actor="ba")] == [
        "a1",
        "a2",
    ]


def test_a_tool_result_command_marker_does_not_reset_the_phase(tmp_path: Path):
    # A tool_result is file content the session merely read — a doc mentioning
    # the literal '/clear' marker must not act as if the session typed it.
    path = write_transcript(
        tmp_path,
        [
            user_row("<command-name>/ba-ticket-author</command-name>"),
            tool_result_row("... <command-name>/clear</command-name> ..."),
            usage_row("a1"),
        ],
    )

    (row,) = transcript.rows_from_transcript(path, actor="ba")

    assert row.phase == "ba-ticket-author"


def test_a_tool_result_ticket_mention_does_not_set_the_ticket_cursor(tmp_path: Path):
    path = write_transcript(
        tmp_path,
        [tool_result_row("see tickets/other-ticket.md for context"), usage_row("a1")],
    )

    (row,) = transcript.rows_from_transcript(path, actor="ba")

    assert row.ticket is None


def test_a_tool_use_file_path_input_sets_the_ticket_cursor(tmp_path: Path):
    # The signal being protected: a Read/Write/Edit's file_path argument is
    # the strongest ticket signal there is, and must keep working.
    path = write_transcript(
        tmp_path,
        [
            {
                "type": "assistant",
                "uuid": "au1",
                "sessionId": "sess-1",
                "timestamp": "2026-08-23T09:58:30.000Z",
                "message": {
                    "model": "claude-sonnet-5",
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Read",
                            "input": {"file_path": "tickets/open-new-flight.md"},
                        }
                    ],
                },
            },
            usage_row("a1"),
        ],
    )

    (row,) = transcript.rows_from_transcript(path, actor="ba")

    assert row.ticket == "open-new-flight"


def test_an_ask_user_question_input_does_not_move_the_ticket_cursor(tmp_path: Path):
    # A rejected naming proposal inside an AskUserQuestion option list is a
    # proposal, not something the session did — it must never plant a ticket.
    path = write_transcript(
        tmp_path,
        [
            {
                "type": "assistant",
                "uuid": "auq1",
                "sessionId": "sess-1",
                "timestamp": "2026-08-23T09:58:50.000Z",
                "message": {
                    "model": "claude-sonnet-5",
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "AskUserQuestion",
                            "input": {
                                "questions": [
                                    {"options": ["tickets/other.md", "keep as is"]}
                                ]
                            },
                        }
                    ],
                },
            },
            usage_row("a1"),
        ],
    )

    (row,) = transcript.rows_from_transcript(path, actor="ba")

    assert row.ticket is None


def test_a_todo_write_input_does_not_move_the_ticket_cursor(tmp_path: Path):
    path = write_transcript(
        tmp_path,
        [
            {
                "type": "assistant",
                "uuid": "tw1",
                "sessionId": "sess-1",
                "timestamp": "2026-08-23T09:58:55.000Z",
                "message": {
                    "model": "claude-sonnet-5",
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "TodoWrite",
                            "input": {"todos": [{"content": "edit tickets/other.md"}]},
                        }
                    ],
                },
            },
            usage_row("a1"),
        ],
    )

    (row,) = transcript.rows_from_transcript(path, actor="ba")

    assert row.ticket is None


def test_a_bash_command_ticket_mention_still_sets_the_cursor(tmp_path: Path):
    # The dominant real signal on BA data (41 of the real hits) — a fix for
    # the AskUserQuestion/TodoWrite phantom must not break this.
    path = write_transcript(
        tmp_path,
        [
            {
                "type": "assistant",
                "uuid": "bc1",
                "sessionId": "sess-1",
                "timestamp": "2026-08-23T09:58:59.000Z",
                "message": {
                    "model": "claude-sonnet-5",
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Bash",
                            "input": {"command": "cat tickets/open-new-flight.md"},
                        }
                    ],
                },
            },
            usage_row("a1"),
        ],
    )

    (row,) = transcript.rows_from_transcript(path, actor="ba")

    assert row.ticket == "open-new-flight"


def test_assistant_text_mentioning_a_ticket_sets_the_ticket_cursor(tmp_path: Path):
    path = write_transcript(
        tmp_path,
        [
            {
                "type": "assistant",
                "uuid": "au2",
                "sessionId": "sess-1",
                "timestamp": "2026-08-23T09:58:45.000Z",
                "message": {
                    "model": "claude-sonnet-5",
                    "content": [
                        {
                            "type": "text",
                            "text": "I'll work on tickets/open-new-flight.md now.",
                        }
                    ],
                },
            },
            usage_row("a1"),
        ],
    )

    (row,) = transcript.rows_from_transcript(path, actor="ba")

    assert row.ticket == "open-new-flight"
