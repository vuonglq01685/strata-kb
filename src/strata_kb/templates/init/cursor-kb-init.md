---
name: kb-init
description: Guided setup for a Strata repo — choose the repo role (hub or child) and, for hubs, the asset storage mode, via the kb init CLI.
---

# /kb-init — guided repo setup

Thin wrapper around the `kb init` CLI. Ask the two setup questions, run
the command, relay next steps, verify with `kb doctor`.

Hard rules:
- The ONLY way to scaffold is the `kb init` CLI — never hand-write
  `.kb/config.yaml` or template files.
- Never change an already-recorded kind or an existing `asset_store:`
  block; `kb init` refuses, and so should you.
- Non-zero exit → show the error verbatim and stop.

## Workflow

1. **Role** — ask hub vs child:
   - **hub** — aggregation + read/search server (`federation/`, `/ui` +
     `/api` + `/mcp`, receives publishes, owns asset storage).
   - **child** — authoring repo: ingest, summarize, publish to the hub;
     never configures asset storage.
   (Skip if `.kb/config.yaml` already records `kind:` — say so.)
2. **Assets mode** (hub only): **none** (recommended first run, zero
   cloud setup) or **s3** (needs a private bucket + credentials in the
   environment).
3. Run `kb init --kind <role>` (add `--assets <mode>` for a hub); relay
   its output.
4. Relay the CLI's next-steps list. For `--assets s3` also walk through:
   fill `bucket`/`endpoint` in `.kb/config.yaml`, export credentials,
   `pip install "strata-kb[s3]"`.
5. Run `kb doctor` and relay the result (s3 probes the bucket; expect
   `kb doctor: OK`). Existing git assets → mention `kb assets migrate`.
