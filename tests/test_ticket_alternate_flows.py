from strata_kb import ticket


def test_alternate_flows_parses_list_under_use_cases():
    text = (
        "# T\n## Use cases\n### Main flow\n- not me\n"
        "### Alternate / exception flows\n- Record missing\n* Timeout\n"
        "1. Bad level\n\n## Business flow\n- nope\n"
    )
    assert ticket.alternate_flows(text) == ["Record missing", "Timeout", "Bad level"]


def test_alternate_flows_empty_when_absent():
    assert ticket.alternate_flows("# T\n## Use cases\n### Main flow\n") == []
    assert ticket.alternate_flows("# T\n") == []
