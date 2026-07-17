---
name: kb-init
description: Guided setup for a CENTER-KB repo — choose the repo role (hub or child) and, for hubs, the asset storage mode, then scaffold and verify. Use when asked to set up or initialize a KB repo, or when the user invokes /kb-init.
---

# kb-init — guided repo setup

Thin wrapper around the `kb init` CLI. Your job: ask the two setup
questions, run the command, relay next steps, verify with `kb doctor`.

Hard rules:
- The ONLY way to scaffold is the `kb init` CLI — never hand-write
  `.kb/config.yaml` or template files.
- Never change an already-recorded kind or an existing `asset_store:`
  block; `kb init` refuses, and so should you.
- Non-zero exit → show the error verbatim and stop.

## Workflow

1. **Role** — ask which role this repo plays:
   - **hub** — aggregation + read/search server: hosts `federation/`,
     serves `/ui` + `/api` + `/mcp`, receives publishes, owns asset storage.
   - **child** — authoring repo: ingests PDFs, summarizes, publishes
     snapshots to the hub. Never configures asset storage.
   (Skip the question if `.kb/config.yaml` already records `kind:` — say so.)

2. **Assets mode** (hub only) — ask which storage mode:
   - **none** (recommended first run) — image assets stay in git; zero
     cloud setup. Fine for a compressed corpus; `kb doctor` warns if it
     outgrows plain git.
   - **s3** — assets go to an object store (AWS S3, MinIO, R2). Needs a
     private bucket and credentials in the environment.

3. **Run** `kb init --kind <role>` (add `--assets <mode>` for a hub) and
   relay its output.

4. **Next steps** — relay the CLI's own next-steps list. For `--assets s3`
   additionally walk the operator through: fill `bucket` (+ `endpoint` for
   MinIO/R2) in `.kb/config.yaml`, export credentials (AWS env chain),
   `pip install "center-kb[s3]"`.

5. **Verify** — run `kb doctor` and relay the result. For s3 it probes the
   bucket; expect `kb doctor: OK` before calling setup done. If assets
   already exist in git, mention `kb assets migrate`.
