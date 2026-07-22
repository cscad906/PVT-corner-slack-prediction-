# pt_spice_deck — 파일별 상세 (deck 생성)

design + PrimeTime으로 SPICE deck을 만드는 코드. 파일 유형: **tcl**(PT 실행) / **py**(PT 구동·deck 후처리) / **config**(코너별 설정) / **sh**(마스터 오케스트레이터).

---

## tcl/ — PrimeTime이 pt_shell로 실행하는 스크립트

전부 env 파라미터화 (`TOP/VERILOG/SDC/SPEF/LIB_DB/CELL_SPF/MODEL_CARD/OUT_DIR/…`), 회로명 하드코딩 없음.

### `run_pt_native_spice_deck.tcl`
- **full-path base deck 생성**. 설계 로드(verilog/sdc/spef/lib) → `update_timing` → `source $FIXED_TCL`로 path 선택 → `get_timing_paths -from -to` → `write_spice_deck`.
- aggressor 없는 순수 victim 경로 deck. launch flop만 구동, 이후 자연전파.
- env: TOP/VERILOG/SDC/SPEF/LIB_DB/FIXED_TCL/CELL_SPF/MODEL_CARD/OUT_DIR + FIXED_INDEX/USE_THROUGHS.

### `run_pt_aligned_path_arcs_spice_deck.tcl`
- **arc-align crosstalk deck 생성** (핵심). path의 **각 net arc마다** `write_spice_deck -align_aggressors`로 aggressor를 그 victim에 worst-case 정렬한 deck 생성.
- 입력: STAGE_CSV(=stage arc 목록, path_arc_quiet_compare가 만듦). 출력: stage별 deck + `pt_stage_arc_generation.csv` manifest.
- env: 위 + STAGE_CSV/DRIVE_PATH_INPUT_PIN(false 기본)/TRAN_SIZE_NS(4.8 필수).

### `run_pt_aligned_arc_spice_deck.tcl`
- 위의 **단일 arc** 버전 (path 아니라 arc 하나만). 디버그/실험용.

### `report_fixed_paths_si_on_off.tcl`
- **PT SI on/off + crosstalk_delta 리포트** 생성. `si_enable_analysis` true/false로 두 번 돌려 SI-on/off 리포트, `-crosstalk_delta`로 delta 리포트.
- `delay_calc_waveform_analysis_mode=full_design`(CCS 정밀 파형), `report_timing -input_pins -nets -capacitance -transition_time` (cell/net/cap/slew 분해).
- env: TOP/VERILOG/SDC/SPEF/LIB_DB/FIXED_TCL/OUT_DIR/FIXED_INDEXES.

---

## py/ — PT 구동 + deck 후처리

### `run_pt_native_spice_flow.py` ★ (base deck 오케스트레이터)
- **배치**: ml.csv의 path마다 (1) write_spice_deck으로 deck 생성 → (2) `--skip-patch` 아니면 ml.csv slew/load/vdd/temp로 patch → (3) HSPICE 실행 → (4) mt0 파싱.
- 인자: `--config --ml-csv --run-name --output-root [--skip-patch] [--timeout-hspice-sec] [--continue-on-error] [--force]`.
- config가 design 파일·PT tcl·modelcard 경로를 다 갖고 있어 self-contained.

### `patch_pt_native_spice_deck.py`
- **생성된 deck 하나를 ML 조건으로 패치**. `input_slew`(경로 시작 victim PWL 재조정) + `output_load`(종점 lumped cap 추가, `C_ML_OUT_LOAD`) + `target_vdd`(전압 스케일) + `target_temp`.
- 인자: `--deck --stim --input-slew-ps --output-load-ff --target-vdd --target-temp [--endpoint-node --summary ...]`. 원본은 `.orig` 백업.

### `patch_targeted_spice_measures.py`
- deck의 `.measure`를 **특정 path edge**로 재조정. `rise=last/fall=last`를 첫 교차로 바꾸고 CK→D/Q→D 직접 measure 추가, .tran 조정. (full-aggressor deck 비용 절감용)
- 인자: `--stim --summary --from-node --to-node --output [...]`.

### `retarget_corner_deck.py` ★ (unseen 코너)
- **arc-align deck을 Vref→Vnew로 후처리** (PT·Liberty 재실행 없이). PWL 전압레벨 ×(Vn/Vr) + VDD + (옵션) slew 램프폭 ×k_slew. 정렬(shift_*) 보존.
- 인자: `--dir --vref --vnew --k-slew`. **b-1** = `--k-slew 1.0`(전압만), **b-2** = `--k-slew 1.258`(slew도 스케일).
- 주의: manifest deck_file 절대경로라 copy dir로 sed치환 + 옛 mt0 삭제 후 재실행.

### `interp_pt_corner.py` ★ (양쪽-코너 보간 reference)
- **감싸는 두 코너의 PT 결과로 목표전압 PT를 예측** (목표전압 Liberty 불필요). stage별 pt_cell/pt_net/pt_out_slew를 물리모델 `y=A/(V−Vth)^α`로 보간 (선형 fallback은 ~0 값만; 선형은 near-threshold 볼록성 때문에 +14% 틀림).
- 인자: `--hi-csv/--hi-vdd --lo-csv/--lo-vdd --target-vdd [--vth 0.45] --out-csv [--spice-csv]`. 입력은 각 코너 run의 `pt_vs_native_stage_compare.csv`.
- 검증(0.8+0.6→0.7): cell합 -0.3~-0.4%, slew합 +0.1~+1.2%. `run_fullflow_unseen.sh` USER CONFIG 7)로 자동 실행 가능.
- 용도: base/절대 타이밍 예측. crosstalk delta에는 불필요(b-1로 충분).

### `inject_victim_slew.py` (method ③)
- base full-path deck에서 **실측한 그-전압 victim slew**를 arc-align deck victim 입력 PWL에 **per-stage 주입**. k_N = spice_out_slew(new, stg N-1)/spice_out_slew(ref, stg N-1). aggressor는 reference 유지(b-2와 차이).
- 인자: `--dir --manifest --base07 --base08`.

### `shift_aggressor_pwl.py`
- aggressor PWL 시각을 **1 클럭주기 앞당김** (PT가 측정 edge보다 1주기 뒤에 emit하는 문제 보정). victim/clock/measure/.tran 불변.
- 인자: 스크립트 참조 (in/out stim).

### `shift_aggressor_pwl_perstage.py`
- 위의 **per-stage drift 보정판**. aggressor마다 -(cycle + drift(stage)) 이동, drift = PT SI-off arrival − SPICE quiet arrival. (실험적, 균일 shift보다 후퇴로 기각됨)

### `freeze_noneffective_aggressors.py`
- PT active('A')로 판정된 **effective aggressor만 남기고** 나머지 PWL을 DC로 동결. `report_delay_calculation -crosstalk` 리포트로 판정. (비용 실험, 정확도 파괴로 기각)
- 인자: `--in --out --reports`.

### `reduce_aggressor_rc.py`
- 각 aggressor net의 상세 RC를 **driver 노드로 lumped 병합** (저항 shorted, ground cap 합산). victim은 byte-불변. (비용 실험, 물리는 보존하나 시간 이득 0)

### `interp_spef_temp.py`
- SPEF의 wire 저항을 **목표 온도로 보간** (R(T) 선형보간). cap은 온도무관 통과. 미추출 온도(예: 50C) 코너 실행용.
- 인자: `--lo --hi --t-lo --t-hi --t --out`.

---

## config/ — 코너별 설정 (json)

전부 동일 구조: `reference_pt`(verilog/sdc/spef/lib_db), `path_registry`(fixed_tcl), `prime_time`(tcl), `spice_model`(model_card/cell_spf), `ml_input`(csv 규격), `deck_patch`(patch 항목), `hspice`.

- `pt_native_spice_config_input2_cnom25.json` — **0.8V 기준** (메인)
- `..._0p78v/0p7v/0p625v/0p6v.json` — 저전압 코너 (lib_db·vdd만 다름)
- `..._0p6v_origmodel.json` — 0.6V, model_card를 **원본 PDK**(/home/0Park/…)로 교체 (modelcard 비교용)
- `..._cnom25_fullpath.json` / `..._fullpath_4p8ns.json` — full-path 변형 (tran window 등)
- `pt_native_spice_config.yaml` / `..._full_aggressor.yaml` — 구 yaml 버전 (참고)

**ml_input 규격**: `path_id, input_slew_ps, output_load_ff, [target_vdd, target_temp]` (slew=ps, load=fF).
**deck_patch**: `patch_vdd/patch_temp/patch_input_slew/patch_output_load` + `output_load_cap_name(C_ML_OUT_LOAD)`.

---

## *.sh — 마스터 오케스트레이터 (PT deck + HSPICE + 분석 전부)

**모든 조정값은 스크립트 맨 위 `USER CONFIG` 블록에 있음.** (툴/설계경로/전압/PATCH_MODE/slew·load) — 본문은 안 건드림.

### `run_fullflow.sh` (0.8V, 메인)
- `run_fullflow.sh "146 153 366" "IntToFP FP_fpiu FP_FDivSqrt" runname`
- path마다 병렬로: **S1** PT SI on/off → **S2** base deck → **S3a** stage arc 목록 → **S3b** arc-align deck → **S3c** HSPICE quiet+align 집계 → summary/stage_detail/xtalk_delta.
- **USER CONFIG 블록**:
  - 1) `BASE/PT/HS/PRIME_BASHRC/LICENSE` (툴·라이선스)
  - 2) `DESIGN_TOP/VERILOG_FILE/.../CONFIG` (설계 파일)
  - 3) `PATCH_MODE`(true면 아래 반영)·`INPUT_SLEW_PS`·`OUTPUT_LOAD_FF`·`TARGET_VDD`·`TARGET_TEMP` (경로 boundary)
  - 4) `TRAN_SIZE_NS`(4.8 유지)·`HSPICE_TIMEOUT`·`DRIVE_PATH_INPUT_PIN`
  - → `PATCH_MODE=true`면 `--skip-patch`가 자동으로 빠지고 ml.csv slew/load 반영.

### `run_fullflow_unseen.sh` (전압 스윕 통합본)
- 구 `run_fullflow_0p7v/0p78v/0p625v/0p6v.sh` 4개를 **하나로 통합**. S1/S2는 목표 전압, S3는 0.8V arc-align deck을 retarget(b-1).
- **USER CONFIG 3)** 에서 목표 전압 3개만 교체: `TARGET_VDD` / `LIB_DB_FILE` / `CONFIG` (전압별 값 주석 표 포함).
- **USER CONFIG 4)**: `RETARGET_KSLEW`(1.0=b-1 권장, 1.258=b-2), `SRC_RUN`(retarget할 0.8V run), `VREF`.
- **선행**: 먼저 run_fullflow.sh로 0.8V arc-align deck(SRC_RUN) 생성 필요.

> **주의**: sh는 원래 `$BASE/code/native_flow/`·`$BASE/code/si_debug/` 참조. 옮긴 구조(`pt_spice_deck/py,tcl` + `spice/py`)로 돌리려면 sh 안의 `$BASE/code/...` 경로를 `pt_spice_deck/{py,tcl}`·`spice/py`로 재배선 필요.
