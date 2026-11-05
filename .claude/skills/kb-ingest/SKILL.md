---
name: kb-ingest
description: Ingest a source PDF or Markdown file into the .kb/ knowledge base. Use when asked to ingest, add, or import a document into the KB, or when the user invokes /kb-ingest with a file name.
---

# KB Ingest — interview first, then run `kb ingest`

You drive the first step of the Strata pipeline: turning a source PDF or Markdown
file into `.kb/` scaffolding. The CLI does the heavy lifting — your job is to
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
   - No argument given → list the PDF and Markdown (`.md`, `.markdown`) files in `source/` and ask which one.
   - File not found → say so, show the files that ARE present, and ask
     again. Never silently pick a different file.
2. **Propose metadata, then ask.** Derive suggestions from the file name:
   - `id`: short, stable, kebab-case (e.g. `employee-handbook.pdf` → `hr-handbook`)
   - `revision`: edition hints in the name (e.g. `2026 edition`)
   - `tags`: 2–4 lowercase topical keywords
   Present all three suggestions and ask the user to confirm or correct
   each one. Wait for the answer before doing anything else.
3. **Run the command** (only after confirmation). Docker-first: the
   scaffold ships `docker-compose.yml` and the image bundles the ingest
   extra, so prefer it — no local Python setup needed.
   - **Docker path** — when `docker info` succeeds and
     `docker-compose.yml` exists:
     `docker compose run --rm hub kb ingest source/<file>.<pdf|md> --id <id> --tags "<tags>" --revision "<revision>" --no-summarize`
     The container has no LLM CLI, so `--no-summarize` is explicit; fill
     the summaries yourself afterwards (follow the kb-summarize skill).
     If `.kb/config.yaml` has `l3_fix: enabled: true`, fill them only after the
     user has run `kb l3 confirm` (step 4); `kb summarize --print-prompt`
     refuses a document still awaiting L3 review.
     Then validate with `docker compose run --rm hub kb build`.
   - **Local fallback** — when Docker is not available (daemon down or no
     compose file), use the local CLI (requires
     `pip install "strata-kb[ingest]"`), which auto-summarizes as usual:
     `kb ingest source/<file>.<pdf|md> --id <id> --tags "<tags>" --revision "<revision>"`
   Omit `--tags` / `--revision` when the user answered "none".
4. **Review the L3 check.** If `.kb/config.yaml` has
   `l3_fix: enabled: true`, first run the kb-l3-fix skill (Claude Code `/kb-l3-fix`,
   Copilot `#kb-l3-fix`, Cursor `/kb-l3-fix`) on this document, then
   continue. `kb ingest` compares L3 with the source and
   flags suspect sections (wrong order, fallback ids, broken paragraphs,
   text that differs from the source) in `.kb/<id>/_l3check.yaml`. When the
   output says `Summarize skipped until the L3 review is confirmed`:
   run `kb l3 report <id>` and show the user every flagged section with
   its evidence and agent verdict. Only the user confirms: after they
   have checked a section, run `kb l3 confirm <id> --section <section-id>`
   (repeatable), or `--all --yes` when they say every flag is fine (their answer is the
   confirmation; without `--yes` the prompt aborts in an agent shell). Never
   confirm on your own, and never edit L3 directly; with L3 fix on, propose
   drafts through kb-l3-fix. Then run
   `kb summarize` (or follow the summarize step) — with `l3_fix` on, only
   after the user has run `kb l3 confirm` for every section that
   `kb l3 report <id>` lists; `kb summarize --print-prompt` refuses a
   document still awaiting review. With Docker, prefix the
   commands with `docker compose run --rm hub`.
   **Markdown source** (`.md` / `.markdown`): needs no ingest extra. The rules
   rewrite only heading lines into `## <id> <title>`; every other byte reaches
   L3 unchanged. Local `.png` / `.webp` images inside the source folder are
   copied to `.kb/<id>/assets/<sha256>.<ext>` and their links rewritten;
   other images stay as written, with a warning. The command refuses a file
   whose fenced code or HTML block holds a `## ` / `### ` line (it lists the
   line numbers: move it out or indent it), and an id used for the other kind
   (`'<id>' was ingested from a PDF — ingest the Markdown under a new --id`,
   and the reverse). The source Markdown is the master: to change the text,
   edit it and re-ingest; re-ingest resets the AI-fix record, so run
   kb-l3-fix again and have the user confirm again. `kb authored <id>` still
   freezes a document. No page images exist for it: `kb l3 fix pages` and
   `--from-image` refuse with `source is Markdown: no page images`.
5. **Report the outcome.** Relay the CLI output: number of sections,
   summarize result, `kb build` status.
   - Some sections failed to summarize → tell the user to run
     `kb summarize` (or the kb-summarize skill) and stop.
   - Non-zero exit → show the error output verbatim. Do NOT retry with
     guessed parameters; ask the user how to proceed.
