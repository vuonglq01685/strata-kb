# AERO-KB Phase 1 (PoC) — Design

**Ngày:** 2026-07-10
**Nguồn:** `AERO-KB_Architecture_v0.1.pdf` (spec kiến trúc tổng thể, v0.1 — 09/07/2026)
**Phạm vi:** Phase 1 theo roadmap §13 — Python package + CLI, cấu trúc `.kb/` 4 tầng, ingest thử 1–2 chương ARINC 424 + 1 Annex, quy trình SME review đầu tiên.

## 1. Mục tiêu & tiêu chí hoàn thành

Trọng tâm Phase 1 là trả lời câu hỏi: **làm sao biến một PDF hàng trăm trang thành 4 tầng L0–L3 một cách lặp lại được, rẻ, và an toàn với bảng biểu.**

Tiêu chí hoàn thành (từ roadmap):

- `kb query` từ CLI trả về đúng section, đúng citation (`arinc-424 §5.3 (Supplement 22)`).
- `kb stats` chứng minh mức tiết kiệm token (mục tiêu ≥ 90% so với nạp raw document; L0 < 1K token).
- Ít nhất 1 chương ARINC 424 + 1 chương Annex đi trọn pipeline: ingest → summarize → SME review → build pass.

Ngoài phạm vi Phase 1: MCP server, `kb diff`, `kb doctor`, federation, embedding search, tích hợp Jira.

## 2. Các quyết định thiết kế đã chốt

| # | Quyết định | Lựa chọn | Lý do |
|---|---|---|---|
| 1 | Nguồn PDF | Text-based, có sẵn 4 tài liệu trong `sources/` | Đã kiểm tra thực tế: text trích sạch |
| 2 | LLM summarize | **Claude Code làm summarizer** (không gọi API trực tiếp) | Dùng subscription sẵn có; `kb ingest` chỉ làm phần deterministic |
| 3 | Ngôn ngữ summary | **Tiếng Anh** | Cùng ngôn ngữ tài liệu gốc và query kỹ thuật → BM25 khớp tốt nhất |
| 4 | Engine parse PDF | **Docling (IBM)** | Chất lượng bảng tốt nhất — bảng field spec ARINC là nội dung "phải giữ nguyên văn"; tự nhận diện heading từ layout nên Annex 4 (bookmark hỏng) đi chung một đường với các tài liệu khác |

Đánh đổi chấp nhận với Docling: lần parse đầu chậm (tải model ~500MB; ARINC 487 trang có thể mất 15–30 phút) — phù hợp nguyên tắc "compile once, query many"; kết quả parse được cache.

### Hiện trạng 4 tài liệu nguồn (đã kiểm tra)

| Tài liệu | Trang | Bookmark | Ghi chú |
|---|---|---|---|
| ARINC424-22.pdf | 487 | 639, lồng 4 cấp | Cấu trúc chuẩn, dày đặc bảng |
| Annex 3 Met Service (Ed 20) | 224 | 128, phân cấp chuẩn | Tốt |
| Doc 8896 Met Practice (2021) | 200 | 74, phân cấp chuẩn | Tốt |
| Annex 4 Charts (2009) | 164 | 7 bookmark rác | Dựa hoàn toàn vào heading detection của Docling |

## 3. Kiến trúc & cấu trúc repo

Python package `aero_kb` + CLI `kb` (Typer). Không database, không server — đúng nguyên tắc docs-as-code.

```
AERO-KB/
├── src/aero_kb/
│   ├── cli.py              # kb ingest / status / build / query / get / stats
│   ├── ingest/
│   │   ├── parser.py       # Docling → DoclingDocument, cache JSON
│   │   ├── sectioner.py    # dựng cây section, đánh id, gộp/tách
│   │   └── scaffold.py     # sinh L3 + khung L1/L2 + entry L0
│   ├── build.py            # validate schema, toàn vẹn bảng, token stats
│   ├── query.py            # tag match → BM25 trên manifest
│   └── models.py           # schema Pydantic: IndexEntry, Manifest, Section
├── .claude/skills/kb-summarize/SKILL.md   # quy trình điền summary chuẩn
├── .kb/                    # knowledge base — sản phẩm, commit vào git
│   ├── index.yaml          # L0
│   └── <doc-id>/
│       ├── _manifest.yaml  # L1
│       ├── ch5-nav-data.md        # L2
│       └── ch5-nav-data.raw.md   # L3
├── .kb-work/               # trung gian (Docling JSON) — gitignore
├── sources/                # PDF gốc có bản quyền — gitignore
└── tests/
```

Hai quyết định kèm theo:

1. **`sources/` gitignore** — spec §12.3: không commit raw tài liệu có bản quyền. Đã dời 4 PDF vào đây.
2. **`.kb-work/` tách khỏi `.kb/`** — kết quả parse Docling đắt tiền được cache; chỉ `.kb/` là sản phẩm.

## 4. Thuật toán cắt section (ingest)

### 4.1 Parse

`docling` đọc PDF → `DoclingDocument` (chuỗi item theo thứ tự đọc: `SectionHeaderItem`, `TextItem`, `TableItem`). Kết quả lưu `.kb-work/<doc-id>/parsed.json`; các bước sau đọc từ cache, không parse lại.

### 4.2 Dựng cây section & đánh id

Duyệt item theo thứ tự đọc; mỗi `SectionHeaderItem` mở một node theo cấp heading. Id chuẩn rút từ text heading bằng regex, theo thứ tự ưu tiên:

```
"5.3 Restrictive Airspace"        → 5.3      (heading đánh số)
"CHAPTER 2. GENERAL PROVISIONS"   → ch2      (chương không số lẻ)
"Appendix 3 ..."                  → app3     (phụ lục)
không khớp mẫu nào                → <id-cha>-a, -b… + cảnh báo trong báo cáo ingest
```

### 4.3 Đối chiếu bookmark (validation, không chặn)

Với tài liệu có bookmark chuẩn: so cây section Docling với outline PDF (pypdf). Section thiếu/thừa → in cảnh báo cho người ingest. Annex 4 bỏ qua bước này.

### 4.4 Chuẩn hóa đơn vị section (gộp/tách)

Áp theo thứ tự:

1. **Độ sâu tối đa 3 cấp** (`x.y.z`) — heading sâu hơn nhập vào section cha.
2. **Gộp section nhỏ**: section lá có L3 < 200 token → nhập vào cha.
3. Kỳ vọng: mỗi đơn vị có L3 khoảng 300–5.000 token (ARINC: 639 bookmark → ~100–150 đơn vị).

### 4.5 Quy tắc bảng — bất khả xâm phạm

`TableItem` xuất thành bảng markdown **nguyên văn ở cả L3 lẫn L2**. Bảng trong L2 do code chép, không phải LLM — LLM không có cơ hội chép sai.

### 4.6 Ghi file theo chương

Một file L2 + một file L3 mỗi chương cấp 1 (`ch5-nav-data.md` / `.raw.md`), section đánh anchor heading (`## 5.3 Restrictive Airspace`) để `kb get` trích đúng khối. Engine không bao giờ trả cả file.

### 4.7 Phạm vi ingest

`kb ingest <pdf> --id <id> --tags <tags> [--sections 5,6]` — Docling parse cả PDF (cache), nhưng chỉ scaffold + summarize các chương được chọn.

## 5. Điền summary bằng Claude Code

### 5.1 Khung chờ điền (output của ingest)

- `_manifest.yaml`: đủ cây section, mỗi section `summary: ""` + `status: pending`.
- File L2: có sẵn heading + bảng chép nguyên văn + marker `<!-- TODO:summarize §5.3 -->` tại chỗ cần văn xuôi cô đọng.
- File L3: hoàn chỉnh ngay từ ingest.

### 5.2 Skill `kb-summarize` (commit trong repo)

Quy trình chuẩn cho bất kỳ ai mở Claude Code trong repo:

1. `kb status` → danh sách section `pending`.
2. Với từng section: đọc L3 đúng section đó (theo anchor) → viết đoạn L2 tiếng Anh thay marker → viết 1 câu summary (≤ 25 từ) vào manifest → `status: summarized`.
3. Xong tài liệu: viết entry L0 vào `index.yaml` (id, title, revision, tags, 1 câu mô tả).

Ràng buộc văn phong trong skill: giữ nguyên mã hiệu, tên record/field, giá trị số; không suy diễn ngoài văn bản; L2 nhắm ~20–30% độ dài L3 (mục tiêu 0,5–2K token/section).

### 5.3 Chốt chặn deterministic (`kb build`)

- Fail nếu còn marker `TODO` hoặc `summary: ""`.
- **Kiểm tra toàn vẹn bảng**: mọi bảng trong L3 của một section phải xuất hiện nguyên văn (chuẩn hóa whitespace) trong L2 — chốt an toàn quan trọng nhất.
- Đếm token thực tế từng tầng, ghi vào manifest (`tokens: {l2: ..., l3: ...}`).

### 5.4 SME review

= PR review: diff của `.kb/` là thứ SME đọc và sửa trực tiếp. Sau merge, section `status: reviewed`.

## 6. Query engine & CLI

### 6.1 Routing (Phase 1: bước 1–2 của spec §7)

```
kb query "restrictive airspace fields" --tags arinc424 --budget 2000
```

1. **Tag match** trên L0 → kích hoạt manifest các doc liên quan (nêu đích danh doc-id → kích hoạt thẳng). ~0 token, deterministic.
2. **BM25** (`rank-bm25`, thuần Python) trên L1: title + summary từng section.
3. Trả danh sách section xếp hạng; nạp L2 từng section đến khi chạm budget; mỗi kết quả kèm citation `<doc-id> §<section> (<revision>)`.

### 6.2 Lệnh CLI Phase 1

| Lệnh | Vai trò |
|---|---|
| `kb ingest <pdf> --id --tags [--sections]` | Parse → cắt section → sinh L3 + khung L1/L2 |
| `kb status` | Liệt kê section `pending` |
| `kb build` | Validate schema, toàn vẹn bảng, hết TODO; cập nhật index + token counts |
| `kb query "..." [--tags] [--budget]` | Routing + trả section trong budget + citation |
| `kb get <doc-id> §<section> [--level l2\|l3]` | Trích đúng một section |
| `kb stats` | Bảng token L0/L1/L2/L3 từng doc |

Token đếm bằng tokenizer xấp xỉ (tiktoken) — nhất quán, đủ cho mục đích theo dõi chi phí.

## 7. Testing

Theo TDD. PDF thật có bản quyền không được commit → test chạy trên **fixture tự tạo nhỏ**:

- Unit: regex đánh id section, quy tắc gộp/tách, cắt anchor, kiểm tra toàn vẹn bảng, BM25 ranking, schema validation.
- Integration: pipeline ingest→build→query trên một PDF fixture nhỏ tự sinh (vài trang, có heading + bảng).
- Verify cuối trên tài liệu thật (chạy local, không commit kết quả trung gian): ARINC ch 5 + 1 chương Annex 3; `kb stats` là bằng chứng nghiệm thu.

## 8. Thứ tự triển khai

1. ~~`git init` + `.gitignore` + dời PDF vào `sources/`~~ (đã xong cùng design doc này)
2. Schema Pydantic + `kb build` validation — nền để test mọi thứ sau
3. Parser Docling + sectioner (cây section, id, gộp/tách)
4. Scaffold L3/L2/manifest + `kb status`
5. Skill `kb-summarize`
6. `kb query` / `kb get` / `kb stats`
7. Chạy thật: ARINC 424 chương 5 + Annex 3 một chương → điền summary → SME review → đo token

## 9. Rủi ro riêng của Phase 1

| Rủi ro | Giảm thiểu |
|---|---|
| Docling nhận diện heading sai/mất ở tài liệu cụ thể | Đối chiếu bookmark (4.3); báo cáo ingest liệt kê heading không khớp mẫu; người ingest duyệt cây section trước khi scaffold |
| Bảng phức tạp (merged cells, xoay ngang) Docling xuất lệch | Kiểm tra mắt thường trong SME review; L3 luôn giữ bản trích để đối chiếu; ghi nhận case lỗi cho Phase 2 |
| Summary bán thủ công khó lặp lại y hệt (hệ quả chọn Claude Code thay API) | Skill + ràng buộc văn phong cố định trong repo; `kb build` chặn thiếu sót; chấp nhận cho PoC, Phase sau có thể nâng lên API |
| 639 section ARINC → khối lượng summarize lớn | `--sections` giới hạn phạm vi; quy tắc gộp giảm số đơn vị còn ~100–150 cho cả tài liệu, PoC chỉ làm 1 chương |
