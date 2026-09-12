# Federation / publish / intake / CI review fixes — a review gate that is structural, a hub that keeps no secrets

**Status:** approved design, ready for an implementation plan
**Source:** reviewer D of the 2026-09-08 full framework review,
`docs/superpowers/reviews/2026-09-08-full-framework-review/D-federation-publish-ci.md`
(findings F-D1–F-D19), and §5 đợt 2 items 1–7 plus đợt 3 items 3 (pins),
4 (`federation/README.md`) and 5 (Windows) of
`docs/superpowers/reviews/2026-09-08-full-framework-review.vi.md`.
**Predecessor:** `2026-09-10-search-mcp-context-review-fixes-design.md`
(reviewer C, merged as PR #48). That batch made the retrieval layer keep
C6, C8 and C9; this batch makes the federation layer keep C7, C15 and C17.
**Approach:** as approved on 2026-09-11 — put every publish gate rule in
one pure module that both write paths call; make `federation/registry.yaml`
the operator's switch for "this hub is governed"; give each intake publish
its own git worktree so the serving tree never leaves the default branch;
and stop mirroring anything that is not a KB artefact.

## Goal

Reviewer D built bare hubs, cache clones and multi-tier hubs by hand, ran
20 adversarial OIDC/tar probes, 30 crafted repo-ids, a two-rid concurrency
probe and a reader-vs-publish probe. The verdict: the federation mechanics
are right, and the guard rails around them are conventional rather than
structural.

- `federation/registry.yaml` is read in exactly one place —
  `intake.authorize()`. The git write path never calls
  `federation.load_registry`, so `kb publish --repo-id victim` from any
  repo holding the hub token **deletes the victim's documents from the hub**
  and makes the aggregate index attribute the attacker's content to
  `victim` (F-D1, CRITICAL; reproduced end to end). README:846, README:606
  and `deploy-remote-mcp.md:52` all present the registry as the gate.
- Auto mode picks a PR only when the hub's remote URL contains the
  substring `github` and `gh` is installed. GitLab, Gitea, Bitbucket,
  Azure DevOps, self-hosted git, and a GitHub hub on a machine without `gh`
  all get a **silent direct push to the hub's `main`** (F-D2, HIGH).
  README:479 says direct is for local-path hubs only.
- The deploy doc prescribes one clone for both the server and the intake
  writer. While a publish is in flight, `kb query`, `kb_search`, the REST
  API and `/ui` serve the unmerged `publish/<rid>` branch (F-D3, HIGH) —
  the exact thing README:469 says cannot happen.
- Two intake publishes for different repo-ids share one working tree:
  beta's PR is based on `publish/alpha`, carries alpha's unreviewed
  content, and the clone is left checked out on `publish/alpha`
  **permanently**, so together with F-D3 the read side serves an unmerged
  branch until someone checks out the default branch by hand (F-D4, HIGH).
- `kb reindex` commits and pushes all of `federation/` under the message
  "rebuild federation/index.yaml" — including hand-edited content and
  untracked directories, which the code's own error paths leave behind
  (F-D5, HIGH).
- `kb publish` mirrors every regular file under `.kb/`, so
  `.kb/config.yaml` — which the docs tell you to put
  `https://x-access-token:<TOKEN>@…` in — and a stray `.kb/.env` are
  committed to the hub (F-D6, HIGH). The same token is then persisted
  world-readable in `~/.center-kb/hub/<sha>/.git/config` (F-D7).
- `_REPO_ID_RE` is byte-wise, so `VICTIM`, `victim.`, `CON` and a 300-char
  id pass the guard and then fold onto a sibling entry on Windows/macOS,
  pushing an aggregate index that disagrees with the committed tree and
  leaving the clone permanently dirty (F-D8).

After this batch:

- a hub carrying a non-empty `federation/registry.yaml` refuses a
  `repo_id` the publisher's own remote is not registered for, and refuses
  a direct push entirely — contributions arrive by PR or through intake;
- auto mode never silently pushes to the default branch: it picks `direct`
  only for a hub with no remote, and otherwise either opens a PR or
  refuses with two named ways forward;
- an intake publish writes in its own `git worktree`; the serving clone
  never leaves the default branch, no PR is ever based on another rid's
  branch, and a hub already stuck on `publish/<rid>` is reported at
  startup;
- `kb publish` mirrors KB artefacts only, and says which files it skipped;
- no credential is persisted in a hub clone's `.git/config` or passed on a
  git command line;
- a fresh hub clone on Windows does not turn the next publish into a
  whole-tree commit;
- `kb reindex` commits `federation/index.yaml` and nothing else;
- an asset whose bytes do not match its content-addressed name is refused
  rather than cached for a year;
- `scripts/gate.sh` runs T0 lint and the sdist smoke, works on Windows,
  and its header claims only what it does;
- scaffolded CI pins `center-kb` to the version that scaffolded it, and
  SHA-pins the actions in jobs that hold `id-token: write`.

## Decisions taken during brainstorming (2026-09-11)

1. **Scope: all 19 of reviewer D's findings.** Same posture as the A, B and
   C batches, which each took nearly their whole reviewer. The heavy item
   is the intake read/write split; everything else is contained. Reviewer
   H's overlapping items (HTTP security headers, cookie hardening, the
   breadth of `kb doctor`, the typer-level traceback callback) stay with
   reviewer H's batch — this one touches `kb doctor` only where a D finding
   needs a new check.
2. **F-D1: a client-side gate plus a forced review route, and honest
   docs.** The git path has no verifiable publisher identity — a child's
   remote URL is self-asserted and one `git remote set-url` away from
   anything. So the registry check in `publish` is a **mistake guard**, and
   the security boundary is the review route the registry now forces (PR
   mode or intake) together with branch protection. The docs stop calling
   the registry an auth boundary on the git path.
   Rejected: a client check alone (leaves direct push open, so the registry
   still governs nothing); a scaffolded pre-receive hook (GitHub.com cannot
   run one, so it would serve only self-hosted hubs and adds a whole
   install surface); refusing every remote hub when a registry exists
   (cleanest trust story, hardest break for anyone publishing over git
   today).
3. **F-D3/F-D4: one `git worktree` per publish, not a second clone.** Keeps
   the single-clone deployment the docs already describe, and removes the
   failure mode instead of coordinating around it — with the serving tree
   never leaving the default branch there is no `original` to read, no
   restore step to skip, and no wrong PR base to compute.
   Rejected: a separate write clone plus a process-wide lock (reviewer D's
   own recommendation, but it changes `deploy-remote-mcp.md`, the
   docker-compose templates and the config surface, and keeps a restore
   step); a temporary clone per publish (perfect isolation, but every
   publish pays for cloning a hub that holds the full L0→L3 mirror).
4. **Fail closed, no escape hatch, bump to 0.21.0.** Every violation is
   exit 1 with a message that names the way forward. No `--allow-direct`
   and no `--no-allowlist`: an escape hatch is what gets pasted into CI
   permanently, which lands back on today's behaviour. A hub with no
   `registry.yaml` is unaffected, so governance is opt-in per hub.
   Rejected: warn-in-0.21, fail-in-0.22 (leaves the CRITICAL open for one
   more release and costs two passes).
5. **Code organisation: one new module, `pubgate.py`.** `cli.py` is already
   2242 lines and `publish.py` carries the auto-mode decision twice
   (`publish.py:266` and `:360`). All gate rules — registry resolution,
   mode selection, repo-id normalisation, the publish allowlist — move into
   one pure module with no I/O, called by `publish.publish()`,
   `publish.publish_federation()` and `intake.authorize()`. New git
   primitives (`worktree_*`, credential-free clone) go into `gitio.py`,
   which is where git primitives live.
   Rejected: in-place edits (`publish.py` would reach ~750 lines and every
   security rule would need a real-git test to exercise it); a second new
   module `hubwrite.py` (`gitio.py` is 202 lines — not enough pressure to
   split).

## Scope

**In.** `src/center_kb/pubgate.py` (new), `publish.py`, `intake.py`,
`gitio.py`, `hub.py`, `federation.py`, `models.py` (the `Registry` schema
only), `assetstore.py`, `assetcmd.py`, `doctor.py`, `cli.py`,
`web/intake_routes.py`, `web/ui.py`, `templates/init/`, `scripts/gate.sh`,
`scripts/check_package.py`, `scripts/demo-federation.sh`,
`.github/workflows/kb-publish.yml`, `.github/workflows/release.yml`,
`README.md`, `docs/deploy-remote-mcp.md`, plus tests in `tests/` and
`tests-gate/`.

**Out.** Reviewer H's HTTP hardening (security headers, cookie flags,
`/api` rate limiting), the typer-level traceback callback, and
`extra="forbid"` on the model layer — all H-batch items that touch the same
files and are better done once, there. No re-ingest and no re-summarize:
the bundled `.kb/` is unchanged. No new runtime dependency, so `uv.lock`
does not need regenerating.

## Design

### 1. `pubgate.py` — every gate rule in one pure module

No filesystem access, no subprocess, no network: callers pass in what they
have already read. That makes each rule a table test, which matters because
these are the security rules.

```python
class GateError(RuntimeError):
    """A publish was refused. The message is user-facing; callers exit 1."""

REPO_ID_MAX = 64
WIN32_DEVICES = {"CON", "PRN", "AUX", "NUL",
                 *(f"COM{i}" for i in range(1, 10)),
                 *(f"LPT{i}" for i in range(1, 10))}

def owner_repo_from_remote(url: str) -> str | None
def normalize_repo_id(rid: str, existing: Iterable[str]) -> str
def resolve_identity(registry, remote_url, requested_rid, self_publish) -> str
def decide_mode(explicit, has_remote, can_pr, governed) -> Literal["pr", "direct"]
def split_allowlist(manifest: dict[str, str]) -> tuple[dict[str, str], list[str]]
def is_governed(registry) -> bool
```

`intake.authorize()` keeps its own OIDC-claim path but calls
`normalize_repo_id` on the value the registry returns, so both write paths
share one definition of a legal repo-id.

### 2. The registry as the publish gate (F-D1)

A hub is **governed** when `federation/registry.yaml` exists and `repos:`
is non-empty. `federation.load_registry` already raises `RegistryError` on
an unreadable file; `publish` treats that as fatal (exit 1), matching
intake's fail-closed behaviour.

On a governed hub, `publish.publish()` and `publish.publish_federation()`:

1. read the publisher's remote — `gitio.remote_url(gitio.git_root(kb_abs))`
   for a child, the mid hub's own remote for a hub→hub publish;
2. `owner_repo_from_remote` parses `https://…/owner/repo(.git)`,
   `https://x-access-token:…@…/owner/repo.git`, `git@host:owner/repo.git`
   and `ssh://git@host/owner/repo.git`, stripping credentials; a local path
   yields `None`;
3. look the result up in `registry.repos` **case-insensitively** (GitHub
   owner/repo names are not case-sensitive in practice);
4. refuse, with the message naming the fix:
   - no remote → *"hub … is governed by federation/registry.yaml but this
     repo has no git remote to identify it — publish through `kb
     ci-publish`, or ask the hub owner to un-govern the hub"*;
   - not registered → the sentence `intake.authorize` already uses:
     *"open a PR on the hub adding `owner/repo: <repo-id>` under `repos:`
     in federation/registry.yaml"*;
   - `--repo-id` given and different → *"registry maps `owner/repo` to
     'x', not 'y'"*;
5. when `--repo-id` is omitted, take the registry's value. On a governed
   hub the registry is the source of truth for the id.

**Self-publish is exempt from governance entirely** — from the identity check
in this section *and* from the direct-push refusal in the next. `kind: hub`
with `hub: "."` writes the hub's own `.kb/` into `federation/<myhub>/`; the
operator is writing to their own hub, so requiring them to register
themselves and open a PR against themselves would only break self-publish on
a governed hub. The exemption is keyed on
`handle.root == gitio.git_root(kb_abs)`, not on a flag.

An ungoverned hub (no registry, or an empty one) keeps today's behaviour —
plus everything else in this batch.

### 3. Mode selection (F-D2, and the pre-push half of F-D9)

`"github" in url` disappears, and no hostname string replaces it. `can_pr` is
`ghio.gh_available()` **and** `gh repo view <hub remote>` succeeding —
probed once, **before** any branch is force-pushed, because today
`gitio.push_branch` runs first and a failing `gh pr create` surfaces a
traceback with the content already on the remote. Asking `gh` whether it can
see the repo is both stricter and broader than any host test: a GitHub
Enterprise hub reached through `GH_HOST` answers yes, and a hub at
`…/github-mirror-hub.git` answers no.

| `--pr`/`--direct` | governed | has remote | can PR | result |
|---|---|---|---|---|
| `--direct` | yes | yes | * | `GateError` — a governed hub takes PR or intake |
| `--direct` | yes | no | * | `direct` (local-path hub, the operator's own machine) |
| `--direct` | no | * | * | `direct` |
| `--pr` | * | no | * | `GateError` — no remote to open a PR against |
| `--pr` | * | yes | no | `GateError`, two named exits |
| `--pr` | * | yes | yes | `pr` |
| auto | * | no | * | `direct` — which is what README:479 already claims |
| auto | * | yes | yes | `pr` |
| auto | * | yes | no | `GateError`, two named exits |

The two named exits: *"install/configure `gh` and re-run with `--pr`, or
re-run with `--direct` if you accept publishing without review"*.

### 4. Repo-id normalisation (F-D8)

`normalize_repo_id` runs before any directory is created, and rejects:

* anything `_REPO_ID_RE` already rejects, plus `.` and `..` (unchanged);
* longer than `REPO_ID_MAX` (64) — the 300-char case raises
  `OSError [WinError 123]` today;
* a trailing `.` (`victim.`, `victim..`) — Win32 folds it away;
* a stem whose casefold is a reserved device name, extension included
  (`CON`, `NUL`, `COM1`, `CON.md`);
* a casefold collision with an existing entry directory under
  `federation/` — `VICTIM` against an existing `victim` is refused instead
  of clobbering it and pushing an index that disagrees with the tree.

The caller passes the existing entry names (directories directly under
`federation/`, minus `_FED_TOP_EXCLUDE`), so the rule stays pure.

### 5. The publish allowlist (F-D6)

One rule, applied to every manifest before it is synced. A path is kept when
**no segment starts with `.`** and one of:

* the basename is `index.yaml`, `_meta.yaml` or `_manifest.yaml`;
* the basename ends with `.md` (this covers `*.raw.md`);
* its parent directory is `assets`.

Everything else is dropped and reported: `[warn] 2 file(s) under .kb/ were
not published (allowlist): config.yaml, .env`. The same rule serves the
`.kb/` source in `_snapshot`, the `federation/` source in
`_snapshot_federation` (nested tiers included, since the rule is
depth-independent), and the extracted tar in `intake.intake_publish` — a
child must not be able to upload what a child must not be able to publish.
`_assets.yaml` stays out of the allowlist by default: it is hub-owned
bookkeeping written by `assetstore.divert_and_record`, never copied from a
`.kb/` source.

**Exception, deliberate: `_snapshot_federation`.** There,
`is_kb_artifact`/`split_allowlist` take `keep_records=True`, so
`_assets.yaml` IS kept on the source side of the diff. A hub-to-hub source
is itself a hub's `federation/` tree, where `_assets.yaml` is hub-*written*
content genuinely being mirrored upward, not a source artefact being
smuggled in — dropping it there (as the general rule above would) made the
record read as source-absent/dest-present on every publish, and the diff
classified that as a deletion: the record (and any diverted asset bytes
behind it) got wiped on the very next hub-to-hub publish (Wave F review
finding 1, closed in `b012f25`/`3845ee5`/`01cbd0a`). `_snapshot_federation`
never diffs `_assets.yaml` as a plain file either way — see
`_prepare_hub_to_hub_manifests`/`_reconcile_asset_records` in `publish.py`,
which pop `RECORD_NAME` from both manifests unconditionally and drive its
content explicitly (union-merge, then divert only while this hub has a
store), so a storeless hub never deletes or truncates what it cannot see.

Files already mirrored heal themselves: dropping them from the local
manifest puts them in `diff_manifests`' `deleted` list, and `apply_sync`
removes them from the hub on the next publish. What does **not** heal is git
history — the CHANGELOG and README say plainly that a token published this
way must be rotated. For an entry whose child has stopped publishing, and
which will therefore never trigger the deletion, `kb doctor` on a hub gains
a warning naming any entry that still holds a non-allowlisted file.

### 6. Hub credentials (F-D7)

Three changes, in `gitio.py` and `hub.py`:

1. **The cache key is derived from the credential-stripped URL.** Today
   `~/.center-kb/hub/<sha1(url)[:12]>` is keyed on the credentialed URL, so
   rotating a token strands the old clone — with the old token in it —
   forever. Existing caches re-clone once under the new key.
2. **A persisted remote URL never carries a credential.** `gitio` gains a
   helper that splits `user:token@` out of an https URL, runs git against
   the stripped URL, and injects the credential through the environment:

   ```
   GIT_CONFIG_COUNT=1
   GIT_CONFIG_KEY_0=http.<stripped-url>.extraheader
   GIT_CONFIG_VALUE_0=Authorization: Basic <b64("x-access-token:<token>")>
   ```

   `/proc/<pid>/environ` is readable only by the same uid;
   `/proc/<pid>/cmdline` is world-readable, which is why `intake.py:393`
   handing the token to `git push` as an argv is the other half of this
   finding. Clone, fetch, pull and push in both `hub.resolve_hub` and
   `intake` go through the helper.
3. **The cache directory is created `0700`**, and on resolve, a cached clone
   whose `remote.origin.url` still carries a credential (written by an older
   version) is rewritten to the stripped URL. `kb doctor` reports one that
   cannot be rewritten.

### 7. Line endings (F-D10)

`gitio.clone` runs `git -c core.autocrlf=false -c core.eol=lf clone` and
writes both keys into the new clone's local config, so later checkouts stay
LF. `publish.publish`/`publish_federation` call `_neutralize_line_endings` —
which exists for exactly this and is called only from the intake path today
(`intake.py:296`) — alongside the `_neutralize_excludes` they already call.
The function moves from `intake.py` to `gitio.py` now that two callers share
it. `kb init` scaffolds `.gitattributes` with `* text=auto eol=lf` for both
hub and child.

### 8. Intake: one worktree per publish (F-D3, F-D4)

`gitio` gains `worktree_add(root, path, branch, base)`,
`worktree_remove(root, path)` and `worktree_prune(root)`.

`intake.intake_publish` loses the variable `original` and the whole
checkout/restore dance:

* the base is read from a ref (`origin/<default>`), never from
  `gitio.current_branch(handle.root)`;
* `dest_on_main` asks git (`git cat-file -e <default>:federation/<rid>`)
  instead of testing `dest.exists()` in the serving tree;
* the hybrid rule is preserved exactly — `worktree add -B publish/<rid>`
  from the base when the rid is already on the default branch or the branch
  does not exist, otherwise check the existing branch out into the worktree,
  so an unmerged PR still accumulates snapshots and a byte-identical
  re-publish is still a true no-op;
* all writing, committing and pushing happens inside the temporary worktree,
  which is removed in a `finally`;
* `repo_lock(rid)` stays — it owns same-rid idempotence — and a
  process-wide lock wraps worktree creation and removal;
* at startup the intake app runs `worktree_prune` (crash cleanup) and checks
  that the serving clone is on the default branch, warning loudly with the
  fix if it is not. That is the recovery path for a hub already stuck on
  `publish/alpha`.

With the serving tree pinned to the default branch, F-D3 and F-D4 stop being
conditions to coordinate around: there is nothing to read the wrong branch
from, and nothing to restore.

### 9. Intake request hardening (F-D12, F-D16, F-D18)

* **Size cap before buffering.** `intake_routes.py:119` reads the upload in
  chunks and aborts at `cfg.max_tar_bytes` with 413; a `Content-Length`
  header over the cap is refused before reading at all.
* **Rate limiting behind a proxy.** A setting names how many trusted proxies
  sit in front of the server (`N`, default `0`). At `0` the limiter keys on
  `request.client.host`, exactly as today, and `X-Forwarded-For` is ignored
  — so the key cannot be spoofed by default. At `N > 0` the key is the
  `N`-th entry from the right of `X-Forwarded-For`, which is the last hop
  the trusted chain did not write.
* **Claim checks.** `ref` is matched by exact segments under
  `refs/tags/kb-publish/` and rejects any `..` segment, instead of the
  current bare prefix test. `Registry` gains an optional mapping form —
  `owner/repo: {repo_id: x, workflow: <job_workflow_ref>}` — so a hub owner
  can pin which workflow may publish; the plain string form keeps working
  and stays the documented default. Both forms are read through one
  accessor, `Registry.resolve(repo) -> RegistryEntry | None`, so §2's
  case-insensitive lookup and `authorize()` see the same shape.
* **Windows path shapes.** A tar member or delete path carrying a drive
  letter (`C:evil.md`) or a backslash is rejected on every OS, not collapsed
  into the destination.

### 10. `kb reindex` (F-D5)

`cli.py:1642` commits `["federation/index.yaml"]`, the way `_publish_direct`
already scopes its own commits. Anything else dirty under `federation/` is
left alone and named in a `[warn]`, so an operator learns about it instead
of having it silently committed under a message that says the index was
rebuilt.

### 11. Assets (F-D11)

1. **Verify what the store returns.** `assetstore` hashes the bytes it reads
   and compares them to the sha256 in the content-addressed name; a mismatch
   is an error. `web/ui.py:465-480` verifies before filling the on-disk
   cache, so nothing wrong is ever served with `max-age=31536000,
   immutable`. `kb assets verify` hashes content instead of calling
   `store.exists` (`assetcmd.py:100-103`) — that is what "verify" means.
2. **Walk entries the way readers do.** `assetcmd._rid_dirs` uses
   `federation.iter_entry_dirs`, so a nested entry `federation/mid/deep`
   gets its record at `federation/mid/deep/_assets.yaml` and
   `synthesized_asset_entries` finds it.
3. **`_snapshot_federation` is no longer store-blind.** It takes the same
   `store` as `_snapshot` (`publish.py:148` hard-codes `None`) and does the
   same divert-and-synthesize, so migrated assets stop looking deleted to an
   upstream hub.

### 12. Clean errors and the demo script (F-D9)

The `publish`, `ci-publish` and `reindex` handlers in `cli.py` catch
`pubgate.GateError`, `ghio.GHError` and `OSError` alongside the
`(HubConfigError, PublishError, GitError)` they already catch, and print one
line. `scripts/demo-federation.sh` defaults `DEMO_DIR` to a path native
Python can resolve on Windows, rather than `mktemp -d`'s MSYS
`/tmp/tmp.XXXX`, which `Path.resolve()` turns into `C:\tmp\…`.

### 13. `scripts/gate.sh` (F-D14)

Add T0 (`ruff check .`), the sdist install smoke `_gate.yml:91-96` runs
(install the `.tar.gz`, `kb --version`, load a packaged template) and
`--tag` for `check_package.py`. Select `bin` vs `Scripts` from the venv
layout in both `gate.sh` and `scripts/check_package.py`, so the script runs
under Git Bash on Windows. The matrix cannot be reproduced locally, so the
header and README:1006 stop claiming it is: they say one interpreter and one
OS, and that CI runs py3.11/3.12/3.13 plus windows-latest.

### 14. Pinning the scaffolded CI (F-D13)

`kb init` renders `pip install center-kb==<version>` and
`ghcr.io/vuonglq01685/center-kb:<version>` using the version of the CLI
doing the scaffolding, in `templates/init/kb-publish.yml`, `kb-code.yml` and
`docker-compose-*.yml`. Actions in jobs that hold `id-token: write` are
SHA-pinned — the scaffolded workflows and `release.yml`'s `pypi` job, where
`pypa/gh-action-pypi-publish@release/v1` is currently pinned to a *branch*;
other jobs keep major tags. The repo's own `.github/workflows/kb-publish.yml`
gains a minimal `permissions:` block (it has none today, so it inherits the
default token scope) and reads the hub from a `KB_HUB_URL` environment
variable instead of passing a credentialed URL as a command-line argument.

### 15. Publish report honesty (F-D17)

`PublishReport` gains `remote: bool`, so `cli.py:1194` distinguishes "push",
"nothing to push" and "hub has no remote" instead of inferring the third
from `pushed`. On the self-publish no-change path the CLI reports the commit
recorded in `_meta.yaml` — the one actually snapshotted — rather than the
hub's current HEAD.

### 16. Docs (F-D15, F-D19, and the lines this batch falsifies)

* `templates/init/federation-README.md`, written into every new hub by
  `initcmd.py:50`, is rewritten for the current architecture: the hub holds
  the full L0→L3 mirror and is the only read source. It describes the
  pre-0.9 slim layout today. The trip-wire at `tests/test_init.py:641` is
  updated with it.
* README:479 (auto mode), README:606 and README:846 plus
  `deploy-remote-mcp.md:52` (what the registry gates, and that branch
  protection and intake are the security boundary), README:1006
  (`gate.sh`).
* README gains one line on T4's real scope: it proves the current binary can
  query and doctor a **flat v0.9.0** federation. A pre-0.9 federation in the
  `manifests/` slim layout is skipped by `federation.iter_entry_dirs` with a
  warning, so an un-republished pre-0.9 entry disappears from search after a
  hub upgrade.
* CHANGELOG gets a **Breaking changes** section for 0.21.0: a governed hub
  refuses direct pushes; `config.yaml` and dotfiles are removed from hub
  entries on the next publish and **any token published this way must be
  rotated**; repo-ids colliding case-insensitively, ending in `.`, naming a
  Win32 device, or longer than 64 characters are refused.

## Error handling

- Every gate refusal is a `GateError` carrying a message that names the way
  forward, surfaced as one line and exit 1. No traceback reaches a user from
  `publish`, `ci-publish` or `reindex` — including the 300-char repo-id
  `OSError` and a failing `gh pr create`.
- Nothing is written before a refusal: repo-id normalisation, registry
  resolution, mode selection and the `gh repo view` probe all run before the
  first file copy or branch push.
- `RegistryError` is fatal on the publish path, as it already is on the
  intake path — a hub whose registry cannot be read is never treated as
  ungoverned.
- An intake publish that fails leaves no worktree behind (`finally`), and a
  crash is cleaned by `worktree_prune` at the next startup.
- An asset whose bytes do not match its name is an error at read time; it is
  never cached and never served.
- Skipped-by-allowlist files are a `[warn]`, not a failure: a stray file is
  a mistake to report, not a reason to block a publish.

## Testing

TDD: each finding gets a failing test before its fix. Reviewer D's tables
become the test tables. The repo uses no mocking library — tests run on a
real filesystem and real git — and that stays.

- `tests/test_pubgate.py` (new), pure and exhaustive: the repo-id table
  (`VICTIM` against an existing `victim`, `victim.`, `victim..`, `CON`,
  `CON.md`, `NUL`, `COM1`, 300 chars, plus the ids reviewer D confirmed are
  correctly rejected today); `owner_repo_from_remote` over https,
  credentialed https, scp-style ssh, `ssh://`, and a local path; the
  registry table (no remote, unregistered, wrong `--repo-id`, omitted
  `--repo-id`, case-differing owner/repo); the `decide_mode` table above,
  all nine rows; the allowlist table (`config.yaml`, `.env`, `ch1.md.bak`,
  `index.yaml`, `<doc>/_manifest.yaml`, `<doc>/ch1.raw.md`,
  `<doc>/assets/<sha>.png`, and the same shapes one and two levels deeper
  for a federation source).
- `tests/test_publish_registry.py` (new): reviewer D's F-D1 repro — a
  registry mapping only `org/victim: victim`, an attacker repo publishing
  `--repo-id victim` → exit 1, hub HEAD unchanged, victim's docs still
  there. Today this succeeds and deletes them.
- `tests/test_publish_mode.py` (new): a bare non-GitHub remote hub → auto
  refuses instead of pushing to the default branch (today: `b3d469a publish:
  victim @ 86ac17d` straight onto main); a hub URL containing
  `github-mirror` no longer routes to PR mode; PR mode against a hub `gh`
  cannot see refuses **before** the branch is pushed.
- `tests/test_publish_allowlist.py` (new): `.kb/config.yaml` carrying a
  token and `.kb/.env` never reach the hub; an entry that already holds them
  loses them on the next publish; `kb doctor` warns about an entry that
  still holds one.
- `tests/test_hub_credentials.py` (new): after `resolve_hub` with a
  credentialed URL, `<cache>/.git/config` contains no token; the cache key
  is unchanged when the token rotates; a legacy cache with a credentialed
  remote is rewritten; the directory is `0700` on POSIX.
- `tests/test_intake_concurrency.py` (new): reviewer D's two-rid probe —
  `alpha` then `beta` 0.3 s later, both PRs based on the default branch,
  neither tree carrying the other's files, and the serving clone still on
  the default branch afterwards.
- `tests/test_read_during_publish.py` (new): a reader against the hub while
  an intake publish is in flight (the GitHub API stubbed with a delay) sees
  no unmerged content at any point.
- `tests/test_publish_crlf.py` (new): a hub clone taken with a global
  `core.autocrlf=true` → the second publish with no source change is a no-op
  and the hub HEAD does not move.
- `tests/test_reindex_scope.py` (new): a hand-edited file and an untracked
  directory under `federation/` are **not** committed by `kb reindex`, are
  named in the warning, and `federation/index.yaml` is committed.
- `tests/test_intake_http.py`: an over-cap upload is refused with 413
  without the whole body being buffered; a `Content-Length` over the cap is
  refused before any read; `X-Forwarded-For` is ignored unless the
  trusted-proxy setting is on; a `ref` with a `..` segment, and a
  `C:`-prefixed tar member and delete path, are refused.
- `tests/test_assetstore.py` / `test_assetcmd.py`: a tampered object behind
  a content-addressed key fails `kb assets verify` and is never cached or
  served; a nested entry `federation/mid/deep` gets its record at the leaf;
  a hub→hub publish carries diverted assets instead of reporting them
  deleted.
- `tests/test_init.py`: the rewritten `federation-README.md` trip-wire; the
  scaffolded `.gitattributes`; `pip install center-kb==<version>` and the
  pinned image tag in the scaffolded workflows and compose files.
- `tests/test_cli_errors.py` (new): a 300-char repo-id, a failing `gh pr
  create` and an unreadable `registry.yaml` each produce one line and exit 1,
  with no traceback on stderr.
- `tests-gate/`: unchanged in shape. `scripts/gate.sh` gains T0 and the
  sdist smoke and is exercised on Windows by hand before the tag, since the
  gate script is the thing under test.

The full suite runs 10–19 minutes, so it runs once at the end of the batch,
not per task.

## Acceptance

- Reviewer D's F-D1 repro exits 1 and the victim's documents are still on
  the hub.
- A bare non-GitHub remote hub never receives a direct push from auto mode;
  the refusal names both ways forward.
- Two intake publishes for different rids finish with both PRs based on the
  default branch, neither carrying the other's files, and the serving clone
  on the default branch.
- A reader sees no unmerged content at any point during an intake publish.
- `kb reindex` on a dirty hub commits `federation/index.yaml` only.
- `.kb/config.yaml` and `.kb/.env` are absent from the hub after a publish,
  and a hub entry that held them no longer does.
- No hub clone's `.git/config` contains a credential, and no token appears
  in any git command line.
- On Windows with `core.autocrlf=true`, publishing twice with no source
  change moves the hub HEAD once.
- `--repo-id VICTIM` against an existing `victim`, `--repo-id CON`, and a
  300-char id each exit 1 before anything is written.
- A tampered asset object is refused by `kb assets verify` and by the web
  asset route.
- `bash scripts/demo-federation.sh` completes all 12 steps on Windows.
- `scripts/gate.sh` runs T0 and the sdist smoke and completes on Windows.
- A freshly scaffolded child pins `center-kb==<version>`; the scaffolded
  `federation/README.md` describes the full L0→L3 mirror.
- README:479, 606, 846, 1006 and `deploy-remote-mcp.md:52` describe what the
  shipped code does.
