# Deploying Remote HTTP MCP for BAs (Phase 3)

Goal: BAs query the KB via MCP without cloning the repo (Phase 3 spec §10).

## Internal server

Note: hub clones used by the server/publishers should keep `core.autocrlf=false`
(the tool sets this repo-locally during publish/intake; a global
`autocrlf=true` on other hub clones degrades no-op detection but not
correctness).

1. Clone the hub: `git clone <kb-hub-url> /srv/kb-hub`
2. Install the tool: `pip install center-kb` (add `.[embed]` if you want semantic search)
3. Set a token: `export CENTER_KB_HTTP_TOKEN=$(openssl rand -hex 24)` — store it in a secret manager
4. Start the server:
   `python -m center_kb.mcp --kb /srv/kb-hub/.kb --hub /srv/kb-hub --transport http --host 0.0.0.0 --port 8321`
5. Cron to keep the hub fresh (every 5 minutes): `*/5 * * * * git -C /srv/kb-hub pull --ff-only`

### Sample systemd unit

    [Unit]
    Description=CENTER-KB remote MCP
    After=network.target

    [Service]
    Environment=CENTER_KB_HTTP_TOKEN=<token>
    ExecStart=/usr/bin/python3 -m center_kb.mcp --kb /srv/kb-hub/.kb --hub /srv/kb-hub --transport http --host 0.0.0.0 --port 8321
    Restart=on-failure

    [Install]
    WantedBy=multi-user.target

## Publish intake (OIDC → PR on the hub)

The same server can accept publishes from child repos with **zero secrets on
the children**. Child CI authenticates with a GitHub Actions OIDC JWT; the
server verifies it, checks `federation/registry.yaml` on the hub, and opens
the PR itself using a GitHub App.

1. Create a GitHub App (hub owner): permissions `Contents: Read and write` +
   `Pull requests: Read and write`; install it on the hub repo only.
   Download the private key PEM.
2. Extra env for the server:

       Environment=CENTER_KB_GH_APP_ID=<app id>
       Environment=CENTER_KB_GH_APP_KEY=/etc/center-kb/app-key.pem
       Environment=CENTER_KB_INTAKE_AUDIENCE=https://kb.internal:8321

   All three present → `/intake/*` routes turn on. Any missing → intake stays
   off, read-only MCP still works.
3. Register each child on the hub: add `owner/repo: repo-id` under `repos:`
   in `federation/registry.yaml` (a normal PR). This is what the intake
   authorises against, and what makes the hub *governed* on the git path:
   `kb publish` then refuses an unregistered repo-id and refuses direct
   pushes. The registry cannot authenticate a git publisher — a remote URL
   is self-asserted — so branch protection on this repo is what makes the
   review route binding. **Warning:** the `repo-id` here must exactly match
   `repo_id:` in the child's `.kb/config.yaml`. On the **intake** path (OIDC,
   as set up in this section) a mismatch still succeeds and the PR opens, but
   the dev CLI will time out waiting for a PR that actually opened, and
   uploads lose incrementality (every publish becomes a full upload). On the
   **git** path (`kb publish` run directly, not through intake), a mismatch
   is refused: `pubgate.resolve_identity` raises before anything is written,
   naming the repo-id the registry actually maps the remote to.
4. Install deps on the server: `pip install "center-kb[server]"`.

The three intake routes are exempt from `CENTER_KB_HTTP_TOKEN` (children don't
hold that token): POST /intake/publish and GET /intake/manifest are
OIDC-authenticated — a child can only diff/publish its own registered repo-id.
GET /intake/status is public by design (the zero-secret dev CLI polls it) and
returns only state/PR URL keyed by repo-id + commit — same internal-network
assumption as the MCP itself.

### Rate-limit key behind a reverse proxy (`CENTER_KB_TRUSTED_PROXIES`)

`/intake/publish` is rate-limited per caller (30 attempts/minute by default).
The key is normally the TCP socket peer, which cannot be spoofed — but every
request from behind a reverse proxy arrives from the *proxy's* address, so
without this variable every child sits behind one shared bucket.

- `CENTER_KB_TRUSTED_PROXIES` (default `0`): the number of reverse proxies you
  operate in front of this server. `0` means `X-Forwarded-For` is ignored
  entirely and the socket peer is used — safe by default, and correct for the
  documented single-node deployment above (no proxy in front). Set it to `N`
  when there are `N` trusted proxies in the path; the key is then the `N`-th
  address from the *right* of `X-Forwarded-For` (the last hop your own
  proxies did not write).
- The server now aborts startup (a clean message, not a traceback) if the
  value isn't a non-negative integer — a malformed value must not silently
  fall back to "header ignored" when an operator meant it trusted, so this
  fails loud rather than quiet.
- **Warning:** at `CENTER_KB_TRUSTED_PROXIES >= 1`, a client that connects
  **directly** to this server — bypassing your proxy — fully controls the
  `X-Forwarded-For` value it sends, and therefore its own rate-limit bucket.
  Setting this variable is only safe when the server is bound (firewalled,
  or listening on an address) so that only your proxy can reach it; do not
  set it on a server also reachable directly from the internet.
- This server also disables uvicorn's own `X-Forwarded-For` handling
  (`proxy_headers=False`) unconditionally — `CENTER_KB_TRUSTED_PROXIES` /
  `client_key` is the single authority on `X-Forwarded-For` here. Two
  independent, differently-trusted implementations reading the same header
  is the hazard this avoids; do not re-enable uvicorn's proxy headers.
- Because uvicorn's own handling is disabled, `CENTER_KB_TRUSTED_PROXIES` is
  the single authority for the **whole app**, not just `/intake/publish` —
  it also governs the web UI's login rate limiter (`/ui/login`), which has
  no separate variable of its own.
- **Leaving it at the default `0` behind a reverse proxy** collapses BOTH
  limiters into one shared bucket, because every request — intake and
  login alike — then keys on the proxy's own address instead of the real
  client: with `/intake/publish`, every child repo's publish attempts share
  one 30-per-minute bucket; with `/ui/login`, every operator's login
  attempts share one 5-per-minute bucket, so one locked-out user locks out
  everyone else too. This is the failure an operator deploying behind a
  reverse proxy will actually hit, and it is the mirror image of the
  spoofing risk described above — get `CENTER_KB_TRUSTED_PROXIES` right in
  *both* directions, not just against a spoofing attacker.

## Client config (Claude Code / Cowork)

    {
      "mcpServers": {
        "center-kb": {
          "type": "http",
          "url": "http://kb.internal:8321/mcp",
          "headers": { "Authorization": "Bearer <token>" }
        }
      }
    }

Note: run only on an internal network/VPN — documents are copyrighted. The server
refuses to start without `CENTER_KB_HTTP_TOKEN`.
