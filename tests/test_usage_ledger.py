from pathlib import Path

import pytest

from strata_kb.usage import ledger


def row(uuid: str, ticket: str | None = "open-new-flight", **kw) -> ledger.UsageRow:
    """A row with every field filled, so a test only states what it varies."""
    base = dict(
        uuid=uuid,
        ts="2026-08-23T09:59:22.432Z",
        session="6c012668-dbc8-4086-a0eb-6fdb6566bc90",
        actor="ba",
        phase="ba-ticket-author",
        ticket=ticket,
        model="claude-sonnet-5",
        tokens_in=4,
        tokens_out=1837,
        cache_read=181392,
        cache_write_5m=0,
        cache_write_1h=3204,
        sidechain=False,
        branch=None,
        assistant="claude-code",
        est=False,
    )
    base.update(kw)
    return ledger.UsageRow(**base)


def test_ledger_path_is_named_after_the_ticket(tmp_path: Path):
    assert ledger.ledger_path(tmp_path, "open-new-flight") == (
        tmp_path / "usage" / "open-new-flight.jsonl"
    )


def test_ledger_path_for_no_ticket_is_the_unattributed_file(tmp_path: Path):
    assert ledger.ledger_path(tmp_path, None) == (
        tmp_path / "usage" / "_unattributed.jsonl"
    )


@pytest.mark.parametrize(
    "stem",
    [
        "..",
        ".",
        "../../etc/passwd",
        "a/b",
        "a\\b",
        "-leading-dash",
        "",
        " sp",
        "ok\n",
        "ok\r",
    ],
)
def test_ledger_path_refuses_a_stem_that_could_escape_the_usage_dir(
    tmp_path: Path, stem: str
):
    # The stem is read out of transcript CONTENT, which is not trusted input.
    with pytest.raises(ledger.LedgerError) as exc:
        ledger.ledger_path(tmp_path, stem)
    assert "ticket id" in str(exc.value)


def test_ledger_path_accepts_the_real_ticket_names(tmp_path: Path):
    # Invariant I4: a real ticket is a file stem, not 'M-<slug>-US<n>'.
    for stem in ("open-new-flight", "remove-witness-crew-stock-transfer"):
        assert ledger.ledger_path(tmp_path, stem).name == f"{stem}.jsonl"


def test_append_writes_one_json_line_per_row(tmp_path: Path):
    report = ledger.append_rows(tmp_path, [row("u1"), row("u2")])

    lines = (tmp_path / "usage" / "open-new-flight.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert report.written == 2
    assert report.duplicates == 0
    assert len(lines) == 2


def test_append_preserves_the_order_rows_were_given_in(tmp_path: Path):
    ledger.append_rows(tmp_path, [row("u1"), row("u2"), row("u3")])

    text = (tmp_path / "usage" / "open-new-flight.jsonl").read_text(encoding="utf-8")
    assert [r.uuid for r in ledger.read_rows(tmp_path)] == ["u1", "u2", "u3"]
    assert text.index("u1") < text.index("u2") < text.index("u3")


def test_append_skips_a_uuid_the_file_already_carries(tmp_path: Path):
    ledger.append_rows(tmp_path, [row("u1"), row("u2")])

    report = ledger.append_rows(tmp_path, [row("u2"), row("u3")])

    assert (report.written, report.duplicates) == (1, 1)
    assert [r.uuid for r in ledger.read_rows(tmp_path)] == ["u1", "u2", "u3"]


def test_append_dedupes_within_one_call_too(tmp_path: Path):
    report = ledger.append_rows(tmp_path, [row("u1"), row("u1")])

    assert (report.written, report.duplicates) == (1, 1)


def test_append_splits_rows_across_files_by_ticket(tmp_path: Path):
    ledger.append_rows(
        tmp_path,
        [
            row("u1", ticket="open-new-flight"),
            row("u2", ticket="remove-witness-crew-stock-transfer"),
            row("u3", ticket=None),
        ],
    )

    names = sorted(p.name for p in (tmp_path / "usage").glob("*.jsonl"))
    assert names == [
        "_unattributed.jsonl",
        "open-new-flight.jsonl",
        "remove-witness-crew-stock-transfer.jsonl",
    ]


def test_a_uuid_never_lands_in_two_files(tmp_path: Path):
    # Invariant I2.
    ledger.append_rows(tmp_path, [row("u1", ticket=None)])
    ledger.append_rows(tmp_path, [row("u1", ticket="open-new-flight")])

    seen = [r.uuid for r in ledger.read_rows(tmp_path)]
    assert seen.count("u1") == 1


def test_read_rows_on_an_empty_repo_is_empty(tmp_path: Path):
    assert ledger.read_rows(tmp_path) == []


def test_read_rows_ignores_a_blank_line(tmp_path: Path):
    ledger.append_rows(tmp_path, [row("u1")])
    path = tmp_path / "usage" / "open-new-flight.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    assert [r.uuid for r in ledger.read_rows(tmp_path)] == ["u1"]


def test_a_corrupt_line_in_any_ticket_file_blocks_append_with_a_named_ledger_error(
    tmp_path: Path,
):
    # _existing_uuids scans every *.jsonl on every append (global dedup,
    # invariant I2), so one unparseable line in ANY ticket's file must raise
    # — never be silently skipped, which would re-append that uuid forever.
    ledger.append_rows(tmp_path, [row("u1", ticket="open-new-flight")])
    corrupt = tmp_path / "usage" / "other-ticket.jsonl"
    corrupt.write_text('{"uuid": "broke"\n', encoding="utf-8")  # truncated JSON

    with pytest.raises(ledger.LedgerError) as exc:
        ledger.append_rows(tmp_path, [row("u2", ticket="open-new-flight")])

    message = str(exc.value)
    assert "other-ticket.jsonl" in message
    assert ":1" in message


def test_read_rows_raises_a_named_ledger_error_for_a_line_that_fails_the_schema(
    tmp_path: Path,
):
    path = tmp_path / "usage" / "open-new-flight.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"uuid": "x"}\n', encoding="utf-8")  # valid JSON, missing fields

    with pytest.raises(ledger.LedgerError) as exc:
        ledger.read_rows(tmp_path)

    message = str(exc.value)
    assert "open-new-flight.jsonl" in message
    assert ":1" in message


def test_hook_errors_survives_a_non_utf8_log(tmp_path: Path):
    log = tmp_path / "usage" / "ingest-errors.log"
    log.parent.mkdir()
    log.write_bytes(b"t1 boom\nt2 \xff\xfe bang\n")  # truncated multi-byte sequence

    count, last = ledger.hook_errors(tmp_path)

    assert count == 2
    assert "bang" in last
