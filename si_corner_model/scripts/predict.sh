#!/usr/bin/env bash
# Dump per-(path, corner) predictions from a trained checkpoint (no training).
#   PY=/path/to/python bash scripts/predict.sh <config.yaml> [--corners hidden|seen|all] [--ckpt path] [--out-dir DIR]
set -euo pipefail
CFG="${1:?usage: predict.sh <config.yaml> [extra args]}"; shift || true
PY="${PY:-python}"
cd "$(dirname "$0")/.."
if [[ "$(basename "$CFG")" == *slew* ]]; then
  "$PY" -m si_model.tasks.slew.predict --config "$CFG" "$@"
else
  "$PY" -m si_model.tasks.slack.predict --config "$CFG" "$@"
fi
