from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal, TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

T = TypeVar("T", bound=BaseModel)


class SectionTokens(BaseModel):
    l2: int = 0
    l3: int = 0


class Provenance(BaseModel):
    """Which runner/model/prompt wrote a section's summaries, and when.
    runner "none" = no LLM call (table-only / brief sections)."""

    runner: str
    model: str = ""
    effort: str = ""
    prompt_sha: str = ""
    at: str = ""


class ReviewRecord(BaseModel):
    """SME sign-off: who, when, and the sha256 of the L2 slice they approved."""

    by: str
    at: str
    l2_sha256: str


class SectionEntry(BaseModel):
    # extra="forbid", same reason as RegistryEntry below: a plausible
    # operator typo in an authored YAML file (`sumary:` for `summary:`)
    # used to validate cleanly, take the field's default, and publish an
    # empty L1 summary. `kb doctor` reported OK on it (M10). Also read
    # cross-install: nested inside every mirrored _manifest.yaml
    # (Manifest.sections), so a field added here is a wire-compat break
    # for an older reader too -- see FedIndexEntry's comment below.
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    summary: str = ""
    status: Literal["pending", "summarized", "reviewed"] = "pending"
    file: str
    tokens: SectionTokens = Field(default_factory=SectionTokens)
    l3_sha256: str | None = None
    provenance: Provenance | None = None
    reviewed: ReviewRecord | None = None


class IngestConfig(BaseModel):
    chapter_pattern: str
    appendix_pattern: str
    attachment_pattern: str = ""   # "" = default pattern (backward compat)
    used_bookmarks: bool = False


class Manifest(BaseModel):
    # extra="forbid": see SectionEntry. Also read cross-install off a hub's
    # mirrored federation/<repo-id>/ tree (web/api.py's manifest lookup
    # parses the matched holder's mirrored _manifest.yaml through this
    # model) -- see FedIndexEntry's comment below for what that means for
    # adding fields.
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    revision: str = ""
    ingested: date | None = None
    source_sha256: str = ""
    sections: list[SectionEntry] = Field(default_factory=list)
    ingest: IngestConfig | None = None


class IndexEntry(BaseModel):
    # extra="forbid": see SectionEntry. Also read cross-install: nested
    # inside every mirrored index.yaml (KBIndex.docs), which
    # federation.load_federation parses unconditionally and drops the
    # WHOLE repo on ValidationError -- the worst-case outcome of the four
    # authored models (see FedIndexEntry's comment below).
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    revision: str = ""
    tags: list[str] = Field(default_factory=list)
    summary: str = ""


class LLMConfig(BaseModel):
    runner: Literal["auto", "claude", "copilot", "none"] = "auto"
    model: str = "sonnet-5"
    effort: Literal["low", "medium", "high"] = "high"
    max_workers: int = 5
    timeout: int = 300


class KBIndex(BaseModel):
    # extra="forbid": see SectionEntry. Also read cross-install off a hub's
    # mirrored federation/<repo-id>/ tree (federation.load_federation parses
    # every mirrored index.yaml through this model) -- see FedIndexEntry's
    # comment below for what that means for adding fields.
    model_config = ConfigDict(extra="forbid")

    docs: list[IndexEntry] = Field(default_factory=list)
    llm: LLMConfig = Field(default_factory=LLMConfig)


class FedIndexEntry(BaseModel):
    # NOT extra="forbid", unlike the authored models above. Their own
    # comment draws an "authored vs wire format" line, but that line isn't
    # clean: SectionEntry, Manifest, IndexEntry and KBIndex are ALL read
    # cross-install too, off a hub's mirrored federation/<repo-id>/ tree --
    # federation.load_federation parses every mirrored index.yaml through
    # KBIndex (nesting IndexEntry); web/api.py's manifest lookup parses the
    # matched holder's mirrored _manifest.yaml through Manifest (nesting
    # SectionEntry) -- so a field added to any of them is a wire-compat
    # break for an older reader too, exactly like a field added here. They
    # stay strict anyway: a human types those files before they are ever
    # mirrored, and the typo-catching value (M10) is worth that risk for
    # them. This file differs because nothing types it by hand --
    # build_federation_index generates it -- so there is no typo to catch
    # and nothing offsets the same risk. Whenever a field is added to any
    # of those four, it must be optional with a safe default -- the way
    # every field here already is except repo_id/doc_id, this entry's
    # required identity since the format's first version -- so an older
    # reader that doesn't know the new field yet still loads a newer
    # writer's file instead of dropping the whole repo (see
    # load_federation's ValidationError handling, which does exactly that
    # today).
    repo_id: str
    doc_id: str
    title: str = ""
    revision: str = ""
    tags: list[str] = Field(default_factory=list)
    summary: str = ""
    source_commit: str = ""
    published_at: str = ""
    # sha256 of the snapshot's own content tree (federation/<rid>/**),
    # written by reindex/publish so `kb doctor` at the HUB can detect
    # content edited in place — the hub has no local .kb to diff against
    # (M9 row #18). "" = published before 0.24, not verifiable.
    content_sha256: str = ""


class FederationIndex(BaseModel):
    docs: list[FedIndexEntry] = Field(default_factory=list)


class RegistryEntry(BaseModel):
    """One allowlisted publisher: the repo-id it owns on the hub, and
    optionally the single workflow allowed to publish as it (matched
    against the OIDC `job_workflow_ref` claim).

    extra="forbid": this is the actual authentication boundary (see
    Registry's docstring below) -- without it, a typo'd key inside an
    entry (e.g. `workflw:` for `workflow:`) validates cleanly, silently
    drops the pin the hub owner thought they set, and `authorize` accepts
    any workflow for that repo. I-3: a security control must fail closed
    on a plausible operator typo, not just on a malicious payload.
    """

    model_config = ConfigDict(extra="forbid")

    repo_id: str
    workflow: str = ""


class Registry(BaseModel):
    """federation/registry.yaml — allowlist: 'owner/repo' (or 'group/subgroup/repo')
    -> repo_id on the hub.

    The key is a host-independent git path, not a GitHub-specific 'owner/repo':
    pubgate.owner_repo_from_remote drops the host on purpose (GitLab subgroups
    can nest arbitrarily deep) and pubgate.resolve_identity matches it against
    this registry case-insensitively. That is the more permissive of this
    project's two matchers by design — it is a mistake guard against
    publishing under the wrong repo-id, not an authentication boundary, since
    the remote URL it reads is self-asserted by the publisher. The actual
    authentication boundary is intake.authorize, which matches the OIDC
    `repository` claim against this same registry exactly and
    case-sensitively.

    A value may be the plain repo-id string (the documented default) or a
    {repo_id, workflow} mapping that additionally pins the one workflow
    allowed to publish as that repo-id — read either shape through
    `resolve`, never `repos` directly."""

    model_config = ConfigDict(extra="forbid")

    repos: dict[str, str | RegistryEntry] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _reject_case_colliding_keys(self) -> "Registry":
        """Two keys differing only in case both load as distinct dict
        entries -- whichever iterates last would silently win wherever a
        caller builds a case-insensitive lookup (pubgate.resolve_identity),
        changing which repo-id a near-duplicate key resolves to with no
        warning. On a governed hub that decides what a publisher may claim,
        so refuse the ambiguity here, at load time, naming both keys."""
        seen: dict[str, str] = {}
        for key in self.repos:
            folded = key.casefold()
            if folded in seen:
                raise ValueError(
                    f"registry keys '{seen[folded]}' and '{key}' collide "
                    "case-insensitively -- keep only one"
                )
            seen[folded] = key
        return self

    def resolve(self, repo: str) -> RegistryEntry | None:
        value = self.repos.get(repo)
        if value is None:
            return None
        if isinstance(value, RegistryEntry):
            return value
        return RegistryEntry(repo_id=value)


class AssetsRecord(BaseModel):
    """Relative paths of assets diverted to the object store for one rid.
    The filename's sha256 IS the file content's sha256 (spec A), so hub
    manifests can synthesize exact entries without holding the bytes."""

    assets: list[str] = Field(default_factory=list)


def load_yaml_model(path: Path, model: type[T]) -> T:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return model.model_validate(data)


def save_yaml_model(path: Path, obj: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(
        obj.model_dump(mode="json", exclude_none=True), allow_unicode=True, sort_keys=False
    )
    path.write_text(text, encoding="utf-8", newline="\n")
