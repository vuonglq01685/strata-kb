# CENTER-KB — Slash command /kb-ingest + /kb-publish scaffold — Design

**Ngày:** 2026-07-11
**Nguồn:** yêu cầu user (brainstorming session 2026-07-11); `initcmd.py` TEMPLATE_MAP; `cli.py` (ingest, diff, approve, publish); template kb-summarize hiện có
**Phạm vi:** `kb init` scaffold thêm 2 slash command cho cả Claude Code lẫn GitHub Copilot: `/kb-ingest` (phỏng vấn id/tags/revision rồi chạy `kb ingest`) và `/kb-publish` (quy trình diff → approve → publish có cổng xác nhận). Thêm đoạn CLI reference để agent biết toàn bộ lệnh `kb`. Không sửa hành vi CLI.

---

## 1. Bối cảnh

`kb init` hiện scaffold skill `kb-summarize` cho Claude
(`.claude/skills/kb-summarize/SKILL.md`) và instructions cho Copilot
(`.github/instructions/kb-summarize.instructions.md`). Nhưng bước **ingest**
— bước đầu tiên và hay sai nhất (quên `--id`, quên `--tags`, gõ nhầm
revision) — chưa có mặt trong hệ sinh thái agent: user phải tự nhớ cú pháp
CLI. Tương tự, quy trình federation (diff → approve → publish) là chuỗi
nhiều lệnh có phán quyết con người ở giữa, chưa được đóng gói.

Ghi chú hiện trạng (đã xác minh trong session):

- CLI `kb ingest` đã đủ options (`--id`, `--tags`, `--revision`, auto-summarize).
- `.github/instructions/*.instructions.md` **không** tạo slash command trong
  Copilot Chat — chỉ prompt file `.github/prompts/*.prompt.md` mới tạo.
- Convention thư mục nguồn của scaffold là `source/` (số ít) — QUICKSTART và
  `source/.gitignore` đều dùng tên này. Repo AERO-KB này đang dùng `sources/`
  (số nhiều) nhưng việc đổi tên nằm **ngoài phạm vi** (PDF bản quyền không
  commit, đổi tên dễ vỡ đường dẫn khác).

## 2. Quyết định

| # | Vấn đề | Quyết định | Lý do |
|---|---|---|---|
| 1 | Thư mục nguồn mặc định cho /kb-ingest | **`source/`** — theo convention scaffold hiện có | User chọn giữ convention; skill hướng dẫn agent list thư mục thật trước khi chạy nên repo lệch tên vẫn dùng được. |
| 2 | Cách hỏi id/tags/revision | **Gợi ý từ tên file + bắt buộc xác nhận.** Agent đề xuất id (kebab-case), revision, tags rồi hỏi user confirm/sửa. HARD RULE: không bao giờ chạy `kb ingest` khi user chưa xác nhận đủ 3 giá trị — kể cả khi trông hiển nhiên. User đã cung cấp field nào thì chỉ hỏi field còn thiếu; được phép trả lời "none" cho tags/revision | Yêu cầu user: agent "luôn luôn và phải hỏi"; gợi ý sẵn giảm công gõ. |
| 3 | Cơ chế phía Claude Code | **Skill** `.claude/skills/kb-ingest/SKILL.md` (và kb-publish tương tự) | Vừa là slash command vừa tự kích hoạt theo intent; nhất quán pattern kb-summarize. |
| 4 | Cơ chế phía Copilot | **Prompt file** `.github/prompts/kb-ingest.prompt.md` (và kb-publish) | Cơ chế duy nhất tạo slash command thật trong Copilot Chat. Instructions kb-summarize cũ giữ nguyên. |
| 5 | Phạm vi slash command | **Chỉ ingest + publish** (summarize đã có). 8 lệnh còn lại KHÔNG wrap — thay bằng đoạn **CLI reference** trong QUICKSTART + instructions | Slash command chỉ đáng tạo khi có quy trình + phán đoán; wrap lệnh một-phát-ăn-ngay là gánh bảo trì. User chọn thêm federation. |
| 6 | Tên skill federation | **`kb-publish`** — bao diff → approve → publish | Đặt theo đích đến của quy trình. `resolve`/`context new` thuộc phía consumer, không đưa vào. |
| 7 | Cổng xác nhận của /kb-publish | Agent trình diff cho user đọc; **không bao giờ tự `kb approve` hay `kb publish` khi user chưa xác nhận rõ ràng** (xác nhận một lần cho cả hai, nêu rõ trước khi hỏi). Hub URL: lấy `CENTER_KB_HUB`, chưa set thì hỏi — không đoán | Approve là phán quyết review của con người; publish là hành động outward-facing. |
| 8 | Ngôn ngữ template | **Tiếng Anh** | Nhất quán quyết định #7 của spec auto-summarize (package general-purpose). |
| 9 | Dogfood | Copy 4 file mới vào `.claude/skills/` + `.github/prompts/` của chính repo AERO-KB | Nhất quán quyết định #8 của spec auto-summarize: bản canonical ở `templates/init/`. |

## 3. Hành vi agent — /kb-ingest

Cả hai template (Claude skill + Copilot prompt) mô tả cùng workflow:

1. **Resolve file:** tham số là tên file (không cần đường dẫn) → tìm trong
   `source/`. Không có tham số → list PDF trong `source/`, hỏi chọn. File
   không tồn tại → báo lỗi + list file có sẵn, không đoán mò.
2. **Đề xuất + xác nhận (HARD RULE):** đề xuất `id`/`revision`/`tags` từ tên
   file, hỏi user xác nhận hoặc sửa. Chưa xác nhận đủ 3 giá trị → không chạy.
3. **Chạy:** `kb ingest source/<file>.pdf --id <id> --tags <tags> --revision
   <revision>`, tường thuật kết quả (số section, summarize OK/failed,
   `kb build` OK). Section failed → chỉ user sang `kb summarize` /
   skill kb-summarize.

Xử lý lỗi: `kb ingest` exit ≠ 0 → hiện nguyên stderr, không tự retry với
tham số đoán.

## 4. Hành vi agent — /kb-publish

1. **Kiểm tra trạng thái:** `kb status` — còn section `pending` → dừng, chỉ
   user chạy summarize trước.
2. **Diff để review:** mỗi doc thay đổi → `kb diff <doc-id> --against <rev>`
   (mặc định `HEAD`), trình bày section added/changed cho user đọc.
3. **Cổng xác nhận (HARD RULE):** nêu rõ sẽ approve những section nào và
   publish lên hub nào, hỏi user xác nhận một lần. Chưa xác nhận → không chạy
   `kb approve` lẫn `kb publish`.
4. **Thực thi:** `kb approve <doc-id> --section ...` rồi `kb publish --hub
   <hub>`; tường thuật (repo-id, commit, số doc, push hay commit-only).
5. **Lỗi:** approve báo pending/missing → hiện nguyên văn, không tự sửa
   manifest thủ công; publish lỗi git/hub → hiện stderr, gợi ý `kb doctor`.

## 5. Thay đổi code

- `src/center_kb/templates/init/` — 4 template mới:
  - `claude-skill-kb-ingest.md` → `.claude/skills/kb-ingest/SKILL.md`
  - `copilot-kb-ingest.prompt.md` → `.github/prompts/kb-ingest.prompt.md`
  - `claude-skill-kb-publish.md` → `.claude/skills/kb-publish/SKILL.md`
  - `copilot-kb-publish.prompt.md` → `.github/prompts/kb-publish.prompt.md`
- `initcmd.py` — +4 entry `TEMPLATE_MAP` (EXPECTED_FILES tự theo).
- `QUICKSTART.md` template + `copilot-kb-summarize.instructions.md` — thêm
  đoạn **CLI reference**: 13 lệnh `kb`, một dòng mỗi lệnh; nhắc `/kb-ingest`
  là đường ingest khuyến nghị khi ở trong Claude/Copilot.
- Dogfood: copy 4 file vào `.claude/skills/` + `.github/prompts/` của repo này.

## 6. Testing

Mở rộng `tests/test_init.py` (pytest, theo pattern hiện có):

- 4 file mới được tạo bởi `kb init`; chạy lại không `--force` → skipped.
- Nội dung chứa marker bắt buộc: frontmatter `name:` đúng; chuỗi thể hiện
  hard rule ("confirm", "never run"), `source/` cho ingest; "approve",
  "confirm" cho publish.
- Không cần test e2e LLM — template là văn bản hướng dẫn; phần CLI đã có
  test riêng.

## 7. Ngoài phạm vi

- Đổi tên `sources/` → `source/` của repo AERO-KB.
- Skill cho `resolve` / `context new` (phía consumer federation).
- Wrap 8 lệnh CLI còn lại thành slash command.
- Mọi thay đổi hành vi CLI `kb`.
