# federation/

L0+L1 snapshots published by child repos.

Each child repo runs `kb publish --hub <this-repo-url-or-path>`, which writes
`federation/<repo-id>/` (index + manifests). The hub serves these read-only
through `kb query --hub`, the MCP tools, and the web UI. Content (L2/L3) stays
in the child repo — the hub only holds the child's catalog and summaries.
