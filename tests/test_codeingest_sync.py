from pathlib import Path

import strata_kb
from strata_kb.codeingest import sync
from strata_kb.config import load_config


def _pin(root: Path, version: str) -> None:
    wf = root / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "kb-code.yml").write_text(
        f"jobs:\n  publish:\n    steps:\n      - run: pip install strata-kb=={version}\n",
        encoding="utf-8",
    )


def _config(root: Path, extra: str = "") -> Path:
    kb = root / ".kb"
    kb.mkdir(exist_ok=True)
    (kb / "config.yaml").write_text(f'kind: dev\nrepo_id: "demo"\n{extra}', encoding="utf-8")
    return kb


def test_config_without_the_block_has_empty_lists(tmp_path):
    cfg = load_config(_config(tmp_path)).code_ingest
    assert cfg.db == [] and cfg.tags == []


def test_ci_pin_reads_the_workflow_pin(tmp_path):
    _pin(tmp_path, "1.3.0")
    assert sync.ci_pin(tmp_path) == "1.3.0"


def test_ci_pin_is_none_without_the_workflow(tmp_path):
    assert sync.ci_pin(tmp_path) is None


def test_version_note_only_when_the_pin_differs(tmp_path, monkeypatch):
    _pin(tmp_path, "1.3.0")
    monkeypatch.setattr(strata_kb, "__version__", "1.3.0")
    assert sync.version_note(tmp_path) is None
    monkeypatch.setattr(strata_kb, "__version__", "1.4.0")
    note = sync.version_note(tmp_path)
    assert note is not None and "1.4.0" in note and "1.3.0" in note


def test_options_from_config_uses_the_code_ingest_block(tmp_path):
    kb = _config(tmp_path, "code_ingest:\n  db: [data/app.sqlite]\n  tags: [payments]\n")
    opts = sync.options_from_config(tmp_path, kb, "demo")
    assert opts.doc_id == "demo-code"
    assert opts.db_paths == ((tmp_path / "data" / "app.sqlite").resolve(),)
    assert opts.tags == ("payments",)


def test_flags_replace_the_config_lists(tmp_path):
    kb = _config(tmp_path, "code_ingest:\n  db: [data/app.sqlite]\n  tags: [payments]\n")
    opts = sync.options_from_config(
        tmp_path, kb, "demo", db=[Path("other.sqlite")], tags=["x"]
    )
    assert opts.db_paths == ((tmp_path / "other.sqlite").resolve(),)
    assert opts.tags == ("x",)
