"""T2 — kiểm tra đóng gói. Thuần stdlib: chạy được ở bất kỳ venv nào.

    python scripts/check_package.py --venv /tmp/artifact --dist dist [--tag v0.9.1]

Bắt năm kiểu sai sót:
  1. kb --version (từ WHEEL ĐÃ CÀI) lệch pyproject.version
  2. tag lệch pyproject.version  (chỉ khi có --tag)
  3. wheel chứa bất kỳ thứ gì ngoài package thật + dist-info
  4. sdist chứa bất kỳ thứ gì ngoài src/ + các file metadata hatchling tự
     thêm — hatchling mặc định nhét mọi thứ không bị gitignore vào sdist,
     và .kb/ chứa text trích nguyên văn PDF bản quyền, nên lọt vào sdist là
     phát tán ra PyPI y như lọt vào wheel
  5. dist/ không có đủ cả wheel lẫn sdist

Mục 3+4 dùng ALLOWLIST (cái gì được phép có), không phải denylist (cái gì bị
cấm): denylist chỉ bắt được tên ai đó nghĩ tới mà viết ra — nó từng bỏ lọt
`AERO-KB_Architecture_v0.1.pdf` ở root, `.claude/`, `.github/`, `scripts/`
vì không ai liệt kê chúng, và nó mục ruỗng dần mỗi khi repo mọc thêm một
thư mục top-level mới. Allowlist ngắn hơn VÀ chặt hơn: bất cứ thứ gì không
nằm trong danh sách biết-là-tốt đều bị gắn cờ, không cần đoán trước tên xấu.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

# ---- Wheel: chỉ được có package thật + thư mục metadata chuẩn của wheel. ----
# Tên thư mục `<name>-<version>.dist-info/` đổi theo version ở mỗi build nên
# so bằng suffix, không hardcode version.
WHEEL_PACKAGE_DIR = "center_kb"
WHEEL_DIST_INFO_SUFFIX = ".dist-info"

# ---- sdist: src/ (mã nguồn thật) + các file metadata hatchling LUÔN tự thêm
# vô điều kiện vào MỌI sdist target, bất kể only-include khai gì.
# pyproject.toml/README/LICENSE: theo comment ở [tool.hatch.build.targets.sdist]
# trong pyproject.toml. PKG-INFO: sinh bởi chính bước build sdist. .gitignore:
# xác nhận bằng thực nghiệm (build thử rồi liệt kê nội dung thật, không đoán).
SDIST_ALLOWED_TOP_LEVEL = {
    "src", "PKG-INFO", "pyproject.toml", "README.md", "LICENSE", ".gitignore",
}


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
    allowed = {WHEEL_PACKAGE_DIR} | {t for t in tops if t.endswith(WHEEL_DIST_INFO_SUFFIX)}
    return sorted(tops - allowed)


def sdist_offenders(sdist: Path) -> list[str]:
    # sdist tarball lồng mọi entry dưới một thư mục gốc `<name>-<version>/` —
    # top-level THẬT là đoạn đường dẫn THỨ HAI, không phải đoạn đầu như wheel.
    tops = set()
    with tarfile.open(sdist, "r:gz") as tf:
        for name in tf.getnames():
            parts = name.split("/", 2)
            if len(parts) > 1:
                tops.add(parts[1])
    return sorted(tops - SDIST_ALLOWED_TOP_LEVEL)


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
