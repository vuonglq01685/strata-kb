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
