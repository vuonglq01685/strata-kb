# Deploying Remote HTTP MCP for BAs (Phase 3)

Goal: BAs query the KB via MCP without cloning the repo (Phase 3 spec §10).

## Internal server

Line endings need no operator action: `kb init` scaffolds `.gitattributes`
(`federation/** -text` on a hub, `.kb/** -text` on a child) — that's what
protects the operator's own `git clone` in step 1 below from CRLF
rewriting on Windows. Separately, any hub *cache* clone `gitio.clone` makes
(e.g. for a child repo consuming this hub) forces `core.autocrlf=false` /
`core.eol=lf` and writes them into that clone's local config.
`tests/test_windows_hygiene.py` scans every text-mode write call under
`src/strata_kb` and `scripts/` and requires `newline="\n"`, unless the call
is binary-mode (no newline translation applies) or carries a
`# newline-exempt: <reason>` comment.

Behind a TLS-terminating reverse proxy, set
`STRATA_KB_TRUSTED_PROXIES=<number of proxies>`. It does two things: the
rate limiter keys on the real client instead of collapsing every user into
the proxy's bucket, and the `/ui` session cookie earns its `Secure` flag
from `X-Forwarded-Proto`. Left unset behind a proxy, the server logs a
warning and sets the cookie without `Secure`. Each trusted proxy in the
chain must *append* the address/scheme it observed to
`X-Forwarded-For`/`X-Forwarded-Proto`, not overwrite it — with more than
one proxy in the chain, an overwriting hop discards the proxies before it,
so the key silently falls back to the peer, which is the exact
shared-bucket failure described below.

Also set `STRATA_KB_ALLOWED_HOSTS` to the public host name(s) the proxy serves,
comma-separated, e.g. `STRATA_KB_ALLOWED_HOSTS=kb.example.com`. `/mcp` keeps
the MCP SDK's DNS-rebinding check, which accepts only a localhost `Host` (and
`Origin`) unless told otherwise, so without it `/mcp` answers
`421 Invalid Host header` while `/api` and `/ui` work. Each name is accepted
with any port, over `http` and `https`. List bare names only: a scheme, port
or path stops the server at startup. Rewriting `Host` to `localhost:8321` at
the proxy is no longer needed.

Every response carries `Content-Security-Policy` (`script-src 'self'`),
`X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
`Referrer-Policy: strict-origin-when-cross-origin` and a
`Permissions-Policy`; HSTS is added only when the request reaches this
server over https. This server unconditionally disables uvicorn's own
`X-Forwarded-Proto` handling, so if you put a TLS-terminating reverse proxy
in front of it, the connection it actually sees is plain HTTP: HSTS never
fires, even though the client used HTTPS. That is an accepted gap, not
something `STRATA_KB_TRUSTED_PROXIES` closes; set HSTS at the reverse
proxy if you need it.

1. Clone the hub: `git clone <kb-hub-url> /srv/kb-hub`
2. Install the tool: `pip install strata-kb` (add `.[embed]` if you want semantic search)
3. Set a token: `export STRATA_KB_HTTP_TOKEN=$(openssl rand -hex 24)` — store it in a secret manager
4. Start the server:
   `python -m strata_kb.mcp --kb /srv/kb-hub/.kb --hub /srv/kb-hub --transport http --host 0.0.0.0 --port 8321`
5. Cron to keep the hub fresh (every 5 minutes): `*/5 * * * * git -C /srv/kb-hub pull --ff-only`

### Sample systemd unit

    [Unit]
    Description=Strata remote MCP
    After=network.target

    [Service]
    Environment=STRATA_KB_HTTP_TOKEN=<token>
    ExecStart=/usr/bin/python3 -m strata_kb.mcp --kb /srv/kb-hub/.kb --hub /srv/kb-hub --transport http --host 0.0.0.0 --port 8321
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

       Environment=STRATA_KB_GH_APP_ID=<app id>
       Environment=STRATA_KB_GH_APP_KEY=/etc/strata-kb/app-key.pem
       Environment=STRATA_KB_INTAKE_AUDIENCE=https://kb.internal:8321

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
4. Install deps on the server: `pip install "strata-kb[server]"`.
5. Optional, per repo: turn on **auto-merge** for a registered repo (the Registry
   page of the hub UI, admin only, or `auto_merge: true` in its registry entry).
   Intake then merges that repo's whole publish PR right after opening it; the
   App's `Contents` and `Pull requests` write permissions (step 1) cover it. A
   failed merge leaves the PR open and the publish `done` (`merged: false`, the
   reason in `detail` for the OIDC caller). Registry-page edits are commits on the
   hub's default branch pushed by the same App, so a protected default branch must
   allow the App to push. UI accounts live in `<hub>/.kb-auth/` and are never
   committed; create the first admin with
   `kb user add <name> --role admin --kb /srv/kb-hub/.kb` or
   `STRATA_KB_BOOTSTRAP_ADMIN` + `STRATA_KB_BOOTSTRAP_PASSWORD_HASH='<hash>'`
   (keep the single quotes in a Compose `.env`: Compose expands `$`, and the hash
   contains several).

The three intake routes are exempt from `STRATA_KB_HTTP_TOKEN` (children don't
hold that token): POST /intake/publish and GET /intake/manifest are
OIDC-authenticated — a child can only diff/publish its own registered repo-id.
GET /intake/status is public by design (the zero-secret dev CLI polls it) and,
without a token, returns only `state` and `pr_url` keyed by repo-id + commit —
same internal-network assumption as the MCP itself. The failure `detail` (it
can carry raw git stderr) goes only to a caller presenting that repo-id's
OIDC token; the child CI's job summary shows it. GET /intake/manifest and
/intake/status share a 120/minute per-caller limit.

The server refuses to start when `STRATA_KB_HTTP_TOKEN` is the `change-me`
placeholder, shorter than 32 characters, or not printable ASCII.
`kb docker-setup --force` writes a fresh 48-character token.

### Rate-limit key behind a reverse proxy (`STRATA_KB_TRUSTED_PROXIES`)

`/intake/publish` is rate-limited per caller (30 attempts/minute by default).
The key is normally the TCP socket peer, which cannot be spoofed — but every
request from behind a reverse proxy arrives from the *proxy's* address, so
without this variable every child sits behind one shared bucket.

- `STRATA_KB_TRUSTED_PROXIES` (default `0`): the number of reverse proxies you
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
- **Warning:** at `STRATA_KB_TRUSTED_PROXIES >= 1`, a client that connects
  **directly** to this server — bypassing your proxy — fully controls the
  `X-Forwarded-For` value it sends, and therefore its own rate-limit bucket.
  Setting this variable is only safe when the server is bound (firewalled,
  or listening on an address) so that only your proxy can reach it; do not
  set it on a server also reachable directly from the internet.
- This server also disables uvicorn's own `X-Forwarded-For` handling
  (`proxy_headers=False`) unconditionally — `STRATA_KB_TRUSTED_PROXIES` /
  `client_key` is the single authority on `X-Forwarded-For` here. Two
  independent, differently-trusted implementations reading the same header
  is the hazard this avoids; do not re-enable uvicorn's proxy headers.
- Because uvicorn's own handling is disabled, `STRATA_KB_TRUSTED_PROXIES` is
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
  spoofing risk described above — get `STRATA_KB_TRUSTED_PROXIES` right in
  *both* directions, not just against a spoofing attacker.

## Ticket Q&A

Ticket Q&A needs nothing set up. The three `kb_question_*` MCP tools keep their
questions in `<hub>/.kb-qa/qa.db`, which is never committed (the hub git-excludes
it, and a new hub's `.gitignore` lists it); back it up with the hub volume. They
work only on this server (or the stdio server inside the hub's own checkout): a client
whose MCP reads the hub through a local cache clone, or anywhere else, gets `Q&A needs
the shared hub server — point MCP at it (kb mcp-setup)`. Any caller the server
authenticates (the bearer token) can ask and answer, and the names they give are
self-declared: tracking, not authentication.

## Client config (Claude Code / Cowork)

    {
      "mcpServers": {
        "strata-kb": {
          "type": "http",
          "url": "http://kb.internal:8321/mcp",
          "headers": { "Authorization": "Bearer <token>" }
        }
      }
    }

Note: run only on an internal network/VPN — documents are copyrighted. The server
refuses to start without `STRATA_KB_HTTP_TOKEN`.

## Connecting a reader repo

On a `child`, `ba` or `dev` repo, `kb mcp-setup` does the client half:

```
kb mcp-setup --hub-url http://kb-hub.example.com:8321
```

It prompts for the token (hidden), writes `STRATA_KB_HUB_URL` and
`STRATA_KB_HTTP_TOKEN` into `.env`, adds `.env` to `.gitignore` when the repo
has no entry for it, and then probes the hub: `GET /api/health` without the
token to check the URL, then `GET /api/docs` with it to check the token. A
wrong URL and a rejected token therefore produce different messages.

Load `.env` into the shell your editor inherits (`set -a; source .env; set
+a`, or direnv) and restart the editor — MCP clients read the environment
only at startup.

`--no-verify` writes the credentials without the probe, for a hub that is
temporarily down.
