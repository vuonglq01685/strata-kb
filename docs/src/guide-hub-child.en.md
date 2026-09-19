# 1. Who this guide is for

You own knowledge, or you produce it.

- A **hub** is the place your organisation's knowledge lives and is searched. If
  you run the hub, you operate the service everyone else reads from, and you are
  the last gate before anything becomes findable.
- A **child** is an authoring repository. If you work in one, you bring documents
  in, get them summarized, check them, and publish them to the hub.

Both roles use the same commands and the same four-layer model, so they are
covered together. Where a step applies to only one, it says so.

You do not need to read the architecture document first. You do need to
understand one rule before anything else:

> **Nothing you author is searchable until a pull request on the hub merges.**
> Your local store is a drafting desk. The hub is the published world.

---

# 2. Install

```bash
pip install "strata-kb[ingest]"
kb --help
```

The `ingest` extra brings the PDF pipeline. Without it every other command still
works — useful on a machine that only queries or publishes.

**Requirements.** Python 3.11 or newer, and Git. If your hub URL carries a
credential (the `https://x-access-token:…@github.com/...` shape), you need **Git
2.31 or newer** on every machine and every CI runner. Older Git silently ignores
the mechanism that keeps the token out of the clone's config, and every hub
command fails with an authentication error. Debian 11 and Ubuntu 20.04 ship
below that floor.

Prefer Docker? `kb docker-setup` handles it; see section 9.

---

# 3. Create the repository

```bash
mkdir my-kb && cd my-kb && git init
kb init            # interactive: it asks which kind
kb init --kind hub # or non-interactive
```

`kb init` scaffolds for the kind you choose and records it in `.kb/config.yaml`.
Re-running it later refreshes skills, templates and workflows while preserving
your data — pass `--force` only if you really want the data files reset too.

## 3.1 Hub configuration

```yaml
# .kb/config.yaml on the hub
kind: hub
repo_id: ops              # this hub's own entry id, if it authors content
asset_store:
  mode: none              # or: {mode: s3, bucket: my-kb-assets}
```

## 3.2 Child configuration

```yaml
# .kb/config.yaml on a child
kind: child
repo_id: safety           # your entry id under federation/
hub: https://github.com/acme/kb-hub.git
```

`repo_id` becomes the prefix in every citation this repository produces
(`safety:handbook §4.2`), so choose something short and durable. Changing it
later orphans the old entry on the hub.

> **Keep credentials out of `config.yaml` where you can.** A `hub:` URL with a
> token in it works, but prefer ssh (`git@github.com:acme/kb-hub.git`) or a
> public https URL on workstations, and keep the credentialed form for CI.

---

# 4. Bring a document in

```bash
kb ingest sources/employee-handbook.pdf \
  --id hr-handbook \
  --tags hr,policy,benefits \
  --revision "2026 edition"
```

| Flag | What it does | Advice |
|---|---|---|
| `--id` | The document's permanent id | Short, lowercase, hyphenated. It appears in every citation forever. |
| `--tags` | Labels used to pre-filter search | 2–5 tags. Think about how someone would narrow a search, not how you would file the document. |
| `--revision` | Edition label | Always set it. It appears in every citation and is how a reader knows which edition an answer came from. |
| `--sections` | Restrict to certain chapters | Use it for a first trial run on a long document. |
| `--no-bookmarks` | Split by heading pattern instead of the PDF outline | Only if the outline is missing or wrong. |
| `--no-summarize` | Skip the automatic summarize pass | When you want to inspect the split before spending model calls. |

## 4.1 Where source files go

Source PDFs are usually licensed or confidential. They live in `sources/`, which
the scaffolding configures Git to ignore. **Do not commit them.** The knowledge
base carries the extracted text under your own control; the source stays where
it legally belongs.

## 4.2 What ingestion produces

```
.kb/hr-handbook/
├── _manifest.yaml               L1 — every section, all "pending"
├── ch4-benefits.md              L2 — tables in place, prose blank
├── ch4-benefits.raw.md          L3 — the full original
└── assets/<sha256>.webp         figures, stored once each
```

The first run on any machine downloads a page-layout model (~500 MB) and caches
it, so it is slow once and fast afterwards.

## 4.3 Read the ingest report

The report is not decoration. It names every judgement call the splitter made:
headings it demoted to ordinary text, ids it had to invent, numbered headings
that arrived out of order, duplicate ids it renamed, bookmarks it could not
match, and the distribution of section sizes.

Skim it before moving on. A document that produced many fallback ids or many
out-of-order headings is usually a document whose outline needs
`--no-bookmarks` and a heading pattern instead.

## 4.4 Re-ingesting

- **Whole document** (no `--sections`): a full replace. Every Markdown file of
  that document is deleted and rewritten — including summaries you have already
  reviewed.
- **One chapter** (`--sections 6`): only that chapter's files and manifest
  entries are rewritten. Everything else, including reviewed summaries and their
  status, is untouched.
- A `--sections` value that matches no heading **deletes** that chapter. The
  report says so explicitly; read it rather than assume.

---

# 5. Summarize

This is the only step a model touches.

`kb ingest` runs it automatically, calling a headless LLM CLI it finds on your
`PATH` (`claude`, then `copilot`). You can pin one with `--llm`, or skip it with
`--no-summarize`.

```bash
kb status                   # what is still pending
kb summarize hr-handbook    # run or retry
```

If no LLM CLI is installed, sections simply stay `pending`. Open your coding
agent and run `/kb-summarize` instead — it reads `kb status`, fans the pending
sections out to parallel read-only sub-agents, and merges their output under the
same rules.

## 5.1 The rules the model is held to

| Rule | Why |
|---|---|
| Write in the source document's language | A summary in another language shares no vocabulary with its original, and keyword search stops matching it |
| Never rephrase codes, field names, numbers, units or cross-references | These are the content people look the document up *for* |
| Never touch tables | Tables are machine-copied and automatically verified; a model editing one is a build failure |
| Prefer the original wording over invention | An unhelpful-but-faithful summary is recoverable; a confident wrong one is not |

## 5.2 Re-running

```bash
kb summarize hr-handbook --redo --section 4.12       # one section
kb summarize hr-handbook --redo --dry-run            # see the plan first
kb summarize --redo --all                            # the whole store
kb summarize hr-handbook --print-prompt --section 4.12
```

`--redo` skips sections a human has already reviewed unless you add
`--include-reviewed --yes`. Sections with very little prose are copied verbatim
without a model call at all.

---

# 6. Check the work

```bash
kb build
```

```
kb build: OK
```

```
[error] hr-handbook §4.12: L2 table does not match L3 table
```

`kb build` runs three checks:

1. **Nothing left blank.** No `TODO` markers, no empty summaries.
2. **Every table matches its original**, in both directions. This is the one
   check that cannot be waived.
3. **Quality rules** — summary length relative to the original, no sentence that
   merely transcribes its own table, no invented uppercase codes, sufficient
   vocabulary overlap with the original, L1 within 25 words, L0 within 30. These
   are warnings by default; `--strict` makes them errors.

It also fails if an original changed after its summary was written, or a summary
changed after it was approved. And it never writes the manifest while reporting
an error, so a failed build leaves nothing half-updated.

```bash
kb build --allow-pending   # validate finished work while the rest is in progress
kb build --strict          # what `kb approve` requires
```

## 6.1 Fixing a table mismatch

Open the section's `.raw.md` (L3), copy the table exactly, and paste it over the
one in the `.md` (L2). Do not retype it, and do not reformat it — the comparison
tolerates alignment and whitespace, nothing else.

---

# 7. Approve (optional but recommended)

```bash
kb approve hr-handbook
kb approve hr-handbook --by "Jane Smith <jane@acme.com>"
```

`kb approve` requires a clean working tree for that document and a passing
`kb build --strict`. It records who approved each section and when, plus a hash
of the summary they approved — so a later edit to an approved summary is
detected rather than assumed benign.

Approval is a human act and is never automatic. The hub pull request remains the
gate that actually controls publication; approval is how you mark per-section
expert sign-off inside it.

---

# 8. Review a change

If you are reviewing rather than authoring, this is your whole job. No commands
— read the diff.

- [ ] **Read the new prose** — the `.md` files, not `.raw.md`. Does it match your
      understanding of the subject?
- [ ] **Compare against the source.** Anything important omitted? Anything
      present that is not in the original?
- [ ] **Check every code, identifier, number and unit.** They must be exactly as
      in the source.
- [ ] **Tables** — you do not need to verify them line by line; the build already
      did, and would have blocked the PR. Do glance for *extraction* errors: a
      row or column the PDF reader misread. A machine cannot catch that.
- [ ] **The one-line summaries in `_manifest.yaml`.** Do they say what the
      section is about, well enough that someone searching would find it?
- [ ] Wrong? Edit the `.md` or `.yaml` directly in the web UI, or comment and ask
      the author.

Merging this pull request is the expert sign-off. It still does not publish
anything.

---

# 9. Publish

```bash
kb publish            # picks the right mode
kb publish --pr       # explicit: open or update a pull request on the hub
kb publish --direct   # explicit: commit straight to the hub
```

Publishing mirrors your whole store (all four layers) into
`federation/<repo-id>/` on the hub and rebuilds the hub's aggregate index.

| Mode | When you want it |
|---|---|
| `--pr` | Normal. Needs a git remote and a `gh` that can open a PR on that host. |
| `--direct` | A purely local hub — a directory on disk with no remote. Refused on a governed hub that has a remote. |
| Neither flag | Direct only for a hub with no remote; otherwise a PR, or a clear refusal. |

**Only artefacts are published.** Documents, indexes, manifests and assets go;
configuration files and dotfiles stay behind and are named in a warning. That is
deliberate: your `hub:` setting may contain a token, and mirroring it would
publish a credential.

> If `kb doctor` on the hub names files inside an entry that a publish would
> never write, an older tool version put them there. Publish again to strip
> them, and **rotate anything secret they contained** — removing a file does not
> remove it from Git history.

## 9.1 Publishing from CI

The scaffolded `kb-publish.yml` runs `kb ci-publish` from your own GitHub Actions
job. It authenticates to the hub's intake service with GitHub Actions OIDC, so
there is no long-lived secret to store or rotate. `kb publish` creates and pushes
the tag that triggers it.

## 9.2 When a publish is refused

| Message | What to do |
|---|---|
| `gh` cannot open a pull request | Install and authenticate `gh` for that host (`GH_HOST=<host>` for Enterprise) until `gh repo view` works inside the hub clone |
| direct push refused on a governed hub | Use `--pr`, or `kb ci-publish` from CI. The refusal is the governance working. |
| `federation cycle detected` | A hub chain would loop content back to itself. Check `hub:` on each hub in the chain. |
| authentication error on every hub command | Check `git --version` — below 2.31 with a credentialed hub URL, nothing will work |

---

# 10. Running the hub service

One process serves agents, programs and people.

```bash
STRATA_KB_HTTP_TOKEN=<secret> \
  python -m strata_kb.mcp --hub . --transport http
```

| Surface | For | Auth |
|---|---|---|
| `http://host:8321/mcp` | AI agents | Bearer token |
| `http://host:8321/api/…` | scripts and integrations | Bearer token or cookie |
| `http://host:8321/ui` | people | sign in with the token |

A hub is mandatory; the server refuses to start without one and searches only
`federation/` — never its own working `.kb/`.

## 10.1 Docker

```bash
kb docker-setup       # hub: writes .env, generates a token, starts the service
docker compose up -d
docker compose run --rm hub kb ingest source/handbook.pdf --id hr-handbook
```

On a child, `kb docker-setup` pulls the ingest image so ingestion needs no local
Python at all.

## 10.2 Before you expose it

- **Replace the generated token.** `kb docker-setup` generates one for
  convenience. Treat it as a placeholder.
- **Set the trusted-proxy count if you are behind a reverse proxy.** The default
  ignores forwarded headers. Left unset behind a proxy, every caller looks like
  the proxy, and one caller can exhaust the rate limiters for everyone.
- **Know the limit.** Authentication is a single bearer token — no OAuth, no SSO.
  That is fine on an internal network and not ready for the public internet.

Full deployment guide: `docs/deploy-remote-mcp.md`.

---

# 11. Searching

```bash
kb query "parental leave eligibility"
kb query "parental leave" --tags hr --budget 600
kb get hr-handbook 4.12 --level l2
kb get hr-handbook 4.12 --level l3
kb tags
```

| Flag | Effect |
|---|---|
| `--tags` | Restrict to documents carrying those tags. A document id works as a tag too. |
| `--budget` | Token ceiling. Advisory — the first result always comes back whole, and sections are never cut mid-way. |
| `--semantic` | Force the semantic leg; warns if embeddings are not installed |

Every result cites `<repo-id>:<doc-id> §<section> (<revision>)`, so you always
know which repository, document and edition answered.

Query in the document's own language. The store never translates, so an English
query against a Vietnamese document will match little.

---

# 12. Keeping the hub healthy

```bash
kb doctor      # structural health; exits non-zero on a real problem
kb reindex     # rebuild federation/index.yaml when it has drifted
kb stats       # token size per layer, per document
```

`kb doctor` reports broken contents, manifest and file disagreements, content
modified directly on the hub rather than through a publish, files a publish would
never have written, a hub clone storing a credential in its own Git config, and a
Git older than the 2.31 floor.

Run it after an upgrade and before a first publish following one. A store that
was green can go red on upgrade with nothing having changed on disk — the checks
got stricter, and the message tells you which command fixes it.

---

# 13. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `kb build`: table mismatch | A table was edited, added, duplicated or reordered in the summary | Copy the table verbatim from `.raw.md` over the one in `.md` |
| `kb build`: sections still pending | Summarization did not finish or was skipped | `kb status`, then `kb summarize`; or `/kb-summarize` with no LLM CLI |
| `kb build`: "L3 changed after summarization" | The document was re-ingested under an existing summary | Re-run `kb summarize` for the affected sections |
| First `kb ingest` takes 10–30 minutes | The layout model is downloading | Wait once; later runs use the cache |
| `kb: command not found` | Virtualenv not active | `source .venv/bin/activate` |
| `kb query` returns nothing | No tag or content match, or the budget is too small | Drop `--tags`, raise `--budget`, and query in the document's language |
| Query returns nothing after a merge | Merged on your repo, not yet on the hub | `kb publish`, then merge the hub PR |
| Every hub command fails on auth | Git older than 2.31 with a credentialed hub URL | Upgrade Git, or use an ssh hub URL |
| MCP server will not start: `python` not found | The client config calls `python`, your system has only `python3` | Point the command at an absolute interpreter path |

---

# 14. Command summary

| Command | Purpose |
|---|---|
| `kb init [--kind hub\|child]` | Create or refresh the repository |
| `kb docker-setup` | Prepare Docker: hub starts the service, child pulls the image |
| `kb ingest <pdf> --id <id>` | Split a document, write L3, scaffold L1/L2 |
| `kb status` | What is still pending |
| `kb summarize <doc>` | Fill or re-fill summaries |
| `kb build [--strict] [--allow-pending]` | Validate the store |
| `kb approve <doc>` | Record expert sign-off per section |
| `kb publish [--pr\|--direct]` | Mirror to the hub |
| `kb query <text>` | Search the hub |
| `kb get <doc> <section>` | Fetch one section |
| `kb tags` | List published tags |
| `kb stats` | Token size per layer |
| `kb doctor` | Health check |
| `kb reindex` | Rebuild the aggregate index |

**Exit codes:** `0` success, `1` error or misconfiguration, `2` a citation (or the
hub cache) is stale.
