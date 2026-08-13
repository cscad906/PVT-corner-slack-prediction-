#!/usr/bin/env bash
# si_corner_model — this is the only run script. config.yaml is the only config.
#
#   bash scripts/run.sh recon               # scout the data (do this first)
#   bash scripts/run.sh list                # see what would run (touches nothing)
#   bash scripts/run.sh all                 # build -> base -> train -> predict -> merge
#   bash scripts/run.sh build               # one stage at a time also works
#   bash scripts/run.sh base                # OLS base check (numpy only, no GPU)
#   bash scripts/run.sh train --design cpu  # one circuit / one temperature
#   bash scripts/run.sh predict --corners all
#
# To use a different python:  env PY=/path/to/python bash scripts/run.sh all
#   (the `PY=... bash ...` prefix form is bash/zsh only. It does not work in
#    csh/tcsh -- use env as above, or `setenv PY /path/to/python` first.)
# To change paths temporarily: env SI_ROOT=/real/path bash scripts/run.sh list
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-python3}"

if [[ "${1:-list}" == "recon" ]]; then
  shift
  exec bash scripts/recon.sh "$@"
fi

exec "$PY" -m si_model.run "$@"
