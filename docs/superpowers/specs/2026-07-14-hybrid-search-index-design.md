# Hybrid Search Index (SQLite FTS5 + vec0) — Design

**Date:** 2026-07-14
**Status:** Approved pending review
**Scope target:** ~100k sections, nhiều repo trong federation, local-only (không server ngoài)

## 1. Bối cảnh & vấn đề

Search hiện tại (`query.search`) mỗi query:

1. `load_federation()` — parse `_meta.yaml` + `index.yaml` mỗi repo.
2. `_gather_candidates()` — parse **mọi** `_manifest.yaml` của mọi doc (O(N docs) YAML I/O).
3. Tokenize title+summary toàn corpus, build `BM25Plus` (rank_bm25) trong RAM từ đầu.
4. Semantic là bước fallback: `ensure_index` chạy **lazy trong query** — cold start lần đầu ăn cả chi phí load model + embed toàn corpus; KNN loop từng repo, mỗi repo một DB (`embeddings-<rid>.db`).

Bottleneck ở 100k section:

- YAML parse per-query là chi phí lớn nhất (hàng nghìn file manifest mỗi lần search).
- BM25 rebuild per-query: corpus tokenize + BM25Plus init O(N).
- Cold-start embed dồn vào query đầu tiên thay vì build-time.
- BM25 per-process RAM: mỗi CLI invocation trả lại toàn bộ chi phí (process ngắn hạn).

## 2. Goals / Non-goals

**Goals**

- Query latency không phụ thuộc O(N sections) parse/rebuild — mục tiêu < 100ms cho keyword leg, < 300ms cho hybrid (không tính lần refresh index).
- Index persistent trên disk, incremental theo content-hash (pattern đã có ở `embed.py`).
- Hybrid ranking: FTS5 BM25 + KNN, trộn RRF — thay routing fallback hiện tại.
- Build eager tại `kb reindex` và sau `kb publish` (direct mode); query giữ lazy freshness-check rẻ.
- Zero-server: chỉ SQLite (FTS5 built-in + sqlite-vec đã có trong stack).
- Degradation mềm: thiếu `fastembed` → FTS-only; index hỏng → rebuild tự động.

**Non-goals**

- Không Elasticsearch/Tantivy/daemon.
- Không đổi format `.kb/` hay federation layout — index là **derived cache cục bộ**, không bao giờ commit.
- Không tối ưu chất lượng ranking sâu (tuning RRF k, threshold) — đo sau khi có KB thật.
- Không thay `get_section()` — path lookup trực tiếp đã O(1), giữ nguyên.

## 3. Kiến trúc

### 3.1 Một DB duy nhất cho cả hub

File: `<hub.root>/.kb-work/search.db` — cạnh convention `embeddings-<rid>.db` hiện tại, ngoài phạm vi `gitio.commit_paths` (không bị commit).

Lý do một DB thay vì per-repo:

- **IDF toàn cục** — BM25 rank đúng trên cả federation, không lệch thống kê per-repo.
- **1 query FTS + 1 query KNN** mỗi search, thay vì loop N repo (hiện `_semantic_fallback` chạy N lần KNN).
- Một pipeline sync duy nhất, RRF trộn theo rank nên không cần chuẩn hoá score.

### 3.2 Schema

```sql
-- metadata index: schema version, embedder model/dim
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
-- keys: schema_version, embed_model, embed_dim

-- fingerprint per repo: bỏ qua repo không đổi mà không cần parse manifest
CREATE TABLE repos(
    repo_id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL      -- sha256(_meta.yaml bytes + index.yaml bytes)
);

-- toàn bộ metadata section — query KHÔNG cần đọc manifest nữa
CREATE TABLE sections(
    id INTEGER PRIMARY KEY,
    repo_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    section_id TEXT NOT NULL,
    title TEXT NOT NULL,           -- sec.title
    file TEXT NOT NULL,            -- sec.file (đọc L2 content cho top results)
    doc_revision TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL,    -- sha256(_section_text) — trigger re-embed + re-FTS
    UNIQUE(repo_id, doc_id, section_id)
);

-- tag filter ở tầng SQL (giữ semantics _filter_tags: tag doc hoặc doc_id)
CREATE TABLE doc_tags(
    repo_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    tag TEXT NOT NULL,             -- lowercase; doc_id cũng insert như một tag
    PRIMARY KEY(repo_id, doc_id, tag)
);

-- FTS5 thường (lưu text) — rowid = sections.id
CREATE VIRTUAL TABLE fts USING fts5(
    title, summary, body_head,
    tokenize='unicode61'
);

-- vec0 — rowid = sections.id (giữ nguyên pattern embed.py)
CREATE VIRTUAL TABLE vec_sections USING vec0(embedding float[<dim>]);
```

- `body_head` = 500 ký tự đầu L2 (`_L2_HEAD_CHARS`) — cùng text đang dùng cho embedding (`_section_text`), keyword match sâu hơn title+summary.
- FTS5 thường (không contentless): lưu text trong index (~1KB/section, ~100MB ở 100k — chấp nhận). Contentless (`content=''`) bị loại vì không hỗ trợ DELETE/UPDATE trực tiếp (cần SQLite ≥ 3.43 `contentless_delete=1` — ràng buộc version không đáng đổi lấy tiết kiệm disk).
- Connection: WAL mode + `busy_timeout` (web/MCP đọc song song trong lúc CLI refresh).
- `vec_sections` chỉ tạo khi có embedder; `embed_dim`/`embed_model` ghi vào `meta` — đổi model/dim ⇒ drop + rebuild bảng vec.

### 3.3 Module mới: `center_kb/searchdb.py`

Gom index lifecycle + query. `embed.py` giữ `Embedder`, `_FastEmbedder`, `default_embedder`, `_section_text`, constants; phần `_connect/ensure_index/semantic_search` per-repo cũ **xoá** (thay bằng searchdb). API:

```python
def sync(hub: HubHandle, embedder: Embedder | None) -> SyncReport
    # incremental: repo fingerprint → skip/diff; trả về số section thay đổi

def fts_search(conn, text, tags, k) -> list[tuple[int, float]]        # (section_rowid, bm25)
def knn_search(conn, embedder, text, tags, k) -> list[tuple[int, float]]
def load_sections(conn, rowids) -> dict[int, SectionRow]
```

### 3.4 Sync (incremental)

```
for repo in load_federation(hub.federation_dir):
    fp = sha256(_meta.yaml bytes + index.yaml bytes)
    if repos.fingerprint == fp: continue          # repo không đổi — 0 manifest parse
    # repo đổi: parse manifests, diff theo content_hash (y hệt ensure_index cũ):
    #   - section mới/đổi hash → update sections + fts + (batch) re-embed vec
    #   - section biến mất → delete cả ba bảng
    #   - rebuild doc_tags cho repo
    repos.fingerprint = fp
drop repo rows không còn trong federation
```

- Fingerprint đúng vì `_meta.yaml.published_at` đổi mỗi lần publish — mọi thay đổi nội dung repo đi qua publish/mirror đều làm fp đổi.
- Embed theo batch một lần cho mọi section thay đổi (như `ensure_index` hiện tại).
- `embedder is None` → sync vẫn chạy FTS/sections/tags, bỏ qua vec (đánh dấu `meta.embed_model=''`; khi embedder xuất hiện lần sau, các row thiếu vec được embed bù — track bằng `LEFT JOIN vec_sections` thiếu rowid).

### 3.5 Trigger

| Điểm | Hành vi |
|---|---|
| `kb reindex` | sau khi rebuild `federation/index.yaml`: gọi `searchdb.sync` (eager, kèm embeddings) |
| `kb publish` direct mode | sau publish thành công: `searchdb.sync` trên hub clone của operator |
| `kb publish` PR mode | **không** build (nội dung chỉ vào hub sau merge; consumer lazy check lo phần còn lại) |
| Mọi query (`search`) | lazy check: so fingerprint từng repo (đọc 2 file nhỏ/repo — không parse manifest); lệch → sync incremental rồi query |

Consumer machine (hub clone qua TTL pull): lần đầu build full là one-time; các lần sau chỉ diff repo đổi.

### 3.6 Query flow (hybrid RRF)

```python
K_LEG = 50   # top-k mỗi leg
RRF_K = 60   # hằng số RRF chuẩn

def search(hub, text, tags=None, budget=2000, semantic=False, embedder=None):
    conn = _open_fresh(hub, embedder)          # lazy freshness check + sync nếu lệch
    fts_hits = fts_search(conn, text, tags, K_LEG)
    knn_hits = knn_search(conn, embedder, text, tags, K_LEG)   # [] nếu không có embedder
    fused = rrf_merge(fts_hits, knn_hits)      # score = Σ 1/(RRF_K + rank_leg)
    # budget packing giữ nguyên logic hiện tại:
    #   đọc L2 content (_candidate_content) theo thứ tự fused, cắt theo token budget
```

- `rrf_merge`: score từng rowid = tổng `1/(60+rank)` trên các leg chứa nó. Sort giảm dần.
- `QueryResult.match_mode`: `"keyword"` (chỉ FTS leg), `"semantic"` (chỉ KNN leg), `"hybrid"` (cả hai). `score` = RRF score.
- Tag filter:
  - FTS leg: `JOIN doc_tags` trong SQL — filter trước ranking, không mất recall.
  - KNN leg: vec0 không pre-filter được — over-fetch `k*4`, filter bằng `doc_tags` sau, cắt còn `K_LEG`.
- KNN leg vẫn áp `SEMANTIC_MIN_SCORE` (lọc nearest-but-irrelevant) trước khi vào RRF.
- FTS leg lọc `bm25 score` hợp lệ (FTS5 MATCH đã đảm bảo có term chung — workaround BM25Plus baseline-score hiện tại xoá được).
- Query text → FTS5 MATCH string: escape/quote từng token (`'"tok1" OR "tok2"'`) — user input không được inject cú pháp FTS (NEAR, cột filter…). Dùng lại `tokenize()` hiện có để tách token.
- Tham số `semantic: bool` giữ cho tương thích chữ ký (cli/mcp/web đang truyền), nhưng hybrid luôn chạy cả hai leg — flag chỉ còn ý nghĩa: `semantic=True` + không có embedder ⇒ warning rõ thay vì im lặng.
- `SEMANTIC_FALLBACK_THRESHOLD` xoá (routing không còn).

### 3.7 Ảnh hưởng call site

`cli.py`, `mcp.py`, `web/api.py`, `web/ui.py` gọi `search()` — chữ ký giữ nguyên, không đổi call site. `QueryResult` giữ nguyên field. Semantics `score` đổi (RRF thay BM25/cosine) — web UI hiển thị score cần xem lại nhãn (cosmetic, ngoài scope nếu không vỡ layout).

## 4. Migration & tương thích

- `embeddings-<rid>.db` cũ: cache thuần — bỏ rơi, không đọc. Dọn: `sync` xoá `embeddings-*.db` trong `.kb-work/` khi thấy (best-effort).
- `search.db` có `meta.schema_version`; version lệch hoặc DB hỏng (sqlite error khi mở/query) → xoá file, rebuild full. Không bao giờ để index hỏng chặn search: rebuild fail → fallback đường cũ? **Không** — giữ một đường code; rebuild fail thì raise lỗi rõ ràng (DB nằm trên disk cục bộ, fail = hết disk/permission, user phải biết).
- `rank_bm25` dependency: gỡ khỏi dependencies.
- Docs/templates (`QUICKSTART-*.md`, copilot instructions) nhắc "BM25 search over the summaries" → cập nhật mô tả hybrid.

## 5. Error handling & degradation

| Tình huống | Hành vi |
|---|---|
| Không cài `fastembed` | FTS-only, log info (như `default_embedder` hiện tại) |
| Model download fail | FTS-only, warning |
| KNN leg lỗi runtime | catch + warning, trả FTS leg (giữ tinh thần "embedding best-effort" hiện tại) |
| FTS leg lỗi / DB hỏng | xoá `search.db`, rebuild một lần; vẫn fail → raise |
| Federation trống | trả `[]` như hiện tại |
| Hai process cùng sync | WAL + busy_timeout; sync idempotent (content-hash) — thua race chỉ tốn công, không sai dữ liệu |

## 6. Testing

- **Unit `searchdb`**: sync tạo/refresh/xoá rows theo fingerprint + content-hash; fingerprint skip không đụng manifest (spy/counter file reads); schema_version mismatch rebuild; embedder None → FTS-only rồi embed bù khi có embedder.
- **Unit query**: RRF merge đúng thứ hạng (case: chỉ FTS, chỉ KNN, cả hai, tie); tag filter cả hai leg; budget packing giữ hành vi cũ (test hiện có phải pass sau khi điều chỉnh score expectation); FTS input escaping (query chứa `"`, `NEAR`, cột syntax không nổ).
- **Integration**: build KB tạm nhiều repo → search end-to-end; publish direct → sync eager chạy; sửa 1 section → chỉ section đó re-embed.
- **Perf smoke** (không gate CI): script tạo KB synthetic ~50–100k section, đo query lạnh/nóng — mục tiêu §2.
- Test embedder giả (`embedder=` injectable — đã có pattern trong `search()`).

## 7. Thứ tự triển khai (phác)

1. `searchdb.py`: schema + sync + fts/knn/load (kèm unit tests) — chưa nối vào query.
2. `query.search` chuyển sang searchdb + RRF; xoá `_gather_candidates`/BM25Plus/`_semantic_fallback`; sửa tests.
3. Nối trigger `kb reindex` + `kb publish`; dọn `embed.py`; gỡ `rank_bm25`; cập nhật docs/templates.
4. Perf smoke script + tuning nhỏ (K_LEG, indexes) nếu cần.
