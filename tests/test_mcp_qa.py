"""kb_question_ask / kb_question_list / kb_question_answer over MCP."""

from __future__ import annotations

import shutil

import pytest
from mcp.shared.memory import (
    create_connected_server_and_client_session as connect_client,
)

from strata_kb.mcp import QA_NEEDS_HUB_SERVER, ServerConfig, create_server
from strata_kb.serving.accounts import ensure_git_exclude
from tests.test_planingest import US1
from tests.test_ticketfetch import _bug_hub

REPO = "ba-one"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _qa_db_out_of_git(fed_hub):
    # The server does this at start; the tests' `git add -A` must not commit qa.db.
    ensure_git_exclude(fed_hub, ".kb-qa/")


def _config(hub_root) -> ServerConfig:
    return ServerConfig(kb_dir=hub_root / ".kb", hub=str(hub_root))


def _text(result) -> str:
    return result.content[0].text


async def _call(client, name: str, **args) -> str:
    return _text(await client.call_tool(name, args))


@pytest.mark.anyio
async def test_round_trip_ask_list_answer(hub_with_ticket):
    hub = hub_with_ticket(rev=1)
    async with connect_client(
        create_server(_config(hub.root)), raise_exceptions=True
    ) as client:
        asked = await _call(
            client,
            "kb_question_ask",
            ticket=US1,
            question="Which currency?",
            asked_by="dev1",
            context="design §Pricing",
            blocks="AC-2",
        )
        assert asked == (
            f"Q1 asked on {REPO}:{US1} — /ui/questions/ticket?repo={REPO}&ticket={US1}"
        )
        listed = await _call(client, "kb_question_list")
        assert "Q1 [open]" in listed and "Which currency?" in listed

        done = await _call(
            client,
            "kb_question_answer",
            id=1,
            answer="EUR",
            answered_by="ba1",
            ticket_sections=["Scope"],
            answer_rev=2,
        )
        assert "Q1 answered" in done and "revision 2" in done
        assert "Q1 [waiting]" in await _call(client, "kb_question_list", status="all")
        assert await _call(client, "kb_question_list") == "No questions."

        hub_with_ticket(rev=2)  # the BA's revision reaches the hub
        answered = await _call(client, "kb_question_list", status="answered")
        assert "Q1 [answered]" in answered and "answer: EUR" in answered

        again = await _call(
            client,
            "kb_question_answer",
            id=1,
            answer="x",
            answered_by="ba2",
            ticket_sections=[],
        )
        assert "already answered by ba1" in again


@pytest.mark.anyio
async def test_write_tools_refuse_cache_clone_hub(tmp_path, monkeypatch):
    monkeypatch.setenv("STRATA_KB_HUB_CACHE", str(tmp_path / "cache"))
    config = ServerConfig(
        kb_dir=tmp_path / "repo" / ".kb", hub="https://example.invalid/hub.git"
    )
    async with connect_client(create_server(config), raise_exceptions=True) as client:
        ask = await _call(
            client, "kb_question_ask", ticket="M-a-US1", question="Q?", asked_by="d"
        )
        answer = await _call(
            client,
            "kb_question_answer",
            id=1,
            answer="A",
            answered_by="b",
            ticket_sections=[],
        )
        listed = await _call(client, "kb_question_list")
    assert ask == answer == QA_NEEDS_HUB_SERVER
    assert QA_NEEDS_HUB_SERVER == (
        "Q&A needs the shared hub server — point MCP at it (kb mcp-setup)"
    )
    assert "hub unreachable" in listed  # list is not refused; here the hub is down
    assert not (tmp_path / "repo" / ".kb-qa").exists()


@pytest.mark.anyio
async def test_unknown_ticket_message(hub_with_ticket):
    hub = hub_with_ticket()
    async with connect_client(
        create_server(_config(hub.root)), raise_exceptions=True
    ) as client:
        out = await _call(
            client,
            "kb_question_ask",
            ticket="M-nope-US9",
            question="Q?",
            asked_by="dev1",
        )
        bad = await _call(
            client, "kb_question_ask", ticket="../x", question="Q?", asked_by="dev1"
        )
        empty = await _call(
            client, "kb_question_ask", ticket=US1, question=" ", asked_by="dev1"
        )
        unknown_id = await _call(
            client,
            "kb_question_answer",
            id=99,
            answer="A",
            answered_by="b",
            ticket_sections=[],
        )
        bad_status = await _call(client, "kb_question_list", status="nope")
    assert "M-nope-US9 is not on the hub" in out
    assert "is not a ticket id" in bad
    assert "question must not be empty" in empty
    assert "Q99 does not exist" in unknown_id
    assert "status must be one of" in bad_status


@pytest.mark.anyio
async def test_question_text_with_newlines_and_markup_round_trips(hub_with_ticket):
    hub = hub_with_ticket()
    text = "Line one\n<script>alert(1)</script>\n- **bold** `code`"
    async with connect_client(
        create_server(_config(hub.root)), raise_exceptions=True
    ) as client:
        await _call(
            client, "kb_question_ask", ticket=US1, question=text, asked_by="dev1"
        )
        listed = await _call(client, "kb_question_list")
    assert (
        "  question: Line one\n    <script>alert(1)</script>\n    - **bold** `code`"
        in listed
    )


@pytest.mark.anyio
async def test_bug_ticket_can_be_asked_about(fed_hub, tmp_path, run_git):
    hub, _ = _bug_hub(fed_hub, tmp_path, run_git)
    async with connect_client(
        create_server(_config(hub.root)), raise_exceptions=True
    ) as client:
        asked = await _call(
            client,
            "kb_question_ask",
            ticket="BUG-12",
            question="Which browsers?",
            asked_by="dev1",
        )
        listed = await _call(client, "kb_question_list", ticket=f"{REPO}:BUG-12")
    assert asked.startswith(f"Q1 asked on {REPO}:BUG-12 — ")
    assert "Q1 [open]" in listed and "Which browsers?" in listed


@pytest.mark.anyio
async def test_nested_repo_ref_mid_slash_ba(fed_hub, tmp_path):
    from tests.test_planingest import context_block
    from tests.test_ticketfetch import publish_plan

    publish_plan(fed_hub, "ba-x", tmp_path / "ba-x", context_block(fed_hub))
    # The loader keeps a nested entry only when its recorded kind is kb, so
    # move the entry under mid/ and record that kind.
    (fed_hub / "federation" / "mid").mkdir()
    entry = fed_hub / "federation" / "mid" / "ba-x"
    shutil.move(str(fed_hub / "federation" / "ba-x"), entry)
    meta = entry / "_meta.yaml"
    meta.write_text(
        meta.read_text(encoding="utf-8").replace("kind: ''", "kind: kb"),
        encoding="utf-8",
        newline="\n",
    )
    async with connect_client(
        create_server(_config(fed_hub)), raise_exceptions=True
    ) as client:
        asked = await _call(
            client,
            "kb_question_ask",
            ticket=f"mid/ba-x:{US1}",
            question="Nested?",
            asked_by="dev1",
        )
        by_repo = await _call(client, "kb_question_list", repo="mid/ba-x")
        by_ref = await _call(client, "kb_question_list", ticket=f"mid/ba-x:{US1}")
    assert asked == (
        f"Q1 asked on mid/ba-x:{US1} — "
        f"/ui/questions/ticket?repo=mid%2Fba-x&ticket={US1}"
    )
    assert "Q1 [open] mid/ba-x:" in by_repo and by_repo == by_ref
