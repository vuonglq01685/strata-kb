# Usage cost review fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `kb usage report` counts every API call a session and its subagents made, once each. It prices each call at the 2026-10-10 list price, or shows it `unpriced`, never at a guessed rate.

**Architecture:**
- Pricing changes stay inside `usage/prices.py` plus the packaged YAML.
- `usage/transcript.py` changes in three ways. Each call is collected first and emitted at the end of the scan, which allows max-output and hold-back. A `ParentCursor` attributes subagent rows. Path helpers find subagent files.
- A new `usage/ingest.py` owns orchestration, so `cli.py` keeps only payload parsing and error swallowing. It covers a main transcript plus its subagents, and a lone subagent transcript.
- `report.py`, `doctor.py`, the settings template and the docs follow.

**Tech Stack:** Python 3.11+, pydantic v2, typer, jinja2, pytest.

**Spec:** `docs/superpowers/specs/2026-10-10-usage-cost-review-fixes-design.md`

## Global Constraints

- Invariants I1–I5 of `2026-08-23-kb-usage-measurement-design.md` hold:
  - I1: a stored row never changes.
  - I2: global dedup by `uuid`.
  - I3: numbers are copied, never computed.
  - I5: unknown model → `unpriced`, never 0.
- Every `--hook-stdin` path exits 0 and writes nothing to stdout. Failures go to `.kb/usage/ingest-errors.log`.
- New `UsageRow` fields are defaulted, so committed ledgers keep loading.
- Release **1.9.0**: `pyproject.toml`, the `strata-kb` entry in `uv.lock`, and a `## 1.9.0 — <date>` CHANGELOG heading.
- Commit messages via `git commit -F <file>` (not heredoc `-m`).
- Test command: `uv run pytest -q` (offline: export `TIKTOKEN_CACHE_DIR` to a primed cache first; see review §4.3).
- Lint: `uv run ruff check .`

## Deviations from the spec (decided while planning)

- **Fixture-id test** (spec §Testing, "every model id appearing in any test fixture transcript"). The usage tests build transcripts inline; there is no fixture directory. The test instead pins a `CURRENT_MODEL_IDS` tuple: the ids Claude Code writes today. It asserts each one resolves to **itself**, not via an alias.
- **PDF rebuild** (spec §6). The QUICKSTARTs are init templates, not PDF sources, and no `docs/src/guide-*.md` mentions usage cost. No PDF is rebuilt.
- **QUICKSTART version line.** "`kb` must be 0.19.0 or newer" stays true for the hook not blocking a turn. An older `kb` receiving a `SubagentStop` payload just re-ingests the main transcript, which is harmless. A second sentence is added: subagent cost needs 1.9.0.

---

### Task 1: Price table: current generation, no family fallback

**Files:**
- Modify: `src/strata_kb/templates/usage/usage-prices.yaml`
- Modify: `src/strata_kb/usage/prices.py` (`resolve_model`, drop `_POINT_RELEASE`)
- Modify: `tests/test_usage_prices.py`, `tests/test_usage_report.py`

**Interfaces:**
- Produces: `prices.resolve_model(table, model) -> str | None`. This means exact id, else alias, else `None`.

Depends on: none

- [ ] **Step 1: Write the failing tests.** In `tests/test_usage_prices.py`:
  - Replace `test_the_packaged_sonnet_5_row_is_the_standard_rate_not_the_promo`.
  - Replace `test_a_point_release_id_falls_back_to_its_family_row`.
  - Replace `test_the_packaged_aliases_price_the_bare_family_names`.
  - Add the rest below.

```python
# Verified against platform.claude.com/docs/en/about-claude/pricing on
# 2026-10-10: (input, output, cache_read, cache_write_5m, cache_write_1h).
LIST_PRICES = {
    "claude-fable-5-1": (10.0, 50.0, 0.25, 12.5, 20.0),
    "claude-fable-5": (10.0, 50.0, 1.0, 12.5, 20.0),
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0, 8.0),
    "claude-opus-5": (5.0, 25.0, 0.50, 6.25, 10.0),
    "claude-sonnet-5-5": (2.0, 10.0, 0.10, 2.5, 4.0),
    "claude-sonnet-5": (2.0, 10.0, 0.20, 2.5, 4.0),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125, 0.20),
    "claude-haiku-4-5": (1.0, 5.0, 0.10, 1.25, 2.0),
}

# The ids Claude Code writes today. Each must have its OWN row: a
# family or alias match is exactly how the 5.5 generation was mispriced.
CURRENT_MODEL_IDS = (
    "claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5",
    "claude-fable-5", "claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5",
)


@pytest.mark.parametrize("model", sorted(LIST_PRICES))
def test_the_packaged_row_is_the_list_price(tmp_path: Path, model: str):
    r = prices.load_prices(tmp_path).models[model]
    assert (r.input, r.output, r.cache_read, r.cache_write_5m, r.cache_write_1h) == (
        pytest.approx(LIST_PRICES[model])
    )


def test_the_packaged_sonnet_5_row_is_the_standard_rate_not_the_promo(tmp_path: Path):
    # 2/10 was announced as introductory and then made standard; the
    # scheduled 3/15 increase "will not occur" (pricing page, 2026-10-10).
    rates = prices.load_prices(tmp_path).models["claude-sonnet-5"]
    assert (rates.input, rates.output) == (2.0, 10.0)


@pytest.mark.parametrize("model", CURRENT_MODEL_IDS)
def test_every_current_model_id_has_its_own_row(tmp_path: Path, model: str):
    assert prices.resolve_model(prices.load_prices(tmp_path), model) == model


def test_a_point_release_id_with_no_row_is_unpriced(tmp_path: Path):
    table = prices.load_prices(tmp_path)
    assert prices.resolve_model(table, "claude-opus-5-6") is None
    assert prices.cost_of(row("u1", model="claude-opus-5-6"), table) is None


def test_the_packaged_aliases_point_at_the_current_generation(tmp_path: Path):
    table = prices.load_prices(tmp_path)
    assert table.aliases == {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5",
                             "haiku": "claude-haiku-5-5"}
    assert prices.resolve_model(table, "opus") == "claude-opus-5-5"


def test_the_packaged_table_is_dated_when_it_was_verified(tmp_path: Path):
    assert prices.load_prices(tmp_path).effective_date == "2026-10-10"
```

  In `tests/test_usage_report.py`, replace `test_priced_as_lists_ids_priced_at_a_family_rate`:

```python
def test_priced_as_lists_only_alias_matches(tmp_path: Path):
    agg = agg_of([row("u1", model="opus"), row("u2", model="claude-opus-5-6")], tmp_path)
    assert agg.priced_as == {"opus": "claude-opus-5-5"}
    assert agg.unpriced_models == ["claude-opus-5-6"]
    assert "opus priced as claude-opus-5-5" in report.render_markdown(agg)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_usage_prices.py tests/test_usage_report.py -q`
Expected: FAIL. The rows for 5.5/5.1 are missing, sonnet-5 is 3.0, and `claude-opus-5-6` resolves to `claude-opus-5`.

- [ ] **Step 3: Implement.** `usage-prices.yaml`:
  - Set `effective_date: "2026-10-10"`.
  - Set the rows exactly as in `LIST_PRICES`. Keep the 4.x rows unchanged; Haiku 5.5's `long_context` is added in Task 2.
  - Set aliases to `opus: claude-opus-5-5`, `sonnet: claude-sonnet-5-5`, `haiku: claude-haiku-5-5`.

  Rewrite the header comment:

```yaml
# Anthropic first-party API list prices, per million tokens (USD), as
# published at platform.claude.com/docs/en/about-claude/pricing.
#
# Rates are written out explicitly, never as multipliers of `input`: the
# cache-read multiplier is 0.1x on most models but 0.05x on Opus/Sonnet 5.5
# and 0.025x on Fable 5.1, and a multiplier convention would have hidden that.
#
# Standard rates only, never promotional ones.
#
# Every model id needs its OWN row. An id with no row (here or in
# .kb/usage-prices.yaml) is reported as `unpriced` with its token counts.
# There is deliberately no fallback from `claude-x-5-5` to `claude-x-5`: the
# 5.5 generation costs less than its family and caches at a different
# multiplier, so a family price is a wrong number that looks right. Add a row.
#
# `kb usage report` prints effective_date and warns once it is over 90 days old.
```

  `prices.py`: delete `_POINT_RELEASE` and the `re` import, then replace `resolve_model`:

```python
def resolve_model(table: PriceTable, model: str) -> str | None:
    """The table row that prices `model`: its exact id, else an alias, else
    None. No family fallback: a point release may be priced differently
    from its family (the 5.5 generation is), so an id without a row is
    `unpriced` until someone adds one — invariant I5 extended to ids."""
    if model in table.models:
        return model
    alias = table.aliases.get(model)
    return alias if alias in table.models else None
```

  Update the module docstring line about families accordingly.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_usage_prices.py tests/test_usage_report.py tests/test_cli_usage.py -q`
Expected: PASS. `test_cost_sums_all_five_components` and `test_a_measured_session_prices_to_the_number_we_verified` use Opus 5, so they are unchanged.

- [ ] **Step 5: Commit.** `fix(usage): list prices for the 5.5/5.1 generation, sonnet-5 at 2/10, no family fallback`

---

### Task 2: Haiku 5.5 long-context tier

**Files:**
- Modify: `src/strata_kb/usage/prices.py`
- Modify: `src/strata_kb/templates/usage/usage-prices.yaml`
- Test: `tests/test_usage_prices.py`

**Interfaces:**
- Produces: `prices.Rates` (the five rates), `prices.LongContextRates(Rates)` with `threshold: int`, and `prices.ModelRates(Rates)` with `long_context: LongContextRates | None = None`. `cost_of` is unchanged in signature.

Depends on: Task 1

- [ ] **Step 1: Write the failing tests**

```python
def _prompt_row(prompt_in: int, cache_read: int = 0):
    return row("u1", model="claude-haiku-5-5", tokens_in=prompt_in, tokens_out=1_000_000,
               cache_read=cache_read, cache_write_5m=0, cache_write_1h=0)


def test_haiku_5_5_at_the_threshold_is_the_base_tier(tmp_path: Path):
    table = prices.load_prices(tmp_path)
    # 100,000 prompt tokens is "up to 100,000": base tier.
    assert prices.cost_of(_prompt_row(100_000), table) == pytest.approx(
        (100_000 * 0.10 + 1_000_000 * 0.50) / 1_000_000)


def test_haiku_5_5_over_the_threshold_prices_the_whole_call_long(tmp_path: Path):
    table = prices.load_prices(tmp_path)
    # Cache reads count toward prompt length: 1 + 100,000 > 100,000.
    assert prices.cost_of(_prompt_row(1, cache_read=100_000), table) == pytest.approx(
        (1 * 0.50 + 100_000 * 0.05 + 1_000_000 * 2.50) / 1_000_000)


def test_an_override_can_add_a_long_context_tier(tmp_path: Path):
    (tmp_path / "usage-prices.yaml").write_text(yaml.safe_dump({"models": {"claude-x": {
        "input": 1.0, "output": 1.0, "cache_read": 0.1, "cache_write_5m": 1.25,
        "cache_write_1h": 2.0,
        "long_context": {"threshold": 10, "input": 2.0, "output": 2.0, "cache_read": 0.2,
                         "cache_write_5m": 2.5, "cache_write_1h": 4.0}}}}), encoding="utf-8")
    table = prices.load_prices(tmp_path)
    r = row("u1", model="claude-x", tokens_in=11, tokens_out=0, cache_read=0,
            cache_write_5m=0, cache_write_1h=0)
    assert prices.cost_of(r, table) == pytest.approx(22 / 1_000_000)


def test_a_misspelled_long_context_key_raises(tmp_path: Path):
    (tmp_path / "usage-prices.yaml").write_text(yaml.safe_dump({"models": {"claude-x": {
        "input": 1.0, "output": 1.0, "cache_read": 0.1, "cache_write_5m": 1.25,
        "cache_write_1h": 2.0, "long_context": {"treshold": 10, "input": 2.0, "output": 2.0,
        "cache_read": 0.2, "cache_write_5m": 2.5, "cache_write_1h": 4.0}}}}), encoding="utf-8")
    with pytest.raises(ValidationError):
        prices.load_prices(tmp_path)
```

- [ ] **Step 2: Run to verify failure.** `uv run pytest tests/test_usage_prices.py -q`. Expected: FAIL. `long_context` is an extra key, forbidden today.

- [ ] **Step 3: Implement.** In `prices.py`, split the model:

```python
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
```

  In `cost_of`, pick the tier before summing:

```python
    model_rates = table.models[key]
    rates: Rates = model_rates
    prompt = row.tokens_in + row.cache_read + row.cache_write_5m + row.cache_write_1h
    if model_rates.long_context is not None and prompt > model_rates.long_context.threshold:
        rates = model_rates.long_context
```

  YAML: give `claude-haiku-5-5` a long-context tier, using a block mapping for readability:

```yaml
  claude-haiku-5-5:
    {input: 0.10, output: 0.50, cache_read: 0.01, cache_write_5m: 0.125, cache_write_1h: 0.20,
     long_context: {threshold: 100000, input: 0.50, output: 2.50, cache_read: 0.05,
                    cache_write_5m: 0.625, cache_write_1h: 1.0}}
```

  Add a header comment line: "`long_context` reprices the whole call when input + cache read + cache write exceeds `threshold`."

- [ ] **Step 4: Run to verify pass.** `uv run pytest tests/test_usage_prices.py -q`. Expected: PASS.
- [ ] **Step 5: Commit.** `feat(usage): long-context price tier (Haiku 5.5 over 100k prompt tokens)`

---

### Task 3: Record and price modifiers

**Files:**
- Modify: `src/strata_kb/usage/ledger.py` (`UsageRow`)
- Modify: `src/strata_kb/usage/prices.py` (`PriceTable.web_search_per_1k`, `cost_of`, `is_lower_bound`, `has_unknown_modifier`)
- Test: `tests/test_usage_prices.py`, `tests/test_usage_ledger.py`

**Interfaces:**
- Produces:
  - `UsageRow.inference_geo: str = ""`, `speed: str = ""`, `service_tier: str = ""`, `web_searches: int = 0`.
  - `prices.is_lower_bound(row) -> bool`.
  - `prices.has_unknown_modifier(row) -> bool`.

Depends on: Task 2

- [ ] **Step 0: Verify value strings.** Before coding, fetch the Messages API `usage` object reference (platform.claude.com docs, "usage" → `inference_geo`, `speed`, `service_tier`). Record the exact strings for US-only geo, global geo, fast and standard speed. The constants below assume `"us"` / `"global"` / `"fast"` / `"standard"`. Correct them, and the tests, if the docs say otherwise.

- [ ] **Step 1: Write the failing tests**

```python
def _plain(**kw):
    base = dict(model="claude-opus-5", tokens_in=0, tokens_out=1_000_000, cache_read=0,
                cache_write_5m=0, cache_write_1h=0)
    base.update(kw)
    return row("u1", **base)


def test_us_only_inference_multiplies_token_cost(tmp_path: Path):
    table = prices.load_prices(tmp_path)
    assert prices.cost_of(_plain(inference_geo="us"), table) == pytest.approx(25.0 * 1.1)
    assert prices.cost_of(_plain(inference_geo="global"), table) == pytest.approx(25.0)


def test_web_searches_add_their_per_search_price(tmp_path: Path):
    table = prices.load_prices(tmp_path)
    assert prices.cost_of(_plain(web_searches=3), table) == pytest.approx(25.0 + 0.03)


def test_fast_mode_is_priced_at_standard_and_flagged_lower_bound(tmp_path: Path):
    table = prices.load_prices(tmp_path)
    r = _plain(speed="fast")
    assert prices.cost_of(r, table) == pytest.approx(25.0)
    assert prices.is_lower_bound(r) and not prices.has_unknown_modifier(r)


def test_an_unrecognised_modifier_is_flagged_and_priced_as_global(tmp_path: Path):
    table = prices.load_prices(tmp_path)
    r = _plain(inference_geo="mars")
    assert prices.cost_of(r, table) == pytest.approx(25.0)
    assert prices.has_unknown_modifier(r)
```

  In `tests/test_usage_ledger.py`:

```python
def test_a_ledger_line_written_before_modifiers_existed_still_loads():
    old = row("u1").model_dump(mode="json")
    for key in ("inference_geo", "speed", "service_tier", "web_searches"):
        old.pop(key)
    loaded = ledger.UsageRow.model_validate(old)
    assert (loaded.inference_geo, loaded.speed, loaded.web_searches) == ("", "", 0)
```

- [ ] **Step 2: Run to verify failure.** `uv run pytest tests/test_usage_prices.py tests/test_usage_ledger.py -q`. Expected: FAIL. The fields are unknown.

- [ ] **Step 3: Implement.** `UsageRow` gains the four defaulted fields after `request`, with a comment. They are copied from the `usage` block (I3). Empty means "not reported", which is every row written before 1.9.0.

  `PriceTable` gains `web_search_per_1k: float = 10.0`, and the YAML gets the same key at top level with a comment.

  `prices.py`:

```python
# Values of the API `usage` block (verified in Task 3 Step 0).
US_ONLY_GEO = frozenset({"us"})
KNOWN_GEO = frozenset({"", "global"}) | US_ONLY_GEO
FAST_SPEED = "fast"
KNOWN_SPEED = frozenset({"", "standard", FAST_SPEED})
US_ONLY_FACTOR = 1.1  # "1.1x multiplier on all token pricing categories"


def is_lower_bound(row: UsageRow) -> bool:
    """Fast mode has no published cache rates, so its cost is reported at
    the standard rate and flagged rather than guessed."""
    return row.speed == FAST_SPEED


def has_unknown_modifier(row: UsageRow) -> bool:
    return row.inference_geo not in KNOWN_GEO or row.speed not in KNOWN_SPEED
```

  At the end of `cost_of`:

```python
    tokens = (...) / _MTOK
    if row.inference_geo in US_ONLY_GEO:
        tokens *= US_ONLY_FACTOR
    return tokens + row.web_searches * table.web_search_per_1k / 1000
```

- [ ] **Step 4: Run to verify pass.** `uv run pytest tests/test_usage_*.py -q`. Expected: PASS.
- [ ] **Step 5: Commit.** `feat(usage): record inference_geo/speed/service_tier/web searches; price geo and search`

---

### Task 4: Transcript: one call → the complete row

**Files:**
- Modify: `src/strata_kb/usage/transcript.py`
- Test: `tests/test_usage_transcript.py`

**Interfaces:**
- Produces: `rows_from_transcript(path, *, actor, session_fallback="", forced_ticket=None, subagent=False, parent=None, hold_back_last=False)`. This task adds only `hold_back_last`; Task 5 adds `subagent` and `parent`. It also adds an internal `_rows(path) -> list[dict]` (the parse loop).

Depends on: Task 3

- [ ] **Step 1: Write the failing tests**

```python
def _streamed(uuid: str, request: str, out: int, **kw):
    return usage_row(uuid, out=out, requestId=request, **kw)


def test_a_streamed_call_keeps_its_largest_output_and_its_first_uuid(tmp_path: Path):
    # Measured 2026-10-10: the first row of a streamed call (a thinking
    # block) reported output 5; the last reported 329.
    path = write_transcript(tmp_path, [_streamed("a1", "req-1", 5), _streamed("a2", "req-1", 329)])
    rows = transcript.rows_from_transcript(path, actor="dev")
    assert [(r.uuid, r.tokens_out) for r in rows] == [("a1", 329)]


def test_the_other_counts_come_from_the_same_row_as_the_max(tmp_path: Path):
    first = _streamed("a1", "req-1", 5)
    last = _streamed("a2", "req-1", 329)
    last["message"]["usage"]["cache_read_input_tokens"] = 4242
    rows = transcript.rows_from_transcript(write_transcript(tmp_path, [first, last]), actor="dev")
    assert rows[0].cache_read == 4242


def test_calls_are_emitted_in_first_seen_order(tmp_path: Path):
    path = write_transcript(tmp_path, [_streamed("a1", "req-1", 5), _streamed("b1", "req-2", 9),
                                       _streamed("a2", "req-1", 50)])
    assert [r.uuid for r in transcript.rows_from_transcript(path, actor="dev")] == ["a1", "b1"]


def test_hold_back_last_drops_only_the_final_call(tmp_path: Path):
    path = write_transcript(tmp_path, [_streamed("a1", "req-1", 5), _streamed("b1", "req-2", 9)])
    rows = transcript.rows_from_transcript(path, actor="dev", hold_back_last=True)
    assert [r.uuid for r in rows] == ["a1"]


def test_top_level_cache_creation_is_read_as_5m_when_the_split_is_absent(tmp_path: Path):
    r = usage_row("a1")
    del r["message"]["usage"]["cache_creation"]
    rows = transcript.rows_from_transcript(write_transcript(tmp_path, [r]), actor="dev")
    assert (rows[0].cache_write_5m, rows[0].cache_write_1h) == (300, 0)


def test_modifiers_are_copied_from_the_usage_block(tmp_path: Path):
    r = usage_row("a1")
    r["message"]["usage"].update({"inference_geo": "us", "speed": "fast",
                                  "service_tier": "standard",
                                  "server_tool_use": {"web_search_requests": 2}})
    row = transcript.rows_from_transcript(write_transcript(tmp_path, [r]), actor="dev")[0]
    assert (row.inference_geo, row.speed, row.service_tier, row.web_searches) == (
        "us", "fast", "standard", 2)
```

- [ ] **Step 2: Run to verify failure.** `uv run pytest tests/test_usage_transcript.py -q`. Expected: FAIL. The first row wins, and `hold_back_last` is an unknown kwarg.

- [ ] **Step 3: Implement.** Restructure `rows_from_transcript`:
  - Factor the parse loop into `_rows(path) -> list[dict]`, so it can be reused by Task 5.
  - Keep the cursor walk exactly as is.
  - Instead of appending on first sight, record a `_Call` and emit at the end:

```python
@dataclass
class _Call:
    first: dict          # the call's first transcript row: uuid, ts, session, branch, model
    usage: dict          # the usage block of the row with the largest output_tokens
    ticket: str | None   # cursor at the first row
    phase: str


def _usage_counts(usage: dict) -> dict:
    creation = usage.get("cache_creation")
    if isinstance(creation, dict):
        w5 = _int(creation, "ephemeral_5m_input_tokens")
        w1 = _int(creation, "ephemeral_1h_input_tokens")
    else:
        # An older or foreign producer writes only the total; the cheaper
        # 5m rate is the conservative reading.
        w5, w1 = _int(usage, "cache_creation_input_tokens"), 0
    server = usage.get("server_tool_use")
    return dict(
        tokens_in=_int(usage, "input_tokens"),
        tokens_out=_int(usage, "output_tokens"),
        cache_read=_int(usage, "cache_read_input_tokens"),
        cache_write_5m=w5,
        cache_write_1h=w1,
        inference_geo=_str(usage, "inference_geo"),
        speed=_str(usage, "speed"),
        service_tier=_str(usage, "service_tier"),
        web_searches=_int(server, "web_search_requests") if isinstance(server, dict) else 0,
    )
```

  In the loop body, where the old code did `if request in seen_calls: continue`:

```python
        call = calls.get(request)
        if call is None:
            calls[request] = _Call(first=row, usage=usage, ticket=ticket, phase=phase)
        elif _int(usage, "output_tokens") > _int(call.usage, "output_tokens"):
            # A streamed call writes a row per content block; the first one
            # can carry a partial output count (5 vs 329 measured). Keep the
            # whole usage block of the largest, never a mix of rows.
            call.usage = usage
```

  After the loop:

```python
    keys = list(calls)  # dict order = first-seen order
    if hold_back_last and keys:
        # The last call may still be streaming (a Stop hook can fire while a
        # background subagent is mid-call). A stored row never changes (I1),
        # so storing it now would freeze a partial output count forever.
        keys = keys[:-1]
    return [_to_row(calls[k], k, actor=actor, session_fallback=session_fallback,
                    forced_ticket=forced_ticket, sidechain_override=False) for k in keys]
```

  `_to_row` builds the `UsageRow` from `call.first` (uuid, timestamp, sessionId, gitBranch, model, isSidechain) and `_usage_counts(call.usage)`. `_str(d, key)` returns `d[key]` when it is a `str`, else `""`. Update the docstring: "the later copies refine the call's output count; they are never emitted".

- [ ] **Step 4: Run to verify pass.** `uv run pytest tests/test_usage_transcript.py tests/test_cli_usage.py -q`. Expected: PASS, including every pre-existing cursor test.
- [ ] **Step 5: Commit.** `fix(usage): a streamed call keeps its largest output count; hold back an in-flight call`

---

### Task 5: Subagent transcripts: path helpers and parent cursor

**Files:**
- Modify: `src/strata_kb/usage/transcript.py`
- Test: `tests/test_usage_transcript.py`

**Interfaces:**
- Produces:
  - `ParentCursor` with `.at(ts: str) -> tuple[str | None, str]`.
  - `parent_cursor(path: Path) -> ParentCursor`.
  - `subagent_transcripts(main: Path) -> list[Path]`.
  - `is_subagent_transcript(path: Path) -> bool`.
  - `parent_of(subagent: Path) -> Path`.
  - `rows_from_transcript(..., subagent: bool = False, parent: ParentCursor | None = None)`.

Depends on: Task 4

- [ ] **Step 1: Write the failing tests**

```python
def _session(tmp_path: Path, main_rows, subagents: dict[str, list[dict]]) -> Path:
    main = write_transcript(tmp_path, main_rows, name="sess-1.jsonl")
    folder = tmp_path / "sess-1" / "subagents"
    folder.mkdir(parents=True)
    for agent_id, rows in subagents.items():
        write_transcript(folder, rows, name=f"agent-{agent_id}.jsonl")
    return main


def test_subagent_transcripts_are_found_next_to_the_main_file(tmp_path: Path):
    main = _session(tmp_path, [usage_row("m1")], {"b": [usage_row("s2")], "a": [usage_row("s1")]})
    found = transcript.subagent_transcripts(main)
    assert [p.name for p in found] == ["agent-a.jsonl", "agent-b.jsonl"]
    assert all(transcript.is_subagent_transcript(p) for p in found)
    assert transcript.parent_of(found[0]) == main
    assert not transcript.is_subagent_transcript(main)


def test_no_subagent_folder_is_no_subagents(tmp_path: Path):
    assert transcript.subagent_transcripts(write_transcript(tmp_path, [usage_row("m1")])) == []


def test_a_subagent_row_is_always_sidechain(tmp_path: Path):
    path = write_transcript(tmp_path, [usage_row("s1", isSidechain=False)])
    rows = transcript.rows_from_transcript(path, actor="dev", subagent=True)
    assert rows[0].sidechain is True


def test_a_subagent_inherits_the_parents_ticket_and_phase_until_it_names_its_own(tmp_path: Path):
    main = write_transcript(tmp_path, [
        skill_call_row("dev-execute"),
        user_row("work on docs/impl/ATM-7/plan.md", timestamp="2026-08-23T09:59:01.000Z"),
        user_row("now tickets/ATM-9.md", timestamp="2026-08-23T10:30:00.000Z"),
    ], name="main.jsonl")
    sub = write_transcript(tmp_path, [
        usage_row("s1", timestamp="2026-08-23T10:00:00.000Z"),
        user_row("read docs/impl/ATM-8/plan.md", timestamp="2026-08-23T10:00:01.000Z"),
        usage_row("s2", timestamp="2026-08-23T10:00:02.000Z"),
    ], name="sub.jsonl")
    rows = transcript.rows_from_transcript(sub, actor="dev", subagent=True,
                                           parent=transcript.parent_cursor(main))
    assert [(r.uuid, r.ticket, r.phase) for r in rows] == [
        ("s1", "ATM-7", "dev-execute"),   # parent at the subagent's first timestamp
        ("s2", "ATM-8", "dev-execute"),   # its own cursor once it has one
    ]


def test_forced_ticket_beats_both_cursors_for_a_subagent(tmp_path: Path):
    main = write_transcript(tmp_path, [user_row("tickets/ATM-7.md")], name="main.jsonl")
    sub = write_transcript(tmp_path, [usage_row("s1")], name="sub.jsonl")
    rows = transcript.rows_from_transcript(sub, actor="dev", subagent=True,
                                           parent=transcript.parent_cursor(main),
                                           forced_ticket="X-1")
    assert rows[0].ticket == "X-1"
```

  Note: `skill_call_row` has timestamp `09:58:00`. `ParentCursor.at` compares ISO-8601 strings lexicographically. That is valid because Claude Code writes every timestamp in the same `YYYY-MM-DDTHH:MM:SS.mmmZ` form; add a comment saying so.

- [ ] **Step 2: Run to verify failure.** `uv run pytest tests/test_usage_transcript.py -q`. Expected: FAIL (`AttributeError: subagent_transcripts`).

- [ ] **Step 3: Implement**

```python
SUBAGENTS_DIR = "subagents"


def subagent_transcripts(main: Path) -> list[Path]:
    """Claude Code writes each subagent to
    `<session-id>/subagents/agent-<id>.jsonl` beside `<session-id>.jsonl`.
    The format is documented as internal and version-dependent; this is the
    one place that knows the layout. A hook payload's `agent_transcript_path`
    is used whenever there is one."""
    return sorted((main.with_suffix("") / SUBAGENTS_DIR).glob("agent-*.jsonl"))


def is_subagent_transcript(path: Path) -> bool:
    return path.parent.name == SUBAGENTS_DIR and path.name.startswith("agent-")


def parent_of(subagent: Path) -> Path:
    return subagent.parent.parent.with_suffix(".jsonl")


@dataclass(frozen=True)
class ParentCursor:
    """The parent session's (ticket, phase) at each change, in file order.

    Timestamps compare as strings: Claude Code writes every one in the same
    ISO-8601 `...Z` form, so lexical order is time order.
    """

    points: tuple[tuple[str, str | None, str], ...] = ()

    def at(self, ts: str) -> tuple[str | None, str]:
        ticket: str | None = None
        phase = UNKNOWN_PHASE
        for point_ts, point_ticket, point_phase in self.points:
            if point_ts > ts:
                break
            ticket, phase = point_ticket, point_phase
        return ticket, phase


def parent_cursor(path: Path) -> ParentCursor:
    """Walk a main transcript with the same cursor rules as
    `rows_from_transcript` and keep each change point."""
    points: list[tuple[str, str | None, str]] = []
    ticket: str | None = None
    phase = UNKNOWN_PHASE
    for row in _rows(path):
        found = _ticket_in(_ticket_blob(row))
        switched = _phase_in(row)
        if found is None and switched is None:
            continue
        ticket = found if found is not None else ticket
        phase = switched if switched is not None else phase
        ts = row.get("timestamp")
        if isinstance(ts, str) and ts:
            points.append((ts, ticket, phase))
    return ParentCursor(tuple(points))
```

  In `rows_from_transcript`:
  - Read `rows = _rows(path)` once.
  - When `parent` is given, compute `first_ts` (first row with a non-empty string `timestamp`) and set `inherited_ticket, phase = parent.at(first_ts)`. Otherwise use `None, UNKNOWN_PHASE`.
  - The own cursor `ticket` starts `None`. A call records `ticket if ticket is not None else inherited_ticket`.
  - `_to_row` sets `sidechain = subagent or bool(first.get("isSidechain"))`.
  - Docstring: a subagent's own cursor wins once it has named a ticket. Before that, the parent's cursor at the subagent's first row stands in. The file's location, not the row flag, makes a row sidechain.

- [ ] **Step 4: Run to verify pass.** `uv run pytest tests/test_usage_transcript.py -q`. Expected: PASS.
- [ ] **Step 5: Commit.** `feat(usage): read subagent transcripts — sidechain rows, parent-cursor attribution`

---

### Task 6: `usage/ingest.py` and the CLI hook dispatch

**Files:**
- Create: `src/strata_kb/usage/ingest.py`
- Modify: `src/strata_kb/cli.py` (`_usage_ingest`, `usage_ingest_transcript`)
- Test: `tests/test_usage_ingest.py` (new), `tests/test_cli_usage.py`

**Interfaces:**
- Consumes: Task 5's helpers, `ledger.append_rows(kb_dir, rows) -> AppendReport`.
- Produces:
  - `ingest.IngestResult(report: AppendReport, notes: list[str])`.
  - `ingest.ingest_main(kb_dir, main, *, actor, session="", ticket=None, hold_back_subagents) -> IngestResult`.
  - `ingest.ingest_subagent(kb_dir, path, *, parent, actor, session="", ticket=None) -> IngestResult`, where `parent` is `Path | None`.
  - `ingest.ingest_path(kb_dir, path, *, actor, ticket=None) -> IngestResult`, the manual entry point.

Depends on: Task 5

- [ ] **Step 1: Write the failing tests.** `tests/test_usage_ingest.py`:

```python
from pathlib import Path

from strata_kb.usage import ingest, ledger
from tests.test_cli_usage import kb_dir
from tests.test_usage_transcript import usage_row, user_row, write_transcript


def _session(tmp_path: Path) -> Path:
    main = write_transcript(tmp_path, [user_row("tickets/ATM-7.md"), usage_row("m1")],
                            name="sess-1.jsonl")
    folder = tmp_path / "sess-1" / "subagents"
    folder.mkdir(parents=True)
    write_transcript(folder, [usage_row("s1", requestId="r1"), usage_row("s2", requestId="r2")],
                     name="agent-a.jsonl")
    return main


def test_a_main_ingest_sweeps_subagents_and_holds_back_their_last_call(tmp_path: Path):
    d = kb_dir(tmp_path)
    result = ingest.ingest_main(d, _session(tmp_path), actor="dev", hold_back_subagents=True)
    assert sorted(r.uuid for r in ledger.read_rows(d)) == ["m1", "s1"]
    assert result.report.written == 2


def test_subagent_stop_then_picks_up_the_held_back_call_without_duplicates(tmp_path: Path):
    d = kb_dir(tmp_path)
    main = _session(tmp_path)
    ingest.ingest_main(d, main, actor="dev", hold_back_subagents=True)
    sub = tmp_path / "sess-1" / "subagents" / "agent-a.jsonl"
    result = ingest.ingest_subagent(d, sub, parent=main, actor="dev")
    assert (result.report.written, result.report.duplicates) == (1, 1)
    rows = {r.uuid: r for r in ledger.read_rows(d)}
    assert rows["s2"].sidechain and rows["s2"].ticket == "ATM-7"


def test_an_unreadable_parent_still_ingests_the_subagent_and_says_so(tmp_path: Path):
    d = kb_dir(tmp_path)
    sub = write_transcript(tmp_path, [usage_row("s1")], name="agent-x.jsonl")
    result = ingest.ingest_subagent(d, sub, parent=tmp_path / "missing.jsonl", actor="dev")
    assert result.report.written == 1
    assert result.notes and "missing.jsonl" in result.notes[0]


def test_a_manual_path_under_subagents_finds_its_parent(tmp_path: Path):
    d = kb_dir(tmp_path)
    _session(tmp_path)
    ingest.ingest_path(d, tmp_path / "sess-1" / "subagents" / "agent-a.jsonl", actor="dev")
    assert {r.ticket for r in ledger.read_rows(d)} == {"ATM-7"}


def test_a_manual_main_ingest_does_not_hold_back(tmp_path: Path):
    d = kb_dir(tmp_path)
    ingest.ingest_path(d, _session(tmp_path), actor="dev")
    assert sorted(r.uuid for r in ledger.read_rows(d)) == ["m1", "s1", "s2"]
```

  In `tests/test_cli_usage.py` (hook dispatch):

```python
def test_hook_mode_with_an_agent_transcript_ingests_the_subagent(tmp_path: Path):
    d = kb_dir(tmp_path)
    main = write_transcript(tmp_path, [user_row("tickets/ATM-7.md")], name="sess-1.jsonl")
    folder = tmp_path / "sess-1" / "subagents"
    folder.mkdir(parents=True)
    sub = write_transcript(folder, [usage_row("s1")], name="agent-a.jsonl")
    payload = json.dumps({"session_id": "sess-1", "transcript_path": str(main),
                          "agent_id": "a", "agent_transcript_path": str(sub)})
    result = runner.invoke(
        app, ["usage", "ingest-transcript", "--hook-stdin", "--kb-dir", str(d)], input=payload)
    assert (result.exit_code, result.output) == (0, "")
    [row] = ledger.read_rows(d)
    assert (row.uuid, row.sidechain, row.ticket) == ("s1", True, "ATM-7")


@pytest.mark.parametrize("payload", [
    '{"agent_transcript_path": 7, "transcript_path": "x"}',
    '{"agent_transcript_path": "/nope/agent-a.jsonl"}',
    '{"agent_transcript_path": "/nope/agent-a.jsonl", "transcript_path": "/nope/p.jsonl"}',
])
def test_hook_mode_never_fails_on_a_bad_subagent_payload(tmp_path: Path, payload: str):
    d = kb_dir(tmp_path)
    result = runner.invoke(
        app, ["usage", "ingest-transcript", "--hook-stdin", "--kb-dir", str(d)], input=payload)
    assert (result.exit_code, result.output) == (0, "")
    assert (d / "usage" / "ingest-errors.log").exists()
```

  (Add `import pytest` to `tests/test_cli_usage.py` if absent.)

- [ ] **Step 2: Run to verify failure.** `uv run pytest tests/test_usage_ingest.py tests/test_cli_usage.py -q`. Expected: FAIL (`ImportError: ingest`).

- [ ] **Step 3: Implement `src/strata_kb/usage/ingest.py`**

```python
"""ingest — which transcript files one ingest reads, and with what cursor.

A session is a main transcript plus one transcript per subagent. A `Stop`
hook ingests the main file and sweeps its subagents, holding back each
subagent's last call because that call may still be streaming. A
`SubagentStop` hook ingests one finished subagent file in full. A manual
backfill ingests whatever path it is given, the session being over.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from strata_kb.usage import ledger, transcript


@dataclass
class IngestResult:
    report: ledger.AppendReport = field(default_factory=ledger.AppendReport)
    notes: list[str] = field(default_factory=list)

    def add(self, other: ledger.AppendReport) -> None:
        self.report.written += other.written
        self.report.duplicates += other.duplicates
        self.report.files = sorted(set(self.report.files) | set(other.files))


def _parent(parent: Path | None, result: IngestResult) -> transcript.ParentCursor | None:
    if parent is None:
        return None
    try:
        return transcript.parent_cursor(parent)
    except OSError as exc:
        # No call is dropped for want of attribution: the subagent's own
        # cursor still applies, and the miss is reported.
        result.notes.append(f"parent transcript unreadable, own cursor only: {parent}: {exc}")
        return None


def ingest_subagent(kb_dir: Path, path: Path, *, parent: Path | None, actor: str,
                    session: str = "", ticket: str | None = None,
                    hold_back_last: bool = False,
                    result: IngestResult | None = None) -> IngestResult:
    result = result or IngestResult()
    rows = transcript.rows_from_transcript(
        path, actor=actor, session_fallback=session, forced_ticket=ticket,
        subagent=True, parent=_parent(parent, result), hold_back_last=hold_back_last)
    result.add(ledger.append_rows(kb_dir, rows))
    return result


def ingest_main(kb_dir: Path, main: Path, *, actor: str, session: str = "",
                ticket: str | None = None, hold_back_subagents: bool) -> IngestResult:
    result = IngestResult()
    rows = transcript.rows_from_transcript(
        main, actor=actor, session_fallback=session, forced_ticket=ticket)
    result.add(ledger.append_rows(kb_dir, rows))
    for sub in transcript.subagent_transcripts(main):
        ingest_subagent(kb_dir, sub, parent=main, actor=actor, session=session,
                        ticket=ticket, hold_back_last=hold_back_subagents, result=result)
    return result


def ingest_path(kb_dir: Path, path: Path, *, actor: str,
                ticket: str | None = None) -> IngestResult:
    if transcript.is_subagent_transcript(path):
        parent = transcript.parent_of(path)
        return ingest_subagent(kb_dir, path, parent=parent if parent.is_file() else None,
                               actor=actor, ticket=ticket)
    return ingest_main(kb_dir, path, actor=actor, ticket=ticket, hold_back_subagents=False)
```

  `cli.py` changes:
  - `_usage_ingest(kb_dir, source, *, session, ticket)` becomes the manual path. It returns `ingest.ingest_path(...).report` and logs any `notes` via `_usage_log_error`.
  - In the `hook_stdin` branch, replace the body inside `try`:

```python
            payload = json.loads(raw)
            session = str(payload.get("session_id") or "")
            actor = _usage_actor(kb_dir)
            agent = payload.get("agent_transcript_path")
            if agent is not None:
                # SubagentStop: one finished subagent, in full.
                parent = payload.get("transcript_path")
                result = _ingest.ingest_subagent(
                    kb_dir, Path(agent), parent=Path(parent) if parent else None,
                    actor=actor, session=session, ticket=ticket or None)
            else:
                # Stop: the main transcript, plus a sweep of its subagents
                # that leaves each one's possibly in-flight last call for
                # SubagentStop.
                result = _ingest.ingest_main(
                    kb_dir, Path(payload["transcript_path"]), actor=actor,
                    session=session, ticket=ticket or None, hold_back_subagents=True)
            for note in result.notes:
                _usage_log_error(kb_dir, note)
```

  `Path(7)` raises `TypeError`, which the existing broad `except` logs. A missing parent reaches `_parent` as `OSError` and becomes a note, not a failure. Keep the "both a path and --hook-stdin" log line. Update the command docstring and the `path` help to say "a main transcript (its subagents are included) or a `subagents/agent-*.jsonl` file".

- [ ] **Step 4: Run to verify pass.** `uv run pytest tests/test_usage_ingest.py tests/test_cli_usage.py tests/test_usage_transcript.py -q`. Expected: PASS.
- [ ] **Step 5: Commit.** `feat(usage): ingest subagent transcripts from Stop (sweep) and SubagentStop`

---

### Task 7: Scaffold the `SubagentStop` hook

**Files:**
- Modify: `src/strata_kb/templates/init/claude-settings-usage.json`
- Modify: `tests/test_init.py` (`test_settings_json_is_scaffolded_for_ba_and_dev`)

Depends on: Task 6

- [ ] **Step 1: Write the failing test.** Extend the existing test so it checks both events:

```python
        for event in ("Stop", "SubagentStop"):
            commands = [hook["command"] for group in settings["hooks"][event]
                        for hook in group["hooks"]]
            assert commands == ["kb usage ingest-transcript --hook-stdin"], (kind, event)
```

- [ ] **Step 2: Run.** `uv run pytest tests/test_init.py -q -k settings_json`. Expected: FAIL (`KeyError: 'SubagentStop'`).
- [ ] **Step 3: Implement.** Add a `"SubagentStop"` array to the JSON, identical to `"Stop"` (same command, `timeout: 30`, `statusMessage: "Recording token usage..."`).
- [ ] **Step 4: Run.** `uv run pytest tests/test_init.py -q`. Expected: PASS. If a golden or `test_templates.py` byte-compare covers this file, update it in the same commit.
- [ ] **Step 5: Commit.** `feat(init): scaffold the SubagentStop usage hook`

---

### Task 8: Report: lower bound, unknown modifiers, unattributed share

**Files:**
- Modify: `src/strata_kb/usage/report.py`
- Modify: `src/strata_kb/templates/usage/report.html.j2`
- Test: `tests/test_usage_report.py`

**Interfaces:**
- Produces: `Aggregate.lower_bound_rows: int = 0`, `unknown_modifier_rows: int = 0`, `unattributed_pct: float = 0.0`. All three are in `--json` automatically via `model_dump_json`.

Depends on: Task 3

- [ ] **Step 1: Write the failing tests**

```python
def test_unattributed_share_is_a_headline_figure(tmp_path: Path):
    agg = agg_of([row("u1", ticket=None, model="claude-opus-5", tokens_out=1_000_000,
                      tokens_in=0, cache_read=0, cache_write_5m=0, cache_write_1h=0),
                  row("u2", ticket="ATM-7", model="claude-opus-5", tokens_out=3_000_000,
                      tokens_in=0, cache_read=0, cache_write_5m=0, cache_write_1h=0)], tmp_path)
    assert agg.unattributed_pct == pytest.approx(25.0)
    assert "Unattributed: 25.0 % of cost" in report.render_markdown(agg)
    assert "Unattributed: 25.0 % of cost" in report.render_html(agg)


def test_fast_mode_rows_make_the_total_a_lower_bound(tmp_path: Path):
    agg = agg_of([row("u1", speed="fast")], tmp_path)
    assert agg.lower_bound_rows == 1
    assert "1 call(s) in fast mode" in report.render_markdown(agg)
    assert "lower bound" in report.render_html(agg)


def test_unknown_modifiers_are_counted(tmp_path: Path):
    agg = agg_of([row("u1", inference_geo="mars")], tmp_path)
    assert agg.unknown_modifier_rows == 1
    assert "1 call(s) with an unrecognised modifier" in report.render_markdown(agg)


def test_no_modifier_lines_when_there_is_nothing_to_say(tmp_path: Path):
    md = report.render_markdown(agg_of([row("u1")], tmp_path))
    assert "fast mode" not in md and "unrecognised modifier" not in md
```

- [ ] **Step 2: Run.** `uv run pytest tests/test_usage_report.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement.** In `aggregate`, count `is_lower_bound` / `has_unknown_modifier` per row. After the loop:

```python
    if agg.total.cost > 0:
        agg.unattributed_pct = 100 * agg.unattributed.cost / agg.total.cost
    else:
        # Nothing priced: fall back to tokens, so the share is still shown.
        def _tok(b: Bucket) -> int:
            return b.tokens_in + b.tokens_out + b.cache_read + b.cache_write
        total = _tok(agg.total)
        agg.unattributed_pct = 100 * _tok(agg.unattributed) / total if total else 0.0
```

  `render_markdown`: right after the table's blank line, before "Priced as", add:

```python
    if agg.total.rows:
        lines.append(f"Unattributed: {agg.unattributed_pct:.1f} % of cost.")
    if agg.lower_bound_rows:
        lines.append(f"{agg.lower_bound_rows} call(s) in fast mode priced at the standard "
                     "rate — the total is a lower bound.")
    if agg.unknown_modifier_rows:
        lines.append(f"{agg.unknown_modifier_rows} call(s) with an unrecognised modifier.")
```

  `report.html.j2`:
  - Add the same three as `<p class="warn">` blocks (unattributed as `<p class="meta">`) directly under the `Total` table.
  - Change "Priced as a family rate:" to "Priced via alias:".

- [ ] **Step 4: Run.** `uv run pytest tests/test_usage_report.py tests/test_cli_usage.py -q`. Expected: PASS.
- [ ] **Step 5: Commit.** `feat(usage): report shows unattributed share, fast-mode lower bound, unknown modifiers`

---

### Task 9: `kb doctor` warns on a missing `SubagentStop` hook

**Files:**
- Modify: `src/strata_kb/doctor.py` (new `check_usage_hooks`)
- Modify: `src/strata_kb/cli.py` (call it next to `check_usage_log` for `ba`/`dev`)
- Test: `tests/test_doctor.py` (where `check_usage_log` is already tested)

**Interfaces:**
- Produces: `doctor.check_usage_hooks(repo_root: Path) -> list[Issue]`.

Depends on: Task 7

- [ ] **Step 1: Write the failing tests**

```python
from strata_kb.doctor import check_usage_hooks

_HOOK = {"hooks": [{"type": "command", "command": "kb usage ingest-transcript --hook-stdin"}]}


def _settings(root: Path, events: dict) -> None:
    (root / ".claude").mkdir(parents=True, exist_ok=True)
    (root / ".claude" / "settings.json").write_text(json.dumps({"hooks": events}), encoding="utf-8")


def test_doctor_warns_when_only_the_stop_usage_hook_is_present(tmp_path: Path):
    _settings(tmp_path, {"Stop": [_HOOK]})
    [issue] = check_usage_hooks(tmp_path)
    assert issue.level == "warning" and "SubagentStop" in issue.message


@pytest.mark.parametrize("events", [{"Stop": [_HOOK], "SubagentStop": [_HOOK]}, {}])
def test_doctor_is_silent_with_both_hooks_or_neither(tmp_path: Path, events: dict):
    _settings(tmp_path, events)
    assert check_usage_hooks(tmp_path) == []


def test_doctor_ignores_settings_it_cannot_read(tmp_path: Path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{not json", encoding="utf-8")
    assert check_usage_hooks(tmp_path) == []
```

  (`doctor.Issue` is a dataclass `Issue(level, message, code="")`.)

- [ ] **Step 2: Run.** Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implement** (add `import json` to `doctor.py`; it has none today)

```python
_USAGE_HOOK = "kb usage ingest-transcript"


def _has_usage_hook(settings: dict, event: str) -> bool:
    groups = (settings.get("hooks") or {}).get(event) or []
    return any(_USAGE_HOOK in str(h.get("command", ""))
               for g in groups if isinstance(g, dict)
               for h in (g.get("hooks") or []) if isinstance(h, dict))


def check_usage_hooks(repo_root: Path) -> list[Issue]:
    """`kb init` never rewrites an existing .claude/settings.json, so a repo
    set up before 1.9.0 has the Stop hook and not SubagentStop. The Stop
    sweep still records its subagents, minus each one's in-flight last call."""
    path = repo_root / ".claude" / "settings.json"
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(settings, dict):
        return []
    if _has_usage_hook(settings, "Stop") and not _has_usage_hook(settings, "SubagentStop"):
        return [Issue("warning",
                      f"{path} records usage on Stop but not on SubagentStop — add a "
                      '"SubagentStop" entry with the same command '
                      f"(`{_USAGE_HOOK} --hook-stdin`) so every subagent call is counted")]
    return []
```

  In `cli.py` `doctor()`, next to `issues += check_usage_log(kb_dir)`, add `issues += check_usage_hooks(kb_dir.resolve().parent)`.

- [ ] **Step 4: Run.** `uv run pytest -q -k "doctor"`. Expected: PASS.
- [ ] **Step 5: Commit.** `feat(doctor): warn when the SubagentStop usage hook is missing`

---

### Task 10: Docs, CHANGELOG, release 1.9.0

**Files:**
- Modify: `src/strata_kb/templates/init/QUICKSTART-dev.md`, `src/strata_kb/templates/init/QUICKSTART-ba.md`
- Modify: `README.md`, `CHANGELOG.md`, `pyproject.toml`, `uv.lock`

Depends on: Tasks 1–9

- [ ] **Step 1: QUICKSTART-dev.md and QUICKSTART-ba.md** (same edits where the text exists):
  1. Replace "Subagent cost is recorded separately (`sidechain`), so a `dev-execute` run that fans work out to subagents shows where the tokens actually went." with: "Subagent cost is recorded too, as `sidechain`. A `SubagentStop` hook ingests each subagent when it finishes, and the `Stop` hook sweeps any it missed. The report's "Main thread vs subagents" table shows where the tokens went." In the BA file, adapt the matching sentence near line 478.
  2. The backfill paragraph: "Ingesting a main transcript also ingests its subagents (`<session-id>/subagents/`), so the loop below needs no second glob."
  3. Under "must be 0.19.0 or newer", add: "Subagent cost needs 1.9.0: an older `kb` treats a `SubagentStop` payload as another `Stop` and records nothing new."
  4. The manual-merge JSON snippet gains a `"SubagentStop"` array identical to `"Stop"`. Add one line: "`kb doctor` warns when `Stop` is there and `SubagentStop` is not."
  5. One sentence in the report bullet: "A model id with no row in the price table is `unpriced`. Add a row to `.kb/usage-prices.yaml`; it is never priced as its family."

- [ ] **Step 2: README.md.** Under the `kb usage` row of the command table, add a short paragraph in the `kb usage` area:

```markdown
`kb usage` records what each ticket cost from Claude Code's own transcripts,
subagents included (`Stop` + `SubagentStop` hooks, scaffolded by
`kb init --kind ba|dev`). Prices come from a packaged list-price table that a
repo can override per model in `.kb/usage-prices.yaml`; a model with no row
is reported `unpriced`, never guessed. Fast-mode calls are priced at the
standard rate and flagged, so a total that contains them is a lower bound.
```

  If `tests/test_readme.py` pins README claims, run it and add a pin for "subagents included".

- [ ] **Step 3: CHANGELOG.md.** Add at the top:

```markdown
## 1.9.0 — <release date>

- `kb usage` counts subagents. Claude Code writes each subagent's transcript to `<session-id>/subagents/`, which the `Stop` hook never read; a new `SubagentStop` hook ingests each finished subagent, and `Stop` sweeps the folder (holding back each subagent's possibly in-flight last call). On the session measured for the 2026-10-10 review, the hook had seen 33 % of the cost. Existing repos: add the `SubagentStop` hook to `.claude/settings.json` (`kb doctor` says so); until then the `Stop` sweep still records subagents.
- Price table re-verified 2026-10-10: `claude-sonnet-5` is 2/10 (the 3/15 increase did not happen); new rows for `claude-fable-5-1` (cache read 0.25), `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5` (with its over-100k-token tier). Reports on existing ledgers change on the next `kb usage report`.
- A model id with no price row is now `unpriced`; it no longer inherits its family's price. Bare `opus`/`sonnet`/`haiku` aliases point at the 5.5 generation.
- A streamed call is recorded with its largest `output_tokens`, not the first row's partial count. Rows already in a ledger keep their old count; delete the ledger file and re-ingest to correct it.
- Ledger rows record `inference_geo`, `speed`, `service_tier` and web searches. US-only inference (×1.1) and web search (10 USD / 1,000) are priced; fast mode is priced at the standard rate and flagged as a lower bound.
- `kb usage report` leads with the unattributed share of cost.
```

- [ ] **Step 4: Version.** Set `pyproject.toml` `version = "1.9.0"`. In `uv.lock`, change the `[[package]] name = "strata-kb"` entry's `version` to `"1.9.0"` (the same one-line change as 1.8.1).

- [ ] **Step 5: Full verification**

Run: `uv run ruff check . && uv run pytest -q`
Expected: ruff clean; the full suite passes (offline: with a primed `TIKTOKEN_CACHE_DIR`; the 6 environment-only failures listed in review §4.3 are not regressions).

- [ ] **Step 6: Real-session smoke test.** Take a real Claude Code session of this repo that used subagents: `~/.claude/projects/<slug>/<session>.jsonl` with a `<session>/` folder. Then:
  1. `kb init --kind dev` a temp repo.
  2. Run `kb usage ingest-transcript <main.jsonl> --kb-dir <tmp>/.kb`.
  3. Run `kb usage report --md --kb-dir <tmp>/.kb`.

  Confirm the following, and paste the report into the PR's Testing section:
  - The "sidechain" row is non-zero.
  - No row is priced via family.
  - The total ≈ the review's §7.1 figures for a comparable session.

- [ ] **Step 7: Commit.** `docs: subagent usage, price table 2026-10-10 — 1.9.0`
