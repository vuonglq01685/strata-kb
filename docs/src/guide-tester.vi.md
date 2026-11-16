# 1. Tài liệu này dành cho ai

Bạn là người kiểm thử. Một story đến tay bạn khi các ticket Dev của nó đã xong và code đã
chạy trên môi trường test dùng chung. Bạn viết test case từ tiêu chí chấp nhận, viết script
Playwright cho chúng, chạy chúng, rồi publish báo cáo kết luận `PASS` hoặc `FAIL`.

Strata cho bạn ticket và cơ sở tri thức mà BA đã dùng làm nền, nơi khai báo môi trường test,
một khóa để hai vòng test không bao giờ dùng chung môi trường, và một trang trên hub hiển
thị mọi vòng. Một báo cáo `FAIL` mở lại story cho Dev. Một lỗi hồi quy trở thành bug
candidate cho BA. Bạn không bao giờ đụng vào code sản phẩm hay ticket.

| Repo tester có làm | Repo tester không làm |
|---|---|
| Đọc ticket và cơ sở tri thức đã publish | Sửa ticket, plan hay code sản phẩm |
| Viết test case, script Playwright và báo cáo | Ingest tài liệu từ bên ngoài repo |
| Publish một tài liệu, `<repo_id>-test` (hiện là Test Report trên hub) | Publish bất cứ thứ gì khác |
| Mở PR báo cáo; merge bằng tay (hoặc để chế độ auto merge, mục 4) | Tự chạy `kb publish` |

Mỗi repo BA có **một repo tester**. Kind của repo trên hub và role của tài khoản đều là
`tester`.

Các khái niệm dùng chung, như các lớp L0 đến L3 và trích dẫn `kb-context`, nằm trong
[tài liệu kiến trúc](architecture.vi.md). Phần của BA ở [hướng dẫn
BA](guide-ba.vi.md), phần của Dev ở [hướng dẫn Developer](guide-dev.vi.md).

**Slash command.** Repo tester có ba lệnh: `/tester-env-setup`, `/tester-strategy` và
`/tester-test-story`. Mỗi lệnh có cho Claude Code, GitHub Copilot và Cursor. Repo tester
không có `/kb-ingest`, `/kb-init` hay `/kb-auto`: chế độ auto chạy bằng CLI `kb auto`.

---

# 2. Thiết lập lần đầu

## 2.1 Cài đặt và dựng khung

```bash
pip install strata-kb
kb init --kind tester
```

`kb init --kind tester` ghi config, phần nối MCP (gồm server MCP `playwright`), ba slash
command, `playwright.config.ts`, một login fixture cùng smoke spec của nó trong
`tests/fixtures/`, các template (`docs/templates/test-cases.md`, `test-report.md`,
`test-strategy.md`), rubric review (`docs/test-review-rubric.md`, kèm bản ghi đè
`.local.md`), `.kb/test-env.example.yaml`, `.github/CODEOWNERS` và các workflow
(`kb-test-lint.yml`, `kb-test-stale.yml`, `kb-publish.yml`, `kb-publish-request.yml`).
Chạy lại an toàn: nó làm mới phần khung và gộp `.claude/settings.json`; file `*.local.md`
không bao giờ bị đụng tới.

## 2.2 Trỏ tới hub và đăng ký repo

Trong `.kb/config.yaml` điền:

```yaml
kind: tester
hub: https://github.com/your-org/kb-hub.git   # hoặc đường dẫn kb-hub cục bộ
repo_id: shop-test                            # phải bằng id của repo này trong registry
intake: https://kb.internal:8321              # cổng intake publish của hub
```

**Không bao giờ để token trong `hub:` hay `intake:`.** File này được commit. URL cần token
thì đặt trong biến môi trường `STRATA_KB_HUB`.

Nhờ người vận hành hub thêm repo này vào `federation/registry.yaml` với `kind: tester`. Để
dùng auto (mục 4), entry còn phải có `auto_merge: true`.

## 2.3 Kết nối trợ lý của bạn

`kb mcp-setup` ghi `STRATA_KB_HUB_URL` và `STRATA_KB_HTTP_TOKEN` vào `.env` (đã git-ignore).
Nạp file này rồi khởi động lại trợ lý. Repo tester dùng token cho API HTTP của hub: claim,
khóa môi trường, các lỗi đã biết.

## 2.4 Mô tả môi trường test: `/tester-env-setup`

Chạy `/tester-env-setup`. Nó dẫn bạn qua môi trường và ghi `.kb/test-env.yaml`.
`.kb/test-env.example.yaml` cho thấy hình dạng của nó:

```yaml
name: staging
apps:
  - repo: shop-fe
    url: https://staging.example.test
    version_check: { url: https://staging.example.test/version, field: commit }
db:
  url_env: TEST_DB_URL
  check: tests/seeds/check.sh
  reset: tests/seeds/reset.sh
  seeds: { checkout-basic: tests/seeds/checkout-basic.sh }
accounts:
  buyer: { user_env: TEST_BUYER_USER, password_env: TEST_BUYER_PASSWORD }
retries: 3
```

Quy tắc: file chỉ chứa **tên biến môi trường**. Giá trị nằm trong `.env` (đã git-ignore)
hoặc secret của CI. Script phải nằm trong repo, và `reset` từ chối production cùng các URL
được bảo vệ. Sau đó skill chạy `kb test-env check` (chỉ tên, không có giá trị trông như bí
mật) và `kb test-env verify` (mỗi URL app, `check` của DB, `reset`, seed, endpoint
version một dòng `ok` hoặc `FAIL`), điền login fixture bằng cách khám phá trang đăng nhập
qua Playwright MCP (không bao giờ gõ credential qua MCP), và đăng nhập một lần cho mỗi
tài khoản bằng smoke spec.

Mỗi app mang một `version_check`: một endpoint và trường chứa commit đang deploy.
`kb test-env deployed <story>` so nó với commit mà các PR Dev của story đã publish. Thiếu
`version_check` thì Tester phải tự xác nhận việc deploy bằng tay, và chế độ auto từ chối
khởi động.

## 2.5 Bật cổng PR

Job `lint` của `kb-test-lint.yml` lint test case, báo cáo và strategy trên mỗi PR. Hãy đặt
nó làm check bắt buộc trên nhánh mặc định, và thay `@OWNER` trong `.github/CODEOWNERS`.
Mục 4.1 giải thích lý do và có mẫu ruleset. Hãy làm dù bạn không bao giờ chạy chế độ auto.

---

# 3. Công việc hằng ngày

## 3.1 Test strategy: `/tester-strategy`

Chạy `/tester-strategy` trước story đầu tiên. Nó ghi `docs/test-strategy.md`: test cái gì
trước, test thế nào và vì sao, trong bảng **Priority order** (mỗi hàng một mission, story
hay vùng KB, kèm rank, mức rủi ro và lý do dẫn bằng chứng). Nó bám các hàng vào KB và
plan trên hub, ghi khối `## KB context`, lint
(`kb strategy lint docs/test-strategy.md --hub`), nhờ một reviewer ngữ cảnh mới đọc, rồi mở
PR. Bạn review và merge; merge sẽ publish nó thành section `strategy`.

Nó viết được chỉ từ tài liệu, trước khi có code hay môi trường. Khi chưa có
`.kb/test-env.yaml`, nó ghi các môi trường dự kiến, đánh dấu "not set up yet" và nhắc bạn
chạy `/tester-env-setup`. Strategy **không bao giờ chặn việc test**: story nào cũng được
test dù có hàng trong strategy hay không.

Khi hub dịch chuyển dưới strategy (ticket bị ghim lại, đích đổi tên, story chưa được phủ),
`kb test stale` báo ra, và `kb-test-stale.yml` giữ một issue gắn nhãn `kb-test-stale` luôn
cập nhật. Chạy `/tester-strategy --amend` để xử lý các phát hiện: mỗi phát hiện một thay
đổi, mỗi thay đổi do bạn duyệt, ghi thành một hàng trong `## Change log` của strategy.
Phát hiện `tc-revision` (test case chậm hơn revision của ticket) không phải thay đổi
strategy; `/tester-test-story` sẽ cập nhật test case.

## 3.2 Chọn story: `kb test next`

`kb test next` liệt kê các story có thể test theo thứ tự strategy (theo thứ tự plan khi
chưa có strategy), kèm tier, rank và cách test; có `--json` và `--all`. Story test được khi
mọi ticket của nó đã `done`, không ticket nào `reopened` hay `testing`, và bản thân story
chưa `closed`. Mã thoát `0` tìm thấy, `3` không có gì test được, `1` lỗi.
`/tester-test-story` không đối số sẽ chạy lệnh này, đề xuất story đầu tiên và hỏi bạn xác
nhận hoặc chọn story khác.

## 3.3 Test một story: `/tester-test-story`

`/tester-test-story <story>` chạy một vòng. Theo thứ tự:

1. Lấy ticket và kiểm tra story test được (chưa giữ gì cả).
2. Kiểm tra deploy (`kb test-env deployed`). Mã thoát `4` nghĩa là môi trường chưa chạy các
   commit đã publish: dừng, không giữ gì.
3. Khóa môi trường (`kb test-env lock`), nhận claim trên nhánh `test/<story>-R<n>`
   (`kb claim take`).
4. Khám phá các tiêu chí chấp nhận trong app bằng Playwright MCP, viết
   `tests/<story>/test-cases.md` (mỗi khối một TC, mỗi tiêu chí ít nhất một TC dương, thêm
   một TC âm hoặc biên khi tiêu chí nêu giá trị, và mọi luồng thay thế hay ngoại lệ) rồi
   lint bằng `kb testcase lint`.
5. Viết một script Playwright cho mỗi TC (locator theo role và text, không sleep cố định,
   mỗi test tự tạo dữ liệu của mình).
6. **Review Q1**: một `test-case-reviewer` ngữ cảnh mới đọc test case và script trước mọi
   lần chạy.
7. Chạy pipeline: preflight, chạy story, retry sạch trên DB đã reset (`retries` lần), xác
   nhận bằng MCP mọi lỗi ổn định, **chạy hồi quy** các story đã closed, và post-check các
   commit đã deploy.
8. Viết `reports/<story>/R<n>.md` (`kb report lint` đến khi thoát `0`), rồi **review Q2**
   bởi một `test-report-reviewer` ngữ cảnh mới.
9. Publish: `kb report-ingest`, commit `tests/<story>/` và `reports/<story>/`, push, rồi
   mở PR bằng `kb pr open`. Bạn merge bằng tay. Merge publish báo cáo qua workflow
   `kb-publish-request`. Skill không bao giờ chạy `kb publish`.

Claim và khóa được nhả khi dừng vì bất cứ lý do nào. Credential chỉ đến từ biến môi trường,
qua login fixture; không cái nào rơi vào test case, script, báo cáo, log hay PR.

**Kết quả của một vòng.**

| Kết quả | Khi nào | Hệ quả |
|---|---|---|
| `PASS` | mọi TC của story đạt, preflight và post-check sạch | báo cáo được commit |
| `FAIL` | có ít nhất một lỗi đã xác nhận (TC của story, hoặc hồi quy của story) | báo cáo được commit; story mở lại cho Dev |
| `INCOMPLETE` | không có lỗi, nhưng có TC flaky hoặc lỗi script | chỉ vào run log (`.kb/runlog/`); thử lại sau |
| `BLOCKED-ENV` | preflight hoặc post-check hỏng (môi trường đổi hoặc không khỏe) | chỉ vào run log; thử lại sau |

TC flaky (retry thì đạt) để tiêu chí đó ở trạng thái *chưa xác minh*, không bao giờ là
`PASS`. Script không bao giờ bị sửa trong lúc chạy một vòng: bản sửa vào vòng sau và đi lại
qua Q1.

## 3.4 Các vòng báo cáo

Một story được test theo vòng, `R1`, `R2`, v.v. Báo cáo `FAIL` nêu từng lỗi (`D<k>`) kèm
ticket con chịu trách nhiệm, các bước, kết quả mong đợi, kết quả thực và bằng chứng. Hub
đánh dấu ticket con đó `reopened`. Dev đọc báo cáo bằng `kb report fetch`, sửa, rồi bàn
giao; ticket con thành `fix-done` và story lại test được. Mỗi vòng mới chạy lại **toàn bộ**
TC của story, không chỉ những TC từng lỗi. Báo cáo `PASS` đóng story, và story đã đóng là
cuối cùng: không bao giờ test lại, chỉ được chạy như hồi quy.

## 3.5 Hồi quy và bug candidate

Khi mọi TC của story đạt, vòng test chạy các script của những story **đã closed**. Một lỗi ở
đó được đối chiếu trước với các lỗi đã biết trên hub (một key như `ST-0/TC-3` đang mở được
liệt kê là đã biết, không ghi lại lần nữa).

- **Hồi quy của story** là lỗi của chính story này: TC đã đạt ở baseline gần nhất (vòng
  `PASS` gần nhất trên môi trường này) **và** trang, route hay service bị lỗi ánh xạ tới
  một file mà các PR Dev của story đã đổi (`kb test-env changed`). Nó được đánh dấu
  `Regression: yes` và mở lại ticket con chịu trách nhiệm.
- Mọi trường hợp khác là **hồi quy bên ngoài**, ghi là `RD<k>`. Nó không ngăn story đóng.
  Nó trở thành **bug candidate** trên hub. BA soạn ticket bug từ đó, rồi Dev sửa.

Nghi ngờ luôn có nghĩa là hồi quy bên ngoài, không bao giờ mở lại theo phỏng đoán.

## 3.6 Menu Test Report

Trang **Test Report** của hub liệt kê mọi story cùng các vòng, kết luận và trạng thái suy ra
(`testing`, `reopened`, `fix-done`, `closed`). Bộ lọc: `all`, `testing`, `reopened`,
`closed`, `regression`, và các bug candidate đang mở. Ticket reopened có lỗi hồi quy mang
badge `regression`. Panel **Strategy** trên cùng trang hiện revision, các rank đầu và
badge `needs re-grounding` khi strategy đã lệch.

## 3.7 Giữ strategy và test case luôn mới

Chạy `kb test stale` bất cứ khi nào bạn muốn biết (mã thoát `0` không có gì, `2` chỉ có
cảnh báo, `1` có lỗi, và không bao giờ chặn việc test). Bám lại test case sau khi ticket đổi
revision là một phần của vòng `/tester-test-story` kế tiếp.

---

# 4. Các chế độ tự động

**Chế độ full-auto (tùy chọn).** Một công tắc trên repo `tester` cho phép nó tự test, trên
máy của Tester: chọn story, test, merge báo cáo, chọn story kế tiếp, cho đến khi không còn
gì để test. Không bước nào chờ con người: agent tự chạy các review của mình, sửa check đỏ
và merge. Khi công tắc tắt, không có gì thay đổi.

Auto của tester chạy trên máy của Tester, có Chromium. Nó **không** chạy trên Claude Code
cloud.

## 4.1 Bảo mật: đọc phần này trước

Hãy đọc mục này trước khi bật công tắc. Một lần chạy không người giám sát **tự merge các
pull request báo cáo và strategy của chính nó** khi check `lint` xanh, theo merge policy C:
check `lint` là bắt buộc, review của code owner là bắt buộc, và CODEOWNERS bao các đường
dẫn nhạy cảm. Không ai đọc báo cáo trước khi nó được merge. Một lỗi mà agent đánh giá sai
đi thẳng lên hub, mở lại ticket của Dev, hoặc đóng một story.

- **`Bash(kb pr merge*)` không còn bị cấm trong settings của tester.** Chế độ auto cần nó,
  nhưng trong repo tester `kb pr merge` từ chối trừ khi chạy bên trong `kb auto` (tiến
  trình task mang `STRATA_KB_AUTO_TASK=1`): một phiên **thủ công** nhận thông báo "kb pr
  merge in a tester repo runs only inside kb auto; merge the report PR on GitHub". GitHub
  mới là cổng thật: hãy thiết lập branch protection **ngay cả khi bạn không bao giờ chạy
  auto**. Dạng `--admin` của `kb pr merge` và `gh pr merge` vẫn bị cấm, và `gh pr merge*`
  vẫn bị cấm.
- **`kb publish` vẫn bị cấm.** Chính việc merge sẽ publish: workflow `kb-publish-request`
  gắn tag lên commit đã merge và publish qua intake của hub.
- Danh sách deny là phòng thủ nhiều lớp, không phải ranh giới. Runner không bao giờ dùng
  `--dangerously-skip-permissions` hay `bypassPermissions`.
- Working tree không bao giờ được đứng trên nhánh mặc định với commit trên đó. Các skill
  tạo nhánh trước; runner không canh việc này.

### Merge policy

`kb auto run` chỉ khởi động khi GitHub không cho agent merge nếu thiếu check bắt buộc và
review của code owner, và không cho nó vượt qua protection đó. Nó đọc các thiết lập qua
GitHub REST API bằng chính tài khoản của agent. Mỗi lý do từ chối kết thúc bằng
`see "Merge policy" in the Tester guide`, trỏ về đây.

**Điều gì phải đúng trên nhánh mặc định.**

- Check `lint` (job của `kb-test-lint.yml`) là status check bắt buộc.
- Review của code owner là bắt buộc. Review phê duyệt thì không:
  `required_approving_review_count` là `0`, nên một PR không đụng đường dẫn nào có code owner
  sẽ merge khi `lint` xanh. PR báo cáo test đụng `tests/` và `reports/`, PR strategy đụng
  `docs/test-strategy.md`: cả hai đều không có code owner.
- Các approval cũ bị hủy khi có commit mới được push (ruleset
  `dismiss_stale_reviews_on_push`; classic `dismiss_stale_reviews`).
- `.github/CODEOWNERS` tồn tại và không còn placeholder `@OWNER`.
- Chặn force push và xóa nhánh (khuyến nghị; `kb` không kiểm tra).

**Quy tắc danh tính.** Chỉ protection mà tài khoản không thể bypass mới được tính. **Ruleset**
chỉ được tính nếu `current_user_can_bypass` là `never` (khi GitHub bỏ trường này:
`bypass_actors` có mặt và rỗng). Bảo vệ nhánh **classic** chỉ được tính với tài khoản admin,
có `enforce_admins` bật và không có allowance bypass review pull request. Tài khoản
không phải admin chỉ có classic bị từ chối, nên bot không phải admin cần dùng **ruleset**.
Mọi lỗi đọc GitHub cũng bị từ chối (fail closed).

**Mẫu ruleset.** Settings, Rules, Rulesets, New branch ruleset (hoặc
`POST /repos/<owner>/<repo>/rulesets` bằng quyền owner):

```json
{
  "name": "main: merge policy",
  "target": "branch",
  "enforcement": "active",
  "conditions": { "ref_name": { "include": ["~DEFAULT_BRANCH"], "exclude": [] } },
  "bypass_actors": [],
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "require_code_owner_review": true,
        "dismiss_stale_reviews_on_push": true,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": false,
        "required_status_checks": [ { "context": "lint" } ]
      }
    }
  ]
}
```

**Bước của owner: CODEOWNERS.** `kb init` ghi `.github/CODEOWNERS` một lần và không bao giờ
ghi đè. Thay mọi `@OWNER` bằng một user hay team GitHub thật, commit vào nhánh mặc định, và
để người hay team đó review. GitHub bỏ qua rule có owner không tồn tại, nên placeholder
chưa thay không bảo vệ gì và lần chạy bị từ chối. **Owner không được là tài khoản của
agent**: GitHub không bao giờ cho tác giả PR tự phê duyệt.

**PR chờ con người.** CODEOWNERS bao `.github/CODEOWNERS`, `.github/workflows/`,
`.claude/settings.json`, `.claude/agents/`, `.claude/skills/`, `.claude/commands/`,
`docs/test-review-rubric.md` và `docs/test-review-rubric.local.md`. PR đụng một trong số đó
không merge được nếu thiếu review của owner, nên task kết thúc
`AUTO-RESULT: blocked-review <pr-url>`. Với một báo cáo, claim vẫn được giữ ở phase
`review` kèm PR, nên Tester khác không nhận story; runner nhả nó khi người merge hoặc đóng PR.

**Rủi ro còn lại.** Token admin vẫn sửa được ruleset. Chỉ allowlist quyền (không cho
`gh api`) ngăn agent làm vậy. Cách củng cố là dùng **danh tính bot không phải admin** với
ruleset nó không bypass được.

## 4.2 Thiết lập một lần

1. Plan của BA và các ticket Dev đã có trên hub, và `docs/test-strategy.md` tồn tại nếu bạn
   muốn có thứ tự theo strategy. Không có strategy thì auto test theo thứ tự plan. Auto
   **không bao giờ viết strategy mới**, chỉ amend strategy đã có.
2. `intake:` đã đặt trong `.kb/config.yaml`, và trang Registry của hub bật **auto-merge**
   cho repo này, để báo cáo đã merge được publish.
3. **Chromium.** Playwright và Chromium phải dùng được từ repo: `npx playwright install
   chromium`. Runner mở Chromium headless một lần để dò.
4. **`version_check`** trên mọi app trong `.kb/test-env.yaml`, và `/tester-env-setup` xanh
   (`kb test-env verify` thoát `0`). Thiếu nó, auto không xác nhận được việc deploy.
5. **Làm mới settings** (xem bên dưới).
6. Export `STRATA_KB_HUB_URL` và `STRATA_KB_HTTP_TOKEN`, và có CLI `claude` trong `PATH`,
   **đăng nhập bằng gói Claude subscription**. Runner không bao giờ dùng API key và kế thừa bất cứ đăng nhập nào `claude` đang có. Runner
   đọc claim của các Tester khác qua API của hub, nên hub phải truy cập được.
7. Giữ `main` làm nhánh mặc định; các skill chạy `git fetch origin`.
8. Thiết lập merge policy ở 4.1.

**Làm mới settings.** Repo tester dựng từ trước vẫn cấm `Bash(kb pr merge*)`. `kb auto run`
từ chối khi mục đó còn (`run kb init --kind tester to refresh the auto-mode settings`).
Chạy `kb upgrade` trong repo: nó chạy lại phần khung, bỏ mục deny đã lỗi thời, thêm các
allow mới (`git switch --detach origin/*`, `git ls-remote --heads origin *`), và mở PR trên
một nhánh mới; nó không bao giờ merge, và do người chạy (task auto không được phép).
`.claude/settings.json` có code owner, nên PR đó cần review của owner.
`kb init --kind tester` làm mới tại chỗ y như vậy; commit kết quả vào nhánh mặc định. Dù
cách nào, mục lỗi thời đó là mục duy nhất mà một lần làm mới gỡ bỏ.

## 4.3 Chạy và dừng

| Việc | Lệnh | Kết quả |
|---|---|---|
| Bật công tắc | `kb auto on` | in cảnh báo, bật `auto.enabled` |
| Commit | commit và push `.kb/config.yaml` và `.claude/settings.json` lên nhánh mặc định | `kb auto run` từ chối cho đến khi bạn làm |
| Chạy vòng lặp | `kb auto run` (`--once`, `--model`, `--effort`) | log ra terminal; chạy trong một phiên được giữ mở |
| Xem đang ở đâu | `kb auto status [--json]` | công tắc, task, số lần thử, lý do dừng |
| Dừng | `kb auto off` | dừng sau task hiện tại |

`idle_interval` (số giây chờ khi chưa có gì bắt đầu được, mặc định `600`) nằm trong khối
`auto:` của `.kb/config.yaml`. Repo tester không có lệnh `/kb-auto`: dùng CLI.

`kb auto run` từ chối, và in mọi lý do, khi:

- công tắc tắt, `.kb/config.yaml` hoặc `.claude/settings.json` chưa được track hoặc đang
  dirty, hoặc `auto.enabled: true` thiếu trong bản của nhánh mặc định;
- `intake:` trống, registry của hub không đọc được, không liệt kê repo này, hoặc thiếu
  `auto_merge: true` cho nó;
- merge policy chưa được GitHub áp dụng (4.1);
- đang chạy trên cloud;
- môi trường test chưa được verify (`run /tester-env-setup`), một app thiếu `version_check`,
  hoặc Playwright với Chromium không dùng được;
- settings vẫn cấm `Bash(kb pr merge*)`;
- API claim của hub chưa được đặt.

Mã thoát: `0` xong, `2` đã dừng, `1` bị từ chối hoặc lỗi, `130` bị ngắt.

## 4.4 Nó làm gì và khi nào dừng

Mỗi task một tiến trình `claude -p` mới. Runner chọn theo thứ tự:

1. **Claim mà máy này đang giữ** và vẫn đang làm (một lần crash để story dở giữa vòng): chọn
   lại đúng story đó. Bước kiểm tra crash của skill sẽ làm tiếp từ chỗ đó.
2. **Amend strategy** (`/tester-strategy --amend`), khi `docs/test-strategy.md` có trên nhánh
   mặc định và `kb test stale` báo phát hiện `broken-target`, `pin-moved`, `kb-context` hoặc
   `coverage`. `tc-revision` không phải task strategy.
3. **Story đầu tiên của `kb test next`** mà không Tester nào khác giữ (đọc qua API claim của
   hub), không đang nghỉ, và qua được kiểm tra deploy (`/tester-test-story <story>`). Story
   có kiểm tra deploy thoát `4` bị gác lại một khoảng idle, không tốn lượt chạy LLM nào.

**`/tester-test-story` ở chế độ auto.** Các bước như 3.3, với các cổng của con người được
thay thế:

- **Kiểm tra crash trước.** Đã `closed`, hoặc `reopened` với vòng mới nhất đã publish:
  `done`. PR báo cáo đã merge: nhả claim và `done`. PR còn mở từ lần crash: làm tiếp từ
  bước chờ check. Nhánh đã push mà chưa có PR: làm tiếp từ bước mở PR. PR bị người đóng mà
  chưa merge là cuối cùng (`failed report-pr-closed`).
- Cả hai review chạy bằng subagent. Khi không dispatch được, task kết thúc
  `failed test-review no-subagents`.
- **Luật merge.** Mở PR, theo dõi `kb pr checks --watch`; nếu đỏ thì đọc lỗi, sửa và push,
  tối đa 2 vòng (vẫn đỏ: `failed ci-red`). Khi xanh,
  `kb pr merge --squash --delete-branch`. Nếu merge bị từ chối vì thiếu review, claim ở lại
  phase `review` kèm `--pr` và task kết thúc `blocked-review`. Sau merge, workflow
  `kb-publish-request` publish báo cáo và claim được nhả.

**`/tester-strategy --amend` ở chế độ auto.** Ghim lại một hàng, trỏ lại đích đã đổi tên
hoặc tách, thêm hàng (hoặc hàng `last`) cho story chưa được phủ, làm mới `## KB context`,
căn chỉnh `.kb/test-env.yaml`, hoặc đổi rank, chỉ khi có bằng chứng được dẫn và reviewer
đồng ý. Auto không bao giờ bỏ một hàng: với đích hỏng mà nó không trỏ lại được, nó kết thúc
`failed broken-target <target>` và Tester quyết định. Mỗi thay đổi là một dòng
`**Auto decision:**` dưới `## Change log`, được reviewer ngữ cảnh mới kiểm tra; đổi rank bị
phản đối hai lần thì bị bỏ và chỉ được ghi lại. Ô Review của hàng change log bắt đầu bằng
`auto`. Nhánh là `auto/strategy` (`auto/strategy-r2`, ... khi đã dùng hết). Sau một lần
auto đổi rank, hub hiện badge `auto-reordered (rev N)` trên panel và trang Strategy cho đến
khi revision của một người xóa nó.

**Dòng kết quả.** Mỗi task kết thúc câu trả lời bằng một dòng, và không có gì sau nó:

| Dòng | Ý nghĩa |
|---|---|
| `AUTO-RESULT: done` | PR báo cáo đã merge, hoặc việc đã xong từ trước |
| `AUTO-RESULT: blocked-review <pr-url>` | merge cần review của người; vòng lặp gác nó lại và đi tiếp |
| `AUTO-RESULT: blocked-env <story> <reason>` | `env-locked`, `not-deployed`, `env-unhealthy` hoặc `claim-taken`; không phải thất bại |
| `AUTO-RESULT: incomplete <story>` | vòng test kết thúc `INCOMPLETE`; không phải thất bại |
| `AUTO-RESULT: failed <reason>` | mọi trường hợp khác; luôn kèm lý do |

Dòng thiếu hoặc sai định dạng tính là một lần thử thất bại.

**Khi nào chờ, khi nào dừng.**

| Tình huống | Kết quả |
|---|---|
| không có amend strategy đến hạn và không có gì test được | xong, thoát `0`, "nothing testable". Nó không chờ Dev sửa: chạy `kb auto run` lại sau |
| còn ứng viên, nhưng tất cả bị Tester khác giữ, đang nghỉ, hoặc chưa deploy | idle: ngủ `idle_interval` rồi chọn lại |
| `blocked-env ... env-locked` (vòng khác đang giữ môi trường) | idle `idle_interval`, trong lúc đó không thử story nào |
| mọi `blocked-env` khác | story đó chờ một `idle_interval`; story kế được thử ngay. Không tính lần thử nào |
| `incomplete` | tính riêng theo từng story (`attempts` của task không đổi); story chờ một khoảng để script của nó có vòng sau. Lần `incomplete` thứ hai của cùng story (`MAX_ATTEMPTS`, 2) gác nó lại kèm cảnh báo, và vòng lặp đi tiếp |
| mọi ứng viên đều bị gác lại (sau nhiều vòng `incomplete` hoặc PR báo cáo bị đóng) | dừng, nêu tên chúng |
| `failed test-review ...` | dừng ngay: một BLOCKER còn đứng sau vòng 2 và cần con người |
| `failed ci-red ...`, hoặc task thất bại `MAX_ATTEMPTS` lần | dừng |
| `blocked-review` | story được gác trong lúc người review; vòng lặp đi tiếp |

Story flaky không bao giờ dừng vòng lặp. Sau khi dừng, hãy sửa nguyên nhân rồi chạy lại
`kb auto run`: nó xóa danh sách story đã gác. Khi một bước cần lệnh ngoài allowlist, task
bỏ qua bước đó và nêu tên lệnh trong ghi chú của PR; muốn nó chạy, hãy thêm lệnh vào
`permissions.allow` trong `.claude/settings.json` bằng tay. Chờ hết hạn mức sử dụng không phải thất bại. Tiến trình
task mang `STRATA_KB_AUTO_TASK=1`, dưới biến này `kb auto on`, `off` và `run` từ chối
(`status` vẫn chạy).

Mỗi lần chạy task thêm một dòng vào `.kb/auto/runs.jsonl` (đã git-ignore). Một Stop hook
nhắc task một lần khi câu trả lời không kết thúc bằng dòng `AUTO-RESULT:` hợp lệ.

## 4.5 Claude Code cloud

Không hỗ trợ. `kb auto run` trong repo tester bị từ chối trên cloud: máy của Tester có
trình duyệt và môi trường test.

---

# 5. Xử lý sự cố

| Triệu chứng | Nguyên nhân và cách sửa |
|---|---|
| `kb test next` thoát `3` | không có gì test được: story cần mọi ticket `done`, không ticket nào `reopened` hay `testing`, và story chưa `closed` |
| `kb test next` thoát `1` | không có hub, hoặc plan của strategy không có trên hub; kiểm tra `hub:` và dòng `> Plan:` |
| `kb test-env deployed` thoát `4` | môi trường chưa chạy các commit đã publish; chờ deploy xong, hoặc sửa `version_check` |
| `kb test-env lock` thoát `3` | vòng khác đang giữ môi trường; khóa có TTL |
| `kb claim take` thoát `3` | Tester khác đang giữ story |
| `kb strategy lint` in `pin-moved` | ticket đã đổi; ghim lại hàng đó (`/tester-strategy --amend`) |
| Một vòng kết thúc `BLOCKED-ENV` | môi trường không khỏe hoặc commit đổi giữa vòng; kiểm tra rồi chạy lại story |
| Một vòng kết thúc `INCOMPLETE` | TC flaky hoặc lỗi script; sửa script ở vòng sau |
| `kb auto run` từ chối với `see "Merge policy" in the Tester guide` | thiết lập branch protection (4.1) |
| `kb auto run` từ chối vì settings của chế độ auto | chạy `kb upgrade` (4.2) |

---

# 6. Phụ lục

## 6.1 Khóa config và biến môi trường

| Khóa hoặc biến | Ý nghĩa |
|---|---|
| `kind`, `hub`, `repo_id`, `intake` | xem 2.2. Không bao giờ để token trong `hub:` hay `intake:` |
| `auto.enabled`, `auto.idle_interval` | chế độ auto; `idle_interval` là số giây chờ khi chưa có gì bắt đầu được (mặc định `600`). `auto.claim_heartbeat` không có tác dụng trong repo tester: runner không gửi heartbeat, các lệnh `kb claim update` của skill giữ claim còn mới |
| `.kb/test-env.yaml` | `name`, `apps` (`repo`, `url`, `api_base`, `version_check`), `db` (`url_env`, `check`, `reset`, `seeds`), `accounts`, `api_auth`, `retries`; chỉ có tên biến môi trường |
| chạy lại `kb init` | tạo file còn thiếu và làm mới file khung; `.kb/config.yaml` và `.claude/settings.json` được bảo vệ (`--force` ghi đè; `.claude/settings.json` còn lại thì được gộp); file `*.local.md` không bao giờ bị đụng |
| `STRATA_KB_HUB` | ghi đè `hub:`; mang URL có credential trong CI |
| `STRATA_KB_HUB_URL`, `STRATA_KB_HTTP_TOKEN` | URL HTTP gốc của hub và bearer token: MCP, claim, khóa môi trường, lỗi đã biết |
| `STRATA_KB_CLAIM_AS` | tên người giữ claim |
| `STRATA_KB_AUTO_TASK` | runner đặt trên tiến trình task; `kb auto on`, `off` và `run` từ chối dưới biến này |
| Biến tài khoản test | các tên trong `accounts:` và `db.url_env`; giá trị chỉ nằm trong `.env` hoặc secret của CI |

Mã thoát: `0` ok, `1` lỗi, `2` trích dẫn cũ (hoặc lỗi cách dùng), `3` claim bị người khác
giữ hoặc đã mất (hoặc môi trường đang bị khóa, hoặc không có gì test được với `kb test next`),
`4` chưa deploy (`kb test-env deployed`), `8` `kb pr checks` vẫn đang chờ.

## 6.2 Thư mục làm việc và phần bị git-ignore

| Đường dẫn | Chứa | Commit |
|---|---|---|
| `tests/<story>/test-cases.md`, `tc<NN>.spec.ts` | test case và một script cho mỗi case | có |
| `tests/fixtures/` | login fixture và smoke spec của nó | có |
| `reports/<story>/R<n>.md`, `assets/` | báo cáo vòng n và bằng chứng (PNG hoặc WebP) | có |
| `docs/test-strategy.md` | thứ tự ưu tiên, từ `/tester-strategy` | có |
| `tests/<story>/ticket.md` | ticket lấy từ hub | không, không bao giờ sửa |
| `.kb/runlog/` | run log của mỗi vòng, gồm cả `INCOMPLETE` và `BLOCKED-ENV` | không |
| `.kb/auto/`, `.kb/*-test/`, `.env` | trạng thái runner auto, index `-test` sinh ra, credential | không |
| `test-results/`, `playwright-report/` | đầu ra của Playwright | không |

## 6.3 Cái gì được ép buộc, cái gì chỉ được nhờ

| Quy tắc | Ép buộc bởi |
|---|---|
| Báo cáo có kết luận `PASS` hoặc `FAIL`, lỗi có bằng chứng, không lộ bí mật | `kb report lint` (job `lint` của CI) |
| Test case phủ mọi tiêu chí và luồng thay thế | `kb testcase lint` (job `lint` của CI) |
| Strategy có thứ tự, KB context và review đạt | `kb strategy lint` (job `lint` của CI) |
| Mỗi story một Tester; mỗi môi trường một vòng | claim và khóa môi trường trên hub (mã thoát `3`) |
| Story đã đóng không bao giờ test lại | bước 1 của `/tester-test-story` và trạng thái trên hub |
| Reviewer là subagent mới, không bao giờ là tác giả | chỉ văn bản của skill |
| Phiên thủ công không merge | `kb pr merge` từ chối trong repo tester ngoài `kb auto`; merge policy của GitHub mới là cổng thật |
| Auto merge cần `lint` xanh và review của code owner trên đường dẫn nhạy cảm | branch protection của GitHub, `kb auto run` kiểm tra |
| Không credential nào trong test case, script, báo cáo, log hay PR | login fixture, `kb report lint` và các reviewer |

## 6.4 Quyền của chế độ auto

`kb init --kind tester` gộp quyền của nó vào `.claude/settings.json` của bạn.
**Cho phép:** `git` hằng ngày (add, commit, status, diff, log, fetch, pull, `switch -c`,
`switch test/*`, `checkout -b`, branch, worktree, merge, `push -u origin HEAD`), các lệnh
chỉ đọc `git switch --detach origin/*`, `git ls-tree *origin/*`, `git show origin/*`,
`git ls-remote --heads origin *` và `git remote show origin`, `gh pr` và `gh run`,
`Read`/`Edit`/`Write`, các tool MCP `strata-kb` và `playwright`, `npx playwright test*`,
và các lệnh con `kb` mà skill dùng: `kb test-env`, `kb testcase`, `kb strategy lint`,
`kb test stale`, `kb test next`, `kb report`, `kb report-ingest`, `kb pr`, `kb claim`,
`kb ticket`, `kb mission`, `kb context`, `kb auto`. Một lệnh `curl` được phép đúng theo
dạng này: đọc `/api/tests/known-failures` của hub bằng bearer token.

**Cấm:** `kb publish`; `gh pr merge*`; dạng `--admin` của `kb pr merge` và `gh pr merge`;
`kb init` và `kb upgrade` (người chạy); mọi `git push` nêu `main` hay `master`, force-push,
refspec `+` và `:` và `--delete`; các dạng `git switch`, `checkout` và `branch` chuyển sang,
tạo, đổi tên hay xóa `main` hoặc `master`; `git switch` với `--discard-changes`, `--force`
hoặc `-f`; `git reset --hard`; `gh repo delete`, `gh run delete`; `rm -rf /*`; sửa
`.claude/settings.json`, `.claude/settings.local.json` và `.git/**`. `Bash(kb pr merge*)`
**không** bị cấm (chế độ auto merge bằng nó, và chính `kb pr merge` từ chối ngoài `kb auto`); lần làm mới settings của tester cũ gỡ nó khỏi
danh sách deny.

## 6.5 Quy tắc của hub liên quan tới bạn

Hub suy ra trạng thái từ báo cáo và claim đã publish, không bao giờ gõ tay: `testing` khi
một Tester đang giữ story, `reopened` sau một `FAIL`, `fix-done` khi Dev bàn giao, `closed`
sau một `PASS`. Claim có TTL được `kb claim update` làm mới; claim đang gác ở `review` hoặc
`publishing` được giữ không có TTL. Khóa môi trường có TTL, và chạy lại `kb test-env lock`
sẽ làm mới nó. Các tool mà skill của bạn gọi: `kb_search`, `kb_get_section`,
`kb_context_new`, `kb_resolve`, `kb_ticket_fetch`, `kb_report_fetch`.
