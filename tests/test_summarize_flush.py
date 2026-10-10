"""2026-10-10 review §6.2 F12: summarize wrote nothing until every section's
call had returned -- a crash in an hours-long run lost every paid-for call.
Results are now written every FLUSH_EVERY sections, with the same final
files as one write at the end."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from strata_kb import models, summarize


@pytest.fixture(autouse=True)
def _no_retry_pause(monkeypatch):
    monkeypatch.setattr(summarize, "RETRY_PAUSE_SECONDS", 0, raising=False)


def _kb(tmp_path: Path, n: int) -> Path:
    """One doc, n llm-sized sections in one file; ids repeat every 4th so
    marker occurrences must stay right across flushes."""
    kb = tmp_path / ".kb"
    doc = kb / "d1"
    doc.mkdir(parents=True)
    ids = [("R" if i % 4 == 0 else f"{i}") for i in range(n)]
    body = "Prose that is long enough to need a model call. " * 6
    (doc / "ch1.raw.md").write_text(
        "".join(f"## {sid} T{i}\n\n{body}{i}\n\n" for i, sid in enumerate(ids)), encoding="utf-8")
    (doc / "ch1.md").write_text(
        "".join(f"## {sid} T{i}\n\n<!-- TODO:summarize {sid} -->\n\n" for i, sid in enumerate(ids)),
        encoding="utf-8")
    models.save_yaml_model(doc / "_manifest.yaml", models.Manifest(
        id="d1", title="Doc", sections=[
            models.SectionEntry(id=sid, title=f"T{i}", file="ch1") for i, sid in enumerate(ids)
        ]))
    models.save_yaml_model(kb / "index.yaml", models.KBIndex(docs=[models.IndexEntry(id="d1", title="Doc")]))
    return kb


class Runner:
    name = "fake"

    def __init__(self, crash_after: int | None = None):
        self.calls = 0
        self.crash_after = crash_after

    def run(self, prompt: str) -> str:
        self.calls += 1
        if self.crash_after is not None and self.calls > self.crash_after:
            raise KeyboardInterrupt  # not an Exception: aborts the run
        if "one-line summaries" in prompt:
            return json.dumps({"summary": "Doc summary."})
        tag = prompt.split("Prose that")[0][-40:].split("## ")[-1].split("\n")[0]
        return json.dumps({"l2_summary": f"L2 for {tag}.", "l1_summary": f"L1 {tag}"})


def _state(kb: Path):
    return (
        (kb / "d1" / "ch1.md").read_text(encoding="utf-8"),
        models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest).model_dump(
            exclude={"sections": {"__all__": {"provenance"}}}
        ),
    )


def test_flushing_in_batches_writes_what_one_final_write_would(tmp_path, monkeypatch):
    one = _kb(tmp_path / "one", 23)
    monkeypatch.setattr(summarize, "FLUSH_EVERY", 10_000)
    summarize.summarize_kb(one, Runner(), max_workers=1)
    batched = _kb(tmp_path / "batched", 23)
    monkeypatch.setattr(summarize, "FLUSH_EVERY", 4)
    report = summarize.summarize_kb(batched, Runner(), max_workers=1)
    assert len(report.summarized) == 23 and report.ok
    assert _state(one) == _state(batched)
    assert "TODO:summarize" not in _state(batched)[0]


def test_a_crash_mid_run_keeps_every_flushed_section(tmp_path, monkeypatch):
    kb = _kb(tmp_path, 30)
    monkeypatch.setattr(summarize, "FLUSH_EVERY", 5)
    with pytest.raises(KeyboardInterrupt):
        summarize.summarize_kb(kb, Runner(crash_after=12), max_workers=1)
    manifest = models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest)
    done = [s for s in manifest.sections if s.status == "summarized"]
    assert len(done) == 10  # two flushes of 5 landed before call 13 crashed
    l2 = (kb / "d1" / "ch1.md").read_text(encoding="utf-8")
    assert l2.count("TODO:summarize") == 20
