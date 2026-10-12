"""Hub kind vocabulary: what a federated repo holds (`kb` documents, `ba`
tickets, `dev` code), how a config kind maps onto it, and how a kind is
inferred when none was recorded.

A near-leaf module on purpose (imports only `errors`): `models` and
`federation` import it, so it must not import either (tests/test_layering.py
bans cycles, lazy imports included)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from strata_kb.errors import KbError

if TYPE_CHECKING:
    from strata_kb import models

KB = "kb"
BA = "ba"
DEV = "dev"
HUB_KINDS = (KB, BA, DEV)
MENU: dict[str, str] = {KB: "Document", BA: "Ticket", DEV: "Code"}

# A plan doc `kb plan-ingest` generated: title suffix + `plan`/`generated`
# tags, never its id (a hand-ingested `release-plan` stays a plain document).
# Lives here, not in planingest/planstatus, so inference needs no heavy import.
PLAN_TITLE_SUFFIX = "— plan"

_CONFIG_TO_HUB = {"hub": KB, "child": KB, "ba": BA, "dev": DEV}


class UnknownKindError(KbError):
    """A kind outside the hub vocabulary. A KbError (RuntimeError), not a
    ValueError: pydantic wraps validator ValueErrors, and this must reach the
    CLI as itself."""


class KindMismatchError(KbError):
    def __init__(self, registry_kind: str, repo_kind: str) -> None:
        super().__init__(
            f"registry records kind '{registry_kind}' but the repo is '{repo_kind}'"
        )
        self.registry_kind = registry_kind
        self.repo_kind = repo_kind


def is_plan(title: str, tags: Iterable[str]) -> bool:
    """A document `kb plan-ingest` generated: shown under Plans, never under
    Documents."""
    return title.endswith(PLAN_TITLE_SUFFIX) and {"plan", "generated"} <= set(tags)


def hub_kind(repo_kind: str) -> str:
    if not repo_kind:
        raise UnknownKindError("repo kind is not recorded in .kb/config.yaml")
    try:
        return _CONFIG_TO_HUB[repo_kind]
    except KeyError:
        raise UnknownKindError(f"unknown repo kind '{repo_kind}'") from None


def normalize_kinds(values: Iterable[str] | None) -> list[str]:
    out = {v.strip().lower() for v in values or ()}
    unknown = out - set(HUB_KINDS)
    if unknown:
        raise UnknownKindError(
            f"unknown kind {sorted(unknown)}; expected one of {list(HUB_KINDS)}"
        )
    return sorted(out)


def infer_kind(docs: Iterable[models.IndexEntry]) -> str:
    docs = list(docs)
    if any(is_plan(d.title, d.tags) for d in docs):
        return BA
    if any(d.id.endswith(("-code", "-svc")) for d in docs):
        return DEV
    return KB


def check_publish_kind(registry_kind: str, repo_kind: str) -> str:
    """The kind to record at publish. `repo_kind` is already a hub kind."""
    if registry_kind and repo_kind and registry_kind != repo_kind:
        raise KindMismatchError(registry_kind, repo_kind)
    return registry_kind or repo_kind


def mismatch_message(exc: KindMismatchError, repo: str) -> str:
    """One wording for a registry/repo kind clash, shared by `kb publish` and
    the intake 403."""
    return (
        f"kind mismatch: registry says '{exc.registry_kind}' for {repo}, this "
        f"repo publishes as '{exc.repo_kind}' — fix kind: in "
        "federation/registry.yaml or the repo's .kb/config.yaml"
    )
