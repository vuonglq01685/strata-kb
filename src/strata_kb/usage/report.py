"""report — aggregate ledger rows and render them.

Reads the committed ledger, never a transcript: the ledger is the record, and
a report that re-derived from transcripts would disagree with what git holds.

HTML is static and self-contained on purpose — no server to run, no CDN to
reach, no JavaScript. Tables, not charts: a self-contained chart means shipping
a library, and a table survives a git diff.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from jinja2 import Environment, PackageLoader, select_autoescape
from pydantic import BaseModel

from strata_kb.usage.ledger import UsageRow
from strata_kb.usage.prices import PriceTable, cost_of, resolve_model, stale_days

STALE_AFTER_DAYS = 90


class Bucket(BaseModel):
    key: str = ""
    rows: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read: int = 0
    cache_write: int = 0
    cost: float = 0.0
    unpriced_rows: int = 0
    est_rows: int = 0


class Aggregate(BaseModel):
    total: Bucket = Bucket(key="total")
    by_ticket: list[Bucket] = []
    by_phase: list[Bucket] = []
    by_model: list[Bucket] = []
    by_actor: list[Bucket] = []
    by_assistant: list[Bucket] = []
    main: Bucket = Bucket(key="main")
    sidechain: Bucket = Bucket(key="sidechain")
    unattributed: Bucket = Bucket(key="unattributed")
    unpriced_models: list[str] = []
    priced_as: dict[str, str] = {}
    hook_errors: int = 0
    effective_date: str = ""
    currency: str = "USD"
    stale_days: int = 0
    stale: bool = False
    generated: str = ""


def _add(bucket: Bucket, row: UsageRow, cost: float | None) -> None:
    """Fold one row into a bucket.

    `cost is None` (invariant I5) increments `unpriced_rows` and leaves
    `cost` untouched — it must never be treated as a $0 contribution, or the
    bucket total would silently understate what was actually spent.
    """
    bucket.rows += 1
    bucket.tokens_in += row.tokens_in
    bucket.tokens_out += row.tokens_out
    bucket.cache_read += row.cache_read
    bucket.cache_write += row.cache_write_5m + row.cache_write_1h
    if cost is None:
        bucket.unpriced_rows += 1
    else:
        bucket.cost += cost
    if row.est:
        bucket.est_rows += 1


def _ranked(buckets: dict[str, Bucket]) -> list[Bucket]:
    """Cost descending, so the dashboard leads with where the money went."""
    return sorted(buckets.values(), key=lambda b: (-b.cost, -b.tokens_out, b.key))


def aggregate(
    rows: list[UsageRow],
    table: PriceTable,
    *,
    today: date,
    generated: str,
) -> Aggregate:
    """Fold ledger rows into totals sliced every way the report needs.

    `today` and `generated` are explicit parameters, not `date.today()` calls,
    so the aggregate is deterministic and testable; Task 5's CLI passes the
    real values in.
    """
    agg = Aggregate(
        total=Bucket(key="total"),
        main=Bucket(key="main"),
        sidechain=Bucket(key="sidechain"),
        unattributed=Bucket(key="unattributed"),
        effective_date=table.effective_date,
        currency=table.currency,
        generated=generated,
    )
    agg.stale_days = stale_days(table, today)
    agg.stale = agg.stale_days > STALE_AFTER_DAYS
    tickets: dict[str, Bucket] = defaultdict(Bucket)
    phases: dict[str, Bucket] = defaultdict(Bucket)
    models: dict[str, Bucket] = defaultdict(Bucket)
    actors: dict[str, Bucket] = defaultdict(Bucket)
    assistants: dict[str, Bucket] = defaultdict(Bucket)
    unpriced: set[str] = set()
    priced_as: dict[str, str] = {}
    for row in rows:
        cost = cost_of(row, table)
        key = resolve_model(table, row.model)
        if key is None:
            unpriced.add(row.model)
        elif key != row.model:
            priced_as[row.model] = key
        _add(agg.total, row, cost)
        _add(agg.sidechain if row.sidechain else agg.main, row, cost)
        if row.ticket is None:
            _add(agg.unattributed, row, cost)
        else:
            tickets[row.ticket].key = row.ticket
            _add(tickets[row.ticket], row, cost)
        for store, key_ in ((phases, row.phase), (models, row.model),
                             (actors, row.actor), (assistants, row.assistant)):
            store[key_].key = key_
            _add(store[key_], row, cost)
    agg.by_ticket = _ranked(tickets)
    agg.by_phase = _ranked(phases)
    agg.by_model = _ranked(models)
    agg.by_actor = _ranked(actors)
    agg.by_assistant = _ranked(assistants)
    agg.unpriced_models = sorted(unpriced)
    agg.priced_as = dict(sorted(priced_as.items()))
    return agg


def _money(bucket: Bucket, currency: str) -> str:
    """One bucket's cost, spelled identically in Markdown and HTML.

    A dash — never a figure — for a bucket with no rows, or one whose rows
    are ALL unpriced (invariant I5): `0.00` in a cost column is exactly the
    "number that looks complete" this feature exists to prevent. A bucket
    that is only partly unpriced still shows its real (partial) cost, plus
    how many rows that cost does not cover.
    """
    if not bucket.rows or bucket.unpriced_rows == bucket.rows:
        money = "-"
    else:
        money = f"{bucket.cost:.2f} {currency}"
    if bucket.unpriced_rows:
        money += f" (+{bucket.unpriced_rows} unpriced)"
    return money


# Mirrors src/strata_kb/web/templating.py:7-11 — a package-local template
# loader with autoescaping on. `model` is copied verbatim out of a transcript
# and is not validated the way a ticket stem is, so it is the field that can
# actually carry markup; autoescaping is what keeps it inert in the page.
_env = Environment(
    loader=PackageLoader("strata_kb", "templates/usage"),
    autoescape=select_autoescape(enabled_extensions=("j2", "html"), default=True),
)
_env.globals["money"] = _money


def render_html(agg: Aggregate) -> str:
    """A static, self-contained page: no script, no CDN, no network request."""
    return _env.get_template("report.html.j2").render(agg=agg)


def _md_row(bucket: Bucket, currency: str) -> str:
    return (
        f"| {bucket.key} | {bucket.rows} | {bucket.tokens_out:,} | "
        f"{bucket.cache_read:,} | {_money(bucket, currency)} |"
    )


def render_markdown(agg: Aggregate) -> str:
    """A PR-body table: what it cost, and where the cost went."""
    lines: list[str] = []
    if agg.stale:
        lines += [f"**Warning: price table is {agg.stale_days} days old — update "
                  ".kb/usage-prices.yaml.**", ""]
    total_key = "total" + (f" ({agg.total.est_rows} estimated)" if agg.total.est_rows else "")
    lines += [
        "| scope | calls | output tokens | cache read | cost |",
        "| --- | --- | --- | --- | --- |",
        _md_row(Bucket(**{**agg.total.model_dump(), "key": total_key}), agg.currency),
    ]
    for bucket in agg.by_ticket:
        lines.append(_md_row(bucket, agg.currency))
    for bucket in agg.by_phase:
        lines.append(_md_row(Bucket(**{**bucket.model_dump(), "key": f"phase: {bucket.key}"}), agg.currency))
    for bucket in agg.by_assistant:
        lines.append(_md_row(Bucket(**{**bucket.model_dump(), "key": f"assistant: {bucket.key}"}), agg.currency))
    lines.append("")
    if agg.priced_as:
        lines.append("Priced as: " + "; ".join(f"{raw} priced as {key}" for raw, key in agg.priced_as.items()) + ".")
    if agg.hook_errors:
        lines.append(f"{agg.hook_errors} hook ingest error(s) logged — see .kb/usage/ingest-errors.log.")
    lines.append(
        f"Prices effective {agg.effective_date} ({agg.stale_days} days old); "
        f"generated {agg.generated}."
    )
    return "\n".join(lines)
