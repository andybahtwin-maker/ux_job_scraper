#!/usr/bin/env bash
set -euo pipefail

# Always work from the script's directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Ensure python venv tools exist (Ubuntu)
if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERR] python3 not found"; exit 1
fi
if ! python3 -c "import venv" 2>/dev/null; then
  echo "[INFO] installing python3-venv (sudo required)..."
  sudo apt-get update -y && sudo apt-get install -y python3-venv
fi

# Create venv if missing
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

# Activate
source .venv/bin/activate

# Upgrade pip & install deps
python -m pip install --upgrade pip wheel setuptools
python -m pip install -r requirements.txt

echo "[OK] Deps installed."

# Optional .env template (only writes if missing)
if [ ! -f ".env" ]; then
  cat > .env <<'ENV'
# --- SMTP/Gmail (edit me) ---
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_SSL=0
SMTP_USER=your.email@gmail.com
SMTP_PASS=REPLACE_WITH_GMAIL_APP_PASSWORD
EMAIL_TO=your.email@gmail.com
EMAIL_FROM=your.email@gmail.com
REPLY_TO=your.email@gmail.com

# --- Email batching ---
ENABLE_EMAIL=0
EMAIL_BATCH_SIZE=100
EMAIL_BATCH_DELAY_SECONDS=2

# --- Output & subject cosmetics ---
EMAIL_SUBJECT_PREFIX=[ApplyPilot]
EMAIL_LABEL=SE-Digest

# --- Data paths ---
JOBS_CSV_PATH=./data/filtered_jobs.csv
RAW_JOBS_CSV=./data/jobs_all.json
MAX_AGE_DAYS=30
ENV
  echo "[OK] Wrote .env (fill in SMTP creds if emailing)."
fi

# Pass CLI args to scraper
echo "[INFO] Running scraper with args: $*"
python applypilot_ux.py "$@"
