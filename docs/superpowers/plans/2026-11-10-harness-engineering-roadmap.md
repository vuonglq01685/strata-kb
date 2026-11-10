# Roadmap: đưa Strata thành harness engineering cho Claude Code

> Ngày: 2026-11-10 · Phạm vi: chỉ Claude Code (không đa provider) · Trạng thái: đề xuất

## Tóm tắt

Định vị đúng: **Claude Code là inner harness** (tool loop, quyền, subagent), **Strata là outer harness** (chọn việc, cấp context, tự verify, đo lường, học từ lỗi).

Không tự viết lại agent loop và không thêm lớp trừu tượng đa provider. Hướng đi là tận dụng tối đa primitive có sẵn của Claude Code: hooks, `.claude/agents/`, `--resume`, `--max-turns`, envelope JSON của `claude -p`.

Strata hiện đã có phần lớn nền móng (context/KB, gate cơ học, outer loop, phân quyền, đo token). Phần còn thiếu nằm ở bốn trụ: **harness tự verify, vòng phản hồi khi retry, guardrail lúc chạy, eval + observability**.

---

## 1. Luồng hiện tại

`kb auto run` → `runner.preflight` → `run_loop` → lặp `run_once`:

1. Kiểm tra `all_done` (mọi ticket `done`; BA cần thêm 0 câu hỏi mở).
2. Chọn task (`autorun/picker.py`):
   - **BA**: đọc `kb mission next --json` từ worktree `origin/HEAD`, ưu tiên `ba-mission-plan --amend` → `ba-ticket-author --amend` → ticket kế tiếp → ticket `to-draft`.
   - **Dev**: `dev-test-workflow` nếu chưa có workflow `kb-test`; sau đó bug → `dev-fix-bug`, ticket/story → `dev-implement-ticket` (ready, đúng repo, đủ `depends_on`).
3. Lấy claim trên hub (Dev) và chạy `ClaimBeat` heartbeat 900s.
4. Chạy `claude -p --output-format json --permission-mode acceptEdits [--model] [--effort]`, prompt `/<skill> <arg>` kèm luật auto mode, timeout 4h, `cwd=root`.
5. Đọc dòng cuối `AUTO-RESULT: done | blocked-qa Q.. | blocked-split BUG-.. | failed <reason>`.
6. `_settle` ghi vào `.kb/auto/state.json`: usage-limit → backoff 900→3600s; `failed` → `attempts+1`, dừng ở `MAX_ATTEMPTS=2`; `ci-red` → dừng ngay.

Toàn bộ verify (test, review subagent A2–A5, CI watch, merge, publish) nằm **trong text của skill**. Runner tin dòng `AUTO-RESULT` của agent.

### Điểm mạnh đã có

| Trụ cột | Hiện trạng |
|---|---|
| Context / system of record | KB L0→L3, `kb context`, MCP 16 tool (`kb_search`, `kb_get_section`, `kb_ticket_check`, `kb_question_*`, ...) |
| Gate cơ học | `ticket lint` (DoR), `mission lint`, `ticket check` (grounding), `pr lint`, table diff trong `kb build`, `l3check`, `ticket stale` nightly |
| Outer loop | picker, state, claim đa máy, QA bất đồng bộ (`QaThread`), backoff, `publishwatch` |
| Phân quyền | allow/deny trong `claude-settings-auto.json` (cấm push main, force push, sửa settings, `.git/**`) |
| Đo lường | Stop/SubagentStop hook → `kb usage ingest-transcript` → `.kb/usage/<ticket>.jsonl`, `kb usage report` |
| Review nhiều tầng | dev-execute: implementer subagent TDD, task-reviewer, branch-reviewer, merge-risk-reviewer |

### Lỗ hổng (đã kiểm chứng trong code)

| # | Lỗ hổng | Vị trí |
|---|---|---|
| G1 | Agent báo `done` là runner ghi done; không verify độc lập (chỉ gián tiếp qua lần pick sau, `MAX_SAME_PICK=5`) | `src/strata_kb/autorun/runner.py:374` |
| G2 | Retry dùng y hệt prompt cũ: không có lý do fail, số lần thử, log trước | `src/strata_kb/autorun/claude.py:63-88` |
| G3 | Bỏ `session_id`, `total_cost_usd`, `num_turns` của envelope; không nối outcome ↔ usage ledger | `src/strata_kb/llm.py:114-117` |
| G4 | Chỉ có Stop/SubagentStop (ghi token). Không có PreToolUse/PostToolUse/SessionStart; `conventions-*-hooks.md` chỉ khuyến nghị, không cài | `templates/init/claude-settings-auto.json` |
| G5 | Task Dev/BA chính chạy thẳng trong `root`, không worktree riêng | `autorun/claude.py:158` |
| G6 | Timeout 4h cố định cho mọi skill, không có ngân sách turn/cost | `autorun/claude.py:26` |
| G7 | Mất claim không dừng task đang chạy, chỉ kiểm tra sau khi task kết thúc | `autorun/claimbeat.py`, `runner.py:573` |
| G8 | Vai trò subagent (implementer, plan-author, task-reviewer, ...) chỉ là text trong prompt, không có `.claude/agents/*.md` | `templates/init/bodies/dev-execute.md` |
| G9 | Không có eval chạy LLM thật; mọi test dùng `tests/fake_claude.py` | `tests/`, `tests-gate/` |
| G10 | `ticket check` không chạy trong CI; agent có thể sửa `.github/workflows/**`, rubric, test (luật chỉ nằm trong prompt) | `templates/init/kb-pr-lint.yml` |
| G11 | Thiếu quyền mà skill có dùng: `kb get`, `mkdir`, `kb build/summarize/approve` | `claude-settings-auto.json` |
| G12 | Command và skill body là hai bản sao đã lệch (vd. dev-execute 324 vs 376 dòng) | `templates/init/claude-command-dev-execute.md` |
| G13 | Kết quả chỉ parse bằng dòng cuối; thiếu dòng → `failed "no result line"`, không có cơ chế buộc agent viết | `autorun/claude.py:44-46` |

### Rủi ro bảo mật cần quyết định trước

Skill hướng dẫn agent dùng `kb pr merge --squash --admin` khi merge bị từ chối do thiếu review (`templates/init/bodies/dev-handover.md:285`, `bodies/ba-ticket-author.md:487`, `bodies/dev-test-workflow.md:133`, `bodies/kb-auto.md:137`). Như vậy agent có thể tự merge PR của chính mình, vượt branch protection.

Trong harness engineering, "agent không tự duyệt cho mình" phải là ràng buộc cứng phía GitHub (required reviews, CODEOWNERS, token không có quyền admin), không phải text trong prompt. Cần quyết định chính sách này trước khi mở rộng tự động hóa.

---

## 2. Roadmap

| Phase | Mục tiêu | Việc chính | Sửa | Cỡ |
|---|---|---|---|---|
| **P0. Run record** | Nền dữ liệu cho mọi phase sau | `run_task` giữ `session_id`, `total_cost_usd`, `num_turns`, `duration_ms`, `is_error` từ envelope. Ghi append-only `.kb/auto/runs.jsonl`: run_id, skill, arg, attempt, outcome, reason, cost, turns, HEAD trước/sau. Nối với usage ledger qua `session`. | G3 | S |
| **P1. Harness tự verify** | "Done" do harness quyết định | Thêm `verify(task)` trước khi `_settle` ghi done. **Dev**: PR merged (`kb pr find`/`kb pr view`), `gh pr checks` xanh, `kb pr lint`, `kb ticket check`, status trên hub. **BA**: `ticket lint`/`mission lint` pass, publish run thành công (tổng quát hóa `publishwatch`). Verify fail → `failed verify:<lý do>`. Đưa `kb ticket check` vào `kb-pr-lint.yml`. | G1, G10 | M |
| **P2. Retry có phản hồi** | Lần sau học từ lần trước | Phân loại lỗi: verify / ci-red / timeout / no-result / permission-denied / usage-limit, mỗi loại một chính sách thay cho `MAX_ATTEMPTS=2` chung. Lỗi verify → `claude -p --resume <session_id>` kèm danh sách lỗi (giữ context, rẻ hơn). Crash/timeout → session mới, prompt có attempt, lý do và đoạn cuối log. | G2 | M |
| **P3. Guardrail lúc chạy** | Chặn ngay khi agent làm, không chờ CI | Lệnh mới `kb guard` được gọi từ hook. **PreToolUse**: chặn sửa `.github/workflows/**`, `pr-review-rubric.md`, `tdd-exemptions.md`, xóa/skip test, sửa bảng L2, file ngoài scope `docs/impl/<id>/plan.md`. **PostToolUse**: format/lint theo ngôn ngữ (cài các hook conventions đang khuyến nghị). **Stop**: khi `STRATA_KB_AUTO_TASK=1` mà reply thiếu `AUTO-RESULT` → block, yêu cầu viết. **SessionStart**: nạp context KB của ticket. Vá quyền G11. | G4, G10, G11, G13 | M |
| **P4. Cô lập & ngân sách** | An toàn, có trần chi phí | Mỗi task một worktree `.kb/auto/worktrees/task-<id>`, dọn sau khi xong. `--max-turns` và timeout theo skill. Trần cost qua `--output-format stream-json`, kill khi vượt. ClaimBeat mất claim → kill process. | G5, G6, G7 | M |
| **P5. Subagent & skill thành artifact** | Giảm phụ thuộc prompt text | Scaffold `.claude/agents/*.md` cho implementer, plan-author, plan-reviewer, task-reviewer, branch-reviewer, merge-risk-reviewer: pin model, reviewer chỉ có tool đọc. Sinh command từ body (hết lệch). Thêm block CLAUDE.md: tổng quan KB, danh mục skill, luật auto mode. | G8, G12 | M |
| **P6. Eval harness** | Đổi skill có số đo | `tests-eval/`: sandbox hub + ba + dev với ticket mẫu, chạy skill bằng `claude -p` thật, chấm bằng **chính verifier của P1** cộng các gate. Đo pass rate, cost, turns, retry. Chạy nightly/thủ công, không đưa vào T1. Gate: không merge thay đổi skill nếu pass rate giảm so với baseline. | G9 | L |
| **P7. Observability & cải tiến liên tục** | Vòng học | `kb auto report` (tái dùng `usage/report.py`): tỉ lệ thành công theo skill, cost/ticket, tỉ lệ retry, top lý do fail. Lỗi lặp ≥N lần → mở issue "skill-debt"; người duyệt sửa skill, qua eval gate. Trang runs trên Web UI hub. | — | M |

### Thứ tự phụ thuộc

```
P0 ──► P1 ──► P2
 │      │
 │      └──► P6 ──► P7
 └──► P4
P3, P5: độc lập, làm song song được
```

### Sprint 1 đề xuất (quick win)

1. Chốt chính sách `--admin` merge và cấu hình GitHub tương ứng.
2. P0: run record.
3. Stop hook ép dòng `AUTO-RESULT` (một phần P3).
4. Vá quyền G11.
5. Thêm `kb ticket check` vào `kb-pr-lint.yml`.

---

## 3. Phụ thuộc cần có

### Công cụ và hạ tầng

| Phụ thuộc | Cần cho | Ghi chú |
|---|---|---|
| Claude Code CLI (pin version tối thiểu) | P0–P4 | Cần `--output-format json/stream-json`, `--resume`, `--max-turns`, `--settings`, schema hook PreToolUse/Stop có decision `block`. Thêm check `claude --version` vào `kb doctor`. |
| `gh` có auth trong môi trường runner | P1 | Verify PR/checks từ runner, không chỉ từ skill. |
| `git worktree` | P4 | Đã dùng sẵn cho plan và QA. |
| Org/repo GitHub test, Claude subscription hoặc API key trong CI secret, trần ngân sách | P6 | Eval chạy LLM thật nên tốn chi phí và có thể flaky; tách khỏi `_gate.yml` T1. |
| Python deps | P0–P5 | **Không cần thêm** (typer, pydantic, jinja2 đã có). |
| `claude-agent-sdk` (tùy chọn) | Sau P4 nếu cần | Chỉ cân nhắc khi cần permission callback hoặc kill theo budget trong process. Hiện chưa cần; subprocess CLI đủ. |

### Hiệu ứng lan khi thay đổi framework

| Chỗ bị ảnh hưởng | Lý do |
|---|---|
| `src/strata_kb/templates/init/claude-settings-auto.json`, `.claude/agents/` (mới), `templates/init/bodies/*` | Hook, quyền, subagent, hợp đồng `AUTO-RESULT` |
| `tests/test_templates.py`, `tests/test_template_bodies.py` | Pin text template; phải cập nhật canon |
| `src/strata_kb/initcmd.py` + **đường migrate cho repo ba/dev đang chạy** | `kb init` bị deny trong auto mode; `preflight` yêu cầu `.claude/settings.json` tracked và sạch trên default branch → mỗi repo cần một PR nâng cấp (cần lệnh kiểu `kb upgrade` hoặc `kb doctor --fix`) |
| `src/strata_kb/autorun/state.py`, `runs.jsonl` mới | Version schema, giữ backward compat (`tests-gate/regression` có test tương thích `.kb`) |
| CI templates (`kb-pr-lint.yml`) | Thêm `ticket check`; CODEOWNERS cho `.github/workflows` |
| Cấu hình GitHub (ngoài code) | Branch protection, required checks, token không có quyền admin. Đây là enforcement thật; hook chỉ chạy phía client |
| `src/strata_kb/doctor/` | Check đủ hook, agents, version CLI |
| `docs/src/guide-dev.*.md`, `guide-ba.*.md`, `templates/init/bodies/kb-auto.md` | Mô tả luồng verify, retry, budget mới |
| `tests/fake_claude.py` | Giả lập thêm `session_id`, cost, `--resume` |

### Không làm

- Lớp trừu tượng đa provider (phạm vi chỉ Claude).
- Tự viết agent loop gọi API trực tiếp.
- Mở rộng fallback `copilot` trong `llm.py` (giữ nguyên cho `kb summarize`).

---

## Chưa kiểm tra

- Chưa đọc hết body skill BA, `dev-design`, `dev-code-seed`, `claimclient.py`.
- Cỡ S/M/L là ước lượng sơ bộ, chưa đo.
