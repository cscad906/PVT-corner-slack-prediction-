#!/usr/bin/env bash
# 도착해서 제일 먼저 돌리는 정찰. config.yaml 의 root 를 그대로 쓴다.
#
#   bash scripts/run.sh recon                 # config.yaml 의 root 사용
#   bash scripts/run.sh recon /real/root      # root 만 임시로 지정
#
# 결과는 recon_out.txt 에 저장된다. 이 파일 내용을 보고 config.yaml 의
#   root / designs / temps.levels / files.annotated_regex 를 확정하면 된다.
set -uo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-python3}"

ROOT="${1:-}"
if [[ -z "$ROOT" ]]; then
  ROOT="$("$PY" - <<'EOF' 2>/dev/null || true
import os, sys
sys.path.insert(0, ".")
from si_model.run import load_project, DEFAULT_PROJECT
print(load_project(DEFAULT_PROJECT)["root"])
EOF
)"
fi
[[ -z "$ROOT" ]] && ROOT="$(cd .. && pwd)"
OUT="recon_out.txt"

{
echo "########## si_corner_model recon ##########"
echo "date : $(date)"
echo "host : $(hostname)"
echo "root : $ROOT       <- config.yaml 의 root"
echo "repo : $(pwd)"
echo

echo "===== [1] root 바로 아래 = 회로 폴더 목록 (config 의 designs) ====="
ls -la "$ROOT" 2>&1 | head -60
echo

DESIGNS="$(find "$ROOT" -maxdepth 1 -mindepth 1 -type d -not -name '.*' \
           -not -name 'si_corner_model' -printf '%f\n' 2>/dev/null | sort)"
echo "--- 회로 후보 ---"; echo "$DESIGNS"
echo

for D in $DESIGNS; do
  P="$ROOT/$D"
  echo "=============================================================="
  echo "===== 회로: $D"
  echo "=============================================================="
  echo "--- 구조 (깊이 2) ---"
  find "$P" -maxdepth 2 -type d 2>/dev/null | head -25
  echo "--- 확장자별 개수 ---"
  find "$P" -maxdepth 3 -type f 2>/dev/null | sed 's/.*\.//' | sort | uniq -c | sort -rn | head -10
  echo "--- 파일명 샘플 (files.annotated_regex 를 여기 맞춘다) ---"
  find "$P" -maxdepth 3 -type f 2>/dev/null | xargs -n1 basename 2>/dev/null | sort | head -25
  echo "--- 코너 토큰 분포 (전압/온도/BEOL 실제 표기 = temps.levels 확정용) ---"
  find "$P" -maxdepth 3 -type f 2>/dev/null | xargs -n1 basename 2>/dev/null \
    | grep -Eio '(sspg|ffpg|tt)|0p[0-9]+|m?[0-9]+c|rcmax|rcmin|cmax|cmin|rcworst|cworst|cbest' \
    | sort | uniq -c | sort -rn | head -25
  echo
done

SAMPLE="$(find "$ROOT" -maxdepth 4 -type f \( -name '*.rpt' -o -name '*report*' \) 2>/dev/null | head -1)"
echo "=============================================================="
echo "===== [2] ★ 리포트 본문 = 파서를 고칠지 결정하는 부분 ★"
echo "=============================================================="
echo "sample : $SAMPLE"
if [[ -n "$SAMPLE" ]]; then
  ls -l "$SAMPLE"; wc -l "$SAMPLE"; echo
  echo "--- 앞 120줄 ---"; head -120 "$SAMPLE"; echo
  echo "--- 키워드 개수 (FIXED_PATH 유무 / SSTA 여부 판정) ---"
  for k in 'FIXED_PATH' 'Startpoint' 'Endpoint' 'data arrival time' 'data required time' \
           'slack' 'library setup time' 'library hold time' '(net)' \
           'sigma' 'mean' 'variation' 'statistical' 'crosstalk' 'delta'; do
    printf '  %-22s %s\n' "$k" "$(grep -c -i -- "$k" "$SAMPLE" 2>/dev/null)"
  done
  echo
  echo "--- ★ 코너 간 경로 집합이 같은지 (모델의 대전제) ---"
  SDIR="$(dirname "$SAMPLE")"
  for f in $(ls "$SDIR" | head -4); do
    printf '  %-50s Startpoint=%s\n' "$f" "$(grep -c 'Startpoint' "$SDIR/$f" 2>/dev/null)"
  done
  echo "  (개수가 코너마다 다르면 = 코너별 worst path -> 고정경로 재-annotate 필요)"
else
  echo "리포트 후보를 못 찾음 -> [1] 출력 보고 root 를 다시 지정할 것"
fi
echo

echo "===== [3] SI / 크로스토크 위치 (files.crosstalk_subdir 확정용) ====="
find "$ROOT" -maxdepth 4 \( -iname '*xtalk*' -o -iname '*crosstalk*' -o -iname '*noise*' \) 2>/dev/null | head -25
[[ -n "$SAMPLE" ]] && echo "--- 리포트 안에 크로스토크 열이 섞여있나 ---" && \
  grep -i -m 6 -E 'crosstalk|delta_delay|si delta|bump|aggressor' "$SAMPLE" 2>/dev/null
echo

echo "===== [4] 파이썬 환경 ====="
for P in python3 python /usr/bin/python3.11 /usr/bin/python3.9; do
  command -v "$P" >/dev/null 2>&1 && echo "$P -> $("$P" -c 'import sys;print(sys.version.split()[0])' 2>&1) \
numpy=$("$P" -c 'import numpy;print(numpy.__version__)' 2>&1|tail -1) \
torch=$("$P" -c 'import torch;print(torch.__version__)' 2>&1|tail -1)"
done
echo "########## end ##########"
} 2>&1 | tee "$OUT"

echo
echo ">>> 저장됨: $(pwd)/$OUT"
