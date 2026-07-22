#!/bin/bash
# Unseen-corner full-flow (b-1 retarget) — moved-folder version.
# 0.8V reference deck을 목표 전압으로 retarget. 전압은 상단 USER CONFIG에서 설정.
# 선행: 먼저 run_fullflow.sh 로 0.8V arc-align deck(=SRC_RUN) 생성 필요.
#
# Usage:
#   run_fullflow_unseen.sh "146 153 366" "IntToFP FP_fpiu FP_FDivSqrt" myrun_0p7v

# ============================================================================
#  USER CONFIG — 여기만 편집
# ============================================================================

# --- 0) 코드 위치 (자동감지) ---
CODE_DECK="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODE_SPICE="$(dirname "$CODE_DECK")/spice"

# --- 1) 데이터 + 출력 위치 ---
DATA_BASE=/home/KSW/auto_spice_breakdown/codex/pt_spice_deck

# --- 2) 툴 + 라이선스 ---
PT=/home/synopsys_tool/Primetime/W-2024.09-SP3/bin/pt_shell
HS=/home/synopsys_tool/Hspice/W-2024.09-SP1/hspice/linux64/hspice
PRIME_BASHRC=/home/synopsys_tool/prime.bashrc
LICENSE=26585@cscad

# --- 3) 설계 파일 ---
DESIGN_TOP=BoomCore
VERILOG_FILE=$DATA_BASE/input2/design_files/BoomCore.route_opt.pt.v.gz
SDC_FILE=$DATA_BASE/input2/design_files/BoomCore.func__tt0p8v25c.sdc
SPEF_FILE=$DATA_BASE/input2/design_files/Cnom_temp_all/BoomCore_14nm.starrc_coupled.Cnom_model_25.spef
FIXED_TCL_FILE=$DATA_BASE/input2/tcl/BoomCore_input2_Cnom25_fixed_paths_3000.tcl

# --- 4) ★ unseen 코너 목표 전압 (여기서 전압 바꿈) ---
TARGET_VDD=0.7
LIB_DB_FILE=$DATA_BASE/0p7V/saed14rvt_tt0p7v25c_ccs_rth0p01_full385_3ns250fj_mono.db  # 그 전압 CCS db (검증용)
CONFIG=$CODE_DECK/config/pt_native_spice_config_input2_0p7v.json                       # 그 전압 base-deck config
#   ┌─ 전압별 (위 3개 교체) ────────────────────────────────────────────────────┐
#   │ 0.7   : DATA_BASE/0p7V/...tt0p7v25c...mono.db   / config .../..._0p7v.json  │
#   │ 0.78  : DATA_BASE/0p78/...tt0p780v25c...mono.db / .../..._0p78v.json        │
#   │ 0.625 : DATA_BASE/0p625/...tt0p625v25c...mono.db/ .../..._0p625v.json       │
#   │ 0.6   : DATA_BASE/0p6V/...tt0p6v25c...mono.db   / .../..._0p6v.json          │
#   └───────────────────────────────────────────────────────────────────────────┘

# --- 5) retarget 방식 ---
SRC_RUN=fullflow_5paths   # retarget할 0.8V run 이름 (run_fullflow.sh로 먼저 생성)
VREF=0.8
RETARGET_KSLEW=1.0        # 1.0 = b-1(권장) / 1.258 = b-2

# --- 6) 고급 ---
HSPICE_TIMEOUT=28800

# --- 7) (선택) 양쪽-코너 보간 reference — 목표전압 Liberty 없이 PT 예측치 생성 ---
#     목표전압을 감싸는 두 코너 run(예: 0.8V와 0.6V)이 있으면 stage별 cell/net/slew를
#     물리모델 y=A/(V-Vth)^a 로 보간해 "예측 PT reference" CSV를 만든다.
#     (검증: 0.8+0.6->0.7 에서 cell합 -0.3%, slew합 +1.2%. 선형보간은 +14% 틀림)
#     crosstalk delta에는 불필요(b-1로 충분) — base/절대 타이밍 예측용.
INTERP_HI_RUN=""                # 높은쪽 코너 run 이름 (예: fullflow_5paths @0.8V). 비우면 스킵
INTERP_HI_VDD=0.8
INTERP_LO_RUN=""                # 낮은쪽 코너 run 이름 (예: fullflow_5paths_0p6v). 비우면 스킵
INTERP_LO_VDD=0.6
INTERP_VTH=0.45                 # 모델 Vth 앵커 (0.8/0.6->0.7 검증 최적값; ±0.05 -> ±1~2%)

# ============================================================================
#  ↓↓↓ 본문 (수정 불필요) ↓↓↓
# ============================================================================
set +e
IFS=' ' read -r -a PATHS  <<< "$1"
IFS=' ' read -r -a LABELS <<< "$2"
RUNNAME=${3:-fullflow_unseen}

source "$PRIME_BASHRC"
export SNPSLMD_LICENSE_FILE=$LICENSE LM_LICENSE_FILE=$LICENSE
export TOP=$DESIGN_TOP
export VERILOG=$VERILOG_FILE SDC=$SDC_FILE SPEF=$SPEF_FILE FIXED_TCL=$FIXED_TCL_FILE
SRC08=$DATA_BASE/output/input2/$SRC_RUN
ROOT=$DATA_BASE/output/input2/$RUNNAME
mkdir -p "$ROOT"

run_one(){
  local P=$1
  local V=$ROOT/p$P; mkdir -p "$V"; cd "$V"

  local S1=$(date +%s); export OUT_DIR=$V/s1 FIXED_INDEXES=$P LIB_DB=$LIB_DB_FILE; mkdir -p "$OUT_DIR"
    $PT -f $CODE_DECK/tcl/report_fixed_paths_si_on_off.tcl > $V/s1.log 2>&1; local E1=$(date +%s)

  printf "path_id,input_slew_ps,output_load_ff,target_vdd,target_temp\n$P,0,0,$TARGET_VDD,25\n" > ml.csv
  local S2=$(date +%s); python3 $CODE_DECK/py/run_pt_native_spice_flow.py \
      --config $CONFIG \
      --ml-csv $V/ml.csv --run-name p${P}_base --output-root $V \
      --skip-patch --timeout-hspice-sec $HSPICE_TIMEOUT --continue-on-error --force > $V/s2.log 2>&1; local E2=$(date +%s)

  local S3=$(date +%s)
  rm -rf $V/s3; cp -r $SRC08/p$P/s3 $V/s3
  sed -i "s|/$SRC_RUN/p$P/s3/|/$RUNNAME/p$P/s3/|g" $V/s3/pt_stage_arc_generation.csv $V/s3/sl.csv 2>/dev/null
  find $V/s3 -name "*.mt0" -delete; find $V/s3 -name "*.tr0" -delete
  rm -f $V/s3/ac.csv $V/s3/ac.rpt
  python3 $CODE_DECK/py/retarget_corner_deck.py \
      --dir $V/s3 --vref $VREF --vnew $TARGET_VDD --k-slew $RETARGET_KSLEW > $V/s3_retarget.log 2>&1
  cd $V/s3
    python3 $CODE_SPICE/py/path_arc_quiet_compare.py run-quiet-compare \
      --stage-csv sl.csv --manifest pt_stage_arc_generation.csv \
      --out-csv ac.csv --out-rpt ac.rpt --hspice $HS --force --continue-on-error > $V/s3c.log 2>&1
  local E3=$(date +%s)

  echo "P=$P S1=$((E1-S1)) S2=$((E2-S2)) S3=$((E3-S3)) TOTAL=$((E3-S1)) stages=$(($(wc -l < $V/s3/sl.csv 2>/dev/null)-1))" > $V/timing.txt
  echo "P=$P DONE ($(date +%T))"
}

echo "=== unseen full-flow start ($(date +%T)) : vdd=$TARGET_VDD kslew=$RETARGET_KSLEW src=$SRC_RUN paths=${PATHS[*]} ==="
for P in "${PATHS[@]}"; do run_one "$P" & done
wait
echo "=== all paths done, generating tables ($(date +%T)) ==="

CJP=$(IFS=,; echo "${PATHS[*]}")
CJL=$(IFS=,; echo "${LABELS[*]}")
python3 $CODE_SPICE/py/summary_pt_spice.py --root $ROOT --paths "$CJP" --labels "$CJL" --name "$RUNNAME"
for i in "${!PATHS[@]}"; do
  P=${PATHS[$i]}; LAB=${LABELS[$i]:-path$P}
  python3 $CODE_SPICE/py/stage_pt_spice_compare.py \
    --fullpath $ROOT/p$P/p${P}_base/pt_vs_native_stage_compare.csv \
    --arc $ROOT/p$P/s3/ac.csv --title "PATH$P $LAB (${TARGET_VDD}V b-1)" \
    --out-csv $ROOT/p$P/stage_detail_p${P}.csv --top 0 > /dev/null
  python3 $CODE_SPICE/py/crosstalk_delta_compare.py \
    --fullpath $ROOT/p$P/p${P}_base/pt_vs_native_stage_compare.csv \
    --arc $ROOT/p$P/s3/ac.csv --title "PATH$P $LAB" \
    --out-csv $ROOT/p$P/xtalk_delta_p${P}.csv > /dev/null
done

# (선택) 양쪽-코너 보간 PT reference: INTERP_HI_RUN + INTERP_LO_RUN 지정 시 생성
if [ -n "$INTERP_LO_RUN" ] && [ -n "$INTERP_HI_RUN" ]; then
  echo "=== interp PT reference (from $INTERP_HI_VDD V + $INTERP_LO_VDD V -> $TARGET_VDD V) ==="
  for i in "${!PATHS[@]}"; do
    P=${PATHS[$i]}; LAB=${LABELS[$i]:-path$P}
    HIC=$DATA_BASE/output/input2/$INTERP_HI_RUN/p$P/p${P}_base/pt_vs_native_stage_compare.csv
    LOC=$DATA_BASE/output/input2/$INTERP_LO_RUN/p$P/p${P}_base/pt_vs_native_stage_compare.csv
    if [ -f "$HIC" ] && [ -f "$LOC" ]; then
      python3 $CODE_DECK/py/interp_pt_corner.py \
        --hi-csv $HIC --hi-vdd $INTERP_HI_VDD \
        --lo-csv $LOC --lo-vdd $INTERP_LO_VDD \
        --target-vdd $TARGET_VDD --vth $INTERP_VTH \
        --out-csv $ROOT/p$P/interp_ref_p${P}.csv \
        --spice-csv $ROOT/p$P/p${P}_base/pt_vs_native_stage_compare.csv | tee $ROOT/p$P/interp_ref_p${P}.txt
      # stage별 cell/net 분리 표 — PT 컬럼을 보간 reference로 교체한 stage_detail
      python3 $CODE_SPICE/py/stage_pt_spice_compare.py \
        --fullpath $ROOT/p$P/p${P}_base/pt_vs_native_stage_compare.csv \
        --arc $ROOT/p$P/s3/ac.csv --interp $ROOT/p$P/interp_ref_p${P}.csv \
        --title "PATH$P $LAB (${TARGET_VDD}V, interp-PT ref ${INTERP_HI_VDD}V+${INTERP_LO_VDD}V)" \
        --out-csv $ROOT/p$P/stage_detail_interp_p${P}.csv --top 0 > /dev/null
    else
      echo "  p$P: 코너 CSV 없음 -> 보간 스킵"
    fi
  done
fi

echo "=== DONE ($(date +%T)) -> $ROOT ==="
