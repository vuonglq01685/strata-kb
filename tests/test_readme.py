"""Doc pins: the README is a short front door; the facts live in the role
guides (`docs/src/guide-<kind>.{en,vi}.md`) and the architecture document.

Each test pins a load-bearing claim as a distinctive multi-word phrase,
matched against whitespace-normalised text so a re-wrap of the prose does not
itself break the test, and points at the file that carries the fact.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _readme_text() -> str:
    return (REPO_ROOT / "README.md").read_text(encoding="utf-8")


def _normalised(text: str) -> str:
    return " ".join(text.split())


def _doc(name: str) -> str:
    """Whitespace-normalised text of `docs/src/<name>`."""
    return _normalised((REPO_ROOT / "docs" / "src" / name).read_text(encoding="utf-8"))


def _doc_paths() -> dict[str, Path]:
    paths = {"README.md": REPO_ROOT / "README.md"}
    for path in sorted((REPO_ROOT / "docs" / "src").glob("*.md")):
        paths[path.name] = path
    return paths


def _all_docs() -> dict[str, str]:
    """README and every Markdown source under docs/src, normalised."""
    docs = {"README.md": _normalised(_readme_text())}
    for path in sorted((REPO_ROOT / "docs" / "src").glob("*.md")):
        docs[path.name] = _normalised(path.read_text(encoding="utf-8"))
    return docs


def test_guides_pin_the_per_repo_auto_merge_switch():
    # `kb ci-publish` opens ONE PR per push (keyed by repo id, not by
    # document), so the per-repo auto-merge switch merges the whole PR and the
    # "-svc" review has to happen locally, before publish.
    dev = _doc("guide-dev.en.md")
    assert "opens **one** hub pull request per push" in dev
    assert "per-repo switch on the hub's Registry page" in dev
    assert "With the switch on, the hub merges the **whole**" in dev
    assert "`/dev-code-seed` step 4" in dev
    assert "It merges the **whole** PR, including any `-svc` content" in _doc(
        "guide-hub.en.md"
    )
    # the old hub-side, path-scoped rule is gone everywhere
    for name, text in _all_docs().items():
        assert "path-scoped" not in text, name


def test_hub_guide_documents_hub_accounts_and_the_registry_page():
    text = _doc("guide-hub.en.md")
    assert "sign in with the token" not in _all_docs()["README.md"]
    assert "`<hub>/.kb-auth/` (`users.db` and `session.key`)" in text
    assert "`STRATA_KB_BOOTSTRAP_ADMIN=<name>`" in text
    assert "`STRATA_KB_BOOTSTRAP_PASSWORD_HASH='<hash>'`" in text
    assert "only `admin` sees and uses the Registry page" in text
    assert "`Contents: Read and write` and `Pull requests: Read and write`" in text


def test_architecture_pins_why_code_and_svc_cannot_share_one_document():
    text = _doc("architecture.en.md")
    assert "They cannot share one document for three independent reasons" in text
    assert "`-svc` needs human review" in text


def test_child_guide_shows_the_real_query_output():
    """Reviewer C F-C13: the docs showed `score=17.19` and an unqualified
    `[arinc-424 §5.129 ...]`. `_citation` (query.py:47-49) prefixes `repo_id:`
    unconditionally — there is no 'only on ambiguity' branch — and `score=` was
    removed in the hybrid rework."""
    for lang in ("en", "vi"):
        text = _doc(f"guide-child.{lang}.md")
        assert (
            "[<repo-id>:<doc-id> §<section> (<revision>)] match=<mode> ~<n>tk" in text
        ), lang
    for name, text in _all_docs().items():
        assert "score=17.19" not in text, name


def test_docs_do_not_promise_every_relevant_section():
    """F-C7: each leg is capped at K_LEG=50 before RRF."""
    for name, text in _all_docs().items():
        assert "returns every relevant section found" not in text, name
    assert "each leg is capped at 50 results before fusion" in _doc(
        "architecture.en.md"
    ).replace("Each leg", "each leg")
    assert "Each leg is capped at 50 results before fusion" in _doc("guide-hub.en.md")


def test_docs_document_the_advisory_budget():
    """F-C8: `query.py:173` always admits result #1, whatever its size — a
    caller asking for 50 tokens can receive a 1488-token section."""
    assert "the first result is always returned whatever its size" in _doc(
        "guide-child.en.md"
    )
    assert "the first result is always returned whole" in _doc("architecture.en.md")


def test_hub_guide_describes_the_closeness_flags_as_the_code_implements_them():
    """F-C5 review fix: the kb_search row claimed the tool flags when the
    top two 'score closely on the keyword leg' — false in both directions.
    The keyword-leg rule (query.py:246, AMBIG_BM25_RATIO = 1.00, lo <= hi)
    fires only on an EXACT BM25 tie, never on merely close scores; the flag
    that does fire on genuinely close scores (mcp.py:27-45 _ambiguity_note,
    both top results hybrid and within _AMBIGUOUS_MIN_RATIO) was omitted."""
    for name, text in _all_docs().items():
        assert "score closely on the keyword leg" not in text, name
    assert "when their keyword scores tie exactly" in _doc("guide-hub.en.md")


def test_docs_document_doc_ids_as_tags():
    """F-C14: searchdb.py:350 indexes doc.id.lower() as a synthetic tag."""
    assert "`--tags` also accepts a document id" in _doc("guide-child.en.md")
    assert "A document id is indexed as a synthetic tag" in _doc("architecture.en.md")


def test_docs_pin_the_publish_mode_rule():
    """Fix round 1, Minor 5: this batch replaced the "local-path hub" /
    "GitHub hub" heuristic with pubgate.decide_mode -- mode is chosen by
    whether the hub has a git remote, not by the hub's URL shape. Pin the new
    phrase, and pin the absence of the old one in every doc so reintroducing
    it anywhere fails -- the positive assertion alone only covers the file
    that carries it."""
    assert "picks direct only for a hub with no git remote" in _doc("guide-child.en.md")
    for name, text in _all_docs().items():
        assert "local-path hub" not in text, name


def test_docs_pin_the_registry_mistake_guard_framing():
    """Fix round 1, Minor 5: the registry check cannot authenticate a
    publisher (the remote URL is self-asserted) -- it is a mistake guard,
    not a security boundary. Branch protection on the hub is the actual
    boundary. Pin this framing so it isn't quietly reworded back into an
    authentication claim."""
    assert "mistake guard" in _doc("architecture.en.md")
    assert "The registry cannot authenticate a git publisher" in _doc("guide-hub.en.md")


def test_hub_guide_pins_the_exit_code_contract():
    """Exit 1 is an error or misconfiguration; exit 2 is a stale citation
    (for `kb doctor`, a stale hub cache) or a CLI usage error. The
    citation-stale producers are `kb resolve`, `kb doctor --context`,
    `kb ticket lint --fail-on-stale`, and `kb mission lint --fail-on-stale`.
    There is no `kb ba lint` command.

    Release 0.25.0 fix round 1, Important 1: the table used to add "only"
    after that list, which is false -- `cli.py`'s `doctor` command exits 2
    whenever `hub_stale` is set (from `check_hub`'s `handle.stale`), with
    or without `--context`, so a stale hub-cache pull shares exit 2 with
    citation staleness. Pin the corrected prose together with the real
    command names so the text can't quietly drift back to a non-existent
    command, lose a producer `cli.py` still has, or reclaim the false
    "only"."""
    text = _doc("guide-hub.en.md")
    assert "`1` error or misconfiguration" in text
    assert (
        "Exit `2` for a stale citation comes from `kb resolve`, `kb doctor "
        "--context`, `kb ticket lint --fail-on-stale` and `kb mission lint "
        "--fail-on-stale`; `kb doctor` also exits `2`, with or without "
        "`--context`, when the hub cache itself is stale" in text
    )
    for name, doc in _all_docs().items():
        assert "kb ba lint" not in doc, name
        assert "--fail-on-stale` only" not in doc, name


def test_guides_say_usage_counts_subagents_and_never_guess_a_price():
    """1.9.0: the Stop hook alone saw a third of a session's cost; subagents
    come from `SubagentStop` and the `Stop` sweep. A model with no price row
    is `unpriced`, never priced as its family."""
    for guide in ("ba", "dev"):
        text = _doc(f"guide-{guide}.en.md")
        assert (
            "The `Stop` and `SubagentStop` hooks run `kb usage ingest-transcript"
            in text
        )
        assert "A model with no row is reported `unpriced`, never guessed" in text
        assert "so a total that contains them is a lower bound" in text
        # Backfilling a session that is still running freezes a partial count.
        assert "Re-ingesting an ended transcript is safe" in text
        assert (
            "a call still streaming would be stored with a partial output "
            "count, and a stored row never changes"
        ) in text
        vi = _doc(f"guide-{guide}.vi.md")
        assert "Ingest lại một transcript đã kết thúc là an toàn" in vi
        assert (
            "số token đầu ra chưa đầy đủ, và một dòng đã lưu không bao giờ thay đổi"
            in vi
        )


# --- 2026-10-10 review batch 1c: README matches the code -------------------


COMMAND_TABLE_HEADING = "## Command reference"


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    nxt = text.find("\n## ", start + len(heading))
    return text[start : nxt if nxt != -1 else len(text)]


def test_docs_stats_examples_sit_inside_the_l2_budget():
    """B17: the old example showed L2 = 89 % of L3 -- a store that fails the
    product's own `kb build --strict`. No doc shows `kb stats` output today;
    if one is added it must stay inside the budget. The README's stated L2
    figure is pinned so the test cannot pass vacuously."""
    assert "~20–30% of the original" in _readme_text()
    for name, path in _doc_paths().items():
        for block in re.findall(
            r"\$ kb stats\n(.*?)```", path.read_text("utf-8"), re.S
        ):
            rows = [
                line.split()
                for line in block.splitlines()
                if line and not line.startswith(("L0", "doc"))
            ]
            assert rows, name
            for _doc_id, _n, _l1, l2, l3, saving in rows:
                ratio = int(l2) / int(l3)
                assert ratio <= 0.35, (name, l2, l3)
                assert abs(float(saving.rstrip("%")) - (1 - ratio) * 100) <= 0.1


def test_docs_claim_no_unmeasured_saving():
    for name, text in _all_docs().items():
        assert ">90%" not in text, name
        assert "11.1%" not in text, name


def test_docs_use_one_source_folder_name():
    for name, text in _all_docs().items():
        assert "kb ingest sources/" not in text, name
        assert "under `sources/`" not in text, name


def _ba_author_steps() -> int:
    skill = (
        REPO_ROOT / "src/strata_kb/templates/init/claude-skill-ba-ticket-author.md"
    ).read_text(encoding="utf-8")
    workflow = _section(skill, "## Workflow")
    return len(re.findall(r"^\d+\. \*\*", workflow, re.M))


def test_ba_guide_matches_the_ticket_author_skill():
    """F1 / F2 / F8: the docs said 8 steps, up to 3 rounds, local-first."""
    numbers = {9: "nine-step"}
    for lang in ("en", "vi"):
        ba = _doc(f"guide-ba.{lang}.md")
        assert _ba_author_steps() in numbers
        assert "7 Ground technical" in ba, lang
        assert "local `--kb-dir` first" not in ba, lang
        assert "up to 3 rounds or until" not in ba, lang
    ba = _doc("guide-ba.en.md")
    assert numbers[_ba_author_steps()] in ba
    assert "one round by default" in ba
    assert "agent-reported" in ba
    assert "checks only that `## Review record` has the right shape" in ba


def test_dev_guide_separates_machine_and_prompt_rules():
    """G3 / G4: TDD was "Enforced throughout"; the design "stays in chat"."""
    dev = _doc("guide-dev.en.md")
    section = dev[dev.index("## 6.4 What is enforced, and what is only asked") :]
    section = section[: section.index("## 6.5")]
    assert "Enforced throughout" not in dev
    assert "| Rule | Enforced by |" in section
    assert "is prompt discipline that nothing in `kb` measures" in section
    assert "the design stays in chat" not in dev
    assert "(architectural tickets only)" not in dev


def test_readme_command_table_lists_every_top_level_command():
    from strata_kb.cli import app

    names = {
        c.name or c.callback.__name__.replace("_", "-")
        for c in app.registered_commands
        if not c.hidden
    } | {g.name for g in app.registered_groups if not g.hidden}
    table = _section(_readme_text(), COMMAND_TABLE_HEADING)
    missing = sorted(n for n in names if f"`kb {n}" not in table)
    assert not missing, missing


def test_readme_documents_the_usage_and_ticket_subcommands():
    table = _normalised(_section(_readme_text(), COMMAND_TABLE_HEADING))
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
    # the guides that set `hub:` repeat the rule
    for guide in ("child", "ba", "dev"):
        assert "Never put a token in `hub:`" in _doc(f"guide-{guide}.en.md"), guide


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
    assert 'print "merged"' in _doc("guide-hub.en.md")


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


def test_hub_guide_lists_all_fourteen_mcp_tools():
    for lang in ("en", "vi"):
        text = (REPO_ROOT / "docs/src" / f"guide-hub.{lang}.md").read_text(
            encoding="utf-8"
        )
        assert "eleven MCP tools" not in _normalised(text).lower(), lang
        rows = [line for line in text.splitlines() if line.startswith("| `kb_")]
        assert sorted(line.split("`")[1] for line in rows) == sorted(_MCP_TOOLS), lang


def test_no_doc_still_counts_eleven_mcp_tools():
    for path in (REPO_ROOT / "docs/src").glob("*.md"):
        flat = _normalised(path.read_text(encoding="utf-8")).lower()
        assert "eleven mcp tools" not in flat, path.name
        assert "mười một mcp tool" not in flat, path.name
    for path in (REPO_ROOT / "docs/src").glob("architecture.*.md"):
        text = path.read_text(encoding="utf-8")
        for name in _MCP_TOOLS:
            assert f"`{name}`" in text, (path.name, name)


def test_guides_document_ticket_qa_rules():
    """The hub guide owns the storage and rules; the BA and Dev guides and the
    skills own their side."""
    from strata_kb.initcmd import read_template

    hub = _doc("guide-hub.en.md")
    assert "`<hub root>/.kb-qa/qa.db`" in hub
    assert "**Never commit `.kb-qa/`**" in hub
    assert "The three tools work only against the hub itself" in hub
    assert "Q&A needs the shared hub server — point MCP at it (kb mcp-setup)" in hub
    assert "Any caller the hub authenticates" in hub
    assert "tracking, not authentication" in hub
    assert "at most 50 open questions per ticket" in hub
    assert "stays *waiting*" in hub
    assert "created and git-excluded on the first Q&A call" in hub
    assert "the stdio server run inside the hub's own checkout" in hub
    assert "a hub URL read through a local cache clone" in hub
    assert "(`--kb <hub>/.kb`" in hub
    assert "Any other target is refused" in hub
    assert "`/ui/questions`" in hub
    assert "`/ui/questions/ticket?repo=<repo-id>&ticket=<id>`" in hub
    # the runner's read-only poll of the Q&A store
    assert "polls `GET /api/questions` with the same bearer token" in hub
    assert "`status` (`open` by default, `waiting`, `answered` or `all`" in hub
    assert "`GET /api/questions`" in _doc("guide-hub.vi.md")
    ba = _doc("guide-ba.en.md")
    assert "**Re-tick the Definition of Ready.**" in ba
    assert "Trigger `question`" in ba
    assert "The skill never commits, pushes or publishes" in ba
    assert "`/ba-answer-questions`" in ba
    dev = _doc("guide-dev.en.md")
    assert "`BA-Q: none | open Q<ids> | waiting Q<ids>`" in dev
    assert "`/dev-sa <question>`" in dev
    # skill internals the guides leave to the skills
    skill = _normalised(read_template("claude-skill-dev-implement-ticket.md"))
    assert "`BA-Q: unknown (Q&A unavailable)`" in skill
    rubric = _normalised(read_template("pr-review-rubric.md"))
    assert "`Q<id>` asked through hub Q&A, never resolved by guessing" in rubric


def test_docs_do_not_refuse_the_hubs_own_stdio_server():
    """The scaffolded hub stdio MCP uses `hub: "."`, a local checkout, so the
    Q&A tools work there; only a cache clone of a hub URL is refused."""
    for name, text in _all_docs().items():
        assert "a stdio hub, or" not in text, name
        assert "stdio hub" not in text, name


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
        hub = (REPO_ROOT / f"docs/src/guide-hub.{lang}.md").read_text(encoding="utf-8")
        assert "## 3.6" in ba and "/ba-answer-questions" in ba, lang
        assert "Trigger `question`" in _normalised(ba), lang
        assert "## 3.3" in dev and "/dev-sa" in dev, lang
        assert "BA-Q: none | open Q<ids> | waiting Q<ids>" in dev, lang
        assert "`.kb-qa/qa.db`" in hub or "`.kb-qa/`" in hub, lang
        for text in (ba, dev, hub):
            assert "Q&A needs the shared hub server" in _normalised(text), lang


def test_version_is_1_35_0_everywhere():
    import tomllib

    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == "1.34.5"
    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    own = [p for p in lock["package"] if p["name"] == "strata-kb"]
    assert [p["version"] for p in own] == ["1.34.5"]
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    first = changelog.split("\n## ", 2)[1]
    assert first.startswith("1.34.5 — 2026-11-05")


def test_docs_describe_structural_coverage():
    """The BA and Dev guides name the section kinds, the `code` extra, the
    coverage statuses and the jobs-never-complete rule (the README only
    installs the extra)."""
    from strata_kb.codeingest.extractors.routes import ROUTE_FRAMEWORKS

    assert "strata-kb[code]" in _readme_text()
    docs = {
        f"guide-{g}.{lang}.md": REPO_ROOT / "docs" / "src" / f"guide-{g}.{lang}.md"
        for g in ("dev", "ba")
        for lang in ("en", "vi")
    }
    for name, path in docs.items():
        text = _normalised(path.read_text(encoding="utf-8"))
        # the BA guides cite the kinds as `route.*`; only the Dev guides carry
        # the section tables
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
    for name in ("guide-dev.en.md", "guide-dev.vi.md"):
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
        "guide-dev.en.md",
        "guide-dev.vi.md",
        "guide-ba.en.md",
        "guide-ba.vi.md",
    ):
        text = _normalised(texts[name].read_text(encoding="utf-8"))
        assert "`<path> [NEW: D<n>]`" in text, name


def test_docs_describe_full_auto_mode():
    """The README keeps the security pointer; the QUICKSTARTs and the BA and
    Dev guides carry the note and the facts a runner's owner must set up."""
    readme = _normalised(_readme_text())
    for phrase in (
        "with the rights of your `gh` login",
        "branch protection on `main`",
    ):
        assert phrase in readme, phrase
    for g in ("ba", "dev"):
        guide = _doc(f"guide-{g}.en.md")
        for phrase in (
            "branch protection on `main`",
            "include administrators",
            "required status check",
            "AUTO-RESULT: done",
            "`failed command-denied <command>`",
            "`auto_merge: true`",
            "`STRATA_KB_HUB_URL` and `STRATA_KB_HTTP_TOKEN`",
        ):
            assert phrase in guide, (g, phrase)
    init = REPO_ROOT / "src" / "strata_kb" / "templates" / "init"
    for name in ("QUICKSTART-ba.md", "QUICKSTART-dev.md"):
        text = _normalised((init / name).read_text(encoding="utf-8"))
        assert "left it alone" not in text, name
        assert "## Full-auto mode (optional)" in text, name
        assert "branch protection on `main`" in text, name
    for g in ("ba", "dev"):
        for lang in ("en", "vi"):
            guide = _normalised(
                (REPO_ROOT / f"docs/src/guide-{g}.{lang}.md").read_text(
                    encoding="utf-8"
                )
            )
            assert "kb auto run" in guide, (g, lang)
            assert "branch protection" in guide, (g, lang)


def test_guides_and_changelog_pin_the_rerunnable_cloud_switch():
    for text in (
        _doc("guide-ba.en.md"),
        _doc("guide-dev.en.md"),
        _normalised((REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")),
    ):
        assert "`/kb-auto run` is re-runnable" in text
        assert "closed and deleted on GitHub by hand" in text
        assert "git branch -D auto/switch" not in text


def test_child_guides_document_the_l3_ai_fix():
    for lang in ("en", "vi"):
        flat = _doc(f"guide-child.{lang}.md")
        assert "kb l3 fix apply" in flat, lang
        assert "_l3fix.yaml" in flat, lang
        assert "kb l3 lint" in flat, lang
        assert "kb l3 fix on" in flat, lang
