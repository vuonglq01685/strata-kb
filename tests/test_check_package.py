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
    # Build a fake pyproject: this tests the parser, it does NOT pin the repo's
    # real version — hardcoding a number here would turn every version bump
    # into a red test.
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


def test_wheel_offenders_allows_any_dist_info_version_suffix(tmp_path):
    # The dist-info name changes with the version on every build (e.g. 0.9.1,
    # 1.0.0-rc1...) — the allowlist matches on the ".dist-info" suffix and does
    # not hardcode a specific version, so any version must pass clean.
    wheel = _make_wheel(
        tmp_path / "clean-9.9.9-py3-none-any.whl",
        ["center_kb/__init__.py", "center_kb-9.9.9.dist-info/METADATA"],
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


def test_wheel_offenders_flags_top_levels_a_denylist_would_have_missed(tmp_path):
    # This is exactly the hole the old denylist (FORBIDDEN_TOP_LEVEL) failed to
    # catch: nobody listed these names ahead of time, so they slipped through
    # silently. The allowlist catches them because it does not need to know the
    # bad names in advance.
    wheel = _make_wheel(
        tmp_path / "dirty2-0.1-py3-none-any.whl",
        [
            "center_kb/__init__.py",
            "AERO-KB_Architecture_v0.1.pdf",
            ".claude/settings.json",
            ".github/workflows/ci.yml",
            "scripts/check_package.py",
        ],
    )

    assert sorted(wheel_offenders(wheel)) == [
        ".claude",
        ".github",
        "AERO-KB_Architecture_v0.1.pdf",
        "scripts",
    ]


def _make_sdist(path: Path, root: str, names: list[str]) -> Path:
    # An sdist nests every entry under a single root directory `<root>/` —
    # unlike a wheel, where the entries are already top-level.
    with tarfile.open(path, "w:gz") as tf:
        for name in names:
            data = b"x"
            info = tarfile.TarInfo(name=f"{root}/{name}")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return path


def test_sdist_offenders_is_empty_for_a_clean_sdist(tmp_path):
    # Do not hardcode the repo's real version — the root only has to match the
    # `<name>-<version>/` structure that a real sdist actually uses. .gitignore
    # is in the list because hatchling adds it unconditionally to every sdist
    # (confirmed against a real build) — it is not an offender.
    root = "clean-0.1"
    sdist = _make_sdist(
        tmp_path / f"{root}.tar.gz",
        root,
        [
            "PKG-INFO",
            "pyproject.toml",
            "README.md",
            "LICENSE",
            ".gitignore",
            "src/center_kb/__init__.py",
        ],
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


def test_sdist_offenders_flags_top_levels_a_denylist_would_have_missed(tmp_path):
    # The same hole as for the wheel (see the corresponding test above): these
    # top-level names were not in the old denylist, so they slipped through
    # silently; the allowlist catches them.
    root = "dirty2-0.1"
    sdist = _make_sdist(
        tmp_path / f"{root}.tar.gz",
        root,
        [
            "PKG-INFO",
            "src/center_kb/__init__.py",
            "AERO-KB_Architecture_v0.1.pdf",
            ".claude/settings.json",
            ".github/workflows/ci.yml",
            "scripts/check_package.py",
        ],
    )

    assert sorted(sdist_offenders(sdist)) == [
        ".claude",
        ".github",
        "AERO-KB_Architecture_v0.1.pdf",
        "scripts",
    ]
