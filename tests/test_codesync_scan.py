from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from strata_kb import gitio, models
from strata_kb.codesync import baseline, scan
from strata_kb.codesync.changes import ChangedItem
from tests.conftest import make_fed_entry
from tests.test_codesync_changes import (
    BASE_SECTIONS,
    _db,
    _svc,
    commit,
    write_doc,
)

NO_LEDGER = {**BASE_SECTIONS, "svc.payment": ("payment", _svc("`postgres`"))}


def _item(section_id: str, title: str, facts=(), *, removed=True) -> ChangedItem:
    fs = frozenset(facts)
    return ChangedItem(
        "acme",
        "acme-code",
        section_id,
        title,
        "changed",
        frozenset() if removed else fs,
        fs if removed else frozenset(),
    )


def _set_arch(root: Path, l3: str, tags=("authored",)) -> None:
    shutil.rmtree(root / "federation" / "kb-hub")
    make_fed_entry(
        root / "federation",
        "kb-hub",
        "arch",
        tags=list(tags),
        sec_id="4.2",
        sec_title="Payment flow",
        l3=l3,
    )


def _add_hub_doc(root: Path, doc_id: str, tags: list[str], l3: str) -> None:
    doc = root / "federation" / "kb-hub" / doc_id
    doc.mkdir()
    (doc / "ch1.md").write_text(l3, encoding="utf-8")
    (doc / "ch1.raw.md").write_text(l3, encoding="utf-8")
    models.save_yaml_model(
        doc / "_manifest.yaml",
        models.Manifest(
            id=doc_id,
            title=doc_id,
            sections=[
                models.SectionEntry(
                    id="1.1", title="One", summary="s", status="summarized", file="ch1"
                )
            ],
        ),
    )
    path = root / "federation" / "kb-hub" / "index.yaml"
    index = models.load_yaml_model(path, models.KBIndex)
    index.docs.append(models.IndexEntry(id=doc_id, title=doc_id, tags=tags))
    models.save_yaml_model(path, index)


def _with_origin(root: Path, run_git, tmp_path: Path) -> None:
    origin = tmp_path / "origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    run_git(root, "remote", "add", "origin", str(origin))
    run_git(root, "push", "-u", "origin", "HEAD")
    run_git(
        root, "remote", "set-head", "origin", run_git(root, "branch", "--show-current")
    )


# --- match_terms -----------------------------------------------------------


def test_match_terms_title_slug_and_fact_values():
    item = _item("svc.payment", "Payment", [("depends_on", "ledger")])
    assert scan.match_terms(item) == ["Payment", "ledger", "payment"]


def test_match_terms_route_path_and_column_name():
    route = _item("api.orders", "orders", [("route", "GET /orders")])
    col = _item("db.orders", "orders", [("column_type", "refund_id:TEXT")])
    assert "/orders" in scan.match_terms(route)
    assert "refund_id" in scan.match_terms(col)


def test_match_terms_drop_stop_words_and_short_names():
    assert set(scan.STOP_WORDS) >= {"api", "app", "web", "db", "service", "test"}
    assert scan.MIN_TERM_LEN == 4
    assert (
        scan.match_terms(_item("svc.api", "api", [("port", "80"), ("env_key", "DB")]))
        == []
    )


def test_match_terms_cmd_uses_command_string_only():
    item = _item("cmd.test", "test", [("command", "pytest -q")])
    assert scan.match_terms(item) == ["pytest -q"]


def test_match_terms_whole_document_is_repo_id():
    item = ChangedItem(
        "acme",
        "acme-code",
        None,
        "t",
        "removed",
        frozenset(),
        frozenset({("column", "amount")}),
    )
    assert scan.match_terms(item) == ["acme"]


# --- run_scan --------------------------------------------------------------


def test_removed_dependency_matches_arch_section(code_sync_hub, run_git):
    root, c1 = code_sync_hub
    write_doc(root, "acme", "code", NO_LEDGER)
    commit(root, run_git)

    r = scan.run_scan(root, baseline_sha=c1)

    [f] = r.findings
    assert (f.doc_id, f.section_id, f.section_title) == ("arch", "4.2", "Payment flow")
    assert f.term in {"payment-service", "ledger"}
    assert f.image is False
    assert f.item.section_id == "svc.payment"
    assert scan.exit_code(r) == 2


def test_generic_and_short_names_never_match(code_sync_hub, run_git):
    root, c1 = code_sync_hub
    sections = {
        **BASE_SECTIONS,
        "svc.api": ("api", _svc("`postgres`")),
        "cmd.test": ("test", "**Primary:** `pytest -q`\n"),
    }
    write_doc(root, "acme", "code", sections)
    c2 = commit(root, run_git)
    _set_arch(
        root, "## 4.2 Payment flow\n\nThe api and the test suite run in the app.\n"
    )
    commit(root, run_git)

    assert scan.run_scan(root, baseline_sha=c1).findings == ()
    assert c2 != c1


def test_cmd_matches_on_command_string_only(code_sync_hub, run_git):
    root, c1 = code_sync_hub
    write_doc(
        root,
        "acme",
        "code",
        {**BASE_SECTIONS, "cmd.build": ("build", "**Primary:** `make release`\n")},
    )
    c2 = commit(root, run_git)
    write_doc(
        root,
        "acme",
        "code",
        {**BASE_SECTIONS, "cmd.build": ("build", "**Primary:** `make dist`\n")},
    )
    commit(root, run_git)

    _set_arch(root, "## 4.2 Payment flow\n\nWe build and run it.\n")
    commit(root, run_git)
    assert scan.run_scan(root, baseline_sha=c2).findings == ()

    _set_arch(root, "## 4.2 Payment flow\n\nShip with make dist.\n")
    commit(root, run_git)
    [f] = scan.run_scan(root, baseline_sha=c2).findings
    assert f.term == "make dist"


def test_word_boundary_case_insensitive(code_sync_hub, run_git):
    root, c1 = code_sync_hub
    write_doc(root, "acme", "code", NO_LEDGER)
    commit(root, run_git)

    _set_arch(root, "## 4.2 Payment flow\n\nLedger posts it.\n")
    commit(root, run_git)
    assert [f.term for f in scan.run_scan(root, baseline_sha=c1).findings] == ["ledger"]

    for prose in ("ledgerX posts it.", "my-ledger posts it."):
        _set_arch(root, f"## 4.2 Payment flow\n\n{prose}\n")
        commit(root, run_git)
        assert scan.run_scan(root, baseline_sha=c1).findings == ()


def test_match_inside_image_description_sets_image_flag(code_sync_hub, run_git):
    root, c1 = code_sync_hub
    write_doc(root, "acme", "code", NO_LEDGER)
    commit(root, run_git)
    image = f"![ledger posting diagram](assets/{'a' * 64}.png)"

    _set_arch(root, f"## 4.2 Payment flow\n\n{image}\n")
    commit(root, run_git)
    [f] = scan.run_scan(root, baseline_sha=c1).findings
    assert (f.term, f.image) == ("ledger", True)

    _set_arch(root, f"## 4.2 Payment flow\n\nThe ledger is shown.\n\n{image}\n")
    commit(root, run_git)
    [f] = scan.run_scan(root, baseline_sha=c1).findings
    assert f.image is False


def test_generated_and_skip_tagged_docs_excluded(code_sync_hub, run_git):
    root, c1 = code_sync_hub
    mention = "## 1.1 One\n\nledger is mentioned here.\n"
    _add_hub_doc(root, "gen", ["generated"], mention)
    _add_hub_doc(root, "skipped", ["code-sync-skip"], mention)
    write_doc(root, "acme", "code", NO_LEDGER)
    commit(root, run_git)

    r = scan.run_scan(root, baseline_sha=c1)

    assert {f.doc_id for f in r.findings} == {"arch"}
    assert not any("gen" in n or "skipped" in n for n in r.notes)


def test_not_authored_doc_gets_note(code_sync_hub, run_git):
    root, c1 = code_sync_hub
    assert scan.run_scan(root, baseline_sha=c1).notes == ()
    _set_arch(root, "## 4.2 Payment flow\n\nledger.\n", tags=())
    commit(root, run_git)

    assert "arch is not tagged authored" in scan.run_scan(root, baseline_sha=c1).notes


def test_hub_repo_id_falls_back_to_directory_name(code_sync_hub, run_git):
    root, c1 = code_sync_hub
    (root / ".kb" / "config.yaml").write_text("kind: hub\nhub: .\n", encoding="utf-8")
    write_doc(root, "acme", "code", NO_LEDGER)
    commit(root, run_git)

    assert [f.doc_id for f in scan.run_scan(root, baseline_sha=c1).findings] == ["arch"]


def test_no_baseline_file_is_note_and_exit_0(code_sync_hub):
    root, _ = code_sync_hub

    r = scan.run_scan(root)

    assert (r.baseline_sha, r.findings) == (None, ())
    assert r.notes == ("no baseline — run kb code-sync baseline",)
    assert scan.exit_code(r) == 0
    assert "note: no baseline — run kb code-sync baseline" in scan.render_markdown(r)


def test_baseline_file_at_scan_sha_is_used(code_sync_hub, run_git):
    root, c1 = code_sync_hub
    baseline.write(root, c1)
    write_doc(root, "acme", "code", NO_LEDGER)
    commit(root, run_git)

    r = scan.run_scan(root)

    assert (r.baseline_sha, r.baseline_source) == (c1, "default-branch")
    assert len(r.findings) == 1


def test_baseline_missing_from_history_raises(code_sync_hub, run_git):
    root, _ = code_sync_hub
    (root / baseline.BASELINE_FILE).write_text(
        "baseline: deadbeefcafe1234\n", encoding="utf-8"
    )
    commit(root, run_git)

    with pytest.raises(gitio.GitError):
        scan.run_scan(root)
    with pytest.raises(gitio.GitError):
        scan.run_scan(root, baseline_sha="deadbeefcafe1234")


def test_invalid_baseline_override_raises_value_error(code_sync_hub):
    root, _ = code_sync_hub
    with pytest.raises(ValueError):
        scan.run_scan(root, baseline_sha="--output=/tmp/x")


def test_bot_branch_baseline_wins(code_sync_hub, run_git, tmp_path):
    root, c1 = code_sync_hub
    write_doc(root, "acme", "code", NO_LEDGER)
    c2 = commit(root, run_git)
    # The rolling PR branch recorded c2; the default branch has no file.
    run_git(root, "checkout", "-q", "-b", "bot")
    baseline.write(root, c2)
    bot = commit(root, run_git)
    run_git(root, "checkout", "-q", "-")
    run_git(root, "branch", "-q", "-D", "bot")
    write_doc(
        root,
        "acme",
        "code",
        {**NO_LEDGER, "db.payments": ("payments", _db("amount", "refund_id"))},
    )
    commit(root, run_git)
    _with_origin(root, run_git, tmp_path)
    run_git(root, "update-ref", f"refs/remotes/origin/{baseline.BOT_BRANCH}", bot)

    r = scan.run_scan(root)

    assert (r.baseline_sha, r.baseline_source) == (c2, "bot-branch")
    assert [f.item.section_id for f in r.findings] == ["db.payments"]
    assert c1 != c2


def test_scan_ref_no_remote_is_head(code_sync_hub):
    root, c1 = code_sync_hub
    assert baseline.scan_ref(root) == c1


def test_scan_ref_remote_without_origin_head_raises(code_sync_hub, run_git, tmp_path):
    root, _ = code_sync_hub
    run_git(root, "remote", "add", "origin", str(tmp_path / "nowhere.git"))
    with pytest.raises(gitio.GitError, match="origin/HEAD is not set"):
        baseline.scan_ref(root)


def test_scan_ref_is_origin_tip_not_local_head(code_sync_hub, run_git, tmp_path):
    root, c1 = code_sync_hub
    _with_origin(root, run_git, tmp_path)
    write_doc(root, "acme", "code", NO_LEDGER)
    commit(root, run_git)  # local only, never pushed

    assert baseline.scan_ref(root) == c1


def test_dirty_worktree_does_not_change_output(code_sync_hub, run_git):
    root, c1 = code_sync_hub
    write_doc(root, "acme", "code", NO_LEDGER)
    commit(root, run_git)
    before = scan.to_json(scan.run_scan(root, baseline_sha=c1))

    raw = root / "federation" / "kb-hub" / "arch" / "ch1.raw.md"
    raw.write_text("## 4.2 Payment flow\n\nrewritten, uncommitted.\n", encoding="utf-8")
    write_doc(root, "acme", "code", BASE_SECTIONS)

    assert scan.to_json(scan.run_scan(root, baseline_sha=c1)) == before


def test_output_is_byte_identical_on_repeat(code_sync_hub, run_git):
    root, c1 = code_sync_hub
    write_doc(root, "acme", "code", NO_LEDGER)
    commit(root, run_git)

    a = scan.run_scan(root, baseline_sha=c1)
    b = scan.run_scan(root, baseline_sha=c1)

    assert scan.render_markdown(a) == scan.render_markdown(b)
    assert scan.digest(a) == scan.digest(b)
    md = scan.render_markdown(a)
    assert md.endswith(f"<!-- kb-code-sync digest:{scan.digest(a)} -->\n")
    assert "## arch §4.2 Payment flow" in md
    assert "`Depends on` no longer lists `ledger`" in md
    assert f"Scan: {a.scan_sha[:12]}" in md.splitlines()[0]


def test_digest_ignores_header(code_sync_hub, run_git):
    root, c1 = code_sync_hub
    write_doc(root, "acme", "code", NO_LEDGER)
    commit(root, run_git)
    a = scan.run_scan(root, baseline_sha=c1)
    b = scan.ScanResult("f" * 40, a.baseline_sha, "bot-branch", a.findings, ("x",))

    assert scan.digest(a) == scan.digest(b)


# --- baseline file ---------------------------------------------------------


def test_parse_accepts_hex_and_missing_key():
    assert baseline.parse("baseline: abcdef1\n") == "abcdef1"
    assert baseline.parse(f"# c\nbaseline: '{'A' * 40}'\n") == "A" * 40
    assert baseline.parse("other: 1\n") is None
    assert baseline.parse("") is None


@pytest.mark.parametrize(
    "value",
    ["", "abc12", "HEAD", "HEAD~1", "--output=x", "g" * 10, "a" * 41, "abc def1"],
)
def test_parse_rejects_non_sha(value):
    with pytest.raises(ValueError):
        baseline.parse(f"baseline: {value}\n")


def test_write_then_read_round_trip(code_sync_hub, run_git):
    root, c1 = code_sync_hub
    baseline.write(root, c1)
    assert (root / baseline.BASELINE_FILE).read_text() == f"baseline: {c1}\n"
    commit(root, run_git)
    assert baseline.read_at(root, "HEAD") == c1
    assert baseline.read_at(root, c1) is None
