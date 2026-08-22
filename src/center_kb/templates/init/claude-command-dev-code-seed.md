---
description: Bootstrap curated service knowledge for a repo adopting center-kb — extract structure, draft each service's responsibility from code evidence, correct it, approve it, and publish
---

Invoke the `dev-code-seed` skill with the Skill tool and follow its
workflow exactly. This is a one-time flow: run it once when a running
project adopts center-kb, never as part of the per-ticket Dev workflow.

*Counterpart in the superpowers plugin: none — this is center-kb's own
onboarding flow.*

## Steps

1. **Preflight** — confirm `.kb/config.yaml` carries `hub:`,
   `repo_id:`, and `intake:`; confirm this repo is allowlisted in the
   hub's `federation/registry.yaml` (tell the Dev to request it there
   if not); warn if the working tree is dirty before extracting.
2. **Extract** — run `kb code-ingest --scaffold-svc` and report the
   sections found per extractor. If it exits 1 (nothing detected but
   the directory tree itself), **stop** and explain which artifact
   kinds were searched (compose/Dockerfile/k8s, dependency manifests,
   migrations, OpenAPI, CI workflows) — a missing `--db` path or no
   compose file is a configuration problem, never a reason to
   hand-write knowledge.
3. **Draft** — run `kb summarize <repo_id>-svc`. The doc-id argument
   matters: it keeps the LLM off `-code`, which must stay deterministic
   and LLM-free.
4. **Review — the actual work, and it is a human's** — walk the
   drafted `svc.*` sections one at a time, showing each draft L2 beside
   its L3 code evidence, and ask the Dev to correct it. The LLM draft
   is a **draft** — it may be wrong, and **approving it unread defeats
   the gate**. The L3 evidence is a bare list of file **paths** and
   structured fields (image, ports, depends-on, env **keys**,
   `db.<table>` ids) only — never a byte of file content, since `.kb/`
   publishes to the hub in full — so read the actual repo checkout
   yourself for grounding; this flow runs locally with the repo
   present, unlike the extractor. `Technology` may render `none` for a
   service built from source — that is a known extractor limit, not a
   missing service; fill it in by hand. Where a responsibility derives
   from a standard, cite `doc-id §section` from the domain KB — never
   restate the rule from the draft. A long `svc.*` id may carry an
   opaque hash suffix (e.g.
   `airspace-flight-plan-validation-orches-a1b2c3`) — copy the id from
   the document, never retype it.
5. **Approve** — run `kb approve <repo_id>-svc` (or `--section <id>`
   for a subset), only for the sections the Dev just confirmed.
6. **Flows (optional)** — add `flow.<name>` sections for business
   flows crossing several services, when the Dev can describe them.
   There is no CLI command for this yet: ask the Dev for the flow's
   name and description, then hand-add the section yourself — a `##
   flow.<name> <title>` heading in `.kb/<repo_id>-svc/flows.md` /
   `flows.raw.md`, plus its `_manifest.yaml` entry: `file: flows` is
   required (no default) and easy to omit or guess wrong. Give that
   entry a non-empty `summary` and make sure its L2 body in
   `flows.md` carries no TODO marker when you add it: `kb build`'s
   pending check reads those two, not `status` — a hand-added
   section missing either one fails step 7's `kb build` with a
   confusing error. Skip freely: a missing flow beats a guessed one.
7. **Validate and publish** — `kb build` **without** `--allow-pending`
   must pass; anything still `pending` is either approved or removed.
   Then commit and run `kb publish --pr` for BA/architect review on the
   hub.

## Hard rules

- The LLM draft is a **draft**. Never approve a section the Dev has not read and corrected — approving it unread defeats the gate.
- A responsibility that touches a standard cites `doc-id §section` from the domain KB. Never restate a rule from the draft as if it were the standard.
- Never invent a service, table, or flow the extractors did not find and the Dev did not confirm.
- `kb build --allow-pending` is for the middle of a seed only — never publish `pending` knowledge.
- Unsure about a service's responsibility → leave it `pending` and record an owned open question. A blank is honest; a guess is not.
- Never edit `-code`: it is regenerated and overwritten on the next merge.
- Never run `kb summarize --redo` to fix one service. It resets the **whole** document, `reviewed` sections included, and rebuilds every L2 from scaffold. Amend by hand. This includes `hist.*`: the recorded ticket rows themselves survive, but its machine-authored summary is replaced by LLM prose, and every `reviewed` section in the document is reset and re-summarized from scratch.
- `kb build` has no `--doc-id`, so any `pending` section committed to the default branch fails CI **by design** — that is the gate working, not a bug to route around.

## Next step — ALWAYS end your response with this block

Close every response with a state line and an ordered list of next
steps, even when you stopped early or hit a blocker — especially then.

    ## Next step

    → 1. <next unfinished step in the seed> — <what it does>   (next in flow)
      2. <redo this step, or correct another draft> — <how>
      3. Stop here — <where things stand, what is already reviewed>

    State: extract <✅ done|⬜ not run> · draft <n>/<m> summarized · review <n>/<m> reviewed · build <✅ clean|⬜ pending remain>

Rules:
- Option 1 is always the next unfinished step, in this order: preflight
  → extract → draft → review → approve → flows (optional) → validate
  and publish. Once every section is `reviewed` and `kb build` passes
  clean without `--allow-pending`, option 1 becomes `kb publish --pr`
  — the one and only terminal step of this one-time flow.
- The `State:` line always shows all four markers, even the ones not
  yet reached.
- A blocker (a zero-detection exit 1, a repo not yet allowlisted on the
  hub) takes option 1 instead and says so.
