# Hub Federation = Single Source of Truth — Design

**Ngày:** 2026-07-13
**Nguồn:** phiên brainstorm 2026-07-13; kế thừa và đảo ngược một phần Phase 3 design (`2026-07-10-aero-kb-phase3-design.md`)
**Phạm vi:** đảo triết lý đọc của toàn hệ thống — `kb query` và mọi MCP tool **chỉ đọc `federation/` của hub**; `.kb/` local thuần là bàn soạn thảo; publish là bắt buộc và đi qua PR trên hub; thêm index tổng `federation/index.yaml`.

## 1. Mục tiêu & tiêu chí hoàn thành

Phase 3 coi hub là *enhancement* (local-first, hub optional). Thiết kế này đảo lại: **hub federation là nguồn tri thức duy nhất của dự án (sau này là cả công ty)**; nội dung chưa publish thì không tồn tại với người đọc.

Tiêu chí hoàn thành:

1. `kb query`, cả 4 MCP tool, và Web UI trả kết quả **chỉ từ `federation/` của hub** — không còn bất kỳ đường đọc nào vào `.kb/` local hay `.kb/` riêng của hub. Không có cờ thoát (`--local` không tồn tại).
2. `federation/<repo-id>/` chứa mirror **đầy đủ L0→L3** (kể cả `.raw.md`); `kb_get_section level=l3` hoạt động thuần qua hub. PDF gốc (bản quyền) vẫn nằm ngoài git như trước.
3. `federation/index.yaml` (index tổng) được đánh lại **deterministic** trong mỗi lần publish; `kb doctor` phát hiện index lệch; `kb reindex` đánh lại tại chỗ để cứu.
4. Publish có 2 chế độ: **PR mode** (hub có remote GitHub + `gh`) — merge PR là cổng review duy nhất; **direct mode** (hub local-path: demo, test, thư mục share) — push thẳng với pull-rebase-retry như Phase 3.
5. Block `kb-context` pin **một commit duy nhất: HEAD của hub**; mọi ref tự động qualify `repo:doc §sec`. Block cũ (pin commit repo local) báo `broken` kèm hint re-pin — breaking có chủ đích, ghi trong migration.
6. Hub được khai báo trong `.kb/config.yaml` (commit); thiếu config → lỗi kèm hướng dẫn 1 dòng; hub offline mà có cache → chạy tiếp với nhãn `stale`.

Ngoài phạm vi (ghi lại để đợt sau):

- Codebase extraction (§8 spec kiến trúc) — không đổi.
- OAuth/SSO cho HTTP MCP — bearer token vẫn đủ.
- Nhiều hub / hub phân tầng (phòng ban → công ty) — topology 1 hub duy nhất cho đến khi có nhu cầu thật.
- Dọn giá trị `status: reviewed` còn sót trong manifest các repo cũ — parser vẫn chấp nhận, không sản sinh mới.

## 2. Các quyết định thiết kế đã chốt

| # | Quyết định | Lựa chọn | Lý do |
|---|---|---|---|
| 1 | Nguồn đọc | **Federation-only tuyệt đối** — CLI lẫn MCP, không cờ thoát | Một đường đọc duy nhất, không lệch kết quả giữa tác giả và BA. Muốn search nội dung mới → publish trước. Loại `--local` (hai chế độ dễ lệch) và CLI-local/MCP-federation (hai code path). |
| 2 | Độ sâu dữ liệu federation | **Mirror đầy đủ L0→L3** | BA đọc full nội dung + verbatim qua hub, mọi tool hoạt động không cần repo gốc. Hub nặng hơn — chấp nhận, vẫn là text/YAML trong git. PDF gốc không commit. |
| 3 | Layout federation | **`federation/<repo-id>/` = copy nguyên trạng `.kb/`** + `_meta.yaml` | Toàn bộ code đọc hiện có (`_local_candidates`, `get_section`, `ensure_index`) tái dùng trực tiếp, chỉ đổi gốc trỏ. Loại layout slim `manifests/` cũ (phải viết đường đọc content song song). |
| 4 | Index tổng | **`federation/index.yaml` sinh deterministic từ các snapshot con, đánh lại ngay trong publish** (PR chứa luôn index mới); branch protection *require branches up to date* trên hub; `kb reindex` + `kb doctor` làm lưới an toàn | Không bắt hub phải có CI (hub local-path vẫn đúng). Regen deterministic → conflict giữa 2 PR song song chỉ cần chạy lại `kb publish`. |
| 5 | Cổng review | **PR vào hub là cổng duy nhất.** Bỏ `kb-review.yml`, lệnh `kb review`, `review.py`, trạng thái `reviewed`; giữ `pending`/`summarized` (pipeline summarize cần) | Gác đúng chỗ cần gác: cái gì được vào nguồn tri thức chung. Review ở repo con thành hình thức khi hub mới là nơi phát hành. Đảo quyết định #4 Phase 3 (publish không cần review) — bối cảnh đổi: federation giờ chứa nội dung thật, không chỉ index máy sinh. |
| 6 | Khai báo hub | **`.kb/config.yaml` commit trong repo** (`hub:`, optional `repo_id:`); ưu tiên `--hub` flag > env `CENTER_KB_HUB` > config | Clone repo là dùng được ngay (CLI, MCP, CI cùng một nguồn cấu hình); flag/env cho test và trường hợp đặc biệt. |
| 7 | `.kb/` riêng của hub | **Hub cũng publish chính nó** vào `federation/<hub-repo-id>/` | Kiến trúc đồng nhất: một đường đọc duy nhất, hub không phải trường hợp đặc biệt. |
| 8 | Pin version kb-context | **Một trường `version` = HEAD hub; refs luôn `repo:doc §sec`** ; `hub_version` deprecated (parser vẫn đọc, không sản sinh) | Mọi nội dung nằm trong 1 repo git (hub) → 1 commit là đủ. Đơn giản hơn mô hình 2 commit của Phase 3. |
| 9 | Embeddings | **Đánh trên hub cache**, mỗi repo con một db: `<hub>/.kb-work/embeddings-<repo-id>.db`; không commit | Tái dùng `ensure_index` per-kb_dir; làm tươi tăng dần theo content-hash như cũ; lần đầu chậm — chấp nhận. |
| 10 | Tương thích ngược | Loader gặp entry federation **format cũ → skip + warn** "republish repo X"; CLI cũ đọc hub mới → skip + warn, không crash; manifest có `reviewed` vẫn parse được | Nâng cấp bằng đúng một lần `kb publish` mỗi repo (publish vốn xóa-ghi-lại toàn bộ entry). Không cần script migration. |

## 3. Kiến trúc module

```
src/center_kb/
├── config.py       # MỚI — đọc .kb/config.yaml (hub, repo_id); thứ tự ưu tiên flag > env > config
├── ghio.py         # MỚI — wrapper `gh pr create/view` (subprocess), fake-able cho test
├── federation.py   # sửa — load layout mirror mới (mỗi federation/<rid>/ đọc như một kb_dir);
│                   #        build_federation_index() -> FederationIndex (deterministic);
│                   #        entry format cũ (manifests/) → skip + warn
├── models.py       # sửa — +FederationIndex, +FedIndexEntry {repo_id, doc_id, title, revision,
│                   #        tags, source_commit, published_at}; SectionStatus bỏ sản sinh 'reviewed'
├── publish.py      # sửa — copy nguyên cây .kb/ → federation/<rid>/; regen index tổng;
│                   #        PR mode (branch ổn định publish/<rid>, force-push cập nhật PR đang mở);
│                   #        direct mode giữ pull-rebase-retry (regen index mỗi lần retry)
├── query.py        # sửa — search()/get_section() nhận HubHandle thay kb_dir; corpus = mọi repo
│                   #        trong federation; get_section auto-resolve doc-id unqualified nếu duy nhất,
│                   #        trùng → lỗi liệt kê ứng viên
├── embed.py        # sửa — db per-repo-id trong hub cache .kb-work/
├── kbcontext.py    # sửa — pin HEAD hub; auto-qualify refs 'repo:doc §sec'; hub_version deprecated
├── resolve.py      # sửa — resolve qua git history của hub clone (path federation/<rid>/<doc>/…)
├── mcp.py          # sửa — hub từ config; kb_get_section thêm param `repo` optional; --kb chỉ còn
│                   #        để tìm config.yaml
├── cli.py          # sửa — bỏ lệnh review; +kb reindex; publish thêm --pr/--direct;
│                   #        query/context/resolve/doctor đọc hub từ config
├── doctor.py       # sửa — checks mới: config có hub, hub reachable, local .kb có gì chưa publish
│                   #        (diff vs snapshot federation), index tổng khớp các snapshot con
├── initcmd.py      # sửa — scaffold .kb/config.yaml; template kb-publish.yml chuyển PR mode
├── review.py       # XÓA (cùng lệnh CLI + tests tương ứng)
└── web/            # sửa — đi qua search() mới, không đổi UI

.github/workflows/
├── kb-review.yml   # XÓA
└── kb-publish.yml  # sửa — push main có đổi .kb/ → kb publish (PR mode)

.claude/skills/kb-publish/  # sửa — luồng mới: diff vs federation → xác nhận → publish → link PR
scripts/demo-federation.sh  # sửa — theo luồng mới (direct mode, có hub tự publish chính nó)
```

Phụ thuộc một chiều giữ nguyên: `config`/`ghio` là tầng đáy, không import ngược.

## 4. Luồng dữ liệu

**Soạn thảo → phát hành:**

```
kb ingest → kb summarize → (chỉnh tay, commit repo con)
  → kb publish
      PR mode:  clone/pull hub cache → xóa-ghi federation/<rid>/ (mirror .kb/)
                → regen federation/index.yaml → commit trên branch ổn định publish/<rid>
                  (message mang source_commit) → force-push → gh pr create
                  (branch đã có PR mở → chỉ force-push là PR tự cập nhật)
                → [con người review + merge trên hub] → nội dung chính thức tồn tại
      direct:   như trên nhưng commit thẳng main + push (retry ≤3, mỗi retry regen index)
```

**Truy vấn (CLI + MCP + Web UI — cùng một đường):**

```
resolve hub (config → cache clone/pull theo TTL, offline → stale)
  → đọc federation/index.yaml → lọc tags → BM25 trên title+summary toàn corpus
  → dưới ngưỡng → semantic fallback (embeddings per-repo trong hub cache)
  → trả L2 + citation 'repo:doc §sec (revision)', source = <repo-id>
```

## 5. Xử lý lỗi & vận hành offline

| Tình huống | Hành vi |
|---|---|
| Thiếu `hub` trong config + không flag/env | Lỗi rõ: *"thêm `hub: <url\|path>` vào `.kb/config.yaml` (hoặc dùng `--hub`)"* — mọi lệnh đọc và publish |
| Hub unreachable, có cache | Chạy tiếp bằng cache, mọi kết quả kèm nhãn `stale (age ~Ns)` |
| Hub unreachable, chưa có cache | Lỗi rõ, không kết quả rỗng giả |
| PR mode nhưng thiếu `gh` / hub không phải GitHub | Lỗi kèm 2 lối thoát: cài `gh` hoặc `kb publish --direct` (nếu chính sách cho phép) |
| 2 PR publish song song lệch index tổng | Branch protection bắt cập nhật; chạy lại `kb publish` (regen deterministic, force-push cùng branch) |
| Index tổng lệch do merge tay/sự cố | `kb doctor` exit 1 + chỉ định `kb reindex`; `kb reindex` đánh lại từ các snapshot con rồi commit |
| Entry federation format cũ (Phase 3 slim) | Skip + warn "entry '<rid>' là format cũ — chạy `kb publish` từ repo đó" |
| Block kb-context cũ (pin commit repo local) | `kb_resolve` báo `broken`: *"block pin theo kiến trúc cũ — re-pin bằng kb_context_new"* |

## 6. Migration (README §mới)

1. Nâng cấp CLI mọi nơi (tool nội bộ, không giữ song song 2 version).
2. Mỗi repo: thêm `.kb/config.yaml` (`hub:` + `repo_id:`), xóa `kb-review.yml`, thay `kb-publish.yml` bằng template mới.
3. Mỗi repo (kể cả hub): chạy `kb publish` một lần — entry format cũ được thay bằng mirror đầy đủ, index tổng hình thành.
4. Hub GitHub: bật branch protection main (*require PR* + *require branches up to date*).
5. Ticket có block kb-context cũ: re-pin khi chạm vào lần tới (số lượng ít, không migrate hàng loạt).

## 7. Testing

- **Hermetic như hiện tại:** hub = local-path trong tmp dir; direct mode phủ toàn bộ đường ghi/đọc (publish → reindex → search → get_section l3 → context → resolve). Không network, không `claude` thật.
- **PR mode:** logic branch/commit test bằng git thật trên tmp repo; phần gọi `gh` cô lập trong `ghio.py`, test bằng fake (ghi lại lệnh, trả PR URL giả).
- **Tương thích ngược:** fixture entry federation format cũ → loader skip + warn; block kb-context cũ → `broken` đúng message; manifest chứa `reviewed` → parse được.
- **E2E:** `demo-federation.sh` cập nhật — hub + 2 repo con + hub tự publish, kiểm tra index tổng, search cross-repo trả L2 đầy đủ, l3 verbatim, citation `repo:doc`.
- Coverage giữ chuẩn dự án (≥80%).

---

*Thiết kế này thay thế các phần tương ứng của Phase 3 design: quyết định #4 (publish không review), #5 (local thắng khi va chạm — hết ý nghĩa vì local không còn được đọc), #6 (pin 2 nguồn). Các phần còn lại của Phase 3 (hub cache TTL, embedding sqlite-vec, HTTP MCP + bearer token) giữ nguyên.*
