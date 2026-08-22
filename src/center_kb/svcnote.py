"""svcnote — `kb svc note`: append-only ticket <-> service history.

Writes `hist.<service>` sections into the curated `<repo_id>-svc` document
(spec Sec6.2/Sec9): one row per ticket in a shared `history.md` (L2) /
`history.raw.md` (L3) file pair, the same way every `svc.*` section shares
`services.md`. There is no sidecar store — idempotency ("re-running for the
same ticket updates rather than duplicates") is achieved by parsing the
existing L2 pipe table back out via `ROW_RE` on every call, upserting by
ticket id, and re-rendering all rows sorted by ticket id.

`hist.*` is a separate section from `svc.*` precisely so appending history
never pushes a just-`reviewed` responsibility section back to `pending`
(spec Sec6.2) — this module never reads or writes a `svc.*` section's own
L2/L3 body, only its manifest entry's `id`, to validate the service exists.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

import yaml
from pydantic import ValidationError

from center_kb import models
from center_kb.codeingest.extractors._mdcells import escape_cell
from center_kb.mdutils import _SEP_ROW_RE, slice_section

# Verbatim per the task brief: used to parse existing rows back out of the
# L2 table so the operation is idempotent without a sidecar store. Matches
# exactly three pipe-delimited cells — the header row ("| Ticket | Title |
# Domain refs |") and the separator row ("| --- | --- | --- |", or a
# Markdown formatter's alignment variant, "|:---|:---:|---:|") have the
# same three-cell shape and DO match this too; they are told apart by
# content in `_parse_existing_rows`, not by a different regex shape.
ROW_RE = re.compile(
    r"^\|\s*(?P<ticket>[^|]+?)\s*\|\s*(?P<title>[^|]*?)\s*\|\s*(?P<refs>[^|]*?)\s*\|\s*$",
    re.M,
)

_L2_HEADER = "| Ticket | Title | Domain refs |"
_L2_SEP = "| --- | --- | --- |"
_BANNER = "> Ticket history, appended by `kb svc note`. Do not edit by hand."

# A byte with no meaning to ROW_RE's `[^|]` groups, used to hide an escaped
# pipe (`\|`, written by `escape_cell`) from the delimiter-matching regex
# while re-parsing a row (fix round 1, Important 1) — see
# `_parse_existing_rows`.
_ESCAPED_PIPE_SENTINEL = "\x00"


def _strip_nul(text: str) -> str:
    """Neutralise a literal NUL byte in caller-supplied text before it
    ever reaches `escape_cell`/`_l3_safe` (final review, Minor 4):
    `escape_cell`'s whitespace-collapse does not touch `\\x00`, so an
    unstripped NUL would both land literally in the published
    `history.md`/`history.raw.md` — worse than merely CLI-unreachable
    (argv cannot carry NUL) once `.kb/` publishes to the shared
    federation hub — and collide with `_ESCAPED_PIPE_SENTINEL` above,
    which is spelled the same `\\x00` for its own escaped-pipe
    bookkeeping: a genuine NUL surviving into the file would be misread
    back as a literal `|` on the very next `kb svc note` call. Stripped
    outright, not substituted — unlike `|` or a backtick, a NUL carries
    no meaning worth preserving in a rendered cell.
    """
    return text.replace("\x00", "")


@dataclass(frozen=True)
class Note:
    ticket: str
    title: str
    refs: tuple[str, ...] = ()


@dataclass
class SvcNoteReport:
    doc_id: str
    section_id: str
    action: str  # "created" | "added" | "updated"
    notes: int


class SvcNoteError(Exception):
    """The curated `-svc` document doesn't exist, the paired `-code`
    document doesn't exist, `service` names no `svc.<service>` section in
    it, one of the two manifests is missing or unreadable, or a `hist.*`
    section recorded in the manifest has no matching heading in the file
    (manifest/file desync — fix round 1, Important 3)."""


def _l3_safe(text: str) -> str:
    """Collapse whitespace (same idiom `escape_cell` uses, and for the same
    reason: an embedded newline could otherwise start what looks like a new
    `field: value` line inside the fenced stanza), then remove — never
    merely escape — a literal `|` or a backtick.

    `escape_cell` (reused below for L2) turns `|` into `\\|`: the pipe BYTE
    survives, backslash-prefixed, which is exactly right for a Markdown
    table cell (the delimiter is neutralised, the character is still
    there) and exactly wrong for L3, where the invariant (task Ruling R5,
    covered by `test_l3_has_no_pipe_table`) is that the character is
    ABSENT so no fenced block can ever be mistaken for spilling out of a
    pipe table. Substituting "/" rather than deleting outright keeps the
    text readable (e.g. a title like "approve A|B corridor" reads as
    "approve A/B corridor") instead of silently fusing two words.

    A backtick gets the same treatment, substituted with "'" (fix round 1,
    Minor 6): `_render_l3_rows` wraps every ticket's stanza in a ```text
    fence, and an un-neutralised triple backtick in a title would close
    that fence early, corrupting every stanza rendered after it.
    """
    text = " ".join(text.split())
    return text.replace("|", "/").replace("`", "'")


def _body_only(heading_and_body: str) -> str:
    """`slice_section()` returns the `## <id> <title>` heading line
    together with the body; splitting the heading back off is what makes
    lifting an old section's body and re-emitting it under a freshly
    rendered heading line round-trip correctly."""
    _heading, _, rest = heading_and_body.partition("\n")
    return rest.lstrip("\n")


def _parse_existing_rows(l2_text: str, section_id: str) -> dict[str, Note]:
    """Parse `hist.<service>`'s existing pipe-table rows back into `Note`s,
    keyed by ticket id — this dict IS the idempotency store; there is no
    sidecar.

    Each line of the section is judged on its own:

    - A separator row — the fixed `| --- | --- | --- |` this module always
      writes, or a Markdown formatter's alignment variant
      (`|:---|:---:|---:|`) — is recognised via mdutils' own
      `_SEP_ROW_RE`, not a home-grown, narrower check (fix round 1, Minor
      1: a hand-rolled "all dashes" test passed a real data row whose
      ticket cell happened to be an alignment marker like `":---"`
      straight through as junk).
    - The header row (`"Ticket"` in the first cell) is skipped by exact
      literal match — it is not a `SEP_ROW_RE` shape (it contains
      letters), so it needs its own check.
    - Every other `|`-shaped line is a data row, matched against `ROW_RE`
      — but first with every escaped pipe (`\\|`, written by
      `escape_cell` when a ticket/title/ref itself contains a literal
      `|`) swapped for `_ESCAPED_PIPE_SENTINEL`, so `ROW_RE`'s `[^|]`
      groups don't mistake it for a column delimiter and refuse to match
      the whole line (fix round 1, Important 1 — this used to silently
      drop such a row on the next call; it no longer does). The swap is
      unambiguous: a genuine delimiter pipe is always preceded by the
      literal `" "` the render template inserts (`f"| {a} | {b} | {c}
      |"`), never by the bare backslash `escape_cell` places immediately
      before an escaped one. The sentinel is restored to `|` in each
      captured group before the `Note` is built.
    """
    rows: dict[str, Note] = {}
    if not l2_text:
        return rows
    section = slice_section(l2_text, section_id)
    if section is None:
        return rows
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        if _SEP_ROW_RE.match(line):
            continue
        m = ROW_RE.match(line.replace("\\|", _ESCAPED_PIPE_SENTINEL))
        if m is None:
            continue
        ticket = m.group("ticket").strip().replace(_ESCAPED_PIPE_SENTINEL, "|")
        if ticket == "Ticket":
            continue
        title = m.group("title").strip().replace(_ESCAPED_PIPE_SENTINEL, "|")
        refs_field = m.group("refs").strip().replace(_ESCAPED_PIPE_SENTINEL, "|")
        # Reconstructed as AT MOST a single-element tuple, deliberately:
        # the original per-ref tuple structure is gone once refs are
        # joined into one cell with ", ", and re-splitting on "," would
        # mis-parse any ref whose own text legitimately contains a comma.
        # A 1-tuple round-trips the joined text byte-for-byte through
        # ", ".join(note.refs) (joining a single element is a no-op)
        # without guessing where the original boundaries were. These
        # reconstructed Notes are only ever re-rendered whole, never
        # inspected element-wise, so this is safe.
        refs = (refs_field,) if refs_field else ()
        rows[ticket] = Note(ticket=ticket, title=title, refs=refs)
    return rows


def _render_l2_rows(notes: list[Note]) -> str:
    """The `| Ticket | Title | Domain refs |` pipe table, sorted rows only
    — sorting is the caller's job (`add_note`) so this stays a pure
    renderer. Every cell goes through the one shared `escape_cell` helper
    (collapse whitespace, then escape `|`) rather than a fresh copy of
    that rule (task Ruling R5: this codebase has had that exact duplicated
    rule defect three times already)."""
    lines = [_L2_HEADER, _L2_SEP]
    for note in notes:
        refs_cell = escape_cell(", ".join(note.refs))
        lines.append(
            f"| {escape_cell(note.ticket)} | {escape_cell(note.title)} | "
            f"{refs_cell} |"
        )
    return "\n".join(lines)


def _render_l3_rows(notes: list[Note]) -> str:
    """One fenced stanza per ticket, `ticket:` / `title:` / `refs:` lines —
    no pipe table anywhere, so the table-integrity invariant (`kb build`'s
    L2/L3 verbatim-echo check) is satisfied by construction, and R5's
    "absent, not escaped" rule is satisfied by `_l3_safe` (which also
    neutralises a backtick — fix round 1, Minor 6 — so a title can never
    close the fence early)."""
    stanzas = [
        f"ticket: {_l3_safe(note.ticket)}\n"
        f"title: {_l3_safe(note.title)}\n"
        f"refs: {_l3_safe(', '.join(note.refs))}"
        for note in notes
    ]
    body = "\n\n".join(stanzas)
    return f"```text\n{body}\n```"


def _load_manifest(path: Path, doc_id: str) -> models.Manifest:
    """Load `<doc_id>/_manifest.yaml`, converting a missing or malformed
    file into a `SvcNoteError` (a red message + exit 1 from the CLI)
    instead of a raw `FileNotFoundError` / `yaml.YAMLError` /
    `ValidationError` traceback (fix round 1, Minor 3).

    Unlike `kb code-ingest`'s own guarded manifest loader — which degrades
    a corrupt `-code` manifest to "no prior state" because that document
    is fully regenerated every run, so losing it is harmless — `add_note`
    both reads AND rewrites the manifest it loads here. Silently treating
    a corrupt one as empty would mean blindly overwriting or discarding
    real curated content with no way to know what was lost, so this
    refuses instead of degrading.
    """
    if not path.exists():
        raise SvcNoteError(f"{doc_id}: {path} does not exist")
    try:
        return models.load_yaml_model(path, models.Manifest)
    except (yaml.YAMLError, OSError, UnicodeDecodeError, ValidationError) as exc:
        raise SvcNoteError(f"{doc_id}: could not read {path} ({exc})") from exc


def add_note(kb_dir: Path, repo_id: str, service: str, note: Note) -> SvcNoteReport:
    # Fix round 1, Important 1(a): normalize the incoming ticket the same
    # way `_parse_existing_rows` normalizes one read back (`.strip()` on
    # each captured group) — otherwise a whitespace-padded id (a pasted or
    # shell-quoted ticket, e.g. "M-1 ") never matches its own already-
    # written row on the next call: the key spaces disagree, `action`
    # reports "added" instead of "updated", and the row duplicates every
    # time it is renoted.
    #
    # Final review, Minor 4: strip a literal NUL from every field at this
    # same entry point, before any of ticket/title/refs reaches
    # `escape_cell`/`_l3_safe` or the sentinel-based re-parse below.
    note = replace(
        note,
        ticket=_strip_nul(" ".join(note.ticket.split())),
        title=_strip_nul(note.title),
        refs=tuple(_strip_nul(r) for r in note.refs),
    )

    # Final review, Minor 5: an empty (post-normalisation) ticket renders
    # as an all-blank row (`|  |  |  |` when title/refs are also empty)
    # that `_SEP_ROW_RE` cannot tell apart from the table's own separator
    # row, so it is silently dropped as junk on the very next call —
    # producing a permanent junk row this command can never repair, and
    # mislabelling that next call's own `action` along the way. An empty
    # TITLE carries no equivalent failure mode (it can never by itself
    # produce an all-separator-shaped row, since the ticket cell still
    # holds the real, non-blank id), so it is deliberately left
    # unvalidated here — rejecting it would be a policy choice this
    # finding does not require.
    if not note.ticket:
        raise SvcNoteError(
            "--ticket must not be empty — an empty ticket renders as an "
            "all-blank row indistinguishable from the table's own "
            "separator row, so it would be silently dropped as junk on "
            "the next `kb svc note` call for this service"
        )

    doc_id = f"{repo_id}-svc"
    doc_dir = kb_dir / doc_id
    if not doc_dir.is_dir():
        raise SvcNoteError(
            f"{doc_id} does not exist at {doc_dir} — run `kb code-ingest "
            "--scaffold-svc` first to bootstrap the curated service document"
        )
    manifest_path = doc_dir / "_manifest.yaml"

    # Validate the service against the paired -code document (step 2): a
    # typo must not invent a service. `svc.<name>` deliberately collides
    # across -code and -svc (spec Sec6.2) as the join key, and a name over
    # 40 characters carries an unconditional, opaque 6-hex-character hash
    # suffix (services.py's `_assign_slugs()`) — Ruling R1 requires this
    # error to say so, since this command is the one place a human types
    # that id by hand.
    #
    # Fix round 1, Minor 3(a): the -code document itself might not exist
    # at all — checked explicitly, and named as such, rather than falling
    # through to "unknown service" (an accurate-sounding but misleading
    # diagnosis when the real problem is that nothing has been ingested
    # yet).
    code_doc_id = f"{repo_id}-code"
    code_doc_dir = kb_dir / code_doc_id
    if not code_doc_dir.is_dir():
        raise SvcNoteError(
            f"{code_doc_id} does not exist at {code_doc_dir} — the paired "
            "-code document must exist first (run `kb code-ingest`) before "
            f"'{service}' can be validated"
        )
    code_manifest = _load_manifest(code_doc_dir / "_manifest.yaml", code_doc_id)
    known_ids = {s.id for s in code_manifest.sections}
    svc_section_id = f"svc.{service}"
    if svc_section_id not in known_ids:
        # Final review, Important 1(b): two honest, independent causes,
        # not one misdiagnosis swapped for another. (1) A typo — the
        # original guidance: copy the real id verbatim, mind the opaque
        # hash suffix on a name over 40 characters. (2) The ticket added
        # or renamed a service, and this repo's *committed* `-code` is
        # simply stale: `kb-code.yml` regenerates and publishes `-code`
        # on the hub on every push to the default branch, with no
        # commit-back step to this repo's own working tree, so the
        # committed copy is a seed-time (or last-checkout-time) snapshot
        # — nothing here ever refreshes it. Cause (2) is the far more
        # likely one whenever the service name is real but new, so it is
        # named explicitly rather than left for the typo guidance to
        # imply on its own.
        raise SvcNoteError(
            f"unknown service '{service}' — no svc.{service} section in "
            f"{code_doc_id} (list the real ids in "
            f"{code_doc_id}/_manifest.yaml or services.md and copy one "
            "verbatim — a service name longer than 40 characters carries "
            "an opaque 6-hex-character hash suffix, e.g. "
            "'-a1b2c3', that must be copied exactly, never retyped. "
            "If the ticket added or renamed a service, this is likely "
            f"not a typo: this repo's committed {code_doc_id} is a "
            "snapshot that CI regenerates and publishes on the hub on "
            "every push but never writes back here — run `kb "
            "code-ingest` to refresh it locally, then retry)"
        )

    # Fix round 1, Minor 3(b): guarded load, not a raw `models.
    # load_yaml_model` call — a missing or malformed -svc manifest must
    # surface as a red message + exit 1, not a traceback.
    manifest = _load_manifest(manifest_path, doc_id)
    section_id = f"hist.{service}"

    l2_path = doc_dir / "history.md"
    l3_path = doc_dir / "history.raw.md"
    old_l2_text = l2_path.read_text(encoding="utf-8") if l2_path.exists() else ""
    old_l3_text = l3_path.read_text(encoding="utf-8") if l3_path.exists() else ""

    # Fix round 1, Important 3: a hist.* section already recorded in the
    # manifest MUST have a matching heading in both history.md and
    # history.raw.md. `kb build` cannot catch a manifest entry whose row
    # content silently vanished — it only checks that the heading exists
    # and the summary is non-empty (build.py:50-56) — so a manifest still
    # claiming "N tickets recorded" for a heading the file no longer has
    # would otherwise pass `kb build` clean while being flatly wrong.
    # Checked against every hist.* entry the manifest already has, not
    # only the one this call is about (the sibling half of the same
    # defect: noting service B must never paper over service A's
    # already-lost history), and before anything is written.
    desynced = sorted(
        entry.id
        for entry in manifest.sections
        if entry.id.startswith("hist.")
        and (
            slice_section(old_l2_text, entry.id) is None
            or slice_section(old_l3_text, entry.id) is None
        )
    )
    if desynced:
        raise SvcNoteError(
            f"{doc_id}: history section(s) {desynced} are recorded in "
            "_manifest.yaml but have no matching heading in history.md / "
            "history.raw.md — the manifest and the file have gone out of "
            "sync; restore the file(s) by hand or remove the stale "
            "manifest entry before re-running `kb svc note`"
        )

    existing_entry = next(
        (s for s in manifest.sections if s.id == section_id), None
    )
    rows = _parse_existing_rows(old_l2_text, section_id)

    if existing_entry is None:
        action = "created"
    elif note.ticket in rows:
        action = "updated"
    else:
        action = "added"

    rows[note.ticket] = note
    ordered = [rows[t] for t in sorted(rows)]

    title = f"{service} — ticket history"
    new_entry = models.SectionEntry(
        id=section_id,
        title=title,
        summary=f"Tickets that touched {service}: {len(ordered)} recorded.",
        status="summarized",
        file="history",
        # Preserve prior token counts (like `kb code-ingest` preserves them
        # by section id, spec Sec6.4) so a note doesn't zero out what the
        # last `kb build` computed; `kb build` recomputes them anyway, so
        # this is purely to avoid pointless churn, not a correctness need.
        tokens=(
            existing_entry.tokens
            if existing_entry is not None
            else models.SectionTokens()
        ),
    )

    if existing_entry is None:
        sections = [*manifest.sections, new_entry]
    else:
        sections = [
            new_entry if s.id == section_id else s for s in manifest.sections
        ]

    # Every hist.* section shares this one history.md/history.raw.md file
    # pair, exactly the way every svc.* section shares services.md (spec
    # Sec6.2/Sec8: `file="history"` is a fixed literal, not per-service).
    # Sibling services' already-recorded sections must round-trip
    # untouched — lifted verbatim from the OLD files via slice_section,
    # never re-derived, so a note for one service can never lose another
    # service's history. The desync guard above already proved every
    # sibling id here has a real heading in both old files, so `slice_
    # section` returning None here would mean the guard's own logic is
    # wrong, not a state this branch is meant to paper over — the "" /
    # None fallback below is defense in depth only, never expected to fire.
    sibling_ids = sorted(
        s.id for s in sections if s.id.startswith("hist.") and s.id != section_id
    )
    titles_by_id = {section_id: title}
    bodies_by_id = {section_id: (_render_l2_rows(ordered), _render_l3_rows(ordered))}
    for sid in sibling_ids:
        sibling_entry = next(s for s in sections if s.id == sid)
        titles_by_id[sid] = sibling_entry.title
        l2_slice = slice_section(old_l2_text, sid)
        l3_slice = slice_section(old_l3_text, sid)
        bodies_by_id[sid] = (
            _body_only(l2_slice) if l2_slice is not None else "",
            _body_only(l3_slice) if l3_slice is not None else "",
        )

    l2_text = _render_group_text(doc_id, bodies_by_id, titles_by_id, level=0)
    l3_text = _render_group_text(doc_id, bodies_by_id, titles_by_id, level=1)

    doc_dir.mkdir(parents=True, exist_ok=True)
    l2_path.write_text(l2_text, encoding="utf-8", newline="\n")
    l3_path.write_text(l3_text, encoding="utf-8", newline="\n")

    manifest.sections = sections
    models.save_yaml_model(manifest_path, manifest)

    return SvcNoteReport(
        doc_id=doc_id, section_id=section_id, action=action, notes=len(ordered)
    )


def _render_group_text(
    doc_id: str,
    bodies_by_id: dict[str, tuple[str, str]],
    titles_by_id: dict[str, str],
    level: int,
) -> str:
    """Render the whole `history` group file (`level=0` -> L2, `level=1`
    -> L3): a fixed `# <doc_id>` / banner header, then one `## <sid>
    <title>` section per id, sorted — every `hist.*` id known this run,
    not only the one just noted."""
    lines: list[str] = [f"# {doc_id}", "", _BANNER, ""]
    for sid in sorted(bodies_by_id):
        body = bodies_by_id[sid][level]
        lines.append(f"## {sid} {titles_by_id[sid]}")
        lines.append("")
        lines.extend(body.splitlines())
        lines.append("")
    text = "\n".join(lines)
    return text.rstrip("\n") + "\n"
