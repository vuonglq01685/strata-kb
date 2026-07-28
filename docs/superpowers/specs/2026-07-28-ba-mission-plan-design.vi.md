# Phase 4.1 — BA Mission Plan (`ba-mission-plan` + mission template C4 + `kb mission lint`) — Thiết kế (bản tiếng Việt)

**Ngày:** 28/07/2026
**Trạng thái:** Thiết kế đề xuất — chưa implement
**Lưu ý:** Bản dịch để đọc; bản tiếng Anh cùng tên (không có `.vi`) là bản chuẩn để agent implement.
**Dựa trên:** `docs/superpowers/specs/2026-07-17-ba-agent-design.md` (Phase 4, đã ship ở `a09f757`)
**Phạm vi:** Luồng tác nghiệp thứ hai của BA, nằm *thượng nguồn* `ba-ticket-author`: một Mission Plan ở mức epic mang diagram C4 Level 1 (System Context) và Level 2 (Container) cùng một US backlog, từ đó mới soạn từng ticket User Story. Gồm: một skill riêng (`ba-mission-plan`), mission template mới, DoR gate `kb mission lint` mới, thêm đúng một check cho `kb ticket lint`, và mở rộng CI gate sẵn có. **Không thêm MCP tool nào** (xem §9). Jira vẫn ở mức chỉ xuất Markdown.

---

## 1. Vấn đề

Phase 4 cho BA một pipeline lặp lại được cho *một* ticket: Intake → Ground → Draft → Pin → Lint → review. Nhưng không có artifact nào ở thượng nguồn. Với feature lớn, BA phải ôm cả epic trong đầu, chẻ thành User Story bằng trực giác, và ground lại từ đầu cho từng ticket — không có gì ghi lại *tại sao* lại chẻ như vậy, feature nằm trong bối cảnh hệ thống nào, đụng tới container nào.

Hệ quả đoán trước được: từng ticket lint PASS riêng lẻ nhưng gộp lại thì thiếu một lát cắt, trùng phạm vi, hoặc mâu thuẫn nhau về ranh giới hệ thống. Trong repo không có gì nói bảy ticket này là một feature.

Phase 4.1 bổ sung artifact thượng nguồn đó và làm cho liên kết epic→story kiểm được bằng máy. Không xây engine mới: mọi thứ tái dùng `kbcontext` + `resolve` + `doctor.check_context`, đúng cách `ticketlint.py` đang làm.

## 2. Mục tiêu

- BA chạy `/ba-mission-plan` cho một feature lớn và tạo ra tài liệu mission chuẩn dưới `missions/`: mục tiêu nghiệp vụ, phạm vi, diagram C4 L1 + L2, ràng buộc, US backlog, và một khối `kb-context` đã pin.
- Mọi claim đụng chuẩn ngành trong mission mang citation `doc-id §section` resolve được tại hub commit đã pin — cùng kỷ luật với ticket.
- Ticket soạn từ mission mang con trỏ ngược kiểm được bằng máy, và bảng backlog của mission không thể mục âm thầm.
- BA vẫn viết ticket độc lập cho việc nhỏ. Mission chỉ dành cho feature lớn; không có gì trở thành bắt buộc.
- Giữ human-in-the-loop: agent không tự sinh file ticket từ backlog, không tự chọn giữa các kết quả search sát điểm nhau, không bịa cấu trúc hệ thống mà nó không ground được.

Không thuộc phạm vi: C4 Level 4 (Code); C4 Level 3 ground theo code (cần code-knowledge của Phase 5 — ở đây L3 là tùy chọn và do BA cung cấp); tích hợp Jira REST; mọi thay đổi lên bốn MCP tool lõi; mọi thay đổi lên `ticket.REQUIRED_HEADINGS`.

## 3. Ràng buộc kiến trúc

1. **Bốn MCP tool lõi không đổi** (`kb_search`, `kb_get_section`, `kb_context_new`, `kb_resolve`). Phase 4.1 thêm **không** tool nào — số lượng giữ nguyên 5 (§9).
2. **Hub là nguồn đọc duy nhất.** Mission lint resolve ref qua hub federation đúng như `kb doctor --context` (tái dùng `doctor.check_context` → `resolve.resolve_refs`).
3. **`ticket.REQUIRED_HEADINGS` không được đổi.** Đây là hợp đồng tương thích giữa bản cài local của BA, MCP server dùng chung, và CI (Phase 4 spec §3.6); đổi nó là breaking change. Vì vậy liên kết ticket→mission mang bằng một dòng blockquote *tùy chọn*, không phải heading mới (§4.4).
4. **Luật citation kế thừa từ kb-summarize**: mã, tên record/field, số, §ref giữ nguyên văn; không suy diễn ngoài nguồn; không chắc → cite và gắn cờ, tuyệt đối không bịa.
5. **Một nội dung, một nguồn**: danh sách heading bắt buộc nằm ở một hằng số Python duy nhất; template ship kèm và các skill wrapper không được trôi khỏi nó (test đồng bộ).
6. **`REQUIRED_MISSION_HEADINGS` mang cùng kỷ luật version** như đối tác bên ticket: nó là hợp đồng xuyên local install / server dùng chung / CI, nên đổi nó là breaking change — chỉ release minor/major, bắt buộc có changelog.
7. **Tương thích ngược ngay từ thiết kế.** Ticket cũ, repo BA đang chạy, và MCP client đang kết nối đều tiếp tục chạy, không cần bước migrate nào (§11).

## 4. Thành phần A — hợp đồng tài liệu mission

### 4.1 Định danh và bố cục file

Một quy tắc suy ra được bằng máy, để lint không cần cấu hình:

| Thứ | Dạng | Ví dụ |
|---|---|---|
| Mission id | `M-<slug>` | `M-airspace-filter` |
| File mission | `missions/<mission-id>.md` | `missions/M-airspace-filter.md` |
| US id | `<mission-id>-US<n>` | `M-airspace-filter-US1` |
| File ticket | `tickets/<us-id>.md` | `tickets/M-airspace-filter-US1.md` |

`<slug>` là kebab-case thường, do BA chọn lúc intake. `<n>` là số nguyên dương, agent đánh tuần tự và BA duyệt. **Cho phép có lỗ hổng** — một story bị bỏ lúc review thì số của nó nghỉ hưu, thay vì buộc đánh số lại làm gãy tên file của các ticket đã soạn. Vì vậy check 7 kiểm dạng và tính duy nhất, không bao giờ kiểm tính liên tục.

ID **cục bộ theo repo**. Jira chỉ cấp key của nó khi BA dán ticket vào, nên key Jira không bao giờ có thể là định danh mà một mission viết *trước đó* tham chiếu tới. Ticket có thể ghi `Jira: PROJ-123` cho người đọc tiện; dòng đó **không** thuộc hợp đồng lint nào.

Mission id xuất hiện **bên trong tài liệu**, không chỉ ở tên file, vì lint còn chạy qua stdin nơi không có tên file:

```markdown
# Lọc và hiển thị vùng trời có kiểm soát

> Mission: M-airspace-filter
```

Khi lint một file thật, phần thân tên file phải bằng mission id đã khai — lệch là error, vì nếu không thì mọi US id và đường dẫn ticket suy ra đều sai.

### 4.2 Cấu trúc bắt buộc

`REQUIRED_MISSION_HEADINGS`, hằng số trong module mới `mission.py`. Heading tiếng Anh cố định (hợp đồng lint); ngôn ngữ phần thân theo ngôn ngữ làm việc của BA.

```markdown
# <Tiêu đề mission — một dòng, thể mệnh lệnh>

> Mission: M-<slug>

## Summary
<1–2 dòng: feature này là gì, ở mức epic>

## Business goal
<vì sao tồn tại và đo thành công thế nào; cite `doc-id §section` cho claim đụng chuẩn>

## Scope
**In scope:** …
**Out of scope:** …

## System context (C4 L1)
```mermaid
C4Context
  …
```

## Containers (C4 L2)
```mermaid
C4Container
  …
```

## Constraints & assumptions
<ràng buộc, câu hỏi mở, và mọi placeholder `%%TODO: verify against codebase%%`>

## US backlog
| US ID | Title |
|---|---|
| M-<slug>-US1 | … |
| M-<slug>-US2 | … |

## KB context
```yaml
kb-context:
  version: "<hub commit>"
  refs:
    - <repo:doc-id §section>
  tags: [ … ]
```

## Definition of Ready
- [ ] Có business goal, scope, diagram L1 + L2, backlog
- [ ] Mọi citation resolve tại version đã pin (kb mission lint PASS)
- [ ] Backlog đã review với team; không có lát cắt thiếu nào đã biết
```

`## Components (C4 L3)` **cố ý không bắt buộc**. Khi có, lint kiểm nó như các section diagram khác; khi không có, không có gì nổ. Phase 4 spec §12 hoãn diagram ground theo code sang Phase 5, nên L3 ở đây chỉ vẽ từ kiến thức component do BA cung cấp trực tiếp.

### 4.3 Bảng US backlog — không có cột status

Chỉ hai cột. Cột status ghi tay sẽ mục ngay khi một ticket được viết mà không ai sửa lại mission. Thay vào đó `kb mission lint` **tính** coverage từ filesystem — `tickets/<us-id>.md` có tồn tại không? — và báo dạng warning (`3/7 US đã soạn`). Trạng thái suy ra được thì không thể cũ.

### 4.4 Liên kết ngược phía ticket

Một dòng blockquote tùy chọn, ngay dưới H1 của ticket:

```markdown
# Lọc vùng trời theo lớp ARINC 424

> Parent mission: M-airspace-filter
```

Tùy chọn là chủ ý. `ticket.REQUIRED_HEADINGS` không bị đụng, nên mọi ticket đang có vẫn lint PASS mà không cần sửa gì. Khi dòng này *có* mặt, `kb ticket lint` bật thêm một check (§5.2).

## 5. Thành phần B — lint

### 5.1 `kb mission lint`

Typer sub-app mới `kb mission`, gương của `kb ticket`:

```
kb mission lint <file|-> [--kb-dir .kb] [--hub <url|path>] [--json]
```

Engine đặt ở module mới `missionlint.py`. Các check, theo thứ tự:

| # | Check | Mức |
|---|---|---|
| 1 | Có H1 title; có `> Mission: <id>` đúng dạng; nếu là file thật thì thân tên file bằng id | error |
| 2 | Đủ `REQUIRED_MISSION_HEADINGS` | error |
| 3 | `## System context (C4 L1)` chứa fence ```` ```mermaid ```` có **token đầu tiên** là `C4Context` **hoặc** `flowchart` | error |
| 4 | `## Containers (C4 L2)` chứa fence có token đầu là `C4Container` **hoặc** `flowchart` | error |
| 5 | `## Components (C4 L3)` — chỉ khi section tồn tại: token đầu là `C4Component` **hoặc** `flowchart` | error |
| 6 | `## US backlog` parse thành bảng pipe có đúng dòng header `\| US ID \| Title \|` và ≥ 1 dòng dữ liệu | error |
| 7 | Mọi US id khớp `^<mission-id>-US\d+$`; không trùng | error |
| 8 | Khối `kb-context` parse được (`kbcontext.parse`) | error |
| 9 | Mọi ref resolve tại version đã pin (`doctor.check_context`) | error (hỏng) / warning (cũ) |
| 10 | Mọi inline citation trong body có mặt trong `kb-context.refs` | error |
| 11 | Mọi ref đã pin được cite ít nhất một lần trong body | warning |
| 12 | Coverage: US id chưa có `tickets/<us-id>.md` | warning |
| 13 | Còn sót placeholder `%%TODO: verify against codebase%%` | warning |

Exit code 1 nếu có error, ngược lại 0. `--json` xuất `{"pass": bool, "errors": [...], "warnings": [...], "notes": [...]}`.

Check 3–5 nhận cả cú pháp C4 gốc lẫn `flowchart`. Tài liệu chính thức của Mermaid ghi rõ C4 là diagram type thử nghiệm và "syntax and properties are subject to change in future releases". Buộc một hợp đồng lint hạng breaking-change vào cú pháp thử nghiệm của upstream nghĩa là một bản release Mermaid có thể làm gãy DoR gate của mọi team. Mục đích của check là *ở mức này có một diagram*, không phải *diagram này đúng cú pháp C4* — nên hợp đồng lỏng hơn cũng là hợp đồng trung thực hơn. Template ship dùng C4 gốc; team nào renderer không đỡ C4 thì lui về `flowchart` mà không FAIL DoR.

Check 12 cần truy cập filesystem, thứ mà stdin và mọi caller không-phải-file đều không có. Chữ ký:

```python
lint(text: str, hub: "HubHandle | None", *, tickets_dir: Path | None) -> LintReport
```

Khi `tickets_dir is None`, check 12 bị bỏ **và phát ra một note nói rõ điều đó**. Một check bị bỏ không bao giờ được phép trông giống một check đã pass.

### 5.2 Thêm đúng một check cho `kb ticket lint`

| # | Check | Mức |
|---|---|---|
| 10 | Khi có `> Parent mission: <id>`: id đúng dạng; `missions/<id>.md` tồn tại; US id của chính ticket có trong bảng backlog của mission đó | error |

Cùng quy tắc suy giảm: không có đường dẫn repo thì check rút về phần kiểm dạng, và report mang note nói phần còn lại đã bị bỏ. Điều này làm MCP tool thứ năm `kb_ticket_lint` *đang tồn tại* yếu hơn CLI — chính cái note giữ cho việc đó hiển thị ra, thay vì ngầm hiểu.

### 5.3 Bố cục module

`ticketlint.py` dài 276 dòng với các hàm check private tách sạch, phần lớn dùng nguyên si được cho mission. Phần logic dùng chung dời sang một module có tên đúng, thay vì import xuyên qua ranh giới private.

| Module | Nội dung |
|---|---|
| `mission.py` (mới) | `REQUIRED_MISSION_HEADINGS`, `MISSION_ID_RE`, `US_ID_RE`, regex bảng backlog |
| `lintcore.py` (mới, rút ra) | `LintReport`, `_section_body`, `_check_title`, `_check_headings(text, required)`, `_check_diagram(text, heading, keywords)`, `_strip_bare_kb_context`, `_citation_scan_text`, `_cite_matches_ref`, `_check_citation_consistency`, lớp bọc `doctor.check_context` |
| `ticketlint.py` (mỏng đi) | `_check_story`, `_check_ac_present`, `_check_ac_citations`, check parent-mission mới, `lint()` |
| `missionlint.py` (mới) | `_check_backlog`, `_check_coverage`, `_check_placeholders`, `lint()` |
| `ticket.py` | thêm `PARENT_MISSION_RE`. `REQUIRED_HEADINGS` **không đổi** |

`_check_diagram` đổi tham số `keyword: str` thành tuple các keyword được nhận. Việc rút module giữ nguyên hành vi; điều kiện nghiệm thu là bộ test `tests/test_ticketlint.py` hiện có pass nguyên vẹn (§10).

## 6. Thành phần C — skill `ba-mission-plan` + wrapper

Bốn wrapper mỏng, cùng khuôn bố cục file như `ba-ticket-author`, đăng ký trong `BA_TEMPLATES` và chỉ scaffold trên kind `ba`. Skill Claude là bộ điều phối.

Workflow — bảy bước, nhiều hơn pipeline ticket một bước:

1. **Intake** — nhu cầu nghiệp vụ ở mức epic, tags hoặc doc mục tiêu, và slug mission chốt với BA. Hỏi, không đoán.
2. **Ground** — `kb_search` trong budget. Trình **toàn bộ** candidate trả về kèm citation. Nếu note ambiguity nổ, BA chọn — không bao giờ tự quyết.
3. **Draft** — điền template. C4 L1 và L2 dựng từ nội dung KB cộng với lời BA nói. Thứ gì cần cấu trúc code (tên service, tên bảng database) thì thành `%%TODO: verify against codebase%%` chứ không phải một phát minh. L3 chỉ khi BA cung cấp kiến thức component thật.
4. **Chẻ backlog** — đề xuất danh sách US, BA sửa và duyệt. Agent đánh id tuần tự theo §4.1.
5. **Pin** — `kb_context_new(refs đã confirm, tags)` → nhúng vào `## KB context`.
6. **Lint** — `kb mission lint`. Sửa error, chạy lại tới PASS, báo cáo warning. **Coverage 0/N lúc mới tạo là bình thường** và không được coi là thất bại.
7. **Review → save** — ghi `missions/M-<slug>.md`; BA review và commit.

Khối hard rules, nguyên văn trong cả bốn wrapper:

- Citation bắt buộc cho claim đụng chuẩn — không citation, không claim.
- Không bao giờ bịa mã, giá trị, tên service, tên bảng. Không chắc → `%%TODO%%`.
- Present-and-confirm trước khi pin.
- Lint FAIL là blocker. **`kb` chạy không được không phải là PASS** — báo BA cài; tuyệt đối không lặng lẽ bỏ bước lint.
- Output của agent là bản nháp; BA publish.
- **Không bao giờ tự sinh file ticket từ backlog.** Mỗi US phải qua `ba-ticket-author` với vòng grounding riêng của nó.

## 7. Thành phần D — `ba-ticket-author` thêm bước mission

Khi BA nêu tên mission cha, skill ticket đọc `missions/<id>.md`, lấy tiêu đề US từ dòng backlog, và điền dòng `> Parent mission:`.

Nó dùng các ref đã pin của mission làm **candidate khởi đầu mà thôi**. Nó không được chép nguyên `kb-context` của mission sang ticket: mission thì rộng còn ticket thì hẹp, nên chép nguyên sẽ kéo theo những ref mà ticket không bao giờ cite và làm check 11 tràn warning. Ticket pin bộ ref của riêng nó, confirm lại từ đầu.

## 8. Thành phần E — scaffolding và CI

### 8.1 Bổ sung vào `BA_TEMPLATES`

| Đường dẫn | Template nguồn |
|---|---|
| `.claude/skills/ba-mission-plan/SKILL.md` | `claude-skill-ba-mission-plan.md` |
| `.claude/commands/ba-mission-plan.md` | `claude-command-ba-mission-plan.md` |
| `.github/prompts/ba-mission-plan.prompt.md` | `copilot-ba-mission-plan.prompt.md` |
| `.cursor/commands/ba-mission-plan.md` | `cursor-ba-mission-plan.md` |
| `docs/missions/TEMPLATE.md` | `mission-template.md` |
| `missions/.gitkeep` | `gitkeep.txt` |

`tickets-gitkeep.txt` đổi tên thành `gitkeep.txt` và cả hai entry trỏ chung — tên resource nội bộ, người dùng không thấy tác động. Không thêm gì vào scaffold hub hay child.

### 8.2 CI gate — mở rộng, không đổi tên

`kb-ticket-lint.yml` mở rộng để phủ cả hai thư mục:

- `paths: ["tickets/**.md", "missions/**.md"]`
- Với mỗi file thay đổi, phân nhánh theo thư mục: `tickets/` → `kb ticket lint`, `missions/` → `kb mission lint`. Bất kỳ FAIL nào cũng làm job fail.

**Tên file workflow và tên job giữ nguyên chính xác như hiện tại**, dù `kb-ticket-lint` giờ mô tả thiếu việc nó làm. Branch protection trên các repo BA đã dựng khoá theo tên job; đổi tên sẽ để những repo đó chờ vĩnh viễn một required check không bao giờ chạy lại nữa. Rủi ro vận hành đó nặng hơn sự chính xác về tên gọi.

Checkout đầy đủ cho CI cả `tickets/` lẫn `missions/`, nên check 12 và check 10 phía ticket chạy đủ sức ở đó — CI là ngữ cảnh lint mạnh nhất trong ba ngữ cảnh.

## 9. Quyết định — không có MCP tool `kb_mission_lint`

Nước đi đối xứng sẽ là một MCP tool thứ sáu gương của `kb_ticket_lint`. Cố ý **không** làm:

- Giá trị riêng của mission lint so với ticket lint nằm chính xác ở các check traceability (số 12, và số 10 phía ticket), và những check đó cần truy cập filesystem mà MCP server dùng chung không có. Một `kb_mission_lint` qua MCP sẽ là bản sao suy giảm hoàn toàn của CLI.
- Phase 4 spec §12 đã chốt mọi BA làm việc bên trong repo requirement — persona chat-only vốn sẽ cần lint không-shell đã bị bỏ. Không còn ai để phục vụ.
- Mỗi tool đăng ký tốn context trong mọi agent kết nối, và làm loãng bất biến "core four không đổi".

Cái giá chấp nhận: có `kb_ticket_lint` mà không có `kb_mission_lint` là bất đối xứng và trông lệch trên danh sách tool. Ghi lại ở đây để lý do không mất. Quyết định đảo ngược được với chi phí bằng không — thêm tool sau này thuần túy là cộng thêm.

Hệ quả phải xử lý dù thế nào: skill `ba-mission-plan` không có MCP fallback cho bước lint, đó là lý do "`kb` chạy không được không phải là PASS" là một hard rule tường minh (§6).

## 10. Test (hermetic — không hub thật, không LLM; fixture `git_kb`)

- `tests/test_missionlint.py` — một mission golden PASS; mỗi check 1–13 một mutation, assert đúng mức và mảnh message; một mission golden thân tiếng Việt (UTF-8 + `§`); dạng `--json`; **cả fence `C4Container` lẫn `flowchart` đều PASS** check 3–5; `tickets_dir=None` bỏ check 12 **và phát note**.
- `tests/test_ticketlint.py` — check 10 mới: parent mission hợp lệ / thiếu file mission / US id không có trong backlog / không có đường dẫn repo → note. Cộng một assert rằng `REQUIRED_HEADINGS` không đổi, canh hợp đồng breaking-change.
- **Rút `lintcore`: toàn bộ bộ test `tests/test_ticketlint.py` hiện có phải pass nguyên vẹn, trước và sau.** Đây là điều kiện nghiệm thu của việc refactor, không phải một test mới.
- `tests/test_cli_mission.py` — exit code, stdin (`-`), `--json`.
- Test MCP — assert đúng **5 tool** và không có `kb_mission_lint`; snapshot chữ ký core-four không đổi.
- `tests/test_init.py` — kind `ba` scaffold đúng bộ bổ sung §8.1; hub/child không nhận gì (assert absence); workflow chứa cả hai path filter và không hardcode secret.
- Test đồng bộ template — `REQUIRED_MISSION_HEADINGS` ⊆ `mission-template.md`; cả bốn wrapper tham chiếu cùng bộ heading. Cùng khuôn với test đồng bộ ticket hiện có.

Xử lý lỗi: bảng backlog không parse được thì báo đúng dòng hỏng chứ không nuốt; thiếu `missions/<id>.md` ở check 10 phía ticket là error, không phải crash; hub không tới được thì kế thừa nguyên hành vi `kb doctor --context`; UTF-8 xuyên suốt qua `utf8io`.

## 11. Tương thích và triển khai

Không cần bước migrate nào:

- `ticket.REQUIRED_HEADINGS` không đổi → mọi ticket đang có vẫn lint PASS.
- `> Parent mission:` là tùy chọn → repo BA đã dựng tiếp tục chạy, không đụng gì.
- Không thêm/bớt MCP tool → client đang kết nối không thấy thay đổi.
- Bump version: **minor** (0.13.0). Phase 4 spec §3.6 chỉ xếp việc đổi `REQUIRED_HEADINGS` là breaking; đây là cộng thêm.

Lưu ý vận hành cho repo BA đã dựng: chạy lại `kb init --kind ba` để lấy template mới. Theo `initcmd.py:193–204`, mọi file **không** nằm trong `PROTECTED_FILES` sẽ bị ghi đè khi nội dung khác — nên `kb-ticket-lint.yml` và bốn wrapper `ba-ticket-author` được refresh, đúng chủ ý, **nhưng team nào sửa tay một wrapper sẽ mất phần sửa đó**. Đây là hành vi init có sẵn, không phải thứ mới đưa vào; QUICKSTART-BA phải ghi rõ một dòng.

## 12. Tài liệu

- QUICKSTART-BA: luồng mission, và hướng dẫn khi nào cần mission (feature lớn trải nhiều story) so với viết ticket độc lập (việc nhỏ). Cộng cảnh báo ghi đè khi re-init ở §11.
- README: mở rộng mục Phase 4 với mission plan, lệnh mới, và quan hệ mission→ticket.
- Tài liệu kiến trúc: task riêng sau khi implement — `kb ticket lint` không còn là DoR gate duy nhất; số MCP tool giữ nguyên 5.

## 13. Nhật ký quyết định

| Quyết định | Lựa chọn |
|---|---|
| Quan hệ mission↔ticket | Mission sinh US backlog; ticket trỏ ngược lên nó (28/07/2026). Đã loại: mission là artifact độc lập không có liên kết bắt buộc; mission là section thêm bên trong một ticket lớn (phá nguyên tắc một-ticket-một-story) |
| Độ sâu C4 | L1 + L2 bắt buộc; L3 tùy chọn và do BA cung cấp; L4 ngoài phạm vi. Đoán L3/L4 sẽ vi phạm chính luật never-fabricate của skill |
| Đóng gói skill | Skill riêng `ba-mission-plan` với bốn wrapper riêng. Tên lệnh *chính là* bộ chọn mode — rõ hơn phân nhánh bên trong một orchestrator dài, và hai luồng có hai hợp đồng heading khác nhau |
| Chỗ chặn traceability | Ở hạ nguồn, tại ticket lint, nơi cả hai artifact đều tồn tại. Chặn ở mission lint sẽ làm mọi mission vừa viết đều FAIL và đảo ngược thứ tự tác nghiệp |
| Theo dõi trạng thái backlog | Không có cột status; coverage suy ra từ filesystem nên không thể mục |
| Định danh US | ID cục bộ theo repo (`M-<slug>-US<n>`). Key Jira không dùng được — Jira chỉ cấp sau khi BA dán ticket, rất lâu sau khi mission đã viết |
| Cú pháp Mermaid C4 | Lint nhận C4 gốc **hoặc** `flowchart`; template ship bản C4 gốc. Mermaid ghi rõ C4 là thử nghiệm với cú pháp có thể đổi; một DoR gate không được làm con tin cho việc đó |
| Cơ chế liên kết ngược phía ticket | Blockquote tùy chọn dưới H1, không phải heading bắt buộc mới — giữ nguyên `REQUIRED_HEADINGS` và do đó giữ nguyên mọi ticket đang có |
| Vị trí engine lint | Rút `lintcore.py`; thêm `missionlint.py`. Đã loại: import hàm private của `ticketlint` (ghép nối ngầm), và một module với tham số `kind` (một file gánh hai hợp đồng heading) |
| MCP tool | Không thêm — xem §9. Số lượng giữ 5 |
| CI gate | Mở rộng `kb-ticket-lint.yml` sang cả hai thư mục; đóng băng tên file và tên job để bảo vệ branch protection đang có |
| Check bị bỏ | Luôn báo dạng note. Một check không chạy được tuyệt đối không được đọc thành một check đã pass |
