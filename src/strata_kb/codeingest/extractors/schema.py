"""schema extractor — `db.<table>` from migration files, ORM schemas, and
(only when explicitly asked) a SQLite file.

Five readers — SQL migrations, Prisma, Alembic, Entity Framework Core, and
an explicit SQLite database — each surface `TableRecord`s from one kind of
evidence. Every reader degrades rather than raises: a malformed or
unreadable file becomes a warning naming the file, and every other reader
still runs (matching `deps.py`, `services.py` and `commands.py`'s
discipline).

**Recognised DDL, and why.** The `sql` reader replays a migration file
statement by statement. It applies `CREATE TABLE` (with its `PARTITION BY`
clause, inline/table `UNIQUE` and MySQL `KEY`/`INDEX` entries, and `PARTITION
OF` children), `DROP TABLE`, `CREATE [UNIQUE|FULLTEXT|SPATIAL] INDEX`,
`DROP INDEX`, `ALTER INDEX ... RENAME`, and the comma-separated actions of
`ALTER TABLE [ONLY] t`: `ADD COLUMN`, `ADD [CONSTRAINT n] PRIMARY KEY|UNIQUE
(cols)`, MySQL `ADD [UNIQUE|FULLTEXT|SPATIAL] INDEX|KEY`, and `ATTACH|DETACH
PARTITION`. Keys and indexes are recorded as such, never as columns.

**Nothing is dropped silently.** The default is inverted. A file is split into
statements on `;` and on `GO` lines (`$$ ... $$` bodies stay inside one). A
statement is applied, fact-neutral (`_NEUTRAL_HEAD_RE`: INSERT, GRANT,
`CREATE VIEW|FUNCTION|SEQUENCE|...`, ...), or a *site*: an unknown head
(`DO`, `RENAME TABLE`, `MERGE`, ...), a handled kind no handler fully applies,
a second statement left in the span for want of a separator, and any ALTER
action that is not applied or listed in `_SILENT_ALTER_ACTIONS_RE` (actions
that cannot change a shown fact: `OWNER TO`, storage parameters,
triggers/RLS, `SET STATISTICS`; `SET DEFAULT` is not among them — the Type
cell shows defaults). A site lands as `file:line` on the table it names
(`TableRecord.schema_partial`) or, when no table can be named, on the
reader's `_Warnings.sites`. The `schema` coverage row for that (scope,
reader) reads `partial`. `FOREIGN KEY`/`CHECK` constraints only warn. A
schema-qualified name never resolves to a table kept under another schema.

**Coverage is never falsely `complete`.** Every warning a reader emits that
names a file (an unparsed file, a comment-strip desync, an unrecognised
`CREATE TABLE`/`CREATE INDEX`, a statement on an unknown table, a duplicate
definition) goes through `_warn`, which also records that file's site on the
reader's `_Warnings.sites`; `_coverage_rows` turns those into `partial` for
the (scope, reader) holding the file. A skipped statement that names a kept
table lands on that table's `schema_partial` instead. Only FOREIGN KEY /
CHECK constraint warnings stay warning-only: no displayed fact moves.

**Prisma + SQL.** Prisma keeps no partitions, and its migrations
(`prisma/migrations/*/migration.sql`) hold the DDL it generated. A SQL record
whose name equals a Prisma model's physical table name (`@@map`, else the
model name) folds into that model: partition, partitions and indexes (a
union keyed by name; an unnamed one is dropped when a named index covers
the same columns and uniqueness) come across, the SQL
primary key fills in when Prisma has none, and the columns stay Prisma's.
Where both state a primary key or partition and differ, both show as
`<value> [<source>]`.

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

**Security (never a secret channel).** The `sqlite` reader is
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
quoting) and `_clean_type` (collapse whitespace). A rule applied in one
of two duplicated code paths and not the other is how a secret once
leaked from `services.py`; the defence here is that there is only one
path.
"""

from __future__ import annotations

import fnmatch
import re
import sqlite3
from dataclasses import dataclass, field, replace
from pathlib import Path

from strata_kb.codeingest.extractors._mdcells import escape_cell
from strata_kb.codeingest.extractors._scopes import Scope, find_scopes, scope_of
from strata_kb.codeingest.extractors.tree import relposix, walk_tree
from strata_kb.codeingest.types import (
    CodeIngestOptions,
    CodeSection,
    CoverageRow,
    ExtractResult,
)

# ---------------------------------------------------------------------------
# shared record shape
# ---------------------------------------------------------------------------


@dataclass
class TableRecord:
    name: str
    columns: list[tuple[str, str]] = field(
        default_factory=list
    )  # (name, type_and_constraints)
    pk: str = ""  # bare column name, or a full "PRIMARY KEY (a, b)" clause
    ddl: str = (
        ""  # genuine DDL text (sql, sqlite) or a reconstruction (prisma, alembic, ef)
    )
    source: str = ""  # comma-joined list of contributing files/paths
    created_in: str = ""  # the file whose CREATE TABLE produced this record
    columns_known: bool = (
        True  # False when the reader recognises the table name only (EF)
    )
    table_name: str = ""  # physical name (Prisma `@@map`); "" means `name`
    partition: str = ""  # e.g. "RANGE (created_at)"
    # (name, comma-joined columns, unique); an unnamed one is "(unnamed)"
    indexes: list[tuple[str, str, bool]] = field(default_factory=list)
    partitions: list[str] = field(default_factory=list)  # `PARTITION OF` children
    # `file:line` (or `file`) of each statement this reader skipped
    schema_partial: list[str] = field(default_factory=list)
    # row label -> "<value> [<source>] / <value> [<source>]", set by the merge
    # when two sources disagree on that row
    disagreements: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.table_name:
            self.table_name = self.name


UNNAMED_INDEX = "(unnamed)"


def _site(rel: str, line: int | None) -> str:
    """A `file:line` coverage site (`file` when no line is known). Never
    contains "; ", which core uses to join sites."""
    return (f"{rel}:{line}" if line else rel).replace("; ", ";")


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _add_index_to(
    indexes: list[tuple[str, str, bool]], name: str, cols: str, unique: bool
) -> None:
    """Add an index once per `(name, cols, unique)` — a replayed migration
    set can state the same index twice."""
    entry = (name or UNNAMED_INDEX, cols, unique)
    if entry not in indexes:
        indexes.append(entry)


def _add_index(record: TableRecord, name: str, cols: str, unique: bool) -> None:
    _add_index_to(record.indexes, name, cols, unique)


def _clean_name(raw: str) -> str:
    """Strip SQL identifier quoting (`"col"`, `` `col` ``, `[col]`) — the
    one place every reader's column/table *name* text is cleaned."""
    return raw.strip().strip('"`[]')


def _clean_type(raw: str) -> str:
    """Collapse embedded whitespace/newlines to single spaces — the one
    place every reader's column *type-and-constraints* text is cleaned.
    Never appends a closing paren: a literal like `DEFAULT '('` is
    genuinely unbalanced and must stay visibly so."""
    return " ".join(raw.split())


class _Warnings(list[str]):
    """The warnings list a reader fills, plus `sites`: the `(file, site)`
    pair behind every warning that names a file. Each such file makes its
    (scope, reader) coverage row `partial` — a warning is a statement or
    file the reader did not take in."""

    def __init__(self) -> None:
        super().__init__()
        self.sites: list[tuple[str, str]] = []


def _warn(warnings: list[str], rel: str, message: str, line: int | None = None) -> None:
    """Append `message`; when `warnings` is a reader's `_Warnings`, also
    record `rel` (+ `line`) as a skipped site."""
    warnings.append(message)
    if isinstance(warnings, _Warnings):
        warnings.sites.append((rel, _site(rel, line)))


def _warn_duplicate(kind: str, name: str, rel: str, warnings: list[str]) -> None:
    """Shared wording for "this reader saw the same table/model name
    twice" — sql's own re-`CREATE TABLE`, and each of prisma/alembic/ef's
    repeated definitions all route through this one helper rather than
    four differently-worded warnings."""
    _warn(warnings, rel, f"duplicate {kind} {name!r} in {rel}; keeping first")


def _join_source(existing: str, new_rel: str) -> str:
    parts = [p for p in existing.split(", ") if p] if existing else []
    if new_rel not in parts:
        parts.append(new_rel)
    return ", ".join(parts)


_PER_MIGRATION_FILES = ("up.sql", "migration.sql")


def _dirname(rel: str) -> str:
    """Directory part of a repo-relative posix path (`"."` at the root).
    An empty `rel` (an unset `TableRecord.created_in`) returns `""`, never
    `"."` — the `_apply_sql_file` guards below compare two `_dirname(...)`
    results, and "created_in was never set" must never compare equal to
    "created at the repo root"."""
    if not rel:
        return ""
    parts = rel.split("/")
    # diesel `migrations/<m>/up.sql` and prisma `migrations/<m>/migration.sql`
    # put every migration in its own directory; they are one migration set,
    # so an index or column added by a later one still belongs to the table.
    if (
        len(parts) >= 3
        and parts[-1] in _PER_MIGRATION_FILES
        and parts[-3] == "migrations"
    ):
        return "/".join(parts[:-2])
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
# glob-via-walk_tree (no hand-rolled unpruned walk)
# ---------------------------------------------------------------------------


def _glob_via_walk(root: Path, kb_dir: Path | None, pattern: str) -> list[Path]:
    """Resolve one `**/<dir>.../<file-glob>` pattern into matching file
    paths under `root`, through `walk_tree`'s pruned, deterministic
    traversal — never `rglob`/`glob`/`os.walk`. The pattern's
    middle segments (if any) must match the *trailing* components of a
    directory's relative path — e.g. `"**/db/migration/*.sql"` only
    matches a directory whose last two path components are `("db",
    "migration")`, so it also matches (and, via the caller's dedup, does
    not double-count relative to) the shorter `"**/migration/*.sql"`
    pattern on the very same directory. The final segment is matched
    against each filename with `fnmatch`.

    A middle segment may itself be a wildcard (`"**/migrations/*/up.sql"`
    — diesel's per-migration directories), matched with `fnmatchcase`:
    case-sensitively, so a directory named `Migrations` matches
    `Migrations` and nothing else on every platform. `fnmatch` would
    fold case on Windows alone, and this module's output is published to
    the federation hub — it must not depend on which OS ran the
    ingest."""
    parts = pattern.split("/")
    if parts[0] != "**":
        # A `raise` here (not an `assert`) because every call site is
        # library code operating on module-constant patterns — an
        # `assert` would silently vanish under `python -O` and this
        # invariant would stop being checked at all.
        raise ValueError(f"unsupported glob shape: {pattern!r}")
    file_glob = parts[-1]
    dir_suffix = tuple(parts[1:-1])
    matches: list[Path] = []
    for _depth, reldir, filenames in walk_tree(root, kb_dir):
        if dir_suffix:
            dir_parts = reldir.parts
            if len(dir_parts) < len(dir_suffix) or not all(
                fnmatch.fnmatchcase(part, expected)
                for part, expected in zip(
                    dir_parts[-len(dir_suffix) :], dir_suffix, strict=True
                )
            ):
                continue
        for name in filenames:
            if fnmatch.fnmatch(name, file_glob):
                matches.append(root / reldir / name)
    return matches


# ---------------------------------------------------------------------------
# reader: sql — CREATE TABLE / ALTER TABLE ... ADD COLUMN from migrations
# ---------------------------------------------------------------------------

MIGRATION_GLOBS = (
    "**/migrations/*.sql",
    "**/migration/*.sql",
    "**/db/migration/*.sql",
    "**/changelog/*.sql",
    # diesel (Rust) gives each migration its own directory holding
    # `up.sql` and `down.sql` — one level deeper than the flat globs
    # above, whose `*` does not cross a path separator. Only `up.sql` is
    # read: `down.sql` is the reverse migration, all `DROP TABLE`, which
    # would warn through `UNSUPPORTED_RE` once per migration in the repo
    # while adding no column anyone can see.
    "**/migrations/*/up.sql",
    # prisma: `prisma/migrations/<timestamp>_<name>/migration.sql`
    "**/prisma/migrations/*/migration.sql",
)

# CREATE_RE matches only the *header* up to and including the table's
# opening paren — never the body. Do not capture the body with
# `\((?P<body>.*?)\);`, a non-greedy scan for the first literal "');'"
# anywhere in the *rest of the file*: a dialect trailing clause between
# the table's real closing paren and its terminating `;` — MySQL
# `) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;`, SQLite `) WITHOUT ROWID;`,
# Postgres `) PARTITION BY RANGE (id);` — has no "');'" adjacency at the
# table's real end, so that scan runs past it into the *next* CREATE
# TABLE statement (or off the end of the file for a final table with no
# trailing `;` at all), smearing one table's tail into another's columns
# and silently deleting the next table outright. The body is instead
# bounded by `_matching_close_paren` (paren-depth
# counting from the header's own open paren), which stops at the
# table's real closing paren regardless of what dialect-specific clause
# follows it — see `_apply_sql_file`.
CREATE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"`\[]?(?P<name>[A-Za-z_][\w.]*)[\"`\]]?\s*\(",
    re.I,
)

# Shared keyword fragment: a top-level CREATE TABLE body entry starting
# with one of these (at a `\b` word boundary — never a bare `startswith`,
# which would also swallow a real column named e.g. `unique_code` or
# `constraint_name`) is a table constraint, not a column.
# An `ADD ...` action is a column unless it starts like one of these, so
# `_ADD_NON_COLUMN_RE` reuses the same fragment plus the index/partition
# keywords.
_CONSTRAINT_KEYWORDS_FRAGMENT = r"PRIMARY\s+KEY|FOREIGN\s+KEY|CONSTRAINT|UNIQUE|CHECK"
_TABLE_CONSTRAINT_RE = re.compile(rf"^(?:{_CONSTRAINT_KEYWORDS_FRAGMENT})\b", re.I)
_PRIMARY_KEY_CONSTRAINT_RE = re.compile(r"^PRIMARY\s+KEY\b", re.I)
_ADD_NON_COLUMN_RE = re.compile(
    rf"^(?:{_CONSTRAINT_KEYWORDS_FRAGMENT}|INDEX|FULLTEXT|SPATIAL|PARTITION)\b", re.I
)
# A body entry that is never a column and that this reader cannot read
# (so the table is partial): EXCLUDE, LIKE (copies columns), PERIOD FOR.
_BODY_OPAQUE_RE = re.compile(
    r"^(?:EXCLUDE\s*(?:USING\b|\()|LIKE\s|PERIOD\s+FOR\b)", re.I
)
# MySQL index entries; a column named `key` has no `(<name>` list.
_BODY_KEYLIKE_RE = re.compile(r"^(?:KEY|INDEX|FULLTEXT|SPATIAL)\b", re.I)
_COLUMN_LIST_OPEN_RE = re.compile(r"\(\s*[A-Za-z_`\"\[(]")


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
    matching `(` inside it — see the dual-scan guard in the module
    docstring."""

    segments: list[tuple[str, str]]
    desynced: bool


def _scan_sql(text: str, *, backslash_escapes: bool) -> _ScanResult:
    """The one shared quote/comment-aware scanner behind both
    `_strip_sql_comments` and `_split_top_level` (two independent,
    hand-rolled trackers drift out of sync with each other — one once
    missed backtick and bracket identifiers entirely). Tracks single- and
    double-quoted
    string literals, backtick- and bracket-quoted identifiers, `--` line
    comments, and properly nested `/* ... */` block comments. Inside any
    of the four quoted-span kinds, a doubled closing character (`''`,
    `""`, `` `` ``, `]]`) is an escaped literal character (the
    standard-SQL convention, always honoured). Inside a `'`/`"` literal
    *only*, a backslash additionally escapes the next character (the
    MySQL convention) when `backslash_escapes` is True — standard SQL
    disagrees and treats `\\` as an ordinary character, which is exactly
    why this is a caller-supplied flag rather than always-on: see
    `_resolve_scan`, which runs this scanner both ways and
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
                if (
                    backslash_escapes
                    and kind in ("squote", "dquote")
                    and c == "\\"
                    and j + 1 < n
                ):
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
                            # later, unrelated ']'.
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
        if ch == "-" and text[i + 1 : i + 2] == "-":
            if i > code_start:
                segments.append(("code", text[code_start:i]))
            j = text.find("\n", i)
            end = n if j == -1 else j
            segments.append(("line_comment", text[i:end]))
            i = end
            code_start = i
            continue
        if ch == "/" and text[i + 1 : i + 2] == "*":
            if i > code_start:
                segments.append(("code", text[code_start:i]))
            depth = 1
            j = i + 2
            while j < n and depth > 0:
                two = text[j : j + 2]
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
    """The outcome of `_resolve_scan`. `segments` is the
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
    to trust, in this order (a bare "did a span merely run off the end?"
    guard is not enough — see the module docstring):

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
    with **no** warning, or MySQL escape handling would regress back to
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
    ever sees it — left in place, a
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
    warn and return the text completely unstripped —
    naming plainly that a table or column below may be **fabricated**
    from commented-out DDL that never got stripped, or that a real one
    may be missing, since "comments unstripped" alone does not convey
    that risk to a reader relying on this document as ground truth."""
    resolution = _resolve_scan(text)
    if resolution.segments is None:
        _warn(
            warnings,
            rel,
            f"could not reliably track quoting/comments in {rel} under either "
            "backslash-escaping reading (an unterminated string literal, quoted "
            "identifier, or block comment) — leaving this file's comments "
            "unstripped; a table or column below may be FABRICATED from "
            "commented-out DDL that was never stripped, or a real one may be "
            "missing",
        )
        return text
    if resolution.ambiguous:
        _warn(warnings, rel, f"{rel}: {_AMBIGUOUS_DIALECT_NOTE}")
    # A block comment keeps its newlines so `file:line` sites stay true.
    return "".join(
        "\n" * seg.count("\n") if kind == "block_comment" else seg
        for kind, seg in resolution.segments
        if kind != "line_comment"
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


def _split_top_level_quote_blind(body: str, brackets: bool = False) -> list[str]:
    """A plain paren-depth-0 split (`brackets=True`: also `[]` and `{}`
    depth, for Python/C# argument lists), with no quote awareness at all —
    the fallback for when `_scan_sql` desyncs. A quote-blind split can
    over-split on a literal's own comma
    or paren (visibly wrong: an extra, oddly-shaped "column"), but it
    can never silently swallow a real column the way a desynced
    quote-aware split can — and in a module whose whole point is to be
    ground truth, visibly wrong beats silently missing."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    openers, closers = ("([{", ")]}") if brackets else ("(", ")")
    for ch in body:
        if ch in openers:
            depth += 1
            current.append(ch)
        elif ch in closers:
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
    column definition, on top of the plain `DECIMAL(10,2)` /
    `PRIMARY KEY (a, b)` cases. If
    `_resolve_scan` can't produce a trustworthy reading at all (both
    backslash readings desynced), this body's actual quoting defeated
    the tracker — warn naming the file and fall back to
    `_split_top_level_quote_blind`, which can over-split (a column's
    name or type may look odd) but never silently deletes a column."""
    resolution = _resolve_scan(body)
    if resolution.segments is None:
        _warn(
            warnings,
            rel,
            f"could not reliably parse quoted text in {rel} under either "
            "backslash-escaping reading (an unterminated string literal or "
            "quoted identifier) — falling back to a quote-blind column split "
            "for this table; a column's name or type may be wrong",
        )
        return _split_top_level_quote_blind(body)
    if resolution.ambiguous:
        _warn(warnings, rel, f"{rel}: {_AMBIGUOUS_DIALECT_NOTE}")

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


_INLINE_UNIQUE_RE = re.compile(r"\bUNIQUE\b", re.I)
_INLINE_UNIQUE_NAME_RE = re.compile(
    r"\bCONSTRAINT\s+(?P<name>\"[^\"]*\"|`[^`]*`|\[[^\]]*\]|[\w.]+)\s+UNIQUE\b", re.I
)
# A constraint entry naming a key family that `_parse_key` could not take in.
_KEY_FAMILY_RE = re.compile(
    r"^(?:CONSTRAINT\s+(?:\"[^\"]*\"|`[^`]*`|\[[^\]]*\]|\S+)\s+)?"
    r"(?:PRIMARY|UNIQUE|INDEX|KEY|FULLTEXT|SPATIAL)\b",
    re.I,
)


def _split_sql_columns(
    body: str, rel: str, warnings: list[str]
) -> tuple[list[tuple[str, str]], str, list[tuple[str, str, bool]], bool]:
    """Column list, PK, indexes and an `unparsed` flag, from one `CREATE
    TABLE` body. A top-level entry is only a table constraint (dropped
    from the column list) when it starts with a constraint keyword at a
    `\\b` word boundary (`_TABLE_CONSTRAINT_RE`) — never a bare
    `startswith`, which would also discard a real column named e.g.
    `unique_code` or `constraint_name`. `PRIMARY KEY (...)` is captured
    into `pk` verbatim. An inline `PRIMARY KEY` on a column (no separate
    table constraint) is also detected, recording that column's bare name.
    `UNIQUE (...)`, `CONSTRAINT n UNIQUE (...)`, MySQL `[UNIQUE] KEY|INDEX
    n (...)` and an inline column `UNIQUE` are recorded as indexes
    (`(unnamed)` where nameless). `unparsed` is True when a key/unique
    entry was dropped without being understood."""
    columns: list[tuple[str, str]] = []
    indexes: list[tuple[str, str, bool]] = []
    pk = ""
    unparsed = False
    for entry in _split_top_level(body, rel, warnings):
        key = _parse_key(entry)
        if key:
            kind, kname, cols = key
            if kind == "PRIMARY KEY":
                if not pk:
                    pk = (
                        entry
                        if _PRIMARY_KEY_CONSTRAINT_RE.match(entry)
                        else f"PRIMARY KEY ({cols})"
                    )
            else:
                _add_index_to(indexes, kname, cols, kind.startswith("UNIQUE"))
            continue
        if _TABLE_CONSTRAINT_RE.match(entry):
            if not pk and _PRIMARY_KEY_CONSTRAINT_RE.match(entry):
                pk = entry
            elif _KEY_FAMILY_RE.match(entry):
                unparsed = True
            continue
        if _BODY_OPAQUE_RE.match(entry) or (
            _BODY_KEYLIKE_RE.match(entry) and _COLUMN_LIST_OPEN_RE.search(entry)
        ):
            unparsed = True
            continue
        tokens = entry.split(None, 1)
        if not tokens:
            continue
        cname = _clean_name(tokens[0])
        rest = _clean_type(tokens[1]) if len(tokens) > 1 else ""
        columns.append((cname, rest))
        if not pk and "PRIMARY KEY" in rest.upper():
            pk = cname
        if _INLINE_UNIQUE_RE.search(_mask_quoted_spans(rest)):
            named = _INLINE_UNIQUE_NAME_RE.search(rest)
            _add_index_to(
                indexes, _clean_name(named.group("name")) if named else "", cname, True
            )
    return columns, pk, indexes, unparsed


_Q = r"(?:\"[^\"]+\"|`[^`]+`|\[[^\]]+\]|[A-Za-z_]\w*)"
_QIDENT = rf"(?P<{{}}>(?:{_Q}\s*\.\s*)*{_Q})"  # optionally schema-qualified
_IDENT = r"[\"`\[]?(?P<{}>[A-Za-z_][\w.]*)[\"`\]]?"
_SEGMENT_RE = re.compile(r"\"[^\"]+\"|`[^`]+`|\[[^\]]+\]|[^.\s]+")

_CREATE_TABLE_HEAD_RE = re.compile(
    r"CREATE\s+(?:(?:GLOBAL|LOCAL|TEMP|TEMPORARY|UNLOGGED)\s+)*TABLE\b", re.I
)
_CREATE_INDEX_HEAD_RE = re.compile(r"CREATE\s+(?:[A-Za-z]+\s+){0,4}?INDEX\b", re.I)
_ALTER_TABLE_HEAD_RE = re.compile(r"ALTER\s+TABLE\b", re.I)
_ALTER_INDEX_HEAD_RE = re.compile(r"ALTER\s+INDEX\b", re.I)
_DROP_INDEX_HEAD_RE = re.compile(r"DROP\s+INDEX\b", re.I)
_DROP_TABLE_HEAD_RE = re.compile(r"DROP\s+TABLE\b", re.I)

CREATE_INDEX_RE = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?(?P<mods>(?:(?:UNIQUE|FULLTEXT|SPATIAL|CLUSTERED|"
    r"NONCLUSTERED|COLUMNSTORE)\s+)*)INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?"
    rf"(?:{_QIDENT.format('name')}\s+)?ON\s+(?:ONLY\s+)?{_QIDENT.format('table')}\s*"
    r"(?:USING\s+\w+\s*)?\(",
    re.I,
)
_DROP_INDEX_RE = re.compile(
    r"DROP\s+INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+EXISTS\s+)?(?P<names>.+?)"
    rf"(?:\s+ON\s+{_QIDENT.format('table')})?(?:\s+(?:CASCADE|RESTRICT))?\s*$",
    re.I | re.S,
)
_DROP_TABLE_RE = re.compile(
    r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?P<names>.+?)(?:\s+(?:CASCADE|RESTRICT))?\s*$",
    re.I | re.S,
)
_PARTITION_OF_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    rf"{_IDENT.format('child')}\s+PARTITION\s+OF\s+{_QIDENT.format('parent')}",
    re.I,
)
_PARTITION_BY_RE = re.compile(r"PARTITION\s+BY\s+(?P<kind>RANGE|LIST|HASH)\s*\(", re.I)
_ALTER_HEAD_RE = re.compile(
    rf"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?{_QIDENT.format('name')}(?:\s*\*)?",
    re.I,
)
# `[CONSTRAINT n] PRIMARY KEY|UNIQUE (cols)` plus MySQL's
# `[UNIQUE|FULLTEXT|SPATIAL] INDEX|KEY n [USING x] (cols)`, up to the
# opening paren. The column list must start like a column, not like a
# length: `key VARCHAR(10)` is a column.
_KEY_HEAD_RE = re.compile(
    rf"^(?:CONSTRAINT\s+{_IDENT.format('cname')}\s+)?"
    r"(?P<kind>PRIMARY\s+KEY|(?:UNIQUE|FULLTEXT|SPATIAL)(?:\s+(?:INDEX|KEY))?|INDEX|KEY)\b\s*"
    rf"(?:{_IDENT.format('iname')}\s*)?(?:USING\s+\w+\s*)?\((?=\s*[A-Za-z_`\"\[(])",
    re.I,
)
_ALTER_INDEX_RENAME_RE = re.compile(
    rf"ALTER\s+INDEX\s+(?:IF\s+EXISTS\s+)?{_QIDENT.format('old')}\s+RENAME\s+TO\s+"
    rf"{_QIDENT.format('new')}\s*$",
    re.I,
)
_ALTER_INDEX_HEAD_PARTS_RE = re.compile(
    rf"ALTER\s+INDEX\s+(?:IF\s+EXISTS\s+)?{_QIDENT.format('old')}\s+(?P<rest>.*)$",
    re.I | re.S,
)
_PARTITION_MOVE_RE = re.compile(
    rf"(?P<op>ATTACH|DETACH)\s+PARTITION\s+{_QIDENT.format('child')}", re.I
)
# ALTER actions that cannot change a fact shown in a `db.*` section (a
# column and its default, the primary key, an index, the partition clause,
# a partition child). Everything else this reader does not apply is a
# coverage site — `SET DEFAULT`/`SET COMPRESSION` included: the Type cell
# shows defaults.
_SILENT_ALTER_ACTIONS_RE = re.compile(
    r"(?:OWNER\s+TO"
    r"|(?:SET|RESET)\s*\("
    r"|SET\s+(?:LOGGED|UNLOGGED|TABLESPACE|WITHOUT\s+(?:CLUSTER|OIDS)|ACCESS\s+METHOD)"
    r"|(?:ENABLE|DISABLE)\s+(?:ALWAYS\s+|REPLICA\s+)?(?:TRIGGER|RULE|ROW\s+LEVEL\s+SECURITY)"
    r"|(?:FORCE|NO\s+FORCE)\s+ROW\s+LEVEL\s+SECURITY"
    r"|CLUSTER\s+ON"
    r"|REPLICA\s+IDENTITY"
    rf"|ALTER\s+(?:COLUMN\s+)?{_Q}\s+(?:SET\s+(?:STATISTICS|STORAGE)"
    r"|SET\s*\(|RESET\s*\())\b",
    re.I,
)
# `ADD ...` constraints that do not move a shown fact (warn, no site).
_SILENT_ADD_RE = re.compile(
    rf"^(?:CONSTRAINT\s+{_Q}\s+)?(?:FOREIGN\s+KEY|CHECK|REFERENCES)\b", re.I
)
_SIMPLE_INDEX_COL_RE = re.compile(
    r"^(?P<col>\"[^\"]+\"|`[^`]+`|\[[^\]]+\]|[\w.]+)(?:\s+(?:ASC|DESC)\b.*)?$", re.I
)


def _norm_name(raw: str) -> str:
    """`"public"."t"` / `[dbo].[t]` / `public.t` -> `public.t`."""
    return ".".join(_clean_name(seg) for seg in _SEGMENT_RE.findall(raw))


def _bare(raw: str) -> str:
    """The unqualified last segment: `public.i` -> `i`."""
    return _norm_name(raw).rsplit(".", 1)[-1]


_DEFAULT_SCHEMAS = frozenset({"", "public", "dbo", "main"})


def _schema_of(name: str) -> str:
    """The schema qualifier of a normalised name (`audit.t` -> `audit`)."""
    parts = name.casefold().split(".")
    return parts[-2] if len(parts) >= 2 else ""


def _schema_ok(stmt_schema: str, record_schema: str) -> bool:
    """May a statement qualified `stmt_schema` apply to a table kept under
    `record_schema`? An unqualified statement may (the search path is
    unknown); a qualified one only to the same schema, or between default
    schemas (`public.t` vs a bare `CREATE TABLE t`)."""
    stmt_schema, record_schema = stmt_schema.casefold(), record_schema.casefold()
    return (
        not stmt_schema
        or stmt_schema == record_schema
        or (stmt_schema in _DEFAULT_SCHEMAS and record_schema in _DEFAULT_SCHEMAS)
    )


def _find_table(tables: dict[str, TableRecord], raw: str) -> TableRecord | None:
    """A table by the name as written, else by its bare name when exactly
    one table has it in a compatible schema (`ON t` vs `CREATE TABLE
    public.t`) — `audit.t` never resolves to a `t` kept under `public`."""
    name = _norm_name(raw)
    if name in tables:
        return tables[name]
    bare, schema = name.rsplit(".", 1)[-1], _schema_of(name)
    same = [
        r
        for k, r in tables.items()
        if k.rsplit(".", 1)[-1] == bare and _schema_ok(schema, _schema_of(k))
    ]
    return same[0] if len(same) == 1 else None


def _parse_key(text: str) -> tuple[str, str, str] | None:
    """`(kind, name, cols)` of a key/index definition (`kind` is
    `PRIMARY KEY`, `UNIQUE`, `UNIQUE KEY`, `INDEX`, ... upper-cased, one
    space), or `None` when `text` is not one this reader understands —
    `UNIQUE USING INDEX x`, `UNIQUE NULLS NOT DISTINCT (a)`, a column."""
    m = _KEY_HEAD_RE.match(text)
    if not m:
        return None
    open_idx = m.end() - 1
    close_idx = _matching_close_paren(text, open_idx)
    if text[close_idx : close_idx + 1] != ")":
        return None
    kind = " ".join(m.group("kind").upper().split())
    name = _clean_name(m.group("cname") or m.group("iname") or "")
    return kind, name, _index_columns(text[open_idx + 1 : close_idx])


def _index_columns(body: str) -> str:
    """Comma-joined column names of an index/constraint column list. A
    plain column loses its quoting and `ASC`/`DESC`; anything else (an
    expression) is kept as written, whitespace collapsed."""
    cols = []
    for part in _split_top_level_quote_blind(body):
        m = _SIMPLE_INDEX_COL_RE.match(part)
        cols.append(_clean_name(m.group("col")) if m else _clean_type(part))
    return ", ".join(cols)


def _table_for(
    tables: dict[str, TableRecord],
    name: str,
    rel: str,
    what: str,
    warnings: list[str],
    line: int | None = None,
) -> TableRecord | None:
    """The record `what` (an index, constraint or partition statement in
    `rel`) applies to, or `None` plus a warning when there is none — the
    table is unknown, or was created in a different migration set (the
    same guard as `ADD COLUMN`: two such tables are not the same table)."""
    record = _find_table(tables, name)
    name = _norm_name(name)
    if record is None:
        _warn(warnings, rel, f"{what} on unknown table {name!r} in {rel}", line)
        return None
    if _dirname(record.created_in) != _dirname(rel):
        _warn(
            warnings,
            rel,
            f"{what} on {name!r} in {rel} not applied — the table kept for "
            f"{name!r} was created in {record.created_in}, a different "
            "migration directory",
            line,
        )
        return None
    return record


def _site_for(
    tables: dict[str, TableRecord],
    name: str,
    rel: str,
    line: int,
    warnings: list[str],
) -> None:
    """A statement this reader did not take in may have changed what a
    table shows: record the site on the table it names (if it is the one
    kept), else on the reader's (scope, reader) row."""
    record = _find_table(tables, name) if name else None
    if record is not None and _dirname(record.created_in) == _dirname(rel):
        record.schema_partial.append(_site(rel, line))
    elif isinstance(warnings, _Warnings):
        warnings.sites.append((rel, _site(rel, line)))


def _unrecognised(warnings: list[str], rel: str, line: int, what: str) -> None:
    _warn(
        warnings,
        rel,
        f"could not recognise this {what} statement at {rel}:{line} — "
        "skipped, not guessed at",
        line,
    )


def _apply_create_index(
    m: re.Match[str],
    text: str,
    masked: str,
    rel: str,
    tables: dict[str, TableRecord],
    warnings: list[str],
) -> None:
    open_idx = m.end() - 1
    close_idx = _matching_close_paren(masked, open_idx)
    record = _table_for(
        tables,
        m.group("table"),
        rel,
        "CREATE INDEX",
        warnings,
        _line_of(text, m.start()),
    )
    if record is None:
        return
    name = _bare(m.group("name")) if m.group("name") else ""
    _add_index(
        record,
        name,
        _index_columns(text[open_idx + 1 : close_idx]),
        "UNIQUE" in m.group("mods").upper(),
    )


def _apply_drop_index(
    stmt: str, rel: str, line: int, tables: dict[str, TableRecord], warnings: list[str]
) -> None:
    """Replay `DROP INDEX [schema.]i[, j] [ON t]`: a dropped index must not
    stay listed; a name that is not a known index is a site."""
    m = _DROP_INDEX_RE.match(stmt)
    if not m:
        _unrecognised(warnings, rel, line, "DROP INDEX")
        return
    only = _find_table(tables, m.group("table")) if m.group("table") else None
    unknown = False
    for raw in m.group("names").split(","):
        dropped, schema = _bare(raw), _schema_of(_norm_name(raw))
        hit = False
        for record in tables.values():
            if _dirname(record.created_in) != _dirname(rel):
                continue
            if only is not None and record is not only:
                continue
            if not _schema_ok(schema, _schema_of(record.name)):
                continue
            kept = [ix for ix in record.indexes if ix[0] != dropped]
            hit = hit or len(kept) != len(record.indexes)
            record.indexes = kept
        unknown = unknown or not hit
    if unknown:
        _unrecognised(warnings, rel, line, "DROP INDEX (no known index)")


def _apply_drop_table(
    stmt: str, rel: str, line: int, tables: dict[str, TableRecord], warnings: list[str]
) -> None:
    """Replay `DROP TABLE [IF EXISTS] a[, b]`: a dropped table is gone. A
    name this migration set never created is nothing to remove; one kept
    from a different migration directory is a site."""
    m = _DROP_TABLE_RE.match(stmt)
    if not m:
        _unrecognised(warnings, rel, line, "DROP TABLE")
        return
    for raw in m.group("names").split(","):
        child = _bare(raw)
        for parent in tables.values():  # a dropped partition leaves its parent
            if _dirname(parent.created_in) == _dirname(rel):
                parent.partitions = [c for c in parent.partitions if _bare(c) != child]
        record = _find_table(tables, raw)
        if record is None:
            continue
        if _dirname(record.created_in) == _dirname(rel):
            del tables[record.name]
        else:
            _unrecognised(warnings, rel, line, "DROP TABLE (other migration directory)")


def _apply_add_key(record: TableRecord, key: tuple[str, str, str]) -> None:
    kind, name, cols = key
    if kind == "PRIMARY KEY":
        if not record.pk:
            record.pk = f"PRIMARY KEY ({cols})"
        return
    _add_index(record, name, cols, kind.startswith("UNIQUE"))


def _apply_add_action(
    action: str,
    name: str,
    stmt: str,
    rel: str,
    line: int,
    tables: dict[str, TableRecord],
    warnings: list[str],
) -> TableRecord | None:
    """One `ADD ...` action (the `ADD` already stripped) of an `ALTER
    TABLE`. Returns the record a column was added to, if any."""
    key = _parse_key(action)
    if key:
        record = _table_for(
            tables, name, rel, "ALTER TABLE ADD CONSTRAINT", warnings, line
        )
        if record is not None:
            _apply_add_key(record, key)
        return None
    if _ADD_NON_COLUMN_RE.match(action):
        # "ALTER TABLE ... ADD CONSTRAINT/INDEX ..." must never become a
        # column named "CONSTRAINT". FOREIGN KEY / CHECK move no shown
        # fact and only warn; any other constraint this reader could not
        # parse is a site on the table.
        warnings.append(
            f"ALTER TABLE ADD CONSTRAINT/INDEX (not a column) skipped in {rel}: {stmt.strip()}"
        )
        if not _SILENT_ADD_RE.match(action):
            _site_for(tables, name, rel, line, warnings)
        return None
    tokens = action.split(None, 1)
    if not tokens:
        return None
    cname = _clean_name(tokens[0])
    rest = _clean_type(tokens[1]) if len(tokens) > 1 else ""
    record = _find_table(tables, name)
    if record is None:
        _warn(
            warnings,
            rel,
            f"ALTER TABLE ADD COLUMN on unknown table {name!r} in {rel}",
            line,
        )
        return None
    if _dirname(record.created_in) != _dirname(rel):
        _warn(
            warnings,
            rel,
            f"ALTER TABLE {name!r} ADD COLUMN in {rel} not applied — the "
            f"table kept for {name!r} was created in {record.created_in}, "
            "a different migration directory",
            line,
        )
        return None
    record.columns.append((cname, rest))
    record.source = _join_source(record.source, rel)
    if not record.pk and "PRIMARY KEY" in rest.upper():
        record.pk = cname
    return record


def _apply_partition_move(
    pm: re.Match[str],
    name: str,
    rel: str,
    line: int,
    tables: dict[str, TableRecord],
    warnings: list[str],
) -> None:
    """`ALTER TABLE p ATTACH|DETACH PARTITION c`: keep `Partitions:` true."""
    child = _bare(pm.group("child"))
    if pm.group("op").upper() == "ATTACH":
        record = _table_for(tables, name, rel, "ATTACH PARTITION", warnings, line)
        if record is not None and child not in record.partitions:
            record.partitions.append(child)
        return
    record = _find_table(tables, name)
    if (
        record is not None
        and _dirname(record.created_in) == _dirname(rel)
        and child in record.partitions
    ):
        record.partitions.remove(child)
    else:
        _site_for(tables, name, rel, line, warnings)


def _apply_alter_index(
    stmt: str, rel: str, line: int, tables: dict[str, TableRecord], warnings: list[str]
) -> None:
    """`ALTER INDEX old RENAME TO new` (Prisma emits it on renames); other
    forms are silent only when they cannot move a shown fact."""
    m = _ALTER_INDEX_RENAME_RE.match(stmt)
    if m:
        old, new = _bare(m.group("old")), _bare(m.group("new"))
        schema = _schema_of(_norm_name(m.group("old")))
        found = False
        for record in tables.values():
            if _dirname(record.created_in) != _dirname(rel):
                continue
            if not _schema_ok(schema, _schema_of(record.name)):
                continue
            for i, (name, cols, unique) in enumerate(record.indexes):
                if name == old:
                    record.indexes[i] = (new, cols, unique)
                    found = True
        if not found:
            _unrecognised(warnings, rel, line, "ALTER INDEX (no known index)")
        return
    rest = _ALTER_INDEX_HEAD_PARTS_RE.match(stmt)
    if not (rest and _SILENT_ALTER_ACTIONS_RE.match(rest.group("rest").strip())):
        _unrecognised(warnings, rel, line, "ALTER INDEX")


def _apply_alter_action(
    action: str,
    name: str,
    stmt: str,
    rel: str,
    line: int,
    tables: dict[str, TableRecord],
    warnings: list[str],
) -> TableRecord | None:
    """One comma-separated action of an `ALTER TABLE`: applied, silent
    (`_SILENT_ALTER_ACTIONS_RE`), or a site. Returns the record a column
    was added to, if any."""
    if _SILENT_ALTER_ACTIONS_RE.match(action):
        return None
    pm = _PARTITION_MOVE_RE.match(action)
    if pm:
        _apply_partition_move(pm, name, rel, line, tables, warnings)
        return None
    if re.match(r"ADD\b", action, re.I):
        body = re.sub(
            r"^ADD\s+(?:COLUMN\s+)?(?:IF\s+NOT\s+EXISTS\s+)?", "", action, flags=re.I
        )
        return _apply_add_action(body, name, stmt, rel, line, tables, warnings)
    if re.search(r"\b(?:RENAME|DROP)\b", action, re.I):
        warnings.append(f"unsupported DDL in {rel}: {stmt.strip()}")
    _site_for(tables, name, rel, line, warnings)
    return None


def _apply_alter(
    stmt: str, rel: str, line: int, tables: dict[str, TableRecord], warnings: list[str]
) -> None:
    """`ALTER TABLE [IF EXISTS] [ONLY] t action[, action ...]`. Every
    action ends applied, silent, or as a site — never quietly dropped."""
    head = _ALTER_HEAD_RE.match(stmt)
    actions = (
        _split_top_level(stmt[head.end() :].strip(), rel, warnings) if head else []
    )
    if not head or not actions:
        _unrecognised(warnings, rel, line, "ALTER TABLE")
        return
    name = _norm_name(head.group("name"))
    touched: TableRecord | None = None
    for action in actions:
        added = _apply_alter_action(action, name, stmt, rel, line, tables, warnings)
        touched = added or touched
    if touched is not None:
        touched.ddl = touched.ddl + "\n\n" + stmt.strip()


def _partition_clause(text: str, masked: str, start: int, end: int) -> str:
    """`RANGE (expr)` from a `PARTITION BY` clause between a table's
    closing paren and its statement end, or `""` when there is none."""
    pm = _PARTITION_BY_RE.search(masked, start, end)
    if not pm:
        return ""
    open_idx = pm.end() - 1
    close_idx = _matching_close_paren(masked, open_idx)
    if masked[close_idx : close_idx + 1] != ")":
        return ""
    return f"{pm.group('kind').upper()} ({_clean_type(text[open_idx + 1 : close_idx])})"


def _apply_partition_of(
    m: re.Match[str],
    line: int,
    rel: str,
    tables: dict[str, TableRecord],
    warnings: list[str],
) -> None:
    """`CREATE TABLE child PARTITION OF parent ...` lists `child` on the parent."""
    record = _table_for(tables, m.group("parent"), rel, "PARTITION OF", warnings, line)
    if record is not None and m.group("child") not in record.partitions:
        record.partitions.append(m.group("child"))


def _apply_create_table(
    m: re.Match[str],
    text: str,
    masked: str,
    rel: str,
    tables: dict[str, TableRecord],
    warnings: list[str],
) -> None:
    name = m.group("name")
    open_idx = m.end() - 1  # CREATE_RE's match ends right after the "("
    close_idx = _matching_close_paren(masked, open_idx)
    body = text[open_idx + 1 : close_idx]
    # The table's real closing paren may be followed by a dialect-specific
    # trailing clause before the statement actually ends — MySQL `)
    # ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;`, SQLite `) WITHOUT ROWID;`,
    # Postgres `) PARTITION BY RANGE (id);` — so the terminator is
    # whatever `;` comes next, not an immediate `);`. A final CREATE TABLE
    # with no trailing `;` at all still parses: the body is already bounded.
    semi_idx = masked.find(";", close_idx + 1)
    stmt_end = semi_idx + 1 if semi_idx != -1 else len(text)
    ddl_text = text[m.start() : stmt_end].strip()
    if name in tables:
        existing = tables[name]
        if _dirname(existing.created_in) != _dirname(rel):
            # Two independent migration directories (a per-service schema
            # and a Flyway tree, say) that both create a table of this
            # name describe two different tables. Merging them would
            # fabricate a schema that exists nowhere; the first in
            # sorted-path order is kept whole and the warning names both.
            _warn(
                warnings,
                rel,
                f"duplicate CREATE TABLE {name!r} in {rel} — keeping the "
                f"definition from {existing.created_in} (a different "
                "migration directory); the two are not merged",
                _line_of(text, m.start()),
            )
        else:
            # A same-directory re-CREATE (most plausibly `IF NOT EXISTS`
            # re-asserting a table) must not discard the ALTER TABLE ...
            # ADD COLUMNs already accumulated — keep the first, warn.
            _warn_duplicate("CREATE TABLE", name, rel, warnings)
        return
    columns, pk, indexes, unparsed = _split_sql_columns(body, rel, warnings)
    tables[name] = TableRecord(
        name=name,
        columns=columns,
        pk=pk,
        ddl=ddl_text,
        source=rel,
        created_in=rel,
        partition=_partition_clause(text, masked, close_idx + 1, stmt_end),
        indexes=indexes,
        schema_partial=[_site(rel, _line_of(text, m.start()))] if unparsed else [],
    )


_STATEMENT_SEP_RE = re.compile(r";|^[ \t]*GO[ \t]*$", re.I | re.M)
_DOLLAR_QUOTED_RE = re.compile(r"\$(?P<tag>\w*)\$.*?\$(?P=tag)\$", re.S)
# DDL that starts a new statement. Found inside one `;`-span after its head,
# a separator is missing and the second statement would be lost.
_NEW_STATEMENT_RE = re.compile(
    r"\b(?:CREATE\s|ALTER\s+(?:TABLE|INDEX)\b|RENAME\s+TABLE\b|"
    r"DROP\s+(?:TABLE|INDEX|VIEW|SCHEMA|SEQUENCE|TYPE|FUNCTION|TRIGGER)\b)",
    re.I,
)
# Statement heads that cannot change a shown fact (a table's columns,
# primary key, indexes, partitions). Any other head is a coverage site.
_NEUTRAL_HEAD_RE = re.compile(
    r"(?:INSERT|UPDATE|DELETE|SELECT|SET|BEGIN|COMMIT|ROLLBACK|END|TRUNCATE"
    r"|START\s+TRANSACTION|GRANT|REVOKE|COMMENT\s+ON|USE|PRAGMA|ANALYZE|VACUUM|LOCK"
    r"|CREATE\s+(?:OR\s+REPLACE\s+)?(?:(?:TEMP|TEMPORARY|MATERIALIZED|RECURSIVE)\s+)*"
    r"(?:VIEW|FUNCTION|PROCEDURE|TRIGGER|TYPE|EXTENSION|SEQUENCE|SCHEMA|ROLE|USER"
    r"|POLICY|RULE|DOMAIN|AGGREGATE|COLLATION|OPERATOR|CAST|PUBLICATION"
    r"|SUBSCRIPTION|DATABASE|TABLESPACE|EVENT|STATISTICS)"
    r"|ALTER\s+(?:MATERIALIZED\s+)?(?:SEQUENCE|SCHEMA|TYPE|VIEW|FUNCTION|PROCEDURE"
    r"|TRIGGER|EXTENSION|ROLE|USER|POLICY|RULE|DOMAIN|DEFAULT\s+PRIVILEGES|DATABASE"
    r"|SYSTEM|TABLESPACE|PUBLICATION|SUBSCRIPTION|COLLATION|AGGREGATE|OPERATOR"
    r"|STATISTICS)"
    r"|DROP\s+(?:MATERIALIZED\s+)?(?:VIEW|FUNCTION|PROCEDURE|TRIGGER|TYPE|SEQUENCE"
    r"|SCHEMA|EXTENSION|ROLE|USER|POLICY|RULE|DOMAIN|AGGREGATE|DATABASE|TABLESPACE"
    r"|PUBLICATION|SUBSCRIPTION))\b",
    re.I,
)
_RENAME_TABLE_RE = re.compile(rf"RENAME\s+TABLE\s+{_QIDENT.format('name')}", re.I)


def _statement_spans(masked: str) -> list[tuple[int, int]]:
    """`(start, end)` of each non-empty statement, split on `;` and on a
    line that is just `GO` (T-SQL). `masked` has quoted text blanked, so a
    separator inside a literal never splits."""
    spans = []
    pos = 0
    for sep in [*_STATEMENT_SEP_RE.finditer(masked), None]:
        end = len(masked) if sep is None else sep.start()
        chunk = masked[pos:end]
        start = pos + (len(chunk) - len(chunk.lstrip()))
        if start < end:
            spans.append((start, end))
        if sep is not None:
            pos = sep.end()
    return spans


def _mask_dollar_quoted(masked: str) -> str:
    """Blank `$$ ... $$` bodies (function and `DO` bodies): their `;` must
    not split a statement, and DDL inside is not a migration step."""
    return _DOLLAR_QUOTED_RE.sub(lambda m: re.sub(r"[^\n]", "\0", m.group(0)), masked)


def _apply_sql_file(
    text: str, rel: str, tables: dict[str, TableRecord], warnings: list[str]
) -> None:
    """Replay one migration file, statement by statement in file order.
    Every statement is applied, fact-neutral (`_NEUTRAL_HEAD_RE`), or a
    coverage site (`_unrecognised`, `_site_for`) — an unknown head, a
    handled kind no handler fully applies, or a second statement left
    inside the span for lack of a `;`/`GO`. There is no silent fall-through."""
    text = _strip_sql_comments(text, rel, warnings)
    # Same length as `text`, quoted spans replaced with filler — used only
    # to find structure (closing parens, statement ends) without a
    # literal's own `(`, `)`, or `;` throwing it off. `text` itself
    # (unmasked) is what names and column text are sliced from.
    masked = _mask_dollar_quoted(_mask_quoted_spans(text))
    create_at = {m.start(): m for m in CREATE_RE.finditer(text)}
    partition_of_at = {m.start(): m for m in _PARTITION_OF_RE.finditer(text)}

    for start, end in _statement_spans(masked):
        head = masked[start:end]
        stmt = text[start:end]
        line = _line_of(text, start)
        if hm := _CREATE_TABLE_HEAD_RE.match(head):
            if start in create_at:
                _apply_create_table(
                    create_at[start], text, masked, rel, tables, warnings
                )
            elif start in partition_of_at:
                _apply_partition_of(partition_of_at[start], line, rel, tables, warnings)
            else:
                _unrecognised(warnings, rel, line, "CREATE TABLE")
        elif hm := _CREATE_INDEX_HEAD_RE.match(head):
            m = CREATE_INDEX_RE.match(text, start, end)
            if m:
                _apply_create_index(m, text, masked, rel, tables, warnings)
            else:
                _unrecognised(warnings, rel, line, "CREATE INDEX")
        elif hm := _ALTER_TABLE_HEAD_RE.match(head):
            _apply_alter(stmt, rel, line, tables, warnings)
        elif hm := _ALTER_INDEX_HEAD_RE.match(head):
            _apply_alter_index(stmt, rel, line, tables, warnings)
        elif hm := _DROP_INDEX_HEAD_RE.match(head):
            _apply_drop_index(stmt, rel, line, tables, warnings)
        elif hm := _DROP_TABLE_HEAD_RE.match(head):
            _apply_drop_table(stmt, rel, line, tables, warnings)
        elif _NEUTRAL_HEAD_RE.match(head):
            continue
        else:
            rename = _RENAME_TABLE_RE.match(head)
            word = re.match(r"[A-Za-z]+", head)
            _unrecognised(warnings, rel, line, word.group(0).upper() if word else "?")
            if rename:
                _site_for(tables, _norm_name(rename.group("name")), rel, line, warnings)
            continue
        if _NEW_STATEMENT_RE.search(head, hm.end()):
            _unrecognised(
                warnings,
                rel,
                line,
                "statement (a `;` or GO is missing before the next one)",
            )


def _read_sql(
    root: Path, opts: CodeIngestOptions
) -> tuple[dict[str, TableRecord], list[str]]:
    warnings = _Warnings()
    found: set[Path] = set()
    for pattern in MIGRATION_GLOBS:
        found.update(_glob_via_walk(root, opts.kb_dir, pattern))

    tables: dict[str, TableRecord] = {}
    for path in sorted(found, key=lambda p: relposix(root, p)):
        rel = relposix(root, path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            _warn(warnings, rel, f"could not parse {rel}: {exc}")
            continue
        try:
            _apply_sql_file(text, rel, tables, warnings)
        except Exception as exc:  # noqa: BLE001 -- defense in depth, see comment below
            # Defense in depth: a parse-time bug on this one file must
            # never unwind past this loop and discard every other file's
            # already-accumulated tables with a warning that names no
            # file — a defect class that is easy to reintroduce.
            _warn(warnings, rel, f"could not parse {rel}: {exc}")
    return tables, warnings


# ---------------------------------------------------------------------------
# reader: prisma — model blocks in schema.prisma
# ---------------------------------------------------------------------------

PRISMA_GLOB = "**/schema.prisma"
PRISMA_MODEL_RE = re.compile(r"^model\s+(\w+)\s*\{(.*?)^\}", re.S | re.M)


_PRISMA_BLOCK_ATTR_RE = re.compile(r"^@@(?P<attr>id|unique|index)\((?P<args>.*)\)$")
_PRISMA_MAP_RE = re.compile(r'^@@map\(\s*(?:name:\s*)?"(?P<table>[^"]+)"')
_PRISMA_FIELDS_RE = re.compile(r"^\s*(?:fields:\s*)?\[(?P<fields>[^\]]*)\]")
_PRISMA_DB_NAME_RE = re.compile(r'\b(?P<key>map|name):\s*"(?P<value>[^"]*)"')
_PRISMA_FIELD_UNIQUE_RE = re.compile(r"@unique\b(?:\((?P<args>[^)]*)\))?")


def _prisma_field_list(fields: str) -> str:
    """`a, title(length: 100)` -> `a, title`: field names only."""
    return ", ".join(
        part.split("(")[0].strip() for part in _split_top_level_quote_blind(fields)
    )


def _prisma_index_name(args: str) -> str:
    """The database name (`map:`) wins over the client name (`name:`);
    neither means `(unnamed)`."""
    found = {
        m.group("key"): m.group("value") for m in _PRISMA_DB_NAME_RE.finditer(args)
    }
    return found.get("map") or found.get("name") or ""


def _apply_prisma_block_attr(
    record: TableRecord, stripped: str, rel: str, line: int
) -> None:
    """`@@id`, `@@unique`, `@@index`, `@@map` on one model line. A key or
    index attribute that does not parse marks the table partial."""
    mapped = _PRISMA_MAP_RE.match(stripped)
    if mapped:
        record.table_name = mapped.group("table")
        return
    m = _PRISMA_BLOCK_ATTR_RE.match(stripped)
    if not m:
        if re.match(r"@@(?:id|unique|index)\b", stripped):
            record.schema_partial.append(_site(rel, line))
        return
    fields_m = _PRISMA_FIELDS_RE.match(m.group("args"))
    fields = _prisma_field_list(fields_m.group("fields")) if fields_m else ""
    if not fields:
        record.schema_partial.append(_site(rel, line))
    elif m.group("attr") == "id":
        record.pk = record.pk or f"PRIMARY KEY ({fields})"
    else:
        _add_index(
            record,
            _prisma_index_name(m.group("args")),
            fields,
            m.group("attr") == "unique",
        )


def _prisma_logical_lines(body: str, first_line: int) -> list[tuple[int, str]]:
    """`(line number, stripped text)` per model line, with a `@@attr(`
    that spans several lines joined onto one (numbered by its first)."""
    out: list[tuple[int, str]] = []
    pending: list[str] = []
    start = first_line
    for offset, line in enumerate(body.splitlines()):
        stripped = line.strip()
        if not pending and not (stripped.startswith("@@") and "(" in stripped):
            out.append((first_line + offset, stripped))
            continue
        if not pending:
            start = first_line + offset
        pending.append(stripped)
        joined = " ".join(pending)
        if joined.count("(") <= joined.count(")"):
            out.append((start, joined))
            pending = []
    if pending:  # never closed: keep it, it will mark the table partial
        out.append((start, " ".join(pending)))
    return out


def _apply_prisma_file(
    text: str, rel: str, tables: dict[str, TableRecord], warnings: list[str]
) -> None:
    for m in PRISMA_MODEL_RE.finditer(text):
        name = m.group(1)
        record = TableRecord(name=name, source=rel, created_in=rel)
        first_line = _line_of(text, m.start(2))
        for line_no, stripped in _prisma_logical_lines(m.group(2), first_line):
            if not stripped or stripped.startswith("//"):
                continue
            if stripped.startswith("@@"):
                _apply_prisma_block_attr(
                    record, re.sub(r"\s//.*$", "", stripped), rel, line_no
                )
                continue
            tokens = stripped.split(None, 1)
            fname = _clean_name(tokens[0])
            rest = _clean_type(tokens[1]) if len(tokens) > 1 else ""
            record.columns.append((fname, rest))
            if not record.pk and "@id" in rest:
                record.pk = fname
            unique = _PRISMA_FIELD_UNIQUE_RE.search(rest)
            if unique:
                _add_index(
                    record, _prisma_index_name(unique.group("args") or ""), fname, True
                )
        if name in tables:
            _warn_duplicate("prisma model", name, rel, warnings)
            continue
        record.ddl = _reconstruct_ddl(name, record.columns, record.pk)
        tables[name] = record


def _read_prisma(
    root: Path, opts: CodeIngestOptions
) -> tuple[dict[str, TableRecord], list[str]]:
    tables: dict[str, TableRecord] = {}
    warnings = _Warnings()
    paths = sorted(
        _glob_via_walk(root, opts.kb_dir, PRISMA_GLOB), key=lambda p: relposix(root, p)
    )
    for path in paths:
        rel = relposix(root, path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            _warn(warnings, rel, f"could not parse {rel}: {exc}")
            continue
        try:
            _apply_prisma_file(text, rel, tables, warnings)
        except Exception as exc:  # noqa: BLE001 -- defense in depth, mirrors _read_sql
            _warn(warnings, rel, f"could not parse {rel}: {exc}")
    return tables, warnings


# ---------------------------------------------------------------------------
# reader: alembic — op.create_table(...) / sa.Column(...) in versions/*.py
# ---------------------------------------------------------------------------

ALEMBIC_GLOB = "**/versions/*.py"
ALEMBIC_TABLE_RE = re.compile(r"op\.create_table\(\s*['\"](\w+)['\"]")
# Only the column *name* is captured; the type is the call's first
# top-level argument, found by balanced-paren scanning (`[^,)]+` would
# stop at the first paren, rendering `sa.Integer()` as `sa.Integer(`).
# `primary_key=True` among the remaining arguments marks
# the column as the PK.
ALEMBIC_COLUMN_RE = re.compile(r"sa\.Column\(\s*['\"](\w+)['\"]\s*,")


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


ALEMBIC_PK_CONSTRAINT_RE = re.compile(r"sa\.PrimaryKeyConstraint\(")
ALEMBIC_UNIQUE_RE = re.compile(r"sa\.UniqueConstraint\(")
# `op.<fn>(` and `<alias>.<fn>(` inside `with op.batch_alter_table(..) as <alias>`;
# anchored so `batch_op.create_index(` is not read as `op.create_index(`.
ALEMBIC_OP_RE = re.compile(
    r"(?<![\w.])(?P<recv>\w+)\.(?P<fn>create_index|create_unique_constraint|"
    r"create_primary_key|drop_index|drop_constraint|add_column|drop_column|"
    r"alter_column|rename_table|drop_table)\("
)
ALEMBIC_BATCH_RE = re.compile(r"with\s+op\.batch_alter_table\(")
# Raw SQL (`op.execute("CREATE INDEX ..")`, `conn.execute(..)`) is not read.
ALEMBIC_EXECUTE_RE = re.compile(r"\.execute\(")
_ALEMBIC_DEF_RE = re.compile(r"^def\s+(\w+)\s*\(", re.M)
# positional parameters: (as `op.<fn>`, as `<batch alias>.<fn>`)
_ALEMBIC_PARAMS = {
    "create_index": (
        ("index_name", "table_name", "columns"),
        ("index_name", "columns"),
    ),
    "create_unique_constraint": (
        ("name", "table_name", "columns"),
        ("name", "columns"),
    ),
    "create_primary_key": (("name", "table_name", "columns"), ("name", "columns")),
    "drop_index": (("index_name", "table_name"), ("index_name",)),
    "drop_constraint": (("name", "table_name"), ("name",)),
    "add_column": (("table_name", "column"), ("column",)),
    "drop_column": (("table_name", "column_name"), ("column_name",)),
    "alter_column": (("table_name", "column_name"), ("column_name",)),
    "rename_table": (("table_name", "new_table_name"), ("new_table_name",)),
    "drop_table": (("table_name",), ()),
}
# Ops this reader does not replay: they change a column or a table, so the
# table they name (or the file, when none) is a coverage site.
_ALEMBIC_UNTRACKED = frozenset(
    {"add_column", "drop_column", "alter_column", "rename_table", "drop_table"}
)
_QUOTED_RE = re.compile(r"""['"]([^'"]+)['"]""")
_KWARG_RE = re.compile(r"^(\w+)\s*=\s*(?!=)(.*)$", re.S)


def _string_literals(text: str) -> list[str]:
    return _QUOTED_RE.findall(text)


def _upgrade_only(text: str) -> str:
    """`text` with the bodies of `def downgrade*(` blanked (same offsets
    and line breaks): a downgrade re-creates and drops what the upgrade
    did, and must not be read as schema. `upgrade()`, multidb
    `upgrade_<engine>()` and the helpers they call all stay."""
    defs = list(_ALEMBIC_DEF_RE.finditer(text))
    out, pos = [], 0
    for i, d in enumerate(defs):
        if not d.group(1).startswith("downgrade"):
            continue
        end = defs[i + 1].start() if i + 1 < len(defs) else len(text)
        out.append(text[pos : d.start()])
        out.append(re.sub(r"[^\n]", " ", text[d.start() : end]))
        pos = end
    out.append(text[pos:])
    return "".join(out)


def _alembic_pk(names: list[str]) -> str:
    """Bare name for one column, a `PRIMARY KEY (a, b)` clause for several."""
    if len(names) <= 1:
        return names[0] if names else ""
    return f"PRIMARY KEY ({', '.join(names)})"


def _alembic_columns(
    scope: str,
) -> tuple[list[tuple[str, str]], str, list[tuple[str, str, bool]]]:
    """`(columns, pk, indexes)` for every `sa.Column('name', <type>, ...)` call in
    `scope` (one `op.create_table(...)` call's text). `pk` is a bare
    column name for a single primary key, or a `PRIMARY KEY (a, b)`
    clause for a composite one — the same form `_pk_clause`/
    `_reconstruct_ddl` and `_pk_columns` already parse (a composite PK
    must not be silently reduced to its first column)."""
    columns: list[tuple[str, str]] = []
    pk_names: list[str] = []
    indexes: list[tuple[str, str, bool]] = []
    for cm in ALEMBIC_COLUMN_RE.finditer(scope):
        call_open = scope.index("(", cm.start())
        call_close = _matching_close_paren(scope, call_open)
        # `call_close` is the closing `)`'s own index only when the call
        # actually closed; when `_matching_close_paren` fell back to
        # `len(scope) - 1` (never closed), that index is *at* the last
        # real character, and the exclusive slice below would silently
        # drop it — turning a visibly truncated `sa.Integer(` into a
        # plausible-looking, wrong, complete `sa.Integer`. Slice through
        # the end of `scope` instead so the
        # truncation stays visible.
        end = call_close if scope[call_close : call_close + 1] == ")" else len(scope)
        args = _split_top_level_quote_blind(scope[cm.end() : end])
        if not args:
            continue
        cname = _clean_name(cm.group(1))
        columns.append((cname, _clean_type(args[0])))
        if any(a.replace(" ", "") == "primary_key=True" for a in args[1:]):
            pk_names.append(cname)
        if any(a.replace(" ", "") == "unique=True" for a in args[1:]):
            _add_index_to(indexes, "", cname, True)
    for um in ALEMBIC_UNIQUE_RE.finditer(scope):
        close = _matching_close_paren(scope, um.end() - 1)
        uargs = _split_top_level_quote_blind(scope[um.end() : close], True)
        named = {k.group(1): k.group(2) for a in uargs if (k := _KWARG_RE.match(a))}
        _add_index_to(
            indexes,
            (_string_literals(named.get("name", "")) or [""])[0],
            ", ".join(
                lit
                for a in uargs
                if not _KWARG_RE.match(a)
                for lit in _string_literals(a)
            ),
            True,
        )
    if not pk_names:  # autogenerate emits `sa.PrimaryKeyConstraint('a', 'b')`
        for pm in ALEMBIC_PK_CONSTRAINT_RE.finditer(scope):
            close = _matching_close_paren(scope, pm.end() - 1)
            pk_names = [
                lit
                for arg in _split_top_level_quote_blind(scope[pm.end() : close], True)
                if not _KWARG_RE.match(arg)  # `name='pk_x'` is not a column
                for lit in _string_literals(arg)
            ]
            break
    return columns, _alembic_pk(pk_names), indexes


def _apply_alembic_file(
    text: str, rel: str, tables: dict[str, TableRecord], warnings: list[str]
) -> None:
    text = _upgrade_only(text)
    for m in ALEMBIC_TABLE_RE.finditer(text):
        name = m.group(1)
        open_idx = text.find("(", m.start())
        if open_idx == -1:
            continue
        close_idx = _matching_close_paren(text, open_idx)
        scope = text[open_idx : close_idx + 1]
        columns, pk, indexes = _alembic_columns(scope)
        if name in tables:
            _warn_duplicate("alembic table", name, rel, warnings)
            continue
        tables[name] = TableRecord(
            name=name,
            columns=columns,
            pk=pk,
            ddl=_reconstruct_ddl(name, columns, pk),
            source=rel,
            created_in=rel,
            indexes=indexes,
        )


def _alembic_call_args(
    text: str, m: re.Match[str], positional: tuple[str, ...]
) -> dict[str, str]:
    """Arguments of the `op.*(...)` call starting at `m`, by parameter
    name (positional ones named by `positional`, the rest by keyword)."""
    open_idx = m.end() - 1
    close_idx = _matching_close_paren(text, open_idx)
    out: dict[str, str] = {}
    args = _split_top_level_quote_blind(text[open_idx + 1 : close_idx], brackets=True)
    for i, arg in enumerate(args):
        kw = _KWARG_RE.match(arg)
        if kw:
            out[kw.group(1)] = kw.group(2).strip()
        elif i < len(positional):
            out[positional[i]] = arg
    return out


def _alembic_batches(text: str) -> list[tuple[int, str, str]]:
    """`(start, alias, table)` for each `with op.batch_alter_table(..) as
    alias` — `table` is `""` when it is not a string literal."""
    found = []
    for b in ALEMBIC_BATCH_RE.finditer(text):
        close = _matching_close_paren(text, b.end() - 1)
        alias = re.match(r"\s*as\s+(\w+)", text[close + 1 :])
        if alias:
            args = _alembic_call_args(text, b, ("table_name",))
            table = (_string_literals(args.get("table_name", "")) or [""])[0]
            found.append((b.start(), alias.group(1), table))
    return found


def _apply_alembic_ops(
    text: str, rel: str, tables: dict[str, TableRecord], warnings: list[str]
) -> None:
    """Index/constraint/key ops on `op` or on a `with op.batch_alter_table
    ("t") as alias` alias (whose table is `t`), in `upgrade()` only. Run
    after every file's `create_table`: revision ids do not sort in
    migration order, so a file can name a table another one creates. For
    the same reason a dropped index cannot be replayed, only flagged. An
    op this reader does not replay, or one on an alias with no batch
    context, is a coverage site."""
    text = _upgrade_only(text)
    batches = _alembic_batches(text)

    def site(record: TableRecord | None, line: int) -> None:
        if record is not None:
            record.schema_partial.append(_site(rel, line))
        elif isinstance(warnings, _Warnings):
            warnings.sites.append((rel, _site(rel, line)))

    for m in ALEMBIC_EXECUTE_RE.finditer(text):
        line = _line_of(text, m.start())
        _warn(warnings, rel, f"raw SQL execute() at {rel}:{line} is not read", line)
    created: set[tuple[str, str]] = set()  # made earlier in THIS file
    for m in ALEMBIC_OP_RE.finditer(text):
        recv, fn = m.group("recv"), m.group("fn")
        line = _line_of(text, m.start())
        op_params, batch_params = _ALEMBIC_PARAMS[fn]
        if recv == "op":
            a = _alembic_call_args(text, m, op_params)
            table = (_string_literals(a.get("table_name", "")) or [""])[0]
        else:
            ctx = next(
                (b for b in reversed(batches) if b[0] <= m.start() and b[1] == recv),
                None,
            )
            if ctx is None or not ctx[2]:
                _warn(
                    warnings,
                    rel,
                    f"{recv}.{fn} in {rel}:{line} — no batch_alter_table with a "
                    "string-literal table names its table",
                    line,
                )
                continue
            a = _alembic_call_args(text, m, batch_params)
            table = ctx[2]
        record = tables.get(table)
        if fn in _ALEMBIC_UNTRACKED:
            site(record, line)
            continue
        names = _string_literals(a.get("index_name") or a.get("name", ""))
        name = names[0] if names else ""
        if fn == "drop_index" and not table:  # older form: the index name alone
            for other in tables.values():
                if any(ix[0] == name for ix in other.indexes):
                    site(other, line)
            continue
        if record is None:
            _warn(warnings, rel, f"{fn} on unknown table {table!r} in {rel}", line)
            continue
        cols = _string_literals(a.get("columns", ""))
        if fn == "create_index":
            _add_index(
                record,
                name,
                ", ".join(cols),
                a.get("unique", "").replace(" ", "") == "True",
            )
            created.add((table, name))
        elif fn == "create_unique_constraint":
            _add_index(record, name, ", ".join(cols), True)
            created.add((table, name))
        elif fn == "create_primary_key":
            created.add((table, ""))
            pk = _alembic_pk(cols)
            if not record.pk:
                record.pk = pk
            elif _pk_columns(record.pk) != _pk_columns(pk):
                site(record, line)
        elif fn == "drop_constraint":
            # Files do not sort in migration order, so only a constraint
            # created earlier in this same file can be removed for certain.
            kind = (_string_literals(a.get("type_", "")) or [""])[0]
            if kind in ("foreignkey", "check"):
                continue  # moves no shown fact
            if kind == "primary":
                if (table, "") in created:
                    record.pk = ""
                else:
                    site(record, line)
            elif (table, name) in created:
                record.indexes = [ix for ix in record.indexes if ix[0] != name]
            else:
                site(record, line)
        elif any(ix[0] == name for ix in record.indexes):  # drop_index
            site(record, line)


def _read_alembic(
    root: Path, opts: CodeIngestOptions
) -> tuple[dict[str, TableRecord], list[str]]:
    tables: dict[str, TableRecord] = {}
    warnings = _Warnings()
    paths = sorted(
        _glob_via_walk(root, opts.kb_dir, ALEMBIC_GLOB), key=lambda p: relposix(root, p)
    )
    loaded: list[tuple[str, str]] = []
    for path in paths:
        rel = relposix(root, path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            _warn(warnings, rel, f"could not parse {rel}: {exc}")
            continue
        try:
            _apply_alembic_file(text, rel, tables, warnings)
            loaded.append((rel, text))
        except Exception as exc:  # noqa: BLE001 -- defense in depth, mirrors _read_sql
            _warn(warnings, rel, f"could not parse {rel}: {exc}")
    for rel, text in loaded:
        try:
            _apply_alembic_ops(text, rel, tables, warnings)
        except Exception as exc:  # noqa: BLE001 -- defense in depth, mirrors _read_sql
            _warn(warnings, rel, f"could not parse {rel}: {exc}")
    return tables, warnings


# ---------------------------------------------------------------------------
# reader: ef — migrationBuilder.CreateTable(name: "...") in Migrations/*.cs
# ---------------------------------------------------------------------------

EF_GLOB = "**/Migrations/*.cs"
EF_TABLE_RE = re.compile(r'migrationBuilder\.CreateTable\(\s*name:\s*"(\w+)"')


EF_PRIMARY_KEY_RE = re.compile(r"\.PrimaryKey\(")
EF_CREATE_INDEX_RE = re.compile(r"migrationBuilder\.CreateIndex\(")
EF_ENTITY_RE = re.compile(r"\.Entity(?:<(?P<generic>[\w.]+)>)?\(")
EF_HAS_KEY_RE = re.compile(r"\.HasKey\(")
EF_HAS_INDEX_RE = re.compile(r"\.HasIndex\(")
_EF_TO_TABLE_RE = re.compile(r'\.ToTable\(\s*"(?P<table>[^"]+)"')
_EF_LAMBDA_RE = re.compile(r"=>\s*(?P<body>.*)$", re.S)
_EF_MEMBER_RE = re.compile(r"\b\w+\.(\w+)")
_EF_CHAIN_RE = re.compile(r"[^;]*")
_EF_NAMED_ARG_RE = re.compile(
    r'(\w+):\s*("[^"]*"|new\s*(?:string)?\s*\[\]\s*\{[^}]*\}|\w+)'
)


def _ef_property_names(args: str) -> list[str]:
    """Property names of a `HasKey`/`HasIndex`/`PrimaryKey` argument list:
    string literals (`"A", "B"`) or a lambda (`x => x.A`, `x => new { x.A, x.B }`)."""
    lam = _EF_LAMBDA_RE.search(args)
    if lam:
        return _EF_MEMBER_RE.findall(lam.group("body"))
    return _string_literals(args)


def _call_span(text: str, m: re.Match[str]) -> tuple[str, int]:
    """Text between the parens of the call that `m` opens, and the index
    just past its closing paren."""
    close_idx = _matching_close_paren(text, m.end() - 1)
    return text[m.end() : close_idx], close_idx + 1


def _apply_ef_file(
    text: str, rel: str, tables: dict[str, TableRecord], warnings: list[str]
) -> None:
    for m in EF_TABLE_RE.finditer(text):
        name = m.group(1)
        if name in tables:
            _warn_duplicate("EF table", name, rel, warnings)
            continue
        record = TableRecord(
            name=name,
            columns=[],
            pk="",
            ddl=_reconstruct_ddl(name, [], ""),
            source=rel,
            created_in=rel,
            columns_known=False,
        )
        # `table.PrimaryKey("PK_x", x => x.Id)` sits inside this CreateTable call.
        open_idx = text.find("(", m.start())
        span = text[open_idx + 1 : _matching_close_paren(text, open_idx)]
        for pk_m in EF_PRIMARY_KEY_RE.finditer(span):
            args = _call_span(span, pk_m)[0]
            record.pk = _alembic_pk(_ef_property_names(args.split(",", 1)[-1]))
            break
        tables[name] = record


def _ef_attach(
    tables: dict[str, TableRecord],
    table: str,
    rel: str,
    line: int,
    warnings: list[str],
) -> TableRecord | None:
    record = tables.get(table)
    if record is None:
        _warn(
            warnings,
            rel,
            f"EF key/index on unknown table {table!r} in {rel}:{line}",
            line,
        )
    return record


def _apply_ef_model(
    text: str, rel: str, tables: dict[str, TableRecord], warnings: list[str]
) -> None:
    """Keys and indexes: `migrationBuilder.CreateIndex(...)` and the
    fluent `Entity(...)` / `HasKey` / `HasIndex(...).IsUnique()` calls of a
    model snapshot, attached to the table by `ToTable("t")` (or, with none,
    an entity name that is itself a known table)."""
    for m in EF_CREATE_INDEX_RE.finditer(text):
        span, _end = _call_span(text, m)
        named = dict(_EF_NAMED_ARG_RE.findall(span))
        table = (_string_literals(named.get("table", "")) or [""])[0]
        record = _ef_attach(tables, table, rel, _line_of(text, m.start()), warnings)
        if record is not None:
            cols = _string_literals(named.get("column") or named.get("columns", ""))
            names = _string_literals(named.get("name", ""))
            _add_index(
                record,
                names[0] if names else "",
                ", ".join(cols),
                named.get("unique") == "true",
            )
    entities = list(EF_ENTITY_RE.finditer(text))
    for i, em in enumerate(entities):
        segment = text[
            em.start() : entities[i + 1].start() if i + 1 < len(entities) else len(text)
        ]
        to_table = _EF_TO_TABLE_RE.search(segment)
        if to_table:
            table = to_table.group("table")
        else:
            _args, _ = _call_span(text, em)
            entity = em.group("generic") or (_string_literals(_args) or [""])[0]
            wanted = entity.rsplit(".", 1)[-1].casefold()
            table = next((n for n in tables if n.casefold() == wanted), entity)
        line = _line_of(text, em.start())
        for km in EF_HAS_KEY_RE.finditer(segment):
            record = _ef_attach(tables, table, rel, line, warnings)
            if record is not None and not record.pk:
                record.pk = _alembic_pk(_ef_property_names(_call_span(segment, km)[0]))
        for im in EF_HAS_INDEX_RE.finditer(segment):
            record = _ef_attach(tables, table, rel, line, warnings)
            if record is None:
                continue
            args, end = _call_span(segment, im)
            chain = _EF_CHAIN_RE.match(segment, end)
            chain_text = chain.group(0) if chain else ""
            db_name = re.search(r'\.HasDatabaseName\(\s*"([^"]+)"', chain_text)
            _add_index(
                record,
                db_name.group(1) if db_name else "",
                ", ".join(_ef_property_names(args)),
                ".IsUnique(" in chain_text,
            )


def _read_ef(
    root: Path, opts: CodeIngestOptions
) -> tuple[dict[str, TableRecord], list[str]]:
    """No column regex is defined for EF — only the table
    name is recognised, so every EF-sourced `TableRecord` has an empty
    column list and `columns_known=False`, which the renderer states in
    the document."""
    tables: dict[str, TableRecord] = {}
    warnings = _Warnings()
    paths = sorted(
        _glob_via_walk(root, opts.kb_dir, EF_GLOB), key=lambda p: relposix(root, p)
    )
    loaded: list[tuple[str, str]] = []
    for path in paths:
        rel = relposix(root, path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            _warn(warnings, rel, f"could not parse {rel}: {exc}")
            continue
        try:
            _apply_ef_file(text, rel, tables, warnings)
            loaded.append((rel, text))
        except Exception as exc:  # noqa: BLE001 -- defense in depth, mirrors _read_sql
            _warn(warnings, rel, f"could not parse {rel}: {exc}")
    # Keys and indexes after every file's tables: a snapshot can sort
    # before the migration that creates the table it describes.
    for rel, text in loaded:
        try:
            _apply_ef_model(text, rel, tables, warnings)
        except Exception as exc:  # noqa: BLE001 -- defense in depth, mirrors _read_sql
            _warn(warnings, rel, f"could not parse {rel}: {exc}")
    return tables, warnings


# ---------------------------------------------------------------------------
# reader: sqlite — only for paths in opts.db_paths, opened read-only
# ---------------------------------------------------------------------------


def _path_label(root: Path, path: Path) -> str:
    """A label for a `--db` path, never the absolute host path. The
    common case — `path` sits under `root` — renders the familiar
    repo-relative form via `relposix`. An out-of-root `--db` must not
    fall back to `path.as_posix()`, the fully-qualified path
    `CodeIngestOptions.__post_init__` already resolved — which includes
    the OS user name on a typical developer machine and, worse, would make
    this module's output depend on *whose* machine ingested the repo (the
    same repo ingested by two developers must produce the same bytes).
    `--db:<basename>` is
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
    path-controlled query string ahead of our own `?mode=ro` (the
    read-only guarantee must not be something a crafted path can turn
    off)."""
    return f"{path.resolve().as_uri()}?mode={mode}"


def _read_sqlite_columns(
    con: sqlite3.Connection, table_name: str
) -> tuple[list[tuple[str, str]], str]:
    """`PRAGMA table_info(<table>)` rows are `(cid, name, type, notnull,
    dflt_value, pk)`; `cid` is already declaration order, but the explicit
    sort documents that guarantee rather than relying on it silently. A
    single PK column records its bare name; a composite PK (more than one
    row with `pk > 0`) is ordered by its own `pk` index — the column's
    *position within the key*, not its `cid` — and rendered as a
    `PRIMARY KEY (...)` clause, matching the `sql` reader's shape."""
    quoted = table_name.replace('"', '""')
    rows = sorted(
        con.execute(f'PRAGMA table_info("{quoted}")').fetchall(), key=lambda r: r[0]
    )
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


def _read_sqlite_indexes(
    con: sqlite3.Connection, table_name: str
) -> list[tuple[str, str, bool]]:
    """`PRAGMA index_list` rows are `(seq, name, unique, origin, partial)`
    (`origin` only on SQLite 3.8.9+); the primary key's own index is
    skipped — it is the primary key row. `index_info` rows are `(seqno, cid,
    name)`; an expression column has no name."""
    quoted = table_name.replace('"', '""')
    found: list[tuple[str, str, bool]] = []
    for row in con.execute(f'PRAGMA index_list("{quoted}")').fetchall():
        if len(row) > 3 and row[3] == "pk":
            continue
        index_quoted = row[1].replace('"', '""')
        info = sorted(con.execute(f'PRAGMA index_info("{index_quoted}")').fetchall())
        cols = ", ".join(
            col[2] if col[2] is not None else "<expression>" for col in info
        )
        found.append((row[1], cols, bool(row[2])))
    return sorted(found)


def _read_sqlite(
    root: Path, opts: CodeIngestOptions
) -> tuple[dict[str, TableRecord], list[str]]:
    """The only code path in this module that opens a `.db` file — and
    only for a path already in `opts.db_paths` (never a file
    merely discovered on disk). Opened read-only via `_sqlite_uri`'s
    `mode=ro` URI, so even a live application database handed to `--db`
    cannot be mutated. A missing path warns; it never raises."""
    tables: dict[str, TableRecord] = {}
    warnings = _Warnings()
    for db_path in opts.db_paths:
        label = _path_label(root, db_path)
        if not db_path.is_file():
            _warn(warnings, label, f"--db path not found: {label}")
            continue
        try:
            con = sqlite3.connect(_sqlite_uri(db_path, "ro"), uri=True)
        except (sqlite3.Error, OSError, ValueError) as exc:
            _warn(warnings, label, f"could not open {label}: {exc}")
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
                    _warn(
                        warnings,
                        label,
                        f"skipping table with whitespace in its name in {label}: {name!r}",
                    )
                    continue
                columns, pk = _read_sqlite_columns(con, name)
                if name in tables:
                    _warn(
                        warnings,
                        label,
                        f"duplicate table {name!r} across --db paths; keeping first ({label})",
                    )
                    continue
                ddl = (sql_text or "").strip() or _reconstruct_ddl(name, columns, pk)
                tables[name] = TableRecord(
                    name=name,
                    columns=columns,
                    pk=pk,
                    ddl=ddl,
                    source=label,
                    created_in=label,
                    indexes=_read_sqlite_indexes(con, name),
                )
        except Exception as exc:  # noqa: BLE001 -- defense in depth, see comment below
            # a failure partway through this db's tables must not also
            # discard tables already collected from an earlier db_path.
            _warn(warnings, label, f"could not read {label}: {exc}")
        finally:
            con.close()
    return tables, warnings


# ---------------------------------------------------------------------------
# merge + section rendering
# ---------------------------------------------------------------------------

_READER_ORDER = ("sql", "prisma", "alembic", "ef", "sqlite")


_PRISMA_MAP_VALUE_RE = re.compile(r'@map\(\s*(?:name:\s*)?"([^"]+)"')


def _prisma_db_columns(record: TableRecord, pk: str) -> list[str]:
    """Casefolded database column names of a Prisma key: each field name
    resolved through its `@map("col")`."""
    by_field: dict[str, str] = {}
    for name, rest in record.columns:
        mapped = _PRISMA_MAP_VALUE_RE.search(rest)
        by_field[name.casefold()] = mapped.group(1) if mapped else name
    return [by_field.get(c.casefold(), c).casefold() for c in _pk_list(pk)]


def _prune_unnamed(record: TableRecord) -> list[tuple[str, str, bool]]:
    """Drop an unnamed index that a named one repeats: same database
    columns (a Prisma field resolved through its `@map`) and uniqueness."""
    fields = {
        name.casefold(): (
            mapped.group(1) if (mapped := _PRISMA_MAP_VALUE_RE.search(rest)) else name
        )
        for name, rest in record.columns
    }

    def resolved(cols: str) -> tuple[str, ...]:
        names = [c.strip() for c in cols.split(",")]
        return tuple(fields.get(c.casefold(), c).casefold() for c in names)

    named = {
        (resolved(cols), unique)
        for n, cols, unique in record.indexes
        if n != UNNAMED_INDEX
    }
    return [
        ix
        for ix in record.indexes
        if ix[0] != UNNAMED_INDEX or (resolved(ix[1]), ix[2]) not in named
    ]


def _absorb_sql(prisma: TableRecord, sql: TableRecord) -> TableRecord:
    """The Prisma record plus what its migration SQL adds: partition,
    partitions, indexes (a union keyed by name; `_merge_tables` then drops an
    unnamed one that a named index repeats) and a primary key when Prisma
    declares none. Columns stay the
    Prisma record's. Where both state a primary key or partition and they
    differ, the Prisma value is kept and both are shown with their source."""
    disagreements = dict(prisma.disagreements)
    pk = prisma.pk or sql.pk
    if (
        prisma.pk
        and sql.pk
        and _prisma_db_columns(prisma, prisma.pk)
        != [c.casefold() for c in _pk_list(sql.pk)]
    ):
        disagreements["Primary key"] = (
            f"{', '.join(_pk_list(prisma.pk))} [prisma] / "
            f"{', '.join(_pk_list(sql.pk))} [sql]"
        )
    partition = prisma.partition or sql.partition
    if (
        prisma.partition
        and sql.partition
        and (
            _clean_type(prisma.partition).casefold()
            != _clean_type(sql.partition).casefold()
        )
    ):
        disagreements["Partition"] = (
            f"{prisma.partition} [prisma] / {sql.partition} [sql]"
        )
    named = {ix[0] for ix in prisma.indexes}
    indexes = list(prisma.indexes)
    for ix in sql.indexes:
        if (ix[0] == UNNAMED_INDEX or ix[0] not in named) and ix not in indexes:
            indexes.append(ix)
    return replace(
        prisma,
        pk=pk,
        partition=partition,
        indexes=indexes,
        partitions=[*prisma.partitions, *sql.partitions],
        schema_partial=[*prisma.schema_partial, *sql.schema_partial],
        source=", ".join(
            dict.fromkeys([*prisma.source.split(", "), *sql.source.split(", ")])
        ),
        disagreements=disagreements,
    )


def _merge_sql_into_prisma(
    per_reader: dict[str, dict[str, TableRecord]],
) -> dict[str, dict[str, TableRecord]]:
    """A SQL record named like a Prisma record's `table_name` is that
    model's migration: fold it in and drop it, so it is not also reported
    as a second claim on the table."""
    sql = dict(per_reader.get("sql", {}))
    prisma: dict[str, TableRecord] = {}
    for name, record in per_reader.get("prisma", {}).items():
        twin = sql.pop(record.table_name, None)
        prisma[name] = _absorb_sql(record, twin) if twin is not None else record
    return {**per_reader, "sql": sql, "prisma": prisma}


def _merge_tables(
    per_reader: dict[str, dict[str, TableRecord]], warnings: list[str]
) -> dict[str, TableRecord]:
    """A SQL migration for a Prisma model folds into that model's record
    (`_merge_sql_into_prisma`). Otherwise the first reader in
    `_READER_ORDER` to claim a table name wins that table's whole
    `TableRecord` — never a per-column merge — and every later claim of
    the same name is a warning naming both readers."""
    per_reader = _merge_sql_into_prisma(per_reader)
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
            merged[name] = replace(record, indexes=_prune_unnamed(record))
            claimed_by[name] = reader_name
    return merged


_PK_LIST_RE = re.compile(r"PRIMARY\s+KEY\s*\(([^)]*)\)", re.I)


def _pk_list(pk: str) -> list[str]:
    """Column names of `pk` in key order, unquoted — a bare column name or
    a `PRIMARY KEY (a, b)` table-constraint clause."""
    if not pk:
        return []
    m = _PK_LIST_RE.search(pk)
    if m:
        return [c.strip().strip('"`[]') for c in m.group(1).split(",") if c.strip()]
    return [pk]


def _pk_columns(pk: str) -> set[str]:
    """Casefolded column names actually covered by `pk`, for marking the
    L2 table's `PK` cell per row. Casefolded because SQL identifiers are
    case-insensitive: `PRIMARY KEY (ID)` must still mark a column declared
    `id`."""
    return {c.casefold() for c in _pk_list(pk)}


def _structure_lines(record: TableRecord) -> list[str]:
    """Table name, primary key, partition and indexes, one row each; a row
    two sources disagree on shows both as `<value> [<source>]`."""
    pk = record.disagreements.get("Primary key") or ", ".join(_pk_list(record.pk))
    partition = record.disagreements.get("Partition") or record.partition
    lines = [
        f"Table: {record.table_name}",
        f"Primary key: {pk or 'none'}",
        f"Partition: {partition or 'none'}",
    ]
    if record.partitions:
        lines.append(f"Partitions: {', '.join(record.partitions)}")
    if record.indexes:
        lines.append("Indexes:")
        lines.extend(
            f"- {name} ({cols}){' unique' if unique else ''}"
            for name, cols, unique in record.indexes
        )
    else:
        lines.append("Indexes: none")
    return lines


def _render_section(record: TableRecord) -> CodeSection:
    pk_cols = _pk_columns(record.pk)
    if record.columns_known:
        l2_lines = ["| Column | Type | PK |", "| --- | --- | --- |"]
        for cname, ctype in record.columns:
            mark = "yes" if cname.casefold() in pk_cols else ""
            l2_lines.append(f"| {escape_cell(cname)} | {escape_cell(ctype)} | {mark} |")
        column_count = len(record.columns)
        columns_phrase = f"{column_count} column" + ("" if column_count == 1 else "s")
    else:
        # An EF migration names the table but this reader extracts no
        # columns from it — say so in the document, never an empty table
        # a reader would take for "no columns".
        l2_lines = [
            "_Columns not extracted: EF Core migrations are recognised by table name only._"
        ]
        columns_phrase = "columns not extracted (EF migration)"
    l2_lines.append("")
    l2_lines.extend(_structure_lines(record))
    l2_lines.append("")
    l2_lines.append(f"_Source: {record.source}_")
    l2_md = "\n".join(l2_lines) + "\n"

    source_files = "\n".join(record.source.split(", ")) if record.source else ""
    l3_md = f"```sql\n{record.ddl}\n```\n\n```\n{source_files}\n```\n"

    # `record.pk` is either empty, a bare column name, or a verbatim
    # `PRIMARY KEY (a, b)` clause (sql/alembic/sqlite readers all store
    # composite keys this way). Rendering the clause after a bare `PK `
    # prefix stuttered — `PK PRIMARY KEY (team_id, user_id)` — so the
    # summary shows just the column list for a composite key, matching
    # the single-column `PK id` shape. A clause that
    # matches but names no columns (`PRIMARY KEY ()`/`PRIMARY KEY (   )`)
    # must degrade to "none detected" too, not a value-less `PK ` — the
    # `or` runs *after* picking the matched group, not before.
    # `" ".join(...split())` then collapses a composite clause wrapped
    # across source lines back to the one-line field this summary is
    # persisted as.
    pk_match = _PK_LIST_RE.search(record.pk)
    pk_phrase = " ".join(
        (
            (pk_match.group(1).strip() if pk_match else record.pk) or "none detected"
        ).split()
    )
    summary = (
        f"Table {record.name}: {columns_phrase}, "
        f"PK {pk_phrase} (source: {record.source})."
    )

    return CodeSection(
        id=f"db.{record.name}",
        title=record.name,
        summary=summary,
        group="db",
        l2_md=l2_md,
        l3_md=l3_md,
    )


def _coverage_rows(
    per_reader: dict[str, dict[str, TableRecord]],
    per_sites: dict[str, list[tuple[str, str]]],
    scopes: list[Scope],
) -> list[CoverageRow]:
    """One row per (scope, reader) that produced any table or skipped any
    file/statement. A table's scope is the one holding its first source
    file (`.` when no manifest scope does); `partial` names the skipped
    sites — those recorded on tables, and each reader-level site (a file
    that did not parse, a statement no table could be named for)."""

    def scope_path(rel: str) -> str:
        scope = scope_of(scopes, rel)
        return scope.path if scope else "."

    sites: dict[tuple[str, str], list[str]] = {}
    for reader in _READER_ORDER:
        for record in per_reader.get(reader, {}).values():
            first = record.created_in or record.source.split(", ")[0]
            sites.setdefault((scope_path(first), reader), []).extend(
                record.schema_partial
            )
        for rel, site in per_sites.get(reader, []):
            sites.setdefault((scope_path(rel), reader), []).append(site)
    return [
        CoverageRow(
            "schema",
            path,
            reader,
            "partial" if skipped else "complete",
            "; ".join(sorted(set(skipped))),
        )
        for (path, reader), skipped in sorted(sites.items())
    ]


class SchemaExtractor:
    name = "schema"

    def detect(self, root: Path) -> bool:
        # Structural exception (matches deps.py / commands.py):
        # Extractor.detect(self, root) is never given opts, so
        # this walk can't be pruned by a non-default --kb-dir; extract()'s
        # walks all thread opts.kb_dir through via _glob_via_walk.
        for pattern in (*MIGRATION_GLOBS, PRISMA_GLOB, ALEMBIC_GLOB, EF_GLOB):
            if _glob_via_walk(root, None, pattern):
                return True
        return False

    def extract(self, root: Path, opts: CodeIngestOptions) -> ExtractResult:
        warnings: list[str] = []
        per_reader: dict[str, dict[str, TableRecord]] = {}
        per_sites: dict[str, list[tuple[str, str]]] = {}

        def _run(key: str, reader, *args: object) -> None:
            try:
                tables, warns = reader(*args)
            except Exception as exc:  # noqa: BLE001 -- defense in depth, mirrors deps.py/commands.py
                tables, warns = {}, [f"could not read {key} schema sources: {exc}"]
            per_reader[key] = tables
            per_sites[key] = list(getattr(warns, "sites", []))
            warnings.extend(warns)

        _run("sql", _read_sql, root, opts)
        _run("prisma", _read_prisma, root, opts)
        _run("alembic", _read_alembic, root, opts)
        _run("ef", _read_ef, root, opts)
        _run("sqlite", _read_sqlite, root, opts)

        merged = _merge_tables(per_reader, warnings)
        sections = [_render_section(merged[name]) for name in sorted(merged)]
        try:
            scopes = find_scopes(root, opts.kb_dir)
        except Exception as exc:  # noqa: BLE001 -- coverage must not cost the sections
            warnings.append(f"could not find package scopes for schema coverage: {exc}")
            scopes = []
        return ExtractResult(
            sections=sections,
            warnings=warnings,
            coverage=_coverage_rows(per_reader, per_sites, scopes),
        )
