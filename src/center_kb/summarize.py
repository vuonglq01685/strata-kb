from __future__ import annotations

import json
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from center_kb import models
from center_kb.llm import RunnerError
from center_kb.mdutils import slice_section

SECTION_PROMPT = """You are filling in summaries for a knowledge-base section.

Section {section_id} — {title}

The source below is prose only — tables were removed and replaced with
[table omitted] markers. The tables are preserved verbatim elsewhere; they
are NOT your concern.

<source>
{l3_body}
</source>

Write two summaries of the source text, following ALL rules:
- Write both summaries in the SAME LANGUAGE as the source text above. Never \
translate: if the source is English, answer in English; if it is Vietnamese, \
answer in Vietnamese; and so on.
- l2_summary: condense the prose to ~20-30% of the original length, keep the \
logical structure. HARD LIMIT: l2_summary must be at most {max_chars} \
characters — if your draft is longer, compress harder before replying.
- Never describe, list, or reconstruct table contents; ignore \
[table omitted] markers entirely.
- Preserve VERBATIM: codes (P, R, D...), record/field names (UR, PA...), \
numeric values, units, cross-references (§x.y). Never paraphrase technical terms.
- Do not invent anything that is not in the source. When unsure, keep the \
original sentence.
- l1_summary: one sentence, max 25 words, stating what the section covers and \
what kind of data it contains.

Reply with ONLY a JSON object, no markdown fences, no commentary:
{{"l2_summary": "...", "l1_summary": "..."}}"""

DOC_PROMPT = """These are the one-line summaries of every section in the \
document "{title}":

{l1_lines}

Write ONE sentence (max 30 words) summarizing what the whole document covers, \
in the SAME LANGUAGE as the section summaries above. Never translate. \
Reply with ONLY a JSON object:
{{"summary": "..."}}"""

TABLE_PLACEHOLDER = "[table omitted]"

_IGNORABLE_LINE_RE = re.compile(
    r"^(#{1,6} .*|" + re.escape(TABLE_PLACEHOLDER) + r"|\s*)$"
)


def strip_tables(text: str) -> str:
    """Replace each contiguous table block with the placeholder.

    A table line is any line whose lstrip() starts with '|' (same
    convention as mdutils.extract_tables).
    """
    out: list[str] = []
    in_table = False
    for line in text.splitlines():
        if line.lstrip().startswith("|"):
            if not in_table:
                out.append(TABLE_PLACEHOLDER)
                in_table = True
            continue
        in_table = False
        out.append(line)
    return "\n".join(out).strip()


def _is_table_only(prose: str) -> bool:
    """True when nothing but headings, placeholders and blanks remain."""
    return all(_IGNORABLE_LINE_RE.match(line) for line in prose.splitlines())


@dataclass(frozen=True)
class PendingSection:
    doc_id: str
    section_id: str
    title: str
    file: str  # stem without extension
    l3_body: str  # prose only — tables replaced by TABLE_PLACEHOLDER
    table_only: bool = False


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
            prose = strip_tables(body)
            out.append(
                PendingSection(
                    entry.id, sec.id, sec.title, sec.file, prose,
                    table_only=_is_table_only(prose),
                )
            )
    return out


def _max_chars(prose: str) -> int:
    return max(300, int(0.35 * len(prose)))


def build_section_prompt(section: PendingSection) -> str:
    return SECTION_PROMPT.format(
        section_id=section.section_id,
        title=section.title,
        l3_body=section.l3_body,
        max_chars=_max_chars(section.l3_body),
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
    if section.table_only:
        return {
            "l2_summary": "",
            "l1_summary": f"Table-only section: {section.title}.",
        }
    limit = _max_chars(section.l3_body)
    prompt = build_section_prompt(section)
    last: Exception | None = None
    for _ in range(2):  # 1 try + exactly 1 retry (spec §3.3)
        try:
            reply = parse_json_reply(
                runner.run(prompt), ("l2_summary", "l1_summary")
            )
        except (RunnerError, ValueError) as exc:
            last = exc
            continue
        if len(reply["l2_summary"]) <= limit:
            return reply
        last = ValueError(
            f"l2_summary too long: {len(reply['l2_summary'])} chars"
            f" > limit {limit}"
        )
        prompt = (
            build_section_prompt(section)
            + f"\n\nYour previous l2_summary was {len(reply['l2_summary'])}"
            f" characters — over the {limit}-character hard limit."
            " Reply again, compressed to fit."
        )
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
            (kb_dir / doc / f"{stem}.md").write_text(
                text, encoding="utf-8", newline="\n"
            )
        models.save_yaml_model(manifest_path, manifest)


_SECTION_HEAD_RE = re.compile(r"^## (?P<sid>\S+)(\s|$)")


def rebuild_l2_scaffold(l2_text: str) -> str:
    """Rebuild the pre-summarize L2 scaffold from a filled L2 file.

    Keeps `## <id> <title>` headings and table blocks; every section's
    prose (old summaries, leftover markers) is replaced by its marker.
    Deterministic and idempotent — used by `kb summarize --redo`.
    """
    out: list[str] = []
    for line in l2_text.splitlines():
        m = _SECTION_HEAD_RE.match(line)
        if m:
            out += [line, "", f"<!-- TODO:summarize {m.group('sid')} -->", ""]
            continue
        if line.lstrip().startswith("|"):
            out.append(line)
            continue
        if line.strip() == "" and out and out[-1].lstrip().startswith("|"):
            out.append("")  # keep the single blank that closes a table block
        # anything else is prose/old summary/old marker -> dropped
    return "\n".join(out)


@dataclass
class RedoReport:
    reset: list[str] = field(default_factory=list)  # "doc-id/section-id"
    reviewed_reset: int = 0


def redo_reset(kb_dir: Path, doc_id: str | None = None) -> RedoReport:
    """Reset summarized/reviewed sections to pending and restore L2 markers."""
    index = models.load_yaml_model(kb_dir / "index.yaml", models.KBIndex)
    report = RedoReport()
    for entry in index.docs:
        if doc_id and entry.id != doc_id:
            continue
        manifest_path = kb_dir / entry.id / "_manifest.yaml"
        if not manifest_path.exists():
            continue
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
        stems: set[str] = set()
        for sec in manifest.sections:
            if sec.status == "reviewed":
                report.reviewed_reset += 1
            if sec.status != "pending":
                report.reset.append(f"{entry.id}/{sec.id}")
            sec.status = "pending"
            sec.summary = ""
            stems.add(sec.file)
        for stem in stems:
            path = kb_dir / entry.id / f"{stem}.md"
            if path.exists():
                path.write_text(
                    rebuild_l2_scaffold(path.read_text(encoding="utf-8")),
                    encoding="utf-8",
                    newline="\n",
                )
        models.save_yaml_model(manifest_path, manifest)
    return report


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
