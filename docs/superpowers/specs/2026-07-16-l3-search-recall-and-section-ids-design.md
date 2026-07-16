# L3 Search Recall + Section Id Fallback — Design

**Date:** 2026-07-16
**Status:** Approved pending review
**Scope:** search index (searchdb), query/get_section, ingest sectioner fallback id, intake warning. Không đổi format `.kb/` hay federation layout.

## 1. Bối cảnh & vấn đề

Ingest fold leaf section < 200 token vào `body_md` của parent unit (`sectioner.py` `_units_from_tree`, heading con thành `### id title` trong body). Nội dung không mất — nằm đủ trong L3 raw của parent — nhưng:

- **Gap 1 — section fold vô hình với search.** Index FTS + embedding chỉ ăn `title + summary (1 câu manifest) + 500 ký tự đầu L2` (`searchdb._section_parts`, `_L2_HEAD_CHARS = 500`). L2 là bản LLM summary nén 20–30%; exact identifier trong section fold (part number, torque value, acronym) dễ bị nén mất → keyword leg miss hẳn, semantic leg yếu. L3 raw không bao giờ được index.
- **Gap 2 — tables ngoài cửa sổ index.** Table giữ verbatim trong L2 (giá trị tra cứu cao) nhưng nằm **sau** summary — thường ngoài 500 chars đầu → không vào FTS lẫn embedding. Nghịch lý: giữ verbatim để tra, search không thấy.
- **Gap 3 — citation lookup chết với folded id.** `get_section("3.2.1")` trả `None`: manifest không có entry, `slice_section` chỉ match `## ` (`mdutils._HEADING_RE`), không match `###`.
- **Gap 4 — section id vô nghĩa `x{n}`.** Heading không parse được số → fallback slug từ title; slug bị loại khi rỗng/toàn số → `x{n}` counter toàn doc (`sectioner.py:312`). Hai đường dính: (a) doc ingest bằng CLI cũ trước `2debcbc` — mọi heading không số đều `x{n}` (arinc-424 local còn 10 id); (b) CLI hiện tại vẫn sinh `x{n}` vì `slugify` NFKD rồi vứt sạch non-ASCII — CJK/Cyrillic chết toàn bộ (`表5-6 データ概要` → `5-6` → toàn số → loại; `ЧАСТЬ 1` → `1` → loại). Doc trên hub có heading non-Latin → `x1, x2, x3…` dù CLI mới nhất.

## 2. Goals / Non-goals

**Goals**

- Keyword search tìm được term chỉ tồn tại trong L3 raw (section fold) và trong tables sau 500 chars của L2.
- Kết quả search vẫn L2-first (rẻ token); match nằm ngoài L2 content → kèm snippet L3 để người dùng thấy vì sao hit.
- `get_section` resolve được folded section id (l3 → đúng subtree, l2 → parent).
- Fallback id đọc được với SME mọi ngôn ngữ; `x{n}` chỉ còn last-resort có log.
- Hub cảnh báo id `x{n}` legacy lúc intake để repo re-ingest.

**Non-goals**

- Không đổi semantic leg: embedding vẫn `title + summary + 500 chars đầu L2` — cap tồn tại vì input limit của embed model; semantic tìm concept, exact identifier là việc của FTS.
- Không mở rộng `tokenize()` ASCII-only (`searchdb.py:506`) — query CJK vẫn không chạm keyword leg; limitation đã ghi nhận, mở khi có nhu cầu thật.
- Không re-ingest arinc-424 trong scope này — việc vận hành, làm riêng.
- Không migration schema — bump `SCHEMA_VERSION`, `open_db` rebuild-once sẵn có tự lo.

## 3. Index schema (searchdb)

FTS5 từ 3 cột thành 4:

```sql
CREATE VIRTUAL TABLE fts USING fts5(
    title, summary, body_l2, body_l3, tokenize='unicode61');
```

- `body_l2` = **full** L2 slice (summary + tables) — bỏ cap 500 cho FTS.
- `body_l3` = full L3 slice từ `.raw.md` (federation có publish `.raw.md` — đã xác nhận).
- `SCHEMA_VERSION` `"1"` → `"2"`.

**Ranking:** `bm25(fts, w_title, w_summary, w_l2, w_l3)` với thứ tự trọng số `title > summary > body_l2 > body_l3` (khởi điểm `4.0, 2.0, 1.5, 1.0`, tune lúc implement) — section L3 dài không được lấn át title/summary match.

**Tách hash khỏi embed text** (hiện chung `_embed_text`):

- `content_hash` = sha256 trên `title + summary + body_l2 + body_l3` — L3 đổi là re-index FTS.
- Embed text giữ nguyên format cũ (`title + summary + body_head` capped 500). `_sync_vectors` so hash embedding riêng như hiện tại — đổi L3 không ép re-embed nếu phần embed không đổi.

**Sync:** `_section_parts` đọc thêm L3 slice. `.raw.md` thiếu → `body_l3 = ""`, log warning, không fail sync (repo publish thiếu raw vẫn index được phần L2).

## 4. Snippet L3 (query)

- `QueryResult` thêm `snippet: str = ""`.
- Điều kiện sinh: kết quả có leg keyword (`match_mode != "semantic"`) **và** không token nào của `tokenize(query)` xuất hiện trong content L2 đã trả → đọc L3 slice của section, tìm hit token đầu tiên (case-insensitive), cắt cửa sổ ±150 chars, `…` hai đầu.
- Pure Python trong `query.search` — không dùng FTS5 `snippet()` (testable, chạy cả hybrid).
- Token của snippet **tính vào budget**. Semantic-only hit không snippet.
- CLI / MCP / web hiển thị snippet dưới content, label `raw match:`.

## 5. Citation fallback cho folded id (get_section)

Id không có trong manifest → parent = section entry có id là **prefix dài nhất** của id yêu cầu, cắt tại `.` hoặc `-` (`3.2.1` → `3.2`; `5.6-commentary` → `5.6`). Không parent → `None` như cũ.

- `level=l3`: slice `.raw.md` của parent tại `### {id} ` đến heading `###`/`##` kế — util mới `slice_subsection()` trong mdutils (regex `## ` hiện tại không đụng).
- `level=l2`: trả nguyên section L2 của **parent**; citation ghi id parent (không nói dối vị trí — L2 không có anchor con).
- `###` không thấy trong raw → `None` (id sai thật).

## 6. Fallback id fix (sectioner + intake)

**6a — slug Unicode-aware cho section id.** Biến thể slugify mới chỉ dùng cho fallback id: giữ ký tự chữ mọi script (`\w` flags unicode, bỏ symbol/punctuation), lowercase, nối `-`, cắt 40 chars. `表5-6 データ概要` → id `5.6-表5-6-データ概要` (dạng chuẩn hoá). `chapter_stem` (tên file) **giữ** ASCII slugify cũ — filesystem/URL an toàn.

- Digit-only title (số trang lạc vào heading) → không tạo section, nhập body parent — cùng hướng symbol-only filter (`0a31a75`).
- `x{n}` giữ làm last-resort (title thực sự rỗng sau lọc), thêm `logger.warning` khi kích hoạt để lộ sớm.
- Index side FTS `unicode61` tokenize được id/title unicode (sẵn có). Query side `tokenize()` ASCII-only — id CJK chưa search được bằng keyword (Non-goal, ghi nhận).
- Kiểm tra kèm: citation `§5.6-表…` qua web UI / MCP không vỡ URL-encoding.

**6b — intake warning.** Intake/publish phát warning khi manifest chứa section id khớp `-x\d+$` — nhắc repo re-ingest bằng CLI mới. Không reject: data cũ vẫn hợp lệ, chỉ kém đọc.

## 7. Error handling

- Sync: lỗi đọc file per-section → skip section đó, log, sync tiếp (giữ pattern hiện tại).
- Snippet: L3 file thiếu/section không slice được → `snippet = ""`, không fail search.
- Fallback get_section: mọi nhánh fail → `None`, không raise (khớp contract hiện tại).
- Corruption/rebuild/lock: cơ chế `open_db` + rebuild-once + `is_lock_error` giữ nguyên, không đụng.

## 8. Testing

Pytest, hermetic — không LLM thật, không model embed thật (embedder inject như test hiện có).

- **searchdb:** term chỉ có trong table sau 500 chars L2 → tìm thấy; term chỉ có trong section fold (L3) → tìm thấy; hash đổi khi chỉ L3 đổi → re-index; `.raw.md` thiếu → sync vẫn xong, `body_l3` rỗng; schema version cũ → rebuild-once; bm25 weights: title match rank trên L3-only match.
- **query:** snippet sinh đúng điều kiện (keyword hit + term vắng L2); semantic-only không snippet; token snippet tính budget; snippet cửa sổ ±150 đúng biên.
- **get_section:** folded id `l3` → đúng `###` subtree; `l2` → parent section, citation id parent; id rác → None; nhiều ứng viên prefix → chọn dài nhất.
- **sectioner:** CJK/Cyrillic title → id slug unicode, không `x{n}`; digit-only heading → không thành section; title rỗng thật → `x{n}` + warning log.
- **intake:** manifest có `-x\d+$` → warning, không reject.
- **tests-gate:** golden/regression cập nhật theo schema mới.

## 9. Rủi ro & lưu ý

- **Index size:** thêm full L2 + L3 vào FTS — corpus 100k section vẫn trong tầm SQLite FTS5; index là derived cache (`.kb-work/search.db`), không commit.
- **bm25 weights** là khởi điểm — đo với KB thật rồi tune; đổi weights không cần đổi schema.
- **`tokenize()` ASCII-only** giới hạn keyword recall cho corpus non-Latin — đã ghi Non-goal, mở rộng là việc riêng khi có KB non-Latin thật.
- **arinc-424 còn 10 id `x{n}` legacy** đến khi re-ingest (ops, ngoài scope). Warning 6b sẽ nhắc.
- Hub cache có file rác `*.raw.md.bak` từ flow cũ — không liên quan design này, dọn riêng nếu cần.
