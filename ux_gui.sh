#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

VENV_DIR="${VENV_DIR:-./.venv}"
PY="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

# Create venv if missing
if [ ! -x "$PY" ]; then
  python3 -m venv "$VENV_DIR"
fi

# Ensure streamlit is in the venv (no system pip)
if ! "$PY" -c "import streamlit" >/dev/null 2>&1; then
  "$PIP" install --quiet --upgrade pip wheel
  "$PIP" install --quiet streamlit
fi

exec "$PY" -m streamlit run ./streamlit_app.py --server.port 8501 --server.headless true
