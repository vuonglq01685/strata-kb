# CENTER-KB — Auto-summarize qua LLM CLI + AI-integration scaffold — Design

**Ngày:** 2026-07-11
**Nguồn:** yêu cầu user (brainstorming session 2026-07-11); SKILL.md kb-summarize hiện có; `initcmd.py` TEMPLATE_MAP
**Phạm vi:** (F1) `kb ingest` mặc định tự gọi LLM CLI điền summary cho section pending, song song tối đa 5 worker; lệnh độc lập `kb summarize`. (F2) `kb init` scaffold thêm Claude skill + Copilot instructions (tiếng Anh) vào repo đích. Không đổi engine tra cứu, không đổi format `.kb/`, không đụng CI review automation (đã có).

---

## 1. Bối cảnh

Pipeline hiện tại sau `kb ingest` dừng ở trạng thái "khung rỗng": mọi section
`status: pending`, file L2 chứa marker `<!-- TODO:summarize <id> -->`, và CLI
in dòng nhắc *"Next: open Claude Code and run the kb-summarize skill"*. Bước
điền summary hoàn toàn thủ công — user phải mở Claude Code, chạy skill
`kb-summarize` (nằm ở `.claude/skills/` của repo này, **không** được đóng gói
trong wheel, **không** được `kb init` scaffold sang repo đích).

Hai khoảng trống:

1. **Trải nghiệm ingest đứt gãy** — user kỳ vọng "một lệnh xong hết": ingest
   → summarize → build. Bước giữa đòi hỏi thao tác tay trong một tool khác.
2. **Phân phối AI-integration thiếu** — team khác `pip install center-kb` +
   `kb init` sẽ có workflow CI, mcp.json… nhưng không có skill cho Claude
   Code lẫn instructions cho GitHub Copilot. Đường thủ công/fallback không
   tồn tại ở repo đích.

Ghi chú hiện trạng (đã xác minh trong session): CI auto-review
(`kb-review.yml` — flip `summarized → reviewed` khi merge vào `main`) **đã
tồn tại và đã nằm trong scaffold** — nằm ngoài phạm vi spec này.

---

## 2. Quyết định

| # | Vấn đề | Quyết định | Lý do |
|---|---|---|---|
| 1 | Hành vi mặc định của `kb ingest` | **Mặc định tự summarize**, có `--no-summarize` để tắt | User chọn trải nghiệm "một lệnh xong hết"; chấp nhận tốn token/thời gian, đã có đường tắt. |
| 2 | Runner LLM | **Auto-detect: `claude` → `copilot`**, override bằng `--llm` hoặc config `llm.runner` trong `index.yaml`. Không có runner nào → in hướng dẫn, giữ pending, **exit 0** | Phủ cả hai hệ sinh thái; thiếu CLI không được làm fail ingest — scaffold vẫn hợp lệ, summarize sau được. |
| 3 | Kiến trúc gọi LLM | **kb điều phối, LLM chỉ sinh text** — mỗi section 1 subprocess headless trả JSON `{l2_summary, l1_summary}`; kb validate rồi tự ghi file | Deterministic, test được bằng stub, LLM không có quyền sửa file → table integrity không thể vỡ; retry theo từng section. |
| 4 | Song song hoá | **ThreadPoolExecutor, `max_workers: 5`** (config được); worker chỉ chạy subprocess, mọi ghi file/manifest dồn về main thread | Yêu cầu user (tối đa 5 sub-agent song song). Ghi tuần tự ở main thread → không cần lock, manifest không race. |
| 5 | Model floor | **`model: sonnet-5`, `effort: high`** trong config; adapter map sang flag từng CLI, effort là best-effort | Yêu cầu user ("thấp nhất là sonnet 5 high"). `claude -p` không có flag effort chính thức — áp qua env/flag nếu version hỗ trợ, bỏ qua nếu không. |
| 6 | Section fail (timeout, JSON rác sau 1 retry) | **Giữ `pending` + warning**; cuối lệnh in `N summarized, M failed — re-run with: kb summarize`; exit code ingest vẫn 0 nếu scaffold OK | Fail một section không được phá cả lần ingest; `kb build` (gate hiện có) vẫn chặn pending khi build final. |
| 7 | Scaffold AI-integration | **Cả hai**: `.claude/skills/kb-summarize/SKILL.md` + `.github/instructions/kb-summarize.instructions.md`, **toàn bộ tiếng Anh** | Đường thủ công/fallback cho cả Claude lẫn Copilot user; package đã reposition general-purpose nên English. |
| 8 | Nguồn duy nhất cho SKILL.md | Bản canonical ở `templates/init/`; `.claude/skills/` của chính repo này thay bằng bản English đó | Tránh hai bản trôi dạt; repo tự ăn scaffold của mình (dogfood). |
| 9 | Doc-level summary trong `index.yaml` | Sau khi mọi section của một doc summarized: **1 call LLM riêng** sinh summary 1 câu cho doc | Giữ nguyên hợp đồng của skill hiện tại (bước 3 trong SKILL.md); input là các L1 summary nên call rẻ. |

---

## 3. F1 — `kb summarize` engine

### 3.1 Thành phần mới

- `src/center_kb/llm.py` — runner adapters:
  - `detect_runner(preference) -> Runner | None`: thứ tự ưu tiên flag `--llm`
    → config `llm.runner` → auto-detect `shutil.which("claude")` rồi
    `shutil.which("copilot")`.
  - `ClaudeRunner` / `CopilotRunner`: encapsulate mapping flag
    (`claude -p --model <model> --output-format json` /
    `copilot -p "<prompt>" --model <model>`), timeout mỗi call
    (mặc định 300s/section), parse output → text JSON.
  - Verify flag thực tế của cả hai CLI ở bước implement (ghi chú §6).
- `src/center_kb/summarize.py` — orchestrator:
  - `collect_pending(kb_dir, doc_id=None) -> list[PendingSection]` (đọc từ
    `_manifest.yaml`).
  - `build_prompt(section) -> str`: L3 nguyên văn + writing rules (English,
    chuyển từ SKILL.md — xem §3.3) + yêu cầu output JSON thuần.
  - `run(sections, runner, max_workers)`: ThreadPoolExecutor; mỗi job =
    subprocess call + parse + validate; kết quả trả về main thread.
  - Ghi tuần tự tại main thread: thay marker `<!-- TODO:summarize <id> -->`
    trong file L2 bằng `l2_summary` (không đụng bảng — bảng nằm ngoài
    marker); manifest `summary = l1_summary`, `status: pending → summarized`.
  - Doc xong hết section → 1 call sinh doc summary, ghi `index.yaml`.
  - Kết thúc: chạy `kb build --allow-pending` nếu còn section fail, `kb build`
    nếu sạch; báo cáo N summarized / M failed / tổng thời gian.

### 3.2 CLI

- `kb ingest …` — thêm bước summarize sau scaffold; flags mới:
  `--no-summarize`, `--llm claude|copilot|none`.
- `kb summarize [DOC_ID]` — lệnh mới, standalone: chạy engine cho mọi section
  pending (hoặc giới hạn 1 doc); dùng sau `--no-summarize` hoặc để retry
  section fail. Flags: `--llm`, `--max-workers`.
- Exit code `kb summarize`: 0 nếu mọi section pending được xử lý xong; 1 nếu
  còn section fail (khác `kb ingest`, nơi summarize fail không phá ingest —
  lệnh chuyên trách thì phải báo lỗi thật).

### 3.3 Prompt contract

Input: id + title + L3 body nguyên văn. Output bắt buộc là JSON duy nhất:

```json
{"l2_summary": "<prose ~20-30% of original length>", "l1_summary": "<one sentence, ≤ 25 words>"}
```

Writing rules nhúng trong prompt (English, chuyển nguyên nghĩa từ SKILL.md):
giữ NGUYÊN VĂN mã hiệu/record/field/giá trị số/đơn vị/tham chiếu §x.y; không
suy diễn ngoài văn bản; không tóm tắt/tạo/xoá bảng; L2 giữ cấu trúc logic;
L1 nêu section nói gì + chứa loại dữ liệu gì (phục vụ BM25).

Validate sau parse: đúng 2 key, đều là string không rỗng; `l1_summary` ≤ 25
từ (soft-check — vượt thì warning, không reject); JSON parse fail hoặc thiếu
key → retry 1 lần với cùng prompt; vẫn fail → section fail (quyết định #6).

### 3.4 Config (`index.yaml`)

```yaml
llm:
  runner: auto        # auto | claude | copilot | none
  model: sonnet-5     # floor; adapter map sang flag từng CLI
  effort: high        # best-effort
  max_workers: 5
  timeout: 300        # giây / section
```

`runner: none` = tắt vĩnh viễn cho repo (tương đương luôn `--no-summarize`).
Model `models.py` thêm block `LLMConfig` tương ứng (optional, default như trên
— repo cũ không có block này vẫn chạy).

---

## 4. F2 — Scaffold AI-integration

`TEMPLATE_MAP` (initcmd.py) thêm 2 entry:

| Target | Template |
|---|---|
| `.claude/skills/kb-summarize/SKILL.md` | `claude-skill-kb-summarize.md` |
| `.github/instructions/kb-summarize.instructions.md` | `copilot-kb-summarize.instructions.md` |

- **SKILL.md** viết lại hoàn toàn bằng English từ bản hiện tại (quy trình
  status → get L3 → điền L2 → manifest → build; writing rules như §3.3; batch
  5–10 section chạy `kb build --allow-pending`). Thêm ghi chú: đường thủ công
  này là fallback — bình thường `kb ingest` đã tự summarize.
- **Copilot instructions** có frontmatter `applyTo: ".kb/**"`, cùng nội dung
  writing rules + quy trình, diễn đạt theo convention Copilot.
- `.claude/skills/kb-summarize/SKILL.md` của chính repo này được thay bằng
  bản English (quyết định #8).
- `kb init` giữ nguyên hành vi không-overwrite (file tồn tại → skip).

---

## 5. Testing

- **Unit** (`tests/`): detect_runner (mock `shutil.which` + config + flag,
  đủ ma trận ưu tiên); build_prompt (chứa L3, rules, JSON instruction); parse
  + validate (JSON tốt/rác/thiếu key/thừa key/l1 quá dài); marker replacement
  (section có bảng — bảng nguyên vẹn; marker không tồn tại → lỗi rõ ràng);
  manifest flip; doc-summary aggregation.
- **Integration**: stub executable (shell script in JSON giả, đặt tên
  `claude`/`copilot` trong PATH tạm) — full flow `kb ingest` → mọi section
  summarized + build pass; fail path (stub trả rác → section pending, message
  re-run đúng, exit 0); `--no-summarize` → như hành vi cũ; không runner →
  hướng dẫn + exit 0; concurrency 5 worker trên ≥ 10 section → manifest nhất
  quán; `kb summarize` standalone + exit code 1 khi còn fail.
- **Init**: 2 file mới xuất hiện đúng nội dung; chạy lại không overwrite.

---

## 6. Giới hạn đã biết

- **Effort mapping best-effort**: `claude -p` chưa có flag effort công khai —
  implement sẽ verify version CLI thực tế; nếu không set được thì chỉ pass
  `--model`, ghi log debug. Copilot CLI tương tự với `--model`.
- **Chi phí**: summarize mặc định tốn token subscription của người chạy;
  đường thoát là `--no-summarize` / `runner: none`.
- **Copilot CLI headless** ít chuẩn hoá hơn Claude CLI (output format, JSON
  mode) — adapter Copilot có thể phải parse text tự do; nếu quá bấp bênh,
  phương án dự phòng là yêu cầu output fenced-JSON và extract bằng regex.
- **Doc summary** sinh từ các L1 (không đọc lại toàn bộ L3) — chấp nhận để
  call rẻ; SME sửa tay được vì `index.yaml` là file thường.
