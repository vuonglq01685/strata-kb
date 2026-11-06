"""Hub ticket pages of a parent story and its children."""

from starlette.applications import Starlette
from starlette.testclient import TestClient

from strata_kb.mcp import ServerConfig
from strata_kb.web import planui, ui
from tests.test_missionlint import MISSION_ID
from tests.test_planingest import API, US1, WEB
from tests.test_planstatus_parents import build  # noqa: F401  (fixture)


def _client(hub) -> TestClient:
    config = ServerConfig(kb_dir=hub.root / ".kb", hub=str(hub.root))
    return TestClient(
        Starlette(routes=ui.build_routes(config, "t") + planui.plan_routes(config))
    )


def _href(story: str) -> str:
    return f"/ui/tickets/{MISSION_ID}/{story}?repo=ba-x"


def test_parent_page_shows_split_and_children(build):  # noqa: F811
    text = _client(build()).get(_href(US1)).text
    assert "Children" in text and "0/2 done" in text
    for child, repo in ((API, "demo"), (WEB, "web")):
        assert f'href="{_href(child)}"' in text
        assert f">{repo}<" in text
    assert "in progress" in text


def test_parent_page_leaves_unwritten_child_unlinked(build):  # noqa: F811
    text = _client(build(unticked=(WEB,))).get(_href(US1)).text
    assert f'href="{_href(API)}"' in text
    assert f'href="{_href(WEB)}"' not in text and WEB in text


def test_child_page_links_parent_and_siblings(build):  # noqa: F811
    text = _client(build()).get(_href(API)).text
    assert f'href="{_href(US1)}"' in text
    assert f'href="{_href(WEB)}"' in text
    assert "Parent story" in text and "Sibling" in text


def test_plain_ticket_page_has_no_family(plan_hub):
    text = _client(plan_hub).get("/ui/tickets/tickets/TAL-1580?repo=ba-one").text
    assert "Sibling" not in text and "Children" not in text


def test_mission_page_lists_parent_with_progress(build):  # noqa: F811
    text = _client(build()).get(f"/ui/tickets/{MISSION_ID}?repo=ba-x").text
    assert "0/2 done" in text and "in progress" in text
    assert f'href="{_href(US1)}"' in text
