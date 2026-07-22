#!/usr/bin/env bash
# SI aux-loss weight sweep for a slack config: lambda in {0, 0.1, 1, 10}.
#   PY=/path/to/python bash scripts/sweep.sh configs/beol14/setup_m40.yaml
set -euo pipefail
CFG="${1:?usage: sweep.sh <slack-config.yaml>}"
PY="${PY:-python}"
cd "$(dirname "$0")/.."
name="$(basename "${CFG%.yaml}")"
for lam in 0 0.1 1 10; do
  echo "=== lambda_si=$lam ==="
  "$PY" -m si_model.tasks.slack.train --config "$CFG" \
    --lambda-si "$lam" --out-dir "runs/sweep/${name}/lam_${lam}"
done
