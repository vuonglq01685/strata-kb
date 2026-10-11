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


def test_readme_pins_the_path_scoped_auto_merge_constraint():
    text = _normalised(_readme_text())
    # The real gate-integrity teeth: `kb ci-publish` opens ONE PR per push
    # (keyed by repo id, not by document -- intake.py:302-330), so a
    # whole-PR or whole-repo auto-merge rule for "-code" would also
    # auto-merge any "-svc" amend riding along in that same PR.
    assert "opens one hub PR per push, not per document" in text
    assert "path-scoped to `.kb/<repo_id>-code/**`" in text
    assert "never a whole-PR or whole-repo rule" in text


def test_readme_pins_why_code_and_svc_cannot_share_one_document():
    text = _normalised(_readme_text())
    assert "One document can't carry both publish policies at once." in text


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
