from datetime import date
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from strata_kb.usage import prices
from tests.test_usage_ledger import row


def test_the_packaged_table_prices_the_models_we_actually_run(tmp_path: Path):
    table = prices.load_prices(tmp_path)

    for model in ("claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"):
        assert model in table.models, model
    assert table.effective_date


def test_the_packaged_table_has_five_rates_per_model(tmp_path: Path):
    # A single 'cache write' rate understates a 1h write by ~37%, and a table
    # with no cache_read rate is off by more than half the bill.
    rates = prices.load_prices(tmp_path).models["claude-opus-5"]

    assert (rates.input, rates.output) == (5.0, 25.0)
    assert (rates.cache_read, rates.cache_write_5m, rates.cache_write_1h) == (
        0.5,
        6.25,
        10.0,
    )


def test_the_packaged_sonnet_5_row_is_the_standard_rate_not_the_promo(tmp_path: Path):
    # Claude Sonnet 5 carries an introductory 2.0/10.0 that expires
    # 2026-08-31; the shipped table must carry the standard 3.0/15.0. Pin
    # this explicitly: test_a_repo_override_replaces_only_the_models_it_names
    # below uses 2.0/10.0 as its override value, so those promo numbers
    # already sit in this file looking like a plausible correct value.
    rates = prices.load_prices(tmp_path).models["claude-sonnet-5"]

    assert (rates.input, rates.output) == (3.0, 15.0)


def test_a_repo_override_replaces_only_the_models_it_names(tmp_path: Path):
    (tmp_path / "usage-prices.yaml").write_text(
        yaml.safe_dump(
            {
                "effective_date": "2026-09-01",
                "models": {
                    "claude-sonnet-5": {
                        "input": 2.0,
                        "output": 10.0,
                        "cache_read": 0.2,
                        "cache_write_5m": 2.5,
                        "cache_write_1h": 4.0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    table = prices.load_prices(tmp_path)

    assert table.models["claude-sonnet-5"].input == 2.0
    assert table.models["claude-opus-5"].input == 5.0  # kept from the default
    assert table.effective_date == "2026-09-01"


def test_cost_sums_all_five_components(tmp_path: Path):
    table = prices.load_prices(tmp_path)
    r = row(
        "u1",
        model="claude-opus-5",
        tokens_in=1_000_000,
        tokens_out=1_000_000,
        cache_read=1_000_000,
        cache_write_5m=1_000_000,
        cache_write_1h=1_000_000,
    )

    assert prices.cost_of(r, table) == pytest.approx(5.0 + 25.0 + 0.5 + 6.25 + 10.0)


def test_a_measured_session_prices_to_the_number_we_verified(tmp_path: Path):
    # The real 305-row Opus 5 session from the spec's evidence, as one row.
    table = prices.load_prices(tmp_path)
    r = row(
        "u1",
        model="claude-opus-5",
        tokens_in=610,
        tokens_out=433_409,
        cache_read=76_847_719,
        cache_write_5m=0,
        cache_write_1h=914_048,
    )

    assert prices.cost_of(r, table) == pytest.approx(58.40, abs=0.01)


def test_an_unknown_model_is_unpriced_not_free(tmp_path: Path):
    # Invariant I5. A silent $0 is the failure that makes a dashboard worse
    # than no dashboard.
    table = prices.load_prices(tmp_path)

    assert prices.cost_of(row("u1", model="claude-nonexistent-9"), table) is None


def test_stale_days_counts_from_the_effective_date(tmp_path: Path):
    table = prices.load_prices(tmp_path)
    table.effective_date = "2026-06-24"

    assert prices.stale_days(table, date(2026, 9, 22)) == 90


def test_an_unparseable_effective_date_reads_as_maximally_stale(tmp_path: Path):
    table = prices.load_prices(tmp_path)
    table.effective_date = "not-a-date"

    assert prices.stale_days(table, date(2026, 9, 22)) > 3650


def test_an_override_with_an_unquoted_date_still_parses(tmp_path: Path):
    # An unquoted 2026-09-01 is the natural way to hand-type a date in a
    # file whose whole premise is hand-editing, but YAML resolves it to a
    # datetime.date rather than a str. Written as raw text, not
    # yaml.safe_dump, because safe_dump would quote the string for us and
    # prove nothing about this path.
    (tmp_path / "usage-prices.yaml").write_text(
        "effective_date: 2026-09-01\n"
        "models:\n"
        "  claude-sonnet-5: {input: 2.0, output: 10.0, cache_read: 0.2, "
        "cache_write_5m: 2.5, cache_write_1h: 4.0}\n",
        encoding="utf-8",
    )

    table = prices.load_prices(tmp_path)

    assert table.effective_date == "2026-09-01"


def test_a_misspelled_top_level_override_key_raises(tmp_path: Path):
    # A typo'd section name (`modelz` for `models`) must not be silently
    # ignored — that would leave the default prices in place while looking
    # like the override applied.
    (tmp_path / "usage-prices.yaml").write_text(
        "effective_date: '2026-09-01'\n"
        "modelz:\n"
        "  claude-sonnet-5: {input: 2.0, output: 10.0, cache_read: 0.2, "
        "cache_write_5m: 2.5, cache_write_1h: 4.0}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        prices.load_prices(tmp_path)


def test_a_misspelled_rate_key_raises(tmp_path: Path):
    # A stray key alongside all five correct ones (not a missing key) must
    # raise, not be dropped — a dropped typo looks like a correct override.
    (tmp_path / "usage-prices.yaml").write_text(
        "effective_date: '2026-09-01'\n"
        "models:\n"
        "  claude-sonnet-5: {input: 2.0, output: 10.0, cache_read: 0.2, "
        "cache_write_5m: 2.5, cache_write_1h: 4.0, cache_write_1hr: 4.0}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        prices.load_prices(tmp_path)


def test_an_override_unit_other_than_per_mtok_is_rejected(tmp_path: Path):
    # cost_of divides by a hard-coded _MTOK; a differently-scaled unit
    # would silently misprice every row by that scale factor.
    (tmp_path / "usage-prices.yaml").write_text(
        "effective_date: '2026-09-01'\n"
        "unit: per_ktok\n"
        "models:\n"
        "  claude-sonnet-5: {input: 2.0, output: 10.0, cache_read: 0.2, "
        "cache_write_5m: 2.5, cache_write_1h: 4.0}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        prices.load_prices(tmp_path)


def test_a_point_release_id_falls_back_to_its_family_row(tmp_path: Path):
    table = prices.load_prices(tmp_path)
    assert prices.resolve_model(table, "claude-fable-5-1") == "claude-fable-5"
    assert prices.resolve_model(table, "claude-opus-5-2-1") == "claude-opus-5"
    assert prices.cost_of(row("u1", model="claude-fable-5-1", tokens_out=1_000_000,
                              tokens_in=0, cache_read=0, cache_write_5m=0, cache_write_1h=0),
                          table) == 50.0


def test_the_packaged_aliases_price_the_bare_family_names(tmp_path: Path):
    table = prices.load_prices(tmp_path)
    assert table.aliases == {"opus": "claude-opus-5", "sonnet": "claude-sonnet-5",
                             "haiku": "claude-haiku-4-5"}
    assert prices.resolve_model(table, "opus") == "claude-opus-5"


def test_a_genuinely_unknown_model_still_resolves_to_none(tmp_path: Path):
    table = prices.load_prices(tmp_path)
    assert prices.resolve_model(table, "gpt-9") is None
    assert prices.resolve_model(table, "claude-sonnet-4") is None


def test_an_override_merges_aliases_per_key(tmp_path: Path):
    (tmp_path / "usage-prices.yaml").write_text(
        "aliases:\n  opus: claude-opus-4-8\n", encoding="utf-8"
    )
    table = prices.load_prices(tmp_path)
    assert table.aliases["opus"] == "claude-opus-4-8"
    assert table.aliases["sonnet"] == "claude-sonnet-5"
