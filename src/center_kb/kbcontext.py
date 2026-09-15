from __future__ import annotations

import difflib
import re
from typing import TYPE_CHECKING

import yaml
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from center_kb.federation import FederatedRepo
    from center_kb.hub import HubHandle


class KBContextError(ValueError):
    """kb-context block is missing or malformed."""


class KBRefNotFoundError(KBContextError):
    """A ref does not resolve to any known section in the local KB or hub."""


class UnknownTagError(KBContextError):
    """A tag passed explicitly to `kb context new` is not published by any
    document on the hub federation."""


class KBRef(BaseModel):
    doc_id: str
    section_id: str
    repo_id: str | None = None

    def __str__(self) -> str:
        prefix = f"{self.repo_id}:" if self.repo_id else ""
        return f"{prefix}{self.doc_id} §{self.section_id}"


class KBContext(BaseModel):
    version: str
    hub_version: str | None = None
    refs: list[KBRef]
    tags: list[str] = Field(default_factory=list)


# An HTML comment. `kbcontext` cannot import `lintcore.HTML_COMMENT_RE`
# (lintcore imports kbcontext, so the reverse import would cycle) — kept
# local rather than moved to a new shared module for one constant.
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)

_REF_RE = re.compile(
    r"^(?:(?P<repo>[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*):)?"
    r"(?P<doc>[A-Za-z0-9][A-Za-z0-9._-]*)\s+§?(?P<sec>\S+)$"
)
_KEY_RE = re.compile(r"^(?P<indent>\s*)kb-context:\s*$")


def parse_ref(text: str) -> KBRef:
    m = _REF_RE.match(" ".join(text.split()))
    if not m:
        raise KBContextError(
            f"ref '{text}' has the wrong format — expected '<doc-id> §<section-id>', e.g. 'arinc-424 §5.3'"
        )
    return KBRef(
        doc_id=m.group("doc"), section_id=m.group("sec"), repo_id=m.group("repo")
    )


def _collect_tags(bucket: dict[str, str], tags: list[str]) -> None:
    """Fold `tags` into a lowercase-keyed `bucket`, first spelling winning.

    The one place the tag-normalisation rule is written: `.strip()` only,
    lowercase key, canonical (as-published) value, blanks dropped. Both
    `tag_vocabulary` and `derive_tags` build the same kind of bucket over
    different inputs, so they call this instead of each writing the rule —
    the same reason `suggest_tags` is the only caller of `difflib` (see its
    docstring for the R5 duplicated-rule note this avoids repeating).
    """
    for tag in tags:
        cleaned = tag.strip()
        if cleaned:
            bucket.setdefault(cleaned.lower(), cleaned)


def tag_vocabulary(repos: list["FederatedRepo"]) -> dict[str, str]:
    """Every tag published anywhere on the federation: lowercase key ->
    canonical spelling as recorded in that repo's `index.yaml`.

    This IS the vocabulary a kb-context block may draw on. Tags live only at
    document level (`models.IndexEntry.tags`) — `SectionEntry` and `Manifest`
    have no tags field — so there is nothing finer to consult.

    Keyed lowercase because `searchdb.py:350` indexes tags as
    `{t.strip().lower() for t in doc.tags}`: casing has no downstream effect,
    so validation must not care about it either. How a tag is cleaned and
    which spelling wins on a clash is `_collect_tags`'s rule; for this
    function the clash order is `federation.iter_entry_dirs()`'s
    deterministic name-ascending DFS, so two repos spelling one tag
    differently resolve the same way on every run.
    """
    vocab: dict[str, str] = {}
    for repo in repos:
        for doc in repo.index.docs:
            _collect_tags(vocab, doc.tags)
    return vocab


def derive_tags(repos: list["FederatedRepo"], refs: list[KBRef]) -> list[str]:
    """The tags of the documents these refs pin — the default content of a
    block's `tags:` line, so no agent ever chooses one.

    Granularity is the DOCUMENT, not the section, because that is the only
    level at which tags exist. A ref whose document publishes no tags, whose
    document is absent from its repo's `index.yaml`, or which has not been
    repo-qualified yet contributes nothing, and none of those is an error:
    `build_context_block` has already proved every ref resolves before
    calling this.

    Sorted by lowercase key so the rendered block is byte-stable regardless
    of the order the caller listed `--refs`. A derived block must not change
    because someone reordered their refs — but the spelling must also match
    `kb tags` and `tag_vocabulary`, which resolve a clash by
    `federation.iter_entry_dirs()`'s DFS order, not by which ref a caller
    happened to list first. So this collects only the lowercase KEYS from
    the refs' documents, then resolves every spelling through
    `tag_vocabulary(repos)` — the one authority for which spelling wins.
    Folding each ref's tags into the result as they are encountered instead
    (the previous implementation) would let whichever ref comes first pick
    the spelling, which can disagree with `tag_vocabulary` whenever two
    repos spell one tag differently. Tag cleaning is `_collect_tags`'s rule
    and is not restated here.
    """
    vocab = tag_vocabulary(repos)
    by_rid = {repo.meta.repo_id: repo for repo in repos}
    keys: set[str] = set()
    for ref in refs:
        repo = by_rid.get(ref.repo_id) if ref.repo_id else None
        if repo is None:
            continue
        for doc in repo.index.docs:
            if doc.id == ref.doc_id:
                keys.update(t.strip().lower() for t in doc.tags if t.strip())
    return [vocab[key] for key in sorted(keys)]


def suggest_tags(tag: str, vocab: dict[str, str]) -> list[str]:
    """Canonical spellings of the vocabulary entries nearest to `tag` — the
    "did you mean" list behind BOTH `kb context new`'s rejection message and
    `kb ticket lint`'s.

    One home, deliberately. Writing the same `difflib` call in `kbcontext`
    and again in `lintcore` would reintroduce the duplicated-rule defect
    this codebase has already shipped three times (see the R5 note in
    `svcnote.py:190-196`) — the same reason the tag rule itself lives in
    exactly one module.
    """
    return [
        vocab[key]
        for key in difflib.get_close_matches(tag.strip().lower(), list(vocab), n=3)
    ]


def _extract_block(text: str) -> str:
    """Extract the first kb-context block by indent — tolerates a block embedded in a ticket."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = _KEY_RE.match(line)
        if not m:
            continue
        indent = len(m.group("indent"))
        block = [line[indent:]]
        for follow in lines[i + 1 :]:
            if not follow.strip():
                block.append("")
                continue
            cur = len(follow) - len(follow.lstrip())
            if cur <= indent:
                break
            block.append(follow[indent:])
        return "\n".join(block)
    raise KBContextError("no 'kb-context:' block found in the text")


def _count_blocks(text: str) -> int:
    """How many bare 'kb-context:' key lines the text carries, at any
    indent — the same line `_extract_block` anchors on.

    HTML comments are stripped first: a commented-out old pin left in
    place (a BA re-running `kb context new` and leaving the previous
    block commented out instead of deleting it) is not rendered, so it
    is not a second block either — only a REAL, visible block counts."""
    return sum(
        1
        for line in _HTML_COMMENT_RE.sub("", text).splitlines()
        if _KEY_RE.match(line)
    )


def parse(text: str) -> KBContext:
    count = _count_blocks(text)
    if count > 1:
        raise KBContextError(
            f"{count} 'kb-context:' blocks found — a document pins exactly "
            "one. Delete the extra block by hand; never re-run "
            "`kb context new`, which would rewrite the pinned version and "
            "falsify when the document was grounded"
        )
    block = _extract_block(text)
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError as exc:
        raise KBContextError(f"kb-context block is not valid YAML: {exc}") from exc
    payload = (data or {}).get("kb-context")
    if not isinstance(payload, dict):
        raise KBContextError("kb-context block is empty or malformed")
    version = str(payload.get("version") or "").strip()
    if not version:
        raise KBContextError("kb-context is missing 'version' (commit hash when the BA wrote it)")
    hub_version_raw = payload.get("hub_version")
    hub_version = str(hub_version_raw).strip() if hub_version_raw else None
    raw_refs = payload.get("refs") or []
    if not raw_refs:
        raise KBContextError("kb-context is missing 'refs' — must cite at least 1 section")
    if not isinstance(raw_refs, list):
        raise KBContextError(
            "'refs' must be a YAML list (one ref per line '- ...')"
        )
    refs = [parse_ref(str(r)) for r in raw_refs]
    raw_tags = payload.get("tags") or []
    if not isinstance(raw_tags, list):
        raise KBContextError(
            "'tags' must be a YAML list (one tag per line '- ...' or [a, b] form)"
        )
    tags = [str(t) for t in raw_tags]
    return KBContext(version=version, hub_version=hub_version, refs=refs, tags=tags)


def render(ctx: KBContext) -> str:
    lines = ["kb-context:", f'  version: "{ctx.version}"']
    if ctx.hub_version:
        lines.append(f'  hub_version: "{ctx.hub_version}"')
    lines.append("  refs:")
    lines += [f"    - {ref}" for ref in ctx.refs]
    if ctx.tags:
        lines.append(f"  tags: [{', '.join(ctx.tags)}]")
    return "\n".join(lines)


def _age_label(hub: "HubHandle") -> str:
    """The one place a hub's cache age is rendered as text, so the stale-hub
    wording in a warning and in `_unknown_tag_message` cannot drift apart.

    `age_seconds == 0.0` falls through to "unknown age" — a pre-existing
    quirk of the truthiness check this helper simply preserves rather than
    fixes. It is safe in practice, not because 0.0 never occurs (`hub.py:90`
    returns exactly that on a successful pull), but because both call sites
    here are inside `if hub.stale:`, and the only constructor that sets
    `stale=True` (`hub.py:97`) passes either `None` or a value already
    proven greater than `_ttl()` — never 0.0. Correcting the truthiness
    check anyway is out of this task's scope.
    """
    return f"~{hub.age_seconds:.0f}s" if hub.age_seconds else "unknown age"


def _unknown_tag_message(
    unknown: list[str], vocab: dict[str, str], hub: "HubHandle"
) -> str:
    """One message naming every unknown tag with its nearest real neighbours,
    plus — stated separately, never implied — the two situations that are not
    a typo at all: a KB that publishes no tags yet, and a hub cache lagging
    behind a tag that really was published."""
    parts: list[str] = []
    for tag in unknown:
        cleaned = " ".join(tag.split())
        close = suggest_tags(tag, vocab)
        hint = f" (did you mean {', '.join(close)}?)" if close else ""
        parts.append(f"'{cleaned}'{hint}")
    msg = "tag not published by any document on the hub federation: " + "; ".join(parts)
    if not vocab:
        msg += (
            " — the KB has no tags at all yet, or the hub mirror is empty or "
            "unreadable: drop --tags to have them derived from the pinned "
            "refs' documents, or ingest with `kb ingest --tags` first"
        )
    else:
        msg += (
            " — list the real ones with `kb tags`, or omit `--tags` to have "
            "them derived from the pinned refs' documents"
        )
    if hub.stale:
        msg += (
            f" [the hub cache is stale ({_age_label(hub)}), so a tag published "
            "very recently may be missing from it — this may not be a typo]"
        )
    return msg


def build_context_block(
    hub: "HubHandle",
    refs: list[str],
    tags: list[str] | None = None,
) -> tuple[str, str | None]:
    """Validate refs against the hub federation, auto-qualify repo id, pin hub HEAD.

    Returns (block_text, stale_warning): stale_warning is a one-line warning
    when the hub cache is stale (offline), otherwise None.
    """
    from center_kb import gitio, models
    from center_kb.federation import load_federation
    from center_kb.query import AmbiguousDocError

    ref_list = [parse_ref(r) for r in refs if r.strip()]
    if not ref_list:
        raise KBContextError(
            "--refs is empty — need at least 1 ref, e.g. 'arinc-kb:arinc-424 §5.3'"
        )

    repos = load_federation(hub.federation_dir)
    by_rid = {r.meta.repo_id: r for r in repos}
    bad: list[str] = []
    for ref in ref_list:
        if ref.repo_id is None:
            holders = [
                r.meta.repo_id
                for r in repos
                if (r.kb_dir / ref.doc_id / "_manifest.yaml").exists()
            ]
            if len(holders) > 1:
                raise KBContextError(str(AmbiguousDocError(ref.doc_id, holders)))
            if not holders:
                bad.append(str(ref))
                continue
            ref.repo_id = holders[0]
        repo = by_rid.get(ref.repo_id)
        found = False
        if repo is not None:
            manifest_path = repo.kb_dir / ref.doc_id / "_manifest.yaml"
            if manifest_path.exists():
                manifest = models.load_yaml_model(manifest_path, models.Manifest)
                found = any(s.id == ref.section_id for s in manifest.sections)
        if not found:
            bad.append(str(ref))
    if bad:
        raise KBRefNotFoundError(
            f"Ref could not be resolved in the hub federation: {', '.join(bad)}"
        )

    version = gitio.head_commit(gitio.git_root(hub.root))
    warning = None
    if hub.stale:
        warning = f"[warn] hub cache is stale ({_age_label(hub)}) — the pinned hash may lag the hub"
    requested: dict[str, str] = {}
    _collect_tags(requested, tags or [])
    if requested:
        # Caller override: validated, never trusted. Canonical spelling from
        # the index; cleaning and case-dedupe are _collect_tags' rule, not
        # restated here. dict insertion order preserves the caller's order.
        vocab = tag_vocabulary(repos)
        unknown = [spelling for key, spelling in requested.items() if key not in vocab]
        if unknown:
            raise UnknownTagError(_unknown_tag_message(unknown, vocab, hub))
        block_tags = [vocab[key] for key in requested]
    else:
        # The default: derived from what the refs actually pin, so no agent
        # ever picks a tag.
        block_tags = derive_tags(repos, ref_list)
    ctx = KBContext(version=version, refs=ref_list, tags=block_tags)
    return render(ctx), warning
