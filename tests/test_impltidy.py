from pathlib import Path

from strata_kb import impltidy


def _flat(d: Path) -> None:
    d.mkdir(parents=True)
    (d / "ABC-12-design.md").write_text("d", encoding="utf-8")
    (d / "ABC-12-plan.md").write_text("p", encoding="utf-8")
    (d / "ABC-12-context.md").write_text("c", encoding="utf-8")
    (d / "ABC-12-review").mkdir()
    (d / "ABC-12-review" / "branch.diff").write_text("x", encoding="utf-8")
    (d / "M-stock-US2-plan.md").write_text("p2", encoding="utf-8")


def test_tidy_moves_every_flat_kind_into_the_ticket_folder(tmp_path: Path):
    d = tmp_path / "docs" / "impl"
    _flat(d)
    done, conflicts = impltidy.tidy(d)
    assert conflicts == []
    assert len(done) == 5
    assert (d / "ABC-12" / "design.md").read_text(encoding="utf-8") == "d"
    assert (d / "ABC-12" / "plan.md").read_text(encoding="utf-8") == "p"
    assert (d / "ABC-12" / "context.md").read_text(encoding="utf-8") == "c"
    assert (d / "ABC-12" / "review" / "branch.diff").read_text(encoding="utf-8") == "x"
    assert (d / "M-stock-US2" / "plan.md").read_text(encoding="utf-8") == "p2"
    assert not (d / "ABC-12-design.md").exists()
    assert not (d / "ABC-12-review").exists()


def test_tidy_is_idempotent(tmp_path: Path):
    d = tmp_path / "docs" / "impl"
    _flat(d)
    impltidy.tidy(d)
    assert impltidy.tidy(d) == ([], [])


def test_existing_destination_is_a_conflict_and_keeps_the_source(tmp_path: Path):
    d = tmp_path / "docs" / "impl"
    d.mkdir(parents=True)
    (d / "ABC-12-plan.md").write_text("old", encoding="utf-8")
    (d / "ABC-12").mkdir()
    (d / "ABC-12" / "plan.md").write_text("new", encoding="utf-8")
    done, conflicts = impltidy.tidy(d)
    assert done == []
    assert len(conflicts) == 1 and "ABC-12-plan.md" in conflicts[0]
    assert (d / "ABC-12-plan.md").read_text(encoding="utf-8") == "old"
    assert (d / "ABC-12" / "plan.md").read_text(encoding="utf-8") == "new"


def test_unrelated_entries_are_left_alone(tmp_path: Path):
    d = tmp_path / "docs" / "impl"
    d.mkdir(parents=True)
    for name in (".gitkeep", ".gitignore", "notes.md", "ABC-12-notes.md"):
        (d / name).write_text("", encoding="utf-8")
    (d / "ABC-9").mkdir()
    (d / "ABC-9" / "plan.md").write_text("", encoding="utf-8")
    assert impltidy.plan_moves(d) == []


def test_missing_impl_dir_is_nothing_to_do(tmp_path: Path):
    assert impltidy.tidy(tmp_path / "nowhere") == ([], [])
