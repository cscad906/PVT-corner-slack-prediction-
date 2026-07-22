#!/usr/bin/env bash
# Train one model from its config. Dispatches slew vs slack by config name.
# Extra args pass through, e.g. --epochs is not a flag but --lambda-si / --out-dir are.
#   PY=/path/to/python bash scripts/train.sh configs/beol14/setup_m40.yaml [extra args]
set -euo pipefail
CFG="${1:?usage: train.sh <config.yaml> [extra args]}"; shift || true
PY="${PY:-python}"
cd "$(dirname "$0")/.."
if [[ "$(basename "$CFG")" == *slew* ]]; then
  "$PY" -m si_model.tasks.slew.train_slew --config "$CFG" "$@"
else
  "$PY" -m si_model.tasks.slack.train --config "$CFG" "$@"
fi
