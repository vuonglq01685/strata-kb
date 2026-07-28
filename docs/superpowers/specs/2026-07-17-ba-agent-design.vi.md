# Phase 4 — BA Agent (`ba-ticket-author` + ticket template + `kb ticket lint` + init kind `ba`) — Thiết kế (bản tiếng Việt)

**Ngày:** 17/07/2026 (v2 — cập nhật cùng ngày sau các quyết định phạm vi, xem §12)
**Trạng thái:** Thiết kế đề xuất — chưa implement (plan: `docs/superpowers/plans/2026-07-17-ba-agent.md`)
**Lưu ý:** Bản dịch để đọc; bản tiếng Anh cùng tên (không có `.vi`) là bản chuẩn để agent implement.
**Phạm vi:** Đủ 3 hạng mục Phase 4 theo Architecture Spec v0.3 §13.5 — skill `ba-ticket-author`, ticket template chuẩn, DoR gate `kb ticket lint` — **cộng thêm** hai bổ sung chốt ngày 17/07/2026: repo kind riêng cho BA (`kb init --kind ba`) và CI DoR gate scaffold sẵn trên thư mục `tickets/` của repo đó. Jira ở mức **chỉ xuất Markdown**: agent tạo nội dung sẵn-để-dán, BA review và tự publish (human-in-the-loop, §13.4). BA làm việc **trong repo requirement riêng** bằng agentic client (Claude Code / Copilot / Cursor); phương án chat-only qua MCP prompt đã cân nhắc và **bỏ** (quyết định 17/07/2026).

---

## 1. Vấn đề

Phase 1–3 cho BA khả năng *truy xuất* có căn cứ (kb_search → xác nhận → kb_context_new → kb_resolve), nhưng bước biến tri thức thành ticket Dev-code-được-ngay vẫn thủ công: chưa có cấu trúc chuẩn, citation trên thực tế vẫn tùy chọn, diagram vẽ tay, và không gì enforce Definition of Ready của team. Phase 4 đóng gói các cơ chế sẵn có thành pipeline soạn ticket lặp lại được (v0.3 §13.2): Intake → Ground → Draft → Pin → Lint → BA review.

Phase 4 **không xây engine mới**. Bốn MCP tool lõi giữ nguyên (bất biến §9.2); mọi thứ bên dưới là orchestration (skill), một template, một lệnh lint, và một init kind mới — tất cả tái dùng `kbcontext` + `resolve` + `doctor.check_context`.

## 2. Mục tiêu

- BA, làm việc trong repo requirement của team với Claude Code (hoặc Copilot/Cursor), chạy `/ba-ticket-author` và tạo được ticket chuẩn: Story, Background, AC, use case, Mermaid sequence + flow, block `kb-context` đã pin — lưu tại `tickets/`, version bằng Git.
- Mọi khẳng định chuẩn ngành mang citation `doc-id §section` resolve được tại commit hub đã pin.
- DoR gate máy-kiểm-được ở hai tầng: local (`kb ticket lint` CLI / `kb_ticket_lint` MCP) và CI (PR đụng `tickets/` phải lint PASS mới merge).
- Onboard BA mới = `pip install center-kb` + clone (hoặc `kb init --kind ba`) + 2 biến môi trường — không vướng bộ máy authoring KB.
- Giữ human-in-the-loop: agent không tự đẩy Jira, không tự chọn giữa hai kết quả search sát điểm.

Ngoài phạm vi: tích hợp Jira REST (spec riêng sau); MCP prompt / flow chat-only không repo (bỏ 17/07/2026 — mọi BA đều dùng repo requirement); lệnh `kb ticket new` (hoãn, §11); grounding diagram bằng cấu trúc code (cần Phase 5 — diagram Phase 4 chỉ dựa KB + thông tin BA).

## 3. Ràng buộc kiến trúc

1. **Bốn MCP tool lõi không đổi.** §9.2 cho phép Phase 4 *thêm* tool — thêm đúng một: `kb_ticket_lint`.
2. **Hub là nguồn đọc duy nhất.** Lint resolve refs qua hub federation y như `kb doctor --context`. Trong CI cũng vậy — workflow cần quyền đọc hub.
3. **Ticket là Markdown** — render trong Jira/GitHub (Mermaid = diagram-as-code), lint được như text, version bằng Git.
4. **Quy tắc citation kế thừa kb-summarize**: mã hiệu, tên record/field, con số, §ref giữ verbatim; không suy diễn; không chắc → cite và gắn cờ, không bịa.
5. **Một nội dung, một nguồn**: danh sách heading bắt buộc nằm trong một hằng Python duy nhất; wrapper skill và template ship kèm không được lệch (có test đồng bộ).
6. **Kỷ luật version**: `REQUIRED_HEADINGS` là hợp đồng tương thích giữa bản cài local của BA, server MCP dùng chung, và CI. Đổi nó = breaking change — chỉ ở minor/major release, bắt buộc ghi changelog.

## 4. Thành phần A — ticket template chuẩn

Một template chuẩn duy nhất, ship trong package, scaffold ra `docs/tickets/TEMPLATE.md` trên kind `ba` (chỉ BA soạn ticket — quyết định 17/07/2026). Cấu trúc bắt buộc (heading là hợp đồng lint, tiếng Anh cố định; thân bài theo ngôn ngữ của BA):

```markdown
# <Title — một dòng, mệnh lệnh thức, có định danh>

## Summary
<1–2 dòng tóm tắt nghiệp vụ>

## User Story
As a <role>, I want <capability>, so that <value>.

## Background / Business context
<ngữ cảnh; mọi khẳng định chuẩn ngành cite `doc-id §section`>

## Acceptance Criteria
- [ ] AC1 … (cite `doc-id §section` khi chạm chuẩn ngành)
- [ ] AC2 …

## Use cases
### Main flow
### Alternate / exception flows

## Sequence diagram
```mermaid
sequenceDiagram
  …
```

## Business flow
```mermaid
flowchart TD
  …
```

## KB context
```yaml
kb-context:
  version: "<hub commit>"
  refs:
    - <repo:doc-id §section>
  tags: [ … ]
```

## Definition of Ready
- [ ] Đủ Story, AC, use case, cả hai diagram
- [ ] Mọi citation resolve được tại version đã pin (kb ticket lint PASS)
- [ ] Không có ref stale
```

Nguồn sự thật duy nhất cho heading list là hằng Python trong module mới `ticket.py`; unit test đảm bảo template và hằng không lệch.

## 5. Thành phần B — `kb ticket lint` (DoR gate)

Typer sub-app mới `kb ticket`, trước mắt một lệnh:

```
kb ticket lint <file|-> [--kb-dir .kb] [--hub <url|path>] [--json]
```

Module mới `src/center_kb/ticketlint.py` (engine, không phụ thuộc CLI) trả `list[Issue]` (tái dùng `doctor.Issue`) + summary máy-đọc. Các check theo thứ tự:

| # | Check | Mức |
|---|---|---|
| 1 | Đủ mọi heading bắt buộc (hằng từ `ticket.py`) | error |
| 2 | User Story khớp `As a … I want … so that …` (không phân biệt hoa thường, đa dòng) | error |
| 3 | ≥ 1 mục checkbox Acceptance Criteria | error |
| 4 | `## Sequence diagram` có fence ```` ```mermaid ```` chứa `sequenceDiagram` ở đầu dòng; `## Business flow` có fence chứa `flowchart` ở đầu dòng (siết lại ở Phase 4.1 để một init directive có thể đứng trước loại diagram, trong khi từ khóa chôn trong nhãn node không còn được tính) | error |
| 5 | Block `kb-context` parse được (`kbcontext.parse`) | error |
| 6 | Mọi ref resolve tại version đã pin — ủy quyền `doctor.check_context` | error (broken) / warning (stale) |
| 7 | Nhất quán: citation inline `doc §sec` trong thân bài phải có trong `kb-context.refs` | error |
| 8 | Nhất quán ngược: ref đã pin phải được cite ít nhất một lần trong thân bài | warning |
| 9 | AC không có citation nào | warning (lint không phán được AC có chạm chuẩn ngành không) |

Exit code: 1 nếu có error, ngược lại 0 (warning vẫn in). `--json` xuất `{"pass": bool, "errors": [...], "warnings": [...], "notes": [...]}` cho agent/CI (`notes` thêm ở Phase 4.1 — ghi lại các check KHÔNG chạy được, ví dụ không có filesystem path; không bao giờ ảnh hưởng `pass`). Output người đọc theo style `kb doctor` + dòng chốt `DoR: PASS|FAIL`. Toàn bộ xử lý UTF-8 (thân bài tiếng Việt + ký tự `§` trên console Windows — áp `utf8io`; test phải cover ticket thân tiếng Việt).

Trích citation inline (check 7) dùng regex thận trọng khớp ngữ nghĩa `kbcontext._REF_RE`; ref không có repo qualifier khớp với ref đã pin mang bất kỳ qualifier nào.

## 6. Thành phần C — MCP tool `kb_ticket_lint`

Cùng engine (`ticketlint.lint(text, hub)`), expose làm MCP tool thứ năm:

```python
kb_ticket_lint(ticket_markdown: str) -> str
```

Render text như các tool khác, kèm note stale-hub. Đăng ký trong `mcp.create_server`; bốn tool lõi không đụng. Với quyết định BA-có-repo, tool này là kênh *phụ* (agent trong repo chạy được CLI) — giữ lại vì rất mỏng trên cùng engine và cho phép client MCP nào cũng lint được mà không cần shell.

## 7. Thành phần D — skill `ba-ticket-author` + wrappers

Bốn template mỏng (layout file theo pattern kb-approve) đăng ký trong `BA_TEMPLATES` — **chỉ** scaffold trên kind `ba`: `.claude/skills/ba-ticket-author/SKILL.md`, `.claude/commands/ba-ticket-author.md`, `.github/prompts/ba-ticket-author.prompt.md`, `.cursor/commands/ba-ticket-author.md`. Dev KHÔNG soạn ticket (quyết định 17/07/2026) — scaffold hub/child không nhận gì từ Phase 4; `kb init --kind dev` với agent riêng cho Dev sẽ đến cùng Phase 5 (§12).

Skill Claude là orchestrator (style kb-summarize: workflow tường minh + hard rules). Workflow = pipeline §13.2:

1. **Intake** — thu thập nhu cầu, tag đích (`#arinc424 #airspace`) hoặc doc đích danh; hỏi, không đoán.
2. **Ground** — `kb_search` trong budget. Trình **tất cả** ứng viên kèm citation. Cờ nhập nhằng bật → BA phải chọn, không bao giờ tự chọn.
3. **Draft** — điền template (§4). Mọi khẳng định chuẩn ngành cite từ ứng viên đã xác nhận. Diagram: vẽ từ KB + những gì BA nêu; chỗ cần cấu trúc code (tên service, bảng DB) → placeholder `%%TODO: verify against codebase%%` thay vì bịa (Phase 5 gỡ hạn chế này).
4. **Pin** — BA xác nhận section áp dụng → `kb_context_new(refs, tags)` → nhúng block vào `## KB context`.
5. **Lint** — `kb ticket lint` (CLI trong repo; MCP `kb_ticket_lint` là fallback). Sửa error, chạy lại đến PASS; báo warning còn lại cho BA.
6. **Review → lưu → Jira** — ghi Markdown cuối vào `tickets/<ticket-id>.md`, BA review và commit; BA dán sang Jira. **Không bao giờ** push Jira, không tự tick DoR khi BA chưa xác nhận.

Khối hard rules (verbatim trong cả 4 wrapper): citation bắt buộc — không citation thì không khẳng định; không bịa mã hiệu/giá trị; trình-và-xác-nhận trước khi pin; output là bản nháp — BA publish; lint FAIL là blocker, không lặng lẽ bàn giao ticket fail.

## 8. Thành phần E — `kb init --kind ba` (repo requirement của BA)

Kind thứ ba bên cạnh `hub` và `child` (đúng triết lý role-aware init v0.3). Repo BA *tiêu thụ* KB và *version ticket*; không author tài liệu KB nào — nên không được mang theo bộ máy ingest/summarize/publish.

`kb init --kind ba` scaffold đúng những thứ sau:

| Đường dẫn | Template nguồn | Mục đích |
|---|---|---|
| `.kb/config.yaml` | `config-ba.yaml` (mới) | `kind: ba` + hub URL |
| `.mcp.json` | `mcp-child.json` (tái dùng) | HTTP MCP → server dùng chung (`${CENTER_KB_HUB_URL}` + token env) |
| `.cursor/mcp.json` | `cursor-mcp-child.json` (tái dùng) | như trên, cho Cursor |
| 4 × wrapper `ba-ticket-author` | Thành phần D | skill |
| `docs/tickets/TEMPLATE.md` | `ticket-template.md` | template tham chiếu |
| `tickets/.gitkeep` | — | nơi chứa ticket |
| `.github/workflows/kb-ticket-lint.yml` | Thành phần F | CI DoR gate |
| `QUICKSTART-BA.md` | `QUICKSTART-ba.md` (mới) | onboarding một trang |

KHÔNG scaffold trên `ba`: wrapper kb-ingest / kb-summarize / kb-approve / kb-publish / kb-docker-setup, `kb-publish.yml`, gitignore thư mục nguồn. Và đối xứng lại: Phase 4 không thêm gì vào scaffold hub/child. Ghi chú implement: `initcmd` thêm map template theo kind (`BA_TEMPLATES`, KHÔNG merge vào `COMMON_TEMPLATES`); `KINDS`/`template_map()` từ 2-way thành 3-way; prompt hỏi kind (`_resolve_kind`) thêm lựa chọn thứ ba; Literal `config.KBConfig.kind` thêm `"ba"` — validation kind nằm ở chính pydantic Literal này, thiếu một dòng đó thì `load_config` từ chối `kind: ba`; bản thân `doctor.check_kind` không cần đổi.

Nội dung `QUICKSTART-BA.md` (một trang): Setup một lần — install, clone-hoặc-init, 2 biến môi trường (`CENTER_KB_HUB_URL`, `CENTER_KB_HTTP_TOKEN`), mở bằng Claude Code; Mỗi ticket — flow 6 bước ở §7; Quy tắc DoR — lint enforce gì, cái gì vẫn là judgment của BA (citation trong AC).

## 9. Thành phần F — CI DoR gate (`kb-ticket-lint.yml`)

Template init mới `kb-ticket-lint.yml`, chỉ scaffold trên kind `ba`. Hành vi:

- Trigger: `pull_request` với `paths: ["tickets/**.md"]`.
- Bước: checkout → setup-python → `pip install center-kb` → với mỗi file `tickets/*.md` thay đổi (diff so với base): `kb ticket lint <file> --hub "$CENTER_KB_HUB"` → có FAIL là job fail.
- Truy cập hub: `CENTER_KB_HUB` từ repo variable; auth hub private qua `secrets.KB_HUB_TOKEN`, theo đúng cách auth của `kb-publish.yml` / pattern OIDC intake sẵn có (tài liệu có bản quyền — không bao giờ nhúng credential vào file workflow).
- Branch protection trên repo BA (require check này) là setting của repo, ghi trong QUICKSTART-BA, tool không enforce.

Kết quả: DoR được enforce bằng máy — requirement chạm chuẩn ngành mà citation không resolve thì không merge được vào `tickets/`.

## 10. Tài liệu

- QUICKSTART-child + QUICKSTART-hub: thêm một dòng flow BA + `kb ticket lint` vào mục CLI.
- QUICKSTART-BA: mới, theo §8.
- README: mục Phase 4 — pipeline, bảng 3 kind (`hub` / `child` / `ba`), lệnh mới, MCP tool thứ năm.
- AERO-KB_Architecture v0.4 (task riêng, sau implement): §13 "thiết kế" → "vận hành"; init kind 2 → 3; MCP tool 4 → 5.

## 11. Kiểm thử (hermetic — không hub thật, không LLM; fixture `git_kb`)

- `tests/test_ticketlint.py`: từng check §5 — golden ticket pass; từng biến thể lỗi assert đúng mức + đoạn message; thêm golden ticket thân tiếng Việt; shape `--json`.
- `tests/test_cli_ticket.py`: exit code, stdin (`-`), `--json`.
- Test MCP: `kb_ticket_lint` đăng ký (tổng 5 tool); đường happy + broken-ref; chữ ký 4 tool lõi không đổi (snapshot).
- `tests/test_init.py`: kind `ba` scaffold đúng bảng §8 và KHÔNG có wrapper authoring; scaffold hub/child KHÔNG nhận `ba-ticket-author` hay `docs/tickets/TEMPLATE.md` (assert vắng mặt — danh sách file kỳ vọng của hub/child giữ nguyên); nội dung workflow (paths filter, không hardcode secret).
- Test đồng bộ template: hằng required-headings ⊆ template ship kèm; wrapper skill tham chiếu đúng bộ heading.

## 12. Hoãn / bỏ (ghi để không mất ngữ cảnh)

- **MCP prompt `ba-ticket-author`** — BỎ (quyết định 17/07/2026): mọi BA làm trong repo requirement với agentic client; không còn persona chat-only. Chỉ xem lại nếu persona BA-không-repo xuất hiện trở lại.
- **Kind `dev` (agent cho Dev)** — chốt 17/07/2026: Dev không soạn ticket; `kb init --kind dev` với agent/mode riêng sẽ ship cùng Phase 5 (Developer Package / Codebase-as-Knowledge). Phase 4 chủ đích không thêm gì vào scaffold phía Dev.
- **Tạo draft ticket qua Jira REST** — làm sau, cần giải quyết credential; không thuộc phase này (quyết định 17/07/2026).
- **`kb ticket new`** — render template rỗng ra `tickets/<id>.md`; đơn giản, thêm khi có người cần.
- **Diagram grounding bằng code** — đến cùng Phase 5; convention `%%TODO: verify against codebase%%` được thiết kế để agent Phase 5 tìm và giải quyết.
- **Việc kiểm tra thực tế trước pilot (không phải việc code):** xác nhận Jira của team render được Mermaid (plugin) — nếu không, diagram dán vào chỉ là code block.

## 13. Nhật ký quyết định

| Quyết định | Lựa chọn |
|---|---|
| Đóng gói | Tích hợp vào `center-kb` (17/07/2026): engine lint phải nằm cạnh `doctor`/`resolve`; skill chỉ là template mỏng; phần đặc thù AERO override trong repo AERO, không fork |
| Tích hợp Jira | Xuất Markdown, BA tự dán; không API trong Phase 4 |
| Mô hình làm việc BA | Repo requirement riêng cho team + agentic client; init kind mới `ba` (17/07/2026) |
| Ai soạn ticket | Chỉ BA — wrapper + template chỉ scaffold trên kind `ba`; hub/child không đổi; Dev có kind `dev` + agent riêng ở Phase 5 (17/07/2026) |
| Flow chat-only | Bỏ — không MCP prompt (17/07/2026) |
| CI DoR gate | TRONG phạm vi (17/07/2026): `kb-ticket-lint.yml` scaffold trên kind `ba` |
| Vị trí engine lint | `ticketlint.py` mới, tái dùng `doctor.check_context` / `kbcontext` / `resolve`; CLI + MCP là wrapper mỏng trên một engine |
| MCP tool thứ 5 | `kb_ticket_lint` giữ làm kênh phụ — §9.2 cho phép; gate chính là CLI trong repo + CI |
| Sở hữu template | Template trong package, scaffold ra `docs/tickets/TEMPLATE.md`; hằng headings trong `ticket.py` là hợp đồng lint; test đồng bộ |
| Ổn định hợp đồng heading | Đổi `REQUIRED_HEADINGS` = breaking change; chỉ minor/major release + changelog |
| Ngôn ngữ heading | Heading tiếng Anh cố định (hợp đồng lint); thân bài theo ngôn ngữ BA (UTF-8, tiếng Việt có test cover) |
| Check citation của AC | Warning, không phải error — BA chịu trách nhiệm qua checklist DoR |
| Diagram khi chưa có Phase 5 | Chỉ từ KB + thông tin BA; chi tiết code chưa verify → placeholder `%%TODO%%`, không bịa |
