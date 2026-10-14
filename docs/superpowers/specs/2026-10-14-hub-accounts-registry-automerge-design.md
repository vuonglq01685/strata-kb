# Hub accounts, registry page, and per-repo auto-merge — design

Date: 2026-10-14
Status: draft, awaiting owner approval
Mockup: `https://claude.ai/artifact/3EQrSt8ouGD83RB7BzYWjm` (registry page layout only)

## 1. Intent

Today every publish from a BA or Dev repo opens a PR on the hub that the hub
owner then merges by hand, even when nobody needs to look at it. The owner
wants the hub itself to decide, per registered repo, whether its publish PRs
merge on their own — and to manage that from the hub web UI rather than by
editing `federation/registry.yaml` in git.

Because the registry is the hub's write-authorization boundary (it decides
which repo may publish under which repo-id), editing it from the web needs a
real "who is this" check. The hub UI's current login is a single shared token
that grants the same rights to every reader. So the work is three linked
pieces:

1. **Accounts + roles** — username/password login backed by SQLite, roles
   `admin`, `ba`, `dev`.
2. **Registry page** — admin-only; add/remove registry entries and toggle
   auto-merge per entry.
3. **Auto-merge** — a new `auto_merge` flag on a registry entry; intake merges
   the PR it just opened when the flag is on.

A separate design (later) covers the Dev ↔ BA/SA Q&A feature. Not here.

## 2. Goals

- The hub owner logs into `/ui` with a username and password.
- A first admin account exists after the first container boot with no
  interactive step (bootstrap from env), and accounts can also be created
  from the CLI.
- Every account has exactly one role: `admin`, `ba`, or `dev`. Only `admin`
  may change the registry. All three roles may read every existing UI page.
- An admin can, from `/ui/registry`: list entries, add an entry (repository,
  repo-id, kind, optional workflow pin, auto-merge on/off), remove an entry,
  toggle auto-merge on an entry.
- A registry entry with `auto_merge: true` gets its publish PR merged by the
  hub immediately after intake opens (or reuses) it.

## 3. Non-goals

- A web page for managing users (add/remove/change role/reset password).
  CLI only for now; the page is a later piece of work. The schema must not
  block it.
- Any read restriction by role. `ba` and `dev` exist so later features can
  differ by role; today they behave identically (read-only).
- Changing how `/api`, `/mcp` or CI authenticate. The bearer token stays
  exactly as it is.
- Auto-merge for PRs that do not go through intake (e.g. `kb publish --pr`
  run locally with the user's own `gh` credentials during a `/dev-code-seed`).
- Any content condition on auto-merge (no "block while sections are
  `pending`", no path scoping). The flag alone decides. This deliberately
  replaces the earlier hub-side, path-scoped auto-merge guidance in
  `QUICKSTART-dev.md` — see §8.
- A hub CI. The hub has none and this does not add one.

## 4. Anti-goals (would be a failure even if it works)

- A password, password hash, or default credential in source code, in a
  template, or in any file that is committed — in this repo or in the hub
  repo.
- A non-admin able to change the registry by any route (crafted POST,
  replayed cookie, stale role after a downgrade).
- An existing hub that upgrades and can no longer reach `/api` or `/mcp`.
- `users.db` ending up inside a git commit on the hub.

## 5. Accounts and roles

### 5.1 Storage

- One SQLite file, separate from the search cache:
  `<hub root>/.kb-auth/users.db` (in Docker: `/data/.kb-auth/users.db`,
  on the existing `./:/data` volume so it survives restarts and image
  upgrades). `search.db` under `.kb-work/` is a rebuildable cache and must
  not hold accounts.
- `.kb-auth/` is added to the hub's `.gitignore` by `kb init --kind hub`
  and by a startup check: if the hub root is a git repo and `.kb-auth/` is
  not ignored, the hub logs an error and appends the ignore line (same
  spirit as `kb mcp-setup` making sure `.env` is ignored).
- Table `users(username TEXT PRIMARY KEY COLLATE NOCASE, password_hash TEXT
  NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','ba','dev')),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL)`.
- Python's stdlib `sqlite3` — no new dependency.

### 5.2 Password hashing

- `hashlib.scrypt` (stdlib), random 16-byte salt per hash, stored as a
  self-describing string, e.g. `scrypt$n=2**14,r=8,p=1$<salt-b64>$<hash-b64>`,
  so parameters can be raised later without breaking old hashes.
- Verification with `hmac.compare_digest`.
- The plaintext password is never logged, never stored, never echoed.

### 5.3 CLI (`kb user ...`)

Run inside the container: `docker compose exec hub kb user <cmd>`.

- `kb user add <username> --role admin|ba|dev` — prompts for the password
  twice (`getpass`); refuses an existing username.
- `kb user passwd <username>` — prompts for a new password.
- `kb user role <username> <role>`.
- `kb user remove <username>` — refuses to remove the last `admin`.
- `kb user list` — username, role, created/updated; never hashes.
- `kb user hash` — prompts for a password and prints its hash string, for
  the bootstrap env var below.

All take the hub root the same way other hub commands do (`--hub`, default
from config/cwd).

### 5.4 Bootstrap admin on startup

On hub service start, **only when the `users` table is empty**:

- If `STRATA_KB_BOOTSTRAP_ADMIN` and `STRATA_KB_BOOTSTRAP_PASSWORD_HASH`
  are both set, insert that user with role `admin` and the given hash, and
  log `bootstrap admin '<name>' created` (name only).
- If only one of them is set, log an error naming the missing one and create
  nothing.
- If the table is not empty, both vars are ignored (log once at info level
  that they are being ignored, so a stale value in `.env` is visible).

Only a **hash** is accepted from env, never a plaintext password: `.env`
sits on disk next to the hub working tree. The operator produces the hash
with `kb user hash` (any machine with `strata-kb` installed, or
`docker run --rm -it <image> kb user hash`). `.env` templates get both vars
commented out with a pointer to `kb user hash`.

### 5.5 Login and session

- `/ui/login` form becomes username + password. Same body cap, same
  `SlidingWindowLimiter` per client IP, same "never log the submitted
  value" rule. Wrong username and wrong password produce the same message
  and take comparable time (verify against a dummy hash when the user does
  not exist).
- If the `users` table is empty, the login page says no account exists yet
  and shows both ways to create one (`kb user add` via `docker compose
  exec`, or the bootstrap env vars). No fallback login, no default password.
- Session cookie (same name `strata_kb_session`, same 12 h max age, same
  `httponly`/`samesite=lax`/`secure` rules) becomes
  `<issued-at>.<username-b64>.<hmac>` signed with the server token as today.
  The cookie does **not** carry the role.
- On every UI request, the auth middleware verifies the signature and age,
  then loads the user row; a missing user means logged out. The role used
  for authorization is the role in the DB at request time, so a role change
  or removal takes effect on the next request. (One indexed SQLite read per
  UI request is acceptable at this scale.)
- Existing token-derived cookies (old format) no longer validate: users get
  sent to the login page once after upgrade. Acceptable.
- `/api/*` and `/mcp` keep accepting the bearer token exactly as today.
  The token is **not** accepted on `/ui/login` any more.

### 5.6 Authorization

- A small `require_role("admin")` check used by every registry route,
  enforced server-side on GET and POST. A non-admin gets 403 on the routes
  and does not see the **Registry** nav item.
- POST routes on the registry page require a CSRF token (per-session value
  rendered into the form, checked on submit) in addition to `samesite=lax`.

## 6. Registry page

### 6.1 Data model change

`models.RegistryEntry` gains `auto_merge: bool = False`. `extra="forbid"`
stays. The plain-string entry shape keeps working and means
`auto_merge: false`. When the page writes an entry that has any non-default
field, it writes the mapping shape.

### 6.2 Routes (admin only)

- `GET /ui/registry` — table: repository, repo-id, kind badge, workflow pin,
  auto-merge switch, remove button; add form on top; recent changes below
  (last N commits touching `federation/registry.yaml`, from `git log`).
- `POST /ui/registry/add` — validate with the same rules the registry
  already enforces on load (`pubgate.normalize_repo_id`, case-colliding key
  check, kind in `HUB_KINDS`, workflow pin shape), plus: repository key not
  already present, repo-id not already claimed by another key.
- `POST /ui/registry/remove` — removes the key. Does not delete the repo's
  published content under `federation/<repo_id>/`; the page says so.
- `POST /ui/registry/auto-merge` — sets the flag on one key.
- Removal is a two-step confirm in the page (no `confirm()` dialogs).

### 6.3 How a change is persisted

Each successful POST:

1. Takes the hub's per-repo write lock used by intake (a registry write and
   an intake publish must not interleave).
2. Re-reads `federation/registry.yaml` from the hub's default branch HEAD,
   applies the one change, re-validates the whole file through
   `models.Registry`, and writes it back preserving the file's existing
   key order (append new keys at the end). Comments in the YAML are not
   guaranteed to survive; the page edits the file, humans should not need to.
3. Commits in a temporary worktree with message
   `registry: <action> <key> (by <username>)` and author/committer set to
   the hub's GitHub App identity, and pushes to the default branch using
   the same GitHub App installation token intake uses.
4. Triggers the hub's pull so the serving tree and the next intake
   authorization see the change immediately.

If the push is rejected (e.g. branch protection on the hub's default
branch), the page shows the error and nothing is half-applied locally.
Operators who protect the default branch must allow the GitHub App to push
to it; the QUICKSTART says so.

Builder's call: whether to factor the worktree/commit/push steps out of
intake's existing publish path or write a small sibling helper.

## 7. Auto-merge

- In `intake_publish`, after `create_or_get_pr` returns the PR, if the
  registry entry for the authorized repository has `auto_merge: true`,
  call a new `ghapp.merge_pr(repo_full, token, number, method)` —
  `PUT /repos/{owner}/{repo}/pulls/{number}/merge`.
- Merge method: `merge` (a merge commit), matching how the hub owner merges
  today unless the builder finds the hub configured otherwise. Builder's
  call if the repo disallows merge commits: fall back to `squash`.
- The registry used for this decision is the same one `authorize` just
  used for this request — no second read.
- After a successful merge, the existing post-merge branch handling in
  `intake_publish` (reset `publish/<rid>` from main next time) already
  covers the next publish. Trigger a hub pull so the UI serves the new
  content without waiting for the auto-pull interval.
- Failure to merge (409 conflict, 405 not mergeable, 403 missing
  permission) **does not fail the publish**: the PR stays open exactly as
  today, the failure is logged with the GitHub status and message, and
  `/intake/status` reports `state: pr_open` with a `detail` saying
  auto-merge failed and why (detail only to the OIDC caller, as today).
- A reused PR (pending publish branch accumulated more content) is merged
  the same way.
- GitHub App permission: merging needs `contents: write` and
  `pull_requests: write` on the hub repo; the hub QUICKSTART and
  `kb doctor` hub check list them.

## 8. Docs and migration

- `QUICKSTART-hub.md`: account bootstrap (both ways), the Registry page,
  the App permissions and branch-protection note, and that `.kb-auth/` must
  never be committed.
- `QUICKSTART-dev.md` step 3 currently says auto-merge is a hub-side,
  path-scoped policy and `-svc` PRs are never auto-merged. Replace with:
  auto-merge is a per-repo switch on the hub's Registry page, it merges the
  whole publish PR (including any `-svc` content riding along), and the
  `-svc` review now happens locally in `/dev-code-seed` step 4 before the
  section reaches `reviewed`. Same change in the user guides
  (`docs/` sources) where the old policy is stated.
- `.env` templates (hub): add the two bootstrap vars, commented.
- CHANGELOG entry and a minor version bump per repo convention.

## 9. Testing expectations

- Unit: hashing round-trip and parameter parsing; bootstrap rules (empty
  table + both vars, one var missing, table non-empty); session cookie
  sign/verify/expiry/tamper; role check reads DB at request time (downgrade
  takes effect); last-admin removal refused.
- Route: non-admin and anonymous get 403/redirect on every registry route
  including POSTs; CSRF missing/wrong → 403; add/remove/toggle produce the
  expected `registry.yaml` and commit message (against the existing local
  git fixture hub); validation failures leave the file untouched.
- Intake: `auto_merge: true` calls the merge hook with the PR number;
  `false` and plain-string entries do not; merge failure leaves publish
  successful with a detail.
- Regression: `/api` and `/mcp` with the bearer token unchanged; old cookie
  format rejected.

## 10. Decided by the owner

- Per-repo flag in the registry, no content condition.
- Registry management in the hub web UI, admin only.
- Username/password accounts in SQLite, roles `admin`/`ba`/`dev` created
  now for later extension.
- Users created via CLI now; a users page later.
- First admin created automatically at startup from env.

## 11. Calls made by the designer (check these)

- Accounts DB at `.kb-auth/users.db`, not inside the search cache.
- Bootstrap takes a password **hash** from env, never plaintext.
- Role is read from the DB on every request, not stored in the cookie.
- Registry edits are git commits pushed by the GitHub App to the hub's
  default branch.
- Auto-merge failure never fails the publish.
- Bearer token stays for `/api`/`/mcp`, is no longer a UI login.
