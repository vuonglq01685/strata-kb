# AERO-KB — Web UI tra cứu + Đóng gói PyPI + Docker — Design

**Ngày:** 2026-07-11
**Trạng thái:** Đã duyệt thiết kế (chờ review spec)

## 1. Bối cảnh & mục tiêu

AERO-KB hiện có: CLI `kb` (typer), MCP server chạy stdio + streamable HTTP với bearer auth
(`src/aero_kb/mcp.py`), cơ chế hub/federation (`--hub`, `src/aero_kb/hub.py`), và
`pyproject.toml` build được wheel bằng hatchling.

Mục tiêu đợt này: biến repo thành một **deployable hub** hoàn chỉnh theo mô hình
"1 tiến trình trên máy chủ nội bộ (VPN)":

```
Máy chủ nội bộ (VPN)
┌───────────────────────────────────────────────────┐
│  repo AERO-KB (clone tại /srv/kb-hub)              │
│                                                    │
│  .kb/          ← nội dung domain FULL L2/L3        │  (1a) KB hoàn chỉnh
│  federation/   ← chỉ mục L0+L1 của repo con        │  (1b) hub trung tâm
│                                                    │
│  1 tiến trình:                                     │
│   python -m aero_kb.mcp --hub . --transport http   │  (2) MCP host + bearer token
│      ├ endpoint MCP  (agent/Claude Code gọi)       │  ← đã có sẵn
│      └ route REST + trang HTML (thêm mới)          │  (3) người tra tay
└───────────────────────────────────────────────────┘
```

Bốn hạng mục:

1. **Web layer**: REST JSON + trang HTML tra cứu, gắn vào chính tiến trình MCP HTTP hiện có.
2. **`kb init`**: scaffold repo KB mới — install xong là sẵn sàng ingest.
3. **Docker**: 1 image đủ cả ingest + serve; `docker compose up` là chạy được hub,
   `docker compose run` là ingest được doc đầu tiên.
4. **Đóng gói & publish**: metadata chuẩn PyPI công khai, release pipeline tự động
   (PyPI + GHCR).

## 2. Phạm vi

**Trong phạm vi:**
- REST read-only + UI tra cứu đầy đủ (search, duyệt cây L0→L1→section, xem L2/L3).
- Auth cookie cho trình duyệt (dùng chung token với bearer).
- Lệnh `kb init` scaffold.
- `Dockerfile`, `docker-compose.yml`, release workflow (PyPI trusted publishing + GHCR).

**Ngoài phạm vi (YAGNI):**
- Dashboard quản trị (trạng thái pending/reviewed, thống kê token) — để đợt sau.
- Ghi/sửa KB qua web (web hoàn toàn read-only; mọi thay đổi vẫn đi qua Git/PR).
- Hệ thống user/password, phân quyền nhiều cấp.
- SPA framework, build step Node.

## 3. Hướng tiếp cận đã chọn

**Hướng A — mount thêm route vào chính Starlette app hiện tại.** FastMCP
`streamable_http_app()` là một Starlette app; ta dựng Starlette app cha bao gồm cả ba
nhánh trong **một tiến trình, một port**. REST/UI/MCP cùng gọi chung `query.py`,
`resolve.py`, `models.py` — không viết lại logic, không thêm dependency
(starlette + uvicorn đã có trong `[project.dependencies]`).

Hai hướng bị loại:
- App web riêng (FastAPI + reverse proxy): thêm process + dependency, trái mục tiêu
  "1 tiến trình".
- Site tĩnh sinh từ `kb build`: mất BM25 server-side và federation theo TTL.

## 4. Web layer

### 4.1. Cấu trúc process

```
Starlette app cha (module mới: src/aero_kb/web/app.py)
├── /mcp        → FastMCP streamable_http_app (giữ nguyên, cho agent)
├── /api/*      → REST JSON (src/aero_kb/web/api.py)
├── /ui/*       → HTML (src/aero_kb/web/ui.py + src/aero_kb/templates/web/)
└── /           → redirect 302 → /ui
```

`python -m aero_kb.mcp --transport http` giữ nguyên cách chạy; `create_http_app()`
trả về app cha thay vì chỉ app MCP. Đường stdio không đổi.

### 4.2. REST endpoints (tất cả read-only)

| Endpoint | Trả về |
|---|---|
| `GET /api/docs` | L0 — danh sách tài liệu local + federation (khi chạy `--hub`) |
| `GET /api/docs/{doc}` | L1 — manifest: section (id, title, summary, status) |
| `GET /api/docs/{doc}/sections/{section}?level=l2\|l3` | Nội dung 1 section + citation + số token |
| `GET /api/search?q=…&tags=…&budget=…` | Kết quả BM25 như `kb_search`, JSON có cấu trúc (citation, score, tokens, content) |
| `GET /api/health` | Trạng thái server + tuổi cache hub. **Không cần auth** (dùng cho healthcheck) |

Tham số `tags` là danh sách phân tách bằng dấu phẩy; `budget` mặc định 2000, giới hạn
trên 20000; `level` mặc định `l2`.

### 4.3. Trang HTML

Server-rendered, zero build step. Template + CSS nhúng trong package, đọc qua
`importlib.resources` để wheel publish lên PyPI vẫn tự chứa.

- `/ui` — trang chính: ô tìm kiếm + filter tags; kết quả hiện citation, score,
  nội dung L2.
- `/ui/docs` — duyệt cây: danh sách tài liệu → manifest L1 (kèm status từng section).
- `/ui/docs/{doc}/{section}` — trang section: render L2, nút "Xem nguyên văn L3",
  nút copy citation.
- `/ui/login` — form dán token (xem 4.4).

**Markdown → HTML render server-side** bằng parser tối giản tự viết
(`src/aero_kb/web/mdrender.py`) cho đúng subset đang dùng trong L2/L3: heading, đoạn
văn, bảng pipe. Bảng render giữ nguyên **từng ký tự từng ô** — nhất quán với nguyên tắc
bất khả xâm phạm "bảng không đi qua tay AI/diễn giải". Mọi nội dung đều được
HTML-escape trước khi chèn vào template (chống XSS từ nội dung KB).

### 4.4. Auth

- Mở rộng `BearerAuthMiddleware`: chấp nhận `Authorization: Bearer <token>` **hoặc**
  cookie `aero_kb_token`; so sánh bằng `hmac.compare_digest` như hiện tại.
- `GET /ui/login`: form dán token. `POST /ui/login`: token đúng → set cookie
  `aero_kb_token` (HttpOnly, SameSite=Lax) → redirect `/ui`; token sai → hiện lại form
  với thông báo lỗi (không tiết lộ gì thêm).
- Route không cần auth: đúng 2 cái — `/api/health` và `/ui/login`.
- Request tới `/ui/*` chưa có auth → redirect 302 về `/ui/login`;
  request tới `/api/*` và `/mcp` chưa có auth → 401 JSON như hiện tại.
- Token vẫn lấy từ env `AERO_KB_HTTP_TOKEN`; thiếu env → từ chối khởi động
  (giữ hành vi hiện có).

### 4.5. Federation

UI/REST chạy trên hub process với `--hub .` nên `search()`/`get_section()` tự bao gồm
chỉ mục L0+L1 của repo con qua tham số `hub=` sẵn có — không cần code federation riêng
cho web. Kết quả từ repo con hiển thị kèm nguồn (tên repo con) trong citation.

### 4.6. Xử lý lỗi

- REST: JSON `{"error": "...", "detail": "..."}` với mã chuẩn — 400 (tham số sai),
  401 (thiếu/sai auth), 404 (doc/section không tồn tại; kèm gợi ý danh sách doc như
  `kb_get_section` đang làm).
- UI: trang lỗi thân thiện cùng layout, không bao giờ lộ traceback.
- Lỗi không lường trước: log server-side đầy đủ, trả 500 với thông điệp chung.

## 5. Lệnh `kb init`

`kb init [path]` (mặc định `.`) tạo bộ khung repo KB:

```
.kb/index.yaml            ← L0 rỗng hợp lệ (docs: [])
federation/README.md      ← giải thích cách đăng ký repo con
source/.gitignore         ← chặn commit PDF bản quyền (*.pdf)
.mcp.json                 ← mẫu: aero-kb qua stdio, trỏ .kb/
.github/workflows/kb-review.yml  ← copy từ workflow auto-flip reviewed hiện có
docker-compose.yml        ← chạy hub (mục 6)
.env.example              ← AERO_KB_HTTP_TOKEN=change-me
QUICKSTART.md             ← 5 bước: init → ingest → summarize → build → serve
```

Nguyên tắc:
- **Idempotent, không phá:** file đã tồn tại → bỏ qua + báo; kết thúc in bảng
  created/skipped. `--force` mới ghi đè.
- Template nhúng trong package tại `src/aero_kb/templates/init/`, đọc bằng
  `importlib.resources` (cùng cơ chế với web templates).
- Không tự chạy `git init` hay commit.
- Kết thúc in bước tiếp theo: `kb ingest source/<file>.pdf --doc-id <id>`.
- Nghiệm thu: `kb doctor` pass ngay trên bộ khung rỗng vừa tạo.

## 6. Docker

### 6.1. `Dockerfile` (gốc repo)

- Base `python:3.12-slim`, multi-stage: stage build tạo wheel (hatchling); stage
  runtime cài wheel + extra `[ingest]`.
- User không-root (`app`), `WORKDIR /data`.
- Model docling **không nướng vào image**; cache model mount ra volume — lần ingest
  đầu tải model, các lần sau dùng lại.
- `EXPOSE 8321`. Entrypoint mặc định:
  `python -m aero_kb.mcp --kb /data/.kb --hub /data --transport http --host 0.0.0.0`.

### 6.2. `docker-compose.yml` (template do `kb init` sinh)

```yaml
services:
  hub:
    image: ghcr.io/<org>/aero-kb:latest   # dev: thay bằng build: .
    ports: ["8321:8321"]
    env_file: .env                        # AERO_KB_HTTP_TOKEN
    volumes:
      - ./:/data                          # KB repo (.kb/, federation/, source/)
      - kb-model-cache:/home/app/.cache   # cache model docling
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request;urllib.request.urlopen('http://localhost:8321/api/health')"]
      interval: 30s
volumes:
  kb-model-cache:
```

`<org>` được chốt khi implement theo GitHub org/user thật của repo.

### 6.3. Trải nghiệm người dùng mới

```bash
pip install aero-kb
kb init && cp .env.example .env    # sửa token
docker compose up -d               # hub chạy: http://localhost:8321/ui
docker compose run --rm hub kb ingest source/my-doc.pdf --doc-id my-doc
```

## 7. Đóng gói & publish

### 7.1. Metadata

- `pyproject.toml` bổ sung: `readme`, `license = "Apache-2.0"` (chỉ áp cho **code**;
  nội dung `.kb/` bản quyền không bao giờ nằm trong package/wheel), `authors`,
  `classifiers`, `[project.urls]`; bump version `0.2.0`.
- Kiểm tra tên `aero-kb` trên PyPI ngay bước đầu khi implement; nếu bị chiếm →
  dự phòng distribution name `aero-kb-hub` (import path `aero_kb` giữ nguyên).

### 7.2. Đóng gói tài nguyên phi-code

- Cấu hình hatchling để wheel chứa `src/aero_kb/templates/` (web + init).
- Test tự động: build wheel → cài venv sạch → `kb init` chạy được + app web serve
  được template (chặn lỗi "quên file ngoài wheel").

### 7.3. Release pipeline (`.github/workflows/release.yml`)

```
push tag v* → pytest → build sdist+wheel
            → publish PyPI (trusted publishing OIDC — không lưu token)
            → build Docker image → push ghcr.io (:latest + :vX.Y.Z)
```

## 8. Testing (chuẩn coverage ≥ 80% của dự án)

- **REST + UI** (Starlette `TestClient`): 401 khi thiếu token/cookie; login flow
  (token đúng/sai); từng endpoint happy-path + 404; search trả đúng citation;
  L3 verbatim — bảng không bị render sai.
- **mdrender**: bảng giữ nguyên từng ký tự; HTML-escape nội dung.
- **`kb init`**: tạo đủ file; idempotent (chạy 2 lần không ghi đè); `--force`;
  `kb doctor` pass trên khung rỗng.
- **Wheel self-containment**: test mô tả ở 7.2.
- **Docker smoke test**: job CI riêng — build image, `docker compose up`, gọi
  `/api/health`; cho phép skip khi chạy local trên Windows.

## 9. Tiêu chí nghiệm thu tổng

1. Một tiến trình `python -m aero_kb.mcp --hub . --transport http` phục vụ đồng thời:
   MCP (agent), REST (`/api`), HTML (`/ui`) — cùng token.
2. Người không cài gì ngoài trình duyệt tra cứu được: login → search → đọc L2 →
   mở L3 → copy citation.
3. `pip install aero-kb && kb init` cho ra repo chạy được `kb doctor` pass.
4. `docker compose up` + `docker compose run … kb ingest` hoạt động đúng như mục 6.3.
5. Push tag `v0.2.0` → package lên PyPI + image lên GHCR tự động.
