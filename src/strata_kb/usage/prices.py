"""prices — model id to money.

The package ships a default table; a repo overrides it at
`.kb/usage-prices.yaml`. The override merges PER MODEL, so a repo correcting
one model's price keeps the rest of the table instead of inheriting a
half-filled one.

An unknown model is `unpriced`, never $0: a dashboard that quietly values an
unrecognised model at nothing is worse than no dashboard, because the number it
shows looks complete.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from importlib import resources
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

from center_kb.usage.ledger import UsageRow

PRICES_FILE = "usage-prices.yaml"
_MTOK = 1_000_000

# extra="forbid" is new to this module rather than a repo-wide convention
# (nothing else under src/center_kb sets model_config): UsageRow parses
# machine-written JSONL, where an unexpected key would mean a code bug and
# extra fields are harmless. PriceTable and ModelRates parse a file this
# feature expects a human to hand-edit, where a misspelled key (`modelz`,
# `cache_write_1hr`) must raise instead of being silently dropped — a
# dropped typo leaves the default price in place while looking like the
# override applied.


class ModelRates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: float
    output: float
    cache_read: float
    cache_write_5m: float
    cache_write_1h: float


class PriceTable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effective_date: str = ""
    currency: str = "USD"
    unit: str = "per_mtok"
    models: dict[str, ModelRates] = {}
    aliases: dict[str, str] = {}

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
        resources.files("center_kb")
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


_POINT_RELEASE = re.compile(r"-\d+$")


def resolve_model(table: PriceTable, model: str) -> str | None:
    """The table row that prices `model`: exact id, then an alias, then the
    family row after stripping trailing `-<digits>` segments one at a time
    (`claude-fable-5-1` → `claude-fable-5`). None when nothing matches."""
    candidate = model
    while True:
        if candidate in table.models:
            return candidate
        alias = table.aliases.get(candidate)
        if alias in table.models:
            return alias
        stripped = _POINT_RELEASE.sub("", candidate)
        if stripped == candidate:
            return None
        candidate = stripped


def cost_of(row: UsageRow, table: PriceTable) -> float | None:
    """USD for one row, or None when the model has no rates."""
    key = resolve_model(table, row.model)
    if key is None:
        return None
    rates = table.models[key]
    return (
        row.tokens_in * rates.input
        + row.tokens_out * rates.output
        + row.cache_read * rates.cache_read
        + row.cache_write_5m * rates.cache_write_5m
        + row.cache_write_1h * rates.cache_write_1h
    ) / _MTOK


def stale_days(table: PriceTable, today: date) -> int:
    """Age of the table in days. An unparseable date reads as ancient, so a
    typo surfaces as a loud warning rather than as a fresh table.
    """
    try:
        effective = datetime.strptime(table.effective_date, "%Y-%m-%d").date()
    except ValueError:
        return 36_500
    return (today - effective).days
