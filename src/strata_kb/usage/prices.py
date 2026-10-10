"""prices — model id to money.

The package ships a default table; a repo overrides it at
`.kb/usage-prices.yaml`. The override merges PER MODEL, so a repo correcting
one model's price keeps the rest of the table instead of inheriting a
half-filled one.

An unknown model is `unpriced`, never $0: a dashboard that quietly values an
unrecognised model at nothing is worse than no dashboard, because the number it
shows looks complete. "Unknown" means no row for that exact id or alias: a
point release is never priced at its family's rate, which is a wrong number
that looks right.
"""
from __future__ import annotations

from datetime import date, datetime
from importlib import resources
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

from strata_kb.usage.ledger import UsageRow

PRICES_FILE = "usage-prices.yaml"
_MTOK = 1_000_000

# Values of the API `usage` block, verified 2026-10-10 against
# platform.claude.com/docs/en/manage-claude/data-residency (`inference_geo`:
# "us" | "global") and .../build-with-claude/fast-mode (`speed`: "fast" |
# "standard"). "" is a row that did not report the field.
US_ONLY_GEO = frozenset({"us"})
KNOWN_GEO = frozenset({"", "global"}) | US_ONLY_GEO
FAST_SPEED = "fast"
KNOWN_SPEED = frozenset({"", "standard", FAST_SPEED})
# "priority" and "batch" are priced differently from standard; Claude Code
# sends neither today, so they are flagged rather than given a rate.
KNOWN_TIER = frozenset({"", "standard"})
US_ONLY_FACTOR = 1.1  # "1.1x multiplier on all token pricing categories"

# extra="forbid" is new to this module rather than a repo-wide convention
# (nothing else under src/strata_kb sets model_config): UsageRow parses
# machine-written JSONL, where an unexpected key would mean a code bug and
# extra fields are harmless. PriceTable and ModelRates parse a file this
# feature expects a human to hand-edit, where a misspelled key (`modelz`,
# `cache_write_1hr`, `treshold`) must raise instead of being silently
# dropped — a dropped typo leaves the default price in place while looking
# like the override applied. The subclasses below inherit model_config.


class Rates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: float
    output: float
    cache_read: float
    cache_write_5m: float
    cache_write_1h: float


class LongContextRates(Rates):
    """Rates for a call whose prompt exceeds `threshold` tokens. The whole
    call moves tier, not just the tokens past the line ("each request is
    priced on its own", pricing page)."""

    threshold: int


class ModelRates(Rates):
    long_context: LongContextRates | None = None


class PriceTable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effective_date: str = ""
    currency: str = "USD"
    unit: str = "per_mtok"
    models: dict[str, ModelRates] = {}
    aliases: dict[str, str] = {}
    # USD per 1,000 web searches, charged on top of tokens. One table-wide
    # rate: the pricing page lists it per tool, not per model.
    web_search_per_1k: float = 10.0

    @field_validator("effective_date", mode="before")
    @classmethod
    def _stringify_date(cls, value: object) -> object:
        """An unquoted `2026-09-01` is the natural way to hand-type a date
        in a file meant to be hand-edited, but YAML resolves it to a
        `date`/`datetime`, not a `str`. Accept that spelling instead of
        crashing the loader over quoting style.
        """
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        return value

    @field_validator("unit")
    @classmethod
    def _only_per_mtok(cls, value: str) -> str:
        """`cost_of` divides by a hard-coded per-million-token constant; a
        table declaring a different unit would silently misprice every row
        by that scale factor rather than failing loudly.
        """
        if value != "per_mtok":
            raise ValueError(
                f"unit {value!r} is not supported — only 'per_mtok' is implemented"
            )
        return value


def _packaged() -> dict:
    text = (
        resources.files("strata_kb")
        .joinpath("templates/usage")
        .joinpath(PRICES_FILE)
        .read_text(encoding="utf-8")
    )
    return yaml.safe_load(text) or {}


def load_prices(kb_dir: Path) -> PriceTable:
    data = _packaged()
    override_path = kb_dir / PRICES_FILE
    if override_path.exists():
        override = yaml.safe_load(override_path.read_text(encoding="utf-8")) or {}
        models = dict(data.get("models") or {})
        models.update(override.get("models") or {})
        aliases = dict(data.get("aliases") or {})
        aliases.update(override.get("aliases") or {})
        data = {**data, **override, "models": models, "aliases": aliases}
    return PriceTable.model_validate(data)


def resolve_model(table: PriceTable, model: str) -> str | None:
    """The table row that prices `model`: its exact id, else an alias, else
    None. No family fallback: a point release may be priced differently
    from its family (the 5.5 generation is), so an id without a row is
    `unpriced` until someone adds one — invariant I5 extended to ids."""
    if model in table.models:
        return model
    alias = table.aliases.get(model)
    return alias if alias in table.models else None


def cost_of(row: UsageRow, table: PriceTable) -> float | None:
    """USD for one row, or None when the model has no rates."""
    key = resolve_model(table, row.model)
    if key is None:
        return None
    model_rates = table.models[key]
    rates: Rates = model_rates
    # Prompt length is everything the model read, cached or not: a cache hit
    # is still context, so cache reads and writes count toward the threshold.
    prompt = row.tokens_in + row.cache_read + row.cache_write_5m + row.cache_write_1h
    if model_rates.long_context is not None and prompt > model_rates.long_context.threshold:
        rates = model_rates.long_context
    tokens = (
        row.tokens_in * rates.input
        + row.tokens_out * rates.output
        + row.cache_read * rates.cache_read
        + row.cache_write_5m * rates.cache_write_5m
        + row.cache_write_1h * rates.cache_write_1h
    ) / _MTOK
    # The geo multiplier applies on top of whichever tier was picked (the
    # pricing page says so for Haiku 5.5's long-context prices), and to
    # tokens only: a web search is a flat per-search charge.
    if row.inference_geo in US_ONLY_GEO:
        tokens *= US_ONLY_FACTOR
    return tokens + row.web_searches * table.web_search_per_1k / 1000


def is_lower_bound(row: UsageRow) -> bool:
    """Fast mode has no published cache rates, so its cost is reported at
    the standard rate and flagged rather than guessed."""
    return row.speed == FAST_SPEED


def has_unknown_modifier(row: UsageRow) -> bool:
    """A geo, speed or service tier value this table does not price. Such a
    row is priced as global/standard and flagged: the token counts are still
    right, and a new API value must not turn a known model into `unpriced`."""
    return (
        row.inference_geo not in KNOWN_GEO
        or row.speed not in KNOWN_SPEED
        or row.service_tier not in KNOWN_TIER
    )


def stale_days(table: PriceTable, today: date) -> int:
    """Age of the table in days. An unparseable date reads as ancient, so a
    typo surfaces as a loud warning rather than as a fresh table.
    """
    try:
        effective = datetime.strptime(table.effective_date, "%Y-%m-%d").date()
    except ValueError:
        return 36_500
    return (today - effective).days
