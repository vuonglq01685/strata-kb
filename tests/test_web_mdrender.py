# tests/test_web_mdrender.py
from aero_kb.web.mdrender import render


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
