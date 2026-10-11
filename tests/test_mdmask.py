"""mdmask — the Markdown masking primitives lintcore, ticket, kbcontext and
prlint share."""

from strata_kb import lintcore, mdmask


def test_lintcore_names_are_the_mdmask_objects():
    for name in (
        "FENCE_RE",
        "HTML_COMMENT_RE",
        "visible_body",
        "_visible_text",
        "_blank_invisible",
    ):
        assert getattr(lintcore, name) is getattr(mdmask, name)


def test_blank_invisible_keeps_line_count_and_blanks_comment_then_fence():
    text = "a\n<!-- x\n``` -->\nb\n```py\ncode\n```\nc\n"
    out = mdmask._blank_invisible(text)
    assert out.count("\n") == text.count("\n")
    assert out.splitlines()[0] == "a"
    assert "b" in out and "c" in out
    assert "code" not in out and "x" not in out


def test_visible_body_strips_comments_and_outer_space():
    assert mdmask.visible_body("  <!-- hint -->\n real \n") == "real"
