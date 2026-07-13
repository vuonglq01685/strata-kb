# Cửa kiểm định trước khi release (E2E + Smoke + Regression) — Design

**Ngày:** 2026-07-13
**Nguồn:** phiên brainstorm 2026-07-13
**Phạm vi:** dựng một cửa kiểm định chạy được ở cả ba nơi (máy dev, PR, tag) trước khi `center-kb` được publish lên PyPI/GHCR. Không đổi tính năng sản phẩm, trừ hai hạng mục hạ tầng bắt buộc phải xây để kiểm được (`kb --version`, kiểm tra `uv.lock`).

## 1. Bối cảnh: hiện trạng và các lỗ hổng

Quy trình release hiện tại nằm trọn trong `.github/workflows/release.yml`, chỉ kích hoạt khi push tag `v*`:

```
tag v* → test (pytest, 3.12) → build (python -m build + kiểm wheel tự chứa) → pypi
                             ↘ docker (build + smoke health/401 + push GHCR)
```

Các lỗ hổng đã xác định trong phiên brainstorm:

| # | Lỗ hổng | Hậu quả |
|---|---|---|
| L1 | **Không có CI nào chạy trên PR hay push `main`.** Chỉ có `release.yml` (tag) và `kb-publish.yml` (`.kb/**`) | Test chạy lần đầu tiên đúng vào lúc tag. Sai là sai ở phút cuối, khi đã muốn phát hành. |
| L2 | Test chạy trên `pip install -e .` (source tree), **không chạy trên artifact đã build** | Lỗi đóng gói (thiếu file trong wheel, entry point hỏng, extras không resolve) không bị 384 test bắt. |
| L3 | `pyproject` khai báo hỗ trợ Python 3.11 + 3.12, **chỉ test 3.12** | Hỏng trên 3.11 mà không ai biết. |
| L4 | Không kiểm version consistency: tag vs `pyproject.version` vs `uv.lock` | Commit `chore: sync uv.lock to 0.9.0` là bằng chứng chỗ này từng lệch và phải sửa tay. |
| L5 | Không có `twine check` | Metadata sai / README vỡ trên trang PyPI, phát hiện sau khi đã publish. |
| L6 | Smoke wheel mới chỉ `kb init` + `kb doctor` | Không chạm ingest / summarize / query / publish / web / MCP. |
| L7 | Job `docker` chỉ `needs: test`, chạy song song `pypi` | Image `:latest` vẫn được đẩy kể cả khi PyPI hỏng; và PyPI vẫn publish được kể cả khi image không build nổi (tức extras `[ingest]` không resolve). |
| L8 | Không có tầng regression nào | Nâng cấp dependency đổi hành vi (ví dụ `rank-bm25` đổi công thức ranking), hoặc đổi schema `.kb/`, đều vỡ trong im lặng. |

Ràng buộc bất biến của dự án (không thay đổi được, thiết kế phải sống chung):

- **LLM chỉ chạy qua `claude` CLI headless** (subscription). CI không có `claude`.
- **PDF nguồn có bản quyền, không commit.** Không thể ingest tài liệu thật trên CI.
- `kb ingest` cần extras `[ingest]` → kéo `docling` + torch (~2GB), và một lần parse thật còn tải model layout/table từ Hugging Face lúc runtime.

## 2. Mục tiêu & tiêu chí hoàn thành

Mục tiêu: **khi `git push --tags` chạy, rủi ro đã được rút gần hết từ trước; tag chỉ còn là nút bấm publish.**

Tiêu chí hoàn thành:

1. Mọi PR và mọi push `main` đều chạy đúng bộ cửa mà tag sẽ chạy — không hơn, không kém.
2. Tồn tại một lệnh duy nhất chạy được toàn bộ cửa trên máy dev, **trước khi** tạo tag.
3. Không có hành động không-thể-hoàn-tác (publish PyPI, đẩy tag GHCR `:latest`) nào xảy ra trước khi toàn bộ cửa xanh.
4. Bốn loại sai sót được phủ: lỗi đóng gói, regression chức năng, lệch version/metadata, hỏng trên môi trường sạch.
5. Một job CI **không thể xanh trong khi chạy 0 test**.

Ngoài phạm vi (ghi lại để đợt sau):

- **Thêm `--json` cho các lệnh CLI.** Sẽ cho hợp đồng máy sạch hơn hẳn để snapshot, và đáng làm — nhưng đó là một *tính năng*, không phải một *cửa kiểm*. Thiết kế này thích ứng với hiện trạng (không có `--json`) bằng cách đặt golden ở tầng MCP tool output.
- **Parse PDF thật trong cửa release.** Cần extras nặng + tải model từ mạng lúc runtime. Một cửa release hay flaky vì mạng thì tệ hơn là không có cửa. Nếu sau này muốn, chỗ đúng của nó là job `schedule:` chạy hàng tuần với PDF tổng hợp tự sinh — nơi mạng flaky không chặn release.
- **Bật `ruff` / `mypy` làm gate.** `.ruff_cache` và `.mypy_cache` tồn tại nhưng cả hai đều **không** có trong `pyproject.toml` (không config, không nằm trong dev deps) — chúng đang được chạy tay, chưa phải hợp đồng của dự án. Biến chúng thành gate cần một đợt dọn nợ riêng.
- **Staging qua TestPyPI.** Đã cân nhắc và loại: luồng một-tag với cửa đầy đủ đặt trước job `pypi` đã đủ, và không phải quản lý số `rc`.
- **Tương thích ngược chiều "bản mới publish → bản cũ đọc".** Hub là single source of truth và do bạn kiểm soát; YAGNI.

## 3. Các quyết định thiết kế đã chốt

| # | Quyết định | Lựa chọn | Lý do |
|---|---|---|---|
| 1 | Hình dạng luồng release | **Một tag, gate toàn bộ đặt trước job `pypi`** | Giữ nguyên thói quen `git tag && git push --tags`. Fail = chưa tốn version, chỉ cần xoá tag, sửa, tag lại. Loại phương án RC/TestPyPI (thêm một vòng thủ công + phải quản số `rc`). |
| 2 | Nơi đặt logic gate | **Bộ test pytest (`tests/e2e/`, `tests/regression/`) trỏ vào binary đã cài**, không phải bash inline trong YAML | Ba trong bốn tầng regression về bản chất là *so sánh dữ liệu có cấu trúc* (YAML/JSON diff qua nhiều fixture) — pytest cho việc đó gần như miễn phí, bash thì không. Và đây là cách duy nhất chạy được toàn bộ cửa **trước khi** tạo tag. |
| 3 | Hợp đồng với artifact | **Một biến môi trường duy nhất `KB_VENV`**, suy ra `$KB_VENV/bin/kb` và `$KB_VENV/bin/python` | Hành trình cần *hai* thứ từ venv artifact: binary `kb`, và `python` của chính venv đó (web/MCP chạy qua `python -m center_kb.mcp` — **không có lệnh `kb serve`**). Truyền một biến rồi suy ra cả hai thì không thể lỡ tay trỏ hai thứ vào hai môi trường khác nhau. |
| 4 | Cô lập artifact | **Hai venv:** `venv-artifact` chỉ chứa wheel (vật thể bị test, không bao giờ có pytest); runner chứa pytest + `mcp` SDK làm client | Server MCP chạy trong venv-artifact, client chạy ở runner — đúng hình thù thật khi một agent cắm vào `center-kb`. |
| 5 | Chống suy thoái tầng | **Test canary**: `importlib.util.find_spec("center_kb") is None` ở runner | Nếu để lọt một `import center_kb` vào `tests/e2e/`, cả tầng T3 âm thầm quay về test source tree và mất sạch giá trị. Không có canary thì kiểu thoái hoá này xảy ra trong vài tháng mà không ai nhận ra. |
| 6 | Cửa xanh giả | Fixture `artifact` **raise** (không `skip`) nếu `KB_VENV` không được set; `--strict-markers` | Một job CI xanh vì pytest thu thập được 0 test là kiểu hỏng nguy hiểm nhất của cửa release — nó cho cảm giác an toàn giả. |
| 7 | Vết nối `kb ingest` | Hành trình e2e bắt đầu từ **đầu ra** của ingest (fixture seed doc ở trạng thái `pending`); ghim vết nối bằng một test T1 khẳng định `kb ingest` sinh ra `.kb` **cùng hình dạng** với fixture đó | Không chạy được ingest thật (xem §1: `parser.load_or_parse` import `docling_core` *trước cả khi* đọc cache → kể cả có cache vẫn phải cài extras). Rủi ro của vết nối là **trôi** — ingest đổi định dạng, fixture không đổi, e2e vẫn xanh trong khi thực tế đã vỡ. Ghim ở cả hai đầu. |
| 8 | Phủ extras `[ingest]`/`[embed]` | **Để job `docker` gánh** — image build = `pip install center-kb[ingest]` thật (xem `Dockerfile`) | Không viết thêm code. Chỉ cần sửa đồ thị phụ thuộc để `pypi` không thể publish khi image không build nổi. |
| 9 | Chỗ đặt golden output | **Hợp đồng máy = chuỗi trả về của MCP tool** (`kb_search`, `kb_get_section`, `kb_resolve` đều `-> str`), không phải stdout CLI | CLI không có `--json` (xem "ngoài phạm vi"). Golden **cứng** cho MCP tool output + `tools/list` schema; golden **mềm** (có chuẩn hoá) cho stdout CLI. |
| 10 | Nguồn fixture legacy | **`git archive vX.Y.Z .kb`** lấy thẳng từ lịch sử repo, materialize lúc chạy test | `.kb/` được commit ở mọi tag (v0.7.0/v0.8.0/v0.9.0, nội dung ARINC-424 thật) — đây đúng là dữ liệu một user đang giữ trong repo của họ. Không nhân đôi vài MB vào `tests/`, không bao giờ lệch với thật. Cái giá: CI cần `fetch-depth: 0`, và **tag trở thành bất biến** (xoá/viết lại tag = đỏ test) — coi là tính năng. |
| 11 | Thứ tự các hành động không-thể-hoàn-tác | `_gate` → `docker-verify` (build + smoke + push tag `sha-<commit>`) → `pypi` → `docker-release` (retag `sha-` → `vX.Y.Z` + `latest`) | Tag `sha-` vô hại, không phải tag release. `docker-release` chỉ retag bằng `imagetools create`, không build lại (~5 giây), nên không phải lưu image nhiều GB làm artifact. |

## 4. Kiến trúc: bốn tầng cửa

Xếp theo thứ tự *rẻ trước, đắt sau*. **Cùng một bộ logic chạy ở cả ba nơi: máy dev, PR, tag.**

```
┌─ T1  unit/integration ──── pytest tests/         (384 test, in-process, source tree)
│                            → được phép import center_kb
├─ T2  đóng gói ──────────── build wheel+sdist → twine check --strict → version consistency
│                            → sdist cài được vào venv sạch (smoke mỏng)
├─ T3  e2e artifact ──────── pytest -m e2e         (KB_VENV trỏ vào wheel đã cài)
│                            → TUYỆT ĐỐI không import center_kb
└─ T4  regression ────────── pytest -m regression  (legacy .kb, golden, federation, MCP contract)
                             → TUYỆT ĐỐI không import center_kb
```

**Ranh giới giữa các tầng là điều quan trọng nhất của thiết kế này.** T1 biết code. T3/T4 chỉ biết `KB_VENV` như một hộp đen. Ranh giới đó được cưỡng chế bằng test canary (quyết định #5), không phải bằng kỷ luật con người.

### 4.1 Bố cục thư mục

```
tests/                       ← T1: 384 test hiện có, được phép import center_kb
tests/e2e/
    conftest.py              ← fixture artifact, stub claude, bare hub, port trống
    test_canary.py           ← center_kb KHÔNG import được ở runner; $KB_VENV/bin/kb chạy được
    test_journey.py          ← hành trình đầy đủ (§5)
tests/regression/
    conftest.py              ← materialize fixture legacy từ git archive
    golden/
        mcp_tools.json       ← snapshot tools/list — so sánh CHÍNH XÁC
        mcp_outputs/         ← snapshot chuỗi trả về của 3 MCP tool
        cli_outputs/         ← snapshot stdout CLI (đã chuẩn hoá)
        federation-v0.9.0/   ← cây federation/ sinh bởi v0.9.0 (§6.4) — fixture DUY NHẤT
                               được commit, vì federation/ không nằm trong repo này
    test_kb_backcompat.py    ← §6.1
    test_mcp_contract.py     ← §6.2
    test_golden_output.py    ← §6.3
    test_federation_compat.py ← §6.4
```

### 4.2 Cấu hình pytest

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--strict-markers -m 'not e2e and not regression'"
markers = [
    "e2e: chạy trên wheel đã cài (cần KB_VENV)",
    "regression: hợp đồng dữ liệu/API (cần KB_VENV)",
]
```

`pytest` trần = T1 như hiện nay (không ai bị chậm). `pytest -m e2e` = T3. `pytest -m regression` = T4.

### 4.3 Chạy toàn bộ cửa trên máy dev

```bash
python -m build
python -m venv /tmp/va && /tmp/va/bin/pip install dist/*.whl
KB_VENV=/tmp/va pytest tests/e2e tests/regression -m "e2e or regression"
```

Một lệnh, không cần push, không cần đốt tag. Đây là tiêu chí hoàn thành #2.

### 4.4 Bốn cái bẫy đã biết, xử lý sẵn trong `tests/e2e/conftest.py`

| Bẫy | Xử lý |
|---|---|
| **Git identity** — `kb publish` commit thật; runner CI không có `~/.gitconfig` | Fixture bơm `GIT_AUTHOR_*` / `GIT_COMMITTER_*` vào env của subprocess (cùng cách `release.yml` đang làm cho job `test`). |
| **Hub phải là bare repo để push được** — `kb publish --direct` push vào `main` của hub; push vào repo đã checkout sẽ bị git từ chối | Fixture dựng hub có layout (`.kb/index.yaml` + `federation/`), commit, rồi `git clone --bare` ra `hub.git`. Ngược lại, `kb doctor --hub` chấp nhận thư mục thường (xem `release.yml` hiện tại). |
| **Stub `claude`** | Ghi shell script tên `claude` vào thư mục tạm rồi prepend vào `PATH` của subprocess. Tái dụng kỹ thuật `_install_stub_claude` (`tests/test_summarize_e2e.py:20`), chỉ khác là tác động lên env của subprocess thay vì `monkeypatch` in-process. |
| **Cổng HTTP** | Bind `socket` vào port 0 để xin cổng trống, thay vì hardcode 8321 — tránh đụng nhau khi chạy song song. |

## 5. Hành trình e2e (T3)

Chạy trên venv chỉ có wheel base (**không** extras), gọi `kb` bằng `subprocess`.

| # | Bước | Khẳng định |
|---|---|---|
| 0 | `kb --version`, `kb --help` | version khớp `pyproject.version` (đọc `pyproject.toml` như một file text — **không** import `center_kb`); `--help` liệt kê đủ **14 mục**: 13 lệnh (`init`, `ingest`, `summarize`, `status`, `build`, `query`, `get`, `stats`, `publish`, `reindex`, `resolve`, `diff`, `doctor`) + nhóm `context`. Bắt lỗi lệnh biến mất khỏi wheel. *(Khẳng định "tag == version" là việc của T2, §7.3 — trên PR không có tag.)* |
| 1 | `kb init` | `.kb/index.yaml` + `.kb/config.yaml` được sinh ra |
| 2 | *seed* 1 doc ở trạng thái `pending` | fixture — xem quyết định #7 (vết nối ingest) |
| 3 | `kb summarize --llm claude` (stub trên `PATH`) | mọi section → `status: summarized`; không còn `TODO:summarize` trong L2 |
| 4 | `kb build`, `kb status`, `kb stats` | index BM25 dựng được; thống kê ra số |
| 5 | `kb query "airspace"`, `kb get 1.1` | có hit; `get` trả đúng nội dung L2/L3 |
| 6 | `kb publish --direct --hub <bare>` | clone hub ra: `federation/<repo-id>/<doc>/` mirror đủ L0→L3 + `_meta.yaml` |
| 7 | `kb doctor --hub <hub>` | exit 0 |
| 8 | `kb context new` → `kb resolve`; rồi `kb diff` giữa 2 revision hub | roundtrip: `resolve` trả đúng section đã pin + cờ freshness; `diff` phát hiện thay đổi |
| 9 | `$KB_VENV/bin/python -m center_kb.mcp --transport http` | `/api/health` → 200; `/api/docs` không token → **401**; có token → 200 **và trả về doc vừa seed** |
| 10 | MCP stdio (client SDK ở runner) | `initialize` OK; `tools/list` = **đúng 4 tool** (`kb_search`, `kb_get_section`, `kb_context_new`, `kb_resolve`); gọi `kb_search` → kết quả không rỗng |
| 11 | `kb ingest x.pdf --id d` (không có docling) | exit ≠ 0 với **thông điệp sạch** `"Docling is not installed…"`, **không phải traceback** |

Bước 9 và 11 là hai bước cửa hiện tại bỏ trống hoàn toàn: một là đường sống của Docker/agent; hai là đường *suy giảm* — thứ mọi user `pip install center-kb` (không extras) sẽ đâm vào đầu tiên.

## 6. Bốn tầng regression (T4)

### 6.1 Tương thích ngược `.kb/` — tầng đắt nhất

Với mỗi tag trong `{v0.7.0, v0.8.0, v0.9.0}`: `git archive <tag> .kb` → thư mục tạm; chạy binary **mới** lên đó: `kb doctor --hub`, `kb build`, `kb query`, `kb get`. Phải sống, không traceback, không nuốt lặng section nào.

**Quy tắc khi cố tình phá tương thích:** *không được sửa test cho xanh.* Phải hoặc (a) viết migration để đọc được định dạng cũ, hoặc (b) đánh dấu `xfail` kèm ghi chú nêu rõ version nào phá và user phải làm gì. Không có quy tắc này thì cửa sẽ bị tắt tiếng dần trong ba tháng.

### 6.2 Hợp đồng MCP — golden nghiêm ngặt

`tools/list` trả JSON schema của 4 tool → snapshot `golden/mcp_tools.json`, so sánh **chính xác**. Đổi tên tool, bỏ field, đổi kiểu tham số ⇒ đỏ. Muốn đổi thật thì phải sửa file golden — một hành động cố ý, hiện rõ trong diff PR. Đây là hợp đồng cứng với mọi agent đang cắm vào `center-kb`.

### 6.3 Golden output

- **Cứng**: chuỗi trả về của `kb_search`, `kb_get_section`, `kb_resolve` trên KB đóng băng (fixture `v0.9.0`).
- **Mềm**: stdout của `kb query` / `kb context new` / `kb diff`, sau khi chuẩn hoá phần biến động: đường dẫn tmp, commit SHA, timestamp, điểm số float.

Giá trị lớn nhất của tầng này không phải bắt lỗi code của bạn, mà bắt **nâng cấp dependency**: `rank-bm25` đổi công thức ⇒ thứ tự kết quả đổi ⇒ golden đỏ. Không có nó thì kiểu vỡ này tuyệt đối im lặng.

### 6.4 Tương thích federation/hub

Federation mới có từ v0.9.0 → chỉ một version trước để đối chiếu. Sinh fixture **một lần**: cài v0.9.0 vào venv → `kb publish --direct` lên bare hub → commit cây `federation/` kết quả vào `tests/regression/golden/federation-v0.9.0/`. Binary mới phải đọc được nó: `kb query --hub`, `kb resolve`, `kb doctor --hub` xanh.

(Đây là fixture *duy nhất* được commit thay vì lấy từ git history — vì `federation/` không nằm trong repo này, nó nằm trên hub.)

## 7. Luồng CI

### 7.1 Một cửa, ba nơi gọi

Toàn bộ T1–T4 sống trong `.github/workflows/_gate.yml` (`on: workflow_call`).

```
_gate.yml  (workflow_call)
  ├─ t1-tests        matrix {3.11, 3.12}   pytest tests/
  ├─ t2-package      build wheel+sdist → twine check --strict
  │                  → bảng version consistency (§7.3)
  │                  → sdist cài được vào venv sạch (smoke mỏng: canary + version + init + doctor + templates)
  ├─ t3-e2e          matrix {3.11, 3.12}   pip install wheel → KB_VENV=… pytest -m e2e
  └─ t4-regression   matrix {3.11, 3.12}   KB_VENV=… pytest -m regression   (fetch-depth: 0)
```

- `ci.yml`: `on: [pull_request, push: main]` → `uses: ./.github/workflows/_gate.yml`. Hết.
- `release.yml`: `on: push tags v*` → `uses: ./.github/workflows/_gate.yml` → rồi mới publish.

**Bất biến phải giữ: tag không chạy gì mới.** Nó chạy đúng cửa đã xanh trên PR, rồi thêm các job publish. Nếu bất biến này gãy (có bước chỉ chạy lúc tag), bạn quay về đúng chỗ cũ: phát hiện lỗi vào giây phút tệ nhất. Đây là lý do T3/T4 chạy matrix `{3.11, 3.12}` ở *cả hai* nơi, thay vì rút gọn trên PR cho nhanh.

### 7.2 Đồ thị phụ thuộc của `release.yml`

Sửa L7. Đồ thị mới:

```
_gate  ─┬─► docker-verify   build image + smoke + push tag sha-<commit>
        │                   (tag sha- vô hại, không phải tag release)
        │        │
        └────────┴─► pypi        publish PyPI   ◄─ irreversible, đi sau cùng mọi cửa
                     │
                     └─► docker-release   retag sha-<commit> → vX.Y.Z + latest
                                          (imagetools create, không build lại, ~5 giây)
```

Không có gì không-thể-hoàn-tác xảy ra trước khi toàn bộ cửa xanh. Và vì `docker-verify` build image = `pip install center-kb[ingest]` thật, tầng "extras có resolve được không" được phủ miễn phí (quyết định #8).

Job `docker-verify` giữ nguyên smoke test hiện có (serve KB rỗng → `/api/health` phải trả lời, `/api/docs` phải 401).

### 7.3 Bảng version consistency (job `t2-package`)

| Kiểm | Trên PR | Trên tag |
|---|---|---|
| `pyproject.version` == version trong `uv.lock` | ✓ | ✓ |
| `kb --version` (từ wheel đã cài) == `pyproject.version` | ✓ | ✓ |
| `twine check --strict` (metadata + README render trên PyPI) | ✓ | ✓ |
| wheel không lỡ đóng gói `tests/`, `.kb/`, `sources/` | ✓ | ✓ |
| tag `vX.Y.Z` == `pyproject.version` | — | ✓ |
| version chưa từng tồn tại trên PyPI | — | ✓ |

Hàng cuối chặn đúng cái đau nhất: phát hiện version đã bị chiếm *trước* khi upload, thay vì nhận HTTP 400 sau khi mọi job khác đã chạy xong.

### 7.4 Vận hành

- `concurrency: group=${{ github.ref }}, cancel-in-progress: true` — PR push liên tiếp không xếp hàng đốt runner.
- `fetch-depth: 0` cho job `t4-regression` (cần tag để `git archive`).
- Ngân sách thời gian ước tính: PR ~6–8 phút (các job song song); tag ~12–15 phút (thêm docker build với torch).

## 8. Hai thứ phải xây, không chỉ kiểm

1. **`kb --version`** — hiện **không tồn tại**. `@app.callback()` tại `src/center_kb/cli.py:28` là một hàm rỗng, không có option `--version`. Không có nó thì hai hàng đầu của bảng §7.3 không kiểm được, và user cũng không có cách nào biết mình đang chạy bản nào. Nguồn version: `importlib.metadata.version("center-kb")` (đọc từ metadata của gói đã cài — đúng thứ ta muốn khẳng định).

2. **Kiểm `uv.lock` đồng bộ với `pyproject.toml`** — lệnh là **`uv lock --check`** ("Check if the lockfile is up-to-date"), đã xác minh trên `uv 0.11.8`. Job `t2-package` phải cài `uv` (pin version trong workflow) và chạy lệnh này; lockfile lệch ⇒ đỏ. Đây chính là thứ đáng lẽ đã chặn được commit `chore: sync uv.lock to 0.9.0`.

## 9. Rủi ro và cách chống

| Rủi ro | Cách chống |
|---|---|
| Tầng T3/T4 thoái hoá thành test source tree | Test canary (quyết định #5) — đỏ ngay nếu `center_kb` import được ở runner. |
| Cửa xanh mà chạy 0 test | Fixture `artifact` raise nếu thiếu `KB_VENV`; `--strict-markers`. |
| Fixture seed trôi khỏi đầu ra thật của `kb ingest` | Test T1 ghim hình dạng đầu ra của `ingest` vào đúng fixture đó (quyết định #7). |
| Golden bị "sửa cho xanh" thay vì điều tra | Golden nằm trong file riêng → mọi thay đổi hiện rõ trong diff PR. Quy tắc §6.1 áp dụng cho cả §6.2/§6.3. |
| Cửa flaky vì mạng → bị vô hiệu hoá | Không parse PDF thật, không tải model HF trong cửa (xem "ngoài phạm vi"). |
| Tag bị xoá/viết lại → T4 đỏ | Chấp nhận có chủ đích: tag bất biến là hygiene tốt (quyết định #10). |
