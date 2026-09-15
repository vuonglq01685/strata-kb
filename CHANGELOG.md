# Changelog

Releases before 0.21.0 are not recorded here -- they are tracked only through
git tags and pull-request history.

## 0.22.0

### Breaking — the BA Definition-of-Ready gate now reads section bodies

A ticket or mission that passed 0.21.0 on structure alone can fail here.
Run `kb ticket lint` over your open tickets before upgrading CI.

- Required sections that are empty or hold only placeholder text
  (`TBD`, `TODO`, `N/A`, `chưa rõ`, …) are errors.
- `## Acceptance Criteria` needs at least 2 items, unique ids, and each AC
  must carry a Given/When/Then triple, a measurable value, or an owned
  `OPEN(<owner>)`. `OPEN(TBD)` and `OPEN(?)` no longer count as owned.
- `## Non-functional requirements` rows need a number or an owned
  `OPEN(...)` in Target; `## Definition of Ready` needs its checklist rows
  (unticked boxes stay a warning).
- A `mermaid` fence must contain a relationship — an arrow or a C4
  `Rel(...)`.
- `## Review record` rows must match the shipped table: five filled cells,
  scores 1–5, increasing round numbers, `gap-verifier` from round 2. Scores
  below 4 and a fourth round remain warnings.
- **Citations are `[doc-id §section]`.** The bare `doc-id §section` form is
  no longer parsed as a citation; when it names a pinned ref it gets a
  warning telling you to bracket it. Natural prose such as
  `per ARINC 424 §5.129` no longer fails the gate.
- Two `kb-context:` blocks in one document is an error.

### Added

- `kb ticket lint --fail-on-stale` / `kb mission lint --fail-on-stale`:
  a stale ref becomes an error and the command exits 2 when that is the only
  failure, mirroring `kb resolve`. The scaffolded CI gate passes the flag
  when the repository variable `KB_FAIL_ON_STALE` is set.
- `kb init --kind ba` scaffolds `docs/review-rubric.local.md` and
  `docs/ac-quality.local.md` once and never refreshes them.

### Fixed

- `section_body` no longer ends a section at a `#` line inside a fenced
  block, so valid tickets stopped being rejected.
- Heading and citation scanning ignore HTML comments: commented-out
  sections read as missing, and a citation inside a comment is neither a
  citation nor an error.
- The scaffolded `kb-ticket-lint` and `kb-pr-lint` workflows pin
  `center-kb==<version>`, carry a `concurrency:` block, surface failures as
  annotations and a step summary, and keep a non-`https://` hub scheme
  intact.

## 0.21.0

### Breaking changes

- **a hub ref that carries a credential now needs git 2.31 or newer, on
  every machine that touches that hub.** before 0.21.0 the token stayed in
  the clone's `remote.origin.url` (the hub was cloned verbatim), so any git
  authenticated from the URL itself. 0.21.0 strips it out of the clone and
  hands it to git only through `GIT_CONFIG_COUNT` / `GIT_CONFIG_KEY_0` /
  `GIT_CONFIG_VALUE_0` -- env-based config git added in **2.31** and older
  git ignores without a word. measured against a loopback server with every
  credential helper disabled, varying only whether git honours
  `GIT_CONFIG_COUNT`: the old URL shape sends `Authorization`, the new shape
  on a git that honours it sends `Authorization`, and the new shape on a git
  that ignores it sends **no `Authorization` header at all**. so below the
  floor nothing is degraded -- nothing authenticates. every command that
  reaches the hub fails, the very first clone included: `kb publish`,
  `kb reindex`, `kb doctor`, `kb query`, and the MCP and web read paths. the
  message does not name git: the CLI prints `could not reach hub '<url>'
  and no cache exists — check the network or the hub path` (or
  `could not reach hub '<url>'` from `kb publish`), with git's own `fatal:
  Authentication failed for '<url>'` on the line above it. `kb ci-publish`
  is the one exception on the publisher's side -- it only reads the child's
  own repo and uploads over HTTP -- but the **intake server** clones the hub
  for it, so an intake host under 2.31 answers every publish `503 hub
  unreachable from the intake server`. **check
  `git --version` on every runner and image before upgrading** -- Debian 11
  ships git 2.30.2 and Ubuntu 20.04 LTS ships 2.25.1, both below the floor,
  and both worked on the previous release. `kb doctor` does flag an old git,
  but only once it already holds a hub clone, which on a token-bearing hub
  is exactly what an old git cannot produce -- do not rely on it to find
  this. an ssh hub ref (`git@…`), a public `https://` hub, and a local-path
  hub carry no credential and are unaffected.
- `kb publish` in auto mode (no `--pr`/`--direct` flag) used to treat any
  remote whose URL did not contain "github" as "push directly" -- so a
  GitLab, Gitea, self-hosted, or otherwise non-GitHub hub always got a
  silent direct push, and so did a **GitHub** hub on any machine or runner
  where `gh` was missing. it now asks `gh` whether it can actually open a
  pull request on that hub's host (`gh repo view` inside the hub clone, so
  the host comes from that clone's own `origin` -- a GitHub Enterprise hub
  answers yes once `gh` is authenticated for it, and a
  `.../github-mirror-hub.git` answers no), and if it cannot -- `gh` missing,
  unauthenticated, or the host itself cannot take a PR -- publish is refused
  instead of pushed. two groups lose a publish that used to work, not one: a
  non-GitHub hub, and a GitHub hub anywhere `gh` is not installed at all.
  (an installed-but-unauthenticated `gh` on a GitHub hub is not one of them:
  the previous release's auto mode tested only whether the `gh` binary was
  on `PATH`, so that case already chose `--pr`, pushed the branch, and then
  failed at `gh pr create`. 0.21.0 refuses it up front instead, before
  anything is pushed.) on an **ungoverned** hub the refusal names
  a way back that works: pass `--direct` to keep the old behaviour, or set up
  `gh` for that host to use `--pr`. on a **governed** hub -- one carrying a
  non-empty `federation/registry.yaml` -- `--direct` is refused as well; see
  the next bullet, and "Known limitations" below for what is left when `gh`
  cannot open a pull request on a governed hub.
- `federation/registry.yaml` now governs `kb publish`, not only the intake
  HTTP route that used to be its only reader. on a hub carrying a non-empty
  registry, `kb publish` refuses -- in every mode, `--pr` included -- a
  source repo whose `owner/repo` (read from that repo's own git remote, host
  dropped) is not listed under `repos:`, and a source repo with no git remote
  cannot publish to a governed hub at all. when the registry does recognize
  the publisher, its mapped repo-id wins: a repo-id that disagrees with it is
  now refused, not honoured -- and that is not only the `--repo-id` flag.
  `repo_id:` in `.kb/config.yaml`, the documented normal way to set it, goes
  through the same check, so an existing child whose `repo_id:` does not
  match the hub's registry entry stops publishing on upgrade with nothing on
  its command line changed. (the refusal reads "drop `--repo-id`" even then,
  naming a flag that was never passed -- the disagreement to fix is between
  `.kb/config.yaml` and the hub's registry.) on top of that, a governed hub
  with a git remote refuses `kb publish --direct` outright. there are exactly
  two exemptions, both deliberate: a governed hub with **no** git remote
  still accepts `--direct` (there is nothing to open a pull request against),
  and a hub publishing its **own** `.kb/` into its own `federation/` -- the
  self-publish route a `hub:` pointing at itself takes -- skips the registry
  check *and* the direct-push refusal entirely, since otherwise a hub owner
  would have to register themselves and open a pull request against
  themselves. the registry check is a mistake guard, not authentication: the
  remote URL it reads is self-asserted by the publisher, so branch protection
  on the hub is still what makes the review route binding.
- `federation/registry.yaml` is also schema-strict now, and a registry that
  fails to load is fatal to every `kb publish` to that hub, in every mode --
  with the same self-publish exemption as the bullet above. a hub mirroring
  its **own** `.kb/` into its own `federation/` never reads the registry at
  all, so an invalid registry stops every other publisher and not the hub
  owner: the hub owner will not see it, and the first symptom is other
  people's publishes failing. before 0.21.0 unknown keys were ignored, and
  the file was parsed only by the intake HTTP route, so a bad registry broke
  at most that route. now
  an unknown top-level key, an unknown key inside an entry, two keys
  differing only in case, or non-UTF-8 bytes each refuse the publish before
  anything is written. the strictness is deliberate -- an entry's optional
  `workflow:` pin is a security control, and a typo'd `workflw:` used to drop
  it silently -- but it means **hub owners should validate their registry
  before upgrading**: a file that has loaded fine for months can stop every
  publisher at once.
- `kb publish` and `kb ci-publish` mirror `.kb/` artefacts only. before
  0.21.0 they mirrored **every** file under `.kb/`; `config.yaml`, dotfiles
  and anything else outside that allowlist are now stripped out of
  `federation/<repo-id>/` on your next publish (the CLI prints a `[warn] ...
  (allowlist)` line naming what it withheld, and `kb doctor` names the files
  an older publish already left on the hub). **if a token or secret was ever
  published into a hub entry this way, rotate it now** -- removing the file
  from the working tree does not remove it from git history. `.kb/config.yaml`
  is the one to check first: its `hub:` field routinely carries a
  `https://x-access-token:<token>@github.com/org/repo.git` URL, and it was
  mirrored on every publish. **run `kb doctor` against the hub before your
  first publish after upgrading.** that first publish strips those files out
  of the entry, and from then on `kb doctor` reports `kb doctor: OK` and
  names nothing -- so the window in which the tool can still tell you what
  an older publish left on the hub closes at the next publish, whoever or
  whatever triggers it: the scaffolded CI workflow fires on a `kb-publish/*`
  tag, and `kb publish` itself creates and pushes that tag. once that has
  happened the only record left is the hub's own history
  (`git log --all -- 'federation/*/config.yaml'`, run inside the hub repo).
  and the warning going away never means the credential is gone: it stays
  in the hub's git history until that history is rewritten. rotating the
  token is the fix; deleting the file is not.
- repo-ids are refused, not silently accepted, when they collide with an
  existing entry case-insensitively, end in `.`, name a reserved Win32 device
  (`CON`, `PRN`, `AUX`, `NUL`, `CONIN$`, `CONOUT$`, `COM0`-`COM9`, `LPT0`-
  `LPT9`, and the NTFS superscript aliases of `COM1`-`COM3`/`LPT1`-`LPT3`
  written with superscript digits), or exceed 64 characters.
- `kb ci-publish`'s intake server now refuses tar members whose names contain
  C0 control characters, DEL, bidi/formatting control code points, unpaired
  surrogates, or drive-relative or backslash path segments, and caps both
  member count and directory count per archive -- an upload that relied on
  any of these is now refused instead
  of landing on the hub. three more refusals join them on the same route: a
  publish tag whose path segments are not well formed is `403` (the old check
  was a bare `refs/tags/kb-publish/` prefix test), a registry entry carrying a
  `workflow:` pin rejects a token minted by any other workflow with `403`,
  and a registry that maps a publisher to a repo-id the hub cannot use as a
  directory name is `500` rather than a broken hub tree.
- **that same intake refuses four more classes of `.kb/` path *shape* that
  0.20 accepted, and each refusal aborts the whole upload.** measured by
  pushing the same tar bytes through each release's own extractor:
  - **two paths that differ only in case, or only in Unicode
    normalization.** members are now compared on
    `NFC(casefold(name minus invisible characters))`, so `Annex3.md`
    alongside `annex3.md` -- or an NFC `café.md` alongside the NFD
    spelling of the same name -- is `400 tar member 'annex3.md' collides
    with 'Annex3.md' once normalized -- rename one`. 0.20 committed both
    files.
  - **a path component that is a reserved Windows device name** --
    `aux.md`, `nul.md`, `lpt1.md`, `CONIN$.md`, or a directory named
    `con/`: `400 ... is a reserved Windows device name`.
  - **a path component ending in a dot or a space** -- a doc-id directory
    named `arinc-424.`, say: `400 ... ends in a dot or space`.
  - **a path component holding a character Windows cannot put in a
    filename** (`< > " | ? *`): `400 ... contains a character Windows
    cannot put in a filename`.

  the repo this breaks is not an exotic one: it is a **Linux-origin `.kb/`
  that has always published fine**. two files differing only in case are
  legal and ordinary there, and a Linux intake host accepted and committed
  the last two shapes as well -- only a Windows host ever failed on them,
  and it failed late, at write time. three of the four are the rules the
  repo-id bullet above already states for repo-ids -- a case-insensitive
  collision, a trailing `.`, a reserved device name -- now applied to every
  path inside the archive too. and they apply on **this route only**:
  neither `kb publish --pr` nor `--direct` casefolds or normalizes a `.kb/`
  path anywhere, so the same working tree publishes cleanly by either of
  them and is refused by `kb ci-publish`. the two routes can disagree about
  one `.kb/`.
- **`kb ci-publish` now caps every uploaded path at 110 UTF-16 code units.**
  the previous release had no path-length check at all. the cap exists so
  that `federation/<repo-id>/<path>`, checked out under the hub cache root,
  stays within a Windows client's `MAX_PATH` without
  `git -c core.longpaths=true`: 110 is the measured 259-character ceiling
  (260 fails) less a 9-character margin, less 64 reserved for the client's
  own prefix, less `federation/`, less the 64-character repo-id maximum,
  less one separator. ordinary image assets fit: `kb ingest` writes them
  under `<doc-id>/assets/` with a content-addressed basename
  (`<sha256>.png` or `.webp`, 68 or 69 characters), so a realistic
  `arinc-424/assets/<sha256>.png` is 85 and publishes normally. a path that
  does cross 110 is refused `400 ... is N UTF-16 code units` and the refusal
  aborts the **whole upload**, not the one file, so a deeply nested doc-id
  plus a long filename can stop a publish outright. one exemption: when the
  hub declares an asset store (`asset_store: {mode: s3}` in its
  `.kb/config.yaml`) asset files are diverted out of the tree before
  anything is committed, so the cap is skipped for them -- deliberately not
  widened to undiverted assets, because an undiverted asset really is a
  tracked path a Windows client has to check out. `kb publish --pr` /
  `--direct` copy files directly and are not bound by this cap at all.
- the HTTP server no longer trusts `X-Forwarded-For` by default, and that
  changes **who shares a rate-limit bucket**. before 0.21.0 the server ran
  uvicorn with its defaults (`proxy_headers=True`, and `forwarded_allow_ips`
  left unset, which uvicorn resolves to `$FORWARDED_ALLOW_IPS` or
  `127.0.0.1`), so a reverse proxy on localhost -- the
  ordinary nginx / docker-compose shape -- had already rewritten each
  request's client address before either limiter saw it, and both limiters
  keyed per real client with no configuration at all. 0.21.0 passes
  `proxy_headers=False` and makes `CENTER_KB_TRUSTED_PROXIES` (default `0`)
  the single authority on that header, so **a deployment behind a reverse
  proxy that needed no configuration now collapses both the `/intake/publish`
  limiter (30/minute) and the `/ui/login` limiter (5/minute) into one bucket
  keyed on the proxy's own address** -- one caller can exhaust either for
  every tenant, and the symptom on upgrade is mass `429`s, with one
  locked-out operator locking out everyone else. set
  `CENTER_KB_TRUSTED_PROXIES` to the number of proxies you operate in front
  of the server, and only where the server cannot also be reached directly
  (see `docs/deploy-remote-mcp.md`, "Rate-limit key behind a reverse proxy").
  the value is parsed strictly: anything that is not a run of decimal digits
  -- `+1`, `-1`, `1_0`, or a value with surrounding whitespace -- now aborts
  startup with a one-line message instead of silently falling back to `0`.
- no hub cache from before 0.21.0 is reused, but how it is retired depends
  on whether the hub ref carries a credential, and one of the two cases
  leaves a token behind. two changes drive it: the cache directory is now
  keyed on the **credential-free** hub URL, so rotating a token no longer
  strands the old clone under the old key, and a cache whose own git config
  does not set `core.autocrlf=false` is treated as legacy and removed.
  - **credential-free ref** (plain `https://`, `git@…`, local path): the
    key is unchanged, so the pre-0.21.0 directory is found where it always
    was, deleted, and re-cloned in place. this is the case the previous
    wording described.
  - **ref carrying a credential** -- the
    `https://x-access-token:<token>@…` shape the CI templates document:
    the key *changes* (measured, same hub: `89efd43bf123` ->
    `9f33c358c732`), so 0.21.0 clones into a **new** directory and never
    visits the old one. the pre-0.21.0 cache is therefore not discarded;
    it is **left on disk with the old token still in its `.git/config`**,
    under `~/.center-kb/hub/<12-hex>/` (or `$CENTER_KB_HUB_CACHE`). the
    previous release wrote it there -- this release neither wrote it nor
    removes it -- and `kb doctor` will not report it either, because it
    inspects the new cache. **clean it up by hand, and delete only the
    orphan:** in the cache base -- `$CENTER_KB_HUB_CACHE` when that is set,
    otherwise `~/.center-kb/hub/` -- run `git -C <dir> config --local --get
    remote.origin.url` on each `<12-hex>` directory. 0.21.0 strips the
    credential out of every cache it touches, so a directory that still
    answers with a `…:<token>@…` URL is the orphan; a credential-free one
    is live. delete that one, with no `kb`, MCP or web process running, and
    treat any token it held as exposed on that machine. **do not delete the
    base directory itself** -- it does not hold only disposable caches. an
    intake host keeps `intake-status.json` there, the per-`(repo-id,
    commit)` publish-status record `/intake/status` answers from and
    `kb publish` polls after an upload, and the web server keeps its
    `asset-cache/` there. neither of those is re-cloned.

  either way the first run after upgrading re-downloads the whole hub, and
  anything that existed only inside the old cache is gone -- notably an
  unmerged `publish/<repo-id>` branch that was never pushed. if a file under
  a cache is locked while it is being removed (on Windows, a `kb query`, MCP
  or web process still holding `.kb-work/search.sqlite3` open), the command
  exits 1 with a single line naming the directory to delete by hand, instead
  of a traceback.
- the asset store fails loudly where it used to pass quietly. an asset whose
  bytes do not hash to its own content-addressed name is now caught wherever
  it is touched. `kb assets verify` reports it as `[corrupt]` and exits
  non-zero, where the previous release swallowed an unreadable record and
  passed -- so a hub holding one mismatched object turns that command red in
  CI. a record that exists but cannot be read aborts the publish instead of
  being treated as empty. and the hub server's `/assets/<name>` now
  hash-verifies what it is about to serve rather than trusting the name: a
  bad local-tree or disk-cache copy is ignored (and the disk cache entry
  evicted), so that image becomes a `404` unless an object store can supply
  a good copy, and a bad object *from* the store is a `503`. 0.20 served all
  three cases.
- `kb reindex` commits `federation/index.yaml` and nothing else. the
  previous release staged the whole of `federation/`, so "hand-edit
  `federation/`, run `kb reindex` to commit it" worked; it no longer does --
  the hand-edited content is left uncommitted and reindex prints
  `[warn] uncommitted content under federation/ was NOT committed by
  reindex: ...`. commit those paths yourself. note also that `kb reindex`'s
  push is the one hub-write path the governance rules above do not cover: it
  pushes `federation/index.yaml` to a governed hub with no registry check
  and no mode decision. it is not a content route -- nothing else is in the
  commit -- but it is why branch protection on the hub, not the registry, is
  the control that binds.

### Known limitations

- **a governed hub that `gh` cannot open a pull request on has no publish
  route in this release.** measured on 0.21.0, against a hub carrying a
  non-empty `federation/registry.yaml` whose git remote `gh repo view` cannot
  answer for: `kb publish`, `kb publish --pr` and `kb publish --direct` all
  exit 1. both refusal messages point at `kb ci-publish`, and it is not
  a fourth route here -- it runs only inside the child's own GitHub Actions
  job (it needs `ACTIONS_ID_TOKEN_REQUEST_*`), the intake server accepts only
  GitHub Actions OIDC tokens (the issuer
  `https://token.actions.githubusercontent.com` is hardcoded), and it lands
  the content by pushing to `https://github.com/<hub>` and opening the pull
  request through `api.github.com` with a GitHub App token. that route needs
  GitHub at **both** ends. on the previous release this same setup published
  silently, by direct push. what is actually available, in order:
  - **hub on GitHub or GitHub Enterprise, `gh` merely not set up here:**
    install and authenticate `gh` for that host (`GH_HOST=<host>` for
    Enterprise) until `gh repo view` succeeds inside the hub clone, then
    publish with `--pr`. this is the ordinary fix, and the common case.
  - **hub on github.com, publisher is a child repo's CI:** wire the child to
    the intake service and publish from its GitHub Actions job with
    `kb ci-publish`. this one does not exist for an **intermediate hub**
    publishing its `federation/` upward: measured, hub-to-hub publish gets
    the same three refusals (and the same message naming `kb ci-publish`),
    while `kb ci-publish` itself tars `.kb/`, not `federation/`, so it could
    not carry a hub's federation tree even if it ran -- and with `intake:`
    in its config the CLI refuses outright, exit 2. for an intermediate hub
    the only route is `--pr` with a working `gh`, on any host.
  - **hub not on GitHub at all (GitLab, Gitea, self-hosted):** there is no
    route on this release. the only lever is the hub owner removing
    `federation/registry.yaml`, which restores `kb publish --direct` for
    every publisher and gives up the governance the registry was added for. a
    pull-request route for a non-GitHub hub, and refusal messages that stop
    naming `kb ci-publish` to operators who cannot use it, are not in 0.21.0.

  none of this is a security boundary on its own. the remote-less exemption
  above is a convenience for a purely local hub, not a governance control --
  a contributor who already has push rights on the hub can reach the same
  result through an ordinary clone, with `kb publish` writing the entry for
  them. the registry is a mistake guard; branch protection on the hub is the
  control that actually holds.

### Fixed

- `kb doctor` scans past a half-written federation entry instead of stopping
  at the first one, and reports every problem it finds under `federation/`.
- `kb doctor` reports the operator-facing half of the allowlist change: any
  entry, intermediate namespace directory, or `federation/` itself holding
  files a publish would never write is named file by file, with "rotate any
  credential they contain"; a hub clone still storing a credential in its own
  `.git/config` is named too; and a git older than 2.31 is flagged. all
  three are warnings -- `kb doctor` still exits 1 only on an error-level
  finding. the git-version warning is a backstop, not the way to find the
  version floor above: it needs a hub clone in hand and a hub ref that
  carries a credential, and on an old git those two conditions rarely
  coexist.
- every git operation `kb publish` and `kb doctor` perform (clone, fetch,
  pull, push) now goes through the credential helper; tokens no longer
  appear in `remote.origin.url` or in any repr/log line. the cost of
  that is the git 2.31 floor in "Breaking changes" above.
- hub and child scaffolds pin LF line endings via a scaffolded
  `.gitattributes`, so a Windows checkout no longer turns a fresh clone into a
  whole-tree CRLF diff. `.gitattributes` is not in `kb init`'s protected
  set, so a re-run of `kb init` on an existing repo replaces one you had
  written yourself.
- CLI commands raise a shared `KbError` base; `kb publish`, `kb ci-publish`,
  `kb reindex` and `kb doctor` print one line and exit 1 on a refusal
  instead of a traceback.
- scaffolded `docker-compose.yml` and workflow templates pin `center-kb` and
  the container image to the exact version of the CLI doing the scaffolding,
  not `:latest` or a hand-maintained constant. the pin assumes the matching
  release exists: a hub scaffolded by 0.21.0 asks for
  `center-kb==0.21.0` and `…/center-kb:v0.21.0`, so `docker compose up` and
  the publish workflow only work once that tag has been released and both
  artefacts pushed.
