# Cửa kiểm định trước release (E2E + Smoke + Regression) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dựng bốn tầng cửa kiểm định (T1 unit → T2 đóng gói → T3 e2e trên artifact → T4 regression) chạy giống hệt nhau ở máy dev, PR và tag; không có hành động không-thể-hoàn-tác nào (publish PyPI, đẩy tag GHCR) xảy ra trước khi toàn bộ cửa xanh.

**Architecture:** T3/T4 là các bộ pytest **không bao giờ import `center_kb`** — chúng gọi binary `kb` đã cài trong một venv riêng (`$KB_VENV`) qua `subprocess`, coi package như hộp đen. Toàn bộ T1–T4 sống trong một reusable workflow `.github/workflows/_gate.yml` mà cả `ci.yml` (PR/push main) lẫn `release.yml` (tag) đều `uses:`, nên tag không chạy gì mới so với PR.

**Tech Stack:** Python 3.11/3.12, pytest, hatchling, `python -m build`, `twine`, `uv` (lockfile check), GitHub Actions (reusable workflow), Docker/GHCR, MCP Python SDK (client), PyYAML.

**Spec:** `docs/superpowers/specs/2026-07-13-release-verification-gate-design.md`

## Global Constraints

- **Python floor: 3.11.** `requires-python = ">=3.11"`. Mọi tầng chạy matrix `{3.11, 3.12}` ở **cả** PR lẫn tag — không rút gọn trên PR, vì bất biến "tag không chạy gì mới" là điều kiện sống của thiết kế này.
- **T3 (`tests-gate/e2e/`) và T4 (`tests-gate/regression/`) TUYỆT ĐỐI không được `import center_kb`**, kể cả gián tiếp qua conftest. Vi phạm ⇒ tầng đó âm thầm thoái hoá thành test source tree.
- **Runner venv không được cài `center-kb`.** Đây là điều kiện để canary `find_spec("center_kb") is None` có nghĩa.
- **Không parse PDF thật, không tải model Hugging Face** ở bất kỳ đâu trong cửa. Cửa flaky vì mạng thì tệ hơn không có cửa.
- **Không có `claude` CLI trên CI.** Mọi bước cần LLM phải dùng stub shell script đặt trên `PATH`.
- **Từ v0.9, hub là nguồn đọc duy nhất.** `kb query`, `kb get`, `kb context new`, `kb resolve`, `kb doctor` đều đi qua `_hub_or_exit()`. `kb build` và `kb diff` là local. ⇒ Trong hành trình e2e, **`kb publish` phải chạy TRƯỚC `kb query`**.
- **Lệnh kiểm lockfile: `uv lock --check`** (đã xác minh trên `uv 0.11.8`).
- Tên distribution là **`center-kb`** (có gạch nối); tên package là `center_kb` (gạch dưới). `importlib.metadata.version("center-kb")`.
- Commit message theo conventional commits (`feat:`, `fix:`, `test:`, `ci:`, `chore:`).

## Sai lệch so với spec (đã kiểm chứng, có lý do)

Ba điểm trong spec không thi hành được như viết. Ghi lại ở đây để người thực thi không tưởng là mình làm sai.

**1. Bố cục: một cây `tests-gate/` ở gốc repo với MỘT conftest chung, KHÔNG phải `tests/e2e/` + `tests/regression/`.**

Spec §4.1 đặt chúng dưới `tests/`. Không được: `tests/conftest.py:6` có `from center_kb import models` ở **module scope**, và pytest nạp mọi `conftest.py` trên đường dẫn tổ tiên. Mọi thứ dưới `tests/` sẽ luôn import `center_kb` lúc collection → canary không bao giờ có thể xanh, và tầng T3/T4 mất sạch tính cô lập. Đưa ra ngoài là cách duy nhất cưỡng chế ranh giới bằng cấu trúc thay vì bằng kỷ luật.

Và chỉ **một** thư mục `tests-gate/` với hai thư mục con, chứ không phải hai thư mục top-level tách rời: T3 và T4 dùng chung hầu hết fixture (`artifact`, `kb_run`, `run_git`, `bare_hub`, `free_port`). Hai thư mục top-level không chia sẻ được conftest, nên sẽ phải sao chép ~80 dòng — DRY thua, và mỗi lần đổi một fixture phải sửa hai nơi. Một `tests-gate/conftest.py` phục vụ cả hai thư mục con, ranh giới với `tests/` vẫn nguyên vẹn.

```
tests-gate/
    conftest.py              ← MỘT conftest cho cả hai tầng
    fixtures/pending-kb/
    golden/
    e2e/          → T3:  pytest tests-gate/e2e
    regression/   → T4:  pytest tests-gate/regression
```

**2. Không cần marker `e2e`/`regression`, không cần đổi `addopts`.**

Hệ quả của (1): `testpaths = ["tests"]` sẵn có đã loại `tests-gate/e2e/` và `tests-gate/regression/` khỏi lần chạy `pytest` trần. T3 = `pytest tests-gate/e2e`, T4 = `pytest tests-gate/regression`. Bỏ được toàn bộ cơ chế marker trong spec §4.2 — ít máy móc hơn, cùng kết quả. Yêu cầu "không thể xanh khi chạy 0 test" vẫn được đảm bảo: pytest trả **exit code 5** khi không thu thập được test nào, và fixture `artifact` **raise** nếu thiếu `KB_VENV`.

**3. Thứ tự hành trình e2e: `publish` phải đứng trước `query`.**

Spec §5 xếp `query` (bước 5) trước `publish` (bước 6). Sai: từ v0.9 `kb query` đọc **chỉ** từ `federation/` của hub (`cli.py:_hub_or_exit`), nên trước khi publish thì không có gì để query. Thứ tự đúng: `init → seed → summarize → build → publish → doctor → query → get → context/resolve → diff → MCP`.

## File Structure

**Tạo mới:**

| File | Trách nhiệm |
|---|---|
| `tests-gate/conftest.py` | **Conftest duy nhất cho cả T3 lẫn T4.** Fixture `artifact` (`$KB_VENV`), `kb_run`, `run_git`, `stub_claude`, `bare_hub`, `free_port`, `seed_kb` (Task 2); `published_repo` (Task 5); `legacy_kb` + `_materialize_kb_at_tag` (Task 8); `published_kb` (Task 9). Không import `center_kb`. |
| `tests-gate/fixtures/pending-kb/` | KB seed ở trạng thái ingest vừa xong (`status: pending`, `<!-- TODO:summarize -->`). Sinh bởi `scripts/gen_e2e_fixture.py`, commit vào repo. |
| `tests-gate/e2e/test_canary.py` | Cưỡng chế ranh giới tầng: `center_kb` không import được ở runner; `$KB_VENV/bin/kb` chạy được. |
| `tests-gate/e2e/test_journey.py` | Hành trình đầy đủ (Task 3, 5, 6). |
| `tests-gate/golden/mcp_tools.json` | Snapshot `tools/list` — so sánh chính xác. |
| `tests-gate/golden/mcp_outputs/*.txt` | Snapshot chuỗi trả về của 3 MCP tool. |
| `tests-gate/golden/cli_outputs/*.txt` | Snapshot stdout CLI (đã chuẩn hoá). |
| `tests-gate/golden/federation-v0.9.0/` | Cây `federation/` sinh bởi v0.9.0 — fixture duy nhất được commit thay vì lấy từ git history. |
| `tests-gate/regression/test_kb_backcompat.py` | §6.1 spec. |
| `tests-gate/regression/test_mcp_contract.py` | §6.2 spec. |
| `tests-gate/regression/test_golden_output.py` | §6.3 spec. |
| `tests-gate/regression/test_federation_compat.py` | §6.4 spec. |
| `scripts/gen_e2e_fixture.py` | Sinh `tests-gate/fixtures/pending-kb/` bằng chính `scaffold_doc()` — nguồn sự thật cho hình dạng đầu ra của ingest. |
| `scripts/check_package.py` | T2: version consistency + nội dung wheel. Thuần stdlib, chạy được độc lập. |
| `scripts/gate.sh` | Chạy toàn bộ cửa trên máy dev bằng một lệnh. |
| `requirements-gate.txt` | Dependency của **runner** venv (pytest, pyyaml, mcp). Không chứa `center-kb`. |
| `tests/test_check_package.py` | T1: unit test cho `scripts/check_package.py`. |
| `tests/test_ingest_seam.py` | T1: ghim `tests-gate/fixtures/pending-kb/` vào đầu ra thật của `scaffold_doc()`. |
| `.github/workflows/_gate.yml` | Reusable workflow chứa T1–T4. |
| `.github/workflows/ci.yml` | PR + push `main` → `uses: _gate.yml`. |

**Sửa:**

| File | Sửa gì |
|---|---|
| `src/center_kb/cli.py:27-30` | Thêm option `--version` vào `@app.callback()`. |
| `tests/test_cli.py` | Thêm test cho `--version`. |
| `.github/workflows/release.yml` | Viết lại: `uses: _gate.yml` → `docker-verify` → `pypi` → `docker-release`. |
| `pyproject.toml` | Thêm `twine` vào extras `dev` (job T2 dùng). |

---

### Task 1: `kb --version`

Hiện `@app.callback()` (`src/center_kb/cli.py:27-30`) là một hàm rỗng — không có `--version`. Không có nó thì hai hàng đầu bảng version-consistency (§7.3 spec) không kiểm được, và user không có cách nào biết mình đang chạy bản nào.

**Files:**
- Modify: `src/center_kb/cli.py:27-30`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `kb --version` in ra **đúng một dòng** là version string (ví dụ `0.9.0`), exit code 0. Task 3 (e2e bước 0) và Task 7 (`check_package.py`) đều dựa vào hợp đồng này.

- [ ] **Step 1: Write the failing test**

Thêm vào cuối `tests/test_cli.py`:

```python
def test_version_flag_prints_installed_version():
    import importlib.metadata

    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0, result.output
    assert result.output.strip() == importlib.metadata.version("center-kb")


def test_version_flag_does_not_require_a_subcommand():
    # `app` has no_args_is_help=True; --version must short-circuit before Click
    # complains about a missing command.
    result = runner.invoke(app, ["--version"])

    assert "Missing command" not in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_cli.py::test_version_flag_prints_installed_version -v`
Expected: FAIL — `--version` chưa tồn tại, Typer báo `No such option: --version`, exit code 2.

- [ ] **Step 3: Write minimal implementation**

Trong `src/center_kb/cli.py`, thêm `import importlib.metadata` vào khối import ở đầu file, rồi thay `@app.callback()` hiện tại (dòng 27-30):

```python
def _version_callback(value: bool) -> None:
    if value:
        typer.echo(importlib.metadata.version("center-kb"))
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the installed center-kb version and exit.",
    ),
) -> None:
    """CENTER-KB CLI."""
```

`is_eager=True` là bắt buộc: nó khiến callback chạy trong lúc parse, **trước khi** Click đòi một subcommand — đó là lý do `test_version_flag_does_not_require_a_subcommand` xanh.

Nguồn version là `importlib.metadata` (metadata của gói **đã cài**), không phải hằng số hardcode — đúng thứ ta muốn khẳng định ở T2.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: PASS toàn bộ, gồm 2 test mới.

- [ ] **Step 5: Verify nothing else broke**

Run: `.venv/bin/pytest -q`
Expected: PASS (386 passed — 384 cũ + 2 mới).

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/cli.py tests/test_cli.py
git commit -m "feat: add kb --version"
```

---

### Task 2: Harness cho tầng artifact (conftest + canary + gate.sh)

Dựng bộ khung để T3/T4 chạy được, và **cưỡng chế ranh giới tầng bằng cấu trúc**. Sau task này bạn có một lệnh duy nhất chạy cửa trên máy dev.

**Files:**
- Create: `requirements-gate.txt`
- Create: `tests-gate/conftest.py`
- Create: `tests-gate/e2e/test_canary.py`
- Create: `scripts/gate.sh`

**Interfaces:**
- Produces:
  - `artifact` fixture (session) → object có `.venv: Path`, `.kb: Path` (= `venv/bin/kb`), `.python: Path` (= `venv/bin/python`). **Raise** `RuntimeError` nếu `KB_VENV` không set.
  - `kb_run` fixture → `_run(*args: str, cwd: Path, env: dict | None = None, check: bool = True, timeout: int = 180) -> subprocess.CompletedProcess`. Tự bơm git identity.
  - `run_git` fixture → `_git(cwd: Path, *args: str) -> str` (stdout đã strip).
  - `stub_claude` fixture → `dict[str, str]` chứa `{"PATH": "<bindir>:<PATH gốc>"}`, merge vào `env` của `kb_run`.
  - `bare_hub` fixture → `Path` tới bare git repo có sẵn `.kb/index.yaml` + `federation/index.yaml`.
  - `free_port` fixture → `int`.
  - Task 3, 5, 6 dùng toàn bộ các fixture trên. Task 8–11 dùng lại `artifact`, `run_git`, `free_port` qua `tests-gate/conftest.py`.

- [ ] **Step 1: Khai báo dependency của runner venv**

Tạo `requirements-gate.txt`:

```
# Dependency của RUNNER venv — môi trường chạy pytest cho tầng T3/T4.
# TUYỆT ĐỐI KHÔNG thêm center-kb vào đây: runner phải không import được
# package thì canary (tests-gate/e2e/test_canary.py) mới có nghĩa.
pytest>=8.0
pyyaml>=6.0
mcp>=1.2
```

- [ ] **Step 2: Write the failing test (canary)**

Tạo `tests-gate/e2e/test_canary.py`:

```python
"""Cưỡng chế ranh giới tầng T3/T4.

Nếu file này đỏ, nghĩa là bộ e2e đã (trực tiếp hoặc gián tiếp qua conftest)
với tay được vào source tree — và cả tầng đã âm thầm thoái hoá thành một bộ
test in-process trá hình, mất sạch giá trị phát hiện lỗi đóng gói.
"""

from __future__ import annotations

import importlib.util
import subprocess


def test_center_kb_is_not_importable_from_the_runner():
    assert importlib.util.find_spec("center_kb") is None, (
        "center_kb import được từ runner venv. Runner CHỈ được có pytest + "
        "requirements-gate.txt; artifact nằm ở venv riêng ($KB_VENV). "
        "Kiểm tra: bạn có lỡ chạy pytest bằng .venv của project không?"
    )


def test_artifact_binary_runs(artifact):
    proc = subprocess.run(
        [str(artifact.kb), "--version"], capture_output=True, text=True, timeout=60
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip(), "kb --version không in ra gì"
```

- [ ] **Step 3: Run it to verify it fails**

Run: `.venv/bin/pytest tests-gate/e2e/test_canary.py -q`
Expected: FAIL — hai lý do cùng lúc, và cả hai đều đúng như thiết kế:
1. `test_center_kb_is_not_importable_from_the_runner` đỏ vì `.venv` có `center-kb` cài editable.
2. `test_artifact_binary_runs` lỗi vì fixture `artifact` chưa tồn tại.

Đây chính là bằng chứng canary hoạt động: **không được chạy tầng này bằng `.venv` của project.**

- [ ] **Step 4: Viết conftest**

Tạo `tests-gate/conftest.py`:

```python
"""Fixtures cho tầng T3 (e2e trên artifact đã cài).

QUY TẮC BẤT DI BẤT DỊCH: file này và mọi file dưới tests-gate/e2e/ KHÔNG được
import center_kb. Artifact chỉ được chạm tới qua subprocess.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

# kb publish tạo commit thật. Runner CI không có ~/.gitconfig, nên git sẽ từ
# chối commit nếu không có identity — cùng lý do release.yml đã set các biến
# này cho job test.
GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "e2e",
    "GIT_AUTHOR_EMAIL": "e2e@local",
    "GIT_COMMITTER_NAME": "e2e",
    "GIT_COMMITTER_EMAIL": "e2e@local",
}

# Payload hợp lệ cho CẢ prompt section lẫn prompt doc của kb summarize.
# claude được gọi là: claude -p --model <m> --output-format json  (prompt qua
# stdin), và --output-format json bọc trả lời trong {"type":"result","result":…}
# — xem center_kb/llm.py:32 và :59.
_INNER = json.dumps(
    {
        "l2_summary": "Condensed via stub.",
        "l1_summary": "Stub line.",
        "summary": "Stub doc summary.",
    }
)
CLAUDE_ENVELOPE = json.dumps({"type": "result", "result": _INNER})


@dataclass(frozen=True)
class Artifact:
    venv: Path

    @property
    def kb(self) -> Path:
        return self.venv / "bin" / "kb"

    @property
    def python(self) -> Path:
        return self.venv / "bin" / "python"


@pytest.fixture(scope="session")
def artifact() -> Artifact:
    raw = os.environ.get("KB_VENV")
    if not raw:
        # RAISE, không skip. Một job CI xanh vì thu thập được 0 test là kiểu
        # hỏng nguy hiểm nhất của một cửa release — nó cho cảm giác an toàn giả.
        raise RuntimeError(
            "KB_VENV chưa được set. Tầng e2e/regression chạy trên WHEEL ĐÃ CÀI, "
            "không bao giờ trên source tree. Dùng: ./scripts/gate.sh"
        )
    venv = Path(raw)
    if not (venv / "bin" / "kb").exists():
        raise RuntimeError(f"KB_VENV={venv} không có bin/kb — wheel đã cài vào đó chưa?")
    return Artifact(venv=venv)


@pytest.fixture
def kb_run(artifact: Artifact):
    """Gọi binary kb thật bằng subprocess."""

    def _run(
        *args: str,
        cwd: Path,
        env: dict[str, str] | None = None,
        check: bool = True,
        timeout: int = 180,
    ) -> subprocess.CompletedProcess[str]:
        full_env = {**os.environ, **GIT_IDENTITY, **(env or {})}
        proc = subprocess.run(
            [str(artifact.kb), *args],
            cwd=cwd,
            env=full_env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if check and proc.returncode != 0:
            raise AssertionError(
                f"kb {' '.join(args)} → exit {proc.returncode}\n"
                f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
            )
        return proc

    return _run


@pytest.fixture
def run_git():
    def _git(cwd: Path, *args: str) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            env={**os.environ, **GIT_IDENTITY},
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout.strip()

    return _git


@pytest.fixture
def stub_claude(tmp_path_factory) -> dict[str, str]:
    """Shell script tên `claude` đặt đầu PATH. center_kb/llm.py dùng
    shutil.which("claude") để dò runner, nên chỉ cần nó nằm trên PATH."""
    bindir = tmp_path_factory.mktemp("stub-bin")
    script = bindir / "claude"
    script.write_text(
        f"#!/bin/sh\ncat > /dev/null\necho '{CLAUDE_ENVELOPE}'\n", encoding="utf-8"
    )
    script.chmod(0o755)
    return {"PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}


@pytest.fixture
def bare_hub(tmp_path: Path, run_git) -> Path:
    """Hub bare git repo. PHẢI bare: `kb publish --direct` push vào main của
    hub, và git từ chối push vào branch đang được checkout của một repo thường."""
    work = tmp_path / "hub-work"
    (work / ".kb").mkdir(parents=True)
    (work / "federation").mkdir()
    (work / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    (work / "federation" / "index.yaml").write_text("docs: []\n", encoding="utf-8")

    run_git(work, "init", "-b", "main")
    run_git(work, "add", "-A")
    run_git(work, "commit", "-m", "hub init")

    bare = tmp_path / "hub.git"
    run_git(tmp_path, "clone", "--bare", str(work), str(bare))
    return bare


@pytest.fixture
def free_port() -> int:
    """Xin một cổng trống thay vì hardcode 8321 — tránh đụng nhau khi chạy song song."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# ---- KB seed (fixture sinh bởi scripts/gen_e2e_fixture.py — xem Task 3) ----
# Hằng số + fixture đặt ở đây (conftest chung) thay vì trong test_journey.py, để
# fixture `published_repo` (Task 5) dùng được mà không cần import chéo giữa các
# test module.
SEED_FIXTURE = Path(__file__).parent / "fixtures" / "pending-kb"


@pytest.fixture
def seed_kb():
    """Đổ KB ở trạng thái 'ingest vừa xong' vào repo, và trỏ config.yaml vào hub."""

    def _seed(repo: Path, hub: Path) -> Path:
        kb = repo / ".kb"
        for src in SEED_FIXTURE.rglob("*"):
            if src.is_file():
                dest = kb / src.relative_to(SEED_FIXTURE)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
        (kb / "config.yaml").write_text(
            f'hub: "{hub}"\nrepo_id: "e2e-repo"\n', encoding="utf-8"
        )
        return kb

    return _seed
```

`shutil` phải có trong khối import ở đầu conftest.

- [ ] **Step 5: Viết `scripts/gate.sh`**

Tạo `scripts/gate.sh` (rồi `chmod +x`):

```bash
#!/usr/bin/env bash
# Chạy TOÀN BỘ cửa release trên máy dev — đúng những gì CI sẽ chạy.
# Dùng trước khi tạo tag. Không cần push, không cần đốt số version.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="${TMPDIR:-/tmp}/kb-gate"
ARTIFACT="$WORK/artifact"
RUNNER="$WORK/runner"

cd "$ROOT"
rm -rf "$WORK" dist
mkdir -p "$WORK"

echo "==> T1: unit/integration (source tree)"
python -m pytest -q

echo "==> Build wheel + sdist"
python -m build

echo "==> T2: đóng gói"
python -m venv "$ARTIFACT"
"$ARTIFACT/bin/pip" install --quiet dist/*.whl
python scripts/check_package.py --venv "$ARTIFACT" --dist dist
python -m twine check --strict dist/*
uv lock --check

# Runner venv: pytest + deps, KHÔNG có center-kb. Đây là điều kiện để canary
# (tests-gate/e2e/test_canary.py) có nghĩa.
echo "==> Dựng runner venv"
python -m venv "$RUNNER"
"$RUNNER/bin/pip" install --quiet -r requirements-gate.txt

echo "==> T3: e2e trên artifact"
KB_VENV="$ARTIFACT" "$RUNNER/bin/pytest" tests-gate/e2e -q

echo "==> T4: regression"
KB_VENV="$ARTIFACT" "$RUNNER/bin/pytest" tests-gate/regression -q

echo ""
echo "✅ Cửa xanh. An toàn để tag."
```

`scripts/check_package.py` chưa tồn tại (Task 7) và `tests-gate/regression/` chưa tồn tại (Task 8+). Ở task này script sẽ dừng ở bước T2 — đó là hành vi đúng của `set -e`. Nó sẽ chạy trọn vẹn sau Task 11.

- [ ] **Step 6: Chạy canary đúng cách và xác minh nó xanh**

```bash
python -m build
python -m venv /tmp/kb-artifact && /tmp/kb-artifact/bin/pip install -q dist/*.whl
python -m venv /tmp/kb-runner && /tmp/kb-runner/bin/pip install -q -r requirements-gate.txt
KB_VENV=/tmp/kb-artifact /tmp/kb-runner/bin/pytest tests-gate/e2e -q
```

Expected: **2 passed**. Cả hai canary xanh — `center_kb` không import được từ runner, và `kb --version` (Task 1) chạy được từ artifact.

- [ ] **Step 7: Xác minh fixture raise khi thiếu `KB_VENV`**

Run: `/tmp/kb-runner/bin/pytest tests-gate/e2e/test_canary.py::test_artifact_binary_runs -q`
Expected: ERROR với `RuntimeError: KB_VENV chưa được set…`, exit code khác 0. Đây là bằng chứng cho tiêu chí "không thể xanh khi chạy 0 test".

- [ ] **Step 8: Xác minh `pytest` trần không bị ảnh hưởng**

Run: `.venv/bin/pytest -q`
Expected: 386 passed. `testpaths = ["tests"]` khiến `tests-gate/e2e/` không bị thu thập — T1 không chậm đi chút nào.

- [ ] **Step 9: Commit**

```bash
git add requirements-gate.txt tests-gate/e2e/ scripts/gate.sh
git commit -m "test: add e2e artifact harness + tier-boundary canary"
```

---

### Task 3: Fixture seed + hành trình e2e phần A (init → summarize → build)

Không chạy được `kb ingest` thật trong cửa (`parser.load_or_parse` import `docling_core` **trước cả khi** đọc cache → kể cả có cache vẫn phải cài extras ~2GB). Nên hành trình bắt đầu từ **đầu ra** của ingest. Fixture đó phải được sinh bởi chính `scaffold_doc()` — không gõ tay — để nó không thể sai hình dạng ngay từ đầu.

**Files:**
- Create: `scripts/gen_e2e_fixture.py`
- Create: `tests-gate/fixtures/pending-kb/` (sinh ra, rồi commit)
- Create: `tests-gate/e2e/test_journey.py`

**Interfaces:**
- Consumes: `artifact`, `kb_run`, `stub_claude` (Task 2).
- Produces:
  - `tests-gate/fixtures/pending-kb/` — cây `.kb` gồm `index.yaml`, `demo-doc/_manifest.yaml`, `demo-doc/ch1-records.md`, `demo-doc/ch1-records.raw.md`. Task 4 ghim nó; Task 5/6 dùng tiếp.
  - `seed_kb` fixture (định nghĩa ở `tests-gate/conftest.py`, Task 2) → callable `_seed(repo: Path, hub: Path) -> Path`; copy fixture vào `repo/.kb` và ghi `hub:` vào `config.yaml`.
  - Doc id: `demo-doc`. Section ids: `1.1` (Airspace Records), `1.2` (Airway Records).

- [ ] **Step 1: Viết generator**

Tạo `scripts/gen_e2e_fixture.py`:

```python
"""Sinh tests-gate/fixtures/pending-kb/ bằng CHÍNH scaffold_doc().

Fixture này là "vết nối" của hành trình e2e: nó thế chỗ cho `kb ingest`, thứ
không chạy được trong cửa release. Sinh nó bằng code thật (thay vì gõ tay) là
nửa đầu của cách chống trôi; nửa sau là tests/test_ingest_seam.py (Task 4),
chạy lại generator này và so với cây đã commit.

Chạy: python scripts/gen_e2e_fixture.py [dest]
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from center_kb.ingest.scaffold import scaffold_doc
from center_kb.ingest.sectioner import SectionUnit

TABLE = "| Code | Meaning |\n|---|---|\n| P | Prohibited |\n| R | Restricted |"

UNITS = [
    SectionUnit(
        id="1.1",
        title="Airspace Records",
        chapter="1",
        body_md=(
            "Airspace records carry a designation, a type, a multiple code and "
            "a level. Restrictive airspace uses the prohibited and restricted "
            "type codes."
        ),
        tables=[TABLE],
    ),
    SectionUnit(
        id="1.2",
        title="Airway Records",
        chapter="1",
        body_md=(
            "Airway records carry route identifiers, sequence numbers and the "
            "fixes that make up the route."
        ),
        tables=[],
    ),
]


def generate(kb_dir: Path) -> None:
    if kb_dir.exists():
        shutil.rmtree(kb_dir)
    kb_dir.mkdir(parents=True)
    # index.yaml phải tồn tại trước: scaffold_doc đọc-rồi-ghi nó.
    (kb_dir / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    scaffold_doc(
        UNITS,
        doc_id="demo-doc",
        title="Demo Document",
        tags=["demo", "airspace"],
        revision="Rev 1",
        source_path=None,
        kb_dir=kb_dir,
    )


if __name__ == "__main__":
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).parent.parent / "tests-gate" / "fixtures" / "pending-kb"
    )
    generate(dest)
    print(f"generated {dest}")
```

- [ ] **Step 2: Sinh fixture và soi bằng mắt**

```bash
.venv/bin/python scripts/gen_e2e_fixture.py
find tests-gate/fixtures/pending-kb -type f | sort
cat tests-gate/fixtures/pending-kb/demo-doc/ch1-records.md
```

Expected: 4 file — `index.yaml`, `demo-doc/_manifest.yaml`, `demo-doc/ch1-records.md`, `demo-doc/ch1-records.raw.md`. File `ch1-records.md` chứa `<!-- TODO:summarize 1.1 -->` và `<!-- TODO:summarize 1.2 -->`; `_manifest.yaml` có `status: pending` cho cả hai section. Nếu không đúng vậy, **dừng lại** — mọi thứ phía sau dựa vào hình dạng này.

- [ ] **Step 3: Write the failing test (hành trình phần A)**

Tạo `tests-gate/e2e/test_journey.py`:

```python
"""Hành trình e2e đầy đủ trên wheel đã cài.

KHÔNG import center_kb ở đây. Artifact là hộp đen, chỉ chạm qua subprocess.
"""

from __future__ import annotations

from pathlib import Path

import yaml

# tests-gate/e2e/test_journey.py → lùi 2 cấp là gốc repo.
REPO_ROOT = Path(__file__).parent.parent.parent


def read_manifest(kb: Path) -> dict:
    return yaml.safe_load((kb / "demo-doc" / "_manifest.yaml").read_text(encoding="utf-8"))


def test_version_and_help(kb_run, tmp_path):
    version = kb_run("--version", cwd=tmp_path).stdout.strip()
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    # Đọc pyproject như file text — KHÔNG import center_kb.
    declared = next(
        line.split("=", 1)[1].strip().strip('"')
        for line in pyproject.splitlines()
        if line.startswith("version =")
    )
    assert version == declared

    help_out = kb_run("--help", cwd=tmp_path).stdout
    expected = [
        "init", "ingest", "summarize", "status", "build", "query", "get",
        "stats", "publish", "reindex", "resolve", "diff", "doctor", "context",
    ]
    for name in expected:
        assert name in help_out, f"lệnh '{name}' biến mất khỏi wheel"


def test_init_scaffolds_a_kb(kb_run, tmp_path):
    kb_run("init", cwd=tmp_path)

    assert (tmp_path / ".kb" / "index.yaml").exists()
    assert (tmp_path / ".kb" / "config.yaml").exists()


def test_summarize_then_build(kb_run, seed_kb, stub_claude, bare_hub, tmp_path):
    kb_run("init", cwd=tmp_path)
    kb = seed_kb(tmp_path, bare_hub)

    before = read_manifest(kb)
    assert all(s["status"] == "pending" for s in before["sections"])
    assert "TODO:summarize" in (kb / "demo-doc" / "ch1-records.md").read_text(
        encoding="utf-8"
    )

    kb_run("summarize", "--llm", "claude", "--kb-dir", str(kb),
           cwd=tmp_path, env=stub_claude)

    after = read_manifest(kb)
    assert all(s["status"] == "summarized" for s in after["sections"])
    l2 = (kb / "demo-doc" / "ch1-records.md").read_text(encoding="utf-8")
    assert "TODO:summarize" not in l2
    assert "Condensed via stub." in l2

    # kb build là LOCAL (validate không còn TODO) — chạy trước publish.
    out = kb_run("build", "--kb-dir", str(kb), cwd=tmp_path).stdout
    assert "kb build: OK" in out
```

- [ ] **Step 4: Run it to verify it fails**

```bash
python -m build && python -m venv /tmp/kb-artifact && /tmp/kb-artifact/bin/pip install -q --force-reinstall dist/*.whl
KB_VENV=/tmp/kb-artifact /tmp/kb-runner/bin/pytest tests-gate/e2e/test_journey.py -q
```
Expected: FAIL — `tests-gate/fixtures/pending-kb` chưa được commit thì `FIXTURE` vẫn tồn tại trên đĩa (Step 2 đã sinh), nên test thực ra **nên PASS**. Nếu nó đỏ, đọc kỹ output: đó là lỗi thật (ví dụ `kb summarize` không nhận stub), không phải lỗi TDD-chưa-implement. Task này là *kiểm chứng hành vi đã có*, không phải xây tính năng mới — nên "test phải đỏ trước" không áp dụng; điều phải xác minh là **nó xanh vì đúng lý do**.

- [ ] **Step 5: Xác minh nó xanh vì đúng lý do**

Chạy lại với `-v` và đọc output. Rồi cố tình phá để chứng minh test có răng:

```bash
# Bỏ stub claude khỏi PATH → summarize phải hỏng
KB_VENV=/tmp/kb-artifact /tmp/kb-runner/bin/pytest \
  tests-gate/e2e/test_journey.py::test_summarize_then_build -q -p no:randomly \
  --override-ini=addopts= 2>&1 | head -5
```
Sau đó tạm sửa `stub_claude` trong test thành `env={}` và chạy lại: expected FAIL (summarize không tìm thấy runner). **Hoàn nguyên sửa đổi này** trước khi commit. Mục đích: chứng minh test đang thực sự kiểm stub, không phải xanh giả.

- [ ] **Step 6: Commit**

```bash
git add scripts/gen_e2e_fixture.py tests-gate/fixtures tests-gate/e2e/test_journey.py
git commit -m "test: e2e journey A — init, seed, summarize, build on the installed wheel"
```

---

### Task 4: Ghim vết nối ingest

Rủi ro của fixture seed là **trôi**: `kb ingest` đổi định dạng đầu ra, fixture không đổi, e2e vẫn xanh trong khi thực tế đã vỡ. Task này ghim đầu còn lại của vết nối — ở tầng T1, nơi được phép import `center_kb`.

**Files:**
- Create: `tests/test_ingest_seam.py`

**Interfaces:**
- Consumes: `scripts.gen_e2e_fixture.generate()` (Task 3), `tests-gate/fixtures/pending-kb/` (Task 3).

- [ ] **Step 1: Write the failing test**

Tạo `tests/test_ingest_seam.py`:

```python
"""Ghim tests-gate/fixtures/pending-kb/ vào đầu ra THẬT của scaffold_doc().

Hành trình e2e không chạy được `kb ingest` (cần docling ~2GB + PDF bản quyền),
nên nó bắt đầu từ một fixture mô phỏng đầu ra của ingest. Test này là thứ giữ
cho fixture đó không trôi khỏi sự thật: sinh lại vào tmp, so với cây đã commit.

ĐỎ NGHĨA LÀ GÌ: đầu ra của ingest đã đổi. Đừng sửa test. Chạy lại
`python scripts/gen_e2e_fixture.py`, đọc kỹ diff, rồi commit fixture mới —
và kiểm tra xem tests-gate/e2e/test_journey.py có còn đúng với hình dạng mới không.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO = Path(__file__).parent.parent
FIXTURE = REPO / "tests-gate" / "fixtures" / "pending-kb"

sys.path.insert(0, str(REPO / "scripts"))
from gen_e2e_fixture import generate  # noqa: E402


def _tree(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


def test_fixture_file_tree_matches_scaffold_output(tmp_path):
    generate(tmp_path / ".kb")

    assert _tree(tmp_path / ".kb") == _tree(FIXTURE)


def test_fixture_markdown_matches_scaffold_output(tmp_path):
    generate(tmp_path / ".kb")

    for name in ("ch1-records.md", "ch1-records.raw.md"):
        fresh = (tmp_path / ".kb" / "demo-doc" / name).read_text(encoding="utf-8")
        committed = (FIXTURE / "demo-doc" / name).read_text(encoding="utf-8")
        assert fresh == committed, f"{name} đã trôi khỏi đầu ra của scaffold_doc()"


def test_fixture_manifest_matches_scaffold_output(tmp_path):
    generate(tmp_path / ".kb")

    fresh = yaml.safe_load(
        (tmp_path / ".kb" / "demo-doc" / "_manifest.yaml").read_text(encoding="utf-8")
    )
    committed = yaml.safe_load(
        (FIXTURE / "demo-doc" / "_manifest.yaml").read_text(encoding="utf-8")
    )
    # scaffold_doc đặt ingested=date.today() → trôi mỗi ngày, không phải tín hiệu.
    fresh.pop("ingested", None)
    committed.pop("ingested", None)

    assert fresh == committed
```

- [ ] **Step 2: Run to verify the pin holds**

Run: `.venv/bin/pytest tests/test_ingest_seam.py -v`
Expected: 3 passed. Nếu đỏ ở `_manifest.yaml` với chênh lệch ở `tokens`, nghĩa là Step 2 của Task 3 chưa được chạy bằng đúng code hiện tại — chạy lại generator và commit lại fixture.

- [ ] **Step 3: Chứng minh cái ghim có răng**

Sửa tạm `scripts/gen_e2e_fixture.py`, đổi `title="Airway Records"` thành `title="Airway Recordz"`, rồi:

Run: `.venv/bin/pytest tests/test_ingest_seam.py -q`
Expected: FAIL ở cả 3 test. **Hoàn nguyên sửa đổi.** Đây là bằng chứng vết nối thực sự được ghim ở cả hai đầu.

- [ ] **Step 4: Commit**

```bash
git add tests/test_ingest_seam.py
git commit -m "test: pin the e2e seed fixture to real scaffold_doc output"
```

---

### Task 5: Hành trình e2e phần B (publish → doctor → query → get → context/resolve → diff)

Từ v0.9, `kb query`/`get`/`context`/`resolve`/`doctor` đọc **chỉ** từ `federation/` của hub. Nên publish phải đứng trước. `kb diff` thì local-git, cần KB dir nằm trong một git repo có commit.

**Files:**
- Modify: `tests-gate/conftest.py` (thêm fixture `published_repo`)
- Modify: `tests-gate/e2e/test_journey.py`

**Interfaces:**
- Consumes: `seed_kb` fixture, `bare_hub`, `run_git`, `stub_claude`, `kb_run` (Task 2).
- Produces: fixture `published_repo` → `dict` với khoá `repo: Path`, `kb: Path`, `hub: Path`. Task 6 dùng lại.

- [ ] **Step 1: Thêm fixture `published_repo`**

Thêm vào **`tests-gate/conftest.py`** (cần `bare_hub` + `stub_claude`, và Task 6 cũng dùng):

```python
@pytest.fixture
def published_repo(tmp_path: Path, kb_run, seed_kb, stub_claude, bare_hub, run_git) -> dict:
    """Một repo đã đi trọn: init → seed → summarize → build → publish lên hub.

    Trả về {"repo", "kb", "hub"}. Đây là trạng thái mà mọi lệnh đọc (query,
    get, context, resolve, doctor) cần — vì từ v0.9 chúng chỉ đọc từ hub.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    kb_run("init", cwd=repo)
    kb = seed_kb(repo, bare_hub)
    kb_run("summarize", "--llm", "claude", "--kb-dir", str(kb),
           cwd=repo, env=stub_claude)
    kb_run("build", "--kb-dir", str(kb), cwd=repo)
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-m", "kb v1")
    kb_run("publish", "--direct", "--hub", str(bare_hub), "--repo-id", "e2e-repo",
           "--kb-dir", str(kb), cwd=repo)
    return {"repo": repo, "kb": kb, "hub": bare_hub}
```

`published_repo` sống trong **conftest chung** (`tests-gate/conftest.py`) chứ không trong `test_journey.py`, vì Task 6 (`tests-gate/e2e/test_server.py`) cũng dùng nó. Nó lấy `seed_kb` qua fixture injection — không import chéo giữa các test module. **Không** tạo `__init__.py` ở bất kỳ đâu dưới `tests-gate/`.

- [ ] **Step 2: Write the failing tests**

Thêm vào cuối `tests-gate/e2e/test_journey.py`:

```python
def test_publish_mirrors_all_levels_into_the_hub(published_repo, run_git, tmp_path):
    checkout = tmp_path / "hub-check"
    run_git(tmp_path, "clone", str(published_repo["hub"]), str(checkout))

    entry = checkout / "federation" / "e2e-repo" / "demo-doc"
    assert (entry / "_manifest.yaml").exists()
    assert (entry / "ch1-records.md").exists(), "thiếu L2"
    assert (entry / "ch1-records.raw.md").exists(), "thiếu L3 (.raw.md)"
    assert (checkout / "federation" / "e2e-repo" / "_meta.yaml").exists()
    assert (checkout / "federation" / "index.yaml").exists()


def test_doctor_is_clean_after_publish(published_repo, kb_run):
    proc = kb_run("doctor", "--hub", str(published_repo["hub"]),
                  "--kb-dir", str(published_repo["kb"]),
                  cwd=published_repo["repo"])

    assert proc.returncode == 0, proc.stdout


def test_query_reads_from_the_hub(published_repo, kb_run):
    proc = kb_run("query", "airspace", "--hub", str(published_repo["hub"]),
                  "--kb-dir", str(published_repo["kb"]),
                  cwd=published_repo["repo"])

    assert "No matching section found." not in proc.stdout
    assert "Condensed via stub." in proc.stdout


def test_get_returns_both_levels(published_repo, kb_run):
    repo, kb, hub = published_repo["repo"], published_repo["kb"], published_repo["hub"]

    l2 = kb_run("get", "demo-doc", "1.1", "--level", "l2",
                "--hub", str(hub), "--kb-dir", str(kb), cwd=repo).stdout
    l3 = kb_run("get", "demo-doc", "1.1", "--level", "l3",
                "--hub", str(hub), "--kb-dir", str(kb), cwd=repo).stdout

    assert "Condensed via stub." in l2
    assert "multiple code" in l3, "L3 phải là verbatim, không phải bản tóm tắt"


def test_context_new_then_resolve_roundtrip(published_repo, kb_run, tmp_path):
    repo, kb, hub = published_repo["repo"], published_repo["kb"], published_repo["hub"]

    block = kb_run("context", "new", "--refs", "demo-doc §1.1",
                   "--hub", str(hub), "--kb-dir", str(kb), cwd=repo).stdout
    assert "kb-context" in block

    block_file = tmp_path / "ticket.md"
    block_file.write_text(block, encoding="utf-8")

    proc = kb_run("resolve", str(block_file), "--hub", str(hub),
                  "--kb-dir", str(kb), cwd=repo, check=False)

    # exit 0 = ok, 2 = stale, 1 = broken. Vừa pin xong thì phải là ok.
    assert proc.returncode == 0, f"resolve → {proc.returncode}\n{proc.stdout}"
    assert "Condensed via stub." in proc.stdout


def test_diff_detects_a_changed_section(published_repo, kb_run, run_git):
    repo, kb = published_repo["repo"], published_repo["kb"]
    l2 = kb / "demo-doc" / "ch1-records.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace(
            "Condensed via stub.", "Condensed via stub. Amended."
        ),
        encoding="utf-8",
    )

    # kb diff là local-git: so worktree với một git rev.
    proc = kb_run("diff", "demo-doc", "--against", "HEAD",
                  "--kb-dir", str(kb), cwd=repo)

    assert "1.1" in proc.stdout
```

- [ ] **Step 3: Run and verify**

```bash
KB_VENV=/tmp/kb-artifact /tmp/kb-runner/bin/pytest tests-gate/e2e/test_journey.py -q
```
Expected: 9 passed (3 từ Task 3 + 6 mới).

Nếu `test_publish_mirrors_all_levels_into_the_hub` đỏ vì git từ chối push: kiểm tra `bare_hub` có thật sự bare không (`git -C <hub> rev-parse --is-bare-repository` phải in `true`). Nếu đỏ vì thiếu identity: kiểm `GIT_IDENTITY` có được merge vào env chưa.

- [ ] **Step 4: Commit**

```bash
git add tests-gate/conftest.py tests-gate/e2e/test_journey.py
git commit -m "test: e2e journey B — publish, doctor, query, get, context/resolve, diff"
```

---

### Task 6: Hành trình e2e phần C (MCP HTTP + MCP stdio + suy giảm ingest)

Ba bước cửa hiện tại bỏ trống hoàn toàn. HTTP + MCP là đường sống của Docker và của agent; bước suy giảm ingest là thứ **mọi** user `pip install center-kb` (không extras) đâm vào đầu tiên.

**Files:**
- Create: `tests-gate/e2e/test_server.py`
- Modify: `tests-gate/e2e/test_journey.py`

**Interfaces:**
- Consumes: `published_repo`, `artifact`, `free_port`, `kb_run` (Task 2, 5).
- Produces: helper `mcp_stdio_params(artifact, published_repo)` → `StdioServerParameters`. Task 9/10 dùng lại qua `tests-gate/conftest.py`.

- [ ] **Step 1: Write the failing tests (HTTP)**

Tạo `tests-gate/e2e/test_server.py`:

```python
"""HTTP + MCP trên artifact đã cài.

Không có lệnh `kb serve` — server chạy qua `python -m center_kb.mcp`, đúng như
CMD của Dockerfile. Nên ta gọi python CỦA VENV ARTIFACT, không phải python của
runner.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
import urllib.error
import urllib.request

import pytest

TOKEN = "e2e-token"


def _get(url: str, token: str | None = None) -> tuple[int, str]:
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


@pytest.fixture
def http_server(artifact, published_repo, free_port):
    proc = subprocess.Popen(
        [
            str(artifact.python), "-m", "center_kb.mcp",
            "--kb", str(published_repo["kb"]),
            "--hub", str(published_repo["hub"]),
            "--transport", "http",
            "--host", "127.0.0.1",
            "--port", str(free_port),
        ],
        cwd=published_repo["repo"],
        env={**os.environ, "CENTER_KB_HTTP_TOKEN": TOKEN},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base = f"http://127.0.0.1:{free_port}"
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            pytest.fail(f"server chết khi khởi động:\n{proc.stdout.read()}")
        try:
            if _get(f"{base}/api/health")[0] == 200:
                break
        except OSError:
            time.sleep(0.3)
    else:
        proc.kill()
        pytest.fail("server không trả lời /api/health trong 60s")

    yield base
    proc.kill()
    proc.wait(timeout=10)


def test_health_is_open(http_server):
    status, _ = _get(f"{http_server}/api/health")

    assert status == 200


def test_docs_require_a_token(http_server):
    # Tài liệu có bản quyền — HTTP không token PHẢI bị chặn.
    status, _ = _get(f"{http_server}/api/docs")

    assert status == 401


def test_docs_with_a_token_return_the_published_doc(http_server):
    status, body = _get(f"{http_server}/api/docs", token=TOKEN)

    assert status == 200
    assert "demo-doc" in body


def test_search_api_finds_the_seeded_section(http_server):
    status, body = _get(f"{http_server}/api/search?q=airspace", token=TOKEN)

    assert status == 200
    assert "Condensed via stub." in body
```

- [ ] **Step 2: Run to verify**

```bash
KB_VENV=/tmp/kb-artifact /tmp/kb-runner/bin/pytest tests-gate/e2e/test_server.py -q
```
Expected: 4 passed.

Nếu `test_search_api_finds_the_seeded_section` đỏ vì tên tham số query khác `q`: mở `src/center_kb/web/api.py` xem hàm `api_search` đọc param nào và sửa test theo **code thật**, không sửa code theo test.

- [ ] **Step 3: Thêm MCP stdio**

Thêm vào cuối `tests-gate/e2e/test_server.py`:

```python
EXPECTED_TOOLS = {"kb_search", "kb_get_section", "kb_context_new", "kb_resolve"}


def mcp_stdio_params(artifact, published_repo):
    from mcp import StdioServerParameters

    return StdioServerParameters(
        command=str(artifact.python),
        args=[
            "-m", "center_kb.mcp",
            "--kb", str(published_repo["kb"]),
            "--hub", str(published_repo["hub"]),
        ],
        cwd=str(published_repo["repo"]),
        env={**os.environ},
    )


async def _handshake(params):
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            hit = await session.call_tool("kb_search", {"query": "airspace"})
            return tools, hit


def test_mcp_stdio_exposes_exactly_the_four_tools(artifact, published_repo):
    tools, hit = asyncio.run(_handshake(mcp_stdio_params(artifact, published_repo)))

    assert {t.name for t in tools.tools} == EXPECTED_TOOLS

    text = "".join(c.text for c in hit.content if c.type == "text")
    assert "Condensed via stub." in text
```

- [ ] **Step 4: Run to verify**

Run: `KB_VENV=/tmp/kb-artifact /tmp/kb-runner/bin/pytest tests-gate/e2e/test_server.py -q`
Expected: 5 passed. Server MCP chạy trong venv artifact; client chạy ở runner — đúng hình thù thật khi một agent cắm vào `center-kb`.

- [ ] **Step 5: Thêm bước suy giảm ingest**

Thêm vào cuối `tests-gate/e2e/test_journey.py`:

```python
def test_ingest_without_docling_fails_cleanly(kb_run, seed_kb, bare_hub, tmp_path):
    """Wheel base KHÔNG có extras [ingest]. User `pip install center-kb` rồi
    chạy ingest sẽ đâm vào đúng đường này — nó phải là một câu tiếng người,
    không phải traceback."""
    kb_run("init", cwd=tmp_path)
    seed_kb(tmp_path, bare_hub)
    fake_pdf = tmp_path / "x.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4\n")

    proc = kb_run("ingest", str(fake_pdf), "--id", "whatever",
                  cwd=tmp_path, check=False)

    assert proc.returncode != 0
    combined = proc.stdout + proc.stderr
    assert "Docling is not installed" in combined
    assert "Traceback" not in combined, (
        "ingest thiếu docling ném traceback thô vào mặt user:\n" + combined
    )
```

- [ ] **Step 6: Run the whole e2e tier**

Run: `KB_VENV=/tmp/kb-artifact /tmp/kb-runner/bin/pytest tests-gate/e2e -q`
Expected: 15 passed (2 canary + 10 journey + 5 server... đếm lại theo thực tế; điều cần khẳng định là **không có test nào đỏ và không có test nào bị skip**).

Nếu `test_ingest_without_docling_fails_cleanly` đỏ vì có `Traceback`: đó là **một bug thật trong sản phẩm**, không phải lỗi test. Ghi lại, báo cho người review, đừng nới lỏng assertion.

- [ ] **Step 7: Commit**

```bash
git add tests-gate/e2e/test_server.py tests-gate/e2e/test_journey.py
git commit -m "test: e2e journey C — HTTP API, MCP stdio, ingest degradation path"
```

---

### Task 7: T2 — kiểm tra đóng gói (`scripts/check_package.py`)

Tầng T2: bắt lệch version/metadata và wheel đóng gói nhầm thứ không nên có. Viết thành script độc lập (thuần stdlib) để CI và `gate.sh` gọi chung, và unit-test được ở T1.

**Files:**
- Create: `scripts/check_package.py`
- Create: `tests/test_check_package.py`
- Modify: `pyproject.toml` (thêm `twine` vào extras `dev`)

**Interfaces:**
- Produces:
  - `pyproject_version(root: Path) -> str`
  - `wheel_offenders(wheel: Path) -> list[str]` — trả về các top-level path bị đóng gói nhầm.
  - `check(venv: Path, dist: Path, root: Path, tag: str | None) -> list[str]` — trả về danh sách lỗi; rỗng = xanh.
  - CLI: `python scripts/check_package.py --venv <path> --dist <dir> [--tag v0.9.1]` → exit 1 nếu có lỗi.

- [ ] **Step 1: Write the failing test**

Tạo `tests/test_check_package.py`:

```python
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from check_package import pyproject_version, tag_matches, wheel_offenders  # noqa: E402


def test_pyproject_version_reads_the_declared_version():
    assert pyproject_version(REPO) == "0.9.0"


def test_tag_matches_strips_the_v_prefix():
    assert tag_matches("v0.9.1", "0.9.1")
    assert not tag_matches("v0.9.1", "0.9.0")


def _make_wheel(path: Path, names: list[str]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name in names:
            zf.writestr(name, "x")
    return path


def test_wheel_offenders_is_empty_for_a_clean_wheel(tmp_path):
    wheel = _make_wheel(
        tmp_path / "clean-0.1-py3-none-any.whl",
        ["center_kb/__init__.py", "center_kb-0.1.dist-info/METADATA"],
    )

    assert wheel_offenders(wheel) == []


def test_wheel_offenders_flags_tests_and_kb_and_sources(tmp_path):
    wheel = _make_wheel(
        tmp_path / "dirty-0.1-py3-none-any.whl",
        [
            "center_kb/__init__.py",
            "tests/test_cli.py",
            ".kb/index.yaml",
            "sources/secret.pdf",
        ],
    )

    assert sorted(wheel_offenders(wheel)) == [".kb", "sources", "tests"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_check_package.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'check_package'`.

- [ ] **Step 3: Write the implementation**

Tạo `scripts/check_package.py`:

```python
"""T2 — kiểm tra đóng gói. Thuần stdlib: chạy được ở bất kỳ venv nào.

    python scripts/check_package.py --venv /tmp/artifact --dist dist [--tag v0.9.1]

Bắt bốn kiểu sai sót:
  1. kb --version (từ WHEEL ĐÃ CÀI) lệch pyproject.version
  2. tag lệch pyproject.version  (chỉ khi có --tag)
  3. wheel lỡ đóng gói tests/ .kb/ sources/
  4. dist/ không có đủ cả wheel lẫn sdist
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from pathlib import Path

# Top-level path KHÔNG bao giờ được nằm trong wheel. `sources/` chứa PDF có bản
# quyền — lọt vào wheel là phát tán ra PyPI.
FORBIDDEN_TOP_LEVEL = {"tests", "tests-gate", ".kb", "sources", "docs"}


def pyproject_version(root: Path) -> str:
    for line in (root / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        if line.startswith("version ="):
            return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError("không tìm thấy `version =` trong pyproject.toml")


def tag_matches(tag: str, version: str) -> bool:
    return tag.removeprefix("v") == version


def wheel_offenders(wheel: Path) -> list[str]:
    tops = set()
    with zipfile.ZipFile(wheel) as zf:
        for name in zf.namelist():
            tops.add(name.split("/", 1)[0])
    return sorted(tops & FORBIDDEN_TOP_LEVEL)


def installed_version(venv: Path) -> str:
    proc = subprocess.run(
        [str(venv / "bin" / "kb"), "--version"],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"`kb --version` lỗi: {proc.stderr}")
    return proc.stdout.strip()


def check(venv: Path, dist: Path, root: Path, tag: str | None) -> list[str]:
    errors: list[str] = []
    declared = pyproject_version(root)

    wheels = sorted(dist.glob("*.whl"))
    sdists = sorted(dist.glob("*.tar.gz"))
    if not wheels:
        errors.append(f"{dist}/ không có wheel nào")
    if not sdists:
        errors.append(f"{dist}/ không có sdist nào")

    got = installed_version(venv)
    if got != declared:
        errors.append(f"`kb --version` = {got!r} nhưng pyproject.version = {declared!r}")

    for wheel in wheels:
        offenders = wheel_offenders(wheel)
        if offenders:
            errors.append(f"{wheel.name} đóng gói nhầm: {', '.join(offenders)}")

    if tag and not tag_matches(tag, declared):
        errors.append(f"tag {tag!r} lệch pyproject.version {declared!r}")

    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--venv", type=Path, required=True, help="venv có wheel đã cài")
    ap.add_argument("--dist", type=Path, default=Path("dist"))
    ap.add_argument("--root", type=Path, default=Path(__file__).parent.parent)
    ap.add_argument("--tag", default=None, help="git tag, ví dụ v0.9.1 (chỉ khi release)")
    args = ap.parse_args()

    errors = check(args.venv, args.dist, args.root, args.tag)
    for err in errors:
        print(f"[error] {err}", file=sys.stderr)
    if errors:
        return 1
    print("check_package: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_check_package.py -v`
Expected: 4 passed.

- [ ] **Step 5: Chạy thật trên dist đã build**

```bash
rm -rf dist && python -m build
python -m venv /tmp/kb-artifact && /tmp/kb-artifact/bin/pip install -q --force-reinstall dist/*.whl
python scripts/check_package.py --venv /tmp/kb-artifact --dist dist
python scripts/check_package.py --venv /tmp/kb-artifact --dist dist --tag v9.9.9
```
Expected: lần 1 in `check_package: OK`, exit 0. Lần 2 exit 1 với `tag 'v9.9.9' lệch pyproject.version '0.9.0'` — bằng chứng cửa tag có răng.

- [ ] **Step 6: Thêm `twine` vào dev extras**

Trong `pyproject.toml`, sửa dòng `dev = [...]`:

```toml
dev = ["pytest>=8.0", "anyio>=4.0", "sqlite-vec>=0.1.6", "twine>=5.0", "build>=1.2"]
```

- [ ] **Step 7: Xác minh twine + uv lock**

```bash
.venv/bin/pip install -q -e ".[dev]"
.venv/bin/python -m twine check --strict dist/*
uv lock --check
```
Expected: twine in `PASSED` cho cả wheel lẫn sdist. `uv lock --check` im lặng, exit 0 — **nếu nó đỏ, đó là lockfile đang lệch thật**: chạy `uv lock` và commit `uv.lock` cùng task này.

- [ ] **Step 8: Commit**

```bash
git add scripts/check_package.py tests/test_check_package.py pyproject.toml uv.lock
git commit -m "test: add package-integrity checks (version consistency, wheel contents)"
```

---

### Task 8: Regression — tương thích ngược `.kb/`

Tầng đắt nhất. `.kb/` được commit ở **mọi** tag (v0.7.0/v0.8.0/v0.9.0, nội dung ARINC-424 thật) — đây đúng là dữ liệu một user đang giữ trong repo của họ. Lấy thẳng từ git history, không bịa.

**Files:**
- Modify: `tests-gate/conftest.py` (thêm `legacy_kb` — conftest đã tồn tại từ Task 2)
- Create: `tests-gate/regression/test_kb_backcompat.py`

**Interfaces:**
- Consumes: `artifact`, `kb_run`, `run_git`, `bare_hub` — đã có sẵn trong conftest chung `tests-gate/conftest.py` (Task 2). Không viết lại.
- Produces: fixture `legacy_kb` (parametrized theo tag) → `dict` với `tag: str`, `repo: Path`, `kb: Path`, `hub: Path`.

- [ ] **Step 1: Bổ sung `legacy_kb` vào conftest chung**

`tests-gate/conftest.py` (Task 2) đã có `artifact`, `kb_run`, `run_git`, `bare_hub`, `free_port` —
tầng regression dùng lại y nguyên, **không** viết conftest thứ hai. Chỉ thêm phần dưới đây
vào cuối file (và `import subprocess` nếu chưa có ở đầu):

```python
LEGACY_TAGS = ["v0.7.0", "v0.8.0", "v0.9.0"]

# tests-gate/conftest.py → lùi 1 cấp là gốc repo.
REPO_ROOT = Path(__file__).parent.parent


def _materialize_kb_at_tag(tag: str, dest_repo: Path, tmp_path: Path) -> Path:
    """Bung .kb/ đúng như nó tồn tại ở một git tag, vào một repo trống.

    Cần `fetch-depth: 0` trên CI để tag tồn tại."""
    archive = tmp_path / f"{tag}.tar"
    subprocess.run(
        ["git", "archive", "--format=tar", "-o", str(archive), tag, ".kb"],
        cwd=REPO_ROOT, check=True, capture_output=True,
    )
    subprocess.run(["tar", "-xf", str(archive)], cwd=dest_repo, check=True)
    kb = dest_repo / ".kb"
    assert (kb / "index.yaml").exists(), f"{tag} không có .kb/index.yaml"
    return kb


@pytest.fixture(params=LEGACY_TAGS, ids=LEGACY_TAGS)
def legacy_kb(request, tmp_path: Path, run_git, bare_hub) -> dict:
    """Materialize .kb/ như nó tồn tại ở một tag cũ, trong một git repo trỏ vào hub.

    Mô phỏng đúng thứ user làm sau khi `pip install -U`: họ có .kb/ cũ trong repo,
    và chạy version MỚI lên nó."""
    tag = request.param
    repo = tmp_path / f"legacy-{tag}"
    repo.mkdir()
    kb = _materialize_kb_at_tag(tag, repo, tmp_path)

    (kb / "config.yaml").write_text(
        f'hub: "{bare_hub}"\nrepo_id: "legacy"\n', encoding="utf-8"
    )
    run_git(repo, "init", "-b", "main")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-m", f"legacy kb from {tag}")

    return {"tag": tag, "repo": repo, "kb": kb, "hub": bare_hub}
```

`_materialize_kb_at_tag` được tách ra vì Task 9 dùng lại nó cho fixture `published_kb`.

- [ ] **Step 2: Write the failing test**

Tạo `tests-gate/regression/test_kb_backcompat.py`:

```python
"""Version MỚI phải đọc được .kb/ do version CŨ sinh ra.

Đây là hợp đồng đắt nhất của dự án: user đã commit .kb/ vào repo của họ. Đổi
schema mà không migrate là làm vỡ hết.

ĐỎ NGHĨA LÀ GÌ — và ĐỪNG SỬA TEST CHO XANH. Phải chọn một trong hai:
  (a) viết migration để version mới đọc được định dạng cũ, hoặc
  (b) đánh dấu xfail kèm ghi chú nêu rõ version nào phá và user phải làm gì.
Không có quy tắc này thì cửa sẽ bị tắt tiếng dần trong ba tháng.
"""

from __future__ import annotations


def test_new_binary_publishes_a_legacy_kb(legacy_kb, kb_run):
    proc = kb_run(
        "publish", "--direct", "--hub", str(legacy_kb["hub"]),
        "--repo-id", "legacy", "--kb-dir", str(legacy_kb["kb"]),
        cwd=legacy_kb["repo"],
    )

    assert proc.returncode == 0, proc.stdout


def test_new_binary_runs_doctor_on_a_legacy_kb(legacy_kb, kb_run):
    kb_run("publish", "--direct", "--hub", str(legacy_kb["hub"]),
           "--repo-id", "legacy", "--kb-dir", str(legacy_kb["kb"]),
           cwd=legacy_kb["repo"])

    proc = kb_run("doctor", "--hub", str(legacy_kb["hub"]),
                  "--kb-dir", str(legacy_kb["kb"]),
                  cwd=legacy_kb["repo"], check=False)

    assert "Traceback" not in proc.stdout + proc.stderr, (
        f"doctor vỡ trên .kb của {legacy_kb['tag']}"
    )


def test_new_binary_queries_a_legacy_kb(legacy_kb, kb_run):
    kb_run("publish", "--direct", "--hub", str(legacy_kb["hub"]),
           "--repo-id", "legacy", "--kb-dir", str(legacy_kb["kb"]),
           cwd=legacy_kb["repo"])

    proc = kb_run("query", "airspace", "--hub", str(legacy_kb["hub"]),
                  "--kb-dir", str(legacy_kb["kb"]), cwd=legacy_kb["repo"])

    assert "No matching section found." not in proc.stdout, (
        f"query trên .kb của {legacy_kb['tag']} không trả về gì — "
        "section bị nuốt lặng?"
    )
```

- [ ] **Step 3: Run and read the result carefully**

```bash
KB_VENV=/tmp/kb-artifact /tmp/kb-runner/bin/pytest tests-gate/regression/test_kb_backcompat.py -v
```
Expected: 9 passed (3 test × 3 tag).

**Nếu có tag nào đỏ, ĐỪNG sửa test.** Đó là một phát hiện thật: version hiện tại đã phá tương thích với `.kb/` của tag đó. Ghi lại chính xác nó vỡ ở đâu, báo cho người review, và áp dụng quy tắc trong docstring (migration hoặc `xfail` có ghi chú).

- [ ] **Step 4: Commit**

```bash
git add tests-gate/conftest.py tests-gate/regression/test_kb_backcompat.py
git commit -m "test: regression — new binary must read .kb/ from v0.7.0/v0.8.0/v0.9.0"
```

---

### Task 9: Regression — hợp đồng MCP (golden `tools/list`)

Hợp đồng cứng với mọi agent đang cắm vào `center-kb`. Đổi tên tool, bỏ field, đổi kiểu tham số ⇒ phải đỏ.

**Files:**
- Create: `tests-gate/regression/test_mcp_contract.py`
- Create: `tests-gate/golden/mcp_tools.json` (sinh ra rồi commit)

**Interfaces:**
- Consumes: `artifact` (Task 8 conftest).
- Produces: `published_kb` fixture (một KB đã publish, dùng chung cho Task 9 + 10).

- [ ] **Step 1: Thêm fixture `published_kb` vào `tests-gate/conftest.py`**

```python
@pytest.fixture
def published_kb(tmp_path: Path, run_git, kb_run, bare_hub) -> dict:
    """KB v0.9.0 (lấy từ git history) đã publish lên hub — nền đóng băng cho
    mọi golden. Không dùng legacy_kb vì nó parametrized theo 3 tag; golden cần
    đúng MỘT nền cố định."""
    repo = tmp_path / "golden-repo"
    repo.mkdir()
    kb = _materialize_kb_at_tag("v0.9.0", repo, tmp_path)  # Task 8

    (kb / "config.yaml").write_text(
        f'hub: "{bare_hub}"\nrepo_id: "golden"\n', encoding="utf-8"
    )
    run_git(repo, "init", "-b", "main")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-m", "golden kb")
    kb_run("publish", "--direct", "--hub", str(bare_hub), "--repo-id", "golden",
           "--kb-dir", str(kb), cwd=repo)
    return {"repo": repo, "kb": kb, "hub": bare_hub}
```

- [ ] **Step 2: Write the test (golden chưa có → sẽ đỏ)**

Tạo `tests-gate/regression/test_mcp_contract.py`:

```python
"""tools/list là hợp đồng CỨNG với mọi agent đang cắm vào center-kb.

ĐỎ NGHĨA LÀ GÌ: bạn vừa đổi bề mặt MCP. Nếu là cố ý, chạy lại với
UPDATE_GOLDEN=1 và commit file golden mới — nó sẽ hiện rõ trong diff PR, và
đó chính là mục đích: một thay đổi phá agent phải là một hành động CỐ Ý, nhìn
thấy được, không phải một tác dụng phụ im lặng.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

GOLDEN = Path(__file__).parent.parent / "golden" / "mcp_tools.json"


async def _list_tools(artifact, published_kb):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=str(artifact.python),
        args=[
            "-m", "center_kb.mcp",
            "--kb", str(published_kb["kb"]),
            "--hub", str(published_kb["hub"]),
        ],
        cwd=str(published_kb["repo"]),
        env={**os.environ},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.list_tools()


def _snapshot(tools) -> dict:
    return {
        t.name: {
            "description": (t.description or "").strip(),
            "inputSchema": t.inputSchema,
        }
        for t in sorted(tools.tools, key=lambda t: t.name)
    }


def test_mcp_tool_contract_is_unchanged(artifact, published_kb):
    snapshot = _snapshot(asyncio.run(_list_tools(artifact, published_kb)))

    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")

    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))

    assert snapshot == expected
```

- [ ] **Step 3: Run to verify it fails**

Run: `KB_VENV=/tmp/kb-artifact /tmp/kb-runner/bin/pytest tests-gate/regression/test_mcp_contract.py -q`
Expected: FAIL — `FileNotFoundError: .../golden/mcp_tools.json`.

- [ ] **Step 4: Sinh golden và soi kỹ**

```bash
KB_VENV=/tmp/kb-artifact UPDATE_GOLDEN=1 /tmp/kb-runner/bin/pytest tests-gate/regression/test_mcp_contract.py -q
cat tests-gate/golden/mcp_tools.json
```
Expected: file chứa **đúng 4 khoá** — `kb_context_new`, `kb_get_section`, `kb_resolve`, `kb_search` — mỗi khoá có `description` và `inputSchema`. Kiểm bằng mắt: `kb_search.inputSchema` phải có `query` (string, required), `tags`, `budget`. Nếu thấy tool lạ hoặc thiếu tool, **dừng lại** — golden sai từ đầu thì nó gác nhầm thứ mãi mãi.

- [ ] **Step 5: Run again to verify it passes**

Run: `KB_VENV=/tmp/kb-artifact /tmp/kb-runner/bin/pytest tests-gate/regression/test_mcp_contract.py -q`
Expected: 1 passed.

- [ ] **Step 6: Chứng minh nó có răng**

Sửa tạm `src/center_kb/mcp.py`, đổi `def kb_search(` thành `def kb_find(`, rồi build + cài lại wheel + chạy lại test.
Expected: FAIL với diff cho thấy `kb_search` biến mất và `kb_find` xuất hiện. **Hoàn nguyên sửa đổi và cài lại wheel sạch.**

- [ ] **Step 7: Commit**

```bash
git add tests-gate/conftest.py tests-gate/regression/test_mcp_contract.py tests-gate/golden/mcp_tools.json
git commit -m "test: regression — freeze the MCP tools/list contract"
```

---

### Task 10: Regression — golden output

Giá trị lớn nhất của tầng này không phải bắt lỗi code của bạn, mà bắt **nâng cấp dependency**: `rank-bm25` đổi công thức ⇒ thứ tự kết quả đổi ⇒ golden đỏ. Không có nó thì kiểu vỡ này tuyệt đối im lặng.

**Files:**
- Create: `tests-gate/regression/test_golden_output.py`
- Create: `tests-gate/golden/mcp_outputs/*.txt`, `tests-gate/golden/cli_outputs/*.txt` (sinh ra rồi commit)

**Interfaces:**
- Consumes: `artifact`, `kb_run`, `published_kb` (Task 8, 9).

- [ ] **Step 1: Write the test**

Tạo `tests-gate/regression/test_golden_output.py`:

```python
"""Đóng băng OUTPUT trên một KB cố định (v0.9.0 từ git history).

Hợp đồng MÁY của center-kb nằm ở chuỗi trả về của MCP tool (kb_search,
kb_get_section, kb_resolve đều -> str) — CLI chưa có --json, nên stdout của nó
là hợp đồng NGƯỜI và chỉ được so ở dạng đã chuẩn hoá.

ĐỎ NGHĨA LÀ GÌ: hành vi đã đổi. Thường là do nâng cấp dependency (rank-bm25 đổi
công thức ranking là ca kinh điển). Điều tra TRƯỚC, chỉ chạy UPDATE_GOLDEN=1
sau khi đã hiểu tại sao nó đổi và xác nhận là mong muốn.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

GOLDEN = Path(__file__).parent.parent / "golden"

# Phần biến động giữa các lần chạy — không phải tín hiệu hành vi.
NOISE = [
    (re.compile(r"/tmp/[^\s\"']+"), "<TMP>"),
    (re.compile(r"\b[0-9a-f]{7,40}\b"), "<SHA>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}T[\d:.+]+"), "<TS>"),
    (re.compile(r"score=\d+\.\d+"), "score=<N>"),
]


def normalize(text: str) -> str:
    for pattern, repl in NOISE:
        text = pattern.sub(repl, text)
    return text.strip() + "\n"


def assert_golden(name: str, actual: str) -> None:
    path = GOLDEN / name
    actual = normalize(actual)
    if os.environ.get("UPDATE_GOLDEN") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8")
    assert actual == path.read_text(encoding="utf-8"), f"{name} đã đổi"


async def _call(artifact, published_kb, tool: str, args: dict) -> str:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=str(artifact.python),
        args=["-m", "center_kb.mcp", "--kb", str(published_kb["kb"]),
              "--hub", str(published_kb["hub"])],
        cwd=str(published_kb["repo"]),
        env={**os.environ},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, args)
            return "".join(c.text for c in result.content if c.type == "text")


def test_golden_kb_search(artifact, published_kb):
    out = asyncio.run(_call(artifact, published_kb, "kb_search", {"query": "airspace"}))

    assert_golden("mcp_outputs/kb_search_airspace.txt", out)


def test_golden_kb_get_section(artifact, published_kb):
    out = asyncio.run(
        _call(artifact, published_kb, "kb_search", {"query": "restrictive airspace"})
    )

    assert_golden("mcp_outputs/kb_search_restrictive.txt", out)


def test_golden_cli_query(published_kb, kb_run):
    out = kb_run("query", "airspace", "--hub", str(published_kb["hub"]),
                 "--kb-dir", str(published_kb["kb"]),
                 cwd=published_kb["repo"]).stdout

    assert_golden("cli_outputs/query_airspace.txt", out)
```

- [ ] **Step 2: Run to verify it fails**

Run: `KB_VENV=/tmp/kb-artifact /tmp/kb-runner/bin/pytest tests-gate/regression/test_golden_output.py -q`
Expected: FAIL — golden chưa tồn tại.

- [ ] **Step 3: Sinh golden và ĐỌC KỸ**

```bash
KB_VENV=/tmp/kb-artifact UPDATE_GOLDEN=1 /tmp/kb-runner/bin/pytest tests-gate/regression/test_golden_output.py -q
cat tests-gate/golden/cli_outputs/query_airspace.txt
cat tests-gate/golden/mcp_outputs/kb_search_airspace.txt
```

Kiểm bằng mắt hai điều, **cả hai đều bắt buộc**:
1. Output có nội dung thật (citation + nội dung L2 của ARINC-424), không phải `No matching section found.` Nếu rỗng, golden đang đóng băng một cái *hỏng*.
2. Không còn đường dẫn `/tmp/...`, SHA, hay timestamp nào lọt qua bộ chuẩn hoá. Nếu còn, golden sẽ đỏ ngẫu nhiên ở lần chạy sau → cửa flaky → cửa bị vô hiệu hoá. Thêm pattern vào `NOISE` và sinh lại.

- [ ] **Step 4: Chạy hai lần liên tiếp để chứng minh không flaky**

```bash
KB_VENV=/tmp/kb-artifact /tmp/kb-runner/bin/pytest tests-gate/regression/test_golden_output.py -q
KB_VENV=/tmp/kb-artifact /tmp/kb-runner/bin/pytest tests-gate/regression/test_golden_output.py -q
```
Expected: 3 passed, cả hai lần. Golden chạy trên `tmp_path` khác nhau mỗi lần — nếu lần hai đỏ, bộ chuẩn hoá còn thủng.

- [ ] **Step 5: Commit**

```bash
git add tests-gate/regression/test_golden_output.py tests-gate/golden/
git commit -m "test: regression — freeze MCP tool outputs and CLI query output"
```

---

### Task 11: Regression — tương thích federation

Snapshot `federation/` do v0.9.0 sinh ra phải được binary mới đọc đúng. Đây là fixture **duy nhất** được commit thay vì lấy từ git history — vì `federation/` không nằm trong repo này, nó nằm trên hub.

**Files:**
- Create: `tests-gate/golden/federation-v0.9.0/` (sinh một lần rồi commit)
- Create: `tests-gate/regression/test_federation_compat.py`

**Interfaces:**
- Consumes: `artifact`, `kb_run`, `run_git` (Task 8).

- [ ] **Step 1: Sinh fixture federation bằng v0.9.0 THẬT**

```bash
# venv riêng, cài đúng center-kb 0.9.0 từ PyPI — KHÔNG dùng source tree.
python -m venv /tmp/kb-090
/tmp/kb-090/bin/pip install -q "center-kb==0.9.0"

WORK=$(mktemp -d)
git archive --format=tar -o "$WORK/kb.tar" v0.9.0 .kb
mkdir -p "$WORK/repo" && tar -xf "$WORK/kb.tar" -C "$WORK/repo"

# hub bare
mkdir -p "$WORK/hubwork/.kb" "$WORK/hubwork/federation"
echo "docs: []" > "$WORK/hubwork/.kb/index.yaml"
echo "docs: []" > "$WORK/hubwork/federation/index.yaml"
git -C "$WORK/hubwork" init -b main -q
git -C "$WORK/hubwork" add -A
git -C "$WORK/hubwork" -c user.name=gen -c user.email=gen@local commit -qm "hub init"
git clone --bare -q "$WORK/hubwork" "$WORK/hub.git"

printf 'hub: "%s"\nrepo_id: "golden"\n' "$WORK/hub.git" > "$WORK/repo/.kb/config.yaml"
git -C "$WORK/repo" init -b main -q
git -C "$WORK/repo" add -A
git -C "$WORK/repo" -c user.name=gen -c user.email=gen@local commit -qm "kb"

cd "$WORK/repo"
GIT_AUTHOR_NAME=gen GIT_AUTHOR_EMAIL=gen@local \
GIT_COMMITTER_NAME=gen GIT_COMMITTER_EMAIL=gen@local \
  /tmp/kb-090/bin/kb publish --direct --hub "$WORK/hub.git" --repo-id golden

# Lấy cây federation/ ra khỏi hub bare
cd "$OLDPWD"
git clone -q "$WORK/hub.git" "$WORK/hubout"
rm -rf tests-gate/golden/federation-v0.9.0
mkdir -p tests-gate/golden/federation-v0.9.0
cp -r "$WORK/hubout/federation/." tests-gate/golden/federation-v0.9.0/
find tests-gate/golden/federation-v0.9.0 -type f | sort
```

Expected: `index.yaml` + `golden/_meta.yaml` + `golden/index.yaml` + `golden/<doc-id>/{_manifest.yaml, *.md, *.raw.md}`. Nếu trống, dừng lại — fixture rỗng gác nhầm.

- [ ] **Step 2: Write the failing test**

Tạo `tests-gate/regression/test_federation_compat.py`:

```python
"""Binary MỚI phải đọc được federation/ do v0.9.0 publish.

Hub là single source of truth và nhiều repo publish lên cùng một hub với các
version khác nhau. Một entry publish bởi bản cũ mà bản mới không đọc được
nghĩa là nâng cấp một repo làm mù cả hub.

ĐỎ NGHĨA LÀ GÌ: xem quy tắc trong test_kb_backcompat.py — migration hoặc xfail
có ghi chú. Không sửa test cho xanh.
"""

from __future__ import annotations

import shutil
from pathlib import Path

FIXTURE = Path(__file__).parent.parent / "golden" / "federation-v0.9.0"


def _hub_from_fixture(tmp_path: Path, run_git) -> Path:
    """Dựng lại một hub git từ cây federation/ đã đóng băng."""
    work = tmp_path / "hub-work"
    (work / ".kb").mkdir(parents=True)
    (work / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    shutil.copytree(FIXTURE, work / "federation")
    run_git(work, "init", "-b", "main")
    run_git(work, "add", "-A")
    run_git(work, "commit", "-m", "hub published by v0.9.0")
    return work


def test_new_binary_queries_a_v090_federation(tmp_path, run_git, kb_run):
    hub = _hub_from_fixture(tmp_path, run_git)
    repo = tmp_path / "reader"
    (repo / ".kb").mkdir(parents=True)
    (repo / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")

    proc = kb_run("query", "airspace", "--hub", str(hub),
                  "--kb-dir", str(repo / ".kb"), cwd=repo)

    assert "No matching section found." not in proc.stdout, (
        "binary mới không đọc được federation do v0.9.0 publish"
    )


def test_new_binary_doctors_a_v090_federation(tmp_path, run_git, kb_run):
    hub = _hub_from_fixture(tmp_path, run_git)
    repo = tmp_path / "reader"
    (repo / ".kb").mkdir(parents=True)
    (repo / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")

    proc = kb_run("doctor", "--hub", str(hub), "--kb-dir", str(repo / ".kb"),
                  cwd=repo, check=False)

    assert "Traceback" not in proc.stdout + proc.stderr
```

- [ ] **Step 3: Run and verify**

Run: `KB_VENV=/tmp/kb-artifact /tmp/kb-runner/bin/pytest tests-gate/regression/test_federation_compat.py -q`
Expected: 2 passed.

- [ ] **Step 4: Chạy trọn cửa lần đầu bằng `gate.sh`**

Run: `./scripts/gate.sh`
Expected: chạy hết T1 → T2 → T3 → T4 và in `✅ Cửa xanh. An toàn để tag.` Đây là lần đầu tiên tiêu chí hoàn thành #2 của spec được thoả mãn.

- [ ] **Step 5: Commit**

```bash
git add tests-gate/golden/federation-v0.9.0 tests-gate/regression/test_federation_compat.py
git commit -m "test: regression — new binary must read a federation published by v0.9.0"
```

---

### Task 12: `_gate.yml` + `ci.yml`

Đưa cửa lên CI. Sau task này, **mọi PR đều chạy đúng bộ cửa mà tag sẽ chạy** — lấp lỗ hổng L1 (hiện tại PR không chạy gì cả).

**Files:**
- Create: `.github/workflows/_gate.yml`
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: reusable workflow `_gate.yml` (`on: workflow_call`). Task 13 `uses:` nó.

- [ ] **Step 1: Viết `_gate.yml`**

Tạo `.github/workflows/_gate.yml`:

```yaml
# Cửa kiểm định dùng chung. ci.yml (PR/main) và release.yml (tag) đều uses: nó.
#
# BẤT BIẾN: tag KHÔNG chạy gì mới so với PR. Nếu bạn định thêm một bước "chỉ
# chạy khi release", dừng lại — đó chính là cách quy trình cũ để lọt lỗi tới
# đúng phút cuối. Thêm vào đây, để PR cũng chạy.
name: gate
on:
  workflow_call:
    inputs:
      tag:
        description: "Git tag khi release (vd v0.9.1). Rỗng trên PR."
        type: string
        required: false
        default: ""

jobs:
  t1-tests:
    name: T1 unit/integration (py${{ matrix.python }})
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - run: pip install -e ".[dev]"
      - run: pytest -q
        env:
          # Test e2e chạy `kb publish` / gitio.commit_* trên git clone thật —
          # commit cần identity, mà runner CI không có ~/.gitconfig.
          GIT_AUTHOR_NAME: ci-test
          GIT_AUTHOR_EMAIL: ci-test@local
          GIT_COMMITTER_NAME: ci-test
          GIT_COMMITTER_EMAIL: ci-test@local

  t2-package:
    name: T2 đóng gói
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - uses: astral-sh/setup-uv@v5
        with:
          version: "0.11.8"
      - run: pip install build twine
      - run: python -m build
      - name: uv.lock đồng bộ với pyproject
        run: uv lock --check
      - name: twine check (metadata + README render trên PyPI)
        run: python -m twine check --strict dist/*
      - name: Cài wheel vào venv sạch
        run: |
          python -m venv /tmp/artifact
          /tmp/artifact/bin/pip install --quiet dist/*.whl
      - name: Version consistency + nội dung wheel
        run: python scripts/check_package.py --venv /tmp/artifact --dist dist --tag "${{ inputs.tag }}"
      - name: sdist cài được vào venv sạch (smoke mỏng)
        run: |
          python -m venv /tmp/sdist-venv
          /tmp/sdist-venv/bin/pip install --quiet dist/*.tar.gz
          /tmp/sdist-venv/bin/kb --version
          /tmp/sdist-venv/bin/python -c "from importlib import resources; resources.files('center_kb').joinpath('templates/web/base.html').read_text(encoding='utf-8')"
      - uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/

  t3-e2e:
    name: T3 e2e trên artifact (py${{ matrix.python }})
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - run: pip install build
      - run: python -m build --wheel
      - name: Venv artifact (CHỈ wheel)
        run: |
          python -m venv /tmp/artifact
          /tmp/artifact/bin/pip install --quiet dist/*.whl
      - name: Venv runner (pytest, KHÔNG có center-kb)
        run: |
          python -m venv /tmp/runner
          /tmp/runner/bin/pip install --quiet -r requirements-gate.txt
      - name: pytest tests-gate/e2e
        run: KB_VENV=/tmp/artifact /tmp/runner/bin/pytest tests-gate/e2e -q

  t4-regression:
    name: T4 regression (py${{ matrix.python }})
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
        with:
          # Fixture legacy lấy từ `git archive v0.7.0 .kb` — cần đủ tag + history.
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - run: pip install build
      - run: python -m build --wheel
      - name: Venv artifact (CHỈ wheel)
        run: |
          python -m venv /tmp/artifact
          /tmp/artifact/bin/pip install --quiet dist/*.whl
      - name: Venv runner (pytest, KHÔNG có center-kb)
        run: |
          python -m venv /tmp/runner
          /tmp/runner/bin/pip install --quiet -r requirements-gate.txt
      - name: pytest tests-gate/regression
        run: KB_VENV=/tmp/artifact /tmp/runner/bin/pytest tests-gate/regression -q
```

- [ ] **Step 2: Viết `ci.yml`**

Tạo `.github/workflows/ci.yml`:

```yaml
name: ci
on:
  pull_request:
  push:
    branches: [main]

# PR push liên tiếp không xếp hàng đốt runner.
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

permissions:
  contents: read

jobs:
  gate:
    uses: ./.github/workflows/_gate.yml
    # tag rỗng → check_package.py bỏ qua khẳng định tag==version (chỉ có
    # nghĩa lúc release).
```

- [ ] **Step 3: Xác minh cú pháp workflow trước khi push**

```bash
python -c "import yaml,sys; [yaml.safe_load(open(f)) for f in ['.github/workflows/_gate.yml','.github/workflows/ci.yml']]; print('YAML OK')"
```
Expected: `YAML OK`.

- [ ] **Step 4: Commit và đẩy lên một branch để CI chạy thật**

```bash
git add .github/workflows/_gate.yml .github/workflows/ci.yml
git commit -m "ci: run the full gate on every PR and push to main"
git push -u origin HEAD
```

- [ ] **Step 5: Xem CI chạy và đọc kết quả**

```bash
gh run watch
```
Expected: 7 job xanh — `t1-tests` ×2, `t2-package`, `t3-e2e` ×2, `t4-regression` ×2.

Nếu `t2-package` đỏ ở `uv lock --check`: lockfile lệch thật → `uv lock && git commit uv.lock`.
Nếu `t4-regression` đỏ ở `git archive`: `fetch-depth: 0` chưa ăn, hoặc tag chưa được fetch — kiểm lại step checkout.

---

### Task 13: `release.yml` — sửa đồ thị phụ thuộc

Lấp lỗ hổng L7. Hiện `docker` chỉ `needs: test` và chạy song song `pypi`: image `:latest` vẫn được đẩy kể cả khi PyPI hỏng, và PyPI vẫn publish được kể cả khi image không build nổi (tức `[ingest]` không resolve).

**Files:**
- Modify: `.github/workflows/release.yml` (viết lại toàn bộ)

**Interfaces:**
- Consumes: `.github/workflows/_gate.yml` (Task 12).

- [ ] **Step 1: Viết lại `release.yml`**

Thay toàn bộ nội dung `.github/workflows/release.yml`:

```yaml
# Release: tag v* → cửa đầy đủ (giống hệt PR) → rồi mới publish.
#
# Thứ tự đồ thị là cố ý:
#   _gate → docker-verify → pypi → docker-release
# Không có gì không-thể-hoàn-tác xảy ra trước khi TOÀN BỘ cửa xanh. docker-verify
# build image = `pip install center-kb[ingest]` thật → nó chính là cửa gác cho
# extras (docling/torch); PyPI không được publish nếu extras không resolve.
name: release
on:
  push:
    tags: ["v*"]

permissions:
  contents: read

jobs:
  gate:
    uses: ./.github/workflows/_gate.yml
    with:
      tag: ${{ github.ref_name }}

  docker-verify:
    name: Build image + smoke (chưa release tag)
    needs: gate
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      - name: Login to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - name: Build image
        run: docker build -t ghcr.io/vuonglq01685/center-kb:sha-${GITHUB_SHA} .
      - name: Smoke — serve một KB rỗng; health phải trả lời, API phải 401
        run: |
          mkdir -p /tmp/data/.kb /tmp/data/federation
          echo "docs: []" > /tmp/data/.kb/index.yaml
          echo "docs: []" > /tmp/data/federation/index.yaml
          docker run -d --name kb -p 8321:8321 \
            -e CENTER_KB_HTTP_TOKEN=smoke-test-token \
            -v /tmp/data:/data \
            ghcr.io/vuonglq01685/center-kb:sha-${GITHUB_SHA}
          for i in $(seq 1 30); do
            curl -sf http://localhost:8321/api/health && break
            sleep 2
          done
          curl -sf http://localhost:8321/api/health
          code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8321/api/docs)
          test "$code" = "401"
          docker rm -f kb
      - name: Push tag sha- (vô hại — KHÔNG phải tag release)
        run: docker push ghcr.io/vuonglq01685/center-kb:sha-${GITHUB_SHA}

  pypi:
    name: Publish PyPI (không thể hoàn tác — đi sau MỌI cửa)
    needs: [gate, docker-verify]
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      - uses: pypa/gh-action-pypi-publish@release/v1

  docker-release:
    name: Retag image → vX.Y.Z + latest
    needs: pypi
    runs-on: ubuntu-latest
    permissions:
      packages: write
    steps:
      - name: Login to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - name: Retag (không build lại — chỉ trỏ manifest, vài giây)
        run: |
          docker buildx imagetools create \
            --tag ghcr.io/vuonglq01685/center-kb:${GITHUB_REF_NAME} \
            --tag ghcr.io/vuonglq01685/center-kb:latest \
            ghcr.io/vuonglq01685/center-kb:sha-${GITHUB_SHA}
```

- [ ] **Step 2: Xác minh cú pháp**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml')); print('YAML OK')"
```
Expected: `YAML OK`.

- [ ] **Step 3: Xác minh đồ thị phụ thuộc bằng mắt**

Đọc lại `needs:` của từng job và khẳng định bốn điều:
1. `docker-verify` needs `gate` — image không build nếu cửa đỏ.
2. `pypi` needs **cả** `gate` **và** `docker-verify` — PyPI không publish nếu image không build/smoke được.
3. `docker-release` needs `pypi` — `:latest` không bao giờ trỏ vào một version chưa lên PyPI.
4. Không job nào push tag `vX.Y.Z` hay `latest` trước `pypi`.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: gate the whole release; nothing irreversible ships before every check is green"
```

- [ ] **Step 5: Diễn tập release trên tag nháp**

```bash
git tag v0.9.0-gate-rehearsal
git push origin v0.9.0-gate-rehearsal
gh run watch
```

Expected: `gate` chạy đủ 7 job. `t2-package` **PHẢI ĐỎ** ở `check_package.py` với thông điệp `tag 'v0.9.0-gate-rehearsal' lệch pyproject.version '0.9.0'` → `docker-verify`, `pypi`, `docker-release` đều bị skip.

Đây là kết quả **mong muốn**: nó chứng minh cửa tag có răng và **không có gì được publish**. Dọn:

```bash
git push --delete origin v0.9.0-gate-rehearsal
git tag -d v0.9.0-gate-rehearsal
```

- [ ] **Step 6: Cập nhật README với quy trình release mới**

Thêm mục vào `README.md` (đặt gần phần development/contributing):

```markdown
## Release

Trước khi tag, chạy toàn bộ cửa trên máy:

```bash
./scripts/gate.sh
```

Nó chạy đúng những gì CI chạy: T1 (unit) → T2 (đóng gói + version consistency)
→ T3 (e2e trên wheel đã cài) → T4 (regression: `.kb` legacy, golden output,
hợp đồng MCP, federation).

Khi cửa xanh:

```bash
# 1. bump version trong pyproject.toml, rồi:
uv lock
git commit -am "chore: bump to X.Y.Z"

# 2. tag — CI chạy lại toàn bộ cửa, chỉ publish khi mọi thứ xanh
git tag vX.Y.Z && git push --tags
```

Tag không chạy gì mới so với PR. Nếu cửa đỏ, chưa có gì được publish — xoá tag,
sửa, tag lại.
```

- [ ] **Step 7: Commit**

```bash
git add README.md
git commit -m "docs: document the gated release workflow"
```

---

## Tự soát (đã chạy)

**Spec coverage** — đối chiếu từng mục của spec với task:

| Spec | Task |
|---|---|
| §2 tiêu chí #1 (PR chạy đúng cửa của tag) | Task 12 (`_gate.yml` dùng chung) |
| §2 tiêu chí #2 (một lệnh chạy cửa trên máy dev) | Task 2 (`scripts/gate.sh`), hoàn chỉnh ở Task 11 Step 4 |
| §2 tiêu chí #3 (không có gì irreversible trước khi cửa xanh) | Task 13 |
| §2 tiêu chí #4 (phủ 4 loại sai sót) | T1 (có sẵn) + Task 7 (đóng gói, version) + Task 3/5/6 (môi trường sạch) + Task 8–11 (regression) |
| §2 tiêu chí #5 (không thể xanh khi chạy 0 test) | Task 2 (fixture `artifact` raise; pytest exit 5) |
| §3 quyết định #1–#11 | Task 2 (#3,#4,#5,#6), Task 3 (#7), Task 12 (#1,#2), Task 13 (#8,#11), Task 9/10 (#9), Task 8 (#10) |
| §5 hành trình bước 0–11 | Task 3 (0–4), Task 5 (5–8), Task 6 (9–11) |
| §6.1 backcompat `.kb` | Task 8 |
| §6.2 hợp đồng MCP | Task 9 |
| §6.3 golden output | Task 10 |
| §6.4 federation compat | Task 11 |
| §7.1 `_gate.yml` + `ci.yml` | Task 12 |
| §7.2 đồ thị phụ thuộc | Task 13 |
| §7.3 bảng version consistency | Task 7 (`check_package.py`) + Task 12 (`uv lock --check`, `twine check`) |
| §7.4 concurrency, fetch-depth | Task 12 |
| §8 hạng mục #1 `kb --version` | Task 1 |
| §8 hạng mục #2 `uv lock --check` | Task 7 Step 7, Task 12 |
| §9 rủi ro: thoái hoá tầng | Task 2 (canary) |
| §9 rủi ro: fixture seed trôi | Task 4 |

Không có mục nào của spec thiếu task.

**Type consistency** — tên hàm/fixture dùng xuyên suốt: `artifact` (`.venv`/`.kb`/`.python`), `kb_run(*args, cwd=, env=, check=, timeout=)`, `run_git(cwd, *args)`, `stub_claude → dict`, `bare_hub → Path`, `free_port → int`, `published_repo → dict{repo,kb,hub}` (e2e), `published_kb → dict{repo,kb,hub}` (regression), `legacy_kb → dict{tag,repo,kb,hub}`, `seed_kb` fixture → callable `(repo, hub) → Path`, `pyproject_version(root)`, `tag_matches(tag, version)`, `wheel_offenders(wheel)`, `check(venv, dist, root, tag)`, `generate(kb_dir)`. Khớp giữa nơi định nghĩa và nơi dùng.

**Ghi chú có chủ đích:** `published_repo` và `published_kb` (cùng sống trong `tests-gate/conftest.py`) là hai fixture khác nhau, không phải lỗi đặt tên: cái đầu dựng KB từ fixture seed tổng hợp; cái sau dựng từ `.kb` thật của tag v0.9.0 để làm nền đóng băng cho golden.
