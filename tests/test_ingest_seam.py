"""Pin tests-gate/fixtures/pending-kb/ to the REAL output of scaffold_doc().

The e2e journey cannot run `kb ingest` (it needs docling ~2GB + a copyrighted
PDF), so it starts from a fixture that simulates ingest's output. This test is
what keeps that fixture from drifting away from the truth: regenerate into tmp,
compare against the committed tree.

WHAT RED MEANS: ingest's output has changed. Do not fix the test. Re-run
`python scripts/gen_e2e_fixture.py`, read the diff carefully, then commit the
new fixture — and check whether tests-gate/e2e/test_journey.py is still correct
against the new shape.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO = Path(__file__).parent.parent
FIXTURE = REPO / "tests-gate" / "fixtures" / "pending-kb"

sys.path.insert(0, str(REPO / "scripts"))
from gen_e2e_fixture import generate  # noqa: E402


def _tree(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


def test_fixture_file_tree_matches_scaffold_output(tmp_path):
    generate(tmp_path / ".kb")

    assert _tree(tmp_path / ".kb") == _tree(FIXTURE)


def test_fixture_markdown_matches_scaffold_output(tmp_path):
    generate(tmp_path / ".kb")

    # Do not hardcode the file names: scaffold_doc().chapter_stem() slugifies the
    # title of the chapter's first unit, so the name is ch1-airspace-records.*.
    # Walk the real tree instead of guessing — the set of names is already pinned
    # by test_fixture_file_tree_matches_scaffold_output.
    names = sorted(p.name for p in (FIXTURE / "demo-doc").glob("*.md"))
    assert names, "the fixture has no .md files"

    for name in names:
        fresh = (tmp_path / ".kb" / "demo-doc" / name).read_text(encoding="utf-8")
        committed = (FIXTURE / "demo-doc" / name).read_text(encoding="utf-8")
        assert fresh == committed, f"{name} has drifted from scaffold_doc()'s output"


def test_fixture_manifest_matches_scaffold_output(tmp_path):
    generate(tmp_path / ".kb")

    fresh = yaml.safe_load(
        (tmp_path / ".kb" / "demo-doc" / "_manifest.yaml").read_text(encoding="utf-8")
    )
    committed = yaml.safe_load(
        (FIXTURE / "demo-doc" / "_manifest.yaml").read_text(encoding="utf-8")
    )
    # scaffold_doc sets ingested=date.today() → it drifts every day, not a signal.
    fresh.pop("ingested", None)
    committed.pop("ingested", None)

    assert fresh == committed


def test_fixture_index_matches_scaffold_output(tmp_path):
    generate(tmp_path / ".kb")

    fresh = yaml.safe_load((tmp_path / ".kb" / "index.yaml").read_text(encoding="utf-8"))
    committed = yaml.safe_load((FIXTURE / "index.yaml").read_text(encoding="utf-8"))
    # No field here drifts with the date/time (unlike ingested in _manifest.yaml)
    # — pop nothing, compare the whole document.

    assert fresh == committed, "index.yaml has drifted from scaffold_doc()'s output"
