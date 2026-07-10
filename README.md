# AERO-KB — Kho tri thức hàng không "biết tự tóm tắt"

> Tài liệu này viết cho người **không rành kỹ thuật** (SME hàng không, người review, người quản lý dự án). Nếu bạn chỉ cần đọc-hiểu hệ thống và biết cách review, đọc từ đầu đến hết là đủ. Nếu bạn cần chạy lệnh, phần [7](#7-từ-điển-lệnh-kb) và [8](#8-quy-trình-làm-việc-đầy-đủ-từng-bước) có ví dụ chạy thật, copy-paste được.

---

## Mục lục

1. [Tóm tắt trong 30 giây](#1-tóm-tắt-trong-30-giây)
2. [Vấn đề mà AERO-KB giải quyết](#2-vấn-đề-mà-aero-kb-giải-quyết)
3. [Ý tưởng cốt lõi: 4 tầng L0 → L1 → L2 → L3](#3-ý-tưởng-cốt-lõi-4-tầng-l0--l1--l2--l3)
4. [Một tài liệu "đi" qua hệ thống như thế nào](#4-một-tài-liệu-đi-qua-hệ-thống-như-thế-nào)
5. [Cấu trúc thư mục — cái gì nằm ở đâu](#5-cấu-trúc-thư-mục--cái-gì-nằm-ở-đâu)
6. [Cài đặt (cho người chạy lần đầu)](#6-cài-đặt-cho-người-chạy-lần-đầu)
7. [Từ điển lệnh `kb`](#7-từ-điển-lệnh-kb)
8. [Quy trình làm việc đầy đủ, từng bước](#8-quy-trình-làm-việc-đầy-đủ-từng-bước)
9. [Vai trò SME review — checklist](#9-vai-trò-sme-review--checklist)
10. [Bằng chứng nó hoạt động (số liệu PoC thật)](#10-bằng-chứng-nó-hoạt-động-số-liệu-poc-thật)
11. [Giới hạn hiện tại & việc chưa làm](#11-giới-hạn-hiện-tại--việc-chưa-làm)
12. [Câu hỏi thường gặp (FAQ)](#12-câu-hỏi-thường-gặp-faq)
13. [Gặp lỗi thì làm gì](#13-gặp-lỗi-thì-làm-gì)

---

## 1. Tóm tắt trong 30 giây

AERO-KB lấy các tài liệu hàng không dạng PDF **dày hàng trăm trang** (ARINC 424, ICAO Annex 3, Annex 4, Doc 8896...) và biến chúng thành một **kho tri thức có cấu trúc** mà:

- **Con người** đọc được trực tiếp bằng file text/markdown thường (không cần phần mềm đặc biệt), review được qua Pull Request như review một tài liệu Word có track-changes.
- **Trợ lý AI** (như Claude) tra cứu được **đúng đoạn cần thiết**, thay vì phải "nhồi" cả trăm nghìn từ của cả cuốn tài liệu vào mỗi câu hỏi — tiết kiệm **trên 90% chi phí** mỗi lần hỏi.

Không có server, không có database. Toàn bộ kho tri thức là các file `.yaml` và `.md` nằm trong thư mục `.kb/`, được quản lý bằng Git y hệt code — đây là triết lý "**tài liệu như là code**" (docs-as-code).

---

## 2. Vấn đề mà AERO-KB giải quyết

Các tài liệu chuẩn hàng không có hai đặc điểm gây khó:

| Đặc điểm | Vì sao gây khó |
|---|---|
| **Rất dài** — ARINC 424 dày 487 trang, Annex 3 dày 224 trang | Không ai (người lẫn AI) đọc lại cả tài liệu mỗi khi cần tra 1 field cụ thể |
| **Nhiều bảng biểu quan trọng đến từng ký tự** — mã hiệu, độ dài field, kiểu ký tự | Nếu tóm tắt bằng lời văn thông thường (kể cả bằng AI), rất dễ **chép sai một ký tự trong bảng** → sai lệch nguy hiểm cho hệ thống điều hướng bay |

AERO-KB giải quyết đồng thời cả hai:

- **Cắt nhỏ theo section** (ví dụ mỗi field của ARINC 424 là một section riêng: §5.129 "Restrictive Airspace Designation") để tra đúng chỗ, không tra cả file.
- **Bảng biểu không bao giờ đi qua tay AI để "diễn giải lại"** — bảng được trích xuất y nguyên bằng code (không phải AI viết lại), và có một bước kiểm tra tự động đảm bảo bảng ở bản tóm tắt **khớp 100%** với bảng ở bản gốc. Đây là "chốt an toàn" quan trọng nhất của cả hệ thống (xem mục 3).

---

## 3. Ý tưởng cốt lõi: 4 tầng L0 → L1 → L2 → L3

Hãy tưởng tượng một **bộ hồ sơ tra cứu** kiểu thư viện, có 4 lớp từ tổng quát đến chi tiết — giống hệt việc bạn tìm sách trong thư viện: nhìn danh mục phòng ban → nhìn mục lục cuốn sách → đọc tóm tắt chương → đọc nguyên văn.

| Tầng | Tên gọi | Là cái gì | Kích thước | Ví dụ thật trong dự án này |
|---|---|---|---|---|
| **L0** | Danh mục tổng | Một file `index.yaml` duy nhất, liệt kê **mọi tài liệu** đang có trong kho: tên, phiên bản, tags, 1 câu mô tả | Cực nhỏ (187 "từ" cho toàn kho, xem mục 10) | `.kb/index.yaml` |
| **L1** | Mục lục chi tiết | Với mỗi tài liệu, một file `_manifest.yaml` liệt kê **từng section**: id, tiêu đề, 1 câu tóm tắt (≤ 25 từ), trạng thái | Vài chục nghìn "từ" mỗi tài liệu | `.kb/arinc-424/_manifest.yaml` |
| **L2** | Bản tóm tắt cô đọng | File `.md` — văn xuôi tiếng Anh cô đọng còn ~20–30% độ dài gốc, **bảng giữ nguyên văn 100%** | Trung bình | `.kb/arinc-424/ch5-navigation-data-field-definitions.md` |
| **L3** | Bản gốc đầy đủ | File `.md` — toàn văn trích ra từ PDF, không cắt bớt gì | Lớn nhất | `.kb/arinc-424/ch5-navigation-data-field-definitions.raw.md` |

**Vì sao chia 4 tầng thay vì chỉ có 1 bản?**
Một câu hỏi tra cứu thường chỉ cần đọc L0 (biết tài liệu nào liên quan) → L1 (biết section nào liên quan, gần như miễn phí vì chỉ là câu tóm tắt) → L2 (đọc nội dung cô đọng của đúng 1–4 section liên quan). Chỉ khi cần đối chiếu pháp lý/kỹ thuật tuyệt đối chính xác mới cần mở L3. Nhờ vậy AI trả lời câu hỏi mà chỉ cần "nạp" một phần rất nhỏ của cả kho tài liệu.

### Ví dụ cụ thể — section §5.4 "Section Code"

**L1 (trong manifest, chỉ là 1 dòng tóm tắt để máy tìm kiếm dùng):**
> Defines the Section Code field (SEC CODE) identifying the major navigation database section for a record, per Table 5-1, 1 alpha character.

**L2 (văn xuôi cô đọng, đọc trong file `.md`):**
> The Section Code field (SEC CODE) defines the major section of the navigation system database in which a record resides, per the encoding scheme in Table 5-1. Used on all records; length 1 character; alpha.

Và ngay bên dưới là **bảng Table 5-1 chép nguyên văn** — không hề bị AI viết lại, vì bảng do code trích xuất trực tiếp từ PDF.

**Nguyên tắc bất khả xâm phạm:** bảng biểu **không bao giờ** do AI viết lại. AI chỉ được phép viết đoạn văn xuôi tóm tắt xung quanh bảng; chính bảng đó luôn được chương trình chép máy móc, y nguyên từ PDF gốc, ở cả tầng L2 lẫn L3. Trước khi một thay đổi được chấp nhận vào kho (`kb build`), hệ thống **tự động so khớp từng bảng ở L2 với L3** — nếu lệch dù chỉ một ký tự, `kb build` sẽ báo lỗi và chặn lại.

---

## 4. Một tài liệu "đi" qua hệ thống như thế nào

```
   PDF gốc (487 trang, có bản quyền)
          │
          │  kb ingest   ← bước 1: máy làm tự động
          ▼
   Cắt PDF thành ~100–300 "section" nhỏ
   (mỗi field/mục là 1 section, có id chuẩn: §5.3, §ch2, §app3...)
          │
          ▼
   Sinh sẵn:
   - L3 (bản gốc) cho mọi section — XONG NGAY
   - L2 (khung rỗng, có sẵn bảng + chỗ trống chờ viết tóm tắt)
   - L1 (manifest, mỗi section status = "pending" — nghĩa là "đang chờ")
          │
          │  skill kb-summarize (chạy trong Claude Code)  ← bước 2: AI điền tóm tắt
          ▼
   Với từng section pending:
   - Đọc L3 (bản gốc)
   - Viết đoạn tóm tắt tiếng Anh vào L2
   - Viết 1 câu tóm tắt vào L1 (manifest)
   - Đổi status: pending → summarized
          │
          │  kb build   ← bước 3: máy kiểm tra tự động, không thể bỏ qua
          ▼
   ✓ Không còn section nào "pending"
   ✓ Mọi bảng ở L2 khớp 100% với bảng ở L3
   ✓ Đếm lại số "từ" (token) từng tầng
          │
          │  Pull Request trên GitHub   ← bước 4: NGƯỜI review
          ▼
   SME (chuyên gia hàng không) đọc diff, so với PDF gốc, sửa trực tiếp nếu cần
          │
          │  Merge
          ▼
   status: summarized → reviewed.  Section này giờ sẵn sàng để AI tra cứu.
          │
          │  kb query "câu hỏi..."   ← bước 5: dùng hàng ngày
          ▼
   Trả về đúng 1–4 section liên quan nhất, kèm trích dẫn rõ ràng
   (vd: arinc-424 §5.129 (Supplement 22))
```

Nói ngắn gọn: **máy làm phần cơ khí** (cắt section, giữ bảng nguyên văn, kiểm tra toàn vẹn), **AI làm phần ngôn ngữ** (viết tóm tắt), **con người làm phần thẩm định cuối cùng** (review PR) — không bước nào được bỏ qua bước kiểm tra của bước sau.

---

## 5. Cấu trúc thư mục — cái gì nằm ở đâu

```
AERO-KB/
├── .kb/                    ← ★ SẢN PHẨM CHÍNH — đây là thứ bạn review, đây là "kho tri thức"
│   ├── index.yaml                          (tầng L0 — danh mục tổng)
│   ├── arinc-424/
│   │   ├── _manifest.yaml                  (tầng L1 — mục lục chi tiết)
│   │   ├── ch5-navigation-...md            (tầng L2 — bản tóm tắt, ĐỌC FILE NÀY khi review)
│   │   └── ch5-navigation-...raw.md        (tầng L3 — bản gốc đầy đủ, dùng để đối chiếu)
│   └── icao-annex-3/  (cấu trúc tương tự)
│
├── sources/                ← PDF gốc có bản quyền — KHÔNG được đưa lên Git (xem mục 12)
├── .kb-work/                ← File trung gian máy tự sinh khi parse PDF — bỏ qua, không cần quan tâm
├── .venv/                   ← Môi trường Python cài đặt — bỏ qua, không cần quan tâm
│
├── .mcp.json                 ← Khai báo MCP server cho Claude Code (Phase 2, xem mục 7.8)
├── src/aero_kb/              ← Mã nguồn của công cụ (chỉ dev cần đụng vào)
│   ├── cli.py                       lệnh `kb` (đủ 11 lệnh, xem mục 7)
│   ├── ingest/                      phần "cắt PDF thành section"
│   ├── build.py                     phần "kiểm tra toàn vẹn"
│   ├── query.py                     phần "tìm kiếm & trả lời"
│   ├── mcp.py                       MCP server cho agent tra cứu (Phase 2)
│   ├── kbcontext.py, resolve.py     block kb-context + resolve theo bản đã pin (Phase 2)
│   └── diff.py, doctor.py, gitio.py so sánh amendment + kiểm tra sức khỏe kho (Phase 2)
│
├── .claude/skills/kb-summarize/    ← "công thức" hướng dẫn AI cách viết tóm tắt cho đúng chuẩn
├── scripts/demo-federation.sh      ← script demo tự dựng kb-hub + 2 repo mẫu, chạy trọn vòng (Phase 3)
├── .github/workflows/kb-publish.yml ← mẫu CI tự đẩy danh mục lên kb-hub khi `.kb/` đổi (Phase 3)
├── docs/                            ← tài liệu thiết kế, kế hoạch (dành cho người phát triển công cụ)
│   └── deploy-remote-mcp.md                triển khai MCP server dùng chung qua HTTP (Phase 3)
└── tests/                           ← bộ kiểm thử tự động của công cụ
```

**Quy tắc ghi nhớ nhanh:** nếu bạn là SME review nội dung, bạn **chỉ cần quan tâm thư mục `.kb/`**. Mọi thứ khác (`.venv/`, `.kb-work/`, `src/`) là "máy móc bên trong", không liên quan đến việc đọc/review nội dung hàng không.

---

## 6. Cài đặt (cho người chạy lần đầu)

Chỉ cần làm phần này nếu bạn muốn **tự chạy lệnh `kb` trên máy mình** (ví dụ để chạy `kb query` thử tra cứu, hoặc `kb build` để kiểm tra trước khi mở PR). Nếu bạn chỉ review PR trên GitHub, có thể **bỏ qua toàn bộ mục này**.

### Yêu cầu
- Máy đã cài **Python 3.11 trở lên** (dự án này dùng Python 3.13).
- Đã cài **Git** và có quyền truy cập repo.

### Các bước

```bash
# 1. Vào thư mục dự án
cd AERO-KB

# 2. Tạo môi trường ảo Python (chỉ làm 1 lần)
python3 -m venv .venv

# 3. Kích hoạt môi trường ảo (phải làm mỗi khi mở terminal mới)
source .venv/bin/activate

# 4. Cài công cụ + các phần phụ thuộc
#    (ingest = cần cho lệnh "kb ingest"; dev = cần để chạy bộ test)
pip install -e ".[ingest,dev]"

# 5. Kiểm tra cài đặt thành công
kb --help
```

Nếu bước 5 in ra danh sách lệnh (`ingest`, `status`, `build`, `query`, `get`, `stats`, `publish`, `context`, `resolve`, `diff`, `doctor`) — cài đặt thành công.

> **Lưu ý:** mỗi lần mở terminal mới để làm việc với dự án, phải chạy lại `source .venv/bin/activate` trước (dấu hiệu nhận biết: đầu dòng lệnh terminal có chữ `(.venv)`).

---

## 7. Từ điển lệnh `kb`

Bảng dưới liệt kê các lệnh cốt lõi (có từ Phase 1) theo đúng thứ tự dùng trong một quy trình thực tế. Bốn lệnh mới của Phase 2 — `context new`, `resolve`, `diff`, `doctor` — xem mục [7.8](#78-phase-2--tích-hợp-workflow). Lệnh `kb publish` và cờ `--hub`/`--semantic` (Phase 3 — chia sẻ kho tri thức giữa nhiều repo) xem mục [7.9](#79-phase-3--federation--remote-mcp).

| # | Lệnh | Dùng để làm gì | Ai chạy |
|---|---|---|---|
| 1 | `kb ingest` | Đưa 1 PDF vào hệ thống: cắt thành section, sinh khung L1/L2/L3 | Người phụ trách nạp tài liệu mới |
| 2 | `kb status` | Xem còn bao nhiêu section **chưa được tóm tắt** (`pending`) | Ai cũng chạy được, để biết còn việc gì |
| 3 | *(skill `kb-summarize` trong Claude Code)* | AI điền phần tóm tắt vào chỗ trống | Chạy trong Claude Code, không phải lệnh terminal |
| 4 | `kb build` | Kiểm tra toàn bộ kho: hết chỗ trống chưa, bảng có khớp không | Bắt buộc trước khi mở Pull Request |
| 5 | `kb query` | Đặt câu hỏi tự nhiên, nhận lại đúng đoạn liên quan; thêm `--hub <url\|path>` để tìm cả trong kho dùng chung, `--semantic` để ép tìm theo ngữ nghĩa (Phase 3, xem mục [7.9](#79-phase-3--federation--remote-mcp)) | Dùng hàng ngày để tra cứu |
| 6 | `kb get` | Lấy chính xác 1 section theo id (biết trước id) | Khi đã biết rõ mình cần section nào |
| 7 | `kb stats` | Xem số liệu "từ" (token) từng tầng — bằng chứng tiết kiệm chi phí | Theo dõi, báo cáo |
| 8 | `kb publish --hub <url\|path>` | Đẩy danh mục (L0) + mục lục (L1) của kho hiện tại lên kb-hub dùng chung — không đẩy nội dung tóm tắt/nguyên văn | CI tự động chạy mỗi khi có thay đổi trong `.kb/` (Phase 3) |

### 7.1 `kb ingest` — nạp một PDF vào hệ thống

```bash
kb ingest sources/ARINC424-22.pdf \
  --id arinc-424 \
  --tags arinc424,navdata,airspace \
  --revision "Supplement 22" \
  --sections 5
```

| Tham số | Ý nghĩa | Bắt buộc? |
|---|---|---|
| `PDF` (tham số đầu, không có tên) | Đường dẫn tới file PDF nguồn | Có |
| `--id` | Mã định danh ngắn gọn cho tài liệu, vd `arinc-424` | Có |
| `--tags` | Nhãn phân loại, cách nhau bằng dấu phẩy, dùng để lọc khi tìm kiếm | Không |
| `--revision` | Ghi rõ phiên bản/ấn bản, vd `"Supplement 22"` — sẽ xuất hiện trong mọi trích dẫn về sau | Không, nhưng **nên có** |
| `--sections` | Chỉ xử lý những chương này (vd `5,6`); để trống = xử lý cả tài liệu | Không |

Lệnh này **không cần AI**, chạy hoàn toàn tự động bằng code, mất vài giây đến vài chục phút tùy độ dài PDF (lần đầu chậm hơn vì phải tải mô hình nhận diện bố cục trang, ~500MB; các lần sau dùng lại cache).

Kết quả: một thư mục mới `.kb/<id>/` với các file L1/L2/L3, mọi section ở trạng thái `pending`.

### 7.2 `kb status` — xem còn gì chưa xong

```bash
$ kb status
arinc-424: 12/325 section pending
  - §5.312 Some Field Name (file: ch5-navigation-data-field-definitions.md)
  - §5.313 ...
Tổng: 12 section pending.
```

Dùng lệnh này để biết **còn bao nhiêu việc tóm tắt chưa làm xong** trước khi mở Claude Code.

### 7.3 Bước điền tóm tắt (không phải lệnh terminal)

Đây là bước duy nhất do **AI (Claude)** thực hiện, thông qua một "công thức" viết sẵn tên `kb-summarize` (nằm ở `.claude/skills/kb-summarize/SKILL.md`). Người dùng chỉ cần mở Claude Code trong thư mục dự án và gõ yêu cầu tóm tắt — Claude sẽ tự chạy `kb status`, đọc từng section, viết tóm tắt theo đúng quy tắc văn phong đã định sẵn (giữ nguyên mọi mã hiệu, số liệu, không được "sáng tác" thêm), rồi lưu lại.

Quy tắc quan trọng nhất mà AI phải tuân theo (đã lập trình cứng vào công thức):
- **Viết tiếng Anh** (cùng ngôn ngữ với tài liệu gốc, để việc tìm kiếm chính xác nhất).
- **Không được diễn giải lại** mã hiệu, tên field, số liệu, đơn vị đo, tham chiếu chéo (§x.y) — phải giữ y nguyên.
- **Không được đụng vào bảng** đã có sẵn.
- Nếu không chắc chắn về nội dung → giữ nguyên câu gốc, không suy diễn.

### 7.4 `kb build` — chốt chặn kiểm tra tự động

```bash
$ kb build
kb build: OK
```

Nếu có lỗi, lệnh sẽ báo rõ và **thoát với mã lỗi** (không cho qua):

```bash
$ kb build
[error] arinc-424 §5.129: bảng ở L2 không khớp bảng ở L3
```

Hai điều kiện để `kb build` PASS:
1. **Không còn marker `TODO` hoặc summary rỗng** — nghĩa là mọi section đã được ai đó (AI hoặc người) điền tóm tắt.
2. **Mọi bảng trong bản tóm tắt (L2) phải khớp y nguyên với bảng trong bản gốc (L3)** — đây là chốt an toàn quan trọng nhất, ngăn dữ liệu kỹ thuật bị sai lệch khi tóm tắt.

> Mẹo: khi đang tóm tắt dở (còn nhiều section `pending`), dùng `kb build --allow-pending` để kiểm tra các phần đã làm mà không bị chặn bởi các phần chưa làm.

### 7.5 `kb query` — tra cứu bằng câu hỏi tự nhiên

```bash
$ kb query "restrictive airspace" --tags arinc424 --budget 400
--- [arinc-424 §5.129 (Supplement 22)] score=17.19 ~246tk
## 5.129 Restrictive Airspace Designation

The Restrictive Airspace Designation field contains the number or name
that uniquely identifies the restrictive airspace, derived from official
government sources. ...

| Field Content      | Field Content   | Field Content   | Field Content   |
|---------------------|-----------------|-----------------|-----------------|
| Charted Designator | ICAO            | Type            | Rest. Desig.    |
| RJ(R)-116           | RJ              | R               | 116             |
...

--- [arinc-424 §5.126 (Supplement 22)] score=16.96 ~103tk
## 5.126 Restrictive Airspace Name
...
```

| Tham số | Ý nghĩa |
|---|---|
| `TEXT` (tham số đầu) | Câu hỏi/từ khóa tra cứu |
| `--tags` | Chỉ tìm trong các tài liệu có tag này (lọc trước, không phải lọc theo section) |
| `--budget` | Giới hạn số "từ" (token) tối đa trả về — càng nhỏ càng rẻ, càng lớn càng nhiều ngữ cảnh |

Kết quả trả về luôn kèm **trích dẫn rõ ràng** dạng `<mã tài liệu> §<section> (<phiên bản>)` — ví dụ `arinc-424 §5.129 (Supplement 22)` — để biết chính xác thông tin lấy từ đâu, đối chiếu ngược lại tài liệu gốc khi cần.

Cách hoạt động bên trong (không cần hiểu để dùng, nhưng hữu ích để biết vì sao nó rẻ): trước tiên lọc theo `tags` ở tầng L0 (gần như miễn phí), sau đó xếp hạng các section liên quan bằng thuật toán tìm-kiếm-văn-bản cổ điển (BM25) trên các câu tóm tắt L1, cuối cùng mới nạp nội dung L2 của những section xếp hạng cao nhất, dừng lại khi chạm `--budget`. Không có bước nào gọi AI trong quá trình tra cứu này — hoàn toàn là code, nhanh và không tốn phí gọi mô hình AI.

### 7.6 `kb get` — lấy đúng 1 section khi đã biết id

```bash
kb get arinc-424 5.129 --level l2   # bản tóm tắt
kb get arinc-424 5.129 --level l3   # bản gốc đầy đủ
```

Dùng khi đã biết chính xác section cần xem (khác với `kb query` là tìm kiếm mù theo câu hỏi).

### 7.7 `kb stats` — số liệu token, bằng chứng tiết kiệm

```bash
$ kb stats
L0 index.yaml: 187 tokens
doc                  sections       L1         L2         L3   saving
arinc-424                 325    28486      76126      85669    11.1%
icao-annex-3                4      420       1778       2722    34.7%
```

Cột `saving` là mức tiết kiệm giữa L2 và L3 **cho riêng tài liệu đó** — không phải mức tiết kiệm thật khi tra cứu (mức tiết kiệm thật cao hơn nhiều, xem mục 10, vì mỗi lần tra cứu chỉ nạp 1–4 section chứ không nạp cả L2).

> "Token" là đơn vị đo lượng chữ mà một mô hình AI phải "đọc" — tạm hiểu gần đúng là số từ. Token càng ít, mỗi lần hỏi AI càng rẻ và càng nhanh.

---

### 7.8 Phase 2 — Tích hợp workflow

Phase 2 mở rộng AERO-KB để tra cứu không chỉ dừng ở dòng lệnh: Claude Code (hoặc bất kỳ agent nào hỗ trợ MCP) có thể tra cứu kho tri thức trực tiếp qua **MCP server**, và một tài liệu (AC trong Jira, spec...) có thể **trích dẫn máy-đọc-được** một section cụ thể, "ghim" (pin) đúng phiên bản kho tại thời điểm viết — để phát hiện khi kho đổi (amendment) mà trích dẫn cũ chưa cập nhật theo.

#### MCP server — 3 tool

Chạy `python -m aero_kb.mcp --kb .kb` (đã khai báo sẵn trong `.mcp.json` ở gốc repo — Claude Code tự nhận, không cần cấu hình thêm).

| Tool | Dùng để làm gì | Tham số chính |
|---|---|---|
| `kb_search` | Tìm section theo câu hỏi tự nhiên (tag match + BM25), trả nội dung L2 trong token budget | `query`, `tags`, `budget` |
| `kb_get_section` | Lấy chính xác 1 section theo id, đã biết trước | `doc`, `section`, `level` (`l2`/`l3`) |
| `kb_resolve` | Nhận block `kb-context` (hoặc cả ticket chứa block) — trả đúng section tại **phiên bản đã pin**, kèm trạng thái freshness `ok`/`stale`/`broken` | `kb_context` |

#### 4 lệnh CLI mới

| Lệnh | Dùng để làm gì | Exit code |
|---|---|---|
| `kb context new --refs "<doc> §<section>,..."` | BA sinh block `kb-context` pin tại commit HEAD hiện tại — dán thẳng vào Jira ticket | `0` OK, `1` ref không resolve được / lỗi git |
| `kb resolve <file\|->` | Đọc lại 1 block `kb-context` (từ file hoặc stdin), trả section đúng bản đã pin + freshness | `0` mọi ref `ok`, `1` có ref `broken`, `2` không broken nhưng có ref `stale` |
| `kb diff <doc-id> --against <rev>` | So section added/removed/changed của 1 tài liệu giữa worktree hiện tại và một git rev — dùng khi cần biết chính xác amendment đổi những gì | `0` OK (kể cả không có khác biệt), `1` lỗi (doc không tồn tại, rev không hợp lệ...) |
| `kb doctor [--context <file\|->]` | Kiểm tra sức khỏe KB (mục lục hỏng, file thiếu...); thêm `--context` để kiểm luôn staleness của 1 citation | `0` OK, `1` có lỗi KB, `2` không lỗi nhưng citation `stale` — CI dùng mã này để phân biệt "cần BA xác nhận lại" |

`kb resolve`/`kb doctor --context` phát hiện thay đổi trên nội dung L2 (tầng BA đọc); `kb diff` báo thay đổi trên summary L1 và nguyên văn L3 (phạm vi SME review). Một sửa đổi chỉ chạm L2 sẽ báo stale ở resolve nhưng không hiện trong diff.

#### Flow BA → Jira → Dev

1. BA chạy `kb context new --refs "<doc> §<section>"` sau khi đọc xong đoạn spec liên quan.
2. BA dán block `kb-context` được in ra vào mô tả/AC của ticket Jira — block này ghim sẵn commit hash hiện tại của kho.
3. Dev mở ticket, agent (qua MCP) gọi `kb_resolve` với nội dung ticket — nhận đúng nội dung BA đã thấy lúc viết, không phải bản mới nhất nếu kho đã đổi.
4. Nếu kết quả báo `status=stale` (kho đã có amendment sau khi ticket được viết), Dev chạy `kb diff <doc-id> --against <rev-đã-pin>` để thấy chính xác section nào đổi, rồi trao đổi lại với BA xem AC có cần cập nhật không.
5. `kb doctor --context <ticket>` dùng trong CI để tự động chặn/gắn cờ các ticket có citation `stale` trước khi merge, không cần người rà tay từng ticket.

> **Ghi chú:** file `.mcp.json` cấu hình sẵn MCP server đã có trong repo — không cần thiết lập gì thêm để Claude Code nhận diện 3 tool trên. Tham số `--hub` của `python -m aero_kb.mcp` giờ đã **kích hoạt** — xem mục [7.9](#79-phase-3--federation--remote-mcp) ngay bên dưới.

---

### 7.9 Phase 3 — Federation & remote MCP

Phase 2 giúp một kho tri thức "biết nói chuyện" với dev qua MCP và biết "ghim" trích dẫn. Phase 3 giải quyết bài toán tiếp theo: **một tài liệu chuẩn (ví dụ ARINC 424) thường liên quan đến nhiều repo khác nhau** (repo nav-data, repo crew-ops...) — không lẽ mỗi repo lại tự nạp và tự tóm tắt lại cùng một tài liệu đó? Phase 3 cho phép tài liệu domain sống **một bản duy nhất** ở một kho trung tâm gọi là **kb-hub**, còn các repo khác chỉ "tham chiếu" vào bản đó.

**kb-hub là gì?** Đơn giản là một repo Git khác, có cấu trúc `.kb/` y hệt repo hiện tại, cộng thêm một thư mục `federation/` do máy tự sinh — chứa "danh mục của các danh mục": mỗi repo tham gia đóng góp một bản sao rút gọn (chỉ L0 + L1, không có nội dung tóm tắt/nguyên văn) để các repo khác biết "repo kia có tài liệu gì" mà không cần phải sang tận nơi. kb-hub không phải server chạy nền — vẫn chỉ là file `.yaml`/`.md` quản lý bằng Git, đúng triết lý docs-as-code như phần còn lại của hệ thống.

**3 điểm mới cần biết:**

1. **`kb publish --hub <url|path>`** — đẩy danh mục (L0) và mục lục (L1) của kho hiện tại lên kb-hub, để các repo khác "biết" mình có tài liệu gì. Không đẩy nội dung tóm tắt (L2) hay nguyên văn (L3) — hai tầng đó chỉ ở lại repo gốc. Chạy tay khi cần, hoặc tự động qua CI (xem mẫu `.github/workflows/kb-publish.yml`) mỗi khi `.kb/` đổi.
2. **Cờ `--hub <url|path>`** trên `kb query`, `kb context new`, `kb resolve`, `kb doctor` — mở rộng phạm vi tìm/kiểm tra ra cả kb-hub, không chỉ kho cục bộ. Ví dụ `kb query "..." --hub https://.../kb-hub.git` trả về: tài liệu domain sống ở hub (đọc đầy đủ như tài liệu cục bộ) lẫn tóm tắt 1 câu của tài liệu bên các repo khác (đánh dấu `[remote]`, muốn đọc sâu phải sang đúng repo đó). Công cụ tự tải/giữ tươi một bản sao cục bộ của hub, không cần tự tay `git clone`.
3. **Cờ `--semantic`** trên `kb query` — ép tra cứu theo **ý nghĩa câu hỏi** thay vì chỉ khớp từ khóa (BM25). Hữu ích khi câu hỏi diễn đạt khác từ ngữ trong tài liệu gốc nhưng cùng ý. Đây là bước tùy chọn cài thêm (`pip install -e ".[embed]"`) — nếu máy chưa cài, `kb query` vẫn chạy bình thường bằng khớp từ khóa như trước, không báo lỗi.

**Block `kb-context` nay có thể "ghim" 2 phiên bản.** Nếu BA trích dẫn một section sống ở kb-hub, block sinh ra sẽ có thêm dòng `hub_version` bên cạnh `version` — ghim đúng bản của cả kho cục bộ lẫn kho trung tâm tại thời điểm viết. Các block Phase 2 cũ (chỉ có `version`) vẫn resolve đúng như trước, không cần sửa lại gì.

**Tra cứu từ xa qua MCP không cần clone repo:** trước đây agent muốn dùng MCP phải clone repo về máy trước. Phase 3 cho phép chạy MCP server dạng "máy chủ dùng chung" qua HTTP (thay vì chỉ chạy cục bộ), có xác thực bằng token — hướng dẫn triển khai chi tiết ở [`docs/deploy-remote-mcp.md`](docs/deploy-remote-mcp.md).

**Muốn xem toàn bộ vòng đời hoạt động thật (2 repo cùng đóng góp vào 1 hub, tra cứu chéo, phát hiện tài liệu đã đổi mà trích dẫn cũ chưa cập nhật)?** Chạy thử `bash scripts/demo-federation.sh` — script tự dựng một hub và 2 repo mẫu trong thư mục tạm, chạy trọn vòng rồi tự dọn dẹp, không đụng đến dữ liệu thật của bạn.

---

## 8. Quy trình làm việc đầy đủ, từng bước

Đây là kịch bản thực tế: thêm một tài liệu mới vào kho tri thức, từ PDF đến khi sẵn sàng dùng.

```
Bước 1 — Nạp PDF (người phụ trách kỹ thuật chạy)
  $ kb ingest sources/ARINC424-22.pdf --id arinc-424 \
      --tags arinc424,navdata --revision "Supplement 22" --sections 5
  → Sinh ra .kb/arinc-424/ với 325 section, tất cả đang "pending"

Bước 2 — Điền tóm tắt (mở Claude Code, dùng skill kb-summarize)
  → Claude tự chạy kb status, đọc từng section, viết tóm tắt tiếng Anh
  → Cứ 5–10 section, Claude tự kiểm tra bằng `kb build --allow-pending`

Bước 3 — Kiểm tra chốt chặn cuối
  $ kb build
  kb build: OK
  → Nếu FAIL, quay lại bước 2 sửa phần bị lỗi (thường là bảng bị đụng vào)

Bước 4 — Mở Pull Request trên GitHub
  → Diff hiển thị đúng các file .kb/*.yaml và .kb/*.md thay đổi
  → SME hàng không review (xem mục 9 — checklist review)

Bước 5 — Merge
  → Sau merge, các section chuyển trạng thái: summarized → reviewed
  → Kho tri thức giờ đã có nội dung mới, sẵn sàng cho kb query
```

---

## 9. Vai trò SME review — checklist

Nếu bạn được mời review một Pull Request thay đổi trong `.kb/`, đây là những gì cần làm — **không cần biết code, không cần chạy lệnh gì**, chỉ cần đọc diff trên GitHub như đọc một tài liệu Word có track-changes:

- [ ] **Đọc phần văn xuôi mới (L2, file `.md` không có đuôi `.raw`)** — có đúng ý so với hiểu biết chuyên môn của bạn về nội dung này không?
- [ ] **Đối chiếu với PDF gốc** (trong `sources/` hoặc bản PDF bạn có sẵn) — đoạn tóm tắt có bỏ sót điều gì quan trọng không, có "bịa" thêm điều gì không có trong bản gốc không?
- [ ] **Kiểm tra mọi mã hiệu, tên field, số liệu, đơn vị đo** (vd `S/T`, `CUST/AREA`, độ dài field, kiểu ký tự) — phải **giữ nguyên y hệt bản gốc**, không được viết lại/diễn giải theo cách khác.
- [ ] **Bảng biểu:** không cần kiểm tra bằng mắt xem bảng ở tóm tắt có khớp bảng gốc không — việc này `kb build` **đã tự động kiểm tra và chặn PR nếu sai** trước khi bạn thấy PR. Nhưng vẫn nên liếc qua xem bảng có bị Docling (công cụ đọc PDF) đọc lệch dòng/lệch cột so với bản PDF gốc không — đây là lỗi mà máy không tự phát hiện được.
- [ ] **Câu tóm tắt 1 dòng trong `_manifest.yaml`** (tầng L1) — có nêu đúng "section này nói về cái gì" để sau này tìm kiếm ra được không?
- [ ] Nếu thấy sai — **sửa trực tiếp trong file `.md` hoặc `.yaml` qua giao diện GitHub** (như sửa một tài liệu thường), rồi comment giải thích tại sao, hoặc yêu cầu người mở PR sửa lại.

Sau khi PR được merge, phần bạn vừa duyệt sẽ chuyển trạng thái `status: reviewed` trong manifest — đánh dấu đây là nội dung đã qua thẩm định chuyên môn, không còn là bản nháp do AI viết.

---

## 10. Bằng chứng nó hoạt động (số liệu PoC thật)

Tính đến lần chạy thử nghiệm gần nhất (xem `docs/superpowers/specs/2026-07-10-aero-kb-phase1-design.md` mục 10 để biết đầy đủ):

- **Đã nạp thật:** ARINC 424-22 chương 5 (325 section) + ICAO Annex 3 chương 2 (4 section).
- **`kb build` PASS** — không có bảng nào sai lệch, không còn section nào bỏ dở.
- **`kb query` trả đúng section, đúng trích dẫn** (vd `arinc-424 §5.213 (Supplement 22)`), cắt đúng theo giới hạn token yêu cầu.
- **Mức tiết kiệm:** L0 (danh mục tổng) chỉ 187 token cho toàn kho. Một câu hỏi tra cứu thông thường trả về 1–4 section (~600–1.200 token) **thay vì phải nạp cả tài liệu gốc (~400.000 token)** — tiết kiệm **≥ 99%** cho mỗi lần tra cứu, vượt mục tiêu đề ra (≥ 90%).
- **5 lỗi thực tế đã tìm ra và sửa** trong quá trình xử lý PDF thật (header lặp mỗi trang bị nhận nhầm thành heading, nhãn "Source/Content:" bị nhận nhầm thành tiêu đề section, v.v.) — đều đã có bài test tự động để không tái diễn.

---

## 11. Giới hạn hiện tại & việc chưa làm

Đây là bản **Phase 1 + Phase 2 + Phase 3**, không phải bản hoàn chỉnh. Những gì **chưa** có:

- **Chưa tự sinh "hiểu biết về mã nguồn"** (ví dụ tự đọc OpenAPI, schema database, danh sách module của một hệ thống để đưa vào kho tri thức) — khác hẳn phạm vi hiện tại (tài liệu chuẩn hàng không dạng PDF), để dành cho một đợt phát triển riêng sau này.
- **Xác thực HTTP MCP mới dừng ở bearer token** (một chuỗi bí mật cố định), chưa có đăng nhập kiểu OAuth/SSO — đủ dùng trong mạng nội bộ/VPN hiện tại, nhưng chưa phù hợp để mở ra Internet công khai.
- Việc điền tóm tắt vẫn cần con người mở Claude Code và kích hoạt — chưa hoàn toàn tự động chạy nền.
- Một số ít section (khoảng 2,4% của chương 5 ARINC, 6/~250 mục) chưa trích xuất được do lỗi đọc PDF — cần SME đối chiếu thủ công khi gặp.

---

## 12. Câu hỏi thường gặp (FAQ)

**Vì sao không thấy các file PDF gốc trong Git?**
Vì các tài liệu này (ARINC, ICAO) có bản quyền — không được phép đưa lên kho mã nguồn dùng chung. Chúng chỉ tồn tại trên máy cục bộ trong thư mục `sources/`, đã được cấu hình để Git **luôn bỏ qua** thư mục này (không bao giờ commit nhầm).

**Vì sao AI (Claude) viết tóm tắt mà không dùng thẳng ChatGPT/API nào đó?**
Vì dự án dùng subscription Claude Code sẵn có thay vì trả tiền gọi API riêng — tiết kiệm chi phí cho giai đoạn thử nghiệm này. Việc này không ảnh hưởng đến chất lượng tóm tắt, chỉ ảnh hưởng đến cách vận hành (cần người mở Claude Code thay vì chạy hoàn toàn tự động).

**Tóm tắt do AI viết — làm sao tin được nó không sai?**
Ba lớp bảo vệ: (1) AI bị ràng buộc quy tắc văn phong nghiêm ngặt (không suy diễn, giữ nguyên mã hiệu/số liệu); (2) bảng biểu — phần dễ sai nhất — **không bao giờ đi qua tay AI**, luôn do code chép nguyên văn và được kiểm tra khớp tự động; (3) **con người (SME) luôn review trước khi merge** — AI chỉ tạo bản nháp, không có quyền tự công bố nội dung cuối cùng.

**"Token" là gì, sao cứ nhắc hoài?**
Là đơn vị đo lượng văn bản mà một mô hình AI xử lý (gần giống số từ). Nó quyết định chi phí và tốc độ mỗi lần gọi AI. Kiến trúc 4 tầng của AERO-KB tồn tại chủ yếu để **giảm số token phải nạp** mỗi khi tra cứu, mà vẫn giữ được thông tin chính xác.

**Tôi có cần biết lập trình để review nội dung không?**
Không. Xem mục 9 — review chỉ là đọc file `.md`/`.yaml` trên giao diện GitHub, hoàn toàn giống đọc một tài liệu văn bản có đánh dấu thay đổi.

---

## 13. Gặp lỗi thì làm gì

| Tình huống | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| `kb build` báo lỗi "bảng không khớp" | Ai đó (thường là AI) lỡ sửa vào nội dung bảng khi viết tóm tắt | Mở file `.raw.md` (L3) của đúng section đó, copy lại bảng nguyên văn, dán đè vào file `.md` (L2) |
| `kb build` báo còn `pending`/`TODO` | Chưa chạy xong bước điền tóm tắt (bước 2 ở mục 8) | Chạy `kb status` xem còn section nào, quay lại Claude Code chạy skill `kb-summarize` |
| `kb ingest` chạy rất lâu (10–30 phút) lần đầu | Bình thường — công cụ đọc PDF (Docling) phải tải mô hình nhận diện bố cục (~500MB) lần đầu tiên | Chờ, hoặc kiểm tra kết nối mạng nếu đứng yên quá lâu. Các lần chạy sau trên cùng PDF sẽ dùng cache, nhanh hơn nhiều |
| Lệnh `kb` báo "command not found" | Chưa kích hoạt môi trường ảo | Chạy `source .venv/bin/activate` trong thư mục dự án trước |
| `kb query` không trả kết quả nào | Từ khóa không khớp tag/nội dung nào trong kho, hoặc `--budget` quá nhỏ | Thử bỏ `--tags`, hoặc tăng `--budget`, hoặc kiểm tra chính tả từ khóa (kho hiện dùng tiếng Anh) |
| Không chắc file nào mới thay đổi trong PR | — | Xem tab "Files changed" trên GitHub — chỉ các file trong `.kb/` là nội dung cần review; thay đổi trong `src/`, `tests/` là phần công cụ, có thể để lại cho người phát triển |

---

*Tài liệu này mô tả trạng thái Phase 1 (PoC) + Phase 2 (tích hợp workflow) + Phase 3 (federation & remote MCP) — cập nhật 2026-07-11. Chi tiết thiết kế kỹ thuật đầy đủ xem `docs/superpowers/specs/2026-07-10-aero-kb-phase1-design.md`, `docs/superpowers/specs/2026-07-10-aero-kb-phase2-design.md` và `docs/superpowers/specs/2026-07-10-aero-kb-phase3-design.md`.*
