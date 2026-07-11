---
mode: agent
description: Ingest a source PDF into the .kb/ knowledge base — interview for id/tags/revision, then run kb ingest
---

# /kb-ingest — ingest a PDF into CENTER-KB

Turn a source PDF into `.kb/` scaffolding via the `kb ingest` CLI. Your
job: resolve the file, confirm metadata with the user, run the command.

NEVER run `kb ingest` until the user has explicitly confirmed all three
values: document id, tags, and revision — even when they look obvious from
the file name. If the user already provided some of them, ask only for the
missing ones. "none" is a valid answer for tags and revision.

## Workflow

1. **Resolve the file.** The argument is a file name — look for it in
   `source/`. If that directory does not exist, list the repository root
   to find the actual source folder before giving up.
   - No argument given → list the PDFs in `source/` and ask which one.
   - File not found → say so, show the files that ARE present, and ask
     again. Never silently pick a different file.
2. **Propose metadata, then ask.** Derive suggestions from the file name:
   - `id`: short, stable, kebab-case (e.g. `ARINC424-22.pdf` → `arinc-424`)
   - `revision`: edition/supplement hints in the name (e.g. `Supplement 22`)
   - `tags`: 2–4 lowercase topical keywords
   Present all three suggestions and ask the user to confirm or correct
   each one. Wait for the answer before doing anything else.
3. **Run the command** (only after confirmation):
   `kb ingest source/<file>.pdf --id <id> --tags "<tags>" --revision "<revision>"`
   Omit `--tags` / `--revision` when the user answered "none".
4. **Report the outcome.** Relay the CLI output: number of sections,
   summarize result, `kb build` status.
   - Some sections failed to summarize → tell the user to run
     `kb summarize` and stop.
   - Non-zero exit → show the error output verbatim. Do NOT retry with
     guessed parameters; ask the user how to proceed.
