"""T2 — kiểm tra đóng gói. Thuần stdlib: chạy được ở bất kỳ venv nào.

    python scripts/check_package.py --venv /tmp/artifact --dist dist [--tag v0.9.1]

Bắt năm kiểu sai sót:
  1. kb --version (từ WHEEL ĐÃ CÀI) lệch pyproject.version
  2. tag lệch pyproject.version  (chỉ khi có --tag)
  3. wheel lỡ đóng gói tests/ .kb/ sources/
  4. sdist lỡ đóng gói tests/ .kb/ sources/ (hatchling mặc định nhét mọi thứ
     không bị gitignore vào sdist — .kb/ chứa text trích nguyên văn PDF bản
     quyền, lọt vào sdist là phát tán ra PyPI y như lọt vào wheel)
  5. dist/ không có đủ cả wheel lẫn sdist
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tarfile
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


def sdist_offenders(sdist: Path) -> list[str]:
    # sdist tarball lồng mọi entry dưới một thư mục gốc `<name>-<version>/` —
    # top-level THẬT là đoạn đường dẫn THỨ HAI, không phải đoạn đầu như wheel.
    tops = set()
    with tarfile.open(sdist, "r:gz") as tf:
        for name in tf.getnames():
            parts = name.split("/", 2)
            if len(parts) > 1:
                tops.add(parts[1])
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

    for sdist in sdists:
        offenders = sdist_offenders(sdist)
        if offenders:
            errors.append(f"{sdist.name} đóng gói nhầm: {', '.join(offenders)}")

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
