"""In-scope facts per `-code` / `-svc` section (spec §5.2).

A section counts as changed only when its fact set differs, so anything not
parsed here (Image, Source, Volumes, Healthcheck, versions, banner,
formatting) can never raise a finding.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from typing import Literal

from strata_kb import lintcore, ticketcheck
from strata_kb.codeingest.hublag import BANNER_PREFIX

Fact = tuple[str, str]

# The extractors' "empty list" words (services.py: `or 'none'` / `'nothing'`).
_EMPTY = frozenset({"", "none", "nothing", "—"})
_FRAMEWORKS_RE = re.compile(r"\*\*Frameworks detected:\*\*[ \t]*(.*)")


def _items(cell: str | None) -> list[str]:
    parts = (p.strip().strip("`").strip() for p in (cell or "").split(","))
    return [p for p in parts if p.lower() not in _EMPTY]


def _svc_code(l2: str, _l3: str) -> frozenset[Fact]:
    props = (
        ("depends_on", "Depends on"),
        ("port", "Ports"),
        ("env_key", "Env keys"),
        ("technology", "Technology"),
    )
    return frozenset(
        (kind, item)
        for kind, name in props
        for item in _items(ticketcheck._property(l2, name))
    )


def _table(l2: str, *columns: str) -> list[list[str]]:
    """Data rows of the L2's table (each -code section has one), one cell
    per named column in the order given; empty when a column is missing."""
    rows = lintcore.table_rows(l2)
    idx = [lintcore.table_column(rows, c) for c in columns]
    cols = [i for i in idx if i is not None]
    if len(cols) < len(columns):
        return []
    return [[row[i] if i < len(row) else "" for i in cols] for row in rows[1:]]


def _db(l2: str, _l3: str) -> frozenset[Fact]:
    facts: set[Fact] = set()
    for name, ctype, pk in _table(l2, "Column", "Type", "PK"):
        facts |= {("column", name), ("column_type", f"{name}:{ctype}")}
        if pk.lower() == "yes":
            facts.add(("pk", name))
    return frozenset(facts)


def _api(l2: str, _l3: str) -> frozenset[Fact]:
    return frozenset(
        ("route", f"{method} {path}") for method, path in _table(l2, "Method", "Path")
    )


def _int(l2: str, _l3: str) -> frozenset[Fact]:
    return frozenset(("env_key", key) for (key,) in _table(l2, "Env key") if key)


def _cmd(l2: str, _l3: str) -> frozenset[Fact]:
    m = ticketcheck.PRIMARY_RE.search(l2)
    return frozenset({("command", m.group(1))}) if m else frozenset()


def _dep(l2: str, _l3: str) -> frozenset[Fact]:
    m = _FRAMEWORKS_RE.search(l2)
    return frozenset(("framework", f) for f in _items(m.group(1) if m else None))


def _text(_l2: str, l3: str) -> frozenset[Fact]:
    kept = (ln for ln in l3.splitlines() if not ln.startswith(BANNER_PREFIX))
    text = " ".join(" ".join(kept).split())
    return frozenset({("text", hashlib.sha256(text.encode()).hexdigest())})


_CODE: tuple[tuple[str, Callable[[str, str], frozenset[Fact]]], ...] = (
    ("svc.", _svc_code),
    ("db.", _db),
    ("api.", _api),
    ("int.", _int),
    ("cmd.", _cmd),
    ("dep.", _dep),
)
_SVC_PREFIXES = ("svc.", "flow.")


def facts_for(
    section_id: str, doc_kind: Literal["code", "svc"], l2: str, l3: str
) -> frozenset[Fact]:
    """Facts of one section; empty for ids with nothing in scope."""
    if doc_kind == "svc":
        return _text(l2, l3) if section_id.startswith(_SVC_PREFIXES) else frozenset()
    for prefix, parse in _CODE:
        if section_id.startswith(prefix):
            return parse(l2, l3)
    return frozenset()
