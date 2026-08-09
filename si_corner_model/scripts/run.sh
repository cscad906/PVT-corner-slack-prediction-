#!/usr/bin/env bash
# si_corner_model — 실행 스크립트는 이거 하나뿐이다. 설정은 config.yaml 하나뿐이다.
#
#   bash scripts/run.sh recon               # 데이터 정찰 (제일 먼저)
#   bash scripts/run.sh list                # 뭐가 돌아갈지 확인 (아무것도 안 건드림)
#   bash scripts/run.sh all                 # build -> base -> train -> predict -> merge
#   bash scripts/run.sh build               # 단계별로도 가능
#   bash scripts/run.sh base                # OLS base 점검 (numpy만, GPU 불필요)
#   bash scripts/run.sh train --design cpu  # 특정 회로/온도만
#   bash scripts/run.sh predict --corners all
#
# 다른 파이썬을 쓰려면:  PY=/path/to/python bash scripts/run.sh all
# 경로만 임시로 바꾸려면: SI_ROOT=/real/path bash scripts/run.sh list
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-python3}"

if [[ "${1:-list}" == "recon" ]]; then
  shift
  exec bash scripts/recon.sh "$@"
fi

exec "$PY" -m si_model.run "$@"
