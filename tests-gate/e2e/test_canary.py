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
