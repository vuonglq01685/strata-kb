#!/usr/bin/env bash
# Chạy TOÀN BỘ cửa release trên máy dev — đúng những gì CI sẽ chạy.
# Dùng trước khi tạo tag. Không cần push, không cần đốt số version.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="${TMPDIR:-/tmp}/kb-gate"
ARTIFACT="$WORK/artifact"
RUNNER="$WORK/runner"

cd "$ROOT"
rm -rf "$WORK" dist
mkdir -p "$WORK"

echo "==> T1: unit/integration (source tree)"
python -m pytest -q

echo "==> Build wheel + sdist"
python -m build

echo "==> T2: đóng gói"
python -m venv "$ARTIFACT"
"$ARTIFACT/bin/pip" install --quiet dist/*.whl
python scripts/check_package.py --venv "$ARTIFACT" --dist dist
python -m twine check --strict dist/*
uv lock --check

# Runner venv: pytest + deps, KHÔNG có center-kb. Đây là điều kiện để canary
# (tests-gate/e2e/test_canary.py) có nghĩa.
echo "==> Dựng runner venv"
python -m venv "$RUNNER"
"$RUNNER/bin/pip" install --quiet -r requirements-gate.txt

echo "==> T3: e2e trên artifact"
KB_VENV="$ARTIFACT" "$RUNNER/bin/pytest" tests-gate/e2e -q

echo "==> T4: regression"
KB_VENV="$ARTIFACT" "$RUNNER/bin/pytest" tests-gate/regression -q

echo ""
echo "✅ Cửa xanh. An toàn để tag."
