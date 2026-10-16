"""Final review, Minor 9: `README.md` has no content coverage at all --
`tests/test_check_package.py` checks only packaging/static-asset presence,
never a word of the prose. Section 7.13 (Phase 5 Stage C) is ~100 new lines
of claim-dense text, including a real gate-integrity constraint (a hub
auto-merging on "this is a `-code` PR" would auto-merge `-svc` content
riding along in the same PR, since `intake.py`'s publish path keys one
branch/PR by repo id, not by document). Pin the load-bearing claims the
same way `tests/test_init.py`'s QUICKSTART pins already do: distinctive
multi-word phrases, matched against whitespace-normalised text so a future
re-wrap of the prose does not itself break this test.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _readme_text() -> str:
    return (REPO_ROOT / "README.md").read_text(encoding="utf-8")


def _normalised(text: str) -> str:
    return " ".join(text.split())


def test_readme_pins_the_per_repo_auto_merge_switch():
    text = _normalised(_readme_text())
    # `kb ci-publish` opens ONE PR per push (keyed by repo id, not by
    # document), so the per-repo auto-merge switch merges the whole PR and the
    # "-svc" review has to happen locally, before publish.
    assert "opens one hub PR per publish, not per document" in text
    assert "per-repo switch on the hub's Registry page" in text
    assert "auto-merge merges the **whole PR**" in text
    assert "`/dev-code-seed` step 4" in text
    # the old hub-side, path-scoped rule is gone
    assert "path-scoped" not in text


def test_readme_documents_hub_accounts_and_the_registry_page():
    text = _normalised(_readme_text())
    assert "sign in with the token" not in text
    assert "`<hub>/.kb-auth/` (`users.db` and `session.key`)" in text
    assert "`STRATA_KB_BOOTSTRAP_ADMIN` and `STRATA_KB_BOOTSTRAP_PASSWORD_HASH`" in text
    assert "`STRATA_KB_BOOTSTRAP_PASSWORD_HASH='<hash>'`" in text
    assert "only `admin` sees and uses the **Registry** page" in text
    assert "`contents: write` and `pull_requests: write`" in text


def test_readme_pins_why_code_and_svc_cannot_share_one_document():
    text = _normalised(_readme_text())
    assert "One document can't carry both review styles at once." in text


def test_readme_shows_the_real_query_output():
    """Reviewer C F-C13: §7.5 still showed `score=17.19` and an unqualified
    `[arinc-424 §5.129 ...]`. `_citation` (query.py:47-49) prefixes `repo_id:`
    unconditionally — there is no 'only on ambiguity' branch — and `score=` was
    removed in the hybrid rework."""
    text = _normalised(_readme_text())
    assert "match=keyword" in text
    assert "score=17.19" not in text
    assert "citation of the form `<repo-id>:<doc-id> §<section> (<revision>)`" in text


def test_readme_does_not_promise_every_relevant_section():
    """F-C7: each leg is capped at K_LEG=50 before RRF."""
    text = _normalised(_readme_text())
    assert "returns every relevant section found" not in text
    assert "each leg is capped at 50 results before fusion" in text


def test_readme_documents_the_advisory_budget():
    """F-C8: `query.py:173` always admits result #1, whatever its size — a
    caller asking for 50 tokens can receive a 1488-token section."""
    text = _normalised(_readme_text())
    assert "the first result is always returned whatever its size" in text


def test_readme_describes_the_closeness_flags_as_the_code_implements_them():
    """F-C5 review fix: §7.8's kb_search row claimed the tool flags when the
    top two 'score closely on the keyword leg' — false in both directions.
    The keyword-leg rule (query.py:246, AMBIG_BM25_RATIO = 1.00, lo <= hi)
    fires only on an EXACT BM25 tie, never on merely close scores; the flag
    that does fire on genuinely close scores (mcp.py:27-45 _ambiguity_note,
    both top results hybrid and within _AMBIGUOUS_MIN_RATIO) was omitted."""
    text = _normalised(_readme_text())
    assert "when their keyword scores tie exactly" in text
    assert "score closely on the keyword leg" not in text


def test_readme_documents_doc_ids_as_tags():
    """F-C14: searchdb.py:350 indexes doc.id.lower() as a synthetic tag."""
    text = _normalised(_readme_text())
    assert "a document id is also accepted as a tag" in text


def test_readme_pins_the_publish_mode_rule():
    """Fix round 1, Minor 5: this batch replaced the "local-path hub" /
    "GitHub hub" heuristic with pubgate.decide_mode -- mode is chosen by
    whether the hub has a git remote, not by the hub's URL shape. Four
    README sites describe this; pin the new phrase, and pin the absence of
    the old one so reintroducing it at ANY of the four sites fails -- the
    positive assertion alone only covers the site that carries it."""
    text = _normalised(_readme_text())
    assert "picks direct only for a hub with no git remote" in text
    assert "local-path hub" not in text


def test_readme_pins_the_registry_mistake_guard_framing():
    """Fix round 1, Minor 5: the registry check cannot authenticate a
    publisher (the remote URL is self-asserted) -- it is a mistake guard,
    not a security boundary. Branch protection on the hub is the actual
    boundary. Pin this framing so it isn't quietly reworded back into an
    authentication claim."""
    text = _normalised(_readme_text())
    assert "mistake guard" in text


def test_readme_pins_the_exit_code_contract():
    """M11 (task 8): usage errors now exit 1, not 2 -- exit 2 means
    citation stale, and the citation-stale producers are `kb resolve`, `kb
    doctor --context`, `kb ticket lint --fail-on-stale`, and `kb mission
    lint --fail-on-stale`. There is no `kb ba lint` command.

    Release 0.25.0 fix round 1, Important 1: the table used to add "only"
    after that list, which is false -- `cli.py`'s `doctor` command exits 2
    whenever `hub_stale` is set (from `check_hub`'s `handle.stale`), with
    or without `--context`, so a stale hub-cache pull shares exit 2 with
    citation staleness. Pin the corrected prose together with the real
    command names so the table can't quietly drift back to a non-existent
    command, lose a producer `cli.py` still has, or reclaim the false
    "only"."""
    text = _normalised(_readme_text())
    assert "error — including a misconfiguration" in text
    assert (
        "`kb ticket lint --fail-on-stale`, `kb mission lint --fail-on-stale`; "
        "`kb doctor` also exits 2, with or without `--context`, when the hub "
        "cache itself is stale" in text
    )
    assert "kb ba lint" not in text
    assert "--fail-on-stale` only" not in text


def test_readme_says_usage_counts_subagents_and_never_guesses_a_price():
    """1.9.0: the Stop hook alone saw a third of a session's cost; subagents
    come from `SubagentStop` and the `Stop` sweep. A model with no price row
    is `unpriced`, never priced as its family."""
    text = _normalised(_readme_text())
    assert "subagents included (`Stop` + `SubagentStop` hooks" in text
    assert "a model with no row is reported `unpriced`, never guessed" in text
    assert "a total that contains them is a lower bound" in text


# --- 2026-10-10 review batch 1c: README matches the code -------------------


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    nxt = text.find("\n## ", start + len(heading))
    return text[start : nxt if nxt != -1 else len(text)]


def test_readme_stats_example_sits_inside_the_l2_budget():
    """B17: the old example showed L2 = 89 % of L3 -- a store that fails the
    product's own `kb build --strict`."""
    block = re.search(r"\$ kb stats\n(.*?)```", _readme_text(), re.S).group(1)
    rows = [
        line.split()
        for line in block.splitlines()
        if line and not line.startswith(("L0", "doc"))
    ]
    assert rows
    for _doc, _n, _l1, l2, l3, saving in rows:
        ratio = int(l2) / int(l3)
        assert ratio <= 0.35, (l2, l3)
        assert abs(float(saving.rstrip("%")) - (1 - ratio) * 100) <= 0.1


def test_readme_claims_no_unmeasured_saving():
    assert ">90%" not in _readme_text()
    assert "11.1%" not in _readme_text()


def test_readme_uses_one_source_folder_name():
    text = _readme_text()
    assert "kb ingest sources/" not in text
    assert "under `sources/`" not in text


def _ba_author_steps() -> int:
    skill = (
        REPO_ROOT / "src/strata_kb/templates/init/claude-skill-ba-ticket-author.md"
    ).read_text(encoding="utf-8")
    workflow = _section(skill, "## Workflow")
    return len(re.findall(r"^\d+\. \*\*", workflow, re.M))


def test_readme_ba_section_matches_the_skill():
    """F1 / F2 / F8: README said 8 steps, up to 3 rounds, local-first."""
    numbers = {9: "nine-step"}
    ba = _normalised(_section(_readme_text(), "## 12. BA repos"))
    assert _ba_author_steps() in numbers
    assert numbers[_ba_author_steps()] in ba
    assert "**Ground technical**" in ba
    assert "one round by default" in ba
    assert "agent-reported" in ba
    assert "hub's `<repo>-code` first" in ba
    assert "local `--kb-dir` first" not in ba
    assert "up to 3 rounds or until" not in ba


def test_readme_dev_section_separates_machine_and_prompt_rules():
    """G3 / G4: TDD was "Enforced throughout"; the design "stays in chat"."""
    dev = _normalised(_section(_readme_text(), "## 13. Dev repos"))
    assert "Enforced throughout" not in dev
    assert "Machine-enforced" in dev
    assert "Prompt-only" in dev
    assert "the design stays in chat" not in dev
    assert "(architectural tickets only)" not in dev
    assert "`rel.<name>`" in dev and "not shipped" in dev.lower()


def test_readme_command_table_lists_every_top_level_command():
    from strata_kb.cli import app

    names = {
        c.name or c.callback.__name__.replace("_", "-")
        for c in app.registered_commands
        if not c.hidden
    } | {g.name for g in app.registered_groups if not g.hidden}
    table = _section(_readme_text(), "## 6. Command reference")
    missing = sorted(n for n in names if f"`kb {n}" not in table)
    assert not missing, missing


def test_readme_documents_the_usage_and_ticket_subcommands():
    table = _normalised(_section(_readme_text(), "## 6. Command reference"))
    for sub in (
        "kb ticket check",
        "kb ticket export",
        "kb ticket fetch",
        "kb usage ingest-transcript",
        "kb usage note",
        "kb usage report",
    ):
        assert f"`{sub}" in table, sub


def test_readme_never_tells_users_to_commit_a_hub_credential():
    """§5.2 #8: config.yaml is committed; a token in `hub:` is in history."""
    text = _normalised(_readme_text())
    assert "never put a token in `hub:`" in text
    assert "whose `.kb/config.yaml` `hub:` URL carries a credential" not in text


def test_no_doc_claims_ci_publish_stays_silent_about_a_merge():
    """cipublish.py echoes `merged: <pr_url>` when intake reports merged;
    only the CI step summary says `hub PR: <url>`."""
    from strata_kb.initcmd import read_template

    texts = [
        _readme_text(),
        (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8"),
        read_template("QUICKSTART-dev.md"),
        read_template("QUICKSTART-hub.md"),
        *(p.read_text(encoding="utf-8") for p in (REPO_ROOT / "docs/src").glob("*.md")),
    ]
    for text in texts:
        flat = _normalised(text)
        assert "`kb ci-publish` does not report it" not in flat
        assert "`kb ci-publish` không báo" not in flat
        assert "`kb ci-publish` không in gì" not in flat
    assert 'print "merged"' in _normalised(_readme_text())


_MCP_TOOLS = (
    "kb_search",
    "kb_get_section",
    "kb_context_new",
    "kb_resolve",
    "kb_ticket_lint",
    "kb_ticket_check",
    "kb_ticket_stale",
    "kb_mission_lint",
    "kb_ticket_fetch",
    "kb_question_ask",
    "kb_question_list",
    "kb_question_answer",
    "kb_mission_next",
    "kb_doctor_hub",
)


def test_readme_lists_all_fourteen_mcp_tools():
    text = _readme_text()
    flat = _normalised(text)
    assert "### The fourteen MCP tools" in text
    assert "eleven MCP tools" not in flat.lower()
    rows = [line for line in text.splitlines() if line.startswith("| `kb_")]
    assert sorted(line.split("`")[1] for line in rows) == sorted(_MCP_TOOLS)


def test_no_doc_still_counts_eleven_mcp_tools():
    for path in (REPO_ROOT / "docs/src").glob("*.md"):
        flat = _normalised(path.read_text(encoding="utf-8")).lower()
        assert "eleven mcp tools" not in flat, path.name
        assert "mười một mcp tool" not in flat, path.name
    for path in (REPO_ROOT / "docs/src").glob("architecture.*.md"):
        text = path.read_text(encoding="utf-8")
        for name in _MCP_TOOLS:
            assert f"`{name}`" in text, (path.name, name)


def test_readme_documents_ticket_qa():
    text = _normalised(_readme_text())
    assert "### Ticket Q&A" in text
    assert "`<hub root>/.kb-qa/qa.db`" in text
    assert "**Never commit `.kb-qa/`**" in text
    assert "All three, the list included, work only against the **hub itself**" in text
    assert "Q&A needs the shared hub server — point MCP at it (kb mcp-setup)" in text
    assert "Any caller the hub authenticates" in text
    assert "tracking, not authentication" in text
    assert "at most 50 open questions per ticket" in text
    assert "*waiting* (answered, but the answer changes the ticket" in text
    assert "created, and git-excluded, on the first Q&A call" in text
    assert "the stdio server run inside the hub's own checkout" in text
    assert "a hub URL read through a local cache clone" in text
    assert "(`--kb <hub>/.kb`" in text
    assert "Any other target is refused" in text
    assert "`/ui/questions`" in text
    assert "`/ui/questions/ticket?repo=<repo-id>&ticket=<id>`" in text
    assert "**the BA must re-tick them**" in text
    assert "Trigger `question`" in text
    assert "It never commits, pushes or publishes" in text
    assert "`BA-Q: none | open Q<ids> | waiting Q<ids>`" in text
    assert "`BA-Q: unknown (Q&A unavailable)`" in text
    assert "`/dev-sa <question>`" in text
    assert "`/ba-answer-questions`" in text
    assert "accepts a hub-asked `Q<id>`" in text


def test_readme_does_not_refuse_the_hubs_own_stdio_server():
    """The scaffolded hub stdio MCP uses `hub: "."`, a local checkout, so the
    Q&A tools work there; only a cache clone of a hub URL is refused."""
    text = _normalised(_readme_text())
    assert "a stdio hub, or" not in text
    assert "stdio hub" not in text


def test_no_doc_says_q_and_a_is_created_on_the_first_question():
    from strata_kb.initcmd import read_template

    texts = [
        _readme_text(),
        (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8"),
        read_template("QUICKSTART-hub.md"),
        *(p.read_text(encoding="utf-8") for p in (REPO_ROOT / "docs/src").glob("*.md")),
    ]
    for text in texts:
        flat = _normalised(text)
        assert "created on the first question" not in flat
        assert "when the first question is written" not in flat
        assert "meaning MCP pointed at the hub's HTTP endpoint" not in flat


def test_guides_document_ticket_qa_in_both_languages():
    for lang in ("en", "vi"):
        ba = (REPO_ROOT / f"docs/src/guide-ba.{lang}.md").read_text(encoding="utf-8")
        dev = (REPO_ROOT / f"docs/src/guide-dev.{lang}.md").read_text(encoding="utf-8")
        hub = (REPO_ROOT / f"docs/src/guide-hub-child.{lang}.md").read_text(
            encoding="utf-8"
        )
        assert "## 3.10" in ba and "/ba-answer-questions" in ba, lang
        assert "Trigger `question`" in _normalised(ba), lang
        assert "## 4.6" in dev and "/dev-sa" in dev, lang
        assert "BA-Q: none | open Q<ids> | waiting Q<ids>" in dev, lang
        assert "`.kb-qa/qa.db`" in hub or "`.kb-qa/`" in hub, lang
        for text in (ba, dev, hub):
            assert "Q&A needs the shared hub server" in _normalised(text), lang


def test_version_is_1_29_0_everywhere():
    import tomllib

    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == "1.29.0"
    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    own = [p for p in lock["package"] if p["name"] == "strata-kb"]
    assert [p["version"] for p in own] == ["1.29.0"]
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    first = changelog.split("\n## ", 2)[1]
    assert first.startswith("1.29.0 — 2026-10-16")
    assert "guide PDFs" in first and "were not rebuilt" in first


def test_docs_describe_structural_coverage():
    """1.28.0: README and the four guides name the new section kinds, the
    `code` extra, the coverage statuses and the jobs-never-complete rule."""
    from strata_kb.codeingest.extractors.routes import ROUTE_FRAMEWORKS

    docs = {
        "README.md": REPO_ROOT / "README.md",
        **{
            f"guide-{g}.{lang}.md": REPO_ROOT / "docs" / "src" / f"guide-{g}.{lang}.md"
            for g in ("dev", "ba")
            for lang in ("en", "vi")
        },
    }
    for name, path in docs.items():
        text = _normalised(path.read_text(encoding="utf-8"))
        # the BA guides cite the kinds as `route.*`; only README and the Dev
        # guides carry the section tables
        kinds = (
            ()
            if name.startswith("guide-ba")
            else (
                "`route.<slug>`",
                "`page.<slug>`",
                "`job.<slug>`",
                "`sym.<slug>`",
                "`struct.files.<dir>`",
            )
        )
        for needle in (
            *kinds,
            "`struct.coverage`",
            "`complete`",
            "`partial`",
            "`not scanned`",
            "strata-kb[code]",
            "jobs outside framework schedulers are not detectable",
        ):
            assert needle in text, (name, needle)
    for name in ("README.md", "guide-dev.en.md", "guide-dev.vi.md"):
        text = docs[name].read_text(encoding="utf-8")
        for framework in ROUTE_FRAMEWORKS:
            assert framework in text, (name, framework)


def test_docs_get_the_publish_flow_and_new_forms_right():
    """Fix round 1: `-code` is re-published by `kb publish` (the workflow
    publishes only on a `kb-publish/*` tag), and a new file is its own
    `Files:` entry, never `<thing> in <path>`."""
    guides = ("dev", "ba")
    texts = {
        "README.md": REPO_ROOT / "README.md",
        **{
            f"guide-{g}.{lang}.md": REPO_ROOT / "docs" / "src" / f"guide-{g}.{lang}.md"
            for g in guides
            for lang in ("en", "vi")
        },
    }
    changelog = _normalised((REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
    entry = next(e for e in changelog.split(" ## ") if e.startswith("1.28.0 "))
    upgrade = entry.split("**Upgrade.**")[1].split(" ## ")[0]
    assert "or the next push" not in upgrade
    assert "with `kb publish`" in upgrade
    for name, path in texts.items():
        text = _normalised(path.read_text(encoding="utf-8"))
        for stale in (
            "or push to the default branch",
            "(hoặc push lên nhánh mặc định)",
            "on every push to the default branch",
            "ở mỗi lần push lên nhánh mặc định",
            "<thing> in <path> [NEW: D<n>]); absent",
        ):
            assert stale not in text, (name, stale)
        assert "QUICKSTART-ba.md" not in text, name
    for name in (
        "README.md",
        "guide-dev.en.md",
        "guide-dev.vi.md",
        "guide-ba.en.md",
        "guide-ba.vi.md",
    ):
        text = _normalised(texts[name].read_text(encoding="utf-8"))
        assert "`<path> [NEW: D<n>]`" in text, name
