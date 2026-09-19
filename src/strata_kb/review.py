from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from strata_kb import gitio, models, quality
from strata_kb.build import build_kb
from strata_kb.diff import diff_doc
from strata_kb.mdutils import heading_occurrences, slice_section


# `hist.*` rows are written by `kb svc note` (Hard rule 12: never hand-
# edited), so a whole-document approve has nothing to sign off there;
# naming one explicitly still works (reviewer F L7).
MACHINE_SECTION_PREFIX = "hist."


@dataclass
class ApproveReport:
    doc_id: str
    flipped: list[str] = field(default_factory=list)
    skipped_pending: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    skipped_machine: list[str] = field(default_factory=list)


def _indexed_doc_ids(kb_dir: Path) -> list[str]:
    """Every doc id in index.yaml, manifest or not; [] if the index is missing.

    Lenient by design (unlike `doc_ids_with_manifest`, which raises): used
    only to recognize which build errors are "about a known doc" so
    `check_approvable` can tell that apart from a structural error that
    names no doc at all (e.g. a missing index.yaml).
    """
    index_path = kb_dir / "index.yaml"
    if not index_path.exists():
        return []
    index = models.load_yaml_model(index_path, models.KBIndex)
    return [e.id for e in index.docs]


def doc_ids_with_manifest(kb_dir: Path) -> list[str]:
    """Doc ids in index.yaml that have a manifest present in the worktree."""
    index_path = kb_dir / "index.yaml"
    if not index_path.exists():
        raise ValueError(f"KB index not found ({index_path})")
    index = models.load_yaml_model(index_path, models.KBIndex)
    return [e.id for e in index.docs if (kb_dir / e.id / "_manifest.yaml").exists()]


def check_approvable(kb_dir: Path, doc_ids: list[str]) -> list[str]:
    """Errors blocking approval of `doc_ids`; empty return = every doc is approvable.

    Approval signs the COMMITTED content, so every target's `.kb/<doc>`
    subtree must be clean first — this is checked for all targets before
    anything else runs, one message per dirty doc. Only if none is dirty do
    we run a single strict build (`kb build --strict`) across the whole KB
    and keep the errors that are about one of the target docs. Running one
    whole-KB build rather than one per doc matters because a passing build
    would otherwise WRITE token counts into every passing manifest — a
    per-doc "check dirty, then build" loop would see the second doc's tree
    turn dirty from the first doc's build before it got checked — so the
    build runs with `write_tokens=False` (never persists) and
    `allow_pending=True` (a pending SECTION is not a reason to block
    approving its already-summarized siblings; `kb approve` already reports
    pending sections via `skipped_pending`).

    An error whose ref matches no doc id in the whole index at all (e.g. a
    missing index.yaml) names no target and no bystander — it is always
    blocking, never silently dropped by the target-prefix filter.
    """
    kb_abs = kb_dir.resolve()
    root = gitio.git_root(kb_abs)
    dirty = [
        f"commit .kb/{d} before approving; approval signs the committed content"
        for d in doc_ids
        if gitio.is_dirty(root, kb_abs / d)
    ]
    if dirty:
        return dirty
    report = build_kb(kb_dir, allow_pending=True, strict=True, write_tokens=False)
    target_prefixes = tuple(f"{d} §" for d in doc_ids) + tuple(f"{d}:" for d in doc_ids)
    known_ids = _indexed_doc_ids(kb_dir)
    known_prefixes = tuple(f"{d} §" for d in known_ids) + tuple(f"{d}:" for d in known_ids)
    return [
        e
        for e in report.errors
        if e.startswith(target_prefixes) or not e.startswith(known_prefixes)
    ]


def resolve_reviewer(root: Path, by: str | None) -> str:
    """Reviewer identity for a review record: `--by` wins, else git config.

    Raises ValueError when neither is available — approval must never be
    recorded under a blank/unknown identity.
    """
    if by and by.strip():
        return by.strip()
    name = gitio.config_value(root, "user.name")
    email = gitio.config_value(root, "user.email")
    if not name and not email:
        raise ValueError(
            "no reviewer identity: pass --by 'name <email>' or set git user.name/user.email"
        )
    return f"{name} <{email}>" if name and email else (name or email)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _resolve_wanted_sections(
    manifest: models.Manifest, section_ids: list[str] | None
) -> tuple[set[str] | None, list[str]]:
    """(wanted ids, missing ids). `wanted=None` means "every section" —
    section ids are NOT unique (regulatory docs restart §-numbering inside
    each part), so a plain {id: section} dict would collapse duplicates."""
    if section_ids is None:
        return None, []
    wanted = set(section_ids)
    present = {s.id for s in manifest.sections}
    missing = [sid for sid in dict.fromkeys(section_ids) if sid not in present]
    return wanted, missing


def _flip_summarized_sections(
    kb_dir: Path, doc_id: str, manifest: models.Manifest, wanted: set[str] | None, by: str
) -> tuple[list[str], list[str], list[str]]:
    """Flip status summarized → reviewed for the wanted sections; return
    (flipped ids, skipped-pending ids, skipped-machine ids). Ids repeat within
    a file (duplicate §-numbering across parts), so the hash must be pinned
    to THIS row's heading occurrence — the same occurrence `kb build`
    resolves it to — or two summarized rows sharing an id would both hash
    occurrence 0, and the second row's review record would drift from its
    real L2 slice on the very next build."""
    occurrences = heading_occurrences(manifest.sections)
    l2_cache: dict[str, str] = {}
    at = _now()
    flipped: list[str] = []
    skipped_pending: list[str] = []
    skipped_machine: list[str] = []
    for row, sec in enumerate(manifest.sections):
        if wanted is not None and sec.id not in wanted:
            continue
        if wanted is None and sec.id.startswith(MACHINE_SECTION_PREFIX):
            if sec.id not in skipped_machine:
                skipped_machine.append(sec.id)
            continue
        if sec.status == "summarized":
            if sec.file not in l2_cache:
                l2_cache[sec.file] = (kb_dir / doc_id / f"{sec.file}.md").read_text(
                    encoding="utf-8"
                )
            l2_slice = slice_section(l2_cache[sec.file], sec.id, occurrence=occurrences[row]) or ""
            sec.status = "reviewed"
            sec.reviewed = models.ReviewRecord(by=by, at=at, l2_sha256=quality.digest(l2_slice))
            flipped.append(sec.id)
        elif sec.status == "pending":
            skipped_pending.append(sec.id)
    return flipped, skipped_pending, skipped_machine


def approve_sections(
    kb_dir: Path, doc_id: str, section_ids: list[str] | None = None, *, by: str
) -> ApproveReport:
    """Flip status summarized → reviewed in <doc>/_manifest.yaml.

    section_ids=None targets every section of the doc. `pending` sections
    are skipped and reported (cannot approve what isn't summarized yet);
    `reviewed` sections are left untouched, so re-running is safe. Every
    section flipped gets a `reviewed` record: who (`by`), when, and the
    sha256 of the L2 slice they signed off on — a later `kb build` compares
    that hash against the current L2 slice to catch post-review edits.
    """
    manifest_path = kb_dir / doc_id / "_manifest.yaml"
    if not manifest_path.exists():
        raise ValueError(f"doc '{doc_id}' is not in the worktree ({manifest_path})")
    manifest = models.load_yaml_model(manifest_path, models.Manifest)

    report = ApproveReport(doc_id=doc_id)
    wanted, report.missing = _resolve_wanted_sections(manifest, section_ids)
    report.flipped, report.skipped_pending, report.skipped_machine = _flip_summarized_sections(
        kb_dir, doc_id, manifest, wanted, by
    )

    if report.flipped:
        models.save_yaml_model(manifest_path, manifest)
    return report


def changed_section_ids(kb_dir: Path, doc_id: str, against: str) -> list[str] | None:
    """Ids of sections added or changed (summary/prose/content) vs `against`.

    None means the doc does not exist at `against` at all (brand-new doc) —
    the caller should treat every section as changed.
    """
    kb_abs = kb_dir.resolve()
    root = gitio.git_root(kb_abs)
    if gitio.read_at(root, against, kb_abs / doc_id / "_manifest.yaml") is None:
        return None
    report = diff_doc(kb_dir, doc_id, against=against)
    return [c.section_id for c in report.added] + [
        c.section_id for c in report.changed
    ]


def approve_all_changed(
    kb_dir: Path, against: str, doc_id: str | None = None, *, by: str
) -> list[ApproveReport]:
    """Approve the sections that differ from `against` (CI mode).

    doc_id=None scans every doc in index.yaml; docs whose manifest is
    missing in the worktree are skipped. Docs with no changes produce no
    report. Raises GitError on a bad rev, ValueError on a missing doc/index.
    """
    if doc_id is not None:
        doc_ids = [doc_id]
    else:
        index_path = kb_dir / "index.yaml"
        if not index_path.exists():
            raise ValueError(f"KB index not found ({index_path})")
        index = models.load_yaml_model(index_path, models.KBIndex)
        doc_ids = [
            e.id for e in index.docs if (kb_dir / e.id / "_manifest.yaml").exists()
        ]

    reports: list[ApproveReport] = []
    for did in doc_ids:
        changed = changed_section_ids(kb_dir, did, against)
        if changed is not None and not changed:
            continue  # doc untouched since `against`
        reports.append(approve_sections(kb_dir, did, changed, by=by))
    return reports
