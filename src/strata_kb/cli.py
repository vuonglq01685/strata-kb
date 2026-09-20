from __future__ import annotations

import importlib.metadata
import json
import os
import sys
from enum import Enum
from pathlib import Path

import typer
import yaml
from pydantic import ValidationError

from strata_kb import models
from strata_kb.utf8io import force_utf8_streams

force_utf8_streams()

# One tuple for every "an operator-authored YAML file did not parse or did
# not validate" read in this module. yaml.YAMLError is not a ValueError;
# UnicodeDecodeError and pydantic.ValidationError both are, but all three are
# kept explicit (like models.load_yaml_model's other callers) so a non-UTF-8
# file is not left to an OSError arm.
# Was three identical locals inside publish(), ci_publish() and reindex()
# (ci_publish() and reindex() each pointed at publish()'s comment; publish()'s
# own carried the reasoning inline) -- _hub_or_exit needs it too, which is
# what made the duplication untenable.
_CONFIG_READ_ERRORS = (yaml.YAMLError, ValidationError, ValueError)


def _invalid_yaml_exit(path: Path, exc: Exception) -> None:
    """Report an unparseable/invalid operator-authored YAML file and exit 1."""
    typer.secho(f"{path} is invalid: {' '.join(str(exc).split())}", fg=typer.colors.RED)
    raise typer.Exit(1)


app = typer.Typer(
    help="Strata — Knowledge Base as Code for large reference documents.",
    no_args_is_help=True,
    # Several commands (mcp-setup) handle secrets. Some typer/click versions
    # default this to True, which prints local variables -- including the
    # secret -- into an uncaught exception's traceback. False everywhere.
    pretty_exceptions_show_locals=False,
)

context_app = typer.Typer(help="Operate on kb-context blocks (machine-readable citations).")
app.add_typer(context_app, name="context")

assets_app = typer.Typer(help="Asset store operations (hub): migrate, verify")
app.add_typer(assets_app, name="assets")

ticket_app = typer.Typer(help="Ticket linting: Definition-of-Ready gate for BA tickets.")
app.add_typer(ticket_app, name="ticket")

mission_app = typer.Typer(
    help="Mission linting: Definition-of-Ready gate for BA mission plans."
)
app.add_typer(mission_app, name="mission")

svc_app = typer.Typer(help="Service knowledge: record which tickets touched which service.")
app.add_typer(svc_app, name="svc")

usage_app = typer.Typer(
    help="Token/cost measurement: ingest transcripts, record rows, render a report."
)
app.add_typer(usage_app, name="usage")

pr_app = typer.Typer(
    help="Pull-request gate: check a PR description carries its evidence."
)
app.add_typer(pr_app, name="pr")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(importlib.metadata.version("strata-kb"))
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the installed strata-kb version and exit.",
    ),
) -> None:
    """Strata CLI."""


class RepoKind(str, Enum):
    hub = "hub"
    child = "child"
    ba = "ba"
    dev = "dev"


class AssetsMode(str, Enum):
    none = "none"
    s3 = "s3"


KIND_DESCRIPTIONS = """\
This repo can be one of four kinds:

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

  dev   — Product code repo. Implements BA tickets grounded in the KB via the
          dev-implement-ticket workflow (design → plan → execute → handover,
          TDD enforced), and, from Stage B on, publishes generated knowledge
          about its own source code back to the hub. Never ingests outside
          documents.
"""


def _stdin_isatty() -> bool:
    return sys.stdin.isatty()


def _resolve_kind(target: Path, kind_flag: RepoKind | None) -> str:
    """persisted kind > --kind flag > interactive prompt > hard error."""
    from strata_kb.config import load_config

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
            answer = typer.prompt("Initialize this repo as (hub, child, ba, dev)")
            answer = answer.strip().lower()
            if answer in ("hub", "child", "ba", "dev"):
                return answer
            typer.secho(
                f"Error: {answer!r} is not one of 'hub', 'child', 'ba', 'dev'.",
                fg=typer.colors.RED,
            )
    # NOTE: this message intentionally still reads "hub|child" (not
    # "hub|child|ba") — an existing test asserts this exact string, and
    # --kind ba works correctly whether or not it's advertised here.
    typer.secho(
        "kb init requires --kind hub|child when not running interactively.",
        fg=typer.colors.RED,
    )
    raise typer.Exit(1)


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
        help="Also overwrite protected data "
        "(.kb/config.yaml, .kb/index.yaml, .claude/settings.json)",
    ),
    assets: AssetsMode | None = typer.Option(
        None,
        "--assets",
        help="Hub asset storage: none (assets in git, default) or s3 "
        "(object store — spec B). Hub kind only.",
    ),
    lang: list[str] = typer.Option(
        [],
        "--lang",
        help="Force a conventions pack for a language whose manifest is not "
        "detectable (repeatable): python, ts, java, go, dotnet, php, rust, "
        "swift, dart, e2e-playwright. Dev kind only; recorded in "
        ".kb/config.yaml so a plain re-init keeps it.",
    ),
) -> None:
    """Scaffold or refresh a KB repo: skills/templates update by default; data is preserved."""
    from strata_kb.initcmd import PROTECTED_FILES, init_repo

    resolved = _resolve_kind(path, kind)
    if assets is not None and resolved != "hub":
        typer.secho(
            "--assets applies to hubs only — a child never configures asset "
            "storage (bytes ride the publish transport to the hub).",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    if lang:
        from strata_kb.conventions import LANG_IDS

        unknown = [lang_id for lang_id in lang if lang_id not in LANG_IDS]
        if unknown:
            typer.secho(
                f"unknown --lang {', '.join(unknown)} — choose from {', '.join(LANG_IDS)}",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)
        if resolved != "dev":
            typer.secho("--lang applies to dev repos only", fg=typer.colors.RED)
            raise typer.Exit(1)
    report = init_repo(path, resolved, force=force,
                       assets=assets.value if assets else None, langs=lang)
    for rel in report.created:
        typer.echo(f"  created  {rel}")
    for rel in report.updated:
        typer.echo(f"  updated  {rel}")
    for rel in report.skipped:
        # `--force` only re-writes PROTECTED_FILES; a `.local.md` override
        # (or any other skip entry, e.g. `.gitignore`'s merge-only skip)
        # already carries its own explanation and `--force` cannot touch
        # it, so the hint below must not be printed for those — it would
        # tell a BA/dev a flag exists that provably cannot do what it says.
        hint = " (protected data — use --force to overwrite)" if rel in PROTECTED_FILES else ""
        typer.secho(f"  skipped  {rel}{hint}", fg=typer.colors.YELLOW)
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
                'export credentials (AWS env chain), pip install "strata-kb[s3]", '
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
    elif resolved == "ba":
        typer.echo("  1. Fill hub: in .kb/config.yaml with the main hub URL/path")
        typer.echo(
            "  2. kb mcp-setup   (or /kb-mcp-setup)"
            "  # writes STRATA_KB_HUB_URL / STRATA_KB_HTTP_TOKEN into .env"
        )
        typer.echo(
            "  3. Open this repo in Claude Code / Copilot Chat / Cursor and "
            "run /ba-ticket-author"
        )
    else:  # dev
        typer.echo(
            "  1. Fill hub: in .kb/config.yaml with the main hub URL/path — "
            "this is the only read source for kb query / kb resolve / MCP. "
            "Also fill intake: and ask the hub maintainer to add this repo "
            "to federation/registry.yaml — prep for Stage B; neither is "
            "usable yet"
        )
        typer.echo(
            "  2. kb mcp-setup   (or /kb-mcp-setup)"
            "  # writes STRATA_KB_HUB_URL / STRATA_KB_HTTP_TOKEN into .env"
        )
        typer.echo(
            "  3. Open this repo in Claude Code / Copilot Chat / Cursor and "
            "run /dev-implement-ticket <ticket>"
        )
    quickstart_name = {
        "ba": "QUICKSTART-BA.md",
        "dev": "QUICKSTART-DEV.md",
    }.get(resolved, "QUICKSTART.md")
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
    from strata_kb import dockersetup

    try:
        kind = dockersetup.repo_kind(path)
    except dockersetup.DockerSetupError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    if kind == "hub":
        _docker_setup_hub(path, force, no_docker)
    elif kind == "child":
        _docker_setup_child(path, no_docker)
    else:
        typer.secho(
            f"kind: {kind} does not run Docker — kb docker-setup applies to "
            "hub (serves the KB) and child (pulls the ingest image). "
            "To connect this repo to a hub, run `kb mcp-setup`.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)


def _docker_setup_hub(path: Path, force: bool, no_docker: bool) -> None:
    from strata_kb import dockersetup

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
    typer.echo('  { "mcpServers": { "strata-kb": { "type": "http",')
    typer.echo('    "url": "http://<host>:8321/mcp",')
    typer.echo('    "headers": { "Authorization": "Bearer <token>" } } } }')


def _docker_setup_child(path: Path, no_docker: bool) -> None:
    from strata_kb import dockersetup

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


@app.command("mcp-setup")
def mcp_setup(
    path: Path = typer.Argument(Path("."), help="Repo root (default: current)"),
    hub_url: str = typer.Option(
        "", "--hub-url", help="Hub HTTP base URL, e.g. http://kb-hub.example.com:8321"
    ),
    token: str = typer.Option(
        "", "--token", help="Hub HTTP token (env: STRATA_KB_HTTP_TOKEN)"
    ),
    no_verify: bool = typer.Option(
        False, "--no-verify", help="Write the files; skip the connection probe"
    ),
) -> None:
    """Connect this repo to the hub's HTTP MCP — write .env, then verify."""
    from strata_kb import mcpsetup
    from strata_kb.errors import KbError

    try:
        mcpsetup.require_client_kind(path)
        if token:
            typer.secho(
                "--token puts the token in your shell history and in "
                "`ps`/process-listing output for any other user on this "
                f"machine — prefer the prompt or {mcpsetup.TOKEN_VAR}.",
                fg=typer.colors.YELLOW,
            )
        url = mcpsetup.normalize_hub_url(
            _resolve_mcp_value(
                path,
                flag=hub_url,
                var=mcpsetup.HUB_URL_VAR,
                prompt="Hub HTTP base URL (e.g. http://kb-hub.example.com:8321)",
            )
        )
        if mcpsetup.is_plaintext_remote(url):
            typer.secho(
                f"{url} is http:// to a non-loopback host — the token will "
                "cross the network in clear. Use https:// if the hub "
                "supports it.",
                fg=typer.colors.YELLOW,
            )
        secret = _resolve_mcp_value(
            path,
            flag=token,
            var=mcpsetup.TOKEN_VAR,
            prompt="Hub HTTP token",
            hide_input=True,
        )
        report = mcpsetup.write_env(path, url, secret)
    except UnicodeDecodeError as exc:
        # A non-UTF-8 .env. Unlike OSError below, str(exc) alone names no
        # file, so name it here -- otherwise the operator sees a bare codec
        # error with no clue it concerns .env.
        typer.secho(f"cannot read {path / '.env'}: {exc}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except (KbError, OSError) as exc:
        # write_env can raise OSError (unwritable repo dir), which must
        # produce the same one-line message as KbError, never propagate to
        # Typer's traceback hook where the token could leak (see
        # app=typer.Typer above).
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)

    action = "created" if report.env_created else "updated"
    typer.echo(
        f".env {action} — {mcpsetup.HUB_URL_VAR} and {mcpsetup.TOKEN_VAR} "
        "written (token not shown; see .env)."
    )
    if report.gitignore_updated:
        typer.echo(".gitignore updated: added .env")
    typer.echo("Load it into the current shell:")
    typer.echo("  bash/zsh:   set -a; source .env; set +a")
    typer.echo(
        "  PowerShell: Get-Content .env | %{ $k,$v = $_.Split('=',2); "
        "[Environment]::SetEnvironmentVariable($k,$v) }"
    )
    typer.echo(
        "To persist, add that line to your shell profile (~/.zshrc), or use "
        "direnv."
    )

    if not no_verify:
        result = mcpsetup.probe(url, secret)
        if not result.ok:
            typer.secho(result.message, fg=typer.colors.RED)
            if result.token_rejected:
                # A plain re-run reads the same rejected value straight
                # back out of .env (the resolution ladder never reaches the
                # prompt once anything is on disk) -- name the one escape
                # that actually replaces it, not the loop that doesn't.
                typer.echo(
                    "Got a new token from the hub maintainer? A bare "
                    "re-run will just read the old one back out of .env. "
                    f"Override it once with: {mcpsetup.TOKEN_VAR}=<new-token> "
                    "kb mcp-setup — or delete the "
                    f"{mcpsetup.TOKEN_VAR} line from .env and re-run."
                )
            else:
                typer.echo(
                    ".env is written — correct the value and re-run `kb mcp-setup`."
                )
            raise typer.Exit(1)
        typer.echo(result.message)
        if result.warning:
            typer.secho(result.warning, fg=typer.colors.YELLOW)

    typer.echo(
        "Restart Claude Code / Cursor so MCP picks up the environment — MCP "
        "servers read env only at client startup."
    )


def _resolve_mcp_value(
    path: Path, flag: str, var: str, prompt: str, hide_input: bool = False
) -> str:
    """flag > environment > the value already in .env > TTY prompt > error.

    The `.env` rung is what makes a bare `kb mcp-setup` on a configured repo
    mean "verify again", and it is how the assistant wrapper re-runs this
    command without ever handling the token itself.

    The final check strips before testing emptiness (not just `not value`):
    a whitespace-only flag or prompt answer must fail here too, since
    `write_env` strips on the way in and would otherwise write an empty
    value, clobbering whatever good value was already on disk.
    """
    from strata_kb import mcpsetup

    value = flag or os.environ.get(var, "") or mcpsetup.read_env_value(path, var)
    if not value and _stdin_isatty():
        value = typer.prompt(prompt, hide_input=hide_input)
    if not value.strip():
        raise mcpsetup.McpSetupError(
            f"no value for {var} — pass the flag, set the environment "
            "variable, or run this in a terminal where it can prompt"
        )
    return value.strip()


def _hub_or_exit(hub_flag: str, kb_dir: Path):
    """Hub is required: flag > env (typer envvar already folded) > .kb/config.yaml."""
    from strata_kb import gitio
    from strata_kb.config import HubConfigError, require_hub
    from strata_kb.hub import resolve_hub

    try:
        hub_ref = require_hub(hub_flag, kb_dir)
    except HubConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    except (*_CONFIG_READ_ERRORS, OSError) as exc:
        # require_hub -> load_config -> models.load_yaml_model raises
        # ValidationError / yaml.YAMLError for an operator-edited
        # .kb/config.yaml. 11 commands funnel through here, so this is the
        # one place that keeps any of them from printing a traceback (H1).
        _invalid_yaml_exit(kb_dir / "config.yaml", exc)
    # cli.py's own last unguarded resolve_hub call site (release review,
    # 2026-09-11): resolve_hub can raise gitio.GitError (hub.py's
    # _discard_cache) when a stale cache's removal is blocked -- e.g. a
    # locked .kb-work/search.sqlite3, and every command that reaches here
    # (`doctor` included, the CHANGELOG's 0.21.0 no-traceback claim for it)
    # is exactly the kind of process that would be holding it open. Same
    # shape as mcp._hub (Wave G fix round 3) and web/api.hub_handle
    # (e869320) -- but this is a CLI path, not one that degrades to a
    # cache-less handle: it must exit 1 naming the way forward, not return
    # None. _discard_cache's own GitError message already names the cache,
    # says it is disposable, and tells the operator to delete it -- let
    # that through unwrapped rather than replacing it.
    try:
        handle = resolve_hub(hub_ref)
    except gitio.GitError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    if handle is None:
        typer.secho(
            f"could not reach hub '{gitio.redact_url(hub_ref)}' and no cache exists — "
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
    doc_id: str = typer.Option(..., "--id", help="Document ID, e.g. hr-handbook"),
    tags: str = typer.Option("", help="Tags, comma-separated"),
    revision: str = typer.Option("", help="Revision, e.g. '2026 edition'"),
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
    from strata_kb import ingestcmd

    _validate_llm_choice(llm)
    opts = ingestcmd.IngestOptions(
        pdf=pdf,
        doc_id=doc_id,
        tags=tags,
        revision=revision,
        sections=sections,
        kb_dir=kb_dir,
        work_dir=work_dir,
        chapter_pattern=chapter_pattern,
        appendix_pattern=appendix_pattern,
        attachment_pattern=attachment_pattern,
        no_bookmarks=no_bookmarks,
    )
    try:
        report = ingestcmd.run_ingest(
            opts,
            echo=typer.echo,
            warn=lambda msg: typer.secho(f"  [warn] {msg}", fg=typer.colors.YELLOW),
        )
    except (ValueError, RuntimeError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
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
    from strata_kb.build import build_kb

    build_report = build_kb(kb_dir, allow_pending=bool(report_s.failed))
    for err in build_report.errors:
        typer.secho(f"  [build] {err}", fg=typer.colors.RED)
    for warn in build_report.warnings + build_report.quality:
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
        raise typer.Exit(1)


def _resolve_runner(kb_dir: Path, llm_choice: str, max_workers: int):
    """Returns (runner | None, reason, workers): reason is "disabled" | "missing" | ""."""
    import strata_kb.llm as llm_mod

    try:
        index = models.load_yaml_model(kb_dir / "index.yaml", models.KBIndex)
    except ValueError as exc:
        # pydantic.ValidationError is a ValueError subclass — a bad literal
        # (e.g. a typo'd llm.effort) must read as a clean CLI error, not a
        # traceback (B4).
        typer.secho(f"[error] {exc}", fg=typer.colors.RED)
        raise typer.Exit(1) from exc
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
    from strata_kb.summarize import summarize_kb

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
        help="Reset summaries of DOC_ID (or --all) to pending and re-summarize",
    ),
    all_docs: bool = typer.Option(
        False, "--all", help="With --redo: reset every document in the KB"
    ),
    include_reviewed: bool = typer.Option(
        False,
        "--include-reviewed",
        help="With --redo: also reset reviewed sections (asks for confirmation)",
    ),
    yes: bool = typer.Option(
        False, "--yes", help="With --redo: skip the confirmation prompt"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="With --redo: print what would be reset and stop"
    ),
    section: list[str] = typer.Option(
        [], "--section", help="With --redo/--print-prompt: only these section ids (repeatable)"
    ),
    print_prompt: bool = typer.Option(
        False,
        "--print-prompt",
        help="Print the engine's prompt for each pending section of DOC_ID and exit",
    ),
) -> None:
    """Fill pending L1/L2 summaries by calling a headless LLM CLI (claude/copilot)."""
    _validate_summarize_args(
        kb_dir, llm, redo, print_prompt, all_docs, include_reviewed, yes, dry_run, section
    )
    _dispatch_summarize(
        kb_dir, llm, max_workers, doc_id, redo, print_prompt,
        all_docs, include_reviewed, yes, dry_run, section,
    )


def _dispatch_summarize(
    kb_dir: Path,
    llm: str,
    max_workers: int,
    doc_id: str,
    redo: bool,
    print_prompt: bool,
    all_docs: bool,
    include_reviewed: bool,
    yes: bool,
    dry_run: bool,
    section: list[str],
) -> None:
    """Route to --print-prompt / --redo / the plain summarize run, in that
    precedence order — flags were already validated by `_validate_summarize_args`."""
    if print_prompt:
        _print_prompts(kb_dir, doc_id, list(section))
        return
    if redo:
        _redo_or_exit(
            kb_dir, llm, max_workers, doc_id, all_docs, include_reviewed, yes,
            dry_run, list(section),
        )
        if dry_run:
            return
    _run_summarize_and_report(kb_dir, llm, doc_id, max_workers)


def _validate_summarize_args(
    kb_dir: Path,
    llm: str,
    redo: bool,
    print_prompt: bool,
    all_docs: bool,
    include_reviewed: bool,
    yes: bool,
    dry_run: bool,
    section: list[str],
) -> None:
    """Flag-combination + KB-presence checks shared by every `summarize` path."""
    _validate_llm_choice(llm)
    if redo and print_prompt:
        typer.secho("--print-prompt cannot be combined with --redo", fg=typer.colors.RED)
        raise typer.Exit(1)
    if not redo:
        _require_redo_for_redo_only_flags(
            all_docs, include_reviewed, yes, dry_run, [] if print_prompt else section
        )
    if not (kb_dir / "index.yaml").exists():
        typer.secho(f"not found: {kb_dir / 'index.yaml'}", fg=typer.colors.RED)
        raise typer.Exit(1)


def _run_summarize_and_report(
    kb_dir: Path, llm: str, doc_id: str, max_workers: int
) -> None:
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


def _require_redo_for_redo_only_flags(
    all_docs: bool, include_reviewed: bool, yes: bool, dry_run: bool, sections: list[str]
) -> None:
    """`--all`/`--include-reviewed`/`--yes`/`--dry-run`/`--section` only mean
    anything alongside `--redo` — refuse them outright otherwise instead of
    silently ignoring a flag the caller thought was doing something."""
    for flag_name, flag_set in (
        ("--all", all_docs),
        ("--include-reviewed", include_reviewed),
        ("--yes", yes),
        ("--dry-run", dry_run),
        ("--section", bool(sections)),
    ):
        if flag_set:
            typer.secho(f"{flag_name} requires --redo", fg=typer.colors.RED)
            raise typer.Exit(1)


def _validate_redo_flags(doc_id: str, all_docs: bool, sections: list[str]) -> None:
    """`--redo` needs exactly one target and rejects contradictory combinations."""
    if sections and not doc_id:
        typer.secho("--section requires a DOC_ID", fg=typer.colors.RED)
        raise typer.Exit(1)
    if not doc_id and not all_docs:
        typer.secho(
            "--redo resets every summary; name a document, or pass --all to "
            "reset the whole KB.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    if doc_id and all_docs:
        typer.secho("--all cannot be combined with a DOC_ID", fg=typer.colors.RED)
        raise typer.Exit(1)


def _echo_redo_plan(doc_id: str, plan) -> None:
    scope = doc_id or "the whole KB"
    typer.echo(
        f"redo: {len(plan.items)} section(s) in {scope} will be reset "
        f"({len(plan.skipped_reviewed)} reviewed skipped)"
    )
    for item in plan.reviewed_items:
        rec = item.reviewed
        who = f"{rec.by} at {rec.at}" if rec else "(no record)"
        typer.echo(f"  {item.doc_id}/{item.section_id} reviewed by {who}")


def _confirm_and_apply_redo(kb_dir: Path, plan, yes: bool) -> None:
    from strata_kb.summarize import redo_reset

    if plan.reviewed_items and not yes:
        try:
            ok = typer.confirm(
                "Reset these reviewed sections? Their L2 text and sign-off "
                "will be removed (recoverable with git checkout).",
                default=False,
            )
        except typer.Abort:
            ok = False
        if not ok:
            typer.secho("redo aborted — nothing written", fg=typer.colors.YELLOW)
            raise typer.Exit(1)
    rr = redo_reset(kb_dir, plan)
    typer.echo(f"redo: {len(rr.reset)} section(s) reset to pending")
    if rr.failed:
        for msg in rr.failed:
            typer.secho(f"[fail] {msg}", fg=typer.colors.RED)
        raise typer.Exit(1)


def _redo_or_exit(
    kb_dir: Path,
    llm: str,
    max_workers: int,
    doc_id: str,
    all_docs: bool,
    include_reviewed: bool,
    yes: bool,
    dry_run: bool,
    sections: list[str],
) -> None:
    """Preview and (unless --dry-run) apply a `--redo` plan before the
    real summarize run. Resolves the runner FIRST: a redo must never wipe
    summaries when the subsequent run can't happen anyway."""
    from strata_kb.summarize import plan_redo

    _validate_redo_flags(doc_id, all_docs, sections)
    runner_probe, reason, _ = _resolve_runner(kb_dir, llm, max_workers)
    if runner_probe is None:
        _echo_no_runner(reason)
        raise typer.Exit(1)
    try:
        plan = plan_redo(kb_dir, doc_id or None, sections or None, include_reviewed)
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from exc
    _echo_redo_plan(doc_id, plan)
    if dry_run:
        return
    _confirm_and_apply_redo(kb_dir, plan, yes)


def _print_prompts(kb_dir: Path, doc_id: str, sections: list[str]) -> None:
    """Print the engine's exact per-section prompt for every pending section
    of `doc_id`, so the manual (skill-driven) path can build it without
    reading L3 directly. Table-only/brief sections need no LLM call — say
    so instead of a prompt."""
    from strata_kb.summarize import build_section_prompt, collect_pending

    if not doc_id:
        typer.secho("--print-prompt requires a DOC_ID", fg=typer.colors.RED)
        raise typer.Exit(1)
    pending = collect_pending(
        kb_dir, doc_id,
        on_missing=lambda msg: typer.secho(f"[skip] {msg}", fg=typer.colors.YELLOW),
    )
    if sections:
        known = {s.section_id for s in pending}
        missing = [s for s in sections if s not in known]
        if missing:
            typer.secho(
                f"not pending or not found in {doc_id}: {', '.join(missing)}",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)
        pending = [s for s in pending if s.section_id in sections]
    if not pending:
        typer.echo("nothing pending")
        return
    for s in pending:
        head = f"=== {s.doc_id}/{s.section_id} ==="
        if s.kind == "llm":
            typer.echo(head)
            typer.echo(build_section_prompt(s))
        else:
            label = "brief" if s.kind == "brief" else "table-only"
            typer.echo(f"{head} [no LLM needed: {label} — run kb summarize to fill it]")
        typer.echo()


@app.command()
def status(
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
) -> None:
    """List sections pending summarization (status=pending)."""
    index_path = kb_dir / "index.yaml"
    if not index_path.exists():
        typer.echo("KB is empty — no index.yaml yet.")
        raise typer.Exit(0)
    try:
        index = models.load_yaml_model(index_path, models.KBIndex)
    except (*_CONFIG_READ_ERRORS, OSError) as exc:
        _invalid_yaml_exit(index_path, exc)
    total_pending = 0
    for entry in index.docs:
        manifest_path = kb_dir / entry.id / "_manifest.yaml"
        if not manifest_path.exists():
            continue
        try:
            manifest = models.load_yaml_model(manifest_path, models.Manifest)
        except (*_CONFIG_READ_ERRORS, OSError) as exc:
            _invalid_yaml_exit(manifest_path, exc)
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
    strict: bool = typer.Option(
        False, "--strict", help="Treat quality findings (C2 rules) as errors"
    ),
) -> None:
    """Validate KB: no TODOs left, table integrity, C2 quality rules, updated token counts."""
    from strata_kb.build import build_kb

    try:
        report = build_kb(kb_dir, allow_pending=allow_pending, strict=strict)
    except ValueError as exc:
        # pydantic.ValidationError is a ValueError subclass — a bad literal
        # (e.g. a typo'd llm.effort) must read as a clean CLI error, not a
        # traceback (B4).
        typer.secho(f"[error] {exc}", fg=typer.colors.RED)
        raise typer.Exit(1) from exc
    for warning in report.warnings + report.quality:
        typer.secho(f"[warn] {warning}", fg=typer.colors.YELLOW)
    for error in report.errors:
        typer.secho(f"[error] {error}", fg=typer.colors.RED)
    if not report.ok:
        raise typer.Exit(1)
    typer.echo("kb build: OK")


@app.command(name="code-ingest")
def code_ingest(
    repo_root: Path = typer.Option(Path("."), "--repo-root", help="Repository root to scan"),
    kb_dir: Path = typer.Option(
        Path(".kb"),
        help="KB directory (default: .kb, relative to the current directory like every other kb command)",
    ),
    repo_id: str = typer.Option("", "--repo-id", help="Repo ID (default: config, then folder name)"),
    doc_id: str = typer.Option("", "--doc-id", help="Document ID (default: <repo_id>-code)"),
    db: list[Path] = typer.Option([], "--db", help="SQLite file to read (repeatable, explicit only)"),
    tags: str = typer.Option("", "--tags", help="Extra index tags, comma-separated"),
    scaffold_svc: bool = typer.Option(
        False, "--scaffold-svc",
        help="Also upsert the curated <repo_id>-svc scaffold (pending sections)",
    ),
    json_out: bool = typer.Option(False, "--json", help="Machine-readable report"),
) -> None:
    """Extract code structure into .kb/<repo_id>-code/ — deterministic, no LLM."""
    import dataclasses

    from strata_kb import config
    from strata_kb.codeingest import core

    resolved_root = repo_root.resolve()
    # Relative --kb-dir is cwd-relative, like every other kb command (G-11).
    resolved_kb_dir = kb_dir.resolve()

    # Ruling R4: effective_repo_id() returns None when neither --repo-id nor
    # .kb/config.yaml supplies one; the help text above promises a folder-
    # name fallback, so supply it here rather than writing a "None-code" doc.
    rid = config.effective_repo_id(repo_id, resolved_kb_dir) or resolved_root.name
    did = doc_id or f"{rid}-code"
    tag_list = tuple(t.strip() for t in tags.split(",") if t.strip())

    opts = core.CodeIngestOptions(
        repo_root=resolved_root,
        kb_dir=resolved_kb_dir,
        doc_id=did,
        repo_id=rid,
        db_paths=tuple(db),
        tags=tag_list,
        scaffold_svc=scaffold_svc,
    )

    try:
        report = core.run(opts)
    except core.CodeIngestError as exc:
        # Review round 3 (Important 5 follow-up): CodeIngestError now
        # carries whatever partial CodeIngestReport existed at the point
        # of failure, so a warning already collected before the refusal
        # (e.g. "could not read _manifest.yaml") is shown too, instead of
        # only this exception's own message — which, for a corrupt -svc
        # manifest, otherwise reads as "no matching entry in
        # _manifest.yaml — restore the manifest entries" with no hint
        # that the manifest is simply malformed. A non-empty
        # `files_written` also means the -code document was already
        # written and indexed before a later --scaffold-svc refusal — a
        # partial success, not a full failure — so that's called out too.
        # Review round 4: all three lines below now pass err=True (the
        # codebase's existing convention for diagnostics that must never
        # land on stdout — see e.g. the RED-secho'd errors elsewhere in
        # this file) so a --json invocation's stdout stays empty, never
        # polluted, on this path — matching the purity --json already
        # guarantees on the success path.
        if exc.report is not None:
            for warning in exc.report.warnings:
                typer.secho(f"[warn] {warning}", fg=typer.colors.YELLOW, err=True)
            if exc.report.files_written:
                typer.secho(
                    f"[note] {exc.report.doc_id}: {len(exc.report.files_written)} "
                    "file(s) were already written before this error — a "
                    "partial success, not a full failure",
                    fg=typer.colors.YELLOW,
                    err=True,
                )
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    if json_out:
        typer.echo(json.dumps(dataclasses.asdict(report), indent=2))
        return

    typer.echo(f"doc: {report.doc_id}")
    typer.echo(f"detected: {', '.join(report.detected)}")
    for name in sorted(report.sections_by_extractor):
        typer.echo(f"  {name}: {report.sections_by_extractor[name]} section(s)")
    typer.echo(f"files written: {len(report.files_written)}")
    if report.dirty_tree:
        typer.secho(
            "[warn] working tree has uncommitted changes — output reflects them",
            fg=typer.colors.YELLOW,
        )
    for warning in report.warnings:
        typer.secho(f"[warn] {warning}", fg=typer.colors.YELLOW)
    if scaffold_svc:
        typer.echo(
            f"scaffolded: {len(report.scaffolded)} new, "
            f"{len(report.stale_risk)} stale-risk, {len(report.orphans)} orphan(s)"
        )
        # Spec Sec8.3 asks for "stale-risk: svc.<name>" / "orphan: svc.<name>"
        # "in the report and in --json" -- --json already carries the ids
        # via report.stale_risk/report.orphans, but the terminal used to
        # print only counts. Stage C's machine consumer of --json does not
        # exist yet, so the terminal is the only surface a Dev has today
        # (task review, Important 5).
        for sid in report.stale_risk:
            typer.echo(f"  stale-risk: {sid}")
        for sid in report.orphans:
            typer.echo(f"  orphan: {sid}")


@svc_app.command("note")
def svc_note(
    service: str = typer.Argument(
        ..., help="Service name, as in svc.<name> of <repo_id>-code"
    ),
    ticket: str = typer.Option(..., "--ticket", help="Ticket / US id"),
    title: str = typer.Option(..., "--title", help="Ticket title"),
    refs: str = typer.Option("", "--refs", help="Domain refs, comma-separated"),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    repo_id: str = typer.Option("", "--repo-id", help="Repo ID (default: config)"),
    json_out: bool = typer.Option(False, "--json", help="Machine-readable report"),
) -> None:
    """Append a ticket to <repo_id>-svc §hist.<service>. Idempotent per ticket."""
    import dataclasses

    from strata_kb import config, svcnote

    # Ruling: effective_repo_id() returns None when neither --repo-id nor
    # .kb/config.yaml supplies one; surfaced the same way every other
    # SvcNoteError-shaped failure is (red message naming the fix, exit 1),
    # since add_note() itself takes a plain (non-optional) repo_id str.
    rid = config.effective_repo_id(repo_id, kb_dir)
    if rid is None:
        typer.secho(
            "no repo-id available — pass --repo-id or set repo_id in "
            f"{kb_dir}/config.yaml",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    ref_list = tuple(r.strip() for r in refs.split(",") if r.strip())
    note = svcnote.Note(ticket=ticket, title=title, refs=ref_list)

    try:
        report = svcnote.add_note(kb_dir, rid, service, note)
    except svcnote.SvcNoteError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)

    if json_out:
        typer.echo(json.dumps(dataclasses.asdict(report), indent=2))
        return

    typer.echo(f"doc: {report.doc_id}")
    typer.echo(f"section: {report.section_id} ({report.action})")
    typer.echo(f"notes: {report.notes}")


def _usage_actor(kb_dir: Path) -> str:
    """The row's actor is the repo's declared kind, never an agent's claim.

    An unset `kind:` reads as "unknown" rather than being guessed from the
    directory layout: a wrong actor silently mis-attributes a whole repo's
    cost to the other side of the workflow.
    """
    from strata_kb import config

    return config.load_config(kb_dir).kind or "unknown"


def _usage_log_error(kb_dir: Path, message: str) -> None:
    """Append one timestamped line to `.kb/usage/ingest-errors.log`.

    This is the ONLY diagnostic channel a silent `--hook-stdin` failure has:
    every error there is swallowed so a bad transcript, a mistyped `kind:`, or
    a corrupt ledger can never block a turn from ending. The write itself must
    never raise either — a broken log is not license to turn "log and move
    on" back into "crash the hook", so any failure here is swallowed too.
    """
    from datetime import datetime, timezone

    from strata_kb.usage import ledger as _ledger

    try:
        path = _ledger.usage_dir(kb_dir) / "ingest-errors.log"
        if not (kb_dir / "config.yaml").is_file():
            return  # wrong directory: nowhere correct to write (reviewer F L2)
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(f"{stamp} {message.rstrip()}\n")
    except Exception:  # noqa: BLE001, S110 -- deliberate: see docstring, this sink must never raise
        pass


def _usage_ingest(kb_dir: Path, source: Path, *, session: str, ticket: str):
    """Turn one transcript into ledger rows and append them.

    Shared by both `ingest-transcript` branches so hook and non-hook mode
    agree on exactly what "ingest" means; only how a failure is reported
    differs between them.
    """
    from strata_kb.usage import ledger, transcript

    rows = transcript.rows_from_transcript(
        source,
        actor=_usage_actor(kb_dir),
        session_fallback=session,
        forced_ticket=ticket or None,
    )
    return ledger.append_rows(kb_dir, rows)


@usage_app.command("ingest-transcript")
def usage_ingest_transcript(
    path: Path | None = typer.Argument(
        None, help="Claude Code transcript JSONL (omit with --hook-stdin)"
    ),
    hook_stdin: bool = typer.Option(
        False, "--hook-stdin", help="Read the hook payload (JSON) from stdin"
    ),
    ticket: str = typer.Option(
        "", "--ticket", help="Force this ticket id for every row in the file"
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    json_out: bool = typer.Option(False, "--json", help="Machine-readable report"),
) -> None:
    """Append this transcript's API calls to the usage ledger.

    Safe to repeat: rows are de-duplicated by the transcript row's uuid, which
    is what lets the `Stop` hook re-ingest the same growing file every turn.
    """
    from strata_kb.usage import ledger

    if hook_stdin:
        if not (kb_dir / "config.yaml").exists():
            # A `.kb` with no config.yaml is strong evidence this is the
            # wrong directory: `kb init` always creates one, so no
            # legitimate case is lost. Without this, a session started in a
            # subdirectory that never got its own `.kb` silently creates a
            # ghost ledger there, while `kb usage report` at the real repo
            # root says "no usage recorded yet" — ONLY hook mode is guarded
            # this way; an explicit --kb-dir from a human is a deliberate
            # choice and is left alone.
            _usage_log_error(
                kb_dir,
                f"hook mode skipped — no {kb_dir / 'config.yaml'} (wrong "
                "working directory for this session?)",
            )
            return
        # ALWAYS exit 0 here, unconditionally: a Stop hook exiting non-zero
        # blocks Claude from ending its turn, so NOTHING in this branch may
        # propagate — a malformed payload, an invalid `kind:`, a corrupt
        # ledger, a missing transcript, anything. `except Exception`, not a
        # narrow tuple, is deliberate: the failure modes this must absorb
        # come from several modules this command does not own, and a list of
        # "the exceptions we thought of" is exactly the list a new one falls
        # through.
        raw = sys.stdin.read()
        try:
            payload = json.loads(raw)
            source = Path(payload["transcript_path"])
            session = str(payload.get("session_id") or "")
            if path is not None:
                _usage_log_error(
                    kb_dir, "both a path and --hook-stdin were given; used the payload"
                )
            _usage_ingest(kb_dir, source, session=session, ticket=ticket)
        except Exception as exc:  # noqa: BLE001 -- deliberate: see comment above, must absorb every failure mode
            # The exception's class name is part of the message, not just
            # str(exc): "Expecting value: line 1 column 1" alone does not say
            # this was a JSON parse failure, and this log is the only place a
            # human ever sees the difference between a bad payload, an
            # invalid `.kb/config.yaml`, and a corrupt ledger. The raw
            # payload snippet (bounded to 200 chars) is what tells apart a
            # genuinely empty stdin, garbage stdin, and stdin clobbered by
            # something upstream — all three raise the identical
            # JSONDecodeError and would otherwise log identically apart from
            # the timestamp.
            _usage_log_error(
                kb_dir,
                f"ingest-transcript (hook) failed: {type(exc).__name__}: {exc}: "
                f"{raw[:200]}",
            )
        return  # silent either way: the hook's stdout would land in the session

    if path is None:
        # Written to stdout, not stderr, matching svc_note's failure style.
        # The suite's CliRunner reads `result.output`, and whether that
        # includes stderr varies with the Click version — a message the test
        # cannot see is a message that stops being checked.
        typer.secho(
            "pass exactly one of a transcript path or --hook-stdin",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    try:
        report = _usage_ingest(kb_dir, path, session="", ticket=ticket)
    except (OSError, ledger.LedgerError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)

    if json_out:
        typer.echo(
            json.dumps(
                {
                    "written": report.written,
                    "duplicates": report.duplicates,
                    "files": report.files,
                }
            )
        )
    else:
        typer.echo(
            f"{report.written} new row(s), {report.duplicates} already recorded"
            + (f" -> {', '.join(report.files)}" if report.files else "")
        )
        if ticket and report.written == 0 and report.duplicates > 0:
            # Global uuid dedup (invariant I2) + forced_ticket compose into a
            # dead escape hatch: once a transcript has already been ingested
            # (e.g. by the Stop hook), every row's uuid is already stored, so
            # --ticket can never move one — "0 new row(s), N already
            # recorded" plus exit 0 reads as success otherwise. `kb usage
            # note` is NOT the fix: it appends a new row, so using it to
            # "correct" an existing one double-counts the tokens. The only
            # real repair is hand-editing the stored row.
            typer.secho(
                f"--ticket was given, but all {report.duplicates} row(s) here "
                "are already recorded — --ticket cannot move a row that is "
                "already in the ledger. To move one, edit its "
                ".kb/usage/*.jsonl file by hand, then re-run `kb usage report`.",
                fg=typer.colors.YELLOW,
            )


@usage_app.command("note")
def usage_note(
    ticket: str = typer.Option(..., "--ticket", help="Ticket / mission id"),
    phase: str = typer.Option(..., "--phase", help="Workflow phase, e.g. dev-plan"),
    model: str = typer.Option(..., "--model", help="Model id"),
    tokens_in: int = typer.Option(..., "--tokens-in", min=0),
    tokens_out: int = typer.Option(..., "--tokens-out", min=0),
    cache_read: int = typer.Option(0, "--cache-read", min=0),
    cache_write_1h: int = typer.Option(0, "--cache-write-1h", min=0),
    cache_write_5m: int = typer.Option(0, "--cache-write-5m", min=0),
    est: bool = typer.Option(
        True, "--est/--measured",
        help="A hand-entered row is a self-reported estimate (default); "
        "--measured marks a figure read from the assistant's own meter",
    ),
    assistant: str = typer.Option(
        ..., "--assistant", help="Which assistant made the calls, e.g. copilot, cursor"
    ),
    session: str = typer.Option("", "--session"),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
) -> None:
    """Append one usage row by hand — for an assistant with no hook, or to
    repair an attribution the cursor got wrong."""
    import uuid as _uuid
    from datetime import datetime, timezone

    from strata_kb.usage import ledger

    row = ledger.UsageRow(
        uuid=str(_uuid.uuid4()),
        ts=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        session=session,
        actor=_usage_actor(kb_dir),
        phase=phase,
        ticket=ticket,
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cache_read=cache_read,
        cache_write_5m=cache_write_5m,
        cache_write_1h=cache_write_1h,
        sidechain=False,
        branch=None,
        assistant=assistant,
        est=est,
    )
    try:
        report = ledger.append_rows(kb_dir, [row])
    except ledger.LedgerError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.echo(f"recorded -> {', '.join(report.files)}")


@usage_app.command("report")
def usage_report(
    ticket: str = typer.Option("", "--ticket", help="Only this ticket"),
    md: bool = typer.Option(False, "--md", help="Print Markdown to stdout"),
    json_out: bool = typer.Option(False, "--json", help="Print JSON to stdout"),
    out: Path | None = typer.Option(
        None, "--out", help="HTML output path (default: <kb-dir>/usage/report.html)"
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
) -> None:
    """Aggregate the usage ledger: per ticket, phase, model, actor."""
    from datetime import date, datetime, timezone

    from pydantic import ValidationError

    from strata_kb.usage import ledger, prices, report as report_mod

    try:
        rows = ledger.read_rows(kb_dir)
    except (ledger.LedgerError, ValidationError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    if ticket:
        rows = [r for r in rows if r.ticket == ticket]
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    hook_error_count, _ = ledger.hook_errors(kb_dir)
    if not rows:
        if json_out:
            # --json is the machine surface a PR/CI step consumes, and it
            # must stay parseable even in the state every repo starts in —
            # before its first ingest. The human-facing guidance below is
            # prose on purpose and is not a substitute here.
            typer.echo(
                report_mod.Aggregate(
                    generated=generated, hook_errors=hook_error_count
                ).model_dump_json(indent=2)
            )
            return
        note = (
            f"; {hook_error_count} hook ingest error(s) logged in "
            ".kb/usage/ingest-errors.log"
            if hook_error_count
            else ""
        )
        typer.echo(
            "no usage recorded yet — run `kb usage ingest-transcript <path>` on a "
            f"Claude Code transcript, or check that the Stop hook is wired{note}"
        )
        return
    agg = report_mod.aggregate(
        rows,
        prices.load_prices(kb_dir),
        today=date.today(),
        generated=generated,
    )
    agg.hook_errors = hook_error_count
    if md:
        typer.echo(report_mod.render_markdown(agg))
        return
    if json_out:
        typer.echo(agg.model_dump_json(indent=2))
        return
    target = out or (ledger.usage_dir(kb_dir) / "report.html")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report_mod.render_html(agg), encoding="utf-8", newline="\n")
    typer.echo(f"wrote {target}")


@app.command()
def query(
    text: str = typer.Argument(..., help="Query text"),
    tags: str = typer.Option("", help="Tags to filter docs by, comma-separated"),
    budget: int = typer.Option(2000, help="Token budget for returned content"),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    hub: str = typer.Option(
        "", "--hub", envvar="STRATA_KB_HUB", help="kb-hub URL/path (empty = config)"
    ),
    semantic: bool = typer.Option(
        False,
        "--semantic",
        help="Warn when embeddings are unavailable (hybrid runs both legs automatically)",
    ),
) -> None:
    """Hybrid search (FTS5 keyword + semantic KNN, RRF-fused) → L2 sections within budget, with citations."""
    import sqlite3

    from strata_kb import searchdb
    from strata_kb.query import search_detailed

    handle = _hub_or_exit(hub, kb_dir)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] or None
    try:
        outcome = search_detailed(
            handle, text, tags=tag_list, budget=budget, semantic=semantic
        )
    except searchdb.IndexBusyError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    except sqlite3.DatabaseError as exc:
        if searchdb.classify_db_error(exc) != "client":
            raise
        typer.secho(f"search index rejected the query: {exc}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except searchdb.TooManyTagsError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    for note in outcome.notes:
        typer.secho(note.strip(), fg=typer.colors.YELLOW, err=True)
    results = outcome.results
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
        "", "--hub", envvar="STRATA_KB_HUB", help="kb-hub URL/path (empty = config)"
    ),
) -> None:
    """Fetch exactly one section at the given level."""
    from strata_kb.query import AmbiguousDocError, InvalidLevelError, get_section

    handle = _hub_or_exit(hub, kb_dir)
    try:
        result = get_section(handle, doc_id, section, level=level, repo=repo or None)
    except InvalidLevelError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
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
    from strata_kb.build import kb_stats

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
    if all(d.l2_tokens == 0 and d.l3_tokens == 0 for d in docs):
        typer.echo("run kb build to refresh token counts")


def _apply_unreviewed_gate(gate) -> None:
    """Echo `publish_mod.unreviewed_gate`'s line (if any) and exit(1) when
    it blocks — shared by `publish` and `ci_publish` (R18)."""
    if gate.line is None:
        return
    typer.secho(gate.line, fg=typer.colors.RED if gate.blocked else typer.colors.YELLOW)
    if gate.blocked:
        raise typer.Exit(1)


def _echo_publish_report(report) -> None:
    if getattr(report, "skipped", None):
        typer.secho(
            f"[warn] {len(report.skipped)} file(s) under .kb/ were not published "
            f"(allowlist): {', '.join(report.skipped)}",
            fg=typer.colors.YELLOW,
        )
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
    if report.pushed:
        action = "push"
    elif getattr(report, "remote", False):
        action = "commit only (nothing to push)"
    else:
        action = "commit only (hub has no remote)"
    typer.echo(
        f"kb publish: {report.repo_id} @ {report.source_commit} — "
        f"{report.n_docs} doc, {action}."
    )


@app.command()
def publish(
    hub: str = typer.Option(
        "", "--hub", envvar="STRATA_KB_HUB",
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
    require_reviewed: bool = typer.Option(
        False,
        "--require-reviewed",
        help="Fail when any section other than machine-authored `hist.*` is not reviewed",
    ),
) -> None:
    """Mirror .kb/ (L0→L3) to the hub's federation/<repo-id>/ + rebuild the index."""
    from strata_kb import ghio, gitio, hashsync
    from strata_kb import publish as publish_mod
    from strata_kb.config import HubConfigError, effective_repo_id, load_config, require_hub
    from strata_kb.errors import KbError

    # module-level _CONFIG_READ_ERRORS (see its definition for why exactly
    # these three classes) covers every corrupt-YAML/schema-invalid/non-UTF-8
    # .kb file this command can meet (F-D9 finding 2): reused at every point
    # this function reads a .kb/*.yaml or federation/*.yaml file outside a
    # call that already wraps its own read.

    if pr and direct:
        typer.secho("--pr and --direct are mutually exclusive", fg=typer.colors.RED)
        raise typer.Exit(1)

    try:
        cfg = load_config(kb_dir)
    except (*_CONFIG_READ_ERRORS, OSError) as exc:
        typer.secho(
            f"{kb_dir / 'config.yaml'} is unreadable ({exc}) -- fix the file, "
            "or remove it to fall back to defaults",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    mode = "pr" if pr else "direct" if direct else "auto"
    is_self = False  # only ever True for cfg.kind == "hub" self-publish fall-through
    if cfg.kind == "hub":
        try:
            hub_ref = require_hub(hub, kb_dir)
        except HubConfigError:
            typer.secho(
                "this is a root hub (kind: hub, no `hub:` configured) — nothing "
                "to publish upstream; add `hub: <url|path>` to .kb/config.yaml "
                "to chain it to a higher hub",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)
        # A relative `hub:` (e.g. the `hub: .` that `kb init --kind hub`
        # ships) must anchor to the repo root, not the process cwd — the
        # same config would otherwise route differently depending on where
        # `kb publish` happens to be invoked from, and could even mirror
        # into an unrelated sibling repo that also has a `.kb/`.
        source_root = None
        try:
            source_root = gitio.git_root(kb_dir.resolve())
        except gitio.GitError:
            pass
        hub_path = Path(hub_ref)
        if source_root is not None and not hub_path.is_absolute():
            hub_path = source_root / hub_ref
        is_self = False
        if source_root is not None and hub_path.is_dir():
            is_self = hub_path.resolve() == source_root
        if is_self:
            # fall-through below must not re-resolve hub_ref cwd-relatively
            hub_ref = str(source_root)
        if not is_self:
            if cfg.intake and not pr and not direct:
                typer.secho(
                    "intake publish is not supported for hub-to-hub publish — "
                    "remove `intake:` from .kb/config.yaml or pass --direct/--pr",
                    fg=typer.colors.RED,
                )
                raise typer.Exit(1)
            try:
                report = publish_mod.publish_federation(
                    kb_dir, hub_ref,
                    repo_id=effective_repo_id(repo_id, kb_dir), mode=mode,
                )
            except (
                # KbError: PublishError (publish_federation's own YAML reads --
                # registry.yaml, the upstream hub's config.yaml for the cycle
                # guard -- are already caught internally and re-raised as
                # PublishError) and GateError, plus assetstore.AssetStoreError --
                # _snapshot_federation (this call's snapshot_fn) resolves this
                # hub's own store and diverts still-raw bytes into it
                # (_reconcile_asset_records, F-D11/Task 21), so a store outage
                # is reachable on this branch too, not only on plain-publish's.
                # Catching the base once means a future KbError sibling, or a
                # new call site for an existing one, is covered without a
                # fourth name added here.
                KbError,
                gitio.GitError, ghio.GHError, OSError,
                # hashsync.HashSyncError: _snapshot_federation's apply_sync
                # guards every write against escaping federation/<rid> on the
                # upper hub -- reachable here (fed->fed).
                hashsync.HashSyncError,
            ) as exc:
                typer.secho(str(exc), fg=typer.colors.RED)
                raise typer.Exit(1)
            _echo_publish_report(report)
            return
        # is_self: fall through — a hub pointing at itself publishes its own
        # .kb/ into its own federation/<repo-id>/ (self-publish, spec #7)

    # Gate applies only to paths that actually publish .kb/ (self-publish
    # fall-through, intake, plain publish) — the hub-to-hub `not is_self`
    # federation branch above already returned without reaching here, since
    # publish_federation() pushes federation/ only; the hub's own .kb/ there
    # is a drafting desk, not what gets published. Still strictly above
    # require_hub()/resolve_hub()/any write below.
    try:
        _apply_unreviewed_gate(publish_mod.unreviewed_gate(kb_dir, require_reviewed))
    except (*_CONFIG_READ_ERRORS, OSError, KbError) as exc:
        # KbError: unreviewed_gate -> unreviewed_sections reads every doc's
        # _manifest.yaml via publish._load_manifest_or_raise, which converts
        # a corrupt/schema-invalid/non-UTF-8 file into PublishError (a
        # KbError) rather than letting the raw yaml/pydantic exception
        # through -- so this guard must catch the wrapper, not just the
        # classes _load_manifest_or_raise wraps (this was the round-1
        # regression: the wrap shipped, this arm did not follow it, and the
        # message right below stopped being reachable).
        typer.secho(
            f"a _manifest.yaml under {kb_dir} is unreadable ({exc}) -- fix or "
            "re-ingest that document",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    if cfg.intake and not pr and not direct:
        try:
            pr_url = publish_mod.publish_via_intake(
                kb_dir, cfg.intake, effective_repo_id(repo_id, kb_dir)
            )
        except (
            # KbError: PublishError, GateError.
            KbError,
            gitio.GitError, OSError,
            # ValueError: publish_via_intake polls the intake server's /intake/
            # status endpoint and parses its JSON body unwrapped
            # (publish.py's _default_get_json) -- a malformed 200 response
            # raises json.JSONDecodeError, a ValueError subclass.
            ValueError,
        ) as exc:
            typer.secho(str(exc), fg=typer.colors.RED)
            raise typer.Exit(1)
        if pr_url:
            typer.echo(f"kb publish: PR on the hub — {pr_url}")
            typer.echo("Content goes live when the PR is merged on the hub.")
        else:
            typer.echo("kb publish: done (no PR URL reported).")
        return

    try:
        # A hub-kind self-publish already resolved+anchored hub_ref above
        # (git-root-anchored, not cwd-relative) — re-deriving it here via
        # require_hub() would re-resolve a relative `hub: .` against the
        # process cwd and undo that anchoring.
        if not is_self:
            hub_ref = require_hub(hub, kb_dir)
        report = publish_mod.publish(
            kb_dir, hub_ref,
            repo_id=effective_repo_id(repo_id, kb_dir), mode=mode,
            self_publish=is_self,
        )
    except (
        # KbError: PublishError, GateError, and assetstore.AssetStoreError --
        # _snapshot (the .kb/ -> federation/<rid> path this call takes) can
        # raise all three: PublishError from its own index.yaml/hub-config
        # reads (wrapped, same shape as finding 2's measured repro),
        # AssetStoreError from divert_and_record on a store outage. Catching
        # the base once, instead of naming each class, means this tuple
        # cannot go stale the way it did before: AssetStoreError used to be
        # listed explicitly here and the hub-to-hub tuple above did not list
        # it at all, even after _snapshot_federation (that branch's own
        # snapshot_fn) started touching the asset store too (3845ee5/
        # 01cbd0a) -- both branches now catch the same base.
        HubConfigError, KbError, gitio.GitError, ghio.GHError, OSError,
        *_CONFIG_READ_ERRORS,
        hashsync.HashSyncError,
    ) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    _echo_publish_report(report)


@app.command(name="ci-publish")
def ci_publish(
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    repo_id: str = typer.Option("", "--repo-id", help="Repo ID on the hub (default: config)"),
    intake: str = typer.Option(
        "", "--intake", envvar="STRATA_KB_INTAKE",
        help="Intake base URL (default: .kb/config.yaml `intake:`)",
    ),
    require_reviewed: bool = typer.Option(
        False,
        "--require-reviewed",
        help="Fail when any section other than machine-authored `hist.*` is not reviewed",
    ),
) -> None:
    """Publish from the child's CI via OIDC — no secrets. Run by kb-publish.yml."""
    from strata_kb import cipublish, gitio
    from strata_kb.config import effective_repo_id, load_config
    from strata_kb.errors import KbError

    # See module-level _CONFIG_READ_ERRORS: same three classes, same reason
    # (yaml.YAMLError is not a ValueError; UnicodeDecodeError/ValidationError
    # both are, but stay explicit).

    try:
        url = intake or load_config(kb_dir).intake
    except (*_CONFIG_READ_ERRORS, OSError) as exc:
        typer.secho(
            f"{kb_dir / 'config.yaml'} is unreadable ({exc}) -- fix the file, "
            "or pass --intake to skip reading it",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    if not url:
        typer.secho(
            "no intake URL — add `intake: <url>` to .kb/config.yaml or pass --intake",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    try:
        cipublish.run(
            kb_dir, url, effective_repo_id(repo_id, kb_dir), require_reviewed=require_reviewed
        )
    except (
        # KbError: CIPublishError (this command's own token/upload failures)
        # and PublishError -- cipublish.run's own unreviewed-gate check
        # (_check_unreviewed_gate -> publish.unreviewed_gate ->
        # unreviewed_sections) reads every doc's _manifest.yaml through
        # publish._load_manifest_or_raise, which converts a corrupt/
        # schema-invalid/non-UTF-8 file into PublishError, NOT a raw
        # yaml/pydantic exception -- it does not land in the ValueError-
        # family classes below (that claim was true before this round
        # wrapped the read, and stale once it did: PublishError is a
        # RuntimeError, not a ValueError, so it escaped uncaught until this
        # arm named the base it belongs to). The OIDC token/publish-response
        # JSON parsing (json.loads, in _request_oidc_token/run) IS still
        # unwrapped and does land in _CONFIG_READ_ERRORS below
        # (json.JSONDecodeError is a ValueError subclass).
        KbError,
        gitio.GitError, OSError,
        *_CONFIG_READ_ERRORS,
    ) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)


@app.command()
def reindex(
    hub: str = typer.Option(
        "", "--hub", envvar="STRATA_KB_HUB",
        help="kb-hub URL/path (default: .kb/config.yaml)",
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory (to find the config)"),
    force: bool = typer.Option(
        False, "--force",
        help="Drop the search index and rebuild it from scratch",
    ),
) -> None:
    """Rebuild federation/index.yaml from the sub-snapshots (fix a drifted index)."""
    import sqlite3

    from strata_kb import gitio, searchdb
    from strata_kb.embed import default_embedder
    from strata_kb.federation import write_federation_index

    # See module-level _CONFIG_READ_ERRORS.

    try:
        handle = _hub_or_exit(hub, kb_dir)
        write_federation_index(handle.federation_dir)
        # commit index.yaml BEFORE syncing the search index: the strict sync can
        # blow up (embed failure) — the rebuilt index must not be left uncommitted
        #
        # Scope the commit the way _publish_direct already does. Committing all of
        # federation/ under a message that says "rebuild index" swept in
        # hand-edited content and untracked directories -- and publish's own
        # error paths leave exactly that behind.
        #
        # -c core.quotePath=false (finding 7): without it, porcelain C-quotes
        # any non-ASCII path (e.g. "federation/ghi-ch\303\272.md") instead of
        # printing it as UTF-8.
        # --untracked-files=all (finding 7): without it, an entirely-untracked
        # federation/ (first-ever reindex, nothing under it committed yet)
        # collapses to one "?? federation/" line -- the strays check below
        # then flags the whole directory even though committing
        # federation/index.yaml right after this was exactly correct.
        dirty_before = gitio._run(
            handle.root, "-c", "core.quotePath=false",
            "status", "--porcelain", "--untracked-files=all", "--", "federation"
        ).stdout.splitlines()
        committed = gitio.commit_paths(
            handle.root, "reindex: rebuild federation/index.yaml", ["federation/index.yaml"]
        )
    except gitio.GitError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    except _CONFIG_READ_ERRORS as exc:
        # write_federation_index -> build_federation_index -> load_federation
        # already skips (warns, does not raise) any entry whose _meta.yaml/
        # index.yaml is corrupt YAML or schema-invalid -- this is belt and
        # suspenders for that aggregation path, not a currently-open hole.
        typer.secho(
            f"a federation/ entry is unreadable while rebuilding the index "
            f"({exc}) -- fix or re-publish that entry",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    except OSError as exc:
        # I5: str(OSError) alone ("[Errno 13] Permission denied: '...'") names
        # no way forward -- add one.
        typer.secho(
            f"reindex failed ({exc}) -- check file permissions under the hub "
            "and retry",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    strays = sorted(
        line[3:].strip()
        for line in dirty_before
        if line[3:].strip() not in ("federation/index.yaml",)
    )
    if strays:
        typer.secho(
            "[warn] uncommitted content under federation/ was NOT committed by "
            f"reindex: {', '.join(strays)}",
            fg=typer.colors.YELLOW,
        )
    try:
        if force:
            searchdb.delete_db(handle)
            typer.echo("kb reindex: search index dropped — rebuilding from scratch")
        sreport = searchdb.sync(handle, default_embedder())
    except searchdb.IndexBusyError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    except sqlite3.DatabaseError as exc:
        if searchdb.classify_db_error(exc) != "client":
            raise
        typer.secho(f"search index rejected the reindex: {exc}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except _CONFIG_READ_ERRORS as exc:
        # searchdb._sync_repo reads every referenced doc's _manifest.yaml
        # unwrapped (unlike load_federation, it does not skip a broken one --
        # it is building content for the index, not enumerating entries).
        typer.secho(
            f"a _manifest.yaml is unreadable while syncing the search index "
            f"({exc}) -- fix or re-ingest that document",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    except OSError as exc:
        # F-D9 CRITICAL, routed: this try's sibling arm above (the
        # write_federation_index/commit_paths block) already has an OSError
        # arm -- this one, guarding searchdb.sync, was added later and
        # missed it. A locked file under the hub (e.g. .kb-work/search.sqlite3
        # held open by another kb process) raised PermissionError with no
        # arm to catch it here -- reindex is one of the three commands the
        # spec names by name for "no traceback reaches a user".
        typer.secho(
            f"reindex failed while syncing the search index ({exc}) -- check "
            "file permissions under the hub and retry",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    typer.echo(
        f"kb reindex: search index — {sreport.sections_updated} updated, "
        f"{sreport.sections_deleted} removed, {sreport.embedded} embedded"
    )
    if not committed:
        typer.echo("kb reindex: index already consistent — nothing to do")
        return
    if gitio.has_remote(handle.root):
        try:
            gitio.push(handle.root, handle.token)
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
        "", "--hub", envvar="STRATA_KB_HUB", help="kb-hub URL/path (empty = config)"
    ),
) -> None:
    """Move in-git federation assets to the configured object store (none → s3)."""
    from strata_kb import assetcmd, assetstore

    handle = _hub_or_exit(hub, kb_dir)
    try:
        report = assetcmd.migrate_assets(handle)
    except (assetcmd.AssetCmdError, assetstore.AssetStoreError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    for rid, n in sorted(report.per_rid.items()):
        typer.echo(f"  {rid}: {n} asset(s) migrated")
    if report.skipped:
        names = ", ".join(report.skipped)
        typer.secho(
            f"skipped (missing _meta.yaml or index.yaml), not migrated: {names} -- "
            "run `kb doctor` for details, then republish from the source repo to "
            "restore the missing marker",
            fg=typer.colors.YELLOW,
        )
    if not report.per_rid:
        if report.skipped:
            # P53 (item 3, wave L1 brief): "nothing to migrate" is an
            # all-clear a script may read at exit 0 -- printing it here
            # would be false, since the entries above were found and
            # skipped, not swept. A skip is not itself a migrate failure
            # (the entry's markers are broken upstream, not this run), but
            # the run could not confirm federation/ is clean, so it must
            # not report clean: exit non-zero with the skip named above.
            typer.echo("nothing migrated -- entries were skipped (see above)")
            raise typer.Exit(1)
        typer.echo("nothing to migrate — no in-git assets under federation/")
    elif report.committed:
        typer.echo("committed: assets: migrate to object store")
        typer.echo("(commit is local — push to publish if the hub has a remote)")


@assets_app.command()
def verify(
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    hub: str = typer.Option(
        "", "--hub", envvar="STRATA_KB_HUB", help="kb-hub URL/path (empty = config)"
    ),
) -> None:
    """Check asset coverage: records vs store, markdown refs, orphans."""
    from strata_kb import assetcmd, assetstore

    handle = _hub_or_exit(hub, kb_dir)
    try:
        report = assetcmd.verify_assets(handle)
    except (assetcmd.AssetCmdError, assetstore.AssetStoreError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    for label in report.missing_records:
        typer.secho(f"[missing] recorded but not in store: {label}", fg=typer.colors.RED)
    for label in report.corrupt:
        typer.secho(
            f"[corrupt] bytes on disk/in the store do not hash to their own "
            f"content-addressed name: {label}",
            fg=typer.colors.RED,
        )
    for label in report.dangling_refs:
        typer.secho(f"[dangling] referenced but unresolvable: {label}", fg=typer.colors.RED)
    for label in report.broken_links:
        typer.secho(f"[broken] {label}", fg=typer.colors.RED)
    for label in report.orphans:
        typer.echo(f"[orphan] recorded but never referenced: {label}")
    if not report.ok:
        raise typer.Exit(1)
    typer.echo("kb assets verify: OK")


@context_app.command("new")
def context_new(
    refs: str = typer.Option(
        ..., "--refs", help="Comma-separated refs, e.g. 'hr-handbook §4.12,travel-policy §2.1'"
    ),
    tags: str = typer.Option("", help="Tags, comma-separated"),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    hub: str = typer.Option(
        "", "--hub", envvar="STRATA_KB_HUB", help="kb-hub URL/path (empty = config)"
    ),
) -> None:
    """Generate a kb-context block pinned at HEAD — paste into a Jira ticket."""
    from strata_kb import gitio, kbcontext

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
def tags(
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    hub: str = typer.Option(
        "", "--hub", envvar="STRATA_KB_HUB", help="kb-hub URL/path (empty = config)"
    ),
) -> None:
    """List every tag published on the hub federation — the vocabulary a
    kb-context block may use."""
    from strata_kb import kbcontext
    from strata_kb.federation import load_federation

    handle = _hub_or_exit(hub, kb_dir)
    vocab = kbcontext.tag_vocabulary(load_federation(handle.federation_dir))
    if not vocab:
        # An empty vocabulary is a valid state, not a failure: a KB whose
        # documents were ingested without --tags simply has none yet.
        typer.echo(
            "no tags published on the hub yet — ingest with `kb ingest --tags` "
            "to create some"
        )
        return
    for key in sorted(vocab):
        typer.echo(vocab[key])


@app.command()
def resolve(
    source: str = typer.Argument(
        ..., help="File containing the kb-context block (or '-' to read from stdin)"
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    hub: str = typer.Option(
        "", "--hub", envvar="STRATA_KB_HUB", help="kb-hub URL/path (empty = config)"
    ),
    status_only: bool = typer.Option(
        False,
        "--status-only",
        help="Print only the citation + freshness verdict per ref, no "
        "section content — for cheap re-checks against a context cache.",
    ),
    write_cache: Path | None = typer.Option(
        None,
        "--write-cache",
        help="Also write docs/impl/<ticket-id>-context.md: header (version, "
        "refs, sha256) + the resolved sections; everything below the "
        "`<!-- kb:placeholder-map -->` marker is kept from the existing file.",
    ),
    cache: Path | None = typer.Option(
        None,
        "--cache",
        help="With --status-only: validate this context cache against the "
        "ticket (version, ref set, sha256 of the resolved block); a bad or "
        "missing cache exits 1.",
    ),
) -> None:
    """Resolve a kb-context block: return sections at the pinned version + freshness."""
    from strata_kb import gitio, kbcontext
    from strata_kb.resolve import render_resolved, resolve_refs, render_cache, cache_problem

    if write_cache is not None and status_only:
        typer.secho("--write-cache needs a full resolve; drop --status-only", fg=typer.colors.RED)
        raise typer.Exit(1)
    if cache is not None and not status_only:
        typer.secho("--cache only makes sense with --status-only", fg=typer.colors.RED)
        raise typer.Exit(1)
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
    typer.echo(render_resolved(results, include_content=not status_only))
    if write_cache is not None:
        from datetime import date

        stem = write_cache.stem.removesuffix("-context")
        try:
            previous = (
                write_cache.read_text(encoding="utf-8") if write_cache.exists() else None
            )
            write_cache.parent.mkdir(parents=True, exist_ok=True)
            write_cache.write_text(
                render_cache(ctx.version, results, today=date.today().isoformat(),
                             stem=stem, previous=previous),
                encoding="utf-8", newline="\n",
            )
        except (OSError, UnicodeDecodeError) as exc:
            typer.secho(f"could not write cache '{write_cache}': {exc}", fg=typer.colors.RED)
            raise typer.Exit(1)
    cache_bad = False
    if cache is not None:
        if not cache.is_file():
            typer.echo(f"!! cache-missing: {cache}")
            cache_bad = True
        else:
            try:
                cache_text = cache.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                cache_text = ""
            problem = cache_problem(cache_text, ctx.version, results) if cache_text else "header"
            if problem:
                typer.echo(f"!! cache-invalid: {problem}")
                cache_bad = True
    if cache_bad or any(r.status == "broken" for r in results):
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
        "", "--hub", envvar="STRATA_KB_HUB", help="kb-hub URL/path (empty = config)"
    ),
    missions_dir: Path | None = typer.Option(
        None,
        "--missions-dir",
        help="Where mission files live (default: the ticket file's sibling "
        "'missions/' directory)",
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit the report as JSON instead of text"
    ),
    fail_on_stale: bool = typer.Option(
        False,
        "--fail-on-stale",
        help="Treat a stale ref (the cited content changed upstream since "
        "the pinned commit) as an error; exit 2 when that is the only "
        "failure, mirroring `kb resolve`",
    ),
) -> None:
    """Definition-of-Ready gate: lint a ticket against the DoR checklist."""
    from strata_kb.ticketlint import lint

    path: Path | None = None
    if source == "-":
        text = sys.stdin.read()
    else:
        path = Path(source)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            typer.secho(
                f"file '{source}' is not valid UTF-8: {exc}", fg=typer.colors.RED
            )
            raise typer.Exit(1)
        except OSError as exc:
            typer.secho(f"could not read file '{source}': {exc}", fg=typer.colors.RED)
            raise typer.Exit(1)

    # An explicitly-passed --missions-dir is a deliberate BA choice, so a
    # typo must be a hard error — otherwise check_parent_mission's
    # .is_file() probing quietly reports "mission file not found" for a
    # mission that actually exists, misdiagnosing a bad path as a missing
    # mission. The sibling default below stays fail-soft: its absence
    # degrades to the engine's note, it never becomes an error.
    if missions_dir is not None and not missions_dir.is_dir():
        typer.secho(
            f"--missions-dir '{missions_dir}' does not exist or is not a "
            "directory",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    # A ticket at tickets/<id>.md has missions/ as its sibling, so the
    # back-link check works with no flag in the layout kb init scaffolds.
    # Gate on the parent directory's name so the default only ever binds to
    # the sibling of an actual tickets/ directory — not some unrelated
    # missions/ that happens to sit next to wherever the ticket file was
    # opened from (mirrors mission_lint's tickets-dir sibling guard).
    resolved_missions = missions_dir
    if (
        resolved_missions is None
        and path is not None
        and path.parent.name == "tickets"
    ):
        sibling = path.parent.parent / "missions"
        if sibling.is_dir():
            resolved_missions = sibling

    handle = _hub_or_exit(hub, kb_dir)
    report = lint(
        text,
        handle,
        path=path,
        missions_dir=resolved_missions,
        fail_on_stale=fail_on_stale,
    )
    if json_output:
        typer.echo(json.dumps(report.to_json()))
    else:
        typer.echo(report.render())
    if report.passed:
        return
    errors = sum(1 for i in report.issues if i.level == "error")
    # Mirror `kb resolve`: 2 means "everything resolves, but the cited
    # content moved", which a caller may want to treat differently from a
    # ticket that is simply not ready.
    raise typer.Exit(2 if report.stale_errors == errors else 1)


@ticket_app.command("check")
def ticket_check(
    source: str = typer.Argument(
        ..., help="Ticket file (or '-' to read from stdin)"
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    hub: str = typer.Option(
        "",
        "--hub",
        envvar="STRATA_KB_HUB",
        help="kb-hub URL/path (empty = config); consulted only when the "
        "-code document is not under --kb-dir",
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit the report as JSON instead of text"
    ),
) -> None:
    """SA grounding gate: every id in '## Technical grounding' exists in the
    -code document, columns/routes/commands/files match it, and Open
    decisions is empty. Exit 0 PASS, 1 FAIL."""
    from strata_kb import ticketcheck

    if source == "-":
        text = sys.stdin.read()
    else:
        try:
            text = Path(source).read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            typer.secho(
                f"file '{source}' is not valid UTF-8: {exc}", fg=typer.colors.RED
            )
            raise typer.Exit(1)
        except OSError as exc:
            typer.secho(f"could not read file '{source}': {exc}", fg=typer.colors.RED)
            raise typer.Exit(1)

    def load_doc(repo: str | None, doc: str) -> ticketcheck.LoadedDoc | None:
        # Local first (a dev machine, or the hub's own checkout): the BA repo
        # never has a -code document locally, so it always falls through to
        # the hub — which is the point, the SA grounded on the hub copy.
        local = kb_dir / doc
        if (local / "_manifest.yaml").exists():
            return ticketcheck.load_doc_dir(local, str(local))
        handle = _hub_or_exit(hub, kb_dir)
        return ticketcheck.load_from_hub(handle.federation_dir, repo, doc)

    report = ticketcheck.check(text, load_doc=load_doc)
    if json_output:
        typer.echo(json.dumps(report.to_json()))
    else:
        typer.echo(report.render("Grounding"))
    if not report.passed:
        raise typer.Exit(1)


@pr_app.command("lint")
def pr_lint(
    source: str = typer.Argument(
        ..., help="File holding the PR description (or '-' to read from stdin)"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit the report as JSON instead of text"
    ),
    plan_dir: Path = typer.Option(
        Path("docs/impl"),
        "--plan-dir",
        help="Where docs/impl/<ticket-id>-plan.md lives; its `cmd.test:` line "
        "must appear inside a Verification fence. Absent plan = warning.",
    ),
) -> None:
    """Gate: every required PR section is present and actually filled in.

    Takes a file or stdin and never a string option: a PR description is
    attacker-controlled text, and keeping it out of argv is what stops a
    caller from interpolating it into a shell command.
    """
    from strata_kb.prlint import lint_body

    if source == "-":
        text = sys.stdin.read()
    else:
        path = Path(source)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            typer.secho(
                f"file '{source}' is not valid UTF-8: {exc}", fg=typer.colors.RED
            )
            raise typer.Exit(1)
        except OSError as exc:
            typer.secho(f"could not read file '{source}': {exc}", fg=typer.colors.RED)
            raise typer.Exit(1)

    report = lint_body(text, plan_dir=plan_dir)
    if json_output:
        typer.echo(json.dumps(report.to_json()))
    else:
        typer.echo(report.render())
    if not report.passed:
        raise typer.Exit(1)


@mission_app.command("lint")
def mission_lint(
    source: str = typer.Argument(
        ..., help="Mission file (or '-' to read from stdin)"
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    hub: str = typer.Option(
        "", "--hub", envvar="STRATA_KB_HUB", help="kb-hub URL/path (empty = config)"
    ),
    tickets_dir: Path | None = typer.Option(
        None,
        "--tickets-dir",
        help="Where ticket files live (default: the mission file's sibling "
        "'tickets/' directory)",
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit the report as JSON instead of text"
    ),
    fail_on_stale: bool = typer.Option(
        False,
        "--fail-on-stale",
        help="Treat a stale ref (the cited content changed upstream since "
        "the pinned commit) as an error; exit 2 when that is the only "
        "failure, mirroring `kb resolve`",
    ),
) -> None:
    """Definition-of-Ready gate: lint a mission plan against the DoR checklist."""
    from strata_kb.missionlint import lint

    path: Path | None = None
    if source == "-":
        text = sys.stdin.read()
    else:
        path = Path(source)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            typer.secho(
                f"file '{source}' is not valid UTF-8: {exc}", fg=typer.colors.RED
            )
            raise typer.Exit(1)
        except OSError as exc:
            typer.secho(f"could not read file '{source}': {exc}", fg=typer.colors.RED)
            raise typer.Exit(1)

    # An explicitly-passed --tickets-dir is a deliberate BA choice, so a
    # typo must be a hard error — otherwise check_coverage's per-file
    # .is_file() probing quietly reports "0/N US drafted", misdiagnosing a
    # bad path as missing tickets. The sibling default below stays
    # fail-soft: its absence degrades to the engine's note, it never
    # becomes an error.
    if tickets_dir is not None and not tickets_dir.is_dir():
        typer.secho(
            f"--tickets-dir '{tickets_dir}' does not exist or is not a directory",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    # A mission at missions/<id>.md has tickets/ as its sibling, so the
    # coverage check works with no flag in the layout kb init scaffolds.
    # Gate on the parent directory's name so the default only ever binds to
    # the sibling of an actual missions/ directory — not some unrelated
    # tickets/ that happens to sit next to wherever the mission file was
    # opened from (e.g. a mission under specs/missions/2026/ looking in
    # specs/missions/tickets, or one under ~/Downloads/ binding to
    # ~/tickets if that happens to exist).
    resolved_tickets = tickets_dir
    if (
        resolved_tickets is None
        and path is not None
        and path.parent.name == "missions"
    ):
        sibling = path.parent.parent / "tickets"
        if sibling.is_dir():
            resolved_tickets = sibling

    handle = _hub_or_exit(hub, kb_dir)
    report = lint(
        text,
        handle,
        path=path,
        tickets_dir=resolved_tickets,
        fail_on_stale=fail_on_stale,
    )
    if json_output:
        typer.echo(json.dumps(report.to_json()))
    else:
        typer.echo(report.render())
    if report.passed:
        return
    errors = sum(1 for i in report.issues if i.level == "error")
    # Mirror `kb resolve`: 2 means "everything resolves, but the cited
    # content moved", which a caller may want to treat differently from a
    # mission that is simply not ready.
    raise typer.Exit(2 if report.stale_errors == errors else 1)


@app.command()
def diff(
    doc_id: str = typer.Argument(..., help="Document ID"),
    against: str = typer.Option("HEAD", help="Git rev to diff against, e.g. HEAD, a3f9c21"),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
) -> None:
    """Diff added/removed/changed sections between the worktree and a git rev."""
    from strata_kb import gitio
    from strata_kb.diff import diff_doc, render_diff

    try:
        report = diff_doc(kb_dir, doc_id, against=against)
    except (ValueError, gitio.GitError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.echo(render_diff(report))


def _resolve_reviewer_and_check_approvable(kb_dir: Path, doc_id: str, by: str) -> str:
    """Resolve the `--by` reviewer identity and run the strict-build gate
    (`kb build --strict` across the whole KB) that `kb approve` requires
    before flipping anything to reviewed."""
    from strata_kb import gitio
    from strata_kb.review import check_approvable, doc_ids_with_manifest, resolve_reviewer

    try:
        targets = [doc_id] if doc_id else doc_ids_with_manifest(kb_dir)
        root = gitio.git_root(kb_dir.resolve())
        reviewer = resolve_reviewer(root, by or None)
        problems = check_approvable(kb_dir, targets)
        for p in problems:
            typer.secho(f"[error] {p}", fg=typer.colors.RED)
        if problems:
            typer.secho(
                "kb approve: not approvable — fix the errors above", fg=typer.colors.RED
            )
            raise typer.Exit(1)
    except (ValueError, gitio.GitError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    return reviewer


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
    by: str = typer.Option(
        "", "--by", help="Reviewer identity 'name <email>' (default: git user.name/email)"
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
) -> None:
    """Mark sections as reviewed (status: summarized → reviewed)."""
    from strata_kb import gitio
    from strata_kb.review import approve_all_changed, approve_sections

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

    reviewer = _resolve_reviewer_and_check_approvable(kb_dir, doc_id, by)

    try:
        if all_changed:
            reports = approve_all_changed(kb_dir, against, doc_id=doc_id or None, by=reviewer)
        else:
            reports = [
                approve_sections(kb_dir, doc_id, list(section) or None, by=reviewer)
            ]
    except (ValueError, gitio.GitError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)

    flipped_total = 0
    has_missing = False
    has_skipped_machine = False
    for rep in reports:
        for sid in rep.skipped_pending:
            typer.secho(
                f"[warn] {rep.doc_id} §{sid} is still pending — cannot approve",
                fg=typer.colors.YELLOW,
                err=True,
            )
        for sid in rep.skipped_machine:
            has_skipped_machine = True
            typer.secho(
                f"[note] {rep.doc_id} §{sid} is machine-authored — skipped "
                "(pass --section to force)",
                fg=typer.colors.YELLOW, err=True,
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
            typer.echo(f"commit .kb/{rep.doc_id} to record the approval")

    if has_missing:
        raise typer.Exit(1)
    if flipped_total == 0:
        if all_changed:
            typer.echo("kb approve: nothing to approve")
        elif has_skipped_machine:
            typer.secho(
                "kb approve: only machine-authored sections remain summarized — "
                "pass --section <id> to force",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(1)
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
        "", "--hub", envvar="STRATA_KB_HUB", help="kb-hub URL/path (empty = config)"
    ),
) -> None:
    """Check KB health; pass --context to check citation staleness."""
    from strata_kb.config import effective_repo_id
    from strata_kb.doctor import (
        Issue,
        _flatten,
        check_asset_store,
        check_context,
        check_hub,
        check_kb,
        check_kind,
        check_usage_log,
    )

    # check_kind first: it is the only check that can report a broken
    # config.yaml, and _hub_or_exit reads that same file to find the hub —
    # resolving first meant doctor exited before its own handler ran (H1).
    kind_issues = check_kind(kb_dir)
    if any(i.level == "error" for i in kind_issues):
        for issue in kind_issues:
            typer.secho(f"[{issue.level}] {issue.message}", fg=typer.colors.RED)
        raise typer.Exit(1)
    handle = _hub_or_exit(hub, kb_dir)
    issues = kind_issues + check_kb(kb_dir) + check_asset_store(kb_dir, handle)

    cfg_kind = ""
    try:
        from strata_kb.config import load_config as _load_config

        cfg_kind = _load_config(kb_dir).kind
    except (*_CONFIG_READ_ERRORS, OSError) as exc:
        # check_kind (doctor.py) now catches this exact class set on this
        # exact file first and exits above -- this read can only still fire
        # on a TOCTOU race between the two reads (config.yaml changes or
        # vanishes between check_kind's read and this one). Kept as a
        # backstop for that race rather than removed, so a hit here still
        # reports instead of continuing with an empty kind and silently
        # skipping the kind-specific checks below.
        issues.append(
            Issue("error", f"could not read .kb/config.yaml: {_flatten(exc)}")
        )

    repo_id = effective_repo_id("", kb_dir)
    if not repo_id:
        from strata_kb import gitio as _gitio

        try:
            repo_id = _gitio.git_root(kb_dir.resolve()).name
        except _gitio.GitError as exc:
            # A reader .kb (any kind other than "hub") never consumes
            # repo_id below — see the "hub"-only uses further down — so an
            # undeterminable repo_id there is not this KB's problem to
            # report. Only a hub's own checks (check_hub, federation
            # publish) actually need it.
            if cfg_kind == "hub":
                issues.append(
                    Issue(
                        "error",
                        f"could not determine the repo id — .kb is not inside a "
                        f"git repo and repo_id is unset in config.yaml: "
                        f"{_flatten(exc)}",
                    )
                )
            repo_id = None

    if cfg_kind in ("ba", "dev"):
        issues += check_usage_log(kb_dir)
    if cfg_kind == "hub":
        from strata_kb import gitio as _gitio2
        from strata_kb.config import load_config as _load_config2
        from strata_kb.doctor import check_federation_publish

        hub_issues, hub_stale = check_hub(
            kb_dir, handle, repo_id=repo_id, warn_untracked_index=True
        )
        issues += hub_issues
        try:
            source_root = _gitio2.git_root(kb_dir.resolve())
        except _gitio2.GitError as exc:
            issues.append(
                Issue(
                    "warning",
                    f"multi-tier checks skipped — .kb is not inside a git repo: {exc}",
                )
            )
        else:
            upstream = None
            if handle is not None and handle.root.resolve() != source_root.resolve():
                # A URL-configured hub resolves to a cache clone — compare
                # identities, not just paths: a cached clone of *this* repo
                # (same repo_id in its config) is still "self".
                try:
                    dest_rid = _load_config2(handle.kb_dir).repo_id
                except (*_CONFIG_READ_ERRORS, OSError) as exc:
                    # publish.py:1291 fails closed on this exact read
                    # ("a corrupt upstream config must not silently blind
                    # the cycle guard"). One condition, one policy.
                    issues.append(
                        Issue(
                            "error",
                            "could not read the upstream hub's .kb/config.yaml: "
                            f"{_flatten(exc)}",
                        )
                    )
                    dest_rid = ""
                if not (repo_id and dest_rid and dest_rid == repo_id):
                    upstream = handle
            issues += check_federation_publish(source_root, upstream, repo_id)
    else:
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
