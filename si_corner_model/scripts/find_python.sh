#!/bin/sh
# 이 패키지를 돌릴 수 있는 python 을 찾는다.  (sh 로 도는 POSIX 스크립트 — 2.7 환경에서도 안전)
#
#   sh scripts/find_python.sh
#
# `python` 이 2.7 이어도 상관없다. RHEL/CentOS 계열은 `python3` 이나
# /usr/libexec/platform-python 으로 3.6 이 거의 항상 같이 깔려 있고, EDA 툴 설치본도
# 각자 python3 을 들고 있다. 이 스크립트가 그걸 전부 훑어서 "이걸 쓰면 된다" 를 찍어준다.
#
# 필요 조건
#   필수 : python >= 3.6  +  numpy  +  pyyaml     -> recon/check/list/build/base 전부 가능
#   추가 : torch                                   -> train 까지 가능
set -u

MIN_MAJOR=3
MIN_MINOR=6

echo "=================================================================="
echo " si_corner_model - python 찾기"
echo "=================================================================="
echo ""

# ---- 후보 모으기 -------------------------------------------------------------
CANDS=""
add() { [ -n "$1" ] && CANDS="$CANDS $1"; }

# 1) PATH 에 있는 흔한 이름들
for n in python3 python3.13 python3.12 python3.11 python3.10 python3.9 python3.8 python3.7 python3.6 python; do
    p=`command -v $n 2>/dev/null`
    add "$p"
done

# 2) RHEL/CentOS 기본 위치 (python 이 2.7 이어도 여기 3.6 이 있다)
for p in /usr/libexec/platform-python /usr/bin/python3 /usr/local/bin/python3; do
    [ -x "$p" ] && add "$p"
done

# 3) conda / venv 흔적
for base in "$HOME/miniconda3" "$HOME/anaconda3" "$HOME/miniforge3" /opt/conda; do
    [ -x "$base/bin/python" ] && add "$base/bin/python"
    if [ -d "$base/envs" ]; then
        for e in "$base"/envs/*/bin/python; do [ -x "$e" ] && add "$e"; done
    fi
done

# 4) EDA 툴 번들 (Synopsys / Cadence / Mentor 는 자체 python3 을 들고 다닌다)
PTBIN=`command -v pt_shell 2>/dev/null`
if [ -n "$PTBIN" ]; then
    PTROOT=`dirname "$PTBIN"`/..
    for p in "$PTROOT"/etc/Python/bin/python3 "$PTROOT"/linux64/Python/bin/python3; do
        [ -x "$p" ] && add "$p"
    done
fi
for root in /usr/synopsys /opt/synopsys /tools/synopsys /usr/cadence /opt/cadence; do
    [ -d "$root" ] || continue
    for p in `find "$root" -maxdepth 6 -name python3 -type f -perm -u+x 2>/dev/null | head -20`; do
        add "$p"
    done
done

# ---- 검사 -------------------------------------------------------------------
echo "후보를 하나씩 검사한다 (>= $MIN_MAJOR.$MIN_MINOR, numpy, pyyaml, torch)"
echo ""
printf "  %-46s %-10s %-8s %-8s %-8s\n" "인터프리터" "버전" "numpy" "pyyaml" "torch"
printf "  %-46s %-10s %-8s %-8s %-8s\n" "----------------------------------------------" "--------" "------" "------" "------"

BEST_FULL=""     # 학습까지 가능
BEST_CORE=""     # build/base 까지 가능
SEEN=""
for p in $CANDS; do
    rp=`readlink -f "$p" 2>/dev/null || echo "$p"`
    case " $SEEN " in *" $rp "*) continue ;; esac
    SEEN="$SEEN $rp"

    ver=`"$p" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])' 2>/dev/null` || continue
    ok=`"$p" -c "import sys;print(1 if sys.version_info[:2]>=($MIN_MAJOR,$MIN_MINOR) else 0)" 2>/dev/null`
    [ "$ok" = "1" ] || { printf "  %-46s %-10s %s\n" "$p" "$ver" "(너무 낮음)"; continue; }

    np=`"$p" -c 'import numpy;print(numpy.__version__)' 2>/dev/null` || np="-"
    yl=`"$p" -c 'import yaml;print(yaml.__version__)' 2>/dev/null` || yl="-"
    tc=`"$p" -c 'import torch;print(torch.__version__)' 2>/dev/null` || tc="-"
    dc=`"$p" -c 'import dataclasses' 2>/dev/null && echo ok || echo "-"`

    printf "  %-46s %-10s %-8s %-8s %-8s%s\n" "$p" "$ver" "$np" "$yl" "$tc" \
        "`[ "$dc" = "-" ] && echo '  (dataclasses 없음)'`"

    [ "$np" = "-" ] && continue
    [ "$yl" = "-" ] && continue
    [ "$dc" = "-" ] && continue
    [ -z "$BEST_CORE" ] && BEST_CORE="$p"
    if [ "$tc" != "-" ] && [ -z "$BEST_FULL" ]; then BEST_FULL="$p"; fi
done

echo ""
echo "=================================================================="
if [ -n "$BEST_FULL" ]; then
    echo " [ 전부 가능 ] 학습까지 이걸로 하면 된다:"
    echo ""
    echo "     PY=$BEST_FULL bash scripts/run.sh all"
    echo ""
    echo " 매번 치기 싫으면:  export PY=$BEST_FULL"
elif [ -n "$BEST_CORE" ]; then
    echo " [ 일부 가능 ] torch 가 없다. 데이터 확인까지는 이걸로 다 된다:"
    echo ""
    echo "     PY=$BEST_CORE bash scripts/run.sh recon"
    echo "     PY=$BEST_CORE bash scripts/run.sh list"
    echo "     PY=$BEST_CORE bash scripts/run.sh build"
    echo "     PY=$BEST_CORE bash scripts/run.sh base     # OLS base 오차 확인"
    echo ""
    echo " train(학습) 만 torch 가 필요하다:"
    echo "     $BEST_CORE -m pip install --user torch     # 인터넷 되면"
    echo "     (3.6 이면 torch==1.10.2 가 마지막 지원 버전)"
    echo "     인터넷이 막혔으면 docs/START.md 'python 이 아예 없을 때' 참고"
else
    echo " [ 없음 ] 쓸만한 python 을 못 찾았다."
    echo ""
    echo " 1) 먼저 아래를 직접 쳐본다 (스크립트가 못 본 곳에 있을 수 있다):"
    echo "      python3 --version ; ls /usr/bin/python3*"
    echo "      module avail 2>&1 | head -30        # module 시스템이 있으면"
    echo "      ls ~/miniconda3 ~/anaconda3 2>/dev/null"
    echo ""
    echo " 2) 그래도 없으면 python 을 들고 와야 한다 -> docs/START.md STEP 0"
    echo "      (miniconda 오프라인 설치본 + 미리 받아둔 wheel. root 권한 불필요)"
fi
echo "=================================================================="
