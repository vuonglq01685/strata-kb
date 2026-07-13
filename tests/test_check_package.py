from __future__ import annotations

import io
import re
import sys
import tarfile
import zipfile
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from check_package import (  # noqa: E402
    pyproject_version,
    sdist_offenders,
    tag_matches,
    wheel_offenders,
)


def test_pyproject_version_reads_the_declared_version(tmp_path):
    # Dựng pyproject giả: test parser, KHÔNG ghim version thật của repo —
    # hardcode một con số ở đây sẽ biến mọi lần bump version thành một test đỏ.
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "center-kb"\nversion = "1.2.3"\n', encoding="utf-8"
    )

    assert pyproject_version(tmp_path) == "1.2.3"


def test_pyproject_version_reads_this_repo():
    version = pyproject_version(REPO)

    assert re.fullmatch(r"\d+\.\d+\.\d+", version), version


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


def _make_sdist(path: Path, root: str, names: list[str]) -> Path:
    # sdist lồng mọi entry dưới một thư mục gốc `<root>/` — khác wheel, nơi
    # các entry đã là top-level sẵn.
    with tarfile.open(path, "w:gz") as tf:
        for name in names:
            data = b"x"
            info = tarfile.TarInfo(name=f"{root}/{name}")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return path


def test_sdist_offenders_is_empty_for_a_clean_sdist(tmp_path):
    # Không hardcode version thật của repo — root chỉ cần khớp cấu trúc
    # `<name>-<version>/` mà sdist thật sự dùng.
    root = "clean-0.1"
    sdist = _make_sdist(
        tmp_path / f"{root}.tar.gz",
        root,
        ["PKG-INFO", "pyproject.toml", "README.md", "LICENSE", "src/center_kb/__init__.py"],
    )

    assert sdist_offenders(sdist) == []


def test_sdist_offenders_flags_tests_and_kb_and_sources(tmp_path):
    root = "dirty-0.1"
    sdist = _make_sdist(
        tmp_path / f"{root}.tar.gz",
        root,
        [
            "PKG-INFO",
            "src/center_kb/__init__.py",
            "tests/x.py",
            ".kb/index.yaml",
            "sources/secret.pdf",
        ],
    )

    assert sorted(sdist_offenders(sdist)) == [".kb", "sources", "tests"]
