---
name: kb-approve
description: Mark KB sections as reviewed (status summarized → reviewed) after an SME has checked the summaries. Use when asked to approve a document or sections, or when the user invokes /kb-approve.
---

# kb-approve — mark sections as reviewed

Thin wrapper around the `kb approve` CLI. Your job: show what is
approvable, confirm the scope with the user, run the command, relay its
output.

Hard rules:
- NEVER edit `_manifest.yaml` (or any `.kb/` file) by hand to change a
  status — the ONLY way to flip a status is the `kb approve` CLI.
- Approving is an SME judgment call. Do not run `kb approve` unless the
  user explicitly asked to approve, and never enlarge the scope they gave
  (doc/sections) on your own.
- Non-zero exit → show the error verbatim and stop. Do not retry with
  guessed fixes.

## Workflow

1. Run `kb status` and show the user the documents and how many sections
   are still pending vs total. `pending` sections cannot be approved —
   point the user at `/kb-summarize` for those.
2. Confirm the scope: whole doc (`kb approve <doc-id>`), specific
   sections (`kb approve <doc-id> --section <id> --section <id>`), or
   everything changed since a rev
   (`kb approve --all-changed --against <rev>`).
3. Run the command and relay the output: which sections flipped to
   reviewed, which were skipped as pending, any missing-section errors.
4. Remind the user the change is local to `_manifest.yaml` — commit it
   (and `kb publish` when ready) to make it durable.
