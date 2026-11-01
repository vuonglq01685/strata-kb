# Strata Quickstart (BA repo)

You write requirements: tickets, user stories, acceptance criteria and, for large features,
mission plans. A finished ticket is Dev-ready: every claim that touches a standard cites a
real document at a known revision, and the Definition of Ready (DoR) gate (`kb ticket lint`,
`kb mission lint`) stops a ticket with a broken or missing citation. This repo is read-only
against the knowledge base: you cite it and never change it. What you publish is your own
plan, `<repo_id>-plan`.

**Full guide:** https://github.com/vuonglq01685/strata-kb/blob/main/docs/src/guide-ba.en.md
(Tiếng Việt: https://github.com/vuonglq01685/strata-kb/blob/main/docs/src/guide-ba.vi.md)

## Set up (once)

1. **Install and scaffold.** `pip install strata-kb`, then `kb init --kind ba` (safe to
   re-run).
2. **Point at the hub.** In `.kb/config.yaml`:
   ```yaml
   kind: ba
   hub: https://github.com/acme/kb-hub.git
   repo_id: acme-requirements
   intake: https://kb-intake.acme.com
   ```
   `repo_id` must equal this repo's id in the hub's `federation/registry.yaml`: ask the hub
   operator to add `owner/repo` there and to leave `workflow:` unset. Publishing is refused
   until you are registered. **Never put a token in `hub:` or `intake:`**: the file is
   committed. A URL that needs a credential goes in the `STRATA_KB_HUB` environment
   variable; `kb doctor` warns on a committed credential.
3. **Connect your assistant.** `kb mcp-setup` (in your assistant: `/kb-mcp-setup`) asks for
   the hub's HTTP base URL (`STRATA_KB_HUB_URL`) and token (`STRATA_KB_HTTP_TOKEN`; get it
   from the hub maintainer), writes both into `.env` and verifies them. Prefer the hidden
   prompt or the variable over `--token`, which leaves the token in your shell history. Then
   load the file (`set -a; source .env; set +a`, or use direnv) and restart your assistant.
4. **One version for every repo.** Every repo runs the hub's strata-kb version; `kb doctor`
   syncs it after `kb mcp-setup`.
5. **Turn on the CI gate.** Actions variable `STRATA_KB_HUB` (the hub the gate resolves
   against), Actions secret `KB_HUB_TOKEN` (a read token, private hub only). In branch
   protection, **require the `lint` check** of the `kb-ticket-lint` workflow on the branch
   your tickets land on: lint running in CI does not block a merge by itself, requiring the
   check does. A pull request from a fork cannot read secrets, so on a private hub the gate
   fails there; merge fork work through a branch in this repo.

## Daily commands

| Task | Run |
|---|---|
| Plan a large feature | `/ba-mission-plan` (writes `missions/M-<slug>.md`) |
| Write a ticket | `/ba-ticket-author` (writes `tickets/<folder>/<ticket-id>.md`) |
| Report a defect | `/ba-bug-report` |
| Answer a Dev's question | `/ba-answer-questions` |
| Change a mission or ticket | `/ba-mission-plan --amend M-<slug>`, `/ba-ticket-author --amend <ticket>` |
| See which story is next | `kb mission next` |
| Publish the plan | `/kb-publish` (or `kb publish`), or merge a change to `missions/` or `tickets/` into `main` |

At a terminal:

```bash
kb query "<text>" [--tags t]
kb get <doc> <section> [--level l2]
kb context new --refs "doc §4.2, doc §4.3"   # paste the block under ## KB context
kb ticket lint <file>
kb mission lint <file>
```

A ticket ships only when every box of its `## Definition of Ready` is ticked. With
`intake:` set, `kb publish` needs `.kb/`, `missions/` and `tickets/` committed.
`.kb/<repo_id>-plan/` and `.kb/index.yaml` are generated and git-ignored: never commit them.

## Full-auto mode (optional)

`/kb-auto on|off|status|run` (terminal: `kb auto on|off|status|run`) lets the BA and Dev
repos run on their own, on your machine, until every ticket on the hub is done. An
unattended run merges its own pull requests and publishes to the hub with no human review.
Read the guide's Automation section before turning it on, and enable GitHub branch
protection on `main` first (block force pushes, include administrators, keep the `lint`
check required, and do not require approving reviews: the agent cannot approve its own PR).

- Automation modes: https://github.com/vuonglq01685/strata-kb/blob/main/docs/src/guide-ba.en.md#4-automation-modes
- Security, read this first: https://github.com/vuonglq01685/strata-kb/blob/main/docs/src/guide-ba.en.md#41-security-read-this-first
- Claude Code cloud: https://github.com/vuonglq01685/strata-kb/blob/main/docs/src/guide-ba.en.md#45-claude-code-cloud
