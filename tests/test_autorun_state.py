from __future__ import annotations

import json
import logging

from strata_kb.autorun.state import AutoState, load, log_dir, save

EMPTY = AutoState(task=None, attempts=0, waiting_on=(), stop_reason=None, updated_at="")


def test_load_missing_file_gives_empty_state(tmp_path):
    assert load(tmp_path) == EMPTY


def test_save_then_load_round_trips(tmp_path):
    state = AutoState(
        task="dev-implement-ticket:M-x-US3",
        attempts=2,
        waiting_on=(4, 7),
        stop_reason="usage-limit",
        updated_at="ignored",
    )

    save(tmp_path, state)
    got = load(tmp_path)

    assert got.task == state.task and got.attempts == 2
    assert got.waiting_on == (4, 7) and got.stop_reason == "usage-limit"
    assert got.updated_at.endswith("+00:00") and got.updated_at != "ignored"


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path):
    save(tmp_path, EMPTY)
    save(tmp_path, EMPTY)

    assert [p.name for p in (tmp_path / "auto").iterdir()] == ["state.json"]


def test_load_unparsable_file_warns_and_gives_empty_state(tmp_path, caplog):
    (tmp_path / "auto").mkdir()
    (tmp_path / "auto" / "state.json").write_text("{not json", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        assert load(tmp_path) == EMPTY

    assert "state.json" in caplog.text


def test_load_wrong_shape_gives_empty_state(tmp_path):
    (tmp_path / "auto").mkdir()
    (tmp_path / "auto" / "state.json").write_text(
        json.dumps({"attempts": "many"}), encoding="utf-8"
    )

    assert load(tmp_path) == EMPTY


def test_log_dir_is_created(tmp_path):
    path = log_dir(tmp_path)

    assert path == tmp_path / "auto" / "logs" and path.is_dir()
