---
name: kb-ingest
description: Ingest a source PDF into the .kb/ knowledge base. Use when asked to ingest, add, or import a document into the KB, or when the user invokes /kb-ingest with a file name.
---

# KB Ingest — interview first, then run `kb ingest`

You drive the first step of the CENTER-KB pipeline: turning a source PDF
into `.kb/` scaffolding. The CLI does the heavy lifting — your job is to
resolve the file, confirm the metadata with the user, and run the command.

<HARD-RULE>
NEVER run `kb ingest` until the user has explicitly confirmed all three
values: document id, tags, and revision — even when they look obvious from
the file name. If the user already provided some of them, ask only for the
missing ones. "none" is a valid answer for tags and revision.
</HARD-RULE>

## Workflow

1. **Resolve the file.** The argument is a file name (no path needed) —
   look for it in `source/`. If that directory does not exist, list the
   repository root to find the actual source folder before giving up.
   - No argument given → list the PDFs in `source/` and ask which one.
   - File not found → say so, show the files that ARE present, and ask
     again. Never silently pick a different file.
2. **Propose metadata, then ask.** Derive suggestions from the file name:
   - `id`: short, stable, kebab-case (e.g. `ARINC424-22.pdf` → `arinc-424`)
   - `revision`: edition/supplement hints in the name (e.g. `Supplement 22`)
   - `tags`: 2–4 lowercase topical keywords
   Present all three suggestions and ask the user to confirm or correct
   each one. Wait for the answer before doing anything else.
3. **Run the command** (only after confirmation). Docker-first: the
   scaffold ships `docker-compose.yml` and the image bundles the ingest
   extra, so prefer it — no local Python setup needed.
   - **Docker path** — when `docker info` succeeds and
     `docker-compose.yml` exists:
     `docker compose run --rm hub kb ingest source/<file>.pdf --id <id> --tags "<tags>" --revision "<revision>" --no-summarize`
     The container has no LLM CLI, so `--no-summarize` is explicit; fill
     the summaries yourself afterwards (follow the kb-summarize skill),
     then validate with `docker compose run --rm hub kb build`.
   - **Local fallback** — when Docker is not available (daemon down or no
     compose file), use the local CLI (requires
     `pip install "center-kb[ingest]"`), which auto-summarizes as usual:
     `kb ingest source/<file>.pdf --id <id> --tags "<tags>" --revision "<revision>"`
   Omit `--tags` / `--revision` when the user answered "none".
4. **Report the outcome.** Relay the CLI output: number of sections,
   summarize result, `kb build` status.
   - Some sections failed to summarize → tell the user to run
     `kb summarize` (or the kb-summarize skill) and stop.
   - Non-zero exit → show the error output verbatim. Do NOT retry with
     guessed parameters; ask the user how to proceed.
