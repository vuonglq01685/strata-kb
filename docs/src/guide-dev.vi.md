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
| Đọc tri thức đã publish trên hub | Ingest tài liệu từ bên ngoài repo |
| Publish tri thức về **chính code của nó** | Publish tri thức nghiệp vụ |
| Chạy quy trình hiện thực gồm năm lệnh | Tự merge hay tự ship bất cứ thứ gì |

Ranh giới này là có chủ đích. Repo `child` đưa tài liệu bên ngoài vào; repo `dev`
không ingest gì cả và chỉ soạn tri thức về chính nó. Chính điều đó làm cho việc
CI của bạn publish liên tục trở nên an toàn.

## 1.2 Hai tài liệu mà repo của bạn publish

| Tài liệu | Nguồn gốc | Sinh lại | Cần review |
|---|---|---|---|
| `<repo_id>-code` | `kb code-ingest` — tất định, không model | mỗi lần push lên nhánh mặc định | không |
| `<repo_id>-svc` | model soạn từ bằng chứng đó, bạn sửa lại | không bao giờ | luôn luôn |

`-code` là sự thật máy móc: tên service, công nghệ, dependency, lệnh, endpoint,
schema, cấu trúc thư mục. `-svc` là khẳng định của con người: mỗi service thực sự
*chịu trách nhiệm* về cái gì.

Chúng nối nhau bằng id section — `svc.<name>` tồn tại ở cả hai — nên một BA vẽ
container C4 lấy alias, nhãn và công nghệ từ `-code`, còn phần mô tả từ `-svc`.

---

# 2. Thiết lập một lần

```bash
pip install strata-kb
kb init --kind dev
```

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

## 2.2 Nối trợ lý của bạn

| Biến | Ví dụ |
|---|---|
| `STRATA_KB_HUB_URL` | `http://kb-hub.example.com:8321` |
| `STRATA_KB_HTTP_TOKEN` | bearer token của hub |

`.mcp.json` (Claude Code) và `.cursor/mcp.json` (Cursor) đã nối sẵn với hai biến
này. Không cần cấu hình gì thêm.

## 2.3 Bật cổng PR

`kb init` ghi ra `.github/workflows/kb-pr-lint.yml` nhưng không bật được branch
protection thay bạn. Hãy thêm **`pr-lint` vào danh sách check bắt buộc** của
nhánh.

> Hãy quyết định điều này một cách có ý thức. Khác với cổng của repo BA, cổng này
> không bao giờ tự bỏ qua. Một khi đã bắt buộc, nó chặn **mọi** pull request
> thiếu tám mục bắt buộc — kể cả pull request của bot như nâng cấp dependency hay
> revert.

## 2.4 Hỏi về chính sách auto-merge của hub

Pull request `-code` trên hub có thể được tự động merge; pull request `-svc` thì
tuyệt đối không. Hãy hỏi người quản trị hub cấu hình ra sao, và chắc chắn một
điều:

> `kb ci-publish` mở **một** pull request trên hub cho mỗi lần push, không phải
> mỗi tài liệu một cái. Intake gắn nhánh publish theo id repository và dùng lại
> nhánh đó trong khi PR còn mở — nên một lần push mang theo `-code` vừa sinh lại
> cùng với một sửa đổi `-svc` đã merge sẽ đưa **cả hai** vào cùng PR đó.
>
> Vì vậy quy tắc auto-merge phải được **giới hạn theo đường dẫn
> `.kb/<repo_id>-code/**`**, không bao giờ là quy tắc cho cả PR hay cả repo. Một
> quy tắc kích hoạt theo kiểu "đây là lượt publish `-code` của repo dev" sẽ âm
> thầm vô hiệu hoá chính cổng review `-svc` mà việc tách hai tài liệu sinh ra để
> bảo vệ.

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
khác trên hub. `-svc` là tri thức do người biên soạn; nó publish qua review, không
bao giờ qua auto-merge.

---

# 4. Hiện thực một ticket

Năm lệnh, được dựng sẵn cho Claude Code, GitHub Copilot và Cursor.

```
/dev-implement-ticket <ticket>     intake · resolve · ground · placeholders
        │
        ├─► dev-design       ── GATE 1: bạn duyệt thiết kế
        ├─► dev-plan         ── GATE 2: bạn duyệt kế hoạch
        ├─► dev-execute         (lặp lại được, tiếp tục được)
        └─► dev-handover     ── GATE 3: bạn mở PR
                                GATE 4: bạn merge
```

`/dev-implement-ticket` cũng là bộ điều phối: với một ticket mới, nó chạy bốn
bước đầu rồi gọi các pha theo thứ tự, tự phát hiện ticket đã đi tới đâu nên không
bao giờ làm lại phần đã xong.

## 4.1 Chọn điểm vào

| Tình huống | Chạy |
|---|---|
| Ticket mới, chưa bắt đầu gì | `/dev-implement-ticket <ticket>` |
| Ticket nhỏ, thay đổi đã quá rõ | `/dev-implement-ticket <ticket>` — luồng tự thu gọn; thiết kế vẫn được ghi ra, chỉ là bản rút gọn |
| Thiết kế đã duyệt, chưa có kế hoạch | `/dev-plan <id>` |
| Kế hoạch đã duyệt, hoặc đang hiện thực dở | `/dev-execute <id>` |
| Code đã tự viết, cần phần mô tả PR | `/dev-handover <id>` |
| Quên mất ticket đang ở đâu | `/dev-implement-ticket <id>` |
| Chỉ muốn kiểm tra một trích dẫn | `kb resolve <file>` |

Mọi điểm vào đều kiểm tra lại độ mới của trích dẫn trước tiên. Hub có thể đã
publish kể từ phiên làm việc trước, nên một tham chiếu hôm qua còn `ok` thì hôm
nay có thể đã `stale`. Chỉ kiểm tra lúc handover thì quá muộn.

## 4.2 Công việc nằm ở đâu

| File | Do ai ghi | Mục đích |
|---|---|---|
| `docs/impl/<id>-design.md` | `dev-design` | bản thiết kế |
| `docs/impl/<id>-plan.md` | `dev-plan` | mỗi tiêu chí chấp nhận một task, dạng checkbox `- [ ]` |
| `docs/impl/<id>-context.md` | `dev-implement-ticket` | cache ngữ cảnh đã phân giải; bị gitignore, sinh lại khi cần |

Trạng thái được suy ra từ hai file đầu, nhánh git hiện tại, và việc PR đã mở hay
chưa — **không bao giờ từ lịch sử hội thoại**. Bất kỳ pha nào cũng tiếp tục được
từ đầu trong một phiên làm việc hoàn toàn mới.

`kb init` không bao giờ đụng tới nội dung `docs/impl/` của bạn. Nó chỉ thêm
`.gitkeep` và một `.gitignore` để cache ngữ cảnh không bao giờ lọt vào pull
request.

## 4.3 Bốn cổng

Không gì trong quy trình này merge hay ship mà không có con người.

1. **Thiết kế được duyệt** — bạn ký duyệt trước khi viết bất kỳ kế hoạch nào.
2. **Kế hoạch được duyệt** — bạn ký duyệt trước khi viết bất kỳ dòng code nào.
3. **PR được mở** — agent viết nội dung; bạn mở PR.
4. **Merge** — bạn review và merge.

Agent không tự làm hai việc cuối.

---

# 5. Cái gì được máy bảo đảm, cái gì chỉ là lời nhắc

Hãy tỉnh táo về sự khác nhau này.

## 5.1 Máy bảo đảm

| Quy tắc | Được bảo đảm bởi |
|---|---|
| PR mang theo bằng chứng của nó | `kb pr lint` trong `kb-pr-lint.yml` ở mọi pull request |
| Tri thức chưa review không lên được hub | `kb build` thoát 1 khi còn section `-svc` ở trạng thái `pending` |
| Cache ngữ cảnh do CLI sở hữu | `kb resolve --status-only --cache` từ chối cache có version, tập tham chiếu hoặc khối đã phân giải khác với ticket |

`kb pr lint` fail khi thiếu một mục bắt buộc, khi mục đó còn nguyên dòng chú
thích mẫu, khi tuyên bố đã verify mà không dán output, khi không có khối
Verification nào chứa lệnh test của kế hoạch, hoặc khi `## TDD exemptions` nêu
một loại nằm ngoài `config`, `ci`, `docs`, `style`.

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
  giờ được tự diễn giải lại.

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

Bảy extractor, tổ chức theo **loại artefact chứ không theo ngôn ngữ lập trình**,
vì Strata được áp dụng trên nhiều dòng dự án.

| Extractor | Tiền tố section | Đọc |
|---|---|---|
| `services` | `svc.<name>` | file compose, Dockerfile, manifest k8s, file solution và workspace |
| `deps` | `dep.<ecosystem>` | manifest của Python, JavaScript, Java, .NET, Go, PHP, Rust, Swift, Dart |
| `commands` | `cmd.<purpose>` | script trong package, Makefile, tox, shell script, bước run trong CI |
| `tree` | `struct.tree` | các file Git theo dõi, nên virtualenv bị ignore không bao giờ xuất hiện |
| `schema` | `db.<table>` | migration SQL, Prisma, Alembic, EF, và file SQLite được nêu tên tường minh |
| `integrations` | `int.<name>` | **chỉ tên khoá** biến môi trường |
| `api` | `api.<tag>` | hợp đồng OpenAPI và Swagger nằm trong repo |

`tree` thì lúc nào cũng tìm ra thứ gì đó, nên quy tắc không-phát-hiện-gì là:
`kb code-ingest` thoát `1` khi **không extractor nào ngoài `tree`** tìm được gì.
Một tài liệu chỉ chứa danh sách thư mục là cấu hình sai, không phải tri thức.

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

- `schema` nhận diện `CREATE TABLE` và `ALTER TABLE … ADD COLUMN` theo thứ tự tên
  file đã sắp xếp. Nó không hiện thực một phương ngữ SQL.
- Một `CREATE TABLE` cho tên đã được tạo ở một thư mục migration *khác* sẽ bị bỏ
  kèm cảnh báo nêu tên cả hai file, và `ADD COLUMN` chỉ áp dụng trong thư mục của
  `CREATE TABLE` tương ứng. Hai schema độc lập trùng tên bảng không bao giờ bị
  gộp thành một thứ không tồn tại ở đâu cả.
- `RENAME`, `DROP`, `ADD CONSTRAINT` và `ADD INDEX` được cảnh báo là ngoài phạm
  vi.
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
ngoài bảy tiền tố được sinh ra, thì `kb code-ingest` thoát 1 và không ghi gì cả.
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

---

# 8. Giữ tri thức luôn mới

Không tài liệu nào đòi hỏi kỷ luật tài liệu hoá mới theo từng ticket từ bạn.

## 8.1 `-code` không cần bạn làm gì

`kb-code.yml` chạy lại `kb code-ingest` → `kb build` → `kb ci-publish` ở mỗi lần
push lên nhánh mặc định, nên nó luôn phản ánh commit hiện tại.

| Kích hoạt | Các bước | Có publish |
|---|---|---|
| push lên nhánh mặc định, hoặc chạy tay | code-ingest → build → ci-publish | có |
| pull request | chỉ build | **không bao giờ** |

`--scaffold-svc` cố tình không bao giờ được truyền trong CI. CI không được phép
tạo nội dung `pending`, vì như vậy sẽ làm fail chính bước build của nó.

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
| `kb code-ingest` thoát 1: không phát hiện gì | Chỉ có `tree` tìm được thứ gì đó | Kiểm tra xem file compose, manifest hay CI workflow có nằm đúng chỗ extractor tìm không; nêu `--db` nếu schema là thứ bạn cần |
| `kb code-ingest` thoát 1: từ chối đích đến | Có một tài liệu do người soạn đang nằm ở doc id đó | Chuyển nó đi, hoặc dùng `--doc-id` |
| `kb build` fail trên CI ở một section `-svc` | Một section `pending` đã bị commit | Hoàn tất bước seed: summarize, review, `kb approve` |
| `kb svc note`: "unknown service" | Không có `svc.<name>` tương ứng trong `-code` | Đối chiếu chính tả với output của `kb get <repo>-code`; một lỗi gõ không được phép bịa ra service |
| `kb publish` treo rồi fail và nhắc xem Actions | Dùng `kb publish` thường trên repo mà CI không có trigger theo tag | Dùng `kb publish --pr` |
| `kb ci-publish` bị từ chối | Repo này chưa có trong `federation/registry.yaml` của hub | Đề nghị người quản trị hub thêm vào |
| Cảnh báo `dirty_tree` | Có thay đổi chưa commit trong khi revision của manifest lấy từ HEAD | Vô hại khi chạy cục bộ; CI luôn chạy trên bản checkout sạch |
| `pr-lint` fail trên PR của Dependabot | Cổng này không tự bỏ qua một khi đã bắt buộc | Đúng như thiết kế. Hãy cân nhắc có giữ nó bắt buộc với PR của bot hay không. |
| Một trích dẫn báo `stale` giữa chừng | Hub đã publish sau khi ticket được viết | `kb diff`, rồi hỏi BA. Đừng tự diễn giải lại tiêu chí chấp nhận. |
| Không kết nối được MCP server | `STRATA_KB_HUB_URL` hoặc `STRATA_KB_HTTP_TOKEN` chưa đặt hoặc sai | Kiểm tra cả hai; xin token mới từ người quản trị hub |

---

# 10. Tóm tắt lệnh

| Lệnh | Mục đích | Mã thoát |
|---|---|---|
| `kb code-ingest [--db p] [--scaffold-svc] [--json]` | Trích cấu trúc code vào `-code` | `0` ok, `1` không phát hiện gì hoặc từ chối đích đến |
| `kb svc note <svc> --ticket <id> --title "…"` | Thêm một dòng vào `hist.<svc>` | `0` ok, `1` service không xác định hoặc thiếu tài liệu |
| `kb build [--strict]` | Kiểm tra kho | `0` ok, `1` lỗi |
| `kb approve <doc> [--section <id>]` | Chuyển các section đã sửa sang `reviewed` | `0` ok |
| `kb publish --pr` | Mở PR trên hub (lượt publish đầu của bước seed) | `0` ok |
| `kb resolve <file>` | Kiểm tra trích dẫn của ticket | `0` ok, `1` hỏng, `2` cũ |
| `kb diff <doc> --against <rev>` | Sửa đổi đã thay đổi những gì | `0` |
| `kb query <text>` / `kb get <doc> <section>` | Tìm và lấy nội dung | `0` |
| `kb pr lint <file>` | Cổng bằng chứng cho PR | `0` PASS, `1` FAIL |

**Slash command:** `/dev-implement-ticket`, `/dev-design`, `/dev-plan`,
`/dev-execute`, `/dev-handover`, `/dev-code-seed`.

---

# 11. Những tên được dành riêng

`<repo_id>-code` và `<repo_id>-svc` được dành riêng cho tri thức về code của
chính repository này. Một tài liệu nghiệp vụ tuyệt đối không được lấy một trong
hai hậu tố đó.

Tiền tố section là một hợp đồng đã công bố mà công cụ của BA và các công cụ tương
lai dựa vào. Mỗi tiền tố có đúng một chủ sở hữu:

| Tiền tố | Tài liệu | Chủ sở hữu |
|---|---|---|
| `struct.tree`, `svc.<name>`, `db.<table>`, `dep.<eco>`, `int.<name>`, `api.<tag>`, `cmd.<purpose>` | `-code` | extractor |
| `svc.<name>` | `-svc` | bạn (model soạn nháp) |
| `flow.<name>` | `-svc` | bạn |
| `hist.<name>` | `-svc` | chỉ `kb svc note` |

`svc.<name>` trùng nhau ở cả hai tài liệu **là có chủ đích**. Đó là khoá nối cho
phép một `Container(alias, label, technology, description)` trong C4 được điền từ
`-code` (ba tham số đầu) và `-svc` (tham số thứ tư).
