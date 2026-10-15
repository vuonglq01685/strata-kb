"""The Q&A menu: read-only pages over the ticket Q&A store."""

import re
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from strata_kb.serving.accounts import Accounts
from strata_kb.ticketqa import QaStore, answer_question, ask_question, qa_db_path
from tests.test_planingest import MISSION_ID, US1

REPO = "ba-one"
TICKET_HREF = f"/ui/tickets/{MISSION_ID}/{US1}?repo={REPO}"
QA_HREF = f"/ui/questions/ticket?repo={REPO}&amp;ticket={US1}"


def _store(hub) -> QaStore:
    return QaStore(qa_db_path(hub.root))


def _main(html: str) -> str:
    return re.search(r"<main.*?</main>", html, re.S).group(0)


def test_menu_link_on_every_page(web_client_logged_in):
    for path in ("/ui", "/ui/docs", "/ui/tickets", "/ui/questions", "/ui/registry"):
        resp = web_client_logged_in.get(path)
        assert resp.status_code == 200, path
        assert 'href="/ui/questions"' in resp.text, path
    page = web_client_logged_in.get("/ui/questions").text
    assert re.search(r'class="active">Q&amp;A<', page)


def test_get_does_not_create_the_db_or_dir(web_client_logged_in, hub_dir):
    resp = web_client_logged_in.get("/ui/questions")
    assert resp.status_code == 200
    assert "No questions yet" in resp.text
    resp = web_client_logged_in.get(f"/ui/questions/ticket?repo={REPO}&ticket={US1}")
    assert resp.status_code == 200
    assert not (hub_dir / ".kb-qa").exists()


def test_list_groups_by_repo_with_counts_and_oldest_age(
    web_client_logged_in, hub_with_ticket
):
    hub = hub_with_ticket(rev=1)
    store = _store(hub)
    q1 = ask_question(hub, store, US1, "first?", "dev1")
    ask_question(hub, store, US1, "second?", "dev1")
    ask_question(hub, store, US1, "third?", "dev1")
    ask_question(hub, store, US1, "fourth?", "dev1")
    answer_question(hub, store, q1.id, "yes", "ba1", None, [])
    answer_question(hub, store, q1.id + 1, "changed", "ba1", 2, ["Scope"])
    # age the oldest open question (Q3) by three days
    old = (datetime.now(UTC) - timedelta(days=3)).isoformat(timespec="seconds")
    with sqlite3.connect(qa_db_path(hub.root)) as conn:
        conn.execute("UPDATE questions SET asked_at = ? WHERE id = ?", (old, q1.id + 2))

    text = web_client_logged_in.get("/ui/questions").text
    assert f"<h2>{REPO}</h2>" in text
    assert f'href="{TICKET_HREF}"' in text
    assert "2 open" in text and "1 waiting" in text and "1 answered" in text
    assert "oldest open: 3d" in text
    assert f'href="{QA_HREF}"' in text


def test_default_hides_fully_answered_tickets_all_shows_them(
    web_client_logged_in, hub_with_ticket
):
    hub = hub_with_ticket(rev=1)
    store = _store(hub)
    q = ask_question(hub, store, US1, "done?", "dev1")
    answer_question(hub, store, q.id, "done", "ba1", None, [])

    default = web_client_logged_in.get("/ui/questions").text
    assert US1 not in _main(default)
    assert "No unresolved questions" in default
    shown = web_client_logged_in.get("/ui/questions?all=1").text
    assert US1 in _main(shown)
    assert "1 answered" in shown


def test_ticket_page_shows_states_answers_sections_and_waiting_note(
    web_client_logged_in, hub_with_ticket
):
    hub = hub_with_ticket(rev=1)
    store = _store(hub)
    ask_question(
        hub, store, US1, "open one?", "dev1", context="design §3", blocks="AC-1"
    )
    waiting = ask_question(hub, store, US1, "waiting one?", "dev2")
    answer_question(hub, store, waiting.id, "see rev 2", "ba1", 2, ["Scope", "AC"])
    done = ask_question(hub, store, US1, "done one?", "dev3")
    answer_question(hub, store, done.id, "no change", "ba2", None, [])

    text = web_client_logged_in.get(
        f"/ui/questions/ticket?repo={REPO}&ticket={US1}"
    ).text
    main = _main(text)
    assert (
        main.index("open one?") < main.index("waiting one?") < main.index("done one?")
    )
    for state in ("open", "waiting", "answered"):
        assert f">{state}</span>" in main
    assert "design §3" in main and "AC-1" in main
    assert "see rev 2" in main and "ticket rev 2" in main
    assert "not on the hub yet" in main
    assert main.count("not on the hub yet") == 1
    assert ">Scope</span>" in main and ">AC</span>" in main
    assert "answered by ba1" in main and "asked by dev1" in main
    assert "hub rev 1" in main
    assert f'href="{TICKET_HREF}"' in main


def test_script_in_question_and_answer_is_escaped(
    web_client_logged_in, hub_with_ticket
):
    hub = hub_with_ticket(rev=1)
    store = _store(hub)
    q = ask_question(
        hub,
        store,
        US1,
        "<script>alert(1)</script>",
        "<b>dev</b>",
        context="<img src=x>",
    )
    answer_question(hub, store, q.id, "<script>alert(2)</script>", "ba1", None, [])
    text = web_client_logged_in.get(
        f"/ui/questions/ticket?repo={REPO}&ticket={US1}"
    ).text
    assert "<script>alert" not in text
    assert "<img src=x>" not in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text
    assert "&lt;script&gt;alert(2)&lt;/script&gt;" in text


def test_nested_repo_id_in_query_string(web_client_logged_in, hub_dir):
    QaStore(qa_db_path(hub_dir)).ask("mid/ba-x", "T-1", "nested?", "", "", "dev1", 1)
    listing = web_client_logged_in.get("/ui/questions").text
    assert "mid/ba-x" in listing
    assert "repo=mid%2Fba-x&amp;ticket=T-1" in listing
    page = web_client_logged_in.get("/ui/questions/ticket?repo=mid%2Fba-x&ticket=T-1")
    assert page.status_code == 200
    assert "nested?" in page.text


def test_ticket_gone_from_hub_renders_id_without_link_and_rev_dash(
    web_client_logged_in, hub_dir
):
    QaStore(qa_db_path(hub_dir)).ask(
        REPO, "TAL-GONE", "still there?", "", "", "dev1", 1
    )
    listing = _main(web_client_logged_in.get("/ui/questions").text)
    assert "TAL-GONE" in listing
    assert "/ui/tickets/" not in listing
    page = _main(
        web_client_logged_in.get(
            f"/ui/questions/ticket?repo={REPO}&ticket=TAL-GONE"
        ).text
    )
    assert "hub rev —" in page
    assert "/ui/tickets/" not in page


def test_ticket_page_shows_unresolved_link(web_client_logged_in, hub_with_ticket):
    hub = hub_with_ticket(rev=1)
    store = _store(hub)
    url = f"/ui/tickets/{MISSION_ID}/{US1}?repo={REPO}"
    assert "unresolved question" not in web_client_logged_in.get(url).text
    ask_question(hub, store, US1, "one?", "dev1")
    text = web_client_logged_in.get(url).text
    assert "1 unresolved question<" in text
    assert f'href="{QA_HREF}"' in text
    ask_question(hub, store, US1, "two?", "dev1")
    assert "2 unresolved questions<" in web_client_logged_in.get(url).text


def test_ticket_page_without_questions_does_not_create_db(
    web_client_logged_in, hub_with_ticket, hub_dir
):
    hub_with_ticket(rev=1)
    resp = web_client_logged_in.get(f"/ui/tickets/{MISSION_ID}/{US1}?repo={REPO}")
    assert resp.status_code == 200
    assert not (hub_dir / ".kb-qa").exists()


def test_pages_have_no_forms(web_client_logged_in, hub_with_ticket):
    hub = hub_with_ticket(rev=1)
    ask_question(hub, _store(hub), US1, "q?", "dev1")
    for path in (
        "/ui/questions",
        "/ui/questions?all=1",
        f"/ui/questions/ticket?repo={REPO}&ticket={US1}",
    ):
        main = _main(web_client_logged_in.get(path).text)
        assert "<form" not in main, path


@pytest.mark.parametrize(
    "query", ["", "?repo=ba-one", "?ticket=X", "?repo=&ticket=X", "?repo=r&ticket=../x"]
)
def test_ticket_page_bad_parameters_are_400(web_client_logged_in, query):
    resp = web_client_logged_in.get(f"/ui/questions/ticket{query}")
    assert resp.status_code == 400


def test_unknown_ticket_has_no_questions_page(web_client_logged_in):
    resp = web_client_logged_in.get("/ui/questions/ticket?repo=r&ticket=NOPE")
    assert resp.status_code == 200
    assert "No questions" in resp.text


def test_bearer_and_dev_role_can_view(web_client, hub_dir, token, admin_user):
    path = "/ui/questions"
    assert web_client.get(path, follow_redirects=False).status_code in (302, 303, 307)
    bearer = web_client.get(path, headers={"Authorization": f"Bearer {token}"})
    assert bearer.status_code == 200
    assert 'href="/ui/questions"' in bearer.text

    Accounts(hub_dir / ".kb-auth" / "users.db").add("dev1", "pw-dev-1234", "dev")
    login = web_client.post(
        "/ui/login",
        data={"username": "dev1", "password": "pw-dev-1234"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    resp = web_client.get(path)
    assert resp.status_code == 200
    assert 'href="/ui/questions"' in resp.text


def test_asker_and_section_names_are_escaped(web_client_logged_in, hub_with_ticket):
    hub = hub_with_ticket(rev=1)
    store = _store(hub)
    q = ask_question(hub, store, US1, "plain?", "<b>dev</b>")
    answer_question(hub, store, q.id, "ok", "<i>ba</i>", 2, ["<script>x</script>"])
    text = web_client_logged_in.get(
        f"/ui/questions/ticket?repo={REPO}&ticket={US1}"
    ).text
    assert "<b>dev</b>" not in text and "&lt;b&gt;dev&lt;/b&gt;" in text
    assert "<i>ba</i>" not in text
    assert "<script>x</script>" not in text
    assert "&lt;script&gt;x&lt;/script&gt;" in text


def test_hostile_repo_param_is_escaped_in_breadcrumbs(web_client_logged_in):
    resp = web_client_logged_in.get(
        "/ui/questions/ticket",
        params={"repo": "<script>boom</script>", "ticket": "T-1"},
    )
    assert resp.status_code == 200
    assert "<script>boom" not in resp.text
    assert "&lt;script&gt;boom" in resp.text


def _corrupt_db(hub_dir):
    path = qa_db_path(hub_dir)
    path.parent.mkdir()
    path.write_bytes(b"this is not a sqlite database" * 20)


def test_corrupt_db_is_503_on_qa_pages(web_client_logged_in, hub_dir):
    _corrupt_db(hub_dir)
    for path in (
        "/ui/questions",
        "/ui/questions/ticket?repo=ba-one&ticket=T-1",
    ):
        resp = web_client_logged_in.get(path)
        assert resp.status_code == 503, path
        assert "Q&amp;A unavailable" in resp.text


def test_plan_ticket_page_survives_corrupt_db(
    web_client_logged_in, hub_with_ticket, hub_dir
):
    hub_with_ticket(rev=1)
    _corrupt_db(hub_dir)
    resp = web_client_logged_in.get(f"/ui/tickets/{MISSION_ID}/{US1}?repo={REPO}")
    assert resp.status_code == 200
    assert "unresolved question" not in resp.text
