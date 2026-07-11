---
name: kb-publish
description: Review and publish KB changes to the federation hub — diff changed sections, approve after user confirmation, then kb publish. Use when asked to publish the KB, push to the hub, or approve reviewed sections.
---

# KB Publish — review → approve → publish

You drive the federation step of the CENTER-KB pipeline. Approving a
section is a human review verdict; publishing is outward-facing. You
execute both — the user decides both.

<HARD-RULE>
NEVER run `kb approve` or `kb publish` until the user has explicitly
confirmed, after seeing the diff, which sections to approve and which hub
to publish to. One explicit confirmation covers both — state clearly what
will happen before asking.
</HARD-RULE>

## Workflow

1. **Check state.** Run `kb status`. If any section is still `pending`,
   stop and tell the user to summarize first (`kb summarize`, or the
   kb-summarize skill).
2. **Show the diff.** For each doc with changes, run
   `kb diff <doc-id> --against HEAD` (use another git rev if the user
   names one) and present the added/changed sections for review.
3. **Confirm — the gate.** State exactly which sections will be approved
   and which hub will receive the publish. The hub is `CENTER_KB_HUB` if
   set; if not set, ask for the hub URL/path — never guess. Then ask for
   one explicit go/no-go and wait.
4. **Execute** (only after confirmation):
   `kb approve <doc-id> --section <id>` (repeat `--section` per section),
   then `kb publish --hub <hub>`. Relay the result: repo-id, source
   commit, doc count, push vs commit-only.
5. **Errors.**
   - `kb approve` warnings about pending or missing sections → show them
     verbatim; NEVER edit `_manifest.yaml` by hand to force a status.
   - `kb publish` git/hub errors → show the stderr and suggest
     `kb doctor`.
