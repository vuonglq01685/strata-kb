#!/usr/bin/env bash
# Run the release gate on a dev machine, on ONE interpreter and ONE OS.
# CI (.github/workflows/_gate.yml) additionally runs the matrix:
# ubuntu x {3.11,3.12,3.13} plus windows-latest. Green here is necessary,
# not sufficient — it is what catches a red PR before you push, not a
# substitute for the matrix.
# Usage: scripts/gate.sh [--tag vX.Y.Z]
set -euo pipefail

TAG=""
if [ "${1:-}" = "--tag" ]; then
    TAG="${2:?--tag needs a version, e.g. --tag v1.2.3}"
elif [ $# -gt 0 ]; then
    echo "usage: scripts/gate.sh [--tag vX.Y.Z]" >&2
    exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="${TMPDIR:-/tmp}/kb-gate"
ARTIFACT="$WORK/artifact"
SDIST_VENV="$WORK/sdist"
RUNNER="$WORK/runner"

# A venv's executable directory: Scripts on Windows (Git Bash), bin elsewhere.
venv_bin() { if [ -d "$1/Scripts" ]; then echo "$1/Scripts"; else echo "$1/bin"; fi; }

if [ -x "$ROOT/.venv/bin/python" ]; then
    PY="$ROOT/.venv/bin/python"
elif [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
    PY="$ROOT/.venv/Scripts/python.exe"
elif command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
    PY="$(command -v python)"
else
    echo "No Python interpreter found (tried .venv, python3, python)." >&2
    echo "  -> Run: python3 -m venv .venv && $(venv_bin "$ROOT/.venv")/pip install -e '.[dev]'" >&2
    exit 1
fi
echo "==> Interpreter: $PY ($("$PY" --version 2>&1))"

cd "$ROOT"
rm -rf "$WORK" dist
mkdir -p "$WORK"

echo "==> T0: lint"
"$PY" -m ruff check .

echo "==> T1: unit/integration (source tree)"
"$PY" -m pytest -q

echo "==> Build wheel + sdist"
"$PY" -m build

echo "==> T2: packaging"
"$PY" -m venv "$ARTIFACT"
"$(venv_bin "$ARTIFACT")/pip" install --quiet dist/*.whl
if [ -n "$TAG" ]; then
    "$PY" scripts/check_package.py --venv "$ARTIFACT" --dist dist --tag "$TAG"
else
    "$PY" scripts/check_package.py --venv "$ARTIFACT" --dist dist
fi
"$PY" -m twine check --strict dist/*
uv lock --check

echo "==> T2b: sdist install smoke"
"$PY" -m venv "$SDIST_VENV"
"$(venv_bin "$SDIST_VENV")/pip" install --quiet dist/*.tar.gz
"$(venv_bin "$SDIST_VENV")/kb" --version
"$(venv_bin "$SDIST_VENV")/python" -c \
    "from importlib import resources; \
     print(len(resources.files('center_kb').joinpath('templates/init/config-hub.yaml').read_text()))"

echo "==> Build the runner venv"
"$PY" -m venv "$RUNNER"
"$(venv_bin "$RUNNER")/pip" install --quiet -r requirements-gate.txt

echo "==> T3: e2e on the artifact"
KB_VENV="$ARTIFACT" "$(venv_bin "$RUNNER")/pytest" tests-gate/e2e -q

echo "==> T4: regression"
KB_VENV="$ARTIFACT" "$(venv_bin "$RUNNER")/pytest" tests-gate/regression -q

echo ""
echo "Gate green on this interpreter/OS. CI still runs the matrix."
