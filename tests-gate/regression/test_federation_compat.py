"""Binary MỚI phải đọc được federation/ do v0.9.0 publish.

Hub là single source of truth và nhiều repo publish lên cùng một hub với các
version khác nhau. Một entry publish bởi bản cũ mà bản mới không đọc được
nghĩa là nâng cấp một repo làm mù cả hub.

ĐỎ NGHĨA LÀ GÌ: xem quy tắc trong test_kb_backcompat.py — migration hoặc xfail
có ghi chú. Không sửa test cho xanh.

NGUỒN FIXTURE — một khác biệt so với kế hoạch gốc, cần nói rõ: `center-kb
0.9.0` CHƯA BAO GIỜ lên PyPI (`pip install center-kb==0.9.0` báo "Could not
find a version that satisfies the requirement" — danh sách version có sẵn
nhảy thẳng từ 0.8.0 sang 0.9.1). Đối chiếu `git diff v0.9.0..v0.9.1 --stat`
cho thấy khác biệt DUY NHẤT là `.github/workflows/release.yml`,
`pyproject.toml` (bump version), `uv.lock` — KHÔNG có dòng nào trong `src/`
đổi. Tức là 0.9.0 release đã hỏng ở bước publish (workflow), được vá và phát
hành lại dưới số 0.9.1 với đúng mã nguồn federation của 0.9.0. Fixture này vì
vậy được sinh bằng `pip install "center-kb==0.9.1"` (venv riêng, từ PyPI thật,
không đụng source tree) — bản build ĐỘC LẬP thật sự cũ hơn HEAD, mang đúng mã
publish/federation của v0.9.0. Tên thư mục giữ nguyên `federation-v0.9.0` vì
đó là điều nó đại diện: định dạng federation của dòng v0.9.0.
"""

from __future__ import annotations

import shutil
from pathlib import Path

FIXTURE = Path(__file__).parent.parent / "golden" / "federation-v0.9.0"


def _repo_id() -> str:
    """repo_id publish của fixture = tên thư mục con DUY NHẤT dưới FIXTURE mà
    không phải index.yaml tổng. Không hardcode 'golden' ở đây lẫn ở nơi khác —
    đọc lại đúng cái đã publish, dù script sinh fixture đổi repo-id sau này."""
    dirs = sorted(p.name for p in FIXTURE.iterdir() if p.is_dir())
    assert len(dirs) == 1, (
        f"kỳ vọng đúng MỘT thư mục repo dưới {FIXTURE}, thấy {dirs} — "
        "fixture federation hỏng hay bị sinh sai?"
    )
    return dirs[0]


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
        "binary mới không đọc được federation do v0.9.0 publish\n"
        f"--- stdout ---\n{proc.stdout}"
    )
    repo_id = _repo_id()
    assert f"[{repo_id}:" in proc.stdout, (
        f"query trả kết quả nhưng không thấy citation gắn với repo "
        f"'{repo_id}' — có thể đang khớp trúng một nguồn khác, không phải "
        f"federation v0.9.0 đang kiểm tra\n--- stdout ---\n{proc.stdout}"
    )


def test_new_binary_doctors_a_v090_federation(tmp_path, run_git, kb_run):
    """Không chỉ "không Traceback" — sàn đó quá thấp (xem lý do trong
    test_kb_backcompat.py::test_new_binary_runs_doctor_on_a_legacy_kb). Phải
    thấy đúng dòng 'kb doctor: OK' VÀ không một dòng [warning]/[error] nào,
    để chứng minh doctor thực sự đọc được — chứ không chỉ đơn giản là không
    sập khi gặp federation/ nó không hiểu."""
    hub = _hub_from_fixture(tmp_path, run_git)
    repo = tmp_path / "reader"
    (repo / ".kb").mkdir(parents=True)
    (repo / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")

    proc = kb_run("doctor", "--hub", str(hub), "--kb-dir", str(repo / ".kb"),
                  cwd=repo, check=False)

    assert "Traceback" not in proc.stdout + proc.stderr, (
        f"doctor vỡ trên federation do v0.9.0 publish\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    assert "kb doctor: OK" in proc.stdout, (
        "doctor không in 'kb doctor: OK' trên federation do v0.9.0 publish — "
        "không rõ là đọc đúng hay chỉ đơn giản là không crash\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    assert "[warning]" not in proc.stdout, (
        "doctor in 'kb doctor: OK' nhưng vẫn có [warning] trên federation do "
        f"v0.9.0 publish\n--- stdout ---\n{proc.stdout}"
    )
    assert "[error]" not in proc.stdout, (
        "doctor in 'kb doctor: OK' nhưng vẫn có [error] trên federation do "
        f"v0.9.0 publish\n--- stdout ---\n{proc.stdout}"
    )
