from typer.testing import CliRunner

from aero_kb import kbcontext
from aero_kb.cli import app

runner = CliRunner()


def test_context_new_prints_block_with_head_hash(git_kb):
    result = runner.invoke(
        app,
        ["context", "new", "--refs", "demo-doc §1.1,demo-doc §1.2",
         "--tags", "demo,airspace", "--kb-dir", str(git_kb["kb"])],
    )
    assert result.exit_code == 0
    assert "kb-context:" in result.output
    assert f"version: {git_kb['rev2']}" in result.output
    assert "- demo-doc §1.1" in result.output
    assert "tags: [demo, airspace]" in result.output


def test_context_new_rejects_unresolvable_ref(git_kb):
    result = runner.invoke(
        app,
        ["context", "new", "--refs", "demo-doc §9.9", "--kb-dir", str(git_kb["kb"])],
    )
    assert result.exit_code == 1
    assert "9.9" in result.output


def test_context_new_warns_when_kb_dirty(git_kb):
    (git_kb["kb"] / "demo-doc" / "ch1-records.md").write_text(
        "## 1.1 Airspace Records\n\nsua chua commit\n\n## 1.2 Airway Records\n\nx\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["context", "new", "--refs", "demo-doc §1.1", "--kb-dir", str(git_kb["kb"])],
    )
    assert result.exit_code == 0
    assert "chưa commit" in result.output


def test_context_new_dirty_warning_goes_to_stderr_not_stdout(git_kb):
    (git_kb["kb"] / "demo-doc" / "ch1-records.md").write_text(
        "## 1.1 Airspace Records\n\nsua chua commit\n\n## 1.2 Airway Records\n\nx\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["context", "new", "--refs", "demo-doc §1.1", "--kb-dir", str(git_kb["kb"])],
    )
    assert result.exit_code == 0
    # stdout chỉ chứa block YAML thuần — pipe/copy không dính dòng warn
    assert "[warn]" not in result.stdout
    assert "chưa commit" in result.stderr
    ctx = kbcontext.parse(result.stdout)
    assert str(ctx.refs[0]) == "demo-doc §1.1"


def test_context_new_rejects_empty_refs(git_kb):
    result = runner.invoke(
        app, ["context", "new", "--refs", ",,", "--kb-dir", str(git_kb["kb"])]
    )
    assert result.exit_code == 1
    assert "rỗng" in result.output
    assert "kb-context:" not in result.stdout


def test_resolve_reads_block_from_file(git_kb, tmp_path_factory):
    ticket = tmp_path_factory.mktemp("ticket") / "tal-1.md"
    ticket.write_text(
        f"# TAL-1\n\nkb-context:\n  version: {git_kb['rev1']}\n  refs:\n"
        "    - demo-doc §1.1\n    - demo-doc §1.2\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app, ["resolve", str(ticket), "--kb-dir", str(git_kb["kb"])]
    )
    assert result.exit_code == 2  # có stale (§1.1), không broken
    assert "status=stale" in result.output
    assert "status=ok" in result.output


def test_resolve_broken_exits_1(git_kb, tmp_path_factory):
    ticket = tmp_path_factory.mktemp("ticket") / "tal-2.md"
    ticket.write_text(
        f"kb-context:\n  version: {git_kb['rev2']}\n  refs:\n    - demo-doc §9.9\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app, ["resolve", str(ticket), "--kb-dir", str(git_kb["kb"])]
    )
    assert result.exit_code == 1
    assert "status=broken" in result.output


def test_resolve_missing_file_exits_1_without_traceback(git_kb, tmp_path_factory):
    missing = tmp_path_factory.mktemp("ticket") / "khong-ton-tai.md"
    result = runner.invoke(
        app, ["resolve", str(missing), "--kb-dir", str(git_kb["kb"])]
    )
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "không đọc được file" in result.output
    assert str(missing) in result.output


def test_resolve_stdin(git_kb):
    block = f"kb-context:\n  version: {git_kb['rev2']}\n  refs:\n    - demo-doc §1.2\n"
    result = runner.invoke(
        app, ["resolve", "-", "--kb-dir", str(git_kb["kb"])], input=block
    )
    assert result.exit_code == 0
    assert "status=ok" in result.output
