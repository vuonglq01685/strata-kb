# Strata Quickstart (child repo)

This repo AUTHORS documents and publishes them to the main hub. It does not host the
company-wide search: `kb query`, MCP and the Web UI read only the hub's `federation/`. New
content is searchable once its publish PR is merged on the hub.

**Full guide:** https://github.com/vuonglq01685/strata-kb/blob/main/docs/src/guide-child.en.md
(Tiếng Việt: https://github.com/vuonglq01685/strata-kb/blob/main/docs/src/guide-child.vi.md)

## Set up (once)

1. **Point at the hub.** In `.kb/config.yaml` set `hub:` (a git URL or path) and, to publish
   from CI, `intake:` (the hub's intake URL). Commit the file. **Never put a token in `hub:`
   or `intake:`**: the file is committed. A URL that needs a credential goes in the
   `STRATA_KB_HUB` environment variable, which overrides it; `kb doctor` warns on a committed
   credential. Any machine that uses a credentialed hub URL needs Git 2.31 or newer.
2. **Get registered.** Ask the hub maintainer to add `owner/repo` to the hub's
   `federation/registry.yaml`. `repo_id:` in `.kb/config.yaml` must **exactly match** the id
   it is registered under: over `intake:` a mismatch still opens the PR, but `kb publish`
   times out waiting for it and every upload becomes a full upload.
3. **Pull the ingest image (optional).** `kb docker-setup` (in your assistant:
   `/kb-docker-setup`) pulls the Strata image so ingest runs in Docker with no local Python.
   Skip it if you installed the extra: `pip install "strata-kb[ingest]"`.
4. **Keep sources out of Git.** Put PDFs in `source/`, which Git ignores. Do not commit them.
5. **Connect your assistant.** `kb mcp-setup` (in your assistant: `/kb-mcp-setup`) asks for
   the hub's HTTP base URL (`STRATA_KB_HUB_URL`) and token (`STRATA_KB_HTTP_TOKEN`; get it
   from the hub maintainer), writes both into `.env` and verifies them. Prefer the hidden
   prompt or the variable over `--token`, which leaves the token in your shell history. Then
   load the file (`set -a; source .env; set +a`, or use direnv) and restart your assistant:
   MCP reads the environment only at startup. `hub:` and `STRATA_KB_HUB_URL` are different
   values.
6. **One version for every repo.** Every repo runs the hub's strata-kb version; `kb doctor`
   syncs it after `kb mcp-setup`.

Ask the hub maintainer whether auto-merge is on for your repo: if not, a person on the hub
reviews every publish PR.

## Daily commands

| Task | Command |
|---|---|
| Ingest a PDF | `kb ingest source/my-doc.pdf --id my-doc --tags "tag1,tag2"` or `/kb-ingest` |
| Review flagged L3 | `kb l3 report <doc-id>`, then `kb l3 confirm <doc-id> --section <id>` (or `--all`) |
| Fix L3 structure with AI (optional) | `kb l3 fix on`, then `/kb-l3-fix <doc-id>` |
| Summarize | automatic at ingest when a `claude` or `copilot` CLI is found; else `kb summarize` or `/kb-summarize` |
| Check pending sections | `kb status` |
| Validate | `kb build` |
| Approve (a human act, never automatic) | commit, then `kb approve <doc-id>` or `/kb-approve` |
| Preview, then publish | `kb diff <doc-id> --against HEAD`, then `kb publish` or `/kb-publish` |
| Search the hub | `kb query "your question"`, `kb get <doc> <section> --level l2\|l3`, `kb tags` |
| Check the setup | `kb doctor` |

A document with an unconfirmed L3 finding cannot be summarized, built or published. With
`intake:` set, `kb publish` needs a clean committed `.kb/`, pushes a `kb-publish/<ts>` tag,
and your CI publishes. Merging to the default branch publishes nothing.

## Automation

A child has no `kb auto`. Auto-summarize, the optional L3 AI fix, CI publish via OIDC and
Docker ingest run without you, but none of them approves or confirms. See the guide's
Automation modes section.
