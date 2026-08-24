# Đánh giá workflow Dev Agent (Phase 5) — khả năng áp dụng thực tế & khoảng trống về coding conventions

**Ngày:** 2026-08-22
**Căn cứ:** `docs/superpowers/specs/2026-08-19-dev-agent-design.md`; các plan Stage A/B/C+D và hai file handover; bộ template `src/center_kb/templates/init/*dev-*`; `QUICKSTART-dev.md`; `config-dev.yaml`; `kb-code.yml`.
**Hiện trạng lúc đánh giá:** Stage A (kind `dev` + 5 skill) và Stage B (`kb code-ingest`, `kb-code.yml`) đã hoàn tất — v0.17.0, full suite 1567 passed. Stage C+D đang chạy trong worktree `phase-5-cd-svc-knowledge`.

---

## 1. Workflow đang dùng là gì

Dev Agent không phải một agent chạy tự do mà là một **pipeline 5 skill có kịch bản cứng**, scaffold vào product repo bằng `kb init --kind dev`, chạy được trên cả Claude Code, Copilot Chat và Cursor:

`/dev-implement-ticket` (orchestrator: Intake → Resolve → Ground → Placeholders) → `/dev-design` → `/dev-plan` → `/dev-execute` → `/dev-handover`.

Xương sống của nó là bốn thứ: **grounding bắt buộc** (ticket phải có `kb-context` resolve được; giá trị chuẩn phải trích verbatim từ section đã pin, có citation); **TDD bắt buộc** (không có production code khi chưa thấy test đỏ); **trạng thái nằm trong file** (`docs/impl/<ticket>-design.md`, `-plan.md` với checkbox — phase nào cũng resume được ở session mới); và **bốn gate con người** (duyệt design, duyệt plan, mở PR, merge — agent không làm hai việc cuối).

## 2. Có thực sự áp dụng được không?

**Kết luận ngắn: áp dụng được, và thiết kế này thực tế hơn phần lớn "dev agent workflow" đang lưu hành — nhưng với ba điều kiện tiên quyết và bốn rủi ro cần quản.**

### 2.1 Vì sao tôi đánh giá là áp dụng được

Thứ nhất, nó **không phát minh phương pháp mới**. Bốn phase được port từ bộ superpowers (brainstorming → writing-plans → subagent-driven-development → verification-before-completion) — một phương pháp đã được kiểm chứng ở quy mô thật — rồi viết lại đứng độc lập cho center-kb. Phần rủi ro nhất của một agent workflow (agent "sáng tác" quy trình mỗi lần chạy) đã bị loại từ thiết kế.

Thứ hai, nó **khớp với nhịp làm việc thật của một ticket**: một ticket kéo dài nhiều ngày, nhiều session. Việc tách 5 skill theo ranh giới session (chứ không theo kích thước việc) cộng với state nằm trong file + branch + PR — không nằm trong trí nhớ hội thoại — nghĩa là Dev quay lại sau ba ngày gõ đúng một lệnh là tiếp tục được. Đây là điểm mà đa số quy trình agent thất bại, và ở đây nó được xử lý đúng.

Thứ ba, **mức độ tự động hoá được chọn khôn ngoan cho môi trường outsourcing/regulated**: agent chỉ tự động phần cơ khí (resolve, plan, viết test, chạy lint), còn quyết định nghiệp vụ luôn dội về người (AC không implement được → `OPEN(BA)`, không tự diễn dịch; citation stale → đưa cả hai version cho người quyết; agent không bao giờ sửa ticket, không merge). Với domain hàng không (ARINC-424, ICAO Annex 3) — nơi giá trị chuẩn sai một ký tự là lỗi nghiêm trọng — nguyên tắc "mọi giá trị chuẩn phải verbatim + citation, không được 'nhớ'" là đúng chỗ, không phải ceremony thừa.

Thứ tư, phần **hạ tầng đã chứng minh chạy được**: Stage A+B đã ship với gate test đầy đủ, `kb code-ingest` deterministic (LLM-free, byte-identical), CI publish qua OIDC không cần secret. Đường ống knowledge nuôi workflow này không phải giả định trên giấy.

### 2.2 Ba điều kiện tiên quyết (thiếu một cái là workflow "đói")

1. **BA phải ra ticket Ready thật.** Ticket không có `kb-context` bị trả lại ngay tại Intake — đây là feature, nhưng nghĩa là nếu pipeline BA (Phase 4/4.1) chưa chạy đều trên project áp dụng, Dev Agent sẽ bounce phần lớn ticket trong giai đoạn đầu và bị đội cảm nhận là "khó tính". Cần tính sequencing adoption: BA agent chạy ổn trước, Dev agent theo sau.
2. **Hub phải vận hành như một service**: hub URL + token + repo được allowlist trong `federation/registry.yaml`, hai biến môi trường `CENTER_KB_HUB_URL`/`CENTER_KB_HTTP_TOKEN` cấp cho từng Dev. Đây là ma sát vận hành thật (onboard từng máy dev), nên có checklist onboard riêng.
3. **`kb code-ingest` phải chạy ít nhất một lần trên repo áp dụng** để có `-code §cmd.*` (lệnh build/test/lint). Có fallback (dev-plan hỏi Dev rồi ghi vào đầu plan) nên không chặn, nhưng trải nghiệm đầy đủ cần Stage B bật trên repo đó.

### 2.3 Bốn rủi ro cần quản khi chạy thật

**R1 — TDD tuyệt đối sẽ va thực tế ở một lớp thay đổi.** "No production code without a failing test observed first, no exception" là đúng cho logic nghiệp vụ, nhưng ticket thật có cả sửa CI config, style/CSS, tài liệu, migration một chiều — những chỗ test-đỏ-trước hoặc vô nghĩa hoặc phải chế test hình thức. Spec chỉ mở một van (spike path). Nếu không định nghĩa rõ các loại thay đổi được miễn/thay thế (ví dụ: characterization test cho legacy, snapshot cho UI, "verify bằng lệnh gì" cho config), Dev sẽ hoặc chế test vô giá trị để qua rule, hoặc bỏ workflow — cả hai đều tệ hơn một ngoại lệ được kiểm soát.

**R2 — Kỷ luật nằm ở tầng prompt, không phải tầng kỹ thuật.** TDD, "paste real output", review checkpoint... đều là chữ trong skill — model tuân theo phần lớn thời gian nhưng không có gì *cưỡng chế* như CI. Phía KB đã có gate máy (kb build, ticket lint, golden fixtures); phía Dev thì gate máy mỏng hơn. Giảm rủi ro rẻ nhất: PR template bắt buộc AC→test map + output verification (dev-handover đã assemble sẵn, chỉ cần reviewer từ chối PR thiếu mục này), và cân nhắc một CI check tối thiểu (test count/coverage không giảm).

**R3 — Review trong dev-execute là self-review.** Checkpoint per-task do chính agent chấm pass/fail. Phía BA có two-reviewer maturity review, phía Dev thì đối trọng độc lập duy nhất là người review PR ở gate 4. Chấp nhận được cho pilot, nhưng nên nói rõ với đội: review checkpoint của agent không thay code review của người.

**R4 — Chi phí ceremony cho ticket nhỏ.** Đã được giảm đúng cách (bounded path: design ở chat, không file; orchestrator tự collapse), nhưng vẫn còn plan file + 4 gate cho mọi ticket. Nên đo ở pilot: lead time ticket nhỏ trước/sau khi áp workflow; nếu phình quá, nới ở quy trình duyệt (gate 1+2 gộp một lần duyệt cho ticket bounded) chứ đừng nới TDD.

**Khuyến nghị triển khai:** pilot trên một project line, 2–3 sprint, đo bốn số: % ticket bị trả vì không Ready, % AC ra `OPEN(BA)`, lead time theo cỡ ticket, số finding ở PR review. Bốn số này nói workflow đang tạo giá trị hay tạo ma sát.

---

## 3. Khoảng trống conventions/rules cho ngôn ngữ lập trình — cảm nhận của anh là **đúng**

Hiện trạng trong toàn bộ Phase 5: chuẩn code chỉ được chạm vào ở **hai chỗ gián tiếp**. Một, review checkpoint của `dev-execute` hỏi "does the change follow the repo's existing conventions" — tức là agent *suy* convention từ code sẵn có; repo nhất quán thì ổn, repo lộn xộn hoặc greenfield thì agent tự chọn style. Hai, `cmd.lint` lấy từ `-code §cmd.*` — nghĩa là repo nào chưa cấu hình linter thì bước lint **không có gì để chạy**, và không ai cảnh báo. Không có template conventions nào trong `DEV_TEMPLATES`, không CLAUDE.md, không `.cursor/rules`, không copilot-instructions cho coding style (grep xác nhận: các file `.cursor/rules/*.mdc`, `*.instructions.md` duy nhất là wrapper kb-summarize). Spec cũng chủ động loại per-language parser — nhưng đó là quyết định cho *knowledge extraction*, không phải câu trả lời cho *coding standards*; hai việc khác nhau và việc thứ hai đơn giản là chưa được thiết kế.

### 3.1 Đề xuất: kiến trúc 3 tầng, tận dụng đúng máy móc đã có

**Tầng 1 — Rule máy cưỡng chế được (làm trước, rẻ nhất).** Chuẩn hoá bộ linter/formatter theo ngôn ngữ: Python = ruff (+format), TS/JS = eslint + prettier, Java = checkstyle/spotless, cộng `.editorconfig`. Đóng gói thành preset nội bộ (một package/config repo của FHN.AVI) để mọi dev repo dùng chung một nguồn. Sửa nhỏ vào `dev-plan`: khi repo chưa có linter, task đầu tiên của plan là setup lint theo preset (hiện skill chỉ hỏi lệnh, chưa xử lý trường hợp "không có lệnh"). Máy bắt máy — đây là 60–70% giá trị của "conventions" với chi phí thấp nhất.

**Tầng 2 — Rules file per-repo cho assistant (scaffold theo stack).** Thêm một họ template `conventions-<lang>.md` deploy thành đúng chỗ mỗi assistant tự đọc: `CLAUDE.md` (Claude Code), `.cursor/rules/coding-<lang>.mdc` (Cursor), `.github/instructions/coding-<lang>.instructions.md` (Copilot). Nội dung là phần linter không bắt được: naming, cấu trúc module, error handling, logging, quy cách comment citation (`# per ATM-STD §5.3 @ rev`), quy tắc viết test. `kb init --kind dev` có thể chọn template theo stack — **tái dùng `detect_frameworks()` của Stage B**, không cần máy móc mới. Ưu điểm lớn: assistant load các file này ở *mọi* phiên làm việc, kể cả khi Dev không đi qua flow `/dev-*`.

**Tầng 3 — Org-wide conventions như KB document trên hub (làm khi chuẩn đã chín).** Đưa bộ chuẩn tổ chức thành document `conv-python`, `conv-typescript`… ingest ở một child repo, review trên hub như mọi standard khác. Khi đó convention **được pin và cite y như giá trị domain** — đúng triết lý "không nhớ, chỉ trích dẫn" của center-kb — và `dev-design`/`dev-execute` chỉ cần thêm một dòng ở bước Ground: `kb_search conv-<stack>`, coi là normative. Quy tắc xung đột nên viết sẵn: org convention vs style hiện hữu của repo → **repo thắng cục bộ** (nhất quán trong file quan trọng hơn), nhưng ghi finding vào PR để trả nợ dần. Tầng này dùng nguyên pipeline ingest→review→publish và 5 MCP tool hiện có — **không vi phạm invariant nào**.

### 3.2 Lưu ý kỹ thuật khi hiện thực (để không vỡ invariants)

Việc này nên làm thành một stage nhỏ **sau khi Stage C+D đóng** (tránh đè lên worktree đang chạy và các template BA sắp bị Stage D sửa). Khi làm, có bốn bẫy đã được chính các handover ghi lại: (a) `tests/test_init.py` pin **số file scaffold chính xác** (hiện 27 cho kind dev) — thêm template là phải bump có chủ đích; (b) `tests/test_templates.py` pin canon SHARED_BLOCK_TEXT trên 20 wrapper (sắp 24 với dev-code-seed) — sửa text skill dev-* là sửa hai chỗ, không regenerate canon từ wrapper; (c) chính sách overwrite của `kb init`: wrapper hand-edit sẽ **bị ghi đè khi re-init** — file conventions per-repo chắc chắn sẽ được hand-edit, nên phải xếp vào nhóm "never touched" như `.kb/config.yaml`, không phải nhóm scaffold; (d) template tiếng Anh — giữ đúng quyết định English-only của bộ template hiện tại.

### 3.3 Thứ tự làm đề xuất

Tuần này có thể làm ngay Tầng 1 (preset lint + editorconfig, không đụng center-kb code). Tầng 2 là một task cỡ 1–1.5 ngày dev theo đúng pattern DEV_TEMPLATES (viết template, bump hai test pin, định nghĩa nhóm never-overwrite). Tầng 3 để sau khi FHN.AVI chốt được nội dung chuẩn từng ngôn ngữ — vì chi phí của nó nằm ở *soạn và review nội dung*, không nằm ở máy móc.

---

## 4. Tóm tắt một đoạn

Workflow Dev Agent áp dụng được thật: phương pháp mượn từ nơi đã được kiểm chứng, state file-based khớp nhịp ticket nhiều ngày, human gates đặt đúng chỗ cho domain regulated, và nền Stage A+B đã ship có test gate. Rủi ro chính không nằm ở thiết kế mà ở vận hành: TDD tuyệt đối cần van xả có kiểm soát cho lớp thay đổi không test được, kỷ luật đang được giữ bằng prompt nhiều hơn bằng CI, và toàn bộ flow đói nếu BA pipeline + hub chưa chạy đều. Còn khoảng trống anh chỉ ra là có thật và hiện chưa nằm trong scope stage nào: chưa có bất kỳ lớp coding conventions/rules nào cho ngôn ngữ lập trình — đề xuất bịt bằng ba tầng (preset linter → rules file per-repo theo stack → conventions document trên hub, pin-và-cite như standard), làm sau khi Stage C+D đóng, và làm đúng luật chơi của chính codebase này: bump hai test pin, xếp file conventions vào nhóm never-overwrite.
