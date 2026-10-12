"""Shared template bodies (1.15.2): a skill's Copilot and Cursor copies, and
for seven skills its Claude skill too, are frontmatter stubs that end in one
include directive; the text they share lives once in templates/init/bodies/.
`kb init` writes the rendered text, never a directive."""

from __future__ import annotations

import re
from importlib import resources

import pytest

from strata_kb.initcmd import KINDS, init_repo, read_template

DIRECTIVE = re.compile(r"<!-- strata-kb:include (bodies/[a-z0-9-]+\.md) -->")
BASE = resources.files("strata_kb").joinpath("templates/init")


def _templates() -> list[str]:
    return sorted(f.name for f in BASE.iterdir() if f.is_file())


def _stubs() -> dict[str, str]:
    stubs = {}
    for name in _templates():
        match = DIRECTIVE.search(BASE.joinpath(name).read_text(encoding="utf-8"))
        if match:
            stubs[name] = match.group(1)
    return stubs


def test_every_body_is_shared_by_at_least_two_stubs():
    by_body: dict[str, list[str]] = {}
    for stub, body in _stubs().items():
        by_body.setdefault(body, []).append(stub)
    bodies = sorted(f"bodies/{f.name}" for f in BASE.joinpath("bodies").iterdir())
    assert sorted(by_body) == bodies  # no orphan body, no missing one
    for body, stubs in by_body.items():
        assert len(stubs) >= 2, (body, stubs)


@pytest.mark.parametrize("name", sorted(_stubs()))
def test_a_stub_is_frontmatter_its_own_short_intro_and_the_directive(name):
    raw = BASE.joinpath(name).read_text(encoding="utf-8")
    assert raw.startswith("---\n")
    after = raw[raw.index("\n---\n", 4) + len("\n---\n") :]
    lines = [line for line in after.splitlines() if line.strip()]
    assert DIRECTIVE.fullmatch(lines[-1])
    # Only what genuinely differs per tool stays in the stub: a heading, and
    # for some skills an intro paragraph; everything shared is in the body.
    assert len(lines) <= 20, lines
    assert raw.count("strata-kb:include") == 1


@pytest.mark.parametrize("name", _templates())
def test_no_rendered_template_carries_a_directive(name):
    assert "strata-kb:include" not in read_template(name)


def test_stubs_of_one_skill_render_one_shared_body():
    for stub, body in _stubs().items():
        shared = BASE.joinpath(body).read_text(encoding="utf-8")
        assert read_template(stub).endswith(shared), stub


@pytest.mark.parametrize("kind", KINDS)
def test_kb_init_writes_rendered_text(tmp_path, kind):
    init_repo(tmp_path, kind)
    for path in tmp_path.rglob("*"):
        if path.is_file() and path.suffix in {".md", ".mdc"}:
            assert "strata-kb:include" not in path.read_text(encoding="utf-8"), path


@pytest.mark.parametrize(
    "name",
    [
        "claude-skill-dev-implement-ticket.md",
        "claude-command-dev-implement-ticket.md",
        "copilot-dev-implement-ticket.prompt.md",
        "cursor-dev-implement-ticket.md",
    ],
)
def test_dev_implement_ticket_runs_ticket_check(name):
    text = " ".join(read_template(name).split())
    assert "kb ticket check docs/impl/<id>/ticket.md" in text, name
    assert "re-run /sa-ticket-ground" in text, name


def _body(name: str) -> str:
    return " ".join(BASE.joinpath("bodies", name).read_text(encoding="utf-8").split())


@pytest.mark.parametrize("name", ["ba-mission-plan.md", "ba-ticket-author.md"])
def test_ba_bodies_search_kb_and_dev_kinds(name):
    assert "--kind kb --kind dev" in _body(name)
    assert 'kinds=["kb","dev"]' in _body(name)


def test_dev_implement_ticket_names_each_kind_it_searches():
    text = _body("dev-implement-ticket.md")
    for kind in ("--kind dev", "--kind ba", "--kind kb"):
        assert kind in text, kind


@pytest.mark.parametrize(
    "text",
    [
        _body("dev-implement-ticket.md"),
        " ".join(read_template("claude-skill-dev-implement-ticket.md").split()),
    ],
    ids=["body", "claude-skill"],
)
def test_dev_implement_ticket_restricts_dev_search_to_own_repo(text):
    for suffix in ("code", "svc"):
        assert f"--tags <repo_id>-{suffix}" in text
        assert f'tags=["<repo_id>-{suffix}"]' in text


def test_sa_ticket_ground_searches_dev_kind():
    assert "--kind dev" in _body("sa-ticket-ground.md")


def test_kb_code_sync_searches_kb_kind():
    assert "--kind kb" in _body("kb-code-sync.md")


@pytest.mark.parametrize("name", ["dev-design.md", "dev-plan.md", "dev-execute.md"])
def test_dev_flow_bodies_carry_no_kind_filter(name):
    assert "--kind" not in _body(name)


@pytest.mark.parametrize(
    "name",
    [
        "claude-skill-kb-publish.md",
        "cursor-kb-publish.md",
        "copilot-kb-publish.prompt.md",
    ],
)
def test_kb_publish_confirm_shows_hub_menu_line(name):
    text = " ".join(read_template(name).split())
    assert "hub menu" in text, name
    assert "kb init --kind" in text, name
    assert "`hub` and `child` repos → Document" in text, name
    assert "`kind:` in `.kb/config.yaml`" in text, name
    assert "`[info] kind: …` line `kb doctor` prints" in text, name
