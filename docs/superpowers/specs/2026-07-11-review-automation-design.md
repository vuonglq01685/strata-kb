# AERO-KB — Tự động hoá trạng thái `reviewed` (Review Automation) — Design

**Ngày:** 2026-07-11
**Nguồn:** `AERO-KB_Architecture_v0.1.pdf` §11 (flow SME/Reviewer), §12 (governance & audit trail), phase1-design §138 ("sau merge → `status: reviewed`")
**Phạm vi:** bổ sung lệnh `kb approve` + GitHub Action tự chuyển `summarized → reviewed` khi PR merge vào `main`. Không đổi engine tra cứu, không đổi format `.kb/`.

---

## 1. Bối cảnh

Trong AERO-KB, mỗi section đi qua 3 trạng thái: `pending` (chưa tóm tắt) → `summarized` (AI đã viết bản nháp) → `reviewed` (đã thẩm định, sẵn sàng để agent tra cứu). Trạng thái nằm ở field `status` trong `_manifest.yaml` (tầng L1, định nghĩa tại `models.py` — `SectionEntry.status`).

Hiện tại có một khoảng trống: **việc chuyển `summarized → reviewed` chưa được tự động hoá**. Field `status` chỉ được *định nghĩa* trong `models.py`; không có lệnh CLI, git hook hay CI nào flip nó. Kiến trúc (phase1-design §138) mô tả "sau merge → `reviewed`" như một *quy ước*, nhưng chưa có cơ chế thực thi. Hệ quả: tính đến 2026-07-11, **0/329 section** ở trạng thái `reviewed` — tất cả vẫn là `summarized`.

Điểm quan trọng về **con người trong quy trình**: trong bối cảnh hiện tại của đội, **người dựng knowledge base chính là SME**. Họ đọc, sửa và tự thẩm định nội dung *trước khi* mở Pull Request. Vì vậy bước "một người thứ hai duyệt lại" (gate approval bằng CODEOWNERS / branch protection / kiểm tra qua API) là **thừa** đối với quy mô và cách làm hiện tại, và đã được quyết định **bỏ đi**.

Nói cách khác: hành động thẩm định đã xảy ra rồi (trước khi tạo PR); cái còn thiếu chỉ là **phản chiếu** hành động đó vào field `status` một cách tự động, để KB có "dấu vết đã-được-duyệt" mà không phải sửa tay từng dòng YAML.

---

## 2. Quyết định

| # | Vấn đề | Quyết định | Lý do |
|---|---|---|---|
| 1 | Ai bấm nút cuối để đổi trạng thái | **CI tự flip khi PR merge vào `main`** (hướng B) | Không thao tác tay; đội nhỏ, author = SME nên "đã merge = đã duyệt" là quy ước chấp nhận được. |
| 2 | Gate SME approval (CODEOWNERS / branch protection / API check) | **Bỏ** | Author chính là SME, đã review trước khi mở PR — thêm gate chỉ tăng ma sát, không tăng giá trị. |
| 3 | `kb build` có tự flip không | **Không** — tách riêng lệnh `kb approve` | `build` là chốt kiểm tra (bảng khớp, hết `pending`). Gộp việc đổi trạng thái vào build thành "cứ build là tự duyệt" — đúng cái bẫy cần tránh. |
| 4 | Phạm vi flip mỗi lần merge | **Chỉ các section thay đổi trong merge đó**, và chỉ những section đang ở `summarized` | Không đụng section `pending` (chưa xong) và không đóng dấu lại toàn repo mỗi lần. |
| 5 | Doc-id trong chế độ CI | **`--all-changed` không cần doc-id** — tự quét mọi doc trong `index.yaml` | CI chạy đúng 1 lệnh, không cần shell parse `git diff --name-only`. Dạng per-doc vẫn dùng được cho thao tác tay. |
| 6 | Đồng bộ hub/federation sau flip | **Chấp nhận độ trễ** — commit flip không kích hoạt lại `kb-publish` | `kb-publish.yml` là template cho repo con; consumer của federation đọc L1 summary, không đọc `status`. Ghi nhận là giới hạn đã biết (§6). |

**Đánh đổi đã chấp nhận (ghi rõ để sau này không hiểu nhầm):**

- `reviewed` từ nay mang nghĩa *"đã được merge vào `main`"*, không phải *"có người thứ hai soi lại"*. Hợp lệ **chỉ khi** giả định author = SME còn đúng; nếu sau này mở rộng đội (người dựng KB ≠ người thẩm định) thì phải bật lại gate (CODEOWNERS + branch protection require review) trước khi tin vào ý nghĩa của `reviewed`.
- Commit đổi trạng thái do **bot CI** tạo (`github-actions[bot]`), nên *danh tính người duyệt* không nằm ở commit này. Truy vết "ai duyệt" vẫn lấy được gián tiếp qua **người merge PR** trong lịch sử Git (audit trail §12 vẫn giữ được, chỉ là ở PR chứ không ở commit flip).
- Vì commit flip được push bằng `GITHUB_TOKEN` (không kích hoạt workflow khác), bản snapshot trên hub (nếu repo có publish lên federation) sẽ **trễ một nhịp** về giá trị `status` — chỉ cập nhật ở lần push nội dung kế tiếp. Xem §6.

---

## 3. Thiết kế

### 3.1 Lệnh mới: `kb approve`

```
kb approve [DOC_ID] [--section <id> ...] [--all-changed] [--against <rev>] [--kb-dir <path>]
```

Chức năng: đổi `status: summarized → reviewed` trong `_manifest.yaml`.

**Các chế độ:**

| Cách gọi | Hành vi |
|---|---|
| `kb approve <doc-id>` | Flip **tất cả** section đang `summarized` của doc đó |
| `kb approve <doc-id> --section 5.3 --section 5.4` | Chỉ flip các section chỉ định |
| `kb approve --all-changed --against <rev>` | **Chế độ CI**: quét mọi doc trong `index.yaml`, tính section thêm-mới/thay-đổi so với `<rev>`, flip chúng |
| `kb approve <doc-id> --all-changed --against <rev>` | Như trên nhưng giới hạn trong 1 doc (thao tác tay) |

**Quy tắc flip (mọi chế độ):**

- **Chỉ flip section đang `summarized`.** Gặp section `pending` → bỏ qua + cảnh báo ra stderr (không thể duyệt cái chưa tóm tắt). Section đã `reviewed` → giữ nguyên (idempotent — chạy lại nhiều lần vẫn an toàn).
- "Section thay đổi" trong chế độ `--all-changed` = tập `added ∪ changed` từ `DiffReport` (bất kỳ thay đổi nào ở summary/prose/content — xem §3.2).
- Ghi manifest bằng `models.save_yaml_model` (giữ format YAML hiện có).

**Exit code:**

| Code | Khi nào |
|---|---|
| `0` | Có section được flip; **hoặc** `--all-changed` không tìm thấy gì để flip (bình thường trong CI khi merge chỉ chạm ví dụ `index.yaml`) |
| `1` | Doc không tồn tại; rev không hợp lệ (`GitError`); `--section` chỉ định section không tồn tại; hoặc chế độ tường minh (`--section` / bare doc-id) không có section nào flip được |

Nguyên tắc: *yêu cầu tường minh mà không làm được gì = lỗi; quét tự động mà không thấy gì = thành công.*

**Vị trí code:** hàm lõi đặt ở module mới `src/aero_kb/review.py` (giữ `build.py` thuần validation, đúng bố cục file-per-concern hiện có). Command đăng ký trong `cli.py` theo pattern các lệnh hiện tại (lazy import, `typer.Exit`).

### 3.2 Mở rộng `diff.py` — bắt thay đổi L2

`diff_doc()` hiện so **L1** (`summary` trong manifest, dòng 71) và **L3** (`.raw.md`, dòng 73-86) — chưa so **L2** (file văn xuôi `{sec.file}.md`).

Mở rộng (không fork):

- Thêm field `prose_changed: bool = False` vào `SectionChange`.
- Trong `diff_doc()`, so L2 giống hệt cách đang so L3: đọc `{sec.file}.md` worktree, `gitio.read_at()` bản cũ, cắt theo section bằng `slice_section` (đã có ở `mdutils`), so sánh sau `.strip()`. Cache theo file như `raw_cache_*` hiện tại.
- `render_diff()` thêm kind `prose` bên cạnh `summary`/`content`.
- `review.py` tiêu thụ trực tiếp `DiffReport` — một engine phát hiện thay đổi duy nhất, không nhân bản logic.

(Trường hợp thường gặp — section vừa được tóm tắt — luôn đổi cả L1 nên vẫn bắt được kể cả không có mở rộng này; phần mở rộng L2 là để chắc chắn với các sửa đổi chỉ chạm văn xuôi.)

### 3.3 GitHub Action: `.github/workflows/kb-review.yml`

- **Trigger:** `push` vào `main` với path filter `.kb/**` (tức là *sau khi* PR đã merge). Đây là điểm khác biệt của hướng B so với "flip trong PR".
- **Điều kiện job (loop guard lớp 3):** bỏ qua nếu commit đẩy tới là của `github-actions[bot]` (check `github.event.head_commit.author` ngay ở `if:` của job).
- **Các bước:**
  1. `actions/checkout` với `fetch-depth: 0` (repo nhỏ; đảm bảo `BEFORE` luôn reachable, tránh lỗi shallow-clone mà `gitio.read_at` đã phải phòng).
  2. Cài tool: `pip install -e .`
  3. Xác định `BEFORE = github.event.before`. **Guard zero-SHA:** nếu `BEFORE` là `0000…0` (force-push / tạo branch) → fallback `HEAD^` (parent đầu của merge commit); nếu `HEAD^` cũng không có (commit đầu repo) → in thông báo và exit 0.
  4. Chạy đúng 1 lệnh: `kb approve --all-changed --against "$BEFORE"`.
  5. Nếu manifest có thay đổi → commit: `review: auto-mark reviewed @ <short-sha> [skip ci]` (short-sha = commit merge vừa xử lý), rồi `git push` bằng `GITHUB_TOKEN`.
- **Quyền:** `permissions: contents: write`.

### 3.4 Chống lặp vô hạn (loop guard) — 3 lớp

1. Commit flip mang `[skip ci]` trong message.
2. Push bằng `GITHUB_TOKEN` mặc định **không kích hoạt** workflow mới (cơ chế sẵn có của GitHub) — bot không tự gọi lại chính nó.
3. Điều kiện `if:` ở job bỏ qua khi author của head commit là `github-actions[bot]`.

### 3.5 Vòng đời một section (sau khi có tính năng này)

```
pending ──(AI tóm tắt qua skill kb-summarize)──> summarized
summarized ──(SME sửa/thẩm định + mở PR + merge vào main)──> reviewed   ← CI tự flip
reviewed ──(amendment: section bị sửa lại trong PR mới, merge)──> reviewed  ← CI flip lại theo lần merge mới
```

Vì author = SME, mỗi lần merge đều ngụ ý một lần thẩm định, nên việc flip-lại khi section đổi ở amendment là **đúng ý nghĩa**, không cần reset thủ công về `summarized`.

---

## 4. Kiểm thử

Pytest, theo style test hiện có (fixture KB tạm + git repo tạm như `test_gitio.py` / `test_publish.py`):

**`review.py` / `kb approve`:**

- Flip đúng section `summarized` → `reviewed`; manifest ghi lại đúng format.
- Section `pending` → bỏ qua, có cảnh báo stderr, exit 0 (khi có section khác flip được hoặc ở chế độ `--all-changed`).
- Idempotent: chạy lại trên section đã `reviewed` → không đổi gì, exit 0.
- `--section` trỏ section không tồn tại → exit 1.
- Chế độ tường minh không flip được gì → exit 1; `--all-changed` không thấy gì → exit 0.
- `--all-changed --against <rev>` bắt đúng tập section: added, changed-L1, changed-L3, và **changed-chỉ-L2**.
- Chế độ quét toàn bộ (không doc-id) xử lý nhiều doc trong một lần chạy.
- Doc không tồn tại / rev không hợp lệ → exit 1, message đỏ.

**`diff.py`:**

- Sửa chỉ L2 → `prose_changed=True`, `summary_changed=False`, `content_changed=False`; `render_diff` in kind `prose`.
- Các test hiện có của diff không đổi hành vi.

---

## 5. Việc cần làm (checklist triển khai)

- [ ] Mở rộng `diff.py`: `prose_changed` + so L2 + render kind `prose` (kèm test).
- [ ] Module mới `src/aero_kb/review.py`: hàm lõi approve (per-doc, per-section, all-changed, all-docs) tiêu thụ `DiffReport`.
- [ ] Đăng ký lệnh `kb approve` trong `cli.py` (doc-id optional, `--section` lặp được, `--all-changed --against`).
- [ ] Test đầy đủ theo §4.
- [ ] Thêm `.github/workflows/kb-review.yml` theo §3.3 + loop guard §3.4.
- [ ] Cập nhật README §7 (từ điển lệnh — thêm `kb approve`) và §9 (checklist SME — mô tả CI tự flip).
- [ ] Ghi rõ đánh đổi §2 + độ trễ hub §6 vào README §11 ("giới hạn hiện tại").

---

## 6. Giới hạn đã biết

1. **Độ trễ hub/federation:** `publish.py` copy nguyên manifest (kèm `status`) lên `federation/<repo-id>/` trên hub, nhưng commit flip của bot không kích hoạt `kb-publish` (hệ quả của loop guard lớp 2). Nếu repo có publish lên hub, bản snapshot trên hub sẽ giữ `summarized` cho tới lần push nội dung kế tiếp. Chấp nhận vì consumer federation đọc L1 summary chứ không quyết định gì dựa trên `status`.
2. **`reviewed` = "đã merge vào main":** chỉ đúng khi author = SME (xem đánh đổi §2).

## 7. Ràng buộc giữ nguyên

1. `kb build` **không** đổi trạng thái — vẫn thuần kiểm tra.
2. Format `.kb/` và `_manifest.yaml` không đổi (chỉ giá trị field `status` thay đổi, không thêm field mới).
3. Engine tra cứu (query/get/resolve) không đổi.
4. Nếu tương lai người dựng KB ≠ người thẩm định, phải **bật lại gate** (CODEOWNERS + branch protection require review) trước khi tin vào ý nghĩa của `reviewed`.
