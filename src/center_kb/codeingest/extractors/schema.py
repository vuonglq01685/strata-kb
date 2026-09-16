"""schema extractor — `db.<table>` from migration files, ORM schemas, and
(only when explicitly asked) a SQLite file.

Five readers — SQL migrations, Prisma, Alembic, Entity Framework Core, and
an explicit SQLite database — each surface `TableRecord`s from one kind of
evidence. Every reader degrades rather than raises: a malformed or
unreadable file becomes a warning naming the file, and every other reader
still runs (matching `deps.py`, `services.py` and `commands.py`'s
discipline).

**Recognised DDL, and why (spec §3.9).** Only `CREATE TABLE` and `ALTER
TABLE ... ADD COLUMN` are recognised by the `sql` reader. Every other
`ALTER TABLE` form — `RENAME`, `DROP`, `ALTER COLUMN`, `ADD CONSTRAINT`,
`ADD INDEX`, etc. — either warns (`RENAME`/`DROP` via `UNSUPPORTED_RE`;
`ADD CONSTRAINT`/`ADD INDEX` via `_ADD_NON_COLUMN_RE`, since either would
otherwise be misread as `ADD COLUMN` and fabricate a phantom column) or is
quietly left unrecognised (any other ALTER form outside the brief's
scope). This is a deliberate, narrow slice: the emitted `db.<table>`
sections are meant to be *ground truth* — every column shown is one this
code actually saw declared, never one it inferred — so a Dev agent reading
this document can trust it completely, at the cost of not describing every
DDL dialect in existence. SQL comments (`-- ...` and possibly-nested
`/* ... */`) are stripped from migration text before any of this parsing
runs, and a top-level entry is only ever treated as a table constraint
(dropped from the column list) when it starts with one of those keywords
at a real word boundary — a column literally named `unique_code` or
`constraint_name` is still a column.

**Quoting, and the dual-scan disagreement guard (Rulings R36 → R38).**
Comment-stripping and column-splitting both run every quote/backtick/
bracket span through the shared `_scan_sql` scanner (below). Standard SQL
(SQLite, Postgres with `standard_conforming_strings=on` — the default
since 9.1 — MSSQL, Oracle) treats `\\` inside a `'`/`"` literal as an
ordinary character; MySQL treats it as an escape. No single tracker can
be correct for both at once, so `_scan_sql` takes a `backslash_escapes`
flag and `_resolve_scan` (Ruling R38, superseding R36's original
runaway-to-EOF-only guard) runs it *twice* per file/body, once each way,
and picks a reading by this order: if exactly one reading is clean (does
not run off the end of the text still inside an open quote/bracket/
comment — a *desync*), use it, no warning; if both are clean and agree,
use it, no warning; if both are clean but disagree, the dialect is
genuinely ambiguous from this text alone — warn, naming the file, and
take the backslash-as-literal (standard SQL) reading, since that is every
engine in this set except MySQL; if both desync, warn and fall back to a
quote-blind split. R36's original guard only asked "did a span run off
the end?", which cannot distinguish MySQL's `'it\'s'` (needs the escape
reading) from standard SQL's `'\'` followed by an ordinary English
contrastive apostrophe in a later comment (needs the literal reading,
and *looks* clean to the escape reading too — just wrong) — hence the
disagreement check. Separately, a bracket span additionally aborts as a
desync if its content ever contains a `)` with no matching `(` inside
that same span: a real `[...]`-quoted identifier or Postgres array
suffix never contains an unbalanced paren, so this is reserved for the
case where a bare `[` in an expression (not a real identifier quote) was
about to swallow everything up to some unrelated, later `]`. Ground truth
that occasionally warns instead of answering is still ground truth;
ground truth that silently drops or fabricates a column is not.

**Ruling R3 (controller) — the `--db` detection gap is B8's, not this
task's.** `SchemaExtractor.detect(root)` has no way to see
`opts.db_paths` (the `Extractor` protocol never passes `opts` to
`detect()`), so on a repo with *no* migration/prisma/alembic/EF source,
`detect()` returns `False`, `core.run()` skips calling `extract()`
entirely, and an explicit `--db` path is silently never read. Task B8
closes this by making `run()` treat `schema` as detected whenever
`opts.db_paths` is non-empty. Nothing here works around it — a caller
that wants `--db`-only ingestion to work must go through B8's fix, not
this module.

**`SchemaExtractor.detect(self, root)` cannot see `opts.kb_dir`** — same
structural exception `deps.py` and `commands.py` document: the `Extractor`
protocol's `detect()` is never passed `opts`, so this is the one walk in
this module that calls the glob helper without a `kb_dir` to prune. Every
walk inside `extract()` does thread `opts.kb_dir` through (Ruling R24).

**Reader precedence.** When two *readers* claim the same table name, the
first one in `_READER_ORDER` — `sql, prisma, alembic, ef, sqlite` — wins
outright (its whole `TableRecord`, not a per-column merge) and a warning
names both contenders. Within a single reader, seeing the same table/model
name a second time (a re-`CREATE TABLE` in `sql`, a repeated `model` block
in `prisma`, ...) follows the identical rule — keep the first, warn, never
silently merge or overwrite — via the one shared `_warn_duplicate` helper.
Migration files are deduplicated and sorted by path before being replayed
in that order, so a later `ALTER TABLE ... ADD COLUMN` deterministically
accumulates onto the table an earlier file's `CREATE TABLE` produced.

**Security (never a secret channel, spec §3.11).** The `sqlite` reader is
the *only* code path in this module that ever opens a `.db` file, and it
only ever does so for paths in `opts.db_paths` — a path merely discovered
on disk (e.g. a stray fixture `.db` sitting in the repo) is never touched.
The connection itself is opened read-only (`mode=ro`), so even a caller
who deliberately points `--db` at a live application database cannot
have this tool mutate it. The path is percent-encoded via
`Path.resolve().as_uri()` (`_sqlite_uri`) *before* `?mode=ro` is appended,
so a `%`, `#`, `?` or `&` character sitting in the path itself can never
be misread as URI syntax that could relax that mode.

**Shared normalisation.** All five readers build their `TableRecord`s
through the same two small helpers, `_clean_name` (strip SQL identifier
quoting) and `_clean_type` (collapse whitespace) — Task B4's postmortem
was a secret-sanitisation rule applied in one of two duplicated code paths
and not the other; the fix here is that there is only one path.
"""
from __future__ import annotations

import fnmatch
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from center_kb.codeingest.core import CodeIngestOptions, CodeSection, ExtractResult
from center_kb.codeingest.extractors._mdcells import escape_cell
from center_kb.codeingest.extractors.tree import relposix, walk_tree

# ---------------------------------------------------------------------------
# shared record shape
# ---------------------------------------------------------------------------


@dataclass
class TableRecord:
    name: str
    columns: list[tuple[str, str]] = field(default_factory=list)  # (name, type_and_constraints)
    pk: str = ""    # bare column name, or a full "PRIMARY KEY (a, b)" clause
    ddl: str = ""   # genuine DDL text (sql, sqlite) or a reconstruction (prisma, alembic, ef)
    source: str = ""  # comma-joined list of contributing files/paths
    created_in: str = ""       # the file whose CREATE TABLE produced this record
    columns_known: bool = True  # False when the reader recognises the table name only (EF)


def _clean_name(raw: str) -> str:
    """Strip SQL identifier quoting (`"col"`, `` `col` ``, `[col]`) — the
    one place every reader's column/table *name* text is cleaned."""
    return raw.strip().strip('"`[]')


def _clean_type(raw: str) -> str:
    """Collapse embedded whitespace/newlines to single spaces — the one
    place every reader's column *type-and-constraints* text is cleaned.
    `ALEMBIC_COLUMN_RE`'s `[^,)]+` capture (verbatim from the brief) can
    stop mid-call — `sa.Integer()` arrives as `sa.Integer(`,
    `sa.Numeric(10, 2)` as `sa.Numeric(10` — and is deliberately left
    that way, visibly incomplete, rather than "balanced" into a
    plausible-but-wrong type: appending a `)` cannot tell a genuinely
    single-argument call from one whose remaining arguments were simply
    never captured, and a fabricated `sa.Numeric(10)` silently drops the
    `2` while looking complete. (Task review round 1 tried the
    paren-balancing approach; round 2 found the exact case above and
    reverted it — a visible truncation beats a plausible-looking wrong
    answer, same principle as Ruling R36's desync guard below.)"""
    return " ".join(raw.split())


def _warn_duplicate(kind: str, name: str, rel: str, warnings: list[str]) -> None:
    """Shared wording for "this reader saw the same table/model name
    twice" — sql's own re-`CREATE TABLE`, and each of prisma/alembic/ef's
    repeated definitions all route through this one helper rather than
    four differently-worded warnings (task review round 1, Minor 4's
    "five-paths-one-rule" note)."""
    warnings.append(f"duplicate {kind} {name!r} in {rel}; keeping first")


def _join_source(existing: str, new_rel: str) -> str:
    parts = [p for p in existing.split(", ") if p] if existing else []
    if new_rel not in parts:
        parts.append(new_rel)
    return ", ".join(parts)


def _dirname(rel: str) -> str:
    """Directory part of a repo-relative posix path (`"."` at the root)."""
    return rel.rsplit("/", 1)[0] if "/" in rel else "."


def _pk_clause(pk: str) -> str:
    if pk.upper().startswith("PRIMARY KEY"):
        return pk
    return f"PRIMARY KEY ({pk})"


def _reconstruct_ddl(name: str, columns: list[tuple[str, str]], pk: str) -> str:
    """A best-effort `CREATE TABLE` rendering for the three readers that
    have no literal SQL text to show (prisma, alembic, ef) — synthesised
    purely for the L3 fenced block. `sql` and `sqlite` keep their own
    genuine DDL text instead: a migration file's matched statement, or
    `sqlite_master.sql`, which is itself real SQL."""
    body_lines = [f"  {cname} {ctype}".rstrip() for cname, ctype in columns]
    if pk:
        body_lines.append(f"  {_pk_clause(pk)}")
    body = ",\n".join(body_lines)
    return f"CREATE TABLE {name} (\n{body}\n);"


# ---------------------------------------------------------------------------
# glob-via-walk_tree (Ruling R7: no hand-rolled unpruned walk)
# ---------------------------------------------------------------------------


def _glob_via_walk(root: Path, kb_dir: Path | None, pattern: str) -> list[Path]:
    """Resolve one `**/<dir>.../<file-glob>` pattern into matching file
    paths under `root`, through `walk_tree`'s pruned, deterministic
    traversal — never `rglob`/`glob`/`os.walk` (Ruling R7). The pattern's
    middle segments (if any) must match the *trailing* components of a
    directory's relative path — e.g. `"**/db/migration/*.sql"` only
    matches a directory whose last two path components are `("db",
    "migration")`, so it also matches (and, via the caller's dedup, does
    not double-count relative to) the shorter `"**/migration/*.sql"`
    pattern on the very same directory. The final segment is matched
    against each filename with `fnmatch`."""
    parts = pattern.split("/")
    if parts[0] != "**":
        # A `raise` here (not an `assert`) because every call site is
        # library code operating on module-constant patterns — an
        # `assert` would silently vanish under `python -O` and this
        # invariant would stop being checked at all (task review round
        # 1, Minor 12).
        raise ValueError(f"unsupported glob shape: {pattern!r}")
    file_glob = parts[-1]
    dir_suffix = tuple(parts[1:-1])
    matches: list[Path] = []
    for _depth, reldir, filenames in walk_tree(root, kb_dir):
        if dir_suffix:
            dir_parts = reldir.parts
            if len(dir_parts) < len(dir_suffix) or dir_parts[-len(dir_suffix):] != dir_suffix:
                continue
        for name in filenames:
            if fnmatch.fnmatch(name, file_glob):
                matches.append(root / reldir / name)
    return matches


# ---------------------------------------------------------------------------
# reader: sql — CREATE TABLE / ALTER TABLE ... ADD COLUMN from migrations
# ---------------------------------------------------------------------------

MIGRATION_GLOBS = (
    "**/migrations/*.sql", "**/migration/*.sql", "**/db/migration/*.sql", "**/changelog/*.sql",
)

# CREATE_RE matches only the *header* up to and including the table's
# opening paren — never the body (task review, Critical 1). The original
# pattern captured the body with `\((?P<body>.*?)\);`, a non-greedy scan
# for the first literal "');'" anywhere in the *rest of the file*. A
# dialect trailing clause between the table's real closing paren and its
# terminating `;` — MySQL `) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;`,
# SQLite `) WITHOUT ROWID;`, Postgres `) PARTITION BY RANGE (id);` — has
# no "');'" adjacency at the table's real end, so that scan ran past it
# into the *next* CREATE TABLE statement (or off the end of the file for
# a final table with no trailing `;` at all), smearing one table's tail
# into another's columns and silently deleting the next table outright.
# The body is now bounded by `_matching_close_paren` (paren-depth
# counting from the header's own open paren), which stops at the
# table's real closing paren regardless of what dialect-specific clause
# follows it — see `_apply_sql_file`.
CREATE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"`\[]?(?P<name>[A-Za-z_][\w.]*)[\"`\]]?\s*\(",
    re.I,
)

# Used only to count how many `CREATE TABLE` occurrences a file's
# (already comment-stripped) text actually contains, so `_apply_sql_file`
# can warn when that count exceeds how many `CREATE_RE` actually matched
# — a statement recognised by eye but not by the regex (a name shape
# outside `[A-Za-z_][\w.]*`, for instance) must be reported, never
# silently skipped without a trace (spec §3.9).
_CREATE_TABLE_KEYWORD_RE = re.compile(r"CREATE\s+TABLE", re.I)

ADD_COL_RE = re.compile(
    r"ALTER\s+TABLE\s+[\"`\[]?(?P<name>[A-Za-z_][\w.]*)[\"`\]]?\s+ADD\s+(?:COLUMN\s+)?"
    r"(?P<col>[^;]+);",
    re.I,
)
UNSUPPORTED_RE = re.compile(r"ALTER\s+TABLE\s+.*?\b(RENAME|DROP)\b", re.I)

# Not in the brief verbatim, but needed to *scope* UNSUPPORTED_RE and
# ADD_COL_RE to one ALTER statement at a time. UNSUPPORTED_RE carries
# only re.I (no re.S), so its `.*?` can never itself cross a newline —
# scoping is not needed to stop it running past a newline. It IS needed
# to make "the statement is skipped, never guessed" actually true:
# without it, the exact same raw text is searched independently by
# UNSUPPORTED_RE and ADD_COL_RE, so one statement could be *both* warned
# about by the former *and* matched and consumed as a column by the
# latter. Scoping each ALTER to its own `...;` span first, and checking
# UNSUPPORTED_RE against that span before ADD_COL_RE ever sees it, is
# what makes the skip real (task review round 1 — controller correction
# to this comment's original, incorrect rationale).
_ALTER_STMT_RE = re.compile(r"ALTER\s+TABLE\s+.*?;", re.S | re.I)

# Shared keyword fragment: a top-level CREATE TABLE body entry starting
# with one of these (at a `\b` word boundary — never a bare `startswith`,
# which would also swallow a real column named e.g. `unique_code` or
# `constraint_name`, task review round 1, Important 1) is a table
# constraint, not a column. `ADD_COL_RE`'s "ADD (?:COLUMN\s+)?" also
# matches "ADD CONSTRAINT ..."/"ADD INDEX ..." (Important 3), so
# `_ADD_NON_COLUMN_RE` reuses the same fragment plus INDEX.
_CONSTRAINT_KEYWORDS_FRAGMENT = r"PRIMARY\s+KEY|FOREIGN\s+KEY|CONSTRAINT|UNIQUE|CHECK"
_TABLE_CONSTRAINT_RE = re.compile(rf"^(?:{_CONSTRAINT_KEYWORDS_FRAGMENT})\b", re.I)
_PRIMARY_KEY_CONSTRAINT_RE = re.compile(r"^PRIMARY\s+KEY\b", re.I)
_ADD_NON_COLUMN_RE = re.compile(rf"^(?:{_CONSTRAINT_KEYWORDS_FRAGMENT}|INDEX)\b", re.I)


_OPEN_TO_KIND = {"'": "squote", '"': "dquote", "`": "backtick", "[": "bracket"}
_CLOSE_FOR = {"'": "'", '"': '"', "`": "`", "[": "]"}


@dataclass
class _ScanResult:
    """One `_scan_sql` pass over a chunk of SQL text. `segments` is a
    list of `(kind, text)` pairs that partition the input exactly —
    concatenating every `text` reconstructs the input byte-for-byte.
    `kind` is one of `"code"`, `"squote"`, `"dquote"`, `"backtick"`,
    `"bracket"`, `"line_comment"`, `"block_comment"`. `desynced` is True
    when the scanner reached the end of the input while still inside a
    quote/backtick/bracket span or an unterminated (possibly nested)
    block comment, *or* a bracket span's content contained a `)` with no
    matching `(` inside it — see Ruling R38 in the module docstring."""
    segments: list[tuple[str, str]]
    desynced: bool


def _scan_sql(text: str, *, backslash_escapes: bool) -> _ScanResult:
    """The one shared quote/comment-aware scanner behind both
    `_strip_sql_comments` and `_split_top_level` (task review round 2 —
    two independent, hand-rolled trackers is exactly how they drifted
    out of sync with each other in round 1's fix, missing backtick and
    bracket identifiers entirely). Tracks single- and double-quoted
    string literals, backtick- and bracket-quoted identifiers, `--` line
    comments, and properly nested `/* ... */` block comments. Inside any
    of the four quoted-span kinds, a doubled closing character (`''`,
    `""`, `` `` ``, `]]`) is an escaped literal character (the
    standard-SQL convention, always honoured). Inside a `'`/`"` literal
    *only*, a backslash additionally escapes the next character (the
    MySQL convention) when `backslash_escapes` is True — standard SQL
    disagrees and treats `\\` as an ordinary character, which is exactly
    why this is a caller-supplied flag rather than always-on: see
    `_resolve_scan` (Ruling R38), which runs this scanner both ways and
    picks a reading, rather than guessing which dialect a file uses.
    `desynced=True` when a quote/bracket/comment ran all the way to the
    end of `text` without closing — the reading is untrustworthy — or
    (bracket spans only) when the content between `[` and its `]` ever
    contains a `)` with no `(` earlier in that same span: a genuine
    `[...]`-quoted identifier or a Postgres array suffix (`TEXT[]`,
    `INT[][]`) never contains an unbalanced paren, so this is reserved
    for a bare `[` in an expression (not a real identifier-quote) that
    would otherwise swallow everything up to some unrelated, later
    `]`."""
    segments: list[tuple[str, str]] = []
    i, n = 0, len(text)
    code_start = 0
    while i < n:
        ch = text[i]
        if ch in _OPEN_TO_KIND:
            if i > code_start:
                segments.append(("code", text[code_start:i]))
            kind = _OPEN_TO_KIND[ch]
            close = _CLOSE_FOR[ch]
            j = i + 1
            closed = False
            bracket_paren_depth = 0
            while j < n:
                c = text[j]
                if backslash_escapes and kind in ("squote", "dquote") and c == "\\" and j + 1 < n:
                    j += 2
                    continue
                if kind == "bracket":
                    if c == "(":
                        bracket_paren_depth += 1
                    elif c == ")":
                        if bracket_paren_depth == 0:
                            # A stray ')' with nothing to match inside
                            # this bracket span -- treat the '[' as never
                            # having been a real identifier-quote opener
                            # rather than let it keep searching for some
                            # later, unrelated ']' (Ruling R38).
                            break
                        bracket_paren_depth -= 1
                if c == close:
                    if j + 1 < n and text[j + 1] == close:
                        j += 2
                        continue
                    j += 1
                    closed = True
                    break
                j += 1
            segments.append((kind, text[i:j]))
            i = j
            code_start = i
            if not closed:
                return _ScanResult(segments, desynced=True)
            continue
        if ch == "-" and text[i + 1:i + 2] == "-":
            if i > code_start:
                segments.append(("code", text[code_start:i]))
            j = text.find("\n", i)
            end = n if j == -1 else j
            segments.append(("line_comment", text[i:end]))
            i = end
            code_start = i
            continue
        if ch == "/" and text[i + 1:i + 2] == "*":
            if i > code_start:
                segments.append(("code", text[code_start:i]))
            depth = 1
            j = i + 2
            while j < n and depth > 0:
                two = text[j:j + 2]
                if two == "/*":
                    depth += 1
                    j += 2
                elif two == "*/":
                    depth -= 1
                    j += 2
                else:
                    j += 1
            segments.append(("block_comment", text[i:j]))
            i = j
            code_start = i
            if depth > 0:
                return _ScanResult(segments, desynced=True)
            continue
        i += 1
    if n > code_start:
        segments.append(("code", text[code_start:n]))
    return _ScanResult(segments, desynced=False)


@dataclass
class _ScanResolution:
    """The outcome of `_resolve_scan` (Ruling R38). `segments` is the
    `_ScanResult.segments` list to actually use, or `None` when *both*
    backslash readings desynced and the caller must fall back to its own
    quote-blind strategy. `ambiguous` is True when both readings were
    clean but produced a different partition of the text — the dialect
    is genuinely ambiguous from this text alone, and `segments` holds
    the backslash-as-literal (standard SQL) reading in that case."""
    segments: list[tuple[str, str]] | None
    ambiguous: bool


def _resolve_scan(text: str) -> _ScanResolution:
    """Run `_scan_sql` twice — once treating `\\` inside a `'`/`"`
    literal as an escape (MySQL), once as an ordinary character
    (standard SQL: SQLite, Postgres with `standard_conforming_strings=on`
    — the default since 9.1 — MSSQL, Oracle) — and resolve which reading
    to trust, in this order (Ruling R38, superseding R36's original
    "did a span merely run off the end?" guard):

    1. Exactly one reading is clean (not desynced) -> use it, no warning.
    2. Both clean and produce the *same* partition -> use it, no warning.
    3. Both clean but *disagree* -> the dialect is genuinely ambiguous;
       take the backslash-as-literal (standard SQL) reading, since that
       is every engine in this set except MySQL — the caller warns.
    4. Both desync -> `segments=None`; the caller falls back to its own
       quote-blind strategy and warns.

    Step order matters, not just the disagreement check in isolation: a
    body like `DEFAULT 'it\\'s', b INT, c INT` has the escape reading
    clean and the literal reading desynced (it never finds a real close
    after re-opening on the trailing `s'`) — step 1 must win outright,
    with **no** warning, or Ruling R36's MySQL fix would regress back to
    a "disagreement -> always fall back to quote-blind" rule that mangles
    this exact case (quote-blind would cut a bogus `s'` fragment)."""
    escaped = _scan_sql(text, backslash_escapes=True)
    literal = _scan_sql(text, backslash_escapes=False)

    if escaped.desynced and literal.desynced:
        return _ScanResolution(segments=None, ambiguous=False)
    if escaped.desynced:
        return _ScanResolution(segments=literal.segments, ambiguous=False)
    if literal.desynced:
        return _ScanResolution(segments=escaped.segments, ambiguous=False)
    if escaped.segments == literal.segments:
        return _ScanResolution(segments=escaped.segments, ambiguous=False)
    return _ScanResolution(segments=literal.segments, ambiguous=True)


_AMBIGUOUS_DIALECT_NOTE = (
    "this file's quoting is ambiguous between MySQL's backslash-escaped "
    "string literals and standard SQL (SQLite/Postgres/MSSQL/Oracle, where "
    "\\ is an ordinary character) — assuming standard SQL"
)


def _strip_sql_comments(text: str, rel: str, warnings: list[str]) -> str:
    """Remove `-- ...` line comments and (possibly nested) `/* ... */`
    block comments from raw migration-file text before any DDL regex
    ever sees it (task review round 1, Important 2) — left in place, a
    comment sitting between two column definitions (`id INT, -- the id,
    unique\\n  name TEXT`) both fabricates a bogus column from the
    comment's own text and, via a stray keyword like "unique" it happens
    to contain, swallows the next real column into a false
    table-constraint match. Quoted string literals and quoted
    identifiers are left alone via `_resolve_scan`'s shared tracking, so
    a `--`/`/*` sitting inside one of those is never mistaken for a real
    comment start. If `_resolve_scan` can't produce a trustworthy
    reading at all (both backslash readings desynced), this file's
    actual quoting convention defeated the tracker entirely; rather than
    trust a text some comments may have been incorrectly stripped from,
    warn and return the text completely unstripped (Ruling R38) —
    naming plainly that a table or column below may be **fabricated**
    from commented-out DDL that never got stripped, or that a real one
    may be missing, since "comments unstripped" alone does not convey
    that risk to a reader relying on this document as ground truth
    (task review round 3)."""
    resolution = _resolve_scan(text)
    if resolution.segments is None:
        warnings.append(
            f"could not reliably track quoting/comments in {rel} under either "
            "backslash-escaping reading (an unterminated string literal, quoted "
            "identifier, or block comment) — leaving this file's comments "
            "unstripped; a table or column below may be FABRICATED from "
            "commented-out DDL that was never stripped, or a real one may be "
            "missing"
        )
        return text
    if resolution.ambiguous:
        warnings.append(f"{rel}: {_AMBIGUOUS_DIALECT_NOTE}")
    return "".join(
        seg for kind, seg in resolution.segments if kind not in ("line_comment", "block_comment")
    )


def _mask_quoted_spans(text: str) -> str:
    """Same length as `text`, byte-for-byte, but every quoted span (string
    literal, or backtick-/bracket-/double-quoted identifier) `_resolve_scan`
    finds has its content replaced with `\\0` filler — a character that is
    never `(`, `)`, or `;`. `_apply_sql_file` runs its structural scan
    (`_matching_close_paren`, and the search for a statement's terminating
    `;`) against this masked text so a paren or semicolon sitting *inside* a
    literal (`DEFAULT '('`, `COMMENT 'a;b'`) is never mistaken for real DDL
    structure, while still slicing the real column text out of the
    original, unmasked `text` at the same indices. Falls back to `text`
    unchanged when `_resolve_scan` can't produce a trustworthy reading at
    all (both backslash readings desynced) — `_strip_sql_comments` already
    warned about that case; this is a last resort, not a second guess."""
    resolution = _resolve_scan(text)
    if resolution.segments is None:
        return text
    return "".join(
        seg if kind == "code" else "\0" * len(seg) for kind, seg in resolution.segments
    )


def _split_top_level_quote_blind(body: str) -> list[str]:
    """The original (pre-Minor-10) paren-depth-0 split, with no quote
    awareness at all — Ruling R36 part 2's fallback for when `_scan_sql`
    desyncs. A quote-blind split can over-split on a literal's own comma
    or paren (visibly wrong: an extra, oddly-shaped "column"), but it
    can never silently swallow a real column the way a desynced
    quote-aware split can — and in a module whose whole point is to be
    ground truth, visibly wrong beats silently missing."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in body:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


def _split_top_level(body: str, rel: str, warnings: list[str]) -> list[str]:
    """Split a `CREATE TABLE` body on commas *at paren depth 0*, via the
    shared `_resolve_scan`/`_scan_sql` scanner so quoted spans (string
    literals, and backtick-/bracket-/double-quoted identifiers) are
    never split or depth-counted internally — a string literal's own
    comma (`DEFAULT 'a,b'`), an unbalanced paren inside a literal
    (`DEFAULT ')'`), or a quoted identifier containing a comma
    (`"odd,name" TEXT`) must never skew the depth count or fragment a
    column definition (task review round 1, Minor 10), on top of the
    brief's own `DECIMAL(10,2)` / `PRIMARY KEY (a, b)` cases. If
    `_resolve_scan` can't produce a trustworthy reading at all (both
    backslash readings desynced), this body's actual quoting defeated
    the tracker — warn naming the file and fall back to
    `_split_top_level_quote_blind`, which can over-split (a column's
    name or type may look odd) but never silently deletes a column
    (Ruling R38)."""
    resolution = _resolve_scan(body)
    if resolution.segments is None:
        warnings.append(
            f"could not reliably parse quoted text in {rel} under either "
            "backslash-escaping reading (an unterminated string literal or "
            "quoted identifier) — falling back to a quote-blind column split "
            "for this table; a column's name or type may be wrong"
        )
        return _split_top_level_quote_blind(body)
    if resolution.ambiguous:
        warnings.append(f"{rel}: {_AMBIGUOUS_DIALECT_NOTE}")

    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for kind, seg in resolution.segments:
        if kind != "code":
            current.append(seg)
            continue
        for ch in seg:
            if ch == "(":
                depth += 1
                current.append(ch)
            elif ch == ")":
                depth -= 1
                current.append(ch)
            elif ch == "," and depth == 0:
                parts.append("".join(current))
                current = []
            else:
                current.append(ch)
    parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


def _split_sql_columns(
    body: str, rel: str, warnings: list[str]
) -> tuple[list[tuple[str, str]], str]:
    """Column list plus PK, from one `CREATE TABLE` body. A top-level
    entry is only a table constraint (dropped from the column list) when
    it starts with a constraint keyword at a `\\b` word boundary
    (`_TABLE_CONSTRAINT_RE`) — never a bare `startswith`, which would
    also discard a real column named e.g. `unique_code` or
    `constraint_name` (task review round 1, Important 1). `PRIMARY KEY
    (...)` is captured into `pk` verbatim. An inline `PRIMARY KEY` on a
    column (no separate table constraint) is also detected, recording
    that column's bare name."""
    columns: list[tuple[str, str]] = []
    pk = ""
    for entry in _split_top_level(body, rel, warnings):
        if _TABLE_CONSTRAINT_RE.match(entry):
            if not pk and _PRIMARY_KEY_CONSTRAINT_RE.match(entry):
                pk = entry
            continue
        tokens = entry.split(None, 1)
        if not tokens:
            continue
        cname = _clean_name(tokens[0])
        rest = _clean_type(tokens[1]) if len(tokens) > 1 else ""
        columns.append((cname, rest))
        if not pk and "PRIMARY KEY" in rest.upper():
            pk = cname
    return columns, pk


def _apply_sql_file(text: str, rel: str, tables: dict[str, TableRecord], warnings: list[str]) -> None:
    text = _strip_sql_comments(text, rel, warnings)
    # Same length as `text`, quoted spans replaced with filler — used only
    # to find the table's real closing paren and terminating `;` without a
    # literal's own `(`, `)`, or `;` throwing off the scan (task review,
    # Critical 1). `text` itself (unmasked) is what column text is sliced
    # from, so a real literal like `DEFAULT '('` is preserved verbatim.
    masked = _mask_quoted_spans(text)

    matched = 0
    for m in CREATE_RE.finditer(text):
        matched += 1
        name = m.group("name")
        open_idx = m.end() - 1  # CREATE_RE's match ends right after the "("
        close_idx = _matching_close_paren(masked, open_idx)
        body = text[open_idx + 1:close_idx]
        # The table's real closing paren may be followed by a
        # dialect-specific trailing clause before the statement actually
        # ends — MySQL `) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;`, SQLite
        # `) WITHOUT ROWID;`, Postgres `) PARTITION BY RANGE (id);` — so the
        # terminator is whatever `;` comes next, not an immediate `);`. A
        # final CREATE TABLE with no trailing `;` at all (`semi_idx == -1`)
        # still parses correctly: the body was already bounded above.
        semi_idx = masked.find(";", close_idx + 1)
        stmt_end = semi_idx + 1 if semi_idx != -1 else len(text)
        ddl_text = text[m.start():stmt_end].strip()
        if name in tables:
            existing = tables[name]
            if _dirname(existing.created_in) != _dirname(rel):
                # Two independent migration directories (a per-service
                # schema and a Flyway tree, say) that both create a table
                # of this name describe two different tables. Merging
                # them fabricated a schema that exists nowhere (reviewer
                # G-4); the first in sorted-path order is kept whole and
                # the warning names both files.
                warnings.append(
                    f"duplicate CREATE TABLE {name!r} in {rel} — keeping the "
                    f"definition from {existing.created_in} (a different "
                    "migration directory); the two are not merged"
                )
            else:
                # A same-directory re-CREATE (most plausibly `IF NOT
                # EXISTS` re-asserting a table) must not discard the
                # ALTER TABLE ... ADD COLUMNs already accumulated (task
                # review round 1, Minor 4) — keep the first, warn.
                _warn_duplicate("CREATE TABLE", name, rel, warnings)
            continue
        columns, pk = _split_sql_columns(body, rel, warnings)
        tables[name] = TableRecord(
            name=name, columns=columns, pk=pk, ddl=ddl_text, source=rel, created_in=rel,
        )

    # A `CREATE TABLE` occurrence CREATE_RE never matched at all (a name
    # shape outside `[A-Za-z_][\w.]*`, for instance) must be reported —
    # ground truth that silently drops a table is exactly what this reader
    # promises never to do (spec §3.9, task review Critical 1 part 2).
    total = len(_CREATE_TABLE_KEYWORD_RE.findall(text))
    if total > matched:
        warnings.append(
            f"found {total} CREATE TABLE statement(s) in {rel} but recognised "
            f"only {matched} — the rest were skipped, not guessed at"
        )

    last_end = 0
    for m in _ALTER_STMT_RE.finditer(text):
        last_end = m.end()
        stmt = m.group(0)
        if UNSUPPORTED_RE.search(stmt):
            warnings.append(f"unsupported DDL in {rel}: {stmt.strip()}")
            continue
        add_m = ADD_COL_RE.match(stmt)
        if not add_m:
            continue  # an ALTER variant outside this reader's recognised scope
        col_text = add_m.group("col").strip()
        if _ADD_NON_COLUMN_RE.match(col_text):
            # "ALTER TABLE ... ADD CONSTRAINT/INDEX ..." matches
            # ADD_COL_RE's optional "(?:COLUMN\s+)?" just as well as a
            # real "ADD COLUMN" does (Ruling R35, task review round 1,
            # Important 3) — recording it as a column named "CONSTRAINT"
            # would fabricate structure, so skip it and warn instead.
            warnings.append(
                f"ALTER TABLE ADD CONSTRAINT/INDEX (not a column) skipped in {rel}: {stmt.strip()}"
            )
            continue
        name = add_m.group("name")
        tokens = col_text.split(None, 1)
        if not tokens:
            continue
        cname = _clean_name(tokens[0])
        rest = _clean_type(tokens[1]) if len(tokens) > 1 else ""
        record = tables.get(name)
        if record is None:
            warnings.append(f"ALTER TABLE ADD COLUMN on unknown table {name!r} in {rel}")
            continue
        if _dirname(record.created_in) != _dirname(rel):
            warnings.append(
                f"ALTER TABLE {name!r} ADD COLUMN in {rel} not applied — the "
                f"table kept for {name!r} was created in {record.created_in}, "
                "a different migration directory"
            )
            continue
        record.columns.append((cname, rest))
        record.ddl = record.ddl + "\n\n" + stmt.strip()
        record.source = _join_source(record.source, rel)
        if not record.pk and "PRIMARY KEY" in rest.upper():
            record.pk = cname

    # A trailing ALTER TABLE ... RENAME/DROP with no terminating ';' is
    # never matched by _ALTER_STMT_RE above (task review round 1, Minor
    # 6 — a regression introduced by adding that scoping regex) — but
    # it's still unsupported DDL and still deserves its warning, even
    # though (lacking a ';') it was never going to be misapplied as a
    # column either way. When no ALTER in this file ever terminates with
    # ';', last_end stays 0 and `tail` is the *entire* file — the warning
    # is bounded to the regex match itself (task review round 2, Minor),
    # not the whole tail, or a large migration would dump its full text
    # into one warning string.
    tail = text[last_end:]
    tail_match = UNSUPPORTED_RE.search(tail)
    if tail_match:
        warnings.append(f"unsupported DDL in {rel}: {tail_match.group(0).strip()}")


def _read_sql(root: Path, opts: CodeIngestOptions) -> tuple[dict[str, TableRecord], list[str]]:
    warnings: list[str] = []
    found: set[Path] = set()
    for pattern in MIGRATION_GLOBS:
        found.update(_glob_via_walk(root, opts.kb_dir, pattern))

    tables: dict[str, TableRecord] = {}
    for path in sorted(found, key=lambda p: relposix(root, p)):
        rel = relposix(root, path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            warnings.append(f"could not parse {rel}: {exc}")
            continue
        try:
            _apply_sql_file(text, rel, tables, warnings)
        except Exception as exc:
            # Defense in depth (task review round 1, Minor 5): a
            # parse-time bug on this one file must never unwind past
            # this loop and discard every other file's already-
            # accumulated tables with a warning that names no file —
            # exactly the defect class this stage has already shipped
            # twice.
            warnings.append(f"could not parse {rel}: {exc}")
    return tables, warnings


# ---------------------------------------------------------------------------
# reader: prisma — model blocks in schema.prisma
# ---------------------------------------------------------------------------

PRISMA_GLOB = "**/schema.prisma"
PRISMA_MODEL_RE = re.compile(r"^model\s+(\w+)\s*\{(.*?)^\}", re.S | re.M)


def _apply_prisma_file(text: str, rel: str, tables: dict[str, TableRecord], warnings: list[str]) -> None:
    for m in PRISMA_MODEL_RE.finditer(text):
        name = m.group(1)
        columns: list[tuple[str, str]] = []
        pk = ""
        for line in m.group(2).splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("@@") or stripped.startswith("//"):
                continue  # a block attribute (`@@map(...)`) or comment, not a field
            tokens = stripped.split(None, 1)
            if not tokens:
                continue
            fname = _clean_name(tokens[0])
            rest = _clean_type(tokens[1]) if len(tokens) > 1 else ""
            columns.append((fname, rest))
            if not pk and "@id" in rest:
                pk = fname
        if name in tables:
            _warn_duplicate("prisma model", name, rel, warnings)
            continue
        tables[name] = TableRecord(
            name=name, columns=columns, pk=pk,
            ddl=_reconstruct_ddl(name, columns, pk), source=rel,
        )


def _read_prisma(root: Path, opts: CodeIngestOptions) -> tuple[dict[str, TableRecord], list[str]]:
    tables: dict[str, TableRecord] = {}
    warnings: list[str] = []
    paths = sorted(_glob_via_walk(root, opts.kb_dir, PRISMA_GLOB), key=lambda p: relposix(root, p))
    for path in paths:
        rel = relposix(root, path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            warnings.append(f"could not parse {rel}: {exc}")
            continue
        try:
            _apply_prisma_file(text, rel, tables, warnings)
        except Exception as exc:  # defense in depth, mirrors _read_sql (Minor 5)
            warnings.append(f"could not parse {rel}: {exc}")
    return tables, warnings


# ---------------------------------------------------------------------------
# reader: alembic — op.create_table(...) / sa.Column(...) in versions/*.py
# ---------------------------------------------------------------------------

ALEMBIC_GLOB = "**/versions/*.py"
ALEMBIC_TABLE_RE = re.compile(r"op\.create_table\(\s*['\"](\w+)['\"]")
ALEMBIC_COLUMN_RE = re.compile(r"sa\.Column\(\s*['\"](\w+)['\"]\s*,\s*([^,)]+)")


def _matching_close_paren(text: str, open_idx: int) -> int:
    """Index of the `)` that closes the `(` at `open_idx`, tracking
    nested parens — needed so each `op.create_table(...)` call's own
    `sa.Column(...)` entries are matched only within that call's span,
    never a sibling table's columns in the same migration file."""
    depth = 0
    for i in range(open_idx, len(text)):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
    return len(text) - 1


def _apply_alembic_file(text: str, rel: str, tables: dict[str, TableRecord], warnings: list[str]) -> None:
    for m in ALEMBIC_TABLE_RE.finditer(text):
        name = m.group(1)
        open_idx = text.find("(", m.start())
        if open_idx == -1:
            continue
        close_idx = _matching_close_paren(text, open_idx)
        scope = text[open_idx:close_idx + 1]
        columns = [
            (_clean_name(cm.group(1)), _clean_type(cm.group(2)))
            for cm in ALEMBIC_COLUMN_RE.finditer(scope)
        ]
        if name in tables:
            _warn_duplicate("alembic table", name, rel, warnings)
            continue
        tables[name] = TableRecord(
            name=name, columns=columns, pk="",
            ddl=_reconstruct_ddl(name, columns, ""), source=rel,
        )


def _read_alembic(root: Path, opts: CodeIngestOptions) -> tuple[dict[str, TableRecord], list[str]]:
    tables: dict[str, TableRecord] = {}
    warnings: list[str] = []
    paths = sorted(_glob_via_walk(root, opts.kb_dir, ALEMBIC_GLOB), key=lambda p: relposix(root, p))
    for path in paths:
        rel = relposix(root, path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            warnings.append(f"could not parse {rel}: {exc}")
            continue
        try:
            _apply_alembic_file(text, rel, tables, warnings)
        except Exception as exc:  # defense in depth, mirrors _read_sql (Minor 5)
            warnings.append(f"could not parse {rel}: {exc}")
    return tables, warnings


# ---------------------------------------------------------------------------
# reader: ef — migrationBuilder.CreateTable(name: "...") in Migrations/*.cs
# ---------------------------------------------------------------------------

EF_GLOB = "**/Migrations/*.cs"
EF_TABLE_RE = re.compile(r'migrationBuilder\.CreateTable\(\s*name:\s*"(\w+)"')


def _apply_ef_file(text: str, rel: str, tables: dict[str, TableRecord], warnings: list[str]) -> None:
    for m in EF_TABLE_RE.finditer(text):
        name = m.group(1)
        if name in tables:
            _warn_duplicate("EF table", name, rel, warnings)
            continue
        tables[name] = TableRecord(
            name=name, columns=[], pk="", ddl=_reconstruct_ddl(name, [], ""), source=rel,
        )


def _read_ef(root: Path, opts: CodeIngestOptions) -> tuple[dict[str, TableRecord], list[str]]:
    """No column regex is given for EF in the brief — only the table
    name is recognised, so every EF-sourced `TableRecord` has an empty
    column list. This is a documented limitation, not a bug."""
    tables: dict[str, TableRecord] = {}
    warnings: list[str] = []
    paths = sorted(_glob_via_walk(root, opts.kb_dir, EF_GLOB), key=lambda p: relposix(root, p))
    for path in paths:
        rel = relposix(root, path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            warnings.append(f"could not parse {rel}: {exc}")
            continue
        try:
            _apply_ef_file(text, rel, tables, warnings)
        except Exception as exc:  # defense in depth, mirrors _read_sql (Minor 5)
            warnings.append(f"could not parse {rel}: {exc}")
    return tables, warnings


# ---------------------------------------------------------------------------
# reader: sqlite — only for paths in opts.db_paths, opened read-only
# ---------------------------------------------------------------------------


def _path_label(root: Path, path: Path) -> str:
    """A label for a `--db` path, never the absolute host path (task
    review, Important 4). The common case — `path` sits under `root` —
    renders the familiar repo-relative form via `relposix`. An out-of-
    root `--db` used to fall back to `path.as_posix()`, the fully-
    qualified path `CodeIngestOptions.__post_init__` already resolved —
    which includes the OS user name on a typical developer machine and,
    worse, made this module's output depend on *whose* machine ingested
    the repo (spec §3.5's determinism guarantee: the same repo ingested
    by two developers must produce the same bytes). `--db:<basename>` is
    stable across machines and carries no host/username information,
    while still naming which `--db` file a warning or a table's source
    refers to."""
    try:
        return relposix(root, path)
    except ValueError:
        return f"--db:{path.name}"


def _sqlite_uri(path: Path, mode: str) -> str:
    """Build the `file:` URI handed to `sqlite3.connect(..., uri=True)`.
    The path is percent-encoded via `Path.resolve().as_uri()` (RFC 8089)
    *before* the query string is appended, so a `%`, `#`, `?` or `&`
    character sitting in the path can never be misread as URI syntax —
    in particular, a raw `?` in the path could otherwise start a second,
    path-controlled query string ahead of our own `?mode=ro` (task
    review round 1, Minor 9 — spec §3.11's read-only guarantee must not
    be something a crafted path can turn off)."""
    return f"{path.resolve().as_uri()}?mode={mode}"


def _read_sqlite_columns(con: sqlite3.Connection, table_name: str) -> tuple[list[tuple[str, str]], str]:
    """`PRAGMA table_info(<table>)` rows are `(cid, name, type, notnull,
    dflt_value, pk)`; `cid` is already declaration order, but the explicit
    sort documents that guarantee rather than relying on it silently. A
    single PK column records its bare name; a composite PK (more than one
    row with `pk > 0`) is ordered by its own `pk` index — the column's
    *position within the key*, not its `cid` — and rendered as a
    `PRIMARY KEY (...)` clause, matching the `sql` reader's shape."""
    quoted = table_name.replace('"', '""')
    rows = sorted(con.execute(f'PRAGMA table_info("{quoted}")').fetchall(), key=lambda r: r[0])
    columns: list[tuple[str, str]] = []
    pk_positions: list[tuple[int, str]] = []
    for _cid, col_name, col_type, notnull, _dflt, pk_flag in rows:
        rest = _clean_type(f"{col_type} {'NOT NULL' if notnull else ''}")
        columns.append((_clean_name(col_name), rest))
        if pk_flag:
            pk_positions.append((pk_flag, col_name))
    if len(pk_positions) == 1:
        pk = pk_positions[0][1]
    elif len(pk_positions) > 1:
        pk = _pk_clause(", ".join(name for _, name in sorted(pk_positions)))
    else:
        pk = ""
    return columns, pk


def _read_sqlite(root: Path, opts: CodeIngestOptions) -> tuple[dict[str, TableRecord], list[str]]:
    """The only code path in this module that opens a `.db` file — and
    only for a path already in `opts.db_paths` (spec §3.11: never a file
    merely discovered on disk). Opened read-only via `_sqlite_uri`'s
    `mode=ro` URI, so even a live application database handed to `--db`
    cannot be mutated. A missing path warns; it never raises."""
    tables: dict[str, TableRecord] = {}
    warnings: list[str] = []
    for db_path in opts.db_paths:
        label = _path_label(root, db_path)
        if not db_path.is_file():
            warnings.append(f"--db path not found: {label}")
            continue
        try:
            con = sqlite3.connect(_sqlite_uri(db_path, "ro"), uri=True)
        except (sqlite3.Error, OSError, ValueError) as exc:
            warnings.append(f"could not open {label}: {exc}")
            continue
        try:
            rows = con.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            for name, sql_text in rows:
                if any(ch.isspace() for ch in name):
                    # CodeSection.id must contain no whitespace; every
                    # other reader's name comes from a `\w+`-shaped regex
                    # capture that can never contain one, but a raw
                    # sqlite_master name is unconstrained.
                    warnings.append(f"skipping table with whitespace in its name in {label}: {name!r}")
                    continue
                columns, pk = _read_sqlite_columns(con, name)
                if name in tables:
                    warnings.append(
                        f"duplicate table {name!r} across --db paths; keeping first ({label})"
                    )
                    continue
                ddl = (sql_text or "").strip() or _reconstruct_ddl(name, columns, pk)
                tables[name] = TableRecord(name=name, columns=columns, pk=pk, ddl=ddl, source=label)
        except Exception as exc:
            # Defense in depth (task review round 1, Minor 5's sibling):
            # a failure partway through this db's tables must not also
            # discard tables already collected from an earlier db_path.
            warnings.append(f"could not read {label}: {exc}")
        finally:
            con.close()
    return tables, warnings


# ---------------------------------------------------------------------------
# merge + section rendering
# ---------------------------------------------------------------------------

_READER_ORDER = ("sql", "prisma", "alembic", "ef", "sqlite")


def _merge_tables(
    per_reader: dict[str, dict[str, TableRecord]], warnings: list[str]
) -> dict[str, TableRecord]:
    """First reader in `_READER_ORDER` to claim a table name wins that
    table's whole `TableRecord` — never a per-column merge — and every
    later claim of the same name is a warning naming both readers."""
    merged: dict[str, TableRecord] = {}
    claimed_by: dict[str, str] = {}
    for reader_name in _READER_ORDER:
        for name, record in per_reader.get(reader_name, {}).items():
            if name in merged:
                warnings.append(
                    f"table {name!r} defined by both {claimed_by[name]} and {reader_name} "
                    f"readers; keeping {claimed_by[name]} (reader precedence: "
                    f"{', '.join(_READER_ORDER)})"
                )
                continue
            merged[name] = record
            claimed_by[name] = reader_name
    return merged


_PK_LIST_RE = re.compile(r"PRIMARY\s+KEY\s*\(([^)]*)\)", re.I)


def _pk_columns(pk: str) -> set[str]:
    """Casefolded column names actually covered by `pk`, for marking the
    L2 table's `PK` cell per row — handles both a bare column name and a
    `PRIMARY KEY (a, b)` table-constraint clause. Casefolded because SQL
    identifiers are case-insensitive: `PRIMARY KEY (ID)` must still mark
    a column declared `id` (task review round 1, Minor 7)."""
    if not pk:
        return set()
    m = _PK_LIST_RE.search(pk)
    if m:
        return {c.strip().strip('"`[]').casefold() for c in m.group(1).split(",") if c.strip()}
    return {pk.casefold()}


def _render_section(record: TableRecord) -> CodeSection:
    pk_cols = _pk_columns(record.pk)
    l2_lines = ["| Column | Type | PK |", "| --- | --- | --- |"]
    for cname, ctype in record.columns:
        mark = "yes" if cname.casefold() in pk_cols else ""
        l2_lines.append(f"| {escape_cell(cname)} | {escape_cell(ctype)} | {mark} |")
    l2_lines.append("")
    l2_lines.append(f"_Source: {record.source}_")
    l2_md = "\n".join(l2_lines) + "\n"

    source_files = "\n".join(record.source.split(", ")) if record.source else ""
    l3_md = f"```sql\n{record.ddl}\n```\n\n```\n{source_files}\n```\n"

    summary = (
        f"Table {record.name}: {len(record.columns)} columns, "
        f"PK {record.pk or 'none detected'} (source: {record.source})."
    )

    return CodeSection(
        id=f"db.{record.name}",
        title=record.name,
        summary=summary,
        group="db",
        l2_md=l2_md,
        l3_md=l3_md,
    )


class SchemaExtractor:
    name = "schema"

    def detect(self, root: Path) -> bool:
        # Ruling R24's structural exception (matches deps.py / commands.py
        # precedent): Extractor.detect(self, root) is never given opts, so
        # this walk can't be pruned by a non-default --kb-dir; extract()'s
        # walks all thread opts.kb_dir through via _glob_via_walk.
        for pattern in (*MIGRATION_GLOBS, PRISMA_GLOB, ALEMBIC_GLOB, EF_GLOB):
            if _glob_via_walk(root, None, pattern):
                return True
        return False

    def extract(self, root: Path, opts: CodeIngestOptions) -> ExtractResult:
        warnings: list[str] = []
        per_reader: dict[str, dict[str, TableRecord]] = {}

        def _run(key: str, reader, *args: object) -> None:
            try:
                tables, warns = reader(*args)
            except Exception as exc:  # defense in depth, mirrors deps.py/commands.py
                tables, warns = {}, [f"could not read {key} schema sources: {exc}"]
            per_reader[key] = tables
            warnings.extend(warns)

        _run("sql", _read_sql, root, opts)
        _run("prisma", _read_prisma, root, opts)
        _run("alembic", _read_alembic, root, opts)
        _run("ef", _read_ef, root, opts)
        _run("sqlite", _read_sqlite, root, opts)

        merged = _merge_tables(per_reader, warnings)
        sections = [_render_section(merged[name]) for name in sorted(merged)]
        return ExtractResult(sections=sections, warnings=warnings)
