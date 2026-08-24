# Roadmap việc cần làm tiếp theo — CENTER-KB (bản 2, cập nhật 2026-08-22)

Bản này thay bản trước theo ba điều chỉnh: (1) mọi việc dưới đây tính từ nền tảng Phase 5 **đã hoàn chỉnh** — kind `dev`, 5 skill Dev, `kb code-ingest`, `-svc`, `kb svc note` đều coi như sẵn sàng; (2) thêm hạng mục mới **đo token + model cho vòng đời một ticket** (BA viết → Dev implement) kèm **website xem ngay trong repo** của Dev/BA; (3) conventions pack đi theo package như đã chốt.

Ký hiệu ưu tiên: A (vá lỗi dữ liệu) → B (đo lường) → C (tối ưu token) → D (conventions) → E (hardening + pilot).

---

## A — Vá lỗ tag fabrication trong kb-context (bug data-integrity, làm đầu tiên)

Đã xác minh trong code: `build_context_block()` (kbcontext.py) validate refs chặt (doc + section phải tồn tại trên federation, sai là raise `KBRefNotFoundError`) nhưng tags chỉ được `.strip()` rồi ghi thẳng vào block; `kb ticket lint` (`lintcore.check_context_block`) không check tags; skill `ba-ticket-author` cho phép tags tự do ở Intake/Pin mà không quy định nguồn. Hệ quả: tag ma lọt vào ticket, các lần search lọc theo tag sau đó trả rỗng im lặng, vocabulary tag trôi khỏi KB.

- [x] **A1 — Auto-derive + validate tags trong `build_context_block()`** (~0.5 ngày, kèm test)
  Đảo mặc định: tags **tự suy** từ union `SectionEntry.tags` (∪ `Manifest.tags`) của chính các refs đã pin — agent không đặt tag nữa. Nếu caller vẫn truyền tags tường minh → validate từng tag against vocabulary của federation; tag lạ → error kèm gợi ý tag gần nhất. Một điểm sửa phục vụ cả CLI lẫn MCP (hai wrapper gọi chung hàm); không đổi signature/docstring tool → golden `mcp_tools.json` giữ nguyên.
- [x] **A2 — Thêm check tags vào `kb ticket lint`** (~0.5 ngày, kèm test)
  Mỗi tag trong block phải tồn tại trong vocabulary hub. **Warning trước** (ticket cũ tiếp tục pass — đúng tinh thần compat contract), nâng error sau khi A3 quét sạch.
- [x] **A3 — Quét backlog tickets/missions hiện có** (~0.5 ngày)
  Chạy lint mới trên toàn bộ `tickets/` + `missions/` các repo BA, liệt kê tag không tồn tại, BA sửa. Xong thì nâng A2 lên error.
  *Kết quả 2026-08-23 — repo `KS-BA` (hub `KS-Center-KB`): 2 ticket, 0 mission, cả hai `DoR: PASS`, không tag nào ngoài vocabulary; hai block đều không có dòng `tags:` nên không phải sửa file nào. Canary (bản copy có `tags: [ghost-tag]`) bị lint chặn, xác nhận check thật sự chạy. A2 do đó ship luôn ở mức `error`, không cần bước nâng cấp.*
- [ ] **A4 — Sửa skill text `ba-ticket-author` + `ba-mission-plan`** (~0.5 ngày — gom vào ĐỢT TEMPLATE CHUNG, xem cuối file)
  Intake: tags từ BA chỉ là từ khoá tìm kiếm. Pin: bỏ "(+ tags)" tự do — "tags do `kb context new` tự suy từ section đã pin; không bao giờ tự đặt".
- [ ] **A5 — (tuỳ chọn, rẻ) CLI `kb tags`** liệt kê vocabulary từ hub. CLI mới thì được; tuyệt đối không thêm MCP tool thứ 6.

## B — Đo token + model cho vòng đời ticket, xem được ngay trong repo (hạng mục mới)

Mục tiêu: với mỗi ticket, trả lời được "viết nó tốn bao nhiêu token, model gì, ở phase nào, phía BA hay phía Dev" — và Dev/BA mở xem được ngay trong repo của mình, không cần hỏi ai.

> **Batch 2 xong 2026-08-24** (PR #39 + PR fix dedup). Lệch so với mô tả dưới đây, đều do đo được chứ không do đổi ý:
> `cache_write` **tách 5m/1h** (giá 1.25× vs 2× input; mọi write đo được đều là 1h); row thêm `uuid`, `request`, `sidechain`, `branch`; **attribute không dùng branch name** — repo BA không phải git repo nên mọi row báo `gitBranch: "HEAD"`; ticket id là **file stem**, không validate theo `M-<slug>-US<n>` vì ticket thật tên `open-new-flight.md`; phase **chỉ** lấy từ marker `<command-name>` và tool call `Skill` (đếm tên skill trong nội dung cho kết quả sai hoàn toàn: một session sửa dev skill nhắc `dev-handover` 339 lần); hook chỉ `Stop`, không `SubagentStop`, và scaffold chỉ cho kind `ba`/`dev`; `report.html` **không commit** mặc định vì suy ra được từ ledger.
>
> **Số baseline thật (KS-BA, 6 transcript):** 239 API call · **$28.88** · `_unattributed` 25.1% · phase `ba-ticket-author` chiếm đa số.
> Cảnh báo cho nhóm C: bản đầu báo 516 row / $65.39 vì đếm một API call nhiều lần (Claude Code tách một assistant message thành 2-7 transcript row, mỗi row mang **cùng** khối `usage`). Mọi ưu tiên trong C nếu dựa vào số trước fix là dựa vào số cao gấp hơn hai lần.

- [x] **B1 — Usage ledger trong repo** (~0.5 ngày)
  File `.kb/usage/<ticket-id>.jsonl` (mission-level → `<mission-id>.jsonl`), **commit vào git** — nhờ đó chi phí đi theo lịch sử ticket và PR mang luôn con số. Mỗi row: `{ts, actor: ba|dev, phase (ba-ticket-author / dev-design / dev-execute…), ticket, model, tokens_in, tokens_out, cache_read, cache_write, est: true|false, assistant: claude-code|copilot|cursor, session}`. Viết qua CLI mới `kb usage note` (append-only, như pattern `kb svc note`).
- [x] **B2 — Capture tự động** (~1 ngày)
  - **Claude Code (nguồn chính xác):** scaffold hook `Stop`/`SubagentStop` trong `.claude/settings.json` gọi script → `kb usage ingest-transcript <path>`: parse transcript JSONL (mỗi message có usage + model thật), attribute vào ticket theo branch name / đường dẫn `docs/impl/<id>-*` xuất hiện trong session, append vào ledger. Không cần agent tự khai — số liệu là số thật của assistant.
  - **Copilot / Cursor (không có hook):** fallback tự khai — closing block của skill gọi `kb usage note --est` với ước lượng của agent, đánh dấu `est: true` để dashboard phân biệt số đo và số ước. Nói thẳng giới hạn này trong QUICKSTART thay vì giả vờ chính xác.
  - **Lưu ý thiết kế:** `.claude/settings.json` là file dev có thể đã tự cấu hình — scaffold chỉ ghi khi chưa tồn tại, hoặc tách script ra `.claude/hooks/` và hướng dẫn merge tay; quyết định trước khi code. Thêm file scaffold = bump `tests/test_init.py` pinned count có chủ đích.
- [x] **B3 — Website trong repo: `kb usage report`** (~1–1.5 ngày)
  Sinh **`.kb/usage/report.html` tĩnh, self-contained** (không server, mở thẳng bằng browser, commit được): tổng theo ticket, breakdown theo phase, theo model, theo actor BA/Dev, ước chi phí qua bảng giá `usage-prices.yaml` (default trong package, repo override được vì giá model thay đổi). Tuỳ chọn thêm sau: `kb usage serve` tái dùng stack FastAPI/templating sẵn có trong `center_kb.web` cho live view, và một job CI regenerate report.html mỗi push. Khuyến nghị: **static-first** — đủ cho nhu cầu "mở ra là thấy", zero vận hành.
- [ ] **B4 — Nối vào handover** (gom vào ĐỢT TEMPLATE CHUNG)
  `dev-handover` thêm mục "Usage" trong PR body (`kb usage report --ticket <id> --md`) — PR nào cũng mang chi phí của chính nó; `ba-ticket-author` báo usage trong handover summary. Chi phí ticket **xuyên hai repo** (BA viết + Dev implement) ghép bằng ticket id chung: MVP mỗi repo xem phần của mình, bước sau thêm `kb usage merge` gộp hai ledger khi cần bức tranh đầy đủ.

## C — Tối ưu token ở BA + Dev (làm SAU khi B có số liệu ~1–2 tuần)

B quyết định thứ tự trong C — cắt chỗ số liệu chỉ ra là đau nhất. Theo phân tích tĩnh, dự đoán xếp hạng như sau:

- [ ] **C1 — Context cache file cho pipeline Dev** (~1 ngày; dự đoán giá trị lớn nhất)
  Freshness re-check chạy ở đầu cả 5 skill và `kb resolve` trả **toàn văn** nội dung pinned mỗi lần → một ticket kéo cùng nội dung ~4–5 lần. Fix: orchestrator ghi `docs/impl/<ticket-id>-context.md` (nội dung resolved + placeholder map) một lần; các phase sau chỉ cần verdict qua flag CLI mới `kb resolve --status-only`; chỉ resolve đầy đủ lại khi verdict ≠ ok hoặc version đổi. **Không** thêm param vào MCP tool `kb_resolve` — schema đổi là vỡ golden; CLI flag thì an toàn.
- [ ] **C2 — Maturity review: round 2–3 chỉ verify gap** (skill text — ĐỢT TEMPLATE CHUNG)
  Hiện tối đa 2 reviewer × 3 round = 6 lần đọc toàn văn. Sửa: round 1 giữ 2 reviewer đầy đủ; round 2–3 một reviewer, nhận đúng gap list + đoạn đã sửa, chấm pass/fail từng gap. Tiết kiệm ~40–60% chi phí review, vẫn giữ two-perspective ở round 1.
- [ ] **C3 — dev-execute: subagent mỗi task chỉ nhận task block của nó** (skill text — ĐỢT TEMPLATE CHUNG)
  Plan format đã thiết kế sẵn cho việc này (mục **Interfaces** tồn tại chính vì "a task's implementer sees only their own task") — chỉ thiếu câu lệnh tường minh trong skill.
- [ ] **C4 — Kỷ luật budget cho kb_search** (skill text — ĐỢT TEMPLATE CHUNG)
  Khám phá rộng: budget 500–800 (đủ citation + summary để chọn); `kb_get_section` chỉ với section đã chọn; L3 chỉ cho giá trị sẽ encode vào code/test.
- [ ] **C5 — Rút gọn shared block trong 5 skill dev** (~0.5 ngày, đụng canon)
  Freshness block + 14 hard rules + Next-step block lặp nguyên văn trong cả 5 skill, nạp ~5 lần/phiên orchestrator. Viết gọn một lần: hard rules gom còn ~8 dòng, freshness block còn nửa. Sửa canon = sửa hai chỗ (SHARED_BLOCK_TEXT + wrappers), không regenerate canon từ wrapper.
- [ ] **C6 — Model tiering (assistant-level, không đụng center-kb)**
  Bước cơ khí (lint-fix loop, tick checkbox, format PR body) chạy model rẻ; design/review chạy model mạnh. Ghi vào QUICKSTART như khuyến nghị vận hành. **B1 ghi lại model per row nên hiệu quả tiering đo được ngay trên dashboard B3.**

## D — Conventions pack đi theo package center-kb

Theo quyết định đã chốt: không có tầng conventions trên hub — tất cả ship trong package, scaffold khi `kb init`.

- [ ] **D1 — Preset linter/formatter theo ngôn ngữ** (~0.5 ngày)
  Python = ruff (+format), TS/JS = eslint + prettier, Java = checkstyle/spotless, cộng `.editorconfig`. `dev-plan` sửa một câu: repo chưa có linter → task đầu tiên của plan là setup lint theo preset (hiện skill chỉ hỏi lệnh, chưa xử lý "không có gì để chạy").
- [ ] **D2 — Template `conventions-<lang>.md` trong `templates/init/`, scaffold theo stack** (~1–1.5 ngày)
  Detect stack bằng `detect_frameworks()` sẵn có; deploy ra đúng chỗ mỗi assistant tự đọc mọi phiên: `CLAUDE.md`, `.cursor/rules/coding-<lang>.mdc`, `.github/instructions/coding-<lang>.instructions.md`. Nội dung: naming, cấu trúc module, error handling, logging, quy cách comment citation (`# per ATM-STD §5.3 @ rev`), quy tắc viết test — phần linter không bắt được.
- [ ] **D3 — Cơ chế base + local override** (thiết kế cùng D2 — điểm quan trọng nhất của D)
  Mâu thuẫn phải giải: file theo package thì upgrade phải ghi đè được, nhưng conventions chắc chắn bị repo tuỳ biến — mà `kb init` re-run ghi đè scaffold hand-edited. Giải bằng hai file: `docs/conventions/<lang>.md` (base, package-owned, ghi đè khi re-init — nhận cập nhật chuẩn qua upgrade package) + `docs/conventions/<lang>.local.md` (never-touch như `.kb/config.yaml`; **local thắng base khi xung đột**). Wrapper rules trỏ cả hai.
- [ ] **D4 — Nối vào workflow Dev** (skill text — ĐỢT TEMPLATE CHUNG nếu kịp, không thì đợt riêng của D)
  Review checkpoint của `dev-execute` đổi "follow the repo's existing conventions" thành trỏ tường minh conventions file (base + local); xung đột với style hiện hữu của repo → repo thắng cục bộ, ghi finding vào PR.
- [ ] **D5 — Bump trip-wires có chủ đích**
  `tests/test_init.py` pin số file scaffold chính xác; `tests/test_templates.py` pin canon. Thêm template = bump hai test này có chủ đích.

## E — Củng cố kỷ luật bằng máy + pilot

- [ ] **E1** PR template bắt buộc AC→test map + verification output (dev-handover đã assemble sẵn — quy ước reviewer từ chối PR thiếu mục).
- [ ] **E2** Định nghĩa TDD exemption categories (config/CI/docs/style → verify bằng gì thay test-đỏ-trước) — vá rủi ro lớn nhất của workflow trước pilot.
- [ ] **E3** Pilot 2–3 sprint trên một project line, đo: % ticket bị trả vì không Ready, % AC ra OPEN(BA), lead time theo cỡ ticket, số finding tại PR review — **cộng token/cost per ticket từ dashboard B3** (giờ là số đo, không phải ước).

---

## ĐỢT TEMPLATE CHUNG — gom mọi sửa skill text thành một lần

Mọi lần sửa template trả cùng chi phí: 4 wrapper/skill (claude-skill, claude-command, copilot, cursor) + canon test hai chỗ. Gom **A4 + B4 + C2 + C3 + C4 (+ D4 nếu nội dung conventions đã sẵn)** thành một đợt duy nhất, làm ngay sau khi engine của A và B xong — một PR template, một lần bump canon, một lần review.

## Hướng đi tốt nhất (một đoạn)

Bắt đầu bằng A1–A3 (engine tag-fix + quét backlog) vì đây là bug đang chủ động làm bẩn KB theo từng ticket mới — nhỏ, độc lập, ~1.5 ngày. Song song hoặc ngay sau đó làm B1–B3 (ledger + capture + report.html): đo lường phải có **trước** khi tối ưu, và website trong repo là thứ tạo cảm nhận giá trị ngay cho cả BA lẫn Dev — mở `.kb/usage/report.html` là thấy ticket này tốn bao nhiêu, model gì, phase nào ngốn nhất. Khi engine A + B xong, chạy **một đợt template chung** (A4 + B4 + C2 + C3 + C4) — trả chi phí 4-wrapper + canon đúng một lần. Sau 1–2 tuần số liệu từ B, làm C1 (context cache + `kb resolve --status-only`, item tiết kiệm dự đoán lớn nhất) và C5 nếu số liệu xác nhận. Rồi D conventions pack theo đúng quyết định đi-theo-package — với D3 (base + local override) là điểm phải thiết kế cẩn thận nhất. E chạy cùng pilot, và pilot lúc này đã có sẵn dashboard token để báo cáo. Xuyên suốt: không thêm MCP tool, không đổi schema/docstring 5 tool hiện có (golden byte-identical), mọi capability mới là CLI command, mọi lần đụng template/scaffold là một lần bump trip-wire có chủ đích.

| Đợt | Gồm | Effort ước | Ghi chú |
|---|---|---|---|
| 1 | A1, A2, A3 (engine tag-fix) | ~1.5 ngày | Branch riêng, độc lập |
| 2 | B1, B2, B3 (ledger + capture + report.html) | ~2.5–3 ngày | CLI `kb usage`, hook Claude Code, fallback est cho Copilot/Cursor |
| 3 | Đợt template chung: A4 + B4 + C2 + C3 + C4 | ~1 ngày | Một PR, một lần bump canon |
| 4 | C1 (+C5 nếu số liệu xác nhận) | ~1.5 ngày | Sau 1–2 tuần dữ liệu từ B |
| 5 | D1→D5 conventions pack | ~2.5–3 ngày | D3 base+local là điểm thiết kế then chốt |
| Cùng pilot | C6, E1–E3 | vận hành | Dashboard B3 nuôi báo cáo pilot |
