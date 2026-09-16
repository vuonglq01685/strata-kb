import json
import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from center_kb import models
from center_kb.cli import app
from tests.fixtures_coderepo import build_code_repo

runner = CliRunner()


def _init_config(root: Path, repo_id: str = "demo") -> None:
    (root / ".kb").mkdir(exist_ok=True)
    (root / ".kb" / "config.yaml").write_text(
        f'kind: dev\nhub: ""\nrepo_id: "{repo_id}"\nintake: ""\n', encoding="utf-8"
    )


def test_code_ingest_writes_the_document_and_reports(tmp_path):
    root = build_code_repo(tmp_path)
    _init_config(root)
    result = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb")])
    assert result.exit_code == 0, result.output
    assert (root / ".kb" / "demo-code" / "_manifest.yaml").is_file()
    assert "services" in result.output


def test_json_output_shape(tmp_path):
    root = build_code_repo(tmp_path)
    _init_config(root)
    result = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb"), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    for key in ("doc_id", "sections_by_extractor", "files_written", "warnings",
                "detected", "dirty_tree"):
        assert key in payload
    assert payload["doc_id"] == "demo-code"


def test_repo_id_comes_from_config_and_doc_id_is_derived(tmp_path):
    root = build_code_repo(tmp_path)
    _init_config(root, repo_id="dashboard")
    result = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb"), "--json"])
    assert json.loads(result.output)["doc_id"] == "dashboard-code"


def test_explicit_doc_id_overrides(tmp_path):
    root = build_code_repo(tmp_path)
    _init_config(root)
    result = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb"),
                                "--doc-id", "custom-code", "--json"])
    assert json.loads(result.output)["doc_id"] == "custom-code"


def test_db_flag_is_repeatable(tmp_path):
    root = build_code_repo(tmp_path)
    _init_config(root)
    for name in ("a.db", "b.db"):
        con = sqlite3.connect(root / name)
        con.execute(f"CREATE TABLE t_{name[0]} (id INTEGER)")
        con.commit()
        con.close()
    result = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb"),
                                "--db", str(root / "a.db"),
                                "--db", str(root / "b.db")])
    assert result.exit_code == 0, result.output
    db_md = (root / ".kb" / "demo-code" / "db.md").read_text(encoding="utf-8")
    assert "t_a" in db_md and "t_b" in db_md


def test_tags_flag_appends_to_the_reserved_tags(tmp_path):
    root = build_code_repo(tmp_path)
    _init_config(root)
    runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                        "--kb-dir", str(root / ".kb"), "--tags", "team-x,platform"])
    index = models.load_yaml_model(root / ".kb" / "index.yaml", models.KBIndex)
    entry = next(d for d in index.docs if d.id == "demo-code")
    assert entry.tags == ["code", "generated", "team-x", "platform"]


def test_scaffold_svc_flag_creates_the_curated_document(tmp_path):
    root = build_code_repo(tmp_path)
    _init_config(root)
    result = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb"), "--scaffold-svc"])
    assert result.exit_code == 0, result.output
    assert (root / ".kb" / "demo-svc" / "_manifest.yaml").is_file()


def test_exit_1_when_only_the_tree_extractor_detects(tmp_path):
    root = tmp_path / "bare"
    (root / "src").mkdir(parents=True)
    (root / "src" / "notes.txt").write_text("hello", encoding="utf-8")
    _init_config(root)
    result = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb")])
    assert result.exit_code == 1
    assert "no code artifacts" in result.output.lower()


def test_build_is_not_called_implicitly(tmp_path):
    root = build_code_repo(tmp_path)
    _init_config(root)
    result = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb")])
    assert result.exit_code == 0
    assert "kb build: OK" not in result.output


# ---------------------------------------------------------------------------
# Ruling R3 — `--db` must be reachable even when no migration/prisma/alembic/
# EF source exists to make SchemaExtractor.detect() fire on its own.
# ---------------------------------------------------------------------------


def test_db_flag_works_with_no_migration_files_present(tmp_path):
    root = tmp_path / "nodb"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    _init_config(root)
    con = sqlite3.connect(root / "only.db")
    con.execute("CREATE TABLE widgets (id INTEGER)")
    con.commit()
    con.close()
    result = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb"),
                                "--db", str(root / "only.db")])
    assert result.exit_code == 0, result.output
    db_md = (root / ".kb" / "demo-code" / "db.md").read_text(encoding="utf-8")
    assert "widgets" in db_md


# ---------------------------------------------------------------------------
# Ruling R4 — `--repo-id` falls back to the repo-root folder name when
# neither the flag nor `.kb/config.yaml` supplies one.
# ---------------------------------------------------------------------------


def test_repo_id_falls_back_to_folder_name_when_unconfigured(tmp_path):
    root = tmp_path / "my-service"
    build_code_repo(root)
    # Deliberately no _init_config(root) call: no .kb/config.yaml at all.
    result = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb"), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["doc_id"] == "my-service-code"


# ---------------------------------------------------------------------------
# G-11 — a relative `--kb-dir` resolves against the process's current
# working directory, like every other `kb` command's --kb-dir.
# ---------------------------------------------------------------------------


def test_kb_dir_relative_path_resolves_against_cwd_like_every_other_kb_command(tmp_path, monkeypatch):
    # Reviewer G-11: resolving against --repo-root was undocumented and
    # created directories inside a repo the reviewer had been told not to touch.
    root = tmp_path / "proj"
    build_code_repo(root)
    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)
    result = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", "out/.kb", "--repo-id", "demo"])
    assert result.exit_code == 0, result.output
    assert (other_cwd / "out" / ".kb" / "demo-code" / "_manifest.yaml").is_file()
    assert not (root / "out").exists()


# ---------------------------------------------------------------------------
# Review round 2 — Important 5: the CLI must degrade (exit 0, a named
# warning), never crash with an uncaught traceback, on a wrong-shaped
# index.yaml or -code _manifest.yaml. Reproduced through the real CLI, as
# the reviewer did.
# ---------------------------------------------------------------------------


def test_cli_degrades_on_wrong_shaped_index_yaml(tmp_path):
    root = build_code_repo(tmp_path)
    _init_config(root)
    (root / ".kb" / "index.yaml").write_text("- a\n- b\n", encoding="utf-8")
    result = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb")])
    assert result.exit_code == 0, result.output
    assert (root / ".kb" / "demo-code" / "_manifest.yaml").is_file()


def test_cli_refuses_a_wrong_shaped_existing_code_manifest_without_a_traceback(tmp_path):
    # Review round 2 wanted no traceback here; reviewer G-1 wants no
    # overwrite either: an unreadable manifest at the -code slot means
    # nobody can tell whose document this is, so it is refused, intact.
    root = build_code_repo(tmp_path)
    _init_config(root)
    first = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb")])
    assert first.exit_code == 0, first.output
    manifest = root / ".kb" / "demo-code" / "_manifest.yaml"
    manifest.write_text("- a\n- b\n", encoding="utf-8")
    result = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb")])
    assert result.exit_code == 1
    assert "could not read" in result.output          # the guarded-load warning
    assert "did not generate" in result.output
    assert "Traceback" not in result.output
    assert manifest.read_text(encoding="utf-8") == "- a\n- b\n"


# ---------------------------------------------------------------------------
# Review round 3 -- folded item: on a --scaffold-svc refusal, the CLI must
# surface any warnings already collected (e.g. the real reason a corrupt
# -svc manifest looks "stray") and call out that the -code document was
# already written -- a partial success, not a full failure.
# ---------------------------------------------------------------------------


def test_cli_surfaces_warnings_and_partial_success_when_svc_scaffold_refuses(tmp_path):
    root = build_code_repo(tmp_path)
    _init_config(root)
    first = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb"), "--scaffold-svc"])
    assert first.exit_code == 0, first.output
    (root / ".kb" / "demo-svc" / "_manifest.yaml").write_text(
        "- a\n- b\n", encoding="utf-8"
    )

    result = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb"), "--scaffold-svc"])

    assert result.exit_code == 1
    assert "could not read" in result.output
    assert "_manifest.yaml" in result.output
    assert "partial success" in result.output.lower()


# ---------------------------------------------------------------------------
# Review round 4 -- item 3: the [warn]/[note] lines (and the pre-existing
# str(exc) line) must go to stderr, not stdout, so --json's stdout purity
# guarantee holds on the failure path too, not just the success path.
# ---------------------------------------------------------------------------


def test_json_flag_keeps_stdout_pure_on_failure(tmp_path):
    root = build_code_repo(tmp_path)
    _init_config(root)
    first = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb"), "--scaffold-svc"])
    assert first.exit_code == 0, first.output
    (root / ".kb" / "demo-svc" / "_manifest.yaml").write_text(
        "- a\n- b\n", encoding="utf-8"
    )

    result = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb"), "--scaffold-svc", "--json"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "could not read" in result.stderr
    assert "_manifest.yaml" in result.stderr
    assert "partial success" in result.stderr.lower()


# ---------------------------------------------------------------------------
# Controller Ruling R47 — the exact end-to-end reproduction from the task
# brief, run through the real CLI: `--doc-id "demo-svc/"` against a curated
# `.kb/demo-svc/` used to exit 0 and overwrite it.
# ---------------------------------------------------------------------------


def test_trailing_slash_doc_id_no_longer_overwrites_the_curated_svc_dir(tmp_path):
    root = build_code_repo(tmp_path)
    _init_config(root)
    scaffold = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                  "--kb-dir", str(root / ".kb"), "--scaffold-svc"])
    assert scaffold.exit_code == 0, scaffold.output
    svc_dir = root / ".kb" / "demo-svc"
    original_services_md = (svc_dir / "services.md").read_text(encoding="utf-8")
    original_manifest = (svc_dir / "_manifest.yaml").read_text(encoding="utf-8")

    result = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb"),
                                "--doc-id", "demo-svc/"])

    assert result.exit_code == 1
    assert (svc_dir / "services.md").read_text(encoding="utf-8") == original_services_md
    assert (svc_dir / "_manifest.yaml").read_text(encoding="utf-8") == original_manifest
    index = models.load_yaml_model(root / ".kb" / "index.yaml", models.KBIndex)
    assert sorted(d.id for d in index.docs) == ["demo-code", "demo-svc"]


def test_a_second_scaffold_svc_run_still_succeeds_over_fire_check(tmp_path):
    """Over-fire re-check, at the CLI: the guard must never block the
    command whose actual job is to maintain the curated document it
    itself created."""
    root = build_code_repo(tmp_path)
    _init_config(root)
    first = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb"), "--scaffold-svc"])
    assert first.exit_code == 0, first.output
    second = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                 "--kb-dir", str(root / ".kb"), "--scaffold-svc"])
    assert second.exit_code == 0, second.output
    assert (root / ".kb" / "demo-svc" / "_manifest.yaml").is_file()


def test_tags_curated_does_not_brick_a_second_plain_code_run_at_the_cli(tmp_path):
    """Controller Ruling R47c, at the CLI: --tags curated on an ordinary
    -code run must not make the document's own next run refuse itself."""
    root = build_code_repo(tmp_path)
    _init_config(root)
    first = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb"), "--tags", "curated"])
    assert first.exit_code == 0, first.output
    second = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                 "--kb-dir", str(root / ".kb"), "--tags", "curated"])
    assert second.exit_code == 0, second.output


# ---------------------------------------------------------------------------
# Task review, Important 5 -- spec Sec8.3 asks for "stale-risk: svc.<name>"
# "in the report and in --json"; the terminal used to print only counts,
# leaving the Dev with no way to know *which* service(s) without --json --
# and Stage C's machine consumer of --json does not exist yet, so the
# terminal is the only surface a Dev actually has today.
# ---------------------------------------------------------------------------


def test_stale_risk_and_orphan_ids_are_named_on_the_terminal_not_just_counted(tmp_path):
    root = build_code_repo(tmp_path)
    _init_config(root)
    first = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb"), "--scaffold-svc"])
    assert first.exit_code == 0, first.output

    manifest_path = root / ".kb" / "demo-svc" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    for sec in manifest.sections:
        sec.status = "reviewed"
        sec.summary = "Reviewed by a human."
    models.save_yaml_model(manifest_path, manifest)

    # Change service evidence (stale-risk for the surviving service) and
    # remove one service outright (orphan for the one that disappears).
    (root / "docker-compose.yml").write_text(
        "services:\n  airspace-service:\n    image: airspace:1.0\n"
        "    ports:\n      - \"9090:9090\"\n",
        encoding="utf-8",
    )
    second = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                 "--kb-dir", str(root / ".kb"), "--scaffold-svc"])
    assert second.exit_code == 0, second.output
    assert "svc.airspace-service" in second.output
    assert "svc.postgres" in second.output
