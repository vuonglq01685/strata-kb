# CENTER-KB — Summarize quality: prose-only input, length guard, --redo — Design

**Ngày:** 2026-07-11
**Nguồn:** chẩn đoán systematic-debugging trên KB thật (`/Users/vuonglq01685/Documents/Projects/CENTER-KB`, arinc-424, 449 sections, sonnet-5 high): L2 = 217k tokens vs L3 = 262k (tiết kiệm 17% thay vì 70–80%); 4 file L2 ≥ L3; prose L2 của ch4 dài hơn prose gốc +22%; model transcribe nội dung bảng thành văn xuôi và bịa prose cho section chỉ-có-bảng.
**Phạm vi:** sửa engine summarize (`summarize.py`, `cli.py`) + template kb-summarize (manual path). Không đổi format `.kb/`, không đổi scaffold ingest, không đổi engine tra cứu.

---

## 1. Root cause (đã xác minh bằng evidence)

| # | Nguyên nhân | Bằng chứng |
|---|---|---|
| RC1 | `parse_json_reply` bắt buộc `l2_summary` non-empty → section chỉ-có-bảng (prose rỗng) ép model bịa văn mô tả bảng | §4.1.2.1 ch4: raw chỉ heading+bảng; L2 có prose mới liệt kê cột ("col 22 §5.16…") trùng với bảng verbatim bên dưới |
| RC2 | `collect_pending` đưa nguyên bảng vào `l3_body` của prompt → model dệt nội dung bảng vào summary; prompt chỉ dặn "do not summarize tables" | ch4: 83% bytes prompt là bảng; L2 prose chứa transcription bảng |
| RC3 | Target 20–30% không được cưỡng chế: retry chỉ kiểm JSON, không kiểm độ dài; các rule "preserve VERBATIM + không bịa" đẩy model chép gần nguyên văn | prose L2 ch4 = 48.1k bytes > prose L3 = 39.6k (+22%) |

Ghi chú kiến trúc: bảng chiếm ~80% tài liệu đặc bảng như ARINC 424 và được copy verbatim vào L2 theo thiết kế — trần tiết kiệm của L2 với loại tài liệu này là ~20–25% kể cả khi prose nén hoàn hảo. Chấp nhận, không đổi thiết kế bảng.

## 2. Quyết định

| # | Vấn đề | Quyết định | Lý do |
|---|---|---|---|
| 1 | Bảng trong prompt input | **Strip bảng khỏi `l3_body` trước khi build prompt**: mỗi khối bảng liên tục (dòng bắt đầu `|`) thay bằng placeholder `[table omitted]` | Model không thể transcribe thứ nó không thấy (diệt RC2); prompt nhẹ ~80% với file đặc bảng → rẻ + nhanh; placeholder giữ ngữ cảnh "chỗ này có bảng" cho l1_summary |
| 2 | Section không có prose | **Không gọi LLM.** Sau khi strip bảng, bỏ heading/placeholder/blank — còn rỗng thì: marker → `""` (L2 = heading + bảng), `l1 = "Table-only section: {title}."` (deterministic), status → summarized | Diệt RC1 tận gốc: không ép model bịa; tiết kiệm call |
| 3 | Cưỡng chế độ dài | **Char budget tường minh trong prompt + guard sau parse.** `max_chars = max(300, int(0.35 * len(prose)))` ghi thẳng vào prompt ("at most {max_chars} characters"). Reply dài hơn → retry 1 lần với prompt nêu rõ vi phạm và budget; vẫn dài → section failed (giữ pending) | Số cụ thể enforce được (diệt RC3); floor 300 chars tránh fail section prose ngắn; giữ tổng ≤ 2 call/section như hiện tại |
| 4 | Chạy lại section đã summarized | **`kb summarize --redo [DOC_ID]`**: tái tạo L2 scaffold từ chính file L2 hiện có (giữ dòng heading `## ` + khối bảng, thay toàn bộ prose mỗi section bằng marker `<!-- TODO:summarize <id> -->`), reset status summarized/reviewed → pending, xoá `summary` trong manifest, rồi chạy summarize bình thường | Không cần parse lại PDF; L2 có cấu trúc xác định (heading → prose → bảng) nên rebuild deterministic; reset cả reviewed vì mục đích là làm lại toàn bộ (in warning số section reviewed bị reset) |
| 5 | Manual path (skill/instructions) | Cập nhật template `claude-skill-kb-summarize.md` + `copilot-kb-summarize.instructions.md` cùng rule: chỉ tóm tắt prose, không mô tả/transcribe bảng, section chỉ-có-bảng thì thay marker bằng rỗng, budget ~30% prose. Sync dogfood copy `.claude/skills/kb-summarize/SKILL.md` | Manual path phải nhất quán với engine, tránh tái nhiễm khi user sửa tay |
| 6 | KB thật (CENTER-KB) | Sau khi merge: chạy `kb summarize --redo arinc-424` + `kb build` tại `/Users/vuonglq01685/Documents/Projects/CENTER-KB`, so sánh kb stats trước/sau | Người dùng đã duyệt re-run toàn bộ 449 section |

## 3. Thay đổi kỹ thuật

- `summarize.py`:
  - `strip_tables(text) -> str` — thay khối bảng bằng `[table omitted]`, gộp blank thừa.
  - `collect_pending`: `l3_body` = prose-only (sau strip). Thêm field đánh dấu table-only (prose rỗng).
  - `SECTION_PROMPT`: nêu rõ nguồn đã bỏ bảng, cấm mô tả/suy diễn nội dung bảng, thêm dòng budget `at most {max_chars} characters`.
  - `_summarize_one`: table-only → trả kết quả deterministic không gọi runner; length guard + strict-retry.
  - `redo_reset(kb_dir, doc_id | None) -> RedoReport` — rebuild L2 + reset manifest như quyết định #4.
- `cli.py`: flag `--redo` cho `kb summarize`.
- Templates + dogfood copy như quyết định #5.

> **2026-09-09 amendment** (spec `2026-09-09-summarize-build-review-fixes-design.md`):
> the budget is `max(120, 0.35 × prose)` measured on `quality.prose_only()`
> (headings, `[table omitted]`, `Figure:` lines excluded) — the 300-char floor
> made it a 0.45× guard in aggregate; sections with ≤ 200 chars of prose are
> copied verbatim into L2 with the label `Brief section: <title>.` and no LLM
> call; the same rules are enforced by `kb build` (warn / `--strict`).
> Decision #6 (re-run the shipped KB) is still outstanding.

## 4. Testing

- Unit: `strip_tables` (bảng đầu/cuối/nhiều khối/không bảng); table-only detection; length guard (pass/violate/retry-then-fail — stub runner); prompt chứa budget; redo rebuild (L2 có summary + bảng → marker + bảng, idempotent, manifest reset, reviewed reset có warning).
- E2E stub-CLI hiện có phải giữ xanh; bổ sung case redo với stub.
- Test init: marker template không đổi nên không ảnh hưởng; test template kb-summarize cập nhật theo nội dung mới.

## 5. Ngoài phạm vi

- Đổi thiết kế "copy bảng verbatim vào L2" (trần tiết kiệm ~20–25% với tài liệu đặc bảng — chấp nhận).
- Tóm tắt/summarize nội dung bảng dưới bất kỳ hình thức nào.
- Thay đổi model/effort mặc định.
