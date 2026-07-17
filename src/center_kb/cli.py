from __future__ import annotations

import importlib.metadata
import json
import sys
from enum import Enum
from pathlib import Path

import typer

from center_kb import models
from center_kb.utf8io import force_utf8_streams

force_utf8_streams()

app = typer.Typer(
    help="CENTER-KB — Knowledge Base as Code for large reference documents.",
    no_args_is_help=True,
)

context_app = typer.Typer(help="Operate on kb-context blocks (machine-readable citations).")
app.add_typer(context_app, name="context")

assets_app = typer.Typer(help="Asset store operations (hub): migrate, verify")
app.add_typer(assets_app, name="assets")

ticket_app = typer.Typer(help="Ticket linting: Definition-of-Ready gate for BA tickets.")
app.add_typer(ticket_app, name="ticket")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(importlib.metadata.version("center-kb"))
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the installed center-kb version and exit.",
    ),
) -> None:
    """CENTER-KB CLI."""


class RepoKind(str, Enum):
    hub = "hub"
    child = "child"
    ba = "ba"


class AssetsMode(str, Enum):
    none = "none"
    s3 = "s3"


KIND_DESCRIPTIONS = """\
This repo can be one of three kinds:

  hub   — Central knowledge hub. Hosts federation/, the single source of
          truth for search. Runs the shared HTTP MCP server + Web UI
          (docker compose up -d, port 8321). Receives publishes from child
          repos — merging hub PRs is the review gate that makes content
          searchable. May also keep its own .kb/ and publish itself.

  child — Authoring repo. Ingest PDFs → summarize → kb build → kb publish
          to the hub. Docker is only needed for one-shot ingest runs, not
          for a long-lived server. Must point hub: in .kb/config.yaml at
          the main hub. Does not host the company-wide MCP/Web service.

  ba    — Requirements repo. Drafts Dev-ready tickets grounded in the KB
          via the ba-ticket-author skill, versions them under tickets/,
          and gates them with a CI Definition-of-Ready check. Never
          ingests, summarizes, or publishes KB content.
"""


def _stdin_isatty() -> bool:
    return sys.stdin.isatty()


def _resolve_kind(target: Path, kind_flag: RepoKind | None) -> str:
    """persisted kind > --kind flag > interactive prompt > hard error."""
    from center_kb.config import load_config

    persisted = load_config(target / ".kb").kind
    if persisted:
        if kind_flag is not None and kind_flag.value != persisted:
            typer.secho(
                f"this repo is already initialized as '{persisted}' "
                f"(.kb/config.yaml) — --kind {kind_flag.value} conflicts. "
                "Edit .kb/config.yaml deliberately if you really mean to switch.",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)
        return persisted
    if kind_flag is not None:
        return kind_flag.value
    if _stdin_isatty():
        typer.echo(KIND_DESCRIPTIONS)
        # Own re-prompt loop: typer >= 0.26 vendors click, so passing the real
        # click.Choice makes BadParameter escape typer.prompt instead of
        # re-prompting.
        while True:
            answer = typer.prompt("Initialize this repo as (hub, child, ba)")
            answer = answer.strip().lower()
            if answer in ("hub", "child", "ba"):
                return answer
            typer.secho(
                f"Error: {answer!r} is not one of 'hub', 'child', 'ba'.",
                fg=typer.colors.RED,
            )
    # NOTE: this message intentionally still reads "hub|child" (not
    # "hub|child|ba") — an existing test asserts this exact string, and
    # --kind ba works correctly whether or not it's advertised here.
    typer.secho(
        "kb init requires --kind hub|child when not running interactively.",
        fg=typer.colors.RED,
    )
    raise typer.Exit(2)


@app.command()
def init(
    path: Path = typer.Argument(Path("."), help="Target directory (default: current)"),
    kind: RepoKind | None = typer.Option(
        None,
        "--kind",
        help="Repo kind: hub (hosts federation + the shared MCP/Web service) "
        "or child (authors and publishes to the hub). Required on first init "
        "when not running interactively.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Also overwrite protected data (.kb/index.yaml)",
    ),
    assets: AssetsMode | None = typer.Option(
        None,
        "--assets",
        help="Hub asset storage: none (assets in git, default) or s3 "
        "(object store — spec B). Hub kind only.",
    ),
) -> None:
    """Scaffold or refresh a KB repo: skills/templates update by default; data is preserved."""
    from center_kb.initcmd import init_repo

    resolved = _resolve_kind(path, kind)
    if assets is not None and resolved != "hub":
        typer.secho(
            "--assets applies to hubs only — a child never configures asset "
            "storage (bytes ride the publish transport to the hub).",
            fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    report = init_repo(path, resolved, force=force, assets=assets.value if assets else None)
    for rel in report.created:
        typer.echo(f"  created  {rel}")
    for rel in report.updated:
        typer.echo(f"  updated  {rel}")
    for rel in report.skipped:
        typer.secho(
            f"  skipped  {rel} (protected data — use --force to overwrite)",
            fg=typer.colors.YELLOW,
        )
    for note in report.notes:
        typer.secho(f"  note     {note}", fg=typer.colors.YELLOW)
    typer.echo(
        f"kb init ({resolved}): {len(report.created)} created, "
        f"{len(report.updated)} updated, {len(report.skipped)} skipped."
    )
    typer.echo("Next steps:")
    if resolved == "hub":
        typer.echo(
            "  1. kb docker-setup   (or /kb-docker-setup in your AI assistant)"
            "  # .env + HTTP token + docker compose up -d"
        )
        typer.echo(
            "  2. Open http://localhost:8321/ui    # Web UI (MCP HTTP on the same port)"
        )
        typer.echo("  3. kb ingest source/<file>.pdf --id <doc-id>")
        if assets is AssetsMode.s3:
            typer.echo(
                "  4. Assets (s3): fill bucket/region/endpoint in .kb/config.yaml, "
                'export credentials (AWS env chain), pip install "center-kb[s3]", '
                "then: kb doctor"
            )
    elif resolved == "child":
        typer.echo("  1. Fill hub: in .kb/config.yaml with the main hub URL/path")
        typer.echo(
            "  2. kb docker-setup   (or /kb-docker-setup)"
            "  # optional: pull the Docker ingest image"
        )
        typer.echo("  3. kb ingest source/<file>.pdf --id <doc-id>    (or /kb-ingest)")
        typer.echo("  4. kb publish    (or /kb-publish)")
    else:  # ba
        typer.echo("  1. Fill hub: in .kb/config.yaml with the main hub URL/path")
        typer.echo(
            "  2. Set CENTER_KB_HUB_URL / CENTER_KB_HTTP_TOKEN so your AI "
            "assistant can reach the shared MCP server"
        )
        typer.echo(
            "  3. Open this repo in Claude Code / Copilot Chat / Cursor and "
            "run /ba-ticket-author"
        )
    quickstart_name = "QUICKSTART-BA.md" if resolved == "ba" else "QUICKSTART.md"
    typer.echo(f"  (details: {quickstart_name})")


@app.command("docker-setup")
def docker_setup(
    path: Path = typer.Argument(Path("."), help="Repo root (default: current)"),
    force: bool = typer.Option(
        False, "--force", help="Hub: regenerate the token inside an existing .env"
    ),
    no_docker: bool = typer.Option(
        False, "--no-docker", help="Prepare files only; skip docker commands"
    ),
) -> None:
    """Prepare this repo for Docker — hub: .env + token + start the service; child: pull the ingest image."""
    from center_kb import dockersetup

    try:
        kind = dockersetup.repo_kind(path)
    except dockersetup.DockerSetupError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    if kind == "hub":
        _docker_setup_hub(path, force, no_docker)
    else:
        _docker_setup_child(path, no_docker)


def _docker_setup_hub(path: Path, force: bool, no_docker: bool) -> None:
    from center_kb import dockersetup

    try:
        try:
            report = dockersetup.run_setup(path, regenerate=force)
        except dockersetup.EnvExistsError:
            if _stdin_isatty() and typer.confirm(
                f"Found existing .env — regenerate {dockersetup.TOKEN_VAR}?"
            ):
                report = dockersetup.run_setup(path, regenerate=True)
            else:
                raise
    except dockersetup.DockerSetupError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    action = "created" if report.env_created else "updated"
    typer.echo(
        f".env {action} — {dockersetup.TOKEN_VAR} written (token not shown; see .env)."
    )
    if report.gitignore_updated:
        typer.echo(".gitignore updated: added .env")
    typer.secho(
        "This token was auto-generated for convenience — replace it with your "
        "own secret for real deployments, and store it in a secret manager.",
        fg=typer.colors.YELLOW,
    )
    if not no_docker and dockersetup.docker_ready():
        typer.echo("Starting the hub: docker compose up -d")
        if dockersetup.compose_up(path) != 0:
            typer.secho(
                "docker compose up failed — see output above.", fg=typer.colors.RED
            )
            raise typer.Exit(1)
        typer.echo(
            "Hub running — Web UI: http://localhost:8321/ui "
            "(sign in with the token from .env)"
        )
    else:
        if not no_docker:
            typer.secho(
                "Docker not detected — start Docker Desktop, then run the steps "
                "below yourself.",
                fg=typer.colors.YELLOW,
            )
        typer.echo("Next steps:")
        typer.echo("  1. docker compose up -d")
        typer.echo(
            "  2. Open http://localhost:8321/ui (sign in with the token from .env)"
        )
    typer.echo("Point remote MCP clients at the hub:")
    typer.echo('  { "mcpServers": { "center-kb": { "type": "http",')
    typer.echo('    "url": "http://<host>:8321/mcp",')
    typer.echo('    "headers": { "Authorization": "Bearer <token>" } } } }')


def _docker_setup_child(path: Path, no_docker: bool) -> None:
    from center_kb import dockersetup

    typer.echo(
        "Child repo: Docker runs one-shot ingest (the image bundles the full "
        "docling stack — no local Python needed)."
    )
    if not no_docker:
        if not dockersetup.docker_ready():
            typer.secho(
                "Docker not detected — install/start Docker Desktop, then re-run "
                "kb docker-setup.",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)
        typer.echo("Pulling the ingest image: docker compose pull")
        if dockersetup.compose_pull(path) != 0:
            typer.secho(
                "docker compose pull failed — see output above.",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)
    typer.echo("Ingest a document:")
    typer.echo(
        "  docker compose run --rm hub kb ingest source/<file>.pdf "
        "--id <doc-id> --no-summarize"
    )
    typer.echo(
        "Note: the first ingest downloads layout/table models into the "
        "kb-model-cache volume (one-time wait)."
    )
    typer.echo("(The shared MCP server + Web UI run on the MAIN hub, not here.)")


def _hub_or_exit(hub_flag: str, kb_dir: Path):
    """Hub is required: flag > env (typer envvar already folded) > .kb/config.yaml."""
    from center_kb.config import HubConfigError, require_hub
    from center_kb.hub import resolve_hub

    try:
        hub_ref = require_hub(hub_flag, kb_dir)
    except HubConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    handle = resolve_hub(hub_ref)
    if handle is None:
        typer.secho(
            f"could not reach hub '{hub_ref}' and no cache exists — "
            "check the network or the hub path",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    if handle.stale:
        age = f"~{handle.age_seconds:.0f}s" if handle.age_seconds else "unknown age"
        typer.secho(
            f"[warn] hub cache is stale ({age})", fg=typer.colors.YELLOW, err=True
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
    attachment_pattern: str = typer.Option(
        "",
        help="Attachment heading regex (default: 'Attachment N', remembered from the previous ingest)",
    ),
    no_bookmarks: bool = typer.Option(
        False,
        "--no-bookmarks",
        help="Ignore PDF bookmarks; split by heading patterns only",
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
            chapter_pattern, appendix_pattern, attachment_pattern, previous
        )
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)

    try:
        doc = parser.load_or_parse(pdf, work_dir / doc_id)
    except RuntimeError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    items = parser.doc_to_items(doc, assets_dir=kb_dir / doc_id / "assets")
    parts = None if no_bookmarks else parser.outline_parts(pdf, heading_config)
    if parts:
        typer.echo(f"sectioning: bookmarks ({len(parts)} parts)")
    else:
        typer.echo("sectioning: heading patterns")
    units = sectioner.build_units(items, config=heading_config, parts=parts)

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
        part_titles={p.id: p.title for p in parts} if parts else None,
        used_bookmarks=bool(parts),
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


def _resolve_runner(kb_dir: Path, llm_choice: str, max_workers: int):
    """Returns (runner | None, reason, workers): reason is "disabled" | "missing" | ""."""
    import center_kb.llm as llm_mod

    index = models.load_yaml_model(kb_dir / "index.yaml", models.KBIndex)
    effective = llm_choice or index.llm.runner
    # Looks redundant with detect_runner's own "none" handling, but it is
    # load-bearing: it's what distinguishes the "disabled" reason returned
    # here from the "missing" reason returned below when detect_runner
    # can't find a runner. Don't collapse the two checks.
    if effective == "none":
        return None, "disabled", 0
    runner = llm_mod.detect_runner(llm_choice or None, index.llm)
    if runner is None:
        return None, "missing", 0
    return runner, "", max_workers or index.llm.max_workers


def _run_summarize(
    kb_dir: Path, llm_choice: str, doc_id: str | None, max_workers: int
):
    """Shared engine for `kb summarize` and `kb ingest`.

    Returns (report | None, reason): report is None when no runner ran;
    reason is "disabled" | "missing" | "" accordingly.
    """
    from center_kb.summarize import summarize_kb

    runner, reason, workers = _resolve_runner(kb_dir, llm_choice, max_workers)
    if runner is None:
        return None, reason
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
    redo: bool = typer.Option(
        False,
        "--redo",
        help="Reset summarized/reviewed sections to pending (restoring L2 "
        "markers) and re-summarize from scratch",
    ),
) -> None:
    """Fill pending L1/L2 summaries by calling a headless LLM CLI (claude/copilot)."""
    _validate_llm_choice(llm)
    if not (kb_dir / "index.yaml").exists():
        typer.secho(f"not found: {kb_dir / 'index.yaml'}", fg=typer.colors.RED)
        raise typer.Exit(1)
    if redo:
        from center_kb.summarize import redo_reset

        # Resolve the runner BEFORE resetting: a redo must never wipe
        # summaries when the subsequent run can't happen anyway.
        runner_probe, reason, _ = _resolve_runner(kb_dir, llm, max_workers)
        if runner_probe is None:
            _echo_no_runner(reason)
            raise typer.Exit(1)
        rr = redo_reset(kb_dir, doc_id or None)
        typer.echo(f"redo: {len(rr.reset)} section(s) reset to pending")
        if rr.reviewed_reset:
            typer.secho(
                f"[warn] {rr.reviewed_reset} reviewed section(s) were reset",
                fg=typer.colors.YELLOW,
            )
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
        False,
        "--semantic",
        help="Warn when embeddings are unavailable (hybrid runs both legs automatically)",
    ),
) -> None:
    """Hybrid search (FTS5 keyword + semantic KNN, RRF-fused) → L2 sections within budget, with citations."""
    from center_kb.query import search

    handle = _hub_or_exit(hub, kb_dir)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] or None
    results = search(
        handle, text, tags=tag_list, budget=budget, semantic=semantic
    )
    if not results:
        typer.echo("No matching section found.")
        raise typer.Exit(0)
    for r in results:
        typer.secho(
            f"--- [{r.citation}] match={r.match_mode} ~{r.tokens}tk", bold=True
        )
        typer.echo(r.content)
        if r.snippet:
            typer.secho(f"raw match: {r.snippet}", dim=True)
        typer.echo("")


@app.command()
def get(
    doc_id: str = typer.Argument(..., help="Document ID"),
    section: str = typer.Argument(..., help="Section ID, e.g. 5.3 or §5.3"),
    level: str = typer.Option("l2", help="Level: l2 or l3"),
    repo: str = typer.Option(
        "", "--repo", help="Repo ID when the doc-id collides across repos"
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    hub: str = typer.Option(
        "", "--hub", envvar="CENTER_KB_HUB", help="kb-hub URL/path (empty = don't use)"
    ),
) -> None:
    """Fetch exactly one section at the given level."""
    from center_kb.query import AmbiguousDocError, get_section

    handle = _hub_or_exit(hub, kb_dir)
    try:
        result = get_section(handle, doc_id, section, level=level, repo=repo or None)
    except AmbiguousDocError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
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
        "", "--hub", envvar="CENTER_KB_HUB",
        help="kb-hub URL/path (default: .kb/config.yaml)",
    ),
    repo_id: str = typer.Option(
        "", "--repo-id",
        help="Repo ID on the hub (default: config.yaml, then the git root dir name)",
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    pr: bool = typer.Option(
        False, "--pr", help="Force PR mode (requires gh + a GitHub hub)"
    ),
    direct: bool = typer.Option(
        False, "--direct", help="Force direct mode (push straight to the hub's main)"
    ),
) -> None:
    """Mirror .kb/ (L0→L3) to the hub's federation/<repo-id>/ + rebuild the index."""
    from center_kb import gitio
    from center_kb import publish as publish_mod
    from center_kb.config import HubConfigError, effective_repo_id, load_config, require_hub

    if pr and direct:
        typer.secho("--pr and --direct are mutually exclusive", fg=typer.colors.RED)
        raise typer.Exit(2)

    cfg = load_config(kb_dir)
    if cfg.intake and not pr and not direct:
        try:
            pr_url = publish_mod.publish_via_intake(
                kb_dir, cfg.intake, effective_repo_id(repo_id, kb_dir)
            )
        except (publish_mod.PublishError, gitio.GitError) as exc:
            typer.secho(str(exc), fg=typer.colors.RED)
            raise typer.Exit(1)
        if pr_url:
            typer.echo(f"kb publish: PR on the hub — {pr_url}")
            typer.echo("Content goes live when the PR is merged on the hub.")
        else:
            typer.echo("kb publish: done (no PR URL reported).")
        return

    mode = "pr" if pr else "direct" if direct else "auto"
    try:
        hub_ref = require_hub(hub, kb_dir)
        report = publish_mod.publish(
            kb_dir, hub_ref,
            repo_id=effective_repo_id(repo_id, kb_dir), mode=mode,
        )
    except (HubConfigError, publish_mod.PublishError, gitio.GitError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    if report.mode == "pr":
        if report.pr_url:
            typer.echo(
                f"kb publish: {report.repo_id} @ {report.source_commit} — "
                f"{report.n_docs} doc, PR: {report.pr_url}"
            )
            typer.echo("Content goes live when the PR is merged on the hub.")
        else:
            typer.echo("kb publish: nothing changed — no PR needed.")
        return
    action = "push" if report.pushed else "commit only (hub has no remote)"
    typer.echo(
        f"kb publish: {report.repo_id} @ {report.source_commit} — "
        f"{report.n_docs} doc, {action}."
    )


@app.command(name="ci-publish")
def ci_publish(
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    repo_id: str = typer.Option("", "--repo-id", help="Repo ID on the hub (default: config)"),
    intake: str = typer.Option(
        "", "--intake", envvar="CENTER_KB_INTAKE",
        help="Intake base URL (default: .kb/config.yaml `intake:`)",
    ),
) -> None:
    """Publish from the child's CI via OIDC — no secrets. Run by kb-publish.yml."""
    from center_kb import cipublish, gitio
    from center_kb.config import effective_repo_id, load_config

    url = intake or load_config(kb_dir).intake
    if not url:
        typer.secho(
            "no intake URL — add `intake: <url>` to .kb/config.yaml or pass --intake",
            fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    try:
        cipublish.run(kb_dir, url, effective_repo_id(repo_id, kb_dir))
    except (cipublish.CIPublishError, gitio.GitError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)


@app.command()
def reindex(
    hub: str = typer.Option(
        "", "--hub", envvar="CENTER_KB_HUB",
        help="kb-hub URL/path (default: .kb/config.yaml)",
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory (to find the config)"),
) -> None:
    """Rebuild federation/index.yaml from the sub-snapshots (fix a drifted index)."""
    from center_kb import gitio, searchdb
    from center_kb.embed import default_embedder
    from center_kb.federation import write_federation_index

    handle = _hub_or_exit(hub, kb_dir)
    write_federation_index(handle.federation_dir)
    # commit index.yaml TRƯỚC khi sync search index: sync strict có thể nổ
    # (lỗi embed) — không được để index rebuilt nằm uncommitted
    committed = gitio.commit_paths(
        handle.root, "reindex: rebuild federation/index.yaml", ["federation"]
    )
    sreport = searchdb.sync(handle, default_embedder())
    typer.echo(
        f"kb reindex: search index — {sreport.sections_updated} updated, "
        f"{sreport.sections_deleted} removed, {sreport.embedded} embedded"
    )
    if not committed:
        typer.echo("kb reindex: index already consistent — nothing to do")
        return
    if gitio.has_remote(handle.root):
        try:
            gitio.push(handle.root)
        except gitio.GitError as exc:
            typer.secho(
                f"reindex committed but push failed: {exc}", fg=typer.colors.RED
            )
            raise typer.Exit(1)
    typer.echo("kb reindex: federation/index.yaml rebuilt")


@assets_app.command()
def migrate(
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    hub: str = typer.Option(
        "", "--hub", envvar="CENTER_KB_HUB", help="kb-hub URL/path (empty = config)"
    ),
) -> None:
    """Move in-git federation assets to the configured object store (none → s3)."""
    from center_kb import assetcmd, assetstore

    handle = _hub_or_exit(hub, kb_dir)
    try:
        report = assetcmd.migrate_assets(handle)
    except (assetcmd.AssetCmdError, assetstore.AssetStoreError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    for rid, n in sorted(report.per_rid.items()):
        typer.echo(f"  {rid}: {n} asset(s) migrated")
    if not report.per_rid:
        typer.echo("nothing to migrate — no in-git assets under federation/")
    elif report.committed:
        typer.echo("committed: assets: migrate to object store")
        typer.echo("(commit is local — push to publish if the hub has a remote)")


@assets_app.command()
def verify(
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    hub: str = typer.Option(
        "", "--hub", envvar="CENTER_KB_HUB", help="kb-hub URL/path (empty = config)"
    ),
) -> None:
    """Check asset coverage: records vs store, markdown refs, orphans."""
    from center_kb import assetcmd, assetstore

    handle = _hub_or_exit(hub, kb_dir)
    try:
        report = assetcmd.verify_assets(handle)
    except (assetcmd.AssetCmdError, assetstore.AssetStoreError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    for label in report.missing_records:
        typer.secho(f"[missing] recorded but not in store: {label}", fg=typer.colors.RED)
    for label in report.dangling_refs:
        typer.secho(f"[dangling] referenced but unresolvable: {label}", fg=typer.colors.RED)
    for label in report.orphans:
        typer.echo(f"[orphan] recorded but never referenced: {label}")
    if not report.ok:
        raise typer.Exit(1)
    typer.echo("kb assets verify: OK")


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

    handle = _hub_or_exit(hub, kb_dir)
    ref_strs = [r for r in refs.split(",") if r.strip()]
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    try:
        block, stale_warning = kbcontext.build_context_block(
            handle, ref_strs, tags=tag_list
        )
    except (kbcontext.KBContextError, gitio.GitError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    if stale_warning:
        typer.secho(stale_warning, fg=typer.colors.YELLOW, err=True)
    typer.echo(block)


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
    handle = _hub_or_exit(hub, kb_dir)
    try:
        ctx = kbcontext.parse(text)
        results = resolve_refs(handle, ctx)
    except (kbcontext.KBContextError, gitio.GitError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.echo(render_resolved(results))
    if any(r.status == "broken" for r in results):
        raise typer.Exit(1)
    if any(r.status == "stale" for r in results):
        raise typer.Exit(2)


@ticket_app.command("lint")
def ticket_lint(
    source: str = typer.Argument(
        ..., help="Ticket file (or '-' to read from stdin)"
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    hub: str = typer.Option(
        "", "--hub", envvar="CENTER_KB_HUB", help="kb-hub URL/path (empty = don't use)"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit the report as JSON instead of text"
    ),
) -> None:
    """Definition-of-Ready gate: lint a ticket against the DoR checklist."""
    from center_kb.ticketlint import lint

    if source == "-":
        text = sys.stdin.read()
    else:
        try:
            text = Path(source).read_text(encoding="utf-8")
        except OSError as exc:
            typer.secho(f"could not read file '{source}': {exc}", fg=typer.colors.RED)
            raise typer.Exit(1)
    handle = _hub_or_exit(hub, kb_dir)
    report = lint(text, handle)
    if json_output:
        typer.echo(json.dumps(report.to_json()))
    else:
        typer.echo(report.render())
    if not report.passed:
        raise typer.Exit(1)


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
    from center_kb.config import effective_repo_id
    from center_kb.doctor import (
        check_asset_store,
        check_context,
        check_hub,
        check_kb,
        check_kind,
    )

    handle = _hub_or_exit(hub, kb_dir)
    issues = check_kind(kb_dir) + check_kb(kb_dir) + check_asset_store(kb_dir, handle)
    repo_id = effective_repo_id("", kb_dir)
    if not repo_id:
        try:
            from center_kb import gitio as _gitio

            repo_id = _gitio.git_root(kb_dir.resolve()).name
        except Exception:
            repo_id = None
    hub_issues, hub_stale = check_hub(kb_dir, handle, repo_id=repo_id)
    issues += hub_issues
    has_stale = False
    if context is not None:
        text = sys.stdin.read() if context == "-" else Path(context).read_text(
            encoding="utf-8"
        )
        ctx_issues, results = check_context(text, handle)
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
