"""Proves the Stage C load-bearing claim: `summarize_kb()`/`approve_sections()`/
`build_kb()` run UNMODIFIED over a `--scaffold-svc` document, with a stub LLM
runner standing in for the real CLI (hermetic — no network, no real LLM).

Brief deviations, both verified against the real `center_kb.summarize` source
before writing this file (per the task's Step 5 instruction; independently
re-verified by task review):

- There is no `summarize.resolve_runner()` to monkeypatch. `summarize_kb()`
  takes a `runner` object directly as its second argument (see
  `summarize.py::summarize_kb`); runner *resolution* (CLI flag > config >
  auto-detect) lives in `cli._resolve_runner()`, which this hermetic test has
  no reason to touch. So `_StubRunner` is simply passed straight in — no
  monkeypatch needed, and `summarize.py` is untouched, as required.
- `parse_json_reply()` requires the keys `"l2_summary"` / `"l1_summary"` for a
  section prompt and `"summary"` for the doc-level prompt (see
  `SECTION_PROMPT`/`DOC_PROMPT`'s output contracts, `_summarize_one()`, and
  `_fill_doc_summaries()`), not the brief's guessed `{"summary", "l2"}`.
  `parse_json_reply()` only reads the keys it is asked for, so `_StubRunner`
  returns all three in one JSON object and serves both call sites (task
  review, Important 2 — see below).
- `review.approve_sections(kb, doc_id, section_ids=None)` treats `None` as
  "every section" and `[]` as "an explicit empty selection" (`wanted = set()`
  matches nothing) — the brief's literal `[]` call would approve zero
  sections. The third argument is omitted below to approve the whole
  document, which is what the test is actually asserting.
"""
from pathlib import Path

import pytest

from center_kb import models, review, summarize, svcnote
from center_kb.build import build_kb
from center_kb.codeingest import core
from tests.fixtures_coderepo import build_code_repo


class _StubRunner:
    """Stands in for the LLM CLI: returns the JSON shape summarize_kb expects.

    Task review, Important 2: `summarize_kb()` ends by calling
    `_fill_doc_summaries()`, which asks `parse_json_reply()` for the
    `"summary"` key alone (`summarize.py:362`) — a reply carrying only
    `l2_summary`/`l1_summary` makes that parse raise, get caught, and get
    reported through the (here, absent) `on_progress` callback, so the whole
    doc-summary leg silently no-ops with no test-visible signal. Returning
    all three keys in one JSON object proves both legs: `parse_json_reply()`
    reads only the keys it's asked for, so the very same reply satisfies
    `_summarize_one()`'s `("l2_summary", "l1_summary")` request and
    `_fill_doc_summaries()`'s `("summary",)` request.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def run(self, prompt: str) -> str:
        self.calls.append(prompt)
        return (
            '{"l2_summary": "Drafted responsibility for this service.", '
            '"l1_summary": "Drafted responsibility for this service.", '
            '"summary": "Drafted responsibility summary for this document."}'
        )


def _seed(tmp_path: Path) -> Path:
    root = build_code_repo(tmp_path)
    core.run(
        core.CodeIngestOptions(
            repo_root=root, kb_dir=root / ".kb", doc_id="demo-code",
            repo_id="demo", scaffold_svc=True,
        )
    )
    return root


def test_scaffolded_svc_sections_are_pending_and_visible_to_summarize(tmp_path):
    root = _seed(tmp_path)
    pending = summarize.collect_pending(root / ".kb", "demo-svc")
    assert pending
    assert all(p.doc_id == "demo-svc" for p in pending)


def test_the_prompt_material_is_the_l3_code_evidence(tmp_path):
    root = _seed(tmp_path)
    pending = summarize.collect_pending(root / ".kb", "demo-svc")
    section = next(p for p in pending if p.section_id == "svc.airspace-service")
    prompt = summarize.build_section_prompt(section)
    # Task review, Important 3 (overrules the brief's literal assertion):
    # `SECTION_PROMPT` interpolates "Section {section_id} — {title}"
    # (summarize.py:16), and the section id IS "svc.airspace-service" — so
    # `"airspace" in prompt.lower()` is satisfied by the id alone and would
    # stay green even if `{l3_body}` (the actual L3 evidence) were empty.
    # Assert real evidence instead, the same tightening
    # test_codeingest_scaffold.py:38-55 already applied to its sibling test
    # for the identical reason.
    assert "src/airspace/service.py" in prompt
    assert "image: airspace:1.0" in prompt


def test_summarize_then_approve_reaches_reviewed_and_builds_clean(tmp_path):
    root = _seed(tmp_path)
    kb = root / ".kb"
    runner = _StubRunner()
    report = summarize.summarize_kb(kb, runner, doc_id="demo-svc")
    assert report.ok

    manifest_path = kb / "demo-svc" / "_manifest.yaml"
    sections = models.load_yaml_model(manifest_path, models.Manifest).sections
    # Minor 4: guard against `all(...)` passing vacuously over an empty list.
    assert len(sections) >= 2  # svc.airspace-service + svc.postgres
    assert all(s.status == "summarized" and s.summary for s in sections)

    # Minor 5 / Important 3 at the summarize_kb level: prove the runner was
    # actually driven off EACH section's own L3 evidence — not merely that
    # some JSON came back for some prompt. Matched by section id (embedded
    # verbatim in SECTION_PROMPT) rather than by call order, since the
    # ThreadPoolExecutor in summarize_kb does not guarantee submission order.
    section_calls = [
        c for c in runner.calls
        if c.startswith("You are filling in summaries for a knowledge-base section.")
    ]
    assert len(section_calls) == 2
    for call in section_calls:
        if "svc.airspace-service" in call:
            assert "src/airspace/service.py" in call
        elif "svc.postgres" in call:
            assert "image: postgres:16" in call
        else:
            pytest.fail(f"unexpected section prompt: {call[:120]!r}")

    # Important 2: the L0/doc-summary leg of summarize_kb (_fill_doc_summaries)
    # must also be proven, not left as a silent no-op — it only fires once
    # every section of the doc is non-pending, and only succeeds now that the
    # stub supplies the "summary" key it asks for. A mere non-empty check
    # would be vacuous here: `--scaffold-svc` already writes a non-empty
    # PLACEHOLDER summary ("Curated service knowledge for the {repo_id}
    # repository.", core.py's scaffold_svc()) before summarize_kb ever runs,
    # so an empty-vs-non-empty check can't tell "the doc-summary leg ran and
    # won" apart from "it silently no-opped and the placeholder survived".
    # Assert the exact drafted text instead — the doc-summary leg is the
    # only path that can ever produce it.
    index = models.load_yaml_model(kb / "index.yaml", models.KBIndex)
    svc_entry = next(e for e in index.docs if e.id == "demo-svc")
    assert svc_entry.summary == "Drafted responsibility summary for this document."

    review.approve_sections(kb, "demo-svc", by="sme <sme@x>")
    sections = models.load_yaml_model(manifest_path, models.Manifest).sections
    assert len(sections) >= 2
    assert all(s.status == "reviewed" for s in sections)
    assert build_kb(kb).ok


def test_summarize_leaves_the_generated_document_untouched(tmp_path):
    root = _seed(tmp_path)
    kb = root / ".kb"
    before = {p.name: p.read_bytes() for p in sorted((kb / "demo-code").iterdir())}
    # Minor 4: guard against `after == before` passing vacuously over {} == {}.
    assert before
    summarize.summarize_kb(kb, _StubRunner(), doc_id="demo-svc")
    after = {p.name: p.read_bytes() for p in sorted((kb / "demo-code").iterdir())}
    assert after == before


# Final review, Important 2: `--scaffold-svc` is not a one-time-only
# command — `dev-code-seed` step 2 runs it, and the documented amend loop
# (QUICKSTART-dev.md's "Keeping it current" section) re-runs it on every
# ticket that touches a service, forever after. `_upsert_index_entry`
# (core.py) used to set `entry.summary` unconditionally on every call,
# including `scaffold_svc()`'s own call, which always passes the same
# static placeholder ("Curated service knowledge for the {repo_id}
# repository."). Once `_fill_doc_summaries` has drafted the document's
# real L0 summary (proven above, `test_summarize_then_approve_reaches_
# reviewed_and_builds_clean`), THAT text is the only thing a re-run must
# never destroy — `_fill_doc_summaries` itself can never restore it: it
# skips a document with no pending sections (summarize.py:358-359), and
# every svc.* section is non-pending forever after this run.
def test_scaffold_svc_rerun_preserves_the_drafted_doc_summary(tmp_path):
    root = _seed(tmp_path)
    kb = root / ".kb"
    report = summarize.summarize_kb(kb, _StubRunner(), doc_id="demo-svc")
    assert report.ok
    index = models.load_yaml_model(kb / "index.yaml", models.KBIndex)
    drafted = next(e for e in index.docs if e.id == "demo-svc").summary
    assert drafted == "Drafted responsibility summary for this document."

    # The routine re-run: dev-code-seed step 2 / the documented amend loop,
    # nothing else changed in the repo.
    core.run(
        core.CodeIngestOptions(
            repo_root=root, kb_dir=kb, doc_id="demo-code",
            repo_id="demo", scaffold_svc=True,
        )
    )

    index_after = models.load_yaml_model(kb / "index.yaml", models.KBIndex)
    entry_after = next(e for e in index_after.docs if e.id == "demo-svc")
    assert entry_after.summary == drafted


# Final review, Recommendation (the highest-value item in this fix round):
# every leg of the seed flow was tested in isolation, but never the real
# SEQUENCE — scaffold -> summarize -> approve -> `kb svc note` -> `kb
# code-ingest --scaffold-svc` again -> strict `build_kb` — and both this
# round's Important findings live exactly in the joins between two of
# those steps. This test walks that exact order once and asserts what
# must survive each hop.
def test_full_seed_sequence_survives_every_hop_in_order(tmp_path):
    root = _seed(tmp_path)
    kb = root / ".kb"
    manifest_path = kb / "demo-svc" / "_manifest.yaml"

    # 1. scaffold already happened via _seed(): svc.* pending, no hist.*.
    pending = summarize.collect_pending(kb, "demo-svc")
    assert {p.section_id for p in pending} == {"svc.airspace-service", "svc.postgres"}

    # 2. summarize (stub runner): every svc.* section drafted, AND the
    #    document's own L0 summary drafted (Important 2's load-bearing text).
    report = summarize.summarize_kb(kb, _StubRunner(), doc_id="demo-svc")
    assert report.ok
    index = models.load_yaml_model(kb / "index.yaml", models.KBIndex)
    drafted_doc_summary = next(e for e in index.docs if e.id == "demo-svc").summary
    assert drafted_doc_summary == "Drafted responsibility summary for this document."

    # 3. approve: every svc.* section flips summarized -> reviewed.
    approve_report = review.approve_sections(kb, "demo-svc", by="sme <sme@x>")
    assert set(approve_report.flipped) == {"svc.airspace-service", "svc.postgres"}
    sections = models.load_yaml_model(manifest_path, models.Manifest).sections
    svc_sections = [s for s in sections if s.id.startswith("svc.")]
    assert len(svc_sections) == 2
    assert all(s.status == "reviewed" for s in svc_sections)

    # 4. kb svc note: a ticket touching airspace-service appends hist.*.
    note_report = svcnote.add_note(
        kb, "demo", "airspace-service",
        svcnote.Note(
            ticket="M-airspace-US4", title="Approve time-bound airspace",
            refs=("ATM-STD §5.3",),
        ),
    )
    assert note_report.action == "created"
    assert note_report.section_id == "hist.airspace-service"

    # 5. kb code-ingest --scaffold-svc AGAIN — the routine re-run that is
    #    both dev-code-seed step 2 and the documented amend loop, nothing
    #    else changed in the repo. Must NOT touch the drafted doc summary
    #    (Important 2), the reviewed svc.* prose (spec 8.2's "refresh L3
    #    evidence only" rule, already covered elsewhere but re-proven
    #    here in sequence), or the hist.* row `kb svc note` just wrote
    #    (scaffold_svc() passes flow./hist.* entries through untouched).
    core.run(
        core.CodeIngestOptions(
            repo_root=root, kb_dir=kb, doc_id="demo-code",
            repo_id="demo", scaffold_svc=True,
        )
    )

    index_after = models.load_yaml_model(kb / "index.yaml", models.KBIndex)
    doc_summary_after = next(e for e in index_after.docs if e.id == "demo-svc").summary
    assert doc_summary_after == drafted_doc_summary

    sections_after = models.load_yaml_model(manifest_path, models.Manifest).sections
    svc_after = {s.id: s for s in sections_after if s.id.startswith("svc.")}
    assert set(svc_after) == {"svc.airspace-service", "svc.postgres"}
    assert all(s.status == "reviewed" for s in svc_after.values())

    hist_entry = next(s for s in sections_after if s.id == "hist.airspace-service")
    assert hist_entry.status == "summarized"
    history_l2 = (kb / "demo-svc" / "history.md").read_text(encoding="utf-8")
    assert "M-airspace-US4" in history_l2
    assert "Approve time-bound airspace" in history_l2

    # 6. strict build_kb (no --allow-pending) must pass clean end to end.
    strict = build_kb(kb)
    assert strict.ok, strict.errors
