# Review toàn diện CENTER-KB v0.20.0 — chất lượng output từng bước và độ chính xác so với tiêu chí gốc

**Ngày:** 2026-09-08
**Đối tượng:** repo `D:\Projects\AERO-KB` @ `4b47b4c` (v0.20.0, `main`, working tree sạch). Review chỉ đọc; mọi thí nghiệm chạy trong thư mục scratch ngoài repo.
**Căn cứ tiêu chí:** `README.md`; `AERO-KB_Architecture_v0.4.pdf` §2.2 (mục tiêu đo được) và §3 (7 nguyên tắc); `docs/superpowers/specs/2026-07-10-aero-kb-phase1-design.md`; `2026-07-11-summarize-quality-design.md`; roadmap `docs/superpowers/reviews/2026-08-22-next-steps-roadmap.vi.md`. Rút thành 17 tiêu chí C1–C17 (phụ lục A).
**Phương pháp:** một lead định hướng + 8 reviewer độc lập chạy song song, mỗi người một vùng (A ingest, B summarize/build, C search/MCP/context, D federation/publish/CI, E BA gates, F dev workflow/usage, G code-ingest, H web/doctor/chất lượng kỹ thuật). Mọi finding đều kèm `file:line` và repro chạy được; báo cáo chi tiết từng vùng nằm trong phụ lục B.

---

## 0. Kết luận

**Về kỹ thuật, framework chạy ổn.** 1875 test pass, 0 fail, ruff sạch, không dùng thư viện mock (test chạy trên filesystem thật, git thật). Packaging đúng (sdist chỉ chứa `src/`, `.kb/` có bản quyền không thể lọt vào wheel). Release gate T0–T4 chạy thật trên CI với ma trận Windows. Bảo mật web ở phần escaping và traversal sạch tuyệt đối qua mọi probe. OIDC intake, tar hardening, cycle detection, republish idempotence đều đứng vững. Đây là một codebase kỷ luật hơn phần lớn dự án cùng cỡ.

**Về chất lượng output so với tiêu chí gốc thì chưa đạt ở đúng chỗ quan trọng nhất.** Tiêu chí gốc của framework là "L2 là bản cô đọng 20–30% văn xuôi, bảng giữ nguyên, không bịa, mọi trích dẫn trỏ đúng section". Trên chính KB mẫu đang ship trong repo:

- **L2 không cô đọng.** Tỷ lệ L2/L3 văn xuôi là 0.79 (arinc-424) và 0.75 (icao-annex-3). 325/325 section vượt guard 35%; 52 section L2 dài hơn cả bản gốc L3. Tiết kiệm token thật là 11.1%, không phải "≥90%" như mục tiêu §2.2.
- **L2 chép bảng thành văn xuôi và chép sai.** 44/90 section có bảng bị chép lại; §5.7 làm rơi mệnh đề ngoại lệ của mã `O`, §5.99 bịa ra mã `IM/MM/OM/BM` không có trong bảng gốc. `kb build` vẫn báo OK vì gate chỉ kiểm bảng L3 có mặt trong L2, không kiểm văn xuôi.
- **Nội dung bị gán nhầm section ngay từ ingest.** Trong KB đang ship, `## 5.83 To FIX` chứa định nghĩa của `§5.84 RUNWAY TRANS`; L2 của §5.83 tóm tắt nội dung RUNWAY TRANS. Một citation `[arinc-424:ch5 §5.83]` resolve `ok` về mặt kỹ thuật nhưng đưa cho Dev sai nội dung. Đây là điểm phá vỡ lời hứa cốt lõi "citation trỏ đúng section".
- **Không có bước nào phát hiện được ba điều trên.** `kb approve` không kiểm gì và chưa từng được chạy (329/329 section `summarized`, 0 `reviewed`). `kb doctor` không đọc lại heading L2/L3, không phát hiện trùng id, không phát hiện sửa nội dung trên hub. Gate DoR của BA chỉ kiểm sự hiện diện của heading: ticket toàn `TBD` vẫn PASS.

Ngoài ra có một lỗi chặn đường vận hành: **`kb_search` qua MCP stdio treo vĩnh viễn** ở mọi môi trường có `sqlite-vec` (extra `embed`, extra `dev`, và `.venv` của chính repo) vì import numpy native lười trên thread event-loop. Đây là lý do MCP server `center-kb` báo `CONNECTION_CLOSED` trong phiên review này. Cùng lớp: `kb get --level L3` (viết hoa) hoặc `--level verbatim` trả lặng lẽ L2 cô đọng với header y hệt.

Nói ngắn: **bộ khung vận hành (git, hub, CI, pin, resolve) là đúng và chắc; lớp kiểm soát chất lượng nội dung mà tiêu chí gốc yêu cầu thì mới có ở dạng prompt và tài liệu, chưa có ở dạng code.** Vì framework tự định vị là "single source of truth cho agent" trong domain hàng không, khoảng trống này là thứ cần đóng trước khi mở rộng thêm tính năng.

**Cần cải thiện gì:** ba đợt, xếp theo mức thiệt hại nếu không sửa. Đợt 1 (nội dung): sửa sectioner rồi re-ingest, re-summarize và approve lại KB mẫu; đưa quy tắc C2 vào `kb build`; sửa runner Copilot; kiểm bảng hai chiều. Đợt 2 (an toàn vận hành): registry gate cho `kb publish`, khoá ghi cho intake, không mirror `config.yaml`, không traceback, CRLF. Đợt 3 (tính chính xác của agent layer): kiểm nội dung trong `kb ticket lint`, ship E1/E2, sửa code-ingest, sửa tài liệu nói quá. Chi tiết ở §5.

---

## 1. Bảng điểm tiêu chí

Thang: **Đạt** / **Một phần** / **Chưa đạt**. Mỗi dòng có một câu lý do và mã finding trong phụ lục B.

| # | Tiêu chí (rút gọn) | Kết quả | Vì sao |
|---|---|---|---|
| C1 | Bảng không bao giờ bị AI viết lại; build fail khi lệch một ký tự | Một phần | Bản sao bảng được bảo vệ tốt (mọi đột biến nội dung đều bị bắt), nhưng check một chiều, mù với bảng bị nhân đôi hoặc bịa thêm, bảng một dòng bị bỏ qua; và không ngăn AI chép lại bảng thành văn xuôi phía trên (B-2, B-7). |
| C2 | L2 = 20–30% văn xuôi (guard 35%), giữ ngôn ngữ nguồn, mã verbatim, không bịa, không chép bảng | **Chưa đạt** | Tỷ lệ 0.79 / 0.75; 325/325 vượt guard; 44/90 chép bảng; 5 section có mã bịa. Trong 8 lời hứa con, đúng 1 (bảng verbatim) được máy kiểm (B-8, B-15). |
| C2 (L3) | L3 = bản gốc đầy đủ, không cắt | Một phần | Deny-list giữ được footnote, caption, công thức; nhưng nội dung gán nhầm id (§5.83 chứa §5.84), `5.15`/`5.139` biến mất, 7 section bị cắt giữa câu (A-F2, A-F3). |
| C3 | Sectioning theo id chuẩn, depth ≤ 3, 300–5000 token/unit, gộp < 200 | **Chưa đạt** | Heading nhiễu (caption, nhãn `Used On:`, COMMENTARY) thành section với 0 cảnh báo; 58% section ch5 < 200 token, chỉ 19.7% trong khoảng mục tiêu; quy tắc gộp không bao giờ chạy trên tài liệu lớn vì logic all-or-nothing theo parent (A-F1, A-F4). |
| C4 | Prompt chỉ văn xuôi, budget ký tự tường minh, ≤ 2 call, quá dài thì pending, `--redo` deterministic | Một phần | Prompt, budget, retry, `--redo` byte-identical trên 1281 dòng bảng: đúng. Nhưng sàn 300 ký tự biến guard thành 0.45× tổng thể (207/325 section bị sàn, tệ nhất 14.3×); trên Windows + Copilot prompt không tới được model (B-1, B-6). |
| C5 | Build fail khi pending/TODO/summary rỗng, fail khi lệch bảng, đếm lại token, cảnh báo L0 > 1000 | Một phần | Bốn hành vi nêu tên đều chạy đúng. Nhưng "summary rỗng" chỉ xét L1, body L2 bị xoá vẫn qua; gate bỏ lọt 8/24 đột biến adversarial; và build ghi đè manifest ngay cả khi fail (B-7, F-B). |
| C6 | Tag pre-filter → FTS5 + KNN → RRF → budget, không gọi AI, citation, "mọi section liên quan", cờ top-2 gần nhau, tiết kiệm ≥ 90% | Một phần | Pipeline, RRF, tag filter, không AI, tiết kiệm 97.7–98.8% so với đọc cả L3: đều verified. Nhưng cờ top-2 không bao giờ bật ở bản cài mặc định (0/14 truy vấn) và bật 9/10 khi có semantic; recall bị cắt cứng ở 50 trong khi docstring hứa "every relevant section"; budget chỉ tư vấn (`--budget 50` trả 246 token); truy vấn không ASCII bị băm thành rác và trả kết quả tự tin sai; sửa trực tiếp trên hub không bao giờ vào index (C-3, C-5, C-7, C-8, C-9). |
| C7 | Hub-first, mirror đầy đủ L0–L3, index tổng, một cổng review, multi-tier + cycle, không lan xoá | Một phần | Mirror, index, nested id, self-publish, cycle detection, idempotence: đều verified. Nhưng "một cổng review" là quy ước, không phải cấu trúc: hub non-GitHub bị push thẳng `main`; `kb reindex` commit cả cây; nội dung chưa merge đọc được giữa lúc publish; ai cũng publish được dưới tên repo khác (D-1, D-2, D-3, D-4, D-5). |
| C8 | Pin một commit hub, resolve ok/stale/broken exit 0/2/1, `kb doctor`/`kb diff` phát hiện amendment | Một phần | Exit code chính xác, stale phát hiện đúng sau amendment thật. Nhưng doctor bắt 12/19 hỏng hóc, crash traceback trên chính case nó có handler; `kb diff` bỏ qua title/thứ tự; README mô tả ngược hành vi diff; không có gì lên lịch chạy doctor nên "amendment detectable" chỉ đúng khi có người gõ lệnh (H-1, H-2, H-M9, H-M14). |
| C9 | Đúng 5 MCP tool, schema byte-identical với golden, stdio + HTTP | Một phần | Đúng 5 tool, snapshot byte-identical với `tests-gate/golden/mcp_tools.json`, `test_mcp_contract.py` xanh, 4 golden output khớp. Nhưng `kb_search` qua stdio **treo vĩnh viễn** khi `sqlite_vec` import được (mọi bản `[embed]`/`[dev]` và chính `.venv` của repo) vì import numpy native lười trên thread event-loop (C-1). Hợp đồng byte-perfect nhưng không trả lời thì chưa đạt. |
| C10 | BA gate: heading, story/AC/diagram, mermaid, KB-context resolve, citation hai chiều, tag, back-link, maturity review | Một phần | Nửa grounding (pin, ghost tag, version giả, back-link, MCP parity) rất chắc, không phá được. Nửa Dev-readiness chỉ kiểm sự hiện diện: ticket toàn `TBD` PASS; review record tự khai 5/5 với reviewer rỗng PASS; maturity review không có dòng code nào (E-H1, E-M3). |
| C11 | Dev workflow: grounding, 5 skill, TDD, 4 gate người, state trong file, E1/E2 | Một phần | Bộ khung CLI đúng; mọi quy tắc kỷ luật đều prompt-only trong khi QUICKSTART-dev nói "được enforce"; E1/E2 chưa xây (`prlint.py` không tồn tại); bounded path mất design khi session chết; C1 context cache không được validate (F-H1, F-H2, F-H3). |
| C12 | code-ingest deterministic, LLM-free, 7 extractor, keys-only, không `.env`, `-code` auto-mergeable | Một phần | Determinism và "keys only never values" đứng vững qua mọi tấn công. Nhưng tài liệu sinh ra trên chính repo này sai: `cmd.lint`/`cmd.run` sai do bug substring, `gate.sh`/tox vô hình, 86% cây thư mục là rác (29k token), schema `users` bịa do gộp migration khác thư mục; doc do người viết tại `<repo>-code` bị xoá âm thầm (G-1, G-2, G-3, G-4). |
| C13 | `kb svc note` idempotent, `-svc` không auto-merge | **Đạt** | Idempotent theo (ticket, service); desync bị bắt bởi cả `kb svc note` lẫn `kb build`. |
| C14 | Usage ledger: một dòng/call, phase attribution, giá đúng | Một phần | Dedup, phase, `_unattributed`, cost math đều đúng. Nhưng 11.5% call thật không có giá (`claude-fable-5-1`, `opus`/`sonnet` trần thiếu trong `usage-prices.yaml`); `est`/`assistant` không bao giờ được báo (F-M3, F-M4). |
| C15 | Không secret trong repo, redact credential, bearer + rate limit, intake hardening, lỗi sạch, Windows, UTF-8, sdist = src | Một phần | OIDC, tar, path safety, constant-time compare, XSS, traversal, sdist: xuất sắc. Nhưng `kb publish` mirror cả `.kb/config.yaml` (có token) lên hub; token nằm 0644 trong cache clone; cookie = raw token không `Secure`; 0 security header; rate limit chỉ ở login; traceback ở nhiều lệnh; `gate.sh` không chạy trên Windows; CRLF gây churn và false warning (D-6, D-7, H-3, H-M4, H-M5, H-M6). |
| C16 | Docs-as-code, re-init giữ state, approve, trip-wire test | Một phần | Re-init giữ config/settings/`*.local.md` byte-identical; trip-wire thật. Nhưng `kb approve` không kiểm, không ghi ai/khi nào/hash, bị `--redo` xoá, không gate gì phía sau; `--sections` re-ingest xoá chương khác và summary đã duyệt không hỏi; `review-rubric.md` bị ghi đè khi re-init (B-approve, A-F6, E-M5). |
| C17 | Release gate T1–T4, `gate.sh` = CI | Một phần | `_gate.yml` thật, T3/T4 chạy trên wheel đã tải, release pipeline thứ tự đúng. Nhưng `gate.sh` thiếu T0 lint, thiếu sdist smoke, thiếu tag assertion, không chạy trên Windows; workflow scaffold cài `center-kb` không pin trong job có `id-token: write` (D-13, D-14). |

### Đối chiếu mục tiêu đo được trong Architecture v0.4 §2.2

| Mục tiêu gốc | Thực tế đo được | Kết quả |
|---|---|---|
| Tiết kiệm ≥ 90% token; index < 1K | L0 = 187 token: đạt. Kết quả `kb query` trả về tiết kiệm 97.7–98.8% so với đọc cả L3: đạt. Nhưng bước cô đọng L2 chỉ tiết kiệm 11.1% (arinc-424) và 34.7% (icao-annex-3), nghĩa là phần tiết kiệm đến từ việc *chọn section*, không phải từ việc *cô đọng*; con số "≥99%" trong README là L0 so với raw. | Truy vấn đạt, L2 chưa |
| 100% ticket DoR có kb-context | Cơ chế bắt buộc có và chạy; nhưng "có kb-context" không đồng nghĩa "ticket đủ chất lượng" — ticket rỗng vẫn qua. | Hình thức đạt, nội dung chưa |
| Citation resolve đúng section + commit | `kb resolve` đúng id, đúng commit. Nhưng id đúng không bảo đảm nội dung đúng (§5.83 chứa §5.84). | Một phần |
| Amendment phát hiện được qua `kb doctor` | Phát hiện đúng khi chạy; không có scheduler, không có cron mẫu; doctor mù với sửa nội dung trực tiếp trên hub. | Một phần |
| Multi-repo | Federation mirror, nested, cycle: đạt. Cổng review không cấu trúc. | Một phần |
| Domain-agnostic, PyPI/Docker/gate/Windows | PyPI, Docker, CI gate: đạt. Windows: `gate.sh`, `check_package.py`, Copilot runner, CRLF, `demo-federation.sh` đều hỏng. Renderer web gộp bullet/code fence thành một đoạn, nên tài liệu có list sẽ mất cấu trúc. | Một phần |
| BA agent với DoR máy kiểm | Xem C10. | Một phần |
| Phase 5: code knowledge không bao giờ stale | Deterministic + CI wiring: đạt. Độ chính xác: chưa. `rel.<name>` và AST extractor mà v0.4 §14.1 hứa không tồn tại và không được ghi nhận là bỏ. | Một phần |

---

## 2. Chất lượng output từng bước

Đi theo đúng thứ tự pipeline. Mỗi bước: output là gì, đo được gì, sai ở đâu, vì sao không ai thấy.

### 2.1 `kb ingest` (Docling → sectioner → scaffold)

**Output tốt ở đâu.** Deny-list extraction giữ footnote, caption, công thức, list item. `uncovered()` bắt được text chưa đặt. L1 `_manifest.yaml` đúng một dòng một section, trip-wire `test_ingest_seam.py` khoá shape này.

**Sai ở đâu, trên KB đang ship.**

1. **Gán nhầm nội dung (A-F2, CRITICAL).** `sectioner.py:248-251` gắn body vào `stack[-1]` theo thứ tự xuất hiện trong trang; khi Docling trả heading theo thứ tự cột, `## 5.84 RUNWAY TRANS` bị cắt giữa câu và phần còn lại chui xuống `## 5.83 To FIX`. Bảng mã của §5.115 nằm dưới `## 5.115-x87 Enroute Airway Records`. 7 section bị cắt giữa câu. Không có cảnh báo nào.
2. **Heading không tiêu đề nuốt id (A-F3, HIGH).** `_NUMBERED_RE` tại `sectioner.py:81` gặp "5.15" không có title thì gán về id chương và ăn luôn đoạn text sau. Đây là lý do `5.15`, `5.139`, `5.155`, `5.156`, `5.158`, `5.159` không có trong manifest.
3. **Heading nhiễu thành section, không cảnh báo (A-F1, HIGH).** Caption bảng, nhãn `Used On:`/`Length:`, khối COMMENTARY thành section riêng; 10 id fallback `-xNN`. Cảnh báo duy nhất nằm trong nhánh không bao giờ chạy tới, và không có `logging.basicConfig` nên ngay cả khi chạy cũng không in ra.
4. **Quy tắc kích thước không hoạt động (A-F4, HIGH).** `_units_from_tree` (`sectioner.py:511-522`) gộp lá nhỏ theo kiểu all-or-nothing trên mỗi parent; chương 5 có 324 con nên luôn rơi về nhánh depth-fold. Kết quả: 58.2% section < 200 token, 80.3% < 300, chỉ 19.7% nằm trong 300–5000. Không có gì đo hay in phân bố này ra. Lưu ý spec tự mâu thuẫn ("mỗi field một section" đối chọi với "gộp < 200"), cần quyết bằng văn bản chứ không nên chỉ đổi code.
5. **`--sections` re-ingest xoá chương không được nêu tên (A-F6, MEDIUM)** cùng mọi L2 đã duyệt trong đó, không hỏi, không dry-run (`scaffold.py:62-63`). `crosscheck` chỉ báo thiếu bookmark, không báo thừa section (A-F5). Duplicate id vẫn tạo được và `kb get` lặng lẽ trả bản đầu (A-F7).

**Hệ quả dây chuyền.** Mọi lỗi ở đây đi thẳng xuống L2, xuống hub, xuống citation trong ticket, xuống code Dev viết. Vì ingest là bước duy nhất chạm bản gốc, đây là chỗ đáng sửa đầu tiên.

### 2.2 `kb summarize` (LLM headless)

**Output tốt ở đâu.** Prompt chỉ đưa văn xuôi (bảng bị thay bằng `[table omitted]`), budget ký tự tường minh, ≤ 2 call, quá dài thì `pending`. `--redo` byte-identical trên 1281 dòng bảng. Thiết kế đúng hướng.

**Sai ở đâu.**

1. **Copilot trên Windows không nhận prompt (B-1, CRITICAL).** `llm.py` truyền prompt qua argv `["copilot", "-p", prompt, ...]`; trên Windows `copilot` là `.CMD`, cmd.exe cắt ở newline đầu tiên nên model thấy đúng 58 ký tự: "You are filling in summaries for a knowledge-base section." Model tự bịa phần còn lại, section vẫn được đánh `summarized`, `kb build` OK. Runner `claude` đi qua stdin nên không dính.
2. **KB mẫu chưa từng được re-summarize theo spec (B-8, HIGH).** Spec 2026-07-11 quyết định #6 là chạy `--redo arinc-424` sau khi sửa prompt; quyết định này chưa bao giờ được thực thi. Tỷ lệ L2/L3 văn xuôi 0.785, 325/325 vượt guard, 52 section dài hơn gốc. README §10 vẫn bán con số 11.1% như "bằng chứng hoạt động". Reviewer B chạy `--redo` thật với stub tuân thủ budget: tiết kiệm lên 49.1% (L2 43566 token), `kb build` OK. Trần lý thuyết là 68% vì bảng chiếm 27% token L3, không phải "20–25%" như spec giả định.
3. **Chép bảng thành văn xuôi, có lỗi (B-2, CRITICAL).** 44/90 section có bảng bị chép lại. §5.7 rơi "except RNAV, RNP or Helicopter Airways" của mã `O`; §5.99 bịa `IM/MM/OM/BM`. Nguồn gốc nhiều khả năng là skill `kb-summarize` thủ công: sub-agent đọc L3 qua `kb get --level l3` nên thấy bảng, chỉ được *dặn* đừng dùng; còn engine thì xoá bảng vật lý khỏi prompt (B-16).
4. **Sàn 300 ký tự vô hiệu hoá guard (B-6, HIGH).** `_max_chars = max(300, 0.35 * len(prose))`: 207/325 section bị sàn, tệ nhất §5.320 có 21 ký tự văn xuôi được cấp 300 (14.3×). Tổng budget ÷ tổng văn xuôi = 0.45, không phải 0.35.
5. **`--redo` phá hoại (B-4, B-5, HIGH).** Cờ trần reset cả KB kể cả section `reviewed` trước khi gọi LLM; `rebuild_l2_scaffold` giữ heading và bảng, xoá luôn dòng `Figure:`.
6. **`_extract_reply` bỏ qua `is_error`** trong JSON của claude CLI (B-MEDIUM): lỗi API thành summary.

### 2.3 `kb build` và `kb approve`

**Output tốt ở đâu.** Fail đúng khi pending/TODO/L1 rỗng (kể cả TODO trong code fence), fail khi bảng L3 bị sửa nội dung, đếm lại token, cảnh báo L0 > 1000.

**Sai ở đâu.**

1. **Table check một chiều (F-B, B-7, HIGH).** Chỉ hỏi "mỗi bảng L3 có trong L2 không". Bảng bịa thêm trong L2, bảng nhân đôi, bảng một dòng (`extract_tables` cần ≥ 2 dòng), body L2 bị xoá, heading mồ côi, L3 sửa sau khi build: 8/24 đột biến adversarial đi qua.
2. **Không có quy tắc C2 nào trong build (B-15).** Tỷ lệ độ dài, ngôn ngữ nguồn, mã verbatim, không chép bảng: không cái nào được kiểm. Reviewer B chứng minh bốn check này viết được rẻ và bắt đúng (check "≥ 4 giá trị ô riêng biệt trong một câu L2" bắt trúng §5.7).
3. **Build ghi đè manifest như tác dụng phụ** (thêm `ingest: null`) ngay cả khi fail; lead đã vô tình làm bẩn repo khi chạy build trong lúc review.
4. **`kb approve` là trang trí.** Đổi `summarized → reviewed`, không kiểm gì (đã approve được một KB chứa bảng bịa), không ghi reviewer/thời điểm/hash L3, `--redo` xoá, `kb publish` ship `summarized` như thường. Trên repo: 329/329 `summarized`, 0 `reviewed`. Cổng SME mà kiến trúc mô tả hiện không tồn tại ở dạng máy kiểm.

### 2.4 `kb publish`, federation, intake, CI

**Output tốt ở đâu.** Mirror L0–L3 byte-identical (chỉ thêm `_meta.yaml`), index tổng deterministic, nested id `mid/repo:doc`, self-publish, cycle detection cả identity lẫn path, republish không tạo commit thừa, từ chối wipe federation rỗng. OIDC: issuer/audience/exp/nbf/`alg:none` đều 401 sạch, RS256-only. Tar: `..`, đường dẫn tuyệt đối, 60 MB, tar bomb 200 MB đều bị chặn. Release pipeline gate → docker-verify → PyPI → retag đúng thứ tự, permission tối thiểu theo job.

**Sai ở đâu.**

1. **Registry không gate `kb publish` (D-1, CRITICAL).** `federation/registry.yaml` chỉ được `intake.authorize()` đọc; `publish.publish()` và `publish_federation()` không gọi `load_registry`. Repro: `kb publish --repo-id victim` từ repo lạ xoá docs của victim trên hub và gán nội dung attacker cho `repo_id: victim` trong index. README (dòng 846, 606) và `deploy-remote-mcp.md:52` đều mô tả registry là cổng kiểm soát; workflow `kb-publish.yml` của chính repo dùng đường không gate này với một token dùng chung.
2. **Auto mode push thẳng `main` cho mọi hub không phải GitHub (D-2, HIGH).** `publish.py:228-234` chọn PR khi URL chứa chuỗi `github` và có `gh`; GitLab, Gitea, Bitbucket, self-hosted, hoặc máy không có `gh` đều thành direct push. README nói "chỉ local-path hub".
3. **Intake dùng một working tree cho cả đọc và ghi (D-3, D-4, HIGH).** Giữa lúc publish, `kb query`/REST/UI trả nội dung của branch `publish/<rid>` chưa merge. Hai publish khác rid chạy song song: PR của beta có base là `publish/alpha`, mang theo nội dung alpha chưa duyệt, và clone bị kẹt ở `publish/alpha` vĩnh viễn nên phía đọc phục vụ branch chưa merge cho đến khi có người checkout `main` bằng tay.
4. **`kb reindex` commit cả cây `federation/`** dưới message "rebuild index" (D-5, HIGH), kể cả file bị sửa tay và thư mục lạ; các đường lỗi của chính publish để lại cây bẩn nên đây không phải giả định.
5. **Publish mirror mọi file dưới `.kb/`** (D-6, HIGH): `config.yaml` với URL `x-access-token:…` mà tài liệu hướng dẫn điền, và `.kb/.env` lạc, đều được commit lên hub. Token cũng nằm 0644 trong `~/.center-kb/hub/<hash>/.git/config`, cache key dẫn xuất từ URL có token nên rotate token để lại clone cũ (D-7).
6. **Repo-id alias trên host case-insensitive** (`VICTIM`, `victim.`, `CON`) đè lên sibling và push index lệch với cây (D-8). Traceback thay vì lỗi sạch khi repo-id 300 ký tự hoặc `gh pr create` fail sau khi đã push (D-9). `demo-federation.sh` fail ở bước 3 trên Windows vì `mktemp -d` trả đường dẫn MSYS.
7. **CRLF (D-10, H-3).** `gitio.clone` không đặt `core.autocrlf=false` (intake thì có, `intake.py:239`); với mặc định Git for Windows, clone hub mới làm mọi file trông như đã đổi: doctor báo false "run `kb publish`", publish tạo hai commit trùng nội dung, và PR mode bắt SME review diff chạm mọi file.
8. **Asset store**: sha256 trong tên file không bao giờ được hash-verify lại; `kb assets verify` chỉ kiểm tồn tại; UI cache byte sai với `immutable` một năm (D-11).

### 2.5 `kb query`, MCP, kb-context, `kb resolve`

**Output tốt ở đâu.** Hub-only đọc được chứng minh thực nghiệm: doc chưa publish với marker riêng không bao giờ lộ qua `kb_search`/`kb_get_section`. Doc id trùng giữa hai repo bị từ chối kèm hai lựa chọn đủ tiêu chuẩn. `kb resolve` trả đúng byte đã pin trong mọi case đột biến (10/10), exit 0/1/2 và parity với `kb doctor --context` chính xác; CRLF trên clone không gây false-stale; cache bị xoá thì tự clone lại. FTS injection vô hiệu. Tách token đối xứng cho `/`, `.`, `-`, `§` nên `CUST/AREA`, `ARPT/HELI IDENT`, `§5.129` đều tìm đúng. Hiệu năng: build lạnh 1.05 s cho 332 section, truy vấn ấm 21 ms. Battery 40 truy vấn: tên field chính xác và viết tắt có dấu câu đạt rank 1 gần như tuyệt đối (21 ✔, 2 ~, 9 ✘, 8 probe nhiễu).

**Sai ở đâu.**

1. **`kb_search` qua MCP stdio treo vĩnh viễn (C-1, HIGH, chặn vận hành).** `searchdb._load_vec()` import `sqlite_vec` lười lúc nhận request (`searchdb.py:76`); `sqlite_vec` kéo numpy native; FastMCP chạy tool sync ngay trên thread event-loop; import native ở đó deadlock trên Windows. Repro 4 lần, 120 s không trả lời, stack `faulthandler` dừng trong `numpy/_core/multiarray.py`. Pre-import numpy lúc khởi động thì trả lời trong 0.0 s. Phạm vi: mọi môi trường có `sqlite-vec` (extra `embed`, extra `dev`, `.venv` của repo). Đây chính là lý do MCP server `center-kb` báo `CONNECTION_CLOSED` trong phiên review này, và là lý do `test_golden_output.py` treo.
2. **`kb get --level L3`/`verbatim`/`raw` trả L2 cô đọng không cảnh báo (C-4, HIGH).** `query.py:261` chỉ so sánh đúng chuỗi `"l3"`; CLI không validate `level` (MCP thì có). Header giống hệt nên người gọi không thể phân biệt. Trong một KB mà tiền đề là "L3 verbatim, L2 không", đây là thay thế lặng lẽ nguy hiểm nhất phía CLI.
3. **Sửa trực tiếp trên hub không bao giờ vào index (C-3, HIGH).** `_repo_fingerprint` chỉ hash `_meta.yaml` + `index.yaml`, hai file chỉ đổi khi child publish. Reviewer sửa typo ngay trong `federation/` và commit trên hub: `kb get` thấy, `kb query` không; `kb reindex` báo "already consistent", `kb doctor` OK. Chỉ xoá `search.db` mới hết.
4. **Build index lạnh đồng thời tự phá index (C-2, HIGH).** 5 process `kb query` cùng lúc trên hub chưa có `search.db`: 3/5 fail, 3/3 lần thử. `UNIQUE constraint` bị `query.py:125-132` coi là corrupt và `delete_db`, rồi `PermissionError [WinError 32]` traceback vì process khác đang giữ file. Comment trong code nói "losing the race only wastes work, never corrupts data" là sai.
5. **Cờ top-2 gần nhau không bao giờ bật mặc định (C-5, HIGH).** `_ambiguity_note` đòi cả hai hit đều `hybrid` hoặc tie tuyệt đối; không có `fastembed` thì không có KNN nên 0/14 truy vấn bật, kể cả case `aero:arinc-424 §5.129` vs `beta:arinc-424 §5.129` mà BA cần được cảnh báo. Có cả hai leg thì bật 9/10, kể cả truy vấn rõ ràng. Golden đã đóng băng hành vi không bật.
6. **Resolve: section bị xoá, đổi số, hoặc cả doc bị xoá đều báo `stale` (exit 2), không `broken` (C-6, MEDIUM).** CI coi "section chuẩn không còn tồn tại" ngang với "sửa một câu". Hint `kb diff` sau khi doc bị xoá dẫn vào ngõ cụt.
7. Recall cắt cứng `K_LEG = 50` không báo (`record`: 154 khớp, trả 50) (C-7); `--budget` luôn nhận hit đầu tiên dù vượt 4.9× (C-8); `tokenize` chỉ `[a-z0-9]+` nên "đường băng sân bay" thành `ng b ng s n bay` và trả 2 kết quả tự tin (C-9); 40k `tags` từ tool call làm `delete_db` index dùng chung (C-10); `SEMANTIC_MIN_SCORE = 0.6` chưa từng đo, stub embedder cho 0 hit qua ngưỡng (C-11); số section trần `5.7` không vào top 3, không có typo tolerance (C-12).
8. Tag trong kb-context dẫn xuất theo *document*, nên block hai doc mang nguyên bộ từ vựng 10 tag của cả federation, dòng `tags:` không mang thông tin (C-15). README §7.5 mẫu output đã lỗi thời (`score=` không còn, citation luôn có `repo:`) (C-13). Index `.kb-work/search.db` nằm untracked trong worktree hub và không có `.gitignore` scaffold nào che (C-17).

### 2.6 BA gates (`kb ticket lint`, `kb mission lint`, maturity review)

**Output tốt ở đâu.** Pin một commit hub, ghost tag bị từ chối kèm gợi ý, version giả bị bắt, stale phát hiện sau amendment thật, back-link mission, parity CLI/MCP, `--json` envelope đúng, agent không bao giờ đẩy Jira. Reviewer E không phá được nửa grounding.

**Sai ở đâu.**

1. **Dev-ready by construction chưa có (E-H1, HIGH).** Gate chỉ kiểm heading có mặt; story `As a x, I want y, so that z`, AC là một `- [ ]`, mermaid fence rỗng, mọi mục `TBD`: PASS. Ticket giả với `## Review record` tự khai 5/5 và reviewer rỗng: PASS. Maturity review không có dòng code nào (`review.py` chính là `kb approve`).
2. **Bug text-scanner (E-H2, E-H3, E-H4).** `check_headings` mù HTML comment: comment 4 heading bắt buộc vẫn PASS. `section_body` không nhận biết code fence: `#` trong fence gây FAIL giả. `INLINE_CITE_RE` bắt nhầm "ARINC 424 §5.129" trong văn xuôi ở mức error. Block `## KB context` thứ hai bị bỏ qua (E-M1).
3. **Tài liệu sai hợp đồng (E-M2).** QUICKSTART-ba nói CI enforce stale và reverse citation; thực tế stale là warning và `kb ticket lint` gộp stale về exit 0.
4. AC quality là deny-list 23 từ có một token `OPEN(` tắt toàn bộ (E-M4); `kb init` re-run ghi đè `review-rubric.md` mà framework bảo BA tinh chỉnh (E-M5); `kb-ticket-lint.yml` cài pip không pin (E-M6).

### 2.7 Dev workflow, conventions, usage

**Output tốt ở đâu.** Grounding, 4 gate người, design/plan resumable, C1 cache, conventions pack, `kb svc note` (C13 đạt), re-init giữ state (C16 đạt), usage dedup tránh 87.9% inflation, cost math đúng.

**Sai ở đâu.**

1. **Mọi quy tắc cứng đều prompt-only (F-H1, HIGH)** trong khi QUICKSTART-dev mục "What is enforced" nói quá. E1 (PR description gate) và E2 (named TDD exemptions) đã có spec và plan trong hai commit gần nhất nhưng chưa xây.
2. Bounded/spike path mất design khi session chết (F-H2); C1 context cache không validate, gitignored, không review được (F-H3).
3. **Giá thiếu (F-M3).** 11.5% call thật không có giá vì `usage-prices.yaml` thiếu `claude-fable-5-1` và alias trần `opus`/`sonnet`; `est`/`assistant` không bao giờ được báo (F-M4). Hint của `kb resolve` gợi dùng `kb diff` mà workflow Dev cấm.
4. Conventions preset tự mâu thuẫn (Java 4-space vs google-java-format 2-space; ruff thiếu T20/N); `detect_langs` bỏ sót monorepo depth-3 nên không sinh CLAUDE.md.

### 2.8 `kb code-ingest`

**Output tốt ở đâu.** Byte-identical qua nhiều lần chạy, ~7 s trên repo 10k file, không LLM, không mạng. Zero rò rỉ giá trị qua mọi tấn công mapping/list/YAML/k8s/OpenAPI. `.env` thật vô hình. SQLite chỉ qua `--db`. `dirty_tree` cảnh báo đúng. 12 manifest hỏng + 2 binary đều thành warning có tên, không traceback.

**Sai ở đâu, trên chính repo này.**

1. **Doc do người viết tại `<repo>-code` bị xoá không cảnh báo (G-1, CRITICAL)**, `core.py:445`; summary trong index của doc cũ được giữ đè lên nội dung sinh.
2. **`_classify` bug substring (G-2, HIGH)**: `cmd.lint`/`cmd.run` sai, `gate.sh` và tox vô hình. `struct.tree` không đọc `.gitignore`: 86% là rác, 29k token L3 (G-3). Gộp migration từ các thư mục khác nhau thành một schema `users` không tồn tại (G-4). Optional deps bị bỏ (G-5). Workspace `package.json` cho services chưa làm (G-6).
3. L2 lớn hơn L3 ở 6/7 section nên latch C1 vô hiệu; `--kb-dir` tương đối resolve theo `--repo-root` nên tạo nhầm thư mục trong repo (đã xảy ra trong review); glob phân biệt hoa thường khác nhau Windows/Linux nên "byte-identical cùng commit" chỉ đúng cùng máy (G-12); `kb-code.yml` không pin (G-9).

### 2.9 Web UI/API, `kb doctor`, `kb diff`

**Output tốt ở đâu.** Mọi XSS probe (prose, ô bảng, Figure, heading, title manifest, title L0, tên tag) đều escaped; `mdrender.py` viết tay không có cú pháp link nên không có bề mặt `javascript:`; `app.js` không có sink `innerHTML`. 10/10 traversal → 404. Constant-time compare cả header lẫn cookie; token không nhận qua query string; lỗi 500 không lộ traceback. Exit code doctor `--context` 0/2/1 chính xác. `utf8io` hoạt động dưới pipe.

**Sai ở đâu.**

1. **Doctor crash trên chính case nó có handler (H-1, HIGH).** `cli.py:1805` gọi `_hub_or_exit` trước `check_kind`, nên `config.yaml` sai `kind` hoặc YAML hỏng ném `ValidationError`/`ParserError` traceback; nhánh "config.yaml is invalid" trong `doctor.py:120` không bao giờ chạy tới. `kb publish` và `kb status` cùng lớp lỗi với manifest hỏng.
2. **README mô tả ngược `kb diff` (H-2, HIGH).** README:449 nói sửa L2-only không hiện trong diff; `diff.py:101` và test đều báo `(prose)`. Đây là spec duy nhất của bước 4 trong Dev flow.
3. **Doctor bắt 12/19 hỏng hóc (H-M9).** Bỏ qua: duplicate id, heading L2 mồ côi, `tokens:` stale, `.raw.md` mới hơn `.md`, key manifest gõ sai (`sumary:` khiến mọi summary thành `""` mà vẫn OK vì model không `extra="forbid"`), sửa nội dung đã publish trên hub.
4. **HTTP**: cookie chứa raw bearer token, không `Secure`, không expiry, không logout (H-M4); 0 security header (H-M5); rate limit chỉ ở login và intake, 10 hit `/api` sai token không 429 (H-M6); limiter theo peer IP nên sau reverse proxy cả tổ chức chung một bucket (H-M7); manifest federation hỏng → 500 trần (H-M8).
5. `kb diff` không so title/thứ tự (H-M14); exit code 2 vừa là "stale" vừa là usage error ở 9 chỗ (H-M11); `mdrender` gộp bullet và code fence thành một `<p>` (H-M18).

### 2.10 Chất lượng kỹ thuật chung

- **Test:** 1875 pass / 5 skip / 0 fail / ~548 s; 3960 assert trên 1805 test; đúng một test không có assert (cố ý); không có `unittest.mock` ở đâu cả. Đây là điểm mạnh thật.
- **Lint:** ruff sạch nhưng chỉ chạy bộ mặc định `E4/E7/E9/F`; 11 marker `# noqa: BLE001` vô tác dụng vì `BLE` không bật (H-L28).
- **Kiến trúc code:** `typer.echo` chỉ trong `cli.py`, logging trong thư viện, một `_hub_or_exit` dùng chung cho 11/12 lệnh hub. Điểm yếu: `cli.py` 1871 dòng giữ ~505 dòng orchestration không module nào sở hữu, trong đó có 3/4 `except Exception` im lặng và cả H-1 lẫn M13.
- **Tài liệu nói quá hoặc sai:** README "20 commands" (thực ~25), "four tools" (thực 5), §10 11.1% là bằng chứng, dòng 449 về diff, dòng 479 về auto mode; QUICKSTART-dev "What is enforced"; QUICKSTART-ba về CI; `federation/README.md` scaffold vẫn mô tả layout slim trước 0.9 (D-15); `hub.resolve_hub` docstring nói hub là "enhancement, not a hard requirement" (L20).

---

## 3. Findings tổng hợp theo mức độ

Chỉ liệt kê CRITICAL và HIGH ở đây; MEDIUM/LOW nằm đủ trong phụ lục B.

### CRITICAL

| Mã | Vùng | Finding | Bằng chứng |
|---|---|---|---|
| A-F2 | ingest | Body gán nhầm section: §5.83 của KB đang ship chứa định nghĩa §5.84 | `sectioner.py:248-251`; `.kb/arinc-424/ch5-*.raw.md` |
| B-1 | summarize | Copilot trên Windows: prompt cắt ở newline đầu, model thấy 58 ký tự, section vẫn `summarized` | `llm.py` `cmd = [executable, "-p", prompt, ...]` |
| B-2 | summarize | L2 chép bảng thành văn xuôi có lỗi ở 44/90 section (§5.7 rơi ngoại lệ, §5.99 bịa mã), build OK | `.kb/arinc-424/ch5-*.md` §5.7, §5.99 |
| D-1 | publish | `federation/registry.yaml` không gate `kb publish`; bất kỳ ai publish được dưới `--repo-id` của repo khác, xoá docs và gán nhầm index | `publish.py:207-334` không gọi `load_registry` |
| G-1 | code-ingest | Doc do người viết tại `<repo>-code` bị xoá không cảnh báo | `codeingest/core.py:445` |

### HIGH

| Mã | Vùng | Finding |
|---|---|---|
| C-1 | MCP | `kb_search` qua stdio treo vĩnh viễn khi `sqlite_vec` import được; nguyên nhân `CONNECTION_CLOSED` của server trong phiên này |
| C-4 | query | `kb get --level` khác đúng chuỗi `l3` trả L2 cô đọng, header y hệt, không cảnh báo |
| C-3 | query | Sửa trực tiếp trên hub không bao giờ vào index; `kb reindex` và `kb doctor` đều nói OK |
| C-2 | query | Build index lạnh đồng thời: `UNIQUE constraint` bị coi là corrupt → xoá index → `PermissionError` traceback, 3/5 process fail |
| C-5 | MCP | Cờ "top-2 gần nhau" không bao giờ bật ở bản cài mặc định (0/14), golden đóng băng hành vi này |
| A-F1 | ingest | Heading nhiễu thành section, 10 id `-xNN`, 0 cảnh báo (nhánh warning không bao giờ chạy) |
| A-F3 | ingest | Heading số không title nuốt id: `5.15`, `5.139`, `5.155`, `5.156`, `5.158`, `5.159` biến mất |
| A-F4 | ingest | Quy tắc gộp < 200 và mục tiêu 300–5000 vô hiệu trên tài liệu lớn: 58% < 200, 19.7% đạt |
| B-6 | summarize | Sàn 300 ký tự làm guard thành 0.45× tổng thể; 207/325 section bị sàn |
| B-7 | build | Table check một chiều; 8/24 đột biến qua gate; body L2 rỗng qua gate |
| B-8 | summarize | KB mẫu chưa re-summarize theo spec; 0.785 ratio; `--redo` thật cho 49.1% |
| B-4/B-5 | summarize | `--redo` trần reset cả `reviewed`; `rebuild_l2_scaffold` xoá dòng `Figure:` |
| D-2 | publish | Auto mode direct push `main` cho mọi hub không phải GitHub |
| D-3/D-4 | intake | Phía đọc phục vụ branch chưa merge giữa lúc publish; publish song song khác rid làm hỏng base PR và kẹt clone vĩnh viễn |
| D-5 | hub | `kb reindex` commit cả cây `federation/` |
| D-6 | publish | Mirror `.kb/config.yaml` (có token) và dotfile lạ lên hub |
| E-H1 | BA | Ticket toàn `TBD` PASS; review record tự khai PASS; maturity review không có code |
| E-H2/H3/H4 | BA | `check_headings` mù HTML comment; `section_body` không fence-aware; `INLINE_CITE_RE` false positive mức error |
| F-H1 | dev | Mọi quy tắc kỷ luật prompt-only; QUICKSTART-dev nói quá; E1/E2 chưa xây |
| F-H2/H3 | dev | Bounded path mất design khi session chết; C1 cache không validate |
| G-2/G-3/G-4 | code-ingest | `_classify` sai `cmd.*`; tree không đọc `.gitignore` (86% rác); schema `users` bịa do gộp migration |
| H-1 | doctor | Traceback trên `config.yaml` sai; handler của doctor không bao giờ chạy tới |
| H-2 | docs | README mô tả ngược hành vi `kb diff` |
| H-3/D-10 | Windows | CRLF: doctor false warning vĩnh viễn, publish churn hai commit, PR review chạm mọi file |

---

## 4. Vận hành đã thực sự ổn chưa?

Trả lời thẳng theo từng vai trong kiến trúc.

- **Người vận hành hub:** chưa ổn. Cổng review là quy ước; ai có token là publish được dưới tên bất kỳ; reindex có thể commit nội dung bẩn; không có gì chạy `kb doctor` định kỳ; credential lọt lên hub và nằm 0644 trong cache. Cần đợt 2 trước khi mở hub cho nhiều repo thật.
- **SME:** chưa ổn. `kb approve` không giúp SME kiểm gì, không ghi lại gì; PR review trên Windows có thể là diff toàn file vì CRLF; KB mẫu chưa có một section nào `reviewed`.
- **BA:** ổn về grounding, chưa ổn về chất lượng ticket. Gate bắt được ticket trỏ sai, không bắt được ticket rỗng; tài liệu hứa CI enforce nhiều hơn thực tế.
- **Dev:** ổn để dùng qua CLI, với điều kiện hiểu rằng TDD và 4 gate là kỷ luật của skill, chưa phải của máy; citation `ok` không đồng nghĩa nội dung đúng cho đến khi KB mẫu được re-ingest; và `--level` phải gõ đúng `l3` thường. Qua MCP thì chưa ổn: `kb_search` treo trên mọi môi trường có `sqlite-vec`.
- **Agent tìm kiếm:** ổn với tên field và viết tắt chuẩn; yếu với số section trần, câu hỏi tự nhiên, lỗi chính tả và mọi ngôn ngữ không ASCII, đúng những chỗ mà semantic leg (mặc định tắt) được thiết kế để cứu.
- **Người dùng Windows:** chưa ổn. Copilot runner, `gate.sh`, `check_package.py`, `demo-federation.sh`, CRLF đều hỏng dù README cam kết Windows đầy đủ. CI có ma trận Windows nên test pass, nhưng đường vận hành thủ công thì không.

---

## 5. Đề xuất cải thiện, xếp ưu tiên

### Đợt 1 — Đúng nội dung (điều kiện để framework giữ được lời hứa cốt lõi)

1. **Sửa sectioner rồi tái tạo KB mẫu.** Gắn body theo id heading thay vì `stack[-1]` theo thứ tự trang (A-F2); xử lý heading số không title bằng cách giữ id và đánh dấu `title: ""` thay vì gộp về chương (A-F3); đưa cảnh báo fallback id ra được (thêm `logging.basicConfig` trong CLI hoặc in trực tiếp); in phân bố token/section cuối `kb ingest` (A-F4). Quyết định bằng văn bản mâu thuẫn "mỗi field một section" và "gộp < 200". Sau đó: re-ingest arinc-424, `kb summarize --redo`, SME approve, publish lại, cập nhật README §10 bằng con số thật (~49%).
2. **Đưa quy tắc C2 vào `kb build`** (B-15): tỷ lệ L2/L3 văn xuôi theo section với guard 35% (bỏ sàn 300 ký tự hoặc hạ xuống mức chỉ áp dụng khi văn xuôi < 100 ký tự); check "câu L2 chứa ≥ 4 giá trị ô của bảng cùng section" → error; overlap từ vựng < 0.45 → error; mã trong L2 phải xuất hiện trong L3. Tất cả deterministic, không cần LLM.
3. **Table check hai chiều và đầy đủ** (B-7): bảng L2 phải là tập con đa tập của bảng L3 (bắt bảng bịa và bảng nhân đôi); hạ ngưỡng `extract_tables` xuống 1 dòng; kiểm body L2 rỗng; kiểm heading L2/L3 khớp manifest; build không ghi manifest khi fail.
4. **Sửa runner Copilot** (B-1): truyền prompt qua stdin hoặc file tạm, không qua argv; và `_extract_reply` tôn trọng `is_error`.
5. **`--redo` an toàn** (B-4, B-5): yêu cầu doc_id hoặc `--all` tường minh; không đụng section `reviewed` nếu không có `--include-reviewed`; `rebuild_l2_scaffold` giữ dòng `Figure:`.
6. **`kb approve` có nghĩa**: ghi reviewer, thời điểm, hash L3 vào manifest; từ chối approve section chưa qua build sạch; `kb publish` cảnh báo (hoặc `--require-reviewed` fail) khi ship `summarized`.
7. Đưa skill `kb-summarize` thủ công về cùng engine: sub-agent nhận văn xuôi đã strip bảng qua một lệnh `kb summarize --print-prompt <doc> <sec>` thay vì đọc L3 (B-16).
8. **Mở lại đường MCP** (C-1): import `sqlite_vec`/numpy ở module scope hoặc warm-up một lần trong `create_server()` trước khi vào loop, và chạy tool sync qua `anyio.to_thread.run_sync`; thêm gate test gọi `kb_search` qua stdio thật với timeout cứng, không phụ thuộc `KB_VENV`.
9. **Validate `--level` trong CLI** như `mcp.py:138` đã làm (C-4); in cảnh báo khi kết quả bị cắt ở `K_LEG` (C-7) và khi truy vấn tách ra không còn token có nghĩa (C-9).

### Đợt 2 — An toàn vận hành hub

1. **Registry gate cho `kb publish`** (D-1): khi hub có `registry.yaml`, từ chối `repo_id` không thuộc repo đang publish; `federation.load_registry` phải được gọi ở `publish.publish()` và `publish_federation()`.
2. **Auto mode fail thay vì direct push** (D-2) khi hub có remote mà không mở được PR; bỏ test chuỗi `"github" in url`.
3. **Intake: khoá ghi toàn tiến trình + tách clone phục vụ khỏi clone ghi** (D-3, D-4); `finally` đọc branch dưới khoá; kiểm tra lúc khởi động rằng clone phục vụ đang ở default branch.
4. **`kb reindex` chỉ commit `federation/index.yaml`** (D-5), như `_publish_direct` đã làm.
5. **Publish theo allowlist**: `index.yaml`, `*/_manifest.yaml`, `*/*.md`, `*/assets/*`; không bao giờ `config.yaml` hay dotfile (D-6). Cache hub `0700`, cache key từ URL đã strip credential hoặc dùng credential helper (D-7). Từ chối repo-id trùng case-insensitive và tên thiết bị Win32 (D-8).
6. **CRLF**: `git -c core.autocrlf=false -c core.eol=lf clone` trong `gitio.clone` (đã có ở `intake.py:239`); scaffold `.gitattributes` `* text=auto eol=lf` cho hub và child; normalize trước khi hash trong `_kb_tree_digest`/`_fed_tree_digest` (D-10, H-3).
7. **Không traceback**: `except (yaml.YAMLError, ValidationError)` ở callback chính của typer; `check_kind` trước `_hub_or_exit` trong doctor (H-1, D-9). `extra="forbid"` cho model trong `models.py` (H-M10).
8. **Doctor định kỳ**: thêm workflow mẫu `kb-doctor.yml` (schedule + `kb doctor` trên hub và `kb doctor --context` trên ticket đang mở) để mục tiêu "amendment detectable" có người gọi; thêm content digest cho `check_hub` (H-M9).
9. HTTP: middleware security header, cookie `Secure` + `max_age` + logout, session id dẫn xuất thay vì raw token, rate limit cho 401 trên `/api` và `/mcp`, guard `api.load_manifest` (H-M4..M8).
10. **Index tìm kiếm**: mở rộng `_repo_fingerprint` ra cả thư mục entry (`hashsync.build_manifest` đã tính sẵn) và cho `kb reindex --force` thật sự xoá và dựng lại (C-3); chỉ `delete_db()` khi là `DatabaseError` không phải `IntegrityError`/"too many SQL variables", dùng force-unlink trên Windows, cap `tags` theo giới hạn bind, và giao dịch `IMMEDIATE` cho build lạnh (C-2, C-10); scaffold `.gitignore` cho `.kb-work/` trên hub (C-17).

### Đợt 3 — Độ chính xác của lớp agent và tài liệu

1. **`kb ticket lint` kiểm nội dung** (E-H1): AC không được là placeholder (`TBD`, rỗng, chỉ dấu `- [ ]`); story phải có ba vế không rỗng; mermaid fence phải có ít nhất một cạnh; `## Review record` phải khớp schema (reviewer không rỗng, round hợp lệ) hoặc bỏ khỏi gate và nói rõ là không enforce. Sửa `check_headings` bỏ HTML comment, `section_body` fence-aware, `INLINE_CITE_RE` yêu cầu dạng `[doc §id]` (E-H2..H4). Sửa QUICKSTART-ba cho khớp CI thật (E-M2).
2. **Ship E1/E2** theo spec và plan đã có (batch 7), rồi sửa mục "What is enforced" của QUICKSTART-dev cho đúng những gì máy kiểm (F-H1). Bổ sung giá thiếu trong `usage-prices.yaml` và báo `est`/`assistant` (F-M3, F-M4).
3. **code-ingest** (G): không xoá doc có sẵn tại `<repo>-code` nếu không có marker "generated" (G-1); sửa `_classify` (so khớp theo tên file đầy đủ, không substring); đọc `.gitignore` cho `struct.tree` (G-3); gộp migration theo thư mục, không gộp chéo (G-4); giữ optional deps (G-5); pin `center-kb==<version>` trong `kb-code.yml`, `kb-publish.yml`, `kb-ticket-lint.yml` (G-9, D-13, E-M6); `--kb-dir` tương đối resolve theo cwd.
4. **Tài liệu**: README §10 số thật; dòng 449 (`kb diff`), 479 (auto mode), "20 commands", "four tools"; `federation/README.md` scaffold mô tả layout hiện tại (D-15); ghi nhận tường minh `rel.<name>` và AST extractor là bỏ hoặc hoãn so với Architecture v0.4 §14.1; docstring `hub.resolve_hub`.
5. **Windows thật**: `gate.sh` và `check_package.py` chọn `bin`/`Scripts` theo platform, thêm T0 lint và sdist smoke vào `gate.sh` (D-14, H-M15); `demo-federation.sh` dùng `DEMO_DIR` Windows-visible (D-9).
6. **Lint có nghĩa**: `ruff` với `select` gồm `B`, `BLE`, `S`, `RUF100` (H-L28). Tách ~500 dòng orchestration khỏi `cli.py` (doctor hub/kind branch trước).
7. **Hợp đồng tìm kiếm cho agent**: sửa `_ambiguity_note` hoạt động trên đường keyword-only hoặc bỏ lời hứa khỏi README §7.8 (C-5); nâng "section/doc được trích không còn tồn tại" từ `stale` lên `broken` để CI chặn được (C-6); đo `SEMANTIC_MIN_SCORE` trên fastembed thật trước khi giữ 0.6 (C-11); dẫn xuất tag theo section nếu muốn giữ đúng lời C8, hoặc sửa lời (C-15); cập nhật README §7.5 (C-13).

---

## Phụ lục A — 17 tiêu chí đối chiếu

(Rút từ README, spec Phase 1, spec summarize-quality, roadmap 2026-08-22, Architecture v0.4 §2.2/§3. Bản đầy đủ có trong `review-brief.md` của phiên review.)

C1 bảng bất khả xâm phạm · C2 bốn lớp và tỷ lệ L2 · C3 sectioning · C4 quy trình summarize · C5 build gate · C6 search FTS5/semantic/RRF · C7 hub-first federation · C8 pin/resolve/doctor/diff · C9 MCP parity · C10 BA gates · C11 Dev workflow · C12 code-ingest · C13 svc note · C14 usage · C15 an toàn/vận hành/Windows · C16 docs-as-code · C17 release gate.

## Phụ lục B — Báo cáo chi tiết từng vùng

Tám báo cáo gốc (tiếng Anh, có repro và `file:line` đầy đủ, mỗi báo cáo có scorecard và top-3 khuyến nghị riêng) nằm trong thư mục `2026-09-08-full-framework-review/` cạnh tài liệu này:

- `A-ingest.md` — Docling, sectioner, scaffold, crosscheck, `--sections`
- `B-summarize-build.md` — prompt, runner, budget, `--redo`, `kb build`, `kb approve`, 24 đột biến adversarial, `--redo` thật với stub
- `C-search-mcp-context.md` — battery 40 truy vấn, 10 đột biến resolve, MCP stdio, index freshness, semantic leg
- `D-federation-publish-ci.md` — publish/intake/reindex/assets, 20 probe OIDC, concurrency, CRLF, release pipeline
- `E-ba-gates.md` — `kb ticket lint`, `kb mission lint`, maturity review, CI, scaffold
- `F-dev-workflow-usage.md` — 5 skill dev, conventions pack, `kb svc note`, usage ledger
- `G-code-ingest.md` — 7 extractor, determinism, secret attacks, output trên chính repo
- `H-web-doctor-quality.md` — XSS/traversal/auth, ma trận 19 hỏng hóc cho doctor, `kb diff`, chất lượng test và lint

Mã finding trong tài liệu này (`A-F2`, `B-1`, `C-4`, `D-1`, `E-H1`, `F-M3`, `G-2`, `H-M9`, …) trỏ vào số finding trong báo cáo tương ứng. Các đường dẫn `scratchpad/...` nhắc trong báo cáo là thư mục tạm của phiên review, không còn tồn tại; mọi repro đều mô tả đủ lệnh để chạy lại từ đầu.
