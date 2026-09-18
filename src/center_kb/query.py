from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from center_kb import models
from center_kb.mdutils import count_tokens, slice_section, slice_subsection
from center_kb.searchdb import tokenize  # re-export (web/ui.py import)

if TYPE_CHECKING:
    from center_kb.hub import HubHandle
    from center_kb.searchdb import SectionRow

logger = logging.getLogger("center_kb.query")


class AmbiguousDocError(LookupError):
    """doc_id exists in several federation repos — must be qualified as repo:doc."""

    def __init__(self, doc_id: str, repo_ids: list[str]) -> None:
        self.doc_id = doc_id
        self.repo_ids = repo_ids
        options = ", ".join(f"{rid}:{doc_id}" for rid in repo_ids)
        super().__init__(
            f"doc '{doc_id}' exists in {len(repo_ids)} federation repos — "
            f"qualify the ref: {options}"
        )


class InvalidLevelError(ValueError):
    """`level` was neither 'l2' nor 'l3'."""


def normalize_level(value: str) -> str:
    """'l2' | 'l3', case-insensitive; anything else raises.

    Reviewer C F-C4: two surfaces disagreeing about what a level means is the
    bug — the MCP tool validated, the CLI did not, and a caller asking for the
    untouched original silently received the AI-condensed text. One function
    both call is the fix."""
    norm = (value or "").strip().lower()
    if norm not in ("l2", "l3"):
        raise InvalidLevelError(f"level '{value}' is invalid — use 'l2' or 'l3'.")
    return norm


@dataclass
class QueryResult:
    doc_id: str
    section_id: str
    title: str
    score: float
    citation: str
    content: str
    tokens: int
    # content_tokens = what a caller that does not receive the snippet
    # actually got (content alone) — REST and the web UI report this one,
    # so their number stops describing text they never send. `tokens`
    # (above) keeps counting content + snippet: the budget this result
    # actually spent (M17). Required, not defaulted: a construction site
    # that forgets it would otherwise silently report 0 tk on REST/the UI.
    content_tokens: int
    source: str = ""  # repo-id within the federation
    match_mode: str = "keyword"  # "keyword" | "semantic" | "hybrid"
    snippet: str = ""  # L3 excerpt around the match when no term appears in L2


@dataclass
class SearchOutcome:
    """Results plus the out-of-band things the caller must be told.

    `notes` exists because an MCP agent never sees stderr: the truncation,
    ambiguity, unknown-tag and no-usable-terms signals have to travel with the
    payload (F-C5, F-C7, F-C9, F-C14)."""

    results: list["QueryResult"]
    notes: list[str] = field(default_factory=list)


def _citation(repo_id: str, doc_id: str, revision: str, section_id: str) -> str:
    base = f"{repo_id}:{doc_id} §{section_id}"
    return f"{base} ({revision})" if revision else base


def stale_hub_note(hub: "HubHandle | None") -> str:
    """One-line staleness warning shared by every caller that resolves a
    hub handle -- moved here from mcp.py's `_stale_note` (M17, identical
    body) so the CLI and REST surfaces can print/report the same wording
    instead of re-deriving it from `hub.stale`/`hub.age_seconds` themselves."""
    if hub is not None and hub.stale:
        age = f"~{hub.age_seconds:.0f}s" if hub.age_seconds else "unknown age"
        return f"[warn] hub cache is stale ({age}) — results may lag the hub\n\n"
    return ""


def _row_content(hub: "HubHandle", row: "SectionRow") -> str | None:
    l2_path = hub.federation_dir / row.repo_id / row.doc_id / f"{row.file}.md"
    if not l2_path.exists():
        return None
    return slice_section(l2_path.read_text(encoding="utf-8"), row.section_id)


_SNIPPET_WINDOW = 150  # chars on each side of the first hit in L3


def _l3_snippet(
    hub: "HubHandle", row: "SectionRow", terms: list[str], content: str
) -> str:
    """The match lives in L3 (fold/tail) while the L2 content contains no term →
    excerpt a window around the first hit so the user sees why this section matched."""
    lower = content.lower()
    if not terms or any(t in lower for t in terms):
        return ""
    raw_path = (
        hub.federation_dir / row.repo_id / row.doc_id / f"{row.file}.raw.md"
    )
    if not raw_path.exists():
        return ""
    raw = slice_section(raw_path.read_text(encoding="utf-8"), row.section_id)
    if not raw:
        return ""
    raw_lower = raw.lower()
    for term in terms:
        pos = raw_lower.find(term)
        if pos < 0:
            continue
        start = max(0, pos - _SNIPPET_WINDOW)
        end = min(len(raw), pos + len(term) + _SNIPPET_WINDOW)
        prefix = "…" if start > 0 else ""
        suffix = "…" if end < len(raw) else ""
        return f"{prefix}{raw[start:end].strip()}{suffix}"
    return ""


def _search_index(
    hub: "HubHandle", embedder, text: str, tags: list[str] | None
) -> tuple[
    list[tuple[int, float, str]],
    dict[int, "SectionRow"],
    bool,
    dict[int, float],
    bool,
]:
    """Run both legs + RRF on the index. DB corrupt mid-way → delete, rebuild
    exactly once; still failing → raise (spec §5). The third element is True
    when a leg filled K_LEG, i.e. matches were dropped before fusion (F-C7).
    The fourth element is the keyword leg's raw BM25 scores (rowid → positive
    score, higher is better) — RRF only carries rank, so the ambiguity note's
    score check needs the real magnitude (F-C5). The fifth element (`busy`)
    is True when the writer lock forced us onto the existing (possibly stale
    or cold-empty) index instead of the freshly-synced one — the caller must
    tell the user, not just log a warning nobody sees (R19, final-branch
    review)."""
    from center_kb import searchdb

    for attempt in (1, 2):
        conn: sqlite3.Connection | None = None
        busy = False
        try:
            # open_fresh sits INSIDE the try — corruption surfacing during the
            # freshness sync must get the same rebuild-once handling as
            # corruption during a query (spec §5)
            try:
                conn = searchdb.open_fresh(hub, embedder)
            except sqlite3.OperationalError as exc:
                if not searchdb.is_lock_error(exc):
                    raise
                # another process holds the writer lock (long sync) — serve the
                # existing (stale) index instead of failing after busy_timeout
                # (spec §3.2)
                logger.warning("search.db busy — serving existing index: %s", exc)
                conn = searchdb.open_db(hub)
                busy = True
            fts_hits = searchdb.fts_search(conn, text, tags)
            knn_hits: list[tuple[int, float]] = []
            if embedder is not None:
                try:
                    knn_hits = searchdb.knn_search(conn, embedder, text, tags)
                except sqlite3.DatabaseError:
                    raise  # index corrupt — let the rebuild branch handle it
                except Exception as exc:  # noqa: BLE001 -- embedding best-effort, must not break the query
                    logger.warning("semantic leg failed — keyword only: %s", exc)
            fused = searchdb.rrf_merge(fts_hits, knn_hits)
            truncated = (
                len(fts_hits) >= searchdb.K_LEG or len(knn_hits) >= searchdb.K_LEG
            )
            return (
                fused,
                searchdb.load_sections(conn, [r for r, _, _ in fused]),
                truncated,
                dict(fts_hits),
                busy,
            )
        except sqlite3.DatabaseError as exc:
            if conn is not None:
                conn.close()  # Windows: close before unlink
                conn = None
            kind = searchdb.classify_db_error(exc)
            if kind != "corrupt" or attempt == 2:
                # lock = another process is writing; client = the caller's own
                # input. Neither is a reason to delete the shared index (F-C2).
                raise
            logger.warning("search.db corrupt — rebuilding once: %s", exc)
            searchdb.delete_db(hub)
        finally:
            if conn is not None:
                conn.close()
    raise AssertionError("unreachable")


# Measured in Task 10, Step 6 — this repo's own .kb/ published to a scratch
# federation entry, top-2 BM25 ratio (2nd-hit / 1st-hit) for reviewer C's
# rank-1-correct query battery:
#
#   0.642  Restrictive Airspace Designation
#   0.991  Runway Identifier
#   0.956  Magnetic Variation
#   0.277  CUST/AREA
#   0.916  S/T
#   0.564  ARPT/HELI IDENT
#   0.000  RT TYPE
#   0.877  IFR CAP
#   0.000  5.129
#   0.920  section 5.4
#   0.942  Continuation Record Number
#   0.960  Section Code
#   0.754  which field says whether a record is standard or tailored
#   0.825  how do I know if an airport supports IFR
#
# Highest: 0.991 ("Runway Identifier"). No value below 0.99 separates the
# unambiguous battery from a close pair on this corpus, so only an exact tie
# counts; re-measure before lowering. The structural (same-section) rule
# carries the documented ambiguous case on its own.
AMBIG_BM25_RATIO = 1.00


def _ambiguity_notes(
    results: list["QueryResult"],
    result_rowids: list[int],
    fts_scores: dict[int, float],
) -> list[str]:
    """Two reasons the caller should look at #2 as well as #1 (F-C5).

    1. STRUCTURAL — the top two are the SAME section published by two
       federation repos. No threshold, no calibration, and it is the case a BA
       must never miss.
    2. SCORE — both come from the keyword leg and their raw BM25 scores are
       within AMBIG_BM25_RATIO. RRF cannot answer this: adjacent ranks within a
       leg are always ~1.6% apart, so a ratio test on RRF fires on everything
       or nothing. BM25 carries real magnitude.

    `result_rowids[i]` must be the rowid that produced `results[i]` — NOT
    `fused[:2]`. `search_detailed`'s loop skips fused entries whose row or L2
    content is missing (stale/partial hub cache), so `fused[:2]` and
    `results[:2]` can name different rows; scoring the wrong pair could name
    two sections whose scores were never actually compared, and — with an
    unlucky skip — invert `lo`/`hi` so a mismatched pair satisfies
    `>= AMBIG_BM25_RATIO` when the cited pair never would (review round 2)."""
    if len(results) < 2:
        return []
    top, second = results[0], results[1]
    if top.doc_id == second.doc_id and top.section_id == second.section_id:
        return [
            f"Note: [{top.citation}] and [{second.citation}] are the same section "
            "published by two federation repos — confirm which repo the story "
            "should cite before pinning.\n\n"
        ]
    ranked = result_rowids[:2]
    if len(ranked) == 2 and all(r in fts_scores for r in ranked):
        if top.match_mode == "keyword" and second.match_mode == "keyword":
            hi, lo = fts_scores[ranked[0]], fts_scores[ranked[1]]
            if hi > 0 and lo <= hi and lo / hi >= AMBIG_BM25_RATIO:
                return [
                    f"Note: [{top.citation}] and [{second.citation}] score closely "
                    "— both may be relevant to your question; review each before "
                    "citing.\n\n"
                ]
    return []


def _unknown_tag_notes(hub: "HubHandle", tags: list[str]) -> list[str]:
    """A tag filter that matched nothing is usually a tag that does not exist
    (reviewer C battery #32). Only runs on the empty-result path.

    Document ids count as valid: `searchdb.py:350` indexes `doc.id.lower()` as
    a synthetic tag, so `--tags arinc-424` is a supported filter (F-C14). It is
    deliberately NOT part of `kbcontext.tag_vocabulary`, which governs what a
    kb-context block may carry."""
    from center_kb import kbcontext
    from center_kb.federation import load_federation

    repos = load_federation(hub.federation_dir)
    vocab = kbcontext.tag_vocabulary(repos)
    doc_ids = {doc.id.lower() for repo in repos for doc in repo.index.docs}
    known = set(vocab) | doc_ids
    unknown = sorted({t.strip().lower() for t in tags if t.strip()} - known)
    if not unknown:
        return []
    published = ", ".join(sorted(vocab.values())) or "(none published)"
    return [
        f"Note: no document is tagged {', '.join(repr(t) for t in unknown)}. "
        f"Published tags: {published}. Document ids are also accepted as tags."
        "\n\n"
    ]


_ECHO_MAX_CHARS = 120


def _truncate_echo(text: str) -> str:
    """Bound a raw caller-supplied query before it's echoed into a note.

    The no-usable-terms note quotes the query verbatim; an MCP agent can
    hand back an arbitrarily long punctuation-only string, and that was
    landing in the payload unbounded (minor finding, promoted on final-branch
    review)."""
    if len(text) <= _ECHO_MAX_CHARS:
        return text
    return text[:_ECHO_MAX_CHARS] + "…"


BUSY_INDEX_NOTE = (
    "Note: another process is rebuilding the search index — these results "
    "were served from the previous index and may be incomplete; retry in a "
    "moment.\n\n"
)


def search_detailed(
    hub: "HubHandle",
    text: str,
    tags: list[str] | None = None,
    budget: int = 2000,
    semantic: bool = False,
    use_semantic: bool = True,
    embedder=None,  # center_kb.embed.Embedder | None — injectable for tests
) -> SearchOutcome:
    from center_kb import embed as embed_mod
    from center_kb import searchdb

    if embedder is None:
        embedder = embed_mod.default_embedder()
    if semantic and embedder is None:
        logger.warning(
            "semantic search requested but no embedder is available — "
            'keyword results only (enable with: pip install "center-kb[embed]")'
        )
    notes: list[str] = []
    terms = tokenize(text)
    if text.strip() and not terms:
        notes.append(
            f"Note: '{_truncate_echo(text)}' contains no searchable terms "
            "after tokenising — the index stores alphanumeric words, so "
            "punctuation-only queries match nothing.\n\n"
        )
        return SearchOutcome(results=[], notes=notes)
    fused, rows, truncated, fts_scores, busy = _search_index(
        hub, embedder if use_semantic else None, text, tags
    )

    results: list[QueryResult] = []
    result_rowids: list[int] = []
    used = 0
    for rowid, score, mode in fused:
        row = rows.get(rowid)
        if row is None:
            continue
        content = _row_content(hub, row)
        if content is None:
            continue
        snippet = "" if mode == "semantic" else _l3_snippet(hub, row, terms, content)
        content_tokens = count_tokens(content)
        n_tokens = content_tokens + (count_tokens(snippet) if snippet else 0)
        if results and used + n_tokens > budget:
            break
        results.append(
            QueryResult(
                doc_id=row.doc_id,
                section_id=row.section_id,
                title=row.title,
                score=score,
                citation=_citation(
                    row.repo_id, row.doc_id, row.doc_revision, row.section_id
                ),
                content=content,
                tokens=n_tokens,
                source=row.repo_id,
                match_mode=mode,
                snippet=snippet,
                content_tokens=content_tokens,
            )
        )
        result_rowids.append(rowid)
        used += n_tokens
        if used >= budget:
            break
    if busy:
        # R19 (final-branch review, Important): a lock error from open_fresh
        # used to fall back to the existing index silently (log.warning only
        # — an MCP agent never sees stderr). On a cold hub that existing
        # index is empty, so the caller got a confident "No matching section
        # found" with no hint the index simply hadn't synced yet.
        notes.append(BUSY_INDEX_NOTE)
    if truncated:
        # Deliberately conservative: a query with exactly K_LEG matches reports a
        # cut it did not suffer. That costs the caller one sentence and never
        # hides a real one (F-C7).
        notes.append(
            f"Note: more sections matched than were ranked — each leg is capped "
            f"at {searchdb.K_LEG} before fusion, so this is not the complete set. "
            "Narrow the query or add --tags to see the rest.\n\n"
        )
    notes.extend(_ambiguity_notes(results, result_rowids, fts_scores))
    if not results and tags:
        notes.extend(_unknown_tag_notes(hub, tags))
    return SearchOutcome(results=results, notes=notes)


def search(
    hub: "HubHandle",
    text: str,
    tags: list[str] | None = None,
    budget: int = 2000,
    semantic: bool = False,
    use_semantic: bool = True,
    embedder=None,
) -> list[QueryResult]:
    """Backwards-compatible view of `search_detailed` — results only."""
    return search_detailed(
        hub, text, tags=tags, budget=budget, semantic=semantic,
        use_semantic=use_semantic, embedder=embedder,
    ).results


def _parent_entry(
    manifest: models.Manifest, section_id: str
) -> models.SectionEntry | None:
    """A folded id has no entry of its own — the parent is the entry whose id
    is the longest prefix of the requested id, cut at '.' or '-' ('3.2.1' →
    '3.2'; '5.6-commentary' → '5.6')."""
    best: models.SectionEntry | None = None
    for s in manifest.sections:
        if section_id.startswith((s.id + ".", s.id + "-")):
            if best is None or len(s.id) > len(best.id):
                best = s
    return best


def _folded_result(
    repo_kb: Path,
    repo_id: str,
    manifest: models.Manifest,
    doc_id: str,
    section_id: str,
    level: str,
) -> QueryResult | None:
    parent = _parent_entry(manifest, section_id)
    if parent is None:
        return None
    if level != "l3":
        # L2 has no child anchor (the summary covers the folded child) — return
        # the parent with the parent's citation id; do not lie about the location.
        return _get_section_in(repo_kb, repo_id, doc_id, parent.id, level)
    path = repo_kb / doc_id / f"{parent.file}.raw.md"
    if not path.exists():
        return None
    parent_md = slice_section(path.read_text(encoding="utf-8"), parent.id)
    if parent_md is None:
        return None
    content = slice_subsection(parent_md, section_id)
    if content is None:
        return None
    head = content.splitlines()[0].split(None, 2)
    title = head[2] if len(head) == 3 else parent.title
    content_tokens = count_tokens(content)
    return QueryResult(
        doc_id=doc_id,
        section_id=section_id,
        title=title,
        score=0.0,
        citation=_citation(repo_id, manifest.id, manifest.revision, section_id),
        content=content,
        tokens=content_tokens,
        source=repo_id,
        content_tokens=content_tokens,
    )


def _get_section_in(
    repo_kb: Path, repo_id: str, doc_id: str, section_id: str, level: str
) -> QueryResult | None:
    manifest_path = repo_kb / doc_id / "_manifest.yaml"
    if not manifest_path.exists():
        return None
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    sec = next((s for s in manifest.sections if s.id == section_id), None)
    if sec is None:
        return _folded_result(
            repo_kb, repo_id, manifest, doc_id, section_id, level
        )
    suffix = ".raw.md" if level == "l3" else ".md"
    path = repo_kb / doc_id / f"{sec.file}{suffix}"
    if not path.exists():
        return None
    content = slice_section(path.read_text(encoding="utf-8"), section_id)
    if content is None:
        return None
    content_tokens = count_tokens(content)
    return QueryResult(
        doc_id=doc_id,
        section_id=section_id,
        title=sec.title,
        score=0.0,
        citation=_citation(repo_id, manifest.id, manifest.revision, section_id),
        content=content,
        tokens=content_tokens,
        source=repo_id,
        content_tokens=content_tokens,
    )


def get_section(
    hub: "HubHandle",
    doc_id: str,
    section_id: str,
    level: str = "l2",
    repo: str | None = None,
) -> QueryResult | None:
    from center_kb.federation import load_federation

    level = normalize_level(level)
    section_id = section_id.lstrip("§")
    if ":" in doc_id and repo is None:
        repo, doc_id = doc_id.split(":", 1)
    holders = [
        r for r in load_federation(hub.federation_dir)
        if (repo is None or r.meta.repo_id == repo)
        and (r.kb_dir / doc_id / "_manifest.yaml").exists()
    ]
    if not holders:
        return None
    if len(holders) > 1:
        raise AmbiguousDocError(doc_id, [r.meta.repo_id for r in holders])
    r = holders[0]
    return _get_section_in(r.kb_dir, r.meta.repo_id, doc_id, section_id, level)
