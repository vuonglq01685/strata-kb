# AERO-KB Phase 2 (Tích hợp workflow) — Design

**Ngày:** 2026-07-10
**Nguồn:** `AERO-KB_Architecture_v0.1.pdf` (spec kiến trúc tổng thể, v0.1 — 09/07/2026), roadmap §13 Phase 2
**Phạm vi:** MCP server stdio + `.mcp.json`; block `kb-context` chuẩn hóa; `kb_resolve`, `kb diff`, `kb doctor`; heading pattern thành config (tồn đọng Phase 1).

## 1. Mục tiêu & tiêu chí hoàn thành

Trọng tâm Phase 2: **đóng vòng BA → Jira → Dev quanh một KB duy nhất** — requirement mang theo context máy-đọc-được, Dev resolve đúng version BA đã dùng, amendment là sự kiện phát hiện được.

Tiêu chí hoàn thành (từ roadmap §13, cụ thể hóa):

1. Một requirement đi trọn vòng: BA sinh block `kb-context` bằng `kb context new` → dán vào Jira ticket → Dev gọi `kb_resolve` qua MCP, nhận đúng section, đúng version đã pin.
2. Amendment thử nghiệm được phát hiện: sửa 1 section → `kb_resolve`/`kb doctor --context` báo `stale`, `kb diff` chỉ ra đúng section thay đổi.
3. `.mcp.json` nằm trong repo — clone về, mở Claude Code là 3 MCP tool dùng được ngay, không cần cài đặt thêm.
4. Response `kb_search` luôn nằm trong token budget client khai báo (kiểm chứng bằng test + `kb stats`).

Ngoài phạm vi Phase 2: gọi Jira API (agent + Jira MCP có sẵn đảm nhiệm), kb-hub federation, remote HTTP MCP, embedding search, codebase extraction. DoR có citation là quy ước quy trình team — spec này chỉ cung cấp công cụ (`kb context new`, `kb doctor --context`).

## 2. Các quyết định thiết kế đã chốt

| # | Quyết định | Lựa chọn | Lý do |
|---|---|---|---|
| 1 | MCP framework | **Official MCP Python SDK** (package `mcp`, FastMCP API) | SDK chính thức, protocol/stdio/schema lo sẵn; decorator sinh schema từ type hints khớp code style hiện tại; Phase 3 đổi transport không đổi code tool. Loại tự viết JSON-RPC (rủi ro lệch protocol) và FastMCP 2.x bên thứ ba (thừa tính năng). |
| 2 | Tích hợp Jira | **Chỉ format + resolve, không gọi Jira API** | Engine định nghĩa schema `kb-context` + resolve; đọc/ghi ticket do agent (Cowork/Claude Code + Jira MCP) đảm nhiệm. Engine không phụ thuộc mạng/credentials. |
| 3 | `kb diff` | **Diff với git revision** (mặc định HEAD) | Tận dụng Git đúng triết lý docs-as-code; không storage riêng, không parse lại PDF cũ. |
| 4 | `kb doctor` | **Sức khỏe KB nội tại + check kb-context đưa vào** (file/stdin) | Chạy được trong CI; agent/CI tự lấy block từ Jira đưa vào. |
| 5 | L1 manifest 28K token (tồn đọng Phase 1) | **Không nén** | Qua MCP, agent không bao giờ nạp manifest — BM25 chạy bằng code phía server, chỉ trả kết quả đã cắt theo budget. Kiểm chứng bằng test budget (tiêu chí 4). |
| 6 | Heading pattern (lưu ý engine thuần) | **Chuyển thành config, default = quy ước tiếng Anh hiện tại, persist vào `_manifest.yaml`** | Engine không hardcode quy ước trình bày; tri thức về cách trình bày của tài liệu cụ thể nằm trong `.kb/` (content). |
| 7 | `--hub` | **MCP server đọc `--hub` optional ngay từ Phase 2, chưa kích hoạt** | Đúng mẫu `.mcp.json` §10.3; Phase 3 chỉ viết logic hub, không đổi interface. |

## 3. Kiến trúc module

Mọi thứ mới là adapter quanh tầng query hiện có. Phụ thuộc một chiều: `mcp.py`/`cli.py` gọi xuống engine, không module engine nào import ngược lên.

```
src/aero_kb/
├── mcp.py          # MỚI — MCP server stdio, entry: python -m aero_kb.mcp
├── kbcontext.py    # MỚI — schema block kb-context + parse/render
├── resolve.py      # MỚI — resolve refs theo version đã pin + freshness
├── diff.py         # MỚI — so sánh KB giữa worktree và git rev
├── doctor.py       # MỚI — kiểm tra sức khỏe KB + staleness kb-context
├── gitio.py        # MỚI — đọc file .kb/ tại một git rev (git show); chỗ duy nhất chạy subprocess git
├── query.py        # giữ nguyên — search/get_section
├── cli.py          # thêm lệnh: diff, doctor, resolve, context new
└── ingest/
    └── sectioner.py  # sửa — heading pattern nhận từ HeadingConfig
```

## 4. MCP server (`mcp.py`)

Adapter mỏng — mỗi tool ≤ ~20 dòng, gọi thẳng engine:

| Tool | Signature | Gọi xuống |
|---|---|---|
| `kb_search` | `(query: str, tags: list[str] \| None = None, budget: int = 2000)` | `query.search()` |
| `kb_get_section` | `(doc: str, section: str, level: str = "l2")` | `query.get_section()` |
| `kb_resolve` | `(kb_context: str)` | `kbcontext.parse()` + `resolve.resolve_refs()` |

Kết quả trả về dạng text có header citation (nhất quán với output CLI) — agent đọc trực tiếp.

**Khởi động:** `python -m aero_kb.mcp --kb .kb/ [--hub <url>]`. `--hub` parse vào `ServerConfig(kb_dir: Path, hub: str | None)`; Phase 2 chỉ log "hub configured but not active until Phase 3" khi có giá trị.

**`.mcp.json`** tại root repo (chưa khai `--hub` vì hub chưa tồn tại; thêm arg là chạy):

```json
{
  "mcpServers": {
    "aero-kb": {
      "command": "python",
      "args": ["-m", "aero_kb.mcp", "--kb", ".kb/"]
    }
  }
}
```

## 5. Block `kb-context` (`kbcontext.py`)

Schema chuẩn hóa theo Phụ lục A của spec kiến trúc, model bằng pydantic:

```yaml
kb-context:
  version: a3f9c21          # commit hash của repo chứa .kb/ lúc BA viết
  refs:
    - arinc-424 §5.3
    - arinc-424 §5.3.2
  tags: [arinc424, airspace, talora]
```

- **Parse khoan dung với đầu vào:** `parse(text)` nhận cả block YAML thuần lẫn nguyên văn ticket Jira — tìm block `kb-context:` đầu tiên, cắt theo indent. Agent ném cả description ticket vào `kb_resolve` là đủ.
- **Ref format:** `<doc-id> §<section-id>` — parse chặt; sai format báo lỗi chỉ rõ ref nào hỏng. Chấp nhận cả biến thể không có `§` (`arinc-424 5.3`) để chống lỗi gõ tay, nhưng `kb context new` luôn sinh dạng chuẩn có `§`.
- **Sinh block:** `kb context new --refs "arinc-424 §5.3,arinc-424 §5.3.2" --tags arinc424,airspace` — lấy commit hash HEAD hiện tại, validate mọi ref resolve được rồi mới in block (chặn citation gãy từ lúc viết). Repo có thay đổi chưa commit trong `.kb/` → cảnh báo (hash pin sẽ không chứa thay đổi đó).

## 6. Resolve theo version pin (`resolve.py` + `gitio.py`)

- `gitio.read_at(rev, path)` — `git show <rev>:<path>`, path tính tương đối từ git root (hoạt động đúng khi `--kb` là đường dẫn tuyệt đối hoặc CWD khác root).
- `resolve.resolve_refs(kb_dir, ctx)` — với mỗi ref:
  1. Đọc manifest + L2 **tại commit `ctx.version`** → đúng nội dung BA đã thấy lúc viết.
  2. So **nội dung L2 của section** tại bản pin với worktree hiện tại (đúng tầng BA đã đọc lúc viết) → trạng thái freshness:
     - `ok` — section không đổi từ lúc pin.
     - `stale` — section đã thay đổi (amendment sau khi BA viết) → Dev trao đổi lại với BA trước khi code (flow §11.2 spec kiến trúc).
     - `broken` — không resolve được (sai doc/section id, section bị xóa, rev không tồn tại), kèm lý do cụ thể; không ảnh hưởng các ref còn lại.
- Output `kb_resolve`: mỗi ref một khối `[citation @ version] status=...` + nội dung L2 tại bản pin; ref `stale` kèm 1 dòng "section đã đổi ở HEAD — chạy kb diff để xem thay đổi".

## 7. `kb diff <doc-id> --against <rev>` (`diff.py`)

Mặc định `--against HEAD` — khớp flow amendment: re-ingest bản mới đè worktree rồi diff với bản đã merge.

- So cây section giữa manifest tại rev và worktree → **added / removed**.
- Section có ở cả hai bên: so summary (L1) và nội dung raw L3 → **changed** (cờ `summary`, `content`, hoặc cả hai).
- Output nhóm theo loại, mỗi dòng một section kèm title — chính là danh sách SME cần review.

Lưu ý: `kb diff` chỉ so L1 (summary) và L3 (raw) — không so L2, nên một sửa đổi chỉ chạm L2 sẽ không hiện ở đây dù `kb resolve` đã báo `stale` (§6).

## 8. `kb doctor` (`doctor.py`)

Một lệnh, hai chế độ:

**a) Sức khỏe KB nội tại** (mặc định, chạy trong CI):
- index.yaml ↔ thư mục doc khớp hai chiều (doc trong index thiếu manifest; manifest mồ côi ngoài index).
- Mỗi section trong manifest: file L2/L3 tồn tại và slice được đúng section id.
- File `.md` mồ côi trong `.kb/` không thuộc manifest nào.
- Đếm section `pending` (warning, không fail).

**b) Kiểm tra kb-context:** `kb doctor --context <file|->` — parse block, resolve từng ref, báo `ok/stale/broken`.

**Exit code:** 0 = sạch; 1 = lỗi (broken ref, lỗi cấu trúc KB); 2 = chỉ có stale (CI phân biệt "cần BA xác nhận lại" với "hỏng").

## 9. Heading pattern thành config (`ingest/`)

- Dataclass `HeadingConfig(chapter_pattern: str, appendix_pattern: str)`; hai regex hiện tại (`^chapter\s+\d+...`, `^appendix\s+...`) trở thành **giá trị mặc định** — quy ước trung tính, không còn hằng số chôn trong logic sectioner.
- `kb ingest --chapter-pattern / --appendix-pattern` override khi tài liệu dùng quy ước khác ("Section N", "Phụ lục A"…). Regex phải có đủ capture group quy định (định danh + title) — validate lúc nhận arg.
- Config đã dùng **ghi vào `_manifest.yaml`** (block `ingest:`); re-ingest amendment tự đọc lại từ manifest, không phải truyền lại arg. Tri thức về cách trình bày của tài liệu cụ thể nằm trong `.kb/`.

## 10. Error handling

- **MCP tools không raise xuyên protocol:** lỗi domain trả text rõ ràng kèm gợi ý ("doc 'arinc424' không tồn tại — có: arinc-424, icao-annex-3").
- **Không có git / không phải git repo:** `gitio` báo tường minh; `kb_search`/`kb_get_section` vẫn hoạt động (chỉ resolve/diff/doctor `--context` cần git).
- **Rev pin không tồn tại** (force-push, shallow clone): ref đánh `broken` kèm lý do, các ref khác vẫn resolve.
- CLI giữ pattern hiện tại: lỗi qua `typer.secho` đỏ, exit code phân biệt (doctor 0/1/2).

## 11. Testing

Theo pattern hiện có (pytest, fixture `.kb/` tạm):

- **Unit:** `kbcontext` (block thuần / lẫn trong ticket text / format hỏng), `diff` (added/removed/changed từng loại), `doctor` (mỗi loại lỗi một fixture), `HeadingConfig` (override, persist manifest, validate capture group).
- **`gitio` + `resolve`:** fixture git repo tạm, commit `.kb/` 2 lần với section sửa giữa 2 commit → test 3 trạng thái ok/stale/broken bằng git thật, không mock.
- **MCP integration:** in-memory client session của SDK chính thức, gọi cả 3 tool end-to-end; test `kb_search` với budget nhỏ → tổng token content trả về không vượt budget (tiêu chí 4); test `--hub` được parse và không kích hoạt gì.
- **E2E nghiệm thu:** `kb context new` → giả lập amendment (sửa section) → `kb_resolve` báo stale → `kb diff` chỉ đúng section → `kb doctor --context` exit 2.

## 12. Ràng buộc kiến trúc (nhắc lại, áp dụng xuyên suốt)

1. `src/aero_kb/` là engine thuần — không hardcode tri thức ARINC/Annex; heading convention chỉ tồn tại dạng config default trung tính (§9).
2. `.kb/` là content thuần — không lẫn logic; config ingest per-doc nằm trong `_manifest.yaml` là metadata của content, không phải code.
3. `--hub` optional có mặt trong interface ngay từ Phase 2 (§4) — Phase 3 chỉ bật logic, không đổi interface.
