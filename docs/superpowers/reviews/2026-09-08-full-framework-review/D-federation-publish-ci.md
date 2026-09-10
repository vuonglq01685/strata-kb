# Reviewer D — Federation / publish / intake / CI (criteria C7, C15, C17)

Repo: `D:\Projects\AERO-KB` @ `4b47b4c` (v0.20.0, main, clean). READ-ONLY; every experiment ran in
`…/scratchpad/D/`. Platform Windows 11, `D:/Projects/AERO-KB/.venv` (py3.11.15), `gh` 2.x installed,
global `core.autocrlf=true` (the Windows default this framework claims to support).

---

## 1. Scope & method

Code read in full: `publish.py`, `federation.py`, `hub.py`, `intake.py`, `cipublish.py`, `ghio.py`,
`ghapp.py`, `gitio.py`, `hashsync.py`, `assetstore.py`, `assetcmd.py`, `dockersetup.py`,
`web/intake_routes.py`, `web/auth.py`, `web/ratelimit.py`, `web/app.py`, the asset route in
`web/ui.py`, the publish/ci-publish/reindex/assets/docker-setup commands in `cli.py`, all four
`.github/workflows/*.yml`, `scripts/gate.sh`, `scripts/demo-federation.sh`, `Dockerfile`,
`docker-compose.yml`, `docs/deploy-remote-mcp.md`, and the `templates/init/` publish/docker/config
artefacts.

Executed (all foreground):

| What | Result |
|---|---|
| `bash scripts/demo-federation.sh` (as shipped) | **fails on Windows at step 3** — see F-D9 |
| Windows-path variant of the same script (`scratchpad/D/demo-federation-win.sh`) | full 12-step run green |
| `pytest tests/test_{publish,publish_hub,publish_intake_cli,federation,federation_e2e,federation_nested,federation_registry,hub,intake_core,intake_http,intake_publish,gitio,gitio_tags,ghio,ghapp,assetstore,assetcmd,cli_hub,dockersetup,redact_url}.py` | **228 passed** in 166 s |
| `KB_VENV=… pytest tests-gate/regression/test_federation_compat.py` | **2 passed** in 14 s |
| `scratchpad/D/test_intake_probe.py` — 20 adversarial HTTP probes | 19 pass, 1 unbuildable (HS256) |
| `scratchpad/D/test_intake_concurrency.py` — two rids in parallel | reproduces F-D4 |
| `scratchpad/D/test_read_during_publish.py` — reader vs in-flight publish | reproduces F-D3 |
| `scratchpad/D/test_assets_probe.py` — nested + integrity | reproduces F-D11 |
| `scratchpad/D/rid_probe.py`, `rid_probe2.py` — 30 crafted repo-ids | reproduces F-D8 |
| Hand-built hubs (bare remote, cache clone, multi-tier) for F-D1/2/5/6/7/10 | see each finding |

---

## 2. Verified-good

These were exercised and behave as claimed:

* **Mirror completeness L0→L3.** `diff -r child/.kb federation/<rid>/` differs only by the added
  `_meta.yaml` — `index.yaml` (L0), `_manifest.yaml` (L1), `ch1.md` (L2) and `ch1.raw.md` (L3) all
  arrive byte-identical. Not a slim snapshot.
* **Aggregate index correctness.** `federation/index.yaml` is regenerated deterministically from the
  leaf snapshots (`federation.build_federation_index`, DFS by name); nested tiers get path-ids
  (`repo_id: mid/repo-alpha`). Ordering and content matched the entries exactly in every run.
* **Republish idempotence.** Second `kb publish` with no source change: hub HEAD unchanged
  (`8c46df0` → `8c46df0`), `git status --porcelain` empty, and `_meta.yaml.published_at` **not**
  bumped. The design note at `publish.py:64-77` is honoured. (Caveat F-D10 on Windows.)
* **Cycle detection.** Root hub pointed back at the mid hub → `federation cycle detected: the
  upstream hub resolves to this repo itself`, exit 1, nothing written. Identity-based *and*
  path-segment-based guards (`publish.py:278-318`, `federation.find_cycle_segment`), and the config
  read fails closed (`publish.py:280-284`).
* **Self-publish route.** `kind: hub` + `hub: "."` mirrors the hub's own `.kb/` into
  `federation/myhub/`, is cwd-anchored (`cli.py:1242-1260`), idempotent on re-run, and queryable as
  `[myhub:hubdoc §1]`.
* **Nested ids end-to-end.** Root-hub query returned `--- [mid/repo-beta:beta-spec §2.1]` with the
  amended content; depth is unbounded and `iter_entry_dirs` skips symlinks (`federation.py:62-67`).
* **Emptied-federation guard.** Wiping the mid hub's `federation/` and publishing upstream is
  refused: *"source federation/ is empty but the hub already holds entries under 'mid' — refusing to
  wipe them"* (`publish.py:172-177`). Exactly matches README:507.
* **OIDC verification is solid.** All rejected 401 with clean JSON, no traceback: wrong audience,
  wrong issuer, expired `exp`, future `nbf` (no leeway), `alg: none`
  ("The specified alg value is not allowed"). RS256-only allowlist (`intake.py:56`) makes HS256
  confusion unbuildable. Non-allowlisted `repository` → 403 with actionable text; `repository:
  "../../../etc"` → 403 (registry decides the path, never the payload — `intake.py:65-84`).
* **Tar hardening.** `../../evil.md` → 400, `/etc/passwd` → 400, 60 MB body → 413, 200 MB-inner
  tar-bomb → 413 via the cumulative cap with lazy iteration (`intake.py:87-119`). Delete paths with
  `..` → 400 before any clone touch (`intake.py:288-292`).
* **Asset URL surface.** `/assets/{name}` is gated by `^[0-9a-f]{64}\.(png|webp)$` (`ui.py:423`) and
  is *not* in `EXEMPT_PATHS`, so it still needs the bearer/cookie. No traversal reachable.
* **Release ordering is genuinely sequential.** `release.yml`: `docker-verify: needs: gate` →
  `pypi: needs: [gate, docker-verify]` → `docker-release: needs: pypi`. PyPI publish is strictly
  after the whole gate *and* a successful image build+smoke; `:latest` moves only after PyPI. The
  `permissions:` blocks are minimal and per-job (`id-token: write` only on the `pypi` job, which
  also uses `environment: pypi`; `packages: write` only on the two GHCR jobs).
* **T1–T4 do exist and are real.** `_gate.yml` runs T0 ruff (pinned `>=0.15,<0.16`), T1 on
  ubuntu×{3.11,3.12,3.13} **plus windows-latest×{3.11,3.13}**, T2 packaging (`uv lock --check`,
  `twine check --strict`, `check_package.py`, sdist smoke), T3 e2e and T4 regression each on
  ubuntu×3 + **windows-latest 3.12**, both installing the *downloaded* wheel artifact into a venv
  and running pytest from a separate runner venv that has no `center-kb`. T3/T4 genuinely test the
  shipped artifact, not the tree.
* **Docker image hygiene.** Multi-stage; only `pyproject.toml README.md LICENSE src/` are copied, so
  `.kb/`, `tests/` and `source/` cannot leak into the image; runs as non-root `app` (`Dockerfile:47`).
  `[tool.hatch.build.targets.sdist] only-include = ["src"]` and `check_package.py` enforce the same
  for the sdist. `kb docker-setup` mints `secrets.token_hex(24)` (192-bit) and appends `.env` to
  `.gitignore` (`dockersetup.py:49,103-115`). No real secrets are tracked in the repo (scanned for
  `ghp_/ghs_/github_pat_/AKIA…/PRIVATE KEY/xox…` — only test fixtures matched).
* **`kb doctor` hub checks are good.** Slim-layout warning, `index.yaml` out-of-sync **error**,
  stale-cache warning, unpublished-repo warning, duplicate doc-id warning, and multi-tier cycle
  warnings (`doctor.py:213-307`, `338-382`).

---

## 3. Findings

### F-D1 — CRITICAL (C7, C15): `federation/registry.yaml` is not an allowlist for `kb publish`; any publisher can overwrite any other repo's entry

`intake.authorize()` (`intake.py:65-84`) is the **only** place the registry is consulted. The git
write path — `publish.publish()` (`publish.py:207-237`) and `publish.publish_federation()`
(`publish.py:240-334`) — never calls `federation.load_registry`. `--repo-id` is taken at face value
after a regex check.

Repro (`scratchpad/D/gate`, hub = bare repo with `federation/registry.yaml` mapping only
`org/victim: victim`):

```
$ kb publish --kb-dir …/victim/.kb            # victim publishes normally
kb publish: victim @ 0719068 — 1 doc, push.
$ kb publish --kb-dir …/attacker/.kb --repo-id victim
kb publish: victim @ 0a311c4 — 1 doc, push.
$ git -C clone ls-tree -r --name-only HEAD | grep victim
federation/victim/attacker-spec/ch1.md      # victim-spec/* is gone
$ grep repo_id clone/federation/index.yaml
- repo_id: victim                            # doc_id: attacker-spec
```

Victim's documents are deleted from the hub and replaced, and the aggregate index attributes the
attacker's content to `victim`. Documentation presents the registry as the gate — README:846
("Allowlist the repo in the hub's `federation/registry.yaml` (both `-code` and `-svc` publish
through this)"), README:606, `deploy-remote-mcp.md:52` ("also your review gate for who may
contribute") — but it only gates the OIDC route. The repo's own
`.github/workflows/kb-publish.yml:20` uses the un-gated route (`kb publish --hub ${{ secrets.KB_HUB_URL }}`),
so on a hub set up that way *every* child holding that one shared token can publish as any repo id.
Also note `federation.load_registry` is imported by nothing outside `intake`/tests.

### F-D2 — HIGH (C7): auto mode silently direct-pushes to the hub's `main` for every non-GitHub remote hub — the "single review gate" is optional in practice

`publish.py:228-234`:

```python
use_pr = (gitio.has_remote(handle.root) and "github" in gitio.remote_url(handle.root)
          and ghio.gh_available())
mode = "pr" if use_pr else "direct"
```

README:479 says *"with neither flag it auto-picks direct for **local-path hubs**"*. Reality: it picks
direct for any hub whose remote URL lacks the substring `github`, or where `gh` is not installed —
i.e. GitLab, Gitea, Bitbucket, Azure DevOps, self-hosted git, or a GitHub hub on a machine without
`gh`. Repro (bare non-GitHub remote):

```
$ kb publish --kb-dir …/victim/.kb
kb publish: victim @ 86ac17d — 1 doc, push.
$ git -C hub-remote.git log --oneline -2
a7a68ca publish: reindex (victim)
b3d469a publish: victim @ 86ac17d       # straight onto main, no PR, no review
```

Complete enumeration of write paths into `federation/` and whether review is *structural*:

| Path | Review gate | Structural? |
|---|---|---|
| `kb publish` (auto, GitHub hub + `gh`) | PR | only if branch protection is enabled by hand (README:980 asks for it; nothing in the code checks — grep for `branch.protection` in `src/` → 0 hits) |
| `kb publish` (auto, any other remote hub) | **none** — push to main | no |
| `kb publish --direct` | **none** | no |
| `kb publish --pr` | PR; branch force-pushed first (`gitio.push_branch`, `--force`) | same caveat |
| `kb ci-publish` → intake | PR via GitHub App, registry-gated | strongest, but see F-D3/F-D4 |
| hub→hub `kb publish` | same auto/pr/direct logic as row 1–3 | no |
| `kb reindex` | **none** — see F-D5 | no |
| `kb assets migrate` | commits all of `federation/` locally, operator pushes | no |

The substring test is also naive: a hub at `…/github-mirror-hub.git` (not GitHub) routes to PR mode
and then crashes — see F-D9.

### F-D3 — HIGH (C7): while an intake publish is in flight, the read side serves the unreviewed content

`docs/deploy-remote-mcp.md` prescribes one clone (`/srv/kb-hub`) used both by the server
(`--hub /srv/kb-hub`) and by the intake writer (`hub_ref` = same path). `web/api.py:18-21` and
`mcp.py:92-95` resolve that path directly (`hub.resolve_hub` returns local paths as-is,
`hub.py:230-232`), while `intake.intake_publish` checks the *same working tree* out to
`publish/<rid>`, commits, and only restores `original` in a `finally` after the GitHub API round
trips (`intake.py:302-409`).

Repro (`scratchpad/D/test_read_during_publish.py`, GitHub API stubbed with a 2 s delay):

```
READ PATH sees mid-publish: [('alpha', ['UNREVIEWED'])]
git branch during publish: publish/alpha
main has federation/alpha? False
...
read path after: []
```

For the duration of the publish (tar extract + optional S3 uploads + 3 GitHub API calls), `kb query`,
`kb_search`, the REST API and `/ui` return content that is not on `main` and whose PR is unmerged —
the exact thing README:469 says cannot happen ("content only becomes searchable once it is merged").

### F-D4 — HIGH (C7): concurrent intake publishes for *different* repo ids cross-contaminate and permanently poison the hub clone

`intake.repo_lock(rid)` (`intake.py:155-161`, taken at `:293`) serialises only same-rid publishes,
but there is exactly one hub working tree. `original = gitio.current_branch(handle.root)`
(`intake.py:302`) therefore reads whatever branch a *concurrent* publish is sitting on.

Repro (`scratchpad/D/test_intake_concurrency.py`, `alpha` then `beta` 0.3 s later):

```
PR CALLS:
 {"title": "publish: alpha @ calpha", "head": "publish/alpha", "base": "main"}
 {"title": "publish: beta  @ cbeta",  "head": "publish/beta",  "base": "publish/alpha"}   # ← wrong base
--- tree on publish/beta:
federation/alpha/_meta.yaml        # ← alpha's unmerged content rides in beta's PR
federation/alpha/alpha.md
federation/beta/...
--- HEAD branch after both finished: publish/alpha        # ← never restored to main
```

Three consequences: (a) beta's PR carries alpha's unreviewed content; (b) the PR base is a publish
branch, not `main`; (c) the clone is left checked out on `publish/alpha` *for good*, so every
subsequent publish inherits the same wrong `original`, and — combined with F-D3 — the read side
serves that unmerged branch **permanently** until someone checks out `main` by hand. The
"hybrid checkout rule" comment at `intake.py:312-326` reasons carefully about same-rid reuse and
misses the cross-rid case entirely.

### F-D5 — HIGH (C7): `kb reindex` commits and pushes the whole `federation/` tree under a message that says it only rebuilt the index

`cli.py:1358-1360`:

```python
committed = gitio.commit_paths(handle.root, "reindex: rebuild federation/index.yaml", ["federation"])
```

Repro: inject an edit + an untracked directory into the hub clone's `federation/`, then reindex.

```
$ git -C hub status --porcelain
 M federation/legit/d1/ch1.md
?? federation/rogue/
$ kb reindex --hub hub --kb-dir hub/.kb
kb reindex: federation/index.yaml rebuilt
$ git -C hub show --name-only HEAD
    reindex: rebuild federation/index.yaml
federation/index.yaml
federation/legit/d1/ch1.md          # ← tampered content committed
federation/rogue/_meta.yaml         # ← whole new repo entry committed
federation/rogue/index.yaml
$ git -C hub show HEAD:federation/legit/d1/ch1.md
TAMPERED unreviewed content
```

This is not hypothetical dirt: the code's *own* error paths leave uncommitted content under
`federation/` (`publish.py:98-124`, `intake.py:342-370` both restore *best-effort* only, and F-D8
below leaves a permanently dirty tree). `_publish_direct` deliberately scopes its commits to
`federation/<rid>` and `federation/index.yaml` (`publish.py:376-388`) — `reindex` should do the same
and does not. It then pushes to `main` (`cli.py:1369-1376`).

### F-D6 — HIGH (C15): `kb publish` mirrors *every* file under `.kb/` into the hub, including `.kb/config.yaml` (which the docs tell you to put a token in) and stray dotfiles

`publish._snapshot` (`publish.py:87-97`) diffs `hashsync.build_manifest(kb_abs)` — every regular file
under `.kb/`, no allowlist (`hashsync.py:15-35`) — and copies it into `federation/<rid>/`, then
commits. README:479 and `.github/workflows/kb-publish.yml:4` describe the hub URL format as
`https://x-access-token:${TOKEN}@github.com/org/kb-hub.git`, and `config-child.yaml` invites putting
it in `hub:`.

Repro:

```
$ cat child/.kb/config.yaml
hub: "https://x-access-token:ghs_SUPERSECRET123@github.com/org/kb-hub.git"
$ printf 'AWS_SECRET_ACCESS_KEY=AKIAEXAMPLESECRET\n' > child/.kb/.env
$ kb publish --hub hub --kb-dir child/.kb
$ cat hub/federation/child/config.yaml
hub: "https://x-access-token:ghs_SUPERSECRET123@github.com/org/kb-hub.git"
$ cat hub/federation/child/.env
AWS_SECRET_ACCESS_KEY=AKIAEXAMPLESECRET
$ git -C hub show --name-only HEAD~1 --format= | head -2
federation/child/.env
federation/child/config.yaml
```

Both are committed to the hub repo, which by design many people can read. `gitio.redact_url` covers
logs and exception text but nothing redacts published *content*. (The stray-file half also explains
the `ch1.md.bak` that `demo-federation.sh`'s own `sed -i.bak` pushes to the hub.)

### F-D7 — MEDIUM/HIGH (C15): hub credentials are persisted in plaintext in the hub cache clone

`hub.resolve_hub` clones the hub ref into `~/.center-kb/hub/<sha1(url)[:12]>` via
`gitio.clone` → `git clone <url> <dest>` (`hub.py:234-250`, `gitio.py:83-90`). git stores the URL —
including `x-access-token:<token>@` — verbatim in `<cache>/.git/config`, mode `0644`, and it survives
the process:

```
$ grep url plainclone/.git/config
	url = https://x-access-token:ghs_SECRETTOKEN@github.com/org/kb-hub.git
$ ls -la plainclone/.git/config
-rw-r--r-- … 327 …
```

Neither `_cache_base()` nor `clone()` restricts the mode, and the cache key is derived *from the
credentialed URL*, so rotating the token leaves the old clone — with the old token — behind forever.
Related, lower severity: `intake.py:393` builds `https://x-access-token:{token}@github.com/…` and
passes it as an argv to `git push`, so the short-lived token is visible in `/proc/<pid>/cmdline` to
other local users on the intake host.

### F-D8 — MEDIUM (C7, C15): repo-id validation is byte-wise; case- and trailing-dot aliases silently clobber a sibling entry and desynchronise the aggregate index (Windows/macOS hubs)

`_REPO_ID_RE = r"[A-Za-z0-9][A-Za-z0-9._-]*"` (`publish.py:15`) plus
`dest.resolve().is_relative_to(fed_root)` (`publish.py:80-85`, mirrored at `intake.py:210-224`) is
the whole path-safety story. Probe results (`scratchpad/D/rid_probe*.py`, 30 candidates):

* Correctly rejected: `..`, `../evil`, `..\evil`, `a/../../evil`, `C:evil`, `C:/evil`,
  `\\server\share`, `a\x00b`, `victim ` / ` victim`, `évil`, any unicode.
* **Accepted and dangerous on a case-insensitive filesystem**: `VICTIM`, `victim.`, `victim..`,
  `CON`, `AUX`, `NUL`, `PRN`, `COM1`, `LPT1`, 300-char names. `Path.resolve()` normalises them
  textually, so the guard passes; Win32 then folds them onto the sibling directory.

End-to-end (`--repo-id VICTIM` against an existing `victim`, hub with a real remote):

```
$ kb publish --kb-dir attacker/.kb --repo-id VICTIM
kb publish: VICTIM @ f5a61f4 — 1 doc, push.
$ cat clone/federation/victim/index.yaml      # committed entry L0
docs:
  - id: victim-spec
$ cat clone/federation/index.yaml             # committed aggregate index
- repo_id: victim
  doc_id: attacker-spec                        # ← advertises a doc the tree does not contain
$ git -C <hub-cache> status --porcelain
 M federation/victim/_meta.yaml
 D federation/victim/victim-spec/ch1.md ...
?? federation/victim/attacker-spec/
```

The pathspec `federation/VICTIM` matches nothing in git's (case-sensitive) index, so the entry commit
is skipped, but `write_federation_index` reads the on-disk tree and **does** commit + push an index
that disagrees with the committed content. The clone is left permanently dirty — feeding F-D5.
`kb query` for the advertised doc then returns *"No matching section found."*
Related, same root: `--repo-id CON` → `commit failed: error: pathspec 'federation/CON' did not match
any file(s) known to git`, exit 1, leaving an orphan `federation/CON/` directory behind.

### F-D9 — MEDIUM (C15): unhandled exceptions print full Rich tracebacks; `scripts/demo-federation.sh` cannot run on Windows

C15 requires clean errors, not tracebacks. Two reproduced cases:

1. `kb publish --repo-id $(python -c "print('x'*300)")` → `OSError [WinError 123]` is not in
   `cli.py:1308`'s `except (HubConfigError, PublishError, GitError)` → 30-line Rich traceback
   ending in the full hub-cache path.
2. `ghio.GHError` is likewise uncaught. Hub URL `…/github-mirror-hub.git` (contains "github", is not
   GitHub) → auto mode picks PR, `gitio.push_branch` force-pushes the branch, then `gh pr create`
   fails and the traceback surfaces at `publish.py:427 → ghio.py:232 → cli.py:1304`. The content was
   already pushed; the gate never opened.

`scripts/demo-federation.sh` fails at step 3 on Windows: `mktemp -d` yields the MSYS path
`/tmp/tmp.XXXX`, which native Python resolves to `C:\tmp\tmp.XXXX`
(`Path('/tmp/foo').resolve() → C:\tmp\foo`), so `resolve_hub` misses the directory, falls through to
clone, and dies with *"could not reach hub '/tmp/tmp.t0cVd8yfR9/kb-hub'"*. Substituting a
Windows-visible `DEMO_DIR` makes all 12 steps pass unchanged, so this is the script's path handling,
not the tool's.

### F-D10 — MEDIUM (C7): `kb publish` does not neutralise `core.autocrlf`, so on Windows the first publish after any fresh hub checkout rewrites the entire mirror

`intake._neutralize_line_endings` (`intake.py:227-247`) exists precisely for this and is called by
the intake path (`intake.py:296-297`); `publish.publish`/`publish_federation` call only
`_neutralize_excludes` (`publish.py:226`, `:319`). With the Windows-default `core.autocrlf=true`,
a fresh checkout of `federation/` writes CRLF; `hashsync.build_manifest` hashes raw bytes, so every
file looks changed:

```
$ od -c <cache>/federation/child/d1/ch1.md | head -1
0000000  #  #     1     T \r \n \r \n  l  i  n  e ...
$ kb publish --kb-dir child/.kb            # no source change whatsoever
kb publish: child @ 8b840f2 — 1 doc, push.
hub HEAD changed? YES--NOT-IDEMPOTENT
```

Each fresh hub cache clone (new machine, cache eviction, `git checkout -- federation` in the recovery
paths, or a reused `publish/<rid>` branch) therefore produces one spurious whole-tree commit. In PR
mode that means an SME is asked to review a diff touching every file in the snapshot — which defeats
the review gate it is meant to serve.

### F-D11 — MEDIUM (C15, C7): asset-store integrity is asserted but never checked, and multi-tier hubs are handled wrongly

Three distinct problems (`scratchpad/D/test_assets_probe.py`):

1. **No content verification.** `models.AssetsRecord`'s docstring states *"The filename's sha256 IS
   the file content's sha256 … so hub manifests can synthesize exact entries without holding the
   bytes"*, and `synthesized_asset_entries` (`assetstore.py:185-193`) takes the hash straight from
   the filename. Nothing ever hashes what the store returns. Tampering an object behind a
   content-addressed key: `kb assets verify` → `ok = True` (it only does `store.exists`,
   `assetcmd.py:100-103`), and `ui._find_asset` writes the wrong bytes into the on-disk cache
   (`ui.py:465-480`) and serves them with `max-age=31536000, immutable` — permanent cache poisoning
   from one bad object.
2. **Multi-tier record misplacement.** `assetcmd._rid_dirs` iterates only the top level
   (`assetcmd.py:44-48`), so a nested entry `federation/mid/deep` is migrated as if `mid` were the
   repo: the record lands at `federation/mid/_assets.yaml` with the path
   `deep/doc/assets/<sha>.png`. Consequently
   `synthesized_asset_entries(federation/mid/deep)` → `{}` — the leaf that
   `federation.iter_entry_dirs` and every reader actually use has no record at all.
3. **`_snapshot_federation` is asset-store-blind.** It declares `store=None` (`publish.py:148`) and
   never references it — hub→hub publish neither diverts nor synthesizes asset entries, so migrated
   assets look "deleted" to the upstream diff. `_snapshot` (`publish.py:86-100`) does both.

### F-D12 — MEDIUM (C15): the intake reads the whole upload into memory before the size cap, and the rate limiter is trivially shared behind a proxy

`intake_routes.py:119` does `archive = await upload.read()` (Starlette applies no default multipart
size limit) and only then does `safe_extract` check `len(data) > max_bytes` (`intake.py:87-89`). The
60 MB probe correctly returns 413 — *after* the whole body has been buffered. An allowlisted child
(or anyone who compromises one) can push arbitrarily large bodies; there is no `Content-Length`
pre-check and no `max_part_size`. Separately, the limiter keys on `request.client.host`
(`intake_routes.py:88`) with no `X-Forwarded-For` handling, so behind the reverse proxy the deploy
doc implies, all children share one 30-req/60 s bucket and one noisy child locks out the rest.

### F-D13 — MEDIUM (C17): scaffolded CI installs `center-kb` unpinned into jobs that hold `id-token: write`

`templates/init/kb-publish.yml:20` and `templates/init/kb-code.yml:31,45`: `pip install center-kb`
with no version constraint and no hash pinning. Every child repo therefore picks up whatever version
PyPI serves at run time, inside a job that mints an OIDC token able to write to the hub via the
GitHub App. A bad or malicious release changes the behaviour of every child's publish
simultaneously, and builds are not reproducible. All `actions/*` are pinned by moving tag
(`@v4`/`@v5`/`@v3`) rather than SHA; `pypa/gh-action-pypi-publish@release/v1` is pinned to a
**branch** and runs in the `id-token: write` job. `templates/init/docker-compose-*.yml` pull
`ghcr.io/vuonglq01685/center-kb:latest` (mutable). The repo's own
`.github/workflows/kb-publish.yml` has **no `permissions:` block at all** (so it inherits the repo
default token scope) and passes a credential-bearing URL as a command-line argument.

### F-D14 — MEDIUM (C17): `scripts/gate.sh` does not run what CI runs, and cannot run on Windows

`gate.sh:2` claims *"Run the ENTIRE release gate on a dev machine — exactly what CI will run"*, and
README:1006 repeats *"It runs exactly what CI runs, in four tiers"*. Differences vs `_gate.yml`:

* **T0 lint (`ruff check .`) is missing entirely** from `gate.sh` — the one tier most likely to turn
  a PR red is the one the local gate does not run.
* The sdist install smoke test (`_gate.yml:91-96`: install the `.tar.gz`, `kb --version`, load a
  packaged template) is missing.
* `--tag` is never passed to `check_package.py`, so the tag↔version assertion never runs locally.
* No matrix: one interpreter, one OS. CI covers py3.11/3.12/3.13 and windows-latest.
* Windows-unusable: it probes `.venv/bin/python` (Windows has `.venv/Scripts/python`) and then uses
  `$ARTIFACT/bin/pip`, which a Windows venv never creates.

### F-D15 — MEDIUM (C7, C16): the scaffolded `federation/README.md` describes the pre-0.9 slim layout — the opposite of the current architecture

`templates/init/federation-README.md`, written into every new hub by `initcmd.py:50` (and pinned as a
trip-wire by `tests/test_init.py:641`):

> "L0+L1 snapshots published by child repos. … writes `federation/<repo-id>/` (index + manifests).
> **Content (L2/L3) stays in the child repo — the hub only holds the child's catalog and summaries.**"

Since 2026-07-13 the hub holds the **full L0→L3 mirror** and is the only read source (README:469,
verified in §2). Every hub operator is handed a top-level document that contradicts the security and
copyright posture of the thing they just created.

### F-D16 — LOW (C7): `ref`/`sub` claim checks are looser than documented

`intake.authorize` only prefix-matches `ref` (`intake.py:69-72`) and ignores `sub`, `workflow`,
`job_workflow_ref`, `environment`, `actor` entirely. Probes: `ref="refs/tags/kb-publish/../../heads/main"`
→ 200; `sub="repo:evil/repo:ref:refs/heads/main"` → 200. Neither is exploitable today (GitHub mints
`ref` and `repository` itself and will not produce those), but the prefix test is the sort of check
that becomes a hole the moment the ref namespace grows, and pinning `job_workflow_ref` is the normal
hardening for "only *this* workflow may publish".

### F-D17 — LOW: misleading publish output and `_meta.yaml`/report mismatch

* `cli.py:1194`: `action = "push" if report.pushed else "commit only (hub has no remote)"`. Observed
  on a hub that *does* have a remote and simply had nothing to push:
  `kb publish: victim @ 0a311c4 — 1 doc, commit only (hub has no remote).` The message states a
  false fact about the hub.
* Self-publish: the CLI reports the *current* HEAD (`7ccf6aa`) while `_meta.yaml` correctly keeps the
  commit that was actually snapshotted (`fe17d9e`), because the no-change path deliberately does not
  rewrite `_meta.yaml`. Cosmetic, but confusing when auditing.

### F-D18 — LOW (C15): drive-relative paths are accepted (Windows intake hosts only)

Tar member `C:evil.md` and delete path `C:boom` are accepted (both returned 200). `Path.is_absolute()`
is False for drive-relative Windows paths and `_guard`/`safe_extract` then collapse them into the
destination (same drive) rather than rejecting them. Not an escape — a *different* drive is caught by
`is_relative_to` — and `_assets.yaml` injection is blocked because `intake.py:332-341` re-scans the
extracted tree before popping the record. Still, these should be rejected outright, and on Linux they
create literal files named `C:evil.md` inside the published snapshot.

### F-D19 — informational (C17): what T4 federation-compat actually guarantees

`tests-gate/regression/test_federation_compat.py` passes (2 tests, 14 s). Its fixture
(`tests-gate/golden/federation-v0.9.0/`) is a single **flat** entry `golden/` with two docs, no
`registry.yaml`, no assets, no nested tiers, built from `center-kb==0.9.1`. So the guarantee is
narrow but honest: *the current binary can query and doctor a v0.9.0-format flat federation.*
README:1026 phrases T4 as "backward compatibility with older `.kb/` stores (v0.7.0/v0.8.0/v0.9.0)
… and federation compatibility"; the v0.7/v0.8 coverage comes from `test_kb_backcompat.py`, which
tests old **`.kb/` stores**, not old **hubs**. A pre-0.9 *federation* (the `manifests/` slim layout)
is silently skipped by `federation.iter_entry_dirs` (`federation.py:69-74`) — it warns and drops the
entry — which is deliberate and doctor-visible, but is untested and means an un-republished pre-0.9
entry vanishes from search after a hub upgrade. Worth an explicit line in the README.

---

## 4. Criteria scorecard

| Criterion | Verdict | One-line why |
|---|---|---|
| **C7 — hub-first, full mirror, aggregate index, single review gate, multi-tier + cycles, no deletion propagation** | **Partially met** | Mirror completeness, aggregate index, nested ids, self-publish, cycle detection and republish idempotence all verified good; but the "single review gate" is conventional, not structural — auto mode direct-pushes to any non-GitHub remote hub (F-D2), `kb reindex` commits the whole tree (F-D5), unreviewed content is readable mid-publish (F-D3) and permanently after the concurrency bug (F-D4), and no allowlist governs who may publish as whom (F-D1). "Never propagates deletions" holds only in the narrow README sense (a *fully emptied* federation upstream); partial deletions do propagate, both child→hub and hub→hub (verified). |
| **C15 — no secrets in repo, credential redaction, bearer auth + rate limiting, intake hardening (OIDC, allowlist, path safety), clean errors, Windows support, UTF-8, sdist = src only** | **Partially met** | Excellent: OIDC verification (issuer/audience/exp/nbf/alg), tar hardening and size caps, `/assets/` name gate, auth-middleware exemptions, no secrets tracked, sdist `only-include=["src"]`, non-root Docker, 192-bit generated tokens. Not met: the registry allowlist does not govern the git path (F-D1); publish mirrors `.kb/config.yaml` and stray dotfiles, tokens included, into the hub (F-D6); hub credentials persist world-readable in the cache clone (F-D7); repo-id aliasing defeats the path guard on case-insensitive hosts (F-D8); tracebacks instead of clean errors (F-D9); unbounded body read before the cap (F-D12); asset bytes never hash-verified (F-D11). |
| **C17 — release gate T1–T4 (`scripts/gate.sh`, `_gate.yml`)** | **Partially met** | `_gate.yml` genuinely runs T0–T4 with a Windows matrix, T3/T4 against the downloaded wheel in a center-kb-free runner venv, and `release.yml` orders gate → docker-verify → PyPI → retag correctly with minimal per-job permissions. But `scripts/gate.sh` — which README:1006 calls "exactly what CI runs" — omits T0 lint, the sdist smoke test and the tag assertion, and cannot run on Windows (F-D14); scaffolded child workflows install `center-kb` unpinned into `id-token: write` jobs and all actions are tag/branch-pinned rather than SHA-pinned (F-D13). |

---

## 5. Top 3 recommendations

1. **Make the review gate structural instead of conventional.** (a) Enforce
   `federation/registry.yaml` in `publish.publish()`/`publish_federation()` — refuse a `repo_id`
   that is not mapped to the publisher's own repo whenever the hub carries a registry (F-D1);
   (b) make `mode == "auto"` fall back to an *error with two exits* for any hub that has a remote but
   cannot open a PR, instead of silently pushing to `main`, and drop the `"github" in url`
   substring test (F-D2); (c) scope `kb reindex` to `["federation/index.yaml"]` like
   `_publish_direct` already does (F-D5).
2. **Give the intake server its own private, serialised working tree.** Take a single process-wide
   hub-write lock (or a per-publish `git worktree add` / temporary clone) so no publish ever reads
   another's `current_branch`, no PR is ever based on `publish/<rid>`, and the tree cannot be left on
   a publish branch (F-D4) — and separate the *serving* clone from the *writing* clone so readers
   never see an unmerged branch (F-D3). Restore `main` in a `finally` that reads the branch under the
   lock, and add a startup check that the serving clone is on the default branch.
3. **Close the credential and content-leak paths.** Restrict `kb publish` to KB artefacts
   (`index.yaml`, `*/_manifest.yaml`, `*/*.md`, `*/assets/*`) instead of "every file under `.kb/`",
   and either exclude `config.yaml` or redact `hub:`/`intake:` credentials before mirroring (F-D6);
   `chmod 0700` the hub cache and derive the cache key from the credential-stripped URL, or store the
   token via a git credential helper rather than in the remote URL (F-D7); reject repo ids that
   collide case-insensitively or after Win32 trailing-dot folding, plus the reserved device names
   (F-D8). While there: pin `center-kb==<version>` in the scaffolded workflows and add T0 lint +
   the sdist smoke to `scripts/gate.sh` so the local gate stops lying (F-D13, F-D14).
