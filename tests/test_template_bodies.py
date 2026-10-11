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
