#!/bin/bash
# PT vs SPICE full-flow driver (moved-folder version — code in /home/KSW/code/{pt_spice_deck,spice}).
#
# Usage:
#   run_fullflow.sh "146 153 366" "IntToFP FP_fpiu FP_FDivSqrt" myrunname
#     arg1 = PT fixed-path 인덱스 (공백 구분)
#     arg2 = 라벨 (같은 순서; "" 생략 시 path<idx>)
#     arg3 = run 이름 -> <DATA_BASE>/output/input2/<runname>/

# ============================================================================
#  USER CONFIG — 여기만 편집
# ============================================================================

# --- 0) 코드 위치 (이 스크립트 기준 자동감지; 보통 그대로) ---
CODE_DECK="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # deck 생성 코드 (= 이 폴더)
CODE_SPICE="$(dirname "$CODE_DECK")/spice"                  # HSPICE 실행/분석 코드 (= ../spice)

# --- 1) 데이터 + 출력 위치 (design/lib/spef 등이 있는 곳; 새 환경이면 수정) ---
DATA_BASE=/home/KSW/auto_spice_breakdown/codex/pt_spice_deck

# --- 2) 툴 + 라이선스 (새 머신이면 수정) ---
PT=/home/synopsys_tool/Primetime/W-2024.09-SP3/bin/pt_shell
HS=/home/synopsys_tool/Hspice/W-2024.09-SP1/hspice/linux64/hspice
PRIME_BASHRC=/home/synopsys_tool/prime.bashrc
LICENSE=26585@cscad

# --- 3) 설계 파일 (새 회로면 수정; DATA_BASE 아래) ---
DESIGN_TOP=BoomCore
VERILOG_FILE=$DATA_BASE/input2/design_files/BoomCore.route_opt.pt.v.gz
SDC_FILE=$DATA_BASE/input2/design_files/BoomCore.func__tt0p8v25c.sdc
SPEF_FILE=$DATA_BASE/input2/design_files/Cnom_temp_all/BoomCore_14nm.starrc_coupled.Cnom_model_25.spef
LIB_DB_FILE=$DATA_BASE/input2/CCS/saed14rvt_tt0p8v25c_ccs_rth0p01_full385_3ns250fj_mono_with_area_footprint_icc2clean.db
CELL_SPF_FILE=$DATA_BASE/input2/modelcard/saed14nm_rvt.spf
MODEL_CARD_FILE=$DATA_BASE/input2/modelcard/saed14nm_hspice_local.lib
FIXED_TCL_FILE=$DATA_BASE/input2/tcl/BoomCore_input2_Cnom25_fixed_paths_3000.tcl
CONFIG=$CODE_DECK/config/pt_native_spice_config_input2_cnom25.json   # (config 내부 data 경로는 DATA_BASE 를 가리킴)

# --- 4) 경로 boundary 조건 (patch 모드에서만 반영) ---
PATCH_MODE=false        # true = 아래 slew/load 반영. false = PT 자연전파(기본)
INPUT_SLEW_PS=0         # 경로 시작 입력 slew [ps] (PATCH_MODE=true일 때만)
OUTPUT_LOAD_FF=0        # 경로 끝 load [fF]
TARGET_VDD=0.8
TARGET_TEMP=25

# --- 5) 고급 ---
TRAN_SIZE_NS=4.8
HSPICE_TIMEOUT=28800
DRIVE_PATH_INPUT_PIN=false

# ============================================================================
#  ↓↓↓ 본문 (수정 불필요) ↓↓↓
# ============================================================================
set +e
IFS=' ' read -r -a PATHS  <<< "$1"
IFS=' ' read -r -a LABELS <<< "$2"
RUNNAME=${3:-fullflow}

source "$PRIME_BASHRC"
export SNPSLMD_LICENSE_FILE=$LICENSE LM_LICENSE_FILE=$LICENSE
export TOP=$DESIGN_TOP
export VERILOG=$VERILOG_FILE SDC=$SDC_FILE SPEF=$SPEF_FILE
export LIB_DB=$LIB_DB_FILE CELL_SPF=$CELL_SPF_FILE MODEL_CARD=$MODEL_CARD_FILE FIXED_TCL=$FIXED_TCL_FILE
ROOT=$DATA_BASE/output/input2/$RUNNAME
mkdir -p "$ROOT"

if [ "$PATCH_MODE" = "true" ]; then SKIP_PATCH_FLAG=""; else SKIP_PATCH_FLAG="--skip-patch"; fi

run_one(){
  local P=$1
  local V=$ROOT/p$P; mkdir -p "$V"; cd "$V"
  printf "path_id,input_slew_ps,output_load_ff,target_vdd,target_temp\n$P,$INPUT_SLEW_PS,$OUTPUT_LOAD_FF,$TARGET_VDD,$TARGET_TEMP\n" > ml.csv
  local S1=$(date +%s); export OUT_DIR=$V/s1 FIXED_INDEXES=$P; mkdir -p "$OUT_DIR"
    $PT -f $CODE_DECK/tcl/report_fixed_paths_si_on_off.tcl > $V/s1.log 2>&1; local E1=$(date +%s)
  local S2=$(date +%s); python3 $CODE_DECK/py/run_pt_native_spice_flow.py \
      --config $CONFIG \
      --ml-csv $V/ml.csv --run-name p${P}_base --output-root $V \
      $SKIP_PATCH_FLAG --timeout-hspice-sec $HSPICE_TIMEOUT --continue-on-error --force > $V/s2.log 2>&1; local E2=$(date +%s)
  local S3a=$(date +%s); local SIRPT=$(ls $V/s1/*si_on*.rpt|head -1)
    python3 $CODE_SPICE/py/path_arc_quiet_compare.py prepare-stage-csv-from-report \
      --si-rpt "$SIRPT" --path-id $P --out-dir $V/s3 --output-name sl.csv > $V/s3a.log 2>&1; local E3a=$(date +%s)
  local S3b=$(date +%s); export OUT_DIR=$V/s3 STAGE_CSV=$V/s3/sl.csv DRIVE_PATH_INPUT_PIN=$DRIVE_PATH_INPUT_PIN TRAN_SIZE_NS=$TRAN_SIZE_NS
    $PT -f $CODE_DECK/tcl/run_pt_aligned_path_arcs_spice_deck.tcl > $V/s3b.log 2>&1; local E3b=$(date +%s)
  local S3c=$(date +%s); cd $V/s3
    python3 $CODE_SPICE/py/path_arc_quiet_compare.py run-quiet-compare \
      --stage-csv sl.csv --manifest pt_stage_arc_generation.csv \
      --out-csv ac.csv --out-rpt ac.rpt --hspice $HS --force --continue-on-error > $V/s3c.log 2>&1; local E3c=$(date +%s)
  echo "P=$P STAGE1=$((E1-S1)) STAGE2=$((E2-S2)) STAGE3a=$((E3a-S3a)) STAGE3b=$((E3b-S3b)) STAGE3c=$((E3c-S3c)) TOTAL=$((E3c-S1)) stages=$(($(wc -l < $V/s3/sl.csv 2>/dev/null)-1))" > $V/timing.txt
  echo "P=$P DONE ($(date +%T))"
}

echo "=== full-flow start ($(date +%T)) : paths=${PATHS[*]}  patch=$PATCH_MODE vdd=$TARGET_VDD ==="
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
    --arc $ROOT/p$P/s3/ac.csv --title "PATH$P $LAB" \
    --out-csv $ROOT/p$P/stage_detail_p${P}.csv --top 0 > /dev/null
  python3 $CODE_SPICE/py/crosstalk_delta_compare.py \
    --fullpath $ROOT/p$P/p${P}_base/pt_vs_native_stage_compare.csv \
    --arc $ROOT/p$P/s3/ac.csv --title "PATH$P $LAB" \
    --out-csv $ROOT/p$P/xtalk_delta_p${P}.csv > /dev/null
done

echo "" ; echo "=== per-stage wall-clock (sec) ===" | tee $ROOT/timing_all.txt
printf "%-7s %-7s %-6s %-7s %-5s %-7s %-7s %-6s\n" path stages S1 S2base S3a S3bgen S3cHSP TOTAL | tee -a $ROOT/timing_all.txt
for P in "${PATHS[@]}"; do
  sed -E 's/P=([0-9]+) STAGE1=([0-9]+) STAGE2=([0-9]+) STAGE3a=([0-9]+) STAGE3b=([0-9]+) STAGE3c=([0-9]+) TOTAL=([0-9]+) stages=([0-9]+)/\1 \8 \2 \3 \4 \5 \6 \7/' $ROOT/p$P/timing.txt 2>/dev/null \
    | awk '{printf "%-7s %-7s %-6s %-7s %-5s %-7s %-7s %-6s\n",$1,$2,$3,$4,$5,$6,$7,$8}' | tee -a $ROOT/timing_all.txt
done
echo "=== DONE ($(date +%T)) -> $ROOT ==="
