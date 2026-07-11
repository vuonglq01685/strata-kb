# CENTER-KB — Bookmark-first sectioning + attachment pattern fallback — Design

**Ngày:** 2026-07-11
**Nguồn:** phản hồi SME (Lam): chia chapter "loạn cào cào", sinh chapter không có trong tài liệu gốc (`ch5-x212-star-coding-example-1`, `ch8-x350-arinc-standard-errata-report`, `x1-x2-x3-published-july-23-2018`, `ch9`/`ch10` giả). Đối chiếu outline PDF ARINC 424-22: 8 chương (p21–330), ATTACHMENT 1–5 (p331–474), front matter (p1–20), SUPPLEMENT 22/ERRATA/APIM (p475+) — engine hiện không nhận diện ATTACHMENT/front/back matter, mọi heading lạ rơi vào fallback `x<n>` thành "chương" giả.
**Phạm vi:** module ingest (parser + sectioner + scaffold + CLI ingest). Không đổi format `.kb/` (vẫn manifest + file per chapter), không đụng summarize/build/query.

---

## 1. Root cause (đã xác minh)

| # | Nguyên nhân | Bằng chứng |
|---|---|---|
| RC1 | `HeadingConfig` chỉ có chapter/appendix pattern — ATTACHMENT, SUPPLEMENT, ERRATA, APIM, front matter không được nhận diện | outline PDF có 13 phần top-level ngoài 8 chương; KB sinh không có att nào |
| RC2 | Heading không khớp → fallback node `x<n>` (sectioner.py:167-176); fallback top-level thành "chương" riêng tên vô nghĩa | `x1-x2-x3-published-july-23-2018` (front matter), `ch5-x212-…`, `ch8-x350-…` |
| RC3 | Outline/bookmark PDF — nguồn cấu trúc chuẩn — chỉ dùng để warn (`crosscheck`), không dùng để chia | parser.py:55-75; câu hỏi của SME chính là gap này |

Đã xác minh kỹ thuật: docling items có `prov[0].page_no`; pypdf outline có page number per entry (`get_destination_page_number`). Quirk ARINC: chương/attachment nằm ở depth 1 DƯỚI entry "TABLE OF CONTENTS" → thuật toán phải quét mọi depth, không chỉ top-level.

## 2. Quyết định

| # | Vấn đề | Quyết định | Lý do |
|---|---|---|---|
| 1 | Nguồn khung chia | **Bookmark-first**: `outline_parts(pdf, config)` quét toàn bộ outline; entry là **part** nếu title parse ra chapter (`Chapter N` / `N.0` / số không có chấm con), attachment, appendix — ở BẤT KỲ depth nào; entry top-level không parse được → front/back-matter part (id = slug title). Sort theo trang. < 2 part hoặc không có outline → **fallback regex mode** (cách hiện tại + quyết định #5) | Outline là cấu trúc tác giả công bố — SME đối chiếu 1:1; quirk TOC-lồng xử lý bằng quét mọi depth |
| 2 | Gom front matter | Các part không-parse-được liên tiếp TRƯỚC chương đầu tiên gộp thành 1 part `front-matter` ("Front Matter"). Back matter (SUPPLEMENT/ERRATA/APIM) giữ riêng từng part | Tránh 6 file vụn cho cover/disclaimer/toc; supplement/errata có giá trị tra cứu riêng |
| 3 | Id & tên file part | Chương: `"1"…"8"` (như cũ). Attachment: `attN`. Appendix: `appX` (như cũ). Front/back: slug (`front-matter`, `supplement-22`, `errata`, `apim`). Tên file qua `chapter_stem` hiện có → `att1-flow-diagram.md`, `errata.md`… | Tên khớp tài liệu gốc, SME nhìn là hiểu |
| 4 | Chia trong part | Gán DocItem vào part theo `page` (item thuộc part cuối cùng có trang bắt đầu ≤ trang item; item không có page kế thừa item trước). Trong mỗi part chạy tree builder hiện tại; part không-phải-chương-số: heading số bên trong namespace `attN-2.1` (tổng quát hoá cơ chế `app*-` hiện có), fallback `attN-x1` — **không còn x-node top-level, không còn chương giả** | Diệt RC2; numbering nội bộ attachment hết va chạm id chương (hết nguy cơ reopen đổ nhầm nội dung) |
| 5 | Fallback regex mode (B) | `HeadingConfig` thêm `attachment_pattern` (default `^attachment\s+([0-9A-Za-z]+)\s*[.:–—-]?\s*(.*)$` → id `attN`); `parse_section_id` nhận diện; CLI `--attachment-pattern`; persist vào manifest `IngestConfig` (pydantic default → manifest cũ vẫn load) | PDF scan/không bookmark vẫn tách được attachment |
| 6 | CLI & persist | `kb ingest --no-bookmarks` ép regex mode. Mode dùng thật persist `ingest.used_bookmarks: bool` vào manifest (thông tin, không ép re-ingest sau) | Người dùng kiểm soát được; tái lập được cách chia |
| 7 | Re-ingest sạch | `scaffold_doc` xoá `*.md`, `*.raw.md` của doc dir trước khi ghi (manifest ghi đè như cũ) | Đổi cách chia → tên file đổi; file cũ mồ côi sẽ làm bẩn KB |
| 8 | Vận hành CENTER-KB | Sau merge: re-ingest arinc-424 (cache docling `.kb-work` giữ nguyên — không tốn parse lại), kiểm tra danh sách file khớp outline, RỒI mới `kb summarize` (449 section đang pending, chưa tốn công summarize — fix trước, trả tiền LLM một lần) | Thời điểm vàng: chưa summarize |

## 3. Thay đổi kỹ thuật

- `sectioner.py`: `DocItem` thêm `page: int | None = None`; `HeadingConfig` + `attachment_pattern`; `parse_section_id` nhận attachment; dataclass `Part(id, title, page)`; `split_by_parts(items, parts)`; tổng quát hoá namespacing (`app*` → mọi part id không bắt đầu bằng số); `build_units(items, parts=None, …)` — có parts thì build per-part, không thì như cũ.
- `parser.py`: `doc_to_items` điền `page` từ `prov`; `outline_parts(pdf_path, config) -> list[Part] | None` (pypdf, quét mọi depth, gom front matter, sort trang).
- `scaffold.py`: xoá file doc cũ trước khi ghi (quyết định #7).
- `cli.py` (`ingest`): gọi `outline_parts` (trừ khi `--no-bookmarks`), truyền parts vào `build_units`, echo mode đã dùng (`sectioning: bookmarks (13 parts)` / `sectioning: heading patterns`); `--attachment-pattern` option.
- `models.py`: `IngestConfig` + `attachment_pattern: str = DEFAULT_ATTACHMENT_PATTERN`, `used_bookmarks: bool = False` (defaults → backward compat).
- `resolve_heading_config`: nhận thêm attachment_pattern (arg > previous > default).

## 4. Testing

- Unit `split_by_parts`: item trước part đầu, item page None, hai part cùng trang, item sau part cuối.
- Unit `outline_parts`: PDF nhỏ sinh bằng pypdf `PdfWriter.add_outline_item` (chapter + attachment lồng dưới TOC-entry + front/back matter) → đúng parts, đúng thứ tự trang; PDF không outline → None.
- Unit `parse_section_id`: "ATTACHMENT 5 PATH AND TERMINATOR" → ("att5", …); pattern override.
- Unit build_units với parts: heading số trong att part → `att5-2.1`, không va chạm "2.1" của chương; front-matter part gom fallbacks nội bộ.
- Scaffold: re-ingest xoá file mồ côi.
- E2E ingest fixture hiện có phải xanh (fixture không bookmark → regex mode như cũ).

## 5. Ngoài phạm vi

- Đổi format `.kb/`, summarize, build, query, federation.
- OCR/xử lý PDF không có text layer.
- Editor/UI cho outline.
