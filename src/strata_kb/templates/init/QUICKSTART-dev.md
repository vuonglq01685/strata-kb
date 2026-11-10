# Strata Quickstart (Dev repo)

You write product code. Tickets reach you grounded in the knowledge base, with citations
pinned to a version of a document, and you implement them. This repo reads the hub's
published knowledge and publishes two documents about its own code: `<repo_id>-code`
(machine fact from `kb code-ingest`, never committed) and `<repo_id>-svc` (curated
responsibility knowledge, always human-reviewed). It publishes no domain knowledge.

**Full guide:** https://github.com/vuonglq01685/strata-kb/blob/main/docs/src/guide-dev.en.md
(Tiếng Việt: https://github.com/vuonglq01685/strata-kb/blob/main/docs/src/guide-dev.vi.md)

## Set up (once)

1. **Install and scaffold.** `pip install "strata-kb[code]"`, then `kb init --kind dev` (safe
   to re-run; `--lang <name>` for a language it cannot detect). Without the `code` extra,
   routes, pages, jobs and symbols are reported as `not scanned` and `kb doctor` warns.
2. **Point at the hub.** In `.kb/config.yaml`:
   ```yaml
   kind: dev
   repo_id: payments
   hub: https://github.com/acme/kb-hub.git
   intake: https://kb-intake.acme.com
   ```
   `repo_id` must equal this repo's id in the hub's `federation/registry.yaml`: ask the hub
   maintainer to add the repo; publishing is refused until they do. **Never put a token in
   `hub:` or `intake:`**: the file is committed. A URL that needs a credential goes in the
   `STRATA_KB_HUB` environment variable; `kb doctor` warns on a committed credential.
3. **Connect your assistant.** `kb mcp-setup` (in your assistant: `/kb-mcp-setup`) asks for
   the hub's HTTP base URL (`STRATA_KB_HUB_URL`) and token (`STRATA_KB_HTTP_TOKEN`; get it
   from the hub maintainer), writes both into `.env` and verifies them. Prefer the hidden
   prompt or the variable over `--token`, which leaves the token in your shell history. Then
   load the file (`set -a; source .env; set +a`, or use direnv) and restart your assistant.
4. **One version for every repo.** Every repo runs the hub's strata-kb version; `kb doctor`
   syncs it after `kb mcp-setup`.
5. **Turn on the PR gate.** Add **`pr-lint` to the branch's required checks**: running in CI
   does not block a merge by itself, requiring the check does. Once required, it blocks
   every pull request lacking the required sections, bot pull requests included.
   `kb-doctor.yml` sweeps citations daily and needs the Actions variable `STRATA_KB_HUB`
   and, for a private hub only, the secret `KB_HUB_TOKEN`.
6. **Ask whether the hub auto-merges your repo.** With the per-repo switch on, the hub
   merges the **whole** publish PR, `-svc` content included, so the `-svc` review happens
   locally in `/dev-code-seed` step 4, never at the hub.
7. **Seed `-svc` once.** Run `/dev-code-seed`: the agent extracts and drafts, you review
   every draft against its code evidence and approve (10 to 15 minutes per service), then
   `kb build` and `kb publish --pr`. A model draft is a draft, not a fact: never approve
   a section you have not read.

## Daily commands

| Task | Run |
|---|---|
| Implement a ticket | `/dev-implement-ticket <ticket>` (claims it, fetches it, checks it, then design, plan, execute, handover) |
| Plan, then execute | `/dev-plan <id>`, `/dev-execute <id>` (state lives in `docs/impl/<id>/`) |
| Write up a hand-made change | `/dev-handover <id>` |
| Fix a bug | `/dev-fix-bug BUG-<n>` |
| Ask a technical question | `/dev-sa <question>` |
| Fetch or claim a ticket by hand | `kb ticket fetch <id>`, `kb claim take <id>` (exit 3 = taken) |
| Check citations | `kb resolve <file>`, `kb diff <doc> --against <rev>`, `kb get <doc> <section> --level l3` |
| Pick the next story | the hub's Ticket menu, or `kb mission next --from-hub` |
| Publish after the merge | `git switch <default> && git pull --ff-only origin <default>`, then `kb publish` |

You approve the design and the plan (gates 1 and 2), open the PR (gate 3) and merge it
(gate 4). `docs/impl/<id>/ticket.md` is fetched from the hub: never commit or edit it. A
`stale` citation means the source changed after the ticket was written: ask the analyst, and
do not silently implement the new version. A push to the default branch publishes nothing.

## Full-auto mode (optional)

`/kb-auto on|off|status|run` (terminal: `kb auto on|off|status|run`) lets the BA and Dev
repos run on their own, on your machine, until every ticket on the hub is done. An
unattended run merges its own pull requests and publishes to the hub with no human review.
Read the guide's Automation section before turning it on, and enable GitHub branch
protection on `main` first: the merge policy (required checks, code-owner review, no bypass
for the agent). `kb auto run` refuses until it is set up; see "Merge policy" in the guide.

- Automation modes: https://github.com/vuonglq01685/strata-kb/blob/main/docs/src/guide-dev.en.md#4-automation-modes
- Security, read this first: https://github.com/vuonglq01685/strata-kb/blob/main/docs/src/guide-dev.en.md#41-security-read-this-first
- Claude Code cloud: https://github.com/vuonglq01685/strata-kb/blob/main/docs/src/guide-dev.en.md#45-claude-code-cloud
