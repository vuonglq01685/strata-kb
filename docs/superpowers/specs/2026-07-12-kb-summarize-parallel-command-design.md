# CENTER-KB — /kb-summarize slash command + parallel sub-agent orchestration — Design

**Ngày:** 2026-07-12
**Nguồn:** yêu cầu user (brainstorming session 2026-07-12); `.claude/skills/kb-summarize/SKILL.md` hiện có; `summarize.py` (`ThreadPoolExecutor` + `_apply_results`); spec 2026-07-11-kb-slash-commands-design.md (convention template canonical + dogfood)
**Phạm vi:** (1) thêm slash command `/kb-summarize` cho Claude Code dưới dạng command wrapper mỏng; (2) viết lại skill kb-summarize thành workflow orchestrator + sub-agents song song (batch ~5 section/agent, tối đa 10 agent đồng thời, sub-agent read-only, orchestrator là writer duy nhất). Không sửa hành vi CLI `kb summarize`.

---

## 1. Bối cảnh

Skill `kb-summarize` là đường thủ công khi auto-summarize (`kb ingest` gọi
LLM CLI headless) bị tắt hoặc fail — tình huống phổ biến khi chạy qua
Docker vì container không có LLM CLI (spec kb-slash-commands, quyết định
#10: `/kb-ingest` trong Docker luôn truyền `--no-summarize`). Hai vấn đề:

1. **Trigger:** user muốn gõ `/kb-summarize` tường minh như `/kb-ingest`,
   `/kb-publish` — hiện chỉ có skill, phụ thuộc intent-matching.
2. **Tốc độ:** workflow hiện tại xử lý tuần tự từng section ("Fill sections
   one at a time... Do not edit many files in parallel") — doc lớn hàng
   chục section rất chậm. Trong khi đường auto (`summarize.py`) đã song song
   hoá từ lâu: `ThreadPoolExecutor(max_workers=5)` cho bước LLM,
   `_apply_results` ghi file tập trung tuần tự. Skill cần tái hiện đúng
   pattern này ở phía agent.

Ràng buộc kỹ thuật quyết định kiến trúc: nhiều section nằm chung một file
L2, và mọi section của một doc chung một `_manifest.yaml` — sub-agent ghi
file trực tiếp sẽ giẫm chân nhau.

## 2. Quyết định

| # | Vấn đề | Quyết định | Lý do |
|---|---|---|---|
| 1 | Quan hệ command ↔ skill | **Command wrapper mỏng + skill giữ toàn bộ logic.** `.claude/commands/kb-summarize.md` chỉ invoke skill kèm args | Một nguồn logic duy nhất; skill vẫn tự kích hoạt theo intent sau ingest; command bảo đảm trigger tay được trong Docker. |
| 2 | Ai ghi file | **Sub-agent read-only, orchestrator là writer duy nhất.** Sub-agent chỉ đọc L3 và trả JSON; orchestrator thay marker L2 + cập nhật manifest tuần tự | Loại bỏ hoàn toàn write conflict (L2 file và `_manifest.yaml` dùng chung). Giống hệt `_apply_results` phía Python. |
| 3 | Độ hạt | **Batch ~5 section/agent**, các agent trong một wave spawn song song, **tối đa 10 agent đồng thời** | Ít overhead spawn hơn 1-section/agent; agent đủ nhỏ để giữ chất lượng; số đồng thời khớp yêu cầu 5–10. |
| 4 | Nhóm batch | Ưu tiên gom section **cùng file L2** vào cùng batch | Agent đọc ít nguồn hơn, prompt gọn hơn. |
| 5 | Verify | `kb build --allow-pending` sau **mỗi wave** merge; `kb build` (strict) khi kết thúc | Giữ nguyên nhịp kiểm tra 5–10 section của skill cũ; không bao giờ để KB ở trạng thái build-fail qua đêm. |
| 6 | Xử lý lỗi sub-agent | JSON hỏng / thiếu section / vượt giới hạn độ dài → orchestrator **tự làm lại section đó tuần tự** (không spawn lại agent), tối đa 1 retry; fail tiếp → để `pending`, liệt kê trong báo cáo | Retry tuần tự rẻ hơn spawn; section hỏng không chặn phần còn lại. |
| 7 | Writing rules | Giữ nguyên 100%, chuyển thành **khối rule nhúng nguyên văn vào prompt sub-agent** (single source trong SKILL.md) | Rule đã được tinh chỉnh qua spec summarize-quality; chỉ đổi người thực thi. |
| 8 | Copilot | **Ngoài phạm vi.** `.github/instructions/kb-summarize.instructions.md` giữ workflow tuần tự | Copilot không spawn được sub-agent; instructions hiện có vẫn đúng cho môi trường đó. |
| 9 | Canonical + dogfood | Sửa template canonical `templates/init/claude-skill-kb-summarize.md`, thêm template mới `claude-command-kb-summarize.md`, thêm entry `TEMPLATE_MAP` (`.claude/commands/kb-summarize.md`), copy dogfood vào `.claude/` của repo AERO-KB | Nhất quán quyết định #8/#9 của các spec trước: bản canonical ở `templates/init/`. |
| 10 | Ngôn ngữ template | **Tiếng Anh** | Nhất quán các spec trước. |

## 3. Thành phần

### 3.1 Command wrapper — `.claude/commands/kb-summarize.md`

Frontmatter: `description` + `argument-hint: [doc-id]`. Thân bài (~5 dòng):
invoke skill `kb-summarize` bằng Skill tool, truyền `$ARGUMENTS` làm doc-id
filter; không args = xử lý mọi doc có section pending.

### 3.2 Skill orchestrator — `SKILL.md` viết lại

Workflow 6 bước:

1. **Collect** — chạy `kb status`, lập danh sách section pending
   `(doc-id, section-id, l2-file)`; lọc theo doc-id nếu được truyền.
   Không có section pending → báo và dừng.
2. **Partition** — chia batch ~5 section, gom cùng file L2 khi có thể;
   lập lịch wave: tối đa 10 agent/wave.
3. **Dispatch** — spawn các sub-agent của wave **trong cùng một message**
   (chạy đồng thời). Prompt mỗi agent gồm:
   - danh sách section được giao;
   - lệnh đọc nguồn: `kb get <doc-id> <section-id> --level l3` cho từng section;
   - khối Writing rules nguyên văn;
   - yêu cầu output: CHỈ một JSON array
     `[{"section_id": "...", "l2_summary": "...", "l1_summary": "...", "table_only": false}, ...]`
     — `table_only: true` khi section không còn prose (chỉ heading + bảng),
     khi đó `l2_summary` để rỗng và `l1_summary` là
     `"Table-only section: <title>."`;
   - cấm tuyệt đối: không ghi/sửa bất kỳ file nào.
4. **Merge** (orchestrator, tuần tự) — với từng kết quả:
   - validate JSON (đủ section, đúng field, l1 ≤ 25 từ, l2 không rỗng trừ
     table_only);
   - trong file L2: thay dòng marker `<!-- TODO:summarize <section-id> -->`
     bằng đoạn l2_summary (hoặc xoá dòng marker nếu table_only);
   - trong `_manifest.yaml`: điền `summary` = l1_summary, đổi
     `status: pending` → `status: summarized`.
5. **Verify wave** — `kb build --allow-pending`; fail table integrity →
   restore bảng verbatim từ `.raw.md` rồi build lại. Lặp bước 3–5 cho wave
   kế tiếp.
6. **Finalize** — doc nào hết pending: điền/sửa `summary` một câu của doc
   trong `.kb/index.yaml`, verify `title`/`revision`/`tags`. Chạy `kb build`
   strict — phải PASS. Báo cáo: số section điền được, số section fail (nếu
   có, kèm lý do), tổng L2 tokens từ `kb stats`.

Xử lý lỗi (quyết định #6): kết quả không qua validate → orchestrator tự
đọc L3 và viết summary cho section đó ngay tại chỗ (1 retry); vẫn fail →
giữ `pending` + ghi vào báo cáo.

### 3.3 Thay đổi code — `initcmd.py`

Thêm một entry vào `TEMPLATE_MAP`:
`".claude/commands/kb-summarize.md": "claude-command-kb-summarize.md"`.
`EXPECTED_FILES` tự cập nhật theo (derived). Cập nhật test init tương ứng
(danh sách file kỳ vọng).

### 3.4 File thay đổi

| File | Hành động |
|---|---|
| `src/center_kb/templates/init/claude-skill-kb-summarize.md` | Viết lại theo §3.2 |
| `src/center_kb/templates/init/claude-command-kb-summarize.md` | Tạo mới theo §3.1 |
| `src/center_kb/initcmd.py` | Thêm 1 entry TEMPLATE_MAP |
| `tests/` (test init) | Cập nhật expected files |
| `.claude/skills/kb-summarize/SKILL.md` | Dogfood copy từ template mới |
| `.claude/commands/kb-summarize.md` | Dogfood copy (mới) |
| `README.md` / `QUICKSTART.md` template | Nhắc `/kb-summarize` nếu đang nhắc skill |

## 4. Testing

- **Unit (pytest):** `init_repo` tạo đủ file mới; nội dung template chứa
  các marker bắt buộc (khối Writing rules, format JSON output). Hermetic —
  không gọi LLM, không cần `claude` CLI (ràng buộc test hiện có của repo).
- **Manual (dogfood):** chạy `/kb-summarize` trên một doc có section
  pending trong repo AERO-KB; xác nhận các wave spawn song song, merge
  đúng, `kb build` PASS, báo cáo đúng số liệu.

## 5. Ngoài phạm vi

- Sửa `kb summarize` CLI / `summarize.py`.
- Copilot prompt file cho kb-summarize (giữ instructions tuần tự).
- Đổi Writing rules.
