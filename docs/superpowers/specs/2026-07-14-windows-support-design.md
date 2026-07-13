# Windows First-Class Support — Design

**Date:** 2026-07-14
**Status:** Approved pending review
**Liên quan:** `2026-07-14-hybrid-search-index-design.md` (search.db lifecycle trên Windows)

## 1. Mục tiêu

`pip install center-kb` trên Windows chạy đúng mọi command — không mojibake, không crash encoding, không file-lock, không path bug. CI gate chứng minh điều đó: Windows nằm trong matrix của các tier, giữ invariant "_gate.yml: PR chạy y hệt release".

**Non-goals**

- Long path > 260 ký tự: không code workaround — ghi README một dòng (`git config core.longpaths true` + registry `LongPathsEnabled`). Doctor check để sau nếu có user thật dính.
- Docker/compose flow: không đổi (Linux container, chạy được từ Docker Desktop).
- `scripts/gate.sh` (bash): dev Windows chạy qua Git Bash hoặc dựa vào CI — không port sang PowerShell.

## 2. Audit runtime (`src/`) — kết quả rà soát

Đã sạch: mọi `read_text`/`write_text` đều explicit `encoding="utf-8"`; không symlink/fcntl/signal/shell=True; `doctor.py`/`gitio.py` đã dùng `as_posix()` cho path ổn định; sqlite-vec + fastembed + docling có wheel Windows; FTS5 có sẵn trong sqlite bundled của python.org build.

Lỗi thật phải sửa:

### R1 — `subprocess.run(text=True)` decode bằng locale (cp1252)

`gitio._run`, `gitio.clone`, `publish._neutralize_excludes`, `llm.Runner.run`: `text=True` không kèm `encoding` → Windows decode cp1252. `claude -p` trả JSON UTF-8 (summary tiếng Việt) → mojibake hoặc `UnicodeDecodeError`; git output path non-ASCII cùng số phận. **Đây là bug runtime nặng nhất.**

Fix: thêm `encoding="utf-8", errors="replace"` vào **mọi** `subprocess.run(text=True)` trong `src/`. Một helper chung không bắt buộc — nhưng gom `gitio._run` + các call rời là đủ điểm chạm (grep `text=True` phải về 0 kết quả thiếu encoding, cả tests lẫn src cho phần chạy thật).

### R2 — stdout/stderr cp1252 khi pipe/redirect

Citation chứa `§`, nội dung KB chứa tiếng Việt. Console Windows hiện đại OK (PEP 528), nhưng **pipe/redirect** (`kb query ... > out.txt`, subprocess trong agent) dùng cp1252 → `UnicodeEncodeError` chết command.

Fix: đầu entrypoint CLI (`cli.py` callback) và `__main__` của `center_kb.mcp`:

```python
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")
```

### R3 — stdin cp1252 (`kb doctor --context -`)

`sys.stdin.read()` decode locale. Fix cùng chỗ R2: `sys.stdin.reconfigure(encoding="utf-8", errors="replace")`.

### R4 — Newline: file sinh ra phải LF

`Path.write_text` không có `newline=` → Windows ghi CRLF. Hệ quả: publish từ máy Windows rồi máy Linux → churn diff toàn file trên hub; content-hash lệch giữa OS.

Fix hai lớp:

1. Mọi `write_text` sinh **nội dung deterministic/committed** (`models.save_yaml_model`, `ingest/scaffold.py`, `summarize.py`, `initcmd.py`, `dockersetup.py`) thêm `newline="\n"`.
2. Thêm `.gitattributes` repo: `* text=auto eol=lf` (fixtures + templates ổn định trên runner Windows checkout).

(`mdutils.slice_section` dùng `splitlines()` — đã an toàn với CRLF đầu vào.)

### R5 — SQLite file lock (giao với search spec)

Windows không xoá được file đang mở. Search spec §5 có đường "DB hỏng → xoá rebuild": **phải close mọi connection trước khi unlink**, xoá kèm `search.db-wal`/`search.db-shm`, và unlink phải retry-tolerant (`PermissionError` → raise lỗi rõ, không loop vô hạn). Ghi thành ràng buộc trong search spec (§5 đã cập nhật).

### R6 — `shutil.rmtree` fail trên file readonly

`publish._snapshot` rmtree mirror cũ. Windows: file readonly → `PermissionError`. Fix: helper `rmtree` với `onexc` handler `os.chmod(path, stat.S_IWRITE)` rồi retry (pattern đã có sẵn trong `tests/test_hub.py`).

## 3. Audit test/gate — POSIX assumptions phải gỡ

### G1 — `venv/bin/` hardcode

`tests-gate/conftest.py` `Artifact.kb = venv/"bin"/"kb"`. Windows: `Scripts\kb.exe`, `Scripts\python.exe`. Fix: helper trong conftest:

```python
def venv_bin(venv: Path, name: str) -> Path:
    if os.name == "nt":
        exe = venv / "Scripts" / f"{name}.exe"
        return exe if exe.exists() else venv / "Scripts" / name
    return venv / "bin" / name
```

### G2 — Stub `claude` là script `#!/bin/sh`

`tests-gate/conftest.py:stub_claude`, `tests/test_summarize_e2e.py`, `tests/test_llm.py` (chỗ thực thi thật). `llm.py` tìm bằng `shutil.which("claude")` — Windows resolve qua `PATHEXT`. Fix: stub hai mảnh portable:

- `claude_impl.py` — python script: đọc hết stdin, in envelope (logic hiện tại).
- POSIX: file `claude` `#!/bin/sh` gọi python (như cũ). Windows: `claude.cmd`: `@python "%~dp0claude_impl.py" %*`.
- Gom thành một fixture/helper dùng chung (`_write_cli_stub(dir, name, body)`) để 3 chỗ không tự chế riêng.

### G3 — `tar -xf` external trong `_materialize_kb_at_tag`

Windows 10+ có `tar.exe` nhưng không cần đánh cược — thay bằng `tarfile.open(...).extractall(dest, filter="data")` (stdlib, mọi OS).

### G4 — Workflow steps hardcode `/tmp` + `bin/`

`_gate.yml` T2/T3/T4 dùng `/tmp/artifact/bin/pip`… Fix: mọi step `shell: bash` (Git Bash có sẵn trên runner Windows), venv path qua env:

```yaml
- shell: bash
  run: |
    BIN=$([ "$RUNNER_OS" = "Windows" ] && echo Scripts || echo bin)
    python -m venv "$RUNNER_TEMP/artifact"
    "$RUNNER_TEMP/artifact/$BIN/pip" install --quiet dist/*.whl
```

`KB_VENV` giữ nguyên semantics (trỏ venv root) — conftest tự resolve bin/Scripts qua G1.

## 4. CI matrix

Nguyên tắc: giữ invariant `_gate.yml` (PR = release, không step nào chỉ chạy lúc release). Windows thêm vào như chiều matrix, cân chi phí runner (Windows runner ~2× phút Linux):

| Tier | Linux | Windows | Lý do |
|---|---|---|---|
| T1 unit/integration | 3.11, 3.12, 3.13 | 3.11, 3.13 | Biên python đủ bắt lỗi OS×version; 3.12 đã có Linux cover |
| T2 packaging | 3.12 | — | Wheel pure-python, build OS-independent; artifact windows test ở T3 |
| T3 e2e artifact | 3.11, 3.12, 3.13 | 3.12 | Black-box wheel trên Windows một version — rủi ro OS-specific (path/encoding/subprocess) không phụ thuộc python minor |
| T4 regression | 3.11, 3.12, 3.13 | 3.12 | Như T3 |

Cách khai: thêm `os` vào matrix (`runs-on: ${{ matrix.os }}`) với `include`/`exclude` thay vì nhân full — tránh 6 job×tier.

Windows job cần: `git config --global core.autocrlf false` trước checkout? Không — `.gitattributes` (R4) đã ép LF, không phụ thuộc config runner.

## 5. Định nghĩa "xong" (gate)

- Toàn bộ T1/T3/T4 xanh trên windows-latest theo matrix §4.
- Grep guard (test unit nhỏ hoặc ruff custom không cần — một test `test_windows_hygiene.py` trong T1):
  - không còn `subprocess.run` với `text=True` thiếu `encoding=` trong `src/`;
  - không còn `write_text` thiếu `newline=` trong nhóm file sinh nội dung committed (danh sách module R4).
- README: mục Windows (supported ✓, long-path note).

## 6. Testing

- **Unit mới**: `venv_bin` helper; rmtree-readonly helper (tạo file readonly rồi xoá); stub CLI helper chạy được trên cả hai OS (skipif theo os cho nhánh kia); hygiene test §5.
- **Hiện có**: toàn bộ suite chính là bài test — mục tiêu là chúng pass trên Windows không sửa assertion (sửa fixture/POSIX-ism, không sửa behavior).
- Encoding regression: test T1 pipe output `kb query` chứa `§` + tiếng Việt qua `subprocess` với `PYTHONIOENCODING` unset và stdout là pipe — không được raise (chạy được trên cả hai OS, chỉ Windows từng fail).

## 7. Thứ tự triển khai (phác)

1. Runtime fixes R1–R4, R6 (+ hygiene test §5) — độc lập, merge trước.
2. Test/gate fixes G1–G3 (chạy được pytest local trên Windows).
3. Workflow G4 + matrix §4 — bật Windows CI, sửa nốt những gì CI Windows phát hiện thêm.
4. R5 thuộc implementation của search spec (đã ghi ràng buộc bên đó).

Lưu ý thứ tự với search spec: workstream Windows (bước 1–3) merge **trước** implementation search — search code mới viết ra là Windows-clean từ đầu và được CI Windows canh ngay.
