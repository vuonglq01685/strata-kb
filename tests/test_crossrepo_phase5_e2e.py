"""Phase 5 end to end: a parent bug with a child in another repo — roll-up with
the own fix, and the split-proposal question — on a hub with two dev repos."""

from __future__ import annotations

import shutil
from pathlib import Path

from strata_kb import planingest, planstatus
from strata_kb.hub import HubHandle
from strata_kb.ticketqa import (
    QaStore,
    answer_question,
    ask_question,
    list_questions,
    qa_db_path,
)
from tests.test_buglint import _bug
from tests.test_crossrepo_phase3_e2e import _dev, _mirror
from tests.test_planingest import _PNG, write_repo
from tests.test_ticketlint_family import bug_child_text, bug_parent_text

REPO = "ba-x"
BUG, KID = "BUG-7", "BUG-7.web"
LOG2 = f"| 2 | 2026-11-08 | scope | split | {KID} | B4 D4 (agent) |\n"
ROWS = (
    f"| {BUG} | demo | - | {KID} | yes | own fix |\n| {KID} | web | - | - | - | ui |\n"
)


def _plain() -> str:
    text = _bug(title=f"# {BUG} — export fails")
    return text.replace("> Type: bug\n", "> Type: bug\n> Target repo: demo\n", 1)


def _parent(rev: int = 1) -> str:
    text = bug_parent_text(BUG, ROWS)
    text = text.replace(
        "> Kind: parent bug\n", "> Kind: parent bug\n> Target repo: demo\n"
    )
    text = text.replace("> Revision: 1", f"> Revision: {rev}", 1)
    return text + LOG2 if rev == 2 else text


def _child(rev: int = 1) -> str:
    return bug_child_text(KID, "web", "None", BUG).replace(
        f"{BUG} @ rev 1", f"{BUG} @ rev {rev}"
    )


def _publish(root: Path, fed_hub: Path, texts: dict[str, str], done=None) -> HubHandle:
    tickets = {
        f"bugs/{i}.md": t.replace("- [ ] ", "- [x] ").replace("BUG-12", BUG)
        for i, t in texts.items()
    }
    write_repo(root, {}, tickets)
    folder = root / "tickets" / "bugs" / BUG
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "toast.png").write_bytes(_PNG)
    planingest.run(root, root / ".kb", "demo", root / "missions", root / "tickets")
    shutil.rmtree(fed_hub / "federation" / REPO, ignore_errors=True)
    _mirror(fed_hub, root, REPO)
    for repo in ("demo", "web"):
        shutil.rmtree(fed_hub / "federation" / repo, ignore_errors=True)
        _dev(fed_hub, repo, (done or {}).get(repo, ()))
    return HubHandle(root=fed_hub)


def _rows(hub: HubHandle) -> dict:
    stories, unparented, _ = planstatus.next_from_hub(hub)
    return {r.us_id: r for r in (*stories, *unparented)}


def test_parent_bug_flow_rolls_up(fed_hub, tmp_path):
    root = tmp_path / REPO
    _publish(root, fed_hub, {BUG: _plain()})
    assert _rows(HubHandle(root=fed_hub))[BUG].target_repo == "demo"

    hub = _publish(root, fed_hub, {BUG: _parent(), KID: _child()})
    rows = _rows(hub)
    assert rows[BUG].status == "in progress" and not rows[BUG].own_fix_ready
    assert (rows[KID].status, rows[KID].target_repo) == ("ready", "web")

    hub = _publish(root, fed_hub, {BUG: _parent(), KID: _child()}, {"web": (KID,)})
    assert _rows(hub)[BUG].own_fix_ready
    assert _rows(hub)[BUG].target_repo == "demo"

    hub = _publish(
        root, fed_hub, {BUG: _parent(), KID: _child()}, {"web": (KID,), "demo": (BUG,)}
    )
    assert _rows(hub)[BUG].status == "done"


def test_split_proposal_question_reaches_parent_bug(fed_hub, tmp_path):
    root = tmp_path / REPO
    hub = _publish(root, fed_hub, {BUG: _plain()})
    store = QaStore(qa_db_path(fed_hub))
    q = ask_question(
        hub, store, f"{REPO}:{BUG}", f"Split proposal for {BUG}: fix in web too", "dev1"
    )

    def state() -> str:
        return list_questions(hub, store, status="all")[0][1]

    answer_question(hub, store, q.id, "Split it", "ba1", 2, [KID])
    assert state() == "waiting"
    hub = _publish(root, fed_hub, {BUG: _parent(2), KID: _child(2)})
    assert state() == "answered"
