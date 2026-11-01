# Strata Quickstart (main hub)

This repo IS the hub. Its `federation/` folder holds the one searchable copy of everything
the organisation publishes, and the hub serves it over HTTP MCP, the REST API and the Web UI.
Nothing a child, BA or Dev repo publishes is searchable until a pull request on this hub
merges. You are that gate.

**Full guide:** https://github.com/vuonglq01685/strata-kb/blob/main/docs/src/guide-hub.en.md
(Tiếng Việt: https://github.com/vuonglq01685/strata-kb/blob/main/docs/src/guide-hub.vi.md)

## Set up (once)

1. **Start the service.** `kb docker-setup` (in your assistant: `/kb-docker-setup`) writes
   `.env` with a fresh `STRATA_KB_HTTP_TOKEN`, adds `.env` to `.gitignore` and runs
   `docker compose up -d`. The Web UI is on port 8321 at `/ui`. Without the helper:
   `cp .env.example .env`, put your own token in it, `docker compose up -d`. Without Docker:
   `python -m strata_kb.mcp --hub . --transport http --host 0.0.0.0` (needs
   `STRATA_KB_HTTP_TOKEN`).
2. **Before you expose it.** The generated token is a convenience: replace it with your own
   secret (32 or more printable ASCII characters). Behind a reverse proxy, set
   `STRATA_KB_TRUSTED_PROXIES` and `STRATA_KB_ALLOWED_HOSTS`. After any change to `.env`:
   `docker compose up -d --force-recreate`.
3. **Create the first admin.** Open the hub in a browser and use `/ui/setup` with the code from
   `docker compose logs hub`, or run
   `docker compose exec hub kb user add <name> --role admin`. **Never commit `.kb-auth/`**
   (accounts). Deleting `.kb-auth/session.key` logs everyone out.
4. **Register the publishers.** Add every repo to `federation/registry.yaml` with a normal
   PR: `owner/repo: repo-id` under `repos:`, or `{repo_id: ..., kind: kb|ba|dev}`. Once the
   file is non-empty the hub is *governed*: unlisted repos cannot publish. `repo-id` must
   exactly match `repo_id:` in that repo's `.kb/config.yaml`. Protect the default branch.
   To accept CI publishes, install a GitHub App on the hub repo (`Contents: Read and write`,
   `Pull requests: Read and write`) and set `STRATA_KB_GH_APP_ID`, `STRATA_KB_GH_APP_KEY`
   and `STRATA_KB_INTAKE_AUDIENCE` on the server.
5. **Give repo owners their settings.** The hub's git URL for `hub:` and the intake URL for
   `intake:` in their `.kb/config.yaml` (**never a token in either**), and the hub's HTTP base
   URL plus the bearer token for `kb mcp-setup`. Tell them whether auto-merge is on for
   their repo.
6. **One version for every repo.** Every repo runs the hub's strata-kb version; `kb doctor`
   syncs it after `kb mcp-setup`.

Optional: asset storage in S3, chained hubs. The guide covers both.

## Daily commands

| Task | Command |
|---|---|
| Review and merge a publish PR | on your Git host; merging is the gate |
| Add or change an account | `docker compose exec hub kb user add <name> --role ba` (also `passwd`, `role`, `remove`, `list`); outside Docker add `--kb <hub>/.kb` |
| Add a repo, switch auto-merge | Registry page (`/ui/registry`, admin only), or a PR on `federation/registry.yaml` |
| Read ticket questions | Q&A menu (`/ui/questions`); the store is `.kb-qa/qa.db`, **never commit `.kb-qa/`** |
| Search | `kb query "your question"`, `kb get <doc> <section>`, `kb tags`, the Web UI |
| Author on the hub itself | `kb ingest source/my-doc.pdf --id my-doc` (`/kb-ingest`), `/kb-summarize`, `kb build`, `/kb-approve`, then `kb publish` (`/kb-publish`); steps in the child guide |
| Check health | `kb doctor`, and `kb reindex` when `federation/index.yaml` drifts |
| Upgrade | `pip install --upgrade strata-kb`, `kb init --kind hub`, `docker compose pull && docker compose up -d`, `kb doctor`; then owners run `kb doctor` |

## Automation

A hub has no `kb auto`. It auto-pulls merged PRs (`STRATA_KB_HUB_PULL_INTERVAL`, default
300 seconds), accepts CI publishes through the intake, can auto-merge a repo's publish PR
(per repo, on the Registry page), and runs the daily code-sync scan in the `hub-sync`
service. Auto-merge merges the whole PR with no review on the hub: turn it on only for repos
you do not need to review here. See the guide's Automation modes section.
