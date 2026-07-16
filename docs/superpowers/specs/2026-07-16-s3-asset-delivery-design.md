# Spec B: S3 Asset Delivery

**Status:** Approved design — not yet implemented.
**Date:** 2026-07-16
**Scope:** `center-kb` engine, hub-side asset delivery. Second of three specs (A: ingest core — merged as PR #14; B: this spec; C: init/profile tooling — deferred, see §9).

---

## 1. Problem

Spec A stores images as plain files in `.kb/<doc-id>/assets/<sha256>.<png|webp>` and every publish transport copies them into hub git verbatim. Binaries accumulate in the hub repository's history forever: clones grow, the 50MB intake tar cap tightens, and GitHub is a poor blob store. The hub needs an object store for asset bytes while git stays text-only.

## 2. Key architectural decision — divert at the publish boundary

The original design sketch moved bytes to S3 with a GitHub Actions job on PR merge (staging buckets, `[skip ci]` loop guards, an ordering window where merged text references not-yet-uploaded images).

All three publish transports already pass asset bytes through code this project owns **before** anything reaches hub git:

- **intake** — child CI uploads a tar; the hub server (`intake_publish`) extracts it, commits a `publish/<rid>` branch, opens the PR. The server holds secrets already (GitHub App PEM).
- **direct / pr** — the operator's machine snapshots `.kb/` into a local hub clone (`_snapshot`), then pushes or opens a PR.

So the design diverts assets at that boundary instead: strip `assets/**` from the tree that goes to git, upload those bytes to S3 right there, commit text-only plus a tiny per-rid record. Bytes are in S3 before any commit exists — no merge automation, no staging, no CI-loop guard, no 404 window. Decided over the merge-time-Actions and hybrid alternatives.

## 3. Configuration

New `asset_store` block in the hub config (`config-hub.yaml`), parsed into the server/publish config:

```yaml
asset_store:
  mode: none        # none | s3
  bucket: ""        # required for s3
  region: ""        # optional (AWS default chain applies)
  endpoint: ""      # optional — MinIO / Cloudflare R2 etc.
  prefix: "assets/" # key prefix inside the bucket
```

- `mode: none` (default) — spec A status quo, zero behavior change anywhere.
- Credentials never live in this config. `S3Store` uses boto3's standard chain (env vars, instance role, profile).
- Spec C scaffolds this block at `kb init`; spec B defines its shape and consumes it.

## 4. `assetstore.py` — the store seam

New module `src/center_kb/assetstore.py`:

- `AssetStore` interface: `exists(name) -> bool`, `put(name, data: bytes) -> None`, `get(name) -> bytes | None`. `name` is always the bare content-addressed filename `<sha256>.<png|webp>`; the store prepends the configured prefix.
- `S3Store` — lazy `import boto3` inside the constructor; missing boto3 raises a clear error naming the install extra (`pip install "center-kb[s3]"`) at first use, not at module import. `put` sets `Content-Type` (png/webp) and `Cache-Control: private, max-age=31536000, immutable`, and skips the upload when the key already exists (`head_object`) — idempotent, natural dedupe.
- `MemoryStore` — dict-backed, for tests.
- `from_config(cfg) -> AssetStore | None` — `None` when `mode: none`.

Dependency: new optional extra `s3 = ["boto3>=1.34"]` in `pyproject.toml`.

## 5. Diverting assets on publish

One shared helper, used by every transport:

`divert_assets(tree_root: Path, store: AssetStore) -> list[str]` — walks `*/assets/<sha256>.<png|webp>` under a snapshot tree; for each file: `exists` → skip upload, else `put`; then delete the file from the tree. Returns the sorted relative paths of diverted assets.

The caller maintains `_assets.yaml` at the rid root (a `models.AssetsRecord` — the only new git-tracked artifact, plain text, tiny). **Record updates are a merge, never a plain write:** intake tars are incremental, so the tar only contains assets that changed this publish. The record = (existing record at the destination, if any) ∪ (newly diverted paths) − (paths in this publish's deletes list). For intake the merged record is written into the extracted tree before `build_manifest`, so it syncs like any text file; for `_snapshot` the full `.kb/` tree is present, so the merge degenerates to the complete current list.

Wired in exactly two places:

1. `intake.intake_publish` — on the extracted `tmp_kb`, after `safe_extract`, before `hashsync.apply_sync`.
2. `publish._snapshot` — covers both `direct` and `pr` modes (the publishing machine needs S3 write credentials; it already holds hub push rights, same trust level).

**Failure is loud and early:** any upload error aborts the publish/intake before any git commit. Nothing binary ever falls back into git silently. Keys already uploaded before the failure are harmless — content-addressed and idempotent, the retry reuses them.

## 6. Manifest synthesis — no re-upload churn

The child computes its upload delta by diffing its local manifest against the hub's (`hub_manifest` → `hashsync.build_manifest`). With bytes absent from the hub tree, every asset would look "missing" and be re-sent on every publish.

Fix: the hub synthesizes manifest entries for diverted assets from `_assets.yaml`. By spec A construction the filename sha **is** the sha256 of the file bytes, so the synthesized entry (`<relpath> → <sha from filename>`) is exact without touching any bytes. Synthesis lives in a `hashsync` helper and is applied in `intake.hub_manifest` (and any other place a hub-side manifest is built for diffing). The child's next diff then sees assets unchanged and skips them; `_assets.yaml` itself is an ordinary text file that syncs normally.

Deletes: a child that stops referencing an asset drops it from its manifest; the normal delete flow removes the `_assets.yaml` entry. S3 keys are not garbage-collected (§9).

## 7. Serving — S3 fallthrough behind the existing route

Spec A's `/assets/{name}` route resolves via `_find_asset` (local dirs, positive-hit cache, threadpool). Spec B extends the resolution chain:

1. local hit (`.kb/`, `federation/`) → serve (keeps in-git assets from `mode: none` hubs working, and makes later migration a resolver-only change);
2. miss + store configured → `store.get(name)`; hit → write to disk cache `<hub cache base>/asset-cache/<name>` (content-addressed → immutable, no invalidation), serve; subsequent requests hit the cache path. The hub cache base is the same directory the hub clone cache lives under — `~/.center-kb/hub` by default, overridable with `CENTER_KB_HUB_CACHE` — so the asset cache defaults to `~/.center-kb/hub/asset-cache/<name>`;
3. store raised → 503; store miss → 404. Disk-cache write failure → still serve the fetched bytes, log a warning.

Auth, name validation, headers, and threadpool behavior are unchanged from spec A.

## 8. Testing

Hermetic — no boto3, no network in CI:

- `MemoryStore` injected through every seam: divert helper (upload + tree-strip + record), intake end-to-end (tar with assets → text-only git tree + populated store + `_assets.yaml`), publish `_snapshot` divert, route fallthrough (local miss → store hit → disk cache → second request served from cache; store error → 503).
- `S3Store` unit-tested against a stubbed client object injected in place of the boto3 client (no moto dependency): put sets content-type/cache-control, existing key skips upload, missing boto3 raises the extra-naming error.
- Manifest-synthesis round-trip: after a diverted publish, child manifest vs hub synthesized manifest diff is empty → second publish is a no-op.
- Existing publish/intake/hashsync suites stay green untouched with `mode: none`.

## 9. Non-goals (deferred)

- **Presigned-URL redirect** for bandwidth/CDN offload — cut per YAGNI; hub-proxy with immutable caching suffices until proven otherwise.
- **S3 garbage collection** of unreferenced keys — content-addressed keys are immutable and cheap; a future `kb assets gc` can reconcile against all `_assets.yaml` files.
- **Spec C** — `kb init --assets` scaffolding, storage profiles, `kb doctor` checks, `kb assets migrate/verify` (`none → s3` backfill is: upload existing in-git assets, flip mode, strip — the local-first resolver makes it safe in either order).
- **Licensing** — private serving controls access; whether ICAO/ARINC terms permit storing excerpts in S3 must be confirmed with the subscription owner.

## 10. Decisions log

| Decision | Choice |
|---|---|
| Where bytes divert | Publish boundary (intake server + `_snapshot`), not merge-time GitHub Actions |
| S3 client | boto3 via optional `s3` extra; lazy import; standard cred chain |
| Serving | Hub-proxy only, local-first, disk cache; presigned redirect deferred |
| Re-upload prevention | `_assets.yaml` per rid + manifest synthesis (filename sha == content sha) |
| Failure mode | Upload error aborts publish before commit; binaries never silently enter git |
| `mode: none` | Bit-for-bit spec A behavior |
