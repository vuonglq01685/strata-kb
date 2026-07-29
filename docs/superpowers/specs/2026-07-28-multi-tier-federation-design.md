# Multi-tier Federation — Hub publish lên Hub — Design

**Ngày:** 2026-07-28
**Nguồn:** phiên brainstorm 2026-07-28; mở rộng `2026-07-13-hub-federation-single-source-design.md` (mục "Ngoài phạm vi: nhiều hub / hub phân tầng")
**Phạm vi:** cho phép một hub publish tiếp `federation/` của nó lên một hub cấp cao hơn — topology phân tầng sâu tuỳ ý (repo → hub team → hub phòng ban → hub công ty …). Không thêm khái niệm mới: "super-hub" chỉ là một hub bình thường.

## 1. Mục tiêu & tiêu chí hoàn thành

Thiết kế 2026-07-13 chốt topology 1 hub duy nhất "cho đến khi có nhu cầu thật". Nhu cầu đã đến: một repo đang làm hub cần đóng góp tri thức nó gom được lên một hub cao hơn, và chuỗi này phải lặp được không giới hạn tầng.

Tiêu chí hoàn thành:

1. Một repo `kind: hub` khai báo được `hub:` + `repo_id:` trong `.kb/config.yaml` (đúng field child đang dùng). Có `hub:` → node trung gian; không có → root hub (hành vi hôm nay, không đổi).
2. `kb publish` trên repo `kind: hub` có `hub:` đẩy **`federation/`** (không phải `.kb/` riêng) lên hub cấp trên, vào `federation/<hub-id>/`, giữ nguyên cấu trúc thư mục lồng; rebuild `federation/index.yaml` bên đó deterministic như publish thường. PR mode / direct mode / auto-pick giữ nguyên.
3. Cycle bị chặn ở publish với lỗi rõ ràng (`federation cycle detected`), cả trường hợp đích trỏ về chính mình lẫn vòng A→B→A.
4. `kb query` / `kb resolve` / MCP / Web UI trên hub nhiều tầng trả kết quả từ mọi tầng dưới; id trùng qualify bằng path đầy đủ `mid/repo-x:doc-id`.
5. Hub phẳng hiện hữu (không `hub:`) hành xử byte-một-byte như hôm nay; gate `tests-gate/regression/test_federation_compat.py` xanh nguyên trạng.
6. `scripts/demo-federation.sh` chạy được kịch bản 3 tầng end-to-end.

Ngoài phạm vi:

- Lọc/chọn lọc nội dung khi đẩy lên (phương án "curated" — đợi nhu cầu che nội dung nội bộ thật sự xuất hiện).
- Đồng bộ ngược từ trên xuống (root hub đẩy về hub con).
- Giới hạn độ sâu bằng config — chưa cần, cycle guard đã chặn trường hợp bệnh lý.

## 2. Các quyết định thiết kế đã chốt

| # | Quyết định | Lựa chọn | Lý do |
|---|---|---|---|
| 1 | Nội dung hub đẩy lên | **Chỉ `federation/`** — không đẩy `.kb/` riêng của hub | Nhất quán triết lý 2026-07-13: `.kb/` local = bàn soạn thảo, chỉ federation là searchable. Hub muốn share tri thức riêng thì self-publish vào chính nó (quyết định #7 spec 2026-07-13) — entry đó tự đi lên theo dòng chảy chung. |
| 2 | Namespace trên hub cấp trên | **Thư mục lồng giữ nguyên cấu trúc**: `federation/mid/repo-x/`, `federation/mid/hub-a/repo-y/` | Path tự mã hoá chuỗi nguồn gốc, không cần metadata riêng. Tránh flatten bằng ký tự nối (dễ va chạm, khó đọc). |
| 3 | Cách kích hoạt đẩy lên | **Cùng lệnh `kb publish`** — kind `hub` tự hiểu source là `federation/`; CI cascade là caller tuỳ chọn (workflow kiểu `kb-publish.yml`, trigger khi merge đổi `federation/`) | Một đường code; nơi nào muốn tự động thì gắn CI, nơi nào muốn tay thì chạy tay. |
| 4 | Chống cycle | **2 lớp tại publish**: (a) đích resolve ra chính mình → lỗi; (b) quét path segment mọi entry sắp đẩy, thấy `repo_id` của chính mình → lỗi `federation cycle detected` | Bắt được mọi vòng (A→B→A: khi B đẩy lần hai, federation của B đã chứa `A/B/...`, B thấy id mình trong segment). Không cần metadata, không cần cấu hình. |
| 5 | Qualify id lồng tầng | **Path đầy đủ làm prefix**: `mid/repo-x:doc-id` — mở rộng cú pháp `repo-id:doc-id` sẵn có | Cú pháp cũ là trường hợp đặc biệt (path 1 đoạn) → back-compat tự nhiên cho resolve, citation, MCP. |
| 6 | Scope search | **Không thêm cơ chế mới** — repo query hub nó khai báo; muốn scope hẹp thì hỏi hub team, scope rộng thì hỏi root hub | Chọn hub để hỏi = chọn scope; rơi ra tự nhiên từ topology, không cần flag. |
| 7 | Assets (kể cả S3-divert) | **Mirror verbatim**, gồm `_assets.yaml` | Entry S3 vẫn resolve như cũ; không xử lý đặc biệt. |

## 3. Model & config

- `.kb/config.yaml` của repo `kind: hub` nhận thêm `hub:` và `repo_id:` — cùng schema, cùng thứ tự ưu tiên override (`--hub` flag > `CENTER_KB_HUB` > config) như child.
- `repo_id` của hub trên hub cấp trên = một đoạn path (ví dụ `mid`). Mọi entry tầng dưới xuất hiện dưới prefix đó.
- Độ sâu không giới hạn về thiết kế; mỗi tầng thêm một đoạn path.

## 4. Hành vi `kb publish` trên hub

- Kind `hub` + có `hub:` → source = `federation/` của repo hiện tại; đích = `federation/<repo_id>/` trên hub cấp trên. Xoá-ghi-lại toàn bộ subtree đích (giống publish child hiện tại) rồi rebuild `federation/index.yaml` deterministic.
- Kind `hub` không có `hub:` → `kb publish` lỗi kèm hướng dẫn (root hub không có nơi để đẩy) — thay vì im lặng làm điều bất ngờ.
- PR mode (GitHub hub) / direct mode (local-path) / auto-pick: tái dùng nguyên đường code publish.
- Cycle guard chạy trước khi ghi bất kỳ byte nào lên đích (quyết định #4, mục 2).

## 5. Query / resolve / doctor / reindex

- `ensure_index` và walk `federation/` chuyển sang **đệ quy**: một entry = thư mục chứa manifest `.kb/`-shape ở lá; mọi tầng thành entry ngang hàng trong `index.yaml`.
- `kb resolve` + citation + MCP nhận qualifier path lồng (`mid/repo-x:doc-id`); ambiguous → tool liệt kê ứng viên kèm path đầy đủ như hành vi hiện tại.
- `kb doctor` thêm: (a) super-hub reachable (khi có `hub:`); (b) cảnh báo sớm cycle — thấy `repo_id` mình trong federation; (c) id lồng hợp lệ (segment không rỗng, không chứa ký tự cấm).
- `kb reindex` dùng chung walk đệ quy.
- Embeddings/search index: giữ nguyên một `search.db` duy nhất trên hub cache (`.kb-work/search.db`), row keyed theo `repo_id` — id lồng chỉ là chuỗi dài hơn, sync fingerprint per-entry hoạt động nguyên trạng, không cần đổi schema.

## 6. Tương thích ngược

- Hub không `hub:`: mọi hành vi giữ nguyên. Walk đệ quy trên cây phẳng cho kết quả y hệt walk phẳng.
- `index.yaml` entry mang path lồng trong field id sẵn có — reader cũ đọc hub phẳng không đổi; reader cũ gặp hub lồng: entry vẫn parse (id chỉ dài hơn), resolve path-1-đoạn vẫn chạy.
- Cú pháp `repo-id:doc-id` cũ = trường hợp đặc biệt của cú pháp mới.
- Gate regression (`test_federation_compat.py`, golden output) phải xanh không sửa fixture.

## 7. Testing

- **Unit:** chọn source theo kind (`hub` → `federation/`, child → `.kb/`); nested index rebuild deterministic; cycle guard lớp (a) và (b); resolve/citation id lồng; `kb publish` trên root hub (không `hub:`) lỗi đúng thông báo; doctor 3 check mới.
- **Regression:** federation compat + golden output nguyên trạng.
- **E2E:** mở rộng `scripts/demo-federation.sh` — root hub + mid hub + 2 child; publish child→mid, mid→root; query tại root thấy đủ nội dung cả 2 child qua prefix `mid/`; tạo cấu hình vòng (root trỏ về mid) → publish lỗi `federation cycle detected`.
