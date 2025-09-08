#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ -f .venv/bin/activate ]; then
  source .venv/bin/activate
fi

export AP_ENGLISH_ONLY="${AP_ENGLISH_ONLY:-1}"

TS="$(date +%Y-%m-%d_%H-%M-%S)"
LOGDIR="$PWD/logs"
mkdir -p "$LOGDIR"
LOGFILE="$LOGDIR/run_${TS}.log"

# Lowered score threshold from 45 to 40
./se_bootstrap.sh --print --max 150 --days 30 --loose --min-score 40 |& tee -a "$LOGFILE"

ln -sf "$(basename "$LOGFILE")" "$LOGDIR/latest.log"
