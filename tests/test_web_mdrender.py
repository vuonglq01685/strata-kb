# tests/test_web_mdrender.py
from strata_kb.web.mdrender import render


def test_heading_levels():
    assert render("## 5.3 Restrictive Airspace") == "<h2>5.3 Restrictive Airspace</h2>"
    assert render("### Sub") == "<h3>Sub</h3>"


def test_paragraph_and_escape():
    out = render("Length <1> char & alpha.")
    assert out == "<p>Length &lt;1&gt; char &amp; alpha.</p>"


def test_script_is_escaped_not_executed():
    out = render("<script>alert(1)</script>")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_pipe_table_header_and_cells_verbatim():
    md = "| Code | Meaning |\n|---|---|\n| P | Prohibited |\n| R | Restricted |"
    out = render(md)
    assert "<table>" in out and "</table>" in out
    assert "<th>Code</th><th>Meaning</th>" in out
    assert "<td>P</td><td>Prohibited</td>" in out
    assert "<td>R</td><td>Restricted</td>" in out


def test_table_cell_characters_preserved_exactly():
    # cell content must survive character-for-character (after HTML escaping)
    md = "| Field | Value |\n|---|---|\n| SEC CODE  | 1 alpha <A-Z> |"
    out = render(md)
    assert "<td>SEC CODE</td>" in out          # strip() around cells is allowed
    assert "<td>1 alpha &lt;A-Z&gt;</td>" in out


def test_table_without_separator_has_no_header():
    md = "| a | b |\n| c | d |"
    out = render(md)
    assert "<th>" not in out
    assert "<td>a</td><td>b</td>" in out


def test_mixed_document():
    md = "## 1.1 Airspace\n\nIntro text.\n\n| K | V |\n|---|---|\n| P | Prohibited |\n\nAfter table."
    out = render(md)
    assert out.index("<h2>") < out.index("<p>Intro text.</p>") < out.index("<table>")
    assert "<p>After table.</p>" in out


def test_multiline_paragraph_joined():
    assert render("line one\nline two") == "<p>line one line two</p>"


def test_highlight_matches_whole_word_case_insensitive_in_paragraph():
    out = render("Restrictive Airspace designation rules.", terms={"airspace"})
    assert out == "<p>Restrictive <mark>Airspace</mark> designation rules.</p>"


def test_highlight_does_not_match_substring():
    out = render("Restricted and restriction apply.", terms={"restrict"})
    assert "<mark>" not in out


def test_highlight_in_heading():
    out = render("## 5.3 Restrictive Airspace", terms={"restrictive"})
    assert out == "<h2>5.3 <mark>Restrictive</mark> Airspace</h2>"


def test_highlight_in_table_cell():
    md = "| Code | Meaning |\n|---|---|\n| P | Prohibited |"
    out = render(md, terms={"prohibited"})
    assert "<td><mark>Prohibited</mark></td>" in out


def test_highlight_preserves_escaping_around_match():
    out = render("Length <1> char & alpha restricted.", terms={"restricted"})
    assert out == "<p>Length &lt;1&gt; char &amp; alpha <mark>restricted</mark>.</p>"


def test_no_terms_behaves_like_before():
    assert render("Plain text.") == "<p>Plain text.</p>"
    assert render("Plain text.", terms=set()) == "<p>Plain text.</p>"


def test_render_block_image():
    sha = "a" * 64
    out = render(f"![Holding pattern](assets/{sha}.webp)")
    assert f'<img src="/assets/{sha}.webp" alt="Holding pattern" loading="lazy">' in out
    assert "<p>![" not in out


def test_render_image_in_table_cell():
    sha = "b" * 64
    md = "| Symbol | Meaning |\n| --- | --- |\n" + f"| ![VOR](assets/{sha}.png) | VOR station |"
    out = render(md)
    assert f'<td><img src="/assets/{sha}.png" alt="VOR" loading="lazy"></td>' in out
    assert "<td>VOR station</td>" in out


def test_render_non_asset_image_ref_stays_escaped_text():
    out = render("![x](http://evil/x.png)")
    assert "<img" not in out
    assert "![x](http://evil/x.png)" in out.replace("&quot;", '"')


def test_render_image_alt_is_escaped():
    sha = "c" * 64
    out = render(f'![a"b<c>](assets/{sha}.png)')
    assert 'alt="a&quot;b&lt;c&gt;"' in out


def test_fenced_code_is_verbatim_and_escaped():
    md = "```\n│\tViewer <A> | x\n  indented\n```"
    out = render(md)
    assert out == "<pre><code>│\tViewer &lt;A&gt; | x\n  indented</code></pre>"


def test_fenced_code_language_tag_is_ignored():
    assert render("```sql\nSELECT 1;\n```") == "<pre><code>SELECT 1;</code></pre>"


def test_fenced_code_is_not_highlighted():
    assert render("```\nairspace\n```", terms={"airspace"}) == "<pre><code>airspace</code></pre>"


def test_unclosed_fence_runs_to_end():
    assert render("```\none\ntwo") == "<pre><code>one\ntwo</code></pre>"


def test_fence_lines_starting_with_pipe_or_hash_stay_code():
    out = render("```\n| a | b |\n## not a heading\n```")
    assert out == "<pre><code>| a | b |\n## not a heading</code></pre>"


def test_list_items_merge_across_single_blank_line():
    md = "- one\n\n- two\n* three\n\nAfter."
    out = render(md)
    assert out == "<ul><li>one</li><li>two</li><li>three</li></ul>\n<p>After.</p>"


def test_list_item_is_highlighted_and_escaped():
    out = render("- Restrictive <Airspace>", terms={"airspace"})
    assert out == "<ul><li>Restrictive &lt;<mark>Airspace</mark>&gt;</li></ul>"


def test_list_closes_before_heading_and_table():
    md = "- a\n## H\n- b\n| x |"
    out = render(md)
    assert out == "<ul><li>a</li></ul>\n<h2>H</h2>\n<ul><li>b</li></ul>\n<table><tr><td>x</td></tr></table>"


def test_dash_inside_paragraph_is_not_a_list():
    assert render("value - not a list") == "<p>value - not a list</p>"
