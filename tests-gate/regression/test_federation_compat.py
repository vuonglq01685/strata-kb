"""The NEW binary must be able to read a federation/ published by v0.9.0.

The hub is the single source of truth, and many repos publish to the same hub
from different versions. An entry published by an old version that the new one
cannot read means upgrading one repo blinds the entire hub.

WHAT RED MEANS: see the rule in test_kb_backcompat.py — either a migration, or
an xfail with a note. Do not edit the test to make it green.

FIXTURE PROVENANCE — one deviation from the original plan, stated plainly:
`center-kb 0.9.0` NEVER made it to PyPI (`pip install center-kb==0.9.0` reports
"Could not find a version that satisfies the requirement" — the list of
available versions jumps straight from 0.8.0 to 0.9.1). Cross-checking
`git diff v0.9.0..v0.9.1 --stat` shows the ONLY differences are
`.github/workflows/release.yml`, `pyproject.toml` (version bump) and `uv.lock`
— NOT a single line under `src/` changed. That is, the 0.9.0 release broke at
the publish step (the workflow), was patched, and re-released under the number
0.9.1 carrying exactly 0.9.0's federation source. This fixture is therefore
generated with `pip install "center-kb==0.9.1"` (its own venv, from the real
PyPI, never touching the source tree) — a genuinely INDEPENDENT build, truly
older than HEAD, carrying exactly v0.9.0's publish/federation code. The
directory name stays `federation-v0.9.0` because that is what it represents:
the federation format of the v0.9.0 line.
"""

from __future__ import annotations

import shutil
from pathlib import Path

FIXTURE = Path(__file__).parent.parent / "golden" / "federation-v0.9.0"


def _repo_id() -> str:
    """The fixture's published repo_id = the ONE and only subdirectory under
    FIXTURE that is not the top-level index.yaml. Do not hardcode 'golden' here
    or anywhere else — read back exactly what was published, even if the fixture
    generation script changes the repo-id later on."""
    dirs = sorted(p.name for p in FIXTURE.iterdir() if p.is_dir())
    assert len(dirs) == 1, (
        f"expected exactly ONE repo directory under {FIXTURE}, saw {dirs} — "
        "is the federation fixture broken, or was it generated wrong?"
    )
    return dirs[0]


def _hub_from_fixture(tmp_path: Path, run_git) -> Path:
    """Rebuild a git hub from the frozen federation/ tree."""
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
        "the new binary cannot read a federation published by v0.9.0\n"
        f"--- stdout ---\n{proc.stdout}"
    )
    repo_id = _repo_id()
    assert f"[{repo_id}:" in proc.stdout, (
        f"query returned results, but no citation tied to repo '{repo_id}' was "
        f"seen — it may be matching some other source, not the v0.9.0 "
        f"federation under test\n--- stdout ---\n{proc.stdout}"
    )


def test_new_binary_doctors_a_v090_federation(
    tmp_path, run_git, kb_run, strip_kind_warning, strip_legacy_config_mirror_warning
):
    """Not just "no Traceback" — that bar is far too low (see the reasoning in
    test_kb_backcompat.py::test_new_binary_runs_doctor_on_a_legacy_kb). We must
    see the exact 'kb doctor: OK' line AND not a single [warning]/[error] line,
    to prove doctor genuinely read the thing — and did not merely fail to crash
    on a federation/ it does not understand.

    The bare reader .kb below has no `kind:` recorded, so the designed
    "repo kind is not recorded" nudge is expected — see KIND_WARNING in
    tests-gate/conftest.py.

    This fixture's golden/config.yaml is also a genuinely older, real
    v0.9.1-published file (see the module docstring above) that `kb publish`
    itself would never write anymore — so the legacy-mirror nudge is
    expected too, and must actually fire: see LEGACY_CONFIG_MIRROR_WARNING in
    tests-gate/conftest.py. Every other warning still fails the gate."""
    hub = _hub_from_fixture(tmp_path, run_git)
    repo = tmp_path / "reader"
    (repo / ".kb").mkdir(parents=True)
    (repo / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")

    proc = kb_run("doctor", "--hub", str(hub), "--kb-dir", str(repo / ".kb"),
                  cwd=repo, check=False)

    assert "Traceback" not in proc.stdout + proc.stderr, (
        f"doctor blew up on a federation published by v0.9.0\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    assert "kb doctor: OK" in proc.stdout, (
        "doctor did not print 'kb doctor: OK' on a federation published by "
        "v0.9.0 — unclear whether it read it correctly or merely did not crash\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    stdout = strip_kind_warning(proc.stdout)
    stdout = strip_legacy_config_mirror_warning(stdout)
    assert "[warning]" not in stdout, (
        "doctor printed 'kb doctor: OK' yet still emitted an unexpected "
        f"[warning] on a federation published by v0.9.0\n"
        f"--- stdout ---\n{proc.stdout}"
    )
    assert "[error]" not in proc.stdout, (
        "doctor printed 'kb doctor: OK' yet still emitted an [error] on a "
        f"federation published by v0.9.0\n--- stdout ---\n{proc.stdout}"
    )
