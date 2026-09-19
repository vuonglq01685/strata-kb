# federation/

Full L0→L3 mirrors published by child repos, and the aggregate index built
from them.

Each child runs `kb publish --hub <this-repo-url-or-path>`, which writes
`federation/<repo-id>/` — the child's complete `.kb/` tree (index, manifests,
L2 summaries and L3 verbatim text), plus a hub-written `_meta.yaml` recording
the source repo and commit. `federation/index.yaml` is regenerated from those
snapshots on every publish.

**The hub is the only read source.** `kb query`, the MCP tools and the web UI
read from here, never from a child repo, so content becomes searchable when it
lands on this hub's default branch — and only then.

Two consequences worth knowing before you open this hub to more repos:

- Everything a child publishes is readable by everyone who can read this repo.
  Copyright and confidentiality are decided by who can clone the hub.
- `federation/registry.yaml` maps `owner/repo` → repo-id. Adding a mapping
  makes this hub *governed*: `kb publish` then refuses a repo-id the
  publisher's own remote is not registered for, and refuses direct pushes —
  contributions arrive by PR or through `kb ci-publish`. The registry is the
  review gate's roster; branch protection on this repo is what enforces it.
  This hub publishing its own `.kb/` into its own `federation/<repo-id>/` is
  exempt from the registry check — self-publish never consults it.
