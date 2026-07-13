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
