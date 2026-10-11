"""Transport-neutral pieces shared by the MCP server, the Web UI/REST app and
the intake routes: the server config, bearer/session auth and rate limiting.
`mcp` and `web` both depend on this package; it depends on neither."""
