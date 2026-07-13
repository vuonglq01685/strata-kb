#!/usr/bin/env bash
# Chạy TOÀN BỘ cửa release trên máy dev — đúng những gì CI sẽ chạy.
# Dùng trước khi tạo tag. Không cần push, không cần đốt số version.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="${TMPDIR:-/tmp}/kb-gate"
ARTIFACT="$WORK/artifact"
RUNNER="$WORK/runner"

# Chọn interpreter Python MỘT LẦN, dùng xuyên suốt script — máy Homebrew
# "sạch" (chưa activate venv nào) thường KHÔNG có `python` trên PATH, chỉ có
# `python3`. Cần interpreter có sẵn module `build` (chạy `python -m build`)
# và tạo được venv. .venv/bin/python của chính repo là lựa chọn tự nhiên vì
# đã có sẵn build/twine/pytest từ `pip install -e '.[dev]'`; nếu không có thì
# fallback python3 rồi python. Không tìm thấy gì → dừng ngay với hướng dẫn rõ
# ràng, thay vì để lỗi mù mờ ba bước sau.
if [ -x "$ROOT/.venv/bin/python" ]; then
    PY="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
    PY="$(command -v python)"
else
    echo "❌ Không tìm thấy interpreter Python nào (đã thử .venv/bin/python, python3, python)." >&2
    echo "   → Chạy: python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2
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

echo "==> T2: đóng gói"
"$PY" -m venv "$ARTIFACT"
"$ARTIFACT/bin/pip" install --quiet dist/*.whl
"$PY" scripts/check_package.py --venv "$ARTIFACT" --dist dist
"$PY" -m twine check --strict dist/*
uv lock --check

# Runner venv: pytest + deps, KHÔNG có center-kb. Đây là điều kiện để canary
# (tests-gate/e2e/test_canary.py) có nghĩa.
echo "==> Dựng runner venv"
"$PY" -m venv "$RUNNER"
"$RUNNER/bin/pip" install --quiet -r requirements-gate.txt

echo "==> T3: e2e trên artifact"
KB_VENV="$ARTIFACT" "$RUNNER/bin/pytest" tests-gate/e2e -q

echo "==> T4: regression"
KB_VENV="$ARTIFACT" "$RUNNER/bin/pytest" tests-gate/regression -q

echo ""
echo "✅ Cửa xanh. An toàn để tag."
