from __future__ import annotations

import hashlib
import json
import random
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from center_kb import models, quality
from center_kb.llm import RunnerError
from center_kb.mdutils import HEADING_RE, heading_occurrences, slice_section
from center_kb.quality import (
    BRIEF_LABEL,
    TABLE_ONLY_LABEL,
    TABLE_PLACEHOLDER,  # re-exported for callers/tests
)

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

PROMPT_SHA = hashlib.sha256(SECTION_PROMPT.encode("utf-8")).hexdigest()[:12]
RETRY_PAUSE_SECONDS = 1.0  # pause before the retry after a RunnerError (tests set 0)


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


@dataclass(frozen=True)
class PendingSection:
    doc_id: str
    section_id: str
    title: str
    file: str  # stem without extension
    l3_body: str  # prose only — tables replaced by TABLE_PLACEHOLDER
    row: int = 0  # index in manifest.sections — ids are not unique
    l3_sha256: str = ""  # digest of the L3 slice that was summarized

    @property
    def prose_chars(self) -> int:
        return len(quality.prose_only(self.l3_body))

    @property
    def kind(self) -> Literal["table_only", "brief", "llm"]:
        if quality.is_table_only(self.prose_chars):
            return "table_only"
        if quality.is_brief(self.prose_chars):
            return "brief"
        return "llm"

    @property
    def table_only(self) -> bool:
        return self.kind == "table_only"


def collect_pending(
    kb_dir: Path,
    doc_id: str | None = None,
    on_missing: Callable[[str], None] | None = None,
) -> list[PendingSection]:
    """Collect every pending section's L3 slice. `heading_occurrences`
    resolves duplicate ids to the right heading occurrence for each row.
    When a row's heading is missing from the raw file, no PendingSection is
    created for it — `on_missing` (if given) is called with a failure
    message instead of the row being silently laundered into a fabricated
    table-only summary."""
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
        occurrences = heading_occurrences(manifest.sections)
        for row, sec in enumerate(manifest.sections):
            if sec.status != "pending":
                continue
            if sec.file not in raw_cache:
                raw_path = kb_dir / entry.id / f"{sec.file}.raw.md"
                raw_cache[sec.file] = (
                    raw_path.read_text(encoding="utf-8") if raw_path.exists() else ""
                )
            occurrence = occurrences[row]
            body = slice_section(raw_cache[sec.file], sec.id, occurrence)
            if body is None:
                if on_missing:
                    on_missing(
                        f"{entry.id}/{sec.id}: heading not found in {sec.file}"
                        f" (occurrence {occurrence})"
                    )
                continue
            out.append(
                PendingSection(
                    entry.id, sec.id, sec.title, sec.file, strip_tables(body),
                    row=row, l3_sha256=quality.digest(body),
                )
            )
    return out


def build_section_prompt(section: PendingSection) -> str:
    return SECTION_PROMPT.format(
        section_id=section.section_id,
        title=section.title,
        l3_body=section.l3_body,
        max_chars=quality.budget(section.prose_chars),
    )


def build_doc_prompt(title: str, l1_summaries: list[str]) -> str:
    return DOC_PROMPT.format(title=title, l1_lines="\n".join(f"- {s}" for s in l1_summaries))


_FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL)


def _balanced_spans(text: str):
    """Every top-level `{…}` span, left to right, string- and escape-aware."""
    i, n = 0, len(text)
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth, in_str, esc = 0, False, False
        for j in range(i, n):
            ch = text[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    yield text[i : j + 1]
                    i = j
                    break
        i += 1


def _candidates(text: str):
    for m in _FENCE_RE.finditer(text):
        yield m.group(1)
    yield from _balanced_spans(text)


def parse_json_reply(text: str, required: tuple[str, ...]) -> dict[str, str]:
    """First JSON object (fenced or balanced) whose required keys are all
    non-empty strings. ValueError otherwise — never a crash path."""
    saw_object = False
    for cand in _candidates(text):
        try:
            data = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        saw_object = True
        out = {k: data.get(k) for k in required}
        if all(isinstance(v, str) and v.strip() for v in out.values()):
            return {k: v.strip() for k, v in out.items()}
    if saw_object:
        raise ValueError(f"missing or empty key among: {', '.join(required)}")
    raise ValueError("no JSON object in reply")


def replace_marker(l2_text: str, section_id: str, summary: str, occurrence: int = 0) -> str:
    """Replace the `occurrence`-th (0-based, file order) marker for
    `section_id`. Ids are not unique within a file, so a caller writing a
    specific manifest row's summary must target that row's own marker
    rather than always the first — `occurrence=0` (default) keeps the
    original first-match behavior."""
    if occurrence < 0:
        raise ValueError(f"occurrence must be >= 0, got {occurrence}")
    marker = f"<!-- TODO:summarize {section_id} -->"
    start = 0
    for _ in range(occurrence + 1):
        idx = l2_text.find(marker, start)
        if idx == -1:
            raise ValueError(f"marker not found: {marker} (occurrence {occurrence})")
        start = idx + len(marker)
    return l2_text[: idx] + summary + l2_text[start:]


@dataclass
class SummarizeReport:
    summarized: list[str] = field(default_factory=list)  # "doc-id/section-id"
    failed: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


def _summarize_one(runner, section: PendingSection) -> dict[str, str]:
    if section.kind == "table_only":
        return {"l2_summary": "", "l1_summary": TABLE_ONLY_LABEL.format(title=section.title)}
    if section.kind == "brief":
        return {
            "l2_summary": quality.prose_only(section.l3_body),
            "l1_summary": BRIEF_LABEL.format(title=section.title),
        }
    limit = quality.budget(section.prose_chars)
    prompt = build_section_prompt(section)
    last: Exception | None = None
    for attempt in range(2):  # 1 try + exactly 1 retry (spec §3.3)
        try:
            reply = parse_json_reply(runner.run(prompt), ("l2_summary", "l1_summary"))
        except (RunnerError, ValueError) as exc:
            last = exc
            if attempt == 0 and RETRY_PAUSE_SECONDS:
                time.sleep(RETRY_PAUSE_SECONDS + random.random() * RETRY_PAUSE_SECONDS / 2)  # noqa: S311 -- retry backoff jitter, not security-sensitive
            continue
        if len(reply["l2_summary"]) <= limit:
            return reply
        last = ValueError(
            f"l2_summary too long: {len(reply['l2_summary'])} chars > limit {limit}"
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
    report = SummarizeReport()
    pending = collect_pending(kb_dir, doc_id, on_missing=report.failed.append)
    results: dict[tuple[str, int], dict[str, str]] = {}
    sections = {(s.doc_id, s.row): s for s in pending}
    if pending:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_summarize_one, runner, s): s for s in pending}
            for fut in as_completed(futures):
                s = futures[fut]
                key = f"{s.doc_id}/{s.section_id}"
                try:
                    results[(s.doc_id, s.row)] = fut.result()
                except Exception as exc:  # noqa: BLE001 — one section must never abort the batch
                    report.failed.append(key)
                    say(f"[fail] {key}: {exc}")
                else:
                    say(f"[ok] {key}")

        _apply_results(kb_dir, results, sections, runner, report)
    touched = {s.doc_id for s in pending}
    _fill_doc_summaries(kb_dir, runner, doc_id, touched, say, report)
    report.summarized.sort()
    report.failed.sort()
    return report


def _provenance(runner, section: PendingSection) -> models.Provenance:
    at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if section.kind != "llm":
        return models.Provenance(runner="none", prompt_sha=PROMPT_SHA, at=at)
    return models.Provenance(
        runner=getattr(runner, "name", ""), model=getattr(runner, "model", ""),
        effort=getattr(runner, "effort", ""), prompt_sha=PROMPT_SHA, at=at,
    )


def _pending_marker_index(sections: list[models.SectionEntry]) -> list[int | None]:
    """0-based marker-occurrence index for each row that is `pending` in
    this snapshot (its L2 marker is still present in the file), or `None`
    for a row that is not (its marker was already consumed by an earlier
    run). Unlike `mdutils.heading_occurrences` (which counts every row,
    since the raw file always has every heading regardless of status), the
    L2 file only ever has markers for rows that are still pending — must be
    computed from a snapshot taken before any row's status is mutated in
    this call."""
    seen: dict[tuple[str, str], int] = {}
    out: list[int | None] = []
    for sec in sections:
        if sec.status != "pending":
            out.append(None)
            continue
        key = (sec.file, sec.id)
        idx = seen.get(key, 0)
        seen[key] = idx + 1
        out.append(idx)
    return out


def _apply_results(
    kb_dir: Path,
    results: dict[tuple[str, int], dict[str, str]],
    sections: dict[tuple[str, int], PendingSection],
    runner,
    report: SummarizeReport,
) -> None:
    by_doc: dict[str, dict[int, dict[str, str]]] = {}
    for (doc, row), result in results.items():
        by_doc.setdefault(doc, {})[row] = result
    for doc, rows in by_doc.items():
        manifest_path = kb_dir / doc / "_manifest.yaml"
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
        # Snapshot BEFORE any row's status is mutated below — marker_index
        # reflects which markers exist in the L2 file right now.
        marker_index = _pending_marker_index(manifest.sections)
        # Markers are consumed (removed) as they're written, which shifts the
        # occurrence of every later marker for the same (file, id) down by
        # one. Rows are always processed in ascending (== heading) order, so
        # subtracting how many earlier same-id markers this loop has already
        # replaced converts the snapshot's marker index into the current one.
        consumed: dict[tuple[str, str], int] = {}
        l2_cache: dict[str, str] = {}
        for row, sec in enumerate(manifest.sections):
            pair = rows.get(row)
            if pair is None:
                continue
            key = f"{doc}/{sec.id}"
            if sec.file not in l2_cache:
                l2_cache[sec.file] = (kb_dir / doc / f"{sec.file}.md").read_text(encoding="utf-8")
            occurrence = marker_index[row] - consumed.get((sec.file, sec.id), 0)
            try:
                l2_cache[sec.file] = replace_marker(
                    l2_cache[sec.file], sec.id, pair["l2_summary"], occurrence=occurrence
                )
            except ValueError:
                report.failed.append(key)
                continue
            consumed[(sec.file, sec.id)] = consumed.get((sec.file, sec.id), 0) + 1
            pending = sections[(doc, row)]
            sec.summary = pair["l1_summary"]
            sec.status = "summarized"
            sec.l3_sha256 = pending.l3_sha256
            sec.provenance = _provenance(runner, pending)
            sec.reviewed = None
            report.summarized.append(key)
        for stem, text in l2_cache.items():
            (kb_dir / doc / f"{stem}.md").write_text(text, encoding="utf-8", newline="\n")
        models.save_yaml_model(manifest_path, manifest)


def _scaffold_lines(lines: list[str]) -> list[str]:
    """Headings, tables and Figure: lines survive; every section's prose
    (old summaries, leftover markers) becomes its marker."""
    out: list[str] = []
    for line in lines:
        m = HEADING_RE.match(line)
        if m:
            out += [line, "", f"<!-- TODO:summarize {m.group('sid')} -->", ""]
            continue
        if line.lstrip().startswith("|") or line.startswith("Figure: "):
            out.append(line)
            continue
        if line.strip() == "" and out and (
            out[-1].lstrip().startswith("|") or out[-1].startswith("Figure: ")
        ):
            out.append("")  # the single blank that closes a table/figure block
        # anything else is prose/old summary/old marker -> dropped
    return out


def rebuild_l2_scaffold(l2_text: str) -> str:
    """Rebuild the pre-summarize L2 scaffold from a filled L2 file.

    Keeps `## <id> <title>` headings, table blocks and `Figure: ` lines;
    every section's prose (old summaries, leftover markers) is replaced
    by its marker. Deterministic and idempotent — used by a whole-doc
    `kb summarize --redo`.
    """
    return "\n".join(_scaffold_lines(l2_text.splitlines()))


def reset_section_prose(l2_text: str, section_id: str, occurrence: int = 0) -> str:
    """Restore the marker in ONE section; every other section (and every
    other occurrence of a duplicate `section_id`) is byte-identical.

    `occurrence` (0-based, file order) picks which heading to target when
    the same id repeats in a file — mirrors `mdutils.slice_section`.
    """
    lines = l2_text.splitlines()
    seen = -1
    start = None
    for i, line in enumerate(lines):
        m = HEADING_RE.match(line)
        if m and m.group("sid") == section_id:
            seen += 1
            if seen == occurrence:
                start = i
                break
    if start is None:
        raise ValueError(f"section not found in L2: {section_id} (occurrence {occurrence})")
    end = next((j for j in range(start + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
    block = _scaffold_lines(lines[start:end])
    if end < len(lines) and block and block[-1] != "":
        block.append("")
    return "\n".join(lines[:start] + block + lines[end:])


@dataclass(frozen=True)
class RedoItem:
    doc_id: str
    row: int
    section_id: str
    status: str
    reviewed: models.ReviewRecord | None


@dataclass
class RedoPlan:
    items: list[RedoItem] = field(default_factory=list)
    skipped_reviewed: list[RedoItem] = field(default_factory=list)

    @property
    def reviewed_items(self) -> list[RedoItem]:
        return [i for i in self.items if i.status == "reviewed"]


def plan_redo(
    kb_dir: Path,
    doc_id: str | None,
    section_ids: list[str] | None = None,
    include_reviewed: bool = False,
) -> RedoPlan:
    """Pure: which manifest rows a redo would reset. doc_id=None means
    every doc — nothing here writes anything."""
    index = models.load_yaml_model(kb_dir / "index.yaml", models.KBIndex)
    known = {e.id for e in index.docs}
    if doc_id and doc_id not in known:
        raise ValueError(f"unknown document: {doc_id}")
    wanted = set(section_ids or [])
    plan = RedoPlan()
    seen: set[str] = set()
    for entry in index.docs:
        if doc_id and entry.id != doc_id:
            continue
        manifest_path = kb_dir / entry.id / "_manifest.yaml"
        if not manifest_path.exists():
            continue
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
        for row, sec in enumerate(manifest.sections):
            if wanted and sec.id not in wanted:
                continue
            seen.add(sec.id)
            item = RedoItem(entry.id, row, sec.id, sec.status, sec.reviewed)
            if sec.status == "reviewed" and not include_reviewed:
                plan.skipped_reviewed.append(item)
            else:
                plan.items.append(item)
    missing = sorted(wanted - seen)
    if missing:
        raise ValueError(f"section(s) not found: {', '.join(missing)}")
    return plan


@dataclass
class RedoReport:
    reset: list[str] = field(default_factory=list)  # "doc-id/section-id"
    reviewed_reset: int = 0
    failed: list[str] = field(default_factory=list)  # "doc-id/section-id: reason"


def redo_reset(kb_dir: Path, plan: RedoPlan) -> RedoReport:
    """Apply a printed plan: reset the planned rows only, restore their
    markers, leave every other row (and every other section's prose,
    tables, Figure: lines) byte-identical.

    A stale plan row (the manifest no longer has `item.section_id` at
    `item.row` — it moved or the manifest shrank since `plan_redo` ran) or
    a heading that has gone missing from the L2 file is recorded in
    `report.failed` and that row is left untouched; every other row in the
    plan is still applied — one bad row must never abort the rest of a
    `--all` redo.
    """
    report = RedoReport()
    by_doc: dict[str, list[RedoItem]] = {}
    for item in plan.items:
        by_doc.setdefault(item.doc_id, []).append(item)
    for doc, items in by_doc.items():
        reset, reviewed_reset, failed = _redo_reset_one_doc(kb_dir, doc, items)
        report.reset.extend(reset)
        report.reviewed_reset += reviewed_reset
        report.failed.extend(failed)
    return report


def _reset_one_row(
    kb_dir: Path,
    doc: str,
    item: RedoItem,
    manifest: models.Manifest,
    occurrences: list[int],
    l2_cache: dict[str, str],
) -> tuple[str | None, str | None, bool]:
    """Reset ONE planned row; return (reset id or None, failure message or
    None, was_reviewed). Mutates `manifest`/`l2_cache` in place on success —
    the caller decides whether to persist them."""
    if item.row >= len(manifest.sections):
        return None, f"{doc}/{item.section_id}: manifest row {item.row} no longer exists", False
    sec = manifest.sections[item.row]
    occurrence = occurrences[item.row]
    if sec.id != item.section_id:
        msg = f"{doc}/{item.section_id}: heading not found in {sec.file} (occurrence {occurrence})"
        return None, msg, False
    path = kb_dir / doc / f"{sec.file}.md"
    if sec.file not in l2_cache and path.exists():
        l2_cache[sec.file] = path.read_text(encoding="utf-8")
    if sec.file in l2_cache:
        try:
            l2_cache[sec.file] = reset_section_prose(
                l2_cache[sec.file], sec.id, occurrence=occurrence
            )
        except ValueError:
            msg = f"{doc}/{sec.id}: heading not found in {sec.file} (occurrence {occurrence})"
            return None, msg, False
    was_reviewed = sec.status == "reviewed"
    reset_id = f"{doc}/{sec.id}" if sec.status != "pending" else None
    sec.status, sec.summary, sec.l3_sha256 = "pending", "", None
    sec.provenance, sec.reviewed = None, None
    return reset_id, None, was_reviewed


def _redo_reset_one_doc(
    kb_dir: Path, doc: str, items: list[RedoItem]
) -> tuple[list[str], int, list[str]]:
    """Apply a plan's rows for ONE doc; return (reset ids, reviewed_reset
    count, failure messages). L2/manifest are written only when at least
    one row actually reset — a doc every one of whose planned rows failed
    must stay byte-identical, not just logically unchanged."""
    manifest_path = kb_dir / doc / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    occurrences = heading_occurrences(manifest.sections)
    l2_cache: dict[str, str] = {}
    reset: list[str] = []
    failed: list[str] = []
    reviewed_reset = 0
    changed = False
    for item in items:
        reset_id, failure, was_reviewed = _reset_one_row(
            kb_dir, doc, item, manifest, occurrences, l2_cache
        )
        if failure:
            failed.append(failure)
            continue
        changed = True
        if was_reviewed:
            reviewed_reset += 1
        if reset_id:
            reset.append(reset_id)
    if changed:
        for stem, text in l2_cache.items():
            (kb_dir / doc / f"{stem}.md").write_text(text, encoding="utf-8", newline="\n")
        models.save_yaml_model(manifest_path, manifest)
    return reset, reviewed_reset, failed


def _fill_doc_summaries(
    kb_dir: Path,
    runner,
    doc_id: str | None,
    touched: set[str],
    say: Callable[[str], None],
    report: SummarizeReport,
) -> None:
    """Write the L0 sentence for every in-scope doc that has no pending
    section and either was touched in this run or has an empty summary."""
    index_path = kb_dir / "index.yaml"
    index = models.load_yaml_model(index_path, models.KBIndex)
    changed = False
    for entry in index.docs:
        if doc_id and entry.id != doc_id:
            continue
        if entry.id not in touched and entry.summary.strip():
            continue
        manifest_path = kb_dir / entry.id / "_manifest.yaml"
        if not manifest_path.exists():
            continue
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
        if any(s.status == "pending" for s in manifest.sections):
            continue  # doc not complete yet
        if not any(s.summary.strip() for s in manifest.sections):
            continue  # no section summary to draw on — never fabricate one
        prompt = build_doc_prompt(entry.title, [s.summary for s in manifest.sections])
        try:
            reply = parse_json_reply(runner.run(prompt), ("summary",))
        except (RunnerError, ValueError) as exc:
            report.failed.append(f"{entry.id}/<doc-summary>")
            say(f"[fail] {entry.id}/<doc-summary>: {exc}")
            continue
        entry.summary = reply["summary"]
        changed = True
    if changed:
        models.save_yaml_model(index_path, index)
