import subprocess
import sys

import pytest

from strata_kb.ingest import mdreader, sectioner
from strata_kb.ingest.mdreader import md_pages, read_md


def _texts(doc):
    return [(i.kind, i.text) for i in doc.items]


def test_blocks_are_verbatim_source_lines():
    blocks = [
        "| a | b |\n|---|---|\n| 1 | 2 |",
        "- one\n  - nested\n- two",
        "> quote\n> more",
        "<div>\nraw\n</div>",
        "```python\nx = 1\n```",
    ]
    doc = read_md("\n\n".join(blocks) + "\n", "a.md")
    assert [i.text for i in doc.items] == blocks
    assert [i.kind for i in doc.items] == ["table", "list", "text", "text", "code"]


def test_indented_code_keeps_first_line_indent():
    doc = read_md("para\n\n    code line\n    more\n", "a.md")
    assert _texts(doc)[1] == ("code", "    code line\n    more")


def test_front_matter_dropped_with_warning():
    doc = read_md("---\ntitle: x\n---\n# Intro\n\ntext\n", "a.md")
    assert doc.warnings == ["front matter dropped (3 lines)"]
    assert doc.title == "Intro"
    assert all("title: x" not in i.text for i in doc.items)


def test_sole_unnumbered_h1_is_title():
    doc = read_md("# My Doc\n\n## 1 Scope\n\ntext\n", "a.md")
    assert doc.title == "My Doc"
    assert [i.text for i in doc.items] == ["1 Scope", "text"]


def test_numbered_h1_is_a_heading_item():
    doc = read_md("# 1 Scope\n\ntext\n", "a.md")
    assert doc.title is None
    assert doc.items[0].kind == "heading" and doc.items[0].level == 1


def test_two_h1_are_items():
    doc = read_md("# A\n\n# B\n", "a.md")
    assert doc.title is None
    assert [i.text for i in doc.items] == ["A", "B"]


def test_heading_level_from_hashes():
    doc = read_md("## a\n\n### b\n\n#### c\n", "a.md")
    assert [i.level for i in doc.items] == [2, 3, 4]


@pytest.mark.parametrize("src", ["## **1.2** Scope", "## 1.2 [Scope](x.md)"])
def test_id_behind_bold_or_link_is_parsed(src):
    item = read_md(src + "\n", "a.md").items[0]
    parsed = sectioner.parse_section_id(item.text)
    assert parsed and parsed[0] == "1.2"


def test_link_wrapping_id_is_unwrapped():
    item = read_md("## [1.2](x.md) Scope\n", "a.md").items[0]
    assert item.text == "1.2 Scope"


def test_crlf_and_bom_same_items_as_lf():
    lf = "# T\n\n## 1 A\n\n- x\n- y\n\n```\ncode\n```\n"
    crlf = "﻿" + lf.replace("\n", "\r\n")
    cr = lf.replace("\n", "\r")
    assert read_md(crlf, "a.md") == read_md(lf, "a.md") == read_md(cr, "a.md")


def test_fenced_heading_line_refused():
    src = "# T\n\ntext\n\n```\n## step\n```\n"
    with pytest.raises(ValueError) as e:
        read_md(src, "doc.md")
    assert str(e.value) == (
        "doc.md: fenced code holds a '## ' heading line at line(s) 6"
        " — move it out of the fence or indent it"
    )


def test_fenced_heading_lines_listed_and_offset_by_front_matter():
    src = "---\na: 1\n---\n```\n## x\n### y\n```\n"
    with pytest.raises(ValueError, match=r"line\(s\) 5, 6 "):
        read_md(src, "d.md")


def test_image_only_paragraph_is_image_item():
    doc = read_md("![alt](a.png)\n\ntext ![x](b.png)\n", "a.md")
    assert [i.kind for i in doc.items] == ["image", "text"]


def test_pages_follow_top_level_headings():
    src = "pre\n\n## a\n\nx\n\n### sub\n\ny\n\n## b\n\nz\n"
    doc = read_md(src, "a.md")
    assert [(i.text, i.page) for i in doc.items] == [
        ("pre", 1), ("a", 1), ("x", 1), ("sub", 1), ("y", 1), ("b", 2), ("z", 2),
    ]  # fmt: skip
    assert all(i.bbox is None for i in doc.items)


def test_md_pages_strip_markdown():
    pages = md_pages("## a\n\n**x** [l](u)\n\n## b\n\nz\n")
    assert set(pages) == {1, 2}
    assert "**" not in pages[1] and "l" in pages[1] and "(u)" not in pages[1]
    assert "z" in pages[2]


def test_md_pages_no_heading_single_page():
    assert set(md_pages("just text\n")) == {1}


def test_reader_imports_no_docling():
    code = (
        "import sys; sys.modules['docling'] = None\n"
        "from strata_kb.ingest.mdreader import read_md\n"
        "assert read_md('## a\\n\\nb\\n', 'a.md').items\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_module_exports():
    assert mdreader.MdDoc


def test_link_reference_definitions_kept():
    src = "See [a][r].\n\n[r]: http://x.example/a\n[s]: http://x.example/b\n\nend\n"
    doc = read_md(src, "a.md")
    assert _texts(doc) == [
        ("text", "See [a][r]."),
        ("text", "[r]: http://x.example/a\n[s]: http://x.example/b"),
        ("text", "end"),
    ]


def test_every_source_line_reaches_an_item():
    src = (
        "---\nk: v\n---\n# Doc Title\n\nintro\n[r]: http://u\n\n## 1 A\n\n"
        "| a | b |\n|---|---|\n| 1 | 2 |\n\n- x\n  - y\n\n> q\n\n"
        "    indented\n\n```\ncode\n```\n\n<div>\nh\n</div>\n\n---\n\n[z]: /z\n"
    )
    doc = read_md(src, "a.md")
    covered = {ln for it in doc.items for ln in it.text.split("\n")}
    body = src.split("\n")[3:]  # minus front matter
    missing = [
        ln for ln in body if ln.strip() and ln != "# Doc Title" and ln not in covered
    ]
    # heading lines are rewritten (markers dropped) -> compare by text
    missing = [ln for ln in missing if ln.lstrip("# ") not in covered]
    assert missing == []


@pytest.mark.parametrize(
    ("src", "text"),
    [
        ("## **Important** changes", "**Important** changes"),
        ("## _private_ api", "_private_ api"),
        ("## **1.2 Scope**", "1.2 Scope"),
    ],
)
def test_only_markup_wrapping_an_id_is_unwrapped(src, text):
    assert read_md(src + "\n", "a.md").items[0].text == text


@pytest.mark.parametrize("src", ["<!--\n## x\n-->\n", "<pre>\n## y\n</pre>\n"])
def test_heading_line_in_html_block_refused(src):
    with pytest.raises(ValueError) as e:
        read_md("intro\n\n" + src, "d.md")
    assert str(e.value) == (
        "d.md: fenced code holds a '## ' heading line at line(s) 4"
        " — move it out of the fence or indent it"
    )


def test_yaml_dict_front_matter_dropped():
    doc = read_md("---\na: 1\n---\ntext\n", "a.md")
    assert doc.warnings == ["front matter dropped (3 lines)"]
    assert [i.text for i in doc.items] == ["text"]


def test_thematic_break_is_not_front_matter():
    doc = read_md("---\n\nintro\n\nTitle\n---\n\nbody\n", "a.md")
    assert doc.warnings == []
    assert [i.text for i in doc.items][0] == "---"
    assert "Title" in [i.text for i in doc.items]


@pytest.mark.parametrize(
    ("src", "sid"), [("## **1.2.** Scope", "1.2"), ("## **2.0** Scope", "2")]
)
def test_normalized_ids_behind_markup_are_parsed(src, sid):
    parsed = sectioner.parse_section_id(read_md(src + "\n", "a.md").items[0].text)
    assert parsed and parsed[0] == sid


def test_unparseable_yaml_block_is_not_front_matter():
    doc = read_md("---\na: 2001-13-01\n---\nx\n", "a.md")
    assert doc.warnings == []
    assert "x" in [i.text for i in doc.items]
