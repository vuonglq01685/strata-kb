from datetime import date
from pathlib import Path

import pytest

from center_kb.usage import prices, report
from tests.test_usage_ledger import row

GEN = "2026-08-23T12:00:00Z"
TODAY = date(2026, 8, 23)


def agg_of(rows, tmp_path: Path):
    return report.aggregate(
        rows, prices.load_prices(tmp_path), today=TODAY, generated=GEN
    )


def test_total_sums_tokens_and_cost(tmp_path: Path):
    rows = [
        row("u1", model="claude-opus-5", tokens_out=1_000_000, cache_read=0,
            cache_write_1h=0, cache_write_5m=0, tokens_in=0),
        row("u2", model="claude-opus-5", tokens_out=1_000_000, cache_read=0,
            cache_write_1h=0, cache_write_5m=0, tokens_in=0),
    ]

    agg = agg_of(rows, tmp_path)

    assert agg.total.rows == 2
    assert agg.total.tokens_out == 2_000_000
    assert agg.total.cost == pytest.approx(50.0)


def test_buckets_split_by_ticket_phase_model_and_actor(tmp_path: Path):
    rows = [
        row("u1", ticket="open-new-flight", phase="ba-ticket-author", actor="ba"),
        row("u2", ticket="ATM-7", phase="dev-execute", actor="dev",
            model="claude-opus-5"),
    ]

    agg = agg_of(rows, tmp_path)

    assert {b.key for b in agg.by_ticket} == {"open-new-flight", "ATM-7"}
    assert {b.key for b in agg.by_phase} == {"ba-ticket-author", "dev-execute"}
    assert {b.key for b in agg.by_model} == {"claude-sonnet-5", "claude-opus-5"}
    assert {b.key for b in agg.by_actor} == {"ba", "dev"}


def test_buckets_are_sorted_by_cost_descending(tmp_path: Path):
    rows = [
        row("u1", ticket="cheap", tokens_out=1),
        row("u2", ticket="dear", tokens_out=1_000_000),
    ]

    assert [b.key for b in agg_of(rows, tmp_path).by_ticket] == ["dear", "cheap"]


def test_sidechain_cost_is_reported_apart_from_main(tmp_path: Path):
    rows = [row("u1", sidechain=False), row("u2", sidechain=True)]

    agg = agg_of(rows, tmp_path)

    assert (agg.main.rows, agg.sidechain.rows) == (1, 1)


def test_unattributed_rows_are_their_own_bucket_and_not_a_ticket(tmp_path: Path):
    agg = agg_of([row("u1", ticket=None), row("u2", ticket="ATM-7")], tmp_path)

    assert agg.unattributed.rows == 1
    assert [b.key for b in agg.by_ticket] == ["ATM-7"]


def test_an_unknown_model_is_counted_in_tokens_but_not_in_money(tmp_path: Path):
    # Invariant I5, report half.
    rows = [
        row("u1", model="claude-opus-5", tokens_out=1_000_000, tokens_in=0,
            cache_read=0, cache_write_1h=0, cache_write_5m=0),
        row("u2", model="claude-nonexistent-9", tokens_out=1_000_000, tokens_in=0,
            cache_read=0, cache_write_1h=0, cache_write_5m=0),
    ]

    agg = agg_of(rows, tmp_path)

    assert agg.total.cost == pytest.approx(25.0)
    assert agg.total.tokens_out == 2_000_000
    assert agg.total.unpriced_rows == 1
    assert agg.unpriced_models == ["claude-nonexistent-9"]


def test_stale_days_is_carried_into_the_aggregate(tmp_path: Path):
    agg = report.aggregate(
        [row("u1")], prices.load_prices(tmp_path), today=date(2030, 1, 1),
        generated=GEN,
    )

    assert agg.stale_days > 90


def test_html_is_self_contained(tmp_path: Path):
    html = report.render_html(agg_of([row("u1")], tmp_path))

    assert "<table" in html
    assert "<script" not in html.lower()
    assert "http://" not in html and "https://" not in html


def test_html_names_the_price_table_date_and_the_ticket(tmp_path: Path):
    html = report.render_html(agg_of([row("u1", ticket="open-new-flight")], tmp_path))

    assert "open-new-flight" in html
    assert "2026-06-24" in html


def test_html_escapes_a_field_that_carries_arbitrary_text(tmp_path: Path):
    # `model` is copied verbatim out of the transcript and is NOT stem-validated
    # the way `ticket` is, so it is the field that can actually carry markup.
    # (A hostile ticket name cannot reach here — STEM_RE rejects '<'.)
    html = report.render_html(
        agg_of([row("u1", model="<script>alert(1)</script>")], tmp_path)
    )

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_html_warns_when_the_price_table_is_old(tmp_path: Path):
    agg = report.aggregate(
        [row("u1")], prices.load_prices(tmp_path), today=date(2030, 1, 1),
        generated=GEN,
    )

    assert "out of date" in report.render_html(agg)


def test_html_says_so_when_a_model_is_unpriced(tmp_path: Path):
    agg = agg_of([row("u1", model="claude-nonexistent-9")], tmp_path)

    html = report.render_html(agg)

    assert "unpriced" in html
    assert "claude-nonexistent-9" in html


def test_markdown_is_a_compact_table_for_a_pr_body(tmp_path: Path):
    md = report.render_markdown(agg_of([row("u1", ticket="open-new-flight")], tmp_path))

    assert md.startswith("| ")
    assert "open-new-flight" in md
    assert "\n\n\n" not in md


def test_markdown_an_all_unpriced_bucket_shows_no_completed_looking_zero(tmp_path: Path):
    # Invariant I5: 0.00 in a cost column is exactly the number that looks
    # complete but is not — an all-unpriced bucket must never show it.
    rows = [
        row("u1", model="claude-nonexistent-9", tokens_out=1_000, tokens_in=0,
            cache_read=0, cache_write_1h=0, cache_write_5m=0),
        row("u2", model="claude-nonexistent-9", tokens_out=2_000, tokens_in=0,
            cache_read=0, cache_write_1h=0, cache_write_5m=0),
    ]

    md = report.render_markdown(agg_of(rows, tmp_path))

    assert "0.00" not in md
    assert "unpriced" in md


def test_html_an_all_unpriced_bucket_shows_no_completed_looking_zero(tmp_path: Path):
    rows = [
        row("u1", model="claude-nonexistent-9", tokens_out=1_000, tokens_in=0,
            cache_read=0, cache_write_1h=0, cache_write_5m=0),
        row("u2", model="claude-nonexistent-9", tokens_out=2_000, tokens_in=0,
            cache_read=0, cache_write_1h=0, cache_write_5m=0),
    ]

    html = report.render_html(agg_of(rows, tmp_path))

    assert "0.00" not in html
    assert "unpriced" in html


def test_a_partially_unpriced_bucket_still_shows_its_real_cost(tmp_path: Path):
    rows = [
        row("u1", model="claude-opus-5", tokens_out=1_000_000, tokens_in=0,
            cache_read=0, cache_write_1h=0, cache_write_5m=0),
        row("u2", model="claude-nonexistent-9", tokens_out=1_000_000, tokens_in=0,
            cache_read=0, cache_write_1h=0, cache_write_5m=0),
    ]
    agg = agg_of(rows, tmp_path)

    md = report.render_markdown(agg)
    html = report.render_html(agg)

    assert "25.00 USD (+1 unpriced)" in md
    assert "25.00" in html and "unpriced" in html


def test_html_and_markdown_spell_a_zero_row_bucket_the_same_way(tmp_path: Path):
    # Before the fix: markdown printed '-' for a zero-row bucket, HTML
    # printed '0.00' — pick one spelling and use it in both.
    agg = agg_of([row("u1", ticket="open-new-flight", sidechain=False)], tmp_path)
    assert agg.sidechain.rows == 0

    html = report.render_html(agg)

    assert "0.00" not in html


def test_estimated_rows_are_counted_and_shown(tmp_path: Path):
    rows = [row("u1"), row("u2", est=True, assistant="copilot")]
    agg = agg_of(rows, tmp_path)
    assert agg.total.est_rows == 1
    assert {b.key: b.rows for b in agg.by_assistant} == {"claude-code": 1, "copilot": 1}
    md = report.render_markdown(agg)
    assert "(1 estimated)" in md
    assert "| assistant: copilot |" in md
    html = report.render_html(agg)
    assert "By assistant" in html and "copilot" in html and "1 estimated" in html
    assert agg.model_dump()["total"]["est_rows"] == 1


def test_priced_as_lists_ids_priced_at_a_family_rate(tmp_path: Path):
    agg = agg_of([row("u1", model="claude-fable-5-1")], tmp_path)
    assert agg.priced_as == {"claude-fable-5-1": "claude-fable-5"}
    assert agg.unpriced_models == []
    assert "claude-fable-5-1 priced as claude-fable-5" in report.render_markdown(agg)
    assert "priced as" in report.render_html(agg)


def test_markdown_warns_when_the_price_table_is_old(tmp_path: Path):
    (tmp_path / "usage-prices.yaml").write_text("effective_date: '2026-01-01'\n", encoding="utf-8")
    md = report.render_markdown(agg_of([row("u1")], tmp_path))
    assert md.startswith("**Warning: price table is 234 days old")


def test_markdown_and_html_mention_hook_errors_when_present(tmp_path: Path):
    agg = agg_of([row("u1")], tmp_path)
    agg.hook_errors = 3
    assert "3 hook ingest error(s) logged" in report.render_markdown(agg)
    assert "3 hook ingest error(s)" in report.render_html(agg)
