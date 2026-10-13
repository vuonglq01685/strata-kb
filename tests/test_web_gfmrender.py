"""gfmrender — GitHub-like rendering of BA mission and ticket markdown."""

from strata_kb.web.gfmrender import has_mermaid, render


def test_mermaid_fence_becomes_an_escaped_mermaid_block():
    out = render("```mermaid\nflowchart TD\n  A-->B\n```\n")
    assert '<pre class="mermaid">flowchart TD\n  A--&gt;B\n</pre>' in out
    assert has_mermaid(out)


def test_task_list_items_render_as_disabled_checkboxes():
    out = render("- [ ] open\n- [x] done\n")
    assert '<li class="task"><input type="checkbox" disabled> open</li>' in out
    assert '<input type="checkbox" checked disabled> done' in out


def test_tables_strikethrough_and_highlighted_code():
    out = render("| a | b |\n|---|---|\n| 1 | ~~2~~ |\n\n```yaml\nk: v\n```\n")
    assert "<th>a</th>" in out and "<s>2</s>" in out
    assert 'class="language-yaml"' in out and "hl-" in out
    assert not has_mermaid(out)


def test_raw_html_comments_and_script_links_never_reach_the_page():
    out = render(
        "<!-- guidance -->\n<script>alert(1)</script>\n\n"
        "text <b>x</b> [l](javascript:alert(1))\n"
    )
    assert "guidance" not in out and "<script" not in out and "<b>" not in out
    assert 'href="javascript' not in out
