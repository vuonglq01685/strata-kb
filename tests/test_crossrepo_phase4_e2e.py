"""Phase 4 end to end: Q&A recorded on the parent of a split story, per-ticket
blocking and the parent answer rule, on a hub with two dev repos."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from strata_kb import planingest
from strata_kb.hub import HubHandle
from strata_kb.ticketqa import (
    QaStore,
    answer_question,
    ask_question,
    confirm_blocks,
    list_questions,
    propose_blocks,
    qa_db_path,
)
from tests.test_crossrepo_phase3_e2e import _dev, _mirror
from tests.test_planingest import (
    API,
    US1,
    WEB,
    context_block,
    family,
    parent_story,
    write_repo,
)
from tests.test_ticketqa import _OLD_SCHEMA

REPO = "ba-x"
LOG2 = f"| 2 | 2026-11-07 | scope | units | {API}, {WEB} | B4 D4 (agent) |\n"


def _publish(root: Path, fed_hub: Path) -> None:
    planingest.run(root, root / ".kb", "demo", root / "missions", root / "tickets")
    shutil.rmtree(fed_hub / "federation" / REPO, ignore_errors=True)
    _mirror(fed_hub, root, REPO)


@pytest.fixture
def hub_ctx(fed_hub: Path, tmp_path: Path):
    """BA repo with parent US1 (rev 1) and children demo/web; two dev repos."""
    root = tmp_path / REPO
    write_repo(root, *family(context_block(fed_hub)))
    _publish(root, fed_hub)
    for repo in ("demo", "web"):
        _dev(fed_hub, repo)
    return HubHandle(root=fed_hub), root, QaStore(qa_db_path(fed_hub))


def _read_blocks(hub, store, ticket):
    return [r[3] for r in list_questions(hub, store, ticket_ref=f"{REPO}:{ticket}")]


def test_question_from_child_blocks_sibling_only_after_confirm(hub_ctx):
    hub, _, store = hub_ctx
    q = ask_question(hub, store, f"{REPO}:{WEB}", "Which unit?", "dev1", blocks="AC3")
    assert _read_blocks(hub, store, WEB) == [True]
    assert _read_blocks(hub, store, API) == [False]
    propose_blocks(store, q.id, "AC2", "same unit rule")
    assert _read_blocks(hub, store, API) == [False]
    confirm_blocks(store, q.id, "ba1")
    assert _read_blocks(hub, store, API) == [True]


def test_answer_flow_answered_after_both_children_republished(hub_ctx):
    hub, root, store = hub_ctx
    q = ask_question(hub, store, f"{REPO}:{WEB}", "Which unit?", "dev1")
    answer_question(hub, store, q.id, "Metres", "ba1", 2, [API, WEB])

    def state():
        return list_questions(hub, store, status="all")[0][1]

    assert state() == "waiting"
    tickets = root / "tickets"
    (tickets / f"{US1}.md").write_text(parent_story(LOG2, rev=2), encoding="utf-8")
    demo = tickets / f"{API}.md"
    demo.write_text(demo.read_text().replace(f"{US1} @ rev 1", f"{US1} @ rev 2"))
    _publish(root, hub.root)
    assert state() == "waiting"
    web = tickets / f"{WEB}.md"
    web.write_text(web.read_text().replace(f"{US1} @ rev 1", f"{US1} @ rev 2"))
    _publish(root, hub.root)
    assert state() == "answered"


def test_old_qa_db_upgrades_on_hub_open(hub_ctx, tmp_path):
    hub, _, _ = hub_ctx
    path = qa_db_path(hub.root)
    path.unlink()
    conn = sqlite3.connect(path)
    conn.execute(_OLD_SCHEMA)
    conn.commit()
    conn.close()
    assert list_questions(hub, QaStore(path), status="all") == []
