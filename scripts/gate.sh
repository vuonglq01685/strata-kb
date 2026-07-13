#!/usr/bin/env bash
# Run the ENTIRE release gate on a dev machine — exactly what CI will run.
# Use it before creating a tag. No push needed, no version numbers burned.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="${TMPDIR:-/tmp}/kb-gate"
ARTIFACT="$WORK/artifact"
RUNNER="$WORK/runner"

# Pick the Python interpreter ONCE and use it throughout the script — a "clean"
# Homebrew machine (with no venv activated) usually does NOT have `python` on
# PATH, only `python3`. We need an interpreter that already has the `build`
# module (to run `python -m build`) and can create venvs. The repo's own
# .venv/bin/python is the natural choice because it already has build/twine/pytest
# from `pip install -e '.[dev]'`; if that is missing, fall back to python3, then
# python. Nothing found → stop right away with clear instructions, instead of
# letting an obscure error surface three steps later.
if [ -x "$ROOT/.venv/bin/python" ]; then
    PY="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
    PY="$(command -v python)"
else
    echo "❌ No Python interpreter found (tried .venv/bin/python, python3, python)." >&2
    echo "   → Run: python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2
    exit 1
fi
echo "==> Interpreter: $PY ($("$PY" --version 2>&1))"

cd "$ROOT"
rm -rf "$WORK" dist
mkdir -p "$WORK"

echo "==> T1: unit/integration (source tree)"
"$PY" -m pytest -q

echo "==> Build wheel + sdist"
"$PY" -m build

echo "==> T2: packaging"
"$PY" -m venv "$ARTIFACT"
"$ARTIFACT/bin/pip" install --quiet dist/*.whl
"$PY" scripts/check_package.py --venv "$ARTIFACT" --dist dist
"$PY" -m twine check --strict dist/*
uv lock --check

# Runner venv: pytest + deps, with NO center-kb. This is the precondition that
# makes the canary (tests-gate/e2e/test_canary.py) meaningful.
echo "==> Build the runner venv"
"$PY" -m venv "$RUNNER"
"$RUNNER/bin/pip" install --quiet -r requirements-gate.txt

echo "==> T3: e2e on the artifact"
KB_VENV="$ARTIFACT" "$RUNNER/bin/pytest" tests-gate/e2e -q

echo "==> T4: regression"
KB_VENV="$ARTIFACT" "$RUNNER/bin/pytest" tests-gate/regression -q

echo ""
echo "✅ Gate green. Safe to tag."
