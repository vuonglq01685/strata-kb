# AERO-KB — Web UI: nới rộng layout + highlight từ khóa + badge chế độ khớp — Design

**Ngày:** 2026-07-12
**Trạng thái:** Đã duyệt thiết kế (chờ review spec)

## 1. Bối cảnh & mục tiêu

Trang web UI tra cứu (`src/center_kb/web/ui.py` + `templates/web/*.html`) đã có giao diện
"technical documentation console" (xem `style.css`). Người dùng phản hồi hai vấn đề:

1. **Layout lãng phí không gian**: `main { max-width: 58rem }` trong `base.html` áp dụng
   cho mọi trang. Bảng danh sách section (`doc.html`, class `.sections`, 4 cột:
   Section/Title/Summary/Status) bị bóp trong container hẹp → cột `Summary` xuống dòng
   liên tục dù màn hình còn nhiều khoảng trắng hai bên. Trang search cũng hiển thị được
   ít kết quả hơn mức màn hình cho phép.
2. **Không rõ cơ chế search theo keyword, và không thấy được từ khóa khớp ở đâu**: search
   hiện dùng BM25 (`query.py::search()`, khớp trên *title + summary* của section) rồi tự
   động rơi xuống semantic/embedding fallback (`_semantic_fallback()`) khi điểm BM25 cao
   nhất thấp hơn `SEMANTIC_FALLBACK_THRESHOLD` — không có tín hiệu nào cho người dùng biết
   kết quả đến từ khớp từ khóa hay khớp ngữ nghĩa, và nội dung khớp không được đánh dấu.

   Đã xác minh: `kb_search` (MCP tool) và `kb query` (CLI) dùng chung đúng hàm
   `search()` này — cùng một engine truy hồi cho cả 3 lối vào (web UI, CLI, MCP).

Mục tiêu đợt này: sửa cả hai, giới hạn trong **web UI**. Không đổi engine truy hồi, không
đổi output của CLI/MCP (việc BM25 chỉ khớp title+summary thay vì full-text là một hạn chế
truy hồi thật sự nhưng **ngoài phạm vi** — ghi nhận lại để cân nhắc ở đợt sau).

## 2. Phạm vi

**Trong phạm vi:**
- Nới rộng `main` cho các trang dữ liệu (search, docs list, doc detail table); giữ
  trang xem nội dung section (`section.html`) ở độ rộng dễ đọc riêng.
- Highlight từ khóa gõ trong ô `q` tại nội dung kết quả search (toàn bộ nội dung hiển
  thị, kể cả trong bảng), khớp từ nguyên vẹn, không phân biệt hoa/thường.
- Badge nhỏ trên mỗi kết quả search cho biết kết quả đến từ khớp từ khóa (BM25) hay
  khớp ngữ nghĩa (semantic fallback).

**Ngoài phạm vi (YAGNI):**
- Đổi BM25 sang index full-text (L2) thay vì title+summary.
- Đưa badge/độ minh bạch cơ chế search vào CLI (`kb query`) hoặc MCP tool (`kb_search`).
- Layout nhiều cột cho kết quả search.
- Đổi renderer markdown (`mdrender.py`) sang thư viện ngoài.

## 3. Chi tiết thiết kế

### 3.1. Layout & độ rộng

- `style.css`: `main { max-width: 58rem }` → `max-width: 76rem`. Áp dụng mặc định cho
  mọi trang qua `base.html` (search, docs list, doc detail, section, login).
- `templates/web/section.html`: bọc toàn bộ thân trang (crumbs, `h1`, `.meta`, `article.content`)
  trong `<div class="detail">`. CSS mới: `.detail { max-width: 54rem; margin-inline: auto; }`
  — tự căn giữa bên trong `main` 76rem, giữ độ rộng đọc gần với hiện trạng (58rem) cho
  văn bản quy định dài, không bị kéo giãn dòng quá mức.
- Không đổi gì ở Python/route — thuần CSS + 1 wrapper `div` trong template.

### 3.2. Highlight từ khóa trong kết quả

Renderer markdown nội bộ (`web/mdrender.py`) là bộ tối giản tự viết: chỉ sinh
`<p>`, `<h1>`–`<h6>`, `<table><tr><th|td>`, mọi text đều đi qua `html.escape()` tại
đúng 3 điểm (đoạn văn ở `flush_para`, heading, ô bảng ở `_render_table`). Vì không có
markup lồng nhau (không code span, không link, không bold/italic), highlight có thể
chèn **ngay trong lúc render** thay vì parse lại HTML sau đó — an toàn hơn, không rủi
ro làm hỏng thẻ.

- `query.py`: đổi `_tokenize` (module-private) thành hàm dùng chung
  `tokenize(text: str) -> list[str]` (bỏ `_`, giữ nguyên regex `[a-z0-9]+` sau
  lowercase) — cả BM25 ranking và highlight đều tokenize giống hệt nhau.
- `mdrender.py`: thêm hàm nội bộ
  ```python
  def _highlight(text: str, terms: set[str]) -> str:
      # quét từng \w+ trong text; nếu .lower() nằm trong terms, bọc <mark>…</mark>;
      # phần còn lại escape như cũ (html.escape từng đoạn con là an toàn, tương
      # đương escape cả chuỗi rồi mới chèn — html.escape không phụ thuộc ngữ cảnh
      # xung quanh).
  ```
  `render(md: str, terms: set[str] | None = None)` dùng `_highlight(segment, terms or set())`
  thay cho `html.escape(segment)` ở cả 3 điểm (đoạn văn, heading, ô bảng).
- `web/ui.py::home()`: `terms = set(query.tokenize(q)) if q else set()`, truyền xuống
  `_result_blocks(results, terms)` → mỗi kết quả gọi `md_render(r.content, terms=terms)`.
- CSS: thêm
  ```css
  mark {
    background: var(--amber-soft); color: var(--amber);
    border-radius: 3px; padding: 0 0.15em; font-weight: 600;
  }
  ```
  dùng tông amber sẵn có trong palette — tách biệt rõ với xanh (link/citation).

**Hành vi kỳ vọng**: kết quả đến từ BM25 luôn có ít nhất 1 từ được highlight (vì BM25 chỉ
giữ lại candidate có giao với `query_tokens`, xem `query.py:178`). Kết quả đến từ semantic
fallback **có thể không có highlight nào** — đây là tín hiệu tự nhiên, hữu ích: cho thấy
đây là match gần đúng theo ngữ nghĩa chứ không khớp đúng từ đã gõ.

### 3.3. Badge chế độ khớp (keyword / semantic)

- `query.py`: thêm field vào `QueryResult`:
  ```python
  match_mode: str = "keyword"  # "keyword" | "semantic"
  ```
  Không đổi gì ở nhánh BM25 (dùng default). Trong `_semantic_fallback()`, khi dựng
  `QueryResult` cho từng hit: thêm `match_mode="semantic"`.
- Đây là field **thêm vào cuối, có default** — không đổi signature `search()`, không đổi
  hành vi CLI (`kb query`) hay MCP tool (`kb_search`); cả hai chỉ đọc `.citation` /
  `.content` / `.score` như hiện tại, hoàn toàn không cần sửa.
- `web/ui.py::_result_blocks()`: render thêm badge cạnh `source-badge` hiện có:
  ```html
  <span class="match-badge match-{mode}">{mode}</span>
  ```
- CSS: tái dùng pattern `.source-badge`/`.status-badge` đã có —
  `.match-keyword` tông trung tính (như `.source-local`), `.match-semantic` tông violet
  (như `.source-remote`) để nổi bật đây là kết quả "mờ" hơn về độ khớp.

## 4. Testing

- **Unit — `mdrender.py`**: `_highlight`/`render(..., terms=...)` — khớp từ nguyên vẹn
  (không match substring, ví dụ `"restrict"` không khớp `"restricted"`), không phân biệt
  hoa/thường, không làm hỏng escape ở ranh giới match (từ khóa chứa `&`, `<` không xảy ra
  vì tokenize chỉ nhận `[a-z0-9]+`, nhưng phần *không* match vẫn phải escape đúng entity).
  Test riêng cho bảng: highlight hoạt động trong `<td>`/`<th>`.
- **Unit — `query.py`**: `QueryResult.match_mode` mặc định `"keyword"`; kết quả từ
  `_semantic_fallback()` có `match_mode == "semantic"`. `tokenize()` (đổi tên từ
  `_tokenize`) — cập nhật lại chỗ gọi nội bộ trong `search()`.
- **Integration — `web/ui.py`**: request `/ui?q=...` trả về HTML chứa `<mark>` bọc đúng
  từ đã gõ; request với `tags` only (không `q`) không có `<mark>` nào (terms rỗng).
  Request buộc semantic fallback (mock embedder) → badge `match-semantic` xuất hiện,
  request BM25 bình thường → badge `match-keyword`.
- **Visual/manual**: chạy `python -m center_kb.mcp --transport http` (hoặc entrypoint HTTP
  hiện có), kiểm tra 320/768/1024/1440px
  — trang search/doc-list/doc-table rộng ra rõ rệt, trang section vẫn giữ độ rộng đọc
  thoải mái, không có tràn ngang (`overflow-x`) ở bất kỳ breakpoint nào.

## 5. Rủi ro & ghi chú

- Đổi `_tokenize` → `tokenize` (bỏ `_`) là đổi tên public API nội bộ trong `query.py` —
  rà lại toàn bộ chỗ gọi (`search()` dùng nội bộ, cần cả `web/ui.py` import mới) trước khi
  merge.
- Giới hạn thật của retrieval (BM25 chỉ thấy title+summary, không thấy full L2) vẫn còn
  đó sau đợt này — badge/highlight chỉ làm **hiện rõ** hạn chế này cho người dùng thấy,
  không giải quyết tận gốc. Nếu sau này BA vẫn gặp nhiều kết quả "semantic mờ", nên quay
  lại cân nhắc index full-text.
