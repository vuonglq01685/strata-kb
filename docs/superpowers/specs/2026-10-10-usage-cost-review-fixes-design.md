# Usage cost review fixes — count subagents, price the current models, never guess a rate

**Status:** approved design, ready for an implementation plan
**Source:** §7.1 findings #1, #2, #3, #6, #7 and §8 đợt 1 item 1 of
`docs/superpowers/reviews/2026-10-10-full-framework-review.vi.md` (batch 1a
of that review's wave 1).
**Predecessor:** `2026-08-23-kb-usage-measurement-design.md` (the module and
its invariants I1–I5) and `2026-09-15-dev-workflow-usage-review-fixes-design.md`
(the request-level dedup and the first model-id fixes).
**Approach:** as approved on 2026-10-10. Ingest subagent transcripts through a
new `SubagentStop` hook plus a `Stop` sweep that holds back the possibly
in-flight last call. A subagent row's ticket comes from its own cursor, falling
back to the parent session's cursor. An id with no explicit price row is
`unpriced`, with no family fallback. Explicit rows cover the 5.5 / 5.1
generation, and Haiku 5.5 gets its long-context tier. Documented price
modifiers are priced, and fast mode is reported as a lower bound.

## Goal

`kb usage report` is the only answer the framework gives to "what did this
ticket cost". The 2026-10-10 review measured it against a real Claude Code
session and against the official pricing page. The number is wrong in two
directions at once:

- **Subagent cost is missing entirely** (CRITICAL). Claude Code writes each
  subagent's transcript to `<session-id>/subagents/agent-<id>.jsonl`, not into
  the main transcript. The `Stop` hook reads only `transcript_path`, so it
  never sees them. On the measured session the hook saw 29 calls / 6.93 USD of
  ≥ 90 calls / ≥ 20.75 USD, which is 33 %. Every expensive workflow
  (`/kb-summarize` fan-out, `dev-execute` lanes, maturity review, A4/A5) runs
  in subagents. The report's "main vs sidechain" split is always 0, and both
  QUICKSTARTs claim otherwise.
- **The price table is wrong for the current generation** (HIGH).
  `claude-sonnet-5` carries 3/15 while the standard price is 2/10, and a test
  pins the wrong value. `claude-sonnet-5` is also `kb summarize`'s default
  model. `claude-fable-5-1`, `claude-opus-5-5` and `claude-sonnet-5-5` fall
  back to their family row. The overcharge is +25 % to +50 % on input/output,
  ×2.5 to ×4 on cache read. `claude-haiku-5-5` is unpriced, and its two-tier
  price cannot be expressed in `ModelRates`.
- **Smaller defects.** Dedup keeps the *first* transcript row of a call, but
  on a streamed call the first row can carry a partial `output_tokens` (5 vs
  329 measured). Modifiers in the `usage` block (`inference_geo`, `speed`,
  `server_tool_use.web_search_requests`) are ignored, so those calls are
  silently under-priced. A transcript without the nested `cache_creation`
  block records cache write as 0. `_unattributed` share is not surfaced.

After this batch, a report built from a session that used subagents:

1. contains every API call made by the session and its subagents, once each;
2. prices every call at the rate on the pricing page as of 2026-10-10, or
   shows it as `unpriced`, never at a guessed rate;
3. says how much of the total is a lower bound (fast mode) and how much is
   unattributed.

## Verified external facts (2026-10-10)

From `code.claude.com/docs/en/hooks.md` and `sub-agents.md`:

- `SubagentStop` stdin carries `agent_id`, `agent_type`,
  `agent_transcript_path` (the subagent's own JSONL under
  `<session>/subagents/`), and `transcript_path` (the main session's).
- Subagent transcripts are `~/.claude/projects/<slug>/<session-id>/subagents/agent-<agentId>.jsonl`.
  The transcript format is documented as internal and version-dependent.
- The docs do **not** say `Stop` waits for background subagents. The
  `background_tasks` field implies it can fire while one is still running.
  The design assumes it can.

From `platform.claude.com/docs/en/about-claude/pricing` (USD / MTok:
input · output · cache read · cache write 5m · cache write 1h):

| Table key | Rates | Note |
|---|---|---|
| `claude-fable-5-1` | 10 · 50 · **0.25** · 12.5 · 20 | cache read 0.025× input |
| `claude-fable-5` | 10 · 50 · 1.00 · 12.5 · 20 | unchanged |
| `claude-opus-5-5` | 4 · 20 · 0.20 · 5 · 8 | cache read 0.05× input |
| `claude-opus-5` | 5 · 25 · 0.50 · 6.25 · 10 | unchanged |
| `claude-sonnet-5-5` | 2 · 10 · 0.10 · 2.5 · 4 | cache read 0.05× input |
| `claude-sonnet-5` | **2 · 10 · 0.20 · 2.5 · 4** | the promo price became standard; the 3/15 increase "will not occur" |
| `claude-haiku-5-5` | 0.10 · 0.50 · 0.01 · 0.125 · 0.20 | prompt ≤ 100,000 tokens |
| `claude-haiku-5-5` long context | 0.50 · 2.50 · 0.05 · 0.625 · 1 | prompt > 100,000 tokens; "prompt length counts all of its input tokens, including cache reads and cache writes. Each request is priced on its own." |
| `claude-haiku-4-5`, `claude-sonnet-4-6`, `claude-opus-4-6/7/8` | unchanged | |

Modifiers: `inference_geo` US-only ×1.1 on every token category; web search
10 USD per 1,000 searches; batch −50 % (not produced by Claude Code); fast
mode has published input/output rates for Opus only and no published cache
rates.

## Design

### 1. Subagent transcripts are ingested

**`SubagentStop` hook.** `templates/init/claude-settings-usage.json` gains a
`SubagentStop` entry running the same command,
`kb usage ingest-transcript --hook-stdin`, with the same timeout.
`--hook-stdin` dispatches on the payload:

- `agent_transcript_path` present → ingest that file as a **subagent
  transcript**, in full (the subagent has finished, so every call in it is
  complete).
- otherwise → today's behaviour on `transcript_path`, plus the sweep below.

Every failure stays swallowed into `ingest-errors.log`. The exit-0 rule of the
`Stop` branch applies verbatim, because a `SubagentStop` hook exiting non-zero
blocks the subagent from finishing.

**`Stop` sweep.** On a main-transcript ingest, `_usage_ingest` also ingests
every `transcript_path.with_suffix("") / "subagents" / "*.jsonl"`. The sweep
is the safety net for a repo whose `.claude/settings.json` predates this
release (`kb init` never rewrites an existing one) and for a lost
`SubagentStop`. In the sweep, the **last call of each subagent file is held
back**, so it is not emitted. `Stop` can fire while a background subagent is
mid-call. A stored row never changes (I1), so storing a half-written call
would freeze its partial `output_tokens` forever. The held-back call is
picked up by that subagent's `SubagentStop`, or by the next sweep once a
later call follows it. A subagent that dies mid-call and never gets a
`SubagentStop` loses its final call. That is accepted and named in the docs.

The sweep goes through a public helper
`transcript.subagent_transcripts(main: Path) -> list[Path]`, so layout
knowledge lives in one place. When Claude Code moves the folder, one function
changes. The payload path is used whenever it is available.

**Subagent rows.** `rows_from_transcript` gains a keyword
`parent: ParentCursor | None`. `ParentCursor` is a small value holding the
parent transcript's cursor timeline: a list of `(timestamp, ticket, phase)`
change points, built by a pure function over the main transcript with the
same cursor rules as today. For a subagent file:

- `sidechain=True` on every row, regardless of the row's `isSidechain`
  field. The file's location is the authority.
- **ticket** = the subagent's own cursor (same `TICKET_PATH_RE` rules over its
  own rows) once it has seen a ticket. Until then, it is the parent's ticket at
  the subagent's first row timestamp. `forced_ticket` still overrides both.
- **phase** = the parent's phase at the subagent's first row timestamp. A
  subagent's own `Skill` / command markers still switch it, by the same
  rules.

When ingesting a subagent file from `SubagentStop`, the parent cursor is
built from `transcript_path` in the same payload. If the parent cannot be
read, the subagent is still ingested with its own cursor only and the miss is
logged. No call is dropped for want of attribution.

**Backfill.** Manual `kb usage ingest-transcript <path>` accepts either kind
of file. A path matching `*/subagents/agent-*.jsonl` is treated as a subagent
transcript, with its parent at `path.parent.parent.with_suffix(".jsonl")`
when that file exists. Ingesting a main transcript by hand runs the same
sweep, but without holding back the last call: a manual backfill runs after
the session has ended, and the operator is told so in `--help`. The
QUICKSTART backfill loop needs no second glob, because the main file pulls
its subagents.

### 2. One call, the complete row

Dedup still collapses the transcript rows of one call into one ledger row,
keyed on `requestId` → `message.id` → `uuid`, and the row still takes the
**first** row's `uuid` (stable across re-ingests, which global uuid dedup I2
depends on). What changes:

- `tokens_out` = the **maximum** `output_tokens` across the call's rows. The
  other four counts are taken from the row carrying that maximum. They are
  identical across rows in every measured transcript, and a test pins that
  they come from one row, never mixed.
- Emission therefore moves to the end of the file scan, in first-seen order.
  The cursors are unchanged: they still advance on every row in file order,
  and a call's attribution is still read at its first row.
- `cache_write_5m` falls back to top-level `cache_creation_input_tokens` when
  the nested `cache_creation` block is absent. The nested split wins whenever
  present.

Ledgers already on disk keep their rows (I1). The fix reaches them only
through the documented repair, which is deleting the ledger file and
re-ingesting. The CHANGELOG names this.

### 3. Prices: explicit rows only

`templates/usage/usage-prices.yaml`:

- rows per the verified table above; `claude-sonnet-5` corrected;
  `effective_date: "2026-10-10"`;
- the header comment is rewritten. "Standard rates only" stays. The
  point-release fallback paragraph is replaced by "an id with no row here is
  `unpriced` — add a row (here or in `.kb/usage-prices.yaml`) rather than
  letting it inherit a family price; the 5.5 generation shows why";
- `aliases` stay, as explicit entries, pointing at the current generation:
  `opus → claude-opus-5-5`, `sonnet → claude-sonnet-5-5`,
  `haiku → claude-haiku-5-5`.

`prices.resolve_model` drops the `_POINT_RELEASE` loop and becomes exact id,
then alias, else `None`. `Aggregate.priced_as` keeps working for aliases. It
now only ever lists an alias, never a family guess. I5 (unknown model →
`unpriced`, never 0) is untouched and now covers point releases too.

**Long-context tier.** `ModelRates` gains an optional
`long_context: LongContextRates | None` with `threshold: int` plus the same
five rates (`extra="forbid"` on both). `cost_of` computes
`prompt = tokens_in + cache_read + cache_write_5m + cache_write_1h` per row.
When `long_context` is set and `prompt > threshold`, it uses those rates for
the **whole** call. Only `claude-haiku-5-5` sets it today. An override can
set it on any model, merged per model as today.

### 4. Modifiers

`UsageRow` gains four defaulted fields, so older ledgers keep loading:
`inference_geo: str = ""`, `speed: str = ""`, `service_tier: str = ""`,
`web_searches: int = 0`. They are copied from the `usage` block when present
(`server_tool_use.web_search_requests` for the last). Nothing is computed,
so I3 is kept.

`cost_of`:

- `inference_geo` naming US-only inference → token cost × 1.1. The exact
  value strings come from the API's `usage` docs at implementation time, with
  a fixture per value. An unrecognised non-empty value is treated as global
  and counted in the report (see below).
- `web_searches` → + 10 USD per 1,000. The rate comes from the table as a
  top-level `web_search_per_1k: 10.0`, so it can be overridden.
- `speed` marking fast mode → priced at the standard rate and counted as a
  **lower bound**. Fast cache rates are not published, so a fast price would
  be a guess.
- `service_tier` is recorded only. Claude Code does not use batch.

`iterations` / `fallback_credit` are not recorded. The pricing page does not
define them, and recording them invites a guess.

### 5. Report

`Aggregate` gains `lower_bound_rows`, `unknown_modifier_rows` and
`unattributed_pct`. All three renderers (HTML, Markdown, JSON) show, under
the total:

- `Unattributed: N % of cost` (of priced cost; tokens when nothing is priced)
  as a headline line, not only as a bucket further down;
- `N call(s) in fast mode priced at the standard rate — the total is a lower
  bound` when N > 0;
- `N call(s) with an unrecognised modifier` when N > 0;
- the existing `unpriced` and stale-table warnings, unchanged.

### 6. Docs and doctor

- `QUICKSTART-dev.md` and `QUICKSTART-ba.md` (and their PDFs via the usual
  rebuild):
  - the "Subagent cost is recorded separately" sentence becomes true;
  - the manual-merge JSON snippet gains `SubagentStop`;
  - the backfill note says subagents are swept from the main file;
  - the stale "`kb` must be 0.19.0 or newer" becomes the version that ships
    this batch.
- README §"kb usage" (one paragraph): subagent cost is included, unknown ids
  are `unpriced`, and fast mode is a lower bound.
- `kb doctor` on a `ba`/`dev` repo: a warning when `.claude/settings.json`
  has the usage `Stop` hook but no `SubagentStop` hook. The fix line is the
  JSON to merge. It is not an error: the sweep still covers that repo, minus
  in-flight calls.

## Out of scope

- `kb usage merge` across BA + Dev repos and the usage table in the PR body
  (§7.1 #4, #5). These are wave 3 item 11 of the review.
- Re-writing committed ledgers. I1 stands, and the repair is documented.
- Fast-mode cache pricing, until Anthropic publishes it.
- Attribution heuristics beyond the subagent rule (session touching two
  tickets).

## Testing

Unit tests per item, real-shaped fixtures (a main transcript plus a
`subagents/` folder):

- **Subagents.**
  - The sweep finds and ingests subagent files.
  - The sweep holds back exactly the last call per file.
  - `SubagentStop` ingests the full file, including the held-back call, with
    no duplicates against an earlier sweep.
  - Every subagent row is `sidechain=True`.
  - Ticket: own cursor wins; the parent's cursor at the first timestamp is
    used before that; `forced_ticket` beats both.
  - An unreadable parent → ingested with own cursor, error logged, exit 0.
  - A manual path under `subagents/` finds its parent.
  - The hook branch never raises for any malformed `SubagentStop` payload
    (parametrised like the existing `Stop` cases).
- **Dedup.**
  - A two-row call with output 5 then 329 → one row with 329 and the first
    row's uuid.
  - The four other counts come from the max row.
  - Re-ingest is stable.
  - Top-level-only `cache_creation_input_tokens` → `cache_write_5m`.
- **Prices.**
  - Every packaged row equals the verified table.
  - `test_the_packaged_sonnet_5_row_is_the_standard_rate_not_the_promo`
    flips to 2/10 and keeps its name's meaning, since 2/10 *is* now the
    standard.
  - `test_a_point_release_id_falls_back_to_its_family_row` is replaced by
    "a point-release id with no row is unpriced".
  - `test_a_measured_session_prices_to_the_number_we_verified` is unchanged
    (Opus 5 rates did not move).
  - New: every model id appearing in any test fixture transcript has an
    explicit row.
  - Haiku 5.5 at 100,000 vs 100,001 prompt tokens, counting cache tokens.
  - An override can add `long_context`, and misspelt keys raise.
- **Modifiers.** A US-geo row ×1.1, web searches added, a fast row counted as
  lower bound, an unknown modifier counted; old ledger lines without the new
  fields load.
- **Report.** The unattributed %, lower-bound and unknown-modifier lines
  appear in HTML / Markdown / JSON when non-zero and are absent when zero.
- **Doctor.** Warn with a `Stop` hook and no `SubagentStop`; silent with both
  or with neither.

## Delivery

One PR, release **1.9.0** (new hook, new row fields, changed fallback
semantics). The CHANGELOG entry states:

- subagent cost is now counted;
- `claude-sonnet-5` and the 5.5 / 5.1 rows changed, so reports on existing
  ledgers change on the next `kb usage report`;
- point-release ids no longer inherit a family price;
- existing ledgers keep their first-row `output_tokens` until re-ingested;
- existing repos must merge the `SubagentStop` hook by hand (`kb doctor`
  says so).
