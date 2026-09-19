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
   local .kb differs from the published snapshot. For each doc with
   changes, run `kb diff <doc-id> --against HEAD` (use another git rev if
   the user names one) and present the added/changed sections.
3. **Confirm — the gate.** State the hub (from `.kb/config.yaml`, or
   `CENTER_KB_HUB` if set) and that a publish PR will be opened on it
   (direct is picked for a hub with no git remote). Ask for one explicit go/no-go and wait.
4. **Execute** (only after confirmation): `kb publish`. Relay the result:
   repo-id, source commit, doc count, and the **PR URL** — remind the user
   the content goes live when that PR is merged on the hub.
5. **Errors.**
   - Missing hub config → tell the user to fill `hub:` in `.kb/config.yaml`.
   - `gh` missing in PR mode → install GitHub CLI, or `kb publish --direct`
     only if direct pushes are allowed for this hub.
   - Other git/hub errors → show the stderr and suggest `kb doctor`.
