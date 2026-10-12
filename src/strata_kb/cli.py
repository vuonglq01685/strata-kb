"""cli — the `kb` command line (typer), entry point `strata_kb.cli:app`.

Defines the root `app` and its sub-apps (context, assets, ticket, mission, svc,
usage, pr, plan, impl). Commands stay thin: they import their domain module
lazily, inside the command body, and turn its errors into one red line and
exit 1. `_GuardedGroup` catches any KbError that escapes a command, so a new
error class must derive from KbError rather than reach the user as a
traceback. Importing this module forces the standard streams to UTF-8.
"""

from __future__ import annotations

import importlib.metadata
import json
import os
import sys
import unicodedata
from datetime import UTC
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

import typer
import yaml
from pydantic import ValidationError
from typer.core import TyperGroup

from strata_kb import models
from strata_kb.utf8io import force_utf8_streams

if TYPE_CHECKING:
    from strata_kb.hub import HubHandle
    from strata_kb.resolve import ResolvedRef
    from strata_kb.usage.ingest import IngestResult

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


class _GuardedGroup(TyperGroup):
    """The root `kb` group. A KbError that escapes any command, sub-apps
    included, becomes one red line and exit 1 instead of a traceback, so a
    command catches a KbError only when it has something to add to it."""

    def invoke(self, ctx):  # click's Context; typer may vendor its own click
        from strata_kb.errors import KbError

        try:
            return super().invoke(ctx)
        except KbError as exc:
            typer.secho(str(exc), fg=typer.colors.RED)
            raise typer.Exit(1) from None


app = typer.Typer(
    cls=_GuardedGroup,
    help="Strata — Knowledge Base as Code for large reference documents.",
    no_args_is_help=True,
    # Several commands (mcp-setup) handle secrets. Some typer/click versions
    # default this to True, which prints local variables -- including the
    # secret -- into an uncaught exception's traceback. False everywhere.
    pretty_exceptions_show_locals=False,
)

context_app = typer.Typer(
    help="Operate on kb-context blocks (machine-readable citations)."
)
app.add_typer(context_app, name="context")

assets_app = typer.Typer(help="Asset store operations (hub): migrate, verify")
app.add_typer(assets_app, name="assets")

ticket_app = typer.Typer(
    help="Ticket linting: Definition-of-Ready gate for BA tickets."
)
app.add_typer(ticket_app, name="ticket")

mission_app = typer.Typer(
    help="Mission linting: Definition-of-Ready gate for BA mission plans."
)
app.add_typer(mission_app, name="mission")

svc_app = typer.Typer(
    help="Service knowledge: record which tickets touched which service."
)
app.add_typer(svc_app, name="svc")

usage_app = typer.Typer(
    help="Token/cost measurement: ingest transcripts, record rows, render a report."
)
app.add_typer(usage_app, name="usage")

pr_app = typer.Typer(
    help="Pull-request gate: check a PR description carries its evidence."
)
app.add_typer(pr_app, name="pr")

plan_app = typer.Typer(
    help="Dev plan tools: dependency waves of docs/impl/<ticket-id>/plan.md."
)
app.add_typer(plan_app, name="plan")

impl_app = typer.Typer(help="Dev work folders: docs/impl/<ticket-id>/.")
app.add_typer(impl_app, name="impl")

code_sync_app = typer.Typer(
    help="Keep hub docs in step with the code docs: scan for drift, set the baseline."
)
app.add_typer(code_sync_app, name="code-sync")


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


class RepoKind(StrEnum):
    hub = "hub"
    child = "child"
    ba = "ba"
    dev = "dev"


class AssetsMode(StrEnum):
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
          ingests or summarizes KB content; publishes only its own plan
          (`<repo_id>-plan`) to the hub.

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
    report = init_repo(
        path, resolved, force=force, assets=assets.value if assets else None, langs=lang
    )
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
        hint = (
            " (protected data — use --force to overwrite)"
            if rel in PROTECTED_FILES
            else ""
        )
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
        typer.echo(
            "  4. kb publish    (or /kb-publish)"
            "  # sends the plan; needs intake: and a hub registry entry"
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

    kind = dockersetup.repo_kind(path)
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
        report = dockersetup.run_setup(path, regenerate=force)
    except dockersetup.EnvExistsError:
        if _stdin_isatty() and typer.confirm(
            f"Found existing .env — regenerate {dockersetup.TOKEN_VAR}?"
        ):
            report = dockersetup.run_setup(path, regenerate=True)
        else:
            raise
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
        raise typer.Exit(1) from None
    except OSError as exc:
        # write_env can raise OSError (unwritable repo dir), which must
        # produce the same one-line message the root guard gives a KbError,
        # never propagate to Typer's traceback hook where the token could
        # leak (see app=typer.Typer above).
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from None

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
        "To persist, add that line to your shell profile (~/.zshrc), or use direnv."
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


def _hub_or_reason(hub_flag: str, kb_dir: Path) -> tuple[HubHandle | None, str]:
    """Same resolution as `_hub_or_exit`, but a failure is a returned reason
    string instead of a red line + exit — for a caller (`mission next`) that
    treats "no hub" as a fact to report, not a fatal error. A malformed
    operator .kb/config.yaml is still a hard exit via `_invalid_yaml_exit`:
    that is an authoring error, not a "no hub configured" fact."""
    from strata_kb import gitio
    from strata_kb.config import HubConfigError, require_hub
    from strata_kb.hub import resolve_hub

    try:
        hub_ref = require_hub(hub_flag, kb_dir)
    except HubConfigError as exc:
        return None, str(exc)
    except (*_CONFIG_READ_ERRORS, OSError) as exc:
        # require_hub -> load_config -> models.load_yaml_model raises
        # ValidationError / yaml.YAMLError for an operator-edited
        # .kb/config.yaml. 11 commands funnel through here, so this is the
        # one place that keeps any of them from printing a traceback.
        _invalid_yaml_exit(kb_dir / "config.yaml", exc)
    # resolve_hub can raise gitio.GitError (hub.py's _discard_cache) when a
    # stale cache's removal is blocked -- e.g. a locked
    # .kb-work/search.sqlite3, and every command that reaches here (`doctor`
    # included, the CHANGELOG's 0.21.0 no-traceback claim for it) is exactly
    # the kind of process that would be holding it open. Same shape as
    # mcp._hub and web/api.hub_handle -- the message already names the cache,
    # says it is disposable, and tells the operator to delete it -- let it
    # through unwrapped rather than replacing it.
    try:
        handle = resolve_hub(hub_ref)
    except gitio.GitError as exc:
        return None, str(exc)
    if handle is None:
        return None, (
            f"could not reach hub '{gitio.redact_url(hub_ref)}' and no cache exists — "
            "check the network or the hub path"
        )
    if handle.stale:
        age = f"~{handle.age_seconds:.0f}s" if handle.age_seconds else "unknown age"
        typer.secho(
            f"[warn] hub cache is stale ({age})", fg=typer.colors.YELLOW, err=True
        )
    return handle, ""


def _hub_or_exit(hub_flag: str, kb_dir: Path) -> HubHandle:
    """Hub is required: flag > env (typer envvar already folded) > .kb/config.yaml."""
    handle, reason = _hub_or_reason(hub_flag, kb_dir)
    if handle is None:
        typer.secho(reason or "hub unavailable", fg=typer.colors.RED)
        raise typer.Exit(1)
    return handle


def _refresh_code_or_exit(kb_dir: Path, repo_id: str) -> None:
    """Bring `<repo_id>-code` up to the working tree before a command reads
    it. Notes go to stderr so --json stays pure."""
    from strata_kb.codeingest import core, sync

    try:
        result = sync.ensure_code_fresh(kb_dir, repo_id)
    except core.CodeIngestError as exc:
        typer.secho(
            f"could not refresh {repo_id}-code: {exc}", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(1) from None
    for note in result.notes:
        typer.secho(f"[note] {note}", fg=typer.colors.YELLOW, err=True)


def _refresh_dev_code(kb_dir: Path) -> None:
    """`kb build` / `kb publish` in a dev repo: refresh `-code` first — but
    only once the repo has one, so a repo before /dev-code-seed builds and
    publishes exactly as before. Any other kind: no-op."""
    from strata_kb.codeingest import sync
    from strata_kb.config import load_config

    try:
        cfg = load_config(kb_dir)
    except (*_CONFIG_READ_ERRORS, OSError):
        return  # the command's own config read reports a broken file
    if (
        cfg.kind != "dev"
        or not cfg.repo_id
        or not sync.has_code_doc(kb_dir, cfg.repo_id)
    ):
        return
    _refresh_code_or_exit(kb_dir, cfg.repo_id)


def _refresh_ba_plan(kb_dir: Path) -> None:
    """`kb publish` in a ba repo: regenerate `<repo_id>-plan` from the working
    tree, so the diff preview and the upload show what CI will send. Same
    defaults as `kb plan-ingest`, anchored to the repo root."""
    from strata_kb import cipublish, config, planingest
    from strata_kb.build import build_kb

    resolved_kb_dir = kb_dir.resolve()
    root = resolved_kb_dir.parent
    rid = config.effective_repo_id("", resolved_kb_dir) or root.name
    try:
        plan_report = planingest.run(
            root, resolved_kb_dir, rid, root / "missions", root / "tickets"
        )
    except planingest.PlanIngestError as exc:
        typer.secho(
            f"could not refresh {rid}-plan: {exc}", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(1) from None
    # A skipped story is not an error, but the BA must see it before it ships.
    for file, reason in plan_report.skipped:
        line = f"skipped: {file} — {reason}"
        typer.secho(line, fg=typer.colors.YELLOW, err=True)
        cipublish.write_step_summary(line)
    report = build_kb(kb_dir)
    for warning in report.warnings + report.quality:
        typer.secho(f"[warn] {warning}", fg=typer.colors.YELLOW, err=True)
    for error in report.errors:
        typer.secho(f"[error] {error}", fg=typer.colors.RED, err=True)
    if not report.ok:
        raise typer.Exit(1)


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
    work_dir: Path = typer.Option(
        Path(".kb-work"), help="Intermediate cache directory"
    ),
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
        raise typer.Exit(1) from None
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
    typer.echo(f"{len(report_s.summarized)} summarized, {len(report_s.failed)} failed.")
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


def _require_hub_kind(kb_dir: Path, command: str) -> None:
    """Exit 1 unless `kb_dir`'s config says `kind: hub`."""
    from strata_kb import config

    kind = config.load_config(kb_dir).kind
    if kind != "hub":
        typer.secho(
            f"{command} runs only on a kind: hub repo (this one is "
            f"kind: {kind or 'unset'})",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)


@app.command()
def authored(
    doc_id: str = typer.Argument(..., help="Document ID to mark"),
    off: bool = typer.Option(False, "--off", help="Remove the authored tag"),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
) -> None:
    """Tag a hub doc `authored`: its markdown is the master, `kb ingest` refuses it."""
    from strata_kb import authored as authored_mod

    try:
        _require_hub_kind(kb_dir, "kb authored")
        changed = authored_mod.set_authored(kb_dir, doc_id, not off)
    except (*_CONFIG_READ_ERRORS, OSError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from None
    state = "unmarked" if off else "marked"
    typer.echo(f"kb authored: {doc_id} {state if changed else 'already ' + state}")


def _code_sync_root(kb_dir: Path, command: str) -> Path:
    """The hub repo root, after the hub-kind check."""
    from strata_kb import gitio

    _require_hub_kind(kb_dir, command)
    return gitio.git_root(kb_dir.resolve().parent)


@code_sync_app.command("scan")
def code_sync_scan(
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    baseline: str = typer.Option(
        "", "--baseline", help="Compare against this hub commit, not the baseline file"
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON"),
    md: bool = typer.Option(False, "--md", help="Emit the Markdown work order"),
) -> None:
    """Hub docs that name something the code docs changed since the baseline.
    Exit 0 nothing to do, 2 findings, 1 error."""
    from strata_kb.codesync import scan
    from strata_kb.errors import KbError

    try:
        root = _code_sync_root(kb_dir, "kb code-sync")
        result = scan.run_scan(root, baseline_sha=baseline or None)
    except (KbError, *_CONFIG_READ_ERRORS, OSError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from None
    if json_output:
        typer.echo(json.dumps(scan.to_json(result)))
    elif md:
        typer.echo(scan.render_markdown(result), nl=False)
    else:
        for note in result.notes:
            typer.echo(f"note: {note}")
        for f in result.findings:
            typer.echo(f"{f.doc_id} §{f.section_id}: {scan.line(f)}")
        if not result.findings:
            typer.echo("kb code-sync: nothing to update")
    code = scan.exit_code(result)
    if code:
        raise typer.Exit(code)


@code_sync_app.command("issue")
def code_sync_issue(
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Which open kb-code-sync issue is the hub job's work order.
    Exit 0 a current or stale one exists, 2 none, 1 error."""
    from dataclasses import asdict

    from strata_kb import ghio
    from strata_kb.codesync import issue as issue_mod
    from strata_kb.codesync import workorder
    from strata_kb.errors import KbError

    try:
        root = _code_sync_root(kb_dir, "kb code-sync")
        verdicts = workorder.classify(
            root, ghio.list_open_issues(root, issue_mod.LABEL)
        )
    except (KbError, *_CONFIG_READ_ERRORS, OSError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from None
    usable = next((v for v in verdicts if v.kind in workorder.USABLE), None)
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "usable": usable.number if usable else None,
                    "baseline_sha": usable.baseline_sha if usable else None,
                    "issue_baseline_sha": usable.issue_baseline_sha if usable else None,
                    "issues": [asdict(v) for v in verdicts],
                }
            )
        )
    else:
        for v in verdicts:
            typer.echo(f"#{v.number} [{v.kind}] {v.reason}")
        if not verdicts:
            typer.echo("kb code-sync: no open kb-code-sync issue")
    if usable is None:
        raise typer.Exit(2)


@code_sync_app.command("baseline")
def code_sync_baseline(
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    at: str = typer.Option(
        "", "--at", help="Hub commit to record (default: the scan sha)"
    ),
) -> None:
    """Record the hub commit the code-sync is current at, in kb-code-sync.yaml."""
    from strata_kb import gitio
    from strata_kb.codesync import baseline as baseline_mod
    from strata_kb.errors import KbError

    try:
        root = _code_sync_root(kb_dir, "kb code-sync")
        sha = (
            gitio.resolve_commit(root, baseline_mod.check_sha(at))
            if at
            else baseline_mod.scan_ref(root)
        )
        baseline_mod.write(root, sha)
    except (KbError, *_CONFIG_READ_ERRORS, OSError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from None
    typer.echo(sha)


@code_sync_app.command("run")
def code_sync_run(
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    issue: bool = typer.Option(
        False, "--issue", help="Create/update/close the rolling GitHub issue"
    ),
    loop: bool = typer.Option(
        False,
        "--loop",
        help="Repeat every STRATA_KB_CODE_SYNC_INTERVAL seconds (default 86400)",
    ),
) -> None:
    """One scan plus issue update (the hub-sync job); logs to stderr.
    Exit 0 nothing to do, 2 findings, 1 error. --loop never exits."""
    import logging

    from strata_kb.codesync import runner
    from strata_kb.errors import KbError

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    interval = runner.interval_from_env() if loop else 0
    try:
        root = _code_sync_root(kb_dir, "kb code-sync")
    except (KbError, *_CONFIG_READ_ERRORS, OSError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from None
    if loop:
        runner.run_loop(root, interval=interval, issue=issue)
    code = runner.run_once(root, issue=issue)
    if code:
        raise typer.Exit(code)


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
        # traceback.
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


def _run_summarize(kb_dir: Path, llm_choice: str, doc_id: str | None, max_workers: int):
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
        kb_dir,
        runner,
        doc_id=doc_id,
        max_workers=workers,
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


def _refuse_generated_or_note(kb_dir: Path, doc_id: str) -> None:
    """-code has one producer, `kb code-ingest`.

    A malformed index.yaml (e.g. a typo'd `llm.effort`) is not this
    helper's concern — let it through so `_resolve_runner`'s own
    ValueError handling turns it into the usual clean `[error]` instead of
    this helper surfacing a raw traceback first.
    """
    from strata_kb.summarize import generated_doc_ids

    try:
        generated = generated_doc_ids(kb_dir)
    except ValueError:
        return
    if doc_id and doc_id in generated:
        typer.secho(
            f"{doc_id} is generated by `kb code-ingest` and is never summarized — "
            "re-run `kb code-ingest` to regenerate it",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    if not doc_id and generated:
        typer.secho(
            f"[note] skipped generated document(s): {', '.join(sorted(generated))}",
            fg=typer.colors.YELLOW,
            err=True,
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
        [],
        "--section",
        help="With --redo/--print-prompt: only these section ids (repeatable)",
    ),
    print_prompt: bool = typer.Option(
        False,
        "--print-prompt",
        help="Print the engine's prompt for each pending section of DOC_ID and exit",
    ),
) -> None:
    """Fill pending L1/L2 summaries by calling a headless LLM CLI (claude/copilot)."""
    _validate_summarize_args(
        kb_dir,
        llm,
        redo,
        print_prompt,
        all_docs,
        include_reviewed,
        yes,
        dry_run,
        section,
    )
    _refuse_generated_or_note(kb_dir, doc_id)
    _dispatch_summarize(
        kb_dir,
        llm,
        max_workers,
        doc_id,
        redo,
        print_prompt,
        all_docs,
        include_reviewed,
        yes,
        dry_run,
        section,
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
            kb_dir,
            llm,
            max_workers,
            doc_id,
            all_docs,
            include_reviewed,
            yes,
            dry_run,
            list(section),
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
        typer.secho(
            "--print-prompt cannot be combined with --redo", fg=typer.colors.RED
        )
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
    all_docs: bool,
    include_reviewed: bool,
    yes: bool,
    dry_run: bool,
    sections: list[str],
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
        kb_dir,
        doc_id,
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
    no_refresh: bool = typer.Option(
        False,
        "--no-refresh",
        help="Dev repo: validate <repo_id>-code as it is; skip regenerating it first",
    ),
) -> None:
    """Validate KB: no TODOs left, table integrity, C2 quality rules, updated token counts."""
    from strata_kb.build import build_kb

    # Dev repo: validate what the merge would publish — on a PR checkout
    # -code is absent until this regenerates it.
    if not no_refresh:
        _refresh_dev_code(kb_dir)

    try:
        report = build_kb(kb_dir, allow_pending=allow_pending, strict=strict)
    except ValueError as exc:
        # pydantic.ValidationError is a ValueError subclass — a bad literal
        # (e.g. a typo'd llm.effort) must read as a clean CLI error, not a
        # traceback.
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
    repo_root: Path = typer.Option(
        Path("."), "--repo-root", help="Repository root to scan"
    ),
    kb_dir: Path = typer.Option(
        Path(".kb"),
        help="KB directory (default: .kb, relative to the current directory like every other kb command)",
    ),
    repo_id: str = typer.Option(
        "", "--repo-id", help="Repo ID (default: config, then folder name)"
    ),
    doc_id: str = typer.Option(
        "", "--doc-id", help="Document ID (default: <repo_id>-code)"
    ),
    db: list[Path] = typer.Option(
        [],
        "--db",
        help="SQLite file to read (repeatable, explicit only; replaces code_ingest.db for this run)",
    ),
    tags: str = typer.Option(
        "",
        "--tags",
        help="Extra index tags, comma-separated (replaces code_ingest.tags for this run)",
    ),
    scaffold_svc: bool = typer.Option(
        False,
        "--scaffold-svc",
        help="Also upsert the curated <repo_id>-svc scaffold (pending sections)",
    ),
    json_out: bool = typer.Option(False, "--json", help="Machine-readable report"),
) -> None:
    """Extract code structure into .kb/<repo_id>-code/ — deterministic, no LLM."""
    import dataclasses

    from strata_kb import config
    from strata_kb.codeingest import core, sync

    resolved_root = repo_root.resolve()
    # Relative --kb-dir is cwd-relative, like every other kb command.
    resolved_kb_dir = kb_dir.resolve()

    # effective_repo_id() returns None when neither --repo-id nor
    # .kb/config.yaml supplies one; the help text above promises a folder-name
    # fallback, so supply it here rather than writing a "None-code" doc.
    rid = config.effective_repo_id(repo_id, resolved_kb_dir) or resolved_root.name
    did = doc_id or f"{rid}-code"
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    # `code_ingest:` in .kb/config.yaml is the one configuration local runs
    # and CI share; a flag replaces its list for this run only, and says so
    # below.
    opts = sync.options_from_config(
        resolved_root,
        resolved_kb_dir,
        rid,
        doc_id=did,
        db=list(db),
        tags=tag_list,
        scaffold_svc=scaffold_svc,
    )

    try:
        report = core.run(opts)
    except core.CodeIngestError as exc:
        # CodeIngestError carries whatever partial CodeIngestReport existed at
        # the point of failure, so a warning already collected before the
        # refusal (e.g. "could not read _manifest.yaml") is shown too, instead
        # of only this exception's own message — which, for a corrupt -svc
        # manifest, otherwise reads as "no matching entry in _manifest.yaml —
        # restore the manifest entries" with no hint that the manifest is
        # simply malformed. A non-empty `files_written` also means the -code
        # document was already written and indexed before a later
        # --scaffold-svc refusal — a partial success, not a full failure — so
        # that's called out too. All three lines below pass err=True (the
        # codebase's existing convention for diagnostics that must never land
        # on stdout — see e.g. the RED-secho'd errors elsewhere in this file)
        # so a --json invocation's stdout stays empty, never polluted, on this
        # path — matching the purity --json already guarantees on the success
        # path.
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
        raise typer.Exit(1) from None

    notes: list[str] = []
    if db or tag_list:
        notes.append(
            "--db/--tags replace code_ingest: in .kb/config.yaml for this run — "
            "output will differ from what CI publishes"
        )
    pin_note = sync.version_note(resolved_root)
    if pin_note:
        notes.append(pin_note)
    for note in notes:
        typer.secho(f"[note] {note}", fg=typer.colors.YELLOW, err=True)

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
        # List each id ("stale-risk: svc.<name>" / "orphan: svc.<name>"), not
        # just the counts: --json already carries them via
        # report.stale_risk/report.orphans, but no machine consumer of --json
        # exists yet, so the terminal is the only surface a Dev has today.
        for sid in report.stale_risk:
            typer.echo(f"  stale-risk: {sid}")
        for sid in report.orphans:
            typer.echo(f"  orphan: {sid}")


@app.command(name="plan-ingest")
def plan_ingest(
    repo_root: Path = typer.Option(
        Path("."), "--repo-root", help="Repository root (read for the commit)"
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    repo_id: str = typer.Option(
        "", "--repo-id", help="Repo ID (default: config, then folder name)"
    ),
    missions_dir: Path = typer.Option(
        Path("missions"), "--missions-dir", help="Where mission files live"
    ),
    tickets_dir: Path = typer.Option(
        Path("tickets"), "--tickets-dir", help="Where ticket files live"
    ),
    json_out: bool = typer.Option(False, "--json", help="Machine-readable report"),
) -> None:
    """Build .kb/<repo_id>-plan/ from ready missions and tickets — deterministic,
    offline, no LLM. Items that are not ready are listed as skipped."""
    from strata_kb import cipublish, config, planingest

    resolved_root = repo_root.resolve()
    resolved_kb_dir = kb_dir.resolve()
    rid = config.effective_repo_id(repo_id, resolved_kb_dir) or resolved_root.name
    try:
        report = planingest.run(
            resolved_root, resolved_kb_dir, rid, missions_dir, tickets_dir
        )
    except planingest.PlanIngestError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from None

    if json_out:
        typer.echo(
            json.dumps(
                {
                    "doc_id": report.doc_id,
                    "published": report.published,
                    "skipped": [list(pair) for pair in report.skipped],
                },
                indent=2,
            )
        )
        return

    typer.echo(f"doc: {report.doc_id}")
    typer.echo(f"published: {len(report.published)} section(s)")
    for sid in report.published:
        typer.echo(f"  {sid}")
    for file, reason in report.skipped:
        line = f"skipped: {file} — {reason}"
        typer.echo(line)
        cipublish.write_step_summary(line)


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
    no_refresh: bool = typer.Option(
        False,
        "--no-refresh",
        help="Read <repo_id>-code as it is; skip regenerating it from the working tree",
    ),
    json_out: bool = typer.Option(False, "--json", help="Machine-readable report"),
) -> None:
    """Append a ticket to <repo_id>-svc §hist.<service>. Idempotent per ticket."""
    import dataclasses

    from strata_kb import config, svcnote

    # effective_repo_id() returns None when neither --repo-id nor
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

    # Guarded the same way build/publish are (_refresh_dev_code): a repo
    # that has not run /dev-code-seed has neither -code nor -svc yet, and
    # svcnote.add_note below is always going to refuse it as "-svc does not
    # exist" — refreshing first would create a -code document and an
    # index.yaml entry as a side effect of a command that was never going
    # to succeed.
    from strata_kb.codeingest import sync

    if not no_refresh and (
        sync.has_code_doc(kb_dir, rid) or (kb_dir / f"{rid}-svc").is_dir()
    ):
        _refresh_code_or_exit(kb_dir, rid)

    ref_list = tuple(r.strip() for r in refs.split(",") if r.strip())
    note = svcnote.Note(ticket=ticket, title=title, refs=ref_list)

    report = svcnote.add_note(kb_dir, rid, service, note)

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
    from datetime import datetime

    from strata_kb.usage import ledger as _ledger

    try:
        path = _ledger.usage_dir(kb_dir) / "ingest-errors.log"
        if not (kb_dir / "config.yaml").is_file():
            return  # wrong directory: nowhere correct to write
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(f"{stamp} {message.rstrip()}\n")
    except Exception:  # noqa: BLE001, S110 -- deliberate: see docstring, this sink must never raise
        pass


def _usage_ingest(
    kb_dir: Path, source: Path, *, ticket: str, result: IngestResult
) -> None:
    """The manual (non-hook) ingest: one path, a main transcript or a
    subagent's, via `usage.ingest.ingest_path`, filling `result` in place.

    Its notes (a parent transcript that could not be read, say) are not
    failures — every call read was still stored — but they cost attribution,
    so they go to `ingest-errors.log` like the hook's, where `kb usage report`
    counts them. Logged in `finally`, so a sweep that collects a note and
    then hits a ledger failure still leaves the note behind. The caller also
    shows them to the human running this.
    """
    from strata_kb.usage import ingest as _ingest

    try:
        _ingest.ingest_path(
            kb_dir,
            source,
            actor=_usage_actor(kb_dir),
            ticket=ticket or None,
            result=result,
        )
    finally:
        for note in result.notes:
            _usage_log_error(kb_dir, note)


@usage_app.command("ingest-transcript")
def usage_ingest_transcript(
    path: Path | None = typer.Argument(
        None,
        help="Claude Code transcript JSONL: a main transcript (its subagents "
        "are included) or a subagents/agent-*.jsonl file. Nothing is held "
        "back, so run it only after the session has ended "
        "(omit with --hook-stdin)",
    ),
    hook_stdin: bool = typer.Option(
        False, "--hook-stdin", help="Read the hook payload (JSON) from stdin"
    ),
    ticket: str = typer.Option(
        "",
        "--ticket",
        help="Force this ticket id for every row ingested (subagents included)",
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    json_out: bool = typer.Option(False, "--json", help="Machine-readable report"),
) -> None:
    """Append this transcript's API calls to the usage ledger.

    PATH is a main transcript (its subagents are included) or a
    `subagents/agent-*.jsonl` file. Manual mode holds nothing back, so run it
    only after the session has ended: a call still streaming would be stored
    with a partial output count, and a stored row never changes (I1).

    In hook mode the payload decides: a
    `SubagentStop` payload carries `agent_transcript_path` and ingests that
    one finished subagent in full; a `Stop` payload ingests the main
    transcript and sweeps its subagents, holding back each one's last call
    (it may still be streaming) for `SubagentStop` to store.

    Safe to repeat: rows are de-duplicated by the transcript row's uuid, which
    is what lets the `Stop` hook re-ingest the same growing file every turn.
    """
    from strata_kb.usage import ingest as _ingest
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
        # ALWAYS exit 0 here, unconditionally: a `Stop` or `SubagentStop`
        # hook exiting non-zero blocks Claude (or the subagent) from ending
        # its turn, so NOTHING in this branch may propagate — a malformed
        # payload, an invalid `kind:`, a corrupt ledger, a missing
        # transcript, anything. `except Exception`, not a narrow tuple, is
        # deliberate: the failure modes this must absorb come from several
        # modules this command does not own, and a list of "the exceptions
        # we thought of" is exactly the list a new one falls through. Which
        # files a payload means is `usage.ingest.ingest_hook_payload`'s
        # business; this branch only parses, swallows, and logs.
        raw = sys.stdin.read()
        # Created before the `try` so notes collected before a failure (a
        # missing parent, then a missing subagent file) are still logged.
        result = _ingest.IngestResult()
        try:
            payload = json.loads(raw)
            if path is not None:
                _usage_log_error(
                    kb_dir, "both a path and --hook-stdin were given; used the payload"
                )
            _ingest.ingest_hook_payload(
                kb_dir,
                payload,
                actor=_usage_actor(kb_dir),
                ticket=ticket or None,
                result=result,
            )
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
        for note in result.notes:
            _usage_log_error(kb_dir, note)
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

    result = _ingest.IngestResult()
    try:
        _usage_ingest(kb_dir, path, ticket=ticket, result=result)
    except (OSError, ledger.LedgerError) as exc:
        for note in result.notes:
            typer.secho(note, fg=typer.colors.YELLOW)
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from None
    report = result.report

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
        for note in result.notes:
            # Already in ingest-errors.log; shown here too because a human
            # running a backfill is looking at this output, not at the log.
            # Not in --json mode: that output is one machine-readable object.
            typer.secho(note, fg=typer.colors.YELLOW)
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
        True,
        "--est/--measured",
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
    from datetime import datetime

    from strata_kb.usage import ledger

    row = ledger.UsageRow(
        uuid=str(_uuid.uuid4()),
        ts=datetime.now(UTC).isoformat(timespec="milliseconds"),
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
    report = ledger.append_rows(kb_dir, [row])
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
    with_kb: list[Path] = typer.Option(
        [],
        "--with",
        help="Also read this KB directory's ledger, e.g. the BA repo's .kb, to "
        "price a ticket end to end (repeatable; read-only)",
    ),
    summary: bool = typer.Option(
        False,
        "--summary",
        help="Print the short '## Usage' block for a PR body",
    ),
) -> None:
    """Aggregate the usage ledger: per ticket, phase, model, actor."""
    from datetime import date, datetime

    from pydantic import ValidationError

    from strata_kb.usage import ledger, prices
    from strata_kb.usage import report as report_mod

    try:
        rows = ledger.read_rows_from([kb_dir, *with_kb])
    except ValidationError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from None
    if ticket:
        rows = [r for r in rows if r.ticket == ticket]
    generated = datetime.now(UTC).isoformat(timespec="seconds")
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
    if summary:
        typer.echo(report_mod.render_summary(agg, ticket), nl=False)
        return
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
    except sqlite3.DatabaseError as exc:
        if searchdb.classify_db_error(exc) != "client":
            raise
        typer.secho(f"search index rejected the query: {exc}", fg=typer.colors.RED)
        raise typer.Exit(1) from None
    except searchdb.TooManyTagsError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from None
    for note in outcome.notes:
        typer.secho(note.strip(), fg=typer.colors.YELLOW, err=True)
    results = outcome.results
    if not results:
        typer.echo("No matching section found.")
        raise typer.Exit(0)
    for r in results:
        typer.secho(f"--- [{r.citation}] match={r.match_mode} ~{r.tokens}tk", bold=True)
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
        raise typer.Exit(1) from None
    except AmbiguousDocError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from None
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
    header = (
        f"{'doc':<20} {'sections':>8} {'L1':>8} {'L2':>10} {'L3':>10} {'saving':>8}"
    )
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
    it blocks — shared by `publish` and `ci_publish`."""
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
        "",
        "--hub",
        envvar="STRATA_KB_HUB",
        help="kb-hub URL/path (default: .kb/config.yaml)",
    ),
    repo_id: str = typer.Option(
        "",
        "--repo-id",
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
    branch: str = typer.Option(
        "",
        "--branch",
        help="Hub self-publish only: commit the mirror on this checked-out "
        "branch and open/reuse its PR (no reset, no force-push)",
    ),
) -> None:
    """Mirror .kb/ (L0→L3) to the hub's federation/<repo-id>/ + rebuild the index."""
    from strata_kb import publish as publish_mod
    from strata_kb.config import effective_repo_id, require_hub
    from strata_kb.errors import KbError

    # Every refusal (both --pr and --direct, an unreadable config.yaml, a
    # root hub with no `hub:`, intake on a hub-to-hub publish) is a
    # PublishError, which the root guard prints as one line.
    plan = publish_mod.plan(kb_dir, hub, pr=pr, direct=direct)
    if branch:
        # Before any refresh or write. publish() re-checks the git-side rules.
        if direct:
            raise publish_mod.PublishError("--branch cannot be combined with --direct")
        if plan.route == "intake":
            raise publish_mod.PublishError(
                "--branch cannot be used with `intake:` -- the intake route opens "
                "its own PR"
            )
        if plan.route != "snapshot" or not plan.self_publish:
            raise publish_mod.PublishError(
                "--branch only applies to a hub's self-publish"
            )
    # A hand publish sends the -code CI would send for this commit — never a
    # stale or summarized copy. No --no-refresh here: skipping it is exactly
    # the divergence this prevents.
    if plan.refresh_code:
        _refresh_dev_code(kb_dir)
    if plan.refresh_plan:
        _refresh_ba_plan(kb_dir)

    # KbError (PublishError, GateError, AssetStoreError, GitError, GHError,
    # HashSyncError, HubConfigError) reaches the root guard. What is caught
    # below is what is not a KbError: OSError, and the YAML/schema/JSON
    # errors of reads no call wraps.
    if plan.route == "federation":
        assert plan.hub_ref is not None  # noqa: S101 -- plan() sets it on this route
        try:
            report = publish_mod.publish_federation(
                kb_dir,
                plan.hub_ref,
                repo_id=effective_repo_id(repo_id, kb_dir),
                mode=plan.mode,
            )
        except OSError as exc:
            typer.secho(str(exc), fg=typer.colors.RED)
            raise typer.Exit(1) from None
        _echo_publish_report(report)
        return

    # The gate applies only to routes that publish .kb/ (self-publish,
    # intake, plain publish): a hub-to-hub publish pushes federation/ only,
    # and the hub's own .kb/ there is a drafting desk. Still strictly above
    # require_hub()/resolve_hub()/any write below.
    try:
        _apply_unreviewed_gate(publish_mod.unreviewed_gate(kb_dir, require_reviewed))
    except (*_CONFIG_READ_ERRORS, OSError, KbError) as exc:
        # unreviewed_sections reads every _manifest.yaml through
        # publish._load_manifest_or_raise, which wraps a corrupt file in
        # PublishError: caught here, not at the guard, to name the fix.
        typer.secho(
            f"a _manifest.yaml under {kb_dir} is unreadable ({exc}) -- fix or "
            "re-ingest that document",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1) from None

    if plan.route == "intake":
        try:
            ba_root = kb_dir.resolve().parent
            pr_url = publish_mod.publish_via_intake(
                kb_dir,
                plan.intake_url,
                effective_repo_id(repo_id, kb_dir),
                plan_inputs=(
                    (ba_root / "missions", ba_root / "tickets")
                    if plan.refresh_plan
                    else ()
                ),
            )
        except (
            OSError,
            # ValueError: publish_via_intake polls the intake server's /intake/
            # status endpoint and parses its JSON body unwrapped
            # (publish.py's _default_get_json) -- a malformed 200 response
            # raises json.JSONDecodeError, a ValueError subclass.
            ValueError,
        ) as exc:
            typer.secho(str(exc), fg=typer.colors.RED)
            raise typer.Exit(1) from None
        if pr_url:
            typer.echo(f"kb publish: PR on the hub — {pr_url}")
            typer.echo("Content goes live when the PR is merged on the hub.")
        else:
            typer.echo("kb publish: done (no PR URL reported).")
        return

    try:
        # A self-publish already has its root-anchored hub_ref; re-deriving
        # it via require_hub() would re-resolve `hub: .` against the cwd.
        hub_ref = plan.hub_ref if plan.self_publish else require_hub(hub, kb_dir)
        assert hub_ref is not None  # noqa: S101 -- set for self-publish, else require_hub returned it
        report = publish_mod.publish(
            kb_dir,
            hub_ref,
            repo_id=effective_repo_id(repo_id, kb_dir),
            mode=plan.mode,
            self_publish=plan.self_publish,
            branch=branch or None,
        )
    except (OSError, *_CONFIG_READ_ERRORS) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from None
    _echo_publish_report(report)


@app.command(name="ci-publish")
def ci_publish(
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    repo_id: str = typer.Option(
        "", "--repo-id", help="Repo ID on the hub (default: config)"
    ),
    intake: str = typer.Option(
        "",
        "--intake",
        envvar="STRATA_KB_INTAKE",
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
        msg = (
            f"{kb_dir / 'config.yaml'} is unreadable ({exc}) -- fix the file, "
            "or pass --intake to skip reading it"
        )
        cipublish.write_step_summary(f"error — {msg}")
        typer.secho(msg, fg=typer.colors.RED)
        raise typer.Exit(1) from None
    if not url:
        msg = "no intake URL — add `intake: <url>` to .kb/config.yaml or pass --intake"
        cipublish.write_step_summary(f"error — {msg}")
        typer.secho(msg, fg=typer.colors.RED)
        raise typer.Exit(1)
    try:
        pr_url = cipublish.run(
            kb_dir,
            url,
            effective_repo_id(repo_id, kb_dir),
            require_reviewed=require_reviewed,
        )
    except (
        # KbError: CIPublishError (this command's own token/upload failures)
        # and PublishError -- cipublish.run's own unreviewed-gate check
        # (_check_unreviewed_gate -> publish.unreviewed_gate ->
        # unreviewed_sections) reads every doc's _manifest.yaml through
        # publish._load_manifest_or_raise, which converts a corrupt/
        # schema-invalid/non-UTF-8 file into PublishError, NOT a raw
        # yaml/pydantic exception -- it does not land in the ValueError-
        # family classes below (PublishError is a RuntimeError, not a
        # ValueError, so without this arm naming the base it belongs to, it
        # would escape uncaught). The OIDC token/publish-response
        # JSON parsing (json.loads, in _request_oidc_token/run) IS still
        # unwrapped and does land in _CONFIG_READ_ERRORS below
        # (json.JSONDecodeError is a ValueError subclass).
        KbError,
        gitio.GitError,
        OSError,
        *_CONFIG_READ_ERRORS,
    ) as exc:
        cipublish.write_step_summary(f"error — {exc}")
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from None
    cipublish.write_step_summary(
        f"hub PR: {pr_url}" if pr_url else "no content change on the hub"
    )


@app.command()
def reindex(
    hub: str = typer.Option(
        "",
        "--hub",
        envvar="STRATA_KB_HUB",
        help="kb-hub URL/path (default: .kb/config.yaml)",
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory (to find the config)"),
    force: bool = typer.Option(
        False,
        "--force",
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
        # -c core.quotePath=false: without it, porcelain C-quotes any non-ASCII
        # path (e.g. "federation/ghi-ch\303\272.md") instead of printing it as
        # UTF-8.
        # --untracked-files=all: without it, an entirely-untracked
        # federation/ (first-ever reindex, nothing under it committed yet)
        # collapses to one "?? federation/" line -- the strays check below
        # then flags the whole directory even though committing
        # federation/index.yaml right after this was exactly correct.
        dirty_before = gitio._run(
            handle.root,
            "-c",
            "core.quotePath=false",
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            "federation",
        ).stdout.splitlines()
        committed = gitio.commit_paths(
            handle.root,
            "reindex: rebuild federation/index.yaml",
            ["federation/index.yaml"],
        )
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
        raise typer.Exit(1) from None
    except OSError as exc:
        # str(OSError) alone ("[Errno 13] Permission denied: '...'") names no
        # way forward -- add one.
        typer.secho(
            f"reindex failed ({exc}) -- check file permissions under the hub and retry",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1) from None
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
    except sqlite3.DatabaseError as exc:
        if searchdb.classify_db_error(exc) != "client":
            raise
        typer.secho(f"search index rejected the reindex: {exc}", fg=typer.colors.RED)
        raise typer.Exit(1) from None
    except _CONFIG_READ_ERRORS as exc:
        # searchdb._sync_repo reads every referenced doc's _manifest.yaml
        # unwrapped (unlike load_federation, it does not skip a broken one --
        # it is building content for the index, not enumerating entries).
        typer.secho(
            f"a _manifest.yaml is unreadable while syncing the search index "
            f"({exc}) -- fix or re-ingest that document",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1) from None
    except OSError as exc:
        # This try guards searchdb.sync and needs its own OSError arm, like
        # its sibling above (the write_federation_index/commit_paths block):
        # a locked file under the hub (e.g. .kb-work/search.sqlite3 held open
        # by another kb process) raises PermissionError here, and reindex
        # must never let a traceback reach a user.
        typer.secho(
            f"reindex failed while syncing the search index ({exc}) -- check "
            "file permissions under the hub and retry",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1) from None
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
            raise typer.Exit(1) from None
    typer.echo("kb reindex: federation/index.yaml rebuilt")


@assets_app.command()
def migrate(
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    hub: str = typer.Option(
        "", "--hub", envvar="STRATA_KB_HUB", help="kb-hub URL/path (empty = config)"
    ),
) -> None:
    """Move in-git federation assets to the configured object store (none → s3)."""
    from strata_kb import assetcmd

    handle = _hub_or_exit(hub, kb_dir)
    report = assetcmd.migrate_assets(handle)
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
            # "nothing to migrate" is an all-clear a script may read at exit 0
            # -- printing it here would be false, since the entries above were
            # found and skipped, not swept. A skip is not itself a migrate
            # failure (the entry's markers are broken upstream, not this run),
            # but the run could not confirm federation/ is clean, so it must
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
    from strata_kb import assetcmd

    handle = _hub_or_exit(hub, kb_dir)
    report = assetcmd.verify_assets(handle)
    for label in report.missing_records:
        typer.secho(
            f"[missing] recorded but not in store: {label}", fg=typer.colors.RED
        )
    for label in report.corrupt:
        typer.secho(
            f"[corrupt] bytes on disk/in the store do not hash to their own "
            f"content-addressed name: {label}",
            fg=typer.colors.RED,
        )
    for label in report.dangling_refs:
        typer.secho(
            f"[dangling] referenced but unresolvable: {label}", fg=typer.colors.RED
        )
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
        ...,
        "--refs",
        help="Comma-separated refs, e.g. 'hr-handbook §4.12,travel-policy §2.1'",
    ),
    tags: str = typer.Option("", help="Tags, comma-separated"),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    hub: str = typer.Option(
        "", "--hub", envvar="STRATA_KB_HUB", help="kb-hub URL/path (empty = config)"
    ),
) -> None:
    """Generate a kb-context block pinned at HEAD — paste into a Jira ticket."""
    from strata_kb import kbcontext

    handle = _hub_or_exit(hub, kb_dir)
    ref_strs = [r for r in refs.split(",") if r.strip()]
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    try:
        block, stale_warning = kbcontext.build_context_block(
            handle, ref_strs, tags=tag_list
        )
    except kbcontext.KBContextError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from None
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
        help="Also write docs/impl/<ticket-id>/context.md: header (version, "
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
    from strata_kb import kbcontext
    from strata_kb.resolve import (
        cache_problem,
        render_cache,
        render_resolved,
        resolve_refs,
    )

    if write_cache is not None and status_only:
        typer.secho(
            "--write-cache needs a full resolve; drop --status-only",
            fg=typer.colors.RED,
        )
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
            raise typer.Exit(1) from None
    handle = _hub_or_exit(hub, kb_dir)
    try:
        ctx = kbcontext.parse(text)
        results = resolve_refs(handle, ctx)
    except kbcontext.KBContextError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from None
    typer.echo(render_resolved(results, include_content=not status_only))
    if write_cache is not None:
        from datetime import date

        stem = (
            write_cache.parent.name
            if write_cache.name == "context.md"
            else write_cache.stem.removesuffix("-context")
        )
        try:
            previous = (
                write_cache.read_text(encoding="utf-8")
                if write_cache.exists()
                else None
            )
            write_cache.parent.mkdir(parents=True, exist_ok=True)
            write_cache.write_text(
                render_cache(
                    ctx.version,
                    results,
                    today=date.today().isoformat(),
                    stem=stem,
                    previous=previous,
                ),
                encoding="utf-8",
                newline="\n",
            )
        except (OSError, UnicodeDecodeError) as exc:
            typer.secho(
                f"could not write cache '{write_cache}': {exc}", fg=typer.colors.RED
            )
            raise typer.Exit(1) from None
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
            problem = (
                cache_problem(cache_text, ctx.version, results)
                if cache_text
                else "header"
            )
            if problem:
                typer.echo(f"!! cache-invalid: {problem}")
                cache_bad = True
    if cache_bad or any(r.status == "broken" for r in results):
        raise typer.Exit(1)
    if any(r.status == "stale" for r in results):
        raise typer.Exit(2)


def _resolve_missions_dir(missions_dir: Path | None, path: Path | None) -> Path | None:
    """Where mission files live for a ticket command. An explicit
    --missions-dir that is not a directory is a BA typo and a hard error —
    otherwise the engine's .is_file() probing would misreport a real mission
    as missing. The default is fail-soft: a ticket under tickets/ (flat or
    tickets/<mission-id>/) gets the missions/ next to that tickets/
    directory when that exists, else None (the engine notes the skipped
    checks). Gated on the nearest ancestor named tickets so an unrelated
    missions/ next to some other file never binds."""
    if missions_dir is not None:
        if not missions_dir.is_dir():
            typer.secho(
                f"--missions-dir '{missions_dir}' does not exist or is not a directory",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)
        return missions_dir
    if path is not None:
        for ancestor in (path.parent, *path.parent.parents):
            if ancestor.name == "tickets":
                sibling = ancestor.parent / "missions"
                return sibling if sibling.is_dir() else None
    return None


@ticket_app.command("lint")
def ticket_lint(
    source: str = typer.Argument(..., help="Ticket file (or '-' to read from stdin)"),
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
            raise typer.Exit(1) from None
        except OSError as exc:
            typer.secho(f"could not read file '{source}': {exc}", fg=typer.colors.RED)
            raise typer.Exit(1) from None

    resolved_missions = _resolve_missions_dir(missions_dir, path)

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


@ticket_app.command("stale")
def ticket_stale(
    paths: list[Path] = typer.Argument(
        None, help="Files or directories to scan (default: tickets/ and missions/)"
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    hub: str = typer.Option(
        "", "--hub", envvar="STRATA_KB_HUB", help="kb-hub URL/path (empty = config)"
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON"),
    md: bool = typer.Option(False, "--md", help="Emit the Markdown issue body"),
) -> None:
    """Every ticket and mission whose citations the hub has moved since they
    were pinned. Exit 0 all current, 2 stale only, 1 any broken."""
    from strata_kb import ticketstale

    targets = paths or [Path(d) for d in ticketstale.DEFAULT_DIRS]
    handle = _hub_or_exit(hub, kb_dir)
    findings = ticketstale.scan(targets, handle)
    if json_output:
        typer.echo(json.dumps(ticketstale.to_json(findings)))
    elif md:
        typer.echo(ticketstale.render_markdown(findings), nl=False)
    elif not findings:
        typer.echo("kb ticket stale: every citation is current")
    else:
        for f in findings:
            for ref in f.refs:
                typer.echo(f"{f.path}: [{ref.status}] {ref.citation} — {ref.reason}")
    code = ticketstale.exit_code(findings)
    if code:
        raise typer.Exit(code)


@ticket_app.command("fetch")
def ticket_fetch(
    ticket: str = typer.Argument(
        ..., help="Ticket id, or <repo>:<id> if several repos hold it"
    ),
    out: Path | None = typer.Option(
        None, "--out", help="Write here (default: docs/impl/<id>/ticket.md)"
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    hub: str = typer.Option(
        "", "--hub", envvar="STRATA_KB_HUB", help="kb-hub URL/path (empty = config)"
    ),
) -> None:
    """Read a ticket from the hub by id and save it as a local ticket file.
    Always overwrites; the BA's repo stays the place to amend it."""
    from strata_kb import ticketfetch

    handle = _hub_or_exit(hub, kb_dir)
    try:
        repo, doc, _ = ticketfetch.find(handle, ticket)
        text = ticketfetch.render(handle, ticket)
    except ticketfetch.TicketFetchError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from None
    ticket_id = ticketfetch.split_ref(ticket)[1]
    path = out or Path("docs") / "impl" / ticket_id / "ticket.md"
    if out is None and not path.resolve().is_relative_to(Path("docs/impl").resolve()):
        typer.secho(f"refusing to write outside docs/impl: {path}", fg=typer.colors.RED)
        raise typer.Exit(1)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    except OSError as exc:
        typer.secho(f"could not write '{path}': {exc}", fg=typer.colors.RED)
        raise typer.Exit(1) from None
    typer.echo(f"fetched: {repo}:{doc} §{ticket_id} -> {path}")


@ticket_app.command("export")
def ticket_export(
    source: str = typer.Argument(..., help="Ticket file (or '-' to read from stdin)"),
    out: Path | None = typer.Option(None, "--out", help="Write here instead of stdout"),
) -> None:
    """Tracker-ready body: the ticket without its guidance comments and
    without the BA-internal '## Definition of Ready' and '## Review record'
    sections. '## KB context', '## Dependencies' and '## Technical
    grounding' stay — the Dev reads those. Paste the output into Jira."""
    from strata_kb.ticket import export_body

    if source == "-":
        text = sys.stdin.read()
    else:
        try:
            text = Path(source).read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            typer.secho(
                f"file '{source}' is not valid UTF-8: {exc}", fg=typer.colors.RED
            )
            raise typer.Exit(1) from None
        except OSError as exc:
            typer.secho(f"could not read file '{source}': {exc}", fg=typer.colors.RED)
            raise typer.Exit(1) from None
    body = export_body(text)
    if out is None:
        typer.echo(body, nl=False)
        return
    try:
        out.write_text(body, encoding="utf-8", newline="\n")
    except OSError as exc:
        typer.secho(f"could not write '{out}': {exc}", fg=typer.colors.RED)
        raise typer.Exit(1) from None
    typer.echo(f"wrote {out}")


@ticket_app.command("tidy")
def ticket_tidy(
    files: list[Path] = typer.Argument(
        None, help="With --into: the flat ticket files to move into that folder"
    ),
    tickets_dir: Path = typer.Option(
        Path("tickets"), "--tickets-dir", help="Where ticket files live"
    ),
    into: str | None = typer.Option(
        None,
        "--into",
        help="Folder under tickets/ for FILES that have no parent mission (an epic or feature slug)",
    ),
) -> None:
    """Move flat tickets/*.md into tickets/<mission-id>/ by their
    '> Parent mission:' line; list the rest as 'unsorted'. With --into,
    move the named FILES into tickets/<folder>/ instead. Idempotent, never
    overwrites, no git — commit the renames yourself. Exit 0 after a report."""
    from strata_kb import tickettidy

    if not tickets_dir.is_dir():
        typer.secho(
            f"--tickets-dir '{tickets_dir}' does not exist or is not a directory",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    if files and into is None:
        typer.secho("FILES need --into <folder>", fg=typer.colors.RED)
        raise typer.Exit(1)
    if into is not None:
        if not tickettidy.FOLDER_RE.match(into):
            typer.secho(
                f"--into '{into}' is not a folder name — letters, digits, '.', '_' and '-' only",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)
        if not files:
            typer.secho("--into needs at least one FILE", fg=typer.colors.RED)
            raise typer.Exit(1)
        resolved_dir = tickets_dir.resolve()
        notes: list[str] = []
        flat_files: list[Path] = []
        for f in files:
            if f.is_file() and f.resolve().parent == resolved_dir:
                flat_files.append(f)
            else:
                notes.append(
                    f"skipped {f}: not a flat file directly under {tickets_dir}"
                )
        moves = tickettidy.into_moves(tickets_dir, into, flat_files)
        unsorted: list[Path] = []
    else:
        moves, unsorted, notes = tickettidy.plan_moves(tickets_dir)
    done, conflicts = tickettidy.apply_moves(moves)
    for n in notes:
        typer.echo(f"note: {n}")
    for src, dst in done:
        typer.echo(f"moved: {src} → {dst}")
    for c in conflicts:
        typer.echo(c)
    for p in unsorted:
        typer.echo(f"unsorted: {p} — pass --into <folder>")
    if not (done or conflicts or unsorted or notes):
        typer.echo("nothing to tidy")


@ticket_app.command("check")
def ticket_check(
    source: str = typer.Argument(..., help="Ticket file (or '-' to read from stdin)"),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    hub: str = typer.Option(
        "",
        "--hub",
        envvar="STRATA_KB_HUB",
        help="kb-hub URL/path (empty = config); read first — the -code "
        "document under --kb-dir is the fallback",
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit the report as JSON instead of text"
    ),
    missions_dir: Path | None = typer.Option(
        None,
        "--missions-dir",
        help="Where mission files live, for `[NEW: D<n>]` references to the "
        "parent mission's Technology decisions (default: the ticket file's "
        "sibling 'missions/' directory; a mission missing there is read from "
        "the hub's plan)",
    ),
    heading: str = typer.Option(
        "## Technical grounding",
        "--heading",
        help="Section to check: `## Technical grounding` (ticket) or "
        "`## Services & order` (mission plan; decisions are read from the "
        "same file)",
    ),
) -> None:
    """SA grounding gate: every id in '## Technical grounding' exists in the
    -code document, columns/routes/commands/files match it, `[NEW: D<n>]`
    points at a DECIDED row of the parent mission's Technology decisions,
    and Open decisions is empty. Exit 0 PASS, 1 FAIL."""
    from strata_kb import ticketcheck, ticketfetch, ticketstale

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
            raise typer.Exit(1) from None
        except OSError as exc:
            typer.secho(f"could not read file '{source}': {exc}", fg=typer.colors.RED)
            raise typer.Exit(1) from None

    resolved_missions = _resolve_missions_dir(missions_dir, path)

    hub_cache: list[tuple[HubHandle | None, str]] = []

    def hub_handle() -> tuple[HubHandle | None, str]:
        # One resolution per run: load_doc, load_drift and load_decisions share it.
        if not hub_cache:
            hub_cache.append(_hub_or_reason(hub, kb_dir))
        return hub_cache[0]

    def load_doc(repo: str | None, doc: str) -> ticketcheck.LoadedDoc | None:
        # Hub first: the SA grounded on the hub copy, and a dev repo's local
        # -code is regenerated from its working tree, so its revision is the
        # branch's, never the grounding's. The local copy is the fallback when
        # no hub is reachable or the hub does not hold the doc (the hub's own
        # checkout, a doc not published yet).
        handle, reason = hub_handle()
        if handle is not None:
            found = ticketcheck.load_from_hub(handle.federation_dir, repo, doc)
            if found is not None:
                return found
            reason = "not on the hub"
        local = kb_dir / doc
        if (local / "_manifest.yaml").exists():
            return ticketcheck.load_doc_dir(
                local, f"{local} (local fallback — {reason})"
            )
        if handle is None:
            typer.secho(reason or "hub unavailable", fg=typer.colors.RED)
            raise typer.Exit(1)
        return None

    def load_drift(repo: str | None, doc: str, rev: str) -> list[ResolvedRef] | None:
        # The cited sections as the hub held them when `rev` was published;
        # None (no baseline to diff) without a hub.
        handle, _ = hub_handle()
        if handle is None:
            return None
        ids = ticketstale.cited_ids(text)
        return ticketstale.drift_refs(handle, repo, doc, rev, ids) if ids else []

    def load_decisions(mission_id: str) -> ticketcheck.DecisionTable | None:
        # Local missions/ first; else the mission's plan section on the hub.
        if resolved_missions is not None:
            mission_path = resolved_missions / f"{mission_id}.md"
            try:
                mission_text = mission_path.read_text(encoding="utf-8")
            except FileNotFoundError:
                pass  # no local file: the hub's plan may hold the mission
            except (OSError, UnicodeDecodeError):
                return None  # there but unreadable: not the hub's to override
            else:
                return ticketcheck.parse_decisions(mission_text, str(mission_path))
        handle, _ = hub_handle()
        if handle is None:
            return None
        try:
            hub_text = ticketfetch.render(handle, mission_id)
        except ticketfetch.TicketFetchError:
            return None
        return ticketcheck.parse_decisions(hub_text, f"hub:{mission_id}")

    report = ticketcheck.check(
        text,
        load_doc=load_doc,
        heading=heading,
        load_decisions=load_decisions,
        load_drift=load_drift,
    )
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
        help="Where docs/impl/<ticket-id>/plan.md lives; its `cmd.test:` line "
        "must appear inside a fence in ## Testing. Absent plan = warning.",
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
            raise typer.Exit(1) from None
        except OSError as exc:
            typer.secho(f"could not read file '{source}': {exc}", fg=typer.colors.RED)
            raise typer.Exit(1) from None

    report = lint_body(text, plan_dir=plan_dir)
    if json_output:
        typer.echo(json.dumps(report.to_json()))
    else:
        typer.echo(report.render())
    if not report.passed:
        raise typer.Exit(1)


@plan_app.command("waves")
def plan_waves(
    source: str = typer.Argument(..., help="Plan file (or '-' to read from stdin)"),
    json_output: bool = typer.Option(
        False, "--json", help='Emit {"errors": [...], "waves": [[...]]} instead of text'
    ),
) -> None:
    """Dependency waves of a dev plan: wave n = tasks whose every `Depends on:`
    task sits in an earlier wave. Exit 1 on a shared file without a
    dependency path, a cycle, an unknown task, or a missing `Depends on:`
    line — those plans have no safe parallel order."""
    from strata_kb import planwaves

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
            raise typer.Exit(1) from None
        except OSError as exc:
            typer.secho(f"could not read file '{source}': {exc}", fg=typer.colors.RED)
            raise typer.Exit(1) from None

    errors, waves = planwaves.check(
        planwaves.parse_plan(text), unclosed=planwaves.unclosed_fence(text)
    )
    if json_output:
        typer.echo(json.dumps(planwaves.to_json(errors, waves)))
    else:
        for e in errors:
            typer.echo(f"error: {e}")
        if not errors:
            typer.echo(planwaves.render(waves))
    if errors:
        raise typer.Exit(1)


@impl_app.command("tidy")
def impl_tidy(
    impl_dir: Path = typer.Option(
        Path("docs/impl"), "--impl-dir", help="Where ticket work folders live"
    ),
) -> None:
    """Move flat docs/impl/<id>-{design,plan,context}.md and <id>-review/
    into docs/impl/<id>/. Idempotent, never overwrites, no git — commit the
    renames yourself. Exit 0 after a report."""
    from strata_kb import impltidy

    if not impl_dir.is_dir():
        typer.secho(
            f"--impl-dir '{impl_dir}' does not exist or is not a directory",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    done, conflicts = impltidy.tidy(impl_dir)
    for src, dst in done:
        typer.echo(f"moved: {src} → {dst}")
    for c in conflicts:
        typer.echo(c)
    if not (done or conflicts):
        typer.echo("nothing to tidy")


@mission_app.command("lint")
def mission_lint(
    source: str = typer.Argument(..., help="Mission file (or '-' to read from stdin)"),
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
            raise typer.Exit(1) from None
        except OSError as exc:
            typer.secho(f"could not read file '{source}': {exc}", fg=typer.colors.RED)
            raise typer.Exit(1) from None

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
    if resolved_tickets is None and path is not None and path.parent.name == "missions":
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


@mission_app.command("next")
def mission_next(
    missions_dir: Path = typer.Option(
        Path("missions"), "--missions-dir", help="Where mission files live"
    ),
    tickets_dir: Path | None = typer.Option(
        None,
        "--tickets-dir",
        help="Where ticket files live (default: the missions dir's sibling 'tickets/')",
    ),
    repo_id: str = typer.Option(
        "",
        "--repo-id",
        help="Product repo id whose <repo-id>-svc history marks stories done "
        "(default: derived from the missions' 'Grounded on:' line — <x>-code → <x>-svc)",
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    hub: str = typer.Option(
        "",
        "--hub",
        envvar="STRATA_KB_HUB",
        help="kb-hub URL/path (empty = config); consulted only when the "
        "-svc document is not under --kb-dir",
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit the report as JSON instead of text"
    ),
    from_hub: bool = typer.Option(
        False,
        "--from-hub",
        help="Read the published plan (<ba-repo>-plan) from the hub instead of "
        "missions/ and tickets/: a story with a published ticket is ready, "
        "and to-draft reads 'not ready (no published ticket)'",
    ),
    repo: str = typer.Option(
        "", "--repo", help="With --from-hub: only this BA repo's plan"
    ),
) -> None:
    """Which story next: every backlog story across missions/ as done /
    ready / draft / to-draft / blocked. Done is derived from the hub's
    <repo>-svc history (kb svc note rows); ready and draft from the
    ticket's Definition of Ready checklist. Read-only; exit 0 after a
    report."""
    from strata_kb import missionnext, planrev, planstatus, ticketcheck

    if repo and not from_hub:
        typer.secho("--repo needs --from-hub", fg=typer.colors.RED)
        raise typer.Exit(1)
    if from_hub:
        handle, reason = _hub_or_reason(hub, kb_dir)
        notes = [] if handle is not None else [f"hub unavailable ({reason})"]
        plans, plan_notes = (
            planstatus.hub_plans(handle, repo or None) if handle else ([], [])
        )
        notes += plan_notes
        if handle is not None and not plans:
            notes.append(
                f"no plan for repo '{repo}' on the hub"
                if repo
                else "no <repo>-plan document on the hub"
            )
        results = [s for r in plans for m in r.missions for s in m.stories]
        if json_output:
            typer.echo(json.dumps(missionnext.to_json(results, notes)))
        else:
            labels = {"to-draft": "not ready (no published ticket)"}
            typer.echo(missionnext.render(results, notes, labels))
        return

    for label, d in (("--missions-dir", missions_dir), ("--tickets-dir", tickets_dir)):
        if d is not None and not d.is_dir():
            typer.secho(
                f"{label} '{d}' does not exist or is not a directory",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

    notes: list[str] = []
    parsed: list[missionnext.ParsedMission] = []
    texts: list[str] = []
    for path in sorted(missions_dir.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            notes.append(f"skipped {path}: {exc}")
            continue
        text = unicodedata.normalize("NFC", text)
        parsed_mission = missionnext.parse_mission(text)
        if parsed_mission[0] is None:
            notes.append(f"skipped {path}: no '> Mission:' line")
            continue
        texts.append(text)
        parsed.append(parsed_mission)

    resolved_tickets = (
        tickets_dir if tickets_dir is not None else missions_dir.parent / "tickets"
    )
    # Ticket id → (ticked, total) DoR boxes. `rglob`: tickets live at
    # tickets/<mission-id>/<id>.md since 1.6.0 and flat before it; both read.
    # A stem present under both: sorted() visits the nested copy first
    # (a strict prefix of the flat path's second part sorts before it) —
    # that first copy wins; a repeated stem is noted and skipped rather
    # than silently overwriting it.
    drafted: dict[str, tuple[int, int]] = {}
    ticket_texts: dict[str, str] = {}
    ticket_paths: dict[str, Path] = {}
    if resolved_tickets.is_dir():
        for p in sorted(resolved_tickets.rglob("*.md")):
            if p.stem in ticket_paths:
                notes.append(
                    f"duplicate ticket {p.stem}: read {ticket_paths[p.stem]}, ignored {p}"
                )
                continue
            ticket_paths[p.stem] = p
            try:
                ticket_text = unicodedata.normalize(
                    "NFC", p.read_text(encoding="utf-8")
                )
            except (OSError, UnicodeDecodeError) as exc:
                notes.append(f"skipped ticket {p}: {exc} — read as draft")
                drafted[p.stem] = (0, 0)
                continue
            ticket_texts[p.stem] = ticket_text
            drafted[p.stem] = missionnext.dor_counts(ticket_text)
    else:
        notes.append(
            f"tickets dir '{resolved_tickets}' not found — no story reads as draft or ready"
        )

    grounded = next((g for g in map(missionnext.grounded_doc, texts) if g), None)
    rid: str | None
    doc_id: str | None
    if repo_id:
        rid, doc_id = repo_id, f"{repo_id}-svc"
    elif grounded is not None:
        rid, doc_id = grounded[0], missionnext.svc_doc_id(grounded[1])
    else:
        rid = doc_id = None
    done: set[str] | None = None
    if doc_id is None:
        notes.append("done: unknown (no repo id — pass --repo-id)")
    else:
        local = kb_dir / doc_id
        doc = None
        hub_reason = ""
        handle = None
        try:
            if (local / "_manifest.yaml").exists():
                doc = ticketcheck.load_doc_dir(local, str(local))
            else:
                handle, hub_reason = _hub_or_reason(hub, kb_dir)
                if handle is not None:
                    doc = ticketcheck.load_from_hub(handle.federation_dir, rid, doc_id)
        except ticketcheck.DocLoadError as exc:
            notes.append(f"done: unknown ({exc})")
        else:
            if handle is None and doc is None:
                notes.append(f"done: unknown ({hub_reason or 'hub unavailable'})")
            elif doc is None:
                notes.append(
                    f"done: unknown ({doc_id} not published — the Dev repo has not run "
                    "dev-code-seed, or CI has not published yet)"
                )
        if doc is not None:
            done = missionnext.done_ids_from_history(doc.read_group("history"))

    mission_texts = {m[0]: t for m, t in zip(parsed, texts, strict=True) if m[0]}
    demoted = planrev.demotions(mission_texts, ticket_texts)
    results = missionnext.statuses(parsed, drafted, done, demoted)
    if json_output:
        typer.echo(json.dumps(missionnext.to_json(results, notes)))
    else:
        typer.echo(missionnext.render(results, notes))


@app.command()
def diff(
    doc_id: str = typer.Argument(..., help="Document ID"),
    against: str = typer.Option(
        "HEAD", help="Git rev to diff against, e.g. HEAD, a3f9c21"
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
) -> None:
    """Diff added/removed/changed sections between the worktree and a git rev."""
    from strata_kb.diff import diff_doc, render_diff

    try:
        report = diff_doc(kb_dir, doc_id, against=against)
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from None
    typer.echo(render_diff(report))


def _resolve_reviewer_and_check_approvable(kb_dir: Path, doc_id: str, by: str) -> str:
    """Resolve the `--by` reviewer identity and run the strict-build gate
    (`kb build --strict` across the whole KB) that `kb approve` requires
    before flipping anything to reviewed."""
    from strata_kb import gitio
    from strata_kb.review import (
        check_approvable,
        doc_ids_with_manifest,
        resolve_reviewer,
    )

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
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from None
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
        "",
        "--by",
        help="Reviewer identity 'name <email>' (default: git user.name/email)",
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
) -> None:
    """Mark sections as reviewed (status: summarized → reviewed)."""
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
            reports = approve_all_changed(
                kb_dir, against, doc_id=doc_id or None, by=reviewer
            )
        else:
            reports = [
                approve_sections(kb_dir, doc_id, list(section) or None, by=reviewer)
            ]
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1) from None

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
        None,
        "--context",
        help="File containing the kb-context block (or '-' to read from stdin)",
    ),
    hub: str = typer.Option(
        "", "--hub", envvar="STRATA_KB_HUB", help="kb-hub URL/path (empty = config)"
    ),
    no_refresh: bool = typer.Option(
        False,
        "--no-refresh",
        help="Dev repo: check <repo_id>-code as it is; skip regenerating it first",
    ),
) -> None:
    """Check KB health; pass --context to check citation staleness."""
    from strata_kb import doctor as doctor_mod
    from strata_kb.doctor import check_kind

    # check_kind first: it is the only check that can report a broken
    # config.yaml, and _hub_or_exit reads that same file to find the hub —
    # resolving first would make doctor exit before its own handler runs.
    kind_issues = check_kind(kb_dir)
    if any(i.level == "error" for i in kind_issues):
        for issue in kind_issues:
            typer.secho(f"[{issue.level}] {issue.message}", fg=typer.colors.RED)
        raise typer.Exit(1)
    # Every local reader sees a derived -code. A dev repo whose index.yaml
    # still lists <repo_id>-code but whose directory is absent (fresh clone, or
    # a teammate's pull of the migration's `git rm --cached` commit) must get
    # it back before check_kb runs below -- otherwise check_kb reports a
    # permanent "missing _manifest.yaml" that kb doctor itself could have
    # fixed. _refresh_dev_code is already a no-op for any other kind and for a
    # repo without a -code document.
    if not no_refresh:
        _refresh_dev_code(kb_dir)
    handle = _hub_or_exit(hub, kb_dir)
    context_text = None
    if context is not None:
        context_text = (
            sys.stdin.read()
            if context == "-"
            else Path(context).read_text(encoding="utf-8")
        )
    result = doctor_mod.run(kb_dir, handle, context_text=context_text)
    issues = kind_issues + result.issues

    for issue in issues:
        color = typer.colors.RED if issue.level == "error" else typer.colors.YELLOW
        typer.secho(f"[{issue.level}] {issue.message}", fg=color)
    if any(i.level == "error" for i in issues):
        raise typer.Exit(1)
    if result.stale:
        raise typer.Exit(2)
    typer.echo("kb doctor: OK")
