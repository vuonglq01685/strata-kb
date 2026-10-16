---
name: kb-publish
description: Review and publish the local KB to the federation hub — diff vs the published snapshot, confirm, then kb publish (PR on the hub). Use when asked to publish the KB or push knowledge to the hub.
---

# KB Publish — diff → confirm → publish (PR on the hub)

The hub federation is the single source of truth: content is searchable only
after the publish PR is merged on the hub. Local `.kb/` is just a drafting desk.

<HARD-RULE>
NEVER run `kb publish` until the user has explicitly confirmed, after
seeing the diff, that the current .kb/ state should be published.
</HARD-RULE>

## Workflow

1. **Check state.** Run `kb status`. If any section is still `pending`,
   stop and tell the user to summarize first (`kb summarize`, or the
   kb-summarize skill).
2. **Show what will be published.** Run `kb doctor` — it reports whether
   local .kb differs from the published snapshot. In a `ba` or `dev` repo
   it asks the hub over MCP (`kb mcp-setup`), never a hub clone. If it
   cannot reach the hub, stop: the user runs `kb mcp-setup` (in a cloud
   session: sets `STRATA_KB_HUB_URL` and `STRATA_KB_HTTP_TOKEN` in the
   environment, since `.env` is not committed), then publish again. For each doc with
   changes, run `kb diff <doc-id> --against HEAD` (use another git rev if
   the user names one) and present the added/changed sections.
   In a `ba` repo, `kb publish` first regenerates `<repo_id>-plan` with
   `kb plan-ingest`; run `kb plan-ingest` to see what will ship and what is
   skipped (`kb doctor` does not diff `-plan`). Both `.kb/<repo_id>-plan/` and `.kb/index.yaml` are generated
   and gitignored there.
3. **Confirm — the gate.** State where it goes. With `intake:` in `.kb/config.yaml`,
   `kb publish` pushes a `kb-publish/*` tag, CI uploads to that intake URL
   and the hub opens the PR: no hub clone and no `hub:` needed. In a `ba`
   repo a push to `main` that changes `missions/` or `tickets/` also
   publishes (`kb-publish-request.yml` tags the merged commit), so a
   merged PR needs no `kb publish`. Otherwise
   state the hub (from `.kb/config.yaml`, or `STRATA_KB_HUB` if set) and
   that a publish PR will be opened on it (direct is picked for a hub with
   no git remote). Also state the repo's kind
   and the hub menu it lands in, as `kb publish` prints it:
   `kind: <hub kind> → hub menu: <Document|Ticket|Code>` (`hub` and `child`
   repos → Document, `ba` → Ticket, `dev` → Code). Read the kind from
   `kind:` in `.kb/config.yaml`, or the `[info] kind: …` line `kb doctor`
   prints. If the kind is unrecorded, stop: tell the user to run `kb init --kind <child|ba|dev|hub>`
   first. Ask for one explicit go/no-go and wait.
4. **Execute** (only after confirmation): `kb publish`. Relay the result:
   the `kind: … → hub menu: …` line, repo-id, source commit, doc count, and the **PR URL** — remind the user
   the content goes live when that PR is merged on the hub.
5. **Errors.**
   - Kind unrecorded (message mentions `kb init --kind`) → stop; the user
     runs `kb init --kind <child|ba|dev|hub>`, then publishes again.
   - Missing hub config (only without `intake:`) → tell the user to fill
     `hub:` in `.kb/config.yaml`; a ba/dev repo whose people cannot clone
     the hub sets `intake:` instead.
   - `gh` missing in PR mode → install GitHub CLI, or `kb publish --direct`
     only if direct pushes are allowed for this hub.
   - Tag push refused (e.g. HTTP 403 where only the branch may be pushed,
     as in a cloud session) in a `ba` repo → nothing was published; merge
     the change into `main`, which publishes it, or run
     `kb-publish-request.yml` by hand on `main`.
   - Other git/hub errors → show the stderr and suggest `kb doctor`.
