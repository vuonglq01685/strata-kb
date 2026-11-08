"""Phase 5 end to end: a parent bug with a child in another repo — roll-up with
the own fix, and the split-proposal question — on a hub with two dev repos; a
child bug whose cause is in a third repo adds a sibling, never a grandchild."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from strata_kb import planingest, planstatus, ticketlint
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


def _publish(
    root: Path,
    fed_hub: Path,
    texts: dict[str, str],
    done=None,
    devs: tuple[str, ...] = ("demo", "web"),
) -> HubHandle:
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
    for repo in devs:
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


# --- a child bug's cause in a third repo: a sibling on the same parent -------

SIB = "BUG-7.api"
DEVS = ("demo", "web", "api")
LOG3 = (
    f"| 3 | 2026-11-08 | scope | sibling for {KID} | {SIB}, {KID} | B4 D4 (agent) |\n"
)
ROWS3 = (
    f"| {BUG} | demo | - | {KID} | yes | own fix |\n"
    f"| {KID} | web | - | {SIB} | - | ui |\n"
    f"| {SIB} | api | - | - | - | data |\n"
)


def _parent3() -> str:
    text = _parent(2).replace(ROWS, ROWS3).replace("> Revision: 2", "> Revision: 3", 1)
    return text + LOG3


def _amended() -> dict[str, str]:
    """`/ba-bug-report --child-of BUG-7.web`: BUG-7's split gains the sibling."""
    kid = _child(3).replace("- Blocked by: None", f"- Blocked by: {SIB}")
    return {
        BUG: _parent3(),
        KID: kid,
        SIB: bug_child_text(SIB, "api", "None", BUG).replace(
            f"{BUG} @ rev 1", f"{BUG} @ rev 3"
        ),
    }


def test_child_bug_sibling_split_rolls_up(fed_hub, tmp_path):
    root = tmp_path / REPO
    hub = _publish(root, fed_hub, {BUG: _parent(2), KID: _child(2)}, devs=DEVS)
    store = QaStore(qa_db_path(fed_hub))
    q = ask_question(
        hub, store, f"{REPO}:{KID}", f"Split proposal for {KID}: cause in api", "dev2"
    )
    assert (q.ticket, q.asked_from) == (BUG, KID)  # Q&A lives at the parent bug

    def proposal() -> str:
        # what the runner's `_split_answered` reads: the list under the child id
        rows = list_questions(hub, store, f"{REPO}:{KID}", status="all")
        mine = [
            r for r in rows if r[0].question.startswith(f"Split proposal for {KID}:")
        ]
        return mine[-1][1]

    assert proposal() == "open"
    answer_question(hub, store, q.id, "Add the api sibling", "ba1", 3, [SIB, KID])
    assert proposal() == "waiting"  # until the amended family is on the hub

    hub = _publish(root, fed_hub, _amended(), devs=DEVS)
    assert proposal() == "answered"
    rows = _rows(hub)
    assert KID in rows and SIB in rows and f"{KID}.api" not in rows  # one level
    assert (rows[SIB].status, rows[SIB].target_repo) == ("ready", "api")
    assert rows[KID].status == "blocked" and not rows[BUG].own_fix_ready

    hub = _publish(root, fed_hub, _amended(), {"api": (SIB,)}, devs=DEVS)
    assert _rows(hub)[KID].status == "ready"

    done = {"api": (SIB,), "web": (KID,)}
    hub = _publish(root, fed_hub, _amended(), done, devs=DEVS)
    assert _rows(hub)[BUG].own_fix_ready and _rows(hub)[BUG].status != "done"

    hub = _publish(root, fed_hub, _amended(), {**done, "demo": (BUG,)}, devs=DEVS)
    assert _rows(hub)[BUG].status == "done"


def test_child_bug_made_a_parent_bug_fails_closed(fed_hub, tmp_path):
    root = tmp_path / REPO
    _publish(root, fed_hub, {BUG: _parent(2), KID: _child(2)}, devs=DEVS)
    nested = f"{KID}.api"
    split = bug_parent_text(
        KID,
        f"| {KID} | web | - | {nested} | yes | ui |\n"
        f"| {nested} | api | - | - | - | data |\n",
    ).split("\n\n## Split", 1)[1]
    # BUG-7.web turned into a parent bug of its own: a grandchild split
    kid = _child(2).replace("> Type: bug\n", "> Type: bug\n> Kind: parent bug\n", 1)
    kid += "\n## Split" + split
    texts = {
        BUG: _parent(2),
        KID: kid,
        nested: bug_child_text(nested, "api", "None", KID),
    }
    with pytest.raises(planingest.PlanIngestError, match="nothing published"):
        _publish(root, fed_hub, texts, devs=DEVS)
    # the publish message shows the first error only; the full lint names the rule
    report = ticketlint.lint(
        kid, HubHandle(root=fed_hub), ticket_id=KID, load_ticket=texts.get
    )
    assert f"{KID} is a child bug and cannot be a parent bug" in "\n".join(
        i.message for i in report.issues if i.level == "error"
    )
