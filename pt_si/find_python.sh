#!/bin/sh
# 이 패키지를 돌릴 수 있는 python 인터프리터를 찾는다.
#
#   sh find_python.sh
#
# 시스템 python 이 2.7 이어도 상관없다. PrimeTime 설치본이 Python 3.6 을 포함하므로
# (etc/Python/bin/python3), PT 가 돌아가는 곳이면 사실상 항상 하나는 나온다.
# networkx 도 그 안에 들어있어 pt_annotation 이 별도 설치 없이 동작한다.
#
# 출력: 사용 가능한 후보 목록 + 권장 1개. 그대로 복사해 쓰면 된다.

echo "=== python 후보 탐색 ==="
echo ""

CANDIDATES=""

# 1) PrimeTime 번들 (가장 확실한 후보)
PTBIN=`command -v pt_shell 2>/dev/null`
if [ -n "$PTBIN" ]; then
    PTROOT=`dirname "$PTBIN"`/..
    for p in "$PTROOT/etc/Python/bin/python3" "$PTROOT/etc/cltPython/bin/python3"; do
        [ -x "$p" ] && CANDIDATES="$CANDIDATES $p"
    done
    echo "PrimeTime  : $PTBIN"
else
    echo "PrimeTime  : PATH 에 없음 (PT_SOURCE 를 먼저 source 하면 번들 python 도 같이 잡힌다)"
fi

# 2) 다른 Synopsys 툴 설치본에도 같은 구조로 들어있다 (ICC2, FusionCompiler, DC, StarRC...).
#    설치 경로는 <root>/<tool>/<version>/etc/Python 인 경우가 흔하므로 깊이 1~2 를 모두 훑는다.
for root in /usr/synopsys /tools/synopsys /opt/synopsys /usr/local/synopsys \
            /eda/synopsys /apps/synopsys "$SYNOPSYS" "$SNPS_ROOT" "$STARRC_ROOT" "$SYNOPSYS_ROOT"; do
    [ -d "$root" ] || continue
    for d in "$root" "$root"/* "$root"/*/*; do
        [ -d "$d" ] || continue
        for p in "$d/etc/Python/bin/python3" "$d/etc/cltPython/bin/python3"; do
            [ -x "$p" ] && CANDIDATES="$CANDIDATES $p"
        done
    done
done

# 3) 시스템/모듈 경로
for p in python3.12 python3.11 python3.10 python3.9 python3.8 python3.7 python3.6 python3; do
    q=`command -v "$p" 2>/dev/null`
    [ -n "$q" ] && CANDIDATES="$CANDIDATES $q"
done

if [ -z "$CANDIDATES" ]; then
    echo ""
    echo "!! python3 을 하나도 못 찾았다."
    echo "   PT_SOURCE 를 source 한 뒤 다시 실행하거나, CAD 팀에 아래를 문의:"
    echo "     - PrimeTime 설치 루트의 etc/Python/bin/python3"
    echo "     - 또는 module load python/3.x"
    exit 1
fi

echo ""
printf "%-58s %-9s %-10s %s\n" "PATH" "VERSION" "networkx" "판정"
printf "%-58s %-9s %-10s %s\n" "----" "-------" "--------" "----"

BEST=""
BEST_OK=0
SEEN=""
for p in $CANDIDATES; do
    real=`readlink -f "$p" 2>/dev/null || echo "$p"`
    case " $SEEN " in *" $real "*) continue;; esac
    SEEN="$SEEN $real"

    ver=`"$p" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])' 2>/dev/null`
    [ -z "$ver" ] && continue
    major=`echo "$ver" | cut -d. -f1`
    minor=`echo "$ver" | cut -d. -f2`
    [ "$major" -lt 3 ] && verdict="X 3.x 아님" && nx="-" && {
        printf "%-58s %-9s %-10s %s\n" "$p" "$ver" "$nx" "$verdict"; continue; }

    if "$p" -c 'import networkx' >/dev/null 2>&1; then nx="있음"; else nx="없음"; fi

    # 3.6 이상이면 이 패키지가 동작한다(코드가 3.6 호환으로 맞춰져 있음).
    if [ "$minor" -ge 6 ]; then
        if [ "$nx" = "있음" ]; then
            verdict="OK  (annotation 포함 전부)"
            score=2
        else
            verdict="OK  (단, res.py 계열은 networkx 필요)"
            score=1
        fi
    else
        verdict="X  3.6 미만"
        score=0
    fi

    printf "%-58s %-9s %-10s %s\n" "$p" "$ver" "$nx" "$verdict"

    if [ "$score" -gt "$BEST_OK" ]; then
        BEST_OK=$score
        BEST="$p"
    fi
done

echo ""
if [ -z "$BEST" ] || [ "$BEST_OK" -eq 0 ]; then
    echo "!! 쓸 수 있는 python 이 없다. CAD 팀 문의 필요."
    exit 1
fi

echo "=== 권장 ==="
echo "  $BEST"
echo ""
echo "  bash:  export PYTHON=$BEST"
echo "  csh :  setenv PYTHON $BEST"
echo ""
echo "  이후 모든 스크립트를 \$PYTHON 으로 실행한다:"
echo "    \$PYTHON run_sweep.py --help"
echo ""
if [ "$BEST_OK" -eq 1 ]; then
    echo "  주의: networkx 가 없어 pt_annotation(res.py)이 import 단계에서 실패한다."
    echo "        설치: $BEST -m pip install --user networkx"
    echo "        (외부망이 막혀 있으면 networkx wheel 을 미리 받아 오거나,"
    echo "         networkx 가 들어있는 다른 후보를 위 표에서 고른다)"
fi
