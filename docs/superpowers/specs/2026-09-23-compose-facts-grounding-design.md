# Compose facts in `-code`, grounding lines the gate checks, and no shell in an AC — Design

**Date:** 2026-09-23
**Status:** Proposed design — not yet implemented
**Builds on:** `docs/superpowers/specs/2026-08-19-dev-agent-design.md` (Phase 5: `kb code-ingest`, `<repo>-code`), `docs/superpowers/specs/2026-08-12-ba-review-agents-design.md` (maturity review), PR #63 (`kb ticket check` verifies `[NEW: D<n>]`), PR #65 (ticket size gates)

## 1. Problem

Field evidence: MyFlix ticket `M-platform-operations-US1` (27 AC, 16 open
questions, `DoR` ticked 2026-09-22) reached `dev-design` and `dev-plan`
and produced 7 + 16 BLOCKER findings over six review rounds, both phases
hitting the round cap. The Dev's own cross-check table, written at the
*Placeholders* step of `dev-implement-ticket` one day after DoR, shows
8 of 27 ACs state a fact about the repo that the repo contradicts:

| AC | Ticket says | Repo has |
|---|---|---|
| AC12 | volumes `myflix-postgres-data`, `-redis-`, `-minio-` (3) | `pgdata`, `redisdata`, `miniodata`, `nginx-cache`, `transcode-scratch` (5) |
| AC14 | `api` healthcheck `curl … /health` | route is `/api/health`; check is `node -e fetch(...)` |
| AC14 | `nginx`, `minio`, `web` healthcheck via `curl` | `wget` (no curl in image), `mc ready local`, no healthcheck |
| AC3 | `minio:9001` bound to `127.0.0.1` | published on all interfaces |
| AC26 | `minio/minio` pinned to `RELEASE.*` | `:latest` |
| AC22 | `.env.example` has 45 vars | 41 |
| AC24 | 14 Prisma tables | 15 models |
| AC26 | 0 compose files under `infra/compose/` | both overrides live there, deliberately |

Three causes, all structural:

1. **`<repo>-code` has no field for what the ticket asked.** `svc.*`
   carries `image`, `ports`, `depends_on`, `env_keys`. It has no
   `volumes`, no `healthcheck`, no `devices`. The SA, who by design has
   no repository access, could not ground AC8/AC12/AC14 and said so in
   the ticket's own closing note.
2. **Uncertainty was moved, not removed.** 16 open questions were closed
   in one day with the label `DECIDED`; 8 of them decided values for
   fields the document lacks. The values went into ACs as if they were
   facts, `Open decisions` became `none`, `kb ticket check` printed
   `Grounding: PASS` (vacuously — `Tables: none`, `Routes: none`, 22
   paths exist), and the BA ticked `Open decisions empty`. Round 4 of
   the maturity review re-derived the score with no reviewer.
3. **ACs were written at the shell-command layer.** 27 ACs embed exact
   `docker compose`, `curl`, `grep`, `psql`, `ffmpeg` invocations. Each
   command authored without a repo to run it in is a guess; the review
   found `{{.State}}` never carries an exit code, a `\|` alternation
   was eaten by markdown, a grep over-matched zod schema keys.

The BA repo and the Dev repo are separate and the SDLC is meant to run
with minimal human hand-offs, so the fix cannot be "the Dev sends the
BA a table". The one automated channel between the repos already exists:
the Dev repo's CI (`kb-code.yml`) runs `kb code-ingest` on every merge
and publishes `<repo>-code` to the hub. The fix is to make that document
carry the facts, make the gate check them, and stop the two habits that
turned guesses into ACs.

## 2. Goals

- The SA can ground volume names, healthcheck commands, and GPU/device
  reservations from `<repo>-code`, deterministically, with no repo access.
- `kb ticket check` fails a `## Technical grounding` line that names a
  volume, healthcheck, or device the service does not have, exactly as it
  already fails an unknown route or column.
- `kb ticket lint` warns on an AC that prescribes a shell command.
- The SA skill no longer has a path from "the document has no field" to
  "a value in an AC": only `[NEW: D<n>]` or `Open decisions`.
- The maturity review cannot raise a score in a round with no reviewer.

## 3. Non-goals

- Heuristic grep of AC prose for compose literals. Every `kb ticket check`
  rule today is deterministic copy-row verification of the SA section;
  a fuzzy AC check would false-positive, get ignored, and cost the gate
  its credibility. AC-vs-grounding consistency stays with the LLM
  reviewer (§7).
- Extracting Dockerfile `configure` flags, shell-script contents, Prisma
  model counts, or framework-prefixed API routes. Those are correctly
  discovered by `dev-design`, the first phase that has the code.
- `restart`, `command`, `user`, or other compose fields not implicated
  by the evidence.
- Backfilling MyFlix's ticket. Re-running `kb code-ingest` there after
  this ships is the verification step (§9), not a deliverable.

## 4. Section 1 — Extractor: three new `svc.*` fields

`ServiceRecord` in `src/strata_kb/codeingest/extractors/services.py`
gains:

```python
volumes: list[str] = field(default_factory=list)   # named volumes only, sorted
healthcheck: str = ""                              # one-line `test`; "" → rendered `none`
devices: list[str] = field(default_factory=list)   # "<driver>:<cap,cap>", sorted
```

Read from the compose `services.<name>` mapping only. Dockerfile-derived
and k8s-derived records leave all three empty; nothing is inferred.

**`volumes`.** Each entry of `volumes:` (short string form `src:dst[:opts]`
or long mapping form with `source`) contributes its source when it is a
named volume: not starting with `.`, `/`, `~`, or `$`, and not containing
`/`. Bind mounts and env-templated sources are dropped. Result is sorted,
de-duplicated.

**`healthcheck`.** From `healthcheck.test`: list form (`["CMD", "curl", …]`
or `["CMD-SHELL", "…"]`) drops the leading `CMD`/`CMD-SHELL` token and
joins the rest with single spaces; string form is taken as is. Passed
through the existing `redact_userinfo` (strips `user:pass@` in URLs).
Truncated to 200 characters with a trailing `…`. `healthcheck.disable:
true` renders `disabled`. No `healthcheck:` key renders `none`. Compose
top-level `x-` anchors merged by YAML are handled by the loader already.

**`devices`.** From `deploy.resources.reservations.devices[]`: each entry
renders `<driver or 'unknown'>:<capabilities joined by ','>`; sorted.
Absent → `[]`, rendered `devices: []` for uniformity with `depends_on`.

Rendering: the three keys are appended to the YAML block `_render_section`
emits, in the order `volumes`, `healthcheck`, `devices`, after `env_keys`.
Determinism holds: same tree, same bytes. Existing documents change on the
next `kb code-ingest` (a new revision), which is the intended trigger for
the SA to re-ground.

Ceiling, deliberate: a healthcheck longer than 200 characters loses its
tail. The tool name and the URL path — the two things the evidence shows
tickets get wrong — sit at the front.

## 5. Section 2 — `## Technical grounding`: three new lines the gate checks

`ticket-template.md` adds, after `- Externals:`:

```
- Volumes: svc.<name> — <volume>, …; svc.<name> — none — or `none`
- Healthchecks: svc.<name> — `<test command>`; svc.<name> — none — or `none`
- Devices: svc.<name> — <driver:caps> — or `none`
```

`kb ticket check` (`src/strata_kb/ticketcheck.py`,
`_check_tables_routes_commands`) adds one branch per line, following the
`Routes:` pattern exactly: parse `svc.<x> — value` pairs, load the svc
section's L2 YAML block, compare.

| Line | Compared against | Error text |
|---|---|---|
| `Volumes:` | `volumes` list | `volume 'myflix-postgres-data' is not in svc.postgres (has: pgdata)` |
| `Healthchecks:` | `healthcheck` string, backticked value must equal it verbatim; `none`/`disabled` must match | `healthcheck for svc.nginx is 'wget -qO- http://localhost/nginx-health', not 'curl -fsS http://localhost/ -o /dev/null'` |
| `Devices:` | `devices` list | `device 'nvidia:gpu' is not in svc.web (has: none)` |

Rules shared with the existing lines:

- A `svc.<x>` on these lines must already be on the `Service:` line;
  otherwise `error: svc.<x> on Volumes: is not on the Service: line`.
- `[NEW: D<n>]` on a value exempts that value (the ticket creates it); the
  marker is judged by the existing `_judge_new` against the parent
  mission's Technology decisions — no new code path.
- A whole-line `none` is valid and is checked: `Volumes: none` while the
  svc has `volumes: [pgdata]` is a **warning** (`svc.postgres has volumes
  the grounding omits: pgdata`), not an error — the ticket may not touch
  them.
- A section written before this change (no such lines) passes: absence of
  the three lines is a **warning** `Volumes:/Healthchecks:/Devices: lines
  missing — re-ground on a -code revision that carries them`, so old
  tickets do not start failing CI.
- Documents whose svc YAML lacks the new keys (generated before this
  release) make the three checks **skip with a note** naming the
  revision, never pass silently, never fail.

`--mission` mode is unchanged: `## Services & order` gets no new columns.

## 6. Section 3 — Lint: an AC is not a shell command

`src/strata_kb/ticketlint.py` adds `_check_ac_shell(ac_items)` beside
`_check_ac_weasel`, emitting **warnings** (the BA judges; DoR requires
them resolved). An AC line triggers when any backticked span:

- starts with a token in `SHELL_COMMANDS = {docker, docker-compose, curl,
  wget, grep, psql, redis-cli, ffmpeg, ffprobe, mc, kubectl, npm, pnpm,
  npx, prisma, ls, cat, find, nvidia-smi, sh, bash}`; or
- contains a shell operator between two words: ` | `, ` && `, ` ; `, ` || `.

Message:

```
AC5 prescribes a shell command (`ffmpeg -f lavfi -i testsrc2=…`) — state the observable outcome here; the command belongs in ## Test data & verification or the Dev's plan — see docs/ac-quality.md
```

Silent when the AC line carries `OPEN(<owner>)` (same exemption as
weasel words). Never triggers on a backticked file name, service name,
env var, or value (`nginx`, `.env.example`, `h264_nvenc`, `POSTGRES_DB`).

`docs/ac-quality.md` gains one row:

| Banned | Write instead |
|---|---|
| a shell command in the AC (`docker compose ps …`, `curl …`, `grep …`) | the observable outcome ("every service reports healthy", "no secret value is committed"); the exact command goes to `## Test data & verification`, or the Dev writes it in the plan where it can be run |

Expected effect on the MyFlix ticket: roughly 20 of 27 ACs warn. That is
the correct count.

## 7. Section 4 — Prompt and rubric rules (no code)

**`sa-ticket-ground`** (`claude-skill-sa-ticket-ground.md` and its
cursor/copilot siblings via `index.yaml`):

- *Load* step: for a ticket, read `volumes`, `healthcheck`, `devices` off
  every `svc.*` the ticket touches.
- *Fill* step: write the three lines of §5 by copying values; a volume or
  device the ticket introduces is `[NEW: D<n>]`.
- New hard rule: *"A value for a field the document does not carry has
  exactly two homes: `[NEW: D<n>]` when the ticket intends to create or
  change it, or `Open decisions` when the document simply cannot prove
  it. It never goes into an AC as a description of the current state.
  `DECIDED` is not a status of this gate — closing an Open decision
  requires a section id or a D-row, nothing else."*

**`ba-ticket-author`**:

- *Draft* step: *"An AC states an observable outcome, never a shell
  command; commands go to `## Test data & verification`. `kb ticket
  lint` warns on the former."*
- *Maturity review* step: *"A round that only closes open questions is
  not a review round and never changes a score. A score rises only when a
  `gap-verifier` (rounds 2–3) or the two reviewers (round 1) record PASS
  on every gap of that axis. Re-deriving a score by hand is forbidden."*

**`review-rubric.md`**, Dev axis, new item at the level that currently
holds "no architecture-blocking open question":

> Every compose-level literal in an AC — volume name, published port and
> bind address, image tag, healthcheck command, device reservation —
> matches the value on the corresponding `## Technical grounding` line, or
> carries `[NEW: D<n>]`. A mismatch is a gap owned by the BA.

**`ticket-template.md`** DoR, last item becomes:

> Technical grounding filled by SA; `kb ticket check` PASS; Open decisions
> empty; no value in an AC rests on a `DECIDED` note instead of a section
> id or a D-row

**`QUICKSTART-ba.md` / `QUICKSTART-dev.md`**: one paragraph each on the
new lines and the lint warning. The Dev guide notes that `kb code-ingest`
must run once (CI does it on the next merge) before the SA sees the new
fields.

## 8. Data flow after the change

```
Dev repo merge → CI kb code-ingest → svc.* {volumes, healthcheck, devices} → hub <repo>-code @ rN
BA repo: ba-ticket-author drafts outcome-level ACs (lint warns on shell)
       → sa-ticket-ground copies Volumes/Healthchecks/Devices from rN, or [NEW: D<n>], or Open decisions
       → kb ticket check verifies the copies against rN
       → maturity review: reviewer confirms AC literals == grounding
       → DoR
Dev repo: dev-design finds only what -code cannot carry (script contents, prefixed routes)
```

No step requires a human to carry an artefact between repos.

## 9. Testing

- `tests/test_codeingest_extractors.py`: one compose fixture with a
  named volume, a bind mount, a `${VAR}` source, a long-form volume
  mapping; healthcheck in list form with `CMD`, list form with
  `CMD-SHELL`, string form, `disable: true`, and absent; devices with
  `driver: nvidia` + two capabilities, and absent. Assert the rendered
  YAML keys, ordering, `none`/`disabled`, sort order, the 200-char cut,
  and byte-identical output across two runs.
- `tests/test_ticketcheck.py`: grounding with the three lines — PASS on
  exact copy; `[error]` on each mismatch with the exact message shape;
  `[NEW: D<n>]` exempted and still judged against the mission table;
  `none` valid; `none` while the svc has volumes → warning; lines absent →
  warning; svc YAML without the keys → skip note.
- `tests/test_ticketlint.py`: `docker compose up` warns; `curl …` warns;
  pipe between words warns; `` `nginx` `` and `` `.env.example` `` do
  not; `OPEN(BA)` line silent; message names the AC id.
- `tests/test_templates.py`: template, both skills, rubric, ac-quality,
  quickstarts contain the new strings; `index.yaml` still maps every
  wrapper.
- Manual verification, recorded in the PR: re-run `kb code-ingest` on
  the MyFlix checkout, confirm `svc.postgres` shows `volumes: [pgdata]`
  and `svc.web` shows `healthcheck: none`; run `kb ticket check` on
  `M-platform-operations-US1.md` with a `Volumes:` line copied from the
  ticket's AC12 values and see the `myflix-postgres-data` error.

## 10. Rollout

One release (`1.3.0`). Changelog names the three new svc keys, the three
grounding lines, the lint warning, and the SA/BA rule changes. Existing
`-code` documents keep working (§5 skip/warning behaviour) until their
repo's next merge regenerates them. Existing tickets keep passing `check`
(missing lines are a warning). Existing tickets with shell in ACs start
warning on `lint` — by design.

## 11. Open items

None. Every value in this document is fixed; anything not listed is out
of scope (§3).
