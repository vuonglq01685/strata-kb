from __future__ import annotations

import json
import logging

from strata_kb.autorun import runlog
from strata_kb.autorun.claude import TaskResult


def _append(kb_dir, **kw):
    runlog.append(
        kb_dir,
        skill="s",
        arg="a",
        attempt=0,
        result=kw.pop("result", TaskResult("done")),
        started_at="t0",
        ended_at="t1",
        head_before=None,
        head_after="abc",
    )


def test_append_writes_one_schema1_line(tmp_path):
    _append(tmp_path)
    _append(tmp_path, result=TaskResult("blocked-qa", (3,), "why"))
    lines = (tmp_path / "auto" / runlog.RUNS_NAME).read_text().splitlines()
    rows = [json.loads(line) for line in lines]
    assert len(rows) == 2
    assert all(r["schema"] == 1 for r in rows)
    assert rows[0]["run_id"] != rows[1]["run_id"]
    assert rows[1]["outcome"] == "blocked-qa"
    assert rows[1]["ids"] == [3]
    assert rows[0]["head_after"] == "abc"


def test_append_oserror_only_warns(tmp_path, caplog):
    (tmp_path / "auto").write_text("x")
    with caplog.at_level(logging.WARNING):
        _append(tmp_path)
    assert "runs.jsonl" in caplog.text


def test_head_is_the_full_sha(tmp_path, run_git):
    run_git(tmp_path, "init")
    (tmp_path / "f").write_text("x")
    run_git(tmp_path, "add", "-A")
    run_git(tmp_path, "commit", "-m", "c")
    assert runlog.head(tmp_path) == run_git(tmp_path, "rev-parse", "HEAD")
    assert len(runlog.head(tmp_path)) == 40
