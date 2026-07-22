#!/usr/bin/env bash
# Build the training cache for one config. Dispatches to the slew builder when
# the config name contains "slew", else the slack (annotated+crosstalk) builder.
#   PY=/path/to/python bash scripts/build.sh configs/beol14/setup_m40.yaml
set -euo pipefail
CFG="${1:?usage: build.sh <config.yaml>}"
PY="${PY:-python}"
cd "$(dirname "$0")/.."
if [[ "$(basename "$CFG")" == *slew* ]]; then
  "$PY" -m si_model.tasks.slew.build_slew --config "$CFG"
else
  "$PY" -m si_model.parsing.build_dataset --config "$CFG"
fi
