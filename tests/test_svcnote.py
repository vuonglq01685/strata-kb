from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata_kb import models, svcnote
from strata_kb.build import build_kb
from strata_kb.cli import app
from strata_kb.codeingest import core
from tests.fixtures_coderepo import build_code_repo

runner = CliRunner()


@pytest.fixture
def seeded(tmp_path: Path) -> Path:
    root = build_code_repo(tmp_path)
    core.run(
        core.CodeIngestOptions(
            repo_root=root, kb_dir=root / ".kb", doc_id="demo-code",
            repo_id="demo", scaffold_svc=True,
        )
    )
    (root / ".kb" / "config.yaml").write_text(
        'kind: dev\nhub: ""\nrepo_id: "demo"\nintake: ""\n', encoding="utf-8"
    )
    return root


def _note(ticket="M-airspace-US4", title="Approve time-bound airspace",
          refs=("ATM-STD §5.3", "ATM-STD §5.7")) -> svcnote.Note:
    return svcnote.Note(ticket=ticket, title=title, refs=refs)


def test_creates_the_hist_section_on_first_note(seeded):
    report = svcnote.add_note(seeded / ".kb", "demo", "airspace-service", _note())
    assert report.section_id == "hist.airspace-service"
    assert report.action == "created"
    l2 = (seeded / ".kb" / "demo-svc" / "history.md").read_text(encoding="utf-8")
    assert "## hist.airspace-service" in l2
    assert "M-airspace-US4" in l2
    assert "ATM-STD §5.3" in l2


def test_hist_section_is_summarized_so_build_stays_clean(seeded):
    svcnote.add_note(seeded / ".kb", "demo", "airspace-service", _note())
    manifest = models.load_yaml_model(
        seeded / ".kb" / "demo-svc" / "_manifest.yaml", models.Manifest
    )
    hist = next(s for s in manifest.sections if s.id == "hist.airspace-service")
    assert hist.status == "summarized"
    assert hist.summary
    # the svc.* sections are still pending, so strict build fails on THOSE only
    strict = build_kb(seeded / ".kb")
    assert all("hist." not in e for e in strict.errors)
    assert build_kb(seeded / ".kb", allow_pending=True).ok


def test_second_note_for_a_different_ticket_appends(seeded):
    svcnote.add_note(seeded / ".kb", "demo", "airspace-service", _note())
    report = svcnote.add_note(
        seeded / ".kb", "demo", "airspace-service",
        _note(ticket="M-notify-US2", title="Notify on change", refs=("ATM-STD §9.1",)),
    )
    assert report.action == "added"
    assert report.notes == 2
    l2 = (seeded / ".kb" / "demo-svc" / "history.md").read_text(encoding="utf-8")
    assert "M-airspace-US4" in l2 and "M-notify-US2" in l2


def test_rerunning_the_same_ticket_updates_instead_of_duplicating(seeded):
    svcnote.add_note(seeded / ".kb", "demo", "airspace-service", _note())
    report = svcnote.add_note(
        seeded / ".kb", "demo", "airspace-service",
        _note(title="Approve time-bound airspace (revised)"),
    )
    assert report.action == "updated"
    assert report.notes == 1
    l2 = (seeded / ".kb" / "demo-svc" / "history.md").read_text(encoding="utf-8")
    assert l2.count("M-airspace-US4") == 1
    assert "(revised)" in l2


def test_rows_are_sorted_by_ticket_id(seeded):
    for ticket in ("M-zulu-US1", "M-alpha-US1", "M-mike-US1"):
        svcnote.add_note(seeded / ".kb", "demo", "airspace-service", _note(ticket=ticket))
    l2 = (seeded / ".kb" / "demo-svc" / "history.md").read_text(encoding="utf-8")
    assert l2.index("M-alpha-US1") < l2.index("M-mike-US1") < l2.index("M-zulu-US1")


def test_l3_has_no_pipe_table(seeded):
    svcnote.add_note(seeded / ".kb", "demo", "airspace-service", _note())
    l3 = (seeded / ".kb" / "demo-svc" / "history.raw.md").read_text(encoding="utf-8")
    assert "|" not in l3
    assert "```" in l3


def test_unknown_service_is_rejected(seeded):
    with pytest.raises(svcnote.SvcNoteError) as exc:
        svcnote.add_note(seeded / ".kb", "demo", "airspce-service", _note())
    assert "airspce-service" in str(exc.value)


# Final review, Important 1(b): the far more likely real-world cause of
# "unknown service" is not a typo but a genuinely new or renamed service
# whose name is real, but not yet in THIS repo's committed `-code` --
# `kb-code.yml` regenerates and publishes `-code` on the hub on every
# push, with no commit-back step, so the committed copy is a seed-time
# snapshot. The error must name `kb code-ingest` as the fix for that
# case without dropping the existing typo guidance (verbatim copy, hash
# suffix) that is still correct when the name really is a typo.
def test_unknown_service_error_names_kb_code_ingest_as_the_stale_code_fix(seeded):
    with pytest.raises(svcnote.SvcNoteError) as exc:
        svcnote.add_note(seeded / ".kb", "demo", "brand-new-service", _note())
    msg = str(exc.value)
    assert "brand-new-service" in msg  # existing rule: name the service
    assert "kb code-ingest" in msg
    # The pre-existing typo guidance must still be present, not replaced.
    assert "hash-character" in msg or "hex-character" in msg
    assert "verbatim" in msg


def test_never_touches_the_svc_responsibility_sections(seeded):
    svc_l2 = seeded / ".kb" / "demo-svc" / "services.md"
    before = svc_l2.read_bytes()
    svcnote.add_note(seeded / ".kb", "demo", "airspace-service", _note())
    assert svc_l2.read_bytes() == before


def test_two_identical_runs_are_byte_identical(seeded):
    svcnote.add_note(seeded / ".kb", "demo", "airspace-service", _note())
    hist = seeded / ".kb" / "demo-svc" / "history.md"
    first = hist.read_bytes()
    svcnote.add_note(seeded / ".kb", "demo", "airspace-service", _note())
    assert hist.read_bytes() == first


def test_cli_svc_note_happy_path(seeded):
    result = runner.invoke(app, [
        "svc", "note", "airspace-service",
        "--kb-dir", str(seeded / ".kb"),
        "--ticket", "M-airspace-US4",
        "--title", "Approve time-bound airspace",
        "--refs", "ATM-STD §5.3, ATM-STD §5.7",
    ])
    assert result.exit_code == 0, result.output
    assert "hist.airspace-service" in result.output


def test_cli_svc_note_json_output(seeded):
    result = runner.invoke(app, [
        "svc", "note", "airspace-service",
        "--kb-dir", str(seeded / ".kb"),
        "--ticket", "M-airspace-US4", "--title", "T", "--refs", "D §1",
        "--json",
    ])
    assert result.exit_code == 0, result.output
    import json

    payload = json.loads(result.output)
    assert payload["section_id"] == "hist.airspace-service"
    assert payload["action"] == "created"


def test_cli_svc_note_unknown_service_exits_1(seeded):
    result = runner.invoke(app, [
        "svc", "note", "nope",
        "--kb-dir", str(seeded / ".kb"),
        "--ticket", "T-1", "--title", "T", "--refs", "D §1",
    ])
    assert result.exit_code == 1
    assert "nope" in result.output


# --- Additional coverage beyond the brief, per Ruling R5 ("make that
# behaviour deliberate and tested rather than incidental") and the
# multi-service nature of file="history" (spec 6.2/6.4): every hist.*
# section shares one L2/L3 file pair, the same way every svc.* section
# shares services.md, so a note for one service must never destroy
# another service's already-recorded history.


def test_pipe_in_title_is_escaped_in_l2_and_absent_in_l3(seeded):
    svcnote.add_note(
        seeded / ".kb", "demo", "airspace-service",
        _note(title="Approve A|B corridor"),
    )
    l2 = (seeded / ".kb" / "demo-svc" / "history.md").read_text(encoding="utf-8")
    l3 = (seeded / ".kb" / "demo-svc" / "history.raw.md").read_text(encoding="utf-8")
    # L2: the pipe is escaped (backslash-prefixed), so it can never read as
    # an extra column delimiter -- the table survives.
    assert "A\\|B" in l2
    assert "A\\\\|B" not in l2  # escaped exactly once, not double-escaped
    # L3: the character must be ABSENT, not merely escaped (R5).
    assert "|" not in l3
    assert "A|B" not in l3


def test_notes_for_two_services_coexist_in_shared_history_files(seeded):
    svcnote.add_note(seeded / ".kb", "demo", "airspace-service", _note())
    report = svcnote.add_note(
        seeded / ".kb", "demo", "postgres",
        _note(ticket="M-db-US1", title="Add index", refs=("ATM-STD §2",)),
    )
    assert report.section_id == "hist.postgres"
    assert report.action == "created"

    l2 = (seeded / ".kb" / "demo-svc" / "history.md").read_text(encoding="utf-8")
    l3 = (seeded / ".kb" / "demo-svc" / "history.raw.md").read_text(encoding="utf-8")
    assert "## hist.airspace-service" in l2 and "## hist.postgres" in l2
    assert "M-airspace-US4" in l2 and "M-db-US1" in l2
    assert "M-airspace-US4" in l3 and "M-db-US1" in l3

    manifest = models.load_yaml_model(
        seeded / ".kb" / "demo-svc" / "_manifest.yaml", models.Manifest
    )
    ids = {s.id for s in manifest.sections}
    assert {"hist.airspace-service", "hist.postgres"}.issubset(ids)

    # Adding the second service's note must not rewrite the first
    # service's own recorded row.
    assert "Approve time-bound airspace" in l2


# --- Fix round 1 coverage: task review findings on the C2 diff ---
#
# Important 1 — the upsert key space must survive the round-trip through
# the rendered L2 table: a whitespace-padded ticket id must still match
# its own row on a later call, and a pipe-titled row must still be found
# (not silently dropped) when a second ticket is noted afterwards.


def test_pipe_titled_row_survives_a_second_note(seeded):
    svcnote.add_note(
        seeded / ".kb", "demo", "airspace-service",
        _note(title="Approve A|B corridor"),
    )
    report = svcnote.add_note(
        seeded / ".kb", "demo", "airspace-service",
        _note(ticket="M-notify-US2", title="Notify on change", refs=("ATM-STD §9.1",)),
    )
    assert report.action == "added"
    assert report.notes == 2  # NOT 1 -- the first, pipe-titled row must survive
    l2 = (seeded / ".kb" / "demo-svc" / "history.md").read_text(encoding="utf-8")
    assert "M-airspace-US4" in l2
    assert "M-notify-US2" in l2
    assert "A\\|B" in l2


def test_whitespace_padded_ticket_id_is_normalized_and_idempotent(seeded):
    svcnote.add_note(
        seeded / ".kb", "demo", "airspace-service",
        _note(ticket="M-airspace-US4 "),  # trailing space -- a pasted/shell-quoted id
    )
    report = svcnote.add_note(
        seeded / ".kb", "demo", "airspace-service",
        _note(ticket=" M-airspace-US4", title="Approve time-bound airspace (revised)"),
    )
    assert report.action == "updated"
    assert report.notes == 1  # NOT 2 -- must not duplicate on whitespace alone
    l2 = (seeded / ".kb" / "demo-svc" / "history.md").read_text(encoding="utf-8")
    assert l2.count("M-airspace-US4") == 1
    assert "(revised)" in l2


# Important 3 — a hist.* section recorded in the manifest but missing its
# heading from the file (a desync) must be refused, not silently
# rewritten with an empty body while the manifest still claims history.


def test_manifest_file_desync_on_target_section_is_rejected(seeded):
    svcnote.add_note(seeded / ".kb", "demo", "airspace-service", _note())
    hist = seeded / ".kb" / "demo-svc" / "history.md"
    hist.write_text("# demo-svc\n\n> banner\n\nno hist heading here\n", encoding="utf-8")
    with pytest.raises(svcnote.SvcNoteError) as exc:
        svcnote.add_note(
            seeded / ".kb", "demo", "airspace-service",
            _note(ticket="M-second-US1"),
        )
    assert "hist.airspace-service" in str(exc.value)


def test_manifest_file_desync_on_sibling_section_is_rejected(seeded):
    svcnote.add_note(seeded / ".kb", "demo", "airspace-service", _note())
    hist = seeded / ".kb" / "demo-svc" / "history.md"
    hist.write_text("# demo-svc\n\n> banner\n\nno hist heading here\n", encoding="utf-8")
    with pytest.raises(svcnote.SvcNoteError) as exc:
        svcnote.add_note(
            seeded / ".kb", "demo", "postgres",
            _note(ticket="M-db-US1", title="Add index", refs=("ATM-STD §2",)),
        )
    assert "hist.airspace-service" in str(exc.value)


# Minor 1 — a Markdown formatter's alignment-style separator row
# (":---"-shaped cells) must be recognised as a separator, not parsed as
# a junk data row.


def test_alignment_style_separator_row_is_not_treated_as_data(seeded):
    svcnote.add_note(seeded / ".kb", "demo", "airspace-service", _note())
    hist = seeded / ".kb" / "demo-svc" / "history.md"
    text = hist.read_text(encoding="utf-8").replace(
        "| --- | --- | --- |", "|:---|:---:|---:|"
    )
    hist.write_text(text, encoding="utf-8")
    report = svcnote.add_note(
        seeded / ".kb", "demo", "airspace-service",
        _note(ticket="M-notify-US2", title="Notify on change", refs=("ATM-STD §9.1",)),
    )
    assert report.notes == 2  # NOT 3 -- the separator row must not become data
    l2 = hist.read_text(encoding="utf-8")
    assert ":---" not in l2


# Minor 3 — a missing -code document gets its own, distinct error (not
# "unknown service"), and a missing/malformed manifest (either document)
# is a red SvcNoteError, never a raw traceback.


def test_missing_code_document_gives_a_distinct_error(seeded):
    import shutil

    shutil.rmtree(seeded / ".kb" / "demo-code")
    with pytest.raises(svcnote.SvcNoteError) as exc:
        svcnote.add_note(seeded / ".kb", "demo", "airspace-service", _note())
    msg = str(exc.value)
    assert "demo-code" in msg
    assert "unknown service" not in msg


def test_missing_svc_manifest_raises_svcnoteerror(seeded):
    (seeded / ".kb" / "demo-svc" / "_manifest.yaml").unlink()
    with pytest.raises(svcnote.SvcNoteError):
        svcnote.add_note(seeded / ".kb", "demo", "airspace-service", _note())


def test_malformed_svc_manifest_raises_svcnoteerror(seeded):
    (seeded / ".kb" / "demo-svc" / "_manifest.yaml").write_text(
        "sections:\n\t- id: x\n", encoding="utf-8"  # tab indent -- invalid YAML
    )
    with pytest.raises(svcnote.SvcNoteError):
        svcnote.add_note(seeded / ".kb", "demo", "airspace-service", _note())


def test_malformed_code_manifest_raises_svcnoteerror(seeded):
    (seeded / ".kb" / "demo-code" / "_manifest.yaml").write_text(
        "sections:\n\t- id: x\n", encoding="utf-8"  # tab indent -- invalid YAML
    )
    with pytest.raises(svcnote.SvcNoteError):
        svcnote.add_note(seeded / ".kb", "demo", "airspace-service", _note())


# Minor 6 — a title containing a code fence must not break the L3
# fenced block.


def test_backtick_in_title_does_not_break_the_l3_fence(seeded):
    svcnote.add_note(
        seeded / ".kb", "demo", "airspace-service",
        _note(title="Use ```rm -rf``` carefully"),
    )
    l3 = (seeded / ".kb" / "demo-svc" / "history.raw.md").read_text(encoding="utf-8")
    # Exactly the outer fence's opening and closing markers survive as
    # literal "```" -- the banner's own single backticks (`kb svc note`)
    # are unrelated to title neutralization and are not being asserted on
    # here. If the title's triple-backtick had survived unneutralized,
    # this count would be 4 (the real fence pair plus the title's own).
    assert l3.count("```") == 2
    assert "```rm" not in l3
    assert "rm -rf```" not in l3
    assert "rm -rf" in l3  # content preserved, only the punctuation changed


# Final review, Minor 4 — a literal NUL byte in caller-supplied text must
# not land in the published `history.md`/`history.raw.md` (worse than
# CLI-unreachable once `.kb/` publishes to the shared federation hub), and
# must not collide with `_ESCAPED_PIPE_SENTINEL` (also `\x00`, used by
# `_parse_existing_rows` for its own escaped-pipe bookkeeping) and get
# misread back as a literal `|` on the next call.


def test_embedded_nul_byte_is_stripped_not_written_or_misread_as_pipe(seeded):
    svcnote.add_note(
        seeded / ".kb", "demo", "airspace-service",
        _note(title="a\x00b"),
    )
    l2 = (seeded / ".kb" / "demo-svc" / "history.md").read_text(encoding="utf-8")
    l3 = (seeded / ".kb" / "demo-svc" / "history.raw.md").read_text(encoding="utf-8")
    assert "\x00" not in l2
    assert "\x00" not in l3
    assert "ab" in l2
    assert "a|b" not in l2

    # A second note re-parses the first row back out of history.md. If the
    # NUL had survived into the file, this call's sentinel swap/restore
    # would misread it as a literal "|" -- prove it does not.
    svcnote.add_note(
        seeded / ".kb", "demo", "airspace-service",
        _note(ticket="M-notify-US2", title="Notify on change", refs=("ATM-STD §9.1",)),
    )
    l2_after = (seeded / ".kb" / "demo-svc" / "history.md").read_text(encoding="utf-8")
    assert "ab" in l2_after
    assert "a|b" not in l2_after


# Final review, Minor 5 — an empty (or whitespace-only, post-normalisation)
# ticket must be rejected outright: rendered as an all-blank row, it reads
# as a second table separator (`_SEP_ROW_RE`) and is silently dropped on
# the very next call, leaving a permanent junk row this command can never
# repair, and mislabelling the NEXT real note's `action` along the way.


def test_empty_ticket_is_rejected(seeded):
    with pytest.raises(svcnote.SvcNoteError) as exc:
        svcnote.add_note(
            seeded / ".kb", "demo", "airspace-service", _note(ticket="")
        )
    assert "ticket" in str(exc.value).lower()


def test_whitespace_only_ticket_is_rejected(seeded):
    with pytest.raises(svcnote.SvcNoteError):
        svcnote.add_note(
            seeded / ".kb", "demo", "airspace-service", _note(ticket="   ")
        )
