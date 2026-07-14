# OIDC Intake Publish — tách quyền nộp bài khỏi quyền ghi hub — Design

**Ngày:** 2026-07-15
**Nguồn:** phiên brainstorm 2026-07-15; mở rộng federation design (`2026-07-13-hub-federation-single-source-design.md`)
**Phạm vi:** thêm đường publish thứ ba — **intake mode** — để repo con đóng góp tri thức lên hub qua PR mà **không giữ bất kỳ secret nào có quyền ghi hub**. Máy dev zero secret; CI child xác thực bằng OIDC JWT; một service trung tâm (mở rộng HTTP MCP server hiện có) verify danh tính, cầm GitHub App token, và mở PR trên hub.

## 1. Vấn đề & mục tiêu

PR mode hiện tại (`publish.py::_publish_pr`) push branch `publish/<rid>` **thẳng lên hub repo** — nên child (hoặc CI child) phải giữ GH_TOKEN có write access hub. Leak một child = rủi ro cả hub. Quyền "nộp bài" và quyền "cầm secret ghi" đang dính vào cùng một chỗ.

Mục tiêu: tách hai quyền đó.

Tiêu chí hoàn thành:

1. Từ máy dev của contributor, `kb publish` chạy xong in ra PR URL trên hub — máy dev **không có** GitHub token, không có secret intake, không đụng GitHub API.
2. Child repo **không chứa secret nào**: workflow chỉ cần `permissions: id-token: write` + URL intake.
3. Credential ghi hub (GitHub App private key) chỉ tồn tại trên server intake; installation token mint ngắn hạn mỗi request.
4. Child A không thể mạo danh child B (ghi đè `federation/<rid-của-B>/`) dù cầm JWT hợp lệ của chính nó.
5. Đăng ký child mới không cần đụng server: một PR sửa `federation/registry.yaml` trên hub.
6. Hai mode cũ giữ nguyên: **direct** (hub local-path — demo/test) và **PR mode gh** (ai vốn có write hub: chính hub, maintainer).

Ngoài phạm vi:

- Child chạy CI ngoài GitHub Actions (GitLab CI, Jenkins) — OIDC issuer khác, đợt sau.
- Rate limiting / chống spam tinh vi trên intake — mạng nội bộ/VPN, registry đã là allowlist.
- Tự động hoá review/merge PR trên hub — con người vẫn là cổng duy nhất.
- Dev machine POST trực tiếp lên intake bằng token tĩnh — loại có chủ đích (quay lại static secret).

## 2. Các quyết định thiết kế đã chốt

| # | Quyết định | Lựa chọn | Lý do |
|---|---|---|---|
| 1 | Xác thực child | **OIDC JWT của GitHub Actions** — không secret tĩnh trên child | JWT sống ~5 phút, GitHub cấp lúc job chạy, chứa claim `repository` không giả được. Leak không có gì để leak. |
| 2 | Ai cầm quyền ghi hub | **GitHub App** install đúng 1 repo hub, quyền `contents: write` + `pull_requests: write`; private key chỉ trên server | Installation token ngắn hạn, thu hồi được, phạm vi hẹp nhất có thể. Bot PAT bị loại: sống dài, phạm vi rộng. |
| 3 | Intake sống ở đâu | **Mở rộng HTTP MCP server hiện có** (`create_http_app` gắn thêm `/intake/*`) | Server đã tồn tại, đã clone hub, đã có deploy doc + systemd. Một chỗ deploy. Service riêng (sạch phân quyền hơn) là YAGNI ở quy mô hiện tại. |
| 4 | Trigger CI child | **Tag `kb-publish/*`** — không phải mọi push `.kb/` | Chủ động: chỉ `kb publish` mới tạo tag; commit `.kb/` thường ngày im lặng. Tag push qua git thuần, không cần GitHub API/token trên máy dev. |
| 5 | Máy dev theo dõi kết quả | **Poll `GET /intake/status`** của service — không poll GitHub API | Giữ zero GitHub auth kể cả khi child private. Service biết PR nó vừa mở. |
| 6 | Allowlist | **`federation/registry.yaml` trong hub repo**: map `owner/repo → repo_id` | Server đọc từ hub clone (tự tươi theo pull). Đăng ký = PR, cũng qua review, không đụng server. `repo_id` lấy từ registry — không tin payload. |
| 7 | Chống PR spam | Branch `publish/<rid>` cố định, force-push cập nhật PR đang mở | Mỗi child tối đa 1 PR mở trên hub (cơ chế sẵn có của PR mode, tái dùng). |

## 3. Kiến trúc & luồng dữ liệu

**4 thành phần:**

1. **Child repo** — zero secret. Workflow `kb-publish.yml` (scaffold bởi `kb init`): `on: push: tags: ['kb-publish/*']`; `permissions: id-token: write, contents: read`; steps: checkout tag, pack `.kb/` tarball, xin OIDC JWT với `audience` = intake URL, POST tarball + JWT + source commit lên `POST /intake/publish`.
2. **Máy dev** — `kb publish` (config có `intake:`): kiểm `.kb/` đã commit sạch → tạo tag `kb-publish/<utc-timestamp>` trỏ HEAD → `git push origin <tag>` → poll `GET /intake/status?repo_id=...&commit=...` tới khi có PR URL → in ra.
3. **Intake** (trong HTTP server): verify JWT → tra registry ra `repo_id` → safe-extract tarball vào temp → chạy lõi publish PR-mode trên hub clone của server → mint GitHub App installation token → push branch `publish/<rid>` → mở PR qua REST API (không cần `gh` CLI server-side) → ghi status.
4. **Hub** — GitHub App install; branch protection main giữ nguyên; merge PR = cổng review duy nhất.

**Luồng:**

```
dev sửa .kb/ → commit + push child
  → kb publish: tag kb-publish/<ts> + push tag
  → CI child: tarball + OIDC JWT (aud = intake) → POST /intake/publish
  → intake: verify JWT → registry → snapshot → App token → PR trên hub
  → kb publish (đang poll status) in PR URL
  → hub owner review + merge → tri thức chính thức tồn tại
```

## 4. Security intake

**Verify JWT (thứ tự chặn):**

1. Chữ ký RS256 qua JWKS `https://token.actions.githubusercontent.com/.well-known/jwks` — cache key theo `kid`, refresh khi gặp `kid` lạ.
2. `iss` = `https://token.actions.githubusercontent.com`.
3. `aud` = intake URL (cấu hình `CENTER_KB_INTAKE_AUDIENCE`) — JWT xin cho audience khác bị chặn.
4. `exp`/`iat` — JWT Actions sống ~5 phút.
5. Claim `repository` tra trong `federation/registry.yaml` — không có: 403 kèm hướng dẫn mở PR thêm vào registry.
6. Claim `ref` phải khớp `refs/tags/kb-publish/*` — chặn workflow từ branch/PR lạ. Fork của child chạy workflow không mang claim `repository` của repo gốc → registry chặn.

**Chống mạo danh giữa child:** `repo_id` chỉ lấy từ registry theo claim `repository`. Không trường nào trong payload quyết định đường ghi.

**Giới hạn payload:** tarball cap 50 MB (config được); safe-extract — chặn `..`, đường dẫn tuyệt đối, symlink/hardlink, chỉ file thường; đích qua guard `is_relative_to` (như `_snapshot` hiện có).

**GitHub App:** private key chỉ trên server (env trỏ file / secret manager). Mỗi request mint installation token (~1h), dùng xong bỏ. Leak installation token = ghi branch không bảo vệ + mở PR — main vẫn có branch protection.

**Status endpoint:** `GET /intake/status` trả `{state, pr_url}` theo `(repo_id, source_commit)` — không nội dung tri thức; cùng giả định mạng nội bộ/VPN như MCP hiện tại.

## 5. Thay đổi module

```
src/center_kb/
├── intake.py       # MỚI — verify OIDC JWT (JWKS cache), registry lookup,
│                   #   safe-extract tarball, gọi lõi publish, status store (in-memory + file)
├── ghapp.py        # MỚI — GitHub App: mint app JWT, đổi installation token,
│                   #   mở PR qua REST API; fake-able cho test
├── publish.py      # sửa — tách _publish_pr thành lõi nhận credential provider:
│                   #   gh CLI (dev có write) | App token (intake). Thêm mode "intake"
│                   #   phía CLI: tag kb-publish/<ts> + push + poll status
├── models.py       # sửa — +Registry {github_repo → repo_id}, +IntakeStatus
├── federation.py   # sửa — đọc/validate federation/registry.yaml
├── mcp.py          # sửa — create_http_app gắn /intake/publish + /intake/status;
│                   #   env: CENTER_KB_GH_APP_ID, CENTER_KB_GH_APP_KEY, CENTER_KB_INTAKE_AUDIENCE
├── cli.py          # sửa — kb publish đọc config: intake: <url> → flow tag+poll
├── config.py       # sửa — +intake url trong .kb/config.yaml
└── initcmd.py      # sửa — template kb-publish.yml mới (tag trigger, id-token, POST intake)
```

Dependency mới: `PyJWT[crypto]` — chỉ trong extra `[server]`; CLI child không cần.

Chọn mode publish: `.kb/config.yaml` có `intake:` → intake mode; không có → auto như hiện tại (github remote + gh → PR mode; còn lại direct). `--direct`/`--pr` flag vẫn override.

## 6. Xử lý lỗi

| Tình huống | Hành vi |
|---|---|
| Repo không có trong registry | 403 + "mở PR thêm `owner/repo: repo-id` vào federation/registry.yaml" |
| JWT hỏng/hết hạn/aud sai | 401; log claim tóm tắt, không bao giờ log token |
| Tarball quá cap / path traversal / symlink | 413 / 400; không ghi gì vào hub clone |
| Push branch hub fail (race) | retry kiểu `_push_with_retry`; kiệt retry: 502 — CI child fail đỏ, dev thấy ngay |
| App key thiếu/hỏng lúc server start | intake route tắt, MCP đọc vẫn chạy, log rõ lý do |
| `kb publish` local: `.kb/` dirty | lỗi liệt kê file chưa commit, không tạo tag |
| Poll status timeout | in link Actions run của child + hướng dẫn xem log |
| Registry YAML hỏng trên hub | intake trả 503 "registry invalid" — fail đóng, không fail mở |

## 7. Testing

- **`intake.py`:** JWT ký bằng RSA key test, JWKS fake local — phủ từng nhánh chặn (chữ ký, iss, aud, exp, ref, registry). Tarball: traversal, symlink, oversize, tar bomb cap.
- **`ghapp.py`:** HTTP fake ghi lại request, trả installation token + PR URL giả.
- **End-to-end intake:** POST vào `create_http_app` test client, hub local-path — verify branch `publish/<rid>`, snapshot, index tổng, status endpoint trả PR URL.
- **CLI:** `kb publish` intake mode trên repo tmp — tag đúng format `kb-publish/<ts>`, push đúng remote, poll parse đúng, dirty tree bị chặn.
- **Golden gate hiện có:** không đổi (đường đọc không chạm).
- Hermetic toàn bộ: không network thật, không GitHub thật. Coverage ≥80% như chuẩn dự án.

## 8. Migration & vận hành

1. Tạo GitHub App (owner hub): quyền `contents: write` + `pull_requests: write`, install lên hub repo; lưu App ID + private key vào server.
2. Server: nâng cấp package, set `CENTER_KB_GH_APP_ID`, `CENTER_KB_GH_APP_KEY`, `CENTER_KB_INTAKE_AUDIENCE`; restart — intake route bật.
3. Hub: thêm `federation/registry.yaml` (PR đầu tiên có thể tạo tay).
4. Mỗi child: `kb init` lại (hoặc chép template) để có `kb-publish.yml` mới + `intake:` trong `.kb/config.yaml`; xoá GH_TOKEN hub khỏi secrets của child — không còn chỗ nào dùng.
5. Docs: cập nhật `docs/deploy-remote-mcp.md` (env mới) + QUICKSTART-child (flow publish mới).
