# Spec C: Asset Storage Init & Operations Tooling

**Status:** Approved design — not yet implemented.
**Date:** 2026-07-17
**Scope:** `center-kb` engine — operator tooling for the asset store. Final spec of the image-handling series (A: ingest core — PR #14; B: S3 delivery, divert at the publish boundary — PR #15).

---

## 1. Problem

Spec B shipped the runtime (`asset_store` config, divert on publish, `/assets` serving) but an operator setting up or evolving a hub has no tooling: nothing scaffolds the config block, nothing verifies the store is reachable or complete, and a hub that started with `mode: none` has no assisted path to move its in-git assets to S3.

## 2. Scope decisions (supersede the original design sketch)

Spec B's divert-at-publish-boundary architecture obsoleted several parts of the original plan:

- **Profiles collapse to `none | s3`.** The old `s3-token` profile existed for a GitHub-Actions/OIDC pipeline that no longer exists. Credentials are boto3's standard env chain wherever publish/serve runs; R2/MinIO/static tokens are just `mode: s3` with an `endpoint` and env creds.
- **No `assets-on-merge.yml`** — there is no merge-time workflow to scaffold.
- **No Terraform stub.** Cloud provisioning is a documented checklist verified by `kb doctor`, not shipped IaC.
- **No git-LFS scaffolding.** Spec A compresses assets, so a `mode: none` corpus fits plain git; `kb doctor` warns past a size threshold and QUICKSTART documents LFS as a manual opt-in.
- **Migration is forward-only** (`none → s3`); rollback is documented manual steps (the local-first `/assets` resolver keeps previously in-git assets serving during and after any switch).

## 3. `kb init --assets <none|s3>`

- Valid only with the `hub` kind (explicit `--kind child --assets …` or a child repo → clear error; the child flow never involves asset storage — bytes ride the publish transport).
- Follows the existing protected-file pattern (`initcmd._record_kind`): **append-only** — when `.kb/config.yaml` lacks an `asset_store:` block, append one; when the block exists, leave the operator's config untouched and say so. Never rewrites values.
  - `--assets none` appends the explicit default block (`mode: none`).
  - `--assets s3` appends the block with `mode: s3` and empty `bucket` / `region` / `endpoint` plus guiding comments.
- Omitting `--assets` keeps today's behavior exactly (no block appended).
- "Next steps" output extends per mode — s3: fill `bucket` (+ `endpoint` for non-AWS), export credentials (env chain), `pip install "center-kb[s3]"`, run `kb doctor`.

## 4. Guided `/kb-init` command

Template command files matching the existing per-assistant pattern, added to `COMMON_TEMPLATES` in `initcmd.py`:

- `.claude/skills/kb-init/SKILL.md` + `.claude/commands/kb-init.md`
- `.github/prompts/kb-init.prompt.md`
- `.cursor/commands/kb-init.md`

The command walks the operator through:

1. **Role** — hub (aggregation + read/search server: hosts `federation/`, serves `/ui` + `/api` + `/mcp`, receives publishes, owns the asset store) or child (authoring repo: ingests, summarizes, publishes; never asked about assets).
2. **Assets mode** (hub only) — `none` (assets in git, zero cloud, recommended first run) or `s3` (object store; needs a bucket + creds).
3. Runs `kb init --kind <role> [--assets <mode>]`.
4. Per-mode next steps, ending with `kb doctor` to verify.

## 5. `kb doctor` storage checks

New `check_asset_store(kb_dir, handle) -> list[Issue]` in `doctor.py`, composed into the CLI `doctor` command like the existing checks:

- **`mode: s3`:**
  - `bucket` empty → error.
  - boto3 not importable → error naming `pip install "center-kb[s3]"`.
  - Reachability probe: one `store.exists()` call on a well-known nonexistent key — a clean "not found" proves bucket + creds + endpoint work (OK); an `AssetStoreError` (auth/network/misconfig) → error with the underlying message.
- **`mode: none`:** sum the bytes of `**/assets/*` under the hub's `.kb/` and `federation/`; above `ASSET_SIZE_WARN_BYTES = 100 * 1024 * 1024` → warning suggesting `mode: s3` (or manual LFS).
- No config block → no issues (default `none` semantics apply).

## 6. `kb assets` commands

New module `src/center_kb/assetcmd.py`, registered as a typer sub-app (`kb assets migrate`, `kb assets verify`). Both operate on the hub clone (resolve via the existing hub handle machinery) and accept a store test seam like spec B's commands.

### 6.1 `kb assets migrate` — none → s3 backfill

- Preconditions: `mode: s3` configured; store reachable (same probe as doctor); otherwise exit with the doctor-style error.
- For each rid directory under `federation/`: run spec B's `assetstore.divert_and_record(dest, store)` — uploads every in-git `assets/<sha>.<png|webp>`, strips the files, merges `_assets.yaml`. Content-addressed puts skip existing keys, and upload precedes unlink, so the command is **idempotent and has no image-down window** (the serving resolver is local-first during the transition).
- Scope is `federation/` rids only. The hub's own `.kb/<doc-id>/assets/` stays in place: `_assets.yaml` records exist per-rid under `federation/` and nowhere else, and the local-first `/assets` resolver serves hub-local files without any migration. (A hub that publishes its own `.kb` into `federation/` gets those assets diverted by the normal spec B publish path.)
- One commit at the end when the tree changed: `assets: migrate to object store`. Prints per-rid counts; re-run is a no-op.

### 6.2 `kb assets verify` — coverage check (both modes)

- **Record coverage:** every entry in every `_assets.yaml` must resolve — in s3 mode via `store.exists()`, in none mode as a local file. Missing → reported, exit 1.
- **Reference coverage:** every `assets/<sha256>.<png|webp>` markdown ref committed under `federation/` (and hub `.kb/`) must resolve to a local file OR a record entry backed by the store. Dangling → reported, exit 1.
- **Orphans:** record entries no markdown references → informational listing only (no GC — spec B §9).
- Exit codes follow doctor's convention (0 OK, 1 errors).

## 7. QUICKSTART-hub.md

New storage section:

- What `mode: none` means and when it is enough (compressed corpus in plain git).
- The s3 setup checklist: create a **private** bucket, block public access, scoped credentials limited to Get/Put/Head on the configured prefix, env vars (AWS chain; `endpoint` for MinIO/R2), `pip install "center-kb[s3]"`, `kb init --assets s3` (or edit the block), `kb doctor`, then `kb assets migrate` if assets already exist in git.
- Manual rollback (s3 → none): download each recorded `assets/<sha>` back into its rid tree, delete `_assets.yaml` files, flip `mode: none`, commit — local-first serving makes the order forgiving.
- Optional git-LFS note for operators who want `mode: none` with a large corpus.

## 8. Error handling

- `kb init --assets` with kind child → typer error, exit 2, message states assets are hub-only.
- Existing `asset_store:` block → init reports "left unchanged" (protected data), exit 0.
- `migrate`/`verify` with unreachable store or missing boto3 → the doctor-style error message, exit 1; migrate never deletes a file whose upload did not complete (spec B's divert ordering), and a mid-run failure leaves a re-runnable state (already-diverted rids keep their merged records; the failed rid's working tree is restored by the spec B cleanup pattern before the command exits — no binaries can be committed by a later unrelated commit).
- `verify` never mutates anything.

## 9. Testing

Hermetic — no boto3, no network:

- Init: append-block semantics for both modes, block-exists no-op, child+`--assets` error, omitted flag unchanged — extending `tests/test_init.py`.
- Templates: `/kb-init` files present for all assistants and rendered by `init_repo` — following `tests/test_templates.py`.
- Doctor: each s3 issue (empty bucket, missing boto3 via import-block, probe failure via failing store seam, probe OK via `MemoryStore`), none-mode size warning across the threshold — extending `tests/test_doctor.py`.
- Assetcmd: migrate on a fixture hub clone with in-git assets (uploads to `MemoryStore`, strips, records, commits, second run no-op), verify happy/missing-record/dangling-ref/orphan cases — new `tests/test_assetcmd.py`.
- Existing suites stay green untouched.

## 10. Decisions log

| Decision | Choice |
|---|---|
| Profiles | `none \| s3` only — `s3-token` collapsed (env-chain creds + endpoint cover it) |
| Provisioning | Checklist in QUICKSTART + doctor verification; no Terraform |
| `mode: none` storage | Plain git; doctor warns > 100 MB; LFS documented opt-in only |
| Migration | Forward-only `none → s3` + `verify`; rollback documented manual |
| Config writes | Append-only into protected `.kb/config.yaml`, mirroring `_record_kind` |
| Guided setup | `/kb-init` templates for Claude/Copilot/Cursor via `COMMON_TEMPLATES` |
