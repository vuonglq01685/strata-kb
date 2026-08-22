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
