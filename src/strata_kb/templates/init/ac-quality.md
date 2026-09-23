# AC quality — banned weasel words

An Acceptance Criterion must be verifiable by someone who has NOT read
the source documents. The phrases below shift all risk to Dev and QA,
then explode at acceptance time. They are banned in ACs; `kb ticket
lint` detects both the English and Vietnamese forms and reports each
hit as a warning; for the last row it stays silent when the AC already
names the means.

| Banned phrase | Write instead |
|---|---|
| "configured", "đã cấu hình" | the real value, or `OPEN(<owner>)` + an Open questions row |
| "appropriate", "reasonable", "phù hợp", "hợp lý" | the concrete criterion |
| "a subset", "some fields", "một tập con", "một số trường" | the full explicit list |
| "responsive", "phản hồi tốt", "không bị chậm" | a number + how it is measured |
| "handled correctly", "xử lý đúng" | the observable behavior |
| "where applicable", "if needed", "nếu cần" | the concrete trigger condition |
| "full support for", "hỗ trợ đầy đủ" | the supported scope AND the unsupported scope |
| "distinguished by type" without the means, "phân biệt theo loại" | the means: label, color, shape, grouping |
| a shell command in the AC (`docker compose ps …`, `curl …`, `grep …`) | the observable outcome (`every service reports healthy`, `no secret value is committed`); the exact command goes to `## Test data & verification`, or the Dev writes it in the plan where it can be run |

**Exception:** a banned phrase is allowed only when the same line
carries `OPEN(<owner>)` AND the ticket has a matching row in
`## Open questions`.

Lint reports violations as warnings — the BA judges. The Definition of
Ready still requires them resolved before handover to Dev.
