# Windows First-Class Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** center-kb cài và chạy đúng mọi command trên Windows (không mojibake, không crash encoding, không file-lock, không path bug), và CI gate có Windows trong matrix để chứng minh + giữ điều đó.

**Architecture:** Ba lớp: (1) runtime fixes trong `src/center_kb` — subprocess UTF-8, stdio reconfigure, newline LF, rmtree readonly; (2) gỡ POSIX-ism trong tests/tests-gate — venv layout, CLI stub portable, tarfile; (3) `_gate.yml` thêm Windows vào matrix T1/T3/T4. Hygiene tests chặn tái phạm.

**Tech Stack:** Python 3.11–3.13, pytest, GitHub Actions (`windows-latest`), Git Bash làm shell chung cho workflow steps.

**Spec:** `docs/superpowers/specs/2026-07-14-windows-support-design.md`

## Global Constraints

- Python floor 3.11 (matrix 3.11/3.12/3.13) — không dùng API mới hơn 3.11 vô điều kiện (`shutil.rmtree(onexc=...)` là 3.12+, phải branch).
- Mọi `subprocess.run(..., text=True)` trong `src/` PHẢI kèm `encoding="utf-8", errors="replace"`.
- Mọi `write_text` sinh nội dung deterministic/committed (`models.py`, `initcmd.py`, `dockersetup.py`, `summarize.py`, `ingest/scaffold.py`) PHẢI kèm `newline="\n"`. (`hub.py` marker và `ingest/parser.py` cache là local-only — miễn.)
- `tests-gate/` KHÔNG ĐƯỢC import `center_kb` (rule sẵn có — stub helper phải duplicate, không import từ `tests/`).
- `_gate.yml` invariant: không step nào chỉ chạy lúc release; Windows thêm như chiều matrix.
- Chạy test cục bộ trên máy dev này (Windows) chính là bài verification tự nhiên: `pytest tests/ -q` phải xanh sau các task runtime/test-fix.
- Commit message: conventional commits, không attribution.

---

### Task 1: Hygiene test + subprocess UTF-8 (spec R1)

**Files:**
- Create: `tests/test_windows_hygiene.py`
- Modify: `src/center_kb/gitio.py:11-14` (`_run`), `src/center_kb/gitio.py:67-73` (`clone`)
- Modify: `src/center_kb/ghio.py:12-13` (`_run_gh`)
- Modify: `src/center_kb/llm.py:43-46` (`Runner.run`)
- Modify: `src/center_kb/publish.py:43-48` (`_neutralize_excludes`)

**Interfaces:**
- Produces: hygiene test `tests/test_windows_hygiene.py` — Task 2 sẽ thêm test thứ hai vào cùng file. Không API mới; chữ ký các hàm sửa giữ nguyên.

- [ ] **Step 1: Viết hygiene test (fail trước fix)**

Tạo `tests/test_windows_hygiene.py`:

```python
"""Guards against Windows-breaking patterns (spec 2026-07-14-windows-support).

subprocess text=True without encoding decodes with the locale codepage
(cp1252) on Windows — UTF-8 output from git/claude gets mojibaked."""
import re
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "center_kb"


def _windows(text: str, needle: str, span: int = 300) -> list[str]:
    """A ±span-char window around each occurrence of needle."""
    return [
        text[max(0, m.start() - span): m.start() + span]
        for m in re.finditer(re.escape(needle), text)
    ]


def test_subprocess_text_true_always_sets_utf8():
    offenders = []
    for py in sorted(SRC.rglob("*.py")):
        text = py.read_text(encoding="utf-8")
        for window in _windows(text, "text=True"):
            if 'encoding="utf-8"' not in window:
                offenders.append(str(py.relative_to(SRC)))
    assert not offenders, (
        f"subprocess text=True without encoding=\"utf-8\" in: {offenders} — "
        "on Windows this decodes with cp1252 and mojibakes UTF-8 output"
    )
```

- [ ] **Step 2: Chạy test, xác nhận FAIL**

Run: `pytest tests/test_windows_hygiene.py -v`
Expected: FAIL, offenders chứa `gitio.py`, `ghio.py`, `llm.py`, `publish.py`.

- [ ] **Step 3: Fix 5 call site**

`gitio.py` `_run`:

```python
def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
```

`gitio.py` `clone`:

```python
    proc = subprocess.run(
        ["git", "clone", url, str(dest)], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
```

`ghio.py` `_run_gh`:

```python
def _run_gh(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gh", *args], cwd=root, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
```

`llm.py` `Runner.run`:

```python
            proc = subprocess.run(
                cmd, input=stdin, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=self.timeout, env=env,
            )
```

`publish.py` `_neutralize_excludes`:

```python
    subprocess.run(
        ["git", "config", "core.excludesFile", ""],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
```

- [ ] **Step 4: Chạy hygiene test + suite, xác nhận PASS**

Run: `pytest tests/test_windows_hygiene.py -v` → PASS
Run: `pytest tests/ -q` → các test sẵn có không vỡ (test_llm dùng stub sh — trên máy Windows này chúng có thể FAIL sẵn từ trước; ghi nhận, Task 6 sửa — chỉ cần không có FAIL MỚI ngoài nhóm đó).

- [ ] **Step 5: Commit**

```bash
git add tests/test_windows_hygiene.py src/center_kb/gitio.py src/center_kb/ghio.py src/center_kb/llm.py src/center_kb/publish.py
git commit -m "fix: force utf-8 decode on all subprocess text output (windows cp1252)"
```

---

### Task 2: newline LF cho file sinh ra + .gitattributes (spec R4)

**Files:**
- Modify: `tests/test_windows_hygiene.py` (thêm test thứ hai)
- Modify: `src/center_kb/models.py:90`, `src/center_kb/initcmd.py:102,130,134`, `src/center_kb/dockersetup.py:55,86`, `src/center_kb/summarize.py:277,335-338`, `src/center_kb/ingest/scaffold.py:83-84`
- Create: `.gitattributes`

**Interfaces:**
- Consumes: `tests/test_windows_hygiene.py` từ Task 1 (cùng file, thêm hàm test).
- Produces: không API mới.

- [ ] **Step 1: Thêm hygiene test newline (fail trước fix)**

Append vào `tests/test_windows_hygiene.py`:

```python
# Writers whose output is committed content (KB YAML, L2/L3 markdown,
# templates) — CRLF from a Windows machine would churn hub diffs and skew
# content hashes. hub.py (marker) and ingest/parser.py (cache) are local-only.
COMMITTED_WRITERS = [
    "models.py",
    "initcmd.py",
    "dockersetup.py",
    "summarize.py",
    "ingest/scaffold.py",
]


def test_committed_writers_force_lf_newline():
    offenders = []
    for rel in COMMITTED_WRITERS:
        text = (SRC / rel).read_text(encoding="utf-8")
        for m in re.finditer(re.escape("write_text("), text):
            window = text[m.start(): m.start() + 300]
            if 'newline="\\n"' not in window:
                offenders.append(rel)
    assert not offenders, (
        f"write_text without newline=\"\\n\" in committed-content writers: {offenders}"
    )
```

Lưu ý: trong source test, chuỗi cần tìm là `newline="\n"` literal trong code — viết pattern là `'newline="\\n"'` (escape trong Python string của test) sao cho khớp text `newline="\n"`.

- [ ] **Step 2: Chạy, xác nhận FAIL**

Run: `pytest tests/test_windows_hygiene.py::test_committed_writers_force_lf_newline -v`
Expected: FAIL với đủ 5 module.

- [ ] **Step 3: Thêm `newline="\n"` vào 10 call site**

Mẫu (áp cho từng dòng liệt kê ở Files):

```python
# models.py:90
    path.write_text(text, encoding="utf-8", newline="\n")

# initcmd.py:102
    config_path.write_text(text + f"kind: {kind}\n", encoding="utf-8", newline="\n")

# initcmd.py:130 và :134
            dest.write_text(text, encoding="utf-8", newline="\n")

# dockersetup.py:55
    env_path.write_text(content, encoding="utf-8", newline="\n")

# dockersetup.py:86
    gitignore.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

# summarize.py:277
            (kb_dir / doc / f"{stem}.md").write_text(
                text, encoding="utf-8", newline="\n"
            )

# summarize.py:335-338
                path.write_text(
                    rebuild_l2_scaffold(path.read_text(encoding="utf-8")),
                    encoding="utf-8",
                    newline="\n",
                )

# ingest/scaffold.py:83-84
        (doc_dir / f"{stem}.raw.md").write_text(
            "\n".join(l3_lines), encoding="utf-8", newline="\n"
        )
        (doc_dir / f"{stem}.md").write_text(
            "\n".join(l2_lines), encoding="utf-8", newline="\n"
        )
```

- [ ] **Step 4: Tạo `.gitattributes` ở repo root**

```
* text=auto eol=lf
*.pdf binary
*.png binary
*.jpg binary
*.tar binary
```

- [ ] **Step 5: Chạy test, xác nhận PASS**

Run: `pytest tests/test_windows_hygiene.py -v` → 2 PASS
Run: `pytest tests/ -q` → không FAIL mới.

- [ ] **Step 6: Commit**

```bash
git add tests/test_windows_hygiene.py src/center_kb/models.py src/center_kb/initcmd.py src/center_kb/dockersetup.py src/center_kb/summarize.py src/center_kb/ingest/scaffold.py .gitattributes
git commit -m "fix: write committed KB content with LF on every OS; add .gitattributes"
```

---

### Task 3: UTF-8 stdio dùng chung cho CLI + MCP (spec R2/R3)

**Files:**
- Create: `src/center_kb/utf8io.py`
- Create: `tests/test_utf8io.py`
- Modify: `src/center_kb/cli.py:12-18` (thay loop inline bằng gọi helper)
- Modify: `src/center_kb/mcp.py:224-226` (`main` — gọi helper đầu hàm)

**Interfaces:**
- Produces: `center_kb.utf8io.force_utf8_streams() -> None` — reconfigure `sys.stdin/stdout/stderr` sang UTF-8 nếu chưa phải và stream hỗ trợ `.reconfigure()`. Task nào sau này thêm entrypoint mới đều gọi hàm này.

- [ ] **Step 1: Viết test (fail trước fix)**

Tạo `tests/test_utf8io.py`:

```python
"""Windows pipes/redirects default to cp1252 — force UTF-8 at the entrypoints
(spec 2026-07-14-windows-support R2/R3)."""
import os
import subprocess
import sys


def _run_py(code: str, input_bytes: bytes = b"") -> subprocess.CompletedProcess[bytes]:
    # PYTHONIOENCODING=cp1252 simulates a Windows pipe on any OS.
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    return subprocess.run(
        [sys.executable, "-c", code], input=input_bytes,
        capture_output=True, env=env,
    )


def test_cli_import_forces_utf8_stdout():
    proc = _run_py("from center_kb import cli\nprint('§ tiếng Việt')")
    assert proc.returncode == 0, proc.stderr
    assert "§ tiếng Việt".encode("utf-8") in proc.stdout


def test_cli_import_forces_utf8_stdin():
    # Without the fix, UTF-8 bytes on stdin decode as cp1252 → mojibake.
    proc = _run_py(
        "from center_kb import cli\nimport sys\nsys.stdout.write(sys.stdin.read())",
        input_bytes="§ tiếng Việt".encode("utf-8"),
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.decode("utf-8") == "§ tiếng Việt"


class _FakeStream:
    def __init__(self, encoding: str) -> None:
        self.encoding = encoding
        self.calls: list[dict] = []

    def reconfigure(self, **kwargs) -> None:
        self.calls.append(kwargs)


def test_force_utf8_streams_skips_utf8_and_reconfigures_legacy(monkeypatch):
    from center_kb import utf8io

    legacy, modern = _FakeStream("cp1252"), _FakeStream("utf-8")
    monkeypatch.setattr(utf8io.sys, "stdin", legacy)
    monkeypatch.setattr(utf8io.sys, "stdout", modern)
    monkeypatch.setattr(utf8io.sys, "stderr", _FakeStream("UTF-8"))
    utf8io.force_utf8_streams()
    assert legacy.calls == [{"encoding": "utf-8"}]
    assert modern.calls == []


def test_force_utf8_streams_tolerates_streams_without_reconfigure(monkeypatch):
    from center_kb import utf8io

    monkeypatch.setattr(utf8io.sys, "stdin", object())  # e.g. test doubles
    utf8io.force_utf8_streams()  # must not raise
```

- [ ] **Step 2: Chạy, xác nhận FAIL**

Run: `pytest tests/test_utf8io.py -v`
Expected: `test_cli_import_forces_utf8_stdin` FAIL (mojibake); các test import `utf8io` FAIL với ModuleNotFoundError. (`test_cli_import_forces_utf8_stdout` có thể PASS sẵn — cli.py đã reconfigure stdout từ trước; giữ làm regression.)

- [ ] **Step 3: Tạo `src/center_kb/utf8io.py`**

```python
from __future__ import annotations

import sys


def force_utf8_streams() -> None:
    """Reconfigure stdin/stdout/stderr to UTF-8.

    Windows consoles are UTF-8-capable since PEP 528, but pipes/redirects
    still default to the locale codepage (cp1252) — printing '§' or reading
    Vietnamese input then crashes or mojibakes. Guarded: test doubles and
    exotic streams may lack .reconfigure().
    """
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        encoding = getattr(stream, "encoding", None) or ""
        if encoding.lower().replace("-", "") != "utf8" and hasattr(
            stream, "reconfigure"
        ):
            stream.reconfigure(encoding="utf-8")
```

- [ ] **Step 4: Dùng helper ở hai entrypoint**

`cli.py` — thay khối dòng 12–18 (comment + for loop) bằng:

```python
from center_kb.utf8io import force_utf8_streams

force_utf8_streams()
```

(giữ vị trí trước `app = typer.Typer(...)`; xoá biến `_stream`/`_enc` cũ.)

`mcp.py` — đầu hàm `main`:

```python
def main(argv: list[str] | None = None) -> None:
    from center_kb.utf8io import force_utf8_streams

    force_utf8_streams()
    logging.basicConfig(level=logging.INFO)
```

- [ ] **Step 5: Chạy test, xác nhận PASS**

Run: `pytest tests/test_utf8io.py -v` → PASS toàn bộ
Run: `pytest tests/ -q` → không FAIL mới.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/utf8io.py src/center_kb/cli.py src/center_kb/mcp.py tests/test_utf8io.py
git commit -m "fix: force utf-8 stdin/stdout/stderr at cli and mcp entrypoints"
```

---

### Task 4: rmtree chịu được file readonly (spec R6)

**Files:**
- Modify: `src/center_kb/publish.py:71` (`_snapshot` — thay `shutil.rmtree(dest)`), thêm helper `_rmtree_force` + import `os`, `stat`, `sys`
- Test: `tests/test_publish_rmtree.py` (create)

**Interfaces:**
- Produces: `publish._rmtree_force(path: Path) -> None` (private, chỉ publish dùng).

- [ ] **Step 1: Viết test (fail trước fix)**

Tạo `tests/test_publish_rmtree.py`:

```python
"""Windows sets PermissionError on rmtree of read-only files — publish
re-snapshots over an existing mirror and must not die on them."""
import os
import stat
from pathlib import Path

from center_kb import publish


def test_rmtree_force_removes_readonly_file(tmp_path: Path):
    tree = tmp_path / "mirror"
    (tree / "doc").mkdir(parents=True)
    victim = tree / "doc" / "ro.md"
    victim.write_text("x", encoding="utf-8")
    os.chmod(victim, stat.S_IREAD)

    publish._rmtree_force(tree)

    assert not tree.exists()
```

- [ ] **Step 2: Chạy, xác nhận FAIL**

Run: `pytest tests/test_publish_rmtree.py -v`
Expected: FAIL — `AttributeError: module 'center_kb.publish' has no attribute '_rmtree_force'`.

- [ ] **Step 3: Implement trong `publish.py`**

Thêm import `os`, `stat`, `sys` (đầu file, `shutil` đã có). Thêm helper trên `_snapshot`:

```python
def _rmtree_force(path: Path) -> None:
    """shutil.rmtree that clears the Windows read-only attribute and retries.

    onexc is the 3.12+ replacement for onerror — both accept the same
    (func, path, exc) shape here, only the exc argument differs.
    """

    def _clear_and_retry(func, p, _exc) -> None:
        os.chmod(p, stat.S_IWRITE)
        func(p)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_clear_and_retry)
    else:
        shutil.rmtree(path, onerror=_clear_and_retry)
```

Trong `_snapshot`, thay `shutil.rmtree(dest)` bằng `_rmtree_force(dest)`.

- [ ] **Step 4: Chạy test, xác nhận PASS**

Run: `pytest tests/test_publish_rmtree.py tests/ -q` → PASS, không FAIL mới.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/publish.py tests/test_publish_rmtree.py
git commit -m "fix: publish snapshot survives read-only files in old mirror (windows)"
```

---

### Task 5: tests-gate — venv layout + tarfile (spec G1, G3)

**Files:**
- Modify: `tests-gate/conftest.py:62-91` (`Artifact`, `artifact` fixture — thêm `venv_bin`), `tests-gate/conftest.py:281-293` (`_materialize_kb_at_tag` — bỏ `tar` external)

**Interfaces:**
- Produces: `venv_bin(venv: Path, name: str) -> Path` trong `tests-gate/conftest.py`; `Artifact.kb`/`Artifact.python` giữ nguyên tên (property, resolve theo OS). Task 7 (workflow) dựa vào semantics "KB_VENV trỏ venv root, conftest tự resolve bin/Scripts".

- [ ] **Step 1: Sửa `Artifact` + `artifact` fixture**

Thay class `Artifact` và fixture `artifact` hiện tại bằng:

```python
def venv_bin(venv: Path, name: str) -> Path:
    """Path of an installed executable inside a venv, on any OS."""
    if os.name == "nt":
        exe = venv / "Scripts" / f"{name}.exe"
        return exe if exe.exists() else venv / "Scripts" / name
    return venv / "bin" / name


@dataclass(frozen=True)
class Artifact:
    venv: Path

    @property
    def kb(self) -> Path:
        return venv_bin(self.venv, "kb")

    @property
    def python(self) -> Path:
        return venv_bin(self.venv, "python")


@pytest.fixture(scope="session")
def artifact() -> Artifact:
    raw = os.environ.get("KB_VENV")
    if not raw:
        # RAISE, do not skip. A green CI job that collected 0 tests is the most
        # dangerous failure mode a release gate has — it gives a false sense of
        # safety.
        raise RuntimeError(
            "KB_VENV is not set. The e2e/regression tiers run against the "
            "INSTALLED WHEEL, never against the source tree. Use: ./scripts/gate.sh"
        )
    art = Artifact(venv=Path(raw))
    if not art.kb.exists():
        raise RuntimeError(
            f"KB_VENV={art.venv} has no kb executable ({art.kb}) — "
            "was the wheel installed into it?"
        )
    return art
```

- [ ] **Step 2: Thay `tar -xf` bằng `tarfile`**

Trong `_materialize_kb_at_tag`, thêm `import tarfile` vào imports đầu file, thay:

```python
    subprocess.run(["tar", "-xf", str(archive)], cwd=dest_repo, check=True)
```

bằng:

```python
    with tarfile.open(archive) as tf:
        tf.extractall(dest_repo, filter="data")
```

- [ ] **Step 3: Verify bằng cách chạy gate tier cục bộ (Git Bash trên máy Windows này)**

```bash
python -m build --wheel
python -m venv .venv-artifact && .venv-artifact/Scripts/pip install --quiet dist/*.whl
python -m venv .venv-runner && .venv-runner/Scripts/pip install --quiet -r requirements-gate.txt
KB_VENV=.venv-artifact .venv-runner/Scripts/pytest tests-gate/regression -q
```

Expected: fixture `artifact` resolve `Scripts\kb.exe`; regression tier chạy (một số test có thể fail vì stub claude chưa portable — Task 6; ghi nhận, không được fail vì `bin/kb` hay `tar`).

- [ ] **Step 4: Commit**

```bash
git add tests-gate/conftest.py
git commit -m "test: resolve venv executables per-OS and untar fixtures with tarfile"
```

---

### Task 6: CLI stub portable (spec G2) + PATH separator

**Files:**
- Create: `tests/cli_stub.py`
- Modify: `tests/test_llm.py` (bỏ `make_stub` sh, dùng helper; sửa 4 call site Runner.run)
- Modify: `tests/test_summarize_e2e.py` (`_install_stub_claude` + mọi call site + `prepend=os.pathsep`)
- Modify: `tests-gate/conftest.py:140-151` (`stub_claude` fixture — duplicate helper, KHÔNG import từ `tests/`)

**Interfaces:**
- Produces: `tests/cli_stub.py`:
  - `write_cli_stub(bindir: Path, name: str, python_body: str) -> Path` — tạo executable `name` chạy được trên cả POSIX (`#!/bin/sh` wrapper) và Windows (`name.cmd` wrapper), body là Python source chạy bằng `sys.executable`.
  - `echo_after_stdin(payload: str) -> str` — body: đọc hết stdin rồi in `payload`.
  - `echo(payload: str) -> str` — body: in `payload` (không đọc stdin — cho copilot nhận prompt qua argv).

- [ ] **Step 1: Tạo `tests/cli_stub.py`**

```python
"""Portable fake CLI executables — '#!/bin/sh' stubs don't run on Windows.

The stub is a two-part pair: <name>_impl.py (the behavior, plain Python) plus
a thin OS wrapper — `<name>` sh script on POSIX, `<name>.cmd` on Windows
(shutil.which resolves .cmd via PATHEXT)."""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path


def write_cli_stub(bindir: Path, name: str, python_body: str) -> Path:
    bindir.mkdir(parents=True, exist_ok=True)
    impl = bindir / f"{name}_impl.py"
    impl.write_text(python_body, encoding="utf-8", newline="\n")
    if os.name == "nt":
        stub = bindir / f"{name}.cmd"
        stub.write_text(f'@"{sys.executable}" "{impl}" %*\n', encoding="utf-8")
        return stub
    stub = bindir / name
    stub.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{impl}" "$@"\n',
        encoding="utf-8", newline="\n",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    return stub


def echo_after_stdin(payload: str) -> str:
    """Consume stdin (claude -p pipes the prompt), then print payload."""
    return f"import sys\nsys.stdin.read()\nsys.stdout.write({payload!r} + '\\n')\n"


def echo(payload: str) -> str:
    """Print payload without touching stdin (copilot takes prompt as argv)."""
    return f"import sys\nsys.stdout.write({payload!r} + '\\n')\n"
```

- [ ] **Step 2: Rewrite `tests/test_llm.py` stub usage**

Thay `make_stub` + 4 test `Runner.run`:

```python
from tests.cli_stub import echo, echo_after_stdin, write_cli_stub

# ... (các test detect_runner giữ nguyên — chúng chỉ mock shutil.which)

def test_claude_run_unwraps_json_envelope(tmp_path):
    inner = json.dumps({"l2_summary": "x", "l1_summary": "y"})
    envelope = json.dumps({"type": "result", "result": inner})
    exe = write_cli_stub(tmp_path, "claude", echo_after_stdin(envelope))
    runner = llm.Runner("claude", str(exe), "sonnet-5", "high", 30)
    assert json.loads(runner.run("prompt")) == {"l2_summary": "x", "l1_summary": "y"}


def test_copilot_run_returns_plain_stdout(tmp_path):
    exe = write_cli_stub(
        tmp_path, "copilot", echo('{"l2_summary": "a", "l1_summary": "b"}')
    )
    runner = llm.Runner("copilot", str(exe), "gpt-5", "high", 30)
    assert '"l2_summary"' in runner.run("prompt")


def test_run_raises_on_nonzero_exit(tmp_path):
    exe = write_cli_stub(
        tmp_path, "claude", "import sys\nsys.stdin.read()\nsys.exit(3)\n"
    )
    runner = llm.Runner("claude", str(exe), "sonnet-5", "high", 30)
    with pytest.raises(llm.RunnerError):
        runner.run("prompt")


def test_run_raises_on_timeout(tmp_path):
    exe = write_cli_stub(
        tmp_path, "claude",
        "import sys, time\nsys.stdin.read()\ntime.sleep(5)\n",
    )
    runner = llm.Runner("claude", str(exe), "sonnet-5", "high", 1)
    with pytest.raises(llm.RunnerError):
        runner.run("prompt")
```

Xoá hàm `make_stub` cũ và import `stat` nếu không còn dùng.

- [ ] **Step 3: Rewrite `tests/test_summarize_e2e.py` stub**

```python
import os

from tests.cli_stub import echo_after_stdin, write_cli_stub


def _install_stub_claude(tmp_path: Path, monkeypatch, payload: str) -> None:
    bindir = tmp_path / "bin"
    write_cli_stub(bindir, "claude", echo_after_stdin(payload))
    monkeypatch.setenv("PATH", str(bindir), prepend=os.pathsep)
```

Sửa MỌI call site trong file (grep `_install_stub_claude(`): tham số thứ ba đổi từ shell body sang payload thuần — ví dụ `_install_stub_claude(tmp_path, monkeypatch, f"cat > /dev/null\necho '{DOC_ENVELOPE}'")` thành `_install_stub_claude(tmp_path, monkeypatch, DOC_ENVELOPE)`; body `"cat > /dev/null\necho 'not json'"` thành `"not json"`. Xoá import `stat` nếu không còn dùng.

- [ ] **Step 4: Rewrite `stub_claude` fixture trong `tests-gate/conftest.py`**

(duplicate helper — tests-gate không import gì từ `tests/`; thêm `import sys` đầu file nếu chưa có)

```python
@pytest.fixture
def stub_claude(tmp_path_factory) -> dict[str, str]:
    """A fake `claude` on PATH, runnable on POSIX and Windows. center_kb/llm.py
    probes with shutil.which("claude") — .cmd resolves via PATHEXT on Windows.
    (Deliberately duplicated from tests/cli_stub.py: tests-gate must stay
    self-contained.)"""
    bindir = tmp_path_factory.mktemp("stub-bin")
    impl = bindir / "claude_impl.py"
    impl.write_text(
        f"import sys\nsys.stdin.read()\nsys.stdout.write({CLAUDE_ENVELOPE!r} + '\\n')\n",
        encoding="utf-8", newline="\n",
    )
    if os.name == "nt":
        (bindir / "claude.cmd").write_text(
            f'@"{sys.executable}" "{impl}" %*\n', encoding="utf-8"
        )
    else:
        script = bindir / "claude"
        script.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{impl}" "$@"\n',
            encoding="utf-8", newline="\n",
        )
        script.chmod(0o755)
    return {"PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
```

- [ ] **Step 5: Chạy toàn bộ T1 trên máy Windows này, xác nhận xanh**

Run: `pytest tests/ -q`
Expected: PASS toàn bộ — đây là mốc "T1 chạy sạch trên Windows local".

Run lại tier gate như Task 5 Step 3 (`KB_VENV=.venv-artifact ... pytest tests-gate/e2e -q` — cần rebuild wheel vì src đã đổi): các test dùng stub claude giờ phải qua được phần summarize.

- [ ] **Step 6: Commit**

```bash
git add tests/cli_stub.py tests/test_llm.py tests/test_summarize_e2e.py tests-gate/conftest.py
git commit -m "test: portable CLI stubs and os.pathsep PATH handling for windows"
```

---

### Task 7: Windows trong CI matrix + workflow bash-hoá (spec G4, §4) + README

**Files:**
- Modify: `.github/workflows/_gate.yml` (T1 matrix, T3/T4 matrix + steps)
- Modify: `README.md` (mục Windows)

**Interfaces:**
- Consumes: semantics `KB_VENV` trỏ venv root (Task 5).
- Produces: matrix chuẩn spec §4 — T1: ubuntu×{3.11,3.12,3.13} + windows×{3.11,3.13}; T3/T4: ubuntu×{3.11,3.12,3.13} + windows×{3.12}; T2 giữ nguyên ubuntu.

- [ ] **Step 1: Sửa `t1-tests`**

```yaml
  t1-tests:
    name: T1 unit/integration (${{ matrix.os }}, py${{ matrix.python }})
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest]
        python: ["3.11", "3.12", "3.13"]
        include:
          # Windows on the python floor+ceiling only — OS-specific risk does
          # not multiply with python minor; 3.12 is covered on ubuntu.
          - os: windows-latest
            python: "3.11"
          - os: windows-latest
            python: "3.13"
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - run: pip install -e ".[dev]"
      - run: pytest -q
        env:
          GIT_AUTHOR_NAME: ci-test
          GIT_AUTHOR_EMAIL: ci-test@local
          GIT_COMMITTER_NAME: ci-test
          GIT_COMMITTER_EMAIL: ci-test@local
```

(giữ nguyên comment giải thích GIT_* hiện có nếu muốn — nội dung env không đổi)

- [ ] **Step 2: Sửa `t3-e2e` — matrix + steps bash**

```yaml
  t3-e2e:
    name: T3 e2e on the artifact (${{ matrix.os }}, py${{ matrix.python }})
    runs-on: ${{ matrix.os }}
    needs: t2-package
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest]
        python: ["3.11", "3.12", "3.13"]
        include:
          - os: windows-latest
            python: "3.12"
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      # (giữ comment "EXACT wheel" hiện có)
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist
      - name: Artifact venv (wheel ONLY)
        shell: bash
        run: |
          BIN=$([ "$RUNNER_OS" = "Windows" ] && echo Scripts || echo bin)
          python -m venv .venv-artifact
          ".venv-artifact/$BIN/pip" install --quiet dist/*.whl
      - name: Runner venv (pytest, WITHOUT center-kb)
        shell: bash
        run: |
          BIN=$([ "$RUNNER_OS" = "Windows" ] && echo Scripts || echo bin)
          python -m venv .venv-runner
          ".venv-runner/$BIN/pip" install --quiet -r requirements-gate.txt
      - name: pytest tests-gate/e2e
        shell: bash
        run: |
          BIN=$([ "$RUNNER_OS" = "Windows" ] && echo Scripts || echo bin)
          KB_VENV=.venv-artifact ".venv-runner/$BIN/pytest" tests-gate/e2e -q
```

Ghi chú cho người implement: venv đặt **in-tree tương đối** (`.venv-artifact`) thay vì `/tmp` — né hẳn vấn đề path separator của `$RUNNER_TEMP` trên Windows trong Git Bash; `KB_VENV` tương đối OK vì pytest chạy từ repo root và conftest chỉ `Path(raw)`.

- [ ] **Step 3: Sửa `t4-regression` — y hệt t3 (matrix include windows 3.12, ba step bash như trên, dòng cuối `KB_VENV=.venv-artifact ".venv-runner/$BIN/pytest" tests-gate/regression -q`), giữ `fetch-depth: 0`.**

- [ ] **Step 4: Thêm mục Windows vào README**

Chèn sau phần cài đặt hiện có:

```markdown
## Windows

Windows is fully supported — `pip install center-kb` and every `kb` command
run natively (CI gates every release on `windows-latest`).

One OS-level note: very deep KB trees can exceed the legacy 260-character
path limit. If you hit `FileNotFoundError` on long paths, enable long paths
once: `git config --global core.longpaths true`, and set the registry key
`HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled = 1`.
```

- [ ] **Step 5: Validate cú pháp workflow cục bộ**

Run: `python -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('.github/workflows/_gate.yml').read_text(encoding='utf-8')); print('yaml ok')"`
Expected: `yaml ok`

- [ ] **Step 6: Commit + đẩy PR để CI Windows chạy thật**

```bash
git add .github/workflows/_gate.yml README.md
git commit -m "ci: add windows to T1/T3/T4 gate matrix; document windows support"
```

Toàn bộ workstream này nên đi trên một branch (vd `feat/windows-support`) → PR; job Windows xanh trên PR chính là Definition of Done của spec §5. Nếu CI Windows phát hiện lỗi mới (điều spec đã dự liệu: "sửa nốt những gì CI Windows phát hiện thêm"), fix trong PR này.

---

## Definition of Done (spec §5)

- [ ] T1/T3/T4 xanh trên windows-latest theo matrix trên (PR run).
- [ ] `pytest tests/ -q` xanh trên máy dev Windows.
- [ ] Hygiene tests chặn: `text=True` thiếu encoding; `write_text` thiếu newline trong nhóm committed-writers.
- [ ] README có mục Windows.
