from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from center_kb import models
from center_kb.llm import RunnerError
from center_kb.mdutils import slice_section

SECTION_PROMPT = """You are filling in summaries for a knowledge-base section.

Section {section_id} — {title}

<source>
{l3_body}
</source>

Write two summaries of the source text, following ALL rules:
- Write in English.
- l2_summary: condense the prose to ~20-30% of the original length, keep the \
logical structure.
- Preserve VERBATIM: codes (P, R, D...), record/field names (UR, PA...), \
numeric values, units, cross-references (§x.y). Never paraphrase technical terms.
- Do not invent anything that is not in the source. When unsure, keep the \
original sentence.
- Do not summarize, create, or delete tables (tables are handled separately).
- l1_summary: one sentence, max 25 words, stating what the section covers and \
what kind of data it contains.

Reply with ONLY a JSON object, no markdown fences, no commentary:
{{"l2_summary": "...", "l1_summary": "..."}}"""

DOC_PROMPT = """These are the one-line summaries of every section in the \
document "{title}":

{l1_lines}

Write ONE English sentence (max 30 words) summarizing what the whole document \
covers. Reply with ONLY a JSON object:
{{"summary": "..."}}"""


@dataclass(frozen=True)
class PendingSection:
    doc_id: str
    section_id: str
    title: str
    file: str  # stem without extension
    l3_body: str


def collect_pending(kb_dir: Path, doc_id: str | None = None) -> list[PendingSection]:
    index = models.load_yaml_model(kb_dir / "index.yaml", models.KBIndex)
    out: list[PendingSection] = []
    for entry in index.docs:
        if doc_id and entry.id != doc_id:
            continue
        manifest_path = kb_dir / entry.id / "_manifest.yaml"
        if not manifest_path.exists():
            continue
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
        raw_cache: dict[str, str] = {}
        for sec in manifest.sections:
            if sec.status != "pending":
                continue
            if sec.file not in raw_cache:
                raw_path = kb_dir / entry.id / f"{sec.file}.raw.md"
                raw_cache[sec.file] = (
                    raw_path.read_text(encoding="utf-8") if raw_path.exists() else ""
                )
            body = slice_section(raw_cache[sec.file], sec.id) or ""
            out.append(PendingSection(entry.id, sec.id, sec.title, sec.file, body))
    return out


def build_section_prompt(section: PendingSection) -> str:
    return SECTION_PROMPT.format(
        section_id=section.section_id, title=section.title, l3_body=section.l3_body
    )


def build_doc_prompt(title: str, l1_summaries: list[str]) -> str:
    return DOC_PROMPT.format(title=title, l1_lines="\n".join(f"- {s}" for s in l1_summaries))


def parse_json_reply(text: str, required: tuple[str, ...]) -> dict[str, str]:
    """Extract the first JSON object; every required key must be a non-empty str."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in reply")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("reply is not a JSON object")
    out: dict[str, str] = {}
    for key in required:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"missing or empty key: {key}")
        out[key] = value.strip()
    return out


def replace_marker(l2_text: str, section_id: str, summary: str) -> str:
    marker = f"<!-- TODO:summarize {section_id} -->"
    if marker not in l2_text:
        raise ValueError(f"marker not found: {marker}")
    return l2_text.replace(marker, summary, 1)


@dataclass
class SummarizeReport:
    summarized: list[str] = field(default_factory=list)  # "doc-id/section-id"
    failed: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


def _summarize_one(runner, section: PendingSection) -> dict[str, str]:
    prompt = build_section_prompt(section)
    last: Exception | None = None
    for _ in range(2):  # 1 try + exactly 1 retry (spec §3.3)
        try:
            return parse_json_reply(
                runner.run(prompt), ("l2_summary", "l1_summary")
            )
        except (RunnerError, ValueError) as exc:
            last = exc
    raise RunnerError(str(last))


def summarize_kb(
    kb_dir: Path,
    runner,
    doc_id: str | None = None,
    max_workers: int = 5,
    on_progress: Callable[[str], None] | None = None,
) -> SummarizeReport:
    """Fill pending sections via the runner. Workers only call the LLM;
    all file writes happen sequentially on the main thread."""
    say = on_progress or (lambda _msg: None)
    pending = collect_pending(kb_dir, doc_id)
    report = SummarizeReport()
    if not pending:
        return report

    results: dict[tuple[str, str], dict[str, str]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_summarize_one, runner, s): s for s in pending}
        for fut in as_completed(futures):
            s = futures[fut]
            key = f"{s.doc_id}/{s.section_id}"
            try:
                results[(s.doc_id, s.section_id)] = fut.result()
            except Exception as exc:  # noqa: BLE001 — one section must never abort the batch
                report.failed.append(key)
                say(f"[fail] {key}: {exc}")
            else:
                say(f"[ok] {key}")

    _apply_results(kb_dir, results, report)
    _fill_doc_summaries(kb_dir, runner, {s.doc_id for s in pending}, say)
    report.summarized.sort()
    report.failed.sort()
    return report


def _apply_results(
    kb_dir: Path,
    results: dict[tuple[str, str], dict[str, str]],
    report: SummarizeReport,
) -> None:
    by_doc: dict[str, dict[str, dict[str, str]]] = {}
    for (doc, sid), pair in results.items():
        by_doc.setdefault(doc, {})[sid] = pair
    for doc, pairs in by_doc.items():
        manifest_path = kb_dir / doc / "_manifest.yaml"
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
        l2_cache: dict[str, str] = {}
        for sec in manifest.sections:
            pair = pairs.get(sec.id)
            if pair is None:
                continue
            key = f"{doc}/{sec.id}"
            if sec.file not in l2_cache:
                l2_cache[sec.file] = (kb_dir / doc / f"{sec.file}.md").read_text(
                    encoding="utf-8"
                )
            try:
                l2_cache[sec.file] = replace_marker(
                    l2_cache[sec.file], sec.id, pair["l2_summary"]
                )
            except ValueError:
                report.failed.append(key)
                continue
            sec.summary = pair["l1_summary"]
            sec.status = "summarized"
            report.summarized.append(key)
        for stem, text in l2_cache.items():
            (kb_dir / doc / f"{stem}.md").write_text(text, encoding="utf-8")
        models.save_yaml_model(manifest_path, manifest)


def _fill_doc_summaries(
    kb_dir: Path, runner, doc_ids: set[str], say: Callable[[str], None]
) -> None:
    index_path = kb_dir / "index.yaml"
    index = models.load_yaml_model(index_path, models.KBIndex)
    changed = False
    for entry in index.docs:
        if entry.id not in doc_ids:
            continue
        manifest = models.load_yaml_model(
            kb_dir / entry.id / "_manifest.yaml", models.Manifest
        )
        if any(s.status == "pending" for s in manifest.sections):
            continue  # doc not complete yet
        prompt = build_doc_prompt(entry.title, [s.summary for s in manifest.sections])
        try:
            reply = parse_json_reply(runner.run(prompt), ("summary",))
        except (RunnerError, ValueError) as exc:
            say(f"[warn] doc summary failed for {entry.id}: {exc}")
            continue
        entry.summary = reply["summary"]
        changed = True
    if changed:
        models.save_yaml_model(index_path, index)
