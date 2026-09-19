"""`--level` validation.

Reviewer C F-C4: `query.py:261` was `suffix = ".raw.md" if level == "l3" else
".md"` and the CLI validated nothing, so `--level L3`, `verbatim`, `raw` and
`l1` all returned the AI-condensed L2 — under a byte-identical header, so the
caller could not tell. Measured on §5.129: l3 = 1310 bytes, everything else
1219. The MCP tool did validate, so the two surfaces disagreed.
"""
import pytest
from typer.testing import CliRunner

from strata_kb.cli import app
from strata_kb.hub import HubHandle
from strata_kb.query import InvalidLevelError, get_section

VALID = ["l2", "l3", "L2", "L3"]
INVALID = ["verbatim", "raw", "l1", "L1", "", "  "]


@pytest.mark.parametrize("level", INVALID)
def test_get_section_refuses_an_invalid_level(fed_hub, level):
    with pytest.raises(InvalidLevelError) as excinfo:
        get_section(HubHandle(root=fed_hub), "arinc-kb:arinc-424", "5.3", level=level)
    assert "use 'l2' or 'l3'" in str(excinfo.value)


@pytest.mark.parametrize("level", VALID)
def test_get_section_accepts_either_case(fed_hub, level):
    result = get_section(
        HubHandle(root=fed_hub), "arinc-kb:arinc-424", "5.3", level=level
    )
    assert result is not None
    expected = "Verbatim" if level.lower() == "l3" else "Condensed"
    assert expected in result.content


@pytest.mark.parametrize("level", INVALID)
def test_cli_get_exits_1_on_an_invalid_level(fed_hub, level):
    result = CliRunner().invoke(
        app,
        ["get", "arinc-kb:arinc-424", "5.3", "--level", level,
         "--hub", str(fed_hub), "--kb-dir", str(fed_hub / ".kb")],
    )
    assert result.exit_code == 1
    assert "use 'l2' or 'l3'" in result.output


def test_cli_get_l3_returns_the_verbatim_text(fed_hub):
    result = CliRunner().invoke(
        app,
        ["get", "arinc-kb:arinc-424", "5.3", "--level", "l3",
         "--hub", str(fed_hub), "--kb-dir", str(fed_hub / ".kb")],
    )
    assert result.exit_code == 0
    assert "Verbatim" in result.output
