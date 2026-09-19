from __future__ import annotations

import io
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import venv as venv_module
import zipfile
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from check_package import (
    installed_version,
    pyproject_version,
    sdist_offenders,
    tag_matches,
    venv_bin,
    wheel_offenders,
    wheel_required_missing,
)


def test_pyproject_version_reads_the_declared_version(tmp_path):
    # Build a fake pyproject: this tests the parser, it does NOT pin the repo's
    # real version — hardcoding a number here would turn every version bump
    # into a red test.
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "strata-kb"\nversion = "1.2.3"\n', encoding="utf-8"
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
        ["strata_kb/__init__.py", "strata_kb-0.1.dist-info/METADATA"],
    )

    assert wheel_offenders(wheel) == []


def test_wheel_offenders_allows_any_dist_info_version_suffix(tmp_path):
    # The dist-info name changes with the version on every build (e.g. 0.9.1,
    # 1.0.0-rc1...) — the allowlist matches on the ".dist-info" suffix and does
    # not hardcode a specific version, so any version must pass clean.
    wheel = _make_wheel(
        tmp_path / "clean-9.9.9-py3-none-any.whl",
        ["strata_kb/__init__.py", "strata_kb-9.9.9.dist-info/METADATA"],
    )

    assert wheel_offenders(wheel) == []


def test_wheel_offenders_flags_tests_and_kb_and_sources(tmp_path):
    wheel = _make_wheel(
        tmp_path / "dirty-0.1-py3-none-any.whl",
        [
            "strata_kb/__init__.py",
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
            "strata_kb/__init__.py",
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


def test_wheel_required_missing_is_empty_when_static_assets_present(tmp_path):
    wheel = _make_wheel(
        tmp_path / "clean-0.1-py3-none-any.whl",
        [
            "strata_kb/__init__.py",
            "strata_kb/templates/web/static/style.css",
            "strata_kb/templates/web/static/app.js",
            "strata_kb/templates/web/static/fonts/IBMPlexSans-Regular.woff2",
            "strata_kb-0.1.dist-info/METADATA",
        ],
    )

    assert wheel_required_missing(wheel) == []


def test_wheel_required_missing_flags_absent_static_assets(tmp_path):
    # A packaging config change (e.g. tightening `only-include`) could drop
    # these files silently — wheel_offenders alone would stay green, since a
    # missing file isn't an extra top-level entry.
    wheel = _make_wheel(
        tmp_path / "dirty-0.1-py3-none-any.whl",
        ["strata_kb/__init__.py", "strata_kb-0.1.dist-info/METADATA"],
    )

    missing = wheel_required_missing(wheel)

    assert "strata_kb/templates/web/static/style.css" in missing
    assert "strata_kb/templates/web/static/app.js" in missing
    assert any("fonts" in m and m.endswith(".woff2") for m in missing)


def test_wheel_required_missing_accepts_any_woff2_font_name(tmp_path):
    # Only the *presence* of a font is required, not a specific filename —
    # the font set can grow/shrink without this check needing an update.
    wheel = _make_wheel(
        tmp_path / "clean2-0.1-py3-none-any.whl",
        [
            "strata_kb/__init__.py",
            "strata_kb/templates/web/static/style.css",
            "strata_kb/templates/web/static/app.js",
            "strata_kb/templates/web/static/fonts/SomeOtherFont-Bold.woff2",
            "strata_kb-0.1.dist-info/METADATA",
        ],
    )

    assert wheel_required_missing(wheel) == []


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
            "src/strata_kb/__init__.py",
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
            "src/strata_kb/__init__.py",
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
            "src/strata_kb/__init__.py",
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


def test_venv_bin_picks_scripts_on_windows_layout(tmp_path):
    venv = tmp_path / "v"
    (venv / "Scripts").mkdir(parents=True)

    assert venv_bin(venv).name == "Scripts"


def test_venv_bin_picks_bin_on_posix_layout(tmp_path):
    venv = tmp_path / "v"
    (venv / "bin").mkdir(parents=True)

    assert venv_bin(venv).name == "bin"


def test_installed_version_reads_the_venv_entry_point(tmp_path):
    """The one helper venv_bin exists for, and the only one still untested.

    Does not rely on venv_bin() to build the fixture itself: on a fresh
    tmp_path neither "Scripts" nor "bin" exists yet, so venv_bin() would
    return "bin" even on Windows (it only picks "Scripts" when that dir
    already is_dir()). Windows builds a real venv via the stdlib (which
    creates its own "Scripts"); POSIX builds "bin" directly.
    """
    venv = tmp_path / "v"
    if os.name == "nt":
        # installed_version runs the venv_bin(venv)/"kb" path with no
        # extension. Windows' CreateProcess auto-appends only ".exe" to an
        # extensionless command -- never ".bat"/".cmd" -- so a .bat stub is
        # silently unreachable here (verified empirically: subprocess.run on
        # an extensionless path finds a sibling "name.exe" but raises
        # FileNotFoundError for a sibling "name.bat"). A copied python.exe
        # is not a drop-in stand-in either: it needs its OWN venv's
        # pyvenv.cfg beside it to locate its home, and the BASE install's
        # python.exe (as opposed to a venv's Scripts/python.exe, a small
        # launcher) crashes outright when copied away from its DLLs. Build
        # a real venv with the stdlib and reuse ITS OWN launcher as "kb.exe"
        # -- ~0.1s, and no fresh .exe bytes are hand-fabricated for a
        # scanner to be suspicious of.
        venv_module.create(venv, with_pip=False)
        bindir = venv / "Scripts"
        shutil.copy(bindir / "python.exe", bindir / "kb.exe")
        expected = subprocess.run(
            [sys.executable, "--version"], capture_output=True, text=True, check=True
        ).stdout.strip()
    else:
        bindir = venv / "bin"
        bindir.mkdir(parents=True)
        stub = bindir / "kb"
        stub.write_text('#!/bin/sh\necho "kb, version 9.9.9"\n', encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        expected = "kb, version 9.9.9"

    # installed_version returns the WHOLE `kb --version` line
    # (proc.stdout.strip()), not a bare version -- match that shape.
    assert installed_version(venv) == expected
