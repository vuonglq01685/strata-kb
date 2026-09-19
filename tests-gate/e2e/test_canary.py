"""Enforces the T3/T4 tier boundary.

If this file goes red, it means the e2e suite has (directly, or indirectly via
conftest) reached into the source tree — and the whole tier has silently
degraded into an in-process test suite in disguise, losing every bit of its
value for catching packaging bugs.
"""

from __future__ import annotations

import importlib.util
import subprocess


def test_strata_kb_is_not_importable_from_the_runner():
    assert importlib.util.find_spec("strata_kb") is None, (
        "strata_kb is importable from the runner venv. The runner may ONLY have "
        "pytest + requirements-gate.txt; the artifact lives in its own venv "
        "($KB_VENV). Check: did you accidentally run pytest with the project's "
        ".venv?"
    )


def test_artifact_binary_runs(artifact):
    proc = subprocess.run(
        [str(artifact.kb), "--version"], capture_output=True, text=True, timeout=60
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip(), "kb --version printed nothing"
