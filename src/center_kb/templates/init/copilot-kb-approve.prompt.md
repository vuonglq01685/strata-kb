---
mode: agent
description: Mark KB sections as reviewed (status summarized → reviewed) via the kb approve CLI.
---

# /kb-approve — mark sections as reviewed

Thin wrapper around the `kb approve` CLI. Show what is approvable, confirm
the scope with the user, run the command, relay its output.

Hard rules:
- NEVER edit `_manifest.yaml` (or any `.kb/` file) by hand to change a
  status — the ONLY way to flip a status is the `kb approve` CLI.
- Approving is an SME judgment call. Do not run `kb approve` unless the
  user explicitly asked to approve, and never enlarge the scope they gave.
- Non-zero exit → show the error verbatim and stop.

## Workflow

1. Run `kb status`; show documents with pending vs summarized counts
   (`pending` cannot be approved — use /kb-summarize first).
2. Confirm scope: `kb approve <doc-id>`, or
   `kb approve <doc-id> --section <id>` (repeatable), or
   `kb approve --all-changed --against <rev>`.
3. Run it and relay the output (flipped / skipped-pending / missing).
4. Remind the user to commit `_manifest.yaml` (and `kb publish` when
   ready) to make it durable.
