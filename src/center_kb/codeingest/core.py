"""codeingest.core — protocol, deterministic orchestration, and KB writer.

`kb code-ingest` turns a codebase into a 4-layer KB document at
`.kb/<repo_id>-code/` without any LLM in the loop: extractors (Tasks B2-B7)
each look for one kind of evidence (services, deps, commands, ...) and
produce `CodeSection`s; `run()` here sorts them, writes one `<group>.md` +
`<group>.raw.md` pair per group, and upserts the manifest + KB index. Output
must be a pure function of the working tree — no wall-clock, no network.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Protocol

import yaml
from pydantic import ValidationError

from center_kb import models
from center_kb.mdutils import _HEADING_RE

# `_HEADING_RE` is imported rather than re-derived: `mdutils.py` is frozen
# (off-limits to edit) but this module needs the *exact* same '## <id>
# <title>' grammar mdutils itself uses, both to find a section's start and
# — the whole point of `_slice_known_section` below — to tell a real
# section heading apart from a human's own free-form '## Something'
# subheading. Re-implementing the regex here instead of importing it would
# risk the two definitions drifting apart (Defect 4 in this stage).


@dataclass(frozen=True)
class CodeSection:
    id: str          # e.g. "svc.airspace-service" — no whitespace (mdutils._HEADING_RE)
    title: str       # e.g. "airspace-service"
    summary: str     # 1-2 deterministic sentences; MUST be non-empty (build invariant)
    group: str       # output file stem, e.g. "services" -> services.md + services.raw.md
    l2_md: str       # body under the "## <id> <title>" heading in the L2 file
    l3_md: str       # body under the same heading in the L3 file; fenced blocks only


@dataclass
class ExtractResult:
    sections: list[CodeSection] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CodeIngestOptions:
    repo_root: Path
    kb_dir: Path
    doc_id: str
    repo_id: str
    db_paths: tuple[Path, ...] = ()
    tags: tuple[str, ...] = ()
    scaffold_svc: bool = False

    def __post_init__(self) -> None:
        # Ruling R23, made durable for every caller (not just the CLI):
        # `tree.walk_tree()` resolves a relative `kb_dir` against
        # `repo_root`, while this module's own writer previously left a
        # relative `kb_dir` to resolve against the process CWD — a
        # legitimate source directory that happens to share a relative
        # --kb-dir's name could be pruned from the tree while the real
        # output directory landed somewhere else entirely. Doing this once
        # here, on the frozen dataclass itself, means every construction
        # site (the CLI, a test, a future MCP tool) gets it for free
        # instead of each caller needing its own copy of the fix.
        # `db_paths` gets the same treatment: a relative `--db` used to
        # resolve against the CWD too, the exact ambiguity R23 removed for
        # `kb_dir`.
        root = self.repo_root.resolve()
        kb = self.kb_dir if self.kb_dir.is_absolute() else root / self.kb_dir
        db_paths = tuple(
            (p if p.is_absolute() else root / p).resolve() for p in self.db_paths
        )
        object.__setattr__(self, "repo_root", root)
        object.__setattr__(self, "kb_dir", kb.resolve())
        object.__setattr__(self, "db_paths", db_paths)


@dataclass
class CodeIngestReport:
    doc_id: str
    sections_by_extractor: dict[str, int] = field(default_factory=dict)
    files_written: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    detected: list[str] = field(default_factory=list)       # extractor names that fired
    scaffolded: list[str] = field(default_factory=list)     # new -svc section ids
    stale_risk: list[str] = field(default_factory=list)     # -svc ids whose evidence moved
    orphans: list[str] = field(default_factory=list)        # -svc ids with no -code peer
    dirty_tree: bool = False


class Extractor(Protocol):
    name: str

    def detect(self, root: Path) -> bool: ...
    def extract(self, root: Path, opts: CodeIngestOptions) -> ExtractResult: ...


class CodeIngestError(Exception):
    """Raised when code-ingest finds no evidence beyond the repo tree itself,
    when two extractors claim the same section id, or when --scaffold-svc
    finds the -svc document unsafe to upsert blind.

    Carries the partial `CodeIngestReport` built so far (once one exists —
    the very first guard in `run()` fires before it does, so `report` can
    still be `None`), so a caller can surface warnings already collected
    (e.g. "could not read _manifest.yaml") instead of only this
    exception's own message, and can tell whether the -code document was
    already written and indexed before a later --scaffold-svc refusal
    (Important 5 follow-up, review round 3): without this, the CLI's
    error path only ever showed `str(exc)` and silently discarded
    `report.warnings`, so a corrupt -svc manifest surfaced as "no matching
    entry in _manifest.yaml — restore the manifest entries" with no hint
    that the manifest was simply unreadable, and no indication that the
    -code document's own write had already succeeded.
    """

    def __init__(self, message: str, report: CodeIngestReport | None = None) -> None:
        super().__init__(message)
        self.report = report


# ---------------------------------------------------------------------------
# git helpers — local (not center_kb.gitio) because a non-git scratch
# directory is a valid code-ingest target: these degrade gracefully instead
# of raising.
# ---------------------------------------------------------------------------


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )


def _head_commit(root: Path) -> str:
    proc = _git(root, "rev-parse", "HEAD")
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _head_date(root: Path) -> date | None:
    """The HEAD commit's *committer* date — never date.today() (determinism)."""
    proc = _git(root, "show", "-s", "--format=%cs", "HEAD")
    if proc.returncode != 0:
        return None
    out = proc.stdout.strip()
    if not out:
        return None
    try:
        return date.fromisoformat(out)
    except ValueError:
        return None


def _is_dirty(root: Path) -> bool:
    proc = _git(root, "status", "--porcelain")
    return proc.returncode == 0 and bool(proc.stdout.strip())


# ---------------------------------------------------------------------------
# renderer
# ---------------------------------------------------------------------------


def _render_group(
    sections: list[CodeSection], level: str, banner: str, doc_id: str, preamble: str = ""
) -> str:
    """Render one L2 (`level="l2"`) or L3 (`level="l3"`) group file.

    `sections` must already be sorted — the renderer only lays them out.
    `preamble`, when non-empty, is emitted verbatim right after the H1 +
    banner block and before the first section — the one piece of
    free-standing human prose `scaffold_svc()` can lift and preserve
    (Ruling R46b): it sits above every section heading, so
    `_slice_known_section()` (which only ever lifts text starting at a
    heading) can never reach it on its own, and without this parameter
    every `--scaffold-svc` re-render would silently drop it.
    """
    lines: list[str] = [f"# {doc_id}", "", banner, ""]
    if preamble:
        lines.extend(preamble.splitlines())
        lines.append("")
    for sec in sections:
        body = sec.l2_md if level == "l2" else sec.l3_md
        lines.append(f"## {sec.id} {sec.title}")
        lines.append("")
        lines.extend(body.splitlines())
        lines.append("")
    text = "\n".join(lines)
    return text.rstrip("\n") + "\n"


def _write_group(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------


def run(opts: CodeIngestOptions) -> CodeIngestReport:
    report = CodeIngestReport(doc_id=opts.doc_id)

    # Controller Ruling R47(a): three rounds of this guard were each
    # defeated by a new way to *spell* the same directory ("demo-svc/",
    # "Demo-svc", ...) because every comparison so far compared the raw
    # `opts.doc_id` *string*. Every comparison below is against a path
    # instead — never against `opts.doc_id` itself — but Controller
    # Ruling R48b (review round 5) split that into two different
    # questions that need two different path forms, after round 5's
    # first attempt (a single `.resolve()`d path for everything) refused
    # a legitimate setup: a document directory that is itself a junction
    # to storage elsewhere (Windows junctions need no privilege; symlinks
    # are ordinary on Linux/macOS).
    #
    # - Containment ("did this id escape --kb-dir?") is judged on the
    #   *logical* path below: "."/".."/repeated-separator segments
    #   normalised away textually, but no symlink/junction anywhere along
    #   the way is followed. A junctioned document directory is logically
    #   still "inside" --kb-dir; only a doc_id that is textually absolute
    #   or walks out via ".." has actually escaped. Judging containment
    #   on the *resolved* (link-following) path instead — what this
    #   guard did before this ruling — refused that legitimate junction
    #   outright, naming --repo-id/--doc-id as the cause when neither was.
    # - Identity ("is this the reserved slot / an already-curated
    #   destination?") is judged on the *resolved* path, which does
    #   follow links: two different-looking paths that are the same
    #   physical directory (a junction, a differently-cased name on a
    #   case-insensitive filesystem, a trailing dot Windows silently
    #   drops) must still compare equal, and the destination check must
    #   read the *real* file content, wherever a link leads.
    #
    # Known, undefeated limitation (documented rather than silently left
    # closed): a *chain* of junctions/symlinks could still be logically
    # contained while physically elsewhere by the time identity is
    # judged below. This is strictly narrower than the over-fire this
    # ruling closed (a single legitimate junction refusing the command
    # outright), and honest documentation of it beats a guard that blocks
    # a legitimate setup.
    logical_dir = Path(os.path.normpath(str(opts.kb_dir / opts.doc_id)))

    if not logical_dir.is_relative_to(opts.kb_dir):
        raise CodeIngestError(
            f"--doc-id {opts.doc_id!r} resolves to {logical_dir}, which "
            f"is outside --kb-dir {opts.kb_dir}; refusing to write "
            "outside the KB directory",
            report=report,
        )
    if logical_dir == opts.kb_dir:
        raise CodeIngestError(
            f"--doc-id {opts.doc_id!r} resolves to --kb-dir "
            f"{opts.kb_dir} itself; choose a non-empty --doc-id naming a "
            "subdirectory",
            report=report,
        )
    # Controller Ruling R47(d): a doc_id whose final path component ends
    # in a space or a dot is never normalised by pathlib and was never
    # validated before use. Windows silently strips a trailing space/dot
    # from the *final* component of a single filesystem call — so
    # `doc_dir.mkdir()` quietly creates "demo-code", not "demo-code " —
    # but does NOT apply that stripping to an *interior* component of a
    # longer path, so `(doc_dir / "services.md").write_text(...)`, where
    # "demo-code " is no longer the final component, looks up the
    # literal space-suffixed name, finds nothing, and raised a raw
    # `FileNotFoundError` out of `_write_group` instead of the
    # `CodeIngestError` every other bad input here raises. Rejecting it
    # outright — on every OS, not just Windows — also avoids the sibling
    # hazard of two different --doc-id spellings ("demo-code" and
    # "demo-code ") silently aliasing one directory while `index.yaml`
    # and `_manifest.yaml` still record whichever spelling was typed
    # last (the same "two entries, one directory" shape R47 was opened
    # to close). Judged on `logical_dir` — this is a property of the
    # literal characters typed, not of what a link happens to lead to,
    # so it fires unconditionally, whether or not anything exists yet at
    # the target (Ruling R48b).
    if logical_dir.name != logical_dir.name.rstrip(" ."):
        raise CodeIngestError(
            f"--doc-id {opts.doc_id!r} ends in a trailing space or dot "
            f"({logical_dir.name!r}); some filesystems silently strip "
            "this, which would make two different --doc-id spellings "
            "alias the same directory - choose a --doc-id without one",
            report=report,
        )

    # Identity from here on (Ruling R48b): `doc_dir` follows any
    # symlink/junction to the real target, exactly like every read/write
    # below it does.
    doc_dir = logical_dir.resolve()

    # Controller Ruling R48a(2): round 4's blanket "-svc is a reserved
    # suffix, full stop, regardless of repo_id" check is restored here.
    # R47(a) only objected to comparing the *raw* `opts.doc_id` string,
    # not to the concept — but round 5 also narrowed the check's *scope*
    # to only *this run's own* `<repo_id>-svc` slot, in the same round it
    # dropped the `index.yaml` "curated" tag signal (Ruling R47c). That
    # left a doc_id ending in "-svc" for an *unrelated* repo_id (e.g.
    # `--repo-id other --doc-id demo-svc`) covered by the destination
    # check alone — and the destination check's only signal for a
    # freshly-scaffolded document with no notes yet was, at that point, a
    # human-editable banner inside `services.md` (Ruling R48a(1) restores
    # a machine-owned signal for that; see `_is_curated_destination()`
    # below). Computed on the *resolved* final component, per R48b — not
    # the raw string, and not the pre-link `logical_dir` — so a
    # "-svc"-suffixed *name* is still what's being judged
    # (case-insensitively, via `.casefold()`, which needs no filesystem
    # query to work: only the separator/dot spellings collapsed in
    # `logical_dir` above ever needed one).
    if doc_dir.name.casefold().endswith("-svc"):
        raise CodeIngestError(
            f"--doc-id {opts.doc_id!r} resolves to {doc_dir}, whose name "
            "ends in the reserved '-svc' suffix; choose a different "
            "--doc-id",
            report=report,
        )

    manifest_path = doc_dir / "_manifest.yaml"
    # Loaded once, here, and reused below for tokens_by_id (Ruling R47e):
    # round 4's guard called `_load_manifest_guarded` a second time on
    # this exact path purely to preserve token counts, so a wrong-shaped
    # `_manifest.yaml` emitted the identical "could not read" warning
    # twice instead of the one review round 2 intended.
    existing_code_manifest = _load_manifest_guarded(manifest_path, opts.doc_id, report)

    # (b) Destination check: the durable half — protects the actual
    # asset regardless of what doc_id/repo_id are spelled, so it holds
    # even for a doc_id that reaches a curated document without its own
    # resolved name ending in "-svc" at all (e.g. via a symlink/junction
    # with an unrelated name — the reserved-suffix check above is a
    # naming convention, not an asset check, and can't see through one).
    # Checked
    # before anything — including the stale-.md prune below — is
    # written.
    if _is_curated_destination(doc_dir, existing_code_manifest, opts.doc_id):
        raise CodeIngestError(
            f"--doc-id {opts.doc_id!r} targets {doc_dir}, which already "
            "holds a curated document; choose a different --doc-id or "
            "--repo-id",
            report=report,
        )

    report.dirty_tree = _is_dirty(opts.repo_root)

    owned: list[tuple[str, CodeSection]] = []
    for extractor in ALL_EXTRACTORS:
        detected = extractor.detect(opts.repo_root)
        if extractor.name == "schema" and opts.db_paths:
            # Ruling R3: `Extractor.detect(self, root)` is never passed
            # `opts` (the frozen protocol B1 published), so
            # SchemaExtractor.detect() cannot see opts.db_paths — on a repo
            # with no migration/prisma/alembic/EF source it would return
            # False and extract() would never run, silently dropping an
            # explicit --db. Treat schema as detected whenever the caller
            # named an explicit db path, regardless of what detect() saw.
            # (Covered by tests/test_cli_codeingest.py — see the "Ruling
            # R3" section there; the CLI is the only caller that can hand
            # this a fresh repo with no migrations at all.)
            detected = True
        if not detected:
            continue
        report.detected.append(extractor.name)
        result = extractor.extract(opts.repo_root, opts)
        report.sections_by_extractor[extractor.name] = len(result.sections)
        owned.extend((extractor.name, sec) for sec in result.sections)
        report.warnings.extend(result.warnings)

    # Gate on what extract() actually *produced*, not on what detect() said
    # (task review, Important 1). Every extractor's detect() is
    # deliberately looser than its extract() — an ordinary typo in --db, or
    # a pyproject.toml holding only an unrelated [tool.*] table, can make
    # detect() return True while extract() finds nothing real. Keying the
    # gate off report.detected let that slip through and ship a tree-only
    # document with exit 0. report.detected is left untouched for
    # reporting (the CLI still shows what fired).
    if not any(
        count > 0
        for name, count in report.sections_by_extractor.items()
        if name != "tree"
    ):
        kinds = [e.name for e in ALL_EXTRACTORS if e.name != "tree"]
        raise CodeIngestError(
            f"no code artifacts detected under {opts.repo_root} — "
            f"looked for: {', '.join(kinds)}",
            report=report,
        )

    owned.sort(key=lambda pair: (pair[1].group, pair[1].id))

    owner_by_id: dict[str, str] = {}
    for owner, sec in owned:
        prior = owner_by_id.get(sec.id)
        if prior is not None:
            raise CodeIngestError(
                f"duplicate section id {sec.id!r}: claimed by both "
                f"{prior!r} and {owner!r}",
                report=report,
            )
        owner_by_id[sec.id] = owner
    sections = [sec for _, sec in owned]

    # `existing_code_manifest` was already loaded once, above, to feed
    # the destination check — reused here rather than read a second time
    # (Ruling R47e).
    tokens_by_id: dict[str, models.SectionTokens] = {}
    if existing_code_manifest is not None:
        tokens_by_id = {s.id: s.tokens for s in existing_code_manifest.sections}

    groups: dict[str, list[CodeSection]] = {}
    for sec in sections:
        groups.setdefault(sec.group, []).append(sec)

    full_commit = _head_commit(opts.repo_root)
    short_commit = full_commit[:7] if full_commit else ""
    banner = (
        f"> Generated by kb code-ingest at {short_commit or 'unknown-commit'} — "
        "do not edit by hand."
    )

    try:
        doc_dir.mkdir(parents=True, exist_ok=True)
        written_names: set[str] = set()
        for group, secs in groups.items():
            l2_path = doc_dir / f"{group}.md"
            l3_path = doc_dir / f"{group}.raw.md"
            _write_group(l2_path, _render_group(secs, "l2", banner, opts.doc_id))
            _write_group(l3_path, _render_group(secs, "l3", banner, opts.doc_id))
            report.files_written.append(l2_path.name)
            report.files_written.append(l3_path.name)
            written_names.add(l2_path.name)
            written_names.add(l3_path.name)

        # Prune group files from a previous run that this run no longer
        # produces (an extractor stopped detecting, a service was
        # deleted, ...). Left behind, they'd carry the "do not edit by
        # hand" banner forever and `kb doctor` would flag each one as a
        # permanent orphan-file warning since the manifest no longer
        # references them.
        for stale in doc_dir.glob("*.md"):
            if stale.name not in written_names:
                stale.unlink()

        manifest = models.Manifest(
            id=opts.doc_id,
            title=f"{opts.repo_id} — code knowledge",
            revision=short_commit,
            source_sha256=full_commit,
            ingested=_head_date(opts.repo_root),
            sections=[
                models.SectionEntry(
                    id=sec.id,
                    title=sec.title,
                    summary=sec.summary,
                    status="summarized",
                    file=sec.group,
                    tokens=tokens_by_id.get(sec.id, models.SectionTokens()),
                )
                for sec in sections
            ],
        )
        models.save_yaml_model(manifest_path, manifest)
        report.files_written.append(manifest_path.name)
    except OSError as exc:
        # Ruling R47(d), defense in depth: the explicit trailing-space/
        # dot rejection above closes the exact reported crash; this
        # catches the surrounding class (a reserved device name, a
        # character this OS's filesystem rejects, ...) the same way,
        # rather than letting a raw traceback out of a filesystem call
        # several frames down.
        raise CodeIngestError(
            f"could not write --doc-id {opts.doc_id!r}'s document under "
            f"{doc_dir} ({exc})",
            report=report,
        ) from exc

    _upsert_index_entry(
        opts.kb_dir, opts.doc_id, manifest.title, manifest.revision,
        f"Generated code knowledge for the {opts.repo_id} repository.",
        ["code", "generated"], opts.tags, report,
    )

    if opts.scaffold_svc:
        scaffold_svc(opts, sections, report)

    return report


def _load_manifest_guarded(
    manifest_path: Path, doc_id: str, report: CodeIngestReport
) -> models.Manifest | None:
    """Guards the top-level shape of a possibly-hand-edited `_manifest.
    yaml` before reading it back (Defect 3 in this stage: a wrong-shaped
    top-level document unwinding past a per-file handler deleted a whole
    reader's output with no file named). A missing or malformed manifest
    degrades to "no prior state" with a named warning, rather than
    crashing the whole command.

    Shared by two read-backs (Important 5 — only one of these three total
    reads in this module was guarded at all before this fix): `run()`'s
    own read of the `-code` document's prior manifest (used only to
    preserve token counts — losing that on a corrupt file is harmless,
    `kb build` recomputes them from scratch) and `scaffold_svc()`'s read
    of the `-svc` document's prior manifest (where losing it is NOT
    harmless — see the stray-heading check in `scaffold_svc()`, which is
    what actually keeps that read-back safe rather than this guard alone).
    """
    if not manifest_path.exists():
        return None
    try:
        return models.load_yaml_model(manifest_path, models.Manifest)
    except (yaml.YAMLError, OSError, UnicodeDecodeError, ValidationError) as exc:
        report.warnings.append(
            f"could not read {manifest_path} ({exc}) - treating {doc_id} "
            "as if it had no prior state"
        )
        return None


def _is_curated_destination(
    doc_dir: Path, manifest: models.Manifest | None, doc_id: str
) -> bool:
    """True when `doc_dir` already holds a curated document — checked by
    inspecting the actual target on disk, never by comparing `doc_id`
    strings (Controller Ruling R47, replacing review round 4's guard).

    **Primary, machine-owned signal (Controller Ruling R48a(1)).** Round
    5's first attempt made the "Responsibility text is human-owned"
    banner `scaffold_svc()` writes into `services.md` the *only* signal
    that exists from a document's first scaffold run — but that banner
    lives inside a file the whole point of `--scaffold-svc` is to hand a
    human for editing. Two states silently destroyed human content as a
    result: a human rewriting `services.md`'s prose without preserving
    the banner line, and a curated document with reviewed summaries in
    `_manifest.yaml` but no `services.md` on disk at all — a state this
    codebase explicitly supports and self-heals from elsewhere (see
    `scaffold_svc()`'s "missing services.md" branch). Neither state can
    be told apart from an ordinary, empty destination if the banner is
    the only thing being asked.

    So the primary signal is the manifest itself, which a human curating
    prose has no reason to hand-edit and `scaffold_svc()`/`run()` never
    produce the same way:
    - `manifest.title` ends with `"curated service knowledge"` — the
      exact suffix `scaffold_svc()` writes, as opposed to `run()`'s own
      `"... code knowledge"` (checked in both directions to be sure they
      cannot collide: measured on both documents, never equal to the
      other).
    - any section's `status` is `"pending"` or `"reviewed"`, **and**
      `manifest.id != doc_id` (Controller Ruling R49(1), added at Task
      B10) — `run()` always writes `-code` sections with
      `status="summarized"` and never anything else; `scaffold_svc()`
      never writes `"summarized"` for a `svc.*` section (new ones start
      `"pending"`, existing ones keep whatever status they already had,
      which can only itself have started as `"pending"` and possibly
      been promoted to `"reviewed"` by a human). The `manifest.id !=
      doc_id` half closes a regression verified at Task B10: two
      ordinary sibling commands write exactly those statuses onto a
      `-code` document's *own* manifest — `kb summarize --redo` with no
      DOC_ID (`summarize.redo_reset()`, iterating every doc in
      `index.yaml`) and `kb approve --all-changed` with no DOC_ID
      (`review.approve_all_changed()` / `approve_sections()`, same
      iteration). Without the identity gate, either command left its own
      `-code` document permanently unable to re-ingest itself: the
      manifest this check reads back at line ~330 above IS the one
      those commands just mutated, `manifest.id` always equals `doc_id`
      in that case, and the status signal fired on the document's own
      prior run rather than on a genuinely different one. Gating on
      identity keeps the signal doing its job for a *foreign* document —
      a manifest whose `id` names an unrelated document that happens to
      sit at this run's resolved destination — while removing the
      self-reference.
    Either one alone is enough; both survive `services.md` not existing,
    and both survive a human rewriting its prose (there is no reason for
    curated-prose editing to touch either).

    **Three more signals below are present in the code but, per Ruling
    R49(4), this docstring no longer claims each has an isolating test —
    it previously did, and that claim was false: no isolating test exists
    for any of the three, and writing one for each is recorded as
    parked, not done (see Task B10's brief). The banner in particular is
    not merely secondary: when `manifest` is `None` (a missing or
    unreadable `_manifest.yaml` — see `_load_manifest_guarded()` above),
    neither the title check, the status check, nor the second bullet
    below (the `flow.`/`hist.` section check — implemented as the third
    `if manifest is not None:` sub-check above, alongside title and
    status, not as separate code down here) can run at all, so a
    curated document with an unreadable manifest is refused by the
    banner alone. Treating it as safe to delete because the docstring
    once called it "secondary" would silently strip that state's only
    protection.**
    - the "Responsibility text is human-owned" banner in `services.md`.
    - `manifest` (the caller's own single guarded read of this
      directory's `_manifest.yaml`, passed in rather than reloaded here
      so a wrong-shaped file only ever produces one warning — Ruling
      R47e) carrying any `flow.*`/`hist.*` section.
    - `flows.md`/`history.md` already on disk.

    Deliberately drops review round 4's `index.yaml` "curated"-tag
    signal (Ruling R47c) — it compared `doc_id` strings (the class of
    comparison R47 ends) and was self-defeating: `--tags curated` on an
    ordinary `-code` run wrote that tag onto the document's *own* index
    entry, so that document's next run found its own prior tag and
    refused itself forever.

    Degrades toward *not* refusing when a signal can't be read — a
    destination check is exactly the kind of guard that over-fires, so
    an unreadable file just means that one signal contributes nothing,
    never that the whole check aborts or assumes the worst.
    """
    if manifest is not None:
        if manifest.title.endswith("curated service knowledge"):
            return True
        if manifest.id != doc_id and any(
            s.status in ("pending", "reviewed") for s in manifest.sections
        ):
            return True
        if any(s.id.startswith(("flow.", "hist.")) for s in manifest.sections):
            return True

    services_md = doc_dir / "services.md"
    if services_md.exists():
        try:
            text = services_md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = ""
        if "Responsibility text is human-owned" in text:
            return True

    return (doc_dir / "flows.md").exists() or (doc_dir / "history.md").exists()


def _upsert_index_entry(
    kb_dir: Path,
    doc_id: str,
    title: str,
    revision: str,
    summary: str,
    base_tags: list[str],
    extra_tags: tuple[str, ...],
    report: CodeIngestReport,
) -> None:
    """Shared by both the `-code` document (`run()`) and the curated
    `-svc` scaffold (`scaffold_svc()`) — the only difference between the
    two callers is which tag pair and summary sentence they pass in, so
    one function upserts both rather than two near-duplicate copies of
    the same merge logic (Defect 4 in this stage: duplicated logic fixed
    in one branch three rounds running).

    A wrong-shaped `index.yaml` (Defect 3 / Important 5) degrades to
    "leave the file untouched this run" rather than either crashing the
    whole command or — the more dangerous alternative — silently
    replacing it with a fresh empty index, which would erase every
    *other* document's entry along with the corrupt one. A named warning
    is the only visible effect; `doc_id`'s own entry simply isn't updated
    until the file is fixed by hand.
    """
    index_path = kb_dir / "index.yaml"
    if index_path.exists():
        try:
            index = models.load_yaml_model(index_path, models.KBIndex)
        except (yaml.YAMLError, OSError, UnicodeDecodeError, ValidationError) as exc:
            report.warnings.append(
                f"could not read {index_path} ({exc}) - leaving it untouched "
                f"this run ({doc_id}'s index entry was not updated)"
            )
            return
    else:
        index = models.KBIndex()

    wanted = [*base_tags, *extra_tags]

    entry = next((d for d in index.docs if d.id == doc_id), None)
    if entry is None:
        index.docs.append(
            models.IndexEntry(
                id=doc_id, title=title, revision=revision,
                tags=list(wanted), summary=summary,
            )
        )
    else:
        preserved = [t for t in entry.tags if t not in wanted]
        entry.title = title
        entry.revision = revision
        # Final review, Important 2: `entry.summary` may already hold a
        # real, LLM-drafted L0 doc summary written by `summarize.
        # _fill_doc_summaries()` — and once written, no `kb summarize` run
        # can ever produce it again (that function skips any doc with no
        # pending sections, and every section here is non-pending after
        # the seed completes). `scaffold_svc()` calls this on EVERY
        # `--scaffold-svc` run, including the routine re-run `dev-code-
        # seed` step 2 and the documented amend loop both make forever
        # after — always passing the same static placeholder. Overwriting
        # unconditionally therefore reverts the drafted summary back to
        # the placeholder the very first time either of those ordinary,
        # documented re-runs happens, with no way back through the
        # documented toolset. Only replace it when there is nothing
        # drafted yet (empty) or it already IS this call's own
        # placeholder (an ordinary re-run before drafting has ever
        # happened) — never when it holds something else. A genuinely new
        # document (the `entry is None` branch above) is unaffected and
        # still always gets the placeholder.
        if not entry.summary or entry.summary == summary:
            entry.summary = summary
        entry.tags = wanted + preserved

    models.save_yaml_model(index_path, index)


# ---------------------------------------------------------------------------
# --scaffold-svc — the curated `.kb/<repo_id>-svc/` document (Ruling R10)
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _name_tokens(text: str) -> set[str]:
    """Lower-cased alnum tokens — the "name match" rule `scaffold_svc`'s
    evidence builder uses to decide whether a file path or a `db.*`
    table id "belongs" to a service. Requiring the service's tokens to
    be a *subset* of the target's tokens (`wanted <= _name_tokens(x)`,
    never `wanted & _name_tokens(x)`) is what Important-3 fixed: a bare
    intersection matched on any *single* shared token, so
    `svc.airspace-service` (tokens {airspace, service}) claimed every
    other `*/service.py` in the repo purely via the token `service`, and
    `svc.cache-db` claimed every SQL migration and `db.*` table purely
    via the token `db`. Subset containment still matches the case this
    exists for — `{airspace, service} <= {src, airspace, service, py}`
    for `src/airspace/service.py` — while dropping every one of those
    false attributions, at the acceptable cost of also dropping some
    looser true matches (a table named only `restrictive_airspace` no
    longer "reaches" `airspace-service` merely by sharing `airspace`,
    since it doesn't also contain `service`) — this codebase's evidence
    is meant to warn/omit rather than fabricate throughout (see
    schema.py's own docstring), and precision matters more than recall
    for a join key Stage C treats as ground truth."""
    return set(_TOKEN_RE.findall(text.lower()))


def _service_evidence(
    root: Path,
    tree_entries: list[tuple[int, Path, list[str]]],
    sec: CodeSection,
    db_sections: list[CodeSection],
) -> str:
    """Deterministic, sorted, fenced L3 evidence for one `svc.*` section:
    the section's own extractor-rendered evidence (image/ports/env-keys —
    already sanitised, spec §3.11) plus a bare list of file paths whose
    name tokens are a superset of the service's own (Important 3), and
    the `db.*` table ids it appears to reach by the same rule — tokenising
    only the table name *after* the `db.` namespace prefix (`s.id.split(
    ".", 1)[1]`), never the prefix itself, so a service named `*-db`
    doesn't match every table purely because its own name contains the
    token `db`.

    `tree_entries` is `walk_tree(root, kb_dir)`'s result, walked exactly
    once by the caller and shared across every service in this run — a
    per-service full tree walk was a real (if minor) performance defect
    the controller review flagged.

    Controller Ruling R42 (Critical 1): this function used to also open
    each matched file and embed its first-5-line docstring/comment
    header as "evidence". Removed entirely, not narrowed — a file's
    *content* can carry a secret (a DSN in a header comment, a password
    on an `.env`-shaped file's first line) no matter how comment-shaped
    the surrounding text looks, and no content classifier can reliably
    tell a helpful module docstring apart from a leak. This document is
    published to the hub (`publish.py`'s snapshot syncs all of `.kb/`),
    so the only safe rule is to never open the file at all. Only the
    *path* — never a byte of the file's content — is evidence here;
    Stage C's `dev-code-seed` has the actual repo checked out when a
    human needs to read further.
    """
    wanted = _name_tokens(sec.title)

    files: list[str] = []
    if wanted:
        for _depth, reldir, filenames in tree_entries:
            for name in filenames:
                relpath = relposix(root, root / reldir / name)
                if wanted <= _name_tokens(relpath):
                    files.append(relpath)
    files = sorted(set(files))

    tables = sorted(
        s.id for s in db_sections
        if wanted and wanted <= _name_tokens(s.id.split(".", 1)[1])
    )

    # Stage C task review (R6, following the Stage B handover's item 2, and
    # Minor 7 extending it to "files:"): a bare "files:"/"tables:" label
    # reads as the factual claim "this service touches no files/tables"
    # when it renders "- none" -- but both matches are the identical
    # same-name-token-superset heuristic (see the docstring above) that
    # essentially never fires on a realistically-named repo. Label both
    # honestly as what they are, so "- none" reads as "no name match
    # found", not "no files/tables found" -- leaving one bare and the
    # other relabelled would make two lines in the same fenced block claim
    # different epistemic strength from the same rule. The rendered list
    # shape below is otherwise unchanged.
    lines = ["```text", "files (name-match heuristic; absence proves nothing):"]
    if files:
        lines.extend(f"  - {f}" for f in files)
    else:
        lines.append("  - none")
    lines.append("tables (name-match heuristic; absence proves nothing):")
    if tables:
        lines.extend(f"  - {t}" for t in tables)
    else:
        lines.append("  - none")
    lines.append("```")
    evidence_block = "\n".join(lines) + "\n"

    base = sec.l3_md.rstrip("\n")
    return f"{base}\n\n{evidence_block}" if base else evidence_block


def _body_only(heading_and_body: str) -> str:
    """`_slice_known_section()` (like `mdutils.slice_section()`) returns
    the `## <id> <title>` heading line together with the body;
    `_render_group()` re-derives that heading itself from a
    `CodeSection`'s own `id`/`title`, so re-feeding a slice through it
    verbatim would duplicate the heading. Splitting it back off here is
    what makes "lift the old slice out and re-emit it unchanged" (Step
    4) actually round-trip byte-for-byte."""
    _heading, _, rest = heading_and_body.partition("\n")
    return rest.lstrip("\n")


def _heading_id_counts(text: str) -> dict[str, int]:
    """How many times each real `## <id> <title>` heading id occurs in
    `text`, using mdutils' own heading grammar (`_HEADING_RE`) — never a
    bare `line.startswith("## ")` check. A human's free-form single-word
    subheading (`## Ownership`, with no second, whitespace-separated
    title token) does not match `_HEADING_RE` at all, so it is correctly
    never counted as a real section boundary here.

    The *count* (not just membership) matters (review round 3, Important
    1): `_slice_known_section()`'s boundary check treats the *first*
    occurrence of a known id after a section's start as that section's
    end, so if a known id occurs more than once, the *first* repeat —
    wherever it is, a "See also" line quoting a different section, a
    section repeating its own id, or a fenced block quoting a real
    heading verbatim — is silently read as a real section break, and
    everything between the two occurrences is dropped when the truncated
    slice is re-emitted. Every one of these is otherwise
    undetectable from a single pass over one section's own text, since
    `_slice_known_section()` never sees the *rest* of the document while
    slicing one id — this whole-document count is what makes them
    detectable at all, and it exists precisely so `scaffold_svc()`'s
    pre-write check can refuse before any of the three ever reaches
    `_slice_known_section()`."""
    counts: dict[str, int] = {}
    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            sid = m.group("sid")
            counts[sid] = counts.get(sid, 0) + 1
    return counts


def _slice_known_section(text: str, sid: str, known_ids: set[str]) -> str | None:
    """Like `mdutils.slice_section()`, but the end boundary is only a
    line that is itself a *real* `## <id> <title>` heading for one of
    this document's own `known_ids` — never merely any line starting
    with `"## "` (Controller Ruling R43 / Critical 2).
    `mdutils.slice_section()`'s boundary check is a bare
    `str.startswith("## ")`, so a human's own free-form subheading inside
    a reviewed body (`## Ownership`, `## Runbook`) is indistinguishable
    from a real section break there, and everything after it is silently
    dropped when the truncated slice is re-emitted through
    `_render_group()` — a writer turning a reader's known limitation into
    permanent data loss. `mdutils.py` is frozen, so this narrower reader
    lives here instead of there; it reuses mdutils' own heading grammar
    (`_HEADING_RE`) rather than re-deriving a second copy of it, so the
    two can never drift apart.

    Known limitation, not exercised by any covering test: if a human's
    own subheading happens to be *exactly* `## <other-real-id> <title>`
    for another id genuinely in `known_ids`, this cannot distinguish that
    coincidence from a real section break either — no purely-textual
    reader could. `scaffold_svc()`'s separate stray-heading check handles
    the complementary, actually-reachable failure mode (a real heading
    with no manifest entry to explain it) by refusing outright instead of
    guessing.
    """
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m and m.group("sid") == sid:
            start = i
            break
    if start is None:
        return None
    for j in range(start + 1, len(lines)):
        m = _HEADING_RE.match(lines[j])
        if m and m.group("sid") in known_ids:
            return "\n".join(lines[start:j]).strip()
    return "\n".join(lines[start:]).strip()


def _extract_preamble(text: str, known_ids: set[str]) -> str:
    """Whatever a human wrote between the banner line and the first known
    section heading in `text` — the one piece of free-standing prose
    `_slice_known_section()` can never reach on its own, since it only
    ever lifts text starting *at* a heading (Ruling R46b: same class as
    R43, the third instance of "human L2 content silently dropped" found
    on this task). `_render_group()` always writes exactly `# <doc_id>`,
    a blank line, the banner, and a blank line before the first section,
    so the preamble — if any — starts right after that fixed four-line
    header and ends at the first line that is itself a real heading for
    one of `known_ids`. Returns `""` when there is none (the normal case,
    including a brand-new document with no prior text at all)."""
    lines = text.splitlines()
    start = 0
    if start < len(lines) and lines[start].startswith("# "):
        start += 1
    while start < len(lines) and lines[start].strip() == "":
        start += 1
    if start < len(lines) and lines[start].startswith(">"):
        start += 1
    while start < len(lines) and lines[start].strip() == "":
        start += 1

    end = len(lines)
    for j in range(start, len(lines)):
        m = _HEADING_RE.match(lines[j])
        if m and m.group("sid") in known_ids:
            end = j
            break

    return "\n".join(lines[start:end]).strip()


def scaffold_svc(opts, sections, report) -> None:
    """Upsert the curated -svc document from the svc.* sections just extracted.

    Absent section -> create as pending with the TODO:summarize marker and L3
    code evidence. Present section -> refresh L3 evidence ONLY; never touch L2
    or status (spec 8.2). Upsert, never clobber.
    """
    svc_doc_id = f"{opts.repo_id}-svc"
    # Same containment-vs-identity split as run()'s guard (Ruling R48b):
    # --repo-id is just as user-controlled as --doc-id, and svc_doc_id is
    # built from it with simple string interpolation — a --repo-id
    # containing ".." segments could otherwise resolve this document's
    # own target outside --kb-dir entirely. Containment is judged on the
    # *logical* (link-free) path — a legitimate junction/symlink at
    # `.kb/<repo_id>-svc` pointing at storage elsewhere is logically
    # still inside --kb-dir, and refusing it here (what this guard did
    # before this ruling) locked out the very command whose job is to
    # maintain that document, naming --repo-id as the cause when it
    # was not. `doc_dir` itself (used for every read/write below) still
    # follows the link, exactly as before.
    logical_dir = Path(os.path.normpath(str(opts.kb_dir / svc_doc_id)))
    if not logical_dir.is_relative_to(opts.kb_dir):
        raise CodeIngestError(
            f"--repo-id {opts.repo_id!r} makes the curated scaffold "
            f"resolve to {logical_dir}, which is outside --kb-dir "
            f"{opts.kb_dir}; choose a different --repo-id",
            report=report,
        )
    doc_dir = logical_dir.resolve()
    manifest_path = doc_dir / "_manifest.yaml"
    l2_path = doc_dir / "services.md"
    l3_path = doc_dir / "services.raw.md"

    current_by_id = {sec.id: sec for sec in sections if sec.id.startswith("svc.")}
    db_sections = [sec for sec in sections if sec.id.startswith("db.")]

    existing_manifest = _load_manifest_guarded(manifest_path, svc_doc_id, report)
    existing_entries: dict[str, models.SectionEntry] = {}
    other_entries: list[models.SectionEntry] = []
    if existing_manifest is not None:
        for entry in existing_manifest.sections:
            if entry.id.startswith("svc."):
                existing_entries[entry.id] = entry
            else:
                # "flows" (flow.*) and "history" (hist.*) are reserved for
                # human-authored content nothing in code-ingest produces
                # yet (Stage C's `kb svc note`) — code-ingest has no
                # ownership claim over them, so they pass through
                # untouched: not upserted, not orphaned, not deleted.
                other_entries.append(entry)

    old_l2_text = l2_path.read_text(encoding="utf-8") if l2_path.exists() else ""
    old_l3_text = l3_path.read_text(encoding="utf-8") if l3_path.exists() else ""

    # Controller Ruling R43 (Critical 2), the refuse-and-error fallback,
    # extended in review round 3 (Important 1) to also cover repeated
    # heading ids:
    #
    # (a) Stray — services.md has a *real* '## svc.<id> <title>' heading
    #     (per mdutils' own grammar, via _heading_id_counts) that this
    #     document's manifest doesn't know about — whether the manifest
    #     was hand-edited, went unreadable (degrading to "no prior state"
    #     just above), or the two files were separately edited out of
    #     sync. There is no safe way to tell whether that heading's body
    #     is human-reviewed prose worth keeping: treating it as "new"
    #     (the branch below) would overwrite it with a TODO marker;
    #     treating it as gone would erase it outright.
    #
    # (b) Duplicated — a known svc.* heading id occurs more than once in
    #     services.md. `_slice_known_section()` treats the *first*
    #     occurrence of a known id after a section's start as that
    #     section's real end, so a second occurrence anywhere — a "See
    #     also" line quoting a *different* section's id, a section
    #     repeating its *own* id, or a fenced code block that happens to
    #     quote a real heading verbatim — is silently read as a section
    #     break, and everything between the two occurrences is dropped.
    #     Every preserved (non-refusing) case has each known id exactly
    #     once, so this closes all three reproductions with no false
    #     refusals against them.
    #
    # Neither the upsert path nor the orphan path can represent either
    # shape of "real content, unknown provenance" or "ambiguous section
    # boundary", so both refuse instead of guessing — before anything is
    # written — naming every affected id.
    heading_counts = _heading_id_counts(old_l2_text)
    svc_heading_ids = {hid for hid in heading_counts if hid.startswith("svc.")}
    stray = svc_heading_ids - set(existing_entries)
    duplicated = {hid for hid in svc_heading_ids if heading_counts[hid] > 1}
    if stray or duplicated:
        problems = []
        if stray:
            problems.append(
                f"heading(s) {sorted(stray)} have no matching entry in "
                "_manifest.yaml"
            )
        if duplicated:
            problems.append(
                f"heading id(s) {sorted(duplicated)} occur more than once"
            )
        raise CodeIngestError(
            f"{svc_doc_id}: services.md is not safe to scaffold blind — "
            + "; ".join(problems)
            + " (their status/summary can't be determined safely and "
            "overwriting them risks destroying human-reviewed text); fix "
            "services.md and/or _manifest.yaml by hand, then re-run",
            report=report,
        )

    full_commit = _head_commit(opts.repo_root)
    short_commit = full_commit[:7] if full_commit else ""

    all_ids = sorted(set(current_by_id) | set(existing_entries))
    known_ids = set(all_ids)
    # Ruling R46b: whatever a human wrote above the first section heading
    # (a document-level note, e.g.) is otherwise invisible to every slice
    # above — they all start *at* a heading — so it has to be lifted
    # separately, once, here. Only L2 is human-owned (L3's own banner
    # says "regenerated"; nothing suggests a human would write free prose
    # there, and nothing preserves it if they do).
    l2_preamble = _extract_preamble(old_l2_text, known_ids)
    # Walked exactly once for this whole document (Minor perf fix) and
    # shared by every service's _service_evidence() call below, instead
    # of one full repo walk per service.
    tree_entries = walk_tree(opts.repo_root, opts.kb_dir)

    rendered_sections: list[CodeSection] = []
    manifest_entries: list[models.SectionEntry] = []

    for sid in all_ids:
        current = current_by_id.get(sid)
        existing = existing_entries.get(sid)

        if existing is None:
            # New: never seen before (and, per the stray-heading refusal
            # above, no orphaned heading for it either — nothing to lose).
            # L2 is exactly the TODO marker; L3 is fresh evidence;
            # status/summary start empty.
            title = current.title
            l2_md = f"<!-- TODO:summarize {sid} -->"
            l3_md = _service_evidence(opts.repo_root, tree_entries, current, db_sections)
            status = "pending"
            summary = ""
            tokens = models.SectionTokens()
            report.scaffolded.append(sid)
        else:
            # Present (still produced this run) or orphan (not produced
            # this run) — either way, status/summary/title default to
            # whatever the existing manifest entry already holds, and the
            # L2 body is lifted from the old file verbatim using this
            # document's own known ids as the *only* valid section
            # boundary (Ruling R43): a human subheading like
            # "## Ownership" inside the body can never truncate anything
            # after it, unlike mdutils.slice_section()'s bare "## " check.
            title = existing.title
            status = existing.status
            summary = existing.summary
            tokens = existing.tokens
            old_l2_slice = _slice_known_section(old_l2_text, sid, known_ids)
            if old_l2_slice is None:
                # The manifest still names this section but its heading
                # itself is gone from services.md (the whole file was
                # deleted, or just this heading was). Important 4: status
                # and summary are durable state that survived in the
                # manifest regardless — keep them, and self-heal the L2
                # body from the summary already on record instead of
                # resetting to an empty pending marker, which would
                # silently discard a human review still sitting right
                # there in `_manifest.yaml`.
                if summary.strip():
                    l2_md = summary
                    report.warnings.append(
                        f"{svc_doc_id}: {sid}'s heading is missing from "
                        "services.md but the manifest still holds its "
                        "summary - L2 body rebuilt from that summary"
                    )
                else:
                    l2_md = f"<!-- TODO:summarize {sid} -->"
                    status, summary, tokens = "pending", "", models.SectionTokens()
                    report.warnings.append(
                        f"{svc_doc_id}: {sid} is in the manifest but missing "
                        "from services.md - recreated as pending (there was "
                        "no summary on record to lose)"
                    )
            else:
                l2_md = _body_only(old_l2_slice)

            if current is None:
                old_l3_slice = _slice_known_section(old_l3_text, sid, known_ids)
                if old_l3_slice is not None:
                    l3_md = _body_only(old_l3_slice)
                else:
                    l3_md = (
                        "```text\n"
                        "(evidence unavailable: services.raw.md no longer "
                        "has this section)\n"
                        "```\n"
                    )
                    report.warnings.append(
                        f"{svc_doc_id}: {sid} is orphaned and its L3 "
                        "evidence is also missing from services.raw.md"
                    )
                report.orphans.append(sid)
            else:
                l3_md = _service_evidence(opts.repo_root, tree_entries, current, db_sections)
                if status == "reviewed":
                    old_l3_slice = _slice_known_section(old_l3_text, sid, known_ids)
                    if old_l3_slice is not None:
                        old_l3_body = _body_only(old_l3_slice)
                        if old_l3_body.strip() != l3_md.strip():
                            report.stale_risk.append(sid)
                    # else: no prior L3 to compare against - nothing to flag.

        rendered_sections.append(
            CodeSection(
                id=sid, title=title, summary=summary, group="services",
                l2_md=l2_md, l3_md=l3_md,
            )
        )
        manifest_entries.append(
            models.SectionEntry(
                id=sid, title=title, summary=summary, status=status,
                file="services", tokens=tokens,
            )
        )

    banner = (
        "> Responsibility text is human-owned. L3 code evidence regenerated "
        f"at {short_commit or 'unknown-commit'}."
    )
    try:
        doc_dir.mkdir(parents=True, exist_ok=True)
        _write_group(
            l2_path,
            _render_group(
                rendered_sections, "l2", banner, svc_doc_id, preamble=l2_preamble
            ),
        )
        _write_group(l3_path, _render_group(rendered_sections, "l3", banner, svc_doc_id))
        # Qualified with the document id (Minor fix): the -code doc's own
        # `run()` contribution to `report.files_written` uses bare names,
        # and with --scaffold-svc both documents share several file names
        # (services.md, services.raw.md, _manifest.yaml) — without the
        # prefix, the CLI's "files written" count was ambiguous between
        # the two documents and each pair appeared to be listed twice.
        report.files_written.append(f"{svc_doc_id}/{l2_path.name}")
        report.files_written.append(f"{svc_doc_id}/{l3_path.name}")

        manifest = models.Manifest(
            id=svc_doc_id,
            title=f"{opts.repo_id} — curated service knowledge",
            revision=short_commit,
            source_sha256=full_commit,
            ingested=_head_date(opts.repo_root),
            sections=sorted(
                manifest_entries + other_entries, key=lambda e: (e.file, e.id)
            ),
        )
        models.save_yaml_model(manifest_path, manifest)
        report.files_written.append(f"{svc_doc_id}/{manifest_path.name}")
    except OSError as exc:
        # Same defense-in-depth as run()'s write section (Ruling R47d):
        # --repo-id is just as capable of producing an OS-rejected
        # directory name as --doc-id is.
        raise CodeIngestError(
            f"could not write the {svc_doc_id!r} curated document under "
            f"{doc_dir} ({exc})",
            report=report,
        ) from exc

    _upsert_index_entry(
        opts.kb_dir, svc_doc_id, manifest.title, manifest.revision,
        f"Curated service knowledge for the {opts.repo_id} repository.",
        ["code", "curated"], opts.tags, report,
    )


# Imported at the bottom of the module, deliberately after every class above
# is defined. B2-B7 extractor modules import CodeSection/ExtractResult from
# `center_kb.codeingest.core`, and `extractors/__init__.py` imports those
# extractor modules to build ALL_EXTRACTORS. Importing `extractors` up top
# (before CodeSection/ExtractResult exist) would hand those modules a
# partially-initialized `core` module with neither name bound yet —
# `from center_kb.codeingest.core import CodeSection` raises ImportError in
# every import order; only `import center_kb.codeingest.core as core` +
# deferred `core.CodeSection` attribute access survives, by accident of
# CPython's partial-module fallback. Deferring this import until everything
# above it is defined makes both import styles work regardless of which
# module a caller imports first. `run()` reads `ALL_EXTRACTORS` as a module
# global at call time, so its position here doesn't affect that lookup —
# and `monkeypatch.setattr(core, "ALL_EXTRACTORS", ...)` still works because
# it rebinds this same module-level name.
from center_kb.codeingest.extractors import ALL_EXTRACTORS  # noqa: E402

# Same deferred-import reasoning as ALL_EXTRACTORS just above: `extractors.
# tree` imports `CodeIngestOptions`/`CodeSection`/`ExtractResult` from this
# module, so importing it at the top of this file (before those names exist)
# would hand it a partially-initialized `core`. By this point in the module
# `extractors/__init__.py` has already imported `extractors.tree` to build
# ALL_EXTRACTORS, so this is just binding names already in `sys.modules`.
# `scaffold_svc()` (defined above, called from `run()`) uses these to walk
# the repo for its L3 evidence.
from center_kb.codeingest.extractors.tree import relposix, walk_tree  # noqa: E402
