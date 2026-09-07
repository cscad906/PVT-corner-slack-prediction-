#!/bin/sh
# 받은 것 검사부터 넘길 형태로 모으기까지 한 줄에 끝낸다.
#
#   sh run_all.sh <코너들이_든_폴더> [<모을_폴더>] [setup|hold]
#
#   sh run_all.sh round2                     -> deliver/setup/
#   sh run_all.sh round2 deliver             -> deliver/setup/
#   sh run_all.sh round2_hold deliver hold   -> deliver/hold/
#
# 하는 일 세 가지
#   8_check_xtalk.py   PT 가 준 xtalk/ 가 온전한지
#   4_all_corners.py   --phase 3 (2a 2b 2c 5a 5b 5c 를 코너마다)
#   6_collect.py       최종 2종만 모으기
#
# 환경 변수로 바꿀 수 있는 것
#   PY=<파이썬>   쓸 파이썬. 안 주면 python3 (0_check.py 가 골라 준 것을 주면 된다)
#   JOBS=<N>      코너를 동시에 몇 개. 기본 1
#   EXTRA=...     4_all_corners.py 에 그대로 넘길 것 (예: --skip-done)

set -u

HERE=`dirname "$0"`
ROOT=${1:-}
OUT=${2:-deliver}
MODE=${3:-setup}
PY=${PY:-python3}
JOBS=${JOBS:-1}
EXTRA=${EXTRA:-}

if [ -z "$ROOT" ]; then
    echo "usage: sh run_all.sh <corner_root> [out_dir] [setup|hold]"
    echo "  example: sh run_all.sh round2 deliver setup"
    exit 2
fi
if [ ! -d "$ROOT" ]; then
    echo "[ FAILED ] no such directory: $ROOT"
    exit 2
fi
case "$MODE" in
    setup|hold) ;;
    *) echo "[ FAILED ] mode must be setup or hold (got: $MODE)"; exit 2 ;;
esac

echo "===================================================================="
echo "  run_all   root=$ROOT   out=$OUT   mode=$MODE   jobs=$JOBS"
echo "  python    $PY"
echo "===================================================================="

# --- 1/3  받은 것 검사 -------------------------------------------------
# 여기서 멈추지 않는다. crosstalk 이 아직 안 왔어도 annotation 은 나오므로,
# 검사는 알려 주기만 하고 진행한다.
echo ""
echo "-- 1/3  checking what PT gave us -----------------------------------"
"$PY" "$HERE/8_check_xtalk.py" --root "$ROOT"
if [ $? -ne 0 ]; then
    echo ""
    echo "  [ NOTE ] the check above found problems. going on anyway --"
    echo "           annotation does not need xtalk/ . look at the table"
    echo "           above to see which corners are affected."
fi

# --- 2/3  전부 돌리기 --------------------------------------------------
echo ""
echo "-- 2/3  running every corner (phase 3 = 2a 2b 2c 5a 5b 5c) ---------"
"$PY" "$HERE/4_all_corners.py" --root "$ROOT" --phase 3 --mode "$MODE" \
      --jobs "$JOBS" $EXTRA
RC=$?
if [ $RC -ne 0 ]; then
    echo ""
    echo "  [ NOTE ] some corners did not finish. collecting what is done."
fi

# --- 3/3  모으기 -------------------------------------------------------
echo ""
echo "-- 3/3  collecting the two final files -----------------------------"
"$PY" "$HERE/6_collect.py" --root "$ROOT" --out "$OUT" --mode "$MODE"
if [ $? -ne 0 ]; then
    echo ""
    echo "  [ FAILED ] nothing to collect. see the table above."
    exit 1
fi

echo ""
echo "===================================================================="
echo "  done.  hand over :  $OUT/$MODE/"
echo "===================================================================="
exit $RC
