# 1. Tài liệu này dành cho ai

Bạn viết code sản phẩm. Ticket đến tay bạn đã được bám vào cơ sở tri thức của tổ
chức, kèm trích dẫn ghim vào một phiên bản cụ thể của một tài liệu cụ thể, và bạn
hiện thực chúng.

Strata làm hai việc cho bạn.

**Nó cho bạn biết bản gốc thực sự nói gì.** Không phải "xem sổ tay đi" — mà là
đúng section đó, ở đúng phiên bản mà người viết yêu cầu đã đọc, kèm cảnh báo nếu
nó đã thay đổi kể từ đó.

**Nó publish ra codebase của bạn là gì**, để mọi người khác — BA vẽ sơ đồ kiến
trúc, nhóm khác, chính bạn trong tương lai — tìm được service, dependency,
endpoint và schema của bạn mà không phải đọc repository.

## 1.1 Repo dev làm gì và không làm gì

| Có làm | Không làm |
|---|---|
| Đọc tri thức đã publish trên hub, gồm cả ticket BA đã publish | Ingest tài liệu từ bên ngoài repo |
| Publish tri thức về **chính code của nó** | Publish tri thức nghiệp vụ |
| Chạy quy trình hiện thực gồm năm lệnh | Tự merge hay tự ship bất cứ thứ gì |

Ranh giới này là có chủ đích. Repo `child` đưa tài liệu bên ngoài vào; repo `dev`
không ingest gì cả và chỉ soạn tri thức về chính nó. Chính điều đó làm cho việc
CI của bạn publish liên tục trở nên an toàn.

## 1.2 Hai tài liệu mà repo của bạn publish

| Tài liệu | Nguồn gốc | Sinh lại | Cần review |
|---|---|---|---|
| `<repo_id>-code` | `kb code-ingest` — tất định, không model | khi cần, từ working tree — không bao giờ commit; CI publish khi `kb publish` push một tag `kb-publish/*` | không |
| `<repo_id>-svc` | model soạn từ bằng chứng đó, bạn sửa lại | không bao giờ | luôn luôn |

`-code` là sự thật máy móc: tên service, công nghệ, dependency, lệnh, endpoint,
schema, cấu trúc thư mục. `-svc` là khẳng định của con người: mỗi service thực sự
*chịu trách nhiệm* về cái gì.

Chúng nối nhau bằng id section — `svc.<name>` tồn tại ở cả hai — nên một BA vẽ
container C4 lấy alias, nhãn và công nghệ từ `-code`, còn phần mô tả từ `-svc`.

---

# 2. Thiết lập một lần

```bash
pip install "strata-kb[code]"
kb init --kind dev
```

Extra `code` (`tree-sitter` cùng `tree-sitter-language-pack`, khoảng 184 MB) là
thứ cho phép `kb code-ingest` đọc route, page, job và symbol từ mã nguồn (§7.5).
Thiếu nó, route và symbol (cùng page, trừ router theo file hệ thống) được báo là
`not scanned`, job vẫn là `partial`, và SA sẽ hỏi bạn. `kb doctor`
cảnh báo khi thiếu, và `kb-code.yml` cài nó trong CI.

## 2.1 Cấu hình

```yaml
# .kb/config.yaml
kind: dev
repo_id: payments
hub: https://github.com/acme/kb-hub.git
intake: https://kb-intake.acme.com
```

- **`hub`** là nguồn đọc duy nhất cho `kb query`, `kb get`, `kb resolve` và MCP.
- **`intake`** là cách CI publish. Hãy đề nghị người quản trị hub thêm repository
  này vào mục `repos:` trong `federation/registry.yaml` của hub — publish sẽ bị
  từ chối cho tới khi họ làm việc đó.

Nếu KB cần mang schema SQLite, hoặc tag index bổ sung, hãy khai báo ở đây —
không phải trong `kb-code.yml` — để mọi lượt refresh cục bộ và CI ingest theo
cùng một cách:

```yaml
code_ingest:
  db: [data/app.sqlite]   # phải tường minh
  tags: [payments]
```

## 2.2 Nối trợ lý của bạn

`.mcp.json` (Claude Code) và `.cursor/mcp.json` (Cursor) đã được scaffold sẵn,
nối tới các công cụ MCP của hub — nhưng qua placeholder,
`${STRATA_KB_HUB_URL}` và `${STRATA_KB_HTTP_TOKEN}`, mà chưa ai điền giá trị.

Chạy `kb mcp-setup` (trong trợ lý: `/kb-mcp-setup`). Lệnh này hỏi URL HTTP cơ
sở và token của hub, ghi cả hai vào `.env`, đảm bảo git bỏ qua file đó, rồi
xác minh chúng với hub, để một URL sai và một token bị từ chối trả về hai lỗi
khác nhau:

| Biến | Ví dụ |
|---|---|
| `STRATA_KB_HUB_URL` | `http://kb-hub.example.com:8321` |
| `STRATA_KB_HTTP_TOKEN` | bearer token của hub |

Chạy lại một lần nữa (không kèm gì) sẽ xác minh lại mà không cần nhập lại
token. Nên dùng prompt ẩn hoặc biến môi trường `STRATA_KB_HTTP_TOKEN` thay vì
cờ `--token` — cờ đó để lại token trong lịch sử shell của bạn.

`.mcp.json` và `.cursor/mcp.json` đọc hai biến đó từ môi trường tiến trình,
không đọc trực tiếp từ `.env`, nên hãy nạp `.env` vào shell của bạn
(`set -a; source .env; set +a`, hoặc dùng direnv) rồi khởi động lại trợ lý —
MCP chỉ đọc môi trường lúc khởi động.

## 2.3 Bật cổng PR

`kb init` ghi ra `.github/workflows/kb-pr-lint.yml` nhưng không bật được branch
protection thay bạn. Hãy thêm **`pr-lint` vào danh sách check bắt buộc** của
nhánh.

> Hãy quyết định điều này một cách có ý thức. Khác với cổng của repo BA, cổng này
> không bao giờ tự bỏ qua. Một khi đã bắt buộc, nó chặn **mọi** pull request
> thiếu các mục bắt buộc — kể cả pull request của bot như nâng cấp dependency
> hay revert.

## 2.4 Hỏi hub có auto-merge repo của bạn không

Auto-merge là công tắc theo từng repo trên trang Registry của hub; admin hub bật
nó cho repo của bạn. Hãy hỏi người quản trị hub xem nó đã bật chưa, và hiểu nó làm
gì:

> `kb ci-publish` mở **một** pull request trên hub cho mỗi lần push, không phải
> mỗi tài liệu một cái. Intake gắn nhánh publish theo id repository và dùng lại
> nhánh đó trong khi PR còn mở — nên một lần push mang theo `-code` vừa sinh lại
> cùng với một sửa đổi `-svc` đã merge sẽ đưa **cả hai** vào cùng PR đó.
>
> Khi công tắc bật, hub merge **cả** PR ngay sau khi mở, kể cả nội dung `-svc`.
> Vì vậy việc review `-svc` diễn ra tại máy, ở bước 4 của `/dev-code-seed`, trước
> khi section lên `reviewed` — không bao giờ ở hub.

Nếu merge thất bại, PR vẫn mở cho người quản trị hub và publish vẫn tính là xong.
`kb publish` và `kb ci-publish` in "merged" khi đã merge (bản tóm tắt bước CI vẫn hiện `hub PR: <url>`). Khi công tắc bật, hub
không bị tụt lại so với main: thiếu nó, mỗi lần push sẽ dồn vào một PR hub đang
chờ mà ai đó phải merge tay. `kb doctor` báo khi `-code` trên hub bị tụt lại.

---

# 3. Đưa một dự án đang chạy vào hệ thống

Repository của bạn đã có các service đang làm việc thật. Áp dụng Strata không
nên có nghĩa là phải viết tài liệu hệ thống từ trang giấy trắng, nên có một bước
seed chạy một lần.

```bash
/dev-code-seed
```

Bảy bước:

| # | Bước | Ai làm |
|---|---|---|
| 1 | **Preflight** — xác nhận đã có `hub:`, `repo_id:` và `intake:`, và repo đã được cho phép trên hub; cảnh báo nếu cây làm việc chưa sạch | agent |
| 2 | **Extract** — `kb code-ingest --scaffold-svc` sinh lại `-code` và tạo khung `svc.<name>` ở trạng thái `pending` cho mỗi service phát hiện được, kèm bằng chứng code tất định | agent |
| 3 | **Draft** — `kb summarize <repo_id>-svc` viết đoạn mô tả trách nhiệm cho từng section từ bằng chứng đó | agent |
| 4 | **Review** — rà từng section đã soạn, đối chiếu với bằng chứng, và sửa lại | **bạn** |
| 5 | **Approve** — `kb approve <repo_id>-svc` chuyển các section đã sửa sang `reviewed` | bạn |
| 6 | **Flows** (tuỳ chọn) — thêm section `flow.<name>` cho các luồng nghiệp vụ đi qua nhiều service | bạn |
| 7 | **Validate và publish** — `kb build` không kèm `--allow-pending`, rồi `kb publish --pr` | bạn |

## 3.1 Bước 4 mới là phần việc thật

> **Bản nháp của model là bản nháp, không phải sự thật.** Nó có thể gọi sai
> luồng, bỏ sót một trách nhiệm, hoặc thổi phồng một trách nhiệm. Duyệt một
> section mà bạn chưa đọc là phá hỏng toàn bộ ý nghĩa của cái cổng này.

Hãy đọc phần tóm tắt của từng section `svc.*` bên cạnh bằng chứng code của nó và
sửa lại. Ở chỗ nào trách nhiệm chạm tới một tiêu chuẩn nghiệp vụ, hãy trích dẫn
`doc-id §section` từ hub thay vì diễn đạt lại quy tắc bằng lời của bạn.

**Hãy dự trù 10–15 phút cho mỗi service.** Đó là chi phí thật, và là chi phí một
lần. Sau khi seed xong, `-code` tự sinh lại còn `-svc` tích luỹ dần từng vài
dòng.

Với bước 6, cứ bỏ qua thoải mái. Thiếu một luồng vẫn tốt hơn một luồng đoán mò.

## 3.2 Vì sao lần publish đầu phải `--pr` thủ công

Bước seed diễn ra *trước khi* có bất cứ thứ gì merge vào nhánh mặc định, nên
không có lần push nào để `kb-code.yml` phản ứng.

Hãy dùng `kb publish --pr`. Lệnh `kb publish` thường sẽ gắn tag vào commit rồi
hỏi dò intake tới mười phút, chờ một lượt CI kích hoạt bằng tag mà repository này
không hề có, rồi báo lỗi gây hiểu nhầm.

Pull request đó trên hub được một BA hoặc kiến trúc sư review, như mọi nội dung
khác trên hub — trừ khi hub đã bật auto-merge cho repo của bạn: khi đó hub merge nó ở
lượt publish qua intake kế tiếp của repo (bản thân `kb publish --pr` không đi qua
intake); lượt review `-svc` bạn làm ở bước 4 là lượt duy nhất.

---

# 4. Hiện thực một ticket

Năm lệnh, được dựng sẵn cho Claude Code, GitHub Copilot và Cursor.

```
/dev-implement-ticket <ticket>     intake · check · resolve · ground · placeholders
        │
        ├─► dev-design       ── A1: reviewer độc lập ── GATE 1: bạn duyệt thiết kế
        ├─► dev-plan         ── A2: reviewer độc lập ── GATE 2: bạn duyệt kế hoạch
        ├─► dev-execute         A3 mỗi task · A4 cuối nhánh  (lặp lại được, tiếp tục được)
        └─► dev-handover     ── A5: merge-risk review ── GATE 3: bạn mở PR
                                GATE 4: bạn merge
```

`/dev-implement-ticket` cũng là bộ điều phối: với một ticket mới, nó chạy năm
bước đầu rồi gọi các pha theo thứ tự, tự phát hiện ticket đã đi tới đâu nên không
bao giờ làm lại phần đã xong.

## 4.1 Chỉ cần id ticket là đủ

Chỉ đưa cho trợ lý một id ticket (`M-<slug>-US<n>`, hoặc một tên ticket trơn).
Intake lấy ticket **từ hub trước**: BA publish mọi ticket đã sẵn sàng trong tài
liệu `<repo_id>-plan`, nên hub là nguồn sự thật.

```bash
kb ticket fetch M-checkout-US3          # hoặc <repo>:<id> nếu nhiều repo cùng có
```

- Lệnh tìm repo federation duy nhất có tài liệu `*-plan` chứa section đó. Nếu không
  có, nó thoát `1`: ticket chưa được publish, hãy nhờ BA `kb publish`, hoặc đưa
  đường dẫn hay dán nội dung. Nếu có nhiều repo, nó thoát `1` và nêu tên chúng;
  hãy viết id dạng `<repo>:<id>`.
- Nó ghi `docs/impl/<id>/ticket.md` (`--out` để đổi) gồm tiêu đề, một dòng nguồn gốc
  và nội dung ticket:
  `> Fetched from hub: <repo>:<doc> §<id> @ <hub rev> — do not edit; amend in the BA repo.`
- Nó **ghi đè** file ở mỗi lần fetch. Bản sao này suy ra được từ hub, nên
  `docs/impl/.gitignore` bỏ qua `*/ticket.md`: không bao giờ commit, không bao giờ
  sửa. Nếu ticket sai, BA sửa đổi nó trong repo BA.
- Id không phải một tên trơn (đường dẫn, `..`) bị từ chối.

Khi không có CLI, trợ lý đọc section qua MCP (`kb_get_section`, `<doc> §<id>` ở mức
`l3`) và lưu theo cùng cách. Một đường dẫn hay nội dung ticket được dán vẫn dùng
được, như phương án dự phòng khi hub không có bản sao hoặc không kết nối được.

Bản trên hub **không có `## Definition of Ready`**: có mặt trên hub nghĩa là BA đã
tick mọi ô, nên không bước nào được dừng vì thiếu mục đó.

`## Sequencing` của mission cha được đọc theo cùng cách khi không có file mission
cục bộ (`kb get <doc> <M-id> --level l3`), nên bạn thấy được ticket bị chặn bởi gì
mà không cần clone repo BA.

### Kiểm tra grounding

Ngay sau Intake, luồng chạy `kb ticket check docs/impl/<id>/ticket.md` (chính là
`<ticket-file>`; bỏ qua kèm một note khi ticket không có `## Technical
grounding`). Lệnh đọc `-code` trên hub và, với `[NEW: D<n>]`, đọc mission cha từ
plan trên hub khi không có `missions/` cục bộ. Revision ở `Grounded on:` đổi theo
mỗi commit bạn merge, nên chỉ lệch revision thì không bao giờ fail:

| Output | Ý nghĩa | Việc cần làm |
|---|---|---|
| PASS, `[note] grounded @<old>, still valid at @<new> — cited sections unchanged` | Không thứ gì ticket trích bị đổi | Làm tiếp |
| PASS, `[warn] … §<id> changed; cited names still hold, review the diff:` | Một section được trích có đổi, mọi tên được trích vẫn còn | Đọc diff rồi quyết; làm tiếp trừ khi nó đổi ý nghĩa ticket |
| PASS, `[warn] some cited facts could not be verified …` | Một bước check bị bỏ qua (ví dụ giới hạn của tree) | Tự kiểm tra những fact đó |
| FAIL, `… re-run /sa-ticket-ground` | Một id, cột, route, lệnh, file hay compose fact được trích đã mất | Dừng: blocker cho BA, SA sẽ ground lại ticket |
| FAIL, kèm `[note] checked against the local -code, not the hub's copy …` | Hub không với tới được hoặc không có `-code`; branch của bạn có thể là nguyên nhân | Chạy lại khi hub với tới được và có `-code` |
| FAIL không có dòng re-ground | Một open decision hoặc `[NEW: D<k>]` chưa quyết | Báo BA và dừng |

### Trạng thái của ticket nghĩa là gì với bạn

Menu **Ticket** của hub (`/ui/tickets`) và `kb mission next --from-hub
[--repo <ba-repo>]` hiển thị mọi story của một mission đã publish là **done** (id
của nó nằm trong một dòng `hist.*` của `-svc` của bạn, do `kb svc note` ghi lúc
handover), **ready** (ticket của nó đã publish), **not ready** (chưa có ticket đã
publish) hoặc **blocked** (kèm lý do). Hãy chọn story **ready**.

Ở phía BA, `kb mission next` còn có thể báo một ticket là `draft` với lý do
`parent mission rev <M> affects this story`: mission đã được sửa sau khi ticket
được viết, và BA chưa soạn lại nó. Ticket như vậy không được publish, nên bạn thấy
story là *not ready* và `kb ticket fetch` không tìm thấy gì. Hãy đợi BA; đừng hiện
thực từ một bản cũ.

## 4.2 Chọn điểm vào

| Tình huống | Chạy |
|---|---|
| Ticket mới, chưa bắt đầu gì | `/dev-implement-ticket <ticket>` |
| Ticket nhỏ, thay đổi đã quá rõ | `/dev-implement-ticket <ticket>` — luồng tự thu gọn; thiết kế vẫn được ghi ra, chỉ là bản rút gọn |
| Thiết kế đã duyệt, chưa có kế hoạch | `/dev-plan <id>` |
| Kế hoạch đã duyệt, hoặc đang hiện thực dở | `/dev-execute <id>` |
| Code đã tự viết, cần phần mô tả PR | `/dev-handover <id>` |
| Quên mất ticket đang ở đâu | `/dev-implement-ticket <id>` |
| Bug do BA báo (`BUG-<n>`) | `/dev-fix-bug BUG-<n>` |
| Một câu hỏi kỹ thuật cần bằng chứng từ repo này và hub | `/dev-sa <câu hỏi>` |
| Chỉ muốn kiểm tra một trích dẫn | `kb resolve <file>` |

Mọi điểm vào đều kiểm tra lại độ mới của trích dẫn trước tiên. Hub có thể đã
publish kể từ phiên làm việc trước, nên một tham chiếu hôm qua còn `ok` thì hôm
nay có thể đã `stale`. Chỉ kiểm tra lúc handover thì quá muộn.

## 4.3 Công việc nằm ở đâu

| File | Do ai ghi | Mục đích |
|---|---|---|
| `docs/impl/<id>/design.md` | `dev-design` | bản thiết kế |
| `docs/impl/<id>/plan.md` | `dev-plan` | mỗi tiêu chí chấp nhận một task, dạng checkbox `- [ ]`, mỗi task một dòng `Depends on:` |
| `docs/impl/<id>/ticket.md` | `kb ticket fetch` | ticket lấy từ hub; bị gitignore, bị ghi đè ở mỗi lần fetch, không bao giờ sửa |
| `docs/impl/<id>/context.md` | `dev-implement-ticket` | cache ngữ cảnh đã phân giải; bị gitignore, sinh lại khi cần |
| `docs/impl/<id>/review/` | `dev-execute`, `dev-handover` | diff và báo cáo reviewer của từng task, diff cả nhánh, báo cáo rủi ro merge; bị gitignore, suy ra được từ git và các bảng review record dưới đây |

`kb init --kind dev` và `kb impl tidy` tự dời layout phẳng cũ
(`docs/impl/<id>-plan.md`, …) vào các folder này.

File thiết kế và kế hoạch mỗi file đều có thêm bảng `## Review record` khi các
vòng review chạy — đây là lịch sử được commit của mọi vòng, không phải một file
riêng.

Trạng thái được suy ra từ hai file đầu, nhánh git hiện tại, và việc PR đã mở hay
chưa — **không bao giờ từ lịch sử hội thoại**. Bất kỳ pha nào cũng tiếp tục được
từ đầu trong một phiên làm việc hoàn toàn mới.

`kb init` không bao giờ sửa nội dung `docs/impl/` của bạn: nó thêm `.gitkeep`
và một `.gitignore` để cache ngữ cảnh, ticket đã fetch và các artefact review không
bao giờ lọt vào pull request, và dời layout phẳng cũ vào `<id>/` — không bao giờ ghi đè.
Hãy commit các lần đổi tên.

**Wave và lane.** Mỗi task trong kế hoạch có một dòng `Depends on:` ngay dưới
tiêu đề `### Task <n>:` — `none`, hoặc các task mà nó dùng Interface hay dùng
chung file. `dev-plan` suy ra dòng này; reviewer A2 kiểm tra nó.
`kb plan waves docs/impl/<id>/plan.md` biến các dòng đó thành các wave (wave n
= các task có mọi dependency nằm ở wave trước) và fail khi hai task dùng chung
một file mà không có dependency giữa chúng, khi có vòng lặp, hoặc khi thiếu
dòng — kế hoạch như vậy không có thứ tự song song an toàn. Kế hoạch mà không
task nào có dòng này là kế hoạch có từ trước khi có wave, và chạy tuần tự.

`dev-execute` chạy lệnh này sau khi tách nhánh. Wave chỉ có một task chạy như
cũ; wave có nhiều task thì mỗi task chạy trong một lane git worktree riêng cắt
từ nhánh ticket, tối đa 3 lane cùng lúc, merge lại theo thứ tự task bằng
`--no-ff`, toàn bộ test suite chạy một lần mỗi wave. Merge conflict nghĩa là kế
hoạch sai, và được trả về `dev-plan`.

## 4.4 Bốn cổng người, năm vòng review agent

Không gì trong quy trình này merge hay ship mà không có con người.

1. **Thiết kế được duyệt** — bạn ký duyệt trước khi viết bất kỳ kế hoạch nào.
2. **Kế hoạch được duyệt** — bạn ký duyệt trước khi viết bất kỳ dòng code nào.
3. **PR được mở** — agent viết nội dung; bạn mở PR.
4. **Merge** — bạn review và merge.

Agent không tự làm hai việc cuối.

Trước mỗi cổng trong ba cổng đầu, một agent khác đã đọc lại công việc trong một
ngữ cảnh riêng — không bao giờ là chính agent đã làm ra nó:

| | Ở đâu | Nhìn cái gì |
|---|---|---|
| A1 | `dev-design`, trước GATE 1 | thiết kế có khớp ticket không |
| A2 | `dev-plan`, trước GATE 2 | kế hoạch có test-first, có chạy được không |
| A3 | `dev-execute`, mỗi task | diff của task này có đúng spec, code có tốt không |
| A4 | `dev-execute`, sau task cuối | nhánh hoàn chỉnh có làm tròn ticket không |
| A5 | `dev-handover`, trước GATE 3 | merge vào nhánh chính có an toàn không |

Tiêu chí nằm ở `docs/pr-review-rubric.md`, ghi đè bằng
`docs/pr-review-rubric.local.md`. Mỗi vòng tối đa 3 lượt fix/review. Một vòng
chỉ tính là sạch khi không còn BLOCKER và không còn SUGGESTED nào bỏ ngỏ —
NOTE và NITS chỉ được ghi lại, không bị bắt sửa — và một BLOCKER hoặc SUGGESTED
còn đứng sau lượt 3 sẽ dừng luồng và chuyển cho bạn.

Ở nơi runtime của trợ lý không dispatch được subagent — mặc định với wrapper
Copilot và Cursor — vòng review vẫn chạy, nhưng chỉ là một lượt đọc đúng những
gì được giao, và đó là một **báo cáo, không phải một cổng**: pha đó dừng lại
tại chỗ và chuyển kết quả cho bạn, thay vì tự tiến bước dựa trên lời tự nhận
của mình.

## 4.5 Sửa một bug

Bug mà BA đã publish là `BUG-<n>` (`> Type: bug` hoặc `hotfix`, `> Severity:
S1`–`S4`). Nó không có user story và không có tiêu chí chấp nhận: xong khi các bước
không còn tái hiện kết quả sai. `/dev-fix-bug BUG-<n>` chạy theo phong cách
`superpowers:systematic-debugging`:

1. **Intake** — lấy bug về. `kb ticket fetch BUG-<n>` ghi `docs/impl/<id>/ticket.md`
   và chép ảnh chụp của bug (PNG hoặc WebP) vào `docs/impl/<id>/assets/`; nó cảnh
   báo một lần cho mỗi ảnh thiếu trong bản clone hub, khi đó bạn mở
   `<hub>/assets/<name>`. MCP `kb_ticket_fetch` chỉ trả về văn bản. Tạo branch
   `fix/<BUG-id>`, hoặc `hotfix/<BUG-id>` từ nhánh production mà bạn chỉ định.
2. **Reproduce** — một test thất bại cho thấy kết quả thực tế. Không có test này
   thì không sửa.
3. **Root cause** — các giả thuyết ghi rõ trong `docs/impl/<id>/rootcause.md`. Ba
   giả thuyết thất bại thì luồng dừng lại để bàn về kiến trúc với bạn.
4. **Fix** — một thay đổi tại nguyên nhân gốc, toàn bộ test xanh.
5. **Handover** — `/dev-handover` với quy tắc cho bug: không có design hay plan; test
   tái hiện và dòng root cause thay thế chúng.

## 4.6 Câu hỏi cho BA, và `/dev-sa`

`dev-design` và `dev-plan` không giải quyết một nghi ngờ bằng cách đoán. Các subagent tác
giả của chúng không bao giờ gọi hub; chúng liệt kê từng nghi ngờ dưới `## Questions
raised` trong bản nháp, gắn nhãn `business` hoặc `technical`, kèm các AC bị chặn. Skill
điều phối phân loại chúng:

- **Kỹ thuật** (xây thế nào, đặt ở đâu, tái dùng thành phần nào) chuyển cho `dev-sa`, kiến
  trúc sư giải pháp của repo này. Nó đọc mã nguồn và các tài liệu `-code`, `-svc` và miền
  của hub rồi trả về một quyết định cùng lập luận, các phương án bị loại và bằng chứng
  `path:line` / `doc §section`. Skill ghi nó vào `## Technical decisions` của bản nháp
  dưới dạng `- SA-<n>: <quyết định> — vì sao — bằng chứng` và gửi lại cho tác giả. Không
  có gì đi lên hub. Bạn có thể tự gọi: `/dev-sa <câu hỏi>` cho ticket đang làm; nó trả về
  dòng để bạn ghi lại. Khi nó xét thấy đáp án sẽ đổi nghĩa của một AC, nó trả về `business
  question:` và câu hỏi chuyển sang BA.
- **Nghiệp vụ** đi tới BA qua MCP `kb_question_ask`, và xuất hiện trong `## Open
  questions` của bản nháp dưới dạng `- Q<id> — <câu hỏi> — blocks: <AC id|none>`. BA trả
  lời bằng `/ba-answer-questions`.
- **Câu hỏi chặn sẽ dừng cổng.** Thiết kế hoặc kế hoạch còn câu hỏi mở chặn một AC thì
  không qua được GATE 1 hay GATE 2; skill dừng và đưa bạn đường dẫn Q&A của hub để dán vào
  chat. Câu hỏi không chặn AC nào thì không dừng, và reviewer A1, A2 coi nó là mục còn mở
  đã biết. Trục Pre-code của rubric review chấp nhận `Q<id>` đã hỏi qua hub như cách mang
  một điều mơ hồ.
- **Marker `BA-Q`.** Dòng `State:` của khối Next-step có thêm marker thứ năm,
  `BA-Q: none | open Q<ids> | waiting Q<ids>`.
- **Tiếp tục.** Mỗi lần vào, `/dev-implement-ticket` đọc `kb_question_list` của ticket.
  Câu hỏi *đã trả lời* mà bạn chưa đánh dấu được hiển thị cùng các section đã đổi; luồng
  tải lại ticket, đánh dấu dòng `## Open questions` là `— answered rev N — re-draft` (pha đó điều phối lại
  author đúng một lần cho dòng này rồi bỏ `— re-draft`), và quay lại
  `dev-design` nếu một section đã đổi chạm vào thiết kế đã duyệt (nó về `draft`). Câu hỏi
  *chờ* (đã trả lời, nhưng revision ticket mới của BA chưa lên hub) chỉ là thông tin: đừng
  hành động theo. Câu hỏi *mở* và chặn thì dừng luồng.
- **Chỉ trên server hub dùng chung.** `kb_question_ask`, `kb_question_list` và
  `kb_question_answer` chỉ chạy khi MCP trỏ tới server HTTP của hub (`kb mcp-setup`); URL hub
  đọc qua bản clone cache cục bộ, hoặc đích khác, trả lời `Q&A needs the shared hub server — point MCP at it (kb mcp-setup)`. Mọi bên
  gọi đã xác thực đều được ghi và tên là tự khai (`git config user.name`), nên chỉ để theo
  dõi ai đã hỏi, không hơn. Mỗi ticket có tối đa 50 câu hỏi mở. Khi Q&A không dùng được và
  trong thiết kế hay kế hoạch mọi dòng `Q<id>` đều có `— answered rev N` (hoặc không có
  dòng nào), `/dev-implement-ticket` tiếp tục với `BA-Q: unknown (Q&A unavailable)` kèm một
  ghi chú; nếu có dòng `Q<id>` thiếu nó thì dừng, vì không thể biết trạng thái. Trong
  `dev-design` và `dev-plan`, câu hỏi nghiệp vụ có `blocks: none` khi đó quay về `OPEN(BA)`;
  chỉ câu hỏi chặn mới dừng.

---

# 5. Cái gì được máy bảo đảm, cái gì chỉ là lời nhắc

Hãy tỉnh táo về sự khác nhau này.

## 5.1 Máy bảo đảm

| Quy tắc | Được bảo đảm bởi |
|---|---|
| PR mang theo bằng chứng của nó | `kb pr lint` trong `kb-pr-lint.yml` ở mọi pull request |
| Tri thức chưa review không lên được hub | `kb build` thoát 1 khi còn section `-svc` ở trạng thái `pending` |
| Cache ngữ cảnh do CLI sở hữu | `kb resolve --status-only --cache` từ chối cache có version, tập tham chiếu hoặc khối đã phân giải khác với ticket |
| Merge-risk review đã chạy và không còn BLOCKER | `kb pr lint` — mục `## Testing` phải có dòng `Blocking: No` |

Mô tả PR ngắn gọn: `## Ticket` (ticket yêu cầu gì), `## Changes` (PR đã làm
gì), `## Testing` (dòng AC→test, lệnh test đã dán kèm các dòng tổng kết, và
`Blocking: No` của A5), cộng `## Notes` tùy chọn (ngoài phạm vi, chưa xử lý,
phát hiện). `kb pr lint` fail khi thiếu Ticket, Changes hoặc Testing, hoặc mục
đó còn nguyên dòng chú thích mẫu, khi Testing không có output đã dán hay không
có khối nào chứa lệnh test của kế hoạch, hoặc khi dòng `Blocking:` thiếu hay
ghi `Yes`.

## 5.2 Chỉ là lời nhắc trong prompt — không có gì đo lường

Đây là những quy tắc mà các skill nhắc đi nhắc lại. Không có gì trong `kb` bảo
đảm hay đo lường chúng. Phép kiểm tra duy nhất là con người ở cổng — tức là bạn.

- **TDD.** Không viết code sản phẩm khi chưa thấy một test fail trước, ở mọi bước
  của `dev-execute`. Các loại được miễn được nêu tên trong
  `docs/tdd-exemptions.md` và khai báo trong kế hoạch.
- **Verify phải có bằng chứng.** Không tuyên bố hoàn thành khi chưa có output
  lệnh thật. `kb pr lint` kiểm tra nội dung PR, không kiểm tra phiên làm việc.
- **Giá trị đã ghim, nguyên văn.** Mọi giá trị suy ra từ tiêu chuẩn phải lấy từ
  section đã phân giải ở phiên bản hub đã ghim, kèm chú thích trích dẫn.
- **Ticket là chỉ đọc.** Phát hiện được chuyển ngược về BA; agent không bao giờ
  sửa ticket.
- **Cổng 1 và cổng 2.** Thiết kế và kế hoạch phải được duyệt trước khi sang pha
  sau. Dòng `status:` ghi lại điều đó; con người mới là người duyệt.
- **`OPEN(BA)`.** Một tiêu chí chấp nhận mơ hồ phải được đưa lên hỏi, không bao
  giờ được tự diễn giải lại. Trong lúc thiết kế và lập kế hoạch, việc đưa lên hỏi là một
  câu hỏi trên hub (`Q<id>`, §4.6); `OPEN(BA)` chỉ còn cho điều `dev-execute` gặp giữa
  lúc hiện thực, và nó quay lại `dev-design`.
- **A1–A4.** Bốn vòng review agent trước GATE 3 là kỷ luật trong prompt.
  Không có gì trong `kb` đo được rằng chúng đã chạy. Chỉ A5 có răng: `kb pr
  lint` đọc dòng `Blocking:` trong mục `## Testing` của PR. Một agent bỏ qua
  A1–A4 rồi viết một dòng `Blocking: No` trung thực vẫn qua cổng — cổng nằm ở
  chỗ merge thật sự xảy ra, không phải ở mọi bước trước đó.

---

# 6. Làm việc với trích dẫn

```bash
kb resolve tickets/ABC-123.md    # ok | stale | broken, theo từng tham chiếu
kb diff hr-handbook --against <rev>
kb get hr-handbook 4.12 --level l3
```

| Trạng thái | Nghĩa là gì | Làm gì |
|---|---|---|
| `ok` | Nội dung đã ghim vẫn khớp với bản đang publish | Cứ hiện thực theo đó |
| `stale` | Nguồn bị sửa đổi sau khi ticket được viết | Chạy `kb diff`, rồi hỏi BA xem tiêu chí chấp nhận còn đúng không. **Đừng âm thầm hiện thực theo bản mới.** |
| `broken` | Tham chiếu không còn phân giải được | Báo lên. Ticket không hiện thực được như đang viết. |

Khi một giá trị trong code của bạn đến từ một tiêu chuẩn — một định dạng, một
enum, một ngưỡng, một độ dài trường — hãy lấy nó từ section đã phân giải ở phiên
bản đã ghim và để lại một chú thích trích dẫn ngay cạnh. Sáu tháng sau, chú thích
đó là thứ duy nhất nối hằng số ấy với lý do tồn tại của nó.

---

# 7. `kb code-ingest` trích xuất những gì

```bash
kb code-ingest                          # mặc định thường là đúng
kb code-ingest --db data/app.sqlite     # nêu tên database một cách tường minh
kb code-ingest --json                   # báo cáo dạng máy đọc
```

Mười một extractor, tổ chức theo **loại artefact chứ không theo ngôn ngữ lập
trình**, vì Strata được áp dụng trên nhiều dòng dự án. Bảy cái đầu đọc file
build, deploy và hợp đồng; bốn cái cuối đọc mã nguồn bằng tree-sitter (§7.5).

| Extractor | Tiền tố section | Đọc |
|---|---|---|
| `services` | `svc.<name>` | file compose, Dockerfile, manifest k8s, file solution và workspace |
| `deps` | `dep.<ecosystem>` | manifest của Python, JavaScript, Java, .NET, Go, PHP, Rust, Swift, Dart |
| `commands` | `cmd.<purpose>` | script trong package, Makefile, tox, shell script, bước run trong CI |
| `tree` | `struct.tree` | các file Git theo dõi, nên virtualenv bị ignore không bao giờ xuất hiện |
| `schema` | `db.<table>` | migration SQL, Prisma, Alembic, EF, và file SQLite được nêu tên tường minh |
| `integrations` | `int.<name>` | **chỉ tên khoá** biến môi trường |
| `api` | `api.<tag>` | hợp đồng OpenAPI và Swagger nằm trong repo |
| `routes` | `route.<slug>` | route HTTP khai báo trong mã nguồn (cần `[code]`) |
| `pages` | `page.<slug>` | route trang UI (router theo file hệ thống chạy được không cần `[code]`) |
| `jobs` | `job.<slug>` | job định kỳ của các scheduler framework (cần `[code]`) |
| `symbols` | `sym.<slug>` | tên được export, member của enum và object, CSS custom property (cần `[code]`) |

`tree` còn ghi `struct.files.<dir>`, và mọi extractor báo cáo vào
`struct.coverage` (§7.5). `tree` thì lúc nào cũng tìm ra thứ gì đó và bốn
extractor đọc mã nguồn không được tính là bằng chứng của một codebase, nên quy
tắc không-phát-hiện-gì là: `kb code-ingest` thoát `1` khi **không cái nào trong
`services`, `deps`, `commands`, `schema`, `integrations` và `api`** tìm được gì.
Một tài liệu chỉ chứa danh sách thư mục và các section sinh từ mã nguồn là cấu
hình sai, không phải tri thức.

## 7.1 Hai thuộc tính an toàn

Đây là thuộc tính thiết kế, không phải tiện ích.

1. **Chỉ lấy khoá, không bao giờ lấy giá trị.** File môi trường duy nhất mà
   extractor integrations mở là `.env.example`, `.sample` hoặc `.template` —
   không bao giờ là `.env` thật — và biểu thức của nó không có nhóm bắt nào quanh
   phần giá trị, nên không có gì để rò rỉ dù dòng khớp chứa gì. Khối
   `environment:` trong compose **có** được đọc và có chứa giá trị thật, nhưng
   chỉ tên khoá được giữ lại.
2. **Đầu vào database phải tường minh.** Schema SQLite chỉ được đọc từ đường dẫn
   bạn nêu trên dòng lệnh. Một database nháp hay fixture trong repository không
   bao giờ vô tình trở thành tri thức đã publish của công ty.

## 7.2 Giới hạn của bộ phân tích, nói rõ từ đầu

Đây là giới hạn, không phải lỗi.

- `schema` chạy lại `CREATE TABLE`, `ALTER TABLE … ADD COLUMN` và các câu lệnh
  index, khoá nêu dưới đây theo thứ tự tên file đã sắp xếp. Nó không hiện thực
  một phương ngữ SQL.
- Một `CREATE TABLE` cho tên đã được tạo ở một thư mục migration *khác* sẽ bị bỏ
  kèm cảnh báo nêu tên cả hai file, và `ADD COLUMN` chỉ áp dụng trong thư mục của
  `CREATE TABLE` tương ứng. Hai schema độc lập trùng tên bảng không bao giờ bị
  gộp thành một thứ không tồn tại ở đâu cả.
- Mệnh đề partition, khoá chính, `CREATE INDEX` và `ADD CONSTRAINT … PRIMARY
  KEY|UNIQUE` được đọc. Câu lệnh mà `schema` không áp dụng được (`RENAME`, một
  action `ALTER` lạ) là một site: dòng coverage `schema` của phạm vi và bộ đọc đó
  hiện `partial` và nêu `file:line`. Ràng buộc `FOREIGN KEY` và `CHECK` chỉ cảnh
  báo.
- Tên bảng không khớp dạng định danh nhận diện được sẽ bị bỏ qua **kèm cảnh báo
  nêu tên file**. Bộ đọc đếm số từ khoá `CREATE TABLE` và so với số nó nhận diện
  được, nên việc bỏ qua không bao giờ im lặng.
- Migration của EF Core chỉ được nhận diện theo tên bảng.
- `build.gradle` được khớp bằng regex, không phân tích như một DSL.
- Maven `<plugins>`, `setup.cfg` `extras_require`, `pnpm-workspace.yaml` và
  `healthcheck:` trong compose không được đọc.

## 7.3 Đích đến mà lệnh này không tạo ra sẽ bị từ chối

Nếu `.kb/<doc_id>/` đã có Markdown hoặc manifest, mà manifest đó thiếu, không đọc
được, không mang tiêu đề `… — code knowledge`, hoặc liệt kê một id section nằm
ngoài các tiền tố được sinh ra, thì `kb code-ingest` thoát 1 và không ghi gì cả.
Không có cờ ghi đè — hãy chuyển tài liệu đi hoặc chọn `--doc-id` khác.

## 7.4 Tính tất định và lưu ý về cây làm việc chưa sạch

Chạy lại trên cùng một commit, cùng một nền tảng sẽ cho file giống nhau từng
byte — chính điều đó làm cho lượt publish trong CI thực sự là no-op khi cây file
không đổi.

Hai giới hạn được nói thẳng: một vài phép khớp glob chuẩn hoá chữ hoa/thường theo
hệ điều hành, nên đảm bảo này là theo từng nền tảng (CI luôn chạy Linux nên thứ
được publish vẫn ổn định); và `revision` trong manifest suy ra từ **commit HEAD**
trong khi cây làm việc của bạn có thể đang có thay đổi chưa commit.
`kb code-ingest` phát hiện điều đó và in cảnh báo `dirty_tree`.

`-code` cục bộ là thứ CI sẽ sinh ra nếu các file đang được track của bạn được
commit ngay bây giờ; `kb doctor` cảnh báo khi strata-kb đã cài trên máy bạn
khác với phiên bản mà `kb-code.yml` ghim.

## 7.5 Route, page, job, symbol và coverage

Bốn extractor đọc cú pháp mã nguồn bằng tree-sitter và cần
`pip install "strata-kb[code]"`. Phiên bản được ghim chính xác
(`tree-sitter-language-pack` 0.13.0, không bao giờ 1.x vì bản 1.x tải grammar
từ mạng lúc chạy), nên cùng một commit cho ra cùng từng byte trên mọi máy. Ngôn
ngữ: JS/TS, Java/Kotlin, C#, Python, PHP, Go, Rust, Swift và Dart, cộng CSS/SCSS
cho custom property.

| Section | Chứa |
|---|---|
| `route.<slug>` | Một section cho mỗi controller class, file router hoặc file route. Bảng `Method \| Path \| Handler \| File \| Request type`, các tiền tố của class, router, group và global được nối lại; L3 thêm các trường của request type định nghĩa trong repo |
| `page.<slug>` | Một section cho mỗi ứng dụng front-end. Bảng `Path \| File \| Layout/group`; route group như `(admin)` và segment động (`[id]`, `:id`, `[...slug]`) giữ nguyên như đã viết; matcher của `middleware` Next.js là một dòng `Middleware matcher` |
| `job.<slug>` | Một section cho mỗi file hoặc manifest khai báo. Bảng `Name \| Schedule \| Handler \| File`; schedule là biểu thức như đã viết, `hosted`, hoặc `(dynamic)` |
| `sym.<slug>` | Một section cho mỗi package root (thư mục có manifest riêng), nếu không thì theo thư mục cấp cao nhất. Bảng `Name \| Kind \| File`; kind gồm `function`, `class`, `interface`, `type`, `const`, `enum`, `member`, `css-var` |
| `struct.files.<dir>` | Mọi file được track dưới một thư mục cấp cao nhất, không giới hạn; `struct.tree` vẫn là bản tổng quan có giới hạn |
| `db.<table>` | Thêm các dòng `Table`, `Primary key`, `Partition` và `Indexes`. Model Prisma và migration SQL của cùng một bảng được gộp thành một section `db.<Model>`; khi hai nguồn lệch nhau, cả hai giá trị hiện ra kèm nguồn |

Framework được hỗ trợ:

- **Route:** NestJS, Express, Next.js, Nuxt, Spring Boot, Quarkus, Micronaut,
  ASP.NET Core, FastAPI, Flask, Django, Gin, Laravel, Symfony, Actix Web, Axum,
  Rocket, Vapor.
- **Page:** Next.js, Nuxt, SvelteKit, Angular, Vue, React (react-router),
  Flutter (go_router).
- **Job:** NestJS, Spring / Quarkus / Micronaut, Hangfire, Quartz và hosted
  service của .NET, Celery, Laravel, Symfony, node-cron, BullMQ, robfig/cron,
  tokio-cron-scheduler, `CronJob` của Kubernetes.

Section được tách theo file, package hoặc thư mục cấp cao nhất, không bao giờ
theo kích thước, và không danh sách nào bị cắt. Chỉ phát ra tên; các chuỗi
literal duy nhất là đường dẫn route và page, matcher của middleware, biểu thức
cron hoặc interval và tên CSS custom property. Giá trị env, giá trị hằng số và
giá trị member của enum không bao giờ xuất hiện.

**`struct.coverage`** cho SA biết nên tin một sự vắng mặt đến đâu. Một bảng,
`Area | Scope | Framework/language | Status | Detail`, các vùng `routes`,
`pages`, `jobs`, `symbols`, `files` và `schema`:

| Status | Ý nghĩa |
|---|---|
| `complete` | Mọi dạng được nhận diện trong phạm vi đó đều đã được giải quyết |
| `partial` | Đã thấy nhưng không giải quyết được: đường dẫn route động, file không parse được, re-export mà bộ đọc không lần theo được. Mỗi vị trí được nêu dạng `file:line` |
| `not scanned` | Chưa quét gì; phần detail nêu lý do (thiếu extra, ngôn ngữ hoặc framework chưa có adapter) |

Vì vậy một đường dẫn động trong code của bạn làm phạm vi của nó thành `partial`,
chứ không lặng lẽ bỏ mất route. **`jobs` không bao giờ `complete`:** một job có
thể nằm ở chỗ không adapter nào nhìn tới (`pg_cron` trong migration, một
`setInterval` viết tay, một crontab), nên dòng của nó luôn là `partial` với
detail `jobs outside framework schedulers are not detectable`. Job đã có thì được
liệt kê; job vắng mặt luôn là một câu hỏi dành cho bạn.

Điều này thay đổi gì với bạn: với route, page, symbol, file hoặc partition,
index, khoá chính của một bảng, SA chỉ ghi một thứ mới là mới khi phạm vi đó là
`complete`: `<thing> in <path> [NEW: D<n>]` cho route, page hoặc symbol, và
`<path> [NEW: D<n>]` làm một mục `Files:` riêng cho file; với index, partition
hoặc khoá chính của bảng, nó là một gạch đầu dòng con của `Tables:`:
`<index|partition|primary key> on db.<table> in <path> [NEW: D<n>]` (`<path>`
là file migration). Phạm vi là phạm vi dài nhất trong một dòng `struct.coverage` không
thuộc vùng `files` làm tiền tố của đường dẫn và phải có dòng riêng cho vùng đó, nếu không vùng ấy là
`not scanned` ở đó. Ngược lại nó là một mục `Open decisions`, trích trạng
thái. `kb ticket check` thực thi quy tắc này (xem hướng dẫn BA §3.8). Tài liệu
`-code` tạo bởi bản cũ không có `struct.coverage`, nên các vùng đó vẫn là câu hỏi
dành cho bạn cho tới khi repo của nó được publish lại.

**Nâng cấp lên 1.28.0:** chạy `pip install "strata-kb[code]"` ở máy; chạy lại
`kb init --kind dev` để có `kb-code.yml` mới (nó cài extra trong CI); sau đó
chạy `kb publish` để publish lại `-code` (push lên nhánh mặc định không publish gì). Chạy lại
`kb init --kind ba` ở repo BA để có SA prompt và ticket template mới.

---

# 8. Giữ tri thức luôn mới

Không tài liệu nào đòi hỏi kỷ luật tài liệu hoá mới theo từng ticket từ bạn.

## 8.1 `-code` không cần bạn làm gì

`-code` không bao giờ được commit. `.gitignore` có dòng `.kb/*-code/`, và
tài liệu được sinh lại từ working tree mỗi khi một lệnh cần đến nó:
`kb svc note`, `kb build`, `kb doctor` và `kb publish` làm mới nó trước khi
chạy nếu nó chưa có, cũ hơn `HEAD`, hoặc các file đang được git track có
thay đổi. File mới chỉ được tính sau khi `git add`. `kb ticket check` đọc
bản trên hub trước — đó là bản SA đã dùng để ground ticket (mục 4.1).

So sánh với snapshot đã publish của `kb doctor` bỏ hẳn `-code` ra ngoài (repo
dev không bao giờ khớp hub ở tài liệu này); `kb publish` mới là lệnh thực sự
làm mới nó và gửi lên hub.

`kb-code.yml` chạy lại `kb code-ingest` → `kb build` → `kb ci-publish` khi một
tag `kb-publish/*` được push, đúng là việc `kb publish` làm. Push lên nhánh mặc
định không publish gì (intake chỉ nhận publish từ tag đó), nên hãy chạy
`kb publish` sau mỗi lần merge; hub phản ánh commit đó ngay khi PR của nó được
merge.

| Kích hoạt | Các bước | Publish |
|---|---|---|
| tag `kb-publish/*` (do `kb publish` push), hoặc chạy tay trên một tag như vậy | code-ingest → build → ci-publish | có |
| pull request | build (sinh lại `-code` từ merge ref) | **không bao giờ** |

`-code` chỉ có một nguồn sinh là `kb code-ingest`: `kb summarize` từ chối nó.
Bản trên hub từng được summarize trước 1.4.0 sẽ trở về L1/L2 deterministic ở
lần CI publish kế tiếp — diff một lần, không mất thông tin; L3 không đổi.

`--scaffold-svc` cố ý không bao giờ được truyền trong CI. CI không được tạo
nội dung `pending`, vì như vậy chính bước build của nó sẽ fail.

## 8.2 `-svc` tích luỹ ở bước handover

`dev-handover` chạy lệnh sau cho mỗi service mà ticket chạm tới:

```bash
kb svc note payments-api --ticket ABC-123 \
  --title "Add refund endpoint" --refs "payments-spec §4.2"
```

Lệnh đó thêm một dòng vào `hist.<service>`. Nó tất định và **idempotent**: chạy
lại với cùng ticket và cùng service sẽ cập nhật dòng đó chứ không nhân đôi.

Bạn không bao giờ sửa tay `hist.*`. Đó là nhật ký chỉ thêm, chỉ do `kb svc note`
ghi. Những section này là sự thật — "ticket này đã chạm tới service này" — không
phải khẳng định, nên chúng không cần review và không bao giờ chặn build.

`kb svc note` thoát 1 khi gặp một trong các trường hợp: không phân giải được id
repo; thiếu tài liệu `-svc` hoặc `-code` đi kèm; service không xác định (một lỗi
gõ không được phép bịa ra service); manifest không đọc được; hoặc manifest và
file lệch nhau.

## 8.3 Trôi dạt trong phần mô tả trách nhiệm

Phần mô tả trách nhiệm vẫn có thể trôi dạt, và hệ thống **tự báo chứ không tự
chữa**.

Khi `kb code-ingest --scaffold-svc` làm mới bằng chứng code của một service mà
phần tóm tắt của section đó đã ở trạng thái `reviewed`, nó so sánh bằng chứng cũ
và mới ở dạng **một chuỗi nguyên khối đã cắt khoảng trắng hai đầu** — không phải
một phép diff ngữ nghĩa trên từng trường. **Bất kỳ** thay đổi nào ngoài khoảng
trắng đầu/cuối đều làm nổi cờ `stale-risk: svc.<name>` trong báo cáo.

Một thay đổi thật sẽ kích hoạt nó — thêm hoặc bớt một file, một bảng. Nhưng một
thay đổi chỉ ở *cách* bằng chứng được kết xuất, dù bên dưới không có dòng code
nào đổi, cũng kích hoạt. Đó không phải lỗi, và nó không bao giờ đụng vào phần tóm
tắt. Đó là một dấu hiệu để con người nhìn lại.

---

# 9. Xử lý sự cố

| Hiện tượng | Nguyên nhân | Cách xử lý |
|---|---|---|
| `kb code-ingest` thoát 1: không phát hiện gì | Chỉ có `tree` và các extractor đọc mã nguồn tìm được thứ gì đó | Kiểm tra xem file compose, manifest hay CI workflow có nằm đúng chỗ extractor tìm không; nêu `--db` nếu schema là thứ bạn cần |
| `kb doctor`: "strata-kb[code] is not installed" | Máy chưa cài extra `code`, nên route và symbol (cùng page, trừ router theo file hệ thống) sẽ là `not scanned` còn job vẫn là `partial` | `pip install "strata-kb[code]"` |
| `kb code-ingest` thoát 1: từ chối đích đến | Có một tài liệu do người soạn đang nằm ở doc id đó | Chuyển nó đi, hoặc dùng `--doc-id` |
| `kb build` fail trên CI ở một section `-svc` | Một section `pending` đã bị commit | Hoàn tất bước seed: summarize, review, `kb approve` |
| `kb svc note`: "unknown service" | Do gõ nhầm, hoặc file của service mới chưa được track | Copy id từ `services.md`; `git add` các file mới rồi thử lại |
| `kb doctor`: "hub `<repo>`-code lags origin/main" | Lượt publish `-code` gần nhất chưa merge trên hub, hoặc lần chạy `kb-code.yml` gần nhất fail | Mở PR trên hub được nêu tên trong job summary của Actions; merge nó hoặc sửa lượt chạy |
| `kb doctor`: "kb-code.yml passes --db" | Cấu hình ingest đang nằm trong workflow | Chuyển các đường dẫn sang `code_ingest.db` trong `.kb/config.yaml`, rồi chạy lại `kb init --kind dev` |
| `kb doctor`: "`.kb/<repo>-code` is tracked by git" | Repo có từ trước 1.4.0 | `git rm -r --cached .kb/<repo>-code` rồi commit, trong cùng một PR |
| `kb doctor`: "hub lag not judged — origin/HEAD is not set" | `origin/HEAD` chưa bao giờ được đặt (vừa `git remote add` + `push -u`, chưa ai chạy `git remote set-head`) | `git remote set-head origin --auto` |
| `kb publish` treo rồi fail và nhắc xem Actions | Dùng `kb publish` thường trên repo mà CI không có trigger theo tag | Dùng `kb publish --pr` |
| `kb ci-publish` bị từ chối | Repo này chưa có trong `federation/registry.yaml` của hub | Đề nghị người quản trị hub thêm vào |
| Cảnh báo `dirty_tree` | Có thay đổi chưa commit trong khi revision của manifest lấy từ HEAD | Vô hại khi chạy cục bộ; CI luôn chạy trên bản checkout sạch |
| `pr-lint` fail trên PR của Dependabot | Cổng này không tự bỏ qua một khi đã bắt buộc | Đúng như thiết kế. Hãy cân nhắc có giữ nó bắt buộc với PR của bot hay không. |
| `pr-lint` fail: `no-review-verdict` | Mục `## Testing` của PR không có dòng `Blocking:` | Chạy A5 (review rủi ro merge của `dev-handover`) và ghi lại kết luận — dù review sạch vẫn phải ghi `Blocking: No` |
| `pr-lint` fail: `review-blocking` | Mục `## Testing` ghi `Blocking: Yes` | Sửa các phát hiện BLOCKER rồi review lại; PR còn `Blocking: Yes` thì không bao giờ được merge |
| `kb ticket fetch`: "is not on the hub" | BA chưa publish nó, hoặc nó bị bỏ khỏi plan (DoR chưa tick đủ, hoặc mission cha đã đi tiếp) | Nhờ BA `kb publish` (hoặc cho biết vì sao nó bị bỏ qua); hoặc đưa file ticket hay dán nội dung |
| `kb ticket fetch`: "published by several repos" | Hai repo BA cùng publish một id | Viết id dạng `kb ticket fetch <repo>:<id>` |
| `kb ticket check` fail với `re-run /sa-ticket-ground` | Một fact ticket trích đã mất khỏi `-code` | Dừng và trả ticket cho BA; SA sẽ ground lại |
| `kb ticket check`: `[warn] … review the diff` | Một section được trích có đổi nhưng các tên được trích vẫn còn | Đọc diff; làm tiếp trừ khi nó đổi ý nghĩa ticket |
| `kb ticket fetch` không kết nối được hub | `hub:` chưa đặt hoặc không với tới được | Sửa `hub:` trong `.kb/config.yaml` (hoặc `STRATA_KB_HUB`), hoặc dùng đường dẫn/dán nội dung |
| Một trích dẫn báo `stale` giữa chừng | Hub đã publish sau khi ticket được viết | `kb diff`, rồi hỏi BA. Đừng tự diễn giải lại tiêu chí chấp nhận. |
| Không kết nối được MCP server | `STRATA_KB_HUB_URL` hoặc `STRATA_KB_HTTP_TOKEN` chưa đặt hoặc sai | Chạy lại `kb mcp-setup` (`/kb-mcp-setup`) — lệnh này chẩn đoán chính xác cái nào sai, chạy lại không kèm gì sẽ xác minh lại mà không cần nhập lại token |
| `kb mcp-setup` báo "token bị từ chối" dù đã xin được token mới từ người quản trị hub | Chạy lại không kèm gì chỉ đọc lại đúng token *cũ* từ `.env` ra — lệnh chỉ hỏi lại khi trên đĩa chưa có gì | Chạy `STRATA_KB_HTTP_TOKEN=<token-mới> kb mcp-setup`, hoặc xoá dòng `STRATA_KB_HTTP_TOKEN` trong `.env` rồi chạy lại |

Bản thân bước kiểm tra hub-lag chạy trọn một lượt `code-ingest` trong một
worktree tạm ở mỗi lần `kb doctor` — hãy tính thêm thời gian này vào lệnh.
Trên Windows, cùng một khác biệt case của glob theo hệ điều hành đã nêu ở
§7.4 có thể khiến một repo không hề đổi gì báo thành `lags`; một kết luận
lag biến mất khi chạy trên Linux (CI) chính là do lưu ý đó, không phải drift
thật.

---

# 10. Tóm tắt lệnh

| Lệnh | Mục đích | Mã thoát |
|---|---|---|
| `kb mcp-setup [--hub-url URL] [--no-verify]` | Ghi thông tin xác thực HTTP MCP của hub vào `.env` và xác minh chúng | `0` ok, `1` thiếu giá trị hoặc kiểm tra kết nối thất bại |
| `kb code-ingest [--db p] [--tags t] [--scaffold-svc] [--json]` | Trích cấu trúc code vào `-code` (`--db`/`--tags` thay thế `code_ingest:` cho lượt chạy đó) | `0` ok, `1` không phát hiện gì hoặc từ chối đích đến |
| `kb svc note <svc> --ticket <id> --title "…" [--no-refresh]` | Thêm một dòng vào `hist.<svc>` | `0` ok, `1` service không xác định hoặc thiếu tài liệu |
| `kb build [--strict] [--no-refresh]` | Kiểm tra kho | `0` ok, `1` lỗi |
| `kb doctor [--no-refresh]` | Kiểm tra sức khoẻ KB (repo dev: làm mới `-code` trước) | `0` ok, `1` lỗi, `2` trích dẫn cũ |
| `kb approve <doc> [--section <id>]` | Chuyển các section đã sửa sang `reviewed` | `0` ok |
| `kb publish --pr` | Mở PR trên hub (lượt publish đầu của bước seed) | `0` ok |
| `kb ticket fetch <id> [--out p] [--hub u]` | Lấy một ticket từ hub vào `docs/impl/<id>/ticket.md` | `0` ok, `1` không có trên hub, mơ hồ, hoặc id không an toàn |
| `kb ticket check <file> [--hub u]` | Grounding của ticket so với `-code` trên hub; revision bị lệch chỉ fail khi một fact được trích đã mất | `0` PASS, `1` FAIL |
| `kb mission next --from-hub [--repo id]` | Trạng thái mọi story đã publish, chỉ từ hub | `0` |
| `kb resolve <file>` | Kiểm tra trích dẫn của ticket | `0` ok, `1` hỏng, `2` cũ |
| `kb diff <doc> --against <rev>` | Sửa đổi đã thay đổi những gì | `0` |
| `kb query <text>` / `kb get <doc> <section>` | Tìm và lấy nội dung | `0` |
| `kb plan waves <plan-file> [--json]` | Các wave dependency của một `docs/impl/<id>/plan.md` | `0` ok, `1` file dùng chung không có dependency, vòng lặp, task không xác định, hoặc thiếu `Depends on:` |
| `kb impl tidy [--impl-dir]` | Dời layout phẳng cũ `docs/impl/<id>-*` vào `docs/impl/<id>/`; chạy lại không đổi gì, không bao giờ ghi đè | `0` sau khi in báo cáo, `1` khi thư mục không tồn tại |
| `kb pr lint <file>` | Cổng bằng chứng cho PR | `0` PASS, `1` FAIL |

**Slash command:** `/dev-implement-ticket`, `/dev-design`, `/dev-plan`,
`/dev-execute`, `/dev-handover`, `/dev-code-seed`, `/dev-fix-bug`, `/dev-sa`.

---

# 11. Những tên được dành riêng

`<repo_id>-code` và `<repo_id>-svc` được dành riêng cho tri thức về code của
chính repository này. Một tài liệu nghiệp vụ tuyệt đối không được lấy một trong
hai hậu tố đó.

Tiền tố section là một hợp đồng đã công bố mà công cụ của BA và các công cụ tương
lai dựa vào. Mỗi tiền tố có đúng một chủ sở hữu:

| Tiền tố | Tài liệu | Chủ sở hữu |
|---|---|---|
| `struct.tree`, `struct.files.<dir>`, `struct.coverage`, `svc.<name>`, `db.<table>`, `dep.<eco>`, `int.<name>`, `api.<tag>`, `route.<slug>`, `page.<slug>`, `job.<slug>`, `sym.<slug>`, `cmd.<purpose>` | `-code` | extractor |
| `svc.<name>` | `-svc` | bạn (model soạn nháp) |
| `flow.<name>` | `-svc` | bạn |
| `hist.<name>` | `-svc` | chỉ `kb svc note` |

`svc.<name>` trùng nhau ở cả hai tài liệu **là có chủ đích**. Đó là khoá nối cho
phép một `Container(alias, label, technology, description)` trong C4 được điền từ
`-code` (ba tham số đầu) và `-svc` (tham số thứ tư).
