from __future__ import annotations

import sys
from pathlib import Path

import typer

from center_kb import models

# Windows console defaults to cp1252 → UnicodeEncodeError crash when printing
# '§'/accented characters. Force UTF-8 when the stream isn't already UTF-8
# (guarded: some test/redirect streams lack .reconfigure()).
for _stream in (sys.stdout, sys.stderr):
    _enc = getattr(_stream, "encoding", None) or ""
    if _enc.lower().replace("-", "") != "utf8" and hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

app = typer.Typer(
    help="CENTER-KB — Knowledge Base as Code for large reference documents.",
    no_args_is_help=True,
)

context_app = typer.Typer(help="Operate on kb-context blocks (machine-readable citations).")
app.add_typer(context_app, name="context")


@app.callback()
def main() -> None:
    """CENTER-KB CLI."""


@app.command()
def init(
    path: Path = typer.Argument(Path("."), help="Target directory (default: current)"),
    force: bool = typer.Option(False, "--force", help="Overwrite files that already exist"),
) -> None:
    """Scaffold a new KB repo: .kb/, federation/, config templates — ready for `kb ingest`."""
    from center_kb.initcmd import init_repo

    report = init_repo(path, force=force)
    for rel in report.created:
        typer.echo(f"  created  {rel}")
    for rel in report.skipped:
        typer.secho(
            f"  skipped  {rel} (exists — use --force to overwrite)",
            fg=typer.colors.YELLOW,
        )
    typer.echo(
        f"kb init: {len(report.created)} file(s) created, {len(report.skipped)} skipped."
    )
    typer.echo("Next steps:")
    typer.echo("  1. cp .env.example .env    # then edit CENTER_KB_HTTP_TOKEN")
    typer.echo("  2. kb ingest source/<file>.pdf --id <doc-id>")
    typer.echo("  (details: QUICKSTART.md)")


def _resolve_hub_option(hub: str, quiet: bool = False):
    """'' → None; otherwise resolve via hub.resolve_hub (None if unreachable).

    quiet=True suppresses the stderr warning here — used when the caller
    (e.g. `doctor`, via check_hub) already reports its own warning, to
    avoid a duplicate.
    """
    if not hub:
        return None
    from center_kb.hub import resolve_hub

    handle = resolve_hub(hub)
    if handle is None and not quiet:
        typer.secho(
            f"[warn] could not reach hub '{hub}' — continuing with local KB",
            fg=typer.colors.YELLOW,
            err=True,
        )
    return handle


@app.command()
def ingest(
    pdf: Path = typer.Argument(..., help="Source PDF file"),
    doc_id: str = typer.Option(..., "--id", help="Document ID, e.g. arinc-424"),
    tags: str = typer.Option("", help="Tags, comma-separated"),
    revision: str = typer.Option("", help="Revision, e.g. 'Supplement 22'"),
    sections: str = typer.Option(
        "", help="Only scaffold these chapters, e.g. '5,6' (empty = all)"
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    work_dir: Path = typer.Option(Path(".kb-work"), help="Intermediate cache directory"),
    chapter_pattern: str = typer.Option(
        "",
        help="Chapter heading regex (default: 'Chapter N', remembered from the previous ingest)",
    ),
    appendix_pattern: str = typer.Option(
        "",
        help="Appendix heading regex (default: 'Appendix X', remembered from the previous ingest)",
    ),
    no_summarize: bool = typer.Option(
        False, "--no-summarize", help="Skip the automatic LLM summarize step"
    ),
    llm: str = typer.Option(
        "", "--llm", help="Runner: claude | copilot | none (default: auto-detect)"
    ),
) -> None:
    """Parse PDF → split into sections → generate L3 + L1/L2 scaffolding pending summarization."""
    from center_kb.ingest import parser, scaffold, sectioner

    _validate_llm_choice(llm)
    manifest_path = kb_dir / doc_id / "_manifest.yaml"
    previous = None
    if manifest_path.exists():
        previous = models.load_yaml_model(manifest_path, models.Manifest).ingest
    try:
        heading_config = sectioner.resolve_heading_config(
            chapter_pattern, appendix_pattern, previous
        )
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)

    doc = parser.load_or_parse(pdf, work_dir / doc_id)
    items = parser.doc_to_items(doc)
    units = sectioner.build_units(items, config=heading_config)

    bm_ids = parser.bookmark_ids(pdf, heading_config)
    if bm_ids:
        for warning in parser.crosscheck({u.id for u in units}, bm_ids):
            typer.secho(f"  [warn] {warning}", fg=typer.colors.YELLOW)

    chapters = {s.strip() for s in sections.split(",") if s.strip()} or None
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    report = scaffold.scaffold_doc(
        units,
        doc_id=doc_id,
        title=doc_id if not hasattr(doc, "name") else (getattr(doc, "name", "") or doc_id),
        tags=tag_list,
        revision=revision,
        source_path=pdf,
        kb_dir=kb_dir,
        chapters=chapters,
        heading_config=heading_config,
    )
    typer.echo(
        f"Ingested '{report.doc_id}': {report.n_sections} sections, "
        f"{len(report.files)} files in {kb_dir / report.doc_id}"
    )
    if no_summarize or llm == "none":
        typer.echo(
            "Summarize skipped. Next: run `kb summarize` (or the kb-summarize "
            "skill in Claude Code), then `kb build`."
        )
        return
    report_s, reason = _run_summarize(kb_dir, llm, doc_id, max_workers=0)
    if report_s is None:
        _echo_no_runner(reason)
        return
    typer.echo(
        f"{len(report_s.summarized)} summarized, {len(report_s.failed)} failed."
    )
    if report_s.failed:
        typer.secho(
            "Failed sections stay pending — re-run with: kb summarize",
            fg=typer.colors.YELLOW,
        )
    from center_kb.build import build_kb

    build_report = build_kb(kb_dir, allow_pending=bool(report_s.failed))
    for err in build_report.errors:
        typer.secho(f"  [build] {err}", fg=typer.colors.RED)
    for warn in build_report.warnings:
        typer.secho(f"  [build] {warn}", fg=typer.colors.YELLOW)
    if build_report.ok:
        typer.echo("kb build: OK")


_LLM_CHOICES = ("", "claude", "copilot", "none")


def _validate_llm_choice(llm_choice: str) -> None:
    if llm_choice not in _LLM_CHOICES:
        typer.secho(
            f"--llm must be one of: claude, copilot, none (got '{llm_choice}')",
            fg=typer.colors.RED,
        )
        raise typer.Exit(2)


def _run_summarize(
    kb_dir: Path, llm_choice: str, doc_id: str | None, max_workers: int
):
    """Shared engine for `kb summarize` and `kb ingest`.

    Returns (report | None, reason): report is None when no runner ran;
    reason is "disabled" | "missing" | "" accordingly.
    """
    import center_kb.llm as llm_mod
    from center_kb.summarize import summarize_kb

    index = models.load_yaml_model(kb_dir / "index.yaml", models.KBIndex)
    effective = llm_choice or index.llm.runner
    # Looks redundant with detect_runner's own "none" handling, but it is
    # load-bearing: it's what distinguishes the "disabled" reason returned
    # here from the "missing" reason returned below when detect_runner
    # can't find a runner. Don't collapse the two checks.
    if effective == "none":
        return None, "disabled"
    runner = llm_mod.detect_runner(llm_choice or None, index.llm)
    if runner is None:
        return None, "missing"
    workers = max_workers or index.llm.max_workers
    model = getattr(runner, "model", "")
    typer.echo(f"Summarizing with {runner.name} ({model}), {workers} workers…")
    report = summarize_kb(
        kb_dir, runner, doc_id=doc_id, max_workers=workers,
        on_progress=lambda msg: typer.echo(f"  {msg}"),
    )
    return report, ""


def _echo_no_runner(reason: str) -> None:
    if reason == "disabled":
        typer.echo("LLM summarize is disabled (runner: none).")
    else:
        typer.secho(
            "No LLM CLI found (tried: claude, copilot).", fg=typer.colors.YELLOW
        )
    typer.echo(
        "Sections stay pending. Install Claude Code or GitHub Copilot CLI and "
        "run `kb summarize`, or use the kb-summarize skill in Claude Code."
    )


@app.command()
def summarize(
    doc_id: str = typer.Argument("", help="Limit to one document (empty = all)"),
    llm: str = typer.Option(
        "", "--llm", help="Runner: claude | copilot | none (default: auto-detect)"
    ),
    max_workers: int = typer.Option(
        0, help="Parallel LLM calls (default: llm.max_workers in index.yaml)"
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
) -> None:
    """Fill pending L1/L2 summaries by calling a headless LLM CLI (claude/copilot)."""
    _validate_llm_choice(llm)
    if not (kb_dir / "index.yaml").exists():
        typer.secho(f"not found: {kb_dir / 'index.yaml'}", fg=typer.colors.RED)
        raise typer.Exit(1)
    report, reason = _run_summarize(kb_dir, llm, doc_id or None, max_workers)
    if report is None:
        _echo_no_runner(reason)
        raise typer.Exit(1)
    typer.echo(f"{len(report.summarized)} summarized, {len(report.failed)} failed.")
    if report.failed:
        typer.secho(
            "Some sections stay pending — re-run with: kb summarize",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(1)


@app.command()
def status(
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
) -> None:
    """List sections pending summarization (status=pending)."""
    index_path = kb_dir / "index.yaml"
    if not index_path.exists():
        typer.echo("KB is empty — no index.yaml yet.")
        raise typer.Exit(0)
    index = models.load_yaml_model(index_path, models.KBIndex)
    total_pending = 0
    for entry in index.docs:
        manifest_path = kb_dir / entry.id / "_manifest.yaml"
        if not manifest_path.exists():
            continue
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
        pending = [s for s in manifest.sections if s.status == "pending"]
        total_pending += len(pending)
        typer.echo(
            f"{entry.id}: {len(pending)}/{len(manifest.sections)} section pending"
        )
        for sec in pending:
            typer.echo(f"  - §{sec.id} {sec.title} (file: {sec.file}.md)")
    typer.echo(f"Total: {total_pending} section(s) pending.")


@app.command()
def build(
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    allow_pending: bool = typer.Option(
        False, "--allow-pending", help="Don't fail while sections are still pending"
    ),
) -> None:
    """Validate KB: no TODOs left, table integrity, updated token counts."""
    from center_kb.build import build_kb

    report = build_kb(kb_dir, allow_pending=allow_pending)
    for warning in report.warnings:
        typer.secho(f"[warn] {warning}", fg=typer.colors.YELLOW)
    for error in report.errors:
        typer.secho(f"[error] {error}", fg=typer.colors.RED)
    if not report.ok:
        raise typer.Exit(1)

    db_path = kb_dir.resolve().parent / ".kb-work" / "embeddings.db"
    if db_path.exists():
        from center_kb.embed import default_embedder, ensure_index

        embedder = default_embedder()
        if embedder is not None:
            n = ensure_index(kb_dir, db_path, embedder)
            if n:
                typer.echo(f"embeddings.db: re-embed {n} section(s).")
    typer.echo("kb build: OK")


@app.command()
def query(
    text: str = typer.Argument(..., help="Query text"),
    tags: str = typer.Option("", help="Tags to filter docs by, comma-separated"),
    budget: int = typer.Option(2000, help="Token budget for returned content"),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    hub: str = typer.Option(
        "", "--hub", envvar="CENTER_KB_HUB", help="kb-hub URL/path (empty = don't use)"
    ),
    semantic: bool = typer.Option(
        False, "--semantic", help="Force embedding search (routing step 3)"
    ),
) -> None:
    """Tag match → BM25 → return L2 sections within budget, with citations."""
    from center_kb.query import search

    handle = _resolve_hub_option(hub)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] or None
    results = search(
        kb_dir, text, tags=tag_list, budget=budget, hub=handle, semantic=semantic
    )
    if not results:
        typer.echo("No matching section found.")
        raise typer.Exit(0)
    for r in results:
        mark = " [remote]" if r.source.startswith("remote:") else ""
        typer.secho(
            f"--- [{r.citation}]{mark} score={r.score:.2f} ~{r.tokens}tk", bold=True
        )
        typer.echo(r.content)
        typer.echo("")


@app.command()
def get(
    doc_id: str = typer.Argument(..., help="Document ID"),
    section: str = typer.Argument(..., help="Section ID, e.g. 5.3 or §5.3"),
    level: str = typer.Option("l2", help="Level: l2 or l3"),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    hub: str = typer.Option(
        "", "--hub", envvar="CENTER_KB_HUB", help="kb-hub URL/path (empty = don't use)"
    ),
) -> None:
    """Fetch exactly one section at the given level."""
    from center_kb.query import get_section

    handle = _resolve_hub_option(hub)
    result = get_section(kb_dir, doc_id, section, level=level, hub=handle)
    if result is None:
        typer.secho(f"Not found: {doc_id} §{section}", fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.secho(f"--- [{result.citation}] ~{result.tokens}tk", bold=True)
    typer.echo(result.content)


@app.command()
def stats(
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
) -> None:
    """Token size per level, per document — for cost tracking."""
    from center_kb.build import kb_stats

    l0_tokens, docs = kb_stats(kb_dir)
    typer.echo(f"L0 index.yaml: {l0_tokens} tokens")
    if not docs:
        typer.echo("KB is empty.")
        raise typer.Exit(0)
    header = f"{'doc':<20} {'sections':>8} {'L1':>8} {'L2':>10} {'L3':>10} {'saving':>8}"
    typer.echo(header)
    for d in docs:
        typer.echo(
            f"{d.doc_id:<20} {d.n_sections:>8} {d.l1_tokens:>8} "
            f"{d.l2_tokens:>10} {d.l3_tokens:>10} {d.saving_pct:>7.1f}%"
        )


@app.command()
def publish(
    hub: str = typer.Option(
        ..., "--hub", envvar="CENTER_KB_HUB", help="kb-hub URL or path"
    ),
    repo_id: str = typer.Option(
        "", "--repo-id", help="Repo ID on the hub (default: git root directory name)"
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
) -> None:
    """Publish this repo's L0+L1 snapshot to federation/<repo-id>/ on the hub."""
    from center_kb import gitio
    from center_kb.publish import PublishError
    from center_kb.publish import publish as publish_kb

    try:
        report = publish_kb(kb_dir, hub, repo_id=repo_id or None)
    except (PublishError, gitio.GitError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    action = "push" if report.pushed else "commit only (hub has no remote)"
    typer.echo(
        f"kb publish: {report.repo_id} @ {report.source_commit} — "
        f"{report.n_docs} doc, {action}."
    )


@context_app.command("new")
def context_new(
    refs: str = typer.Option(
        ..., "--refs", help="Comma-separated refs, e.g. 'arinc-424 §5.3,arinc-424 §5.3.2'"
    ),
    tags: str = typer.Option("", help="Tags, comma-separated"),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    hub: str = typer.Option(
        "", "--hub", envvar="CENTER_KB_HUB", help="kb-hub URL/path (empty = don't use)"
    ),
) -> None:
    """Generate a kb-context block pinned at HEAD — paste into a Jira ticket."""
    from center_kb import gitio, kbcontext
    from center_kb.query import get_section

    try:
        ref_list = [kbcontext.parse_ref(r) for r in refs.split(",") if r.strip()]
        root = gitio.git_root(kb_dir.resolve())
        version = gitio.head_commit(root)
    except (kbcontext.KBContextError, gitio.GitError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)

    if not ref_list:
        typer.secho(
            "--refs is empty — need at least 1 ref, e.g. 'arinc-424 §5.3'",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    handle = _resolve_hub_option(hub)
    bad: list[str] = []
    needs_hub = False
    for r in ref_list:
        if r.repo_id:
            found = handle is not None and (
                handle.federation_dir / r.repo_id / "manifests" / f"{r.doc_id}.yaml"
            ).exists()
            needs_hub = True
        else:
            found = get_section(kb_dir, r.doc_id, r.section_id) is not None
            if not found and handle is not None:
                found = (
                    get_section(kb_dir, r.doc_id, r.section_id, hub=handle) is not None
                )
                needs_hub = needs_hub or found
        if not found:
            bad.append(str(r))
    if bad:
        typer.secho(
            f"Ref could not be resolved in worktree: {', '.join(bad)}",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    if gitio.is_dirty(root, kb_dir.resolve()):
        typer.secho(
            "[warn] .kb/ has uncommitted changes — the pinned hash will not include them",
            fg=typer.colors.YELLOW,
            err=True,
        )
    hub_version = None
    if needs_hub and handle is not None:
        hub_version = gitio.head_commit(gitio.git_root(handle.root))
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    ctx = kbcontext.KBContext(
        version=version, hub_version=hub_version, refs=ref_list, tags=tag_list
    )
    typer.echo(kbcontext.render(ctx))


@app.command()
def resolve(
    source: str = typer.Argument(
        ..., help="File containing the kb-context block (or '-' to read from stdin)"
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    hub: str = typer.Option(
        "", "--hub", envvar="CENTER_KB_HUB", help="kb-hub URL/path (empty = don't use)"
    ),
) -> None:
    """Resolve a kb-context block: return sections at the pinned version + freshness."""
    from center_kb import gitio, kbcontext
    from center_kb.resolve import render_resolved, resolve_refs

    if source == "-":
        text = sys.stdin.read()
    else:
        try:
            text = Path(source).read_text(encoding="utf-8")
        except OSError as exc:
            typer.secho(f"could not read file '{source}': {exc}", fg=typer.colors.RED)
            raise typer.Exit(1)
    handle = _resolve_hub_option(hub)
    try:
        ctx = kbcontext.parse(text)
        results = resolve_refs(kb_dir, ctx, hub=handle)
    except (kbcontext.KBContextError, gitio.GitError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.echo(render_resolved(results))
    if any(r.status == "broken" for r in results):
        raise typer.Exit(1)
    if any(r.status == "stale" for r in results):
        raise typer.Exit(2)


@app.command()
def diff(
    doc_id: str = typer.Argument(..., help="Document ID"),
    against: str = typer.Option("HEAD", help="Git rev to diff against, e.g. HEAD, a3f9c21"),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
) -> None:
    """Diff added/removed/changed sections between the worktree and a git rev."""
    from center_kb import gitio
    from center_kb.diff import diff_doc, render_diff

    try:
        report = diff_doc(kb_dir, doc_id, against=against)
    except (ValueError, gitio.GitError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.echo(render_diff(report))


@app.command()
def approve(
    doc_id: str = typer.Argument(
        "", help="Document ID (optional with --all-changed: empty = scan all docs)"
    ),
    section: list[str] = typer.Option(
        [], "--section", help="Section ID(s) to approve, e.g. 5.3 (repeatable)"
    ),
    all_changed: bool = typer.Option(
        False,
        "--all-changed",
        help="Approve the sections added/changed vs --against (CI mode)",
    ),
    against: str = typer.Option(
        "", "--against", help="Git rev to compare with (required with --all-changed)"
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
) -> None:
    """Mark sections as reviewed (status: summarized → reviewed)."""
    from center_kb import gitio
    from center_kb.review import approve_all_changed, approve_sections

    if all_changed != bool(against):
        typer.secho(
            "--all-changed and --against must be used together, "
            "e.g. `kb approve --all-changed --against HEAD^`",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    if all_changed and section:
        typer.secho(
            "--section cannot be combined with --all-changed", fg=typer.colors.RED
        )
        raise typer.Exit(1)
    if not all_changed and not doc_id:
        typer.secho(
            "DOC_ID is required unless --all-changed is used", fg=typer.colors.RED
        )
        raise typer.Exit(1)

    try:
        if all_changed:
            reports = approve_all_changed(kb_dir, against, doc_id=doc_id or None)
        else:
            reports = [approve_sections(kb_dir, doc_id, list(section) or None)]
    except (ValueError, gitio.GitError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)

    flipped_total = 0
    has_missing = False
    for rep in reports:
        for sid in rep.skipped_pending:
            typer.secho(
                f"[warn] {rep.doc_id} §{sid} is still pending — cannot approve",
                fg=typer.colors.YELLOW,
                err=True,
            )
        for sid in rep.missing:
            has_missing = True
            typer.secho(
                f"[error] {rep.doc_id} §{sid} not found in manifest",
                fg=typer.colors.RED,
            )
        if rep.flipped:
            flipped_total += len(rep.flipped)
            ids = ", ".join(f"§{sid}" for sid in rep.flipped)
            typer.echo(f"{rep.doc_id}: {len(rep.flipped)} section(s) → reviewed: {ids}")

    if has_missing:
        raise typer.Exit(1)
    if flipped_total == 0:
        if all_changed:
            typer.echo("kb approve: nothing to approve")
        else:
            typer.secho(
                "kb approve: no summarized section to approve", fg=typer.colors.RED
            )
            raise typer.Exit(1)


@app.command()
def doctor(
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    context: str | None = typer.Option(
        None, "--context", help="File containing the kb-context block (or '-' to read from stdin)"
    ),
    hub: str = typer.Option(
        "", "--hub", envvar="CENTER_KB_HUB", help="kb-hub URL/path (empty = don't use)"
    ),
) -> None:
    """Check KB health; pass --context to check citation staleness."""
    from center_kb.doctor import check_context, check_hub, check_kb

    issues = check_kb(kb_dir)
    # quiet=True: check_hub() below reports its own "could not reach hub"
    # warning when needed — avoids a duplicate warning.
    handle = _resolve_hub_option(hub, quiet=True)
    hub_stale = False
    if hub:  # only check the hub when --hub / CENTER_KB_HUB env is provided
        repo_root_name = None
        try:
            from center_kb import gitio as _gitio

            repo_root_name = _gitio.git_root(kb_dir.resolve()).name
        except Exception:
            pass
        hub_issues, hub_stale = check_hub(kb_dir, handle, repo_id=repo_root_name)
        issues += hub_issues
    has_stale = False
    if context is not None:
        text = sys.stdin.read() if context == "-" else Path(context).read_text(
            encoding="utf-8"
        )
        ctx_issues, results = check_context(kb_dir, text, hub=handle)
        issues += ctx_issues
        has_stale = any(r.status == "stale" for r in results)

    for issue in issues:
        color = typer.colors.RED if issue.level == "error" else typer.colors.YELLOW
        typer.secho(f"[{issue.level}] {issue.message}", fg=color)
    if any(i.level == "error" for i in issues):
        raise typer.Exit(1)
    if has_stale or hub_stale:
        raise typer.Exit(2)
    typer.echo("kb doctor: OK")
