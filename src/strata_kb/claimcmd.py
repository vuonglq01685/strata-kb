"""`kb claim` logic: take, update, release and list ticket claims on the hub.

Each function returns the CLI exit code: 0 ok, 1 error, 3 taken or lost.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import typer

from strata_kb import claimclient
from strata_kb.claimclient import ClaimLostError, ClaimTakenError, LocalClaims

EXIT_TAKEN_OR_LOST = 3


def _age(last_seen: str) -> str:
    """Whole minutes since the hub-clock `last_seen`, against the local clock."""
    try:
        seen = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
    except ValueError:
        return "unknown"
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=UTC)
    return f"{max(0, round((datetime.now(UTC) - seen).total_seconds() / 60))} min"


def _no_claim(ticket: str) -> int:
    typer.echo(
        f"no claim held for {ticket} on this machine — run kb claim take {ticket}"
    )
    return 1


def _lost(local: LocalClaims, ticket: str, exc: ClaimLostError) -> int:
    local.drop(ticket)
    typer.echo(f"lost: {exc.close_reason} by {exc.closed_by}")
    return EXIT_TAKEN_OR_LOST


def take(kb_dir: Path, root: Path, ticket: str, as_name: str | None) -> int:
    holder = as_name or claimclient.holder_name(root)
    local = LocalClaims(kb_dir)
    known = local.get(ticket)
    try:
        claim, token = claimclient.from_env().take(
            ticket, holder, known[1] if known else None
        )
    except ClaimTakenError as exc:
        c = exc.claim
        typer.echo(
            f"taken by {c.get('holder', '?')} ({c.get('phase', '?')}, "
            f"updated {_age(str(c.get('last_seen', '')))} ago)"
        )
        return EXIT_TAKEN_OR_LOST
    local.put(ticket, claim["id"], token)
    typer.echo(f"claimed {ticket} as {holder}")
    return 0


def update(
    kb_dir: Path,
    ticket: str,
    phase: str | None,
    pr: str | None,
    stopped: str | None,
    active: bool,
) -> int:
    if stopped is not None and active:
        typer.echo("--stopped and --active are mutually exclusive")
        return 1
    local = LocalClaims(kb_dir)
    held = local.get(ticket)
    if held is None:
        return _no_claim(ticket)
    fields: dict[str, str] = {}
    if phase is not None:
        fields["phase"] = phase
    if pr is not None:
        fields["pr"] = pr
    if stopped is not None:
        fields.update(state="stopped", stop_reason=stopped)
    if active:
        fields["state"] = "active"
    try:
        claimclient.from_env().update(held[0], held[1], **fields)
    except ClaimLostError as exc:
        return _lost(local, ticket, exc)
    return 0


def release(kb_dir: Path, ticket: str, reason: str) -> int:
    local = LocalClaims(kb_dir)
    held = local.get(ticket)
    if held is None:
        return _no_claim(ticket)
    try:
        claimclient.from_env().release(held[0], held[1], reason)
    except ClaimLostError as exc:
        return _lost(local, ticket, exc)
    local.drop(ticket)
    return 0


def list_(kb_dir: Path, as_json: bool) -> int:
    claims = claimclient.from_env().held()
    if as_json:
        typer.echo(json.dumps(claims))
        return 0
    for c in claims:
        typer.echo(
            f"{c.get('ticket', '')}\t{c.get('holder', '')}\t{c.get('phase', '')}\t"
            f"{c.get('state', '')}\t{c.get('last_seen', '')}"
        )
    return 0
