# AERO-KB Phase 3 (Scale) — Design

**Ngày:** 2026-07-10
**Nguồn:** `AERO-KB_Architecture_v0.1.pdf` (spec kiến trúc tổng thể, v0.1 — 09/07/2026), roadmap §13 Phase 3, §9 Federation, §10.3 khai báo MCP
**Phạm vi:** kb-hub federation + CI publish index; remote HTTP MCP cho BA không clone repo; embedding search (sqlite-vec).

## 1. Mục tiêu & tiêu chí hoàn thành

Trọng tâm Phase 3: **mở rộng KB ra ngoài một repo** — tài liệu domain sống một bản duy nhất ở kb-hub, nhiều repo tham gia federation mà token cost không tăng đáng kể, BA truy vấn được không cần clone repo.

Tiêu chí hoàn thành (từ roadmap §13, cụ thể hóa):

1. ≥ 2 repo tham gia federation: query từ repo A trả về tài liệu domain của hub (full L2) lẫn summary L1 của repo B, kèm citation đúng nguồn — kiểm chứng bằng demo script + E2E test.
2. `kb doctor` phát hiện được index lệch hub (CI publish fail) và hub cache stale — chạy được định kỳ trong CI.
3. BA truy vấn qua remote HTTP MCP với bearer token, không clone repo, 3 tool giữ nguyên signature.
4. Embedding search hoạt động như bước 3 của routing (sau tag match + BM25), thuần local, không hạ tầng ngoài; thiếu dependency thì hệ thống chạy tiếp bằng BM25, không lỗi.
5. Block `kb-context` Phase 2 đã phát hành trong ticket Jira **tiếp tục resolve được nguyên vẹn** — không migration.

Ngoài phạm vi Phase 3 (deferred, ghi lại để đợt sau):

- **Codebase extraction** (OpenAPI, schema, module list tự sinh trong CI — §8 spec kiến trúc): độc lập hoàn toàn với hub, làm đợt riêng.
- OAuth/SSO cho HTTP MCP (bearer token đủ cho mạng nội bộ giai đoạn này).
- Đẩy các repo demo lên GitHub private (bước thủ công tùy chọn sau khi merge).

## 2. Các quyết định thiết kế đã chốt

| # | Quyết định | Lựa chọn | Lý do |
|---|---|---|---|
| 1 | Mô hình federation | **Hub là repo Git thụ động, client tự merge** (phương án A) | Đúng nguyên văn §9; giữ docs-as-code, offline chạy bằng cache; không thêm hạ tầng thường trực. Loại hub-as-service (phá triết lý file-thuần §4, SPOF) và peer-to-peer (duplicate tài liệu domain, kết nối n²). |
| 2 | Hạ tầng thử nghiệm | **Repo Git demo tạo mới** (hub + 2 repo con) qua script + E2E test | Giai đoạn PoC chưa có repo công ty tham gia; demo script là bằng chứng vận hành cho tiêu chí ≥2 repo. |
| 3 | Truy cập hub | **`--hub` nhận git URL hoặc path; tool tự clone/pull vào cache** `~/.aero-kb/hub/<sha1-url>/` | Đúng mẫu `.mcp.json` §10.3 — ai clone repo là dùng được. Loại submodule (dễ quên update) và path thuần (mỗi người tự clone). |
| 4 | CI publish | **Lệnh `kb publish` push thẳng vào hub** + GitHub Actions mẫu | Index là dữ liệu máy sinh, không cần review; publish qua PR gây ứ đọng → index stale, đúng rủi ro §14. Race giữa 2 CI: pull --rebase + retry ≤3. |
| 5 | Va chạm doc-id local ↔ hub | **Local thắng khi query; `kb doctor` exit 1 + in hướng dẫn dọn dẹp** | Repo đang chạy không đổi hành vi đột ngột vì commit ở hub; collision thành việc-phải-làm hiện trên CI. Loại hub-thắng (một commit hub làm gãy kb-context đang pin bản cục bộ — vi phạm chống drift §12) và hard-error (hub thành điểm gãy của hệ thống thiết kế để chạy offline). |
| 6 | Pin version hai nguồn | **Thêm trường optional `hub_version` cạnh `version`** trong block kb-context | Block Phase 2 hợp lệ nguyên vẹn (tiêu chí 5); parser chỉ mở rộng; khớp Phụ lục A. Loại pin theo từng ref (phá format, phải migrate ticket đã phát hành — YAGNI vì topology cố định 1 hub) và một trường duy nhất (mất pin tri thức cục bộ). |
| 7 | HTTP MCP | **Streamable HTTP của SDK chính thức + bearer token qua `AERO_KB_HTTP_TOKEN`** | Đổi transport không đổi code tool — đúng lời hứa spec Phase 2 §2.1. Token thiếu lúc khởi động http → fail fast (tài liệu có bản quyền, không có chế độ "tạm không auth"). |
| 8 | Embedding search | **sqlite-vec + fastembed (ONNX, `bge-small-en-v1.5`), dependency group `[embed]` tùy chọn** | Đúng chỉ định §7 (local, không hạ tầng ngoài); fastembed ~100MB không kéo PyTorch ~2GB; nội dung KB tiếng Anh nên không cần model đa ngữ; thiếu `[embed]` → fallback BM25, không bao giờ lỗi. |
| 9 | Lưu index embedding | **`.kb-work/embeddings.db`, không commit; làm tươi tăng dần theo content-hash** | Tránh binary churn trong git; chỉ re-embed section đổi nội dung; `kb build` làm tươi nếu index tồn tại để CI giữ nóng. |

## 3. Kiến trúc module

Giữ nguyên tắc Phase 2: mọi thứ mới là adapter/tầng quanh engine hiện có, phụ thuộc một chiều.

```
src/aero_kb/
├── hub.py          # MỚI — resolve --hub (URL/path) → clone cache, pull theo TTL, offline fallback
├── federation.py   # MỚI — đọc federation/<repo>/ của hub; model FederatedIndex
├── publish.py      # MỚI — snapshot L0+L1 → federation/<repo-id>/ → commit + push (retry)
├── embed.py        # MỚI — embedding index sqlite-vec, import lười, fake-able cho test
├── mcp.py          # sửa — --transport {stdio,http}, --host/--port, middleware bearer token; kích hoạt --hub
├── query.py        # sửa — search hợp nhất 3 lớp (local + hub .kb + federation); bước 3 embedding fallback
├── resolve.py      # sửa — resolve per-ref theo nguồn (version | hub_version)
├── kbcontext.py    # sửa — trường optional hub_version, parse/render tương thích ngược
├── doctor.py       # sửa — check hub: cache stale, index lệch, collision doc-id (kèm hướng dẫn dọn dẹp)
├── gitio.py        # sửa — thêm clone/pull/push (hiện chỉ có read-at-rev)
└── cli.py          # sửa — lệnh publish; --hub cho query/resolve/doctor/context; --semantic cho query

scripts/
├── demo-federation.sh / .ps1   # MỚI — dựng hub + 2 repo demo, chạy trọn vòng federation
.github/workflows/
└── kb-publish.yml              # MỚI — mẫu: merge vào main có đổi .kb/ → kb publish
```

## 4. Cấu trúc repo kb-hub

```
kb-hub/
├── .kb/                          # tài liệu domain dùng chung — MỘT bản duy nhất
│   ├── index.yaml                #   L0 của hub
│   └── arinc-424/ ...            #   L1/L2/L3 — y hệt cấu trúc .kb/ hiện tại
├── federation/                   # máy sinh, không review
│   ├── <repo-id>/
│   │   ├── index.yaml            #   bản sao L0 của repo con
│   │   ├── manifests/<doc>.yaml  #   bản sao L1 từng tài liệu cục bộ
│   │   └── _meta.yaml            #   repo_id, source_url, source_commit, published_at
│   └── ...
└── README.md
```

Hub tái dùng nguyên vẹn format `.kb/` — mọi code Phase 1+2 đọc được hub không cần format mới. `federation/` chỉ chứa L0+L1, **không bao giờ** chứa L2/L3 của repo con (đúng "index của các index" §9). `_meta.yaml.source_commit` là chốt phát hiện index lệch.

## 5. Truy cập hub (`hub.py`)

- Cache: `~/.aero-kb/hub/<sha1(url)>/` (override bằng `AERO_KB_HUB_CACHE`). `--hub` là path local thì dùng thẳng, không cache.
- Tươi mới: `git pull` khi cache cũ hơn TTL **15 phút** (override `AERO_KB_HUB_TTL`, giây). Pull fail (offline) → dùng cache cũ + cảnh báo stderr/log kèm tuổi cache. Chưa từng có cache + clone fail → chạy tiếp **chỉ với KB cục bộ**, cảnh báo rõ — hub là tăng cường, không phải điều kiện sống.
- Mọi thao tác git qua `gitio.py` (mở rộng clone/pull/push) — vẫn là chỗ duy nhất chạy subprocess git.

## 6. `kb publish` (`publish.py`)

```
kb publish --hub <url|path> [--repo-id <id>]
```

1. Đọc `.kb/index.yaml` + toàn bộ `_manifest.yaml` (chỉ L0+L1) của repo hiện tại.
2. Ghi vào clone cache của hub dưới `federation/<repo-id>/` + `_meta.yaml` (source_commit = HEAD repo nguồn).
3. Commit message `publish: <repo-id> @ <short-hash>`, push thẳng. Push reject → `pull --rebase` + retry, tối đa 3 lần, quá → exit 1 thông điệp rõ.
4. `--repo-id` mặc định từ tên repo git; validate không trùng doc-id domain trong hub → trùng thì exit 1.

`.github/workflows/kb-publish.yml` mẫu: trigger push vào main có thay đổi `.kb/**`, chạy `kb publish` với deploy key/token có quyền ghi hub.

## 7. Query hợp nhất (`query.py` + `federation.py`)

Không gian tìm kiếm khi có `--hub` — ba lớp, một lần xếp hạng chung (tag match rồi BM25 trên L0/L1 gộp, không ưu tiên nguồn theo thứ tự cứng):

| Nguồn | Có gì | Trả về |
|---|---|---|
| `.kb/` cục bộ | L0→L3 | Nội dung L2 + citation (như hiện tại) |
| `.kb/` của hub | L0→L3 (trong clone cache) | Nội dung L2 + citation — hành xử y hệt local |
| `federation/<repo>/` | Chỉ L0+L1 | Summary 1 câu + citation + `repo: <id> (<source_url>)`, đánh dấu `[remote]` |

- Kết quả `[remote]` không có L2 để nạp — token budget chỉ tính phần summary; agent muốn sâu hơn thì sang repo đó.
- Citation giữ format `<doc> §<sec> (<rev>)`; kết quả từ repo khác thêm tiền tố: `<repo-id>:<doc> §<sec>`.
- **Collision doc-id local ↔ hub:** local thắng khi query (quyết định #5); collision giữa hai repo federation → hiển thị kèm repo-id nên không nhầm, doctor cảnh báo.

### Bước 3 — embedding fallback (`embed.py`)

- Kích hoạt khi BM25 trả 0 kết quả hoặc điểm cao nhất < ngưỡng (hằng số config trong `embed.py`, tinh chỉnh khi đo thật); hoặc ép bằng `kb query --semantic`.
- Mỗi section một vector: embed `title + summary L1 + phần đầu L2`. Index local tại `.kb-work/embeddings.db`; index cho hub đặt cạnh clone cache. Làm tươi tăng dần theo content-hash của section — lần query ngữ nghĩa đầu build cả index, các lần sau chỉ re-embed section đổi.
- `kb build` làm tươi index nếu file đã tồn tại (CI giữ index nóng); không tự tạo mới trong build để không bắt CI tải model.
- Import `fastembed`/`sqlite-vec` **lười** (trong hàm), interface `Embedder` tiêm được — test dùng fake embedder, không tải model trong CI.

## 8. kb-context hai nguồn (`kbcontext.py` + `resolve.py`)

```yaml
kb-context:
  version: 4f2a91c        # commit repo cục bộ (như Phase 2)
  hub_version: a3f9c21    # MỚI, optional — commit kb-hub, chỉ có khi cite tài liệu hub
  refs:
    - arinc-424 §5.3      # sống ở hub → resolve theo hub_version trong clone cache
    - local-mapping §2    # sống ở repo → resolve theo version (như Phase 2)
  tags: [arinc424, airspace]
```

- `kb context new`: ref nào resolve vào tài liệu hub → tự thêm `hub_version` = HEAD của hub cache (pull trước khi pin); không có ref hub thì block y hệt Phase 2.
- `resolve_refs`: xác định nguồn của từng ref (tra L0 local trước — nhất quán quy tắc local thắng — rồi L0 hub), đọc đúng commit đã pin qua `gitio` trên repo tương ứng. Freshness `ok/stale/broken` tính riêng theo nguồn.
- **Tương thích ngược:** block không có `hub_version` + mọi ref đều local → như Phase 2. Ref hub mà block thiếu `hub_version` → `broken` kèm gợi ý chạy lại `kb context new`.
- Ref dạng `<repo-id>:<doc> §<sec>` (cite chéo repo khác): Phase 3 resolve trả summary L1 từ federation index + con trỏ repo — không có L2; ghi rõ trong output.

## 9. `kb doctor` học thêm hub (`doctor.py`)

Thêm khi có `--hub` (mặc định lấy từ config MCP/CLI nếu đã khai):

- **Hub cache stale / không pull được** — cảnh báo kèm tuổi cache (exit 2 nếu chỉ có stale, giữ quy ước).
- **Index lệch:** `federation/<repo-id>/_meta.yaml.source_commit` ≠ HEAD của repo đang đứng → CI publish fail hoặc chưa chạy (rủi ro §14) — exit 1.
- **Collision doc-id** local ↔ hub → exit 1, in hướng dẫn dọn dẹp từng bước: xóa `.kb/<doc>/` + entry trong index cục bộ; ref đã pin vẫn resolve theo `version` cũ; `kb context new` kể từ đó tự chuyển sang `hub_version`.
- Collision giữa hai repo federation → warning (không thuộc quyền sửa của repo đang đứng).

Exit code giữ quy ước: 0 sạch, 1 lỗi, 2 chỉ stale.

## 10. Remote HTTP MCP (`mcp.py`)

- `--transport {stdio,http}` (mặc định `stdio` — `.mcp.json` hiện tại không đổi), `--host` (mặc định `127.0.0.1`), `--port` (mặc định `8321`).
- Transport http dùng streamable HTTP của SDK chính thức — **3 tool giữ nguyên signature và logic**.
- Bearer token: đọc `AERO_KB_HTTP_TOKEN`; request thiếu/sai header `Authorization: Bearer <token>` → 401. Khởi động http mà biến chưa đặt → **từ chối chạy ngay** (fail fast).
- Kích hoạt `--hub`: server truyền hub xuống query/resolve (thay log "chưa kích hoạt" của Phase 2).
- **Triển khai cho BA** (docs + service file mẫu, không phải code mới): máy nội bộ chạy `python -m aero_kb.mcp --kb <hub-clone>/.kb --hub <hub-clone> --transport http`, cron/systemd timer `git pull` hub clone. BA cấu hình client bằng URL + header Authorization.

## 11. Demo federation (`scripts/demo-federation.sh` / `.ps1`)

Dựng tại chỗ: hub bare repo + 2 repo con (`demo-nav-data`, `demo-crew-ops`) với vài section mẫu, chạy trọn vòng:

1. `kb publish` từ cả hai repo → hub có `federation/demo-nav-data/` + `demo-crew-ops/`.
2. Query từ repo A: thấy tài liệu domain hub (full L2) + summary repo B `[remote]`.
3. `kb context new` trong repo A cite tài liệu hub → block có `hub_version`.
4. Sửa section ở hub → `kb resolve` báo `stale`.
5. Commit thêm ở repo A không publish → `kb doctor` bắt index lệch, exit 1.

Vừa là bằng chứng tiêu chí ≥2 repo, vừa là tài liệu sống. Đẩy 3 repo demo lên GitHub private là bước thủ công tùy chọn sau.

## 12. Error handling

| Tình huống | Hành xử |
|---|---|
| Hub offline / pull fail | Cache cũ + cảnh báo kèm tuổi cache; chưa từng có cache → chạy tiếp chỉ với KB cục bộ |
| Push publish bị race | pull --rebase + retry ≤3, quá → exit 1 thông điệp rõ |
| Collision doc-id local ↔ hub | Local thắng khi query; doctor exit 1 + hướng dẫn dọn dẹp |
| Block cũ thiếu `hub_version`, ref là hub doc | `broken` + gợi ý `kb context new` |
| HTTP thiếu/sai token | 401; thiếu `AERO_KB_HTTP_TOKEN` lúc khởi động http → fail fast |
| Chưa cài `[embed]` / thiếu sqlite-vec | Fallback BM25, log thông báo, không lỗi |
| Model embedding tải fail (offline lần đầu) | Fallback BM25 + cảnh báo; index build ở lần chạy có mạng |
| MCP tools | Giữ nguyên tắc Phase 2: lỗi domain trả text rõ ràng, không raise xuyên protocol |

## 13. Testing

Theo pattern hiện có (pytest, fixture `.kb/` + git repo tạm):

- **Unit:** `hub.py` (TTL, offline fallback, cache path từ URL), `publish` (bare repo tạm: lần đầu, cập nhật, race → retry), doctor (collision, index lệch, hub stale — mỗi loại một fixture), `kbcontext` (parse/render `hub_version`, block Phase 2 cũ nguyên vẹn), `resolve` hai nguồn (ok/stale/broken từng nguồn), query merge 3 lớp (ranking chung, đánh dấu `[remote]`, local thắng collision), trigger embedding fallback (ngưỡng BM25), middleware auth (200/401/fail-fast).
- **Embedding:** fake `Embedder` tiêm vào (vector định trước) — kiểm tra build tăng dần theo content-hash, fallback khi thiếu dependency. Một test `slow` (skip mặc định) chạy model thật ở máy dev.
- **HTTP integration:** khởi động server port ngẫu nhiên, gọi `kb_search` qua streamable HTTP với token thật; sai token → 401.
- **E2E federation:** đúng kịch bản demo script (§11) bằng pytest với tmp git repos — publish 2 repo → query merge → context new có `hub_version` → amendment hub → resolve stale → doctor index lệch.
- Coverage ≥ 80% như các phase trước.

## 14. Ràng buộc kiến trúc (nhắc lại, áp dụng xuyên suốt)

1. `src/aero_kb/` là engine thuần — không hardcode tri thức domain; ngưỡng/TTL là config trung tính.
2. `.kb/` (cả ở hub) là content thuần; `federation/` là dữ liệu máy sinh — không review, không sửa tay.
3. Đổi transport MCP không đổi code tool (giữ lời hứa Phase 2).
4. Embedding là tăng cường tùy chọn — mọi đường đi phải hoạt động đầy đủ khi thiếu `[embed]`.
5. Hub là tăng cường — mọi lệnh Phase 1+2 hoạt động nguyên vẹn khi không có `--hub`.
